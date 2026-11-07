from datetime import datetime, timedelta, timezone

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.sim.ensemble import forecast
from app.sim.fuels import FUEL_KEYS, FuelGrid, multipliers
from app.sim.spread import SpreadInput, WeatherStep, _blocks, _step_multipliers, block_rates, build_domain, propagate
from app.situation import Ignition, Provenance, Situation, Weather, WeatherHour, list_scenarios, load_scenario

LAT, LON = 38.8, -99.45
T0 = datetime(2026, 3, 17, 19, tzinfo=timezone.utc)
SIM = Provenance(source="test", kind="simulated")


def _inp(**kw):
    base = dict(lat=LAT, lon=LON, wind_kmh=40.0, wind_from_deg=180.0, temp_c=24, rh_pct=15, curing_pct=95,
                minutes=60, use_terrain=False)
    return SpreadInput(**(base | kw))


def _run(inp: SpreadInput, fuel_mult: np.ndarray | None = None):
    steps = inp.weather or [WeatherStep(0, inp.wind_kmh, inp.wind_from_deg, inp.temp_c, inp.rh_pct)]
    blocks = _blocks(steps, inp.minutes)
    rates, heads = block_rates(blocks, inp.curing_pct)
    dom = build_domain(inp, blocks, max(heads))
    if fuel_mult is not None:
        dom.fuel = FuelGrid(fuel_mult(dom), dom.fuel.fuel_class, "test", True)
        dom.step_mult = _step_multipliers(dom)
    return dom, propagate(dom, rates, [(inp.lat, inp.lon)], inp.minutes, inp.fire_age_min)


def _north_km(dom, arrival, minutes):
    rows = np.nonzero((arrival <= minutes).any(axis=1))[0]
    return (dom.lats[rows.max()] - LAT) * 110.574


def test_unburnable_band_stops_the_head():
    def band(dom):
        m = np.ones((dom.n, dom.n))
        i = int(np.searchsorted(dom.lats, LAT + 1.0 / 110.574))  # 1 km north of the ignition
        m[i:i + 4, :] = 0.0
        return m

    dom, open_run = _run(_inp())
    _, blocked = _run(_inp(), band)
    assert _north_km(dom, open_run, 60) > 3
    assert _north_km(dom, blocked, 60) < 1.1


def test_slow_fuel_slows_spread():
    dom, grass = _run(_inp())
    _, wheat = _run(_inp(), lambda d: np.full((d.n, d.n), multipliers(3)[FUEL_KEYS.index("wheat")]))
    assert (wheat <= 60).sum() < 0.3 * (grass <= 60).sum()


def test_wind_shift_turns_the_flank_into_a_head():
    steady = [WeatherStep(0, 40, 180, 24, 15), WeatherStep(60, 40, 180, 24, 15)]
    shift = [WeatherStep(0, 40, 180, 24, 15), WeatherStep(25, 40, 180, 24, 15), WeatherStep(35, 40, 270, 24, 15)]
    dom1, a1 = _run(_inp(weather=steady))
    dom2, a2 = _run(_inp(weather=shift))

    def east_km(dom, arrival):
        cols = np.nonzero((arrival <= 60).any(axis=0))[0]
        return (dom.lons[cols.max()] - LON) * 111.32 * np.cos(np.radians(LAT))

    assert east_km(dom2, a2) > 2 * east_km(dom1, a1)
    assert _north_km(dom2, a2, 60) < _north_km(dom1, a1, 60)


def test_new_ignition_starts_slower_than_established_fire():
    dom1, established = _run(_inp(fire_age_min=None, grid_n=400))
    dom2, new = _run(_inp(fire_age_min=0, grid_n=400))
    # FBP acceleration puts a new fire's head at about half the established run after 15 minutes
    assert _north_km(dom2, new, 15) < 0.7 * _north_km(dom1, established, 15)
    assert _north_km(dom2, new, 60) > 0.8 * _north_km(dom1, established, 60)


def _situation(**kw) -> Situation:
    hours = [WeatherHour(time=T0 + timedelta(hours=h), wind_kmh=45, wind_from_deg=190, temp_c=25, rh_pct=12)
             for h in range(-1, 3)]
    base = dict(
        ignition=Ignition(lat=LAT, lon=LON, time=T0, provenance=SIM),
        weather=Weather(hours=hours, provenance=SIM),
        use_fuel_map=False, use_terrain=False,
    )
    return Situation(**(base | kw))


def test_ensemble_ranges_are_ordered_and_reproducible():
    r1 = forecast(_situation(), minutes=60, members=8)
    r2 = forecast(_situation(), minutes=60, members=8)
    for cp in r1["checkpoints"]:
        for key in ("area_ha", "head_km"):
            assert cp[key]["p10"] <= cp[key]["p50"] <= cp[key]["p90"]
    assert r1["checkpoints"] == r2["checkpoints"]
    assert [f["properties"]["probability"] for f in r1["probability"]["features"]] == [0.1, 0.5, 0.9]
    assert r1["provenance"]["spread"]["kind"] == "simulated"


def test_scenarios_validate_against_the_contract():
    slugs = [s["slug"] for s in list_scenarios()]
    assert "cottonwood-creek" in slugs
    for slug in slugs:
        meta, sit = load_scenario(slug)
        assert meta["synthetic"]
        assert sit.weather_steps()[0].t_min < 0  # weather starts before ignition, for interpolation
    _, front = load_scenario("cottonwood-creek-front")
    _, base = load_scenario("cottonwood-creek")
    assert front.wind_shift_deg(240) > 90 > base.wind_shift_deg(240)


def test_forecast_api_accepts_a_situation():
    with TestClient(app) as client:
        body = _situation().model_dump(mode="json")
        r = client.post("/api/forecast", params={"minutes": 30, "members": 4}, json=body)
        assert r.status_code == 200
        out = r.json()
        assert out["isochrones"]["features"] and "_arrival" not in out
        assert client.get("/api/scenarios/nope/forecast").status_code == 404
        assert client.post("/api/forecast", json={"weather": {}}).status_code == 422
