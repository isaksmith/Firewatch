"""The public board API. Device token only: main.py mounts the token-guarded admin_router, never this module."""
import hashlib
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator, model_validator

from . import notify, posts, scenario
from .config import get_settings
from .db import connect, iso, utcnow
from .district import LADDER_ROLES
from .keywords import classify

public_router = APIRouter()
admin_router = APIRouter()

STATION_ROLES = ("volunteer", *LADDER_ROLES)
BADGE = "Fire department is aware. Call 911 if you are in danger."
EXACT = ("fire", "smoke")


def _clock():
    replay = scenario.running_now()
    return replay or utcnow(), replay is not None or get_settings().mode == "sample"


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
def new_device():
    token = secrets.token_urlsafe(32)
    h = _hash(token)
    now = iso(utcnow())
    with connect() as conn:
        cur = conn.execute("INSERT INTO contacts(name, phone, role, registered) VALUES ('Community', ?, 'pending', 0)", (f"web:{h[:32]}",))
        conn.execute("INSERT INTO post_devices(token_hash, contact_id, created_at) VALUES (?,?,?)", (h, cur.lastrowid, now))
    return {"token": token}


@public_router.get("/board/me")
def me(x_firewatch_device: str = Header(default="")):
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
        return {"name": c["name"], "role": c["role"], "member": bool(c["registered"]), "station": c["role"] in STATION_ROLES}


def _item(conn, r, station: bool, now) -> dict:
    exact = station or r["category"] in EXACT
    lat, lon = r["lat"], r["lon"]
    if not exact and lat is not None:
        lat, lon = round(lat, 2), round(lon, 2)
    member = bool(r["a_registered"])
    author = (r["a_name"] or "Community") if station else ("Member" if member else "Community")
    held = notify.post_held(conn, r, now)
    out = {"id": r["id"], "category": r["category"], "body": r["body"], "lat": lat, "lon": lon,
           "estimated": bool(r["estimated"]), "hearsay": bool(r["hearsay"]), "flagged": bool(r["flagged"]),
           "status": r["status"], "parent_id": r["parent_id"], "event_id": r["event_id"], "created_at": r["created_at"],
           "author": author, "confirms": r["n_counted"], "notes": r["n_notes"], "badge": BADGE if held else None}
    if station:
        out["held"] = held
    return out


@public_router.get("/board/posts")
def list_posts(x_firewatch_device: str = Header(default="")):
    now, is_sample = _clock()
    with connect() as conn:
        c = _device(conn, x_firewatch_device)
        station = c is not None and c["role"] in STATION_ROLES
        q = ("SELECT p.*, c.registered a_registered, c.name a_name, "
             "(SELECT COUNT(*) FROM post_confirms k WHERE k.post_id = p.id AND k.counted = 1) n_counted, "
             "(SELECT COUNT(*) FROM post_confirms k WHERE k.post_id = p.id AND k.counted = 0) n_notes "
             "FROM posts p LEFT JOIN contacts c ON c.id = p.contact_id WHERE p.created_at >= ? AND p.is_sample = ? ")
        if not station:
            q += ("AND p.status = 'open' AND (c.registered = 1 OR p.category = 'burn' OR "
                  "EXISTS (SELECT 1 FROM post_confirms k WHERE k.post_id = p.id AND k.counted = 1)) ")
        q += "ORDER BY " + ("p.flagged DESC, " if station else "") + "p.created_at DESC, p.id DESC LIMIT 200"
        rows = conn.execute(q, (iso(now - timedelta(hours=24)), int(is_sample))).fetchall()
        return [_item(conn, r, station, now) for r in rows]


@public_router.post("/board/posts")
def create_post(body: NewPost, x_firewatch_device: str = Header(default="")):
    now, is_sample = _clock()
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
        r = posts.create(conn, c, c["phone"], body.body, body.category, classify(body.body).hearsay, now, is_sample,
                         channel="web", at=(body.lat, body.lon) if body.lat is not None else None, estimated=body.estimated)
    return {"post_id": r["post_id"], "event_id": r["event_id"], "flagged": r["flagged"], "asked": r["asked"], "known": r.get("known", False)}


@public_router.post("/board/posts/{post_id}/confirm")
def confirm_post(post_id: int, body: Confirm, request: Request, x_firewatch_device: str = Header(default="")):
    now, is_sample = _clock()
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
        ip = None if c["registered"] else _hash(request.client.host if request.client else "")
        return posts.confirm(conn, post_id, c, body.kind, now, is_sample, "web", body.lat, body.lon, ip_hash=ip)
