from datetime import datetime, timezone
from pathlib import Path

import httpx
import netCDF4
import numpy as np
import pytest

from app.ingest import goes

FIX = Path(__file__).parent / "fixtures"
PROJ = {
    "perspective_point_height": 35786023.0,
    "semi_major_axis": 6378137.0,
    "semi_minor_axis": 6356752.31414,
    "longitude_of_projection_origin": -75.0,
}
KANSAS = (-102.05, 36.99, -94.59, 40.00)


def test_projection_nadir():
    lat, lon = goes.pixel_to_latlon(0.0, 0.0, PROJ)
    assert lat == pytest.approx(0.0, abs=1e-9) and lon == pytest.approx(-75.0, abs=1e-9)


def test_projection_matches_pug_example():
    # Worked example from GOES-R PUG vol. 3: x=-0.024052, y=0.095340 -> 33.846162 N, 84.690932 W
    lat, lon = goes.pixel_to_latlon(-0.024052, 0.095340, PROJ)
    assert lat == pytest.approx(33.846162, abs=1e-4)
    assert lon == pytest.approx(-84.690932, abs=1e-4)


def test_off_earth_is_nan():
    lat, lon = goes.pixel_to_latlon(0.2, 0.2, PROJ)
    assert np.isnan(lat) and np.isnan(lon)


def test_filename_times_and_confidence():
    key = "ABI-L2-FDCC/2026/311/00/OR_ABI-L2-FDCC-M6_G19_s20263110001182_e20263110003555_c20263110004057.nc"
    start, end = goes.scan_times(key)
    assert start == datetime(2026, 11, 7, 0, 1, 18, 200000, tzinfo=timezone.utc)
    assert end.minute == 3
    assert goes.confidence_from_mask(10) == "high"
    assert goes.confidence_from_mask(34) == "nominal"
    assert goes.confidence_from_mask(35) == "low"


def test_listing_and_latency():
    files = goes.parse_listing((FIX / "goes_listing.xml").read_text())
    assert len(files) == 2 and files[0]["key"] < files[1]["key"]
    ingest = datetime(2026, 11, 7, 0, 10, tzinfo=timezone.utc)
    rec = goes.latency_record(files[0], ingest)
    assert rec["scan_start"] == "2026-11-07T00:01:18Z"
    assert rec["scan_end"] == "2026-11-07T00:03:55Z"
    assert rec["s3_last_modified"] == "2026-11-07T00:04:14Z"
    assert rec["scan_end_to_s3_min"] == 0.3
    assert rec["s3_to_ingest_min"] == 5.8
    assert rec["scan_start_to_ingest_min"] == 8.7


def _tiny_file(tmp_path) -> bytes:
    """A 3x3 FDCC-like file; pixel (1,1) is found by inverting the projection for a point near Coldwater KS."""
    req, rpol, H = PROJ["semi_major_axis"], PROJ["semi_minor_axis"], PROJ["perspective_point_height"] + 6378137.0
    lat, lon = np.radians(37.27), np.radians(-99.31)
    lon0 = np.radians(-75.0)
    phic = np.arctan((rpol ** 2 / req ** 2) * np.tan(lat))
    rc = rpol / np.sqrt(1 - (1 - rpol ** 2 / req ** 2) * np.cos(phic) ** 2)
    sx = H - rc * np.cos(phic) * np.cos(lon - lon0)
    sy = -rc * np.cos(phic) * np.sin(lon - lon0)
    sz = rc * np.sin(phic)
    y0 = np.arctan(sz / sx)
    x0 = np.arcsin(-sy / np.sqrt(sx ** 2 + sy ** 2 + sz ** 2))
    xs = x0 + np.array([-1, 0, 1]) * 5.6e-5
    ys = y0 + np.array([1, 0, -1]) * 5.6e-5
    path = tmp_path / "t.nc"
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("y", 3)
        ds.createDimension("x", 3)
        ds.createVariable("x", "f8", ("x",))[:] = xs
        ds.createVariable("y", "f8", ("y",))[:] = ys
        mask = ds.createVariable("Mask", "i2", ("y", "x"), fill_value=-99)
        mask[:] = np.array([[0, 0, 0], [0, 33, 0], [0, 0, 11]])
        power = ds.createVariable("Power", "f4", ("y", "x"), fill_value=-9.0)
        power[:] = np.array([[-9, -9, -9], [-9, 42.5, -9], [-9, -9, -9]])
        p = ds.createVariable("goes_imager_projection", "i4")
        for k, v in PROJ.items():
            setattr(p, k, v)
    return path.read_bytes()


def test_read_fire_file_filters_to_bbox(tmp_path):
    data = _tiny_file(tmp_path)
    dets = goes.read_fire_file(data, KANSAS, "2026-11-07T00:01:18Z")
    # the other fire pixel (mask 11) is 2 pixels away but also inside Kansas; check both
    assert len(dets) == 2
    d = next(x for x in dets if x["mask_code"] == 33)
    assert d["source"] == "GOES19_FDC" and d["satellite"] == "G19"
    assert d["lat"] == pytest.approx(37.27, abs=0.01) and d["lon"] == pytest.approx(-99.31, abs=0.01)
    assert d["frp_mw"] == 42.5 and d["confidence"] == "high"
    assert d["scan_km"] == 2.0 and d["track_km"] == 2.0
    assert d["acq_time"] == "2026-11-07T00:01:18Z"
    other = next(x for x in dets if x["mask_code"] == 11)
    assert other["frp_mw"] is None
    # a bbox elsewhere keeps nothing
    assert goes.read_fire_file(data, (-90, 30, -85, 35), "x") == []


def test_garbage_file_is_scrubbed_error():
    with pytest.raises(RuntimeError) as e:
        goes.read_fire_file(b"not a netcdf file", KANSAS, "x")
    assert "http" not in str(e.value).lower()


def test_latest_detections_with_fake_network(monkeypatch, tmp_path):
    data = _tiny_file(tmp_path)
    listing = (FIX / "goes_listing.xml").read_text()

    def fake_get(url, params=None, timeout=None):
        req = httpx.Request("GET", url)
        return httpx.Response(200, content=listing.encode() if params else data, request=req)

    monkeypatch.setattr(goes.httpx, "get", fake_get)
    dets, lat = goes.latest_detections(KANSAS, now=datetime(2026, 11, 7, 0, 10, tzinfo=timezone.utc))
    assert len(dets) == 2 and lat["scan_start"].endswith("Z")


@pytest.mark.parametrize("fail", ["status", "connect"])
def test_errors_do_not_leak_url(monkeypatch, fail):
    def fake_get(url, params=None, timeout=None):
        req = httpx.Request("GET", url)
        if fail == "status":
            return httpx.Response(503, request=req)
        raise httpx.ConnectError("boom for " + url, request=req)

    monkeypatch.setattr(goes.httpx, "get", fake_get)
    with pytest.raises(RuntimeError) as e:
        goes.list_hour(datetime(2026, 11, 7, 0, tzinfo=timezone.utc))
    msg = str(e.value)
    assert "amazonaws" not in msg and "http" not in msg.lower().replace("http 503", "")
