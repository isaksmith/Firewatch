"""Situation updates on the district's mesh channel while a paged fire is open (docs/DESIGN.md section 5.11).

The alerts stay fixed templates. On top of them, everyone on the channel gets a short plain-language update when
crews are paged, mutual aid goes out or the fire is stood down, then every CHANNEL_UPDATE_MIN minutes, sooner when
the wind swings or the forecast size doubles. The model in llm.py words it from the same facts a texted question
gets (no names, no addresses); a plain template goes out when it can't.

Off unless there is an OpenRouter key and the server's radio is up. A replay posts only while it plays on its clock,
never while it is loaded all at once.
"""

import logging
import threading
from datetime import datetime, timedelta

from . import ask, llm, mesh
from .config import get_settings
from .db import connect, iso
from .district import load_district

log = logging.getLogger(__name__)
CHECK_MIN = 5  # how often the clock looks for a wind shift or growth
SHIFT_DEG = 45
SHIFT_MIN_MPH = 5
GROWTH = 2.0
GROWTH_MIN_ACRES = 100  # a young fire doubles every few minutes; that alone is not news
MAX_CHARS = 220  # under the radio's 233-byte payload; updates are ASCII

SYSTEM = (
    "You write situation updates for the radio channel of {district}, a volunteer rural fire district in Kansas. "
    "Everyone on the channel reads them: volunteers, ranchers, neighbors. Write one or two plain sentences from the "
    "FACTS only, most important first: what changed, where the fire is heading, and how big the forecast says it "
    "gets. At most {words} words and {n} characters: anything longer is cut. No greeting, no markdown, no emoji, no "
    "names of people. Never invent a number, place or time."
)

_lock = threading.Lock()
_last: dict[tuple, dict] = {}  # (event id, first_seen) -> {"at", "wind_deg", "acres"} of the last update posted
_checked: dict[tuple, datetime] = {}


def _key(ev) -> tuple:
    # ids restart when a replay clears the database, so first_seen tells two fire 3s apart
    return ev["id"], ev["first_seen"]


def enabled(ev) -> bool:
    if not (llm.enabled() and get_settings().mesh_channel_updates and mesh.get_bridge() is not None):
        return False
    if ev["sample_slug"]:
        from . import scenario

        return scenario.running_now() is not None
    return True


def decided(conn, ev, action: str, state: dict, now: datetime, first: bool) -> None:
    """After a PAGE, SEND or NO took effect (first=False for a repeat that changed nothing). The facts are read
    here, on the decision's own connection: a worker would not see the decision until it commits."""
    if not first or not enabled(ev):
        return
    if action == "page":
        reason = "Crews were just paged."
    elif action == "send":
        reason = f"Mutual aid was just requested from {load_district().neighbor_district}."
    elif state.get("escalate_at"):
        reason = "The duty officer stood this one down: no crews needed."
    else:
        return
    try:
        fire = ask.fire_facts(conn, ev, now)
    except Exception:
        log.exception("channel update for event %s: no facts", ev["id"])
        return
    with _lock:
        _last[_key(ev)] = {"at": now, "wind_deg": fire["wind_deg"], "acres": fire["acres_now"]}
    ask.spawn(_post, ev["id"], now, reason, fire)


def tick(conn, ev, state: dict, now: datetime) -> None:
    """From notify.tick: every CHECK_MIN minutes, see whether a paged fire is due an update."""
    if state.get("decision") != "page" or ev["status"] in ("dismissed", "closed") or not enabled(ev):
        return
    key = _key(ev)
    with _lock:
        last = _checked.get(key)
        if last is not None and last <= now < last + timedelta(minutes=CHECK_MIN):
            return
        _checked[key] = now
    ask.spawn(_post, ev["id"], now, None)


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _due(last: dict | None, fire: dict, now: datetime) -> str | None:
    """Why this fire is due an update now, or None."""
    every = get_settings().channel_update_min
    if last is None:
        return "Regular update."
    if fire["wind_deg"] is not None and last["wind_deg"] is not None and fire["wind_mph"] >= SHIFT_MIN_MPH \
            and _angle(fire["wind_deg"], last["wind_deg"]) >= SHIFT_DEG:
        return f"The wind has shifted and now blows from the {fire['wind_from']}."
    if fire["acres_now"] and last["acres"] and fire["acres_now"] >= GROWTH * last["acres"] \
            and fire["acres_now"] - last["acres"] >= GROWTH_MIN_ACRES:
        return "The fire has at least doubled in size since the last update."
    if now - last["at"] >= timedelta(minutes=every):
        return "Regular update."
    return None


def template(fire: dict, reason: str) -> str:
    head = f"FIREWATCH update fire {fire['id']} {fire['short_place'][:40]}: "
    parts = [reason]
    if fire["wind_from"]:
        parts.append(f"Wind {fire['wind_from']} {fire['wind_mph']} mph, spreading {fire['toward']}.")
    if fire["acres_now"] is not None:
        parts.append(f"About {fire['acres_now']:,} ac, likely {fire['acres_60']:,} ac in 1 hr.")
    if fire["paged"] and fire["responding"]:
        parts.append(f"{fire['responding']} responding.")
    fit = []
    for p in parts:
        if len(head) + len(" ".join([*fit, p])) > MAX_CHARS:
            break
        fit.append(p)
    return head + " ".join(fit)


def compose(fire: dict, reason: str) -> str:
    head = f"FIREWATCH update fire {fire['id']}: "
    n = MAX_CHARS - len(head)
    facts = f"WHAT JUST HAPPENED: {reason}\n" + ask.facts_text([fire], asker=False)
    words = llm.complete(SYSTEM.format(district=load_district().name, n=n, words=n // 7), facts, "Write the update.", n)
    return head + words if words else template(fire, reason)


def _post(event_id: int, now: datetime, reason: str | None, fire: dict | None = None) -> None:
    """Worker: gather the facts and decide (for a clock check), word it, post it, log it."""
    from . import notify

    try:
        with connect() as conn:
            ev = notify._event(conn, event_id)
            if ev is None:
                return
            if fire is None:
                fire = ask.fire_facts(conn, ev, now)
        if reason is None:
            key = _key(ev)
            with _lock:
                last = _last.get(key)
                if last is not None and last["at"] > now:
                    last = None  # left over from an earlier run of the same replay
                reason = _due(last, fire, now)
                if reason is None:
                    return
                _last[key] = {"at": now, "wind_deg": fire["wind_deg"], "acres": fire["acres_now"]}
        body = compose(fire, reason)
        bridge = mesh.get_bridge()
        status = "sent"
        if bridge is None:
            status = "failed"
        else:
            try:
                bridge.post(body)
            except Exception as e:
                log.warning("channel update for event %s failed: %s", event_id, e)
                status = "failed"
        with connect() as conn:
            conn.execute(
                "INSERT INTO messages(event_id, contact_id, phone, direction, purpose, body, status, is_sample, created_at, channel) "
                "VALUES (?, NULL, ?, 'out', 'channel_update', ?, ?, ?, ?, 'mesh')",
                (event_id, mesh.BROADCAST_ID, body, status, ev["is_sample"], iso(now)),
            )
    except Exception:
        log.exception("channel update for event %s failed", event_id)
