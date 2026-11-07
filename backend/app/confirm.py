"""Confirm: combine satellite, line-fault, and people signals into one level (docs/DESIGN.md section 4.5).

A level needs independent sources. One source gets the duty officer an FYI and asks the neighbors; two
(or a strong satellite detection) asks the duty officer to page. A registered burn that has not escaped
stays at Monitor and texts nobody.
"""

import json
import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .db import iso, loads, mark_source, parse_iso, utcnow
from .district import District, load_district
from .features.cluster import LOCATING_SIGNALS, SENSOR_SIGNALS
from .features.enrich import build_features, context_features
from .fire_weather import gfdi_band
from .geo import KM_PER_MILE, bearing_deg, compass, haversine_km
from .ingest.weather import weather_at
from .redflag import red_flag_active
from .scoring.score import LEVELS, persist_score

log = logging.getLogger(__name__)
CENTRAL = ZoneInfo("America/Chicago")
IN_TOWN_KM = 1.0
BURN_ESCAPE_OUTSIDE_KM = 1.0
REC_LABEL = {"monitor": "Monitor", "investigate": "Investigate", "escalate": "Escalate"}


def fetch_weather(conn: sqlite3.Connection, event_id: int) -> dict:
    """Live weather at the event; {} (degraded) if the service fails."""
    ev = conn.execute("SELECT lat, lon, last_seen FROM events WHERE id = ?", (event_id,)).fetchone()
    try:
        w = weather_at(ev["lat"], ev["lon"], parse_iso(ev["last_seen"]))
        mark_source(conn, "open_meteo", ok=True)
        return w
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.warning("weather unavailable for event %s: %s", event_id, e)
        mark_source(conn, "open_meteo", ok=False, error=str(e))
        return {}


def _district() -> District | None:
    try:
        return load_district()
    except FileNotFoundError:
        return None


def evaluate_event(
    conn: sqlite3.Connection, event_id: int, weather: dict | None = None, now: datetime | None = None,
    red_flag: bool | None = None,
) -> dict:
    """Re-level an event from all its evidence and start the response if the level rose.

    `weather` None reuses the weather stored on the event, fetching it live if there is none.
    `now` is the response clock (the scenario replay passes its own).
    `red_flag` None reads the stored NWS Red Flag Warning; a replay passes its scenario's explicit flag.
    """
    now = now or utcnow()
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if weather is None:
        weather = loads(ev["weather_json"], {}) or fetch_weather(conn, event_id)
    if weather and not ev["is_sample"]:
        from .sensors import local_weather

        weather = local_weather(conn, ev["lat"], ev["lon"], weather)

    has_dets = conn.execute("SELECT 1 FROM detections WHERE event_id = ? LIMIT 1", (event_id,)).fetchone()
    sat = None
    if has_dets:
        f, degraded = build_features(conn, event_id, weather)
        sat = persist_score(conn, event_id, f, degraded)
    else:
        f, degraded = context_features(
            conn, event_id, ev["is_sample"], ev["lat"], ev["lon"],
            parse_iso(ev["first_seen"]), parse_iso(ev["last_seen"]), weather,
        )
    district = _district()
    if red_flag is None:
        red_flag = red_flag_active(conn, ev["lat"], ev["lon"], now)
    level, reason, evidence, suppression = decide_level(conn, ev, f, sat, district, red_flag)

    prev_level = ev["recommendation"]
    status, reraised = ev["status"], 0
    if status == "dismissed" and prev_level in LEVELS and LEVELS.index(level) > LEVELS.index(prev_level):
        status, reraised = "new", 1
    conn.execute(
        "UPDATE events SET features_json = ?, weather_json = ?, score = ?, recommendation = ?, degraded = ?, "
        "guardrail = ?, suppression = ?, status = ?, reraised = MAX(reraised, ?), evidence_json = ?, "
        "level_reason = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(f), json.dumps(weather or {}), sat.score if sat else None, level, int(degraded),
            sat.guardrail if sat else None, suppression, status, reraised, json.dumps(evidence),
            reason, iso(utcnow()), event_id,
        ),
    )

    rose = LEVELS.index(level) > (LEVELS.index(prev_level) if prev_level in LEVELS else -1)
    if rose and level != "monitor" and district is not None and district.contains(ev["lat"], ev["lon"]):
        from . import notify

        notify.on_level(conn, event_id, level, now)
    return {"level": level, "reason": reason, "evidence": evidence}


