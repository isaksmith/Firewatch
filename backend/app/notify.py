"""Respond: who gets texted, when, and what (docs/DESIGN.md section 5.6).

Every text is one SMS (<= 160 chars) because the district has one bar of cell and no data. All functions
take an explicit `now` so the scenario replay can run the same code on its own clock.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from . import mesh
from .config import get_settings
from .db import iso, loads, parse_iso
from .district import LADDER_ROLES, NEIGHBOR_ROLES, VOLUNTEER_ROLES, load_district
from .fire_weather import default_curing
from .geo import KM_PER_MILE, bearing_deg, compass, haversine_km
from .where import parse_where, point_from
from .sim.spread import SpreadInput, simulate

log = logging.getLogger(__name__)
CENTRAL = ZoneInfo("America/Chicago")
SMS_MAX = 160
HA_PER_ACRE = 0.404686
HELPER_ROLES = ("water_truck", "disc")
HELPER_RADIUS_KM = 10.0
PLAN_MINUTES = 60
OUTSIDE_FYI_WINDOW_MIN = 60
DECIDERS = ("duty_fyi", "duty_escalate", "ladder", "mutual_aid_draft")


# --- gateways -------------------------------------------------------------------------------------------


class SmsGateway(Protocol):
    name: str

    def send(self, to: str, body: str) -> str: ...


class OutboxGateway:
    """Records messages without sending them (sample mode, the scenario, and tests)."""

    name = "outbox"

    def send(self, to: str, body: str) -> str:
        return f"outbox-{uuid.uuid4().hex[:12]}"


class TwilioGateway:
    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.sid, self.token, self.from_number = account_sid, auth_token, from_number

    def send(self, to: str, body: str) -> str:
        r = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
            data={"To": to, "From": self.from_number, "Body": body},
            auth=(self.sid, self.token),
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["sid"]


def gateway_for(is_sample: bool) -> SmsGateway:
    s = get_settings()
    if is_sample or s.sms_gateway != "twilio":
        return OutboxGateway()
    return TwilioGateway(s.twilio_account_sid, s.twilio_auth_token, s.twilio_from)


def valid_twilio_signature(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = base64.b64encode(hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(digest, signature or "")


# --- templates (each must fit one SMS; tests check the worst case) ---------------------------------------


def _short_place(ev) -> str:
    return (ev["place_label"] or f"{ev['lat']:.3f},{ev['lon']:.3f}").split(",")[0]


def _rel(ev, contact) -> str:
    km = haversine_km(contact["lat"], contact["lon"], ev["lat"], ev["lon"])
    return f"{km / KM_PER_MILE:.1f} mi {compass(bearing_deg(contact['lat'], contact['lon'], ev['lat'], ev['lon']))}"


def _with_link(body: str, event_id: int) -> str:
    """Append the console link only when it still fits in one SMS."""
    base = get_settings().public_base_url
    link = f" {base.rstrip('/')}/#/e/{event_id}" if base else ""
    return body + link if len(body) + len(link) <= SMS_MAX else body


def t_duty_fyi(ev, why: str, n_asked: int) -> str:
    body = f"FIREWATCH check: {why}, {_short_place(ev)}. Asked {n_asked} neighbors. Reply PAGE to page, NO to stand down."
    return _with_link(body, ev["id"])


def t_ask_neighbor(ev, contact, short_name: str) -> str:
    return f"{short_name}: possible fire {_rel(ev, contact)} of you. See smoke? Reply 1 smoke, 2 no, 3 my burn. STOP to opt out"


def t_duty_escalate(ev, why: str, prefix: str = "") -> str:
    return _with_link(f"FIREWATCH FIRE {_short_place(ev)}: {why}. {prefix}Reply PAGE to page, NO to stand down.", ev["id"])


def t_dispatch_ladder(ev, why: str) -> str:
    return f"FIREWATCH: no answer from duty or chief. Likely fire {_short_place(ev)}: {why}. Calling you now."


def t_page(ev, plan: dict) -> str:
    w = plan["wind"]
    return (
        f"FIRE {_short_place(ev)}. Grass, wind {w['from']} {w['mph']} mph, ~{plan['acres_60']} ac in 1 hr. "
        f"{ev['lat']:.4f},{ev['lon']:.4f} Reply R if responding"
    )


def t_page_dispatch(ev, short_name: str, by: str) -> str:
    return f"{short_name} PAGE: grass fire {_short_place(ev)}, {ev['lat']:.4f},{ev['lon']:.4f}. Tone out the district. Paged by {by} via Firewatch"


def t_downwind(ev, contact, eta: int, short_name: str) -> str:
    return f"{short_name}: grass fire {_rel(ev, contact)} of you, moving your way. Could reach you in ~{eta} min. Move stock and vehicles. Crews paged."


def t_helper(ev, contact, short_name: str) -> str:
    kind = "water truck" if contact["role"] == "water_truck" else "disc"
    return f"{short_name}: grass fire {_rel(ev, contact)} of you. Can you bring your {kind}? Reply R if heading there. Stay off the fire's head."


def t_mutual_aid_draft(reason: str, neighbor: str) -> str:
    return f"FIREWATCH mutual aid: {reason}. Reply SEND to request {neighbor}."


def t_mutual_aid(ev, short_name: str, plan: dict, n_resp: int) -> str:
    return (
        f"{short_name} requests mutual aid: grass fire {_short_place(ev)}, {ev['lat']:.4f},{ev['lon']:.4f}, "
        f"~{plan['acres_60']} ac in 1 hr, {n_resp} responding."
    )


# --- sending ---------------------------------------------------------------------------------------------


def _excerpt(text: str | None, n: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def t_ask_post(post, contact, short_name: str) -> str:
    what = "smoke" if post["category"] == "smoke" else "fire"
    return (f"{short_name}: a neighbor posted a possible {what} {_rel(post, contact)} of you. Do you see it? "
            "Reply 1 yes, 2 no, 3 my burn. STOP to opt out")


def t_post_duty(post, why: str) -> str:
    head = f"FIREWATCH board: {why}, {post['lat']:.4f},{post['lon']:.4f}. "
    return head + _excerpt(post["body"], SMS_MAX - len(head) - 1 - 20) + " Check the board."


def t_place_hint() -> str:
    return "To place it: FIRE N 5 (5 mi north)."


ESTIMATE_JOIN_KM = 8.0  # a report placed by bearing and distance may be off by miles, so it joins wider

CHANNELS = ("sms", "mesh")


def send(
    conn: sqlite3.Connection, contact, body: str, purpose: str, event_id: int | None, now: datetime, is_sample: bool,
    channels: tuple[str, ...] = CHANNELS, post_id: int | None = None,
) -> dict | None:
    """Text a contact by SMS and, when they carry a radio and the server's radio is up, over the mesh too.

    Mesh messages go out even in sample mode: they only reach radios the roster links to a contact.
    """
    if not contact["opted_in"] and purpose != "reply":
        return None
    if len(body) > SMS_MAX:
        log.warning("%s text is %d chars; truncating", purpose, len(body))
        body = body[: SMS_MAX - 1] + "…"
    routes = []
    if "sms" in channels and not contact["phone"].startswith(("!", "web:")):
        routes.append(("sms", contact["phone"], gateway_for(is_sample)))
    node = contact["mesh_id"] if "mesh_id" in contact.keys() else None
    if "mesh" in channels and node and (bridge := mesh.get_bridge()):
        routes.append(("mesh", node, bridge))
    first = None
    for channel, to, gateway in routes:
        status, gid = "sent", None
        try:
            gid = gateway.send(to, body)
        except (httpx.HTTPError if channel == "sms" else Exception) as e:
            log.warning("%s to %s failed: %s", channel, to, e)
            status = "failed"
        cur = conn.execute(
            "INSERT INTO messages(event_id, contact_id, phone, direction, purpose, body, status, gateway_id, is_sample, created_at, channel, post_id) "
            "VALUES (?, ?, ?, 'out', ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, contact["id"], to, purpose, body, status, gid, int(is_sample), iso(now), channel, post_id),
        )
        first = first or {"id": cur.lastrowid, "to": contact["name"], "purpose": purpose, "body": body, "status": status, "channel": channel}
    return first


def _contacts(conn, roles: tuple[str, ...]) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT * FROM contacts WHERE role IN ({','.join('?' * len(roles))}) ORDER BY ladder_rank IS NULL, ladder_rank, id",
        roles,
    ).fetchall()


def _ladder(conn) -> list[sqlite3.Row]:
    return [c for c in _contacts(conn, LADDER_ROLES) if c["ladder_rank"] is not None]


def _one(conn, role: str):
    rows = _contacts(conn, (role,))
    return rows[0] if rows else None


def _state(ev) -> dict:
    return loads(ev["response_json"], {}) or {}


def _save(conn, event_id: int, state: dict) -> None:
    conn.execute("UPDATE events SET response_json = ? WHERE id = ?", (json.dumps(state), event_id))


def _event(conn, event_id: int):
    return conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()


WHY_MAX = 45


def _why(ev) -> str:
    """The level reason without its prefix, cut at a word to fit the templates."""
    why = (ev["level_reason"] or "").split(": ", 1)[-1].split(", needs")[0]
    if len(why) > WHY_MAX:
        why = why[: WHY_MAX - 1].rsplit(" ", 1)[0] + "…"
    return why


# --- level changes ---------------------------------------------------------------------------------------


def on_level(conn: sqlite3.Connection, event_id: int, level: str, now: datetime) -> None:
    ev = _event(conn, event_id)
    state = _state(ev)
    sample = bool(ev["is_sample"])
    if level in ("investigate", "escalate") and "investigate_at" not in state:
        state["investigate_at"] = iso(now)
        if level == "investigate":
            asked = ask_neighbors(conn, ev, now)
            state["asked"] = [a["contact_id"] for a in asked]
            duty = _ladder(conn)[:1]
            if duty:
                send(conn, duty[0], t_duty_fyi(ev, _why(ev), len(asked)), "duty_fyi", event_id, now, sample)
    if level == "escalate" and "escalate_at" not in state:
        state["escalate_at"] = iso(now)
        state["ladder_step"] = 0
        _save(conn, event_id, state)
        if not state.get("decision"):
            _ladder_step(conn, ev, state, now)
        return
    _save(conn, event_id, state)


def ask_neighbors(conn: sqlite3.Connection, ev, now: datetime) -> list[dict]:
    """Text up to N opted-in neighbors within the ask radius, nearest first."""
    d = load_district()
    radius_km = d.settings.get("ask_neighbor_radius_mi", 3) * KM_PER_MILE
    reporters = {r["contact_id"] for r in conn.execute("SELECT contact_id FROM signals WHERE event_id = ?", (ev["id"],))}
    near = []
    for c in _contacts(conn, NEIGHBOR_ROLES):
        if c["lat"] is None or not c["opted_in"] or c["id"] in reporters:
            continue
        km = haversine_km(ev["lat"], ev["lon"], c["lat"], c["lon"])
        if km <= radius_km:
            near.append((km, c))
    near.sort(key=lambda kc: kc[0])
    out = []
    for km, c in near[: d.settings.get("ask_neighbor_max", 3)]:
        send(conn, c, t_ask_neighbor(ev, c, d.short_name), "ask_neighbor", ev["id"], now, bool(ev["is_sample"]))
        out.append({"contact_id": c["id"], "name": c["name"], "km": round(km, 2)})
    return out


def _ladder_step(conn, ev, state: dict, now: datetime) -> None:
    step = state.get("ladder_step", 0)
    ladder = _ladder(conn)
    sample = bool(ev["is_sample"])
    why = _why(ev)
    if step < len(ladder):
        c = ladder[step]
        if step == 0:
            body = t_duty_escalate(ev, why)
            purpose = "duty_escalate"
        else:
            body = t_duty_escalate(ev, why, "No answer from duty officer. ")
            purpose = "ladder"
        send(conn, c, body, purpose, ev["id"], now, sample)
    else:
        dispatch = _one(conn, "dispatch")
        if dispatch:
            send(conn, dispatch, t_dispatch_ladder(ev, why), "ladder_dispatch", ev["id"], now, sample)
    state.setdefault("ladder", []).append({"step": step, "at": iso(now)})
    state["ladder_step"] = step + 1
    _save(conn, ev["id"], state)


# --- clock -----------------------------------------------------------------------------------------------


def tick(conn: sqlite3.Connection, now: datetime, is_sample: bool | None = None) -> None:
    """Advance timers: the no-answer ladder, and mutual aid when too few respond."""
    d = load_district()
    waits = d.settings.get("ladder_minutes", [3, 6])
    q = "SELECT * FROM events WHERE response_json IS NOT NULL AND status != 'closed'"
    args: tuple = ()
    if is_sample is not None:
        q += " AND is_sample = ?"
        args = (int(is_sample),)
    for ev in conn.execute(q, args).fetchall():
        state = _state(ev)
        if state.get("escalate_at") and not state.get("decision"):
            step = state.get("ladder_step", 0)
            if 1 <= step <= len(waits):
                due = parse_iso(state["escalate_at"]) + timedelta(minutes=sum(waits[:step]))
                if now >= due:
                    _ladder_step(conn, ev, state, now)
        if state.get("page_at") and not state.get("mutual_aid"):
            after = parse_iso(state["page_at"]) + timedelta(minutes=d.settings.get("mutual_aid_after_min", 5))
            n = _n_responding(state)
            if now >= after and n < d.settings.get("min_responding", 2):
                _draft_mutual_aid(conn, ev, state, f"{n} responding {d.settings.get('mutual_aid_after_min', 5)} min after page", now)


def _n_responding(state: dict) -> int:
    return sum(1 for r in state.get("responders", []) if r["role"] in VOLUNTEER_ROLES)


# --- decisions -------------------------------------------------------------------------------------------


def decide(conn: sqlite3.Connection, event_id: int, action: str, by: str, now: datetime) -> dict:
    """PAGE / NO / SEND from the duty officer or chief (by text or the console)."""
    ev = _event(conn, event_id)
    state = _state(ev)
    d = load_district()
    sample = bool(ev["is_sample"])
    if action == "page":
        if state.get("decision") == "page":
            return state
        state.update(decision="page", decision_by=by, decision_at=iso(now), page_at=iso(now))
        plan = plan_response(conn, ev, now)
        state["plan"] = plan
        dispatch = _one(conn, "dispatch")
        if dispatch:
            send(conn, dispatch, t_page_dispatch(ev, d.short_name, by), "page_dispatch", event_id, now, sample)
        for c in _contacts(conn, VOLUNTEER_ROLES):
            send(conn, c, t_page(ev, plan), "page", event_id, now, sample)
        contacts = {c["id"]: c for c in conn.execute("SELECT * FROM contacts")}
        for w in plan["downwind"]:
            send(conn, contacts[w["contact_id"]], t_downwind(ev, contacts[w["contact_id"]], w["eta_min"], d.short_name), "downwind", event_id, now, sample)
        for h in plan["helpers"]:
            send(conn, contacts[h["contact_id"]], t_helper(ev, contacts[h["contact_id"]], d.short_name), "helper", event_id, now, sample)
        cap_ha = d.settings.get("capacity_ha_60min", 150)
        if plan["area_60_ha"] > cap_ha:
            _draft_mutual_aid(
                conn, ev, state,
                f"~{plan['acres_60']} ac in 1 hr, over the {round(cap_ha / HA_PER_ACRE)} ac 2 trucks can hold",
                now,
            )
        conn.execute("UPDATE events SET status = 'escalated' WHERE id = ? AND status IN ('new', 'acknowledged')", (event_id,))
    elif action == "no":
        state.update(decision="no", decision_by=by, decision_at=iso(now))
        conn.execute("UPDATE events SET status = 'dismissed' WHERE id = ?", (event_id,))
    elif action == "send":
        if not state.get("mutual_aid"):
            _draft_mutual_aid(conn, ev, state, f"requested by {by}", now)
        ma = state["mutual_aid"]
        if not ma.get("sent_at"):
            target = _one(conn, "mutual_aid")
            plan = state.get("plan") or plan_response(conn, ev, now)
            if target:
                send(conn, target, t_mutual_aid(ev, d.short_name, plan, _n_responding(state)), "mutual_aid", event_id, now, sample)
            ma.update(sent_at=iso(now), sent_by=by)
    else:
        raise ValueError(f"unknown decision {action!r}")
    conn.execute(
        "INSERT INTO actions(event_id, action, operator, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (event_id, {"page": "escalate", "no": "dismiss", "send": "escalate"}[action], by, f"{action.upper()} via Firewatch", iso(now)),
    )
    _save(conn, event_id, state)
    return state


def _draft_mutual_aid(conn, ev, state: dict, reason: str, now: datetime) -> None:
    d = load_district()
    state["mutual_aid"] = {"reason": reason, "drafted_at": iso(now)}
    chief = next((c for c in _ladder(conn) if c["role"] == "chief"), None)
    if chief:
        send(conn, chief, t_mutual_aid_draft(reason, d.neighbor_district), "mutual_aid_draft", ev["id"], now, bool(ev["is_sample"]))
    _save(conn, ev["id"], state)


def plan_response(conn: sqlite3.Connection, ev, now: datetime) -> dict:
    """Spread from the event over the next hour: footprint, downwind contacts with ETAs, nearby helpers."""
    f = loads(ev["features_json"], {})
    w = loads(ev["weather_json"], {})
    elapsed = max(0, round((now - parse_iso(ev["first_seen"])).total_seconds() / 60))
    horizon = elapsed + PLAN_MINUTES
    contacts = [c for c in conn.execute("SELECT * FROM contacts WHERE lat IS NOT NULL AND opted_in = 1")]
    wind = w.get("wind_kmh") or f.get("wind_kmh", 0.0)
    wdir = w.get("wind_dir_deg") if w.get("wind_dir_deg") is not None else f.get("wind_dir_deg", 0.0)
    sim = simulate(
        SpreadInput(
            lat=ev["lat"], lon=ev["lon"], wind_kmh=wind, wind_from_deg=wdir,
            temp_c=f.get("temp_c", 15.0), rh_pct=f.get("rh_pct", 50.0),
            curing_pct=f.get("curing_pct", default_curing(parse_iso(ev["first_seen"]).month)),
            minutes=horizon, use_terrain=not ev["is_sample"],
        ),
        points=[(c["lat"], c["lon"]) for c in contacts],
    )
    area = next((iso_["properties"]["area_ha"] for iso_ in reversed(sim["isochrones"]["features"])), 0.0)
    downwind, helpers = [], []
    for c, t in zip(contacts, sim["point_minutes"]):
        if c["role"] in HELPER_ROLES and haversine_km(ev["lat"], ev["lon"], c["lat"], c["lon"]) <= HELPER_RADIUS_KM:
            helpers.append({"contact_id": c["id"], "name": c["name"], "role": c["role"]})
        elif c["role"] in NEIGHBOR_ROLES and t is not None:
            eta = max(5, int(5 * round((t - elapsed) / 5)))
            downwind.append({"contact_id": c["id"], "name": c["name"], "eta_min": eta})
    downwind.sort(key=lambda x: x["eta_min"])
    return {
        "minutes": horizon,
        "area_60_ha": round(area, 1),
        "acres_60": int(round(area / HA_PER_ACRE, -1)),
        "wind": {"from": compass(wdir), "mph": round(wind / KM_PER_MILE)},
        "downwind": downwind,
        "helpers": helpers,
    }


def _latest_open_response(conn, is_sample: bool) -> int | None:
    """The newest event with a response under way, for a ladder member who was not texted about it."""
    r = conn.execute(
        "SELECT id FROM events WHERE response_json IS NOT NULL AND status NOT IN ('closed', 'dismissed') "
        "AND is_sample = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
        (int(is_sample),),
    ).fetchone()
    return r["id"] if r else None


# --- inbound ---------------------------------------------------------------------------------------------

HELP = "{name} Firewatch: text FIRE to report a fire, BURN to register a burn today, STOP to opt out."


RESERVED = ("1", "2", "3", "PAGE", "NO", "SEND", "R", "ACK", "STOP", "START", "JOIN", "FIRE", "BURN")


def _newest_ask(conn, contact_id: int):
    """The newest open ask for a contact: ("post", post_id, ask_id) or ("event", event_id), else None."""
    pa = conn.execute(
        "SELECT id, post_id, asked_at FROM post_asks WHERE contact_id = ? AND answered_at IS NULL ORDER BY id DESC LIMIT 1",
        (contact_id,)).fetchone()
    ev = conn.execute(
        "SELECT id, event_id, created_at FROM messages WHERE contact_id = ? AND direction = 'out' AND event_id IS NOT NULL "
        "AND purpose = 'ask_neighbor' ORDER BY id DESC LIMIT 1", (contact_id,)).fetchone()
    if pa and (not ev or pa["asked_at"] >= ev["created_at"]):
        return ("post", pa["post_id"], pa["id"])
    if ev:
        return ("event", ev["event_id"])
    return None


def _confirm_reply(r: dict) -> str:
    if r.get("reason") in ("own_post", "duplicate"):
        return "Firewatch: thanks, you already have this one."
    if not r.get("ok"):
        return "Firewatch: that post is no longer open."
    return "Firewatch: thanks. The fire district has your answer."


def handle_inbound(
    conn: sqlite3.Connection, phone: str, body: str, now: datetime, is_sample: bool = False,
    channel: str = "sms", at: tuple[float, float] | None = None,
) -> dict:
    """Parse one inbound text. Returns {"action", "event_id", "reply"}; the reply is also sent.

    `phone` is the sender's number, or their radio's node ID on the mesh channel. `at` is where the sender is
    right now (a radio's GPS fix) and locates their reports in place of their roster address.
    """
    from . import posts as posts_mod
    from .confirm import evaluate_event
    from .keywords import classify
    from .signals import add_signal

    d = load_district()
    contact = conn.execute("SELECT * FROM contacts WHERE phone = ? OR mesh_id = ?", (phone, phone)).fetchone()
    here = at or ((contact["lat"], contact["lon"]) if contact and contact["lat"] is not None else None)
    words = re.findall(r"[A-Za-z0-9]+", body.upper())
    word = words[0] if words else ""
    rest = body.strip()[len(words[0]):].strip(" :-,") if words else ""
    conn.execute(
        "INSERT INTO messages(event_id, contact_id, phone, direction, purpose, body, status, is_sample, created_at, channel) "
        "VALUES (NULL, ?, ?, 'in', NULL, ?, 'received', ?, ?, ?)",
        (contact["id"] if contact else None, phone, body, int(is_sample), iso(now), channel),
    )
    msg_id = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    out: dict = {"action": "help", "event_id": None, "reply": None}

    def latest_event(purposes: tuple[str, ...]) -> int | None:
        if contact is None:
            return None
        r = conn.execute(
            f"SELECT event_id FROM messages WHERE contact_id = ? AND direction = 'out' AND event_id IS NOT NULL "
            f"AND purpose IN ({','.join('?' * len(purposes))}) ORDER BY id DESC LIMIT 1",
            (contact["id"], *purposes),
        ).fetchone()
        return r["event_id"] if r else None

    def fire_report(rest_text: str, category: str = "fire"):
        w = parse_where(rest_text)
        at_pt, join_km, reply = here, None, "Firewatch: report received. The duty officer is being told."
        if w:
            at_pt, join_km = point_from(*here, w), ESTIMATE_JOIN_KM
            reply = f"Firewatch: placed {w.label} of you. The duty officer is being told. Wrong? Text FIRE again."
        elif rest_text:
            reply += " " + t_place_hint()
        eid = add_signal(conn, "report", *at_pt, iso(now), f"{channel}:{phone}", rest_text or None,
                         contact["id"] if contact else None, is_sample, join_radius_km=join_km)
        evaluate_event(conn, eid, None, now)
        posts_mod.record(conn, contact, phone, body, at_pt, bool(w), eid, now, is_sample, channel, category)
        ev = _event(conn, eid)
        if not d.contains(ev["lat"], ev["lon"]):
            # The ladder only alerts for in-district events, so tell the duty officer directly.
            # event_id=None and a purpose outside DECIDERS keep the text from being a PAGE/NO target,
            # and nothing is written to the event. Dedupe is per sender over a window, not per event.
            # The prefix is matched from the start of the body, so text a sender writes can never match it.
            # A mesh row counts only once the recipient confirmed it: relayed is just a rebroadcast.
            prefix = f"FIREWATCH report outside district from {phone} at "
            recent = conn.execute(
                "SELECT 1 FROM messages WHERE direction = 'out' AND purpose = 'duty_fyi_outside' "
                "AND ((channel = 'sms' AND status = 'sent') OR status = 'delivered') "
                "AND is_sample = ? AND created_at > ? AND created_at <= ? AND substr(body, 1, ?) = ? LIMIT 1",
                (int(is_sample), iso(now - timedelta(minutes=OUTSIDE_FYI_WINDOW_MIN)), iso(now), len(prefix), prefix),
            ).fetchone()
            if recent:
                reply = "Firewatch: your earlier report already went to the duty officer. Call 911 if anyone is in danger."
            else:
                fyi = f"{prefix}{here[0]:.4f},{here[1]:.4f}: {body.strip()}"
                for c in _ladder(conn):
                    sent = send(conn, c, fyi[:SMS_MAX], "duty_fyi_outside", None, now, is_sample)
                    if sent and sent["status"] == "sent":
                        break
                else:
                    reply = "Firewatch: report received but no duty officer could be reached. Call 911 if anyone is in danger."
        return eid, reply

    if word == "STOP":
        if contact:
            conn.execute("UPDATE contacts SET opted_in = 0 WHERE id = ?", (contact["id"],))
        out.update(action="stop", reply="Firewatch: you won't get more texts. Text START to opt back in.")
    elif word == "START":
        if contact:
            conn.execute("UPDATE contacts SET opted_in = 1 WHERE id = ?", (contact["id"],))
        out.update(action="start", reply="Firewatch: you're back on. Text STOP to opt out.")
    elif word == "JOIN":
        if contact is None:
            conn.execute(
                "INSERT INTO contacts(name, phone, role, registered, mesh_id) VALUES (?, ?, 'pending', 0, ?)",
                (rest[:60] or "Unregistered", phone, phone if channel == "mesh" else None),
            )
        out.update(action="join", reply=f"Firewatch: thanks. {d.short_name} will confirm your number and place.")
    elif word in ("1", "2", "3") and contact and (ask := _newest_ask(conn, contact["id"])):
        kind = {"1": "see", "2": "not_seeing", "3": "burn"}[word]
        if ask[0] == "post":
            conn.execute("UPDATE post_asks SET answered_at = ? WHERE id = ?", (iso(now), ask[2]))
            r = posts_mod.confirm(conn, ask[1], contact, kind, now, is_sample, channel, *(here or (None, None)))
            out.update(action="post_confirm", event_id=r.get("event_id"), reply=_confirm_reply(r))
        else:
            eid = ask[1]
            first = conn.execute("SELECT id FROM posts WHERE event_id = ? ORDER BY id LIMIT 1", (eid,)).fetchone()
            if first and word == "1":
                r = posts_mod.confirm(conn, first["id"], contact, "see", now, is_sample, channel, *(here or (None, None)))
                out.update(action="post_confirm", event_id=eid, reply=_confirm_reply(r))
            else:
                if first:
                    conn.execute(
                        "INSERT OR IGNORE INTO post_confirms(post_id, contact_id, kind, channel, counted, reason, created_at) "
                        "VALUES (?, ?, ?, ?, 0, 'note', ?)", (first["id"], contact["id"], kind, channel, iso(now)))
                add_signal(conn, "neighbor_reply", contact["lat"], contact["lon"], iso(now), f"{channel}:{phone}", word,
                           contact["id"], is_sample, event_id=eid)
                evaluate_event(conn, eid, None, now)
                out.update(action="neighbor_reply", event_id=eid, reply="Thanks. The fire district has your answer.")
    elif word in ("PAGE", "NO", "SEND") and contact and contact["role"] in LADDER_ROLES:
        purposes = ("mutual_aid_draft",) + DECIDERS if word == "SEND" else DECIDERS
        eid = latest_event(purposes) or _latest_open_response(conn, is_sample)
        if eid is None:
            out.update(action="help", reply="Firewatch: no open alert for you to answer.")
        else:
            decide(conn, eid, word.lower(), contact["name"], now)
            reply = {"page": "Paged. Dispatch and crews notified.", "no": "Stood down. Logged.",
                     "send": "Mutual aid requested."}[word.lower()]
            out.update(action=word.lower(), event_id=eid, reply=f"Firewatch: {reply}")
    elif word == "R" and (eid := latest_event(("page", "helper"))):
        ev = _event(conn, eid)
        state = _state(ev)
        responders = state.setdefault("responders", [])
        if all(r["contact_id"] != contact["id"] for r in responders):
            responders.append({"contact_id": contact["id"], "name": contact["name"], "role": contact["role"], "at": iso(now)})
        _save(conn, eid, state)
        out.update(action="responding", event_id=eid, reply=f"Firewatch: copy, {len(responders)} responding.")
    elif word == "FIRE":
        if here:
            eid, reply = fire_report(rest)
            out.update(action="report", event_id=eid, reply=reply)
        else:
            duty = _ladder(conn)[:1]
            if duty:
                send(conn, duty[0], f"FIREWATCH unlocated report from {phone}: {body.strip()}"[:SMS_MAX], "duty_fyi", None, now, is_sample)
            posts_mod.record(conn, contact, phone, body, None, False, None, now, is_sample, channel)
            out.update(action="report_unlocated", reply="Firewatch: report sent to the duty officer. Call 911 if anyone is in danger.")
    elif word == "BURN" and contact and here:
        burn_date = now.astimezone(CENTRAL).date().isoformat()
        radius = d.settings.get("burn_radius_km", 1.5)
        conn.execute(
            "INSERT INTO burn_notices(contact_id, lat, lon, radius_km, burn_date, is_sample, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (contact["id"], *here, radius, burn_date, int(is_sample), iso(now)),
        )
        out.update(action="burn", reply="Firewatch: burn noted for today near your place. Text FIRE if it gets away.")
    else:
        out["reply"] = HELP.format(name=d.short_name)
        text = body.strip()
        if text and word not in RESERVED:
            cat = classify(text)
            if (contact and contact["registered"] and not cat.hearsay and cat.category in ("fire", "smoke") and here):
                eid, reply = fire_report(text, cat.category)
                out.update(action="report", event_id=eid, reply=reply)
            else:
                r = posts_mod.create(conn, contact, phone, text, cat.category, cat.hearsay, now, is_sample, channel, at=here)
                if cat.category != "other":
                    out["event_id"] = r["event_id"]
                    if r["event_id"]:
                        out.update(action="post_report", reply="Firewatch: report received. The duty officer is being told.")
                    elif r["flagged"]:
                        reply = "Firewatch: posted."
                        if r["asked"] > 0:
                            reply += " Neighbors nearby are being asked."
                        reply += " Call 911 if anyone is in danger."
                        out.update(action="post_flagged", reply=reply)
                    elif cat.category == "burn":
                        out.update(action="post", reply="Firewatch: to register a burn, text BURN. Text FIRE if it gets away.")
                    else:
                        reply = "Firewatch: posted to the board."
                        if not here and cat.category in ("fire", "smoke"):
                            reply += " " + t_place_hint()
                        out.update(action="post", reply=reply)

    if out["event_id"]:
        conn.execute("UPDATE messages SET event_id = ? WHERE id = ?", (out["event_id"], msg_id))
    if out["reply"]:
        target = contact or {"id": None, "phone": phone, "name": phone, "opted_in": 1, "mesh_id": phone if channel == "mesh" else None}
        send(conn, target, out["reply"], "reply", out["event_id"], now, is_sample, channels=(channel,))
    return out
