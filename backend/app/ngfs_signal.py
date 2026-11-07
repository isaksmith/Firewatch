"""NOAA NGFS tracked features as a confirmation signal.

NGFS never goes through process_detections, so it cannot reach the model, the features or the score.
A tracked feature becomes one `ngfs` signal only when all three hold:
  1. type_description is exactly "Possible Wildland Fire" (missing or null fails closed),
  2. it has been seen in at least two separate scans (two different acq_date_time values),
  3. no registered burn notice for that day covers it.
The signal is the same source class as a satellite detection in the independence rule, and it can never
be a strong detection, so NGFS alone reaches Investigate and cannot escalate. NOAA labels the service beta.
"""

import sqlite3
from datetime import datetime

from .confirm import CENTRAL
from .db import iso, parse_iso
from .geo import haversine_km
from .signals import add_signal

WILDLAND = "Possible Wildland Fire"
MIN_SCANS = 2
KIND = "ngfs"


def qualifying(points: list[dict]) -> list[dict]:
    """One dict per qualifying tracked feature: id, lat, lon (latest scan), scans, latest acq time."""
    by_id: dict[str, list[dict]] = {}
    for p in points:
        tid = p.get("feature_tracking_id")
        if tid in (None, "") or p.get("type_description") != WILDLAND or not p.get("acq_date_time"):
            continue
        if not isinstance(p.get("lat"), (int, float)) or not isinstance(p.get("lon"), (int, float)):
            continue
        by_id.setdefault(str(tid), []).append(p)
    out = []
    for tid, rows in by_id.items():
        scans = {r["acq_date_time"] for r in rows}
        if len(scans) < MIN_SCANS:
            continue
        last = max(rows, key=lambda r: r["acq_date_time"])
        out.append({"id": tid, "lat": last["lat"], "lon": last["lon"], "scans": len(scans), "last": last["acq_date_time"]})
    return out


def burn_covers(conn: sqlite3.Connection, lat: float, lon: float, at: datetime, is_sample: int) -> bool:
    day = at.astimezone(CENTRAL).date().isoformat()
    rows = conn.execute(
        "SELECT lat, lon, radius_km FROM burn_notices WHERE burn_date = ? AND is_sample = ?", (day, is_sample)
    ).fetchall()
    return any(haversine_km(lat, lon, b["lat"], b["lon"]) <= b["radius_km"] for b in rows)


def add_ngfs_signals(conn: sqlite3.Connection, points: list[dict], now: datetime, is_sample: bool = False) -> list[int]:
    """Add one signal per newly qualifying feature (never twice for the same tracking id).
    Returns the ids of the events that got a signal, for the caller to re-level."""
    events = []
    for q in qualifying(points):
        source = f"ngfs:{q['id']}"
        if conn.execute("SELECT 1 FROM signals WHERE kind = ? AND source = ?", (KIND, source)).fetchone():
            continue
        if burn_covers(conn, q["lat"], q["lon"], now, int(is_sample)):
            continue
        events.append(add_signal(conn, KIND, q["lat"], q["lon"], iso(now), source, str(q["scans"]), is_sample=is_sample))
    return events
