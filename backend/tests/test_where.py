from datetime import timedelta

import pytest

from app import notify
from app.db import connect, iso
from app.district import sync_roster
from app.geo import haversine_km
from app.where import Where, parse_where, point_from
from app.db import parse_iso

HERE = (37.77, -96.66)
NOW = parse_iso("2026-03-14T18:50:00Z")


@pytest.mark.parametrize("text,bearing,miles", [
    ("N 5", 0, 5), ("NW 5", 315, 5), ("5 MI NW", 315, 5), ("5 MILES NORTHWEST", 315, 5),
    ("NORTH 5", 0, 5), ("1.5 MI E", 90, 1.5), ("n 5", 0, 5),
    ("south west 3", None, None), ("25 MI W", 270, 25), ("WEST 0.5 MILE", 270, 0.5),
])
def test_accepted_forms(text, bearing, miles):
    w = parse_where(text)
    if bearing is None:
        assert w is None, "split words are not a direction token"
    else:
        assert w == Where(bearing, miles)


@pytest.mark.parametrize("text", [
    "", None, "NEAR THE HOUSE", "NO SMOKE", "N", "NORTH", "5", "5 MI", "26 MI N", "0 N",
    "N 5 E 3", "2 BARNS N", "SNOW 5", "WINDOW 5 N5X",
    "smoke SE 2", "KITTLE'S 5 ACRES", "HWY 160 W 5", "E85", "S 5 ACRES ON FIRE",
])
def test_rejected_forms(text):
    assert parse_where(text) is None


def test_five_miles_north_moves_latitude():
    lat, lon = point_from(*HERE, Where(0, 5))
    assert lat - HERE[0] == pytest.approx(0.0724, abs=0.0002)
    assert lon == pytest.approx(HERE[1])


def test_point_is_the_stated_distance_away():
    for b in (0, 45, 90, 135, 180, 225, 270, 315):
        p = point_from(*HERE, Where(b, 7))
        assert haversine_km(*HERE, *p) == pytest.approx(7 * 1.609344, rel=1e-4)


def _reports(conn):
    return conn.execute("SELECT * FROM signals WHERE kind = 'report' ORDER BY id").fetchall()


def test_report_with_bearing_is_stored_at_the_estimated_point():
    with connect() as conn:
        sync_roster(conn)
        r = notify.handle_inbound(conn, "+13165559999", "FIRE 5 MI N", NOW, at=HERE, is_sample=True)
        sig = _reports(conn)[0]
    assert sig["value"] == "5 MI N", "raw text is kept"
    assert sig["lat"] - HERE[0] == pytest.approx(0.0724, abs=0.0002)
    assert "5 mi N" in r["reply"] and len(r["reply"]) <= notify.SMS_MAX


def test_report_joins_an_event_up_to_8_km_away():
    with connect() as conn:
        sync_roster(conn)
        a = notify.handle_inbound(conn, "+13165559991", "FIRE", NOW, at=HERE, is_sample=True)
        # estimated point 7 km from the first report: beyond the 3 km report radius, inside 8 km
        far = (HERE[0] + 7 / 111.2, HERE[1])
        b = notify.handle_inbound(conn, "+13165559992", "FIRE 5 MI N", NOW, at=(far[0] - 0.0724, far[1]), is_sample=True)
        assert a["event_id"] == b["event_id"]


def test_report_without_bearing_behaves_as_before():
    with connect() as conn:
        sync_roster(conn)
        a = notify.handle_inbound(conn, "+13165559991", "FIRE", NOW, at=HERE, is_sample=True)
        far = (HERE[0] + 7 / 111.2, HERE[1])
        b = notify.handle_inbound(conn, "+13165559992", "FIRE smoke near the house", NOW, at=far, is_sample=True)
        sig = _reports(conn)[1]
    assert (sig["lat"], sig["lon"]) == far
    assert a["event_id"] != b["event_id"], "7 km apart stays two events without a bearing"
    assert b["reply"] == "Firewatch: report received. The duty officer is being told."


def _fyi(conn):
    return conn.execute("SELECT * FROM messages WHERE direction = 'out' AND purpose = 'duty_fyi_outside'").fetchall()


