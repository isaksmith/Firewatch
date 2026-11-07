"""The FW1 feed: one row per alert change (new, level change, cleared, not a fire), each holding its FW1 code.

`sync_event` runs wherever an alert's level or status can change. It compares the alert with the last row it wrote
for that event and adds a row only when something changed, so every change is coded, fed and radioed exactly once.
The rows serve GET /api/m/feed and go out on the Meshtastic district channel as the bare code.
"""

import json
import logging
import sqlite3
from datetime import datetime
from functools import lru_cache

from . import fw1
from .config import DATA_DIR
from .db import iso, loads
from .redflag import replay_forecast_red_flag
from .district import _dir, load_district
from .geo import bearing_deg, haversine_km

log = logging.getLogger(__name__)
PACK_CODES = {"cottonwood-creek": "cwc"}
DEFAULT_SCORE = {"escalate": 80, "investigate": 50, "monitor": 20}
PATH_KM = 5.0
PATH_HALF_ANGLE = 30.0
LEVELS = ("monitor", "investigate", "escalate")


@lru_cache(maxsize=8)
def pack_origin(code: str) -> tuple[float, float]:
    """(lat, lon) of the pack's origin, from the built pack, else the district's station 1."""
    path = DATA_DIR / "packs" / f"{code}.json"
    if path.exists():
        o = json.loads(path.read_text())["origin"]
        return o["lat"], o["lon"]
    st = load_district().settings["station"]
    return st["lat"], st["lon"]


def pack_for(ev) -> str | None:
    """The pack whose district holds the alert, else None (the feed only carries alerts a pack can place)."""
    try:
        d = load_district()
    except FileNotFoundError:
        return None
    if not d.contains(ev["lat"], ev["lon"]):
        return None
    return d.settings.get("pack_code") or PACK_CODES.get(d.slug, d.slug)


@lru_cache(maxsize=4)
def _homes(slug: str) -> tuple[tuple[float, float], ...]:
    path = _dir(slug) / "structures.geojson"
    if not path.exists():
        return ()
    out = []
    for f in json.loads(path.read_text())["features"]:
        p = f["properties"]
        if p.get("houses", 0) >= 1 or p.get("buildings", 0) >= 3:
            lon, lat = f["geometry"]["coordinates"]
            out.append((lat, lon))
    return tuple(out)


def _homes_in_path(ev, toward: float | None) -> bool:
    if toward is None:
        return False
    for lat, lon in _homes(load_district().slug):
        if haversine_km(ev["lat"], ev["lon"], lat, lon) <= PATH_KM:
            diff = abs((bearing_deg(ev["lat"], ev["lon"], lat, lon) - toward + 180) % 360 - 180)
            if diff <= PATH_HALF_ANGLE:
                return True
    return False


def _head(ev, now: datetime) -> tuple[float | None, float | None]:
    """(head direction in degrees toward, head speed in mph) from the ensemble forecast the playbook uses.

    Speed is the median head rate of spread. Direction is the bearing from the ignition to the farthest cell the
    median run has burned half an hour from now. Either is None when there is no forecast."""
    import math

    import numpy as np

    from . import playbook
    from .geo import KM_PER_DEG_LAT, km_per_deg_lon

    try:
        sit = playbook.situation_for_event(ev)
        now_min = max(0.0, (now - sit.ignition.time).total_seconds() / 60)
        horizon = min(300, int(math.ceil((now_min + playbook.HEADS_UP_WINDOW_MIN + 15) / 15) * 15))
        fc = playbook._forecast(ev, sit, horizon)
    except Exception:
        log.warning("no forecast for event %s; head speed and direction left to the wind", ev["id"], exc_info=True)
        return None, None
    mph = fc["head_ros_kmh"]["p50"] / 1.609344
    a = fc["_arrival"]
    dom = a["domain"]
    lat, lon = sit.ignition.lat, sit.ignition.lon
    yy, xx = np.meshgrid((dom.lats - lat) * KM_PER_DEG_LAT, (dom.lons - lon) * km_per_deg_lon(lat), indexing="ij")
    burned = a["t50"] <= now_min + 30
    toward = None
    if burned.any():
        dist = np.where(burned, np.hypot(yy, xx), -1.0)
        i, j = np.unravel_index(int(np.argmax(dist)), dist.shape)
        if dist[i, j] > 0:
            toward = (math.degrees(math.atan2(xx[i, j], yy[i, j])) + 360) % 360
    return toward, (mph if mph > 0 else None)


