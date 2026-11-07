from datetime import timedelta

import pytest

from app import notify, posts
from app.confirm import evaluate_event
from app.db import connect, iso, loads, parse_iso
from app.district import sync_roster
from app.notify import SMS_MAX
from app.signals import add_signal

T0 = parse_iso("2026-03-14T18:50:00Z")
FIRE = (37.77, -96.66)
WEATHER = {"wind_kmh": 26, "gust_kmh": 45, "wind_dir_deg": 200, "rh_pct": 18, "temp_c": 24, "precip_72h_mm": 0, "thunder_24h": 0}
DUTY, WES = "+13165550101", "+13165550131"


def at(minutes: float):
    return T0 + timedelta(minutes=minutes)


def out(conn, purpose, eid=None):
    q, a = "SELECT * FROM messages WHERE direction = 'out' AND purpose = ?", [purpose]
    if eid is not None:
        q, a = q + " AND event_id = ?", a + [eid]
    return conn.execute(q, a).fetchall()


def ev(conn, eid):
    return conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()


def volunteer(conn):
    return conn.execute("SELECT * FROM contacts WHERE role = 'volunteer' ORDER BY id").fetchone()


def escalated(conn):
    """A line fault confirmed by a neighbor: level escalate, duty officer texted at minute 8."""
    sync_roster(conn)
    eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
    evaluate_event(conn, eid, WEATHER, at(0))
    notify.handle_inbound(conn, WES, "1", at(8), is_sample=True)
    assert len(out(conn, "duty_escalate", eid)) == 1
    return eid


def test_duty_ack_stops_the_ladder():
    with connect() as conn:
        eid = escalated(conn)
        r = notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        assert r["ok"] and r["level"] == "ladder"
        row = ev(conn, eid)
        assert row["ack_level"] == "ladder" and row["status"] == "acknowledged"
        assert parse_iso(row["ack_until"]) == at(39)
        assert row["ack_mark_det"] is not None and row["ack_mark_sig"] is not None
        notify.tick(conn, at(12), is_sample=True)
        notify.tick(conn, at(20), is_sample=True)
        assert not out(conn, "ladder") and not out(conn, "ladder_dispatch")
        assert conn.execute("SELECT 1 FROM actions WHERE event_id = ? AND action = 'acknowledge'", (eid,)).fetchone()


def test_volunteer_ack_does_not_stop_the_ladder():
    with connect() as conn:
        eid = escalated(conn)
        r = notify.acknowledge(conn, event_id=eid, by="Vol", role="volunteer", now=at(9))
        assert r["ok"] and r["level"] == "crowd"
        notify.tick(conn, at(11), is_sample=True)
        assert len(out(conn, "ladder", eid)) == 1, "a crowd hold never silences the no-answer ladder"


def test_member_cannot_acknowledge():
    with connect() as conn:
        eid = escalated(conn)
        r = notify.acknowledge(conn, event_id=eid, by="Rancher", role="rancher", now=at(9))
        assert not r["ok"] and r["refused"] == "not_allowed"
        assert ev(conn, eid)["ack_until"] is None


def test_refusals_without_target_or_on_a_closed_event():
    with connect() as conn:
        eid = escalated(conn)
        assert notify.acknowledge(conn, by="Duty", role="duty_officer", now=at(9))["refused"] == "no_target"
        assert notify.acknowledge(conn, event_id=9999, by="Duty", role="duty_officer", now=at(9))["refused"] == "not_found"
        conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (eid,))
        assert notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))["refused"] == "closed"


def test_crowd_never_replaces_a_ladder_hold_and_repeat_extends_nothing():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        r = notify.acknowledge(conn, event_id=eid, by="Vol", role="volunteer", now=at(10))
        assert r["ok"] and r["level"] == "ladder" and ev(conn, eid)["ack_by"] == "Duty"
        r = notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(20))
        assert parse_iso(ev(conn, eid)["ack_until"]) == at(39), "a repeat tap does not push the expiry out"


def test_ladder_hold_gate_in_on_level_leaves_no_state():
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(0))
        notify.on_level(conn, eid, "escalate", at(1))
        assert ev(conn, eid)["response_json"] is None, "nothing may be written while held, so resume can replay"
        assert not out(conn, "duty_escalate") and not out(conn, "ask_neighbor")


def test_crowd_hold_skips_asks_but_keeps_duty_fyi():
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
        notify.acknowledge(conn, event_id=eid, by="Vol", role="volunteer", now=at(0))
        notify.on_level(conn, eid, "investigate", at(1))
        assert not out(conn, "ask_neighbor")
        assert len(out(conn, "duty_fyi", eid)) == 1
        assert loads(ev(conn, eid)["response_json"])["asks_skipped"] is True


