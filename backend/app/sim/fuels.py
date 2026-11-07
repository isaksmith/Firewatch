"""Fuel map for the spread grid from national 30 m land cover, cached on disk.

Base layer: NLCD 2021 land cover (MRLC WCS), which separates grassland, pasture, cropland, shrub,
trees, water and towns. Where a USDA Cropland Data Layer (CDL) tile has been prefetched
(`python -m scripts.fetch_fuels`), cropland is refined into winter wheat, row-crop residue or
fallow. CDL is never fetched during a forecast because its service is slow and often down.

Each class gets a spread multiplier relative to cured natural grassland (1.0) that varies by
season: green winter wheat in March barely carries fire, the same field as July stubble does.
The multipliers are planning assumptions, not measured values. Grassland and pasture are both
treated as ungrazed grass (the worst case), since neither dataset separates CRP from grazed range.
"""

import io
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache

import httpx
import numpy as np
import tifffile
from pyproj import Transformer

from ..config import DATA_DIR

log = logging.getLogger(__name__)
logging.getLogger("tifffile").setLevel(logging.ERROR)  # NLCD's "0.0" no-data tag is harmless

NLCD_URL = "https://www.mrlc.gov/geoserver/mrlc_download/NLCD_2021_Land_Cover_L48/wcs"
NLCD_COVERAGE = "NLCD_2021_Land_Cover_L48"
CDL_URL = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile"
CDL_YEAR = 2024
TILE_M = 15_000  # fetch and cache in 15 km square tiles of EPSG:5070 (500 x 500 px)
CACHE_DIR = DATA_DIR / "cache"
SUBSAMPLES = 3  # land-cover samples per grid cell side, averaged into the cell's multiplier
RETRY_AFTER_S = 300  # after a failed download, don't retry that tile for 5 minutes

# Fuel classes. Multipliers by season: dormant (Nov-Apr), growing (May-Jul), late (Aug-Oct).
FUELS: dict[str, tuple[str, tuple[float, float, float]]] = {
    "grass": ("Grass, pasture, CRP", (1.0, 1.0, 1.0)),
    "shrub": ("Shrub and sand sage", (0.9, 0.9, 0.9)),
    "cropland": ("Cropland (wheat or residue)", (0.3, 0.3, 0.3)),
    "wheat": ("Winter wheat", (0.15, 0.6, 0.3)),
    "crop": ("Row-crop residue", (0.4, 0.1, 0.3)),
    "fallow": ("Fallow", (0.25, 0.25, 0.25)),
    "trees": ("Trees", (0.5, 0.5, 0.5)),
    "wetland": ("Wetland", (0.4, 0.3, 0.4)),
    "developed_open": ("Roads and open developed", (0.3, 0.3, 0.3)),
    "developed": ("Town", (0.05, 0.05, 0.05)),
    "nonburnable": ("Water or barren", (0.0, 0.0, 0.0)),
    "unknown": ("Unknown (assumed grass)", (1.0, 1.0, 1.0)),
}
FUEL_KEYS = tuple(FUELS)
_K = {k: i for i, k in enumerate(FUEL_KEYS)}

_NLCD_CLASS = {11: "nonburnable", 12: "nonburnable", 21: "developed_open", 22: "developed", 23: "developed",
               24: "developed", 31: "nonburnable", 41: "trees", 42: "trees", 43: "trees", 52: "shrub",
               71: "grass", 81: "grass", 82: "cropland", 90: "wetland", 95: "wetland"}
# CDL codes used to refine NLCD cropland; any other crop code is row-crop residue.
_CDL_REFINE = {22: "wheat", 23: "wheat", 24: "wheat", 26: "wheat", 27: "wheat", 236: "wheat", 238: "wheat",
               61: "fallow", 176: "grass", 37: "grass", 58: "grass", 59: "grass", 60: "grass", 152: "shrub"}


def _lut(table: dict[int, str], default: str) -> np.ndarray:
    lut = np.full(256, _K[default], dtype=np.int8)
    for code, key in table.items():
        lut[code] = _K[key]
    return lut


_NLCD_LUT = _lut(_NLCD_CLASS, "unknown")
_CDL_LUT = _lut(_CDL_REFINE, "crop")
_CDL_LUT[0] = _K["cropland"]  # CDL no-data: keep the NLCD cropland class


