"""Low-data path: a server-rendered /lite page (no JavaScript, under 8 KB) and a small JSON feed.

GET  /api/lite/alerts  compact feed for a low-data mode (ETag, 304 on a match)
GET  /lite             one HTML page for a chief on one bar of cell. Shows the newest escalate, else the newest investigate.
POST /lite/act         form target for "I'm on it", "Not a fire" and "Undo"; answers 303 back to /lite

Reads the team's alerts through app.main (imported lazily, because main includes this router): list_alerts for the
list, get_alert for the detail, act_on_alert for the action. The form carries an HMAC token keyed by FIREWATCH_SECRET.
Undo never trusts the form: it puts back the status the server recorded when the lite page made the change.
"""

import hashlib
import hmac
import html
import json
import secrets
import time
from datetime import datetime
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import fw1_feed, scenario
from .config import get_settings
from .db import connect, iso, parse_iso, utcnow

router = APIRouter()

_PROCESS_SECRET = secrets.token_bytes(32)  # used when FIREWATCH_SECRET is not set; tokens then die on restart
TOKEN_WINDOW_MIN = 30
GAP_MIN = 10
OPERATOR = "Chief (lite page)"
NOTE_PREFIX = "lite page|prev="
STATUSES = ("new", "acknowledged", "escalated", "dismissed", "closed")
LEVELS = ("escalate", "investigate")  # monitor is shown only when asked for by id
HEADLINE = {
    "escalate": "Likely fire. Page the district.",
    "investigate": "Possible fire. No page yet.",
    "monitor": "Watching. No page needed.",
}
CENTRAL = ZoneInfo("America/Chicago")
e = html.escape


def _m():
    from . import main  # lazy: main imports this module
    return main


def _secret() -> bytes:
    s = get_settings().firewatch_secret
    return s.encode() if s else _PROCESS_SECRET


# ---------- feed ----------

def _data_at(a: dict) -> str | None:
    """Newest time the evidence on this alert was observed (where the evidence carries a time)."""
    times = [x["at"] for x in a.get("evidence", []) if x.get("at")]
    return max(times) if times else None


def _feed() -> dict:
    data = _m().list_alerts()
    alerts = [
        {"id": a["id"], "level": a["recommendation"], "score": a["score"], "label": a["place_label"],
         "lat": round(a["lat"], 4), "lon": round(a["lon"], 4), "why": a["level_reason"] or a["top_reason"],
         "status": a["status"], "seen": a["last_seen"], "data_at": _data_at(a)}
        for a in data["alerts"] if a["recommendation"] in LEVELS
    ]
    alerts.sort(key=lambda a: (a["level"] != "escalate", _neg(a["seen"])))
    sup = data["suppressed"]
    quiet = {k: sup.get(k, 0) for k in ("total", "registered_burn", "static_source", "likely_prescribed", "low_signal")}
    # "t" is the newest data time, not the wall clock, so the body (and its ETag) only changes when the data does.
    t = max((a["seen"] for a in alerts), default="1970-01-01T00:00:00Z")
    return {"t": t, "alerts": alerts, "quiet": quiet}


def _neg(iso_time: str) -> float:
    return -parse_iso(iso_time).timestamp()


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    return header.strip() == "*" or any(p.strip().removeprefix("W/") == etag for p in header.split(","))


@router.get("/api/lite/alerts")
def lite_alerts(request: Request):
    body = json.dumps(_feed(), separators=(",", ":"), ensure_ascii=False).encode()
    etag = '"' + hashlib.sha256(body).hexdigest()[:20] + '"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


# ---------- form token ----------

