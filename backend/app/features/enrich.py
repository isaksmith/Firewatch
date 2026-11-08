"""Build the feature vector for an event (see docs/DESIGN.md section 4.3)."""

import logging
import math
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..db import iso, parse_iso
from ..fire_weather import default_curing, gfdi
from ..geo import KM_PER_DEG_LAT, haversine_km, km_per_deg_lon
from ..layers import (
    in_flint_hills,
    nearest_line,
    nearest_static_source,
    nearest_substation,
    nearest_town,
)
from ..terrain import TerrainUnavailable, point_elevation_and_slope

log = logging.getLogger(__name__)
CENTRAL = ZoneInfo("America/Chicago")

WEATHER_KEYS = ("wind_kmh", "gust_kmh", "wind_dir_deg", "rh_pct", "temp_c", "precip_72h_mm", "thunder_24h")


def build_features(
    conn: sqlite3.Connection, event_id: int, weather: dict | None, as_of: datetime | None = None
) -> tuple[dict, bool]:
    """Returns (features, degraded). Degraded means weather inputs were missing.

    `as_of` restricts the event to detections seen by that time, so training can reproduce what live
    scoring would have seen after each pass. Live scoring leaves it None.
    """
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    dets = conn.execute(
        "SELECT * FROM detections WHERE event_id = ? AND acq_time <= ? ORDER BY acq_time",
        (event_id, iso(as_of) if as_of else "9999"),
    ).fetchall()
    if not dets:
        raise ValueError(f"event {event_id} has no detections as of {as_of}")
    lat, lon = ev["lat"], ev["lon"]
    if as_of is not None:
        weights = [max(d["frp_mw"] or 0.0, 1.0) for d in dets]
        lat = sum(d["lat"] * w for d, w in zip(dets, weights)) / sum(weights)
        lon = sum(d["lon"] * w for d, w in zip(dets, weights)) / sum(weights)

    frps = [d["frp_mw"] or 0.0 for d in dets]
    passes: dict[tuple, float] = {}
    for d in dets:
        key = (d["satellite"], d["acq_time"])
        passes[key] = passes.get(key, 0.0) + (d["frp_mw"] or 0.0)
    ordered = sorted(passes.items(), key=lambda kv: kv[0][1])
    first_frp, last_frp = ordered[0][1], ordered[-1][1]

    first_seen = parse_iso(dets[0]["acq_time"])
    last_seen = parse_iso(dets[-1]["acq_time"])

    f: dict[str, float] = {
        "frp_max": max(frps),
        "frp_sum": sum(frps),
        "brightness_max": max((d["brightness_k"] or 0.0) for d in dets),
        "conf_high_frac": sum(d["confidence"] == "high" for d in dets) / len(dets),
        "pixel_km2_min": min(((d["scan_km"] or 0.375) * (d["track_km"] or 0.375)) for d in dets),
        "n_detections": len(dets),
        "n_satellites": len({d["satellite"] for d in dets}),
        "minutes_active": (last_seen - first_seen).total_seconds() / 60,
        "frp_growth": (last_frp / first_frp) if first_frp > 0 and len(ordered) > 1 else 1.0,
        "is_night": float(any(d["daynight"] == "N" for d in dets)),
    }
    ctx, degraded = context_features(conn, event_id, ev["is_sample"], lat, lon, first_seen, last_seen, weather)
    f.update(ctx)
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in f.items()}, degraded


def context_features(
    conn: sqlite3.Connection,
    event_id: int,
    is_sample: int,
    lat: float,
    lon: float,
    first_seen: datetime,
    last_seen: datetime,
    weather: dict | None,
) -> tuple[dict, bool]:
    """Time, weather, fire danger, terrain, and infrastructure context. Needs no satellite pixels, so events
    opened by a line fault or a text get it too."""
    local = first_seen.astimezone(CENTRAL)
    doy = local.timetuple().tm_yday
    f: dict[str, float] = {
        "local_hour": local.hour,
        "month": local.month,
        "doy_sin": math.sin(2 * math.pi * doy / 365.25),
        "doy_cos": math.cos(2 * math.pi * doy / 365.25),
    }

    degraded = False
    w = weather or {}
    for key in ("wind_kmh", "wind_dir_deg", "rh_pct", "temp_c"):
        if w.get(key) is None:
            degraded = True
    f["wind_kmh"] = w.get("wind_kmh") or 0.0
    f["gust_kmh"] = w.get("gust_kmh") if w.get("gust_kmh") is not None else f["wind_kmh"] * 1.5
    f["wind_dir_deg"] = w.get("wind_dir_deg") or 0.0
    f["rh_pct"] = w.get("rh_pct") if w.get("rh_pct") is not None else 50.0
    f["temp_c"] = w.get("temp_c") if w.get("temp_c") is not None else 15.0
    f["precip_72h_mm"] = w.get("precip_72h_mm") or 0.0
    f["thunder_24h"] = float(w.get("thunder_24h") or 0)
    f["curing_pct"] = default_curing(local.month, get_settings().curing_pct_override)
    f["gfdi"] = gfdi(f["curing_pct"], f["temp_c"], f["rh_pct"], f["wind_kmh"])

    try:
        f["elevation_m"], f["slope_deg"] = point_elevation_and_slope(lat, lon)
    except TerrainUnavailable as e:
        log.warning("terrain unavailable for event %s: %s", event_id, e)
        f["elevation_m"], f["slope_deg"] = 0.0, 0.0

    f["dist_line_km"] = nearest_line(lat, lon).distance_km
    f["dist_substation_km"] = nearest_substation(lat, lon).distance_km
    f["dist_town_km"] = nearest_town(lat, lon).distance_km
    f["dist_static_km"] = nearest_static_source(lat, lon).distance_km
    f["in_flint_hills"] = float(in_flint_hills(lat, lon))
    f["nearby_events_24h"] = _nearby_events(conn, event_id, is_sample, lat, lon, last_seen)
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in f.items()}, degraded


NEARBY_RADIUS_KM = 25.0


def _nearby_events(conn: sqlite3.Connection, event_id: int, is_sample: int, lat: float, lon: float, at: datetime) -> int:
    """Other events active within 25 km during the 24 h before `at`."""
    dlat = NEARBY_RADIUS_KM / KM_PER_DEG_LAT
    dlon = NEARBY_RADIUS_KM / km_per_deg_lon(lat)
    rows = conn.execute(
        "SELECT lat, lon FROM events WHERE id != ? AND is_sample = ? AND first_seen <= ? AND last_seen >= ? "
        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (
            event_id, is_sample, iso(at + timedelta(hours=1)), iso(at - timedelta(hours=24)),
            lat - dlat, lat + dlat, lon - dlon, lon + dlon,
        ),
    ).fetchall()
    return sum(1 for r in rows if haversine_km(lat, lon, r["lat"], r["lon"]) <= NEARBY_RADIUS_KM)
