"""Elevation from AWS Terrain Tiles (Terrarium PNG encoding), cached on disk."""

import io
import logging
import math
from functools import lru_cache

import httpx
import numpy as np
from PIL import Image

from .config import DATA_DIR

log = logging.getLogger(__name__)

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
ZOOM = 12
CACHE_DIR = DATA_DIR / "cache" / "terrain"


class TerrainUnavailable(Exception):
    pass


def _tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 2**z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


@lru_cache(maxsize=64)
def _tile(z: int, x: int, y: int) -> np.ndarray:
    path = CACHE_DIR / str(z) / str(x) / f"{y}.png"
    if path.exists():
        data = path.read_bytes()
    else:
        try:
            resp = httpx.get(TILE_URL.format(z=z, x=x, y=y), timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise TerrainUnavailable(str(e)) from e
        data = resp.content
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float64)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def elevation_grid(lats: np.ndarray, lons: np.ndarray, z: int = ZOOM) -> np.ndarray:
    """Elevation (m) for 1-D lat and lon axes; returns array shaped (len(lats), len(lons))."""
    out = np.empty((len(lats), len(lons)))
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            fx, fy = _tile_xy(lat, lon, z)
            tx, ty = int(fx), int(fy)
            px = min(int((fx - tx) * 256), 255)
            py = min(int((fy - ty) * 256), 255)
            out[i, j] = _tile(z, tx, ty)[py, px]
    return out


def point_elevation_and_slope(lat: float, lon: float, radius_m: float = 500.0) -> tuple[float, float]:
    """Elevation at the point and the max slope (degrees) found on a 5x5 grid within radius_m."""
    dlat = radius_m / 110_574
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    lats = np.linspace(lat - dlat, lat + dlat, 5)
    lons = np.linspace(lon - dlon, lon + dlon, 5)
    z = elevation_grid(lats, lons)
    step = 2 * radius_m / 4
    gy, gx = np.gradient(z, step, step)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    return float(z[2, 2]), float(slope.max())
