import json
from datetime import timedelta

import pytest

from fastapi.testclient import TestClient

from app import notify, scenario
from app.confirm import evaluate_event
from app.db import connect, iso, loads, parse_iso
from app.district import load_district, sync_roster
from app.geo import haversine_km
from app.main import app
from app.signals import add_signal

T0 = parse_iso("2026-03-14T18:50:00Z")
FIRE = (37.3821, -99.4681)
WEATHER = {"wind_kmh": 26, "gust_kmh": 45, "wind_dir_deg": 200, "rh_pct": 18, "temp_c": 24, "precip_72h_mm": 0, "thunder_24h": 0}
CALM = {**WEATHER, "wind_kmh": 8, "rh_pct": 45}
BLOWING = {**WEATHER, "wind_kmh": 45}
DUTY, CHIEF, WES, GARY = "+13165550101", "+13165550102", "+13165550131", "+13165550135"


def _at(minutes: float):
    return T0 + timedelta(minutes=minutes)


def _line_fault(conn, weather=WEATHER, at=0, value="lockout", where=FIRE) -> int:
    eid = add_signal(conn, "line_fault", *where, iso(_at(at)), "coop:feeder-4", value, is_sample=True)
    evaluate_event(conn, eid, weather, _at(at))
    return eid


def _out(conn, purpose: str, event_id: int | None = None) -> list:
    q, args = "SELECT * FROM messages WHERE direction = 'out' AND purpose = ?", [purpose]
    if event_id is not None:
        q += " AND event_id = ?"
        args.append(event_id)
    return conn.execute(q, args).fetchall()


def _event(conn, eid: int):
    return conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()


def test_scenario_beats_baseline():
    scenario.run_now("cottonwood-creek")
    st = scenario.status("cottonwood-creek")
    fw = {m["key"]: m["t"] for m in st["firewatch"]}
    assert fw["signal"] == 0 and fw["investigate"] == 0
    assert fw["escalate"] == 8 and fw["page"] == 9
    assert fw["on_scene"] == 38 and fw["mutual_aid"] == 12  # page 9 + packet turnout 11 + drive 18
    assert st["weather"]["gfdi_band"] == "Extreme"
    assert st["size_on_scene"]["firewatch"]["acres"] < st["size_on_scene"]["baseline"]["acres"] / 2

    (fire,) = st["events"]  # the packet's pasture burns were over the weekend; the replay has only the fire
    assert fire["recommendation"] == "escalate"

    with connect() as conn:
        assert len(_out(conn, "ask_neighbor", fire["id"])) == 3
        assert len(_out(conn, "page", fire["id"])) == 18
        downwind = [m["body"] for m in _out(conn, "downwind", fire["id"])]
        assert downwind and all("Could reach you in as little as " in b for b in downwind)
        assert len(_out(conn, "mutual_aid", fire["id"])) == 1
        assert not _out(conn, "ladder"), "the duty officer answered, so the ladder never moved"


def test_line_fault_alone_investigates_and_asks_nearest_neighbors():
    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn)
        ev = _event(conn, eid)
        assert ev["recommendation"] == "investigate" and ev["score"] is None
        asked = [m["contact_id"] for m in _out(conn, "ask_neighbor", eid)]
        assert len(asked) == 3
        names = [conn.execute("SELECT name FROM contacts WHERE id = ?", (c,)).fetchone()["name"] for c in asked]
        assert names[0] == "Wes Kittle", "nearest first"
        assert len(_out(conn, "duty_fyi", eid)) == 1
        assert not _out(conn, "page")


def test_line_fault_on_a_low_danger_day_does_not_count():
    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn, weather=CALM)
        ev = _event(conn, eid)
        assert ev["recommendation"] == "monitor"
        assert "not counted" in ev["level_reason"]
        assert not conn.execute("SELECT 1 FROM messages").fetchone()


def test_momentary_trip_does_not_count():
    with connect() as conn:
        sync_roster(conn)
        assert _event(conn, _line_fault(conn, value="momentary"))["recommendation"] == "monitor"


def test_unregistered_reports_stop_at_investigate():
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "report", *FIRE, iso(_at(0)), "sms:+13165559991", "smoke", is_sample=True)
        add_signal(conn, "report", 37.3831, -99.4691, iso(_at(1)), "sms:+13165559992", "fire", is_sample=True)
        evaluate_event(conn, eid, WEATHER, _at(1))
        assert _event(conn, eid)["recommendation"] == "investigate"


