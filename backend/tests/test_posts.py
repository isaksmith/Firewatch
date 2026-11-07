"""M2a: the community board. Posts, confirms, the timer, the ask round, and the handler paths."""
from datetime import timedelta

import pytest

from app import notify, posts
from app.db import connect, iso, parse_iso
from app.notify import SMS_MAX

HERE = (37.77, -96.66)
FAR = (45.0, -90.0)
NOW = parse_iso("2026-03-14T18:50:00Z")
_n = [0]


def mk(conn, role="rancher", lat=37.78, lon=-96.66, registered=1, rank=None, opted=1):
    _n[0] += 1
    phone = f"+1316555{_n[0]:04d}"
    conn.execute(
        "INSERT INTO contacts(name, phone, role, lat, lon, weekday_avail, ladder_rank, opted_in, registered) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (f"M{_n[0]}", phone, role, lat, lon, 1, rank, opted, registered))
    return conn.execute("SELECT * FROM contacts WHERE phone = ?", (phone,)).fetchone()


def duty(conn):
    return mk(conn, role="duty_officer", lat=37.9, lon=-96.5, rank=1)


def out(conn, purpose=None):
    q = "SELECT * FROM messages WHERE direction = 'out'" + (" AND purpose = ?" if purpose else "")
    return conn.execute(q, (purpose,) if purpose else ()).fetchall()


def level(conn, eid):
    return conn.execute("SELECT recommendation FROM events WHERE id = ?", (eid,)).fetchone()["recommendation"]


def anon_post(conn, hearsay=False, cat="fire", at=HERE, now=NOW):
    return posts.create(conn, None, "+13165559999", "smoke on the ridge", cat, hearsay, now, True, "sms", at=at)


# ---- What a post does ----
def test_member_fire_opens_event():
    with connect() as conn:
        duty(conn); m = mk(conn)
        r = posts.create(conn, m, m["phone"], "fire north", "fire", False, NOW, True, at=HERE)
        assert r["event_id"] and not r["flagged"]
        assert conn.execute("SELECT event_id FROM posts WHERE id = ?", (r["post_id"],)).fetchone()[0] == r["event_id"]


def test_anonymous_fire_flagged_and_asks():
    with connect() as conn:
        duty(conn); mk(conn); mk(conn)
        r = anon_post(conn)
        assert r["flagged"] and r["event_id"] is None and r["asked"] == 2
        assert all(len(m["body"]) <= SMS_MAX for m in out(conn, "ask_post"))


def test_hearsay_member_flagged():
    with connect() as conn:
        m = mk(conn)
        r = posts.create(conn, m, m["phone"], "heard there is a fire", "fire", True, NOW, True, at=HERE)
        assert r["flagged"] and r["event_id"] is None


def test_hazard_and_other_plain():
    with connect() as conn:
        m = mk(conn)
        r = posts.create(conn, m, m["phone"], "downed line", "hazard", False, NOW, True, at=HERE)
        assert r["post_id"] and not r["flagged"] and r["event_id"] is None and not out(conn)


def test_nearby_post_joins_parent_and_asks_nothing():
    with connect() as conn:
        mk(conn)
        a = anon_post(conn)
        before = len(out(conn))
        b = anon_post(conn, at=(37.771, -96.66))
        assert b["parent_id"] == a["post_id"] and b["asked"] == 0 and len(out(conn)) == before


# ---- Refusals ----
def test_confirm_refusals():
    with connect() as conn:
        a, b = mk(conn), mk(conn)
        p = posts.create(conn, a, a["phone"], "smoke", "smoke", True, NOW, True, at=HERE)["post_id"]
        assert posts.confirm(conn, 9999, b, "see", NOW, True)["reason"] == "not_found"
        assert posts.confirm(conn, p, a, "see", NOW, True)["reason"] == "own_post"
        assert posts.confirm(conn, p, b, "see", NOW + timedelta(hours=7), True)["reason"] == "expired"
        assert posts.confirm(conn, p, b, "see", NOW, True)["counted"]
        assert posts.confirm(conn, p, b, "see", NOW, True)["duplicate"]
        conn.execute("UPDATE posts SET status = 'closed' WHERE id = ?", (p,))
        assert posts.confirm(conn, p, mk(conn), "see", NOW, True)["reason"] == "closed"


def test_confirm_unlocated_and_too_far():
    with connect() as conn:
        a = mk(conn); far = mk(conn, lat=FAR[0], lon=FAR[1]); nopos = mk(conn, lat=None, lon=None)
        p = posts.create(conn, a, a["phone"], "smoke", "smoke", True, NOW, True, at=HERE)["post_id"]
        assert posts.confirm(conn, p, far, "see", NOW, True)["reason"] == "too_far"
        assert posts.confirm(conn, p, nopos, "see", NOW, True)["reason"] == "no_position"
        q = posts.create(conn, a, a["phone"], "smoke", "smoke", True, NOW, True, at=None)["post_id"]
        conn.execute("UPDATE posts SET lat = NULL, lon = NULL WHERE id = ?", (q,))
        assert posts.confirm(conn, q, far, "see", NOW, True)["reason"] == "post_unlocated"


# ---- Abuse ----
def test_100_anonymous_posts_no_pages_one_round():
    with connect() as conn:
        duty(conn)
        for _ in range(3):
            mk(conn)
        for _ in range(100):
            anon_post(conn)
        assert not out(conn, "page") and not [m for m in out(conn) if m["purpose"] in ("duty_escalate", "ladder")]
        assert len(out(conn, "ask_post")) <= 3


def test_confirm_from_200_miles_triggers_nothing():
    with connect() as conn:
        a = mk(conn); far = mk(conn, lat=FAR[0], lon=FAR[1])
        p = anon_post(conn)["post_id"]
        r = posts.confirm(conn, p, far, "see", NOW, True)
        assert not r["counted"] and r["event_id"] is None


def test_two_strangers_stay_investigate():
    with connect() as conn:
        p = anon_post(conn, hearsay=True)["post_id"]
        r = posts.confirm(conn, p, mk(conn), "see", NOW, True)
        assert r["level"] == "investigate"
        r = posts.confirm(conn, p, mk(conn, registered=0), "see", NOW, True)
        assert r["level"] in ("investigate", "monitor")


def test_hearsay_plus_one_member_stays_investigate():  # defect 5
    with connect() as conn:
        poster = mk(conn)
        p = posts.create(conn, poster, poster["phone"], "heard of a fire", "fire", True, NOW, True, at=HERE)["post_id"]
        r = posts.confirm(conn, p, mk(conn), "see", NOW, True)
        assert r["level"] == "investigate"


def test_anonymous_tap_is_never_full_source():
    with connect() as conn:
        a = mk(conn)
        p = posts.create(conn, a, a["phone"], "smoke", "smoke", True, NOW, True, at=HERE)["post_id"]
        r = posts.confirm(conn, p, mk(conn, registered=0), "see", NOW, True)
        assert r["level"] != "escalate"


def test_note_never_counts_and_kind_validated_first():  # defect 11
    assert posts.KINDS == ("see", "not_seeing", "burn")
    with connect() as conn:
        a, b = mk(conn), mk(conn)
        p = anon_post(conn)["post_id"]
        r = posts.confirm(conn, p, b, "burn", NOW, True)
        assert r["reason"] == "note" and not r["counted"]
        with pytest.raises(ValueError):
            posts.confirm(conn, p, a, "bogus", NOW, True)
        with pytest.raises(ValueError):  # kind check runs before own_post and duplicate
            posts.confirm(conn, p, b, "note", NOW, True)


def test_closed_event_closes_post():  # defect 4
    with connect() as conn:
        a = mk(conn)
        r = posts.create(conn, a, a["phone"], "fire", "fire", False, NOW, True, at=HERE)
        conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (r["event_id"],))
        assert posts.confirm(conn, r["post_id"], mk(conn), "see", NOW, True)["reason"] == "closed"


