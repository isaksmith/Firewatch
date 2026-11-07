import asyncio
import logging
from contextlib import asynccontextmanager
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import sample
from .config import get_settings
from .db import connect, init_db, iso, loads, parse_iso, utcnow
from .fire_weather import default_curing, gfdi_band
from .layers import LAYER_NAMES, load_layer, nearest_assets
from .pipeline import add_burn, poll_firms_once, process_line_fault, process_report
from .alerts.routes import router as alerts_router
from .lite import router as lite_router
from .sim.spread import SpreadInput, simulate

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
    if s.mode == "sample" and not sample.sample_is_current():
        n = await asyncio.to_thread(sample.load_all_now)
        log.info("loaded %d sample fixtures", n)
    if s.mode == "live":
        _poll_task = asyncio.create_task(_poll_loop())
    yield
    if _poll_task:
        _poll_task.cancel()


app = FastAPI(title="Firewatch Confirmation Layer", lifespan=lifespan)
# One bar of signal: compress anything over 500 bytes.
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
api = APIRouter(prefix="/api")


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    # FastAPI's default 422 echoes the rejected input back. That would put a phone number in the
    # response (and in any proxy log), so report only where the problem is and what it is.
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})

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
    for r in conn.execute("SELECT kind FROM signals WHERE event_id = ?", (event_id,)):
        out[r["kind"]] = out.get(r["kind"], 0) + 1
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
    if ev["suppression"] == "logged_burn" and reasons:
        top = reasons[0]
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
        alerts, suppressed = [], {"total": 0, "static_source": 0, "likely_prescribed": 0, "logged_burn": 0, "low_signal": 0}
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
        out["signals"] = [
            {"id": r["id"], "kind": r["kind"], "lat": r["lat"], "lon": r["lon"], "time": r["time"], **_signal_public(r)}
            for r in conn.execute("SELECT * FROM signals WHERE event_id = ? ORDER BY time", (event_id,))
        ]
        out["data_age"] = _data_age(conn, ev, out["detections"], out["signals"], out["weather"])
    return out


def _signal_public(row) -> dict:
    """What the screen may show of a signal. A reporter's phone number is never sent back out."""
    p = loads(row["payload_json"], {})
    if row["kind"] == "line_fault":
        return {"circuit": p.get("circuit"), "fault_kind": p.get("kind")}
    phone = p.get("phone") or ""
    return {"text": p.get("text"), "phone_last4": phone[-4:] if phone else None}


def _data_age(conn, ev, detections: list[dict], signals: list[dict], weather: dict) -> list[dict]:
    """One row per source with when it was last heard from, so the screen can say "3 min ago".
    A source with no timestamp keeps its row with last_seen null: a gap, not a quiet "no fire"."""
    rows: list[dict] = []
    latest_by_source: dict[str, str] = {}
    for d in detections:
        latest_by_source[d["source"]] = max(latest_by_source.get(d["source"], ""), d["acq_time"])
    for source, t in sorted(latest_by_source.items(), key=lambda kv: kv[1], reverse=True):
        rows.append({"source": source, "label": "Satellite", "last_seen": t})
    for kind, label in (("line_fault", "Line fault"), ("report", "Public report")):
        times = [x for x in signals if x["kind"] == kind]
        if times:
            last = max(times, key=lambda x: x["time"])
            rows.append({"source": last.get("circuit") or kind, "label": label, "last_seen": last["time"]})
    if weather:
        station = re.sub(r"\s*\([^)]*\)\s*$", "", weather.get("station") or "") or None  # "Medicine Lodge airport (K51)" -> "Medicine Lodge airport"
        rows.append({
            "source": station or weather.get("source") or "weather",
            "label": f"Weather ({station})" if station else "Weather",
            "last_seen": weather.get("observed_at"),
        })
    return rows