def test_page_still_works_and_clears_the_hold():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        r = notify.handle_inbound(conn, DUTY, "page", at(10), is_sample=True)
        assert r["action"] == "page"
        assert out(conn, "page_dispatch", eid)
        row = ev(conn, eid)
        assert row["ack_until"] is None and row["ack_level"] is None and row["status"] == "escalated"


def test_no_clears_the_hold():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        notify.decide(conn, eid, "no", "Duty", at(10))
        assert ev(conn, eid)["ack_until"] is None


def test_crowd_hold_stops_post_timer_and_ring_asks(monkeypatch):
    monkeypatch.setattr(posts, "high_danger", lambda *a, **k: True)
    with connect() as conn:
        sync_roster(conn)
        p = posts.create(conn, None, "+13165559000", "smoke north", "smoke", False, T0, True, at=FIRE)["post_id"]
        asked = len(out(conn, "ask_post"))
        notify.acknowledge(conn, post_id=p, by="Vol", role="volunteer", now=at(1))
        assert posts.tick(conn, at(6), True) == [] and not out(conn, "post_timer")
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (p,)).fetchone()
        assert posts.ask_ring(conn, post, at(7)) == [] and len(out(conn, "ask_post")) == asked
        assert post["ack_level"] == "crowd"


def test_new_texts_fit_one_sms():
    ev_row = {"id": 1, "kind": "line_fault", "lat": 37.77, "lon": -96.66, "recommendation": "escalate", "score": 80,
              "level_reason": "x" * 300, "place_label": "y" * 90, "created_at": iso(T0)}
    for body in (notify.t_hold_expired(ev_row), notify.t_hold_broken(ev_row, "x" * 300), notify.t_ack_reply("x" * 80, 30)):
        assert len(body) <= SMS_MAX


def _det(conn, eid, minute):
    conn.execute(
        "INSERT INTO detections(dedupe_key, source, lat, lon, acq_time, is_sample, ingested_at, event_id) "
        "VALUES (?, 'VIIRS_SNPP_NRT', ?, ?, ?, 1, ?, ?)",
        (f"k{minute}", *FIRE, iso(at(minute)), iso(at(minute)), eid))


def test_satellite_hit_breaks_the_hold_with_one_text():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        notify.hold_tick(conn, at(10), is_sample=True)
        assert ev(conn, eid)["ack_until"] is not None and not out(conn, "hold_broken")
        _det(conn, eid, 11)
        notify.hold_tick(conn, at(12), is_sample=True)
        notify.hold_tick(conn, at(13), is_sample=True)
        assert ev(conn, eid)["ack_until"] is None
        assert len(out(conn, "hold_broken", eid)) == 1


def test_lapse_sends_one_text_to_duty_and_resumes_the_ladder():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        notify.hold_tick(conn, at(38), is_sample=True)
        assert not out(conn, "hold_expired")
        notify.hold_tick(conn, at(40), is_sample=True)
        notify.hold_tick(conn, at(41), is_sample=True)
        assert len(out(conn, "hold_expired", eid)) == 1
        assert ev(conn, eid)["ack_until"] is None
        notify.tick(conn, at(45), is_sample=True)
        assert out(conn, "ladder")


def test_crowd_lapse_is_silent_and_runs_the_skipped_asks():
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
        notify.acknowledge(conn, event_id=eid, by="Vol", role="volunteer", now=at(0))
        evaluate_event(conn, eid, WEATHER, at(1))
        assert not out(conn, "ask_neighbors") and not out(conn, "ask")
        before = conn.execute("SELECT COUNT(*) c FROM messages WHERE direction = 'out' AND event_id = ?", (eid,)).fetchone()["c"]
        notify.hold_tick(conn, at(31), is_sample=True)
        assert not out(conn, "hold_expired")
        after = conn.execute("SELECT COUNT(*) c FROM messages WHERE direction = 'out' AND event_id = ?", (eid,)).fetchone()["c"]
        assert after > before
        assert "asks_skipped" not in (loads(ev(conn, eid)["response_json"]) or {})


def test_rise_swallowed_by_a_ladder_hold_fires_on_expiry():
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
        evaluate_event(conn, eid, WEATHER, at(0))
        assert not out(conn, "duty_escalate")
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(1))
        notify.handle_inbound(conn, WES, "1", at(8), is_sample=True)
        assert not out(conn, "duty_escalate")
        notify.hold_tick(conn, at(32), is_sample=True)
        assert len(out(conn, "duty_escalate", eid)) == 1