# ---- Text and tap match ----
def test_text_and_tap_match():
    with connect() as conn:
        duty(conn); m1, m2 = mk(conn), mk(conn)
        p = anon_post(conn)["post_id"]
        r1 = posts.confirm(conn, p, m1, "see", NOW, True, channel="sms", lat=HERE[0], lon=HERE[1])
        c2 = mk(conn)
        r2 = posts.confirm(conn, p, c2, "see", NOW, True, channel="web", lat=HERE[0], lon=HERE[1], ip_hash="x")
        assert r1["counted"] and r2["counted"] and r2["count"] == 2


# ---- Timer ----
def test_timer_once_and_only_high_danger(monkeypatch):
    with connect() as conn:
        duty(conn)
        p = anon_post(conn)["post_id"]
        later = NOW + timedelta(minutes=6)
        assert posts.tick(conn, NOW + timedelta(minutes=1), True) == []
        assert posts.tick(conn, later, True) == [p]
        assert posts.tick(conn, later + timedelta(minutes=5), True) == []
        assert len(out(conn, "post_timer")) == 1


def test_timer_quiet_on_low_danger(monkeypatch):
    monkeypatch.setattr(posts, "high_danger", lambda *a, **k: False)
    with connect() as conn:
        duty(conn); anon_post(conn)
        assert posts.tick(conn, NOW + timedelta(minutes=6), True) == []
        assert not out(conn, "post_timer")


