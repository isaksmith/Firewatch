"""Who and what is in the fire's path, with arrival times.

The spread starts at the event's FIRST signal (line fault if the event carries one, else the earliest
detection, else first_seen at the event point), not at the latest update. It runs from then through
"now" plus 60 minutes (90 for "later"). Places the footprint already covers by "now" are "reached".
"now" is the real clock for live events and last_seen for sample events (see clock_now).

Uses the existing spread model (app.sim.spread). That model returns isochrones every 5 minutes, so an
arrival time is the first isochrone that contains the place: it is rounded UP to the next 5 minutes (a place within 150 m of an isochrone edge counts as reached).
Terrain is switched off so the answer is the same offline. If the model cannot run, a head-speed
fallback (straight-line distance divided by head speed, inside the downwind ellipse) is used and
flagged with source "fallback".
"""

import math
from datetime import datetime, timedelta, timezone

from ..fire_weather import default_curing, head_ros_kmh, length_to_breadth
from ..db import parse_iso
from ..geo import KM_PER_DEG_LAT, bearing_deg, km_per_deg_lon, point_segment_km
from ..sim.spread import SpreadInput, simulate
from .common import KM_PER_MILE, clock, compass8, local_tz, miles

LATER_MIN = 60
MAX_MIN = 90


def start_of(event: dict) -> tuple[datetime, float, float]:
    """(start time, lat, lon) of the first signal."""
    ft = event.get("line_fault")
    if ft and ft.get("time"):
        return ft["time"], ft["lat"], ft["lon"]
    dets = sorted(event.get("detections") or [], key=lambda d: d["acq_time"])
    if dets:
        d = dets[0]
        t = parse_iso(d["acq_time"])
        first = parse_iso(event["first_seen"]) if event.get("first_seen") else t
        return min(t, first), d["lat"], d["lon"]
    t = parse_iso(event["first_seen"]) if event.get("first_seen") else datetime.now(timezone.utc)
    return t, event["lat"], event["lon"]


def clock_now(event: dict) -> datetime:
    """Real time for live events; the event's last_seen for sample events so the scenario clock stays coherent."""
    if event.get("is_sample") and event.get("last_seen"):
        return parse_iso(event["last_seen"])
    return datetime.now(timezone.utc)


def event_inputs(event: dict, start: datetime, lat: float, lon: float, minutes: int) -> SpreadInput:
    f = event.get("features") or {}
    return SpreadInput(
        lat=lat, lon=lon,
        wind_kmh=f.get("wind_kmh", 20.0), wind_from_deg=f.get("wind_dir_deg", 180.0),
        temp_c=f.get("temp_c", 15.0), rh_pct=f.get("rh_pct", 50.0),
        curing_pct=f.get("curing_pct", default_curing(start.month)),
        minutes=minutes, use_terrain=False,
    )


MAX_AGE_MIN = 240  # a fire older than 4 h is simulated as 4 h old, so a stale event cannot run a huge grid


def _bounded_start(event: dict, now: datetime) -> tuple[datetime, float, float]:
    start, lat, lon = start_of(event)
    if (now - start).total_seconds() > MAX_AGE_MIN * 60:
        start = now - timedelta(minutes=MAX_AGE_MIN)
    return start, lat, lon


def _age_min(start: datetime, now: datetime) -> int:
    return max(0, math.ceil((now - start).total_seconds() / 60))


def _horizon(age: int, extra: int) -> int:
    return int(math.ceil((age + extra) / 5) * 5)


