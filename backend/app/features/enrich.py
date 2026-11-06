"""Build the feature vector for an event (see docs/DESIGN.md section 4.3)."""

import logging
import math
import sqlite3
from datetime import timedelta
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..db import parse_iso
from ..fire_weather import default_curing, gfdi
from ..geo import haversine_km
from ..layers import in_flint_hills, nearest_line, nearest_static_source, nearest_substation, nearest_town
from ..terrain import TerrainUnavailable, point_elevation_and_slope

log = logging.getLogger(__name__)
CENTRAL = ZoneInfo("America/Chicago")

WEATHER_KEYS = ("wind_kmh", "gust_kmh", "wind_dir_deg", "rh_pct", "temp_c", "precip_72h_mm", "thunder_24h")


def build_features(conn: sqlite3.Connection, event_id: int, weather: dict | None) -> tuple[dict, bool]:
    """Returns (features, degraded). Degraded means weather inputs were missing."""
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    dets = conn.execute(
        "SELECT * FROM detections WHERE event_id = ? ORDER BY acq_time", (event_id,)
    ).fetchall()

    frps = [d["frp_mw"] or 0.0 for d in dets]
    passes: dict[tuple, float] = {}
    for d in dets:
        key = (d["satellite"], d["acq_time"])
        passes[key] = passes.get(key, 0.0) + (d["frp_mw"] or 0.0)
    ordered = sorted(passes.items(), key=lambda kv: kv[0][1])
    first_frp, last_frp = ordered[0][1], ordered[-1][1]

    first_seen = parse_iso(ev["first_seen"])
    last_seen = parse_iso(ev["last_seen"])
    local = first_seen.astimezone(CENTRAL)
    doy = local.timetuple().tm_yday

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
        f["elevation_m"], f["slope_deg"] = point_elevation_and_slope(ev["lat"], ev["lon"])
    except TerrainUnavailable as e:
        log.warning("terrain unavailable for event %s: %s", event_id, e)
        f["elevation_m"], f["slope_deg"] = 0.0, 0.0

    f["dist_line_km"] = nearest_line(ev["lat"], ev["lon"]).distance_km
    f["dist_substation_km"] = nearest_substation(ev["lat"], ev["lon"]).distance_km
    f["dist_town_km"] = nearest_town(ev["lat"], ev["lon"]).distance_km
    f["dist_static_km"] = nearest_static_source(ev["lat"], ev["lon"]).distance_km
    f["in_flint_hills"] = float(in_flint_hills(ev["lat"], ev["lon"]))
    f["nearby_events_24h"] = _nearby_events(conn, ev, last_seen)

    return {k: round(v, 4) if isinstance(v, float) else v for k, v in f.items()}, degraded


def _nearby_events(conn: sqlite3.Connection, ev: sqlite3.Row, at) -> int:
    since = at - timedelta(hours=24)
    rows = conn.execute(
        "SELECT id, lat, lon, last_seen FROM events WHERE id != ? AND is_sample = ?",
        (ev["id"], ev["is_sample"]),
    ).fetchall()
    return sum(
        1
        for r in rows
        if since <= parse_iso(r["last_seen"]) <= at + timedelta(hours=1)
        and haversine_km(ev["lat"], ev["lon"], r["lat"], r["lon"]) <= 25
    )