# ---- Caps ----
def test_ask_caps_per_member_per_day():
    with connect() as conn:
        m = mk(conn)
        for i in range(5):
            anon_post(conn, at=(37.77 + 0.2 * i, -96.66))
            conn.execute("UPDATE contacts SET lat = ?, lon = ? WHERE id = ?", (37.77 + 0.2 * (i + 1), -96.66, m["id"]))
        assert len(out(conn, "ask_post")) <= 3


def test_timer_cap(monkeypatch):
    with connect() as conn:
        duty(conn)
        for i in range(12):
            anon_post(conn, at=(37.77 + 0.1 * i, -96.66))
        posts.tick(conn, NOW + timedelta(minutes=6), True)
        assert len(out(conn, "post_timer")) <= 10


def test_hazard_texts_once_per_post():  # defect 3
    with connect() as conn:
        duty(conn); a = mk(conn)
        p = posts.create(conn, a, a["phone"], "downed line", "hazard", False, NOW, True, at=HERE)["post_id"]
        for _ in range(3):
            posts.confirm(conn, p, mk(conn), "see", NOW, True)
        assert len(out(conn, "post_hazard")) == 1
        assert conn.execute("SELECT duty_told_at FROM posts WHERE id = ?", (p,)).fetchone()[0]


def test_hazard_daily_cap():
    with connect() as conn:
        duty(conn); a = mk(conn)
        for i in range(8):
            p = posts.create(conn, a, a["phone"], "line", "hazard", False, NOW, True, at=HERE)["post_id"]
            posts.confirm(conn, p, mk(conn), "see", NOW, True)
        assert len(out(conn, "post_hazard")) <= 5


# ---- Estimated, cache ----
def test_estimated_stored_and_joins_wide():  # defect 9
    with connect() as conn:
        a = mk(conn)
        r = posts.create(conn, a, a["phone"], "fire", "fire", False, NOW, True, at=HERE, estimated=True)
        assert conn.execute("SELECT estimated FROM posts WHERE id = ?", (r["post_id"],)).fetchone()[0] == 1


def test_high_danger_caches_live(monkeypatch):  # defect 10
    import app.ingest.weather as w
    calls = []
    monkeypatch.setattr(w, "weather_at", lambda *a, **k: calls.append(1) or {"temp_c": 30, "rh_pct": 10, "wind_kmh": 40})
    posts.high_danger(37.77, -96.66, NOW, False)
    posts.high_danger(37.7701, -96.6601, NOW, False)
    assert len(calls) == 1


