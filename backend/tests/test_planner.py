import math
from itertools import pairwise

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import climate, planner
from app.geo import haversine_km
from app.main import app

DISTRICT = "district:cottonwood-creek"


def _flat(lats, lons, z=10):
    return np.full((len(lats), len(lons)), 400.0)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(planner, "elevation_grid", _flat)
    real = climate.climatology
    monkeypatch.setattr(climate, "climatology", lambda lat, lon, fetch=True: real(lat, lon, fetch=False))


@pytest.fixture(scope="module")
def plan():
    mp = pytest.MonkeyPatch()
    mp.setattr(planner, "elevation_grid", _flat)
    out = planner.plan_region(planner.resolve_region(DISTRICT), fetch_climate=False)
    mp.undo()
    return out


def test_wind_modes_finds_the_frontal_shift():
    rose = [0.0] * 16
    rose[8], rose[9], rose[10] = 0.3, 0.3, 0.1  # S, SSW, SW
    rose[14], rose[15] = 0.2, 0.1  # NW, NNW behind the front
    modes = climate.wind_modes(rose)
    assert modes[0]["from"] in ("S", "SSW")
    assert modes[1]["from"] in ("NW", "NNW")
    assert climate.wind_modes([1.0] + [0.0] * 15)[1:] == []


def test_summarize_counts_only_fire_weather_hours():
    hours = ["2020-03-15T14:00", "2020-03-15T15:00", "2020-07-01T14:00"]
    raw = {
        "hourly": {
            "time": hours,
            "temperature_2m": [28, 27, 35],
            "relative_humidity_2m": [15, 18, 60],
            "wind_speed_10m": [40, 35, 10],
            "wind_direction_10m": [200, 205, 90],
        },
        "daily": {"time": [f"2020-03-{d:02d}" for d in range(1, 15)] + [f"2020-12-{d:02d}" for d in range(1, 15)],
                  "shortwave_radiation_sum": [15.0] * 14 + [6.0] * 14, "temperature_2m_min": [0.0] * 14 + [-12.0] * 14},
    }
    s = climate.summarize(raw, 37.75, -96.5)
    assert s["fire_hours_by_month"][2] > 0 and s["fire_hours_by_month"][6] == 0
    assert s["fire_wind_modes"][0]["from"] in ("SSW", "S")
    assert s["pm_too_cold_days_per_year"] > 0
    assert s["sun_hours"]["winter_worst_week"] < s["sun_hours"]["fire_season_worst_week"]


def test_district_plan_follows_the_readme_mix(plan):
    s = plan["summary"]
    assert (s["sites"], s["bare"], s["rich"]) == (10, 70, 20)
    region = planner.resolve_region(DISTRICT)
    for site in plan["sites"]:
        assert planner._inside(np.array([site["lon"]]), np.array([site["lat"]]), region.rings)[0]
        assert (site["bare"], site["rich"]) == (7, 2)
        assert site["reasons"]
    for a in plan["sites"]:
        for b in plan["sites"]:
            if a["id"] < b["id"]:
                assert haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) >= 3.0 - 1e-6
    curve = s["coverage_curve"]
    assert all(b >= a for a, b in pairwise(curve))
    assert 0 < s["priority_covered"] < 1


def test_every_site_reaches_the_station_within_the_hop_limit(plan):
    assert plan["summary"]["unreached_sites"] == []
    assert all(site["gateway"] and site["hops"] <= planner.HOP_LIMIT for site in plan["sites"])
    for r in plan["relays"]:
        assert r["km"] <= planner.RANGE_KM[("tower", "tower")]


def test_bom_adds_up(plan):
    bom = plan["bom"]
    s = plan["summary"]
    assert bom["hardware"] == s["bare"] * 175 + s["rich"] * 240 + s["relays"] * 105 + 45
    assert bom["total"] == bom["hardware"] + bom["spares"]
    assert bom["custom_pcb_hardware"] < bom["hardware"]


def test_rich_nodes_sit_downwind_of_each_fire_wind_mode(plan):
    modes = plan["climate"]["fire_wind_modes"]
    assert len(modes) == 2
    for site in plan["sites"]:
        rich = [n for n in site["nodes"] if n["tier"] == "rich"]
        assert [n["faces"] for n in rich] == [m["from"] for m in modes]
        for n, mode in zip(rich, modes):
            dx = (n["lon"] - site["lon"]) * math.cos(math.radians(site["lat"]))
            bearing = math.degrees(math.atan2(dx, n["lat"] - site["lat"])) % 360
            assert climate.angle_diff(bearing, climate.downwind_deg(mode["from_deg"])) <= 60


def test_budget_caps_the_plan():
    out = planner.plan_region(planner.resolve_region(DISTRICT), {"budget_usd": 8000}, fetch_climate=False)
    assert out["bom"]["total"] <= 8000
    assert out["summary"]["sites"] >= 1


def test_terrain_blocks_a_link():
    flat = planner.Terrain(-10, -10, 0.25, np.full((81, 81), 400.0))
    a = {"x": -3.0, "y": 0.0, "mount": "ground"}
    b = {"x": 3.0, "y": 0.0, "mount": "tower"}
    assert planner.link(flat, a, b)["km"] == 6.0
    ridge = flat.z.copy()
    ridge[:, 40] = 480.0
    assert planner.link(planner.Terrain(-10, -10, 0.25, ridge), a, b) is None
    far = {"x": 9.0, "y": 0.0, "mount": "ground"}
    assert planner.link(flat, a, far) is None


def test_planner_api():
    client = TestClient(app)
    regions = client.get("/api/planner/regions").json()
    assert any(d["key"] == DISTRICT for d in regions["districts"])
    assert len(regions["counties"]) == 105
    r = client.get("/api/planner/plan", params={"region": DISTRICT, "sites": 4})
    assert r.status_code == 200
    assert r.json()["summary"]["sites"] == 4
    assert client.get("/api/planner/plan", params={"region": "county:Atlantis"}).status_code == 404
