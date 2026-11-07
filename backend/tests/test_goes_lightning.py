from datetime import datetime, timezone

import netCDF4
import numpy as np
import pytest

from app.ingest import goes_lightning as gl
from app.ingest import s3


def make_glm(tmp_path, flashes, start="2026-11-07T01:59:20.0Z"):
    """flashes: list of (lat, lon, offset_s, energy_j). Offsets use the real packed int16 scheme."""
    path = tmp_path / "glm.nc"
    ds = netCDF4.Dataset(path, "w")
    ds.time_coverage_start = start
    ds.createDimension("flash", len(flashes))
    lat = ds.createVariable("flash_lat", "f4", ("flash",))
    lon = ds.createVariable("flash_lon", "f4", ("flash",))
    off = ds.createVariable("flash_time_offset_of_first_event", "i2", ("flash",))
    off.scale_factor, off.add_offset = np.float32(0.0003814756), np.float32(-5.0)
    en = ds.createVariable("flash_energy", "i2", ("flash",))
    en.scale_factor, en.add_offset = np.float32(9.99996e-16), np.float32(2.8515e-16)
    lat[:] = [f[0] for f in flashes]
    lon[:] = [f[1] for f in flashes]
    off[:] = [f[2] for f in flashes]
    en[:] = [f[3] for f in flashes]
    ds.close()
    return path.read_bytes()


def test_parse_filters_to_kansas_and_decodes_time(tmp_path):
    data = make_glm(tmp_path, [(38.7, -98.7, 5.0, 2e-13), (10.0, -75.0, 6.0, 1e-13), (45.0, -98.0, 6.0, 1e-13)])
    out = gl.parse(data)
    assert len(out) == 1
    assert out[0]["lat"] == pytest.approx(38.7, abs=1e-3)
    assert out[0]["time"].startswith("2026-11-07T01:59:2")  # start + ~5 s
    assert out[0]["energy_fj"] == pytest.approx(200, abs=1)


def test_parse_empty(tmp_path):
    assert gl.parse(make_glm(tmp_path, [(0.0, 0.0, 5.0, 1e-13)])) == []


def test_fetch_window_cache_and_cap(tmp_path, monkeypatch):
    gl._cache.clear()
    data = make_glm(tmp_path, [(38.7, -98.7, 5.0, 2e-13)])
    keys = [f"GLM-L2-LCFA/2026/311/02/OR_GLM-L2-LCFA_G19_s20263110200{i:02d}0_e0_c0.nc" for i in range(0, 40, 2)]
    fetched = []
    monkeypatch.setattr(s3, "recent_keys", lambda *a, **k: list(keys))
    monkeypatch.setattr(s3, "get_bytes", lambda b, k, byte_range=None: fetched.append(k) or data)
    out = gl.fetch(datetime(2026, 11, 7, 2, 5, tzinfo=timezone.utc))
    assert out["files"] == gl.WINDOW_FILES and len(fetched) == gl.WINDOW_FILES
    assert out["count"] == gl.WINDOW_FILES  # one flash per file
    gl.fetch()
    assert len(fetched) == gl.WINDOW_FILES  # nothing new, nothing downloaded
    monkeypatch.setattr(gl, "MAX_FLASHES", 3)
    assert gl.fetch()["count"] == 3


def test_fetch_no_files_raises(monkeypatch):
    gl._cache.clear()
    monkeypatch.setattr(s3, "recent_keys", lambda *a, **k: [])
    with pytest.raises(RuntimeError):
        gl.fetch()