def test_high_danger_failure_not_cached(monkeypatch):
    import app.ingest.weather as w
    calls = []
    def boom(*a, **k):
        calls.append(1); raise RuntimeError("x")
    monkeypatch.setattr(w, "weather_at", boom)
    assert posts.high_danger(38.5, -96.1, NOW, False) is True
    posts.high_danger(38.5, -96.1, NOW, False)
    assert len(calls) == 2


# ---- Merge, replay ----
def test_merge_moves_posts_to_the_kept_event():
    from app.features import cluster
    with connect() as conn:
        a, b = mk(conn), mk(conn)
        r1 = posts.create(conn, a, a["phone"], "fire", "fire", False, NOW, True, at=HERE)
        r2 = posts.create(conn, b, b["phone"], "fire", "fire", False, NOW, True, at=(HERE[0] + 1, HERE[1]))
        assert r1["event_id"] != r2["event_id"]
        cluster._merge(conn, keep=r1["event_id"], drop=r2["event_id"])
        assert conn.execute("SELECT event_id FROM posts WHERE id = ?", (r2["post_id"],)).fetchone()[0] == r1["event_id"]


def test_free_text_smoke_from_a_member_stays_smoke_on_the_board():
    with connect() as conn:
        a = mk(conn)
        notify.handle_inbound(conn, a["phone"], "smoke over the ridge", NOW, is_sample=True)
        assert conn.execute("SELECT category FROM posts ORDER BY id DESC LIMIT 1").fetchone()[0] == "smoke"


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Stale:
    """Answers one query from a snapshot, like a read taken just before another writer committed."""

    def __init__(self, conn, sql, rows):
        self.conn, self.sql, self.rows, self.used = conn, sql, rows, False

    def execute(self, q, *a):
        if q.startswith(self.sql) and not self.used:
            self.used = True
            return _Rows(self.rows)
        return self.conn.execute(q, *a)

    def __getattr__(self, name):
        return getattr(self.conn, name)


def test_two_taps_at_once_count_once():
    with connect() as conn:
        s, m = mk(conn, registered=0), mk(conn)
        p = posts.create(conn, s, s["phone"], "smoke here", "smoke", False, NOW, True, at=HERE)["post_id"]
        assert posts.confirm(conn, p, m, "see", NOW, True)["counted"]
        before = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        r = posts.confirm(_Stale(conn, "SELECT * FROM post_confirms", []), p, m, "see", NOW, True)
        assert r["duplicate"] and conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == before


def test_two_people_at_once_do_not_double_the_posters_signal():
    with connect() as conn:
        s, m1, m2 = mk(conn, registered=0), mk(conn), mk(conn)
        p = posts.create(conn, s, s["phone"], "smoke here", "smoke", False, NOW, True, at=HERE)["post_id"]
        snap = conn.execute("SELECT * FROM posts WHERE id = ?", (p,)).fetchone()
        posts.confirm(conn, p, m1, "see", NOW, True)
        posts.confirm(_Stale(conn, "SELECT * FROM posts WHERE id", [snap]), p, m2, "see", NOW, True)
        n = conn.execute("SELECT COUNT(*) FROM signals WHERE source LIKE ?", (f"%:post:{p}",)).fetchone()[0]
        assert n == 1, "the poster's signal is written once, by whichever confirm opened the event"


def test_replay_clears_posts():
    from app import scenario
    with connect() as conn:
        a = mk(conn)
        posts.create(conn, a, a["phone"], "fire", "fire", False, NOW, True, at=HERE)
        scenario._clear_posts(conn, "1=1")
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