# --- step 3: ACK text, button, attach, estimated join ------------------------------------------------------

def all_out(conn):
    return conn.execute("SELECT COUNT(*) n FROM messages WHERE direction = 'out'").fetchone()["n"]


def last_reply(conn):
    return conn.execute("SELECT body FROM messages WHERE direction = 'out' AND purpose = 'reply' ORDER BY id DESC").fetchone()["body"]


def test_ack_text_by_duty_holds_at_ladder_level():
    with connect() as conn:
        eid = escalated(conn)
        r = notify.handle_inbound(conn, DUTY, "ACK", at(9), is_sample=True)
        assert r["action"] == "ack" and r["event_id"] == eid
        assert ev(conn, eid)["ack_level"] == "ladder"
        assert len(last_reply(conn)) <= SMS_MAX


def test_ack_text_by_volunteer_holds_at_crowd_level():
    with connect() as conn:
        eid = escalated(conn)
        vol = volunteer(conn)
        notify.send(conn, vol, "FIREWATCH page", "page", eid, at(8), True)
        r = notify.handle_inbound(conn, vol["phone"], "ack", at(9), is_sample=True)
        assert r["action"] == "ack" and ev(conn, eid)["ack_level"] == "crowd"


def test_member_ack_text_gets_help_and_no_hold():
    with connect() as conn:
        eid = escalated(conn)
        r = notify.handle_inbound(conn, WES, "ACK", at(9), is_sample=True)
        assert r["action"] == "help"
        assert ev(conn, eid)["ack_until"] is None


def test_ack_with_no_target_says_so():
    with connect() as conn:
        sync_roster(conn)
        r = notify.handle_inbound(conn, DUTY, "ACK", at(1), is_sample=True)
        assert r["action"] == "help" and "nothing open" in last_reply(conn)
        assert conn.execute("SELECT COUNT(*) n FROM events WHERE ack_until IS NOT NULL").fetchone()["n"] == 0


def test_ack_text_matches_the_button():
    with connect() as conn:
        a = escalated(conn)
        notify.handle_inbound(conn, DUTY, "ACK", at(9), is_sample=True)
        text_row = dict(ev(conn, a))
    with connect() as conn:
        conn.execute("UPDATE events SET ack_level = NULL, ack_by = NULL, ack_at = NULL, ack_until = NULL, status = 'new' WHERE id = ?", (a,))
        notify.acknowledge(conn, event_id=a, by="Duty", role="operator", now=at(9))
        btn = ev(conn, a)
        for k in ("ack_level", "ack_until", "status", "ack_mark_det", "ack_mark_sig"):
            assert btn[k] == text_row[k]


def test_button_acknowledge_holds_at_ladder_level():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        top = client.get("/api/alerts").json()["alerts"][0]
        r = client.post(f"/api/alerts/{top['id']}/actions", json={"action": "acknowledge", "operator": "Dispatch 2"})
        assert r.status_code == 200
    with connect() as conn:
        row = ev(conn, top["id"])
        assert row["ack_level"] == "ladder" and row["ack_by"] == "Dispatch 2" and row["ack_until"]


def test_post_near_held_event_attaches_and_sends_nothing():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        n_out, n_ev = all_out(conn), conn.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]
        r = notify.handle_inbound(conn, WES, "heard there is smoke near the creek", at(10), is_sample=True)
        post = conn.execute("SELECT * FROM posts ORDER BY id DESC").fetchone()
        assert post["event_id"] == eid and post["flagged"] == 0
        assert conn.execute("SELECT COUNT(*) n FROM events").fetchone()["n"] == n_ev
        assert "already known" in last_reply(conn)
        assert all_out(conn) == n_out + (1 if r["reply"] else 0)  # only the poster's reply


def test_post_near_held_post_attaches_to_it(monkeypatch):
    monkeypatch.setattr(posts, "high_danger", lambda *a, **k: True)
    with connect() as conn:
        sync_roster(conn)
        p = posts.create(conn, None, "+13165559000", "smoke north", "smoke", False, T0, True, at=FIRE)["post_id"]
        notify.acknowledge(conn, post_id=p, by="Vol", role="volunteer", now=at(1))
        n_out = all_out(conn)
        r = posts.create(conn, None, "+13165559001", "smoke north too", "smoke", False, at(2), True, at=(FIRE[0] + 0.01, FIRE[1]))
        assert r.get("known") and r["parent_id"] == p and r["asked"] == 0
        assert all_out(conn) == n_out


