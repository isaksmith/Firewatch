"""Scenario replay: a scripted incident run through the real signal, confirm, and notify code on its own
clock (docs/DESIGN.md section 10). Everything it writes is sample data."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from functools import lru_cache

from .config import DATA_DIR, get_settings
from .confirm import evaluate_event
from .redflag import replay_red_flag
from .db import connect, iso, loads, parse_iso
from .district import load_district, sync_roster
from .fire_weather import default_curing, gfdi, gfdi_band
from .ngfs_signal import add_ngfs_signals
from .notify import handle_inbound, tick
from .pipeline import process_detections
from .signals import add_signal
from .sim.spread import SpreadInput, growth_curve

log = logging.getLogger(__name__)
SCENARIOS_DIR = DATA_DIR / "scenarios"
HA_PER_ACRE = 0.404686

_task: asyncio.Task | None = None
_clock: dict = {}  # slug, t_min, running


def load_scenario(slug: str) -> dict:
    path = SCENARIOS_DIR / f"{slug}.json"
    if not path.is_file() or path.parent != SCENARIOS_DIR:
        raise KeyError(slug)
    return json.loads(path.read_text())


def list_scenarios() -> list[dict]:
    out = []
    for p in sorted(SCENARIOS_DIR.glob("*.json")):
        sc = json.loads(p.read_text())
        out.append({k: sc.get(k) for k in ("slug", "title", "story")})
    return out


def clear(slug: str) -> None:
    """Remove this scenario's events and all sample signals, messages, and burn notices."""
    with connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM events WHERE is_sample = 1 AND (sample_slug = ? OR sample_slug IS NULL)", (slug,))]
        for table in ("scores", "actions", "detections", "signals", "messages"):
            conn.executemany(f"DELETE FROM {table} WHERE event_id = ?", [(i,) for i in ids])
        conn.executemany("DELETE FROM events WHERE id = ?", [(i,) for i in ids])
        for table in ("signals", "messages", "burn_notices"):
            conn.execute(f"DELETE FROM {table} WHERE is_sample = 1")


def _apply(conn, sc: dict, step: dict, now: datetime) -> None:
    kind = step["type"]
    if kind == "signal":
        eid = add_signal(conn, step["kind"], step["lat"], step["lon"], iso(now), step["source"], step.get("value"), is_sample=True)
        evaluate_event(conn, eid, sc["weather"], now)
    elif kind == "sms":
        handle_inbound(conn, step["from"], step["body"], now, is_sample=True)
    elif kind == "detections":
        dets = [{**d, "acq_time": iso(now)} for d in step["detections"]]
        process_detections(conn, dets, is_sample=True, weather=sc["weather"], now=now)
    elif kind == "ngfs":
        # Each ngfs step is one scan of one tracked feature; the snapshot is every scan so far.
        pts = [
            {"lat": s["lat"], "lon": s["lon"], "feature_tracking_id": s["feature_tracking_id"],
             "type_description": s.get("type_description"),
             "acq_date_time": iso(parse_iso(sc["t0"]) + timedelta(minutes=s["t"] - s.get("lag_min", 0)))}
            for s in sc["timeline"] if s["type"] == "ngfs" and s["t"] <= step["t"]
        ]
        for eid in add_ngfs_signals(conn, pts, now, is_sample=True):
            evaluate_event(conn, eid, sc["weather"], now)
    else:
        raise ValueError(f"unknown step type {kind!r}")
    conn.execute("UPDATE events SET sample_slug = ? WHERE is_sample = 1 AND sample_slug IS NULL", (sc["slug"],))


def _minute(conn, sc: dict, t: int) -> None:
    t0 = parse_iso(sc["t0"])
    now = t0 + timedelta(minutes=t)
    token = replay_red_flag.set(bool(sc.get("red_flag", False)))
    try:
        for step in sc["timeline"]:
            if step["t"] == t:
                _apply(conn, sc, step, now)
        tick(conn, now, is_sample=True)
    finally:
        replay_red_flag.reset(token)


def _pre_steps(sc: dict) -> list[int]:
    return sorted({s["t"] for s in sc["timeline"] if s["t"] < 0})


def run_now(slug: str, until: int | None = None) -> None:
    """Run the whole scenario synchronously (tests, and the instant 'load' button)."""
    sc = load_scenario(slug)
    clear(slug)
    end = sc["duration_min"] if until is None else until
    with connect() as conn:
        sync_roster(conn, sc["district"])
        for t in [*_pre_steps(sc), *range(end + 1)]:
            _minute(conn, sc, t)
    _clock.update(slug=slug, t_min=end, running=False)


async def _replay(slug: str, seconds_per_minute: float) -> None:
    sc = load_scenario(slug)
    await asyncio.to_thread(clear, slug)

    def setup():
        with connect() as conn:
            sync_roster(conn, sc["district"])
            for t in _pre_steps(sc):
                _minute(conn, sc, t)

    await asyncio.to_thread(setup)
    _clock.update(slug=slug, t_min=-1, running=True)
    try:
        for t in range(sc["duration_min"] + 1):
            def step(t=t):
                with connect() as conn:
                    _minute(conn, sc, t)

            await asyncio.to_thread(step)
            _clock["t_min"] = t
            await asyncio.sleep(seconds_per_minute)
    finally:
        _clock["running"] = False
    log.info("scenario %s finished", slug)


def start(slug: str, seconds_per_minute: float | None = None) -> None:
    global _task
    load_scenario(slug)
    if _task and not _task.done():
        _task.cancel()
    _task = asyncio.create_task(_replay(slug, seconds_per_minute or get_settings().scenario_seconds_per_minute))


