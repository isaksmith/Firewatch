"""detections -> events -> features -> scores. Used by both live polling and sample mode."""

import json
import logging
import sqlite3
from datetime import timedelta

import httpx

from .config import get_settings
from .db import connect, iso, mark_source, parse_iso, utcnow
from .features.cluster import SIGNAL_JOIN_AFTER, assign_detection, event_points, refresh_event_geometry
from .features.enrich import build_features
from .fire_weather import default_curing, gfdi
from .geo import haversine_km
from .ingest import firms
from .ingest.weather import weather_at
from .scoring.score import persist_score

log = logging.getLogger(__name__)


def dedupe_key(d: dict) -> str:
    return f"{d['source']}|{d['lat']:.4f}|{d['lon']:.4f}|{d['acq_time']}"


def insert_detections(conn: sqlite3.Connection, dets: list[dict], is_sample: bool = False) -> list[int]:
    now = iso(utcnow())
    new_ids = []
    for d in dets:
        cur = conn.execute(
            "INSERT OR IGNORE INTO detections(dedupe_key, source, satellite, lat, lon, acq_time, brightness_k, "
            "frp_mw, confidence, scan_km, track_km, daynight, is_sample, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dedupe_key(d), d["source"], d.get("satellite"), d["lat"], d["lon"], d["acq_time"],
                d.get("brightness_k"), d.get("frp_mw"), d.get("confidence"), d.get("scan_km"),
                d.get("track_km"), d.get("daynight"), int(is_sample), now,
            ),
        )
        if cur.rowcount:
            new_ids.append(cur.lastrowid)
    return new_ids


def score_event(conn: sqlite3.Connection, event_id: int, weather: dict | None = None) -> None:
    """Enrich and score one event. If `weather` is None, fetch it live (failure -> degraded)."""
    if weather is None:
        ev = conn.execute("SELECT lat, lon, last_seen FROM events WHERE id = ?", (event_id,)).fetchone()
        try:
            weather = weather_at(ev["lat"], ev["lon"], parse_iso(ev["last_seen"]))
            mark_source(conn, "open_meteo", ok=True)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("weather unavailable for event %s: %s", event_id, e)
            mark_source(conn, "open_meteo", ok=False, error=str(e))
            weather = None
    features, degraded = build_features(conn, event_id, weather)
    persist_score(conn, event_id, features, degraded, weather)


def process_detections(
    conn: sqlite3.Connection, dets: list[dict], is_sample: bool = False, weather: dict | None = None
) -> set[int]:
    touched: set[int] = set()
    for det_id in insert_detections(conn, dets, is_sample):
        touched.add(assign_detection(conn, det_id))
    existing = {r["id"] for r in conn.execute("SELECT id FROM events").fetchall()}
    touched &= existing
    for event_id in sorted(touched):
        score_event(conn, event_id, weather)
    return touched


JOIN_FAULT_KM = 2.0     # a fault this close to an open event, around the same time, is the same fire
JOIN_REPORT_KM = 5.0    # a public report this close to an open event joins it
GFDI_HIGH = 25.0        # "Very High" and up counts as high fire weather


def fire_weather_high(weather: dict | None, when) -> bool:
    """Red Flag Warning, or a grass fire danger index in the Very High band or worse."""
    if not weather:
        return False
    if weather.get("red_flag"):
        return True
    try:
        g = gfdi(default_curing(when.month, get_settings().curing_pct_override), weather["temp_c"],
                 weather["rh_pct"], weather["wind_kmh"])
    except (KeyError, TypeError):
        return False
    return g >= GFDI_HIGH


def _open_events(conn: sqlite3.Connection, is_sample: bool):
    return conn.execute(
        "SELECT id, lat, lon, first_seen, last_seen FROM events WHERE status != 'closed' AND is_sample = ?",
        (int(is_sample),),
    ).fetchall()


def _closest_event(conn, events, lat, lon, max_km):
    best, best_km = None, max_km
    for ev in events:
        km = min((haversine_km(lat, lon, a, b) for a, b in event_points(conn, ev["id"])), default=None)
        if km is not None and km <= best_km:
            best, best_km = ev["id"], km
    return best


def _attach_signal(conn, kind, lat, lon, t, payload, event_id, is_sample) -> int:
    cur = conn.execute(
        "INSERT INTO signals(kind, lat, lon, time, payload_json, event_id, is_sample, ingested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, lat, lon, t, json.dumps(payload), event_id, int(is_sample), iso(utcnow())),
    )
    return cur.lastrowid


def _new_signal_event(conn, lat, lon, t, is_sample) -> int:
    return conn.execute(
        "INSERT INTO events(lat, lon, first_seen, last_seen, is_sample, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (lat, lon, t, t, int(is_sample), iso(utcnow())),
    ).lastrowid


