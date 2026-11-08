"""Field hardware health, read from the telemetry each node sends (sensors/README.md, "Power, sensing, and
operating limits").

Every check works only from what arrived over the mesh, so a check with no data says so rather than guessing.
Radio health and sensor health are separate. No heartbeat means the radio link is down, cause unknown. Heartbeats
that keep arriving while the firmware's per-sensor sample counter stops advancing mean the sensor is stale. A node
is healthy only when both are. The service intervals below are placeholders until the first field season sets
real ones.
"""

from datetime import datetime, timedelta
from statistics import median

from .db import loads, parse_iso

STATUSES = ("ok", "watch", "service", "replace", "stale", "offline")
STALE_REPORTS = 3  # reports in a row with the same sample counter
LATE_MIN = 30  # three missed reports at the planned 10-minute summary interval
OFFLINE_MIN = 120
WEAK_SNR_DB = -12.0
HISTORY = timedelta(hours=26)  # long enough to hold one whole night and one whole day

# Nominal pack energy (Wh) and panel rating (W). Relays are budgeted like a rich node's power system.
PACK_WH = {"bare": 16.3, "rich": 24.4, "relay": 24.4}
PANEL_W = {"bare": 2.0, "rich": 5.0, "relay": 5.0}
# Open-circuit voltage to state of charge for a 1S Li-ion pack; a rough curve, not a calibrated one.
SOC_CURVE = [(3.0, 0.0), (3.45, 0.05), (3.68, 0.3), (3.8, 0.6), (3.95, 0.8), (4.2, 1.0)]
NIGHT_MIN_H = 4.0
SOLAR_DARK_MA = 1.0
# Assumed replacement intervals, to be set from the first field season's inspections.
BATTERY_LIFE_D = 3 * 365
PM_LIFE_D = 2 * 365
PM_DUTY = 0.25  # 45 s awake every 3 min (README "Particulate warm-up")
GAS_DRIFT_WATCH, GAS_DRIFT_REPLACE = 0.3, 0.5
FROZEN_READINGS = 8


def soc(v: float) -> float:
    if v <= SOC_CURVE[0][0]:
        return 0.0
    for (v0, s0), (v1, s1) in zip(SOC_CURVE, SOC_CURVE[1:]):
        if v <= v1:
            return s0 + (s1 - s0) * (v - v0) / (v1 - v0)
    return 1.0


def volts(s: float) -> float:
    """Inverse of soc(), for the simulator."""
    s = min(max(s, 0.0), 1.0)
    for (v0, s0), (v1, s1) in zip(SOC_CURVE, SOC_CURVE[1:]):
        if s <= s1:
            return v0 + (v1 - v0) * (s - s0) / (s1 - s0)
    return SOC_CURVE[-1][0]


def worst(statuses) -> str:
    return max(statuses, key=STATUSES.index, default="ok")


def _check(key: str, part: str, status: str, value: str, detail: str, action: str | None = None) -> dict:
    return {"key": key, "part": part, "status": status, "value": value, "detail": detail, "action": action}


def history(conn, nid: str, now: datetime) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM sensor_readings WHERE node_id = ? AND at >= ? ORDER BY at",
        (nid, (now - HISTORY).strftime("%Y-%m-%dT%H:%M:%SZ")),
    )]


def solar_peak_w(rows: list[dict]) -> float | None:
    p = [r["solar_v"] * r["solar_ma"] / 1000 for r in rows if r["solar_v"] is not None and r["solar_ma"] is not None]
    return max(p) if p else None


def _last_night(rows: list[dict]) -> list[dict]:
    """The longest stretch of readings with no solar charge, if it lasts at least NIGHT_MIN_H."""
    best, run = [], []
    for r in rows:
        if r["pack_v"] is None or r["solar_ma"] is None:
            continue
        if r["solar_ma"] <= SOLAR_DARK_MA:
            run.append(r)
            if len(run) > len(best):
                best = list(run)
        else:
            run = []
    if len(best) < 2 or (parse_iso(best[-1]["at"]) - parse_iso(best[0]["at"])).total_seconds() < NIGHT_MIN_H * 3600:
        return []
    return best