def decide_level(
    conn: sqlite3.Connection, ev: sqlite3.Row, f: dict, sat, district: District | None, red_flag: bool = False
) -> tuple[str, str, list[dict], str | None]:
    """Returns (level, reason, evidence, suppression). Evidence `counts` is strong | yes | weak | no:
    `yes` sources are independent and two of them escalate; `weak` ones only reach Investigate."""
    cfg = district.settings if district else {}
    min_gfdi = cfg.get("line_fault_min_gfdi", 12)
    g = f["gfdi"]
    evidence: list[dict] = []
    independent: dict[str, str] = {}  # source key -> label
    weak: list[str] = []
    strong = False
    red_flag_fault = False

    if sat is not None:
        last = conn.execute("SELECT MAX(acq_time) t FROM detections WHERE event_id = ?", (ev["id"],)).fetchone()["t"]
        counts = {"escalate": "strong", "investigate": "yes"}.get(sat.recommendation, "no")
        label = f"Satellite: score {sat.score} ({REC_LABEL[sat.recommendation]})"
        evidence.append({"kind": "satellite", "label": label, "at": last, "counts": counts})
        if counts != "no":
            independent["satellite"] = "satellite detection"
            strong = counts == "strong"

    signals = conn.execute(
        "SELECT s.*, c.name AS contact_name, c.registered AS contact_registered, c.lat AS c_lat, c.lon AS c_lon "
        "FROM signals s LEFT JOIN contacts c ON c.id = s.contact_id WHERE s.event_id = ? ORDER BY s.observed_at",
        (ev["id"],),
    ).fetchall()
    claimed_by = None
    for s in signals:
        item = {"kind": s["kind"], "at": s["observed_at"], "source": s["source"]}
        if s["kind"] == "line_fault":
            why_not = []
            if (s["value"] or "").lower() != "lockout":
                why_not.append("momentary trip, not a lockout")
            if f["dist_town_km"] <= IN_TOWN_KM:
                why_not.append("in town")
            if g < min_gfdi:
                why_not.append(f"fire danger {gfdi_band(g)} (GFDI {g:.0f} < {min_gfdi})")
            item["label"] = f"Power line {(s['value'] or 'fault').lower()} on {s['source'].split(':')[-1]}"
            item["counts"] = "no" if why_not else "yes"
            if why_not:
                item["note"] = "not counted: " + ", ".join(why_not)
            else:
                independent.setdefault("line", "power line lockout")
                if red_flag:
                    red_flag_fault = True
                    item["note"] = "inside the district on a Red Flag day: escalates on its own"
        elif s["kind"] == "report":
            who = s["contact_name"] if s["contact_id"] else "unregistered number"
            item["label"] = f"Text report from {who}" + (f": “{s['value']}”" if s["value"] else "")
            if s["contact_id"] and s["contact_registered"]:
                item["counts"] = "yes"
                independent.setdefault(f"contact:{s['contact_id']}", f"report from {who}")
            else:
                item["counts"] = "weak"
                item["note"] = "unregistered numbers reach Investigate, not Escalate"
                weak.append("unregistered report")
        elif s["kind"] == "neighbor_reply":
            where = ""
            if s["c_lat"] is not None:
                km = haversine_km(ev["lat"], ev["lon"], s["c_lat"], s["c_lon"])
                where = f" ({km / KM_PER_MILE:.1f} mi {compass(bearing_deg(ev['lat'], ev['lon'], s['c_lat'], s['c_lon']))} of fire)"
            answer = {"1": "sees smoke", "2": "no smoke", "3": "says it's their burn"}.get(s["value"], s["value"])
            item["label"] = f"{s['contact_name']}{where}: {answer}"
            item["counts"] = "yes" if s["value"] == "1" else "no"
            if s["value"] == "1":
                independent.setdefault(f"contact:{s['contact_id']}", f"{s['contact_name']} sees smoke")
            elif s["value"] == "3":
                claimed_by = s["contact_name"]
        elif s["kind"] == "camera_smoke":
            item["label"] = f"Camera smoke: {s['source']}"
            item["counts"] = "yes"
            independent.setdefault(f"camera:{s['source']}", "camera smoke")
        elif s["kind"] == "ngfs":
            item["label"] = "Unconfirmed NOAA beta satellite detection (NGFS)"
            item["counts"] = "yes"
            item["note"] = "same source class as a satellite: never a second source with one, never strong"
            independent.setdefault("satellite", item["label"])
        elif s["kind"] == "sensor_smoke":
            # Every smoke sensor together is one source: a plume reaching two of them is still one observation.
            item["label"] = f"Smoke sensor {s['source'].split(':')[-1]}" + (f": {s['value']}" if s["value"] else "")
            item["counts"] = "yes"
            independent.setdefault("sensor", "smoke sensor")
        evidence.append(item)

    burn, escaped, late = _registered_burn(conn, ev, signals)
    extreme = False
    if burn is not None:
        extreme = red_flag or g >= cfg.get("burn_escape_gfdi", 25)
        evidence.append({
            "kind": "burn_notice",
            "label": f"Registered burn: {burn['name']}, today, {burn['radius_km']:g} km radius",
            "at": burn["created_at"],
            "counts": "no",
            **({"note": "escaped: " + ", ".join(escaped)} if escaped else {}),
            **({"note": "notice sent after the event started: a claim, not a reason to stay quiet"} if late else {}),
        })

    n = len(independent)
    labels = list(independent.values())
    if burn is not None and not late and not escaped:
        if not extreme:
            return "monitor", f"Monitor: {burn['name']}'s registered burn, inside its notice and not escaped", evidence, "registered_burn"
        # Fire danger is extreme, so a burn that has not shown escape evidence is still worth one quiet look.
        # Capped at Investigate: a registered burn is visible from space, so a satellite never escalates it.
        why = "Red Flag day" if red_flag else f"fire danger {gfdi_band(g)}"
        return (
            "investigate",
            f"Investigate: {burn['name']}'s registered burn, no sign it escaped, but {why}",
            evidence,
            None,
        )
    if red_flag_fault and district is not None and district.contains(ev["lat"], ev["lon"]):
        level, reason = "escalate", "Escalate: Line fault on a Red Flag day"
    elif strong or n >= 2:
        level = "escalate"
        reason = "Escalate: " + (" + ".join(labels) if n >= 2 else "strong satellite detection")
    elif n == 1 or weak:
        level = "investigate"
        reason = "Investigate: " + (labels[0] if n else weak[0]) + ", needs a second source"
    else:
        level = sat.recommendation if sat else "monitor"
        reason = f"{REC_LABEL[level]}: " + (
            f"satellite score {sat.score}" if sat else next(
                (f"{e['label']}, {e['note']}" for e in evidence if e.get("note")), "no qualifying signal"
            )
        )
    if late and level == "escalate" and not escaped:
        level, reason = "investigate", f"Investigate: {burn['name']} sent a burn notice after this started (a claim); check before paging"
    elif claimed_by and level == "escalate" and not escaped:
        level, reason = "investigate", f"Investigate: {claimed_by} says it's their burn (unregistered); check before paging"

    suppression = None
    if level == "monitor":
        suppression = sat.suppression if sat else "low_signal"
    return level, reason, evidence, suppression