def test_post_ten_km_away_is_a_new_item():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        r = posts.create(conn, None, "+13165559002", "smoke far", "smoke", False, at(10), True, at=(FIRE[0] + 0.09, FIRE[1]))
        assert not r.get("known") and r["flagged"] == 1 and r["parent_id"] is None
        assert conn.execute("SELECT event_id FROM posts WHERE id = ?", (r["post_id"],)).fetchone()["event_id"] is None


def test_estimated_report_five_km_out_opens_a_new_event():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        far = add_signal(conn, "report", FIRE[0] + 0.045, FIRE[1], iso(at(10)), "sms:est", None, None, True,
                         join_radius_km=notify.ESTIMATE_JOIN_KM)
        assert far != eid


def test_confirms_during_a_hold_send_no_texts_and_count_rises():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        sync_roster(conn)
        pid = posts.create(conn, None, "+13165559003", "smoke by road", "smoke", False, at(10), True, at=FIRE)["post_id"]
        n_out = all_out(conn)
        wes = conn.execute("SELECT * FROM contacts WHERE phone = ?", (WES,)).fetchone()
        r = posts.confirm(conn, pid, wes, "see", at(11), True)
        assert r["ok"] and r["counted"] and r["count"] == 1
        assert all_out(conn) == n_out


def test_actions_route_requires_token_when_set(monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app import main
    from app.main import app

    real = main.get_settings()
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(**{**vars(real), "api_token": "s3cret"}))
    with TestClient(app) as client:
        top = client.get("/api/alerts").json()["alerts"][0]
        body = {"action": "acknowledge", "operator": "Dispatch 2"}
        r = client.post(f"/api/alerts/{top['id']}/actions", json=body)
        assert r.status_code == 401
        with connect() as conn:
            assert ev(conn, top["id"])["ack_until"] is None
        r = client.post(f"/api/alerts/{top['id']}/actions", json=body, headers={"X-Firewatch-Token": "s3cret"})
        assert r.status_code == 200


def _held_via_route(role, level_rec="escalate"):
    """A line-fault event held now by `role`; a rise to level_rec was swallowed by the hold."""
    from app.db import utcnow

    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(utcnow()), "coop:feeder-4", "lockout", is_sample=True)
        notify.acknowledge(conn, event_id=eid, by="Hold", role=role, now=utcnow())
        conn.execute("UPDATE events SET recommendation = ? WHERE id = ?", (level_rec, eid))
        notify.on_level(conn, eid, level_rec, utcnow())
        assert not out(conn, "duty_escalate", eid)
    return eid


def _act(client, eid, action, **kw):
    return client.post(f"/api/alerts/{eid}/actions", json={"action": action, "operator": "Dispatch 2", **kw})


@pytest.mark.parametrize("action", ["dismiss", "escalate", "reopen"])
def test_dismiss_escalate_reopen_clear_the_hold(action):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        eid = _held_via_route("duty_officer", "monitor")
        assert _act(client, eid, action).status_code == 200
        with connect() as conn:
            row = ev(conn, eid)
            assert row["ack_until"] is None and row["ack_level"] is None


@pytest.mark.parametrize("action", ["escalate", "reopen"])
def test_escalate_and_reopen_fire_the_swallowed_rise(action):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        eid = _held_via_route("duty_officer")
        assert _act(client, eid, action).status_code == 200
        with connect() as conn:
            assert out(conn, "duty_escalate", eid)


