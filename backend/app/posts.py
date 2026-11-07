"""The community board: posts, "I see it too" confirms, the unconfirmed-post timer and the ask round.

A post is a row. Only a registered member's first-hand fire or smoke post makes a `report` signal. Anyone
else's post stays on the board and asks nearby members; a second person confirming opens the event. Confirms
go through `report` signals at the POST's point, never `neighbor_reply`. Nothing here writes
`events.response_json`: `evaluate_event` does that for a real response.
"""

import logging
import sqlite3
from datetime import datetime, timedelta

from .db import iso, parse_iso
from .district import NEIGHBOR_ROLES, load_district
from .geo import KM_PER_MILE, haversine_km

log = logging.getLogger(__name__)

FIRE_LIKE = ("fire", "smoke")
EXPIRE_HOURS = {"fire": 6, "smoke": 6, "hazard": 24}
KINDS = ("see", "not_seeing", "burn")
REPLY_KIND = {"1": "see", "2": "not_seeing", "3": "burn"}


def _setting(key: str, default):
    return load_district().settings.get(key, default)


def _day_start(now: datetime) -> str:
    from .notify import CENTRAL

    local = now.astimezone(CENTRAL).replace(hour=0, minute=0, second=0, microsecond=0)
    return iso(local)


def _post(conn, post_id: int):
    return conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()


def _insert(conn, contact, phone, channel, category, body, pt, estimated, hearsay, flagged, parent_id, event_id, is_sample, now) -> int:
    lat, lon = pt if pt else (None, None)
    cur = conn.execute(
        "INSERT INTO posts(contact_id, phone, channel, category, body, lat, lon, estimated, hearsay, flagged, "
        "parent_id, event_id, is_sample, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (contact["id"] if contact else None, phone, channel, category, body, lat, lon, int(estimated), int(hearsay),
         int(flagged), parent_id, event_id, int(is_sample), iso(now), iso(now)),
    )
    return cur.lastrowid


def _level(conn, event_id: int | None) -> str | None:
    if event_id is None:
        return None
    r = conn.execute("SELECT recommendation FROM events WHERE id = ?", (event_id,)).fetchone()
    return r["recommendation"] if r else None


def _parent_for(conn, category: str, pt, is_sample: bool, now: datetime):
    """An open fire or smoke post with no parent near this point in the last 6 hours."""
    if category not in FIRE_LIKE or pt is None:
        return None
    km = _setting("post_join_km", 3.0)
    rows = conn.execute(
        "SELECT p.* FROM posts p LEFT JOIN events e ON e.id = p.event_id "
        "WHERE p.category IN ('fire','smoke') AND p.status = 'open' AND p.parent_id IS NULL "
        "AND (e.id IS NULL OR e.status NOT IN ('dismissed','closed')) "  # a new report beside a dismissed event is a new alarm
        "AND p.lat IS NOT NULL AND p.is_sample = ? AND p.created_at > ? ORDER BY p.id",
        (int(is_sample), iso(now - timedelta(hours=EXPIRE_HOURS["fire"]))),
    ).fetchall()
    near = [(haversine_km(pt[0], pt[1], r["lat"], r["lon"]), r) for r in rows]
    near = [(d, r) for d, r in near if d <= km]
    return min(near, key=lambda x: x[0])[1] if near else None


def _known_hold(conn, pt, is_sample: bool, now: datetime):
    """(event_id, parent_id) of a held event or post within post_join_km and 6 h of the point, else None. Sends nothing."""
    from .notify import held

    if pt is None:
        return None
    km = _setting("post_join_km", 3.0)
    for e in conn.execute("SELECT * FROM events WHERE ack_until IS NOT NULL AND status NOT IN ('closed','dismissed') "
                          "AND is_sample = ? ORDER BY id", (int(is_sample),)).fetchall():
        if held(e, now) and haversine_km(pt[0], pt[1], e["lat"], e["lon"]) <= km:
            return e["id"], None
    for p in conn.execute("SELECT * FROM posts WHERE ack_until IS NOT NULL AND status = 'open' AND lat IS NOT NULL "
                          "AND is_sample = ? AND created_at > ? ORDER BY id",
                          (int(is_sample), iso(now - timedelta(hours=EXPIRE_HOURS["fire"])))).fetchall():
        if held(p, now) and haversine_km(pt[0], pt[1], p["lat"], p["lon"]) <= km:
            return p["event_id"], p["id"]
    return None


