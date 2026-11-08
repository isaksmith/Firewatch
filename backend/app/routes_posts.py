"""The public board API. Device token only: main.py mounts the token-guarded admin_router, never this module."""
import hashlib
import io
import re
import secrets
import sqlite3
import threading
from datetime import timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Header, HTTPException, Request, Response
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, field_validator, model_validator

from . import notify, posts, scenario
from .config import get_settings
from .db import connect, iso, parse_iso, utcnow
from .confirm import burn_late, burns_overlapping, evaluate_event
from .geo import haversine_km
from .where import Where, point_from
from .district import LADDER_ROLES, load_district
from .keywords import classify
from .ratelimit import LIMITS, client_ip

public_router = APIRouter()
admin_router = APIRouter()

STATION_ROLES = ("volunteer", *LADDER_ROLES)
MAX_PHOTO = 2 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
PHOTO_SIDE = 1600
PHOTO_PIXELS = 40_000_000
# A full-size decode can take over 100 MB, and the thread pool runs 40 at once: allow two.
_DECODES = threading.BoundedSemaphore(2)
Image.MAX_IMAGE_PIXELS = PHOTO_PIXELS
# The public view: one rule for the list and the photo route.
PUBLIC_WHERE = "AND p.status = 'open' AND (e.id IS NULL OR e.status NOT IN ('dismissed', 'closed')) "
BADGE = "Fire department is aware. Call 911 if you are in danger."


def _clock():
    replay = scenario.running_now()
    return replay or utcnow(), replay is not None or get_settings().mode == "sample"


def _limit(request: Request, name: str, contact=None):
    """Rate limit for the public app only (it sets app.state.limiter). Keys on the contact only once the token is verified."""
    lim = getattr(request.app.state, "limiter", None)
    if lim is None:
        return
    ip = client_ip(request)
    keys = {"ip": f"{name}:ip:{ip}", "global": f"{name}:global"}
    if contact is not None:
        keys["device"] = f"{name}:dev:{contact['id']}"
    hits = [(keys[sc], n, w) for sc, n, w in LIMITS[name] if sc in keys]
    wait = lim.check(hits)
    if wait is not None:
        msg = "Too many requests. Try again shortly."
        if name.startswith(("post", "confirm")):
            msg = "Too many reports from this device. If there is a fire, call 911."
        raise HTTPException(429, msg, headers={"Retry-After": str(wait)})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _device(conn, token: str):
    """The contact behind a device token, or None. Updates last_seen_at."""
    if not token:
        return None
    h = _hash(token)
    row = conn.execute("SELECT c.* FROM post_devices d JOIN contacts c ON c.id = d.contact_id WHERE d.token_hash = ?", (h,)).fetchone()
    if row:
        conn.execute("UPDATE post_devices SET last_seen_at = ? WHERE token_hash = ?", (iso(utcnow()), h))
    return row


def _need(conn, token: str):
    c = _device(conn, token)
    if c is None:
        raise HTTPException(401, "missing or bad device token")
    return c


_KEY = re.compile(r"[A-Za-z0-9_-]{16,64}", re.ASCII)
COMPASS_MILES = (0.5, 2.0, 4.0, 7.0)


