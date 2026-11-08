"""Simulated sensor network (SENSOR_SIM=1), for demos before real nodes are in the ground.

It installs the region planner's plots, relays, and station bridge for the district as Meshtastic radios, then
sends their telemetry through the same packet handler a real radio's packets go through. Sensor nodes also send
the FireWatch firmware's per-sensor sample counters. A day of history is
backfilled so battery and solar checks have a night and a day to read. A few nodes get faults a field season
would turn up (a worn pack, a dirty panel, a drifting gas head, a blocked PM inlet, a sensor that stalls while the
radio keeps reporting, a node gone silent), so the health checks have something to find.

Everything it writes is marked simulated: its smoke signals are sample events that never text anyone, and its
temperatures never stand in for the forecast. Meshtastic sends each telemetry variant as its own packet; the
simulator folds them into one per report to keep the table small.
"""

import json
import logging
import math
import random
from datetime import datetime, timedelta

from . import mesh, planner, sensors
from .config import get_settings
from .db import iso, loads, parse_iso, utcnow
from .geo import haversine_km
from .sensor_health import PACK_WH, PANEL_W, volts

log = logging.getLogger(__name__)
TICK_S = 120
BACKFILL = timedelta(hours=26)
BACKFILL_STEP = timedelta(minutes=10)
KEEP = timedelta(hours=30)
PLUME = timedelta(minutes=20)
PLUME_KM = 0.6  # a plume reaches the nodes on one plot, not the next plot over
NODE_BASE = 0xF1000000
RELAY_BASE = 0xF1EE0000
BRIDGE_NUM = 0xF1EEFF00
YIELD = 0.6  # net panel yield after angle, heat, and charger loss (README "Energy budget")
LOAD_W = {"bare": 0.12, "rich": 0.27, "relay": 0.15}  # average draw; rich includes the PM fan at 25% duty


def _num(nid: str) -> int:
    return int(nid[1:], 16)


def _sun(lon: float, at: datetime) -> float:
    """0 at night to 1 at solar noon; a November day of about ten hours."""
    h = (at.hour + at.minute / 60 + lon / 15) % 24
    return max(0.0, math.sin(math.pi * (h - 7) / 10)) if 7 <= h <= 17 else 0.0


def _cloud(at: datetime) -> float:
    """Share of clear-sky sun that gets through, the same across the district on a given day."""
    return random.Random(at.date().isoformat()).uniform(0.6, 1.0)


def _weather(lon: float, at: datetime) -> tuple[float, float, float]:
    h = (at.hour + at.minute / 60 + lon / 15) % 24
    warm = math.sin(math.pi * (h - 9) / 12) if 9 <= h <= 21 else -0.5
    temp = 10 + 9 * warm
    rh = min(95.0, max(15.0, 55 - 25 * warm))
    pressure = 1016 + 3 * math.sin(at.timestamp() / 86400 * math.pi)
    return temp, rh, pressure


def _plan(slug: str) -> dict:
    region = planner.resolve_region(f"district:{slug}")
    try:
        return planner.plan_region(region)
    except Exception:
        log.warning("climate fetch failed; planning the simulated network from cached climate")
        return planner.plan_region(region, fetch_climate=False)


