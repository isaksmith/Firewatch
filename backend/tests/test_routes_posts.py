import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, notify, routes_posts
from app.db import connect, iso, parse_iso, utcnow
from app.main import app
from app.routes_posts import BADGE, _hash

PT = (37.7712, -96.6634)
H = "X-Firewatch-Device"


def hd(t):
    return {H: t}


def device(client):
    return client.post("/api/board/device").json()["token"]


def member(name="Wes", role="spotter", registered=1, lat=37.77, lon=-96.66):
    """A contact with a device token, inserted straight into the database."""
    token = f"tok-{name}-{role}-{registered}"
    with connect() as conn:
        cur = conn.execute("INSERT INTO contacts(name, phone, role, lat, lon, registered) VALUES (?,?,?,?,?,?)",
                           (name, f"+1555{abs(hash(token)) % 10**7:07d}", role, lat, lon, registered))
        conn.execute("INSERT INTO post_devices(token_hash, contact_id, created_at) VALUES (?,?,?)",
                     (_hash(token), cur.lastrowid, iso(utcnow())))
    return token


def post(client, token, category="hazard", body="Downed power line by the creek", lat=PT[0], lon=PT[1]):
    r = client.post("/api/board/posts", json={"category": category, "body": body, "lat": lat, "lon": lon}, headers=hd(token))
    assert r.status_code == 200, r.text
    return r.json()["post_id"]


def see(client, token, pid):
    return client.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", "lat": 37.77, "lon": -96.66}, headers=hd(token))


def pub(client, token=""):
    return client.get("/api/board/posts", headers=hd(token)).json()


def ids(items):
    return [i["id"] for i in items]


def test_refusals_401():
    with TestClient(app) as c:
        for h in ({}, hd("nope")):
            assert c.get("/api/board/me", headers=h).status_code == 401
            assert c.post("/api/board/posts", json={"category": "fire", "body": "smoke"}, headers=h).status_code == 401
            assert c.post("/api/board/posts/1/confirm", json={"kind": "see"}, headers=h).status_code == 401


@pytest.mark.parametrize("payload", [
    {"category": "party", "body": "x"},
    {"category": "fire", "body": "x" * 501},
    {"category": "fire", "body": "   "},
    {"category": "fire", "body": "x", "lat": 91, "lon": 0},
    {"category": "fire", "body": "x", "lat": 10},
    {"category": "fire", "body": "x", "lon": 10},
])
def test_create_422(payload):
    with TestClient(app) as c:
        assert c.post("/api/board/posts", json=payload, headers=hd(device(c))).status_code == 422


def test_confirm_422_and_not_found():
    with TestClient(app) as c:
        t = device(c)
        assert c.post("/api/board/posts/1/confirm", json={"kind": "maybe"}, headers=hd(t)).status_code == 422
        assert c.post("/api/board/posts/1/confirm", json={"kind": "see", "lat": 5}, headers=hd(t)).status_code == 422
        r = c.post("/api/board/posts/999/confirm", json={"kind": "see"}, headers=hd(t))
        assert r.status_code == 200 and r.json()["ok"] is False and r.json()["reason"] == "not_found"


def test_device_and_me():
    with TestClient(app) as c:
        t = device(c)
        assert c.get("/api/board/me", headers=hd(t)).json() == {"name": "Community", "role": "pending", "member": False, "station": False}
        v = member("Vol", "volunteer")
        assert c.get("/api/board/me", headers=hd(v)).json()["station"] is True


def test_public_shows_anonymous_marked_unconfirmed_until_counted_confirm():
    """Michael, 2026-11-07: everyone sees a post at once, so people nearby can confirm it."""
    with TestClient(app) as c:
        anon, m = device(c), member()
        pid = post(c, anon)
        items = pub(c)
        assert ids(items) == [pid] and items[0]["unconfirmed"] is True and items[0]["author"] == "Community"
        r = see(c, m, pid)
        assert r.json()["counted"] is True
        items = pub(c)
        assert ids(items) == [pid] and items[0]["confirms"] == 1 and items[0]["unconfirmed"] is False


def test_second_anonymous_phone_can_see_and_confirm():
    with TestClient(app) as c:
        pid = post(c, device(c), "smoke", "Smoke off the highway")
        other = device(c)
        assert ids(pub(c, other)) == [pid]
        assert see(c, other, pid).status_code == 200
        assert pub(c, other)[0]["confirms"] == 1


def test_member_post_is_never_unconfirmed():
    with TestClient(app) as c:
        post(c, member(), "smoke", "Smoke to the north")
        assert pub(c)[0]["unconfirmed"] is False


def test_member_post_and_burn_show_at_once():
    with TestClient(app) as c:
        m, anon = member(), device(c)
        a = post(c, m, "hazard")
        b = post(c, anon, "burn", "Burning brush pile today")
        assert set(ids(pub(c))) == {a, b}
        assert {i["id"]: i["author"] for i in pub(c)}[a] == "Member"


