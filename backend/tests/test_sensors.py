import json
from datetime import timedelta

import pytest

from app import confirm, decision, mesh, sensor_model, sensors
from app.db import connect, iso, loads, utcnow
from app.district import sync_roster
from app.signals import add_signal

WEATHER = {"wind_kmh": 26, "gust_kmh": 45, "wind_dir_deg": 200, "rh_pct": 18, "temp_c": 24, "precip_72h_mm": 0, "thunder_24h": 0}
TOWER = (37.4121, -99.4681)
FAR_A, FAR_B = (37.6621, -99.4681), (37.4121, -99.11)
SMOKE = {"airQualityMetrics": {"pm25Environmental": 160, "pm100Environmental": 190}}


@pytest.fixture(autouse=True)
def towers(monkeypatch):
    monkeypatch.setattr(confirm, "fetch_weather", lambda conn, event_id: dict(WEATHER))
    with connect() as conn:
        sync_roster(conn)
        for nid, (lat, lon) in {"!tower01": TOWER, "!tower02": FAR_A, "!tower03": FAR_B}.items():
            conn.execute(
                "INSERT INTO mesh_nodes(node_id, lat, lon, position_at, last_heard) VALUES (?, ?, ?, ?, ?)",
                (nid, lat, lon, iso(utcnow()), iso(utcnow())),
            )
            _history(conn, nid, pm25=8)


def _history(conn, nid: str, pm25: float, temp: float = 22, rh: float = 35) -> None:
    for minutes in (150, 110, 70, 40):
        conn.execute(
            "INSERT INTO sensor_readings(node_id, at, temp_c, rh_pct, pm25, pm10) VALUES (?, ?, ?, ?, ?, ?)",
            (nid, iso(utcnow() - timedelta(minutes=minutes)), temp, rh, pm25, pm25 * 1.3),
        )


def _now_reading(conn, nid: str, pm25: float) -> None:
    conn.execute(
        "INSERT INTO sensor_readings(node_id, at, pm25, pm10) VALUES (?, ?, ?, ?)", (nid, iso(utcnow()), pm25, pm25 * 1.2)
    )


def _event(conn, eid):
    return conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()


def test_smoke_alone_investigates_never_pages():
    with connect() as conn:
        eid = sensors.record(conn, "!tower01", SMOKE)
        assert eid is not None
        ev = _event(conn, eid)
        assert ev["recommendation"] == "investigate" and "smoke sensor" in ev["level_reason"]
        sig = conn.execute("SELECT * FROM signals WHERE event_id = ?", (eid,)).fetchone()
        assert sig["kind"] == "sensor_smoke" and "PM2.5 160" in sig["value"] and "usual 8" in sig["value"]
        assert sensors.record(conn, "!tower01", SMOKE) is None, "one signal per sensor per hour"


def test_two_sensors_on_one_plume_are_still_one_source():
    with connect() as conn:
        conn.execute("UPDATE mesh_nodes SET lat = ?, lon = ? WHERE node_id = '!tower02'", (TOWER[0] + 0.03, TOWER[1]))
        a = sensors.record(conn, "!tower01", SMOKE)
        b = sensors.record(conn, "!tower02", SMOKE)
        assert a == b, "a second nearby sensor joins the same event"
        assert _event(conn, a)["recommendation"] == "investigate"


def test_dust_is_not_smoke():
    dust = {"airQualityMetrics": {"pm25Environmental": 90, "pm100Environmental": 420}}
    with connect() as conn:
        assert sensors.record(conn, "!tower01", dust) is None
        ok, why = sensors.smoke_verdict(conn, "!tower01", 90, 420, utcnow())
        assert not ok and "dust" in why


def test_regional_smoke_is_not_a_local_fire():
    with connect() as conn:
        _now_reading(conn, "!tower02", 120)
        _now_reading(conn, "!tower03", 110)
        assert sensors.record(conn, "!tower01", SMOKE) is None
        ok, why = sensors.smoke_verdict(conn, "!tower01", 160, 190, utcnow())
        assert not ok and "regional" in why