def test_neighbor_smoke_confirms_and_page_reaches_dispatch():
    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn)
        r = notify.handle_inbound(conn, WES, "1", _at(8), is_sample=True)
        assert r["action"] == "neighbor_reply" and r["event_id"] == eid
        assert _event(conn, eid)["recommendation"] == "escalate"
        assert len(_out(conn, "duty_escalate", eid)) == 1

        r = notify.handle_inbound(conn, DUTY, "page", _at(9), is_sample=True)
        assert r["action"] == "page"
        state = loads(_event(conn, eid)["response_json"])
        assert state["decision"] == "page" and state["page_at"] == iso(_at(9))
        assert len(_out(conn, "page_dispatch", eid)) == 1
        assert _event(conn, eid)["status"] == "escalated"


def test_no_answer_ladder_reaches_chief_then_dispatch():
    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn)
        notify.handle_inbound(conn, WES, "1", _at(8), is_sample=True)
        notify.tick(conn, _at(10.9), is_sample=True)
        assert not _out(conn, "ladder", eid)
        notify.tick(conn, _at(11), is_sample=True)
        assert len(_out(conn, "ladder", eid)) == 1
        notify.tick(conn, _at(16.9), is_sample=True)
        assert not _out(conn, "ladder_dispatch", eid)
        notify.tick(conn, _at(17), is_sample=True)
        assert len(_out(conn, "ladder_dispatch", eid)) == 1
        notify.tick(conn, _at(60), is_sample=True)
        assert len(_out(conn, "ladder_dispatch", eid)) == 1, "dispatch is the last rung"


def test_chief_can_stand_down():
    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn)
        notify.handle_inbound(conn, WES, "1", _at(8), is_sample=True)
        notify.handle_inbound(conn, CHIEF, "NO", _at(9), is_sample=True)
        ev = _event(conn, eid)
        assert ev["status"] == "dismissed"
        notify.tick(conn, _at(30), is_sample=True)
        assert not _out(conn, "ladder", eid) and not _out(conn, "page", eid)


def test_mutual_aid_drafted_when_too_few_respond():
    with connect() as conn:
        sync_roster(conn)
        conn.execute("UPDATE contacts SET opted_in = 0 WHERE role IN ('rancher', 'pumper', 'water_truck', 'disc')")
        eid = _line_fault(conn, weather=CALM)  # monitor; force a page by hand
        notify.on_level(conn, eid, "escalate", _at(1))
        state = notify.decide(conn, eid, "page", "Lt. Ana Reyes", _at(2))
        assert "mutual_aid" not in state, "a calm-day fire stays under the 60-minute capacity"
        notify.tick(conn, _at(6.9), is_sample=True)
        assert not _out(conn, "mutual_aid_draft", eid)
        notify.tick(conn, _at(7), is_sample=True)
        assert len(_out(conn, "mutual_aid_draft", eid)) == 1


def test_registered_burn_stays_quiet_until_it_escapes():
    burn = (37.3621, -99.3537)
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, GARY, "BURN", _at(-200), is_sample=True)
        eid = _line_fault(conn, where=burn)
        assert _event(conn, eid)["suppression"] == "registered_burn"
        assert not _out(conn, "duty_fyi")
        add_signal(conn, "report", *burn, iso(_at(5)), "sms:+13165559991", "fire spreading", is_sample=True)
        evaluate_event(conn, eid, WEATHER, _at(5))
        ev = _event(conn, eid)
        assert ev["recommendation"] != "monitor"
        assert any("escaped" in e.get("note", "") for e in loads(ev["evidence_json"]))


EXTREME = {**WEATHER, "wind_kmh": 56, "gust_kmh": 90, "rh_pct": 11}
BURN = (37.3621, -99.3537)


def _gary(conn):
    return conn.execute("SELECT id FROM contacts WHERE phone = ?", (GARY,)).fetchone()["id"]


def test_extreme_day_burn_without_escape_evidence_investigates_with_one_fyi_never_escalates():
    # Root cause of the packet bug: fire danger alone (GFDI >= 25) used to mark every burn escaped.
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, GARY, "BURN", _at(-200), is_sample=True)
        eid = _line_fault(conn, weather=EXTREME, where=BURN)
        ev = _event(conn, eid)
        assert ev["recommendation"] == "investigate"
        assert not any("escaped" in e.get("note", "") for e in loads(ev["evidence_json"]))
        assert len(_out(conn, "duty_fyi", eid)) == 1
        assert not _out(conn, "duty_escalate", eid)
        evaluate_event(conn, eid, EXTREME, _at(4))
        ev = _event(conn, eid)
        assert ev["recommendation"] != "escalate"
        assert not any("escaped" in e.get("note", "") for e in loads(ev["evidence_json"]))
        assert len(_out(conn, "duty_fyi", eid)) == 1


