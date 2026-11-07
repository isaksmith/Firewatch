import asyncio
import hmac
import json
import logging
import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from urllib.parse import parse_qsl

import numpy as np
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import climate, mesh, notify, planner, posts, routes_posts, sample, scenario
from .config import DATA_DIR, get_settings
from .confirm import evaluate_event
from .db import connect, init_db, iso, load_snapshot, loads, mark_source, parse_iso, redact, utcnow
from .district import boundary_geojson, load_district, sync_roster
from .fire_weather import default_curing, gfdi_band
from .ingest import goes_fire, goes_lightning, goes_smoke, hms, landsat_nrt, lsr, metar, ngfs, nws, risk_grid, rtma_ru, spc, wfigs
from .layers import LAYER_NAMES, load_layer, nearest_assets, segment_index
from .pipeline import poll_firms_once
from .signals import add_signal
from .sim.spread import SpreadInput, simulate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # INFO logs full URLs, and the FIRMS key is in the path
log = logging.getLogger("firewatch")

_tasks: list[asyncio.Task] = []
TICK_SECONDS = 30
MESH_RETRY_SECONDS = 30


async def _source_loop(name: str, interval_s: int, job) -> None:
    """Poll one source forever. A failure is logged and recorded, never raised."""
    while True:
        try:
            result = await asyncio.to_thread(job)
            log.info("%s poll: %s", name, result)
        except Exception as e:
            log.exception("%s poll failed", name)
            try:
                with connect() as conn:
                    mark_source(conn, name, ok=False, error=str(e))
            except Exception:
                log.exception("could not record failure for %s", name)
        await asyncio.sleep(interval_s)


def poll_jobs() -> dict:
    """Source name -> callable. Sources without a job here are not polled."""
    jobs = {
        "firms": poll_firms_once,
        "nws_alerts": nws.poll,
        "lsr": lsr.poll,
        "wfigs_incidents": wfigs.poll_incidents,
        "wfigs_perimeters": wfigs.poll_perimeters,
        "metar": metar.poll,
        "open_meteo": risk_grid.poll,
        "spc": spc.poll,
        "hms": hms.poll,
        "goes_fire": goes_fire.poll,
        "ngfs": ngfs.poll,
        "goes_lightning": goes_lightning.poll,
        "goes_smoke": goes_smoke.poll,
        "rtma_ru": rtma_ru.poll,
    }
    if get_settings().firms_map_key:
        jobs["landsat_nrt"] = landsat_nrt.poll
    return jobs


def _tick_live() -> None:
    with connect() as conn:
        now = utcnow()
        notify.hold_tick(conn, now, is_sample=get_settings().mode == "sample",
                         skip_slugs=[p.stem for p in scenario.SCENARIOS_DIR.glob("*.json")])
        notify.tick(conn, now, is_sample=False)
        posts.tick(conn, now, is_sample=get_settings().mode == "sample")


async def _tick_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_tick_live)
        except Exception:
            log.exception("response tick failed")
        await asyncio.sleep(TICK_SECONDS)


