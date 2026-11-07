"""Shared pieces for the context feeds (alerts, reports, stations, outlooks).

Context feeds never touch the model or scoring. Each poll stores one snapshot
the API serves at /api/feeds/{name}, and marks the source healthy.
"""

import httpx

from ..config import get_settings
from ..db import connect, mark_source, save_snapshot

TIMEOUT = 25


def client_headers() -> dict:
    return {"User-Agent": get_settings().nws_user_agent, "Accept": "application/json"}


def get_json(url: str, params: dict | None = None):
    r = httpx.get(url, params=params, headers=client_headers(), timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def get_text(url: str, params: dict | None = None) -> str:
    r = httpx.get(url, params=params, headers=client_headers(), timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.text


def in_bbox(lon: float, lat: float) -> bool:
    w, s, e, n = get_settings().bbox_tuple
    return w <= lon <= e and s <= lat <= n


def geom_overlaps_bbox(geom: dict | None) -> bool:
    """True when any vertex of a geometry falls inside the AOI, or its bounds span it."""
    if not geom:
        return False
    xs, ys = [], []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c or []:
                walk(x)

    if geom.get("type") == "GeometryCollection":
        return any(geom_overlaps_bbox(g) for g in geom.get("geometries", []))
    walk(geom.get("coordinates"))
    if not xs:
        return False
    w, s, e, n = get_settings().bbox_tuple
    return min(xs) <= e and max(xs) >= w and min(ys) <= n and max(ys) >= s


def run_feed(name: str, data: dict) -> dict:
    """Persist a snapshot and mark the source healthy. Returns a one-line summary."""
    with connect() as conn:
        save_snapshot(conn, name, data)
        mark_source(conn, name, ok=True)
    return {"feed": name, "count": data.get("count")}