def season_index(month: int) -> int:
    if month in (11, 12, 1, 2, 3, 4):
        return 0
    return 1 if month in (5, 6, 7) else 2


def multipliers(month: int) -> np.ndarray:
    s = season_index(month)
    return np.array([FUELS[k][1][s] for k in FUEL_KEYS])


class FuelUnavailable(Exception):
    pass


@dataclass
class Tile:
    data: np.ndarray  # land-cover codes
    x0: float  # EPSG:5070 coordinate of the upper-left pixel
    y0: float
    res: float


@lru_cache(maxsize=1)
def _to_albers() -> Transformer:
    return Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)


def _read_tile(raw: bytes) -> Tile:
    with tifffile.TiffFile(io.BytesIO(raw)) as tif:
        page = tif.pages[0]
        tags = page.tags
        if "ModelTransformationTag" in tags:
            m = tags["ModelTransformationTag"].value
            res, x0, y0 = m[0], m[3], m[7]
        else:
            res = tags["ModelPixelScaleTag"].value[0]
            _, _, _, x0, y0, _ = tags["ModelTiepointTag"].value[:6]
        return Tile(page.asarray(), x0, y0, res)


def _tile_bounds(tx: int, ty: int) -> tuple[int, int, int, int]:
    return tx * TILE_M, ty * TILE_M, (tx + 1) * TILE_M, (ty + 1) * TILE_M


def _nlcd_path(tx: int, ty: int):
    return CACHE_DIR / "nlcd" / f"{tx}_{ty}.tif"


def _cdl_path(tx: int, ty: int, year: int = CDL_YEAR):
    return CACHE_DIR / "cdl" / str(year) / f"{tx}_{ty}.tif"


def download_nlcd(tx: int, ty: int, timeout: float = 30) -> None:
    x0, y0, x1, y1 = _tile_bounds(tx, ty)
    params = {"service": "WCS", "version": "2.0.1", "request": "GetCoverage", "coverageid": NLCD_COVERAGE,
              "format": "image/geotiff"}
    url = f"{NLCD_URL}?{httpx.QueryParams(params)}&subset=X({x0},{x1})&subset=Y({y0},{y1})"
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    if "tiff" not in resp.headers.get("content-type", ""):
        raise FuelUnavailable(f"NLCD returned {resp.headers.get('content-type')}")
    path = _nlcd_path(tx, ty)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)


def download_cdl(tx: int, ty: int, year: int = CDL_YEAR, timeout: float = 240) -> None:
    x0, y0, x1, y1 = _tile_bounds(tx, ty)
    resp = httpx.get(CDL_URL, params={"year": year, "bbox": f"{x0},{y0},{x1},{y1}"}, timeout=timeout)
    resp.raise_for_status()
    m = re.search(r"<returnURL>(.*?)</returnURL>", resp.text)
    if not m:
        raise FuelUnavailable(f"CDL returned no file for tile {tx},{ty}")
    tif = httpx.get(m.group(1), timeout=timeout)
    tif.raise_for_status()
    path = _cdl_path(tx, ty, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tif.content)


_failed: dict[tuple[int, int], float] = {}


@lru_cache(maxsize=128)
def _nlcd_tile(tx: int, ty: int) -> Tile:
    if not _nlcd_path(tx, ty).exists():
        if time.monotonic() - _failed.get((tx, ty), -1e9) < RETRY_AFTER_S:
            raise FuelUnavailable("recent download failed")
        try:
            download_nlcd(tx, ty)
        except (httpx.HTTPError, FuelUnavailable) as e:
            _failed[(tx, ty)] = time.monotonic()
            raise FuelUnavailable(str(e)) from e
    return _read_tile(_nlcd_path(tx, ty).read_bytes())


@lru_cache(maxsize=128)
def _cdl_tile(tx: int, ty: int) -> Tile | None:
    """Only from cache: never downloads."""
    path = _cdl_path(tx, ty)
    return _read_tile(path.read_bytes()) if path.exists() else None


def _safe_nlcd(tx: int, ty: int) -> Tile | None:
    try:
        return _nlcd_tile(tx, ty)
    except (FuelUnavailable, OSError, ValueError, KeyError) as e:
        log.warning("NLCD tile %s,%s unavailable: %s", tx, ty, e)
        return None