async def _mesh_loop() -> None:
    """Keep the server's Meshtastic radio connected; reconnect if it is unplugged or reboots."""
    while True:
        if mesh.get_bridge() is None:
            try:
                await asyncio.to_thread(mesh.start)
            except Exception:
                log.exception("mesh connect failed")
        await asyncio.sleep(MESH_RETRY_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    s = get_settings()
    try:
        with connect() as conn:
            log.info("district %s: %d contacts", s.district, sync_roster(conn))
    except FileNotFoundError:
        log.warning("no district data for %s; texting is off", s.district)
    if s.mode == "sample" and not sample.has_sample_events():
        n = await asyncio.to_thread(sample.load_all_now)
        log.info("loaded %d sample fixtures", n)
    if s.mode == "live":
        intervals = s.source_intervals
        _tasks.extend(asyncio.create_task(_source_loop(n, intervals[n], job)) for n, job in poll_jobs().items())
    _tasks.append(asyncio.create_task(_tick_loop()))
    if s.mesh_gateway != "off":
        _tasks.append(asyncio.create_task(_mesh_loop()))
    yield
    for t in _tasks:
        t.cancel()
    _tasks.clear()
    mesh.stop()


def require_admin(x_firewatch_token: str = Header(default="")) -> None:
    """Admin routes mint credentials, so a blank token fails closed outside sample mode."""
    s = get_settings()
    if not s.api_token and s.mode != "sample":
        raise HTTPException(503, "set API_TOKEN to use admin routes")
    require_token(x_firewatch_token)


def require_token(x_firewatch_token: str = Header(default="")) -> None:
    token = get_settings().api_token
    if token and not hmac.compare_digest(token, x_firewatch_token):
        raise HTTPException(401, "missing or wrong X-Firewatch-Token")


app = FastAPI(title="Firewatch Confirmation Layer", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
api = APIRouter(prefix="/api")

RECOMMENDATION_ORDER = {"escalate": 0, "investigate": 1, "monitor": 2}
TRANSITIONS = {
    "acknowledge": ({"new", "acknowledged", "escalated"}, "acknowledged"),
    "escalate": ({"new", "acknowledged"}, "escalated"),
    "dismiss": ({"new", "acknowledged", "escalated"}, "dismissed"),
    "reopen": ({"acknowledged", "escalated", "dismissed", "closed"}, "new"),
}


def _sources(conn, event_id: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in conn.execute("SELECT source FROM detections WHERE event_id = ?", (event_id,)):
        family = r["source"].split("_")[0]
        out[family] = out.get(family, 0) + 1
    return out


def _summary(conn, ev) -> dict:
    trend = [r["score"] for r in conn.execute(
        "SELECT score FROM scores WHERE event_id = ? ORDER BY id", (ev["id"],)
    )]
    latest = conn.execute(
        "SELECT reasons_json FROM scores WHERE event_id = ? ORDER BY id DESC LIMIT 1", (ev["id"],)
    ).fetchone()
    reasons = loads(latest["reasons_json"], []) if latest else []
    top = next((r for r in reasons if r["contribution"] > 0), reasons[0] if reasons else None)
    return {
        "id": ev["id"],
        "lat": ev["lat"],
        "lon": ev["lon"],
        "place_label": ev["place_label"],
        "county": ev["county"],
        "first_seen": ev["first_seen"],
        "last_seen": ev["last_seen"],
        "status": ev["status"],
        "score": ev["score"],
        "recommendation": ev["recommendation"],
        "score_trend": trend[-6:],
        "degraded": bool(ev["degraded"]),
        "guardrail": ev["guardrail"],
        "suppression": ev["suppression"],
        "reraised": bool(ev["reraised"]),
        "sources": _sources(conn, ev["id"]),
        "signals": _signal_counts(conn, ev["id"]),
        "top_reason": top["label"] if top else None,
        "level_reason": ev["level_reason"],
        "evidence": loads(ev["evidence_json"], []),
        "response": _response_brief(conn, ev),
        "is_sample": bool(ev["is_sample"]),
        "sample_slug": ev["sample_slug"],
    }


def _signal_counts(conn, event_id: int) -> dict[str, int]:
    return {r["kind"]: r["n"] for r in conn.execute(
        "SELECT kind, COUNT(*) n FROM signals WHERE event_id = ? GROUP BY kind", (event_id,)
    )}


def _response_brief(conn, ev) -> dict | None:
    """Where the response stands: who Firewatch is waiting on, and what has gone out."""
    state = loads(ev["response_json"], None)
    if not state:
        return None
    awaiting = None
    if not state.get("decision"):
        if state.get("escalate_at"):
            step = state.get("ladder_step", 1) - 1
            ladder = [r["name"] for r in conn.execute(
                "SELECT name FROM contacts WHERE ladder_rank IS NOT NULL ORDER BY ladder_rank"
            )]
            awaiting = ladder[step] if 0 <= step < len(ladder) else "County Dispatch (voice call)"
        else:
            awaiting = "neighbor replies"
    ma = state.get("mutual_aid")
    return {
        "investigate_at": state.get("investigate_at"),
        "escalate_at": state.get("escalate_at"),
        "awaiting": awaiting,
        "decision": state.get("decision"),
        "decision_by": state.get("decision_by"),
        "decision_at": state.get("decision_at"),
        "page_at": state.get("page_at"),
        "ladder": state.get("ladder", []),
        "responders": state.get("responders", []),
        "mutual_aid": ma,
        "plan": state.get("plan"),
        "texts_sent": conn.execute(
            "SELECT COUNT(*) n FROM messages WHERE event_id = ? AND direction = 'out'", (ev["id"],)
        ).fetchone()["n"],
        "crew": mesh.crew_positions(conn, ev["lat"], ev["lon"]),
    }


@api.get("/alerts")
def list_alerts(
    min_score: int = 0,
    status: str = "new,acknowledged,escalated",
    since_hours: float = 24,
    include_monitor: bool = False,
):
    statuses = [s.strip() for s in status.split(",") if s.strip()]
    since = iso(utcnow() - timedelta(hours=since_hours))
    live = get_settings().mode == "live"
    # Live mode hides the frozen sample fixtures but keeps scenario replay events, which are
    # is_sample = 1 rows tagged with a scenario slug.
    scenario_slugs = [p.stem for p in scenario.SCENARIOS_DIR.glob("*.json")] if live else []
    sample_clause = (
        f"(is_sample = 1 AND sample_slug IN ({','.join('?' * len(scenario_slugs))}))" if live and scenario_slugs
        else "0" if live else "is_sample = 1"
    )
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM events WHERE status IN ({','.join('?' * len(statuses))}) "
            f"AND recommendation IS NOT NULL AND ({sample_clause} OR (is_sample = 0 AND last_seen >= ?))",
            (*statuses, *scenario_slugs, since),
        ).fetchall()
        suppressed = {"total": 0, "static_source": 0, "likely_prescribed": 0, "registered_burn": 0, "low_signal": 0}
        alerts = []
        for ev in rows:
            if ev["recommendation"] == "monitor":
                suppressed["total"] += 1
                if ev["suppression"] in suppressed:
                    suppressed[ev["suppression"]] += 1
                if not include_monitor:
                    continue
            # Signal-only events have no satellite score; the score filter applies to satellite evidence.
            if ev["score"] is not None and ev["score"] < min_score:
                continue
            alerts.append(_summary(conn, ev))
    alerts.sort(key=lambda a: (
        RECOMMENDATION_ORDER.get(a["recommendation"], 9),
        -(a["score"] if a["score"] is not None else 101),
        a["last_seen"],
    ))
    return {"mode": get_settings().mode, "generated_at": iso(utcnow()), "alerts": alerts, "suppressed": suppressed}


def _get_event(conn, event_id: int):
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if ev is None:
        raise HTTPException(404, "alert not found")
    return ev


@api.get("/alerts/{event_id}")
def get_alert(event_id: int):
    with connect() as conn:
        ev = _get_event(conn, event_id)
        out = _summary(conn, ev)
        features = loads(ev["features_json"], {})
        out["features"] = features
        out["weather"] = loads(ev["weather_json"], {})
        if features:
            out["weather"]["gfdi"] = round(features["gfdi"], 1)
            out["weather"]["gfdi_band"] = gfdi_band(features["gfdi"])
        out["detections"] = [dict(r) for r in conn.execute(
            "SELECT id, source, satellite, lat, lon, acq_time, frp_mw, confidence, brightness_k, daynight "
            "FROM detections WHERE event_id = ? ORDER BY acq_time", (event_id,)
        )]
        out["score_history"] = [
            {"scored_at": r["scored_at"], "score": r["score"], "recommendation": r["recommendation"],
             "scorer": r["scorer"], "guardrail": r["guardrail"]}
            for r in conn.execute("SELECT * FROM scores WHERE event_id = ? ORDER BY id", (event_id,))
        ]
        latest = conn.execute(
            "SELECT reasons_json, scorer FROM scores WHERE event_id = ? ORDER BY id DESC LIMIT 1", (event_id,)
        ).fetchone()
        out["reasons"] = loads(latest["reasons_json"], []) if latest else []
        out["scorer"] = latest["scorer"] if latest else None
        out["actions"] = [dict(r) for r in conn.execute(
            "SELECT action, operator, note, created_at FROM actions WHERE event_id = ? ORDER BY id DESC", (event_id,)
        )]
        out["signal_list"] = [dict(r) for r in conn.execute(
            "SELECT s.id, s.kind, s.lat, s.lon, s.observed_at, s.source, s.value, c.name AS contact_name "
            "FROM signals s LEFT JOIN contacts c ON c.id = s.contact_id WHERE s.event_id = ? ORDER BY s.observed_at",
            (event_id,),
        )]
        out["messages"] = _messages(conn, event_id=event_id)
        out["nearest_assets"] = nearest_assets(ev["lat"], ev["lon"])
    return out


def _mask(phone: str | None) -> str | None:
    return None if phone is None else f"…{phone[-4:]}"


def _messages(conn, event_id: int | None = None, limit: int = 300) -> list[dict]:
    q = (
        "SELECT m.id, m.event_id, m.direction, m.purpose, m.body, m.status, m.created_at, m.phone, m.channel, "
        "c.name AS contact_name, c.role AS contact_role FROM messages m LEFT JOIN contacts c ON c.id = m.contact_id"
    )
    args: tuple = ()
    if event_id is not None:
        q += " WHERE m.event_id = ?"
        args = (event_id,)
    rows = conn.execute(q + " ORDER BY m.id DESC LIMIT ?", (*args, limit)).fetchall()
    return [{**dict(r), "phone": _mask(r["phone"])} for r in reversed(rows)]


class ActionIn(BaseModel):
    action: Literal["acknowledge", "escalate", "dismiss", "reopen"]
    operator: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


@api.post("/alerts/{event_id}/actions", dependencies=[Depends(require_token)])
def act_on_alert(event_id: int, body: ActionIn):
    allowed_from, new_status = TRANSITIONS[body.action]
    with connect() as conn:
        ev = _get_event(conn, event_id)
        if ev["status"] not in allowed_from:
            raise HTTPException(400, f"cannot {body.action} an alert that is {ev['status']}")
        clock = (scenario.clock_now(ev["sample_slug"]) if ev["is_sample"] else None) or utcnow()
        if body.action == "acknowledge":
            r = notify.acknowledge(conn, event_id=event_id, by=body.operator, role="operator", now=clock, note=body.note)
            if not r["ok"]:
                raise HTTPException(409, f"cannot acknowledge: {r['refused']}")
        else:
            conn.execute(
                "INSERT INTO actions(event_id, action, operator, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, body.action, body.operator, body.note, iso(clock)),
            )
            conn.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (new_status, iso(clock), event_id))
            if body.action == "dismiss":
                notify.clear_hold(conn, event_id)
            else:
                notify.release_hold(conn, event_id, clock)
    return get_alert(event_id)


_sim_cache: dict[tuple, dict] = {}


@api.get("/alerts/{event_id}/simulate")
def simulate_alert(
    event_id: int,
    minutes: int = Query(60, ge=5, le=120),
    wind_kmh: float | None = Query(None, ge=0, le=150),
    wind_from_deg: float | None = Query(None, ge=0, le=360),
):
    with connect() as conn:
        ev = _get_event(conn, event_id)
        f = loads(ev["features_json"], {})
        dets = conn.execute("SELECT lat, lon FROM detections WHERE event_id = ?", (event_id,)).fetchall()
    if not f:
        raise HTTPException(409, "alert has not been scored yet")
    observed_wind = f.get("wind_kmh", 0.0)
    observed_dir = f.get("wind_dir_deg", 0.0)
    w = observed_wind if wind_kmh is None else wind_kmh
    d = observed_dir if wind_from_deg is None else wind_from_deg
    key = (event_id, minutes, round(w / 2) * 2, round(d / 5) * 5)
    if key not in _sim_cache:
        month = parse_iso(ev["first_seen"]).month
        result = simulate(SpreadInput(
            lat=ev["lat"], lon=ev["lon"], wind_kmh=key[2], wind_from_deg=key[3] % 360,
            temp_c=f.get("temp_c", 15.0), rh_pct=f.get("rh_pct", 50.0),
            curing_pct=f.get("curing_pct", default_curing(month)),
            minutes=minutes, ignitions=[(r["lat"], r["lon"]) for r in dets] or None,
        ))
        result["event_id"] = event_id
        result["observed_wind"] = {"from_deg": round(observed_dir), "kmh": round(observed_wind, 1)}
        result["overridden"] = wind_kmh is not None or wind_from_deg is not None
        _sim_cache[key] = result
    return _sim_cache[key]


@api.get("/layers/{name}")
def get_layer(name: str):
    if name not in LAYER_NAMES:
        raise HTTPException(404, f"unknown layer; choose from {', '.join(LAYER_NAMES)}")
    return load_layer(name)


FEEDS_DIR = DATA_DIR / "samples" / "feeds"
FEED_NAMES = tuple(n for n in get_settings().source_intervals if n != "firms")


@api.get("/feeds/{name}")
def get_feed(name: str):
    """Latest snapshot of a context feed. In sample mode or before the first poll, a labeled fixture."""
    if name not in FEED_NAMES:
        raise HTTPException(404, f"unknown feed; choose from {', '.join(FEED_NAMES)}")
    if get_settings().mode != "sample":
        with connect() as conn:
            snap = load_snapshot(conn, name)
        if snap:
            return {"feed": name, "fixture": False, **snap}
    path = FEEDS_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, f"no data yet for {name}")
    return {"feed": name, "fixture": True, "fetched_at": None, "data": json.loads(path.read_text())}


