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
    assert bom["pricing"] == "custom"
    custom = s["bare"] * 136.44 + s["rich"] * 203.60 + s["relays"] * 105 + 45
    assert bom["hardware"] == round(custom, 2)
    assert bom["total"] == round(bom["hardware"] + bom["spares"], 2)
    stocked = s["bare"] * 175 + s["rich"] * 240 + s["relays"] * 105 + 45
    assert bom["alternative"] == {"pricing": "stocked", "hardware": stocked}


def test_custom_board_pricing_buys_more_plots_on_a_budget():
    region = planner.resolve_region(DISTRICT)
    stocked, custom = (planner.plan_region(region, {"budget_usd": 12000, "pricing": k}, fetch_climate=False)
                       for k in ("stocked", "custom"))
    assert custom["bom"]["lines"][0]["unit"] == 136.44 and custom["bom"]["lines"][1]["unit"] == 203.60
    assert custom["bom"]["total"] <= 12000
    assert custom["summary"]["sites"] > stocked["summary"]["sites"]


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


def test_routing_past_the_hop_limit_terminates():
    flat = planner.Terrain(-10, -10, 0.5, np.full((40, 160), 400.0))
    station = {"name": "Station", "x": 0.0, "y": 0.0, "mount": "mast", "lon": 0, "lat": 0}
    masts = [
        {"kind": "high_point", "name": f"Mast {k}", "x": 9.0 * k, "y": 0.0, "mount": "mast", "lon": 0, "lat": 0}
        for k in range(1, 7)
    ]
    far = {"x": 9.0 * 6 + 4.0, "y": 0.0, "mount": "ground"}
    near = {"x": 3.0, "y": 0.0, "mount": "ground"}
    mesh = planner.route_mesh(flat, station, [near, far], masts)
    assert mesh["unreached"] == []
    assert mesh["over_hop_limit"] == [1]
    assert mesh["hops"] == {0: 0, 1: 6}


def test_planner_api():
    client = TestClient(app)
    regions = client.get("/api/planner/regions").json()
    assert any(d["key"] == DISTRICT for d in regions["districts"])
    assert len(regions["counties"]) == 105
    r = client.get("/api/planner/plan", params={"region": DISTRICT, "sites": 4})
    assert r.status_code == 200
    assert r.json()["summary"]["sites"] == 4
    assert client.get("/api/planner/plan", params={"region": "county:Atlantis"}).status_code == 404


def test_plan_explains_each_site_and_relay(plan):
    first, *rest = plan["sites"]
    assert first["choice"][0].startswith("First pick")
    assert all(s["choice"][0].startswith(f"Pick {s['id']}:") for s in rest)
    for s in plan["sites"]:
        assert 0 <= s["risk"]["rank"] <= 1
        assert abs(sum(f["share"] for f in s["risk"]["factors"]) - 1) < 0.02
        assert s["placement"] and "downwind" in s["layout"]
    for r in plan["relays"]:
        assert r["why"] and r["serves"]
    cell = plan["geojson"]["cells"]["features"][0]["properties"]
    assert {"rank", "history", "burns", "lines", "people", "tallgrass", "downwind"} <= cell.keys()


def test_every_requested_node_is_placed_past_sixteen():
    p = planner.plan_region(planner.resolve_region(DISTRICT), {"sites": 2, "bare_per_site": 14, "rich_per_site": 4},
                            fetch_climate=False)
    assert all(s["bare"] == 14 and s["rich"] == 4 for s in p["sites"])
    assert len({(n["lon"], n["lat"]) for s in p["sites"] for n in s["nodes"]}) == 2 * 18


def test_more_bare_nodes_never_watch_less():
    region = planner.resolve_region(DISTRICT)
    watched = [planner.plan_region(region, {"sites": 3, "bare_per_site": b}, fetch_climate=False)["summary"]
               for b in (0, 3, 7, 12)]
    assert all(a["watched_by_bare"] <= b["watched_by_bare"] for a, b in pairwise(watched))
    assert watched[0]["watched_by_bare"] == 0
