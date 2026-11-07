from fastapi.testclient import TestClient

from app.main import app


def test_alert_flow():
    with TestClient(app) as client:
        body = client.get("/api/alerts").json()
        assert body["mode"] == "sample"
        assert body["alerts"], "sample alerts should load on startup"
        assert body["suppressed"]["total"] >= 1
        assert all(a["recommendation"] != "monitor" for a in body["alerts"])

        top = body["alerts"][0]
        assert top["recommendation"] == "escalate"

        detail = client.get(f"/api/alerts/{top['id']}").json()
        assert detail["reasons"] and detail["detections"]

        r = client.post(f"/api/alerts/{top['id']}/actions", json={"action": "acknowledge", "operator": "Dispatch 2"})
        assert r.status_code == 200 and r.json()["status"] == "acknowledged"

        r = client.post(f"/api/alerts/{top['id']}/actions", json={"action": "acknowledge", "operator": "Dispatch 2"})
        assert r.status_code == 400

        sim = client.get(f"/api/alerts/{top['id']}/simulate", params={"wind_kmh": 30, "wind_from_deg": 270}).json()
        assert sim["overridden"] and sim["isochrones"]["features"]


def test_health_in_sample_mode():
    with TestClient(app) as client:
        h = client.get("/api/health").json()
        assert h["mode"] == "sample"
        assert h["sources"]["firms"]["status"] == "sample"


def test_health_lists_every_source_with_interval():
    with TestClient(app) as client:
        h = client.get("/api/health").json()
        for name in ("firms", "nws_alerts", "lsr", "wfigs_incidents", "wfigs_perimeters",
                     "metar", "open_meteo", "spc", "hms", "ngfs"):
            assert name in h["sources"], name
            assert h["sources"][name]["interval_s"] > 0