def create(
    conn: sqlite3.Connection, contact, phone: str, body: str, category: str, hearsay: bool, now: datetime,
    is_sample: bool = False, channel: str = "sms", at: tuple[float, float] | None = None,
    estimated: bool = False,
) -> dict:
    """Store a board post from free text or the web and do what the 'What a post does' table says."""
    from .confirm import evaluate_event
    from .signals import add_signal

    pt = at or ((contact["lat"], contact["lon"]) if contact and contact["lat"] is not None else None)
    member = bool(contact and contact["registered"])
    out = {"post_id": None, "event_id": None, "asked": 0, "flagged": 0, "parent_id": None}
    if category in FIRE_LIKE:
        if member and not hearsay and pt:
            pid = _insert(conn, contact, phone, channel, category, body, pt, estimated, hearsay, False, None, None, is_sample, now)
            from .notify import ESTIMATE_JOIN_KM

            eid = add_signal(conn, "report", *pt, iso(now), f"{channel}:post:{pid}", body, contact["id"], is_sample,
                             join_radius_km=ESTIMATE_JOIN_KM if estimated else None)
            conn.execute("UPDATE posts SET event_id = ? WHERE id = ?", (eid, pid))
            evaluate_event(conn, eid, None, now)
            out.update(post_id=pid, event_id=eid)
            return out
        known = _known_hold(conn, pt, is_sample, now)
        if known:
            eid, parent_id = known
            pid = _insert(conn, contact, phone, channel, category, body, pt, estimated, hearsay, False, parent_id, eid, is_sample, now)
            out.update(post_id=pid, event_id=eid, parent_id=parent_id, known=True)
            return out
        parent = _parent_for(conn, category, pt, is_sample, now)
        pid = _insert(conn, contact, phone, channel, category, body, pt, estimated, hearsay, True,
                      parent["id"] if parent else None, None, is_sample, now)
        out.update(post_id=pid, flagged=1, parent_id=parent["id"] if parent else None)
        if parent is None and pt:
            out["asked"] = len(ask_ring(conn, _post(conn, pid), now))
        return out
    pid = _insert(conn, contact, phone, channel, category, body, pt, False, hearsay, False, None, None, is_sample, now)
    out["post_id"] = pid
    return out


def record(
    conn: sqlite3.Connection, contact, phone: str, body: str, pt, estimated: bool, event_id: int | None, now: datetime,
    is_sample: bool, channel: str, category: str = "fire",
) -> int:
    """Store the board row for a FIRE text the FIRE branch already handled. Sends nothing."""
    return _insert(conn, contact, phone, channel, category, body, pt, estimated, False, False, None, event_id, is_sample, now)


def _result(row) -> dict:
    return {"ok": True, "reason": row["reason"] or "duplicate", "counted": bool(row["counted"]), "duplicate": True}


def open_event(conn: sqlite3.Connection, post, now: datetime, is_sample: bool, channel: str = "web") -> int:
    """Open the event for a located post, carry any hold on the post (or its parent) onto it, and return its id."""
    from .notify import ESTIMATE_JOIN_KM, carry_hold
    from .signals import add_signal

    eid = add_signal(conn, "report", post["lat"], post["lon"], iso(now), f"{channel}:post:{post['id']}", post["body"],
                     None, is_sample, join_radius_km=ESTIMATE_JOIN_KM if post["estimated"] else None)
    conn.execute("UPDATE posts SET event_id = ?, updated_at = ? WHERE id = ?", (eid, iso(now), post["id"]))
    carry_hold(conn, post, eid, now)
    return eid


