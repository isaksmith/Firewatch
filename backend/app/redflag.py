"""Is a point under an active NWS Red Flag Warning? Read from what the nws_alerts feed stored.

Fails closed: a missing feed, a stale feed, a warning with no polygon (NWS sometimes gives zones only), or an
unparseable time all mean "no". Fire danger is never inferred from weather numbers here.
"""

import sqlite3
from contextvars import ContextVar
from datetime import datetime

from .config import get_settings
from .db import load_snapshot, parse_iso
from .layers import _point_in_ring

# A scenario replay sets this from its explicit "red_flag" field; None means read the live feed.
replay_red_flag: ContextVar[bool | None] = ContextVar("replay_red_flag", default=None)
STALE_INTERVALS = 3  # same cut-off the status page uses for "stale"


def _rings(geometry: dict | None) -> list[list]:
    if not geometry:
        return []
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        return [coords[0]] if coords else []
    if geometry.get("type") == "MultiPolygon":
        return [p[0] for p in coords if p]
    return []


def red_flag_active(conn: sqlite3.Connection, lat: float, lon: float, now: datetime) -> bool:
    if (forced := replay_red_flag.get()) is not None:
        return forced
    snap = load_snapshot(conn, "nws_alerts")
    if snap is None:
        return False
    try:
        age_s = (now - parse_iso(snap["fetched_at"])).total_seconds()
    except (TypeError, ValueError):
        return False
    if age_s > STALE_INTERVALS * get_settings().poll_nws_s:
        return False
    for a in (snap["data"] or {}).get("alerts") or []:
        if a.get("event") != "Red Flag Warning":
            continue
        try:
            if not (parse_iso(a["onset"]) <= now < parse_iso(a["expires"])):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if any(_point_in_ring(lon, lat, r) for r in _rings(a.get("geometry"))):
            return True
    return False
