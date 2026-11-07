from datetime import datetime, timezone

import netCDF4
import numpy as np
import pytest

from app.ingest import goes_fire, s3

PROJ = dict(semi_major_axis=6378137.0, semi_minor_axis=6356752.31414, perspective_point_height=35786023.0,
            longitude_of_projection_origin=-75.2)


def forward(lat, lon, p=PROJ):
    """PUG forward projection (lat/lon degrees -> x, y radians), used to build fixtures."""
    req, rpol = p["semi_major_axis"], p["semi_minor_axis"]
    h = p["perspective_point_height"] + req
    lam0 = np.radians(p["longitude_of_projection_origin"])
    phi_c = np.arctan((rpol**2 / req**2) * np.tan(np.radians(lat)))
    e2 = (req**2 - rpol**2) / req**2
    rc = rpol / np.sqrt(1 - e2 * np.cos(phi_c) ** 2)
    sx = h - rc * np.cos(phi_c) * np.cos(np.radians(lon) - lam0)
    sy = -rc * np.cos(phi_c) * np.sin(np.radians(lon) - lam0)
    sz = rc * np.sin(phi_c)
    return np.arcsin(-sy / np.sqrt(sx**2 + sy**2 + sz**2)), np.arctan(sz / sx)


def make_nc(tmp_path, spots):
    """Tiny 6x6 FDC file. spots: list of (lat, lon, mask, power, temp), pixel placed at the nearest grid cell."""
    xs = np.linspace(*forward(38.0, -100.0)[:1], 1)  # placeholder
    pts = [forward(la, lo) for la, lo, *_ in spots]
    n = len(spots) + 2
    path = tmp_path / "fdc.nc"
    ds = netCDF4.Dataset(path, "w")
    ds.createDimension("x", n)
    ds.createDimension("y", n)
    x = ds.createVariable("x", "f8", ("x",))
    y = ds.createVariable("y", "f8", ("y",))
    x[:] = [pt[0] for pt in pts] + [0.0, 0.0]  # last two cells face the sub-satellite point (not fire)
    y[:] = [pt[1] for pt in pts] + [0.0, 0.0]
    mask = ds.createVariable("Mask", "i1", ("y", "x"), fill_value=-99)
    power = ds.createVariable("Power", "f4", ("y", "x"), fill_value=-99)
    temp = ds.createVariable("Temp", "f4", ("y", "x"), fill_value=-99)
    mask[:] = 0
    power[:] = np.nan
    temp[:] = np.nan
    for i, (_, _, m, pw, tk) in enumerate(spots):
        mask[i, i], power[i, i], temp[i, i] = m, pw, tk
    g = ds.createVariable("goes_imager_projection", "i4")
    for k, v in PROJ.items():
        g.setncattr(k, v)
    ds.close()
    return path.read_bytes()


def test_projection_round_trip():
    for lat, lon in [(38.9, -98.9), (37.0, -100.5), (39.5, -95.0)]:
        x, y = forward(lat, lon)
        la, lo = goes_fire.fixed_grid_to_latlon(x, y, PROJ)
        assert la == pytest.approx(lat, abs=1e-6) and lo == pytest.approx(lon, abs=1e-6)


def test_projection_off_earth_is_nan():
    la, lo = goes_fire.fixed_grid_to_latlon(0.5, 0.5, PROJ)
    assert np.isnan(la) and np.isnan(lo)


def test_parse_filters_codes_and_bbox(tmp_path):
    data = make_nc(tmp_path, [
        (38.9, -98.9, 10, 12.5, 330.0),   # Kansas, good
        (38.5, -99.4, 33, 40.0, 360.0),   # Kansas, filtered high probability
        (38.9, -98.5, 14, 1.0, 300.0),    # Kansas but not a fire code
        (30.0, -98.9, 10, 5.0, 320.0),    # Texas, outside bbox
    ])
    pts = goes_fire.parse(data, "goes19")
    assert len(pts) == 2
    a, b = pts
    assert (a["lat"], a["lon"]) == (pytest.approx(38.9, abs=1e-3), pytest.approx(-98.9, abs=1e-3))
    assert a["class"] == "good" and not a["filtered"] and a["power_mw"] == 12.5 and a["satellite"] == "goes19"
    assert b["class"] == "high_probability" and b["filtered"] and b["temp_k"] == 360.0


def test_parse_no_fire(tmp_path):
    assert goes_fire.parse(make_nc(tmp_path, [(38.9, -98.9, 0, 0.0, 0.0)]), "goes19") == []


def test_fetch_labels_satellites_caches_and_isolates_failure(tmp_path, monkeypatch):
    data = make_nc(tmp_path, [(38.9, -98.9, 10, 12.5, 330.0)])
    goes_fire._cache.clear()
    calls = []
    key = "ABI-L2-FDCC/2026/311/12/OR_ABI-L2-FDCC-M6_G19_s20263111201175_e20263111203548_c20263111204000.nc"

    def keys(bucket, product, now=None, hours=2):
        if bucket == "noaa-goes18":
            raise RuntimeError("boom")
        return [key]

    def get(bucket, k, byte_range=None):
        calls.append(k)
        return data

    monkeypatch.setattr(s3, "recent_keys", keys)
    monkeypatch.setattr(s3, "get_bytes", get)
    now = datetime(2026, 11, 7, 12, 5, tzinfo=timezone.utc)
    out = goes_fire.fetch(now)
    assert out["count"] == 1 and out["points"][0]["satellite"] == "goes19"
    assert out["points"][0]["scan_start"].startswith("2026-11-07T12:01")
    assert any("error" in s for s in out["satellites"])
    goes_fire.fetch(now)
    assert len(calls) == 1  # unchanged key is not re-downloaded


def test_fetch_all_fail_raises(monkeypatch):
    goes_fire._cache.clear()
    monkeypatch.setattr(s3, "recent_keys", lambda *a, **k: [])
    with pytest.raises(RuntimeError):
        goes_fire.fetch()