def _token(event_id: int, action: str, minute: int | None = None) -> str:
    minute = int(time.time() // 60) if minute is None else minute
    return hmac.new(_secret(), f"{event_id}:{action}:{minute}".encode(), hashlib.sha256).hexdigest()[:24]


def _token_ok(event_id: int, action: str, token: str) -> bool:
    now = int(time.time() // 60)
    return any(hmac.compare_digest(_token(event_id, action, now - i), token) for i in range(TOKEN_WINDOW_MIN + 1))


# ---------- time ----------

def _now(ev: dict) -> datetime:
    """Scenario events keep the scenario clock; everything else uses the real clock."""
    if ev["is_sample"]:
        return scenario.clock_now(ev.get("sample_slug")) or parse_iso(ev["last_seen"])
    return utcnow()


def _clock(dt: datetime) -> str:
    d = dt.astimezone(CENTRAL)
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"


def _ago(mins: float) -> str:
    mins = max(0, int(mins))
    return "just now" if mins < 1 else f"{mins} min ago" if mins < 90 else f"{mins // 60} h {mins % 60} min ago"


# ---------- page ----------

CSS = (
    "*{box-sizing:border-box}body{overflow-wrap:anywhere;margin:0;background:#ECEFEC;color:#16222C;"
    "font:17px/1.4 system-ui,sans-serif}main{max-width:480px;margin:0 auto;padding:12px 16px 24px}"
    "h1{font-size:27px;line-height:1.1;margin:8px 0 2px}h1.f{color:#C93A15}h1.w{color:#8A5E00}"
    "h2{font-size:18px;margin:18px 0 6px}p{margin:4px 0}.s{color:#4A5863;font-size:16px}ul{margin:4px 0;padding-left:22px}"
    ".b{display:block;width:100%;min-height:56px;margin:10px 0 0;border-radius:10px;border:2px solid #16222C;"
    "background:#fff;color:#16222C;font:600 19px system-ui,sans-serif}.b.p{background:#E8461E;border-color:#E8461E;color:#fff}"
    ".g{background:#E9E5F8;border-left:8px solid #6D5BD0;border-radius:8px;padding:12px 14px;font-weight:600;margin:8px 0}"
    ".ok{background:#fff;border:2px solid #2E9E6B;border-radius:10px;padding:12px 14px;margin:8px 0;font-weight:600}"
    "a{color:#16222C}.o a{display:block;padding:12px 0;border-top:1px solid #C9D1CF;text-decoration:none}"
    "footer{margin-top:20px;font-size:13px;color:#4A5863;text-align:center}"
)


def _page(title: str, body: str, refresh: bool, status: int = 200) -> HTMLResponse:
    meta = '<meta http-equiv="refresh" content="60">' if refresh else ""
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">{meta}<title>{e(title)}</title>'
           f'<style>{CSS}</style></head><body><main>{body}</main></body></html>')
    return HTMLResponse(doc, status_code=status, headers={"Cache-Control": "no-store"})


def _plain(message: str, status: int) -> HTMLResponse:
    return _page("Firewatch", f'<h1>{e(message)}</h1><p><a href="/lite">Back to the alert page</a></p>', False, status)


def _form(event_id: int, action: str, label: str, primary: bool = False) -> str:
    return (f'<form method="post" action="/lite/act"><input type="hidden" name="id" value="{event_id}">'
            f'<input type="hidden" name="token" value="{_token(event_id, action)}">'
            f'<input type="hidden" name="action" value="{action}"><button class="b{" p" if primary else ""}">{e(label)}</button></form>')


def _undo_status(eid: int) -> str | None:
    """The status to put back, if the newest action on this event is one this page made. Read from the server's log."""
    with connect() as conn:
        row = conn.execute("SELECT operator, note FROM actions WHERE event_id = ? ORDER BY id DESC LIMIT 1", (eid,)).fetchone()
    if row is None or row["operator"] != OPERATOR or not (row["note"] or "").startswith(NOTE_PREFIX):
        return None
    prev = row["note"].removeprefix(NOTE_PREFIX)
    return prev if prev in STATUSES else None


def _alert_body(d: dict, done: str | None) -> str:
    now = _now(d)
    rec = d["recommendation"] or "monitor"
    out = []
    times = [parse_iso(x["at"]) for x in d["evidence"] if x.get("at")]
    if times:
        gap = (now - max(times)).total_seconds() / 60
        if gap > GAP_MIN:
            out.append(f'<div class="g">No new data for {int(gap)} min. Call dispatch if you see smoke.</div>')
    else:
        out.append('<div class="g">No data times on record. Call dispatch if you see smoke.</div>')
    if done:
        msgs = {"ack": "Marked: you are on it.", "dismiss": "Marked: not a fire.", "undo": "Undone. Back to how it was."}
        out.append(f'<div class="ok">{e(msgs[done])}</div>')
    if done != "undo" and _undo_status(d["id"]) is not None:
        out.append(_form(d["id"], "undo", "Undo"))
    out.append(f'<h1 class="{"f" if rec == "escalate" else "w"}">{e(HEADLINE.get(rec, HEADLINE["monitor"]))}</h1>')
    where = d["place_label"] or f"{d['lat']:.3f}, {d['lon']:.3f}"
    out.append(f'<p><b>{e(where)}</b></p>')
    score = f"Score {d['score']} out of 100. " if d["score"] is not None else ""
    out.append(f'<p class="s">{score}Status: {e(d["status"])}.</p>')
    if not done or done == "undo":
        if d["status"] == "new":
            out.append(_form(d["id"], "ack", "I'm on it", primary=True))
        if d["status"] in ("new", "acknowledged", "escalated"):
            out.append(_form(d["id"], "dismiss", "Not a fire"))
    if d["level_reason"]:
        out.append(f'<p>{e(d["level_reason"])}</p>')
    reasons = [r for r in d["reasons"] if r["contribution"] > 0][:4] or d["reasons"][:3]
    lines = [r["label"] for r in reasons] + [x["label"] for x in d["evidence"] if x.get("label") and x["kind"] != "satellite"][:4]
    if lines:
        out.append("<h2>Why</h2><ul>" + "".join(f"<li>{e(str(t))}</li>" for t in lines[:7]) + "</ul>")
    texts = [s["value"] for s in d["signal_list"] if s["kind"] == "report" and s["value"]][:2]
    if texts:
        out.append("<h2>Reports</h2><ul>" + "".join(f"<li>&ldquo;{e(t)}&rdquo;</li>" for t in texts) + "</ul>")
    fresh = []
    for x in d["evidence"]:
        if x.get("at"):
            fresh.append(f"<li>{e(str(x['label']).split(':')[0])}: {_ago((now - parse_iso(x['at'])).total_seconds() / 60)}</li>")
    if fresh:
        out.append("<h2>How fresh</h2><ul>" + "".join(fresh[:5]) + "</ul>")
    return "".join(out)


BAD_LINK = '<div class="g">That alert link isn\'t right. Showing the newest alert instead.</div>'


@router.get("/lite")
def lite_page(id: str | None = None, done: str | None = None):
    m = _m()
    data = m.list_alerts()
    active = [a for a in data["alerts"] if a["recommendation"] in LEVELS]
    sup = data["suppressed"]
    # A chief on one bar wants the newest page first: newest escalate, else newest investigate.
    ordered = sorted(sorted(active, key=lambda a: _neg(a["last_seen"])), key=lambda a: a["recommendation"] != "escalate")
    notice, d = "", None
    if id is not None:
        try:
            d = m.get_alert(int(id))
        except (ValueError, HTTPException):  # not a number, or no such alert
            notice = BAD_LINK
    if d is None:
        if not ordered:
            quiet = f"Quiet: {sup['total']} logged or other." if sup["total"] else "Quiet."
            return _page("Firewatch", f'{notice}<h1>No fires right now.</h1><p>{e(quiet)}</p>'
                         f'<p class="s">Updated {_clock(utcnow())}. Refreshes every minute.</p>', True)
        d = m.get_alert(ordered[0]["id"])
    eid = d["id"]
    shown = done if done in ("ack", "dismiss", "undo") else None
    body = notice + _alert_body(d, shown)
    others = [a for a in ordered if a["id"] != eid]
    if others:
        lines = "".join(
            f'<a href="/lite?id={a["id"]}">{"Page" if a["recommendation"] == "escalate" else "Possible"}: {e(a["place_label"] or "")}</a>'
            for a in others[:5])
        body += f'<h2>Other fires</h2><div class="o">{lines}</div>'
    burns = sup.get("registered_burn", 0)
    body += f'<p class="s">Quiet: {burns} logged burn{"" if burns == 1 else "s"}, {sup["total"] - burns} other.</p>'
    body += f'<footer>Updated {_clock(_now(d))}.' + ("" if shown else " Refreshes every minute.")
    if d["is_sample"]:
        body += "<br>Practice data. Not a real fire."
    body += "</footer>"
    return _page("Firewatch alert", body, not shown)


@router.post("/lite/act")
async def lite_act(request: Request):
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True).items()}
    try:
        eid = int(form.get("id", ""))
    except ValueError:
        return _plain("That did not work. Please try again.", 400)
    action = form.get("action", "")
    if action not in ("ack", "dismiss", "undo") or not _token_ok(eid, action, form.get("token", "")):
        return _plain("That page is out of date. Open it again and retry.", 400)
    m = _m()
    try:
        if action in ("ack", "dismiss"):
            before = _status(eid)
            # The status we are about to replace goes in the action log: that record, not the form, drives Undo.
            m.act_on_alert(eid, m.ActionIn(action="acknowledge" if action == "ack" else "dismiss",
                                           operator=OPERATOR, note=f"{NOTE_PREFIX}{before}"))
        else:
            prev = _undo_status(eid)
            if prev is None:
                return _plain("There is nothing to undo, or someone changed it since.", 409)
            _restore(eid, prev)
    except HTTPException as ex:
        if ex.status_code == 404:
            return _plain("That alert was not found.", 404)
        return _plain("Someone already changed this alert. Open it again to see.", 409)
    return RedirectResponse(f"/lite?{urlencode({'id': eid, 'done': action})}", status_code=303)


def _status(eid: int) -> str:
    with connect() as conn:
        row = conn.execute("SELECT status FROM events WHERE id = ?", (eid,)).fetchone()
    if row is None:
        raise HTTPException(404, "alert not found")
    return row["status"]


def _restore(eid: int, status: str) -> None:
    """Undo: put the stored status back and log it, which also closes the undo (the newest action is no longer ours)."""
    now = iso(utcnow())
    with connect() as conn:
        if conn.execute("SELECT 1 FROM events WHERE id = ?", (eid,)).fetchone() is None:
            raise HTTPException(404, "alert not found")
        conn.execute("INSERT INTO actions(event_id, action, operator, note, created_at) VALUES (?, ?, ?, ?, ?)",
                     (eid, "reopen", OPERATOR, f"undo, back to {status}", now))
        conn.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (status, now, eid))
        fw1_feed.sync_event(conn, eid, parse_iso(now))
