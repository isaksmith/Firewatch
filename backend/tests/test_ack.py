from datetime import timedelta

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
