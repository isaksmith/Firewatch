from datetime import datetime, timezone

import netCDF4
import numpy as np
import pytest

from app.ingest import goes_smoke as gs
from app.ingest import s3
from tests.test_goes_fire import PROJ, forward


def make_adp(tmp_path, smoke_spots, sza_good=1000):
    """Tiny ADP file: smoke_spots is a list of (lat, lon); each gets its own x/y cell with Smoke=1."""
    pts = [forward(la, lo) for la, lo in smoke_spots]
    n = len(pts) + 1
    path = tmp_path / "adp.nc"
    ds = netCDF4.Dataset(path, "w")
    ds.createDimension("x", n)
    ds.createDimension("y", n)
    x = ds.createVariable("x", "f8", ("x",))
    y = ds.createVariable("y", "f8", ("y",))
    x[:] = [p[0] for p in pts] + [0.0]
    y[:] = [p[1] for p in pts] + [0.0]
    sm = ds.createVariable("Smoke", "i1", ("y", "x"), fill_value=-128)
    sm[:] = 0
    for i in range(len(pts)):
        sm[i, i] = 1
    sza = ds.createVariable("number_good_SZA_pixels", "i4")
    sza[...] = sza_good
    g = ds.createVariable("goes_imager_projection", "i4")
    for k, v in PROJ.items():
        g.setncattr(k, v)
    ds.close()
    return path.read_bytes()


def test_parse_bbox_and_thinning(tmp_path):
    # two spots in the same 0.1 deg cell merge; one outside Kansas is dropped
    out = gs.parse(make_adp(tmp_path, [(38.51, -98.51), (38.53, -98.52), (38.2, -97.2), (30.0, -90.0)]))
    assert out["daytime"] and out["total"] == 3 and len(out["points"]) == 2
    assert out["points"][0]["pixels"] == 2


def test_parse_night_is_not_error(tmp_path):
    out = gs.parse(make_adp(tmp_path, [], sza_good=0))
    assert out == {"daytime": False, "total": 0, "points": []}


def test_fetch_night_notice_cache_and_cap(tmp_path, monkeypatch):
    gs._cache.clear()
    night = make_adp(tmp_path, [], sza_good=0)
    key = "ABI-L2-ADPC/2026/311/01/OR_ABI-L2-ADPC-M6_G19_s20263110151182_e0_c0.nc"
    calls = []
    monkeypatch.setattr(s3, "recent_keys", lambda *a, **k: [key])
    monkeypatch.setattr(s3, "get_bytes", lambda b, k, byte_range=None: calls.append(k) or night)
    out = gs.fetch(datetime(2026, 11, 7, 2, tzinfo=timezone.utc))
    assert out["count"] == 0 and out["daytime"] is False and "Night" in out["notice"]
    assert out["scan_start"].startswith("2026-11-07T01:51:18")
    gs.fetch()
    assert len(calls) == 1  # same key, no second download


def test_cap(tmp_path, monkeypatch):
    spots = [(38.0 + 0.1 * i, -98.0) for i in range(6)]
    monkeypatch.setattr(gs, "MAX_POINTS", 4)
    assert len(gs.parse(make_adp(tmp_path, spots))["points"]) == 4


def test_fetch_no_files_raises(monkeypatch):
    gs._cache.clear()
    monkeypatch.setattr(s3, "recent_keys", lambda *a, **k: [])
    with pytest.raises(RuntimeError):
        gs.fetch()