def capacity_share(rows: list[dict], nominal_wh: float) -> float | None:
    """Usable pack energy as a share of nominal: energy drawn overnight over the fall in charge it caused."""
    night = _last_night(rows)
    if not night:
        return None
    wh = 0.0
    for a, b in zip(night, night[1:]):
        hours = (parse_iso(b["at"]) - parse_iso(a["at"])).total_seconds() / 3600
        wh += a["pack_v"] * max(-(a["pack_ma"] or 0), 0) / 1000 * hours
    drop = soc(night[0]["pack_v"]) - soc(night[-1]["pack_v"])
    if drop < 0.03 or wh <= 0:
        return None
    return wh / drop / nominal_wh


def _age_days(installed_at: str, now: datetime) -> float:
    return (now - parse_iso(installed_at)).total_seconds() / 86400


def _radio(node: dict, now: datetime) -> list[dict]:
    heard = (now - parse_iso(node["last_heard"])).total_seconds() / 60 if node.get("last_heard") else None
    if heard is None:
        return [_check("radio", "Radio link", "offline", "never heard", "No packet has reached the station.",
                       "Visit the site: check power and antenna")]
    ago = f"heard {round(heard)} min ago" if heard < 120 else f"heard {heard / 60:.1f} h ago"
    if heard >= OFFLINE_MIN:
        return [_check("radio", "Radio link", "offline", ago, "Radio link down, cause unknown: no heartbeat. Check power, "
                       "the radio path, and the relay it reports through.", "Radio link down: check power, antenna, and relay")]
    out = []
    if heard >= LATE_MIN:
        out.append(_check("radio", "Radio link", "watch", ago, "Missed several reports.", "Check the relay it reports through"))
    snr = node.get("snr")
    if snr is not None and snr < WEAK_SNR_DB:
        out.append(_check("snr", "Antenna / signal", "watch", f"SNR {snr:.0f} dB",
                          "Weak signal at the next hop: packets may drop in bad weather.",
                          "Check the antenna and its cable; consider a relay"))
    if not out:
        out.append(_check("radio", "Radio link", "ok", ago + (f" · SNR {snr:.0f} dB" if snr is not None else ""), "Reporting normally."))
    return out


def _battery(node: dict, rows: list[dict], now: datetime) -> list[dict]:
    kind = node["tier"] or node["kind"]
    if kind not in PACK_WH:
        return []
    v = next((r["pack_v"] for r in reversed(rows) if r["pack_v"] is not None), None)
    if v is None:
        return [_check("battery", "Battery pack", "watch", "no data", "No pack-voltage telemetry yet; the charge is "
                       "unknown, not assumed.")]
    out = []
    charge = soc(v)
    share = capacity_share(rows, PACK_WH[kind])
    age = _age_days(node["installed_at"], now)
    value = f"{v:.2f} V · {charge:.0%}"
    if share is not None:
        value += f" · holds ~{min(share, 1):.0%}"
    if share is not None and share < 0.7:
        out.append(_check("battery", "Battery pack", "replace", value,
                          f"Holds about {share:.0%} of its rated {PACK_WH[kind]} Wh, from last night's discharge. "
                          "It may not last a cloudy stretch.", f"Replace the {PACK_WH[kind]} Wh pack"))
    elif charge < 0.08:
        out.append(_check("battery", "Battery pack", "service", value, "Nearly empty: the node may shut down overnight.",
                          "Check the panel and charger"))
    elif share is not None and share < 0.8:
        out.append(_check("battery", "Battery pack", "watch", value,
                          f"Holds about {share:.0%} of rated capacity: wearing out.", "Plan a pack replacement"))
    elif charge < 0.2:
        out.append(_check("battery", "Battery pack", "watch", value, "Low charge.", "Check the panel is charging"))
    elif age > BATTERY_LIFE_D:
        out.append(_check("battery", "Battery pack", "watch", value, f"In service {age / 365:.1f} years, past the "
                          "assumed 3-year interval.", "Plan a pack replacement"))
    else:
        detail = "Capacity can't be estimated until it has run through a night." if share is None else "Healthy."
        out.append(_check("battery", "Battery pack", "ok", value, detail))
    return out


