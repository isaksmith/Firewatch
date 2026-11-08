"""Fire-weather climatology for a point, for the region planner (docs/DESIGN.md section 5.9).

Ten years of hourly ERA5 reanalysis from the Open-Meteo archive, reduced to what sensor siting needs:
which way the wind blows when grass fire danger is High or worse, when in the year that happens,
how much winter and fire-season sun a solar node gets, and how often it's too cold or foggy for the
particulate sensor. Summaries are cached per 0.25-degree ERA5 cell in data/climate/, and the cache
for the demo district is committed so planning works offline.
"""

import json
import math
from datetime import date

import httpx
import numpy as np

from .config import DATA_DIR
from .fire_weather import default_curing, gfdi
from .geo import COMPASS_16

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
CLIMATE_DIR = DATA_DIR / "climate"
YEARS = (2016, 2025)
FIRE_GFDI = 12.0  # High: the same bar a line fault has to clear to count as a fire source
VERY_HIGH_GFDI = 25.0
FIRE_SEASON_MONTHS = (2, 3, 4)
PM_MIN_C = -10.0  # PMSA003I operating minimum


class ClimateUnavailable(Exception):
    pass


def _cell(lat: float, lon: float) -> tuple[float, float]:
    return round(lat * 4) / 4, round(lon * 4) / 4


def _path(lat: float, lon: float):
    clat, clon = _cell(lat, lon)
    return CLIMATE_DIR / f"{clat:.2f}_{clon:.2f}.json"


def climatology(lat: float, lon: float, fetch: bool = True) -> dict:
    path = _path(lat, lon)
    if path.exists():
        return json.loads(path.read_text())
    if not fetch:
        raise ClimateUnavailable(f"no cached climatology for {path.stem}")
    clat, clon = _cell(lat, lon)
    try:
        resp = httpx.get(
            ARCHIVE_URL,
            params={
                "latitude": clat, "longitude": clon,
                "start_date": f"{YEARS[0]}-01-01", "end_date": f"{YEARS[1]}-12-31",
                "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
                "daily": "shortwave_radiation_sum,temperature_2m_min",
                "timezone": "America/Chicago", "wind_speed_unit": "kmh",
            },
            timeout=60,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ClimateUnavailable(str(e)) from e
    summary = summarize(resp.json(), clat, clon)
    CLIMATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=1))
    return summary


def _lobe(shares: np.ndarray, center: int) -> float:
    return float(sum(shares[(center + k) % 16] for k in range(-2, 3)))


def wind_modes(rose: list[float]) -> list[dict]:
    """The main fire-wind direction and, if there is one, a second one at least 67.5 degrees away."""
    shares = np.asarray(rose)
    smooth = np.array([shares[(i - 1) % 16] + shares[i] + shares[(i + 1) % 16] for i in range(16)])
    first = int(smooth.argmax())
    modes = [{"from_deg": first * 22.5, "from": COMPASS_16[first], "share": round(_lobe(shares, first), 3)}]
    far = [i for i in range(16) if min((i - first) % 16, (first - i) % 16) >= 4]
    second = max(far, key=lambda i: smooth[i])
    share = _lobe(shares, second)
    if share >= 0.1:
        modes.append({"from_deg": second * 22.5, "from": COMPASS_16[second], "share": round(share, 3)})
    return modes


def summarize(raw: dict, lat: float, lon: float) -> dict:
    h = raw["hourly"]
    years = YEARS[1] - YEARS[0] + 1
    rose = np.zeros(16)
    by_month = np.zeros(12)
    speeds, very_high, fog, fog_n = [], 0, 0, 0
    for t, temp, rh, wind, wdir in zip(
        h["time"], h["temperature_2m"], h["relative_humidity_2m"], h["wind_speed_10m"], h["wind_direction_10m"]
    ):
        if None in (temp, rh, wind, wdir):
            continue
        month, hour = int(t[5:7]), int(t[11:13])
        if month in FIRE_SEASON_MONTHS and 5 <= hour <= 9:
            fog_n += 1
            fog += rh >= 95
        g = gfdi(default_curing(month), temp, rh, wind)
        if g < FIRE_GFDI:
            continue
        rose[int((wdir % 360) / 22.5 + 0.5) % 16] += 1
        by_month[month - 1] += 1
        speeds.append(wind)
        very_high += g >= VERY_HIGH_GFDI
    total = rose.sum()
    if total == 0:
        raise ClimateUnavailable("no High fire-danger hours in the record")

    d = raw["daily"]
    days = [date.fromisoformat(x) for x in d["time"]]
    sun = np.array([np.nan if v is None else v / 3.6 for v in d["shortwave_radiation_sum"]])  # kWh/m2/day
    tmin = np.array([np.nan if v is None else v for v in d["temperature_2m_min"]])

    def worst_week(mask: np.ndarray) -> float:
        vals = np.where(mask, sun, np.nan)
        weeks = [np.nanmean(vals[i:i + 7]) for i in range(len(vals) - 6) if mask[i:i + 7].all()]
        return round(float(np.nanmin(weeks)), 2)

    months = np.array([x.month for x in days])
    fire_season = np.isin(months, FIRE_SEASON_MONTHS)
    shares = rose / total
    return {
        "lat": lat, "lon": lon, "elevation_m": raw.get("elevation"),
        "source": f"ERA5 reanalysis via Open-Meteo archive, hourly {YEARS[0]}-{YEARS[1]}",
        "fire_gfdi": FIRE_GFDI,
        "fire_hours_per_year": round(total / years, 1),
        "very_high_hours_per_year": round(very_high / years, 1),
        "fire_hours_by_month": [round(x / years, 1) for x in by_month],
        "fire_wind_rose": [round(float(x), 4) for x in shares],
        "fire_wind_kmh_median": round(float(np.median(speeds)), 1),
        "fire_wind_modes": wind_modes(list(shares)),
        "sun_hours": {
            "fire_season_mean": round(float(np.nanmean(sun[fire_season])), 2),
            "fire_season_worst_week": worst_week(fire_season),
            "winter_worst_week": worst_week(np.isin(months, (11, 12, 1, 2))),
            "december_mean": round(float(np.nanmean(sun[months == 12])), 2),
        },
        "pm_too_cold_days_per_year": round(float((tmin < PM_MIN_C).sum()) / years, 1),
        "fire_season_fog_morning_share": round(fog / fog_n, 3) if fog_n else 0.0,
    }


def downwind_deg(from_deg: float) -> float:
    return (from_deg + 180.0) % 360.0


def sector_vectors(rose: list[float]) -> list[tuple[float, float]]:
    """(downwind bearing, share) for each non-empty sector of a from-direction rose."""
    return [(downwind_deg(i * 22.5), s) for i, s in enumerate(rose) if s > 0]


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def unit(deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return math.sin(r), math.cos(r)
