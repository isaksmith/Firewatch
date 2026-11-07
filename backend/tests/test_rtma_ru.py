from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import connect, save_snapshot
from app.ingest import risk_grid, rtma_ru, s3
from app.main import app

IDX = """1:0:d=2026110701:HGT:surface:anl:
2:7490118:d=2026110701:PRES:surface:anl:
3:14980236:d=2026110701:TMP:2 m above ground:anl:
4:21065993:d=2026110701:DPT:2 m above ground:anl:
5:27151750:d=2026110701:UGRD:10 m above ground:anl:
"""
KEY = "rtma2p5_ru.20261107/rtma2p5_ru.t0145z.2dvaranl_ndfd.grb2"


def test_byte_ranges_end_at_next_message():
    r = rtma_ru.byte_ranges(IDX)
    assert r == {"p": (7490118, 14980235), "t": (14980236, 21065992), "d": (21065993, 27151749)}


def test_byte_ranges_last_message_without_successor_is_skipped():
    assert "d" not in rtma_ru.byte_ranges("\n".join(IDX.splitlines()[:4]))


def test_key_time():
    assert rtma_ru.key_time(KEY) == datetime(2026, 11, 7, 1, 45, tzinfo=timezone.utc)
    assert rtma_ru.key_time("junk") is None


def test_newest_key_ignores_other_products_and_falls_back(monkeypatch):
    seen = []

    def fake(bucket, prefix):
        seen.append(prefix)
        if prefix.endswith("t02"):
            return []
        return [f"{prefix}00z.2dvarges_ndfd.grb2", f"{prefix}00z.2dvaranl_ndfd.grb2",
                f"{prefix}00z.2dvaranl_ndfd.grb2.idx", f"{prefix}15z.2dvaranl_ndfd.grb2"]

    monkeypatch.setattr(s3, "list_keys", fake)
    k = rtma_ru.newest_key(datetime(2026, 11, 7, 2, 10, tzinfo=timezone.utc))
    assert seen == ["rtma2p5_ru.20261107/rtma2p5_ru.t02", "rtma2p5_ru.20261107/rtma2p5_ru.t01"]
    assert k.endswith("t0115z.2dvaranl_ndfd.grb2")


def _fields():
    pts = risk_grid.grid_points()
    lat0, lon0 = pts[0]
    lats, lons = np.meshgrid(np.linspace(lat0 - 1, lat0 + 1, 21), np.linspace(lon0 - 1, lon0 + 1, 21), indexing="ij")
    t = np.full(lats.shape, 303.15)  # 30 C
    d = np.full(lats.shape, 283.15)  # 10 C
    p = np.full(lats.shape, 90000.0)
    return {"p": (p, lats, lons), "t": (t, lats, lons), "d": (d, lats, lons)}


def test_sample_units_and_rh():
    out = rtma_ru.sample(_fields())
    assert len(out) == len(risk_grid.grid_points())
    c = out[0]
    assert c["temp_c"] == 30.0 and c["dew_c"] == 10.0 and c["p_hpa"] == 900.0
    assert 25 < c["rh"] < 30  # 30 C / 10 C dew point is about 26 percent


def test_sample_picks_nearest_cell():
    f = _fields()
    t, lats, lons = f["t"]
    lat0, lon0 = risk_grid.grid_points()[0]
    i = np.unravel_index(np.argmin((lats - lat0) ** 2 + (lons - lon0) ** 2), lats.shape)
    t[i] = 273.15
    assert rtma_ru.sample(f)[0]["temp_c"] == 0.0


def test_fetch_downloads_three_ranges_once(monkeypatch):
    rtma_ru._cache.clear()
    calls = []
    monkeypatch.setattr(rtma_ru, "newest_key", lambda now=None: KEY)

    def fake_get(bucket, key, byte_range=None):
        calls.append(byte_range)
        return IDX.encode() if byte_range is None else b"x"

    monkeypatch.setattr(s3, "get_bytes", fake_get)
    monkeypatch.setattr(rtma_ru, "parse", lambda blob: [{"lat": 1.0, "lon": 2.0, "temp_c": 1, "dew_c": 0, "rh": 90, "p_hpa": 900}])
    out = rtma_ru.fetch()
    assert out["count"] == 1 and out["valid_time"] == "2026-11-07T01:45:00+00:00"
    assert [c for c in calls if c] == [(7490118, 14980235), (14980236, 21065992), (21065993, 27151749)]
    n = len(calls)
    rtma_ru.fetch()
    assert len(calls) == n  # same key, no re-download


def test_fetch_no_file_raises(monkeypatch):
    rtma_ru._cache.clear()
    monkeypatch.setattr(rtma_ru, "newest_key", lambda now=None: None)
    with pytest.raises(RuntimeError):
        rtma_ru.fetch()


def _save_rtma(valid: datetime):
    pts = [{"lat": la, "lon": lo, "temp_c": 20.0, "dew_c": 0.0, "rh": 12.5, "p_hpa": 900.0} for la, lo in risk_grid.grid_points()]
    with connect() as conn:
        save_snapshot(conn, "rtma_ru", {"count": len(pts), "valid_time": valid.isoformat(), "points": pts})


def test_grid_route_prefers_fresh_rtma_then_falls_back(monkeypatch):
    with TestClient(app) as c:
        assert c.get("/api/risk/grid").json()["source"] == "open_meteo"  # sample mode
        monkeypatch.setenv("MODE", "live")
        get_settings.cache_clear()
        assert c.get("/api/risk/grid").json()["source"] == "open_meteo"  # live, no snapshot yet
        _save_rtma(datetime.now(timezone.utc) - timedelta(minutes=20))
        g = c.get("/api/risk/grid").json()
        assert g["source"] == "rtma_ru"
        assert all(f["properties"]["rh"] == 12.5 and f["properties"]["temp_c"] == 20.0 for f in g["features"])
        assert all("gust_kmh" in f["properties"] for f in g["features"])  # wind still from Open-Meteo
        _save_rtma(datetime.now(timezone.utc) - timedelta(hours=5))
        assert c.get("/api/risk/grid").json()["source"] == "open_meteo"  # stale
