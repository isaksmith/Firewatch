from app.db import connect
from app.pipeline import insert_detections
from app.features.cluster import assign_detection


def _det(lat, lon, t="2025-11-02T19:00:00Z", source="VIIRS_SNPP_NRT", scan=0.4, track=0.4):
    return {
        "source": source, "satellite": source, "lat": lat, "lon": lon, "acq_time": t,
        "frp_mw": 10.0, "confidence": "nominal", "scan_km": scan, "track_km": track, "daynight": "D",
    }


def _events_for(dets):
    with connect() as conn:
        ids = insert_detections(conn, dets)
        return [assign_detection(conn, i) for i in ids]


def test_close_detections_merge():
    events = _events_for([_det(38.80, -99.45), _det(38.809, -99.45)])  # ~1 km apart
    assert events[0] == events[1]


def test_far_detections_stay_separate():
    events = _events_for([_det(38.80, -99.45), _det(38.845, -99.45)])  # ~5 km apart
    assert events[0] != events[1]


def test_coarse_goes_pixel_joins_viirs_event():
    events = _events_for([
        _det(38.80, -99.45),
        _det(38.820, -99.45, t="2025-11-02T19:10:00Z", source="GOES_NRT", scan=2.6, track=2.6),  # ~2.2 km
    ])
    assert events[0] == events[1]


def test_outside_time_window_starts_new_event():
    events = _events_for([_det(38.80, -99.45), _det(38.80, -99.45, t="2025-11-03T12:00:00Z")])
    assert events[0] != events[1]


def _signal_event(conn, lat, lon):
    from app.signals import add_signal
    return add_signal(conn, "report", lat, lon, "2025-11-02T19:00:00Z", "test", is_sample=True)


def test_estimate_attaches_to_nearest_event_and_never_merges():
    from app.signals import add_signal
    with connect() as conn:
        a = _signal_event(conn, 38.80, -99.45)
        b = _signal_event(conn, 38.80 + 10 / 111.2, -99.45)  # 10 km north of a
        assert a != b
        conn.execute("UPDATE events SET response_json = '{\"e\": \"a\"}' WHERE id = ?", (a,))
        conn.execute("UPDATE events SET response_json = '{\"e\": \"b\"}' WHERE id = ?", (b,))
        # estimate 4 km from a, 6 km from b: inside 8 km of both
        got = add_signal(conn, "report", 38.80 + 4 / 111.2, -99.45, "2025-11-02T19:05:00Z", "test",
                         is_sample=True, join_radius_km=8.0)
        rows = {r["id"]: r["response_json"] for r in conn.execute("SELECT id, response_json FROM events")}
    assert got == a
    assert rows == {a: '{"e": "a"}', b: '{"e": "b"}'}


def test_estimate_does_not_attach_to_a_dismissed_event():
    from app.signals import add_signal
    with connect() as conn:
        a = _signal_event(conn, 38.80, -99.45)
        conn.execute("UPDATE events SET status = 'dismissed' WHERE id = ?", (a,))
        got = add_signal(conn, "report", 38.80 + 2 / 111.2, -99.45, "2025-11-02T19:05:00Z", "test",
                         is_sample=True, join_radius_km=8.0)
    assert got != a


# --- merge safety ---
import json

from app.features.cluster import join_or_create

_T = "2025-11-02T19:00:00Z"


def _ev(conn, status="new", resp=None, **cols):
    cur = conn.execute(
        "INSERT INTO events(lat, lon, first_seen, last_seen, is_sample, updated_at, status, response_json) "
        "VALUES (38.8, -99.45, ?, ?, 1, ?, ?, ?)",
        (_T, _T, _T, status, json.dumps(resp) if resp is not None else None),
    )
    for k, v in cols.items():
        conn.execute(f"UPDATE events SET {k} = ? WHERE id = ?", (v, cur.lastrowid))
    return cur.lastrowid


def _row(conn, i):
    return conn.execute("SELECT * FROM events WHERE id = ?", (i,)).fetchone()


