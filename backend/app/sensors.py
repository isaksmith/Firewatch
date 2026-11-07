"""Mesh sensor nodes: temperature, humidity, gas resistance, particulate, and power (docs/DESIGN.md section 5.8).

Tower relays carry a PMSA003I particulate sensor and a temperature and humidity sensor, and Meshtastic sends
their readings as telemetry. A smoke signal needs all three of:

- PM2.5 well above the node's own recent baseline;
- a fine-particle mix (PM2.5 / PM10) that looks like smoke, not wind-blown dust, which is coarse;
- a jump that distant sensors aren't seeing too, which would be regional smoke such as Flint Hills burn season.

Temperature and humidity replace the gridded forecast's values near live (non-sample) events.
"""

import sqlite3
from datetime import datetime, timedelta
from statistics import median

from .config import get_settings
from .db import iso, parse_iso, utcnow
from .geo import haversine_km

DEFAULTS = {
    "smoke_pm25_rise": 50,  # µg/m³ above the node's baseline
    "smoke_fine_ratio": 0.6,  # PM2.5 / PM10 at or above this looks like smoke
    "smoke_regional_share": 0.5,  # this share of other sensors jumping too means regional smoke
    "smoke_repeat_min": 60,
}
BASELINE = timedelta(hours=3)
BASELINE_GAP = timedelta(minutes=20)
DEFAULT_BASELINE = 10.0
FRESH = timedelta(minutes=30)
LOCAL_WEATHER_KM = 15.0
REGIONAL_KM = 15.0


def _settings() -> dict:
    from .district import load_district

    try:
        return {**DEFAULTS, **load_district().settings}
    except FileNotFoundError:
        return dict(DEFAULTS)


def store(conn: sqlite3.Connection, nid: str, telemetry: dict, at: datetime) -> tuple[float | None, float | None] | None:
    """Store one telemetry packet's readings at `at`; returns (pm25, pm10), or None if it carried no readings.

    Power readings come from Meshtastic power telemetry: channel 1 is the battery pack, channel 2 the solar panel.
    The sample counters go up by one each time the firmware reads that sensor successfully.
    """
    env = telemetry.get("environmentMetrics") or {}
    aq = telemetry.get("airQualityMetrics") or {}
    pw = telemetry.get("powerMetrics") or {}
    fw = telemetry.get("firewatchMetrics") or {}  # FireWatch firmware: per-sensor sample counters
    temp, rh = env.get("temperature"), env.get("relativeHumidity")
    gas = env.get("gasResistance")  # MΩ in Meshtastic
    pm25 = aq.get("pm25Environmental", aq.get("pm25Standard"))
    pm10 = aq.get("pm100Environmental", aq.get("pm100Standard"))
    row = {
        "temp_c": temp, "rh_pct": rh, "pm25": pm25, "pm10": pm10,
        "gas_kohm": gas * 1000 if gas is not None else None, "pressure_hpa": env.get("barometricPressure"),
        "pack_v": pw.get("ch1Voltage"), "pack_ma": pw.get("ch1Current"),
        "solar_v": pw.get("ch2Voltage"), "solar_ma": pw.get("ch2Current"),
        "env_seq": fw.get("envSeq"), "pm_seq": fw.get("pmSeq"),
    }
    if all(v is None for v in row.values()):
        return None
    conn.execute(
        f"INSERT INTO sensor_readings(node_id, at, {', '.join(row)}) VALUES (?, ?, {', '.join('?' * len(row))})",
        (nid, iso(at), *row.values()),
    )
    return pm25, pm10


def record(conn: sqlite3.Connection, nid: str, telemetry: dict, weather: dict | None = None) -> int | None:
    """Store one telemetry packet's readings; returns the event id if it raised a smoke signal."""
    at = utcnow()
    pm_seq = (telemetry.get("firewatchMetrics") or {}).get("pmSeq")
    prev = conn.execute(
        "SELECT pm_seq FROM sensor_readings WHERE node_id = ? AND pm_seq IS NOT NULL ORDER BY id DESC LIMIT 1", (nid,)
    ).fetchone() if pm_seq is not None else None
    stored = store(conn, nid, telemetry, at)
    if stored is None or stored[0] is None:
        return None
    if prev and prev["pm_seq"] == pm_seq:
        return None  # a resent sample from a stalled sensor is not new evidence
    pm25, pm10 = stored
    return check_smoke(conn, nid, float(pm25), float(pm10) if pm10 is not None else None, at, weather)


def simulated(conn, nid: str) -> bool:
    r = conn.execute("SELECT simulated FROM sensor_nodes WHERE node_id = ?", (nid,)).fetchone()
    return bool(r and r["simulated"])


def baseline(conn, nid: str, at: datetime) -> float:
    """Median PM2.5 over the previous 3 hours, leaving out the last 20 minutes so a growing plume can't hide."""
    rows = conn.execute(
        "SELECT pm25 FROM sensor_readings WHERE node_id = ? AND pm25 IS NOT NULL AND at BETWEEN ? AND ?",
        (nid, iso(at - BASELINE), iso(at - BASELINE_GAP)),
    ).fetchall()
    return median(r["pm25"] for r in rows) if len(rows) >= 3 else DEFAULT_BASELINE


