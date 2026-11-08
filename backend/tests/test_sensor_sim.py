from datetime import timedelta

import numpy as np
import pytest

from app import climate, confirm, planner, sensor_health, sensor_sim, sensors
from app.db import connect, iso, loads, utcnow
from app.district import sync_roster
from app.main import get_sensor, list_alerts, list_sensors, _sensor_cache

WEATHER = {"wind_kmh": 26, "gust_kmh": 45, "wind_dir_deg": 200, "rh_pct": 18, "temp_c": 24, "precip_72h_mm": 0, "thunder_24h": 0}


@pytest.fixture(autouse=True)
def network(monkeypatch):
    monkeypatch.setattr(planner, "elevation_grid", lambda lats, lons, z=10: np.full((len(lats), len(lons)), 400.0))
    real = climate.climatology
    monkeypatch.setattr(climate, "climatology", lambda lat, lon, fetch=True: real(lat, lon, fetch=False))
    monkeypatch.setattr(confirm, "fetch_weather", lambda conn, event_id: dict(WEATHER))
    _sensor_cache.clear()
    with connect() as conn:
        sync_roster(conn)
        sensor_sim.seed(conn)


def _by_label() -> dict:
    return {n["label"]: n for n in list_sensors()["nodes"]}


def test_seed_lays_out_the_plan_with_a_day_of_history():
    out = list_sensors()
    kinds = [n["kind"] for n in out["nodes"]]
    assert kinds.count("bridge") == 1 and kinds.count("relay") >= 1 and kinds.count("sensor") >= 80
    assert out["simulated"] and all(n["simulated"] for n in out["nodes"])
    assert out["links"]["features"], "relays and plots draw their radio links"
    with connect() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM sensor_readings").fetchone()["c"]
    assert n > 90 * 100


def test_injected_faults_are_found_and_healthy_nodes_are_not_flagged():
    nodes = list_sensors()["nodes"]
    with connect() as conn:
        faults = {r["node_id"]: loads(r["sim_json"])["fault"] for r in conn.execute("SELECT * FROM sensor_nodes")}
    for n in nodes:
        if faults[n["node_id"]]:
            assert n["status"] != "ok", (n["label"], faults[n["node_id"]])
        else:
            assert n["status"] == "ok", (n["label"], n["actions"])
    offline = [n for n in nodes if faults[n["node_id"]].get("offline_at")]
    assert offline and all(n["status"] == "offline" and n["radio"] == "down" for n in offline)


def test_radio_and_sensors_are_judged_separately():
    nodes = list_sensors()["nodes"]
    with connect() as conn:
        faults = {r["node_id"]: loads(r["sim_json"])["fault"] for r in conn.execute("SELECT * FROM sensor_nodes")}
    stalled = [n for n in nodes if {"env_stall_at", "pm_stall_at"} & faults[n["node_id"]].keys()]
    assert len(stalled) == 2
    for n in stalled:
        assert n["radio"] == "ok" and n["sensors"] == "stale" and n["status"] == "stale"
        assert any("Stale sensor, may need replacement" in a for a in n["actions"])
    healthy = [n for n in nodes if n["kind"] == "sensor" and not faults[n["node_id"]]]
    assert all(n["radio"] == "ok" and n["sensors"] == "ok" for n in healthy)
    pm_stalled = next(n for n in stalled if "pm_stall_at" in faults[n["node_id"]])
    keys = [c["key"] for c in get_sensor(pm_stalled["node_id"])["checks"]]
    assert "stale_pm_seq" in keys and "pm" not in keys, "a stale sensor's old value isn't judged"


def test_firmware_without_counters_is_never_called_stale():
    with connect() as conn:
        conn.execute("UPDATE sensor_readings SET env_seq = NULL, pm_seq = NULL")
    _sensor_cache.clear()
    assert all(n["sensors"] in ("ok", "unknown", "n/a") for n in list_sensors()["nodes"])


def test_resent_sample_from_a_stalled_sensor_raises_no_smoke():
    rich = next(n for n in list_sensors()["nodes"] if n["tier"] == "rich" and n["status"] == "ok")
    smoke = {"airQualityMetrics": {"pm25Environmental": 180, "pm100Environmental": 200}, "firewatchMetrics": {"pmSeq": 1}}
    with connect() as conn:
        assert sensors.record(conn, rich["node_id"], smoke) is not None
        conn.execute("DELETE FROM signals")
        assert sensors.record(conn, rich["node_id"], smoke) is None


def test_worn_battery_is_told_apart_by_overnight_discharge():
    nodes = list_sensors()["nodes"]
    with connect() as conn:
        worn = next(r["node_id"] for r in conn.execute("SELECT * FROM sensor_nodes")
                    if loads(r["sim_json"])["fault"].get("capacity") == 0.58)
        healthy = next(n["node_id"] for n in nodes if n["tier"] == "bare" and n["status"] == "ok")
        share = {nid: sensor_health.capacity_share(sensor_health.history(conn, nid, utcnow()), 16.3) for nid in (worn, healthy)}
    assert share[worn] == pytest.approx(0.58, abs=0.08)
    assert share[healthy] == pytest.approx(1.0, abs=0.1)
    detail = get_sensor(worn)
    battery = next(c for c in detail["checks"] if c["key"] == "battery")
    assert battery["status"] == "replace" and "Replace" in battery["action"]


def test_plume_raises_a_sample_smoke_alert_that_shows_in_live_mode(monkeypatch):
    monkeypatch.setenv("MODE", "live")
    from app.config import get_settings

    get_settings.cache_clear()
    rich = next(n for n in list_sensors()["nodes"] if n["tier"] == "rich" and n["status"] == "ok")
    with connect() as conn:
        out = sensor_sim.plume(conn, rich["node_id"])
        assert out["events"] and rich["node_id"] in out["nodes"]
        ev = conn.execute("SELECT * FROM events WHERE id = ?", (out["events"][0],)).fetchone()
    assert ev["is_sample"] == 1 and ev["recommendation"] in ("investigate", "escalate")
    assert out["events"][0] in [a["id"] for a in list_alerts()["alerts"]]


def test_simulated_temperatures_never_replace_the_forecast():
    n = list_sensors()["nodes"][-1]
    with connect() as conn:
        w = sensors.local_weather(conn, n["lat"], n["lon"], dict(WEATHER))
    assert "local_sensor" not in w


def test_simulated_nodes_report_on_each_tick():
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) c FROM sensor_readings").fetchone()["c"]
        sensor_sim.tick(conn, utcnow() + timedelta(minutes=2))
        after = conn.execute("SELECT COUNT(*) c FROM sensor_readings").fetchone()["c"]
        heard = conn.execute("SELECT MAX(last_heard) m FROM mesh_nodes").fetchone()["m"]
    assert after - before >= 90
    assert heard >= iso(utcnow() - timedelta(seconds=5))
