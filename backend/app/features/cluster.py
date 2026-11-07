"""Group detections into events: one fire should produce one alert."""

import json
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
LOCATING_SIGNALS = ("line_fault", "report", "camera_smoke", "sensor_smoke")
# A smoke sensor sits downwind of the fire, not on it: it joins events farther out and only places an event
# when nothing else does.
SENSOR_SIGNALS = ("sensor_smoke",)
SENSOR_JOIN_KM = 8.0


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


def signal_matches(
    conn: sqlite3.Connection, lat: float, lon: float, t, is_sample: int, radius_km: float = SIGNAL_RADIUS_KM
) -> set[int]:
    """Open events with a locating signal within radius_km (SENSOR_JOIN_KM of a smoke sensor) and SIGNAL_WINDOW."""
    reach = max(radius_km, SENSOR_JOIN_KM)
    dlat = reach / KM_PER_DEG_LAT
    dlon = reach / km_per_deg_lon(lat)
    rows = conn.execute(
        "SELECT s.event_id, s.kind, s.lat, s.lon FROM signals s JOIN events e ON e.id = s.event_id "
        f"WHERE e.status != 'closed' AND e.is_sample = ? AND s.kind IN ({','.join('?' * len(LOCATING_SIGNALS))}) "
        "AND s.observed_at BETWEEN ? AND ? AND s.lat BETWEEN ? AND ? AND s.lon BETWEEN ? AND ?",
        (
            is_sample, *LOCATING_SIGNALS, iso(t - SIGNAL_WINDOW), iso(t + SIGNAL_WINDOW),
            lat - dlat, lat + dlat, lon - dlon, lon + dlon,
        ),
    ).fetchall()
    return {
        r["event_id"] for r in rows
        if haversine_km(lat, lon, r["lat"], r["lon"]) <= (reach if r["kind"] in SENSOR_SIGNALS else radius_km)
    }


def join_or_create(conn: sqlite3.Connection, matched: list[int], lat: float, lon: float, at: str, is_sample: int) -> int:
    if not matched:
        cur = conn.execute(
            "INSERT INTO events(lat, lon, first_seen, last_seen, is_sample, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (lat, lon, at, at, is_sample, iso(utcnow())),
        )
        return cur.lastrowid
    # A dismissed event is never merged into a live one: drop it from the merge unless nothing else matched.
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT * FROM events WHERE id IN ({','.join('?' * len(matched))})", matched)}
    live = [i for i in matched if i in rows and rows[i]["status"] != "dismissed"]
    ids = live or matched
    keep = max(ids, key=lambda i: (_advanced(rows[i]["response_json"]), -i))
    for other in ids:
        if other != keep:
            _merge(conn, keep=keep, drop=other)
    return keep


STATUS_RANK = {"escalated": 2, "acknowledged": 1, "new": 0}


def _advanced(raw: str | None) -> tuple:
    """How far a response got: page, decision, escalate_at, investigate_at. Bigger is more advanced."""
    r = json.loads(raw) if raw else {}
    return (int(bool(r.get("page_at"))), int(bool(r.get("decision"))), int(bool(r.get("escalate_at"))),
            int(bool(r.get("investigate_at"))))


def _merge_response(a: str | None, b: str | None) -> str | None:
    """Combine two response states (a is keep's). NULL stays NULL: a flag would make the event a page target."""
    if a is None or b is None:
        return a if b is None else b
    x, y = json.loads(a), json.loads(b)
    base, rest = (y, x) if _advanced(b) > _advanced(a) else (x, y)
    for k in ("asked", "responders"):
        seen, out = set(), []
        for v in (base.get(k) or []) + (rest.get(k) or []):
            key = v.get("contact_id") if isinstance(v, dict) else v
            if key not in seen:
                seen.add(key)
                out.append(v)
        if out or k in base or k in rest:
            base[k] = out
    for k in ("escalate_at", "investigate_at"):
        times = [t for t in (x.get(k), y.get(k)) if t]
        if times:
            base[k] = min(times)
    return json.dumps(base)


def _merge(conn: sqlite3.Connection, keep: int, drop: int) -> None:
    for table in ("detections", "signals", "messages", "scores", "actions", "posts"):
        conn.execute(f"UPDATE {table} SET event_id = ? WHERE event_id = ?", (keep, drop))
    k, d = (conn.execute("SELECT * FROM events WHERE id = ?", (i,)).fetchone() for i in (keep, drop))
    if k and d:
        ack = ("ack_level", "ack_by", "ack_at", "ack_until", "ack_mark_det", "ack_mark_sig")
        src = d if (d["ack_until"] or "") > (k["ack_until"] or "") else k
        status = max(k["status"], d["status"], key=lambda s: STATUS_RANK.get(s, -1))
        conn.execute(
            f"UPDATE events SET response_json = ?, status = ?, {', '.join(c + ' = ?' for c in ack)} WHERE id = ?",
            (_merge_response(k["response_json"], d["response_json"]), status, *(src[c] for c in ack), keep),
        )
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
        points = [(s["lat"], s["lon"]) for s in signals if s["kind"] in LOCATING_SIGNALS and s["kind"] not in SENSOR_SIGNALS]
        points = points or [(s["lat"], s["lon"]) for s in signals if s["kind"] in SENSOR_SIGNALS]
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