def test_location_rounding():
    with TestClient(app) as c:
        m = member()
        hz = post(c, m, "hazard")
        fr = post(c, m, "fire", "Flames in the field right now")
        pv = {i["id"]: i for i in pub(c)}
        assert (pv[hz]["lat"], pv[hz]["lon"]) == (37.77, -96.66)
        assert (pv[fr]["lat"], pv[fr]["lon"]) == (37.77, -96.66)
        st = {i["id"]: i for i in pub(c, member("Vol", "volunteer"))}
        assert (st[hz]["lat"], st[hz]["lon"]) == PT
        assert (st[fr]["lat"], st[fr]["lon"]) == PT


def test_station_view_shows_hidden_flagged_first_with_name():
    with TestClient(app) as c:
        named = member("Dana", registered=0)
        first = post(c, named, "hazard")
        flagged = post(c, device(c), "fire", "Flames over by the road")
        vol = member("Vol", "volunteer")
        items = pub(c, vol)
        assert ids(items)[0] == flagged and first in ids(items)
        assert {i["id"]: i["author"] for i in items}[first] == "Dana"
        assert {i["author"] for i in pub(c)} == {"Community"}


def test_bad_token_gets_public_view():
    with TestClient(app) as c:
        post(c, member(), "hazard")
        r = c.get("/api/board/posts", headers=hd("garbage"))
        assert r.status_code == 200 and len(r.json()) == 1


def test_held_post_carries_badge_in_both_views():
    with TestClient(app) as c:
        pid = post(c, member(), "hazard")
        with connect() as conn:
            conn.execute("UPDATE posts SET ack_level = 'ladder', ack_until = ? WHERE id = ?", (iso(utcnow() + timedelta(hours=1)), pid))
        assert pub(c)[0]["badge"] == BADGE
        st = pub(c, member("Vol", "volunteer"))[0]
        assert st["badge"] == BADGE and st["held"] == "ladder"


def test_no_private_fields_leak():
    with TestClient(app) as c:
        anon, m, vol = device(c), member(), member("Vol", "volunteer")
        pid = post(c, anon)
        see(c, m, pid)
        post(c, m, "fire", "Flames in the field right now")
        raws = [c.get("/api/board/posts").text, c.get("/api/board/posts", headers=hd(vol)).text,
                c.get("/api/board/me", headers=hd(anon)).text, c.get("/api/board/me", headers=hd(vol)).text,
                c.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see"}, headers=hd(m)).text]
        for raw in raws:
            for bad in ("phone", "ip_hash", "contact_id", "web:", anon, m, vol):
                assert bad not in raw


def test_raw_token_never_stored():
    with TestClient(app) as c:
        t = device(c)
        with connect() as conn:
            assert t not in "\n".join(conn.iterdump())
            assert _hash(t) in "\n".join(conn.iterdump())


def test_same_host_members_both_count_anonymous_once():
    with TestClient(app) as c:
        pid = post(c, member("Owner"), "hazard")
        assert see(c, member("A"), pid).json()["counted"] is True
        assert see(c, member("B"), pid).json()["count"] == 2
        pid2 = post(c, member("Owner2"), "hazard")
        r1, r2 = see(c, device(c), pid2).json(), see(c, device(c), pid2).json()
        assert r1["counted"] is True and r2.get("duplicate") is True and r2["count"] == 1


def test_public_routes_ignore_api_token(monkeypatch):
    real = main.get_settings()
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(**{**vars(real), "api_token": "s3cret"}))
    assert main.get_settings().api_token == "s3cret"
    with TestClient(app) as c:
        assert c.post("/api/alerts/1/actions", json={"action": "acknowledge", "operator": "x"}).status_code == 401  # the guard is live
        t = device(c)
        pid = post(c, member(), "hazard")
        assert c.get("/api/board/me", headers=hd(t)).status_code == 200
        assert c.get("/api/board/posts").status_code == 200
        assert c.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see"}, headers=hd(t)).status_code == 200


def test_module_source_clean():
    src = Path(routes_posts.__file__).read_text()
    assert "require_token" not in src and "api_token" not in src and "import main" not in src and "from .main" not in src


def test_contacts_hides_web_rows():
    with TestClient(app) as c:
        device(c)
        member("Wes")
        rows = c.get("/api/contacts").json()
        assert rows and not any(r["phone"].startswith("web:") for r in rows)
        assert any(r["name"] == "Wes" for r in rows)


DUTY = "+13165550101"


def _fire_with_event(c):
    from app.district import sync_roster
    with connect() as conn:
        sync_roster(conn)
    pid = post(c, member("Reporter"), "fire", "Smoke column north of the grain elevator")
    with connect() as conn:
        row = conn.execute("SELECT event_id, status FROM posts WHERE id = ?", (pid,)).fetchone()
    assert row["event_id"], "fixture needs a post with an event"
    return pid, row["event_id"]


def _status(pid):
    with connect() as conn:
        return conn.execute("SELECT status FROM posts WHERE id = ?", (pid,)).fetchone()["status"]


def _station_view(c, pid):
    duty = member("DutyView", "duty_officer")
    return next(i for i in c.get("/api/board/posts", headers=hd(duty)).json() if i["id"] == pid)


def _dismissed_everywhere(c, pid):
    assert pid not in ids(pub(c))
    item = _station_view(c, pid)
    assert item["event_status"] == "dismissed" and item["status"] == "open"
    assert _status(pid) == "open"


