"""Non-satellite evidence (line faults, texted reports, neighbor replies) attached to events.

See docs/DESIGN.md section 4.5.
"""

import sqlite3

from .db import iso, parse_iso, utcnow
from .features.cluster import (
    LOCATING_SIGNALS,
    SENSOR_JOIN_KM,
    SENSOR_SIGNALS,
    SIGNAL_RADIUS_KM,
    SIGNAL_WINDOW,
    join_or_create,
    refresh_event_geometry,
    signal_matches,
)
from .geo import KM_PER_DEG_LAT, haversine_km, km_per_deg_lon

KINDS = ("line_fault", "report", "neighbor_reply", "camera_smoke", "sensor_smoke")


def add_signal(
    conn: sqlite3.Connection,
    kind: str,
    lat: float,
    lon: float,
    observed_at: str,
    source: str,
    value: str | None = None,
    contact_id: int | None = None,
    is_sample: bool = False,
    event_id: int | None = None,
    join_radius_km: float | None = None,
) -> int:
    """Store a signal and attach it to an event; returns the event id.

    Neighbor replies pass the `event_id` they answer. Locating signals join an open event with a detection
    or signal within 3 km and 6 h, or open a new event. `join_radius_km` overrides that radius (estimated
    reports pass ESTIMATE_JOIN_KM).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown signal kind {kind!r}")
    if event_id is None:
        if kind not in LOCATING_SIGNALS:
            raise ValueError(f"{kind} needs the event it refers to")
        flag = int(is_sample)
        radius = join_radius_km or (SENSOR_JOIN_KM if kind in SENSOR_SIGNALS else SIGNAL_RADIUS_KM)
        matched = signal_matches(conn, lat, lon, parse_iso(observed_at), flag, radius)
        matched |= _detection_matches(conn, lat, lon, observed_at, flag, radius)
        event_id = join_or_create(conn, sorted(matched), lat, lon, observed_at, flag)
    conn.execute(
        "INSERT INTO signals(event_id, kind, lat, lon, observed_at, source, value, contact_id, is_sample, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, kind, lat, lon, observed_at, source, value, contact_id, int(is_sample), iso(utcnow())),
    )
    refresh_event_geometry(conn, event_id)
    return event_id


def _detection_matches(
    conn: sqlite3.Connection, lat: float, lon: float, at: str, is_sample: int, radius_km: float = SIGNAL_RADIUS_KM
) -> set[int]:
    t = parse_iso(at)
    dlat, dlon = radius_km / KM_PER_DEG_LAT, radius_km / km_per_deg_lon(lat)
    rows = conn.execute(
        "SELECT d.event_id, d.lat, d.lon FROM detections d JOIN events e ON e.id = d.event_id "
        "WHERE e.status != 'closed' AND e.is_sample = ? AND d.acq_time BETWEEN ? AND ? "
        "AND d.lat BETWEEN ? AND ? AND d.lon BETWEEN ? AND ?",
        (is_sample, iso(t - SIGNAL_WINDOW), iso(t + SIGNAL_WINDOW), lat - dlat, lat + dlat, lon - dlon, lon + dlon),
    ).fetchall()
    return {r["event_id"] for r in rows if haversine_km(lat, lon, r["lat"], r["lon"]) <= radius_km}