# ---- SMS length ----
def test_sms_lengths():
    p = {"category": "smoke", "lat": 37.77, "lon": -96.66, "id": 1, "body": "x" * 300, "created_at": iso(NOW)}
    c = {"name": "N" * 40, "lat": 37.0, "lon": -97.5}
    assert len(notify.t_ask_post(p, c, "Cottonwood Creek FD")) <= SMS_MAX
    assert len(notify.t_place_hint()) <= SMS_MAX


# ---- Handler ----
def say(conn, m, body, at=HERE):
    return notify.handle_inbound(conn, m["phone"], body, NOW, at=at, is_sample=True)


def test_reply_1_uses_newest_ask():
    with connect() as conn:
        duty(conn); m = mk(conn)
        a = anon_post(conn, at=(37.80, -96.66))["post_id"]
        b = anon_post(conn, at=(37.70, -96.66))["post_id"]
        conn.execute("UPDATE post_asks SET asked_at = ? WHERE post_id = ?", (iso(NOW - timedelta(minutes=5)), a))
        conn.execute("UPDATE post_asks SET asked_at = ? WHERE post_id = ?", (iso(NOW), b))
        say(conn, m, "1")
        assert conn.execute("SELECT COUNT(*) FROM post_confirms WHERE post_id = ?", (b,)).fetchone()[0] == 1


def test_reply_1_passes_position():  # defect 6
    with connect() as conn:
        duty(conn); m = mk(conn, lat=None, lon=None)
        anon_post(conn)
        conn.execute("INSERT OR IGNORE INTO post_asks(post_id, contact_id, asked_at) VALUES (1,?,?)", (m["id"], iso(NOW)))
        say(conn, m, "1")
        row = conn.execute("SELECT lat, counted FROM post_confirms WHERE contact_id = ?", (m["id"],)).fetchone()
        assert row and row["lat"] == HERE[0] and row["counted"] == 1


def test_own_post_and_duplicate_thanks():
    with connect() as conn:
        duty(conn); m = mk(conn)
        anon_post(conn)
        conn.execute("INSERT OR IGNORE INTO post_asks(post_id, contact_id, asked_at) VALUES (1,?,?)", (m["id"], iso(NOW)))
        r1 = say(conn, m, "1"); r2 = say(conn, m, "1")
        assert r1["reply"] and r2["reply"] and len(r2["reply"]) <= SMS_MAX


def test_unlocated_fire_row():
    with connect() as conn:
        duty(conn); m = mk(conn, lat=None, lon=None)
        notify.handle_inbound(conn, m["phone"], "FIRE", NOW, is_sample=True)
        assert conn.execute("SELECT COUNT(*) FROM posts WHERE category = 'fire'").fetchone()[0] == 1


def test_other_text_keeps_help():
    with connect() as conn:
        m = mk(conn)
        assert "text FIRE" in say(conn, m, "hello there")["reply"]


def test_burn_text_asks_for_burn():  # defect 7
    with connect() as conn:
        m = mk(conn)
        r = say(conn, m, "controlled burn on my place")["reply"]
        assert "BURN" in r and "posted to the board" not in r


def test_flagged_reply_911_and_asked_conditional():  # defect 8
    with connect() as conn:
        m = mk(conn, registered=0, lat=37.20)  # nobody to ask
        r = say(conn, m, "I see smoke on the ridge", at=(37.2, -96.66))["reply"]
        assert "911" in r and "being asked" not in r and len(r) <= SMS_MAX
    with connect() as conn:
        mk(conn); m = mk(conn, registered=0)
        r = say(conn, m, "I see smoke on the ridge")["reply"]
        assert "911" in r and "being asked" in r and len(r) <= SMS_MAX


def test_free_text_member_fire_uses_fire_helper_outside_district():  # defect 2
    with connect() as conn:
        d = duty(conn); m = mk(conn, lat=FAR[0], lon=FAR[1])
        r = say(conn, m, "there is a big fire", at=FAR)
        assert r["reply"] != "Firewatch: report received. The duty officer is being told." or out(conn, "duty_fyi_outside")
