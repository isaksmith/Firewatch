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
    return conn.execute("SELECT * FROM messages WHERE direction = 'out' AND purpose = 'duty_fyi'").fetchall()


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