def test_report_outside_the_district_goes_to_the_duty_officer_directly():
    far = (45.0, -90.0)  # well outside the district
    with connect() as conn:
        sync_roster(conn)
        r = notify.handle_inbound(conn, "+13165559992", "FIRE 5 MI N", NOW, at=far, is_sample=True)
        fyi = _fyi(conn)
    assert len(fyi) == 1
    body = fyi[0]["body"]
    assert "FIRE 5 MI N" in body and "45.0000" in body and len(body) <= notify.SMS_MAX
    assert "duty officer is being told" in r["reply"] and len(r["reply"]) <= notify.SMS_MAX


def test_outside_report_reply_is_honest_when_nobody_can_be_told():
    far = (45.0, -90.0)
    with connect() as conn:
        sync_roster(conn)
        conn.execute("UPDATE contacts SET ladder_rank = NULL")
        r = notify.handle_inbound(conn, "+13165559992", "FIRE 5 MI N", NOW, at=far, is_sample=True)
        assert _fyi(conn) == []
    assert "being told" not in r["reply"] and "911" in r["reply"] and len(r["reply"]) <= notify.SMS_MAX


FAR = (45.0, -90.0)


def _outside(conn):
    return _fyi(conn)


def _duty(conn):
    return notify._ladder(conn)[0]


def test_outside_fyi_is_never_a_decision_target():
    with connect() as conn:
        sync_roster(conn)
        duty = _duty(conn)
        inside = notify.handle_inbound(conn, "+13165559991", "FIRE", NOW, at=HERE, is_sample=True)["event_id"]
        notify.send(conn, duty, "alert", "duty_escalate", inside, NOW, True)
        notify.handle_inbound(conn, "+13165559992", "FIRE 5 MI N", NOW, at=FAR, is_sample=True)
        r = notify.handle_inbound(conn, duty["phone"], "PAGE", NOW, is_sample=True)
        assert r["event_id"] == inside
        assert _outside(conn) and all(m["event_id"] is None for m in _outside(conn))


class _FailingGateway:
    name = "fail"

    def send(self, to, body):
        raise notify.httpx.ConnectError("down")


EARLIER = "Firewatch: your earlier report already went to the duty officer. Call 911 if anyone is in danger."


def test_outside_report_never_makes_the_event_a_page_target():
    with connect() as conn:
        sync_roster(conn)
        r = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        eid = r["event_id"]
        ladder = notify._ladder(conn)
        member = ladder[1]
        assert not conn.execute("SELECT 1 FROM messages WHERE contact_id = ? AND purpose IN ('duty_fyi','duty_escalate','ladder','mutual_aid_draft')", (member["id"],)).fetchone()
        out = notify.handle_inbound(conn, member["phone"], "PAGE", NOW, is_sample=True)
        assert out["event_id"] != eid and out["action"] == "help"
        assert conn.execute("SELECT response_json FROM events WHERE id = ?", (eid,)).fetchone()["response_json"] is None


def test_same_sender_inside_an_hour_gets_one_fyi_and_an_honest_reply():
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        b = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW + timedelta(minutes=59), at=FAR, is_sample=True)
        assert len(_outside(conn)) == 1
    assert b["reply"] == EARLIER and len(b["reply"]) <= notify.SMS_MAX


def test_same_sender_after_an_hour_gets_a_second_fyi():
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        b = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW + timedelta(minutes=61), at=FAR, is_sample=True)
        assert len(_outside(conn)) == 2
    assert "being told" in b["reply"]


def test_different_senders_on_one_event_each_get_through():
    with connect() as conn:
        sync_roster(conn)
        a = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        b = notify.handle_inbound(conn, "+13165559993", "FIRE", NOW, at=FAR, is_sample=True)
        assert a["event_id"] == b["event_id"]
        assert len(_outside(conn)) == 2
    assert "being told" in b["reply"]


def test_failed_send_does_not_count_so_a_repeat_retries(monkeypatch):
    with connect() as conn:
        sync_roster(conn)
        monkeypatch.setattr(notify, "gateway_for", lambda s: _FailingGateway())
        notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        monkeypatch.undo()
        b = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW + timedelta(minutes=1), at=FAR, is_sample=True)
        sent = [m for m in _outside(conn) if m["status"] == "sent"]
    assert len(sent) == 1 and "being told" in b["reply"]


