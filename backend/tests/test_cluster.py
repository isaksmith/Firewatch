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
