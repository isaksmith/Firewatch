from datetime import timedelta

import pytest

from app import confirm, mesh, sensors
from app.db import connect, iso, utcnow
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
