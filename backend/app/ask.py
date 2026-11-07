"""Answers to questions people text or radio in: "is it heading our way?" (docs/DESIGN.md section 5.11).

A question gets the facts on the open fires nearest the person asking (status, distance, wind, the forecast's size
and earliest arrival at them), worded by the model in llm.py into one text, or by a plain template when the model
is off or its answer fails the checks. The answer goes out on a worker thread, so a slow model never holds up the
radio or the SMS webhook.
"""

import contextvars
import logging
import re
import threading
from datetime import datetime

import numpy as np

from . import llm
from .db import connect, loads
from .district import load_district
from .geo import KM_PER_MILE, bearing_deg, compass, haversine_km

log = logging.getLogger(__name__)
NEAR_KM = 40.0  # fires this close to the person asking are theirs to hear about
MAX_FIRES = 2
REACH_WINDOW_MIN = 120
LIMIT = 160  # one SMS; notify.send cuts mesh texts to this too
PREFIX = "Firewatch: "
OPEN_LEVELS = ("investigate", "escalate")
QUESTION_WORDS = {
    "is", "are", "was", "were", "where", "wheres", "how", "hows", "what", "whats", "when", "which", "who", "why",
    "will", "would", "should", "can", "could", "do", "does", "did", "any", "anyone", "has", "have", "status", "update",
}
ALONE_WORDS = {"status", "update", "info"}

SYSTEM = (
    "You are Firewatch, the text line of {district}, a volunteer rural fire district in Kansas with one bar of cell "
    "and LoRa radios. A resident texted a question. Answer it from the FACTS only. The first sentence answers the "
    "question. At most {words} words and {n} characters in all: it goes out as one text and anything longer is cut. "
    "No greeting, no markdown, no emoji. Never invent a number, place or time. Never say someone is safe, and never "
    "say what they are seeing is or isn't the fire: say what the forecast shows. If the facts don't answer the "
    "question, say so. If they say they see fire or smoke, tell them to text FIRE. Don't mention 911: that line is "
    "added after your answer."
)
SAFETY = " Call 911 if in danger."


def is_question(text: str) -> bool:
    t = text.strip()
    words = re.findall(r"[a-z]+", t.lower().replace("'", ""))
    if not words:
        return False
    if t.endswith("?"):
        return True
    return (len(words) == 1 and words[0] in ALONE_WORDS) or (len(words) >= 2 and words[0] in QUESTION_WORDS)


# --- facts -----------------------------------------------------------------------------------------------


def _status(ev, state: dict, held: bool) -> tuple[str, str]:
    """(short words for the template, a sentence for the model)."""
    if state.get("decision") == "page":
        n = len(state.get("responders", []))
        ma = state.get("mutual_aid") or {}
        aid = " Mutual aid requested." if ma.get("sent_at") else ""
        return f"crews paged, {n} responding", f"Confirmed fire: crews were paged and {n} people are responding.{aid}"
    if held:
        return "known, being watched", "Known to the duty officer, who is watching it."
    if ev["recommendation"] == "escalate":
        return "likely fire, duty officer deciding", "Likely fire: the duty officer is deciding whether to page crews."
    return "possible fire, being checked", "Possible fire, not confirmed yet: neighbors are being asked to look."


