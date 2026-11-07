"""Shared helpers: scenario place file, local time, event loading, road terms."""

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from ..config import DATA_DIR
from ..db import connect, loads
from ..geo import KM_PER_DEG_LAT, bearing_deg, haversine_km, km_per_deg_lon

PLACES_FILE = DATA_DIR / "places" / "cottonwood-creek.json"
KM_PER_MILE = 1.609344
_POINTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_WORDS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


@lru_cache
def scenario() -> dict:
    return json.loads(PLACES_FILE.read_text())


def local_tz(sc: dict | None = None) -> timezone:
    return timezone(timedelta(hours=(sc or scenario()).get("utc_offset_hours", -5)))


def compass8(deg: float, words: bool = False) -> str:
    return (_WORDS if words else _POINTS)[int(((deg % 360) + 22.5) // 45) % 8]


def clock(dt: datetime, tz: timezone | None = None) -> str:
    """12-hour clock without am/pm, e.g. 2:29."""
    d = dt.astimezone(tz or local_tz())
    return f"{d.hour % 12 or 12}:{d.minute:02d}"


def miles(lat1, lon1, lat2, lon2) -> float:
    return haversine_km(lat1, lon1, lat2, lon2) / KM_PER_MILE


def _miles_word(m: float) -> str:
    h = round(m * 2) / 2
    if h == 0.5:
        return "half mi"
    return f"{h:g} mi"


def road_phrase(lat: float, lon: float, with_station: bool = True) -> str:
    """Describe a point in road terms using the scenario grid, e.g. 'Rd K half mi S of CR 12, 11mi NW of station'."""
    sc = scenario()
    roads = sc["roads"]
    ew = [(n, abs(lat - r["lat"]) * KM_PER_DEG_LAT / KM_PER_MILE, lat - r["lat"]) for n, r in roads.items() if "lat" in r]
    ns = [(n, abs(lon - r["lon"]) * km_per_deg_lon(lat) / KM_PER_MILE, lon - r["lon"]) for n, r in roads.items() if "lon" in r]
    # ties go to the road ahead (north / east) of the point
    ew.sort(key=lambda t: (round(t[1], 1), t[2]))
    ns.sort(key=lambda t: (round(t[1], 1), t[2]))
    (ewn, ewd, ews), (nsn, nsd, nss) = ew[0], ns[0]
    st = sc["station"]
    tail = ""
    if with_station:
        d = miles(lat, lon, st["lat"], st["lon"])
        tail = f"{d:.0f}mi {compass8(bearing_deg(st['lat'], st['lon'], lat, lon))} of station"
    if min(ewd, nsd) > 1.5:
        return tail or sc["district"]
    if nsd <= ewd:  # on a north-south road
        if ewd < 0.25:
            core = f"{nsn} & {ewn}"
        else:
            core = f"{nsn} {_miles_word(ewd)} {'N' if ews > 0 else 'S'} of {ewn}"
    else:
        if nsd < 0.25:
            core = f"{ewn} & {nsn}"
        else:
            core = f"{ewn} {_miles_word(nsd)} {'E' if nss > 0 else 'W'} of {nsn}"
    return f"{core}, {tail}" if tail else core


def crossroads(lat: float, lon: float) -> str:
    """Nearest pair of roads, e.g. 'Rd K and CR 12'."""
    roads = scenario()["roads"]
    ew = min((n for n, r in roads.items() if "lat" in r), key=lambda n: (round(abs(lat - roads[n]["lat"]), 3), -roads[n]["lat"]))
    ns = min((n for n, r in roads.items() if "lon" in r), key=lambda n: (round(abs(lon - roads[n]["lon"]), 3), -roads[n]["lon"]))
    return f"{ns} and {ew}"


def load_event(event_id: int) -> dict | None:
    """Read one event, its latest reasons and detections, through db.py helpers."""
    with connect() as conn:
        ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if ev is None:
            return None
        latest = conn.execute(
            "SELECT reasons_json FROM scores WHERE event_id = ? ORDER BY id DESC LIMIT 1", (event_id,)
        ).fetchone()
        dets = [dict(r) for r in conn.execute(
            "SELECT lat, lon, acq_time, source FROM detections WHERE event_id = ? ORDER BY acq_time", (event_id,))]
    out = {k: ev[k] for k in ev.keys() if not k.endswith("_json")}
    out["features"] = loads(ev["features_json"], {})
    out["weather"] = loads(ev["weather_json"], {})
    out["reasons"] = loads(latest["reasons_json"], []) if latest else []
    out["detections"] = dets
    return out


def offset_km(lat: float, lon: float, north_km: float, east_km: float) -> tuple[float, float]:
    return lat + north_km / KM_PER_DEG_LAT, lon + east_km / km_per_deg_lon(lat)