def test_normal_day_burn_stays_monitor():
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, GARY, "BURN", _at(-200), is_sample=True)
        eid = _line_fault(conn, weather=CALM, where=BURN)
        ev = _event(conn, eid)
        assert ev["suppression"] == "registered_burn" and ev["recommendation"] == "monitor"
        assert not _out(conn, "duty_fyi")


def test_burners_own_fire_report_escapes():
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, GARY, "BURN", _at(-200), is_sample=True)
        eid = _line_fault(conn, weather=CALM, where=BURN)
        assert _event(conn, eid)["recommendation"] == "monitor"
        notify.handle_inbound(conn, GARY, "FIRE", _at(5), is_sample=True)
        ev = _event(conn, eid)
        assert ev["recommendation"] != "monitor"
        assert any("escaped" in e.get("note", "") for e in loads(ev["evidence_json"]))
        assert ev["recommendation"] == "investigate"
        assert len(_out(conn, "duty_fyi", eid)) == 1


def test_neighbor_one_from_someone_else_escapes_the_burn():
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, GARY, "BURN", _at(-200), is_sample=True)
        eid = _line_fault(conn, weather=EXTREME, where=BURN)
        wes = conn.execute("SELECT id FROM contacts WHERE phone = ?", (WES,)).fetchone()["id"]
        conn.execute(  # Wes was asked about this event (the nearest-first ask only reached Gary)
            "INSERT INTO messages(event_id, contact_id, phone, direction, purpose, body, status, is_sample, created_at) "
            "VALUES (?, ?, ?, 'out', 'ask_neighbor', 'ask', 'sent', 1, ?)", (eid, wes, WES, iso(_at(1))))
        notify.handle_inbound(conn, WES, "1", _at(6), is_sample=True)
        ev = _event(conn, eid)
        assert any("neighbor sees smoke" in e.get("note", "") for e in loads(ev["evidence_json"]))
        assert ev["suppression"] != "registered_burn"


def test_late_burn_notice_cannot_suppress_an_event():
    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn, where=BURN)
        assert _event(conn, eid)["recommendation"] == "investigate"
        notify.handle_inbound(conn, GARY, "BURN", _at(10), is_sample=True)
        evaluate_event(conn, eid, WEATHER, _at(11))
        ev = _event(conn, eid)
        assert ev["recommendation"] != "monitor" and ev["suppression"] != "registered_burn"


def test_burn_that_left_its_notice_escalates_on_an_extreme_day():
    extreme = {**WEATHER, "wind_kmh": 56, "gust_kmh": 90, "rh_pct": 11}
    burn = (37.3621, -99.3537)
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, GARY, "BURN", _at(-200), is_sample=True)
        eid = _line_fault(conn, weather=extreme, where=burn)
        gary = conn.execute("SELECT id FROM contacts WHERE phone = ?", (GARY,)).fetchone()["id"]
        # The burner's own report 2.7 km out, past the 1.5 km notice plus 1 km: the "outside the notice" path alone.
        add_signal(conn, "report", 37.3866, -99.3537, iso(_at(3)), f"sms:{GARY}", "fire", contact_id=gary, is_sample=True)
        evaluate_event(conn, eid, extreme, _at(3))
        ev = _event(conn, eid)
        assert ev["recommendation"] != "monitor"
        assert any("escaped" in e.get("note", "") for e in loads(ev["evidence_json"]))


def test_stop_and_start():
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, WES, "STOP", _at(0), is_sample=True)
        eid = _line_fault(conn)
        asked = {m["phone"] for m in _out(conn, "ask_neighbor", eid)}
        assert WES not in asked
        notify.handle_inbound(conn, WES, "start", _at(1), is_sample=True)
        assert conn.execute("SELECT opted_in FROM contacts WHERE phone = ?", (WES,)).fetchone()["opted_in"] == 1
        sync_roster(conn)
        notify.handle_inbound(conn, WES, "STOP", _at(2), is_sample=True)
        sync_roster(conn)
        assert conn.execute("SELECT opted_in FROM contacts WHERE phone = ?", (WES,)).fetchone()["opted_in"] == 0, \
            "a roster re-sync must not undo an opt-out"