def test_a_tag_quoted_in_another_senders_body_does_not_suppress_their_fyi():
    # The dedupe key used to match anywhere in the body, so this text silenced the victim for an hour.
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, "+13165559993", "FIRE from +13165559992 at home", NOW, at=FAR, is_sample=True)
        b = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW + timedelta(minutes=1), at=FAR, is_sample=True)
        assert len(_outside(conn)) == 2
    assert "being told" in b["reply"]


def test_a_delivered_mesh_fyi_still_counts_for_the_dedupe():
    # mesh._ack rewrites status, so a status = 'sent' match let acked FYIs drop out of the cap.
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        conn.execute("UPDATE messages SET channel = 'mesh', status = 'delivered' WHERE purpose = 'duty_fyi_outside'")
        b = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW + timedelta(minutes=1), at=FAR, is_sample=True)
        assert len(_outside(conn)) == 1
    assert b["reply"] == EARLIER


def test_a_relayed_mesh_fyi_does_not_suppress_a_retry():
    # relayed means another radio rebroadcast it, so "already went to the duty officer" would be untrue.
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        conn.execute("UPDATE messages SET channel = 'mesh', status = 'relayed' WHERE purpose = 'duty_fyi_outside'")
        b = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW + timedelta(minutes=1), at=FAR, is_sample=True)
        assert len(_outside(conn)) == 2
    assert "being told" in b["reply"]


def test_an_unacked_mesh_fyi_does_not_suppress_a_retry():
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        conn.execute("UPDATE messages SET channel = 'mesh' WHERE purpose = 'duty_fyi_outside'")
        b = notify.handle_inbound(conn, "+13165559992", "FIRE", NOW + timedelta(minutes=1), at=FAR, is_sample=True)
        assert len(_outside(conn)) == 2
    assert "being told" in b["reply"]


def test_fyi_follows_the_event_position_not_the_report_point():
    # A report just outside the boundary that joins an in-district event: no FYI.
    with connect() as conn:
        sync_roster(conn)
        d = notify.load_district()
        a = notify.handle_inbound(conn, "+13165559991", "FIRE", NOW, at=HERE, is_sample=True)
        ev = notify._event(conn, a["event_id"])
        assert d.contains(ev["lat"], ev["lon"])
        notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=HERE, is_sample=True)
        assert _outside(conn) == []
    with connect() as conn:
        sync_roster(conn)
        b = notify.handle_inbound(conn, "+13165559993", "FIRE", NOW, at=FAR, is_sample=True)
        assert not notify.load_district().contains(*FAR)
        assert len(_outside(conn)) == 1 and b["event_id"]


def test_fyi_skips_events_whose_averaged_position_is_inside(monkeypatch):
    with connect() as conn:
        sync_roster(conn)
        a = notify.handle_inbound(conn, "+13165559991", "FIRE", NOW, at=HERE, is_sample=True)
        # report point outside, but the event it joined sits inside
        monkeypatch.setattr("app.signals.add_signal", lambda *a_, **k: a["event_id"])
        notify.handle_inbound(conn, "+13165559992", "FIRE", NOW, at=FAR, is_sample=True)
        assert _outside(conn) == []


def test_outside_reply_is_honest_when_every_send_fails(monkeypatch):
    monkeypatch.setattr(notify, "gateway_for", lambda s: _FailingGateway())
    with connect() as conn:
        sync_roster(conn)
        r = notify.handle_inbound(conn, "+13165559992", "FIRE 5 MI N", NOW, at=FAR, is_sample=True)
    assert "being told" not in r["reply"] and "911" in r["reply"]


def test_outside_fyi_falls_through_to_next_ladder_contact(monkeypatch):
    with connect() as conn:
        sync_roster(conn)
        ladder = notify._ladder(conn)
        assert len(ladder) > 1
        conn.execute("UPDATE contacts SET opted_in = 0 WHERE id = ?", (ladder[0]["id"],))
        r = notify.handle_inbound(conn, "+13165559992", "FIRE 5 MI N", NOW, at=FAR, is_sample=True)
        rows = _outside(conn)
    assert len(rows) == 1 and rows[0]["contact_id"] == ladder[1]["id"]
    assert "being told" in r["reply"]