def test_no_text_dismisses_the_event_not_the_post():
    from app import notify
    with TestClient(app) as c:
        pid, eid = _fire_with_event(c)
        assert pid in ids(pub(c))
        with connect() as conn:
            notify.decide(conn, eid, "no", "Duty", utcnow())
        _dismissed_everywhere(c, pid)


def test_dashboard_dismiss_dismisses_the_event_not_the_post():
    with TestClient(app) as c:
        pid, eid = _fire_with_event(c)
        r = c.post(f"/api/alerts/{eid}/actions", json={"action": "dismiss", "operator": "Ops"})
        assert r.status_code == 200, r.text
        _dismissed_everywhere(c, pid)


def test_child_without_event_hidden_under_dismissed_parent_event():
    with TestClient(app) as c:
        pid, eid = _fire_with_event(c)
        with connect() as conn:
            cid = conn.execute("SELECT contact_id FROM posts WHERE id = ?", (pid,)).fetchone()[0]
            kid = conn.execute("INSERT INTO posts(contact_id, category, body, status, parent_id, lat, lon, channel, is_sample, created_at, updated_at) VALUES (?,'fire','kid','open',?,?,?,'web',1,?,?)",
                               (cid, pid, *PT, iso(utcnow()), iso(utcnow()))).lastrowid
        assert kid in ids(pub(c))
        c.post(f"/api/alerts/{eid}/actions", json={"action": "dismiss", "operator": "Ops"})
        assert kid not in ids(pub(c))


def test_reraise_brings_a_dismissed_post_back():
    from app import notify, posts
    with TestClient(app) as c:
        pid = post(c, device(c), "fire", "Smoke over the field east of town")
        m1, m2 = member("M1"), member("M2")
        with connect() as conn:
            cid = lambda n: conn.execute("SELECT * FROM contacts WHERE name = ?", (n,)).fetchone()
            r1 = posts.confirm(conn, pid, cid("M1"), "see", utcnow(), True, "web", 37.77, -96.66)
            assert r1["ok"] and r1["counted"] and r1["event_id"]
            eid = r1["event_id"]
            before = conn.execute("SELECT recommendation FROM events WHERE id = ?", (eid,)).fetchone()[0]
            notify.decide(conn, eid, "no", "Duty", utcnow())
            assert conn.execute("SELECT status FROM events WHERE id = ?", (eid,)).fetchone()[0] == "dismissed"
        assert pid not in ids(pub(c))
        with connect() as conn:
            r2 = posts.confirm(conn, pid, cid("M2"), "see", utcnow(), True, "web", 37.77, -96.66)
            ev = conn.execute("SELECT status, recommendation FROM events WHERE id = ?", (eid,)).fetchone()
            n = conn.execute("SELECT COUNT(*) FROM signals WHERE event_id = ?", (eid,)).fetchone()[0]
        assert r2["ok"] and r2["counted"], r2
        assert n >= 3
        assert notify.LEVELS.index(ev["recommendation"]) > notify.LEVELS.index(before) if hasattr(notify, "LEVELS") else ev["recommendation"] != before
        assert ev["status"] == "new"
        assert pid in ids(pub(c))


def test_dashboard_reopen_brings_the_post_back():
    with TestClient(app) as c:
        pid, eid = _fire_with_event(c)
        c.post(f"/api/alerts/{eid}/actions", json={"action": "dismiss", "operator": "Ops"})
        assert pid not in ids(pub(c))
        assert c.post(f"/api/alerts/{eid}/actions", json={"action": "reopen", "operator": "Ops"}).status_code == 200
        assert pid in ids(pub(c))


@pytest.fixture(autouse=True)
def _offline_weather(monkeypatch):
    from app import confirm
    monkeypatch.setattr(confirm, "fetch_weather", lambda conn, eid: {"wind_kmh": 26, "gust_kmh": 45, "wind_dir_deg": 200, "rh_pct": 18, "temp_c": 24, "precip_72h_mm": 0, "thunder_24h": 0})


def sh(c, tok, pid, action):
    return c.post(f"/api/board/posts/{pid}/station", json={"action": action}, headers=hd(tok))


def _row(pid):
    with connect() as conn:
        return conn.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()


def _n_events():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]


def _n_out():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) n FROM messages WHERE direction = 'out'").fetchone()["n"]


def _pair(c, category="fire"):
    """An unlocated-event fire post by a community member who is not a station, plus a volunteer and a duty token."""
    pid = post(c, device(c), category, "Smoke over the field east of town")
    return pid, member("Vol", "volunteer"), member("Duty", "duty_officer")


def test_station_route_refusals():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        assert c.post(f"/api/board/posts/{pid}/station", json={"action": "ack"}).status_code == 401
        assert sh(c, member("Mem", "spotter"), pid, "ack").status_code == 403
        assert sh(c, device(c), pid, "ack").status_code == 403  # pending device
        assert sh(c, device(c), 99999, "ack").status_code == 403  # role check before lookup
        assert sh(c, vol, 99999, "ack").status_code == 404
        assert sh(c, vol, pid, "bogus").status_code == 422