class _Where(BaseModel):
    lat: float | None = None
    lon: float | None = None

    @field_validator("lat")
    @classmethod
    def _lat(cls, v):
        if v is not None and not -90 <= v <= 90:
            raise ValueError("lat out of range")
        return v

    @field_validator("lon")
    @classmethod
    def _lon(cls, v):
        if v is not None and not -180 <= v <= 180:
            raise ValueError("lon out of range")
        return v

    @model_validator(mode="after")
    def _both(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon go together")
        return self


class NewPost(_Where):
    category: Literal["fire", "smoke", "hazard", "burn", "other"]
    body: str
    estimated: bool = False
    attach_location: bool = True
    client_key: str | None = None
    queued_min: int | None = None
    bearing: float | None = None
    miles: float | None = None

    @field_validator("client_key")
    @classmethod
    def _key(cls, v):
        if v is not None and not _KEY.fullmatch(v):
            raise ValueError("client_key must be 16 to 64 of A-Z a-z 0-9 _ -")
        return v

    @field_validator("queued_min")
    @classmethod
    def _queued(cls, v):
        if v is not None and not 0 <= v <= 120:
            raise ValueError("queued_min out of range")
        return v

    @field_validator("bearing")
    @classmethod
    def _bearing(cls, v):
        if v is not None and not 0 <= v < 360:
            raise ValueError("bearing out of range")
        return v

    @field_validator("miles")
    @classmethod
    def _miles(cls, v):
        if v is not None and v not in COMPASS_MILES:
            raise ValueError("miles must be 0.5, 2, 4 or 7")
        return v

    @model_validator(mode="after")
    def _compass(self):
        if (self.bearing is None) != (self.miles is None):
            raise ValueError("bearing and miles go together")
        if self.bearing is not None and self.lat is None:
            raise ValueError("a compass direction needs the reporter's position")
        return self

    @field_validator("body")
    @classmethod
    def _body(cls, v):
        v = v.strip()
        if not 1 <= len(v) <= 500:
            raise ValueError("body must be 1 to 500 characters")
        return v


class Confirm(_Where):
    kind: Literal["see", "not_seeing", "burn"]


@public_router.post("/board/device")
def new_device(request: Request):
    _limit(request, "device")
    token = secrets.token_urlsafe(32)
    h = _hash(token)
    now = iso(utcnow())
    with connect() as conn:
        cur = conn.execute("INSERT INTO contacts(name, phone, role, registered) VALUES ('Community', ?, 'pending', 0)", (f"web:{h[:32]}",))
        conn.execute("INSERT INTO post_devices(token_hash, contact_id, created_at) VALUES (?,?,?)", (h, cur.lastrowid, now))
    return {"token": token}


@public_router.get("/board/me")
def me(request: Request, x_firewatch_device: str = Header(default="")):
    _limit(request, "read")
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
        return {"name": c["name"], "role": c["role"], "member": bool(c["registered"]), "station": c["role"] in STATION_ROLES}


def _item(conn, r, station: bool, now) -> dict:
    exact = station
    lat, lon = r["lat"], r["lon"]
    if not exact and lat is not None:
        lat, lon = round(lat, 2), round(lon, 2)
    member = bool(r["a_registered"])
    author = (r["a_name"] or "Community") if station else ("Member" if member else "Community")
    held = notify.post_held(conn, r, now)
    out = {"id": r["id"], "category": r["category"], "body": r["body"], "lat": lat, "lon": lon,
           "estimated": bool(r["estimated"]), "hearsay": bool(r["hearsay"]), "flagged": bool(r["flagged"]),
           "status": r["status"], "parent_id": r["parent_id"], "created_at": r["created_at"],
           "author": author, "confirms": r["n_counted"], "notes": r["n_notes"], "badge": BADGE if held else None,
           "unconfirmed": not member and not r["n_counted"],
           "has_photo": bool(r["has_photo"]), "thread_size": r["thread_size"],
           "age_min": max(0, int((now - parse_iso(r["created_at"])).total_seconds() // 60)),
           "sent_late_min": r["queued_min"] or None}
    if station:  # the alert routes behind event_id are not public, so the public view has no link to them
        out["held"] = held
        out["event_id"] = r["event_id"]
        out["event_status"] = r["e_status"]
    return out


def _list(conn, now, is_sample: bool, station: bool) -> list[dict]:
    q = ("SELECT p.*, c.registered a_registered, c.name a_name, "
         "e.status e_status, (SELECT COUNT(*) FROM post_confirms k WHERE k.post_id = p.id AND k.counted = 1) n_counted, "
         "(SELECT COUNT(*) FROM post_confirms k WHERE k.post_id = p.id AND k.counted = 0) n_notes, "
         "EXISTS(SELECT 1 FROM post_photos ph WHERE ph.post_id = p.id) has_photo, "
         "(SELECT COUNT(*) FROM posts t WHERE t.id = COALESCE(p.parent_id, p.id) OR t.parent_id = COALESCE(p.parent_id, p.id)) thread_size "
         "FROM posts p LEFT JOIN contacts c ON c.id = p.contact_id "
         "LEFT JOIN posts par ON par.id = p.parent_id LEFT JOIN events e ON e.id = COALESCE(p.event_id, par.event_id) WHERE p.created_at >= ? AND p.is_sample = ? ")
    if not station:
        # Everyone sees every open post at once, so people nearby can confirm it (Michael, 2026-11-07).
        # A post from a non-member with no counted confirm is marked unconfirmed.
        q += PUBLIC_WHERE
    q += "ORDER BY " + ("p.flagged DESC, " if station else "") + "p.created_at DESC, p.id DESC LIMIT 200"
    rows = conn.execute(q, (iso(now - timedelta(hours=24)), int(is_sample))).fetchall()
    return [_item(conn, r, station, now) for r in rows]


@public_router.get("/board/posts")
def list_posts(request: Request, x_firewatch_device: str = Header(default="")):
    _limit(request, "read")
    now, is_sample = _clock()
    with connect() as conn:
        c = _device(conn, x_firewatch_device)
        station = c is not None and c["role"] in STATION_ROLES
        return _list(conn, now, is_sample, station)


@admin_router.get("/board/admin/posts")
def admin_posts():
    now, is_sample = _clock()
    with connect() as conn:
        return _list(conn, now, is_sample, True)


CENTRAL = ZoneInfo("America/Chicago")
BURN_NEAR_KM = 1.0


def _clock_time(dt) -> str:
    local = dt.astimezone(CENTRAL)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def _burns(conn, now, is_sample: bool, admin: bool):
    """Today's burn notices (Central date of the board clock), newest first, at most 100. The public view
    is rounded to 2 decimals and carries no identity. Its `reports_nearby` uses only the rounded burn and post
    points, which are public anyway: from exact points, anyone could post at chosen spots and close in on the burn."""
    # The same store and rule as the alert logic and the burn log (confirm.burns_overlapping): a text-registered
    # notice for today, or a burn logged by phone whose window overlaps today (Central).
    local = now.astimezone(CENTRAL)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
    rows = burns_overlapping(conn, is_sample, local.date().isoformat(), day_start, day_end,
                             "AND b.created_at <= ?", (iso(now),))
    rows = sorted(rows, key=lambda b: (b["created_at"], b["id"]), reverse=True)[:100]
    posts_ = conn.execute(
        "SELECT p.lat, p.lon FROM posts p LEFT JOIN posts par ON par.id = p.parent_id "
        "LEFT JOIN events e ON e.id = COALESCE(p.event_id, par.event_id) "
        "WHERE p.created_at >= ? AND p.is_sample = ? AND p.lat IS NOT NULL AND p.lon IS NOT NULL "
        "AND p.category IN ('fire', 'smoke') " + PUBLIC_WHERE,
        (iso(now - timedelta(hours=24)), int(is_sample)),
    ).fetchall()
    out = []
    for b in rows:
        pt = (b["lat"], b["lon"]) if admin else (round(b["lat"], 2), round(b["lon"], 2))
        near = any(haversine_km(*pt, *((p["lat"], p["lon"]) if admin else (round(p["lat"], 2), round(p["lon"], 2))))
                   <= b["radius_km"] + BURN_NEAR_KM for p in posts_)
        row = {
            "lat": pt[0],
            "lon": pt[1],
            "radius_km": b["radius_km"],
            "registered_at": _clock_time(parse_iso(b["created_at"])),
        }
        if admin:
            row["name"] = b["name"]
            row["late"] = burn_late(conn, dict(b))
            if b["start_at"]:  # logged by phone: its window (exact times are for the station only)
                row["start"], row["end"] = b["start_at"], b["end_at"]
        row["reports_nearby"] = near
        out.append(row)
    return out


@public_router.get("/board/burns")
def burns(request: Request):
    _limit(request, "read")
    now, is_sample = _clock()
    with connect() as conn:
        return _burns(conn, now, is_sample, False)


@admin_router.get("/board/admin/burns")
def admin_burns():
    now, is_sample = _clock()
    with connect() as conn:
        return _burns(conn, now, is_sample, True)


@public_router.post("/board/posts")
def create_post(body: NewPost, request: Request, x_firewatch_device: str = Header(default="")):
    now, is_sample = _clock()
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
        _limit(request, "post_member" if c["registered"] or c["role"] in STATION_ROLES else "post_anon", c)
        # With no GPS fix a member's report still sounds the alarm from their home, marked as an estimate: an alarm
        # placed roughly beats no alarm. The page tells them, so they are never told it has no location.
        used_home = body.attach_location and body.lat is None and c["lat"] is not None
        at = (body.lat, body.lon) if body.lat is not None and body.attach_location else None
        est = body.estimated or used_home
        if body.bearing is not None and body.attach_location:
            # The reporter's own fix is only the origin: the stored point is where they pointed. With location off
            # nothing is placed, since a short distance would put the point close to the reporter.
            at, est, used_home = point_from(body.lat, body.lon, Where(body.bearing, body.miles)), True, False
        if body.client_key and (first := _first_by_key(conn, c["id"], body.client_key)):
            return _answer(conn, first, duplicate=True)
        try:
            r = posts.create(conn, c, c["phone"], body.body, body.category, classify(body.body).hearsay, now, is_sample,
                             channel="web", at=at, estimated=est, use_home=body.attach_location,
                             client_key=body.client_key, queued_min=body.queued_min or None)
        except sqlite3.IntegrityError:
            # A concurrent send won the unique index. Every insert runs before any event or ask, so nothing is half written.
            first = _by_key(conn, c["id"], body.client_key) if body.client_key else None
            if first is None:
                raise
            return _answer(conn, first, duplicate=True)
    return {"post_id": r["post_id"], "flagged": r["flagged"], "asked": r["asked"], "known": r.get("known", False),
            "used_home": used_home, "alerted": r["event_id"] is not None, "duplicate": False}


def _first_by_key(conn, contact_id: int, key: str):
    return _by_key(conn, contact_id, key)


def _by_key(conn, contact_id: int, key: str):
    return conn.execute("SELECT * FROM posts WHERE contact_id = ? AND client_key = ?", (contact_id, key)).fetchone()


def _answer(conn, row, duplicate: bool) -> dict:
    """The first send's answer, rebuilt from its row."""
    asked = conn.execute("SELECT COUNT(*) n FROM post_asks WHERE post_id = ?", (row["id"],)).fetchone()["n"]
    own = conn.execute("SELECT 1 FROM signals WHERE source LIKE ?", (f"web:post:{row['id']}",)).fetchone()
    alerted = row["event_id"] is not None
    return {"post_id": row["id"], "flagged": row["flagged"], "asked": asked, "known": alerted and not own and not row["flagged"],
            "used_home": False, "alerted": alerted, "duplicate": duplicate}


def _reencode(raw: bytes, ctype: str) -> tuple[bytes, int, int]:
    try:
        with _DECODES, Image.open(io.BytesIO(raw)) as img:
            if img.format != PHOTO_TYPES[ctype]:
                raise ValueError("format mismatch")
            # Pillow only refuses past twice its limit, so check the header size before anything is decoded.
            if img.width * img.height > PHOTO_PIXELS:
                raise ValueError("too many pixels")
            if img.format == "JPEG":
                img.draft("RGB", (PHOTO_SIDE, PHOTO_SIDE))
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=75)
            return out.getvalue(), img.width, img.height
    except Exception:  # decompression bombs, truncated or foreign bytes: all the same refusal
        raise HTTPException(415, "Not a readable image of that type")


@public_router.post("/board/posts/{post_id}/photo")
async def add_photo(post_id: int, request: Request, x_firewatch_device: str = Header(default="")):
    now, _ = _clock()
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_PHOTO:
        raise HTTPException(413, "Photo too large")
    raw = await request.body()
    # Decoding and the database are blocking work: keep them off the event loop.
    return await run_in_threadpool(_store_photo, post_id, request, x_firewatch_device, raw, ctype, now)


def _store_photo(post_id: int, request: Request, x_firewatch_device: str, raw: bytes, ctype: str, now) -> dict:
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
        _limit(request, "photo", c)
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(404, "No such post")
        if post["contact_id"] != c["id"] and c["role"] not in STATION_ROLES:
            raise HTTPException(403, "Not your post")
        if post["status"] != "open" or conn.execute("SELECT 1 FROM post_photos WHERE post_id = ?", (post_id,)).fetchone():
            raise HTTPException(409, "This post cannot take a photo")
        if len(raw) > MAX_PHOTO:
            raise HTTPException(413, "Photo too large")
        if ctype not in PHOTO_TYPES:
            raise HTTPException(415, "Use a JPEG, PNG or WebP photo")
        jpeg, w, h = _reencode(raw, ctype)
        conn.execute("INSERT INTO post_photos(post_id, jpeg, width, height, created_at) VALUES (?,?,?,?,?)",
                     (post_id, jpeg, w, h, iso(now)))
    return {"ok": True, "width": w, "height": h}


def _photo_response(jpeg: bytes) -> Response:
    return Response(jpeg, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


def _photo(conn, post_id: int):
    row = conn.execute("SELECT jpeg FROM post_photos WHERE post_id = ?", (post_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No photo")
    return row["jpeg"]


@public_router.get("/board/posts/{post_id}/photo")
def get_photo(post_id: int, request: Request):
    _limit(request, "read")
    now, is_sample = _clock()
    with connect() as conn:
        visible = conn.execute(
            "SELECT 1 FROM posts p LEFT JOIN posts par ON par.id = p.parent_id "
            "LEFT JOIN events e ON e.id = COALESCE(p.event_id, par.event_id) "
            "WHERE p.id = ? AND p.created_at >= ? AND p.is_sample = ? " + PUBLIC_WHERE,
            (post_id, iso(now - timedelta(hours=24)), int(is_sample))).fetchone()
        if visible is None:
            raise HTTPException(404, "No photo")
        return _photo_response(_photo(conn, post_id))


@admin_router.get("/board/admin/posts/{post_id}/photo")
def admin_photo(post_id: int):
    with connect() as conn:
        return _photo_response(_photo(conn, post_id))


@public_router.post("/board/posts/{post_id}/confirm")
def confirm_post(post_id: int, body: Confirm, request: Request, x_firewatch_device: str = Header(default="")):
    now, is_sample = _clock()
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
        _limit(request, "confirm", c)
        ip = None if c["registered"] else _hash(client_ip(request))
        r = posts.confirm(conn, post_id, c, body.kind, now, is_sample, "web", body.lat, body.lon, ip_hash=ip)
    return {k: v for k, v in r.items() if k not in ("event_id", "level")}


class StationIn(BaseModel):
    action: Literal["ack", "send", "page", "dismiss", "resolve"]


class AdminStationIn(StationIn):
    operator: str = Field(min_length=1, max_length=80)


def _open_for_alerts(conn, root, now, is_sample, by) -> tuple[int, bool]:
    """The event for a root post, opening and logging it when it has none. Returns (event_id, opened)."""
    if root["event_id"]:
        return root["event_id"], False
    eid = posts.open_event(conn, root, now, is_sample, "web")
    evaluate_event(conn, eid, None, now)
    conn.execute("INSERT INTO actions(event_id, action, operator, note, created_at) VALUES (?,?,?,?,?)",
                 (eid, "escalate", by, "Sent to alerts from the board", iso(now)))
    return eid, True


def station_action(conn, post, action: str, by: str, role: str, now, is_sample: bool) -> dict:
    ladder = role in LADDER_ROLES or role == "operator"
    root = conn.execute("SELECT * FROM posts WHERE id = ?", (post["parent_id"],)).fetchone() if post["parent_id"] else post
    root = root or post
    eid = post["event_id"] or root["event_id"]
    ok = {"ok": True, "event_id": eid, "repeat": False}
    if action == "ack":
        r = notify.acknowledge(conn, post_id=post["id"], by=by, role=role, now=now)
        if not r["ok"]:
            raise HTTPException({"not_allowed": 403, "not_found": 404}.get(r["refused"], 409), r["refused"])
        return {**ok, "level": r["level"], "until": r["until"], "repeat": bool(r["repeat"])}
    if action in ("send", "page"):
        if action == "page" and not ladder:
            raise HTTPException(403, "Not allowed")
        if root["status"] != "open" or root["category"] not in posts.FIRE_LIKE or root["lat"] is None:
            raise HTTPException(409, "This post cannot go to alerts")
        if eid and conn.execute("SELECT status FROM events WHERE id = ?", (eid,)).fetchone()["status"] == "closed":
            raise HTTPException(409, "Event closed")
        if action == "send":
            if eid:
                return {**ok, "repeat": True}
            eid, _ = _open_for_alerts(conn, root, now, is_sample, by)
            return {**ok, "event_id": eid}
        eid, _ = _open_for_alerts(conn, root, now, is_sample, by)
        notify.decide(conn, eid, "page", by, now)
        return {**ok, "event_id": eid}
    if action == "dismiss":
        if post["status"] == "dismissed":
            return {**ok, "repeat": True}
        if post["status"] != "open":
            raise HTTPException(409, "Post is " + post["status"])
        if eid:
            if not ladder:
                raise HTTPException(403, "Not allowed")
            if conn.execute("SELECT status FROM events WHERE id = ?", (eid,)).fetchone()["status"] in ("dismissed", "closed"):
                return {**ok, "repeat": True}
            notify.decide(conn, eid, "no", by, now)
            return ok
        family = conn.execute("SELECT * FROM posts WHERE id = ? OR parent_id = ?", (root["id"], root["id"])).fetchall()
        if not ladder and any(r["event_id"] or notify.held(r, now) == "ladder" for r in family):
            raise HTTPException(403, "Not allowed")
        conn.execute(f"UPDATE posts SET status = 'dismissed', updated_at = ?, {notify.POST_HOLD_COLS} WHERE id = ? OR parent_id = ?",
                     (iso(now), root["id"], root["id"]))
        return ok
    if post["category"] != "hazard":  # resolve
        raise HTTPException(409, "Only hazards can be resolved")
    if post["status"] == "resolved":
        return {**ok, "repeat": True}
    if post["status"] != "open":
        raise HTTPException(409, "Post is " + post["status"])
    conn.execute(f"UPDATE posts SET status = 'resolved', updated_at = ?, {notify.POST_HOLD_COLS} WHERE id = ?", (iso(now), post["id"]))
    return ok


def _station(conn, post_id: int):
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if post is None:
        raise HTTPException(404, "No such post")
    return post


@public_router.post("/board/posts/{post_id}/station")
def station(post_id: int, body: StationIn, request: Request, x_firewatch_device: str = Header(default="")):
    now, is_sample = _clock()
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
        _limit(request, "station", c)
        if c["role"] not in STATION_ROLES:
            raise HTTPException(403, "Station only")
        return station_action(conn, _station(conn, post_id), body.action, c["name"], c["role"], now, is_sample)


@admin_router.post("/board/admin/posts/{post_id}/station")
def admin_station(post_id: int, body: AdminStationIn):
    now, is_sample = _clock()
    with connect() as conn:
        return station_action(conn, _station(conn, post_id), body.action, body.operator, "operator", now, is_sample)


def _issue_link(conn, contact, now, is_sample) -> dict:
    conn.execute("DELETE FROM post_devices WHERE contact_id = ?", (contact["id"],))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO post_devices(token_hash, contact_id, created_at) VALUES (?,?,?)", (_hash(token), contact["id"], iso(now)))
    base = get_settings().public_base_url
    link = f"{base.rstrip('/')}/board#d={token}" if base else None
    texted = False
    if link:
        body = f"{load_district().short_name} Firewatch: you are approved. Keep this link private: {link}"
        if len(body) <= notify.SMS_MAX:
            sent = notify.send(conn, contact, body, "member_link", None, now, is_sample, channels=("sms",),
                               log_body=f"{load_district().short_name} Firewatch: approval link sent.")
            texted = (sent or {}).get("status") == "sent"
    return {"token": None if texted else token, "link": None if texted else link, "texted": texted}


class Position(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


def _contact(conn, cid: int):
    c = conn.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "No such member")
    return c


@admin_router.get("/members/pending")
def pending_members():
    with connect() as conn:
        rows = conn.execute("SELECT id, name, phone FROM contacts WHERE role = 'pending' AND phone NOT LIKE 'web:%' ORDER BY id").fetchall()
    return [{"id": r["id"], "name": r["name"], "phone": "\u2026" + r["phone"][-4:]} for r in rows]


@admin_router.post("/members/{contact_id}/approve")
def approve_member(contact_id: int, body: Position):
    now, is_sample = _clock()
    with connect() as conn:
        c = _contact(conn, contact_id)
        if c["role"] != "pending" or c["phone"].startswith("web:"):
            raise HTTPException(409, "Not a pending member")
        conn.execute("UPDATE contacts SET role = 'spotter', registered = 1, lat = ?, lon = ? WHERE id = ?",
                     (body.lat, body.lon, contact_id))
        return _issue_link(conn, _contact(conn, contact_id), now, is_sample)


@admin_router.post("/members/{contact_id}/reject")
def reject_member(contact_id: int):
    with connect() as conn:
        if _contact(conn, contact_id)["role"] != "pending":
            raise HTTPException(409, "Not a pending member")
        conn.execute("UPDATE contacts SET role = 'rejected', registered = 0 WHERE id = ?", (contact_id,))
        conn.execute("DELETE FROM post_devices WHERE contact_id = ?", (contact_id,))
    return {"ok": True}


@admin_router.post("/members/{contact_id}/link")
def member_link(contact_id: int):
    now, is_sample = _clock()
    with connect() as conn:
        c = _contact(conn, contact_id)
        if c["phone"].startswith("web:") or c["role"] in ("pending", "rejected"):
            raise HTTPException(409, "No phone on file or not approved")
        return _issue_link(conn, c, now, is_sample)
