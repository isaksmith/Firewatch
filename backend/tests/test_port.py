"""Add-ons ported from the shane branch onto the team's model: burn log, signal inputs, /lite, CAP, live-send guard,
mesh fixes."""

import threading
import time
import xml.etree.ElementTree as ET
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import confirm, livesend, mesh, notify
from app.config import get_settings
from app.confirm import evaluate_event
from app.db import connect, iso, loads, parse_iso, utcnow
from app.district import sync_roster
from app.main import app
from app.signals import add_signal

T0 = parse_iso("2026-03-17T18:50:00Z")  # the packet's red-flag Tuesday
FIRE = (37.3821, -99.4681)
BURN = (37.3621, -99.3537)
WEATHER = {"wind_kmh": 26, "gust_kmh": 45, "wind_dir_deg": 200, "rh_pct": 18, "temp_c": 24, "precip_72h_mm": 0, "thunder_24h": 0}
CALM = {**WEATHER, "wind_kmh": 8, "rh_pct": 45}
WES = "+13165550131"


@pytest.fixture
def client():
    with TestClient(app) as c:
        with connect() as conn:  # startup loads the sample fixtures; these tests want only their own events
            for t in ("scores", "actions", "detections", "signals", "messages", "burn_notices", "events"):
                conn.execute(f"DELETE FROM {t}")
        yield c


def _burn(**kw):
    return {"lat": BURN[0], "lon": BURN[1], "start": "2026-03-17T17:00:00Z", "end": "2026-03-17T23:00:00Z",
            "called_in": "2026-03-17T16:00:00Z", "caller": "Gary Hale", "label": "pasture", **kw}


def _fault(conn, where, weather=CALM):
    eid = add_signal(conn, "line_fault", *where, iso(T0), "coop:feeder-4", "lockout", is_sample=True)
    evaluate_event(conn, eid, weather, T0)
    return conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()


# ---------- 1. burn-call log ----------

def test_burn_post_and_get(client):
    r = client.post("/api/burns", json=_burn())
    assert r.status_code == 201
    b = r.json()
    assert set(b) == {"id", "lat", "lon", "start", "end", "called_in", "caller", "label", "is_sample"}
    assert b["start"] == "2026-03-17T17:00:00Z" and b["called_in"] == "2026-03-17T16:00:00Z"
    assert client.get("/api/burns").json()["burns"] == [b]


@pytest.mark.parametrize("patch", [
    {"end": "2026-03-18T17:00:01Z"},                                  # over 24 h
    {"end": "2026-03-17T17:00:00Z"},                                  # end == start
    {"end": "2026-03-17T16:00:00Z"},                                  # end before start
    {"caller": "   "},                                                # blank caller
    {"start": "2099-01-01T00:00:00Z", "end": "2099-01-01T06:00:00Z"},  # far ahead
])
def test_burn_bounds_rejected(client, patch):
    assert client.post("/api/burns", json=_burn(**patch)).status_code == 422
    assert client.get("/api/burns").json()["burns"] == []


def test_burn_up_to_24h_and_14_days_ahead_ok(client):
    soon = utcnow() + timedelta(days=13)
    ok = _burn(start=iso(soon), end=iso(soon + timedelta(hours=24)))
    assert client.post("/api/burns", json=ok).status_code == 201


def test_burn_post_needs_the_api_token_when_one_is_set(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "t0k")
    get_settings.cache_clear()
    assert client.post("/api/burns", json=_burn()).status_code == 401
    assert client.post("/api/burns", json=_burn(), headers={"X-Firewatch-Token": "t0k"}).status_code == 201


def test_logged_burn_suppresses_a_nearby_detection_like_a_permit(client):
    client.post("/api/burns", json=_burn())
    with connect() as conn:
        ev = _fault(conn, BURN)
        assert ev["recommendation"] == "monitor" and ev["suppression"] == "registered_burn"
        shown = loads(ev["evidence_json"])
        assert any(e["kind"] == "burn_notice" for e in shown)