def _grid_cells() -> list[dict]:
    return get_feed("open_meteo")["data"]["cells"]


RTMA_MAX_AGE_S = 2 * 3600  # RTMA-RU lags about 17 min; older than 2 h means the feed has stalled


def _fresh_rtma() -> dict | None:
    """Latest RTMA-RU snapshot, or None when absent, a fixture, or too old to prefer."""
    if get_settings().mode == "sample":
        return None
    try:
        feed = get_feed("rtma_ru")
    except HTTPException:
        return None
    if feed["fixture"] or not feed["data"].get("valid_time"):
        return None
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(feed["data"]["valid_time"])).total_seconds()
    return feed["data"] if age <= RTMA_MAX_AGE_S else None


def _vpd_kpa(temp_c: float, rh: float) -> float:
    es = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return round(es * (1 - rh / 100), 2)


@api.get("/risk/grid")
def risk_grid_route():
    """Open-Meteo grid, with temperature, dew point, RH and VPD replaced by the
    RTMA-RU analysis when it is fresh. Wind and forecast fields stay Open-Meteo. `source`
    says which one the humidity came from."""
    feed = get_feed("open_meteo")
    cells = [dict(c) for c in feed["data"]["cells"]]
    rtma = _fresh_rtma()
    source = "open_meteo"
    if rtma:
        by = {(round(p["lat"], 3), round(p["lon"], 3)): p for p in rtma["points"]}
        hit = 0
        for c in cells:
            p = by.get((round(c["lat"], 3), round(c["lon"], 3)))
            if p:
                c.update(temp_c=p["temp_c"], dew_c=p["dew_c"], rh=p["rh"],
                         vpd_kpa=_vpd_kpa(p["temp_c"], p["rh"]), valid_time=rtma["valid_time"])
                hit += 1
        if hit:
            source = "rtma_ru"
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
              "properties": {k: v for k, v in c.items() if k not in ("lat", "lon")}} for c in cells]
    return {"type": "FeatureCollection", "features": feats, "fixture": feed["fixture"],
            "fetched_at": feed["fetched_at"], "source": source}


