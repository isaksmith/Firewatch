"""Group detections into events: one fire should produce one alert."""

import sqlite3
from datetime import timedelta

from ..db import iso, parse_iso, utcnow
from ..geo import haversine_km
from ..layers import place_label

WINDOW = timedelta(hours=12)
BASE_RADIUS_KM = 2.0


def match_radius_km(scan_km: float | None, track_km: float | None) -> float:
    pixel = max(scan_km or 0.0, track_km or 0.0)
    return max(BASE_RADIUS_KM, 0.5 * pixel + 1.0)


def assign_detection(conn: sqlite3.Connection, det_id: int) -> int:
    """Attach a detection to an existing event (merging events if needed) or create one. Returns event id."""
    d = conn.execute("SELECT * FROM detections WHERE id = ?", (det_id,)).fetchone()
    t = parse_iso(d["acq_time"])
    radius = match_radius_km(d["scan_km"], d["track_km"])

    candidates = conn.execute(
        "SELECT id, first_seen, last_seen FROM events WHERE status != 'closed' AND is_sample = ?",
        (d["is_sample"],),
    ).fetchall()
    matched: list[int] = []
    for ev in candidates:
        if not (parse_iso(ev["first_seen"]) - WINDOW <= t <= parse_iso(ev["last_seen"]) + WINDOW):
            continue
        rows = conn.execute(
            "SELECT lat, lon FROM detections WHERE event_id = ?", (ev["id"],)
        ).fetchall()
        if any(haversine_km(d["lat"], d["lon"], r["lat"], r["lon"]) <= radius for r in rows):
            matched.append(ev["id"])

    if not matched:
        now = iso(utcnow())
        cur = conn.execute(
            "INSERT INTO events(lat, lon, first_seen, last_seen, is_sample, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (d["lat"], d["lon"], d["acq_time"], d["acq_time"], d["is_sample"], now),
        )
        event_id = cur.lastrowid
    else:
        event_id = min(matched)
        for other in matched:
            if other != event_id:
                _merge(conn, keep=event_id, drop=other)

    conn.execute("UPDATE detections SET event_id = ? WHERE id = ?", (event_id, det_id))
    refresh_event_geometry(conn, event_id)
    return event_id


def _merge(conn: sqlite3.Connection, keep: int, drop: int) -> None:
    for table in ("detections", "scores", "actions"):
        conn.execute(f"UPDATE {table} SET event_id = ? WHERE event_id = ?", (keep, drop))
    conn.execute("DELETE FROM events WHERE id = ?", (drop,))


def refresh_event_geometry(conn: sqlite3.Connection, event_id: int) -> None:
    rows = conn.execute(
        "SELECT lat, lon, frp_mw, acq_time FROM detections WHERE event_id = ?", (event_id,)
    ).fetchall()
    weights = [max(r["frp_mw"] or 0.0, 1.0) for r in rows]
    total = sum(weights)
    lat = sum(r["lat"] * w for r, w in zip(rows, weights)) / total
    lon = sum(r["lon"] * w for r, w in zip(rows, weights)) / total
    times = sorted(r["acq_time"] for r in rows)
    label, town, county = place_label(lat, lon)
    conn.execute(
        "UPDATE events SET lat = ?, lon = ?, first_seen = ?, last_seen = ?, place_label = ?, "
        "nearest_town = ?, county = ?, updated_at = ? WHERE id = ?",
        (lat, lon, times[0], times[-1], label, town, county, iso(utcnow()), event_id),
    )