def test_burn_only_counts_when_its_window_overlaps_the_event(client):
    # Ended 3 hours before the fire started: no suppression.
    client.post("/api/burns", json=_burn(start="2026-03-17T10:00:00Z", end="2026-03-17T15:00:00Z"))
    with connect() as conn:
        assert _fault(conn, BURN)["suppression"] != "registered_burn"


def test_burn_called_in_after_the_event_started_is_only_a_claim(client):
    client.post("/api/burns", json=_burn(called_in="2026-03-17T19:30:00Z"))
    with connect() as conn:
        ev = _fault(conn, BURN, WEATHER)
        assert ev["recommendation"] == "investigate"  # existing "late notice" rule applies to a logged burn too


def test_burn_escape_rule_is_unchanged_for_logged_burns(client):
    client.post("/api/burns", json=_burn())
    with connect() as conn:
        ev = _fault(conn, BURN)
        assert ev["recommendation"] == "monitor"
        add_signal(conn, "report", *BURN, iso(T0 + timedelta(minutes=5)), "sms:+13165559991", "fire spreading", is_sample=True)
        evaluate_event(conn, ev["id"], CALM, T0 + timedelta(minutes=5))
        ev = conn.execute("SELECT * FROM events WHERE id = ?", (ev["id"],)).fetchone()
        assert ev["recommendation"] != "monitor"
        assert any("escaped" in e.get("note", "") for e in loads(ev["evidence_json"]))


def test_burn_table_rebuilt_on_an_old_database():
    from app.db import init_db
    with connect() as conn:
        conn.executescript(
            "DROP TABLE burn_notices; CREATE TABLE burn_notices (id INTEGER PRIMARY KEY, contact_id INTEGER NOT NULL, "
            "lat REAL NOT NULL, lon REAL NOT NULL, radius_km REAL NOT NULL DEFAULT 1.5, burn_date TEXT NOT NULL, "
            "is_sample INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);")
        sync_roster(conn)
        conn.execute("INSERT INTO burn_notices(contact_id, lat, lon, burn_date, created_at) VALUES (1, 1, 2, '2026-03-17', 'x')")
    init_db()
    with connect() as conn:
        cols = {r["name"]: r["notnull"] for r in conn.execute("PRAGMA table_info(burn_notices)")}
        assert cols["contact_id"] == 0 and "start_at" in cols
        assert conn.execute("SELECT COUNT(*) FROM burn_notices").fetchone()[0] == 1


# ---------- 2. line_fault and public_report through POST /api/signals ----------

@pytest.fixture
def signals(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "t0k")
    get_settings.cache_clear()
    monkeypatch.setattr(confirm, "fetch_weather", lambda conn, eid: WEATHER)

    def post(body, token="t0k"):
        return client.post("/api/signals", json=body, headers={"X-Firewatch-Token": token})
    return post


def _now_iso(**delta):
    return iso(utcnow() + timedelta(**delta))


def test_signals_accept_line_fault_and_public_report_under_the_token(signals):
    base = {"lat": FIRE[0], "lon": FIRE[1], "source": "coop:feeder-4"}
    assert signals({**base, "kind": "line_fault", "value": "lockout"}, token="nope").status_code == 401
    r = signals({**base, "kind": "line_fault", "value": "lockout"})
    assert r.status_code == 200 and r.json()["event_id"]
    r = signals({**base, "kind": "report", "source": "public", "value": "  smoke by the creek  "})
    assert r.status_code == 200
    with connect() as conn:
        rows = conn.execute("SELECT kind, value FROM signals ORDER BY id").fetchall()
    assert [(x["kind"], x["value"]) for x in rows] == [("line_fault", "lockout"), ("report", "smoke by the creek")]


