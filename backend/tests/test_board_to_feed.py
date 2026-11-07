"""The merge contract: one burn store behind both burn views, and a confirmed board report reaching the FW1 feed."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import posts, routes_posts
from app.config import get_settings
from app.db import connect, iso
from app.main import app
from tests.test_posts import anon_post, duty, mk

IGNITION = (37.3821, -99.4681)  # the packet stand-in at Coldwater
NOW = datetime(2026, 3, 17, 18, 50, tzinfo=timezone.utc)  # Tue Mar 17 2026, 1:50 pm CDT
TOKEN = "s3cret-token"


def test_confirmed_board_report_opens_an_event_and_feeds_a_code():
    with connect() as conn:
        duty(conn)
        a, b = mk(conn, lat=IGNITION[0], lon=IGNITION[1] + 0.02), mk(conn, lat=IGNITION[0] + 0.01, lon=IGNITION[1])
        p = anon_post(conn, cat="smoke", at=IGNITION, now=NOW)
        assert p["event_id"] is None and conn.execute("SELECT COUNT(*) n FROM fw1_feed").fetchone()["n"] == 0
        assert posts.confirm(conn, p["post_id"], a, "see", NOW, True, "web", *IGNITION)["counted"]
        r = posts.confirm(conn, p["post_id"], b, "see", NOW, True, "web", *IGNITION)
        assert r["event_id"] is not None and r["level"] == "escalate"
        rows = conn.execute("SELECT level, code FROM fw1_feed WHERE event_id = ? ORDER BY seq", (r["event_id"],)).fetchall()
    assert [x["level"] for x in rows] == ["investigate", "escalate"]
    feed = TestClient(app).get("/api/m/feed").text
    assert rows[-1]["code"] in feed and rows[-1]["code"].startswith("FW1.cwc.")


def test_board_alone_is_not_lifted_past_investigate_by_the_stakes_model():
    """One member's confirm on an anonymous post is one source: Investigate, even on the packet's red-flag day."""
    with connect() as conn:
        duty(conn)
        p = anon_post(conn, cat="smoke", at=IGNITION, now=NOW)
        r = posts.confirm(conn, p["post_id"], mk(conn), "see", NOW, True, "web", *IGNITION)
    assert r["level"] == "investigate"


def _admin(c):
    r = c.get("/api/board/admin/burns", headers={"X-Firewatch-Token": TOKEN})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_logged_burn_shows_in_both_views_and_follows_the_window(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    get_settings.cache_clear()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    monkeypatch.setattr(routes_posts, "_clock", lambda: (now, True))
    c = TestClient(app)
    body = {"lat": IGNITION[0], "lon": IGNITION[1], "start": iso(now - timedelta(hours=1)), "end": iso(now + timedelta(hours=2)),
            "caller": "Pat Rancher", "called_in": iso(now - timedelta(minutes=5))}
    assert c.post("/api/burns", json=body).status_code == 401  # caller names stay behind the token
    assert c.post("/api/burns", json=body, headers={"X-Firewatch-Token": TOKEN}).status_code == 201
    assert c.get("/api/burns").status_code == 401
    logged = c.get("/api/burns", headers={"X-Firewatch-Token": TOKEN}).json()["burns"]
    assert [b["caller"] for b in logged] == ["Pat Rancher"]

    pub = c.get("/api/board/burns").json()
    assert pub == [{"lat": round(IGNITION[0], 2), "lon": round(IGNITION[1], 2), "radius_km": 1.5,
                    "registered_at": pub[0]["registered_at"], "reports_nearby": False}]
    adm = _admin(c)
    assert adm[0]["name"] == "Pat Rancher" and adm[0]["lat"] == IGNITION[0] and adm[0]["start"] and adm[0]["end"]

    # A burn whose window misses today (Central) is not one of today's burns, same as for the alert logic.
    later = dict(body, start=iso(now + timedelta(days=3)), end=iso(now + timedelta(days=3, hours=4)), caller="Next Week")
    assert c.post("/api/burns", json=later, headers={"X-Firewatch-Token": TOKEN}).status_code == 201
    assert [b["name"] for b in _admin(c)] == ["Pat Rancher"]
    # The window bounds still hold: at most 24 h, at most 14 days ahead.
    too_long = dict(body, end=iso(now + timedelta(hours=30)))
    too_far = dict(body, start=iso(now + timedelta(days=15)), end=iso(now + timedelta(days=15, hours=1)))
    for b in (too_long, too_far):
        assert c.post("/api/burns", json=b, headers={"X-Firewatch-Token": TOKEN}).status_code == 422
