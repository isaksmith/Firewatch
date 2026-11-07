"""GOES-R ABI aerosol detection smoke mask (ABI-L2-ADPC) from NOAA open-data S3.

5-minute CONUS scans from GOES-East. Daytime only: at night the product carries no
retrievals (number_good_SZA_pixels is 0), which is reported as daytime=false and zero
points, not as an error. Context feed only: pixels never go through process_detections.
"""

import logging
from datetime import datetime, timezone

import netCDF4
import numpy as np

from . import s3
from .feedlib import in_bbox, run_feed
from .goes_fire import fixed_grid_to_latlon

log = logging.getLogger("firewatch.goes_smoke")

BUCKET = "noaa-goes19"
PRODUCT = "ABI-L2-ADPC"
CELL_DEG = 0.1  # thin to one point per 0.1 degree cell (about 10 km, 5 native pixels)
MAX_POINTS = 600

_cache: dict[str, dict] = {}  # newest key -> result


def parse(data: bytes) -> dict:
    """Thinned smoke-present pixels inside the AOI, plus whether the scan had daylight."""
    ds = netCDF4.Dataset("adp.nc", mode="r", memory=data)
    try:
        daytime = int(np.ma.filled(ds["number_good_SZA_pixels"][:], 0)) > 0
        smoke = np.ma.filled(ds["Smoke"][:], 0)
        rows, cols = np.nonzero(smoke == 1)
        if rows.size == 0:
            return {"daytime": daytime, "total": 0, "points": []}
        proj = {a: ds["goes_imager_projection"].getncattr(a) for a in ds["goes_imager_projection"].ncattrs()}
        xs = np.ma.filled(ds["x"][:], np.nan).astype("float64")[cols]
        ys = np.ma.filled(ds["y"][:], np.nan).astype("float64")[rows]
        lat, lon = fixed_grid_to_latlon(xs, ys, proj)
    finally:
        ds.close()
    cells: dict[tuple[int, int], list[float]] = {}
    total = 0
    for la, lo in zip(lat, lon):
        if not (np.isfinite(la) and np.isfinite(lo)) or not in_bbox(float(lo), float(la)):
            continue
        total += 1
        c = cells.setdefault((int(np.floor(la / CELL_DEG)), int(np.floor(lo / CELL_DEG))), [0.0, 0.0, 0])
        c[0] += la
        c[1] += lo
        c[2] += 1
    pts = [{"lon": round(c[1] / c[2], 4), "lat": round(c[0] / c[2], 4), "pixels": c[2]} for c in cells.values()]
    pts.sort(key=lambda p: -p["pixels"])
    return {"daytime": daytime, "total": total, "points": pts[:MAX_POINTS]}


def fetch(now: datetime | None = None) -> dict:
    keys = s3.recent_keys(BUCKET, PRODUCT, now)
    if not keys:
        raise RuntimeError("no ABI-L2-ADPC files in last 2 hours")
    key = keys[-1]
    if key not in _cache:
        _cache.clear()
        _cache[key] = parse(s3.get_bytes(BUCKET, key))
    res = _cache[key]
    start = s3.scan_start(key)
    out = {"count": len(res["points"]), "total_pixels": res["total"], "daytime": res["daytime"],
           "scan_start": start.isoformat() if start else None, "key": key.rsplit("/", 1)[-1],
           "points": res["points"]}
    if not res["daytime"]:
        out["notice"] = "Night: smoke mask has no retrievals (daytime only)"
    return out


def poll() -> dict:
    return run_feed("goes_smoke", fetch())