def _nodes_from_plan(plan: dict, rng: random.Random) -> list[dict]:
    st = plan["station"]
    bridge = mesh.node_id(BRIDGE_NUM)
    relays = {r["name"]: mesh.node_id(RELAY_BASE + i + 1) for i, r in enumerate(plan["relays"])}
    relays[st["name"]] = bridge

    def installed(lo: str = "2025-09-01", hi: str = "2026-06-01") -> str:
        a, b = parse_iso(lo + "T15:00:00Z"), parse_iso(hi + "T15:00:00Z")
        return iso(a + (b - a) * rng.random())

    out = [{"node_id": bridge, "kind": "bridge", "tier": None, "site": None, "label": f"{st['name']} bridge",
            "short": "BRDG", "lat": st["lat"], "lon": st["lon"], "via": None, "installed_at": installed()}]
    for i, r in enumerate(plan["relays"]):
        out.append({"node_id": relays[r["name"]], "kind": "relay", "tier": None, "site": None,
                    "label": f"Relay {i + 1}: {r['name']}", "short": f"RLY{i + 1}", "lat": r["lat"], "lon": r["lon"],
                    "via": relays.get(r["uplink"], bridge), "installed_at": installed()})
    for s in plan["sites"]:
        via = relays.get((s.get("gateway") or {}).get("name"), bridge)
        counts = {"bare": 0, "rich": 0}
        for j, n in enumerate(s["nodes"]):
            counts[n["tier"]] += 1
            tag = f"{'R' if n['tier'] == 'rich' else 'B'}{counts[n['tier']]}"
            out.append({"node_id": mesh.node_id(NODE_BASE + s["id"] * 0x100 + j), "kind": "sensor", "tier": n["tier"],
                        "site": s["id"], "label": f"Plot {s['id']} {n['tier']} {tag}", "short": f"P{s['id']}{tag}"[:4],
                        "lat": n["lat"], "lon": n["lon"], "via": via, "installed_at": installed()})
    return out


def _faults(nodes: list[dict], rng: random.Random, now: datetime) -> None:
    """Give a few nodes the problems a field season turns up."""
    bare = [n for n in nodes if n["tier"] == "bare"]
    rich = [n for n in nodes if n["tier"] == "rich"]
    picks = rng.sample(bare, 7) + rng.sample(rich, 4)
    for n, fault in zip(picks, [
        {"capacity": 0.58}, {"panel": 0.15}, {"panel": 0.0, "soc": 0.3}, {"gas_drift": 0.38},
        {"env_stall_at": iso(now - timedelta(minutes=45))},
        {"snr": -14.5}, {"offline_at": iso(now - timedelta(hours=3, minutes=20))},
        {"capacity": 0.75}, {"pm_blocked": True}, {"pm_old": True},
        {"pm_stall_at": iso(now - timedelta(minutes=50))},
    ]):
        n["fault"] = fault
        if fault.get("pm_old"):
            n["installed_at"] = "2024-08-20T15:00:00Z"
    relay = next(n for n in nodes if n["kind"] == "relay")
    relay["fault"] = {"panel": 0.2, "soc": 0.25}


def _state(n: dict, rng: random.Random) -> dict:
    f = n.get("fault") or {}
    return {
        "soc": f.get("soc", rng.uniform(0.7, 0.95)),
        "gas_base": rng.uniform(90, 180),
        "pm_base": rng.uniform(4, 9),
        "snr": f.get("snr", rng.uniform(5, 10) if n["kind"] != "sensor" else rng.uniform(-6, 8)),
        "fault": f,
        "plume_until": None,
        "env_seq": rng.randrange(1000, 9000),  # firmware sample counters, one per sensor
        "pm_seq": rng.randrange(1000, 9000),
        "last_env": None,
        "last_pm": None,
    }


def _stalled(f: dict, key: str, at: datetime) -> bool:
    return bool(f.get(key)) and at >= parse_iso(f[key])


