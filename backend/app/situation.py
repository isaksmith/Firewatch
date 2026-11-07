"""The Situation: everything known about one fire at one moment, with where each piece came from.

This is the contract between data ingestion and the forecast / recommendation layer. Ingestion fills
it in; the spread forecast and recommendations only read it. Every block carries a Provenance so the
UI can label each input as observed, forecast, inferred, simulated or assumed.

Only `ignition` and `weather` are required. Everything else has a documented fallback.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from .config import DATA_DIR
from .fire_weather import default_curing
from .geo import angle_diff
from .sim.spread import WeatherStep

Kind = Literal["observed", "forecast", "inferred", "simulated", "assumed"]
SCENARIO_DIR = DATA_DIR / "scenarios"


class Provenance(BaseModel):
    source: str  # e.g. "open-meteo forecast", "USDA CDL 2024", "competitor packet"
    kind: Kind
    as_of: datetime | None = None


class Ignition(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    time: datetime  # forecast starts here (timezone-aware)
    points: list[tuple[float, float]] | None = None  # extra burning points (lat, lon), e.g. satellite pixels
    # Minutes the fire had already burned at `time`. 0 = brand-new point ignition (it accelerates);
    # None = established fire spreading at its full rate (e.g. first seen by satellite).
    fire_age_min: float | None = 0.0
    provenance: Provenance


class WeatherHour(BaseModel):
    time: datetime
    wind_kmh: float = Field(ge=0)  # 10 m sustained
    wind_from_deg: float = Field(ge=0, le=360)
    temp_c: float
    rh_pct: float = Field(ge=0, le=100)
    gust_kmh: float | None = None


class Weather(BaseModel):
    hours: list[WeatherHour] = Field(min_length=1)  # hourly or finer, any order
    provenance: Provenance


class Curing(BaseModel):
    pct: float = Field(ge=0, le=100)
    provenance: Provenance


class BurnPermit(BaseModel):
    id: str
    lat: float
    lon: float
    acres: float | None = None
    start: datetime
    end: datetime
    status: Literal["active", "extinguished", "scheduled"] = "active"
    provenance: Provenance


class Resource(BaseModel):
    id: str
    name: str
    kind: Literal["brush", "tanker", "engine", "water_truck", "disc", "aircraft", "other"]
    lat: float  # where it is now (station, lease, ranch)
    lon: float
    crew: int | None = None
    available: bool = True
    ready_min: float = 0.0  # minutes from page to rolling (volunteer turnout)
    provenance: Provenance


class Situation(BaseModel):
    ignition: Ignition
    weather: Weather
    curing: Curing | None = None  # None -> seasonal default for Kansas grass (assumed)
    red_flag: bool | None = None
    burn_permits: list[BurnPermit] = []
    resources: list[Resource] = []
    use_fuel_map: bool = True  # False -> uniform grass
    use_terrain: bool = True

    def curing_or_default(self) -> Curing:
        if self.curing is not None:
            return self.curing
        month = self.ignition.time.astimezone(timezone.utc).month
        return Curing(pct=default_curing(month), provenance=Provenance(source="seasonal table", kind="assumed"))

    def weather_steps(self) -> list[WeatherStep]:
        """Weather as minutes after the ignition time, sorted. Hours before ignition are kept for interpolation."""
        t0 = self.ignition.time
        return sorted(
            (WeatherStep(
                t_min=(h.time - t0).total_seconds() / 60, wind_kmh=h.wind_kmh, wind_from_deg=h.wind_from_deg,
                temp_c=h.temp_c, rh_pct=h.rh_pct,
            ) for h in self.weather.hours),
            key=lambda s: s.t_min,
        )

    def wind_shift_deg(self, horizon_min: float) -> float:
        """Largest wind-direction change within the forecast window."""
        steps = [s for s in self.weather_steps() if -60 <= s.t_min <= horizon_min]
        if len(steps) < 2:
            return 0.0
        return max(abs(angle_diff(a.wind_from_deg, b.wind_from_deg)) for a in steps for b in steps)


def from_open_meteo(lat: float, lon: float, when: datetime, hours: int = 4) -> Situation:
    """A Situation for a new ignition with weather from Open-Meteo (forecast, or archive if in the past)."""
    from .ingest.weather import weather_series

    when = when.astimezone(timezone.utc)
    series, kind = weather_series(lat, lon, when - timedelta(hours=1), hours + 2)
    return Situation(
        ignition=Ignition(lat=lat, lon=lon, time=when, provenance=Provenance(source="user", kind="assumed")),
        weather=Weather(
            hours=[WeatherHour(**h) for h in series],
            provenance=Provenance(source=f"open-meteo {kind}", kind="observed" if kind == "archive" else "forecast",
                                  as_of=datetime.now(timezone.utc)),
        ),
    )


def list_scenarios() -> list[dict]:
    import json

    out = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        raw = json.loads(path.read_text())
        out.append({"slug": path.stem, "title": raw["title"], "story": raw.get("story"), "synthetic": raw.get("synthetic", True)})
    return out


def load_scenario(slug: str) -> tuple[dict, Situation]:
    """Returns (metadata, situation). Raises FileNotFoundError for an unknown slug."""
    import json

    path = SCENARIO_DIR / f"{slug}.json"
    if not path.is_file() or path.parent != SCENARIO_DIR:
        raise FileNotFoundError(slug)
    raw = json.loads(path.read_text())
    meta = {k: v for k, v in raw.items() if k != "situation"}
    return meta, Situation.model_validate(raw["situation"])