def test_sensor_downwind_of_a_line_fault_escalates():
    with connect() as conn:
        fault = (TOWER[0] - 0.045, TOWER[1])  # 5 km south, upwind on a south wind
        eid = add_signal(conn, "line_fault", *fault, iso(utcnow()), "coop:feeder-4", "lockout", is_sample=True)
        confirm.evaluate_event(conn, eid, WEATHER)
        assert _event(conn, eid)["recommendation"] == "investigate"
        assert sensors.record(conn, "!tower01", SMOKE, weather=WEATHER) == eid
        ev = _event(conn, eid)
        assert ev["recommendation"] == "escalate"
        assert (round(ev["lat"], 3), round(ev["lon"], 3)) == (round(fault[0], 3), round(fault[1], 3)), "the fault places the fire"


def test_tower_without_a_position_raises_nothing():
    with connect() as conn:
        conn.execute("UPDATE mesh_nodes SET lat = NULL, lon = NULL WHERE node_id = '!tower01'")
        assert sensors.record(conn, "!tower01", SMOKE) is None
        assert conn.execute("SELECT COUNT(*) FROM sensor_readings WHERE node_id = '!tower01'").fetchone()[0] == 5


def test_local_weather_from_the_nearest_sensor():
    with connect() as conn:
        sensors.record(conn, "!tower01", {"environmentMetrics": {"temperature": 31.5, "relativeHumidity": 12.0}})
        w = sensors.local_weather(conn, TOWER[0] - 0.05, TOWER[1], WEATHER)
        assert (w["temp_c"], w["rh_pct"]) == (31.5, 12.0) and w["local_sensor"].startswith("!tower01")
        assert sensors.local_weather(conn, 39.5, -99.0, WEATHER) == WEATHER


def test_telemetry_packets_feed_the_sensors():
    with connect() as conn:
        pkt = {"from": 0x70, "fromId": "!tower01", "to": 0xFFFFFFFF, "decoded": {"portnum": "TELEMETRY_APP", "telemetry": SMOKE}}
        assert mesh.handle_packet(conn, pkt, 0x0A0A0A0A) == "telemetry"
        assert conn.execute("SELECT COUNT(*) FROM signals WHERE kind = 'sensor_smoke'").fetchone()[0] == 1
        node = next(n for n in mesh.list_nodes(conn) if n["node_id"] == "!tower01")
        assert node["sensors"]["pm25"] == 160 and node["sensors"]["rh_pct"] == 35


# --- sensor smoke model: how much a reading counts ---

def _gas_history(conn, nid: str, usual: float = 200.0, recent: float | None = None) -> None:
    for minutes in (150, 110, 70, 40):
        conn.execute("INSERT INTO sensor_readings(node_id, at, gas_kohm) VALUES (?, ?, ?)",
                     (nid, iso(utcnow() - timedelta(minutes=minutes)), usual))
    if recent is not None:
        conn.execute("INSERT INTO sensor_readings(node_id, at, gas_kohm) VALUES (?, ?, ?)",
                     (nid, iso(utcnow() - timedelta(minutes=10)), recent))


def _sensor_step(eid: int) -> dict:
    with connect() as conn:
        ev = conn.execute("SELECT evidence_json FROM events WHERE id = ?", (eid,)).fetchone()
    evidence = loads(ev["evidence_json"], [])
    steps = decision.probability(evidence, "High", decision.weights({}))["steps"]
    return next(s for s in steps if "sensor" in s["text"])


def test_a_bigger_rise_counts_for_more():
    assert sensor_model.load() is not None, "backend/data/model/smoke_sensor.json ships with the app"
    assert 1 < sensor_model.pm_lr(60) < sensor_model.pm_lr(150)
    with connect() as conn:
        eid = sensors.record(conn, "!tower01", SMOKE)
        sig = conn.execute("SELECT meta_json FROM signals WHERE event_id = ?", (eid,)).fetchone()
    meta = json.loads(sig["meta_json"])
    assert meta == {"via": "pm", "pm_lr": sensor_model.pm_lr(160 - 8)}
    w = decision.weights({})
    assert _sensor_step(eid)["factor"] == round(min(meta["pm_lr"], w["lr_sensor_pm_max"]), 2)