def test_templates_fit_one_sms():
    d = load_district()
    ev = {"id": 12345, "lat": 37.123456, "lon": -100.123456, "place_label": "18 mi WSW of Medicine Lodge, Barber Co."}
    far = {"lat": 37.3, "lon": -100.4, "role": "water_truck"}
    plan = {"wind": {"from": "WSW", "mph": 45}, "acres_60": 12340}
    why = notify._why({"level_reason": "Escalate: satellite detection + power line lockout + Wes Kittle sees smoke"})
    assert len(why) <= notify.WHY_MAX
    bodies = [
        notify.t_duty_fyi(ev, why, 3),
        notify.t_ask_neighbor(ev, far, d.short_name),
        notify.t_duty_escalate(ev, why, "No answer from duty officer. "),
        notify.t_dispatch_ladder(ev, why),
        notify.t_page(ev, plan),
        notify.t_page_dispatch(ev, d.short_name, "Chief Dan Moser"),
        notify.t_downwind(ev, far, 55, d.short_name),
        notify.t_helper(ev, far, d.short_name),
        notify.t_mutual_aid_draft("~12340 ac in 1 hr, over the 371 ac 2 trucks can hold", d.neighbor_district),
        notify.t_mutual_aid(ev, d.short_name, plan, 12),
    ]
    too_long = [(len(b), b) for b in bodies if len(b) > notify.SMS_MAX]
    assert not too_long


def test_twilio_signature():
    params = {"From": "+13165550131", "Body": "1"}
    url = "https://firewatch.example/api/sms/inbound"
    import base64
    import hashlib
    import hmac

    good = base64.b64encode(hmac.new(b"secret", (url + "Body1From+13165550131").encode(), hashlib.sha1).digest()).decode()
    assert notify.valid_twilio_signature("secret", url, params, good)
    assert not notify.valid_twilio_signature("secret", url, {**params, "Body": "PAGE"}, good)
    assert not notify.valid_twilio_signature("secret", url, params, "")


def test_scenario_and_decision_api():
    with TestClient(app) as client:
        st = client.post("/api/scenario/cottonwood-creek/load").json()
        fire = st["events"][0]
        detail = client.get(f"/api/alerts/{fire['id']}").json()
        assert detail["evidence"] and detail["messages"] and detail["response"]["decision"] == "page"
        assert all(m["phone"].startswith("…") for m in detail["messages"])

        alerts = client.get("/api/alerts").json()
        listed = {a["id"]: a for a in alerts["alerts"]}
        assert listed[fire["id"]]["recommendation"] == "escalate"
        assert listed[fire["id"]]["response"]["texts_sent"] > 20

        r = client.post(f"/api/alerts/{fire['id']}/decision", json={"action": "send", "operator": "Console"})
        assert r.status_code == 200
        assert client.get("/api/scenario/nope").status_code == 404
        assert client.get("/api/scenario/..%2Fsamples%2Fx").status_code == 404

        r = client.post("/api/sms/simulate", json={"from": "+13165559999", "body": "hello"})
        assert r.status_code == 200 and "FIRE" in r.json()["reply"]
        assert client.get("/api/district").json()["settings"]["capacity_ha_60min"] == 150


def _first_out_minute(conn, slug: str, purpose: str, t0: str):
    row = conn.execute(
        "SELECT MIN(m.created_at) AS t FROM messages m JOIN events e ON e.id = m.event_id "
        "WHERE e.sample_slug = ? AND m.direction = 'out' AND m.purpose = ?",
        (slug, purpose),
    ).fetchone()
    return None if row["t"] is None else round((parse_iso(row["t"]) - parse_iso(t0)).total_seconds() / 60)