def tiles_for(lats: np.ndarray, lons: np.ndarray) -> list[tuple[int, int]]:
    glon, glat = np.meshgrid([lons.min(), lons.max()], [lats.min(), lats.max()])
    x, y = _to_albers().transform(glon, glat)
    xs = range(int(np.floor(x.min() / TILE_M)), int(np.floor(x.max() / TILE_M)) + 1)
    ys = range(int(np.floor(y.min() / TILE_M)), int(np.floor(y.max() / TILE_M)) + 1)
    return [(a, b) for a in xs for b in ys]


def _sample(tile: Tile, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    col = np.clip(((x - tile.x0) / tile.res).astype(int), 0, tile.data.shape[1] - 1)
    row = np.clip(((tile.y0 - y) / tile.res).astype(int), 0, tile.data.shape[0] - 1)
    return tile.data[row, col]


@dataclass
class FuelGrid:
    multiplier: np.ndarray  # (n_lat, n_lon) spread multiplier per cell, 0 = does not burn
    fuel_class: np.ndarray  # (n_lat, n_lon) index into FUEL_KEYS (majority of the cell's samples)
    source: str
    complete: bool  # False when some tiles failed and fell back to grass


def uniform_grass(shape: tuple[int, int], source: str = "uniform grassland (no fuel map)") -> FuelGrid:
    return FuelGrid(np.ones(shape), np.full(shape, _K["grass"], dtype=np.int8), source, False)


def fuel_grid(lats: np.ndarray, lons: np.ndarray, month: int) -> FuelGrid:
    """Fuel multiplier for evenly spaced 1-D lat and lon axes. Missing tiles fall back to grass."""
    n_lat, n_lon, k = len(lats), len(lons), SUBSAMPLES
    off = (np.arange(k) + 0.5) / k - 0.5
    sub_lat = (lats[:, None] + off[None, :] * (lats[1] - lats[0])).ravel()
    sub_lon = (lons[:, None] + off[None, :] * (lons[1] - lons[0])).ravel()
    glon, glat = np.meshgrid(sub_lon, sub_lat)
    x, y = _to_albers().transform(glon, glat)
    tx = np.floor(x / TILE_M).astype(int)
    ty = np.floor(y / TILE_M).astype(int)

    cls = np.full(x.shape, _K["unknown"], dtype=np.int8)
    keys = sorted(set(zip(tx.ravel().tolist(), ty.ravel().tolist())))
    with ThreadPoolExecutor(max_workers=4) as pool:
        tiles = dict(zip(keys, pool.map(lambda key: _safe_nlcd(*key), keys)))
    complete, refined = True, 0
    for (a, b), tile in tiles.items():
        if tile is None:
            complete = False
            continue
        sel = (tx == a) & (ty == b)
        c = _NLCD_LUT[_sample(tile, x[sel], y[sel])]
        cdl = _cdl_tile(a, b)
        if cdl is not None:
            crop = c == _K["cropland"]
            c[crop] = _CDL_LUT[_sample(cdl, x[sel][crop], y[sel][crop])]
            refined += 1
        cls[sel] = c

    cls = cls.reshape(n_lat, k, n_lon, k)
    mult = multipliers(month)[cls].mean(axis=(1, 3))
    counts = np.stack([(cls == c).sum(axis=(1, 3)) for c in range(len(FUEL_KEYS))])
    source = "NLCD 2021 (30 m)"
    if refined:
        source += f" + USDA CDL {CDL_YEAR} cropland" + ("" if refined == len(keys) else " (partial)")
    if not complete:
        source += "; some tiles unavailable, assumed grass"
    return FuelGrid(mult, counts.argmax(axis=0).astype(np.int8), source, complete)


def fuel_mix(grid: FuelGrid, mask: np.ndarray) -> list[dict]:
    """Share of the masked cells by fuel class, largest first."""
    total = int(mask.sum())
    if total == 0:
        return []
    out = []
    for c, key in enumerate(FUEL_KEYS):
        n = int(((grid.fuel_class == c) & mask).sum())
        if n:
            out.append({"fuel": key, "label": FUELS[key][0], "pct": round(100 * n / total, 1)})
    return sorted(out, key=lambda r: -r["pct"])