def test_refused_acknowledge_is_409_and_changes_nothing(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(notify, "acknowledge", lambda *a, **k: {"ok": False, "refused": "closed"})
    with TestClient(app) as client:
        with connect() as conn:
            eid = add_signal(conn, "line_fault", *FIRE, iso(T0), "coop:feeder-4", "lockout", is_sample=True)
            before = ev(conn, eid)["status"]
        r = _act(client, eid, "acknowledge")
        assert r.status_code == 409 and "closed" in r.json()["detail"]
        with connect() as conn:
            assert ev(conn, eid)["status"] == before
            assert not conn.execute("SELECT 1 FROM actions WHERE event_id = ?", (eid,)).fetchone()


def test_one_acknowledge_one_action_row_with_the_note():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        with connect() as conn:
            sync_roster(conn)
            eid = add_signal(conn, "line_fault", *FIRE, iso(T0), "coop:feeder-4", "lockout", is_sample=True)
        r = _act(client, eid, "acknowledge", note="crew rolling")
        assert r.status_code == 200
        with connect() as conn:
            rows = conn.execute("SELECT * FROM actions WHERE event_id = ? AND action = 'acknowledge'", (eid,)).fetchall()
            assert len(rows) == 1 and rows[0]["note"] == "crew rolling"
            assert ev(conn, eid)["status"] == "acknowledged"


def test_operator_acknowledge_upgrades_a_crowd_hold_and_repeat_is_200():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        eid = _held_via_route("volunteer", "monitor")
        with connect() as conn:
            assert ev(conn, eid)["ack_level"] == "crowd"
        assert _act(client, eid, "acknowledge").status_code == 200
        with connect() as conn:
            assert ev(conn, eid)["ack_level"] == "ladder"
        assert _act(client, eid, "acknowledge").status_code == 200


def test_volunteer_ack_with_no_text_about_an_event_holds_nothing():
    with connect() as conn:
        eid = escalated(conn)
        vol = volunteer(conn)
        r = notify.handle_inbound(conn, vol["phone"], "ACK", at(9), is_sample=True)
        assert r["action"] == "help" and "nothing open" in last_reply(conn)
        assert ev(conn, eid)["ack_until"] is None


def test_volunteer_ask_text_is_not_an_ack_target():
    with connect() as conn:
        eid = escalated(conn)
        vol = volunteer(conn)
        notify.send(conn, vol, "FIREWATCH check", "ask_neighbors", eid, at(8), True)
        r = notify.handle_inbound(conn, vol["phone"], "ACK", at(9), is_sample=True)
        assert r["action"] == "help" and ev(conn, eid)["ack_until"] is None


def test_duty_ack_targets_the_newer_post_text_over_a_closed_event():
    with connect() as conn:
        eid = escalated(conn)
        conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (eid,))
        pid = posts.create(conn, None, "+13165559003", "smoke by road", "smoke", False, at(10), True, at=FIRE)["post_id"]
        duty = conn.execute("SELECT * FROM contacts WHERE phone = ?", (DUTY,)).fetchone()
        notify.send(conn, duty, "FIREWATCH post", "post_timer", None, at(11), True, post_id=pid)
        r = notify.handle_inbound(conn, DUTY, "ACK", at(12), is_sample=True)
        assert r["action"] == "ack"
        assert conn.execute("SELECT ack_level FROM posts WHERE id = ?", (pid,)).fetchone()["ack_level"] == "ladder"
        assert ev(conn, eid)["ack_until"] is None


def test_duty_ack_with_no_texts_falls_back_to_the_open_response():
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
        evaluate_event(conn, eid, WEATHER, at(0))
        conn.execute("DELETE FROM messages WHERE direction = 'out'")
        assert conn.execute("SELECT response_json FROM events WHERE id = ?", (eid,)).fetchone()[0] is not None
        r = notify.handle_inbound(conn, DUTY, "ACK", at(2), is_sample=True)
        assert r["action"] == "ack" and ev(conn, eid)["ack_level"] == "ladder"


MEMBER = "+13165550131"  # WES, a registered member


@pytest.mark.parametrize("role", ["duty_officer", "volunteer"])
def test_member_web_post_near_held_event_stores_a_report_signal_and_sends_nothing(role):
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Holder", role=role, now=at(9))
        wes = conn.execute("SELECT * FROM contacts WHERE phone = ?", (WES,)).fetchone()
        assert wes["registered"]
        n_out, n_sig = all_out(conn), conn.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"]
        r = posts.create(conn, wes, WES, "smoke near the creek", "smoke", False, at(10), True, channel="web", at=FIRE)
        assert conn.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"] == n_sig + 1
        sig = conn.execute("SELECT * FROM signals ORDER BY id DESC").fetchone()
        assert sig["kind"] == "report" and sig["event_id"] == eid and sig["contact_id"] == wes["id"]
        assert r["post_id"] and r["event_id"] == eid
        assert all_out(conn) == n_out


def test_stranger_post_near_held_event_attaches_with_no_signal():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        n_sig = conn.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"]
        r = posts.create(conn, None, "+13165559003", "smoke near the creek", "smoke", False, at(10), True, at=FIRE)
        assert r.get("known") and r["event_id"] == eid
        assert conn.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"] == n_sig


# --- replay clock, ladder resume, unseen evidence, dismiss -----------------------------------------------


