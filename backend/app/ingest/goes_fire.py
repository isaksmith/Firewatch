"""GOES-R ABI fire/hot spot characterization (ABI-L2-FDCC), straight from NOAA open-data S3.

5-minute CONUS scans from GOES-East (goes19) and GOES-West (goes18). The fixed-grid
x/y scan angles are converted to lat/lon with the GOES-R PUG inverse projection.
This is a context feed: pixels never go through process_detections, so they cannot
change n_satellites, n_detections or any model feature.
"""

import logging
from datetime import datetime, timezone

import netCDF4
import numpy as np

from . import s3
from .feedlib import in_bbox, run_feed

log = logging.getLogger("firewatch.goes_fire")

SATELLITES = {"goes19": "noaa-goes19", "goes18": "noaa-goes18"}
PRODUCT = "ABI-L2-FDCC"
# FDC Mask flag values, from the file's flag_values/flag_meanings:
#   10 good, 11 saturated, 12 cloud_contaminated, 13 high_probability fire pixel
#   30..33 the same four classes, temporally filtered.
FIRE_CODES = (10, 11, 12, 13, 30, 31, 32, 33)
CLASS = {0: "good", 1: "saturated", 2: "cloud_contaminated", 3: "high_probability"}

_cache: dict[str, tuple[str, dict]] = {}  # satellite -> (newest key, parsed result)


def fixed_grid_to_latlon(x, y, proj: dict):
    """GOES-R PUG (L1b/L2 product user guide) inverse projection. x, y in radians.

    Returns (lat, lon) in degrees; NaN for scan angles that miss the Earth.
    """
    x, y = np.asarray(x, dtype="float64"), np.asarray(y, dtype="float64")
    r_eq, r_pol = float(proj["semi_major_axis"]), float(proj["semi_minor_axis"])
    big_h = float(proj["perspective_point_height"]) + r_eq
    lon0 = np.radians(float(proj["longitude_of_projection_origin"]))
    sin_x, cos_x, sin_y, cos_y = np.sin(x), np.cos(x), np.sin(y), np.cos(y)
    a = sin_x**2 + cos_x**2 * (cos_y**2 + (r_eq**2 / r_pol**2) * sin_y**2)
    b = -2.0 * big_h * cos_x * cos_y
    c = big_h**2 - r_eq**2
    disc = b**2 - 4.0 * a * c
    with np.errstate(invalid="ignore"):
        rs = (-b - np.sqrt(disc)) / (2.0 * a)
        sx, sy, sz = rs * cos_x * cos_y, -rs * sin_x, rs * cos_x * sin_y
        lat = np.degrees(np.arctan((r_eq**2 / r_pol**2) * sz / np.sqrt((big_h - sx) ** 2 + sy**2)))
        lon = np.degrees(lon0 - np.arctan(sy / (big_h - sx)))
    return lat, lon


def parse(data: bytes, satellite: str) -> list[dict]:
    """Fire pixels inside the AOI from one FDCC NetCDF file (bytes)."""
    ds = netCDF4.Dataset("fdc.nc", mode="r", memory=data)
    try:
        mask = np.ma.filled(ds["Mask"][:], -1)
        proj = {a: ds["goes_imager_projection"].getncattr(a) for a in ds["goes_imager_projection"].ncattrs()}
        rows, cols = np.nonzero(np.isin(mask, FIRE_CODES))
        if rows.size == 0:
            return []
        xs = np.ma.filled(ds["x"][:], np.nan).astype("float64")[cols]
        ys = np.ma.filled(ds["y"][:], np.nan).astype("float64")[rows]
        lat, lon = fixed_grid_to_latlon(xs, ys, proj)
        power = np.ma.filled(ds["Power"][:].astype("float64"), np.nan)[rows, cols]
        temp = np.ma.filled(ds["Temp"][:].astype("float64"), np.nan)[rows, cols]
        codes = mask[rows, cols]
    finally:
        ds.close()
    out = []
    for i in range(rows.size):
        if not (np.isfinite(lat[i]) and np.isfinite(lon[i])) or not in_bbox(float(lon[i]), float(lat[i])):
            continue
        code = int(codes[i])
        out.append({
            "lon": round(float(lon[i]), 4), "lat": round(float(lat[i]), 4), "satellite": satellite,
            "mask": code, "class": CLASS[code % 10], "filtered": code >= 30,
            "power_mw": None if not np.isfinite(power[i]) else round(float(power[i]), 1),
            "temp_k": None if not np.isfinite(temp[i]) else round(float(temp[i]), 1),
        })
    return out


def fetch(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    points: list[dict] = []
    sats = []
    for sat, bucket in SATELLITES.items():
        try:
            keys = s3.recent_keys(bucket, PRODUCT, now)
            if not keys:
                sats.append({"satellite": sat, "error": "no files in last 2 hours"})
                continue
            key = keys[-1]
            cached = _cache.get(sat)
            if cached and cached[0] == key:
                pts = cached[1]["points"]
            else:
                pts = parse(s3.get_bytes(bucket, key), sat)
                _cache[sat] = (key, {"points": pts})
            start = s3.scan_start(key)
            sats.append({"satellite": sat, "key": key.rsplit("/", 1)[-1], "count": len(pts),
                         "scan_start": start.isoformat() if start else None})
            for p in pts:
                points.append({**p, "scan_start": start.isoformat() if start else None})
        except Exception as e:  # one satellite down must not blank the other
            log.warning("goes_fire %s failed: %s", sat, e)
            sats.append({"satellite": sat, "error": str(e)[:120]})
    if sats and all("error" in s for s in sats):
        raise RuntimeError("; ".join(f"{s['satellite']}: {s['error']}" for s in sats))
    starts = [s["scan_start"] for s in sats if s.get("scan_start")]
    return {"count": len(points), "scan_start": max(starts) if starts else None, "satellites": sats, "points": points}


def poll() -> dict:
    return run_feed("goes_fire", fetch())