def _utc_iso(dt: datetime) -> str:
    return iso(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


class BurnIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    start: datetime
    end: datetime
    called_in: datetime | None = None
    caller: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _window(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        # A logged burn hides real fires near it, so its window is bounded.
        if self.end - self.start > timedelta(hours=24):
            raise ValueError("a burn window can be at most 24 hours")
        start = self.start if self.start.tzinfo else self.start.replace(tzinfo=timezone.utc)
        if start - datetime.now(timezone.utc) > timedelta(days=14):
            raise ValueError("a burn can be logged at most 14 days ahead")
        return self


@api.post("/burns", status_code=201)
def post_burn(body: BurnIn):
    called_in = body.called_in or utcnow()
    with connect() as conn:
        r = add_burn(conn, body.lat, body.lon, _utc_iso(body.start), _utc_iso(body.end), _utc_iso(called_in),
                     body.caller, body.label, is_sample=get_settings().mode == "sample")
        return _burn_row(conn.execute("SELECT * FROM burns WHERE id = ?", (r["id"],)).fetchone())


def _burn_row(b) -> dict:
    return {"id": b["id"], "lat": b["lat"], "lon": b["lon"], "start": b["start"], "end": b["end"],
            "called_in": b["called_in"], "caller": b["caller"], "label": b["label"], "is_sample": bool(b["is_sample"])}


@api.get("/burns")
def list_burns():
    with connect() as conn:
        return {"burns": [_burn_row(b) for b in conn.execute('SELECT * FROM burns ORDER BY "start", id')]}


def _recent(v: datetime | None) -> datetime | None:
    """Live signal times: within the last 48 hours, at most 10 minutes ahead (clocks drift)."""
    if v is None:
        return v
    t = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    now = utcnow()
    if t < now - timedelta(hours=48) or t > now + timedelta(minutes=10):
        raise ValueError("time must be within the last 48 hours and not in the future")
    return v


class LineFaultIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    time: datetime | None = None
    circuit: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="fault", min_length=1, max_length=40)

    _time_ok = field_validator("time")(_recent)


PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


class ReportIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    text: str = Field(min_length=1, max_length=500)
    phone: str | None = Field(default=None, max_length=30)
    time: datetime | None = None

    _time_ok = field_validator("time")(_recent)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None):
        if v is None or v == "":
            return None
        cleaned = re.sub(r"[\s().-]", "", v)
        if not PHONE_RE.match(cleaned):
            raise ValueError("phone must be 7 to 15 digits, with an optional leading +")  # never echo the value
        return cleaned


def _signal_weather() -> dict | None:
    """Sample mode has no live weather feed; hand-posted signals use the scenario's weather."""
    return sample.scenario_weather() if get_settings().mode == "sample" else None


def _signal_result(conn, r: dict) -> dict:
    out = dict(r)
    if r["event_id"]:
        ev = conn.execute("SELECT score, recommendation FROM events WHERE id = ?", (r["event_id"],)).fetchone()
        out.update(score=ev["score"], recommendation=ev["recommendation"])
    return out


@api.post("/signals/line-fault", status_code=201)
def post_line_fault(body: LineFaultIn):
    when = _utc_iso(body.time) if body.time else iso(utcnow())
    with connect() as conn:
        r = process_line_fault(conn, body.lat, body.lon, when, body.circuit, body.kind,
                               is_sample=get_settings().mode == "sample", weather=_signal_weather())
        return _signal_result(conn, r)


@api.post("/signals/report", status_code=201)
def post_report(body: ReportIn):
    when = _utc_iso(body.time) if body.time else iso(utcnow())
    with connect() as conn:
        r = process_report(conn, body.lat, body.lon, when, body.text, body.phone,
                           is_sample=get_settings().mode == "sample", weather=_signal_weather())
        return _signal_result(conn, r)


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
            minutes=minutes, ignitions=[(r["lat"], r["lon"]) for r in dets],
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


app.include_router(alerts_router)  # Respond: CAP, in-path, messages, notify (dry-run unless FIREWATCH_NOTIFY_LIVE=1)
app.include_router(lite_router)  # Low-data: /lite page (no JS) and /api/lite/alerts
app.include_router(api)


@app.get("/")
def root():
    return {"name": "Firewatch Confirmation Layer", "docs": "/docs", "api": "/api"}
