from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import scenario
from app.config import get_settings
from app.db import connect, iso, parse_iso, utcnow
from app.main import app
from tests.test_routes_posts import PT, hd, member, post

SLUG = "cottonwood-creek-packet"
TOKEN = "s3cret-token"

TOKEN_ROUTES = [
    ("POST", "/api/ingest/run"),
    ("POST", "/api/sample/replay"),
    ("POST", "/api/sample/load"),
    (("POST"), f"/api/scenario/{SLUG}/run"),
    ("POST", f"/api/scenario/{SLUG}/load"),
    ("GET", "/api/contacts"),
    ("POST", "/api/sms/inbound"),
]


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("method,path", TOKEN_ROUTES)
def test_token_routes_refuse_without_token(secured, method, path):
    with TestClient(app) as c:
        assert c.request(method, path, json={"from": "+15550001111", "body": "hi"}).status_code == 401
        assert c.request(method, path, headers={"X-Firewatch-Token": "wrong"}, json={}).status_code == 401
        r = c.request(method, path, headers={"X-Firewatch-Token": TOKEN}, json={"from": "+15550001111", "body": "hi"})
        assert r.status_code != 401


def _write_clock(slug, t_min, running, age_s=0):
    with connect() as conn:
        conn.execute("DELETE FROM replay_clock")
        conn.execute("INSERT INTO replay_clock(id, slug, t_min, running, updated_at) VALUES (1,?,?,?,?)",
                     (slug, t_min, int(running), iso(utcnow() - timedelta(seconds=age_s))))


def test_run_now_writes_clock_row():
    scenario.run_now(SLUG, 3)
    with connect() as conn:
        row = conn.execute("SELECT * FROM replay_clock").fetchone()
    assert row["slug"] == SLUG and row["t_min"] == 3 and row["running"] == 0


def test_running_now_reads_row_in_other_process(monkeypatch):
    monkeypatch.setattr(scenario, "_clock", {})
    _write_clock(SLUG, 7, True)
    t0 = parse_iso(scenario.load_scenario(SLUG)["t0"])
    assert scenario.running_now() == t0 + timedelta(minutes=7)


def test_running_now_ignores_stale_row(monkeypatch):
    monkeypatch.setattr(scenario, "_clock", {})
    _write_clock(SLUG, 7, True, age_s=200)
    assert scenario.running_now() is None


def test_running_now_ignores_stopped_row(monkeypatch):
    monkeypatch.setattr(scenario, "_clock", {})
    _write_clock(SLUG, 7, False)
    assert scenario.running_now() is None


def test_lifespan_stops_stored_clock(monkeypatch):
    _write_clock(SLUG, 7, True)
    with TestClient(app):
        pass
    with connect() as conn:
        assert conn.execute("SELECT running FROM replay_clock").fetchone()["running"] == 0


def test_admin_post_list_shows_station_view():
    m = member("Wes", "spotter", 1)
    with TestClient(app) as c:
        post(c, m, "fire", "Smoke over the ridge")
        r = c.get("/api/board/admin/posts", headers={"X-Firewatch-Token": TOKEN})
        assert r.status_code == 200
        item = r.json()[0]
        assert item["lat"] == PT[0] and item["lon"] == PT[1]
        assert "held" in item and "event_id" in item
