"""Low-data path: a server-rendered /lite page (no JavaScript) and a tiny JSON feed.

GET  /api/lite/alerts  compact feed for the dashboard's low-data mode (strong ETag, 304 on match)
GET  /lite             one HTML page for a chief on one bar of cell (inline CSS, one small SVG)
POST /lite/act         form target for "I'm on it", "Not a fire" and "Undo"; answers 303 back to /lite

Alert queries and the action itself are reused from app.main (imported lazily, because main
includes this router). Wire in main.py with:
    from .lite import router as lite_router
    app.include_router(lite_router)
"""

import hashlib
import hmac
import html
import json
import math
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .alerts.common import KM_PER_MILE, miles, road_phrase, scenario
from .db import connect, iso, parse_iso, utcnow
from .geo import KM_PER_DEG_LAT, km_per_deg_lon

router = APIRouter()

_PROCESS_SECRET = secrets.token_bytes(32)
TOKEN_WINDOW_MIN = 30
GAP_MIN = 10
OPERATOR = "Chief (lite page)"
PAGES = {"escalate": "Grass fire. Page the district.", "investigate": "Possible fire. No page yet."}


def _m():
    from . import main  # lazy: main imports this module
    return main


def _secret() -> bytes:
    s = os.environ.get("FIREWATCH_SECRET")
    return s.encode() if s else _PROCESS_SECRET


# ---------- feed ----------

def _feed() -> dict:
    data = _m().list_alerts()
    alerts = [
        {"id": a["id"], "score": a["score"], "rec": a["recommendation"], "label": a["place_label"],
         "lat": round(a["lat"], 4), "lon": round(a["lon"], 4), "why": a["top_reason"],
         "status": a["status"], "seen": a["last_seen"]}
        for a in data["alerts"] if a["recommendation"] in PAGES
    ]
    sup = data["suppressed"]
    quiet = {k: sup.get(k, 0) for k in ("total", "logged_burn", "static_source", "likely_prescribed", "low_signal")}
    # "t" is the newest data time, not the wall clock, so the body (and its ETag) only changes when the data does.
    t = max((a["seen"] for a in alerts), default="1970-01-01T00:00:00Z")
    return {"t": t, "alerts": alerts, "quiet": quiet}


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


# ---------- CSRF-lite token ----------