def test_volunteer_limits():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        assert sh(c, vol, pid, "page").status_code == 403
        assert sh(c, vol, pid, "send").status_code == 200
        assert sh(c, vol, pid, "dismiss").status_code == 403  # now has an event
        pid2 = post(c, device(c), "fire", "Another column of smoke", lat=PT[0] + 0.3)
        r = sh(c, vol, pid2, "dismiss")
        assert r.status_code == 200 and _row(pid2)["status"] == "dismissed"
        assert sh(c, vol, pid2, "dismiss").json()["repeat"] is True


def test_send_opens_event_once():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        r = sh(c, vol, pid, "send").json()
        eid = r["event_id"]
        assert eid and r["repeat"] is False and _row(pid)["event_id"] == eid
        with connect() as conn:
            n = conn.execute("SELECT COUNT(*) n FROM actions WHERE event_id = ? AND action = 'escalate' AND note = 'Sent to alerts from the board'", (eid,)).fetchone()["n"]
        assert n == 1
        before = (_n_events(), _n_out())
        r2 = sh(c, vol, pid, "send").json()
        assert r2["repeat"] is True and r2["event_id"] == eid and (_n_events(), _n_out()) == before
        assert set(r2) == {"ok", "event_id", "repeat"}


def test_send_on_ladder_hold_texts_nothing():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        assert sh(c, duty, pid, "ack").json()["level"] == "ladder"
        before = _n_out()
        r = sh(c, vol, pid, "send").json()
        assert r["event_id"] and _n_out() == before
        with connect() as conn:
            ev = conn.execute("SELECT * FROM events WHERE id = ?", (r["event_id"],)).fetchone()
            assert notify.held(ev, utcnow()) == "ladder"


def test_hazard_and_unlocated_refuse_send_page():
    with TestClient(app) as c:
        vol, duty = member("Vol", "volunteer"), member("Duty", "duty_officer")
        haz = post(c, device(c), "hazard")
        n = _n_events()
        assert sh(c, vol, haz, "send").status_code == 409 and sh(c, duty, haz, "page").status_code == 409
        assert _n_events() == n
        nowhere = c.post("/api/board/posts", json={"category": "fire", "body": "Smoke somewhere"}, headers=hd(device(c))).json()["post_id"]
        assert sh(c, vol, nowhere, "send").status_code == 409


def test_page_opens_and_is_idempotent():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        r = sh(c, duty, pid, "page")
        assert r.status_code == 200
        eid = r.json()["event_id"]
        with connect() as conn:
            assert json.loads(conn.execute("SELECT response_json FROM events WHERE id = ?", (eid,)).fetchone()[0])["decision"] == "page"
        n = _n_out()
        assert sh(c, duty, pid, "page").status_code == 200 and _n_out() == n
        with connect() as conn:
            conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (eid,))
        assert sh(c, duty, pid, "page").status_code == 409


def test_dismiss_parent_takes_children():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        kids = []
        with connect() as conn:
            for i in range(3):
                kids.append(conn.execute("INSERT INTO posts(category, body, status, parent_id, channel, is_sample, created_at, updated_at) VALUES ('fire','kid','open',?,'web',1,?,?)",
                                         (pid, iso(utcnow()), iso(utcnow()))).lastrowid)
        assert sh(c, vol, pid, "dismiss").status_code == 200
        assert [_row(i)["status"] for i in [pid, *kids]] == ["dismissed"] * 4


def test_resolve():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        haz = post(c, device(c), "hazard")
        assert sh(c, vol, pid, "resolve").status_code == 409
        assert sh(c, vol, haz, "resolve").status_code == 200 and _row(haz)["status"] == "resolved"
        assert sh(c, vol, haz, "resolve").json()["repeat"] is True
        assert sh(c, vol, haz, "dismiss").status_code == 409


def test_child_ack_holds_parent():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        with connect() as conn:
            cid = conn.execute("SELECT contact_id FROM posts WHERE id = ?", (pid,)).fetchone()[0]
            kid = conn.execute("INSERT INTO posts(contact_id, category, body, status, parent_id, lat, lon, channel, is_sample, created_at, updated_at) VALUES (?,'fire','kid','open',?,?,?,'web',1,?,?)",
                               (cid, pid, *PT, iso(utcnow()), iso(utcnow()))).lastrowid
        r = sh(c, vol, kid, "ack")
        assert r.status_code == 200 and r.json()["level"] == "crowd"
        with connect() as conn:
            assert notify.held(_row(pid), utcnow()) == "crowd"


def test_admin_station():
    real = main.get_settings()
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        r = c.post(f"/api/board/admin/posts/{pid}/station", json={"action": "ack", "operator": "Ops"})
        assert r.status_code == 200 and r.json()["level"] == "ladder"
        assert c.post(f"/api/board/admin/posts/{pid}/station", json={"action": "ack"}).status_code == 422
        assert c.post("/api/board/admin/posts/99999/station", json={"action": "ack", "operator": "Ops"}).status_code == 404


def test_admin_station_needs_token(monkeypatch):
    real = main.get_settings()
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(**{**vars(real), "api_token": "s3cret"}))
    with TestClient(app) as c:
        assert c.post("/api/board/admin/posts/1/station", json={"action": "ack", "operator": "Ops"}).status_code == 401
        assert c.get("/api/members/pending").status_code == 401