def _solar(node: dict, rows: list[dict], network_ratio: float | None) -> list[dict]:
    kind = node["tier"] or node["kind"]
    if kind not in PANEL_W:
        return []
    peak = solar_peak_w(rows)
    if peak is None:
        return [_check("solar", "Solar panel", "watch", "no data", "No panel telemetry yet.")]
    ratio = peak / PANEL_W[kind]
    value = f"peak {peak:.1f} W of {PANEL_W[kind]:.0f} W"
    if peak < 0.05:
        return [_check("solar", "Solar panel", "replace", value, "No charge current in the last day, even in daylight.",
                       "Check the panel lead and adapter; replace the panel if it is damaged")]
    if network_ratio and ratio < 0.45 * network_ratio:
        return [_check("solar", "Solar panel", "service", value,
                       f"Made {ratio / network_ratio:.0%} of what other panels on the network did yesterday.",
                       "Clean the panel and check it isn't shaded or knocked off its aim")]
    return [_check("solar", "Solar panel", "ok", value, "Charging normally.")]


SENSOR_COUNTERS = (("env_seq", "Environmental head (BME680)"), ("pm_seq", "Particulate sensor (PMSA003I)"))


def _samples(node: dict, rows: list[dict], now: datetime) -> list[dict]:
    """Stale sensors: the radio keeps reporting but a sensor's sample counter has stopped advancing."""
    if node["kind"] != "sensor":
        return []
    out = []
    for col, part in SENSOR_COUNTERS:
        if col == "pm_seq" and node["tier"] != "rich":
            continue
        seqs = [(r[col], r["at"]) for r in rows if r[col] is not None]
        if not seqs:
            continue  # firmware without the FireWatch counter: no way to tell, so no claim either way
        last = seqs[-STALE_REPORTS:]
        if len(last) == STALE_REPORTS and len({v for v, _ in last}) == 1:
            since = next(at for v, at in seqs if v == last[-1][0])
            mins = round((now - parse_iso(since)).total_seconds() / 60)
            out.append(_check(f"stale_{col}", part, "stale", f"no new sample for {mins} min (stuck at #{last[-1][0]})",
                              "Stale sensor: the radio still reports, but this sensor has taken no new sample.",
                              f"Stale sensor, may need replacement: inspect the {part.split(' (')[0].lower()}"))
    if not out and any(r["env_seq"] is not None for r in rows):
        out.append(_check("samples", "Sensor samples", "ok", "counters advancing", "Every sensor is taking new samples."))
    return out


def _gas(node: dict, rows: list[dict], now: datetime) -> list[dict]:
    if node["kind"] != "sensor":
        return []
    part = "Gas sensor (BME680)"
    gas = [r["gas_kohm"] for r in rows if r["gas_kohm"] is not None]
    if not gas:
        return [_check("gas", part, "service", "no data", "The node reports but its environmental head doesn't.",
                       "Reseat the head's cable; replace the head if it stays silent")]
    recent = gas[-FROZEN_READINGS:]
    has_counter = any(r["env_seq"] is not None for r in rows)  # with a counter, the stale check covers this
    if not has_counter and len(recent) == FROZEN_READINGS and max(recent) - min(recent) < 1e-6:
        return [_check("gas", part, "replace", f"{recent[-1]:.0f} kΩ, unchanged",
                       f"The last {FROZEN_READINGS} readings are identical: the sensor or its driver has stopped updating.",
                       "Replace the environmental head")]
    base = (loads(node.get("baseline_json")) or {}).get("gas_kohm")
    six_h = [r["gas_kohm"] for r in rows if r["gas_kohm"] is not None and parse_iso(r["at"]) >= now - timedelta(hours=6)]
    now_kohm = median(six_h or recent)
    if not base:
        return [_check("gas", part, "ok", f"{now_kohm:.0f} kΩ", "No commissioning baseline to compare against.")]
    drift = now_kohm / base - 1
    value = f"{now_kohm:.0f} kΩ ({drift:+.0%} vs install)"
    if abs(drift) >= GAS_DRIFT_REPLACE:
        return [_check("gas", part, "replace", value, "Its clean-air baseline has moved too far to tell a smoke drop "
                       "from aging.", "Replace the environmental head")]
    if abs(drift) >= GAS_DRIFT_WATCH:
        return [_check("gas", part, "watch", value, "Clean-air baseline is drifting.", "Recalibrate the baseline on the "
                       "next visit")]
    return [_check("gas", part, "ok", value, "Baseline steady.")]