def _token(event_id: int, minute: int | None = None) -> str:
    minute = int(time.time() // 60) if minute is None else minute
    return hmac.new(_secret(), f"{event_id}:{minute}".encode(), hashlib.sha256).hexdigest()[:24]


def _token_ok(event_id: int, token: str) -> bool:
    now = int(time.time() // 60)
    return any(hmac.compare_digest(_token(event_id, now - i), token) for i in range(TOKEN_WINDOW_MIN + 1))


# ---------- time ----------

def _local_tz(ev: dict):
    if ev["is_sample"]:
        return timezone(timedelta(hours=scenario().get("utc_offset_hours", -5)))
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Chicago")
    except Exception:  # no tz database on the box: fixed CDT
        return timezone(timedelta(hours=-5))


def _clock(dt: datetime, tz) -> str:
    d = dt.astimezone(tz)
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"


def _now(ev: dict) -> datetime:
    """Sample events keep the scenario clock (their last_seen); live events use the real clock."""
    return parse_iso(ev["last_seen"]) if ev["is_sample"] else utcnow()


def _ago(mins: float) -> str:
    mins = max(0, int(mins))
    return "just now" if mins < 1 else f"{mins} min ago" if mins < 90 else f"{mins // 60} h {mins % 60} min ago"


# ---------- page pieces ----------

e = html.escape

CSS = (
    "*{box-sizing:border-box}body{overflow-wrap:anywhere;margin:0;background:#ECEFEC;color:#16222C;font:17px/1.4 system-ui,-apple-system,Roboto,sans-serif}"
    "main{max-width:480px;margin:0 auto;padding:12px 16px 24px}"
    "h1{font-size:27px;line-height:1.1;margin:8px 0 2px;font-weight:800}h1.f{color:#C93A15}h1.w{color:#8A5E00}"
    "h2{font-size:18px;margin:18px 0 6px}p{margin:4px 0}.s{color:#4A5863;font-size:16px}"
    "ul{margin:4px 0;padding-left:22px}li{margin:3px 0}"
    ".b{display:block;width:100%;min-height:56px;margin:10px 0 0;border-radius:10px;border:2px solid #16222C;"
    "background:#fff;color:#16222C;font:600 19px system-ui,sans-serif;text-align:center;cursor:pointer}"
    ".b.p{background:#E8461E;border-color:#E8461E;color:#fff}"
    ".gap{background:#E9E5F8;border-left:8px solid #6D5BD0;border-radius:8px;padding:12px 14px;font-weight:600;margin:8px 0}"
    ".ok{background:#fff;border:2px solid #2E9E6B;border-radius:10px;padding:12px 14px;margin:8px 0;font-weight:600}"
    "a{color:#16222C}.o a{display:block;padding:12px 0;border-top:1px solid #C9D1CF;text-decoration:none;min-height:24px}"
    ".q{color:#6D5BD0;font-weight:600}svg{display:block;width:100%;max-width:100%;height:auto;border:1px solid #C9D1CF;border-radius:8px}"
    "footer{margin-top:20px;font-size:13px;color:#4A5863;text-align:center}"
)


def _grid_svg(ev: dict, path: list[dict], fp: dict | None) -> str:
    """Section-grid sketch cropped to the fire and the places in its path (+1 mi); the footprint is clipped at the edge."""
    lat0, lon0 = ev["lat"], ev["lon"]
    kx = km_per_deg_lon(lat0)
    east = lambda lon: (lon - lon0) * kx / KM_PER_MILE
    north = lambda lat: (lat - lat0) * KM_PER_DEG_LAT / KM_PER_MILE
    keys = [(east(p["lon"]), north(p["lat"])) for p in path]
    xs, ys = [0.0] + [k[0] for k in keys], [0.0] + [k[1] for k in keys]
    x0, x1 = min(xs) - 1, max(xs) + 1
    y0, y1 = min(ys) - 1, max(ys) + 1
    if x1 - x0 < 3:
        x0, x1 = (x0 + x1) / 2 - 1.5, (x0 + x1) / 2 + 1.5
    if y1 - y0 < 3:
        y0, y1 = (y0 + y1) / 2 - 1.5, (y0 + y1) / 2 + 1.5
    w = 330
    sc = w / (x1 - x0)
    h = min(300, max(160, (y1 - y0) * sc))
    sc = min(sc, h / (y1 - y0))
    ox, oy = (w - (x1 - x0) * sc) / 2 - x0 * sc, (h - (y1 - y0) * sc) / 2 + y1 * sc
    px = lambda v: ox + v * sc
    py = lambda v: oy - v * sc
    box = lambda x, y, t, anchor="start": (
        f'<rect x="{x - (len(t) * 6.4 + 6 if anchor == "end" else 2):.0f}" y="{y - 11:.0f}" width="{len(t) * 6.4 + 4:.0f}" height="14" fill="#fff" fill-opacity=".85"/>'
        f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="{anchor}" font-size="11" font-weight="600">{e(t)}</text>')
    out = [f'<svg viewBox="0 0 {w} {h:.0f}" width="{w}" height="{h:.0f}" role="img" aria-label="Sketch of the fire, its path in the next hour, and nearby roads">'
           f'<rect width="{w}" height="{h:.0f}" fill="#E3D7B4"/>']
    ns_last = -99.0
    for name, r in sorted(scenario()["roads"].items(), key=lambda kv: kv[1].get("lon", 0)):
        if "lat" in r:
            y = py(north(r["lat"]))
            if 6 < y < h - 6:
                out.append(f'<path d="M0 {y:.0f}H{w}" stroke="#8A949B" stroke-width="2"/>' + box(4, y - 2, name))
        else:
            x = px(east(r["lon"]))
            if 4 < x < w - 4:
                out.append(f'<path d="M{x:.0f} 0V{h:.0f}" stroke="#8A949B" stroke-width="2"/>')
                if x - ns_last >= 40:
                    out.append(box(x + 3, h - 3, name))
                    ns_last = x
    if fp:
        parts = []
        for poly in fp["geometry"]["coordinates"]:
            ring = poly[0]
            step = max(1, len(ring) // 70)
            parts.append("M" + "L".join(f"{px(east(x)):.0f} {py(north(y)):.0f}" for x, y in ring[::step]) + "Z")
        out.append(f'<path d="{"".join(parts)}" fill="#F9D3C7" fill-opacity=".8" stroke="#E8461E" stroke-width="1.5" stroke-dasharray="4 3"/>')
    for p, (ex, ny) in list(zip(path, keys))[:5]:
        x, y = px(ex), py(ny)
        if 0 < x < w and 0 < y < h:
            t = str(p["label"]).split(" at ")[0][:22]
            out.append(f'<rect x="{x - 5:.0f}" y="{y - 5:.0f}" width="10" height="10" fill="#16222C"/>'
                       + (box(x - 8, y + 4, t, "end") if x > w * .55 else box(x + 8, y + 4, t)))
    out.append(f'<circle cx="{px(0):.0f}" cy="{py(0):.0f}" r="7" fill="#E8461E" stroke="#fff" stroke-width="2"/></svg>')
    return "".join(out)


def _where(ev: dict) -> str:
    sc = scenario()["ignition"]
    if miles(ev["lat"], ev["lon"], sc["lat"], sc["lon"]) < 15:
        return road_phrase(ev["lat"], ev["lon"])
    return ev["place_label"] or "Location not named"


def _form(event_id: int, action: str, label: str, primary: bool = False, prev: str = "") -> str:
    extra = f'<input type="hidden" name="prev" value="{e(prev)}">' if prev else ""
    return (f'<form method="post" action="/lite/act"><input type="hidden" name="id" value="{event_id}">'
            f'<input type="hidden" name="token" value="{_token(event_id)}"><input type="hidden" name="action" value="{action}">'
            f'{extra}<button class="b{" p" if primary else ""}">{label}</button></form>')


def _detail(event_id: int):
    """(summary+detail dict, raw event dict, in-path rows, footprint). Reuses main's detail and the Respond layer."""
    from .alerts.common import load_event
    from .alerts.inpath import footprint
    from .alerts.routes import _path
    d = _m().get_alert(event_id)
    raw = load_event(event_id)
    path, fp = [], None
    try:
        path = _path(raw)
        fp = footprint(raw, 60)
    except Exception:
        pass
    return d, raw, path, fp


def _page(title: str, body: str, refresh: bool, status: int = 200) -> HTMLResponse:
    meta = '<meta http-equiv="refresh" content="60">' if refresh else ""
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">{meta}<title>{e(title)}</title>'
           f'<style>{CSS}</style></head><body><main>{body}</main></body></html>')
    return HTMLResponse(doc, status_code=status, headers={"Cache-Control": "no-store"})


def _plain(message: str, status: int) -> HTMLResponse:
    return _page("Firewatch", f'<h1>{e(message)}</h1><p><a href="/lite">Back to the alert page</a></p>', False, status)


def _alert_body(d: dict, path: list[dict], fp: dict | None, raw: dict, done: str | None, prev: str) -> str:
    tz = _local_tz(d)
    now = _now(d)
    rec = d["recommendation"]
    cls = "f" if rec == "escalate" else "w"
    out = []
    # freshness: newest time across all sources
    stamps = [parse_iso(r["last_seen"]) for r in d["data_age"] if r["last_seen"]]
    if stamps:
        gap = (now - max(stamps)).total_seconds() / 60
        if gap > GAP_MIN:
            out.append(f'<div class="gap">No new data for {int(gap)} min. Call dispatch if you see smoke.</div>')
    else:
        out.append('<div class="gap">No data times on record. Call dispatch if you see smoke.</div>')
    if done:
        msgs = {"ack": "Marked: you are on it.", "dismiss": "Marked: not a fire.", "undo": "Undone. Back to how it was."}
        out.append(f'<div class="ok">{e(msgs.get(done, "Done."))}</div>')
        if done in ("ack", "dismiss") and prev:
            out.append(_form(d["id"], "undo", "Undo", prev=prev))
    out.append(f'<h1 class="{cls}">{e(PAGES.get(rec, "Possible fire. No page yet."))}</h1>')
    out.append(f'<p><b>{e(_where(d))}</b></p>')
    out.append(f'<p class="s">Score {d["score"]} out of 100. Status: {e(d["status"])}.</p>')
    # actions
    if not done:
        if d["status"] == "new":
            out.append(_form(d["id"], "ack", "I'm on it", primary=True))
        if d["status"] in ("new", "acknowledged", "escalated"):
            out.append(_form(d["id"], "dismiss", "Not a fire"))
    # reasons
    reasons = [r for r in d["reasons"] if r["contribution"] > 0][:5] or d["reasons"][:3]
    if reasons:
        out.append("<h2>Why</h2><ul>" + "".join(f"<li>{e(r['label'])}</li>" for r in reasons) + "</ul>")
    texts = [s.get("text") for s in d["signals"] if s["kind"] == "report" and s.get("text")][:2]
    if texts:
        out.append("<h2>Reports</h2><ul>" + "".join(f"<li>“{e(t)}”</li>" for t in texts) + "</ul>")
    # data age
    rows = []
    for r in d["data_age"]:
        if r["last_seen"]:
            age = (now - parse_iso(r["last_seen"])).total_seconds() / 60
            rows.append(f"<li>{e(r['label'])}: {_ago(age)}</li>")
        else:
            rows.append(f'<li class="q">{e(r["label"])}: no time on record (gap)</li>')
    if rows:
        out.append("<h2>How fresh</h2><ul>" + "".join(rows) + "</ul>")
    # in path
    if path:
        items = []
        suffix = _clock(now, tz).split()[1]  # in_path clock strings carry no am/pm; a fire's path spans under 2 hours
        for p in path[:8]:
            t = f'{p["reached_local"] if p["status"] == "reached" else p["eta_local"]} {suffix}'
            verb = "reached about" if p["status"] == "reached" else "by about"
            items.append(f"<li>{e(str(p['label']))}: {verb} {e(str(t))}"
                         + (f" ({p['eta_min']} min)" if p["eta_min"] else "") + "</li>")
        out.append("<h2>In the path</h2><ul>" + "".join(items) + "</ul>")
    out.append("<h2>Next hour</h2>" + _grid_svg(d, path, fp))
    return "".join(out)


@router.get("/lite")
def lite_page(id: int | None = None, done: str | None = None, prev: str = ""):
    m = _m()
    data = m.list_alerts()
    active = [a for a in data["alerts"] if a["recommendation"] in PAGES]
    sup = data["suppressed"]
    if id is None and not active:
        quiet = f"Quiet: {sup['total']} logged or other." if sup["total"] else "Quiet."
        return _page("Firewatch", f'<h1>No fires right now.</h1><p>{e(quiet)}</p>'
                     f'<p class="s">Updated {_clock(utcnow(), _local_tz({"is_sample": False}))}. Refreshes every minute.</p>', True)
    # A chief on one bar wants the newest page first, not the highest-scoring old one.
    newest = sorted(active, key=lambda a: a["last_seen"], reverse=True)
    newest = sorted(newest, key=lambda a: a["recommendation"] != "escalate")  # stable: pages first, newest within
    eid = id if id is not None else newest[0]["id"]
    try:
        d, raw, path, fp = _detail(eid)
    except HTTPException:
        return _plain("That alert was not found.", 404)
    body = _alert_body(d, path, fp, raw, done if done in ("ack", "dismiss", "undo") else None,
                       prev if prev in ("new", "acknowledged", "escalated") else "")
    others = [a for a in active if a["id"] != eid]
    if others:
        lines = "".join(
            f'<a href="/lite?id={a["id"]}">{a["score"]} {e("Page" if a["recommendation"] == "escalate" else "Possible")}: '
            f'{e(a["place_label"] or "")}</a>' for a in others[:6])
        body += f'<h2>Other fires</h2><div class="o">{lines}</div>'
    lb, other = sup.get("logged_burn", 0), sup["total"] - sup.get("logged_burn", 0)
    body += f'<p class="s">Quiet: {lb} logged burn{"" if lb == 1 else "s"}, {other} other.</p>'
    tz = _local_tz(d)
    shown = done in ("ack", "dismiss", "undo")
    body += f'<footer>Updated {_clock(_now(d), tz)}.' + ("" if shown else " Refreshes every minute.")
    if d["is_sample"]:
        body += "<br>Concept screen. Sample data from the Cottonwood Creek scenario."
    body += "</footer>"
    return _page("Firewatch alert", body, not shown)


@router.post("/lite/act")
async def lite_act(request: Request):
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True).items()}
    try:
        eid = int(form.get("id", ""))
    except ValueError:
        return _plain("That did not work. Please try again.", 400)
    if not _token_ok(eid, form.get("token", "")):
        return _plain("That page is out of date. Open it again and retry.", 400)
    action = form.get("action", "")
    m = _m()
    q: dict[str, str]
    try:
        if action == "ack":
            before = _status(eid)
            m.act_on_alert(eid, m.ActionIn(action="acknowledge", operator=OPERATOR, note="lite page"))
            q = {"done": "ack", "prev": before}
        elif action == "dismiss":
            before = _status(eid)
            m.act_on_alert(eid, m.ActionIn(action="dismiss", operator=OPERATOR, note="lite page"))
            q = {"done": "dismiss", "prev": before}
        elif action == "undo":
            prev = form.get("prev", "")
            if prev not in ("new", "acknowledged", "escalated"):
                return _plain("That did not work. Please try again.", 400)
            _restore(eid, prev)
            q = {"done": "undo"}
        else:
            return _plain("That did not work. Please try again.", 400)
    except HTTPException as ex:
        if ex.status_code == 404:
            return _plain("That alert was not found.", 404)
        return _plain("Someone already changed this alert. Open it again to see.", 409)
    return RedirectResponse(f"/lite?{urlencode({'id': eid, **q})}", status_code=303)


def _status(eid: int) -> str:
    with connect() as conn:
        row = conn.execute("SELECT status FROM events WHERE id = ?", (eid,)).fetchone()
    if row is None:
        raise HTTPException(404, "alert not found")
    return row["status"]


def _restore(eid: int, status: str) -> None:
    """Undo: put the previous status back and log it, using the same tables act_on_alert writes."""
    now = iso(utcnow())
    with connect() as conn:
        if conn.execute("SELECT 1 FROM events WHERE id = ?", (eid,)).fetchone() is None:
            raise HTTPException(404, "alert not found")
        conn.execute("INSERT INTO actions(event_id, action, operator, note, created_at) VALUES (?, ?, ?, ?, ?)",
                     (eid, "reopen", OPERATOR, f"undo, back to {status}", now))
        conn.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (status, now, eid))
