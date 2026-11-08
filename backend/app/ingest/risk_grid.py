"""Open-Meteo HRRR grid over the bbox: dry-air and wind context. Context only, never model input.

0.6 degree grid, 8 hourly variables, batched. Free, no key, non-commercial use.
"""

import math
from datetime import datetime, timezone

import httpx

from ..config import get_settings
from .feedlib import client_headers, run_feed

URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = ("temperature_2m,relative_humidity_2m,dew_point_2m,vapour_pressure_deficit,"
          "wind_gusts_10m,pressure_msl,wind_speed_10m,wind_direction_10m")
STEP = 0.6
BATCH = 25


def grid_points() -> list[tuple[float, float]]:
    w, s, e, n = get_settings().bbox_tuple
    nx = max(1, math.ceil((e - w) / STEP))
    ny = max(1, math.ceil((n - s) / STEP))
    return [(round(s + (j + 0.5) * (n - s) / ny, 3), round(w + (i + 0.5) * (e - w) / nx, 3))
            for j in range(ny) for i in range(nx)]


def _cell(lat: float, lon: float, h: dict, now: datetime) -> dict | None:
    times = h.get("time") or []
    if not times:
        return None
    stamp = now.strftime("%Y-%m-%dT%H:00")
    idx = times.index(stamp) if stamp in times else min(len(times) - 1, 24)

    def at(key, i=idx):
        v = h.get(key) or []
        return v[i] if 0 <= i < len(v) else None

    gusts = [g for g in (h.get("wind_gusts_10m") or [])[idx:idx + 13] if g is not None]
    p, p3 = at("pressure_msl"), at("pressure_msl", idx - 3)
    return {
        "lat": lat, "lon": lon, "valid_time": times[idx] + "Z",
        "rh": at("relative_humidity_2m"), "dew_c": at("dew_point_2m"), "vpd_kpa": at("vapour_pressure_deficit"),
        "gust_kmh": at("wind_gusts_10m"), "gust_max_12h_kmh": max(gusts) if gusts else None,
        "wind_kmh": at("wind_speed_10m"), "wind_dir_deg": at("wind_direction_10m"),
        "p_hpa": p, "p_change_3h_hpa": round(p - p3, 1) if p is not None and p3 is not None else None,
        "temp_c": at("temperature_2m"),
    }


def parse(payloads: list, pts: list, now: datetime) -> dict:
    cells = []
    for payload, (lat, lon) in zip(payloads, pts):
        c = _cell(lat, lon, payload.get("hourly") or {}, now)
        if c:
            cells.append(c)
    return {"count": len(cells), "cells": cells}


def fetch(now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    pts = grid_points()
    payloads: list = []
    for i in range(0, len(pts), BATCH):
        chunk = pts[i:i + BATCH]
        r = httpx.get(URL, params={
            "latitude": ",".join(str(p[0]) for p in chunk), "longitude": ",".join(str(p[1]) for p in chunk),
            "hourly": HOURLY, "models": "gfs_hrrr", "past_days": 1, "forecast_days": 1,
            "wind_speed_unit": "kmh", "timezone": "GMT"}, headers=client_headers(), timeout=40)
        r.raise_for_status()
        data = r.json()
        payloads.extend(data if isinstance(data, list) else [data])
    return parse(payloads, pts, now)


def poll() -> dict:
    return run_feed("open_meteo", fetch())