def test_gas_drop_on_the_same_node_adds_a_little():
    with connect() as conn:
        _gas_history(conn, "!tower01", recent=50.0)
        conn.execute("INSERT INTO sensor_readings(node_id, at, gas_kohm) VALUES (?, ?, ?)", ("!tower01", iso(utcnow()), 40.0))
        eid = sensors.record(conn, "!tower01", SMOKE)
        sig = conn.execute("SELECT value, meta_json FROM signals WHERE event_id = ?", (eid,)).fetchone()
    meta = json.loads(sig["meta_json"])
    assert meta["via"] == "pm+gas" and meta["gas_lr"] > 1 and "gas resistance 20% of usual" in sig["value"]
    w = decision.weights({})
    want = min(meta["pm_lr"], w["lr_sensor_pm_max"]) * min(meta["gas_lr"], w["lr_sensor_gas_max"]) ** w["sensor_gas_weight"]
    assert _sensor_step(eid)["factor"] == round(want, 2)


def test_gas_alone_never_opens_an_event():
    with connect() as conn:
        _gas_history(conn, "!tower01", recent=50.0)
        assert sensors.record(conn, "!tower01", {"environmentMetrics": {"gasResistance": 0.04}}) is None
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0


def test_gas_alone_adds_weight_to_a_nearby_event_but_is_not_a_source():
    with connect() as conn:
        fault = (TOWER[0] - 0.045, TOWER[1])
        eid = add_signal(conn, "line_fault", *fault, iso(utcnow()), "coop:feeder-4", "lockout", is_sample=True)
        confirm.evaluate_event(conn, eid, WEATHER)
        _gas_history(conn, "!tower01", recent=50.0)
        assert sensors.record(conn, "!tower01", {"environmentMetrics": {"gasResistance": 0.04}}, weather=WEATHER) == eid
        ev = _event(conn, eid)
        assert ev["recommendation"] == "investigate", "a gas drop is not a second source"
        gas = next(e for e in loads(ev["evidence_json"]) if e["kind"] == "sensor_smoke")
        assert gas["counts"] == "no" and gas["label"].startswith("Gas sensor !tower01")
        assert sensors.record(conn, "!tower01", {"environmentMetrics": {"gasResistance": 0.03}}) is None, "once per hour"
    step = _sensor_step(eid)
    assert step["factor"] == min(gas["gas_lr"], decision.weights({})["lr_sensor_gas_max"]) and "gas alone" in step["text"]


def test_one_gas_reading_or_a_small_drop_is_nothing():
    with connect() as conn:
        _gas_history(conn, "!tower01")
        conn.execute("INSERT INTO sensor_readings(node_id, at, gas_kohm) VALUES (?, ?, ?)", ("!tower01", iso(utcnow()), 40.0))
        assert sensors.gas_verdict(conn, "!tower01", utcnow())[0] is None, "the reading before it was normal"
        conn.execute("INSERT INTO sensor_readings(node_id, at, gas_kohm) VALUES (?, ?, ?)", ("!tower01", iso(utcnow()), 150.0))
        assert sensors.gas_verdict(conn, "!tower01", utcnow())[0] is None, "75% of usual is not smoke"


def test_gas_and_pressure_are_stored():
    with connect() as conn:
        sensors.record(conn, "!tower01", {"environmentMetrics": {"temperature": 20.0, "gasResistance": 0.18, "barometricPressure": 951.2}})
        got = sensors.latest_readings(conn, "!tower01")
    assert got["gas_kohm"] == 180.0 and got["pressure_hpa"] == 951.2


def test_all_smoke_sensors_count_once_toward_the_chance_of_fire():
    w = decision.weights({})
    at = "2026-03-17T18:56:00Z"
    a = {"kind": "sensor_smoke", "label": "Smoke sensor !a", "counts": "yes", "at": at, "pm_lr": 4.0}
    b = {"kind": "sensor_smoke", "label": "Smoke sensor !b", "counts": "yes", "at": at, "pm_lr": 12.0}
    steps = decision.probability([a, b], "High", w)["steps"]
    assert [s["factor"] for s in steps if "factor" in s] == [12.0]


def test_the_rule_weight_is_measured_not_assumed():
    w = {d["key"]: d for d in decision.described({})}
    assert w["lr_sensor_smoke"]["value"] == sensor_model.rule_lr()["lr"]
    assert w["lr_sensor_smoke"]["source"].startswith("Sensor smoke model v1")