@api.get("/risk/lines-under-wind")
def lines_under_wind():
    """Transmission lines whose nearest grid cell forecasts gusts at or above the flag threshold in the next 12 h."""
    feed = get_feed("open_meteo")
    cells = feed["data"]["cells"]
    thr = get_settings().wind_gust_flag_kmh
    seg = segment_index()
    out: dict[int, float] = {}
    if cells and len(seg.owner):
        cy = np.array([c["lat"] for c in cells])
        cx = np.array([c["lon"] for c in cells])
        cg = np.array([c["gust_max_12h_kmh"] if c["gust_max_12h_kmh"] is not None else -1.0 for c in cells])
        mx, my = (seg.ax + seg.bx) / 2, (seg.ay + seg.by) / 2
        for k in range(0, len(mx), 2000):
            d = (mx[k:k + 2000, None] - cx[None]) ** 2 + (my[k:k + 2000, None] - cy[None]) ** 2
            g = cg[d.argmin(axis=1)]
            for o, gv in zip(seg.owner[k:k + 2000], g):
                if gv >= thr:
                    out[int(o)] = max(out.get(int(o), 0.0), float(gv))
    feats = [{"type": "Feature", "geometry": load_layer("power_lines")["features"][o]["geometry"],
              "properties": {**seg.props[o], "max_gust_kmh": round(g, 1)}} for o, g in out.items()]
    return {"type": "FeatureCollection", "features": feats, "threshold_kmh": thr,
            "fixture": feed["fixture"], "fetched_at": feed["fetched_at"]}