@pytest.mark.parametrize("body", [
    {"kind": "report", "value": "   "},      # nothing after stripping
    {"kind": "report"},                       # no text at all
    {"kind": "line_fault", "source": "   "},  # blank source
    {"kind": "public_report", "value": "x"},  # not a kind: the public report is `report`
])
def test_signals_reject_empty_text(signals, body):
    full = {"lat": FIRE[0], "lon": FIRE[1], "source": "public", **body}
    assert signals(full).status_code == 422


def test_signal_time_bounds(signals):
    base = {"kind": "line_fault", "lat": FIRE[0], "lon": FIRE[1], "source": "coop:f4", "value": "lockout"}
    assert signals({**base, "observed_at": _now_iso(hours=-47)}).status_code == 200
    assert signals({**base, "observed_at": _now_iso(hours=-49)}).status_code == 422
    assert signals({**base, "observed_at": _now_iso(minutes=9)}).status_code == 200
    assert signals({**base, "observed_at": _now_iso(minutes=12)}).status_code == 422
    assert signals({**base, "observed_at": "yesterday"}).status_code == 422


# ---------- 3. /lite and /api/lite/alerts ----------

def _seed_two_events():
    """An escalate (line lockout plus a neighbor who sees smoke) and a newer, lone investigate."""
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(T0), "coop:feeder-4", "lockout", is_sample=True)
        evaluate_event(conn, eid, WEATHER, T0)
        notify.handle_inbound(conn, WES, "1", T0 + timedelta(minutes=8), is_sample=True)
        other = add_signal(conn, "line_fault", 37.30, -99.40, iso(T0 + timedelta(minutes=30)), "coop:feeder-9", "lockout", is_sample=True)
        evaluate_event(conn, other, WEATHER, T0 + timedelta(minutes=30))
        levels = {r["id"]: r["recommendation"] for r in conn.execute("SELECT id, recommendation FROM events")}
    assert levels[eid] == "escalate" and levels[other] == "investigate", levels
    return eid, other


