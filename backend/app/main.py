import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import sample
from .config import get_settings
from .db import connect, init_db, iso, loads, parse_iso, utcnow
from .fire_weather import default_curing, gfdi_band
from .layers import LAYER_NAMES, load_layer, nearest_assets
from .pipeline import poll_firms_once
from .sim.ensemble import forecast
from .sim.spread import SpreadInput, simulate
from .situation import Situation, list_scenarios, load_scenario

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("firewatch")

_poll_task: asyncio.Task | None = None


async def _poll_loop() -> None:
    minutes = get_settings().poll_minutes
    while True:
        try:
            summary = await asyncio.to_thread(poll_firms_once)
            log.info("FIRMS poll: %s", summary)
        except Exception:
            log.exception("FIRMS poll failed")
        await asyncio.sleep(minutes * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poll_task
    init_db()
    s = get_settings()
    if s.mode == "sample" and not sample.has_sample_events():
        n = await asyncio.to_thread(sample.load_all_now)
        log.info("loaded %d sample fixtures", n)
    if s.mode == "live":
        _poll_task = asyncio.create_task(_poll_loop())
    yield
    if _poll_task:
        _poll_task.cancel()


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
    "acknowledge": ({"new"}, "acknowledged"),
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
        "top_reason": top["label"] if top else None,
        "is_sample": bool(ev["is_sample"]),
        "sample_slug": ev["sample_slug"],
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
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM events WHERE status IN ({','.join('?' * len(statuses))}) "
            "AND score IS NOT NULL AND (is_sample = 1 OR last_seen >= ?)",
            (*statuses, since),
        ).fetchall()
        alerts, suppressed = [], {"total": 0, "static_source": 0, "likely_prescribed": 0, "low_signal": 0}
        for ev in rows:
            if ev["recommendation"] == "monitor":
                suppressed["total"] += 1
                if ev["suppression"] in suppressed:
                    suppressed[ev["suppression"]] += 1
                if not include_monitor:
                    continue
            if ev["score"] < min_score:
                continue
            alerts.append(_summary(conn, ev))
    alerts.sort(key=lambda a: (RECOMMENDATION_ORDER.get(a["recommendation"], 9), -a["score"], a["last_seen"]))
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
        out["nearest_assets"] = nearest_assets(ev["lat"], ev["lon"])
    return out


class ActionIn(BaseModel):
    action: Literal["acknowledge", "escalate", "dismiss", "reopen"]
    operator: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


@api.post("/alerts/{event_id}/actions")
def act_on_alert(event_id: int, body: ActionIn):
    allowed_from, new_status = TRANSITIONS[body.action]
    with connect() as conn:
        ev = _get_event(conn, event_id)
        if ev["status"] not in allowed_from:
            raise HTTPException(400, f"cannot {body.action} an alert that is {ev['status']}")
        now = iso(utcnow())
        conn.execute(
            "INSERT INTO actions(event_id, action, operator, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (event_id, body.action, body.operator, body.note, now),
        )
        conn.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (new_status, now, event_id))
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
            minutes=minutes, ignitions=[(r["lat"], r["lon"]) for r in dets], use_fuel=True, month=month,
        ))
        result["event_id"] = event_id
        result["observed_wind"] = {"from_deg": round(observed_dir), "kmh": round(observed_wind, 1)}
        result["overridden"] = wind_kmh is not None or wind_from_deg is not None
        _sim_cache[key] = result
    return _sim_cache[key]


def _public(result: dict) -> dict:
    return {k: v for k, v in result.items() if not k.startswith("_")}


@api.get("/scenarios")
def get_scenarios():
    return list_scenarios()


@api.get("/scenarios/{slug}")
def get_scenario(slug: str):
    try:
        meta, sit = load_scenario(slug)
    except FileNotFoundError:
        raise HTTPException(404, "unknown scenario")
    return meta | {"slug": slug, "situation": sit.model_dump(mode="json")}


_forecast_cache: dict[tuple, dict] = {}


@api.get("/scenarios/{slug}/forecast")
def scenario_forecast(slug: str, minutes: int = Query(120, ge=10, le=240), members: int = Query(24, ge=1, le=64)):
    key = (slug, minutes, members)
    if key not in _forecast_cache:
        try:
            _, sit = load_scenario(slug)
        except FileNotFoundError:
            raise HTTPException(404, "unknown scenario")
        _forecast_cache[key] = _public(forecast(sit, minutes, members)) | {"scenario": slug}
    return _forecast_cache[key]


@api.post("/forecast")
def forecast_situation(sit: Situation, minutes: int = Query(120, ge=10, le=240), members: int = Query(24, ge=1, le=64)):
    return _public(forecast(sit, minutes, members))


@api.get("/layers/{name}")
def get_layer(name: str):
    if name not in LAYER_NAMES:
        raise HTTPException(404, f"unknown layer; choose from {', '.join(LAYER_NAMES)}")
    return load_layer(name)


@api.get("/health")
def health():
    s = get_settings()
    now = utcnow()
    sources = {}
    with connect() as conn:
        rows = {r["source"]: r for r in conn.execute("SELECT * FROM source_health")}
    for name in ("firms", "open_meteo"):
        r = rows.get(name)
        if s.mode == "sample":
            sources[name] = {"status": "sample", "age_min": None, "last_ok": None, "last_error": None}
            continue
        if r is None or r["last_ok"] is None:
            sources[name] = {"status": "down", "age_min": None, "last_ok": None,
                             "last_error": r["last_error"] if r else None}
            continue
        age = (now - parse_iso(r["last_ok"])).total_seconds() / 60
        status = "ok" if age < 15 else "stale" if age < 60 else "down"
        sources[name] = {"status": status, "age_min": round(age), "last_ok": r["last_ok"], "last_error": r["last_error"]}
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


app.include_router(api)


@app.get("/")
def root():
    return {"name": "Firewatch Confirmation Layer", "docs": "/docs", "api": "/api"}
