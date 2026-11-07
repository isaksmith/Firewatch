import logging
from datetime import datetime, timedelta, timezone

import pytest

from fastapi.testclient import TestClient

from app.main import app

FAULT = {"lat": 37.30, "lon": -99.80, "time": "2026-03-17T18:50:00Z", "circuit": "Ortiz lease line", "kind": "fault"}
PHONE = "+15550100009"
SCENARIO_NOW = datetime(2026, 3, 17, 19, 30, tzinfo=timezone.utc)


@pytest.fixture
def scenario_clock(monkeypatch):
    """The API only takes recent times; pretend it is 2:30 pm on the scenario day."""
    monkeypatch.setattr("app.main.utcnow", lambda: SCENARIO_NOW)


def test_line_fault_in_red_flag_weather_opens_possible_fire(scenario_clock):
    with TestClient(app) as client:
        r = client.post("/api/signals/line-fault", json={**FAULT, "lat": 37.12, "lon": -99.2})
        assert r.status_code == 201
        body = r.json()
        assert body["created_event"] and body["recommendation"] == "investigate"
        detail = client.get(f"/api/alerts/{body['event_id']}").json()
        assert detail["reasons"][0]["label"].startswith("A power-line fault on the Ortiz lease line at 1:50")
        assert detail["detections"] == []
        assert detail["signals"][0]["circuit"] == "Ortiz lease line"


def test_line_fault_in_calm_weather_is_only_logged(monkeypatch, scenario_clock):
    from app import main
    monkeypatch.setattr(main, "_signal_weather", lambda: {"wind_kmh": 5, "rh_pct": 60, "temp_c": 10})
    with TestClient(app) as client:
        body = client.post("/api/signals/line-fault", json=FAULT).json()
        assert body["event_id"] is None and body["signal_id"]


def test_report_far_from_any_event_opens_investigate_event(scenario_clock):
    with TestClient(app) as client:
        body = client.post("/api/signals/report", json={"lat": 37.0, "lon": -98.5, "text": "Smoke over the ridge", "phone": PHONE, "time": "2026-03-17T19:20:00Z"}).json()
        assert body["created_event"] and body["recommendation"] == "investigate"


def test_report_joins_nearest_open_event_within_5km(scenario_clock):
    with TestClient(app) as client:
        alerts = client.get("/api/alerts").json()["alerts"]
        fire = next(a for a in alerts if a["sample_slug"] == "cottonwood-creek")
        body = client.post("/api/signals/report", json={
            "lat": 37.2960, "lon": -99.7700, "text": "Smoke to the west of CR 10", "phone": PHONE,
            "time": "2026-03-17T19:30:00Z"}).json()
        assert body["joined"] and body["event_id"] == fire["id"]
        detail = client.get(f"/api/alerts/{fire['id']}").json()
        assert PHONE not in str(detail) and any(s.get("phone_last4") == "0009" for s in detail["signals"])


def test_bad_phone_and_text_are_rejected_without_echoing_the_number(caplog):
    secret = "555-not-a-phone-0199"
    with TestClient(app) as client, caplog.at_level(logging.DEBUG):
        r = client.post("/api/signals/report", json={"lat": 37, "lon": -99, "text": "Smoke", "phone": secret})
        assert r.status_code == 422
        assert secret not in r.text and "0199" not in r.text
        assert client.post("/api/signals/report", json={"lat": 37, "lon": -99, "text": "x" * 501}).status_code == 422
        assert client.post("/api/signals/report", json={"lat": 137, "lon": -99, "text": "Smoke"}).status_code == 422
        assert client.post("/api/signals/line-fault", json={**FAULT, "lon": -300}).status_code == 422
    assert secret not in caplog.text


def test_signal_times_must_be_recent(scenario_clock):
    with TestClient(app) as client:
        for t in ("2099-01-01T00:00:00Z", "1970-01-01T00:00:00Z", "2026-03-15T19:00:00Z", "2026-03-17T19:45:00Z"):
            assert client.post("/api/signals/line-fault", json={**FAULT, "time": t}).status_code == 422, t
            assert client.post("/api/signals/report", json={"lat": 37, "lon": -99, "text": "Smoke", "time": t}).status_code == 422, t
        ok = client.post("/api/signals/line-fault", json={**FAULT, "lat": 37.12, "lon": -99.2, "time": "2026-03-17T19:35:00Z"})
        assert ok.status_code == 201


def test_blank_report_text_is_rejected_and_text_is_trimmed(scenario_clock):
    with TestClient(app) as client:
        assert client.post("/api/signals/report", json={"lat": 37, "lon": -99, "text": "   \n "}).status_code == 422
        r = client.post("/api/signals/report", json={"lat": 37.0, "lon": -98.5, "text": "  Smoke  ", "time": "2026-03-17T19:20:00Z"}).json()
        detail = client.get(f"/api/alerts/{r['event_id']}").json()
        assert detail["signals"][0]["text"] == "Smoke"
