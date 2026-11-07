from fastapi.testclient import TestClient

from app import main, scenario
from app.main import app


def _scenario_fire(client, minute: int) -> int:
    scenario.run_now("cottonwood-creek", until=minute)
    return scenario.status("cottonwood-creek")["events"][0]["id"]


def test_scenario_wind_is_the_scenarios_weather_labeled_simulated():
    with TestClient(app) as client:
        eid = _scenario_fire(client, 10)
        w = client.get("/api/wind", params={"event_id": eid}).json()
        assert w["kind"] == "simulated" and w["hours"] == len(w["cells"][0]["wind_kmh"])
        assert {c["from_deg"][0] for c in w["cells"]} == {w["cells"][0]["from_deg"][0]}, "one series, the same everywhere"
        assert 170 <= w["cells"][0]["from_deg"][0] <= 200, "the packet's south wind"


def test_alert_forecast_steps_grow_from_now(monkeypatch):
    monkeypatch.setattr(main, "MAP_MEMBERS", 3)
    main._map_fc.clear()
    with TestClient(app) as client:
        eid = _scenario_fire(client, 10)
        fc = client.get(f"/api/alerts/{eid}/forecast").json()
        steps = fc["steps"]
        assert steps[0]["ahead_min"] == 0 and steps[-1]["ahead_min"] == main.MAP_AHEAD_MIN
        assert fc["now"].startswith("2026-03-17T19:00"), "minute 10 of the replay"
        later = steps[8]  # +2 h
        assert later["likely"]["coordinates"] and later["worst"]["coordinates"]
    main._map_fc.clear()