def test_live_tick_leaves_holds_on_scenario_events_alone():
    from app import main, scenario

    slug = sorted(p.stem for p in scenario.SCENARIOS_DIR.glob("*.json"))[0]
    with connect() as conn:
        eid = escalated(conn)
        conn.execute("UPDATE events SET sample_slug = ? WHERE id = ?", (slug, eid))
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        conn.commit()
    main._tick_live()
    with connect() as conn:
        assert ev(conn, eid)["ack_until"] is not None, "the real clock must not expire a replay hold"
        assert not out(conn, "hold_expired")


def test_sms_simulate_uses_the_replay_clock(monkeypatch):
    from fastapi.testclient import TestClient

    from app import scenario
    from app.main import app

    with connect() as conn:
        eid = escalated(conn)
        conn.commit()
    monkeypatch.setattr(scenario, "running_now", lambda: at(9))
    with TestClient(app) as client:
        r = client.post("/api/sms/simulate", json={"from": DUTY, "body": "ACK"})
        assert r.status_code == 200
    with connect() as conn:
        assert parse_iso(ev(conn, eid)["ack_until"]) == at(9) + timedelta(minutes=30)


def test_ladder_waits_a_full_step_after_a_hold_ends():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(9))
        notify.hold_tick(conn, at(40), is_sample=True)
        assert len(out(conn, "hold_expired", eid)) == 1
        notify.tick(conn, at(40), is_sample=True)
        notify.tick(conn, at(42), is_sample=True)
        assert not out(conn, "ladder", eid)
        notify.tick(conn, at(43), is_sample=True)
        assert len(out(conn, "ladder", eid)) == 1
        notify.tick(conn, at(43.5), is_sample=True)
        assert not out(conn, "ladder_dispatch", eid)
        notify.tick(conn, at(49), is_sample=True)
        assert len(out(conn, "ladder_dispatch", eid)) == 1


def test_ladder_upgrade_keeps_marks_so_unseen_evidence_breaks_the_hold():
    with connect() as conn:
        eid = escalated(conn)
        notify.acknowledge(conn, event_id=eid, by="Vol", role="volunteer", now=at(9))
        _det(conn, eid, 10)
        notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(11))
        assert ev(conn, eid)["ack_level"] == "ladder"
        notify.hold_tick(conn, at(12), is_sample=True)
        assert ev(conn, eid)["ack_until"] is None
        assert len(out(conn, "hold_broken", eid)) == 1


def test_dismissed_event_gets_no_ladder_step():
    from fastapi.testclient import TestClient

    from app.main import app

    with connect() as conn:
        eid = escalated(conn)
        conn.commit()
    with TestClient(app) as client:
        assert _act(client, eid, "dismiss").status_code == 200
    with connect() as conn:
        assert ev(conn, eid)["status"] == "dismissed"
        notify.tick(conn, at(20), is_sample=True)
        assert not out(conn, "ladder", eid)


# ---- defects 4, 5, 8, 9 -------------------------------------------------------------------------

def _stranger_post(conn, minute=0, phone="+13165559003", body="smoke by road", cat="smoke"):
    sync_roster(conn)
    return posts.create(conn, None, phone, body, cat, False, at(minute), True, at=FIRE)["post_id"]


def _post(conn, pid):
    return conn.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()


def _contact(conn, phone):
    return conn.execute("SELECT * FROM contacts WHERE phone = ?", (phone,)).fetchone()


def test_d4_ladder_hold_on_post_carries_to_the_event_it_opens():
    with connect() as conn:
        pid = _stranger_post(conn)
        notify.acknowledge(conn, post_id=pid, by="Duty", role="duty_officer", now=at(1))
        n_out = all_out(conn)
        r = posts.confirm(conn, pid, _contact(conn, WES), "see", at(2), True)
        assert r["ok"] and r["counted"] and r["count"] == 1
        assert all_out(conn) == n_out, "a ladder hold on the post silences the event it opens"
        assert ev(conn, r["event_id"])["ack_level"] == "ladder"
        assert _post(conn, pid)["ack_until"] is None, "the hold moved to the event"


def test_d4_carried_ladder_hold_replays_at_its_end():
    with connect() as conn:
        pid = _stranger_post(conn)
        notify.acknowledge(conn, post_id=pid, by="Duty", role="duty_officer", now=at(1))
        r = posts.confirm(conn, pid, _contact(conn, WES), "see", at(2), True)
        assert not out(conn, "duty_fyi", r["event_id"])
        notify.hold_tick(conn, at(40), True)
        assert out(conn, "duty_fyi", r["event_id"]), "the swallowed level is replayed"


