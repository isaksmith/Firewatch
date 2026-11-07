"""Open-Meteo weather for an event location and time (no API key)."""

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import httpx

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,weather_code"


@lru_cache(maxsize=512)
def _hourly(lat_r: float, lon_r: float, day: str, archive: bool) -> dict:
    params = {
        "latitude": lat_r,
        "longitude": lon_r,
        "hourly": HOURLY,
        "wind_speed_unit": "kmh",
        "timezone": "GMT",
    }
    if archive:
        start = (datetime.fromisoformat(day) - timedelta(days=3)).date().isoformat()
        params |= {"start_date": start, "end_date": day}
        url = ARCHIVE_URL
    else:
        params |= {"past_days": 3, "forecast_days": 2}
        url = FORECAST_URL
    resp = httpx.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()["hourly"]


def weather_at(lat: float, lon: float, when: datetime) -> dict:
    """Weather features at the hour nearest `when`. Raises httpx.HTTPError on failure."""
    when = when.astimezone(timezone.utc)
    archive = when < datetime.now(timezone.utc) - timedelta(days=5)
    h = _hourly(round(lat, 1), round(lon, 1), when.date().isoformat(), archive)
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h["time"]]
    idx = min(range(len(times)), key=lambda i: abs((times[i] - when).total_seconds()))

    def window(key: str, hours: int) -> list[float]:
        return [v for v in h[key][max(0, idx - hours + 1): idx + 1] if v is not None]

    return {
        "wind_kmh": h["wind_speed_10m"][idx],
        "gust_kmh": h["wind_gusts_10m"][idx],
        "wind_dir_deg": h["wind_direction_10m"][idx],
        "rh_pct": h["relative_humidity_2m"][idx],
        "temp_c": h["temperature_2m"][idx],
        "precip_72h_mm": round(sum(window("precipitation", 72)), 1),
        "thunder_24h": int(any(95 <= c <= 99 for c in window("weather_code", 24))),
        "source": "open-meteo",
        "valid_time": h["time"][idx] + "Z",
    }


def weather_series(lat: float, lon: float, start: datetime, hours: int) -> tuple[list[dict], str]:
    """Hourly weather from `start` for `hours` hours, as Situation WeatherHour dicts, plus "forecast" or "archive".

    Raises httpx.HTTPError on failure.
    """
    start = start.astimezone(timezone.utc)
    end = start + timedelta(hours=hours)
    archive = end < datetime.now(timezone.utc) - timedelta(days=5)
    days = sorted({start.date().isoformat(), end.date().isoformat()})
    out = []
    for day in days:
        h = _hourly(round(lat, 2), round(lon, 2), day, archive)
        for i, t in enumerate(h["time"]):
            ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            if start <= ts <= end and h["wind_speed_10m"][i] is not None and all(
                o["time"] != ts for o in out
            ):
                out.append({
                    "time": ts,
                    "wind_kmh": h["wind_speed_10m"][i],
                    "wind_from_deg": h["wind_direction_10m"][i],
                    "temp_c": h["temperature_2m"][i],
                    "rh_pct": h["relative_humidity_2m"][i],
                    "gust_kmh": h["wind_gusts_10m"][i],
                })
    return sorted(out, key=lambda o: o["time"]), "archive" if archive else "forecast"