def test_lite_feed_etag_and_304(client):
    eid, other = _seed_two_events()
    r = client.get("/api/lite/alerts")
    feed = r.json()
    assert [a["id"] for a in feed["alerts"]] == [eid, other]  # escalate first
    a = feed["alerts"][0]
    assert a["level"] == "escalate" and a["why"] and set(a) >= {"id", "level", "score", "label", "lat", "lon", "why", "status", "seen", "data_at"}
    assert r.headers["etag"] and "quiet" in feed
    again = client.get("/api/lite/alerts", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    assert client.get("/api/lite/alerts", headers={"If-None-Match": '"stale"'}).status_code == 200


def test_lite_page_defaults_to_the_newest_escalate_and_stays_small(client):
    eid, other = _seed_two_events()
    r = client.get("/lite")
    assert r.status_code == 200
    assert "Page the district" in r.text  # the escalate, though the investigate is newer
    assert "<script" not in r.text.lower() and "onclick" not in r.text.lower()
    assert len(r.content) < 8 * 1024
    assert f'/lite?id={other}' in r.text  # the other fire is one tap away
    assert "Possible fire" in client.get(f"/lite?id={other}").text

    for bad in ("abc", "9999", "-1"):
        r = client.get(f"/lite?id={bad}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert "That alert link isn't right. Showing the newest alert instead." in r.text
        assert "Page the district" in r.text  # the default newest escalate follows


def test_lite_empty_state(client):
    assert "No fires right now" in client.get("/lite").text
    r = client.get("/lite?id=abc")
    assert r.status_code == 200 and "link isn't right" in r.text and "No fires right now" in r.text


def test_gzip_applies_to_big_responses(client):
    _seed_two_events()
    r = client.get("/api/alerts", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def _form(client, eid, action, **extra):
    page = client.get(f"/lite?id={eid}").text
    import re
    token = re.search(rf'name="token" value="(\w+)"><input type="hidden" name="action" value="{action}"', page).group(1)
    return client.post("/lite/act", data={"id": eid, "action": action, "token": token, **extra}, follow_redirects=False)


def test_lite_action_and_undo_restore_the_server_stored_status(client):
    eid, _ = _seed_two_events()
    r = _form(client, eid, "dismiss")
    assert r.status_code == 303 and "done=dismiss" in r.headers["location"]
    status = lambda: client.get(f"/api/alerts/{eid}").json()["status"]
    assert status() == "dismissed"
    # A forged "prev" field is ignored: Undo reads the status the server logged.
    r = _form(client, eid, "undo", prev="escalated")
    assert r.status_code == 303 and status() == "new"
    assert 'value="undo"' not in client.get(f"/lite?id={eid}").text  # nothing left to undo


def test_lite_second_undo_is_refused_and_bad_tokens_are_rejected(client):
    eid, _ = _seed_two_events()
    _form(client, eid, "ack")
    assert client.get(f"/api/alerts/{eid}").json()["status"] == "acknowledged"
    page = client.get(f"/lite?id={eid}").text
    assert 'value="undo"' in page
    _form(client, eid, "undo")
    assert 'value="undo"' not in client.get(f"/lite?id={eid}").text
    token_for_other_action = client.post("/lite/act", data={"id": eid, "action": "undo", "token": "0" * 24})
    assert token_for_other_action.status_code == 400
    bad = client.post("/lite/act", data={"id": eid, "action": "dismiss", "token": "x"})
    assert bad.status_code == 400 and client.get(f"/api/alerts/{eid}").json()["status"] == "new"


def test_lite_undo_is_closed_when_someone_else_acted_after(client):
    eid, _ = _seed_two_events()
    _form(client, eid, "ack")
    client.post(f"/api/alerts/{eid}/actions", json={"action": "escalate", "operator": "Dana"})
    page = client.get(f"/lite?id={eid}").text
    assert 'value="undo"' not in page


def test_lite_token_uses_firewatch_secret(monkeypatch):
    from app import lite
    monkeypatch.setenv("FIREWATCH_SECRET", "one")
    get_settings.cache_clear()
    t = lite._token(5, "ack")
    assert lite._token_ok(5, "ack", t) and not lite._token_ok(5, "dismiss", t) and not lite._token_ok(6, "ack", t)
    monkeypatch.setenv("FIREWATCH_SECRET", "two")
    get_settings.cache_clear()
    assert not lite._token_ok(5, "ack", t)


# ---------- 4. CAP 1.2 ----------

CAP = "{urn:oasis:names:tc:emergency:cap:1.2}"


def test_cap_export_is_exercise_for_scenario_events(client):
    eid, _ = _seed_two_events()
    r = client.get(f"/api/alerts/{eid}/cap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/cap+xml")
    root = ET.fromstring(r.text)
    assert root.tag == CAP + "alert"
    assert root.find(CAP + "status").text == "Exercise"
    assert root.find(CAP + "msgType").text == "Alert"
    info = root.find(CAP + "info")
    assert info.find(CAP + "urgency").text == "Immediate" and info.find(CAP + "severity").text == "Severe"
    lat, lon, radius = info.find(CAP + "area").find(CAP + "circle").text.replace(",", " ").split()
    assert abs(float(lat) - FIRE[0]) < 0.01 and abs(float(lon) - FIRE[1]) < 0.01
    assert client.get("/api/alerts/9999/cap.xml").status_code == 404


def test_cap_status_is_actual_for_a_live_event_and_text_is_escaped():
    from app import cap
    xml = cap.to_cap({"id": 1, "lat": 37.0, "lon": -99.0, "last_seen": "2026-11-01T12:00:00Z", "recommendation": "investigate",
                      "place_label": "A & B <farm>", "is_sample": False, "score": 50, "reasons": [{"label": "x < y"}]})
    root = ET.fromstring(xml)
    assert root.find(CAP + "status").text == "Actual"
    assert "A & B <farm>" in root.find(CAP + "info").find(CAP + "headline").text


# ---------- 5. live-send guard ----------

@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("SMS_GATEWAY", "twilio")
    monkeypatch.setenv("FIREWATCH_OPERATOR_TOKEN", "op-secret")
    get_settings.cache_clear()
    calls = []
    monkeypatch.setattr(notify.TwilioGateway, "send", lambda self, to, body: calls.append((to, body)) or "SMfake")
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(utcnow()), "coop:f4", "lockout", is_sample=False)
        contact = conn.execute("SELECT * FROM contacts WHERE phone = ?", (WES,)).fetchone()
    return calls, eid, contact


def _send(eid, contact, purpose="duty_fyi"):
    with connect() as conn:
        out = notify.send(conn, contact, "test", purpose, eid, utcnow(), False, channels=("sms",))
    return out["status"]


def test_real_sms_is_held_without_the_operator_token(live):
    calls, eid, contact = live
    assert _send(eid, contact) == "held" and calls == []
    with livesend.operator("wrong"):
        assert _send(eid, contact) == "held"
    with livesend.operator(""):
        assert _send(eid, contact) == "held"
    assert calls == []


def test_real_sms_needs_a_configured_token(live, monkeypatch):
    calls, eid, contact = live
    monkeypatch.setenv("FIREWATCH_OPERATOR_TOKEN", "")
    get_settings.cache_clear()
    with livesend.operator(""):
        assert _send(eid, contact) == "held" and calls == []


def test_real_sms_goes_out_once_per_event_per_two_minutes(live):
    calls, eid, contact = live
    with livesend.operator("op-secret"):
        assert _send(eid, contact) == "sent"
        assert _send(eid, contact) == "sent"  # same operator action: the whole page goes out together
    assert len(calls) == 2
    with livesend.operator("op-secret"):
        assert _send(eid, contact) == "held"  # a new action inside the cooldown
    assert len(calls) == 2
    with connect() as conn:  # two minutes later
        conn.execute("UPDATE messages SET created_at = ? WHERE status = 'sent'", (iso(utcnow() - timedelta(minutes=2, seconds=5)),))
    with livesend.operator("op-secret"):
        assert _send(eid, contact) == "sent"


def test_practice_and_dry_run_sends_stay_open(live):
    calls, eid, contact = live
    with connect() as conn:
        out = notify.send(conn, contact, "test", "duty_fyi", eid, utcnow(), True, channels=("sms",))  # sample / replay
    assert out["status"] == "sent" and calls == []  # outbox gateway, nothing real
    assert _send(eid, contact, purpose="reply") == "sent"  # a reply to a text the person just sent


def test_decision_endpoint_needs_the_token_and_respects_the_cooldown(client, live):
    calls, eid, contact = live
    with connect() as conn:
        conn.execute("UPDATE events SET response_json = '{}' WHERE id = ?", (eid,))
    body = {"action": "page", "operator": "Dana"}
    r = client.post(f"/api/alerts/{eid}/decision", json=body)
    assert r.status_code == 401 and "op-secret" not in r.text
    r = client.post(f"/api/alerts/{eid}/decision", json=body, headers={"X-Firewatch-Operator-Token": "bad"})
    assert r.status_code == 401
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages(event_id, contact_id, phone, direction, purpose, body, status, is_sample, created_at, channel) "
            "VALUES (?, ?, ?, 'out', 'page', 'x', 'sent', 0, ?, 'sms')", (eid, contact["id"], WES, iso(utcnow())))
    r = client.post(f"/api/alerts/{eid}/decision", json=body, headers={"X-Firewatch-Operator-Token": "op-secret"})
    assert r.status_code == 429 and "op-secret" not in r.text and int(r.headers["retry-after"]) > 0
    assert calls == []


# ---------- 6. mesh fixes ----------

def test_mesh_text_is_cut_at_233_utf8_bytes_on_a_character_boundary():
    assert mesh.MESH_MAX_BYTES == 233
    assert mesh._fit("a" * 233) == "a" * 233
    assert mesh._fit("a" * 300) == "a" * 233
    s = "é" * 200  # 2 bytes each
    out = mesh._fit(s)
    assert len(out.encode()) == 232 and set(out) == {"é"}
    s = "—" * 100  # 3 bytes each: 233 = 77 chars + 2 spare bytes
    assert len(mesh._fit(s).encode()) == 231
    s = "ab" + "\U0001f525" * 80  # 4-byte emoji
    out = mesh._fit(s)
    assert len(out.encode()) <= 233 and out.encode().decode() == out and out.startswith("ab")
    assert mesh._fit("short") == "short"


def test_mesh_position_inside_district_box_only():
    assert mesh.plausible_position(*FIRE)
    assert mesh.plausible_position(37.3821, -99.0)          # ~55 km east of the fire, inside the padded box
    assert not mesh.plausible_position(0, 0)                 # no GPS fix
    assert not mesh.plausible_position(0.0, 0.0)
    assert not mesh.plausible_position(40.7, -74.0)          # New York
    assert not mesh.plausible_position(None, None)
    assert not mesh.plausible_position(float("nan"), -99.0)
    assert not mesh.plausible_position(37.3821, -97.0)       # well past the 40 km pad


def test_mesh_handle_packet_rejects_bad_positions():
    def pkt(lat, lon):
        return {"from": 0xBEEF, "to": 0xFFFFFFFF, "fromId": mesh.node_id(0xBEEF),
                "decoded": {"portnum": "POSITION_APP", "position": {"latitude": lat, "longitude": lon}}}
    with connect() as conn:
        for lat, lon in ((0, 0), (40.7, -74.0)):
            assert mesh.handle_packet(conn, pkt(lat, lon), 1) == "position"
            assert conn.execute("SELECT lat FROM mesh_nodes").fetchone()["lat"] is None
        mesh.handle_packet(conn, pkt(*FIRE), 1)
        assert conn.execute("SELECT lat FROM mesh_nodes").fetchone()["lat"] == pytest.approx(FIRE[0], abs=1e-4)


def test_mesh_seeded_node_positions_are_checked_too():
    iface = SimpleNamespace(nodes={"!0000beef": {"lastHeard": 1773773400, "position": {"latitude": 0.0, "longitude": 0.0}}})
    with connect() as conn:
        mesh._seed_nodes(conn, iface)
        assert conn.execute("SELECT lat, position_at FROM mesh_nodes").fetchone()["lat"] is None


def test_no_radio_is_a_clear_error_within_the_limit(monkeypatch):
    monkeypatch.setattr(mesh, "OPEN_TIMEOUT_S", 0.3)
    # 2.7.11 returns an unconnected interface when the device is missing
    dead = SimpleNamespace(isConnected=threading.Event(), close=lambda: None)
    monkeypatch.setattr(mesh, "_open_raw", lambda: dead)
    t = time.monotonic()
    with pytest.raises(RuntimeError, match="no Meshtastic radio"):
        mesh._open_interface()
    assert time.monotonic() - t < 2
    # a radio that never answers
    monkeypatch.setattr(mesh, "_open_raw", lambda: time.sleep(5))
    t = time.monotonic()
    with pytest.raises(RuntimeError, match="within"):
        mesh._open_interface()
    assert time.monotonic() - t < 2
    # a connected one is returned
    ok = SimpleNamespace(isConnected=threading.Event())
    ok.isConnected.set()
    monkeypatch.setattr(mesh, "_open_raw", lambda: ok)
    assert mesh._open_interface() is ok


def test_start_reports_down_when_no_radio(monkeypatch):
    monkeypatch.setenv("MESH_GATEWAY", "serial")
    get_settings.cache_clear()
    monkeypatch.setattr(mesh, "OPEN_TIMEOUT_S", 0.3)
    monkeypatch.setattr(mesh, "_open_raw", lambda: SimpleNamespace(isConnected=threading.Event(), close=lambda: None))
    t = time.monotonic()
    assert mesh.start() is False and time.monotonic() - t < 2
    assert mesh.health()["status"] == "down" and "no Meshtastic radio" in mesh.health()["last_error"]
