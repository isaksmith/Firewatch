from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from app.pipeline import process_detections

WEATHER = {"wind_kmh": 30, "gust_kmh": 45, "wind_dir_deg": 180, "rh_pct": 20, "temp_c": 20,
           "precip_72h_mm": 0, "thunder_24h": 0, "utc_offset_hours": -5}


def _det(t="2026-03-17T17:30:00Z"):
    return {"source": "VIIRS_NOAA21_NRT", "satellite": "N21", "lat": 38.0002, "lon": -98.5002, "acq_time": t,
            "frp_mw": 14.0, "confidence": "nominal", "brightness_k": 330.0, "scan_km": 0.39, "track_km": 0.39, "daynight": "D"}


BURN = {"lat": 38.0, "lon": -98.5, "start": "2026-03-17T16:00:00Z", "end": "2026-03-17T21:00:00Z",
        "called_in": "2026-03-17T15:40:00Z", "caller": "Henderson", "label": "Henderson pasture burn"}


def _post_and_score(burn, det_time):
    with TestClient(app) as client:
        assert client.post("/api/burns", json=burn).status_code == 201
        with connect() as conn:
            ids = process_detections(conn, [_det(det_time)], is_sample=True, weather=WEATHER)
            ev = conn.execute("SELECT * FROM events WHERE id = ?", (next(iter(ids)),)).fetchone()
            reasons = [r["label"] for r in __import__("json").loads(
                conn.execute("SELECT reasons_json FROM scores WHERE event_id = ?", (ev["id"],)).fetchone()[0])]
    return ev, reasons


def test_detection_inside_burn_window_is_quiet():
    ev, reasons = _post_and_score(BURN, "2026-03-17T17:30:00Z")
    assert ev["recommendation"] == "monitor" and ev["suppression"] == "logged_burn"
    assert "Matches a burn called in to dispatch at 10:40" in reasons


def test_burn_outside_its_window_does_not_suppress():
    # Same place, but the heat is seen at 9:30 local, an hour and a half before the burn was to start.
    ev, reasons = _post_and_score(BURN, "2026-03-17T14:30:00Z")
    assert ev["suppression"] != "logged_burn"
    assert not any(r.startswith("Matches a burn") for r in reasons)


def test_burn_far_away_does_not_suppress():
    ev, _ = _post_and_score({**BURN, "lat": 38.10}, "2026-03-17T17:30:00Z")
    assert ev["suppression"] != "logged_burn"


def test_burn_logged_after_the_detection_rescoring_it():
    with TestClient(app) as client:
        with connect() as conn:
            ids = process_detections(conn, [_det()], is_sample=True, weather=WEATHER)
            event_id = next(iter(ids))
        assert client.post("/api/burns", json=BURN).status_code == 201
        with connect() as conn:
            assert conn.execute("SELECT suppression FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "logged_burn"


def test_burn_validation_and_listing():
    with TestClient(app) as client:
        bad = client.post("/api/burns", json={**BURN, "lat": 120})
        assert bad.status_code == 422
        assert client.post("/api/burns", json={**BURN, "end": BURN["start"]}).status_code == 422
        client.post("/api/burns", json=BURN)
        burns = client.get("/api/burns").json()["burns"]
        assert any(b["caller"] == "Henderson" and b["called_in"] == "2026-03-17T15:40:00Z" for b in burns)


def _escape(dets):
    with TestClient(app) as client:
        client.post("/api/burns", json=BURN)
        with connect() as conn:
            ids = set()
            for d in dets:
                ids |= process_detections(conn, [d], is_sample=True, weather=WEATHER)
            ev = conn.execute("SELECT * FROM events WHERE id = ?", (next(iter(ids)),)).fetchone()
            labels = [r["label"] for r in __import__("json").loads(conn.execute(
                "SELECT reasons_json FROM scores WHERE event_id = ? ORDER BY id DESC LIMIT 1", (ev["id"],)).fetchone()[0])]
    return ev, labels


def _d(t, frp, dlat=0.0):
    return {**_det(t), "lat": 38.0002 + dlat, "frp_mw": frp}


def test_burn_that_is_growing_past_its_hold_escapes():
    ev, labels = _escape([_d("2026-03-17T17:30:00Z", 14), _d("2026-03-17T17:40:00Z", 60), _d("2026-03-17T17:50:00Z", 250)])
    assert ev["suppression"] != "logged_burn" and ev["recommendation"] in ("investigate", "escalate")
    assert "Near a burn called in at 10:40, but growing past it. Call the burner." in labels


def test_burn_that_spreads_past_1_5_km_escapes():
    ev, labels = _escape([_d("2026-03-17T17:30:00Z", 14), _d("2026-03-17T17:35:00Z", 14, dlat=0.0165)])
    assert ev["recommendation"] != "monitor" and any("growing past it" in x for x in labels)


def test_detection_after_the_window_escapes():
    ev, labels = _escape([_d("2026-03-17T17:30:00Z", 14), _d("2026-03-17T21:30:00Z", 14)])
    assert ev["recommendation"] != "monitor" and any("growing past it" in x for x in labels)


def test_modest_growth_inside_the_window_stays_held():
    ev, _ = _escape([_d("2026-03-17T17:30:00Z", 14), _d("2026-03-17T17:40:00Z", 20)])
    assert ev["recommendation"] == "monitor" and ev["suppression"] == "logged_burn"