def _pm(node: dict, rows: list[dict], now: datetime, network_pm: float | None) -> list[dict]:
    if node["tier"] != "rich":
        return []
    part = "Particulate sensor (PMSA003I)"
    pm = [(r["pm25"], r["pm10"]) for r in rows if r["pm25"] is not None and parse_iso(r["at"]) >= now - timedelta(hours=3)]
    fan_h = _age_days(node["installed_at"], now) * 24 * PM_DUTY
    life_h = PM_LIFE_D * 24 * PM_DUTY
    fan = f"fan ~{fan_h:,.0f} h"
    if not pm:
        return [_check("pm", part, "service", f"no data · {fan}", "No particulate readings in 3 hours.",
                       "Check the PM adapter's flex cable and fan")]
    if all(p25 <= 0 and (p10 or 0) <= 0 for p25, p10 in pm) and (network_pm or 0) >= 2:
        return [_check("pm", part, "service", f"0 µg/m³ for 3 h · {fan}",
                       f"Reads zero while other rich nodes read about {network_pm:.0f}: the inlet is blocked or the fan "
                       "has stopped.", "Clean the insect screen and inlet; replace the sensor if it still reads zero")]
    value = f"PM2.5 {pm[-1][0]:.0f} µg/m³ · {fan}"
    if fan_h >= life_h:
        return [_check("pm", part, "replace", value, f"Fan has run about {fan_h:,.0f} h, past the assumed {life_h:,.0f} h "
                       "service life.", "Replace the PM sensor")]
    if fan_h >= 0.8 * life_h:
        return [_check("pm", part, "watch", value, f"Fan at {fan_h / life_h:.0%} of its assumed service life.",
                       "Order a spare PM sensor")]
    return [_check("pm", part, "ok", value, "Reading normally.")]


def assess(conn, node: dict, now: datetime, network: dict, rows: list[dict] | None = None) -> dict:
    """Health of one node. `node` joins sensor_nodes with mesh_nodes; `network` holds the network medians that
    a single node is compared against (solar_ratio, pm25)."""
    rows = history(conn, node["node_id"], now) if rows is None else rows
    checks = _radio(node, now)
    radio = "down" if checks[0]["status"] == "offline" else "ok"
    sensors = "n/a" if node["kind"] != "sensor" else "unknown" if radio == "down" else "ok"
    if radio == "ok":
        samples = _samples(node, rows, now)
        stale = {c["key"] for c in samples if c["status"] == "stale"}
        if stale:
            sensors = "stale"
        checks += samples + _battery(node, rows, now) + _solar(node, rows, network.get("solar_ratio"))
        # A stale sensor's last value is old news, so the checks that read its values are skipped.
        if "stale_env_seq" not in stale:
            checks += _gas(node, rows, now)
        if "stale_pm_seq" not in stale:
            checks += _pm(node, rows, now, network.get("pm25"))
    status = worst(c["status"] for c in checks)
    return {
        "status": status,
        "radio": radio,
        "sensors": sensors,
        "actions": [c["action"] for c in checks if c["status"] != "ok" and c["action"]],
        "checks": checks,
    }


def network_medians(conn, nodes: list[dict], now: datetime, rows_by_node: dict[str, list[dict]]) -> dict:
    ratios, pms = [], []
    for n in nodes:
        rows = rows_by_node.get(n["node_id"], [])
        kind = n["tier"] or n["kind"]
        if kind in PANEL_W and (peak := solar_peak_w(rows)) is not None:
            ratios.append(peak / PANEL_W[kind])
        if n["tier"] == "rich":
            recent = [r["pm25"] for r in rows if r["pm25"] is not None and parse_iso(r["at"]) >= now - timedelta(hours=3)]
            if recent:
                pms.append(median(recent))
    return {"solar_ratio": median(ratios) if ratios else None, "pm25": median(pms) if pms else None}
