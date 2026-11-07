import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import connect, save_snapshot
from app.ingest import hms, lsr, metar, nws, spc, wfigs
from app.main import app


def test_nws_empty_and_nonempty():
    assert nws.parse({"features": []}) == {"count": 0, "alerts": []}
    p = {"features": [
        {"properties": {"event": "Red Flag Warning", "id": "a", "areaDesc": "X"}, "geometry": None},
        {"properties": {"event": "Winter Storm Watch"}, "geometry": None}]}
    out = nws.parse(p)
    assert out["count"] == 1 and out["alerts"][0]["event"] == "Red Flag Warning"


def test_spc_no_areas_dropped():
    p = {"features": [{"properties": {"LABEL": "No Areas"}, "geometry": None}]}
    assert spc.parse("day1", p) == []
    sq = {"type": "Polygon", "coordinates": [[[-99, 38], [-98, 38], [-98, 39], [-99, 39], [-99, 38]]]}
    out = spc.parse("day1", {"features": [{"properties": {"LABEL": "ELEV"}, "geometry": sq}]})
    assert len(out) == 1 and out[0]["label"] == "ELEV"


def test_lsr_flags():
    f = lambda t, r: {"properties": {"lon": -98.5, "lat": 38.5, "typetext": t, "remark": r}}
    out = lsr.parse({"features": [f("TSTM WND DMG", "power line down"), f("HAIL", "quarters"),
                                  f("NON-TSTM WND GST", "grass fire started")]})
    assert out["total_reports"] == 3 and out["count"] == 2
    assert out["reports"][0]["downed_line"] and out["reports"][1]["fire"]


def test_metar_rh():
    assert metar.rh_from_dewpoint(20, 20) == pytest.approx(100, abs=0.5)
    assert 40 < metar.rh_from_dewpoint(25, 12) < 50
    rows = metar.parse_primary([{"icaoId": "KICT", "lat": 37.6, "lon": -97.4, "temp": 25, "dewp": 12,
                                 "wspd": 10, "wgst": 20, "wdir": 180, "altim": 1013}])
    assert rows[0]["id"] == "KICT" and rows[0]["wind_kmh"] == pytest.approx(18.5, abs=0.1)
    assert 40 < rows[0]["rh_pct"] < 50


def test_wfigs_parse():
    out = wfigs.parse({"features": [{"properties": {"IncidentName": "Z", "IncidentSize": 12.5}, "geometry": None}]})
    assert out["count"] == 1 and out["items"][0]["name"] == "Z" and out["items"][0]["acres"] == 12.5


def test_hms_404_falls_back_to_yesterday(monkeypatch):
    calls = []

    def fake(url, params=None):
        calls.append(url)
        if len(calls) == 1:
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("nf", request=req, response=httpx.Response(404, request=req))
        return "Lon,Lat,YearDay,Time,Satellite,Method,Ecosystem,FRP\n-98.5,38.5,2026310,1800,GOES,x,1,5\n-120,38,2026310,1800,GOES,x,1,5\n"

    monkeypatch.setattr(hms, "get_text", fake)
    out = hms.fetch()
    assert len(calls) == 2 and out["count"] == 1


def test_feed_route_fixture_and_snapshot(monkeypatch):
    with TestClient(app) as c:
        r = c.get("/api/feeds/nws_alerts").json()
        assert r["fixture"] is True
        assert c.get("/api/feeds/nope").status_code == 404
        monkeypatch.setenv("MODE", "live")
        get_settings.cache_clear()
        assert c.get("/api/feeds/nws_alerts").json()["fixture"] is True
        with connect() as conn:
            save_snapshot(conn, "nws_alerts", {"count": 0, "alerts": []})
        r = c.get("/api/feeds/nws_alerts").json()
        assert r["fixture"] is False and r["data"]["count"] == 0


def test_risk_grid_and_lines_under_wind():
    with TestClient(app) as c:
        g = c.get("/api/risk/grid").json()
        assert g["type"] == "FeatureCollection" and len(g["features"]) > 0
        w = c.get("/api/risk/lines-under-wind").json()
        assert w["type"] == "FeatureCollection" and "threshold_kmh" in w


def test_health_lists_every_source():
    with TestClient(app) as c:
        h = c.get("/api/health").json()
        text = str(h)
        for n in get_settings().source_intervals:
            assert n in text


def _deny(url, timeout=None):
    req = httpx.Request("GET", url)
    raise httpx.HTTPStatusError(f"403 for url {url}", request=req, response=httpx.Response(403, request=req))


def test_firms_errors_never_carry_the_key(monkeypatch):
    from app.ingest import firms

    monkeypatch.setattr(firms.httpx, "get", _deny)
    with pytest.raises(RuntimeError) as e:
        firms.fetch_area("SECRETKEY123", "VIIRS_SNPP_NRT", (0, 0, 1, 1))
    assert "SECRETKEY123" not in str(e.value)
    assert "403" in str(e.value)
    assert e.value.__suppress_context__


def test_mark_source_redacts_the_key(monkeypatch):
    from types import SimpleNamespace

    from app import db

    monkeypatch.setattr(db, "get_settings", lambda: SimpleNamespace(firms_map_key="SECRETKEY123"))
    calls = []

    class Conn:
        def execute(self, sql, params):
            calls.append(params)

    db.mark_source(Conn(), "firms", ok=False, error="failed at /csv/SECRETKEY123/VIIRS")
    assert "SECRETKEY123" not in calls[0][1]


def test_init_db_scrubs_old_errors_and_recovery_clears_them(tmp_path):
    from app import db

    path = str(tmp_path / "t.sqlite")
    db.init_db(path)
    with db.connect(path) as conn:
        conn.execute(
            "INSERT INTO source_health(source, last_error) VALUES ('firms', ?)",
            ("403 for https://firms.modaps.eosdis.nasa.gov/api/area/csv/SECRETKEY123/VIIRS",),
        )
        conn.execute("INSERT INTO source_health(source, last_error) VALUES ('nws_alerts', 'timeout')")
    db.init_db(path)
    with db.connect(path) as conn:
        assert conn.execute("SELECT last_error FROM source_health WHERE source='firms'").fetchone()[0] is None
        db.mark_source(conn, "nws_alerts", ok=True)
        assert conn.execute("SELECT last_error FROM source_health WHERE source='nws_alerts'").fetchone()[0] is None
