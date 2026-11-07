from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import public_app, routes_posts
from app.config import get_settings
from app.db import connect, iso
from app.main import app
from app.ratelimit import Limiter
from tests.test_routes_posts import member

import itertools

_n = itertools.count(1)
CENTRAL = ZoneInfo("America/Chicago")
TOKEN = "s3cret-token"
# 22:00 Central on 2026-11-07 is already 2026-11-08 04:00 UTC.
NOW = datetime(2026, 11, 7, 22, 0, tzinfo=CENTRAL).astimezone(timezone.utc)
BURN = (37.7712, -96.6634)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(routes_posts, "_clock", lambda: (NOW, True))


def central(h, m, day=7):
    return datetime(2026, 11, day, h, m, tzinfo=CENTRAL).astimezone(timezone.utc)


def burn(at, lat=BURN[0], lon=BURN[1], sample=1, name="Burner", radius=1.5):
    with connect() as conn:
        cid = conn.execute("INSERT INTO contacts(name, phone, role, registered) VALUES (?,?,?,1)",
                           (name, f"+1555{abs(hash((name, at))) % 10**7:07d}", "spotter")).lastrowid
        conn.execute("INSERT INTO burn_notices(contact_id, lat, lon, radius_km, burn_date, is_sample, created_at) VALUES (?,?,?,?,?,?,?)",
                     (cid, lat, lon, radius, at.astimezone(CENTRAL).date().isoformat(), sample, iso(at)))


def near_post(category="smoke", status="open", dlat=0.018, sample=1):
    """dlat 0.018 degrees is about 2 km north of BURN."""
    with connect() as conn:
        cid = conn.execute("INSERT INTO contacts(name, phone, role, registered) VALUES ('P', ?, 'spotter', 1)",
                           (f"+1556{next(_n):07d}",)).lastrowid
        conn.execute("INSERT INTO posts(contact_id, category, body, status, lat, lon, channel, is_sample, created_at, updated_at) "
                     "VALUES (?,?,'Smoke by the road',?,?,?,'web',?,?,?)",
                     (cid, category, status, BURN[0] + dlat, BURN[1], sample, iso(NOW), iso(NOW)))


def get(c, path="/api/board/burns", **kw):
    r = c.get(path, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_public_row_shape_has_no_identity_and_rounds():
    burn(central(9, 40))
    c = TestClient(app)
    rows = get(c)
    assert rows == [{"lat": 37.77, "lon": -96.66, "radius_km": 1.5, "registered_at": "9:40 AM", "reports_nearby": False}]
    for r in rows:
        assert not {"name", "contact_id", "phone", "id"} & set(r)
        for k in ("lat", "lon"):
            assert round(r[k], 2) == r[k]


def test_yesterday_missing_and_early_today_present_across_utc_midnight():
    burn(central(23, 55, day=6), name="Yest")
    burn(central(0, 5), name="Early")
    c = TestClient(app)
    rows = get(c)
    assert [r["registered_at"] for r in rows] == ["12:05 AM"]


def test_burn_after_the_replay_clock_is_missing():
    burn(NOW + timedelta(minutes=1), name="Future")
    burn(NOW - timedelta(minutes=1), name="Past")
    c = TestClient(app)
    assert [r["registered_at"] for r in get(c)] == ["9:59 PM"]


def test_sample_and_live_never_mix(monkeypatch):
    burn(central(9, 0), sample=1, name="S")
    burn(central(10, 0), sample=0, name="L")
    c = TestClient(app)
    assert [r["registered_at"] for r in get(c)] == ["9:00 AM"]
    monkeypatch.setattr(routes_posts, "_clock", lambda: (NOW, False))
    assert [r["registered_at"] for r in get(c)] == ["10:00 AM"]


def test_newest_first_and_capped_at_100():
    for i in range(101):
        burn(central(0, 0) + timedelta(minutes=i), name=f"B{i}")
    c = TestClient(app)
    rows = get(c)
    assert len(rows) == 100 and rows[0]["registered_at"] == "1:40 AM"


def test_reports_nearby_rules():
    burn(central(9, 0))
    c = TestClient(app)
    assert get(c)[0]["reports_nearby"] is False
    near_post("hazard")
    assert get(c)[0]["reports_nearby"] is False
    near_post("smoke", status="dismissed")
    assert get(c)[0]["reports_nearby"] is False
    near_post("smoke", dlat=0.05)  # about 5.5 km, outside radius + 1
    assert get(c)[0]["reports_nearby"] is False
    near_post("smoke")
    assert get(c)[0]["reports_nearby"] is True


def test_reports_nearby_ignores_a_post_whose_event_is_dismissed():
    burn(central(9, 0))
    near_post("fire")
    with connect() as conn:
        eid = conn.execute("INSERT INTO events(lat, lon, status, first_seen, last_seen, updated_at, is_sample) VALUES (?,?,'dismissed',?,?,?,1)",
                           (*BURN, iso(NOW), iso(NOW), iso(NOW))).lastrowid
        conn.execute("UPDATE posts SET event_id = ?", (eid,))
    c = TestClient(app)
    assert get(c)[0]["reports_nearby"] is False


def test_admin_burns_need_the_token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    get_settings.cache_clear()
    burn(central(9, 40), name="Pat")
    c = TestClient(app)
    assert c.get("/api/board/admin/burns").status_code == 401
    assert c.get("/api/board/admin/burns", headers={"X-Firewatch-Token": "wrong"}).status_code == 401
    rows = get(c, "/api/board/admin/burns", headers={"X-Firewatch-Token": TOKEN})
    assert rows == [{"lat": BURN[0], "lon": BURN[1], "radius_km": 1.5, "registered_at": "9:40 AM",
                     "name": "Pat", "late": False, "reports_nearby": False}]


def _event(at, lat=BURN[0], lon=BURN[1]):
    with connect() as conn:
        conn.execute("INSERT INTO events(lat, lon, status, first_seen, last_seen, updated_at, is_sample) VALUES (?,?,'open',?,?,?,1)",
                     (lat, lon, iso(at), iso(at), iso(at)))


def _admin(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    get_settings.cache_clear()
    c = TestClient(app)
    return get(c, "/api/board/admin/burns", headers={"X-Firewatch-Token": TOKEN})


def test_admin_late_when_the_event_started_first(monkeypatch):
    burn(central(9, 0), name="Late")
    _event(central(8, 0))
    assert _admin(monkeypatch)[0]["late"] is True


def test_admin_not_late_when_sent_before_the_event(monkeypatch):
    burn(central(9, 0), name="Early")
    _event(central(10, 0))
    assert _admin(monkeypatch)[0]["late"] is False


def test_admin_not_late_with_no_event(monkeypatch):
    burn(central(9, 0), name="Quiet")
    assert _admin(monkeypatch)[0]["late"] is False


@pytest.fixture
def pub():
    public_app.app.state.limiter = Limiter()
    return TestClient(public_app.app)


def test_public_app_serves_burns_and_rate_limits(pub):
    burn(central(9, 0))
    for _ in range(120):
        assert pub.get("/api/board/burns").status_code == 200
    r = pub.get("/api/board/burns")
    assert r.status_code == 429 and "retry-after" in r.headers


def test_public_app_has_no_admin_burns(pub):
    assert pub.get("/api/board/admin/burns").status_code == 404