def test_d4_carried_crowd_hold_sends_duty_fyi_but_no_neighbor_ask():
    with connect() as conn:
        pid = _stranger_post(conn)
        notify.acknowledge(conn, post_id=pid, by="Vol", role="volunteer", now=at(1))
        r = posts.confirm(conn, pid, _contact(conn, WES), "see", at(2), True)
        eid = r["event_id"]
        assert ev(conn, eid)["ack_level"] == "crowd"
        assert out(conn, "duty_fyi", eid)
        assert not out(conn, "ask_neighbor", eid)
        assert "asks_skipped" in (ev(conn, eid)["response_json"] or "")


def _swallowed(conn):
    sync_roster(conn)
    eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
    notify.acknowledge(conn, event_id=eid, by="Duty", role="duty_officer", now=at(0))
    evaluate_event(conn, eid, WEATHER, at(1))
    return eid


def test_d5_ladder_hold_swallows_level_but_is_still_found_for_a_page():
    with connect() as conn:
        eid = _swallowed(conn)
        assert ev(conn, eid)["ack_level"] == "ladder"
        assert notify._latest_open_response(conn, True) == eid


def test_d5_console_page_works_under_a_ladder_hold():
    from fastapi.testclient import TestClient

    from app.main import app

    with connect() as conn:
        eid = _swallowed(conn)
        conn.commit()
    with TestClient(app) as client:
        r = client.post(f"/api/alerts/{eid}/decision", json={"action": "page", "operator": "Dispatch 2"})
        assert r.status_code == 200, r.text
    with connect() as conn:
        assert ev(conn, eid)["ack_until"] is None
        assert out(conn, "page", eid)


def test_d5_texted_page_from_duty_pages_under_a_ladder_hold():
    with connect() as conn:
        eid = _swallowed(conn)
        r = notify.handle_inbound(conn, DUTY, "PAGE", at(3), is_sample=True)
        assert r["action"] == "page" and r["event_id"] == eid
        assert out(conn, "page", eid)


def test_d5_crowd_hold_keeps_its_response_so_page_still_works():
    """Guard: a crowd hold does not swallow the ladder, so the fix must not change this path."""
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
        notify.acknowledge(conn, event_id=eid, by="Vol", role="volunteer", now=at(0))
        evaluate_event(conn, eid, WEATHER, at(1))
        assert ev(conn, eid)["response_json"] is not None
        r = notify.handle_inbound(conn, DUTY, "PAGE", at(3), is_sample=True)
        assert r["action"] == "page" and r["event_id"] == eid


def test_d8_post_only_ladder_hold_lapse_tells_duty_once(monkeypatch):
    monkeypatch.setattr(posts, "high_danger", lambda *a, **k: True)
    with connect() as conn:
        pid = _stranger_post(conn)
        notify.acknowledge(conn, post_id=pid, by="Duty", role="duty_officer", now=at(1))
        notify.hold_tick(conn, at(40), True)
        sent = out(conn, "hold_expired")
        assert len(sent) == 1 and sent[0]["post_id"] == pid and sent[0]["event_id"] is None
        assert _post(conn, pid)["ack_until"] is None
        notify.hold_tick(conn, at(41), True)
        assert len(out(conn, "hold_expired")) == 1
        assert posts.tick(conn, at(42), True) == [] and not out(conn, "post_timer")


def test_d8_post_only_crowd_hold_lapse_is_silent_then_timer_fires(monkeypatch):
    monkeypatch.setattr(posts, "high_danger", lambda *a, **k: True)
    with connect() as conn:
        pid = _stranger_post(conn)
        notify.acknowledge(conn, post_id=pid, by="Vol", role="volunteer", now=at(1))
        notify.hold_tick(conn, at(40), True)
        assert not out(conn, "hold_expired")
        posts.tick(conn, at(41), True)
        assert len(out(conn, "post_timer")) == 1


def test_d8_unlocated_post_hold_lapse_does_not_raise_and_fits():
    with connect() as conn:
        pid = _stranger_post(conn)
        conn.execute("UPDATE posts SET lat = NULL, lon = NULL WHERE id = ?", (pid,))
        notify.acknowledge(conn, post_id=pid, by="Duty", role="duty_officer", now=at(1))
        notify.hold_tick(conn, at(40), True)
        sent = out(conn, "hold_expired")
        assert len(sent) == 1 and len(sent[0]["body"]) <= SMS_MAX


