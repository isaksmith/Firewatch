import json
from pathlib import Path

import httpx
import pytest

from app.ingest import nws

FIX = Path(__file__).parent / "fixtures"


def _patch(monkeypatch, fixture=None, status=200, exc=None):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(params=params, headers=headers)
        req = httpx.Request("GET", url)
        if exc:
            raise exc(f"failed {url}", request=req)
        body = (FIX / fixture).read_bytes() if fixture else b"<html>"
        return httpx.Response(status, content=body, request=req)

    monkeypatch.setattr(nws.httpx, "get", fake_get)
    return seen


def test_red_flag_present(monkeypatch):
    seen = _patch(monkeypatch, "nws_red_flag.json")
    r = nws.red_flag_at(37.27, -99.31)
    assert r["red_flag"] is True
    assert r["headline"].startswith("Red Flag Warning")
    assert r["expires"] == "2026-11-07T02:00:00+00:00"
    assert r["fetched_at"].endswith("Z")
    assert seen["params"] == {"point": "37.2700,-99.3100"}
    assert seen["headers"]["User-Agent"] == "Firewatch hackathon demo (github.com/isaksmith/Firewatch)"
    assert "@" not in seen["headers"]["User-Agent"]


def test_no_alerts(monkeypatch):
    _patch(monkeypatch, "nws_none.json")
    r = nws.red_flag_at(37.27, -99.31)
    assert r["red_flag"] is False and r["headline"] is None and r["expires"] is None


@pytest.mark.parametrize("kwargs", [
    {"status": 500, "fixture": "nws_none.json"},
    {"exc": httpx.ConnectError},
    {"exc": httpx.ReadTimeout},
    {"status": 200, "fixture": None},  # not JSON
])
def test_failure_raises_and_never_returns_false(monkeypatch, kwargs):
    _patch(monkeypatch, **kwargs)
    with pytest.raises(RuntimeError) as e:
        nws.red_flag_at(37.27, -99.31)
    msg = str(e.value)
    assert "weather.gov" not in msg and "http" not in msg.lower().replace("http 500", "")


def test_unexpected_shape_raises(monkeypatch):
    def fake_get(url, **kw):
        return httpx.Response(200, content=json.dumps({"hello": 1}).encode(), request=httpx.Request("GET", url))

    monkeypatch.setattr(nws.httpx, "get", fake_get)
    with pytest.raises(RuntimeError):
        nws.red_flag_at(1, 2)


@pytest.mark.parametrize("body", [
    {"features": None}, {"features": "abc"}, {"features": [1]}, {"features": [{}]},
    {"features": [{"properties": None}]}, {}, [1], "abc", None,
])
def test_malformed_never_reads_as_no_red_flag(monkeypatch, body):
    def fake_get(url, **kw):
        return httpx.Response(200, content=json.dumps(body).encode(), request=httpx.Request("GET", url))

    monkeypatch.setattr(nws.httpx, "get", fake_get)
    with pytest.raises(RuntimeError, match="malformed"):
        nws.red_flag_at(1, 2)


def test_empty_list_is_valid_no_alerts(monkeypatch):
    def fake_get(url, **kw):
        return httpx.Response(200, content=b'{"features": []}', request=httpx.Request("GET", url))

    monkeypatch.setattr(nws.httpx, "get", fake_get)
    assert nws.red_flag_at(1, 2)["red_flag"] is False