def fire_facts(conn, ev, now: datetime, here: tuple[float, float] | None = None) -> dict:
    """What a question or a channel update about this fire can say. Forecast fields are None when the forecast
    can't be run."""
    from . import notify
    from .playbook import Fire, sites_reached
    from .sim.spread import _arrival_many, interp_weather

    state = loads(ev["response_json"], {}) or {}
    short, line = _status(ev, state, bool(notify.held(ev, now)))
    out = {
        "id": ev["id"], "place": ev["place_label"] or notify._short_place(ev), "short_place": notify._short_place(ev),
        "status": short, "status_line": line, "paged": state.get("decision") == "page",
        "responding": len(state.get("responders", [])),
        "mutual_aid": bool((state.get("mutual_aid") or {}).get("sent_at")),
        "downwind_warned": conn.execute(
            "SELECT COUNT(DISTINCT contact_id) n FROM messages WHERE event_id = ? AND purpose = 'downwind'", (ev["id"],)
        ).fetchone()["n"],
        "dist_mi": None, "from_you": None, "eta_min": None,
        "wind_from": None, "wind_deg": None, "wind_mph": None, "toward": None,
        "acres_now": None, "acres_60": None, "sites_60": None, "stations": [], "red_flag": False, "danger": None,
    }
    if here:
        km = haversine_km(here[0], here[1], ev["lat"], ev["lon"])
        out["dist_mi"] = round(km / KM_PER_MILE, 1)
        out["from_you"] = compass(bearing_deg(here[0], here[1], ev["lat"], ev["lon"]))
    try:
        f = Fire(conn, ev, now)
    except Exception:
        log.warning("no forecast for event %s", ev["id"], exc_info=True)
        return out
    w = interp_weather(f.sit.weather_steps(), f.now_min)
    out.update(
        wind_from=compass(w.wind_from_deg), wind_deg=round(w.wind_from_deg), wind_mph=round(w.wind_kmh / KM_PER_MILE),
        toward=compass((w.wind_from_deg + 180) % 360), acres_now=f.acres_at(f.now_min),
        acres_60=f.acres_at(f.now_min + 60), sites_60=sites_reached(f, f.now_min + 60),
        red_flag=bool(f.sit.red_flag), danger=f.danger,
        stations=[{"name": s["contact"]["name"], "eta_min": s["eta"]} for s in f.stations_in_path(conn)[:2]],
    )
    if here:
        t = float(_arrival_many(f.t10, f.dom.lats, f.dom.lons, np.array([here[0]]), np.array([here[1]]))[0])
        if t <= f.now_min + REACH_WINDOW_MIN:
            out["eta_min"] = max(0, int(5 * round((t - f.now_min) / 5)))
    return out


def facts_text(fires: list[dict], asker: bool) -> str:
    """The facts as the model reads them. Every number the answer may use is in here."""
    lines = []
    for x in fires:
        lines.append(f"Fire {x['id']}, {x['place'].rstrip('.')}. {x['status_line']}")
        if x["dist_mi"] is not None:
            lines.append(f"  It is {x['dist_mi']} mi {x['from_you']} of the person asking.")
        if x["wind_from"]:
            lines.append(f"  It spreads toward the {x['toward']}, pushed by the wind.")
            lines.append(f"  Wind: from the {x['wind_from']}, {x['wind_mph']} mph. This is the wind's speed; the "
                         "forecast gives no speed for the fire itself.")
        if x["acres_now"] is not None:
            lines.append(f"  Forecast size: about {x['acres_now']:,} acres now, likely {x['acres_60']:,} acres in 1 hour.")
        if x["sites_60"]:
            lines.append(f"  {x['sites_60']} homes, farmsteads or leases are in its likely path in the next hour.")
        if asker and x["acres_now"] is not None:
            if x["eta_min"] is None:
                lines.append("  The forecast does not have it reaching the person asking in the next 2 hours.")
            elif x["eta_min"] == 0:
                lines.append("  The worst-case forecast has it already at the person asking's location.")
            else:
                lines.append(f"  Worst case (1 in 10 forecast runs), it could reach the person asking in {x['eta_min']} minutes.")
        for s in x["stations"]:
            lines.append(f"  Worst case, it could reach the first-due area of {s['name']} in {s['eta_min']} minutes.")
        if x["downwind_warned"]:
            lines.append(f"  {x['downwind_warned']} households downwind were warned by text.")
        if x["red_flag"]:
            lines.append("  A red flag warning is in effect.")
        if x["danger"]:
            lines.append(f"  Fire danger: {x['danger']}.")
    if not fires:
        lines.append("No open fires near the person asking right now.")
    return "\n".join(lines)


