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
