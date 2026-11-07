"""Live alert sending needs the operator token; burn windows are bounded."""
from fastapi.testclient import TestClient

from app.main import app


def _client():
    return TestClient(app)


def _event_id(c):
    return c.get("/api/alerts").json()["alerts"][0]["id"]


def test_dry_run_notify_needs_no_token(monkeypatch):
    monkeypatch.delenv("FIREWATCH_NOTIFY_LIVE", raising=False)
    with _client() as c:
        assert c.post(f"/api/alerts/{_event_id(c)}/notify", json={}).status_code == 200


def test_live_notify_refused_without_configured_token(monkeypatch):
    monkeypatch.setenv("FIREWATCH_NOTIFY_LIVE", "1")
    monkeypatch.delenv("FIREWATCH_OPERATOR_TOKEN", raising=False)
    with _client() as c:
        assert c.post(f"/api/alerts/{_event_id(c)}/notify", json={}).status_code == 403


def test_live_notify_wrong_token_then_cooldown(monkeypatch):
    monkeypatch.setenv("FIREWATCH_NOTIFY_LIVE", "1")
    monkeypatch.setenv("FIREWATCH_OPERATOR_TOKEN", "right-token")
    monkeypatch.setenv("FIREWATCH_NOTIFY_URLS", "")
    with _client() as c:
        eid = _event_id(c)
        url = f"/api/alerts/{eid}/notify"
        assert c.post(url, json={}, headers={"X-Firewatch-Operator": "wrong"}).status_code == 401
        assert c.post(url, json={}, headers={"X-Firewatch-Operator": "right-token"}).status_code == 200
        assert c.post(url, json={}, headers={"X-Firewatch-Operator": "right-token"}).status_code == 429


def test_burn_window_over_24h_rejected():
    with _client() as c:
        r = c.post("/api/burns", json={"lat": 37.3, "lon": -99.8, "caller": "x",
                                       "start": "2026-03-17T16:00:00Z", "end": "2026-03-19T16:00:00Z"})
        assert r.status_code == 422
