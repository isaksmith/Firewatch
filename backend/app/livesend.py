"""Live-send safeguard: a real SMS needs the operator token, and one event can be texted live once per cooldown.

Practice and dry-run sends (sample mode, scenario replays, the outbox gateway) never come here. A real send is one
that would go through Twilio. The token is FIREWATCH_OPERATOR_TOKEN and is compared with hmac.compare_digest. An
endpoint that can cause real texts wraps its work in `operator(header_value)`; notify.send asks `check` before every
Twilio call. Work with no operator (the background poll and tick loops) is held, not sent, and the held text is
recorded as a message with status "held" so the console shows it and an operator can release it with a decision.
The token is never logged and never returned.
"""

import hmac
import logging
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import HTTPException

from .config import get_settings
from .db import parse_iso, utcnow

log = logging.getLogger(__name__)
COOLDOWN = timedelta(minutes=2)
_current: ContextVar["Grant | None"] = ContextVar("live_grant", default=None)


@dataclass
class Grant:
    authorized: bool
    events: set[int] = field(default_factory=set)  # events this operator action has already been cleared to text


def token_ok(given: str | None) -> bool:
    """True when an operator token is configured and `given` matches it. Unset means live sending is off."""
    want = get_settings().firewatch_operator_token
    return bool(want) and hmac.compare_digest(want.encode(), (given or "").encode())


def real_sms_possible(is_sample: bool) -> bool:
    return (not is_sample) and get_settings().sms_gateway == "twilio"


@contextmanager
def operator(given: str | None):
    """Mark the work inside as done by the operator if `given` is the right token."""
    g = Grant(authorized=token_ok(given))
    t = _current.set(g)
    try:
        yield g
    finally:
        _current.reset(t)


def _last_live_text(conn: sqlite3.Connection, event_id: int) -> datetime | None:
    r = conn.execute(
        "SELECT MAX(created_at) t FROM messages WHERE event_id = ? AND direction = 'out' AND channel = 'sms' "
        "AND is_sample = 0 AND status != 'held'",
        (event_id,),
    ).fetchone()
    return parse_iso(r["t"]) if r and r["t"] else None


def check(conn: sqlite3.Connection, event_id: int | None, now: datetime | None = None) -> str | None:
    """None if a real SMS may go out now, else the plain reason it is held. Clears the event for this action."""
    g = _current.get()
    if g is None or not g.authorized:
        return "operator token needed"
    if event_id is None or event_id in g.events:
        return None
    last = _last_live_text(conn, event_id)
    if last is not None and (now or utcnow()) - last < COOLDOWN:
        return "cooldown: this event was texted live less than 2 minutes ago"
    g.events.add(event_id)
    return None


def precheck(given: str | None, conn: sqlite3.Connection, event_id: int) -> None:
    """For endpoints: refuse before doing anything when the event would send real texts and may not."""
    if not token_ok(given):
        raise HTTPException(401, "live texting needs the operator token (X-Firewatch-Operator-Token)")
    last = _last_live_text(conn, event_id)
    if last is not None and utcnow() - last < COOLDOWN:
        wait = int((COOLDOWN - (utcnow() - last)).total_seconds()) + 1
        raise HTTPException(429, f"this event was texted live less than 2 minutes ago; try again in {wait} s",
                            headers={"Retry-After": str(wait)})