def nearby_fires(conn, here: tuple[float, float] | None, is_sample: bool, now: datetime) -> list[dict]:
    """The open fires a question is about: nearest the person asking, or the district's newest if we don't know
    where they are."""
    from . import notify

    rows = [
        r for r in conn.execute(
            "SELECT * FROM events WHERE is_sample = ? AND status NOT IN ('closed', 'dismissed') "
            "ORDER BY updated_at DESC, id DESC LIMIT 500", (int(is_sample),))
        if r["recommendation"] in OPEN_LEVELS or notify._state(r).get("decision") == "page"
    ]
    if here:
        near = [(haversine_km(here[0], here[1], r["lat"], r["lon"]), r) for r in rows]
        picked = [r for km, r in sorted(near, key=lambda kr: kr[0]) if km <= NEAR_KM]
    else:
        d = load_district()
        picked = [r for r in rows if d.contains(r["lat"], r["lon"])]
    return [fire_facts(conn, r, now, here) for r in picked[:MAX_FIRES]]


# --- the answer ------------------------------------------------------------------------------------------


def template(fires: list[dict], limit: int) -> str:
    if not fires:
        return f"{PREFIX}no open fire near you right now. Seeing one? Text FIRE. Call 911 if anyone is in danger."
    x = fires[0]
    head = f"{PREFIX}fire {x['id']} {x['short_place'][:40]}"
    if x["dist_mi"] is not None:
        head += f", {x['dist_mi']} mi {x['from_you']} of you"
    parts = [f"{head}: {x['status']}."]
    if x["eta_min"] is not None:
        parts.append(f"Could reach you in as little as {x['eta_min']} min." if x["eta_min"] else "It may already be near you.")
    elif x["wind_from"]:
        parts.append(f"Wind {x['wind_from']} {x['wind_mph']} mph.")
    parts.append("Call 911 if in danger.")
    body = ""
    for p in parts:
        if len(body) + len(p) + 1 > limit:
            break
        body = f"{body} {p}".strip()
    return body


def compose(question: str, fires: list[dict]) -> str:
    n = LIMIT - len(PREFIX) - len(SAFETY)
    facts = facts_text(fires, asker=True)
    words = llm.complete(SYSTEM.format(district=load_district().name, n=n, words=n // 7), facts,
                         f"QUESTION: {question.strip()[:300]}", n)
    return f"{PREFIX}{words}{SAFETY}" if words else template(fires, LIMIT)


def _spawn(fn, *args) -> None:
    # A replay's district overrides and red flag live in context variables; the worker needs them too.
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(fn, *args), daemon=True).start()


spawn = _spawn  # tests run the job inline


def answer_later(msg_id: int, phone: str, question: str, here: tuple[float, float] | None, now: datetime,
                 is_sample: bool, channel: str) -> None:
    spawn(_answer, msg_id, phone, question, here, now, is_sample, channel)


def _answer(msg_id: int, phone: str, question: str, here, now: datetime, is_sample: bool, channel: str) -> None:
    from . import notify

    try:
        with connect() as conn:
            fires = nearby_fires(conn, here, is_sample, now)
        text = compose(question, fires)
    except Exception:
        log.exception("could not answer %s", phone)
        fires, text = [], f"{PREFIX}could not look that up right now. Call 911 if anyone is in danger."
    eid = fires[0]["id"] if fires else None
    with connect() as conn:
        contact = conn.execute("SELECT * FROM contacts WHERE phone = ? OR mesh_id = ?", (phone, phone)).fetchone()
        if eid:
            conn.execute("UPDATE messages SET event_id = ? WHERE id = ? AND event_id IS NULL", (eid, msg_id))
        target = contact or {"id": None, "phone": phone, "name": phone, "opted_in": 1,
                             "mesh_id": phone if channel == "mesh" else None}
        notify.send(conn, target, text, "answer", eid, now, is_sample, channels=(channel,))
