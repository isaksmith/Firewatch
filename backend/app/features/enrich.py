"""Build the feature vector for an event (see docs/DESIGN.md section 4.3)."""

import logging
import math
import sqlite3
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..db import loads, parse_iso
from ..fire_weather import default_curing, gfdi
from ..geo import KM_PER_MILE, haversine_km
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

    frps = [d["frp_mw"] or 0.0 for d in dets] or [0.0]
    passes: dict[tuple, float] = {}
    for d in dets:
        key = (d["satellite"], d["acq_time"])
        passes[key] = passes.get(key, 0.0) + (d["frp_mw"] or 0.0)
    ordered = sorted(passes.items(), key=lambda kv: kv[0][1])
    first_frp, last_frp = (ordered[0][1], ordered[-1][1]) if ordered else (0.0, 0.0)

    first_seen = parse_iso(ev["first_seen"])
    last_seen = parse_iso(ev["last_seen"])
    local = first_seen.astimezone(CENTRAL)
    doy = local.timetuple().tm_yday

    f: dict[str, float] = {
        "frp_max": max(frps),
        "frp_sum": sum(frps),
        "brightness_max": max((d["brightness_k"] or 0.0) for d in dets) if dets else 0.0,
        "conf_high_frac": (sum(d["confidence"] == "high" for d in dets) / len(dets)) if dets else 0.0,
        "pixel_km2_min": min(((d["scan_km"] or 0.375) * (d["track_km"] or 0.375)) for d in dets) if dets else 0.14,
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
    f["red_flag"] = float(bool(w.get("red_flag")))
    f.update(_signal_features(conn, ev, dets, w))

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


BURN_RADIUS_KM = 1.5       # a detection this close to a logged burn, in its window, is that burn
FAULT_RADIUS_KM = 2.0      # a satellite look this close and soon after a fault corroborates it
BURN_LOG_COVERS_KM = 25    # the burn log only says "none here" for places it plausibly covers


def _clock(iso_s: str, tz) -> str:
    dt = parse_iso(iso_s).astimezone(tz)
    return f"{dt.hour % 12 or 12}:{dt.minute:02d}"


def _signal_features(conn: sqlite3.Connection, ev: sqlite3.Row, dets: list, w: dict) -> dict:
    """Line faults, public reports, the burn log and plain-word clock times. Local time comes from
    the weather record's utc_offset_hours when it has one, otherwise US Central."""
    tz = timezone(timedelta(hours=w["utc_offset_hours"])) if w.get("utc_offset_hours") is not None else CENTRAL
    sigs = conn.execute("SELECT * FROM signals WHERE event_id = ? ORDER BY time", (ev["id"],)).fetchall()
    faults = [s for s in sigs if s["kind"] == "line_fault"]
    reports = [s for s in sigs if s["kind"] == "report"]
    burns = conn.execute("SELECT * FROM burns WHERE is_sample = ?", (ev["is_sample"],)).fetchall()
    ctx: dict = {}
    out: dict = {
        "line_fault": float(bool(faults)), "fault_corroborated": 0.0, "n_reports": len(reports),
        "n_looks": 0, "looks_growing": 0.0, "burn_match": 0.0, "no_burn_near": 0.0,
    }

    look_times = sorted({d["acq_time"] for d in dets})
    out["n_looks"] = len(look_times)
    ctx["look_clocks"] = [_clock(t, tz) for t in look_times]
    passes: dict[tuple, float] = {}
    for d in dets:
        passes[(d["satellite"], d["acq_time"])] = passes.get((d["satellite"], d["acq_time"]), 0.0) + (d["frp_mw"] or 0.0)
    by_time = [v for _, v in sorted(passes.items(), key=lambda kv: kv[0][1])]
    out["looks_growing"] = float(len(look_times) >= 2 and by_time[-1] > by_time[0] * 1.05)

    def nearest_ref_km(s) -> float | None:
        refs = [(d["lat"], d["lon"]) for d in dets]
        return min((haversine_km(s["lat"], s["lon"], a, b) for a, b in refs), default=None)

    if faults:
        fa = faults[0]
        ft = parse_iso(fa["time"])
        d_km = nearest_ref_km(fa)
        out["fault_corroborated"] = float(any(
            haversine_km(fa["lat"], fa["lon"], d["lat"], d["lon"]) <= FAULT_RADIUS_KM
            and -timedelta(minutes=5) <= parse_iso(d["acq_time"]) - ft <= timedelta(minutes=15)
            for d in dets
        ))
        ctx["fault"] = {
            "circuit": loads(fa["payload_json"], {}).get("circuit", "power line"),
            "clock": _clock(fa["time"], tz),
            "miles": round(d_km / KM_PER_MILE, 1) if d_km is not None else None,
        }
    if reports:
        r = reports[0]
        refs = [(d["lat"], d["lon"]) for d in dets] + [(s["lat"], s["lon"]) for s in faults]
        d_km = min((haversine_km(r["lat"], r["lon"], a, b) for a, b in refs), default=None)
        ctx["report"] = {
            "clock": _clock(r["time"], tz),
            "miles": round(d_km / KM_PER_MILE, 1) if d_km is not None else None,
        }

    pts = [(d["lat"], d["lon"]) for d in dets] + [(s["lat"], s["lon"]) for s in sigs] or [(ev["lat"], ev["lon"])]
    near_any = near_covered = False
    for b in burns:
        d_km = min(haversine_km(b["lat"], b["lon"], a, c) for a, c in pts)
        # A burn only counts toward "a burn was called in near here" if its window overlaps this alert's time.
        if parse_iso(b["start"]) <= parse_iso(ev["last_seen"]) and parse_iso(b["end"]) >= parse_iso(ev["first_seen"]):
            near_covered = near_covered or d_km <= BURN_LOG_COVERS_KM
            near_any = near_any or d_km <= BURN_RADIUS_KM
        if out["burn_match"] or out.get("burn_escape"):
            continue
        for d in dets:
            if (
                haversine_km(b["lat"], b["lon"], d["lat"], d["lon"]) <= BURN_RADIUS_KM
                and parse_iso(b["start"]) <= parse_iso(d["acq_time"]) <= parse_iso(b["end"])
            ):
                ctx["burn"] = {"called_in_clock": _clock(b["called_in"], tz), "label": b["label"], "caller": b["caller"]}
                # A burn that is getting away: heat at least doubling across looks, heat spread well past the
                # burn point, or heat outside the window the burner gave. Then the log no longer explains it.
                grew = len(look_times) >= 2 and by_time[0] > 0 and by_time[-1] >= 2 * by_time[0]
                spread = any(haversine_km(b["lat"], b["lon"], x["lat"], x["lon"]) > BURN_RADIUS_KM for x in dets)
                outside = any(not (parse_iso(b["start"]) <= parse_iso(x["acq_time"]) <= parse_iso(b["end"])) for x in dets)
                if grew or spread or outside:
                    out["burn_escape"] = 1.0
                else:
                    out["burn_match"] = 1.0
                break
    # "No burn called in" only means something where the log covers the area and there is other evidence.
    if near_covered and not near_any and (faults or reports or w.get("red_flag")):
        out["no_burn_near"] = 1.0

    out["ctx"] = ctx
    return out