def confirm(
    conn: sqlite3.Connection, post_id: int, contact, kind: str, now: datetime, is_sample: bool = False,
    channel: str = "sms", lat: float | None = None, lon: float | None = None, ip_hash: str | None = None,
) -> dict:
    """One person's answer on a post. Refusals, in order: not_found, closed, expired, own_post, duplicate."""
    from .confirm import evaluate_event
    from .signals import add_signal

    post = _post(conn, post_id)
    if post is None:
        return {"ok": False, "reason": "not_found"}
    if kind not in KINDS:
        raise ValueError(f"unknown confirm kind {kind!r}")
    ev_status = conn.execute("SELECT status FROM events WHERE id = ?", (post["event_id"],)).fetchone() if post["event_id"] else None
    if post["status"] != "open" or (ev_status and ev_status["status"] == "closed"):
        return {"ok": False, "reason": "closed"}
    if now - parse_iso(post["created_at"]) > timedelta(hours=EXPIRE_HOURS.get(post["category"], 24)):
        return {"ok": False, "reason": "expired"}
    if post["contact_id"] == contact["id"]:
        return {"ok": False, "reason": "own_post"}
    dup = conn.execute("SELECT * FROM post_confirms WHERE post_id = ? AND contact_id = ?", (post_id, contact["id"])).fetchone()
    if dup is None and ip_hash:
        dup = conn.execute("SELECT * FROM post_confirms WHERE post_id = ? AND ip_hash = ?", (post_id, ip_hash)).fetchone()
    if dup:
        r = _result(dup)
        r.update(count=_count(conn, post_id), event_id=post["event_id"], level=_level(conn, post["event_id"]))
        return r

    pos = (lat, lon) if lat is not None and lon is not None else (
        (contact["lat"], contact["lon"]) if contact["lat"] is not None else None)
    counted, reason = 0, None
    if kind != "see":
        reason = "note"
    elif post["category"] not in ("fire", "smoke", "hazard"):
        reason = "note"
    elif post["lat"] is None:
        reason = "post_unlocated"
    elif pos is None:
        reason = "no_position"
    elif haversine_km(pos[0], pos[1], post["lat"], post["lon"]) > _setting("confirm_radius_mi", 15) * KM_PER_MILE:
        reason = "too_far"
    else:
        counted = 1
    cur = conn.execute(
        "INSERT OR IGNORE INTO post_confirms(post_id, contact_id, kind, channel, lat, lon, ip_hash, counted, reason, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (post_id, contact["id"], kind, channel, pos[0] if pos else None, pos[1] if pos else None, ip_hash, counted, reason, iso(now)),
    )
    if cur.rowcount == 0:  # the same person tapped twice at once and the other tap won
        row = conn.execute("SELECT * FROM post_confirms WHERE post_id = ? AND contact_id = ?", (post_id, contact["id"])).fetchone()
        r = _result(row)
        r.update(count=_count(conn, post_id), event_id=post["event_id"], level=_level(conn, post["event_id"]))
        return r
    post = _post(conn, post_id)  # re-read under the write lock: another confirm may have opened the event
    eid = post["event_id"]
    if counted and post["category"] in FIRE_LIKE:
        if eid is None:
            eid = open_event(conn, post, now, is_sample, channel)
        # The confirmer's signal sits at the post's point, never at the confirmer's.
        add_signal(conn, "report", post["lat"], post["lon"], iso(now), f"{channel}:confirm:{post_id}", None,
                   contact["id"], is_sample, event_id=eid)
        evaluate_event(conn, eid, None, now)
    elif counted and post["category"] == "hazard":
        _tell_duty_hazard(conn, post, now, is_sample)
    return {"ok": True, "reason": reason, "counted": bool(counted), "count": _count(conn, post_id),
            "event_id": eid, "level": _level(conn, eid)}


def _count(conn, post_id: int) -> int:
    return conn.execute("SELECT COUNT(*) n FROM post_confirms WHERE post_id = ? AND counted = 1", (post_id,)).fetchone()["n"]


def _sent_today(conn, purpose: str, now: datetime, is_sample: bool) -> int:
    return conn.execute(
        "SELECT COUNT(*) n FROM messages WHERE direction = 'out' AND purpose = ? AND is_sample = ? AND created_at >= ?",
        (purpose, int(is_sample), _day_start(now)),
    ).fetchone()["n"]


def _duty(conn):
    from .notify import _ladder

    ladder = _ladder(conn)
    return ladder[0] if ladder else None


def _tell_duty_hazard(conn, post, now: datetime, is_sample: bool) -> None:
    from .notify import post_held, send, t_post_duty

    if post_held(conn, post, now):
        return
    if _sent_today(conn, "post_hazard", now, is_sample) >= _setting("post_hazard_max_day", 5):
        return
    if post["duty_told_at"]:
        return
    if (duty := _duty(conn)):
        send(conn, duty, t_post_duty(post, "hazard confirmed"), "post_hazard", None, now, is_sample, post_id=post["id"])
        conn.execute("UPDATE posts SET duty_told_at = ?, updated_at = ? WHERE id = ?", (iso(now), iso(now), post["id"]))


_GFDI_CACHE: dict = {}


