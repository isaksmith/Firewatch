"""Caller names on logged burns are personal data: reading them needs the API token when one is set."""
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_burn_list_needs_token_when_set(monkeypatch):
    monkeypatch.setattr(get_settings(), "api_token", "t0ken")
    with TestClient(app) as c:
        assert c.get("/api/burns").status_code == 401
        assert c.get("/api/burns", headers={"X-Firewatch-Token": "wrong"}).status_code == 401
        assert c.get("/api/burns", headers={"X-Firewatch-Token": "t0ken"}).status_code == 200


def test_burn_list_open_when_no_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "api_token", "")
    with TestClient(app) as c:
        assert c.get("/api/burns").status_code == 200
