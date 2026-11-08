"""GOES-19 GLM lightning flashes (GLM-L2-LCFA), from NOAA open-data S3.

20-second files. Each poll lists the current hour, keeps the last WINDOW_FILES files
(about 5 minutes), downloads only files not already parsed, and keeps flashes inside
the Kansas bbox. Context feed only: never touches the model.
"""

import logging
from datetime import datetime, timedelta, timezone

import netCDF4
import numpy as np

from . import s3
from .feedlib import in_bbox, run_feed

log = logging.getLogger("firewatch.goes_lightning")

BUCKET = "noaa-goes19"
PRODUCT = "GLM-L2-LCFA"
WINDOW_FILES = 15  # 15 x 20 s = 5 minutes
MAX_FLASHES = 500

_cache: dict[str, list[dict]] = {}  # key -> flashes in bbox


def parse(data: bytes) -> list[dict]:
    """Flashes inside the AOI from one GLM file (bytes)."""
    ds = netCDF4.Dataset("glm.nc", mode="r", memory=data)
    try:
        lat = np.ma.filled(ds["flash_lat"][:], np.nan).astype("float64")
        lon = np.ma.filled(ds["flash_lon"][:], np.nan).astype("float64")
        off = np.ma.filled(ds["flash_time_offset_of_first_event"][:], np.nan).astype("float64")  # scaled seconds
        energy = np.ma.filled(ds["flash_energy"][:], np.nan).astype("float64")
        start = datetime.fromisoformat(str(ds.time_coverage_start).replace("Z", "+00:00"))
    finally:
        ds.close()
    out = []
    for i in np.nonzero(np.isfinite(lat) & np.isfinite(lon))[0]:
        if not in_bbox(float(lon[i]), float(lat[i])):
            continue
        t = start + timedelta(seconds=float(off[i]) if np.isfinite(off[i]) else 0.0)
        out.append({"lon": round(float(lon[i]), 4), "lat": round(float(lat[i]), 4), "time": t.isoformat(),
                    "energy_fj": None if not np.isfinite(energy[i]) else round(float(energy[i]) * 1e15, 1)})
    return out


def fetch(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    keys = s3.recent_keys(BUCKET, PRODUCT, now)[-WINDOW_FILES:]
    if not keys:
        raise RuntimeError("no GLM files in last 2 hours")
    for k in keys:
        if k not in _cache:
            _cache[k] = parse(s3.get_bytes(BUCKET, k))
    for k in [k for k in _cache if k not in keys]:
        del _cache[k]
    flashes = sorted((f for k in keys for f in _cache[k]), key=lambda f: f["time"], reverse=True)
    newest = s3.scan_start(keys[-1])
    return {"count": len(flashes[:MAX_FLASHES]), "total": len(flashes), "files": len(keys),
            "window_min": round(WINDOW_FILES * 20 / 60), "scan_start": newest.isoformat() if newest else None,
            "points": flashes[:MAX_FLASHES]}


def poll() -> dict:
    return run_feed("goes_lightning", fetch())