def clock_now(slug: str | None) -> datetime | None:
    """The scenario's current time, so console actions on its events land on its timeline."""
    if not slug or _clock.get("slug") != slug or _clock.get("t_min") is None:
        return None
    try:
        sc = load_scenario(slug)
    except KeyError:
        return None
    return parse_iso(sc["t0"]) + timedelta(minutes=max(_clock["t_min"], 0))


def running_now() -> datetime | None:
    """The running replay's clock, for replies from real radios while it plays."""
    return clock_now(_clock.get("slug")) if _clock.get("running") else None


@lru_cache(maxsize=4)
def _growth(slug: str) -> list[dict]:
    sc = load_scenario(slug)
    w, ig = sc["weather"], sc["ignition"]
    curve = growth_curve(SpreadInput(
        lat=ig["lat"], lon=ig["lon"], wind_kmh=w["wind_kmh"], wind_from_deg=w["wind_dir_deg"],
        temp_c=w["temp_c"], rh_pct=w["rh_pct"], curing_pct=default_curing(parse_iso(sc["t0"]).month),
        minutes=sc["duration_min"], use_terrain=False,
    ))
    return [{"minute": g["minute"], "acres": round(g["area_ha"] / HA_PER_ACRE), "head_mi": round(g["head_km"] / 1.609344, 2)} for g in curve]


def status(slug: str) -> dict:
    sc = load_scenario(slug)
    t0 = parse_iso(sc["t0"])
    w = sc["weather"]
    curing = default_curing(t0.month)
    g = gfdi(curing, w["temp_c"], w["rh_pct"], w["wind_kmh"])

    def minutes(at: str | None) -> float | None:
        return None if at is None else round((parse_iso(at) - t0).total_seconds() / 60, 1)

    cfg = load_district(sc["district"]).settings
    turnout, drive = cfg.get("turnout_min", 13), cfg.get("drive_min", 18)
    events, firewatch, escalated_seen = [], [], False
    with connect() as conn:
        rows = conn.execute("SELECT * FROM events WHERE sample_slug = ? ORDER BY first_seen", (slug,)).fetchall()
        n_out = conn.execute(
            "SELECT COUNT(*) n FROM messages m JOIN events e ON e.id = m.event_id WHERE e.sample_slug = ? AND m.direction = 'out'",
            (slug,),
        ).fetchone()["n"]
        for ev in rows:
            state = loads(ev["response_json"], {}) or {}
            events.append({
                "id": ev["id"], "place_label": ev["place_label"], "recommendation": ev["recommendation"],
                "level_reason": ev["level_reason"], "suppression": ev["suppression"],
                "first_seen_t": minutes(ev["first_seen"]),
                "texts_sent": conn.execute(
                    "SELECT COUNT(*) n FROM messages WHERE event_id = ? AND direction = 'out'", (ev["id"],)
                ).fetchone()["n"],
            })
            # one timeline: the first event that got a text, unless a later one escalated
            if state.get("investigate_at") and (not firewatch or (state.get("escalate_at") and not escalated_seen)):
                escalated_seen = bool(state.get("escalate_at"))
                page_t = minutes(state.get("page_at"))
                firewatch = [
                    {"key": "signal", "t": minutes(ev["first_seen"]), "label": "First signal"},
                    {"key": "investigate", "t": minutes(state.get("investigate_at")), "label": "Duty officer FYI, neighbors asked"},
                    {"key": "escalate", "t": minutes(state.get("escalate_at")), "label": "Confirmed by a second source"},
                    {"key": "page", "t": page_t, "label": "Paged"},
                    {"key": "roll", "t": None if page_t is None else page_t + turnout, "label": f"Trucks roll (+{turnout} turnout)"},
                    {"key": "on_scene", "t": None if page_t is None else page_t + turnout + drive, "label": f"On scene (+{drive} drive)"},
                ]
                if state.get("mutual_aid", {}).get("sent_at"):
                    firewatch.append({"key": "mutual_aid", "t": minutes(state["mutual_aid"]["sent_at"]), "label": "Mutual aid requested"})

    growth = _growth(slug)

    def size_at(t: float | None) -> dict | None:
        if t is None:
            return None
        g_ = growth[min(round(t), len(growth) - 1)]
        return {"acres": g_["acres"], "head_mi": g_["head_mi"]}

    base_on_scene = next(m["t"] for m in sc["baseline"]["milestones"] if m["key"] == "on_scene")
    fw_on_scene = next((m["t"] for m in firewatch if m["key"] == "on_scene"), None)
    running = _clock.get("slug") == slug and _clock.get("running", False)
    return {
        "slug": slug,
        "title": sc["title"],
        "story": sc["story"],
        "synthetic": sc.get("synthetic", False),
        "t0": sc["t0"],
        "t0_local": sc["t0_local"],
        "duration_min": sc["duration_min"],
        "ignition": sc["ignition"],
        "weather": {**w, "curing_pct": curing, "gfdi": round(g, 1), "gfdi_band": gfdi_band(g)},
        "running": running,
        "t_min": _clock.get("t_min") if _clock.get("slug") == slug else None,
        "baseline": sc["baseline"]["milestones"],
        "firewatch": firewatch,
        "size_on_scene": {"baseline": size_at(base_on_scene), "firewatch": size_at(fw_on_scene)},
        "growth": growth,
        "events": events,
        "texts_sent": n_out,
    }