def high_danger(lat: float, lon: float, now: datetime, is_sample: bool) -> bool:
    """True on a day when an unconfirmed post is worth the duty officer's text. Fails open to True."""
    threshold = _setting("post_timer_min_gfdi", 12)
    if is_sample:
        return _setting("demo_gfdi", 20) >= threshold
    from .fire_weather import default_curing, gfdi
    from .ingest.weather import weather_at

    key = (round(lat, 1), round(lon, 1), now.strftime("%Y%m%d%H"))
    if key in _GFDI_CACHE:
        return _GFDI_CACHE[key] >= threshold
    try:
        w = weather_at(lat, lon, now)
        g = gfdi(default_curing(now.month), w["temp_c"], w["rh_pct"], w["wind_kmh"])
        _GFDI_CACHE[key] = g
    except Exception as e:
        log.warning("post timer weather unavailable: %s", e)
        return True
    return g >= threshold


def tick(conn: sqlite3.Connection, now: datetime, is_sample: bool) -> list[int]:
    """Text the duty officer once about an open fire or smoke post nobody has confirmed, on a high-danger day."""
    from .notify import post_held, send, t_post_duty

    told = []
    wait = timedelta(minutes=_setting("post_timer_minutes", 5))
    rows = conn.execute(
        "SELECT * FROM posts WHERE category IN ('fire','smoke') AND status = 'open' AND event_id IS NULL "
        "AND parent_id IS NULL AND duty_told_at IS NULL AND lat IS NOT NULL AND is_sample = ? ORDER BY id",
        (int(is_sample),),
    ).fetchall()
    for p in rows:
        if now - parse_iso(p["created_at"]) < wait or now - parse_iso(p["created_at"]) > timedelta(hours=EXPIRE_HOURS["fire"]):
            continue
        if post_held(conn, p, now):
            continue
        if _sent_today(conn, "post_timer", now, is_sample) >= _setting("post_timer_max_day", 10):
            break
        if not high_danger(p["lat"], p["lon"], now, is_sample):
            continue
        duty = _duty(conn)
        if duty is None:
            continue
        mins = int((now - parse_iso(p["created_at"])).total_seconds() // 60)
        send(conn, duty, t_post_duty(p, f"unconfirmed {p['category']} post, {mins} min old"), "post_timer", None, now,
             is_sample, post_id=p["id"])
        conn.execute("UPDATE posts SET duty_told_at = ?, updated_at = ? WHERE id = ?", (iso(now), iso(now), p["id"]))
        told.append(p["id"])
    return told


def ask_ring(conn: sqlite3.Connection, post, now: datetime) -> list[dict]:
    """Text nearby opted-in members once each about an unconfirmed post. Nearest first, capped per member per day."""
    from .notify import _contacts, post_held, send, t_ask_post

    if post_held(conn, post, now):
        return []
    d = load_district()
    sample = bool(post["is_sample"])
    radius_km = d.settings.get("ask_neighbor_radius_mi", 3) * KM_PER_MILE
    day = _day_start(now)
    near = []
    for c in _contacts(conn, NEIGHBOR_ROLES):
        if c["lat"] is None or not c["opted_in"] or c["id"] == post["contact_id"]:
            continue
        km = haversine_km(post["lat"], post["lon"], c["lat"], c["lon"])
        if km > radius_km:
            continue
        asked = conn.execute("SELECT COUNT(*) n FROM post_asks WHERE contact_id = ? AND asked_at >= ?", (c["id"], day)).fetchone()["n"]
        asked += conn.execute(
            "SELECT COUNT(*) n FROM messages WHERE contact_id = ? AND direction = 'out' AND purpose = 'ask_neighbor' AND created_at >= ?",
            (c["id"], day)).fetchone()["n"]
        if asked >= d.settings.get("ask_member_max_day", 3):
            continue
        near.append((km, c))
    near.sort(key=lambda kc: kc[0])
    out = []
    for km, c in near[: d.settings.get("ask_neighbor_max", 3)]:
        conn.execute("INSERT OR IGNORE INTO post_asks(post_id, contact_id, asked_at) VALUES (?,?,?)", (post["id"], c["id"], iso(now)))
        send(conn, c, t_ask_post(post, c, d.short_name), "ask_post", None, now, sample, post_id=post["id"])
        out.append({"contact_id": c["id"], "name": c["name"], "km": round(km, 2)})
    return out
