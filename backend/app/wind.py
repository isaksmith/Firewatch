"""Hourly wind fields for the map's wind layer, matched to what the dispatcher is looking at.

  no alert           live forecast over the Kansas box (Open-Meteo, HRRR), from this hour
  historical sample  the archive's actual wind around the fire, from its first detection
  scenario fire      the scenario's hourly weather (simulated), the same everywhere in a box around the fire

Every field says where it came from (`source`, `kind`), so a simulated or archived wind is never shown as a
live forecast.
"""

import math
import time
from datetime import datetime, timedelta, timezone

import httpx

from .config import get_settings
from .db import utcnow
from .ingest.feedlib import client_headers

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = "wind_speed_10m,wind_direction_10m,wind_gusts_10m"
HOURS = 7  # this hour and the next six, matching the fire forecast on the map
STATE_STEP = 0.6  # degrees, like the dry-air grid
LOCAL_HALF = 1.0  # degrees around a fire
LOCAL_STEP = 0.25
BATCH = 25
CACHE_S = 1800

_cache: dict[tuple, tuple[float, dict]] = {}


def _grid(w: float, s: float, e: float, n: float, step: float) -> list[tuple[float, float]]:
    nx, ny = max(1, math.ceil((e - w) / step)), max(1, math.ceil((n - s) / step))
    return [(round(s + (j + 0.5) * (n - s) / ny, 3), round(w + (i + 0.5) * (e - w) / nx, 3))
            for j in range(ny) for i in range(nx)]


def _fetch(points: list[tuple[float, float]], start: datetime, archive: bool) -> list[dict]:
    """Hourly wind at each point for HOURS hours from `start` (UTC, on the hour)."""
    out = []
    for k in range(0, len(points), BATCH):
        chunk = points[k:k + BATCH]
        params = {"latitude": ",".join(str(p[0]) for p in chunk), "longitude": ",".join(str(p[1]) for p in chunk),
                  "hourly": HOURLY, "wind_speed_unit": "kmh", "timezone": "GMT"}
        if archive:
            params |= {"start_date": start.date().isoformat(), "end_date": (start + timedelta(hours=HOURS)).date().isoformat()}
            url = ARCHIVE_URL
        else:
            params |= {"models": "gfs_hrrr", "forecast_days": 2}
            url = FORECAST_URL
        r = httpx.get(url, params=params, headers=client_headers(), timeout=40)
        r.raise_for_status()
        data = r.json()
        for (lat, lon), d in zip(chunk, data if isinstance(data, list) else [data]):
            h = d["hourly"]
            times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h["time"]]
            want = [start + timedelta(hours=i) for i in range(HOURS)]
            idx = [times.index(t) if t in times else None for t in want]

            def col(key):
                return [None if i is None else h[key][i] for i in idx]

            out.append({"lat": lat, "lon": lon, "wind_kmh": col("wind_speed_10m"),
                        "from_deg": col("wind_direction_10m"), "gust_kmh": col("wind_gusts_10m")})
    return out


def _cached(key: tuple, build) -> dict:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    value = build()
    _cache[key] = (time.monotonic(), value)
    return value


def live_field() -> dict:
    start = utcnow().replace(minute=0, second=0, microsecond=0)
    w, s, e, n = get_settings().bbox_tuple

    def build():
        return {"start": start.isoformat(), "hours": HOURS, "cells": _fetch(_grid(w, s, e, n, STATE_STEP), start, False),
                "source": "Open-Meteo forecast (HRRR), Kansas", "kind": "forecast", "now_hour": 0}

    return _cached(("live", start), build)


def event_field(ev, situation, now_min: float) -> dict:
    """Wind around an alert's fire. `now_min` is minutes since the situation's start (the scenario clock)."""
    lat, lon = situation.ignition.lat, situation.ignition.lon
    t0 = situation.ignition.time.astimezone(timezone.utc)
    now = t0 + timedelta(minutes=now_min)
    start = now.replace(minute=0, second=0, microsecond=0)
    box = (lon - LOCAL_HALF, lat - LOCAL_HALF * 0.8, lon + LOCAL_HALF, lat + LOCAL_HALF * 0.8)

    if ev["sample_slug"] and situation.weather.provenance.kind == "simulated":
        # The scenario's weather is one hourly series: draw it the same everywhere near the fire.
        from .sim.spread import interp_weather

        steps = situation.weather_steps()
        series = [interp_weather(steps, (start - t0).total_seconds() / 60 + 60 * i) for i in range(HOURS)]
        gusts = {h.time.astimezone(timezone.utc): h.gust_kmh for h in situation.weather.hours}
        cells = [{"lat": la, "lon": lo, "wind_kmh": [round(s.wind_kmh, 1) for s in series],
                  "from_deg": [round(s.wind_from_deg) for s in series],
                  "gust_kmh": [gusts.get(start + timedelta(hours=i)) for i in range(HOURS)]}
                 for la, lo in _grid(*box, LOCAL_STEP * 2)]
        return {"start": start.isoformat(), "hours": HOURS, "cells": cells,
                "source": situation.weather.provenance.source, "kind": "simulated", "now_hour": 0}

    archive = start < utcnow() - timedelta(days=5)
    key = ("event", ev["id"], start)

    def build():
        return {"start": start.isoformat(), "hours": HOURS, "cells": _fetch(_grid(*box, LOCAL_STEP), start, archive),
                "source": "Open-Meteo archive (what the wind actually did)" if archive else "Open-Meteo forecast (HRRR)",
                "kind": "archive" if archive else "forecast", "now_hour": 0}

    return _cached(key, build)


