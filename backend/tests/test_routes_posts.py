import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, routes_posts
from app.db import connect, iso, utcnow
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


def test_public_hides_anonymous_until_counted_confirm():
    with TestClient(app) as c:
        anon, m = device(c), member()
        pid = post(c, anon)
        assert pub(c) == []
        r = see(c, m, pid)
        assert r.json()["counted"] is True
        items = pub(c)
        assert ids(items) == [pid] and items[0]["confirms"] == 1 and items[0]["author"] == "Community"


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
        assert (pv[fr]["lat"], pv[fr]["lon"]) == PT
        st = {i["id"]: i for i in pub(c, member("Vol", "volunteer"))}
        assert (st[hz]["lat"], st[hz]["lon"]) == PT


def test_station_view_shows_hidden_flagged_first_with_name():
    with TestClient(app) as c:
        named = member("Dana", registered=0)
        first = post(c, named, "hazard")
        flagged = post(c, device(c), "fire", "Flames over by the road")
        vol = member("Vol", "volunteer")
        items = pub(c, vol)
        assert ids(items)[0] == flagged and first in ids(items)
        assert {i["id"]: i["author"] for i in items}[first] == "Dana"
        assert pub(c) == []


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


def test_no_text_dismisses_the_post():
    from app import notify
    with TestClient(app) as c:
        pid, eid = _fire_with_event(c)
        assert pid in ids(pub(c))
        with connect() as conn:
            notify.decide(conn, eid, "no", "Duty", utcnow())
        assert _status(pid) == "dismissed"
        assert pid not in ids(pub(c))


def test_dashboard_dismiss_dismisses_the_post():
    with TestClient(app) as c:
        pid, eid = _fire_with_event(c)
        r = c.post(f"/api/alerts/{eid}/actions", json={"action": "dismiss", "operator": "Ops"})
        assert r.status_code == 200, r.text
        assert _status(pid) == "dismissed"
        assert pid not in ids(pub(c))
