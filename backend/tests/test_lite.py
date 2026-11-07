import gzip
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import lite, sample
from app.db import connect

COTTONWOOD = "cottonwood-creek"


@pytest.fixture()
def client():
    sample.load_all_now()
    app = FastAPI()
    app.include_router(lite.router)
    return TestClient(app, follow_redirects=False)


def cw_id():
    with connect() as conn:
        return conn.execute("SELECT id FROM events WHERE sample_slug = ?", (COTTONWOOD,)).fetchone()["id"]


def status_of(eid):
    with connect() as conn:
        return conn.execute("SELECT status FROM events WHERE id = ?", (eid,)).fetchone()["status"]


def token_of(html, action):
    form = re.search(rf'<form[^>]*>(?:(?!</form>).)*value="{action}".*?</form>', html, re.S).group(0)
    return re.search(r'name="token" value="([^"]+)"', form).group(1)


def test_feed_shape_and_budget(client):
    r = client.get("/api/lite/alerts")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    j = r.json()
    assert set(j) == {"t", "alerts", "quiet"}
    assert set(j["quiet"]) == {"total", "logged_burn", "static_source", "likely_prescribed", "low_signal"}
    assert j["alerts"] and all(set(a) == {"id", "score", "rec", "label", "lat", "lon", "why", "status", "seen"} for a in j["alerts"])
    assert all(a["rec"] in ("escalate", "investigate") for a in j["alerts"])
    scores = [a["score"] for a in j["alerts"] if a["rec"] == "escalate"]
    assert scores == sorted(scores, reverse=True)
    assert all(a["lat"] == round(a["lat"], 4) for a in j["alerts"])
    assert len(gzip.compress(r.content)) < 2048


def test_feed_etag_304(client):
    r = client.get("/api/lite/alerts")
    etag = r.headers["etag"]
    assert etag.startswith('"')
    r2 = client.get("/api/lite/alerts", headers={"If-None-Match": etag})
    assert r2.status_code == 304 and r2.content == b"" and r2.headers["etag"] == etag
    assert client.get("/api/lite/alerts", headers={"If-None-Match": '"nope"'}).status_code == 200


def test_page_renders_cottonwood(client):
    eid = cw_id()
    r = client.get(f"/lite?id={eid}")
    assert r.status_code == 200
    t = r.text
    assert "Grass fire. Page the district." in t
    assert "A power-line fault on the Ortiz lease line" in t
    assert "Rd K" in t and "CR 12" in t
    assert "In the path" in t and "Miller" in t
    assert "<svg" in t and "<script" not in t
    assert 'http-equiv="refresh" content="60"' in t
    assert "Refreshes every minute." in t and "Quiet:" in t
    assert len(r.content) < 14 * 1024


def test_page_default_is_top_alert(client):
    r = client.get("/lite")
    assert r.status_code == 200 and "Other fires" in r.text and "/lite?id=" in r.text


def test_act_and_undo(client):
    eid = cw_id()
    assert status_of(eid) == "new"
    html = client.get(f"/lite?id={eid}").text
    r = client.post("/lite/act", data={"id": eid, "action": "ack", "token": token_of(html, "ack")})
    assert r.status_code == 303 and f"id={eid}" in r.headers["location"] and "done=ack" in r.headers["location"]
    assert status_of(eid) == "acknowledged"
    done = client.get(r.headers["location"])
    assert "Undo" in done.text and 'http-equiv="refresh"' not in done.text
    r2 = client.post("/lite/act", data={"id": eid, "action": "undo", "prev": "new", "token": token_of(done.text, "undo")})
    assert r2.status_code == 303 and status_of(eid) == "new"


def test_dismiss_then_undo_restores_acknowledged(client):
    eid = cw_id()
    tok = token_of(client.get(f"/lite?id={eid}").text, "dismiss")
    client.post("/lite/act", data={"id": eid, "action": "ack", "token": tok})
    r = client.post("/lite/act", data={"id": eid, "action": "dismiss", "token": tok})
    assert status_of(eid) == "dismissed" and "prev=acknowledged" in r.headers["location"]
    client.post("/lite/act", data={"id": eid, "action": "undo", "prev": "acknowledged", "token": tok})
    assert status_of(eid) == "acknowledged"


def test_bad_token_is_400(client):
    eid = cw_id()
    r = client.post("/lite/act", data={"id": eid, "action": "dismiss", "token": "bad"})
    assert r.status_code == 400 and "out of date" in r.text
    assert status_of(eid) == "new"
    assert client.post("/lite/act", data={"action": "dismiss"}).status_code == 400


def test_report_text_is_escaped(client):
    eid = cw_id()
    with connect() as conn:
        conn.execute("INSERT INTO signals(kind, lat, lon, time, payload_json, event_id, is_sample, ingested_at) "
                     "VALUES ('report', 37.3, -99.8, '2026-03-17T19:10:00Z', ?, ?, 1, '2026-03-17T19:10:00Z')",
                     ('{"text": "<script>alert(1)</script>"}', eid))
    t = client.get(f"/lite?id={eid}").text
    assert "<script>alert" not in t and "&lt;script&gt;alert(1)&lt;/script&gt;" in t
