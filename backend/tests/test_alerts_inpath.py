from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.alerts import fanout
from app.alerts.common import scenario
from app.alerts.inpath import in_path
from app.alerts.routes import router
from test_alerts_cap import seed

TZ = timezone(timedelta(hours=-5))
START = datetime(2026, 3, 17, 14, 5, tzinfo=TZ)


def scen_event():
    ig = scenario()["ignition"]
    return {"id": 1, "lat": ig["lat"], "lon": ig["lon"], "first_seen": "2026-03-17T18:50:00Z",
            "features": {"wind_kmh": 35 * 1.609344, "wind_dir_deg": 180, "temp_c": 25.5, "rh_pct": 11, "curing_pct": 95}}


def by_id(now=START):
    return {r["id"]: r for r in in_path(scen_event(), scenario()["places"], now)}


def test_in_path_counts_fire_age_and_marks_reached():
    # fire started at 1:50; at 2:05 the model's head is already past CR 14 and the Miller house
    by = by_id()
    assert by["cr14-at-rdk"]["status"] == "reached" and by["cr14-at-rdk"]["eta_min"] is None
    assert by["cr14-at-rdk"]["reached_local"] == by["cr14-at-rdk"]["arrival_local"]
    # starting the clock at ignition shows the same place as still to come
    early = by_id(datetime(2026, 3, 17, 13, 50, tzinfo=TZ))
    assert early["cr14-at-rdk"]["status"] == "coming" and early["cr14-at-rdk"]["eta_min"] > 0
    assert early["cr14-at-rdk"]["arrival_local"] == by["cr14-at-rdk"]["arrival_local"]


def test_in_path_sorted_and_labelled():
    now = datetime(2026, 3, 17, 13, 55, tzinfo=TZ)
    rows = in_path(scen_event(), scenario()["places"], now)
    etas = [r["eta_min"] for r in rows]
    assert etas == sorted(etas) and rows
    by = {r["id"]: r for r in rows}
    assert by["cr14-at-rdk"]["eta_min"] < by["miller-house"]["eta_min"]
    assert by["miller-house"]["fire_dir_from_place"] == "south"
    assert "dir_from_fire" not in by["miller-house"]
    assert by["miller-house"]["miles_from_fire"] == 3.0
    assert all(r["later"] == (r["eta_min"] > 60) for r in rows)


def test_scenario_arrival_clock_times():
    by = by_id()
    assert by["cr14-at-rdk"]["arrival_local"] == "2:05" and by["miller-house"]["arrival_local"] == "2:15"


def test_far_place_excluded():
    far = [{"id": "x", "label": "far", "kind": "house", "lat": 38.5, "lon": -99.8}]
    assert in_path(scen_event(), far, START) == []


def test_landowner_text_direction():
    from app.alerts import messages
    miller = next(p for p in scenario()['places'] if p['id'] == 'miller-house')
    row = by_id(datetime(2026, 3, 17, 13, 55, tzinfo=TZ))['miller-house']
    assert 'fire 3 mi south of your house' in messages.landowner_text({**miller, **row}, row['eta_local'])


def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_routes(monkeypatch):
    monkeypatch.delenv("FIREWATCH_NOTIFY_LIVE", raising=False)
    seed()
    c = client()
    r = c.get("/api/alerts/1/cap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    ip = c.get("/api/alerts/1/in-path").json()
    assert ip["places"] and ip["start"].startswith("2026-03-17T13:50")
    m = c.get("/api/alerts/1/messages").json()
    assert m["chief"].startswith("FIRE 87/100") and len(m["chief"]) <= 160 and m["landowners"]
    n = c.post("/api/alerts/1/notify", json={"channels": ["push", "sms"]}).json()
    assert n["live"] is False and n["results"]
    assert all(x["status"] == "dry_run" for x in n["results"])
    for path in ("cap.xml", "in-path", "messages"):
        assert c.get(f"/api/alerts/99/{path}").status_code == 404
    assert c.post("/api/alerts/99/notify", json={"channels": ["push"]}).status_code == 404