def _join(c, phone="+13165559999", name="Pat Hill"):
    r = c.post("/api/sms/simulate", json={"from": phone, "body": f"JOIN {name}"})
    assert r.status_code == 200, r.text
    with connect() as conn:
        return conn.execute("SELECT id FROM contacts WHERE phone = ?", (phone,)).fetchone()["id"]


def test_member_flow_end_to_end():
    with TestClient(app) as c:
        cid = _join(c)
        rows = c.get("/api/members/pending").json()
        assert [r["id"] for r in rows] == [cid] and rows[0]["phone"] == "…9999"
        r = c.post(f"/api/members/{cid}/approve", json={"lat": 37.77, "lon": -96.66})
        assert r.status_code == 200 and r.json()["token"] and c.get("/api/members/pending").json() == []
        tok = r.json()["token"]
        pid = post(c, tok, "fire", "Flames in the ditch along the county road")
        with connect() as conn:
            sig = conn.execute("SELECT * FROM signals WHERE kind = 'report' AND contact_id = ?", (cid,)).fetchone()
            assert sig is not None
            assert not _row(pid)["flagged"]


def test_approve_and_reject_refusals():
    with TestClient(app) as c:
        cid = _join(c)
        assert c.post("/api/members/999/approve", json={"lat": 1, "lon": 1}).status_code == 404
        assert c.post(f"/api/members/{cid}/approve", json={}).status_code == 422
        assert c.post(f"/api/members/{cid}/approve", json={"lat": 91, "lon": 1}).status_code == 422
        assert c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6}).status_code == 200
        assert c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6}).status_code == 409
        assert c.post(f"/api/members/{cid}/reject").status_code == 409
        assert c.post("/api/members/999/reject").status_code == 404
        t = device(c)
        with connect() as conn:
            web = conn.execute("SELECT contact_id FROM post_devices WHERE token_hash = ?", (_hash(t),)).fetchone()[0]
        assert c.post(f"/api/members/{web}/approve", json={"lat": 1, "lon": 1}).status_code == 409
        assert c.post(f"/api/members/{web}/link").status_code == 409
        assert c.post("/api/members/999/link").status_code == 404


def test_reject_kills_old_token_and_link_rotates():
    with TestClient(app) as c:
        cid = _join(c)
        t0 = c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6}).json()["token"]
        t1 = c.post(f"/api/members/{cid}/link").json()["token"]
        assert c.get("/api/board/me", headers=hd(t0)).status_code == 401
        assert c.get("/api/board/me", headers=hd(t1)).status_code == 200
        c2 = _join(c, "+13165558888", "Sam")
        assert c.post(f"/api/members/{c2}/reject").status_code == 200
        with connect() as conn:
            assert conn.execute("SELECT role FROM contacts WHERE id = ?", (c2,)).fetchone()["role"] == "rejected"


def _with_base(monkeypatch, base):
    real = main.get_settings()
    s = SimpleNamespace(**{**vars(real), "public_base_url": base})
    monkeypatch.setattr(routes_posts, "get_settings", lambda: s)


def test_token_never_stored_and_link_texted(monkeypatch):
    _with_base(monkeypatch, "https://fw.example.org")
    sent = []
    monkeypatch.setattr(notify, "gateway_for", lambda is_sample: SimpleNamespace(send=lambda to, body: sent.append((to, body)) or "g1"))
    with TestClient(app) as c:
        cid = _join(c)
        with connect() as conn:
            conn.execute("UPDATE contacts SET mesh_id = '!abc12345' WHERE id = ?", (cid,))
        r = c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6}).json()
        assert r["texted"] is True and r["token"] is None and r["link"] is None
        tok = [b for _, b in sent if "#d=" in b][0].split("#d=")[1]  # the token is read from the gateway stub, not the response
        link = [b for _, b in sent if tok in b]
        assert len(link) == 1 and len(link[0]) <= notify.SMS_MAX
        with connect() as conn:
            dump = "\n".join(conn.iterdump())
            assert _hash(tok) in dump and tok not in dump
            rows = conn.execute("SELECT channel, body FROM messages WHERE purpose = 'member_link'").fetchall()
        assert [x["channel"] for x in rows] == ["sms"] and "approval link sent" in rows[0]["body"]
        assert tok not in c.get("/api/messages").text


def test_approve_dump_has_no_raw_token():
    with TestClient(app) as c:
        cid = _join(c)
        tok = c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6}).json()["token"]
        with connect() as conn:
            assert tok not in "\n".join(conn.iterdump())


def test_long_base_url_not_texted(monkeypatch):
    _with_base(monkeypatch, "https://" + "a" * 90 + ".example.org")
    with TestClient(app) as c:
        cid = _join(c)
        r = c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6}).json()
        assert r["texted"] is False and r["link"]
        with connect() as conn:
            assert conn.execute("SELECT 1 FROM messages WHERE purpose = 'member_link'").fetchone() is None


def test_public_router_has_no_admin_paths():
    paths = [r.path for r in routes_posts.public_router.routes]
    assert not any(p.startswith("/members") or p.startswith("/board/admin") for p in paths)