@pytest.mark.parametrize(
    "slug,fyi,escalate,dispatch",
    [("cottonwood-creek-packet", None, 0, 9), ("cottonwood-creek-packet-no-fault", 31, 38, 47), ("cottonwood-creek-packet-ngfs", 19, 38, 47)],
)
def test_packet_scenarios_report_the_worse_number(slug, fyi, escalate, dispatch):
    # Measured, not tuned. With the line fault on a Red Flag day Firewatch escalates at minute 0 (no FYI
    # first, and no FYI at all now that the same-day registered burn is gone from the packet replays); the no-fault packet has no fault to lean on and escalates at 38. Neither asks to page.
    t0 = "2026-03-17T18:50:00Z"
    scenario.run_now(slug)
    with connect() as conn:
        assert _first_out_minute(conn, slug, "duty_fyi", t0) == fyi
        assert _first_out_minute(conn, slug, "duty_escalate", t0) == escalate
        assert _first_out_minute(conn, slug, "ladder_dispatch", t0) == dispatch
    fw = {m["key"]: m["t"] for m in scenario.status(slug)["firewatch"]}
    assert fw["escalate"] == escalate and fw["page"] is None


def test_a_second_replay_in_the_same_db_keeps_its_own_timeline():
    # The packet replays share a place and a clock: a leftover open event used to swallow the next replay's signals.
    t0 = "2026-03-17T18:50:00Z"
    scenario.run_now("cottonwood-creek-packet-no-fault")
    scenario.run_now("cottonwood-creek-packet-ngfs")
    with connect() as conn:
        assert _first_out_minute(conn, "cottonwood-creek-packet-ngfs", "duty_fyi", t0) == 19
    assert scenario.status("cottonwood-creek-packet-no-fault")["events"] == []
    assert {m["key"]: m["t"] for m in scenario.status("cottonwood-creek-packet-ngfs")["firewatch"]}["investigate"] == 19


@pytest.mark.parametrize("slug", ["cottonwood-creek-packet", "cottonwood-creek-packet-no-fault", "cottonwood-creek-packet-ngfs"])
def test_packet_replays_match_the_packet(slug):
    sc = scenario.load_scenario(slug)
    ig = sc["ignition"]
    with connect() as conn:
        sync_roster(conn, sc["district"])
        located = conn.execute("SELECT lat, lon FROM contacts WHERE lat IS NOT NULL").fetchall()
    assert located and min(haversine_km(ig["lat"], ig["lon"], c["lat"], c["lon"]) for c in located) >= 4 * 1.609344
    reports = [s for s in sc["timeline"] if s.get("kind") == "report"]
    assert [s["t"] for s in reports] == [31]  # the driver sees smoke at 27 but has no signal until 31


# --- line fault on a Red Flag day -----------------------------------------------------------------------

def _nws(conn, fetched_min=0, onset_min=-60, expires_min=600, geometry="box", event="Red Flag Warning"):
    box = {"type": "Polygon", "coordinates": [[[-99.81, 37.11], [-99.11, 37.11], [-99.11, 37.61], [-99.81, 37.61], [-99.81, 37.11]]]}
    alert = {"id": "x", "event": event, "onset": iso(_at(onset_min)), "expires": iso(_at(expires_min)),
             "geometry": box if geometry == "box" else geometry}
    conn.execute(
        "INSERT OR REPLACE INTO feed_snapshots(source, fetched_at, payload) VALUES ('nws_alerts', ?, ?)",
        (iso(_at(fetched_min)), json.dumps({"count": 1, "alerts": [alert]})),
    )


def _fault_level(**nws):
    with connect() as conn:
        sync_roster(conn)
        if nws is not None:
            _nws(conn, **nws)
        eid = add_signal(conn, "line_fault", *FIRE, iso(_at(0)), "coop:feeder-4", "lockout", is_sample=True)
        # No red_flag passed: the live path reads the stored NWS feed.
        return evaluate_event(conn, eid, WEATHER, _at(0))


def test_line_fault_on_a_red_flag_day_escalates_alone():
    out = _fault_level()
    assert out["level"] == "escalate" and "Line fault on a Red Flag day" in out["reason"]


def test_line_fault_without_a_warning_stays_at_investigate():
    with connect() as conn:
        sync_roster(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(_at(0)), "coop:feeder-4", "lockout", is_sample=True)
        assert evaluate_event(conn, eid, WEATHER, _at(0))["level"] == "investigate"


@pytest.mark.parametrize(
    "nws",
    [
        {"event": "Wind Advisory"},
        {"expires_min": -5},
        {"onset_min": 30},
        {"geometry": {"type": "Polygon", "coordinates": [[[-99, 37], [-98, 37], [-98, 38], [-99, 38], [-99, 37]]]}},
    ],
)
def test_other_nws_alerts_and_expired_or_distant_warnings_do_not_count(nws):
    # One case per test: repeated lockouts in one event compound P(fire) and the stakes rule would escalate.
    assert _fault_level(**nws)["level"] == "investigate"