def _step(n: dict, st: dict, at: datetime, hours: float, rng: random.Random) -> dict:
    """Advance one node's charge by `hours` and return the telemetry it reports at `at`."""
    kind = n["tier"] or n["kind"]
    f = st["fault"]
    telemetry: dict = {}
    if kind in PACK_WH:
        solar_w = PANEL_W[kind] * YIELD * _sun(n["lon"], at) * _cloud(at) * f.get("panel", 1.0)
        load_w = LOAD_W[kind]
        cap_wh = PACK_WH[kind] * f.get("capacity", 1.0)
        st["soc"] = min(1.0, max(0.0, st["soc"] + (solar_w - load_w) * hours / cap_wh))
        v = volts(st["soc"]) + rng.uniform(-0.004, 0.004)
        full = st["soc"] >= 1.0
        net_ma = 0.0 if full else (solar_w - load_w) / v * 1000
        if full:
            solar_w = load_w if solar_w > load_w else solar_w  # charger stops taking more than the load
        solar_v = (5.6 if kind == "bare" else 5.2) if solar_w > 0 else 0.0
        telemetry["powerMetrics"] = {
            "ch1Voltage": round(v, 3), "ch1Current": round(net_ma, 1),
            "ch2Voltage": solar_v, "ch2Current": round(solar_w / solar_v * 1000, 1) if solar_v else 0.0,
        }
        telemetry["deviceMetrics"] = {"batteryLevel": round(st["soc"] * 100), "voltage": round(v, 3)}
    if n["kind"] == "sensor":
        temp, rh, pressure = _weather(n["lon"], at)
        temp += rng.uniform(-0.4, 0.4)
        rh += rng.uniform(-1.5, 1.5)
        smoky = st["plume_until"] and at <= parse_iso(st["plume_until"])
        gas = st["gas_base"] * (1 + f.get("gas_drift", 0)) * (1 - 0.004 * (rh - 40)) * rng.uniform(0.97, 1.03)
        if smoky:
            gas *= rng.uniform(0.4, 0.55)  # reducing gases in smoke pull the heated element's resistance down
            temp += 1.5
        # A stalled sensor takes no new sample: the firmware resends its last one with the same counter.
        if _stalled(f, "env_stall_at", at) and st["last_env"]:
            telemetry["environmentMetrics"] = st["last_env"]
        else:
            st["env_seq"] += 1
            st["last_env"] = telemetry["environmentMetrics"] = {
                "temperature": round(temp, 1), "relativeHumidity": round(rh, 1),
                "barometricPressure": round(pressure, 1), "gasResistance": round(gas / 1000, 5),
            }
        telemetry["firewatchMetrics"] = {"envSeq": st["env_seq"]}
        if n["tier"] == "rich" and _stalled(f, "pm_stall_at", at) and st["last_pm"]:
            telemetry["airQualityMetrics"] = st["last_pm"]
            telemetry["firewatchMetrics"]["pmSeq"] = st["pm_seq"]
        elif n["tier"] == "rich":
            if f.get("pm_blocked"):
                pm25 = pm10 = 0
            elif smoky:
                pm25 = round(rng.uniform(140, 240))
                pm10 = round(pm25 * rng.uniform(1.1, 1.25))
            else:
                pm25 = max(0, round(st["pm_base"] + rng.uniform(-2, 2)))
                pm10 = round(pm25 * rng.uniform(1.4, 1.9))
            st["pm_seq"] += 1
            st["last_pm"] = telemetry["airQualityMetrics"] = {"pm25Environmental": pm25, "pm100Environmental": pm10}
            telemetry["firewatchMetrics"]["pmSeq"] = st["pm_seq"]
    return telemetry


def _packet(n: dict, st: dict, telemetry: dict, rng: random.Random) -> dict:
    return {
        "from": _num(n["node_id"]), "fromId": n["node_id"], "rxSnr": round(st["snr"] + rng.uniform(-1.5, 1.5), 1),
        "decoded": {"portnum": "TELEMETRY_APP", "telemetry": telemetry},
    }


def installed(conn) -> bool:
    return conn.execute("SELECT 1 FROM sensor_nodes WHERE simulated = 1 LIMIT 1").fetchone() is not None


def clear(conn) -> None:
    ids = [r["node_id"] for r in conn.execute("SELECT node_id FROM sensor_nodes WHERE simulated = 1")]
    for t in ("sensor_readings", "mesh_nodes", "sensor_nodes"):
        conn.executemany(f"DELETE FROM {t} WHERE node_id = ?", [(i,) for i in ids])