def test_send_logs_the_acting_volunteer_and_admin_operator():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        eid = sh(c, vol, pid, "send").json()["event_id"]
        pid2 = post(c, device(c), "fire", "Another column of smoke", lat=PT[0] + 0.3)
        r = c.post(f"/api/board/admin/posts/{pid2}/station", json={"action": "send", "operator": "Ops"})
        assert r.status_code == 200, r.text
        with connect() as conn:
            who = lambda e: conn.execute("SELECT operator FROM actions WHERE event_id = ? AND action = 'escalate'", (e,)).fetchone()["operator"]
            assert who(eid) == "Vol" and who(r.json()["event_id"]) == "Ops"


def test_repeat_ladder_dismiss_writes_one_action():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        assert sh(c, vol, pid, "send").json()["event_id"]
        r1, r2 = sh(c, duty, pid, "dismiss"), sh(c, duty, pid, "dismiss")
        assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
        assert not r1.json().get("repeat") and r2.json()["repeat"] is True
        with connect() as conn:
            n = conn.execute("SELECT COUNT(*) n FROM actions WHERE action = 'dismiss'").fetchone()["n"]
        assert n == 1


def _cfg(monkeypatch, **kw):
    real = main.get_settings()
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(**{**vars(real), **kw}))


def _n_devices():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) n FROM post_devices").fetchone()["n"]


def test_admin_fails_closed_with_blank_token_outside_sample(monkeypatch):
    with TestClient(app) as c:
        cid = _join(c)
        _cfg(monkeypatch, api_token="", mode="live")
        before = _n_devices()
        r = c.get("/api/members/pending")
        assert r.status_code == 503 and "API_TOKEN" in r.text
        assert c.post(f"/api/members/{cid}/link").status_code == 503
        assert c.post(f"/api/members/{cid}/approve", json={"lat": 1, "lon": 1}).status_code == 503
        assert _n_devices() == before


def test_admin_blank_token_still_works_in_sample_mode(monkeypatch):
    with TestClient(app) as c:
        cid = _join(c)
        _cfg(monkeypatch, api_token="", mode="sample")
        assert c.get("/api/members/pending").status_code == 200
        c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6})
        assert c.post(f"/api/members/{cid}/link").status_code == 200


def test_admin_set_token_needs_header(monkeypatch):
    with TestClient(app) as c:
        cid = _join(c)
        _cfg(monkeypatch, api_token="s3cret", mode="live")
        assert c.get("/api/members/pending").status_code == 401
        assert c.post(f"/api/members/{cid}/link").status_code == 401
        assert c.get("/api/members/pending", headers={"X-Firewatch-Token": "s3cret"}).status_code == 200


def test_link_refuses_pending_and_rejected():
    with TestClient(app) as c:
        cid = _join(c)
        before = _n_devices()
        assert c.post(f"/api/members/{cid}/link").status_code == 409  # pending
        assert c.post(f"/api/members/{cid}/reject").status_code == 200
        assert c.post(f"/api/members/{cid}/link").status_code == 409  # rejected
        assert _n_devices() == before


def test_messages_needs_token_when_set(monkeypatch):
    with TestClient(app) as c:
        _cfg(monkeypatch, api_token="s3cret")
        assert c.get("/api/messages").status_code == 401
        assert c.get("/api/messages", headers={"X-Firewatch-Token": "s3cret"}).status_code == 200


def test_token_returned_only_when_not_texted(monkeypatch):
    _with_base(monkeypatch, "https://fw.example.org")
    import httpx

    def boom(to, body):
        raise httpx.HTTPError("down")

    monkeypatch.setattr(notify, "gateway_for", lambda is_sample: SimpleNamespace(send=boom))
    with TestClient(app) as c:
        cid = _join(c)
        r = c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6}).json()
        assert r["texted"] is False and r["token"] and r["link"]  # failed send counts as not texted
        with connect() as conn:
            conn.execute("UPDATE contacts SET opted_in = 0 WHERE id = ?", (cid,))
        r = c.post(f"/api/members/{cid}/link").json()
        assert r["texted"] is False and r["token"] and r["link"]  # skipped send too


def test_approval_does_not_override_stop(monkeypatch):
    _with_base(monkeypatch, "https://fw.example.org")
    sent = []
    monkeypatch.setattr(notify, "gateway_for", lambda is_sample: SimpleNamespace(send=lambda to, body: sent.append((to, body)) or "g1"))
    with TestClient(app) as c:
        cid = _join(c)
        with connect() as conn:
            conn.execute("UPDATE contacts SET opted_in = 0 WHERE id = ?", (cid,))
        sent.clear()  # drop the join acknowledgement; only the approval matters
        r = c.post(f"/api/members/{cid}/approve", json={"lat": 37.7, "lon": -96.6}).json()
        assert r["texted"] is False and r["token"] and r["link"]
        assert sent == []
        with connect() as conn:
            assert conn.execute("SELECT opted_in FROM contacts WHERE id = ?", (cid,)).fetchone()["opted_in"] == 0


def _kid(pid, event_id=None):
    with connect() as conn:
        return conn.execute("INSERT INTO posts(category, body, status, parent_id, event_id, channel, is_sample, created_at, updated_at) VALUES ('fire','kid','open',?,?,'web',1,?,?)",
                            (pid, event_id, iso(utcnow()), iso(utcnow()))).lastrowid