def test_stale_or_geometry_less_nws_feed_does_not_count():
    assert _fault_level(fetched_min=-30)["level"] == "investigate"  # 30 min old, polled every minute
    assert _fault_level(geometry=None)["level"] == "investigate"


def test_momentary_trip_on_a_red_flag_day_does_not_escalate():
    with connect() as conn:
        sync_roster(conn)
        _nws(conn)
        eid = add_signal(conn, "line_fault", *FIRE, iso(_at(0)), "coop:feeder-4", "momentary", is_sample=True)
        assert evaluate_event(conn, eid, WEATHER, _at(0))["level"] != "escalate"


# --- NGFS as a confirmation signal ----------------------------------------------------------------------

from app.ngfs_signal import add_ngfs_signals, qualifying  # noqa: E402


def _pt(tid="f1", scan=0, label="Possible Wildland Fire", where=FIRE):
    return {"feature_tracking_id": tid, "type_description": label, "lat": where[0], "lon": where[1],
            "acq_date_time": iso(_at(scan))}


def _ngfs(conn, points, now=10, where=FIRE):
    eids = add_ngfs_signals(conn, points, _at(now), is_sample=True)
    for e in eids:
        evaluate_event(conn, e, CALM, _at(now))
    return eids


def test_ngfs_needs_the_wildland_label():
    assert qualifying([_pt(scan=0), _pt(scan=5)])
    assert not qualifying([_pt(label="Possible Industrial", scan=0), _pt(label="Possible Industrial", scan=5)])
    assert not qualifying([_pt(label=None, scan=0), _pt(label=None, scan=5)])
    bare = [_pt(scan=0), _pt(scan=5)]
    for p in bare:
        del p["type_description"]
    assert not qualifying(bare)


def test_ngfs_needs_two_separate_scans():
    assert not qualifying([_pt(scan=0)])
    assert not qualifying([_pt(scan=0), _pt(scan=0)])
    assert qualifying([_pt(scan=0), _pt(scan=5)])[0]["scans"] == 2


def test_ngfs_inside_a_registered_burn_adds_no_signal():
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, GARY, "BURN", _at(-200), is_sample=True)
        assert add_ngfs_signals(conn, [_pt(scan=0, where=BURN), _pt(scan=5, where=BURN)], _at(10), is_sample=True) == []
        assert conn.execute("SELECT COUNT(*) FROM signals WHERE kind = 'ngfs'").fetchone()[0] == 0


def test_ngfs_adds_one_signal_per_feature_across_repeated_polls():
    with connect() as conn:
        sync_roster(conn)
        pts = [_pt(scan=0), _pt(scan=5)]
        assert len(_ngfs(conn, pts)) == 1
        assert _ngfs(conn, pts) == []
        assert _ngfs(conn, pts + [_pt(scan=10)], now=15) == []
        assert conn.execute("SELECT COUNT(*) FROM signals WHERE kind = 'ngfs'").fetchone()[0] == 1


def test_ngfs_alone_investigates_with_a_beta_label_and_never_escalates():
    with connect() as conn:
        sync_roster(conn)
        eid = _ngfs(conn, [_pt(scan=0), _pt(scan=5)])[0]
        ev = _event(conn, eid)
        assert ev["recommendation"] == "investigate"
        assert any("NOAA beta" in e["label"] for e in loads(ev["evidence_json"]))
        assert len(_out(conn, "duty_fyi", eid)) == 1
        assert "unconfirmed" in _out(conn, "duty_fyi", eid)[0]["body"].lower()


def test_ngfs_and_a_satellite_pass_are_one_source_class():
    with connect() as conn:
        sync_roster(conn)
        eid = _ngfs(conn, [_pt(scan=0), _pt(scan=5)])[0]
        assert _event(conn, eid)["recommendation"] == "investigate"
        ev = loads(_event(conn, eid)["evidence_json"])
        assert sum(1 for e in ev if e["label"].startswith("Unconfirmed NOAA")) == 1


def test_ngfs_plus_a_line_fault_escalates():
    with connect() as conn:
        sync_roster(conn)
        eid = _ngfs(conn, [_pt(scan=0), _pt(scan=5)])[0]
        add_signal(conn, "line_fault", *FIRE, iso(_at(11)), "coop:feeder-4", "lockout", is_sample=True)
        assert evaluate_event(conn, eid, WEATHER, _at(11))["level"] == "escalate"