def pick_burn(conn, ev) -> tuple[dict | None, bool]:
    """The burn notice covering this event today and whether it is `late` (sent after the event started)."""
    burn_date = parse_iso(ev["first_seen"]).astimezone(CENTRAL).date().isoformat()
    rows = conn.execute(
        "SELECT b.*, c.name FROM burn_notices b JOIN contacts c ON c.id = b.contact_id "
        "WHERE b.burn_date = ? AND b.is_sample = ? ORDER BY b.created_at",
        (burn_date, ev["is_sample"]),
    ).fetchall()
    first = parse_iso(ev["first_seen"])
    covering = [dict(b) for b in rows if haversine_km(ev["lat"], ev["lon"], b["lat"], b["lon"]) <= b["radius_km"]]
    on_time = [b for b in covering if parse_iso(b["created_at"]) <= first]
    burn = (on_time or covering or [None])[0]
    return burn, burn is not None and not on_time


def burn_late(conn, burn: dict) -> bool:
    """True when an event this notice covers started before it was sent and no earlier notice covered it."""
    for ev in conn.execute("SELECT * FROM events WHERE is_sample = ?", (burn["is_sample"],)):
        picked, late = pick_burn(conn, dict(ev))
        if late and picked is not None and picked["id"] == burn["id"]:
            return True
    return False


def _registered_burn(conn, ev, signals) -> tuple[dict | None, list[str], bool]:
    """The burn notice covering this event today, why it counts as escaped (empty if it hasn't), and
    whether it is `late`: sent after the event started, so only a claim and never a reason to stay quiet.

    Escape needs evidence: any report (the notice tells the burner to text FIRE), a "1" (sees smoke) from
    someone other than the burner, or fire seen outside the notice. Fire danger is a condition, not evidence,
    and a satellite detection is not evidence either: a registered burn is visible from space."""
    burn, late = pick_burn(conn, ev)
    if burn is None:
        return None, [], False
    escaped = []
    limit = burn["radius_km"] + BURN_ESCAPE_OUTSIDE_KM
    points = [(d["lat"], d["lon"]) for d in conn.execute("SELECT lat, lon FROM detections WHERE event_id = ?", (ev["id"],))]
    points += [(s["lat"], s["lon"]) for s in signals if s["kind"] in LOCATING_SIGNALS and s["kind"] not in SENSOR_SIGNALS]
    if any(haversine_km(lat, lon, burn["lat"], burn["lon"]) > limit for lat, lon in points):
        escaped.append(f"fire seen more than {BURN_ESCAPE_OUTSIDE_KM:g} km outside the notice")
    if any(s["kind"] == "report" for s in signals):
        escaped.append("a text report of fire")
    if any(s["kind"] == "neighbor_reply" and s["value"] == "1" and s["contact_id"] != burn["contact_id"] for s in signals):
        escaped.append("a neighbor sees smoke")
    return burn, escaped, late