@api.get("/health")
def health():
    s = get_settings()
    now = utcnow()
    sources = {}
    with connect() as conn:
        rows = {r["source"]: r for r in conn.execute("SELECT * FROM source_health")}
    for name, interval_s in s.source_intervals.items():
        r = rows.get(name)
        if s.mode == "sample":
            sources[name] = {"status": "sample", "age_min": None, "last_ok": None, "last_error": None,
                             "interval_s": interval_s}
            continue
        last_error = redact(r["last_error"]) if r else None
        if r is None or r["last_ok"] is None:
            status = "skipped" if name in ("firms", "landsat_nrt") and not s.firms_map_key else "down"
            sources[name] = {"status": status, "age_min": None, "last_ok": None, "last_error": last_error,
                             "interval_s": interval_s}
            continue
        age_s = (now - parse_iso(r["last_ok"])).total_seconds()
        # stale at 3 intervals, down at 12
        status = "ok" if age_s < 3 * interval_s else "stale" if age_s < 12 * interval_s else "down"
        sources[name] = {"status": status, "age_min": round(age_s / 60), "last_ok": r["last_ok"],
                         "last_error": last_error, "interval_s": interval_s}
    if (m := mesh.health()) is not None:
        sources["mesh"] = m
    return {
        "mode": s.mode,
        "firms_key_configured": bool(s.firms_map_key),
        "replay_running": sample.replay_running(),
        "sources": sources,
    }