def _in_ring(lat: float, lon: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


SNAP_KM = 0.15  # the model grid cell is about 130 m, so early isochrones are slivers; accept a place this close to the edge


def _near_ring(lat: float, lon: float, ring: list) -> bool:
    return _in_ring(lat, lon, ring) or any(
        point_segment_km(lat, lon, a, b) <= SNAP_KM for a, b in zip(ring, ring[1:]))


def _eta_from_isochrones(iso: dict, lat: float, lon: float) -> int | None:
    for feat in iso["features"]:  # ascending minutes
        for poly in feat["geometry"]["coordinates"]:
            if _near_ring(lat, lon, poly[0]):
                return feat["properties"]["minutes"]
    return None


def _fallback_eta(inp: SpreadInput, lat: float, lon: float) -> float | None:
    ros = head_ros_kmh(inp.wind_kmh, inp.temp_c, inp.rh_pct, inp.curing_pct)
    ecc = math.sqrt(1 - 1 / length_to_breadth(inp.wind_kmh) ** 2)
    north = (lat - inp.lat) * KM_PER_DEG_LAT
    east = (lon - inp.lon) * km_per_deg_lon(inp.lat)
    down = math.radians((inp.wind_from_deg + 180) % 360)
    dist = math.hypot(north, east)
    cos_t = (north * math.cos(down) + east * math.sin(down)) / dist if dist else 1.0
    speed = ros * (1 - ecc) / (1 - ecc * cos_t)
    return dist / speed * 60 if speed > 0 else None


def footprint(event: dict, minutes: int = 60, now: datetime | None = None) -> dict | None:
    """The fire's outline `minutes` after `now` (GeoJSON feature), simulated from the first signal."""
    now = now or clock_now(event)
    start, lat, lon = _bounded_start(event, now)
    target = _horizon(_age_min(start, now), minutes)
    try:
        res = simulate(event_inputs(event, start, lat, lon, target))
    except Exception:
        return None
    for feat in res["isochrones"]["features"]:
        if feat["properties"]["minutes"] == target:
            return feat
    return None


def in_path(event: dict, places: list[dict], now: datetime) -> list[dict]:
    """Places the fire has reached or will reach within 90 minutes of `now`, sorted by arrival.

    Row: id, label, kind, family, lat, lon, status ("reached"|"coming"), arrival_local (clock time the
    fire gets there), eta_min (minutes from now; None when reached), eta_local (same as arrival_local),
    reached_local (when reached), later (coming but more than 60 min away), miles_from_fire,
    fire_dir_from_place (compass word for the direction FROM the place TO the fire), source.
    """
    start, slat, slon = _bounded_start(event, now)
    age = _age_min(start, now)
    inp = event_inputs(event, start, slat, slon, _horizon(age, MAX_MIN))
    iso, source = None, "fallback"
    try:
        iso = simulate(inp)["isochrones"]
        source = "spread_model"
    except Exception:
        pass
    tz = local_tz()
    out = []
    for p in places:
        if iso is not None:
            eta = _eta_from_isochrones(iso, p["lat"], p["lon"])
        else:
            eta = _fallback_eta(inp, p["lat"], p["lon"])
            eta = math.ceil(eta / 5) * 5 if eta is not None else None
        if eta is None or eta > age + MAX_MIN:
            continue
        arrival = start + timedelta(minutes=eta)
        reached = arrival <= now
        to_go = None if reached else max(1, math.ceil((arrival - now).total_seconds() / 60))
        if to_go is not None and to_go > MAX_MIN:
            continue
        out.append({
            "id": p.get("id"), "label": p.get("label"), "kind": p.get("kind"),
            "family": p.get("family"), "lat": p["lat"], "lon": p["lon"],
            "status": "reached" if reached else "coming",
            "arrival_local": clock(arrival, tz), "eta_local": clock(arrival, tz),
            "reached_local": clock(arrival, tz) if reached else None,
            "eta_min": to_go, "later": bool(to_go and to_go > LATER_MIN),
            "miles_from_fire": round(miles(p["lat"], p["lon"], slat, slon), 1),
            "fire_dir_from_place": compass8(bearing_deg(p["lat"], p["lon"], slat, slon), words=True),
            "source": source, "_arrival": arrival,
        })
    out.sort(key=lambda r: r["_arrival"])
    for r in out:
        del r["_arrival"]
    return out