def seed(conn, now: datetime | None = None) -> int:
    """Install the simulated network and backfill a day of telemetry. Returns the number of nodes."""
    now = now or utcnow()
    slug = get_settings().district
    rng = random.Random(f"firewatch-sim:{slug}")
    nodes = _nodes_from_plan(_plan(slug), rng)
    _faults(nodes, rng, now)
    clear(conn)
    for n in nodes:
        st = _state(n, rng)
        offline_at = parse_iso(st["fault"]["offline_at"]) if st["fault"].get("offline_at") else None
        t = now - BACKFILL
        last = t
        while t <= now and (offline_at is None or t <= offline_at):
            telemetry = _step(n, st, t, (t - last).total_seconds() / 3600, rng)
            if telemetry:
                sensors.store(conn, n["node_id"], telemetry, t)
            last = t
            t += BACKFILL_STEP
        st["at"] = iso(last)
        baseline = {"gas_kohm": round(st["gas_base"], 1)} if n["kind"] == "sensor" else None
        conn.execute(
            "INSERT INTO sensor_nodes(node_id, kind, tier, site, label, lat, lon, via, installed_at, baseline_json, "
            "simulated, sim_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (n["node_id"], n["kind"], n["tier"], n["site"], n["label"], n["lat"], n["lon"], n["via"], n["installed_at"],
             json.dumps(baseline) if baseline else None, json.dumps(st)),
        )
        battery = round(st["soc"] * 100) if (n["tier"] or n["kind"]) in PACK_WH else None
        conn.execute(
            "INSERT INTO mesh_nodes(node_id, long_name, short_name, hw_model, lat, lon, position_at, battery_pct, snr, "
            "last_heard) VALUES (?, ?, ?, 'RAK4631', ?, ?, ?, ?, ?, ?)",
            (n["node_id"], n["label"], n["short"], n["lat"], n["lon"], n["installed_at"], battery,
             round(st["snr"], 1), iso(last)),
        )
    log.info("simulated sensor network: %d nodes for %s", len(nodes), slug)
    return len(nodes)


def tick(conn, now: datetime | None = None, only: list[str] | None = None) -> list[int]:
    """Send one report from every simulated node that is up. Returns the events any smoke signals raised."""
    now = now or utcnow()
    rng = random.Random()
    events = []
    q = "SELECT * FROM sensor_nodes WHERE simulated = 1"
    for r in conn.execute(q).fetchall():
        if only is not None and r["node_id"] not in only:
            continue
        st = loads(r["sim_json"])
        if st["fault"].get("offline_at"):
            continue
        hours = (now - parse_iso(st["at"])).total_seconds() / 3600
        telemetry = _step(dict(r), st, now, hours, rng)
        st["at"] = iso(now)
        conn.execute("UPDATE sensor_nodes SET sim_json = ? WHERE node_id = ?", (json.dumps(st), r["node_id"]))
        mesh.handle_packet(conn, _packet(dict(r), st, telemetry, rng), None)
        eid = conn.execute(
            "SELECT event_id FROM signals WHERE kind = 'sensor_smoke' AND source = ? AND created_at >= ? "
            "ORDER BY id DESC LIMIT 1", (f"mesh:{r['node_id']}", iso(now - timedelta(seconds=5))),
        ).fetchone()
        if eid and eid["event_id"] not in events:
            events.append(eid["event_id"])
    conn.execute(
        "DELETE FROM sensor_readings WHERE at < ? AND node_id IN (SELECT node_id FROM sensor_nodes WHERE simulated = 1)",
        (iso(now - KEEP),),
    )
    return events


def plume(conn, nid: str, now: datetime | None = None) -> dict:
    """Send smoke over the plot `nid` sits on for the next 20 minutes, and report from its nodes right away."""
    now = now or utcnow()
    me = conn.execute("SELECT lat, lon FROM sensor_nodes WHERE node_id = ? AND simulated = 1", (nid,)).fetchone()
    if me is None:
        raise KeyError(nid)
    hit = []
    for r in conn.execute("SELECT node_id, lat, lon, sim_json FROM sensor_nodes WHERE simulated = 1 AND kind = 'sensor'").fetchall():
        if haversine_km(me["lat"], me["lon"], r["lat"], r["lon"]) <= PLUME_KM:
            st = loads(r["sim_json"])
            st["plume_until"] = iso(now + PLUME)
            conn.execute("UPDATE sensor_nodes SET sim_json = ? WHERE node_id = ?", (json.dumps(st), r["node_id"]))
            hit.append(r["node_id"])
    return {"nodes": hit, "until": iso(now + PLUME), "events": tick(conn, now, only=hit)}
