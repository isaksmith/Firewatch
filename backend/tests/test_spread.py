import math
import time

from app.sim.spread import SpreadInput, simulate


def _extent(result, minutes):
    feat = next(f for f in result["isochrones"]["features"] if f["properties"]["minutes"] == minutes)
    pts = [p for poly in feat["geometry"]["coordinates"] for ring in poly for p in ring]
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return min(lons), max(lons), min(lats), max(lats)


def _run(wind_kmh, wind_from_deg=180.0):
    return simulate(SpreadInput(
        lat=38.8, lon=-99.45, wind_kmh=wind_kmh, wind_from_deg=wind_from_deg,
        temp_c=24, rh_pct=20, curing_pct=95, minutes=60, use_terrain=False,
    ))


def test_zero_wind_is_roughly_circular():
    w, e, s, n = _extent(_run(0.0), 60)
    width_km = (e - w) * 111.32 * math.cos(math.radians(38.8))
    height_km = (n - s) * 110.57
    assert 0.8 < width_km / height_km < 1.25


def test_wind_from_south_spreads_north():
    w, e, s, n = _extent(_run(40.0, 180.0), 60)
    assert (n - 38.8) > 3 * (38.8 - s)


def test_flipping_wind_mirrors_shape():
    _, _, s1, n1 = _extent(_run(40.0, 180.0), 60)
    _, _, s2, n2 = _extent(_run(40.0, 0.0), 60)
    assert abs((n1 - 38.8) - (38.8 - s2)) < 0.01


def test_more_wind_runs_further():
    assert _run(50.0)["head_ros_kmh"] > _run(20.0)["head_ros_kmh"]


def test_runs_fast_enough():
    start = time.perf_counter()
    _run(45.0)
    assert time.perf_counter() - start < 1.0


ZERO_RATE = dict(wind_kmh=0.0, temp_c=10, rh_pct=100, curing_pct=95)


def test_zero_spread_rate_does_not_crash():
    r = simulate(SpreadInput(lat=38.8, lon=-99.45, wind_from_deg=180.0, minutes=60, use_terrain=False, **ZERO_RATE))
    assert r["head_ros_kmh"] == 0
    assert {f["properties"]["area_ha"] for f in r["isochrones"]["features"]} == {0.4}  # the ignition cell only, no growth


def test_page_with_zero_spread_rate_still_pages():
    from fastapi.testclient import TestClient
    from app import notify
    from app.db import connect, utcnow
    from app.main import app
    from tests.test_routes_posts import _fire_with_event
    with TestClient(app) as c:
        pid, eid = _fire_with_event(c)
        with connect() as conn:
            conn.execute("UPDATE events SET features_json = ?, weather_json = ? WHERE id = ?",
                         ('{"temp_c": 10, "rh_pct": 100, "curing_pct": 95}', '{"wind_kmh": 0}', eid))
            notify.decide(conn, eid, "page", "Duty", utcnow())
            assert conn.execute("SELECT response_json FROM events WHERE id = ?", (eid,)).fetchone()[0]