@api.post("/ingest/run")
async def ingest_run():
    if get_settings().mode == "sample":
        raise HTTPException(400, "ingest is disabled in sample mode; use /api/sample/replay")
    return await asyncio.to_thread(poll_firms_once)


@api.post("/sample/replay")
async def sample_replay(duration_s: float = Query(60, ge=5, le=600)):
    sample.start_replay(duration_s)
    return {"status": "started", "duration_s": duration_s, "fixtures": len(sample.load_fixtures())}


@api.post("/sample/load")
async def sample_load():
    n = await asyncio.to_thread(sample.load_all_now)
    return {"status": "loaded", "fixtures": n}


@api.get("/sample/fixtures")
def sample_fixtures():
    return [
        {k: fx.get(k) for k in ("slug", "title", "expected", "story", "approximate", "synthetic")}
        for fx in sample.load_fixtures()
    ]


class SignalIn(BaseModel):
    kind: Literal["line_fault", "report", "camera_smoke", "sensor_smoke"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    observed_at: str | None = None
    source: str = Field(min_length=1, max_length=80)
    value: str | None = Field(default=None, max_length=200)


@api.post("/signals", dependencies=[Depends(require_token)])
def post_signal(body: SignalIn):
    """Line faults (co-op feed), camera smoke, or a located report. Attaches to an event and re-levels it."""
    observed = body.observed_at or iso(utcnow())
    try:
        parse_iso(observed)
    except ValueError:
        raise HTTPException(422, "observed_at must be ISO 8601") from None
    sample_mode = get_settings().mode == "sample"
    with connect() as conn:
        eid = add_signal(conn, body.kind, body.lat, body.lon, observed, body.source, body.value, is_sample=sample_mode)
        result = evaluate_event(conn, eid)
    return {"event_id": eid, **result}


@api.post("/sms/inbound")
async def sms_inbound(request: Request):
    """Twilio inbound webhook (form-encoded From/Body). Replies go out through the gateway, not TwiML."""
    s = get_settings()
    params = dict(parse_qsl((await request.body()).decode()))
    if s.sms_gateway == "twilio":
        url = f"{s.public_base_url.rstrip('/')}{request.url.path}"
        if not notify.valid_twilio_signature(s.twilio_auth_token, url, params, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "bad Twilio signature")
    phone, text = params.get("From"), params.get("Body", "")
    if not phone:
        raise HTTPException(422, "From is required")

    def handle():
        with connect() as conn:
            replay_now = scenario.running_now()
            notify.handle_inbound(conn, phone, text, replay_now or utcnow(), is_sample=replay_now is not None or s.mode == "sample")

    await asyncio.to_thread(handle)
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response/>', media_type="application/xml")


class SimulatedSms(BaseModel):
    from_: str = Field(alias="from", min_length=3, max_length=20)
    body: str = Field(min_length=1, max_length=320)


@api.post("/sms/simulate", dependencies=[Depends(require_token)])
def sms_simulate(msg: SimulatedSms):
    """Pretend a phone texted Firewatch (sample mode only, so it never texts real people)."""
    if get_settings().mode != "sample":
        raise HTTPException(400, "simulated texts are only allowed in sample mode")
    with connect() as conn:
        return notify.handle_inbound(conn, msg.from_, msg.body, scenario.running_now() or utcnow(), is_sample=True)


@api.get("/messages", dependencies=[Depends(require_token)])
def list_messages(event_id: int | None = None, limit: int = Query(300, ge=1, le=2000)):
    with connect() as conn:
        return _messages(conn, event_id=event_id, limit=limit)


@api.get("/contacts")
def list_contacts():
    with connect() as conn:
        return [
            {**dict(r), "phone": _mask(r["phone"])}
            for r in conn.execute("SELECT * FROM contacts WHERE phone NOT LIKE 'web:%' ORDER BY ladder_rank IS NULL, ladder_rank, role, name")
        ]


@api.get("/mesh/nodes")
def list_mesh_nodes():
    """Every Meshtastic radio the server's radio has heard, with its last position and the contact who carries it."""
    with connect() as conn:
        return mesh.list_nodes(conn)


@api.get("/district")
def get_district():
    try:
        d = load_district()
    except FileNotFoundError:
        raise HTTPException(404, "no district configured") from None
    return {"slug": d.slug, "settings": d.settings, "boundary": boundary_geojson(d.slug)}


class PlanParams(BaseModel):
    sites: int | None = Field(None, ge=1, le=60)
    bare_per_site: int | None = Field(None, ge=0, le=16)
    rich_per_site: int | None = Field(None, ge=0, le=16)
    budget_usd: float | None = Field(None, ge=500, le=500_000)
    rich_range_km: float | None = Field(None, gt=0, le=10)
    bare_fetch_km: float | None = Field(None, gt=0, le=2)
    site_min_sep_km: float | None = Field(None, ge=0.5, le=30)


class CustomPlanIn(PlanParams):
    geometry: dict


_plan_cache: dict[str, dict] = {}


def _plan(key: str, params: PlanParams, geometry: dict | None = None) -> dict:
    cache_key = f"{key}|{params.model_dump_json()}|{hash(str(geometry)) if geometry else ''}"
    if cache_key in _plan_cache:
        return _plan_cache[cache_key]
    try:
        region = planner.resolve_region(key, geometry)
        result = planner.plan_region(region, params.model_dump())
    except KeyError:
        raise HTTPException(404, f"unknown region {key}") from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except climate.ClimateUnavailable as e:
        raise HTTPException(503, f"climate data unavailable: {e}") from None
    if len(_plan_cache) > 32:
        _plan_cache.clear()
    _plan_cache[cache_key] = result
    return result


@api.get("/planner/regions")
def planner_regions():
    """Districts and Kansas counties the region planner can lay out a sensor network for."""
    return planner.list_regions()


@api.get("/planner/plan")
def planner_plan(
    params: Annotated[PlanParams, Depends()],
    region: str = Query(..., description="district:<slug> or county:<name>"),
):
    """Mixed bare/rich sensor plots, relays, and station bridge for a region, sited from geography and climate."""
    return _plan(region, params)


@api.post("/planner/plan")
def planner_plan_custom(body: CustomPlanIn):
    return _plan("custom", PlanParams(**body.model_dump(exclude={"geometry"})), body.geometry)


class DecisionIn(BaseModel):
    action: Literal["page", "no", "send"]
    operator: str = Field(min_length=1, max_length=80)


@api.post("/alerts/{event_id}/decision", dependencies=[Depends(require_token)])
def alert_decision(event_id: int, body: DecisionIn):
    """PAGE / NO / SEND from the console; the same path as the duty officer texting it."""
    with connect() as conn:
        ev = _get_event(conn, event_id)
        if not ev["response_json"] and not ev["ack_until"]:
            raise HTTPException(409, "this alert has no response in progress")
        now = scenario.clock_now(ev["sample_slug"]) if ev["is_sample"] else None
        notify.decide(conn, event_id, body.action, body.operator, now or utcnow())
    return get_alert(event_id)


@api.get("/scenarios")
def list_scenarios():
    return scenario.list_scenarios()


@api.get("/scenario/{slug}")
def get_scenario(slug: str):
    try:
        return scenario.status(slug)
    except KeyError:
        raise HTTPException(404, "unknown scenario") from None


@api.post("/scenario/{slug}/run")
async def run_scenario(slug: str, seconds_per_minute: float | None = Query(None, ge=0.05, le=60)):
    """Replay the scenario on a scaled clock (default 2 s per scenario minute)."""
    try:
        scenario.start(slug, seconds_per_minute)
    except KeyError:
        raise HTTPException(404, "unknown scenario") from None
    return {"status": "started", "slug": slug}


@api.post("/scenario/{slug}/load")
async def load_scenario_now(slug: str):
    """Run the whole scenario instantly (no animation)."""
    try:
        await asyncio.to_thread(scenario.run_now, slug)
    except KeyError:
        raise HTTPException(404, "unknown scenario") from None
    return scenario.status(slug)


api.include_router(routes_posts.public_router)
api.include_router(routes_posts.admin_router, dependencies=[Depends(require_admin)])
app.include_router(api)


@app.get("/")
def root():
    return {"name": "Firewatch Confirmation Layer", "docs": "/docs", "api": "/api"}