def kind_and_level(ev) -> tuple[str, str]:
    level = ev["recommendation"] if ev["recommendation"] in LEVELS else "monitor"
    if ev["status"] == "dismissed":
        return "notfire", level
    if ev["status"] == "closed":
        return "clear", level
    return "alert", level


def sync_event(conn: sqlite3.Connection, event_id: int, now: datetime, red_flag: bool | None = None) -> str | None:
    """Add a feed row if the alert changed since its last row. Returns the new code, or None. Never raises."""
    try:
        return _sync(conn, event_id, now, red_flag)
    except Exception:  # the feed must never stop an alert from being leveled or texted
        log.exception("fw1 feed sync failed for event %s", event_id)
        return None


def _sync(conn, event_id: int, now: datetime, red_flag: bool | None) -> str | None:
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    pack = pack_for(ev) if ev else None
    if pack is None:
        return None
    kind, level = kind_and_level(ev)
    last = conn.execute("SELECT * FROM fw1_feed WHERE event_id = ? ORDER BY seq DESC LIMIT 1", (event_id,)).fetchone()
    state = loads(ev["response_json"], {}) or {}
    mutual_aid = bool(state.get("mutual_aid"))
    if last is None and (kind != "alert" or level == "monitor"):
        return None  # nobody was told about it, so there is nothing to clear
    if last is not None:
        had_aid = bool(last["flags"] & fw1.FLAGS["mutual_aid"])
        if (last["kind"], last["level"]) == (kind, level) and (had_aid or not mutual_aid):
            return None
    if red_flag is None:
        red_flag = bool(last["flags"] & fw1.FLAGS["red_flag"]) if last else False
    red_flag = bool(red_flag) or replay_forecast_red_flag.get()
    weather = loads(ev["weather_json"], {}) or {}
    wind_from = weather.get("wind_dir_deg")
    toward = None if wind_from is None else (float(wind_from) + 180) % 360
    mph = None
    if kind == "alert" and level != "monitor":
        head_toward, mph = _head(ev, now)
        toward = head_toward if head_toward is not None else toward
    counted = [e for e in (loads(ev["evidence_json"], []) or []) if e.get("counts") in ("yes", "strong")]
    flags = []
    if red_flag:
        flags.append("red_flag")
    if kind == "alert" and _homes_in_path(ev, toward):
        flags.append("homes_in_path")
    if ev["is_sample"]:
        flags.append("exercise")
    if mutual_aid:
        flags.append("mutual_aid")
    if len(counted) >= 2:
        flags.append("two_sources")
    code = fw1.encode(
        {"pack": pack, "kind": kind, "level": level, "id": event_id,
         "score": ev["score"] if ev["score"] is not None else DEFAULT_SCORE[level],
         "lat": ev["lat"], "lon": ev["lon"], "time": now, "toward_deg": toward, "mph": mph, "flags": flags},
        pack_origin(pack),
    )
    conn.execute(
        "INSERT INTO fw1_feed(pack, event_id, kind, level, flags, code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pack, event_id, kind, level, sum(fw1.FLAGS[f] for f in flags), code, iso(now)),
    )
    _radio(conn, ev, code, now)
    return code


def _radio(conn, ev, code: str, now: datetime) -> None:
    """Put the bare code on the Meshtastic district channel, recorded like the other mesh sends.

    Real (non-sample) alerts follow the live-send rules when a Twilio gateway is configured: held without the
    operator token. The text never blocks the replay clock: the radio send runs in the bridge's own thread."""
    from . import livesend, mesh

    bridge = mesh.get_bridge()
    if bridge is None or not getattr(bridge, "connected", True):
        return
    sample = bool(ev["is_sample"])
    status = "sent"
    if livesend.real_sms_possible(sample) and livesend.check(conn, ev["id"], now):
        status = "held"
    else:
        bridge.spawn(bridge._post_quietly, code)
    conn.execute(
        "INSERT INTO messages(event_id, contact_id, phone, direction, purpose, body, status, is_sample, created_at, channel) "
        "VALUES (?, NULL, ?, 'out', 'fw1', ?, ?, ?, ?, 'mesh')",
        (ev["id"], mesh.BROADCAST_ID, code, status, int(sample), iso(now)),
    )