def test_volunteer_cannot_dismiss_through_a_ladder_hold():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        assert sh(c, duty, pid, "ack").status_code == 200
        before = _row(pid)
        assert before["ack_level"] == "ladder"
        assert sh(c, vol, pid, "dismiss").status_code == 403
        after = _row(pid)
        assert after["status"] == "open" and after["ack_level"] == "ladder" and after["ack_until"] == before["ack_until"]
        assert sh(c, duty, pid, "dismiss").status_code == 200 and _row(pid)["status"] == "dismissed"


def test_volunteer_cannot_dismiss_a_root_whose_child_has_an_event():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        other = post(c, device(c), "fire", "Another column of smoke", lat=PT[0] + 0.3)
        eid = sh(c, vol, other, "send").json()["event_id"]
        kid = _kid(pid, eid)
        assert sh(c, vol, pid, "dismiss").status_code == 403
        assert [_row(i)["status"] for i in (pid, kid)] == ["open", "open"]
        assert sh(c, duty, pid, "dismiss").status_code == 200
        assert [_row(i)["status"] for i in (pid, kid)] == ["dismissed", "dismissed"]


def test_volunteer_dismisses_plain_and_crowd_held_families():
    with TestClient(app) as c:
        pid, vol, duty = _pair(c)
        kid = _kid(pid)
        assert sh(c, vol, pid, "dismiss").status_code == 200
        assert [_row(i)["status"] for i in (pid, kid)] == ["dismissed", "dismissed"]
        pid2 = post(c, device(c), "fire", "Another column of smoke", lat=PT[0] + 0.3)
        assert sh(c, vol, pid2, "ack").status_code == 200
        assert _row(pid2)["ack_level"] == "crowd"
        assert sh(c, vol, pid2, "dismiss").status_code == 200
        assert _row(pid2)["status"] == "dismissed" and _row(pid2)["ack_level"] is None


def test_messages_fail_closed_with_blank_token_outside_sample(monkeypatch):
    with TestClient(app) as c:
        _cfg(monkeypatch, api_token="", mode="live")
        assert c.get("/api/messages").status_code == 503


def test_location_opt_out_stores_no_point_and_no_signal():
    with TestClient(app) as c:
        m = member()
        r = c.post("/api/board/posts", headers=hd(m), json={"category": "fire", "body": "Flames by the road", "attach_location": False})
        assert r.status_code == 200
        row = _row(r.json()["post_id"])
        assert row["lat"] is None and row["lon"] is None
        with connect() as conn:
            assert conn.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"] == 0


def test_public_view_has_no_event_link():
    with TestClient(app) as c:
        pid = post(c, member(), "fire", "Flames in the field right now")
        assert "event_id" not in {i["id"]: i for i in pub(c)}[pid]
        assert "event_id" in {i["id"]: i for i in pub(c, member("Vol", "volunteer"))}[pid]


def test_home_fallback_is_marked_estimated_and_reported():
    with TestClient(app) as c:
        r = c.post("/api/board/posts", headers=hd(member()), json={"category": "fire", "body": "Flames by the road"})
        assert r.status_code == 200 and r.json()["used_home"] is True
        row = _row(r.json()["post_id"])
        assert row["lat"] == 37.77 and row["estimated"] == 1
        r = c.post("/api/board/posts", headers=hd(member("Ann")), json={"category": "fire", "body": "Flames here", "lat": PT[0], "lon": PT[1]})
        assert r.json()["used_home"] is False and _row(r.json()["post_id"])["estimated"] == 0


# ---- offline posting: client_key and queued_min ----

KEY = "abcd1234efgh5678"


def _send(c, tok, **extra):
    body = {"category": "fire", "body": "Smoke over the ridge", "lat": PT[0], "lon": PT[1], **extra}
    return c.post("/api/board/posts", json=body, headers=hd(tok))


def _counts():
    with connect() as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"] for t in ("posts", "events", "post_asks", "messages"))


def test_repeat_client_key_is_one_post_one_event():
    with TestClient(app) as c:
        m = member()
        start = _counts()
        a = _send(c, m, client_key=KEY)
        before = _counts()
        b = _send(c, m, client_key=KEY)
        assert a.status_code == b.status_code == 200
        assert b.json()["post_id"] == a.json()["post_id"]
        assert b.json()["duplicate"] is True
        assert a.json().get("duplicate", False) is False
        assert _counts() == before
        assert before[0] == start[0] + 1 and before[1] == start[1] + 1


def test_repeat_key_anonymous_makes_no_second_ask():
    with TestClient(app) as c:
        anon = device(c)
        a = _send(c, anon, client_key=KEY)
        before = _counts()
        b = _send(c, anon, client_key=KEY)
        assert b.json()["post_id"] == a.json()["post_id"] and b.json()["flagged"] == a.json()["flagged"]
        assert b.json()["asked"] == a.json()["asked"]
        assert _counts() == before


