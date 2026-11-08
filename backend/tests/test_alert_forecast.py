from fastapi.testclient import TestClient

from app import main, scenario
from app.main import app


def _scenario_fire(client, minute: int) -> int:
    scenario.run_now("cottonwood-creek", until=minute)
    return scenario.status("cottonwood-creek")["events"][0]["id"]


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
        assert later["wind"]["compass"] in ("S", "SSW", "SSE") and later["wind"]["kmh"] > 40, "the packet's south wind"
    main._map_fc.clear()
