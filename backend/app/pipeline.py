"""detections -> events -> features -> scores. Used by both live polling and sample mode."""

import logging
import sqlite3
from datetime import datetime, timedelta

import httpx

from .config import get_settings
from .confirm import evaluate_event, fetch_weather
from .db import connect, iso, mark_source, utcnow
from .features.cluster import assign_detection
from .ingest import firms

log = logging.getLogger(__name__)


def dedupe_key(d: dict) -> str:
    return f"{d['source']}|{d['lat']:.4f}|{d['lon']:.4f}|{d['acq_time']}"


_SUFFIXES = ("_URT", "_RT", "_NRT", "_SP")
_RT_SUFFIXES = ("_URT", "_RT")
MATCH_DEG = 0.003  # about 300 m: a processed row re-locates the same pixel by less than this


def base_source(source: str) -> str:
    for suf in _SUFFIXES:
        if source.endswith(suf):
            return source[: -len(suf)]
    return source


def _same_pixel_other_product(conn: sqlite3.Connection, d: dict):
    """Existing row for the same sensor and overpass time under a different product suffix
    (real-time vs near-real-time vs standard) at nearly the same location."""
    base = base_source(d["source"])
    rows = conn.execute(
        "SELECT id, source FROM detections WHERE acq_time = ? AND source != ? "
        "AND abs(lat - ?) <= ? AND abs(lon - ?) <= ?",
        (d["acq_time"], d["source"], d["lat"], MATCH_DEG, d["lon"], MATCH_DEG),
    ).fetchall()
    return [r for r in rows if base_source(r["source"]) == base]


def insert_detections(conn: sqlite3.Connection, dets: list[dict], is_sample: bool = False) -> list[int]:
    now = iso(utcnow())
    new_ids = []
    for d in dets:
        twins = _same_pixel_other_product(conn, d)
        if twins:
            # Same detection seen under another product. A processed row replaces a real-time one
            # in place (keeps its event); anything else is a duplicate and is dropped.
            rt = [r for r in twins if r["source"].endswith(_RT_SUFFIXES)]
            if rt and not d["source"].endswith(_RT_SUFFIXES):
                conn.execute(
                    "UPDATE detections SET dedupe_key = ?, source = ?, lat = ?, lon = ?, brightness_k = ?, "
                    "frp_mw = ?, confidence = ?, scan_km = ?, track_km = ?, daynight = ? WHERE id = ?",
                    (dedupe_key(d), d["source"], d["lat"], d["lon"], d.get("brightness_k"), d.get("frp_mw"),
                     d.get("confidence"), d.get("scan_km"), d.get("track_km"), d.get("daynight"), rt[0]["id"]),
                )
            continue
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


def score_event(
    conn: sqlite3.Connection, event_id: int, weather: dict | None = None, now: datetime | None = None
) -> None:
    """Enrich, score, and re-level one event. If `weather` is None, fetch it live (failure -> degraded)."""
    if weather is None:
        weather = fetch_weather(conn, event_id)
    evaluate_event(conn, event_id, weather, now)


def process_detections(
    conn: sqlite3.Connection,
    dets: list[dict],
    is_sample: bool = False,
    weather: dict | None = None,
    now: datetime | None = None,
) -> set[int]:
    touched: set[int] = set()
    for det_id in insert_detections(conn, dets, is_sample):
        touched.add(assign_detection(conn, det_id))
    existing = {r["id"] for r in conn.execute("SELECT id FROM events").fetchall()}
    touched &= existing
    for event_id in sorted(touched):
        score_event(conn, event_id, weather, now)
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
                dets = firms.fetch_area(s.firms_map_key, source, s.bbox_tuple, days=s.firms_days)
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