def process_line_fault(
    conn: sqlite3.Connection, lat: float, lon: float, time_iso: str, circuit: str, kind: str = "fault",
    is_sample: bool = False, weather: dict | None = None,
) -> dict:
    """A utility fault. In high fire weather it opens (or joins) a "possible fire" event, Investigate at most."""
    t = parse_iso(time_iso)
    if weather is None:
        try:
            weather = weather_at(lat, lon, t)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("weather unavailable for line fault: %s", e)
    payload = {"circuit": circuit, "kind": kind}
    if not fire_weather_high(weather, t):
        sid = _attach_signal(conn, "line_fault", lat, lon, time_iso, payload, None, is_sample)
        return {"signal_id": sid, "event_id": None, "created_event": False, "joined": False,
                "note": "Logged. Fire weather is not high, so no event was opened."}

    near = [
        ev for ev in _open_events(conn, is_sample)
        if parse_iso(ev["first_seen"]) - SIGNAL_JOIN_AFTER <= t <= parse_iso(ev["last_seen"]) + SIGNAL_JOIN_AFTER
    ]
    event_id = _closest_event(conn, near, lat, lon, JOIN_FAULT_KM)
    created = event_id is None
    if created:
        event_id = _new_signal_event(conn, lat, lon, time_iso, is_sample)
    sid = _attach_signal(conn, "line_fault", lat, lon, time_iso, payload, event_id, is_sample)
    refresh_event_geometry(conn, event_id)
    score_event(conn, event_id, weather)
    return {"signal_id": sid, "event_id": event_id, "created_event": created, "joined": not created}


def process_report(
    conn: sqlite3.Connection, lat: float, lon: float, time_iso: str, text: str, phone: str | None = None,
    is_sample: bool = False, weather: dict | None = None,
) -> dict:
    """A public smoke report. Joins the nearest open event within 5 km, else opens an Investigate event."""
    t = parse_iso(time_iso)
    near = [
        ev for ev in _open_events(conn, is_sample)
        if parse_iso(ev["first_seen"]) - timedelta(hours=12) <= t <= parse_iso(ev["last_seen"]) + timedelta(hours=12)
    ]
    event_id = _closest_event(conn, near, lat, lon, JOIN_REPORT_KM)
    created = event_id is None
    if created:
        event_id = _new_signal_event(conn, lat, lon, time_iso, is_sample)
    sid = _attach_signal(conn, "report", lat, lon, time_iso, {"text": text, "phone": phone}, event_id, is_sample)
    refresh_event_geometry(conn, event_id)
    score_event(conn, event_id, weather)
    return {"signal_id": sid, "event_id": event_id, "created_event": created, "joined": not created}


def add_burn(
    conn: sqlite3.Connection, lat: float, lon: float, start: str, end: str, called_in: str, caller: str,
    label: str | None = None, is_sample: bool = False,
) -> dict:
    """Log a burn called in to dispatch, then re-score any open event it may explain."""
    cur = conn.execute(
        'INSERT INTO burns(lat, lon, "start", "end", called_in, caller, label, is_sample, created_at) '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (lat, lon, start, end, called_in, caller, label, int(is_sample), iso(utcnow())),
    )
    for ev in _open_events(conn, is_sample):
        if any(haversine_km(lat, lon, a, b) <= 25 for a, b in event_points(conn, ev["id"])):
            row = conn.execute("SELECT weather_json FROM events WHERE id = ?", (ev["id"],)).fetchone()
            w = json.loads(row["weather_json"]) if row["weather_json"] else None
            if w:  # already scored once; re-score with the weather it had
                w.pop("gfdi", None)
                score_event(conn, ev["id"], w)
    return {"id": cur.lastrowid}


def poll_firms_once() -> dict:
    """One live ingest pass over all configured FIRMS sources."""
    s = get_settings()
    summary = {"sources": {}, "events_touched": 0}
    if not s.firms_map_key:
        summary["error"] = "FIRMS_MAP_KEY not set"
        return summary
    with connect() as conn:
        all_dets = []
        for source in s.firms_source_list:
            try:
                dets = firms.fetch_area(s.firms_map_key, source, s.bbox_tuple, days=1)
                mark_source(conn, "firms", ok=True)
                summary["sources"][source] = len(dets)
                all_dets.extend(dets)
            except (httpx.HTTPError, RuntimeError) as e:
                log.warning("FIRMS %s failed: %s", source, e)
                mark_source(conn, "firms", ok=False, error=f"{source}: {e}")
                summary["sources"][source] = f"error: {e}"
        touched = process_detections(conn, all_dets)
        summary["events_touched"] = len(touched)
        close_stale_events(conn)
    return summary


def close_stale_events(conn: sqlite3.Connection, hours: int = 24) -> None:
    cutoff = iso(utcnow() - timedelta(hours=hours))
    conn.execute(
        "UPDATE events SET status = 'closed' WHERE is_sample = 0 AND status != 'closed' AND last_seen < ?",
        (cutoff,),
    )