def _distant_rises(conn, nid: str, at: datetime) -> list[float]:
    """PM2.5 rise at each sensor far enough away that it can't be smelling the same fire."""
    me = conn.execute("SELECT lat, lon FROM mesh_nodes WHERE node_id = ?", (nid,)).fetchone()
    # Simulated sensors are only compared with each other, never with real ones.
    rows = conn.execute(
        "SELECT r.node_id, r.pm25, n.lat, n.lon FROM sensor_readings r JOIN mesh_nodes n ON n.node_id = r.node_id "
        "LEFT JOIN sensor_nodes s ON s.node_id = r.node_id "
        "WHERE r.node_id != ? AND r.pm25 IS NOT NULL AND r.at >= ? AND n.lat IS NOT NULL "
        "AND COALESCE(s.simulated, 0) = ? "
        "AND r.id = (SELECT MAX(id) FROM sensor_readings WHERE node_id = r.node_id AND pm25 IS NOT NULL)",
        (nid, iso(at - FRESH), int(simulated(conn, nid))),
    ).fetchall()
    return [
        r["pm25"] - baseline(conn, r["node_id"], at) for r in rows
        if haversine_km(me["lat"], me["lon"], r["lat"], r["lon"]) > REGIONAL_KM
    ]


def smoke_verdict(conn, nid: str, pm25: float, pm10: float | None, at: datetime) -> tuple[bool, str]:
    cfg = _settings()
    base = baseline(conn, nid, at)
    if pm25 - base < cfg["smoke_pm25_rise"]:
        return False, f"PM2.5 {pm25:.0f}, usual {base:.0f}"
    if pm10 and pm25 / pm10 < cfg["smoke_fine_ratio"]:
        return False, f"coarse particles (PM2.5/PM10 {pm25 / pm10:.2f}): dust, not smoke"
    others = _distant_rises(conn, nid, at)
    if len(others) >= 2:
        share = sum(r >= cfg["smoke_pm25_rise"] / 2 for r in others) / len(others)
        if share >= cfg["smoke_regional_share"]:
            return False, f"{share:.0%} of other sensors rose too: regional smoke"
    ratio = f", PM2.5/PM10 {pm25 / pm10:.2f}" if pm10 else ""
    return True, f"PM2.5 {pm25:.0f} µg/m³ (usual {base:.0f}){ratio}"


def check_smoke(conn, nid: str, pm25: float, pm10: float | None, at: datetime, weather: dict | None = None) -> int | None:
    from . import scenario
    from .confirm import evaluate_event
    from .signals import add_signal

    node = conn.execute("SELECT lat, lon FROM mesh_nodes WHERE node_id = ?", (nid,)).fetchone()
    if node is None or node["lat"] is None:
        return None  # a tower node needs a fixed position set in Meshtastic
    smoke, why = smoke_verdict(conn, nid, pm25, pm10, at)
    if not smoke:
        return None
    repeat = timedelta(minutes=_settings()["smoke_repeat_min"])
    if conn.execute(
        "SELECT 1 FROM signals WHERE kind = 'sensor_smoke' AND source = ? AND created_at >= ?",
        (f"mesh:{nid}", iso(at - repeat)),
    ).fetchone():
        return None
    env = latest_env(conn, nid, at)
    if env:
        why += f", {env['temp_c']:.0f}°C RH {env['rh_pct']:.0f}%"
    replay_now = scenario.running_now()
    eid = add_signal(
        conn, "sensor_smoke", node["lat"], node["lon"], iso(replay_now or at), f"mesh:{nid}", why,
        is_sample=replay_now is not None or get_settings().mode == "sample" or simulated(conn, nid),
    )
    evaluate_event(conn, eid, weather, replay_now or at)
    return eid


def latest_env(conn, nid: str, at: datetime) -> dict | None:
    r = conn.execute(
        "SELECT temp_c, rh_pct, at FROM sensor_readings WHERE node_id = ? AND temp_c IS NOT NULL AND rh_pct IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (nid,),
    ).fetchone()
    return dict(r) if r and at - parse_iso(r["at"]) <= FRESH else None


def local_weather(conn, lat: float, lon: float, weather: dict) -> dict:
    """The forecast with temperature and humidity from the nearest fresh sensor within 15 km, if there is one."""
    now = utcnow()
    best = None
    for n in conn.execute(
        "SELECT n.node_id, n.lat, n.lon FROM mesh_nodes n LEFT JOIN sensor_nodes s ON s.node_id = n.node_id "
        "WHERE n.lat IS NOT NULL AND COALESCE(s.simulated, 0) = 0"
    ):
        km = haversine_km(lat, lon, n["lat"], n["lon"])
        if km <= LOCAL_WEATHER_KM and (env := latest_env(conn, n["node_id"], now)) and (best is None or km < best[0]):
            best = (km, n["node_id"], env)
    if best is None:
        return weather
    km, nid, env = best
    return {**weather, "temp_c": env["temp_c"], "rh_pct": env["rh_pct"], "local_sensor": f"{nid} ({km:.1f} km)"}


def latest_readings(conn, nid: str) -> dict:
    out = {}
    for col in ("temp_c", "rh_pct", "pm25", "pm10", "gas_kohm", "pressure_hpa", "pack_v", "pack_ma", "solar_v", "solar_ma"):
        r = conn.execute(
            f"SELECT {col} v, at FROM sensor_readings WHERE node_id = ? AND {col} IS NOT NULL ORDER BY id DESC LIMIT 1",
            (nid,),
        ).fetchone()
        if r:
            out[col] = r["v"]
            out["reading_at"] = max(out.get("reading_at", ""), r["at"])
    return out