def test_d8_old_replay_post_hold_is_left_alone():
    with connect() as conn:
        pid = _stranger_post(conn)
        notify.acknowledge(conn, post_id=pid, by="Duty", role="duty_officer", now=at(1))
        conn.execute("UPDATE posts SET created_at = ? WHERE id = ?", (iso(at(0) - timedelta(days=200)), pid))
        notify.hold_tick(conn, at(40), True)
        assert not out(conn, "hold_expired")
        assert _post(conn, pid)["ack_until"] is not None


def test_d8_duty_ack_after_hold_expired_text_holds_again():
    with connect() as conn:
        pid = _stranger_post(conn)
        notify.acknowledge(conn, post_id=pid, by="Duty", role="duty_officer", now=at(1))
        notify.hold_tick(conn, at(40), True)
        r = notify.handle_inbound(conn, DUTY, "ACK", at(41), is_sample=True)
        assert r["action"] == "ack"
        assert _post(conn, pid)["ack_level"] == "ladder" and _post(conn, pid)["ack_until"] is not None


def _post_text(conn, purpose, cat="smoke"):
    """Duty has a duty_fyi on an older event and a newer text about a post with no event."""
    sync_roster(conn)
    old = add_signal(conn, "line_fault", 37.5, -96.3, iso(at(0)), "coop:feeder-9", "lockout", is_sample=True)
    duty = _contact(conn, DUTY)
    notify.send(conn, duty, "FIREWATCH old", "duty_fyi", old, at(1), True)
    pid = posts.create(conn, None, "+13165559003", "smoke by road", cat, False, at(10), True, at=FIRE)["post_id"]
    assert _post(conn, pid)["event_id"] is None
    notify.send(conn, duty, "FIREWATCH post", purpose, None, at(11), True, post_id=pid)
    return old, pid


def _decision(conn, eid):
    return (loads(ev(conn, eid)["response_json"]) or {}).get("decision") if ev(conn, eid)["response_json"] else None


def test_d9_page_after_post_text_opens_that_posts_event():
    with connect() as conn:
        old, pid = _post_text(conn, "post_timer")
        r = notify.handle_inbound(conn, DUTY, "PAGE", at(12), is_sample=True)
        new = _post(conn, pid)["event_id"]
        assert new and new != old and r["action"] == "page" and r["event_id"] == new
        assert _decision(conn, new) == "page"
        assert _decision(conn, old) is None


def test_d9_page_after_post_text_with_older_event_closed():
    with connect() as conn:
        old, pid = _post_text(conn, "post_timer")
        conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (old,))
        r = notify.handle_inbound(conn, DUTY, "PAGE", at(12), is_sample=True)
        new = _post(conn, pid)["event_id"]
        assert new and r["event_id"] == new and _decision(conn, new) == "page"
        assert _decision(conn, old) is None


def test_d9_no_after_post_timer_dismisses_the_post():
    with connect() as conn:
        old, pid = _post_text(conn, "post_timer")
        r = notify.handle_inbound(conn, DUTY, "NO", at(12), is_sample=True)
        assert r["action"] == "no"
        assert _post(conn, pid)["status"] == "dismissed" and _post(conn, pid)["event_id"] is None
        assert _decision(conn, old) is None


def test_d9_page_after_hazard_text_opens_no_event():
    with connect() as conn:
        old, pid = _post_text(conn, "post_hazard", cat="hazard")
        r = notify.handle_inbound(conn, DUTY, "PAGE", at(12), is_sample=True)
        assert _post(conn, pid)["event_id"] is None
        assert "check the board" in r["reply"].lower()
        assert _decision(conn, old) is None


def test_d9_page_when_post_already_has_an_event_pages_that_event():
    with connect() as conn:
        old, pid = _post_text(conn, "post_timer")
        eid = add_signal(conn, "report", *FIRE, iso(at(10)), "web:post:x", "smoke", None, is_sample=True)
        conn.execute("UPDATE posts SET event_id = ? WHERE id = ?", (eid, pid))
        r = notify.handle_inbound(conn, DUTY, "PAGE", at(12), is_sample=True)
        assert r["event_id"] == eid and _decision(conn, eid) == "page"
        assert _decision(conn, old) is None


def test_d9_page_after_text_about_a_closed_event_finds_no_alert():
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(at(0)), "coop:feeder-4", "lockout", is_sample=True)
        conn.execute("DELETE FROM messages WHERE direction = 'out'")
        notify.send(conn, _contact(conn, DUTY), "FIREWATCH x", "duty_fyi", eid, at(1), True)
        conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (eid,))
        r = notify.handle_inbound(conn, DUTY, "PAGE", at(3), is_sample=True)
        assert "no open alert" in r["reply"]
        assert not out(conn, "page")