def _join(conn, ids):
    return join_or_create(conn, sorted(ids), 38.8, -99.45, _T, 1)


def test_merge_keeps_page_from_higher_id():
    with connect() as conn:
        a = _ev(conn)
        b = _ev(conn, resp={"decision": "page", "page_at": "2025-11-02T19:05:00Z"})
        keep = _join(conn, [a, b])
        r = json.loads(_row(conn, keep)["response_json"])
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert r["decision"] == "page" and r["page_at"] == "2025-11-02T19:05:00Z"


def test_merge_unions_responders_and_asked_without_duplicates():
    with connect() as conn:
        a = _ev(conn, resp={"asked": [1, 2], "responders": [{"contact_id": 1}]})
        b = _ev(conn, resp={"asked": [2, 3], "responders": [{"contact_id": 1}, {"contact_id": 4}]})
        r = json.loads(_row(conn, _join(conn, [a, b]))["response_json"])
    assert sorted(r["asked"]) == [1, 2, 3]
    assert sorted(x["contact_id"] for x in r["responders"]) == [1, 4]


def test_merge_keeps_earliest_escalate_and_investigate():
    with connect() as conn:
        a = _ev(conn, resp={"escalate_at": "2025-11-02T20:00:00Z", "investigate_at": "2025-11-02T19:30:00Z"})
        b = _ev(conn, resp={"escalate_at": "2025-11-02T19:50:00Z", "investigate_at": "2025-11-02T19:40:00Z"})
        r = json.loads(_row(conn, _join(conn, [a, b]))["response_json"])
    assert r["escalate_at"] == "2025-11-02T19:50:00Z" and r["investigate_at"] == "2025-11-02T19:30:00Z"


def test_merge_leaves_response_null_when_neither_had_one():
    with connect() as conn:
        a, b = _ev(conn), _ev(conn)
        keep = _join(conn, [a, b])
        assert _row(conn, keep)["response_json"] is None


def test_merge_keeps_later_ack_with_its_fields():
    with connect() as conn:
        a = _ev(conn, ack_level="chief", ack_by="x", ack_at="2025-11-02T19:01:00Z", ack_until="2025-11-02T20:00:00Z",
                ack_mark_det=1, ack_mark_sig=1)
        b = _ev(conn, ack_level="duty", ack_by="y", ack_at="2025-11-02T19:02:00Z", ack_until="2025-11-02T21:00:00Z",
                ack_mark_det=7, ack_mark_sig=8)
        r = _row(conn, _join(conn, [a, b]))
    assert (r["ack_level"], r["ack_by"], r["ack_until"], r["ack_mark_det"], r["ack_mark_sig"]) == (
        "duty", "y", "2025-11-02T21:00:00Z", 7, 8)


def test_merge_keeps_higher_status():
    with connect() as conn:
        a = _ev(conn, status="new")
        b = _ev(conn, status="escalated")
        assert _row(conn, _join(conn, [a, b]))["status"] == "escalated"


def test_live_event_not_merged_into_dismissed():
    with connect() as conn:
        d = _ev(conn, status="dismissed", resp={"decision": "no"})
        before = tuple(_row(conn, d))
        live = _ev(conn)
        keep = _join(conn, [d, live])
        assert keep == live
        assert tuple(_row(conn, d)) == before


def test_report_next_to_only_dismissed_still_joins_it():
    with connect() as conn:
        d = _signal_event(conn, 38.80, -99.45)
        conn.execute("UPDATE events SET status = 'dismissed' WHERE id = ?", (d,))
        got = _signal_event(conn, 38.80 + 1 / 111.2, -99.45)
    assert got == d


def test_two_live_and_one_dismissed_merge_live_only():
    with connect() as conn:
        d = _ev(conn, status="dismissed")
        a, b = _ev(conn), _ev(conn)
        keep = _join(conn, [d, a, b])
        ids = {r[0] for r in conn.execute("SELECT id FROM events")}
    assert keep == a and ids == {d, a}
