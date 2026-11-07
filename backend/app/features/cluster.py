"""Group detections into events: one fire should produce one alert."""

import sqlite3
from datetime import timedelta

from ..db import iso, parse_iso, utcnow
from ..geo import KM_PER_DEG_LAT, haversine_km, km_per_deg_lon
from ..layers import place_label

WINDOW = timedelta(hours=12)
BASE_RADIUS_KM = 2.0
# Line faults and texted reports are located to a feeder section or a road, not a pixel.
SIGNAL_RADIUS_KM = 3.0
SIGNAL_WINDOW = timedelta(hours=6)
LOCATING_SIGNALS = ("line_fault", "report", "camera_smoke")


def match_radius_km(scan_km: float | None, track_km: float | None) -> float:
    pixel = max(scan_km or 0.0, track_km or 0.0)
    return max(BASE_RADIUS_KM, 0.5 * pixel + 1.0)


def assign_detection(conn: sqlite3.Connection, det_id: int) -> int:
    """Attach a detection to an existing event (merging events if needed) or create one. Returns event id."""
    d = conn.execute("SELECT * FROM detections WHERE id = ?", (det_id,)).fetchone()
    t = parse_iso(d["acq_time"])
    radius = match_radius_km(d["scan_km"], d["track_km"])
    dlat = radius / KM_PER_DEG_LAT
    dlon = radius / km_per_deg_lon(d["lat"])

    # Join an event if one of its detections is within `radius` and WINDOW of this one. Matching on
    # detections (not the event's whole span) stops a week of neighboring pasture burns chaining into one event.
    lo, hi = iso(t - WINDOW), iso(t + WINDOW)
    rows = conn.execute(
        "SELECT d.event_id, d.lat, d.lon FROM events e JOIN detections d ON d.event_id = e.id "
        "WHERE e.status != 'closed' AND e.is_sample = ? AND e.last_seen >= ? AND e.first_seen <= ? "
        "AND d.acq_time BETWEEN ? AND ? AND d.lat BETWEEN ? AND ? AND d.lon BETWEEN ? AND ?",
        (
            d["is_sample"], lo, hi, lo, hi,
            d["lat"] - dlat, d["lat"] + dlat, d["lon"] - dlon, d["lon"] + dlon,
        ),
    ).fetchall()
    matched = {
        r["event_id"] for r in rows if haversine_km(d["lat"], d["lon"], r["lat"], r["lon"]) <= radius
    }
    matched |= signal_matches(conn, d["lat"], d["lon"], t, d["is_sample"])
    event_id = join_or_create(conn, sorted(matched), d["lat"], d["lon"], d["acq_time"], d["is_sample"])
    conn.execute("UPDATE detections SET event_id = ? WHERE id = ?", (event_id, det_id))
    refresh_event_geometry(conn, event_id)
    return event_id


def signal_matches(conn: sqlite3.Connection, lat: float, lon: float, t, is_sample: int) -> set[int]:
    """Open events with a locating signal within SIGNAL_RADIUS_KM and SIGNAL_WINDOW of (lat, lon, t)."""
    dlat = SIGNAL_RADIUS_KM / KM_PER_DEG_LAT
    dlon = SIGNAL_RADIUS_KM / km_per_deg_lon(lat)
    rows = conn.execute(
        "SELECT s.event_id, s.lat, s.lon FROM signals s JOIN events e ON e.id = s.event_id "
        f"WHERE e.status != 'closed' AND e.is_sample = ? AND s.kind IN ({','.join('?' * len(LOCATING_SIGNALS))}) "
        "AND s.observed_at BETWEEN ? AND ? AND s.lat BETWEEN ? AND ? AND s.lon BETWEEN ? AND ?",
        (
            is_sample, *LOCATING_SIGNALS, iso(t - SIGNAL_WINDOW), iso(t + SIGNAL_WINDOW),
            lat - dlat, lat + dlat, lon - dlon, lon + dlon,
        ),
    ).fetchall()
    return {r["event_id"] for r in rows if haversine_km(lat, lon, r["lat"], r["lon"]) <= SIGNAL_RADIUS_KM}


def join_or_create(conn: sqlite3.Connection, matched: list[int], lat: float, lon: float, at: str, is_sample: int) -> int:
    if not matched:
        cur = conn.execute(
            "INSERT INTO events(lat, lon, first_seen, last_seen, is_sample, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (lat, lon, at, at, is_sample, iso(utcnow())),
        )
        return cur.lastrowid
    keep = matched[0]
    for other in matched[1:]:
        _merge(conn, keep=keep, drop=other)
    return keep


def _merge(conn: sqlite3.Connection, keep: int, drop: int) -> None:
    for table in ("detections", "signals", "messages", "scores", "actions"):
        conn.execute(f"UPDATE {table} SET event_id = ? WHERE event_id = ?", (keep, drop))
    conn.execute("DELETE FROM events WHERE id = ?", (drop,))


def refresh_event_geometry(conn: sqlite3.Connection, event_id: int) -> None:
    """Location from satellite pixels when there are any (FRP-weighted), else from locating signals."""
    rows = conn.execute(
        "SELECT lat, lon, frp_mw, acq_time FROM detections WHERE event_id = ?", (event_id,)
    ).fetchall()
    signals = conn.execute("SELECT kind, lat, lon, observed_at FROM signals WHERE event_id = ?", (event_id,)).fetchall()
    if rows:
        weights = [max(r["frp_mw"] or 0.0, 1.0) for r in rows]
        points = [(r["lat"], r["lon"]) for r in rows]
    else:
        points = [(s["lat"], s["lon"]) for s in signals if s["kind"] in LOCATING_SIGNALS]
        weights = [1.0] * len(points)
    if not points:
        return
    total = sum(weights)
    lat = sum(p[0] * w for p, w in zip(points, weights)) / total
    lon = sum(p[1] * w for p, w in zip(points, weights)) / total
    times = sorted([r["acq_time"] for r in rows] + [s["observed_at"] for s in signals])
    label, town, county = place_label(lat, lon)
    conn.execute(
        "UPDATE events SET lat = ?, lon = ?, first_seen = ?, last_seen = ?, place_label = ?, "
        "nearest_town = ?, county = ?, updated_at = ? WHERE id = ?",
        (lat, lon, times[0], times[-1], label, town, county, iso(utcnow()), event_id),
    )
