"""HTTP routes for the Respond layer. Include with: app.include_router(router)."""

import hmac
import os
import time
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import fanout, messages
from .cap import to_cap
from .common import load_event, local_tz, miles, scenario
from .inpath import clock_now, in_path, start_of

router = APIRouter(prefix="/api/alerts", tags=["respond"])


def _event_or_404(event_id: int) -> dict:
    ev = load_event(event_id)
    if ev is None:
        raise HTTPException(404, "alert not found")
    return ev


def _with_fault(ev: dict) -> dict:
    """Sample events: the scenario's line fault (1:50 pm) is the first signal if it is near the event."""
    if not ev.get("is_sample") or "line_fault" in ev:
        return ev
    sc = scenario()
    lf = sc.get("line_fault")
    if lf and miles(lf["lat"], lf["lon"], ev["lat"], ev["lon"]) <= 2:
        t = datetime.fromisoformat(f"{sc['date_local']}T{lf['time_local']}:00").replace(tzinfo=local_tz(sc))
        return {**ev, "line_fault": {"lat": lf["lat"], "lon": lf["lon"], "time": t}}
    return ev


def _places() -> list[dict]:
    return scenario()["places"]


def _path(ev: dict) -> list[dict]:
    ev = _with_fault(ev)
    return in_path(ev, _places(), clock_now(ev))


def _composed(ev: dict) -> dict:
    path = _path(ev)
    crossing = next((p for p in path if p["kind"] == "road" and p["status"] == "coming"), None)
    enriched = dict(ev)
    if crossing:
        enriched["next_crossing"] = {"name": crossing["label"].split(" at ")[0], "time": crossing["eta_local"]}
    by_id = {p["id"]: p for p in _places()}
    owners = []
    for p in path:
        src = by_id.get(p["id"], {})
        if p["kind"] != "road" and src.get("phone") and p["status"] == "coming":
            owners.append({"id": p["id"], "name": p["label"], "phone": src["phone"],
                           "text": messages.landowner_text({**src, **p}, p["eta_local"], ev)})
    return {
        "escalated": ev.get("recommendation") == "escalate",
        "chief": messages.chief_text(enriched),
        "quiet": messages.quiet_notice(ev),
        "landowners": owners,
    }


@router.get("/{event_id}/cap.xml")
def cap_xml(event_id: int):
    return Response(to_cap(_event_or_404(event_id)), media_type="application/xml")


@router.get("/{event_id}/in-path")
def get_in_path(event_id: int):
    ev = _event_or_404(event_id)
    return {"event_id": event_id, "start": start_of(_with_fault(ev))[0].isoformat(), "now": clock_now(ev).isoformat(), "places": _path(ev)}


@router.get("/{event_id}/messages")
def get_messages(event_id: int):
    return _composed(_event_or_404(event_id))


class NotifyIn(BaseModel):
    channels: list[str] = Field(default_factory=lambda: list(fanout.CHANNELS), max_length=8)


_LIVE_COOLDOWN_S = 120
_last_live: dict[int, float] = {}


def _check_live_allowed(event_id: int, operator_token: str | None) -> None:
    """Live sends reach real phones, so they need the operator token and are limited per alert. Dry-run stays open."""
    if not fanout.is_live():
        return
    expected = os.environ.get("FIREWATCH_OPERATOR_TOKEN", "")
    if not expected:
        raise HTTPException(403, "Live sending is off until FIREWATCH_OPERATOR_TOKEN is set")
    if not operator_token or not hmac.compare_digest(operator_token, expected):
        raise HTTPException(401, "Operator token required to send live alerts")
    now = time.monotonic()
    if now - _last_live.get(event_id, -_LIVE_COOLDOWN_S) < _LIVE_COOLDOWN_S:
        raise HTTPException(429, "This alert was just sent. Wait 2 minutes before sending it again")
    _last_live[event_id] = now


@router.post("/{event_id}/notify")
def notify(event_id: int, body: NotifyIn, x_firewatch_operator: str | None = Header(default=None)):
    ev = _event_or_404(event_id)
    _check_live_allowed(event_id, x_firewatch_operator)
    msgs = _composed(ev)
    primary = msgs["chief"] if msgs["escalated"] else msgs["quiet"]
    recipients = [{"name": "Chief and duty officer", "text": primary}]
    if msgs["escalated"]:
        recipients += msgs["landowners"]
    return {"live": fanout.is_live(), "results": fanout.send(ev, recipients, body.channels)}
