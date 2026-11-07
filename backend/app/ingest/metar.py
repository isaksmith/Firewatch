"""Measured surface weather. Primary: aviationweather.gov METAR (US government).
Backup: Iowa Mesonet ASOS currents. Relative humidity is computed from temperature and dew point."""

import math

from ..config import get_settings
from .feedlib import get_json, run_feed

PRIMARY = "https://aviationweather.gov/api/data/metar"
BACKUP = "https://mesonet.agron.iastate.edu/api/1/currents.json"
KT_TO_KMH = 1.852


def rh_from_dewpoint(temp_c: float, dew_c: float) -> float:
    """Magnus formula, result clamped to 0..100."""
    a, b = 17.625, 243.04
    rh = 100 * math.exp(a * dew_c / (b + dew_c) - a * temp_c / (b + temp_c))
    return max(0.0, min(100.0, rh))


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def _station(id_, name, lat, lon, when, temp, dew, wdir, wspd_kmh, gust_kmh, pres, rh=None) -> dict:
    if rh is None and temp is not None and dew is not None:
        rh = rh_from_dewpoint(temp, dew)
    return {
        "id": id_, "name": name, "lat": lat, "lon": lon, "time": when,
        "temp_c": temp, "dew_point_c": dew, "rh_pct": None if rh is None else round(rh, 1),
        "wind_dir_deg": wdir, "wind_kmh": wspd_kmh, "gust_kmh": gust_kmh, "pressure_hpa": pres,
    }


def parse_primary(rows: list) -> list[dict]:
    out = []
    for r in rows or []:
        kt, gk = _num(r.get("wspd")), _num(r.get("wgst"))
        when = r.get("reportTime")
        if when is None and _num(r.get("obsTime")) is not None:
            from datetime import datetime, timezone
            when = datetime.fromtimestamp(r["obsTime"], timezone.utc).isoformat().replace("+00:00", "Z")
        out.append(_station(
            r.get("icaoId"), r.get("name"), _num(r.get("lat")), _num(r.get("lon")), when,
            _num(r.get("temp")), _num(r.get("dewp")), _num(r.get("wdir")),
            None if kt is None else round(kt * KT_TO_KMH, 1), None if gk is None else round(gk * KT_TO_KMH, 1),
            _num(r.get("altim")),
        ))
    return out


def parse_backup(payload: dict) -> list[dict]:
    out = []
    f2c = lambda f: None if f is None else round((f - 32) * 5 / 9, 1)  # noqa: E731
    for r in (payload or {}).get("data") or []:
        sk, gu = _num(r.get("sknt")), _num(r.get("gust"))
        out.append(_station(
            r.get("station"), r.get("name"), _num(r.get("lat")), _num(r.get("lon")), r.get("utc_valid"),
            f2c(_num(r.get("tmpf"))), f2c(_num(r.get("dwpf"))), _num(r.get("drct")),
            None if sk is None else round(sk * KT_TO_KMH, 1), None if gu is None else round(gu * KT_TO_KMH, 1),
            _num(r.get("mslp")) or (None if _num(r.get("alti")) is None else round(r["alti"] * 33.8639, 1)),
            rh=_num(r.get("relh")),
        ))
    return out


def fetch() -> dict:
    w, s, e, n = get_settings().bbox_tuple
    try:
        rows = get_json(PRIMARY, {"bbox": f"{s},{w},{n},{e}", "format": "json"})
        stations, source = parse_primary(rows), "aviationweather.gov"
        if not stations:
            raise ValueError("empty METAR response")
    except Exception:
        stations, source = parse_backup(get_json(BACKUP, {"network": "KS_ASOS"})), "mesonet.agron.iastate.edu"
    stations = [x for x in stations if x["lat"] is not None and x["lon"] is not None]
    return {"count": len(stations), "provider": source, "stations": stations}


def poll() -> dict:
    return run_feed("metar", fetch())
