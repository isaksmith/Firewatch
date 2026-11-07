"""The public board API. Device token only: main.py mounts the token-guarded admin_router, never this module."""
import hashlib
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from . import notify, posts, scenario
from .config import get_settings
from .db import connect, iso, utcnow
from .confirm import evaluate_event
from .district import LADDER_ROLES, load_district
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
        out["event_status"] = r["e_status"]
    return out


@public_router.get("/board/posts")
def list_posts(x_firewatch_device: str = Header(default="")):
    now, is_sample = _clock()
    with connect() as conn:
        c = _device(conn, x_firewatch_device)
        station = c is not None and c["role"] in STATION_ROLES
        q = ("SELECT p.*, c.registered a_registered, c.name a_name, "
             "e.status e_status, (SELECT COUNT(*) FROM post_confirms k WHERE k.post_id = p.id AND k.counted = 1) n_counted, "
             "(SELECT COUNT(*) FROM post_confirms k WHERE k.post_id = p.id AND k.counted = 0) n_notes "
             "FROM posts p LEFT JOIN contacts c ON c.id = p.contact_id "
             "LEFT JOIN posts par ON par.id = p.parent_id LEFT JOIN events e ON e.id = COALESCE(p.event_id, par.event_id) WHERE p.created_at >= ? AND p.is_sample = ? ")
        if not station:
            q += ("AND p.status = 'open' AND (c.registered = 1 OR p.category = 'burn' OR "
                  "EXISTS (SELECT 1 FROM post_confirms k WHERE k.post_id = p.id AND k.counted = 1)) "
                  "AND (e.id IS NULL OR e.status NOT IN ('dismissed', 'closed')) ")
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
        if root["status"] != "open" or root["category"] not in EXACT or root["lat"] is None:
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
def station(post_id: int, body: StationIn, x_firewatch_device: str = Header(default="")):
    now, is_sample = _clock()
    with connect() as conn:
        c = _need(conn, x_firewatch_device)
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
            texted = notify.send(conn, contact, body, "member_link", None, now, is_sample, channels=("sms",),
                                        log_body=f"{load_district().short_name} Firewatch: approval link sent.") is not None
    return {"token": token, "link": link, "texted": texted}


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
        conn.execute("UPDATE contacts SET role = 'spotter', registered = 1, opted_in = 1, lat = ?, lon = ? WHERE id = ?",
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
        if c["phone"].startswith("web:"):
            raise HTTPException(409, "No phone on file")
        return _issue_link(conn, c, now, is_sample)