def test_same_key_other_device_is_a_new_post():
    with TestClient(app) as c:
        a = _send(c, device(c), client_key=KEY).json()
        b = _send(c, device(c), client_key=KEY).json()
        assert a["post_id"] != b["post_id"]
        assert not b.get("duplicate")


def test_unique_index_stops_a_race(monkeypatch):
    """Both sends pass the read check; the unique index makes the loser a duplicate with no extra rows."""
    with TestClient(app) as c:
        m = member()
        a = _send(c, m, client_key=KEY).json()
        before = _counts()
        monkeypatch.setattr(routes_posts, "_first_by_key", lambda *a, **k: None)
        b = _send(c, m, client_key=KEY)
        assert b.status_code == 200 and b.json()["post_id"] == a["post_id"] and b.json()["duplicate"] is True
        assert _counts() == before


def test_repeat_key_still_counts_toward_rate_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(routes_posts, "_limit", lambda *a, **k: calls.append(a[1]))
    with TestClient(app) as c:
        m = member()
        _send(c, m, client_key=KEY)
        _send(c, m, client_key=KEY)
    assert len(calls) == 2


@pytest.mark.parametrize("extra", [
    {"client_key": "short"}, {"client_key": "a" * 65}, {"client_key": "bad key chars!!!!"}, {"client_key": "é" * 20},
    {"queued_min": 121}, {"queued_min": -1},
])
def test_offline_fields_422(extra):
    with TestClient(app) as c:
        assert _send(c, device(c), **extra).status_code == 422


def test_queued_min_is_display_only():
    with TestClient(app) as c:
        m = member()
        pid = _send(c, m, queued_min=25).json()["post_id"]
        plain = _send(c, m, category="hazard", body="Line down on road").json()["post_id"]
        with connect() as conn:
            row = conn.execute("SELECT created_at FROM posts WHERE id = ?", (pid,)).fetchone()
            assert abs((parse_iso(row["created_at"]) - utcnow()).total_seconds()) < 60
        for tok in ("", member("Vol", "volunteer")):
            items = {i["id"]: i for i in pub(c, tok)}
            assert items[pid]["sent_late_min"] == 25
            assert items[pid]["age_min"] == 0
            assert items[plain]["sent_late_min"] is None
        assert ids(pub(c))[:2] == [plain, pid]


def test_queued_min_zero_is_null():
    with TestClient(app) as c:
        pid = _send(c, member(), queued_min=0).json()["post_id"]
        assert {i["id"]: i for i in pub(c)}[pid]["sent_late_min"] is None


# ---- compass direction: bearing and miles ----

HOME = (37.5, -96.2)


def _compass(c, tok, **extra):
    body = {"category": "smoke", "body": "Smoke far off", "lat": HOME[0], "lon": HOME[1], "bearing": 312.0, "miles": 4, **extra}
    return c.post("/api/board/posts", json=body, headers=hd(tok))


def test_compass_stores_computed_point_estimated():
    from app.where import Where, point_from
    want = point_from(*HOME, Where(312.0, 4.0))
    with TestClient(app) as c:
        pid = _compass(c, member()).json()["post_id"]
        with connect() as conn:
            row = conn.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()
        assert (row["lat"], row["lon"]) == pytest.approx(want)
        assert row["estimated"] == 1
        pub_item = {i["id"]: i for i in pub(c)}[pid]
        assert pub_item["estimated"] is True
        assert (pub_item["lat"], pub_item["lon"]) == (round(want[0], 2), round(want[1], 2))


@pytest.mark.parametrize("extra", [
    {"bearing": 10.0, "miles": None}, {"bearing": None, "miles": 2}, {"miles": 3}, {"bearing": 360}, {"bearing": -1},
])
def test_compass_422(extra):
    with TestClient(app) as c:
        assert _compass(c, device(c), **extra).status_code == 422


def test_compass_without_position_422():
    with TestClient(app) as c:
        r = c.post("/api/board/posts", json={"category": "smoke", "body": "x", "bearing": 10, "miles": 2}, headers=hd(device(c)))
        assert r.status_code == 422


def test_compass_miles_whole_number_accepted():
    with TestClient(app) as c:
        assert _compass(c, device(c), miles=2).status_code == 200
        assert _compass(c, device(c), miles=0.5).status_code == 200


def test_reporters_own_position_is_stored_nowhere():
    own = (37.123456, -96.654321)
    with TestClient(app) as c:
        m = member()
        pid = _compass(c, m, lat=own[0], lon=own[1]).json()["post_id"]
        for tok in ("", member("Vol", "volunteer")):
            blob = json.dumps({i["id"]: i for i in pub(c, tok)}[pid])
            assert "37.1234" not in blob and "96.6543" not in blob
        with connect() as conn:
            dump = "\n".join(conn.iterdump())
        assert "37.1234" not in dump and "96.6543" not in dump


def test_compass_with_location_off_stores_no_point():
    """Location off means no point at all: a direction "under 1 mile" would put the reporter within half a mile."""
    with TestClient(app) as c:
        pid = _compass(c, member(), attach_location=False).json()["post_id"]
        with connect() as conn:
            row = conn.execute("SELECT lat, lon, estimated FROM posts WHERE id = ?", (pid,)).fetchone()
        assert (row["lat"], row["lon"]) == (None, None)
