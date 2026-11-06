"""detections -> events -> features -> scores. Used by both live polling and sample mode."""

import logging
import sqlite3
from datetime import timedelta

import httpx

from .config import get_settings
from .db import connect, iso, mark_source, parse_iso, utcnow
from .features.cluster import assign_detection
from .features.enrich import build_features
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
