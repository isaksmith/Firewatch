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


def test_live_alerts_hide_fixtures_but_keep_scenario_replay(monkeypatch):
    from app import sample, scenario
    from app.config import get_settings
    from app.main import app
    from fastapi.testclient import TestClient

    sample.load_all_now()
    scenario.run_now("cottonwood-creek")
    monkeypatch.setenv("MODE", "sample")
    get_settings.cache_clear()
    with TestClient(app) as client:
        before = client.get("/api/alerts?include_monitor=true&since_hours=1").json()["alerts"]
        slugs = {a["sample_slug"] for a in before}
        assert "cottonwood-creek" in slugs and len(slugs) > 1, "sample mode shows fixtures and scenario"
    monkeypatch.setenv("MODE", "live")
    get_settings.cache_clear()
    with TestClient(app) as client:
        live = client.get("/api/alerts?include_monitor=true&since_hours=1").json()["alerts"]
        assert live and {a["sample_slug"] for a in live} == {"cottonwood-creek"}
