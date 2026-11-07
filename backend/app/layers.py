import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .config import DATA_DIR
from .geo import EARTH_RADIUS_KM, KM_PER_DEG_LAT, KM_PER_MILE, bearing_deg, compass, km_per_deg_lon

LAYER_NAMES = ("towns", "power_lines", "substations", "static_sources", "flint_hills", "distribution_lines", "wildfire_history", "counties")
DISTANCE_CAP_KM = 50.0


@lru_cache
def load_layer(name: str) -> dict:
    if name not in LAYER_NAMES:
        raise KeyError(name)
    with open(DATA_DIR / "layers" / f"{name}.geojson") as f:
        return json.load(f)


@dataclass
class Nearest:
    name: str | None
    distance_km: float
    props: dict
    lon: float | None = None
    lat: float | None = None


@dataclass(frozen=True)
class PointIndex:
    lons: np.ndarray
    lats: np.ndarray
    props: tuple[dict, ...]


@dataclass(frozen=True)
class SegmentIndex:
    """Every segment of every line, as parallel arrays of endpoints (lon/lat) and owning feature index."""
    ax: np.ndarray
    ay: np.ndarray
    bx: np.ndarray
    by: np.ndarray
    owner: np.ndarray
    props: tuple[dict, ...]


@lru_cache
def point_index(layer: str) -> PointIndex:
    feats = load_layer(layer)["features"]
    coords = np.array([f["geometry"]["coordinates"] for f in feats], dtype=float).reshape(-1, 2)
    return PointIndex(coords[:, 0], coords[:, 1], tuple(f["properties"] for f in feats))


@lru_cache
def segment_index() -> SegmentIndex:
    ax, ay, bx, by, owner = [], [], [], [], []
    feats = load_layer("power_lines")["features"]
    for i, feat in enumerate(feats):
        geom = feat["geometry"]
        lines = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
        for coords in lines:
            for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                ax.append(x1)
                ay.append(y1)
                bx.append(x2)
                by.append(y2)
                owner.append(i)
    arr = lambda v: np.array(v, dtype=float)  # noqa: E731
    return SegmentIndex(arr(ax), arr(ay), arr(bx), arr(by), np.array(owner, dtype=int), tuple(f["properties"] for f in feats))


def _haversine_np(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    p1, p2 = np.radians(lat), np.radians(lats)
    dp = p2 - p1
    dl = np.radians(lons - lon)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _nearest_point(layer: str, lat: float, lon: float) -> Nearest:
    idx = point_index(layer)
    if len(idx.lons) == 0:
        return Nearest(None, DISTANCE_CAP_KM, {})
    d = _haversine_np(lat, lon, idx.lats, idx.lons)
    i = int(d.argmin())
    if d[i] >= DISTANCE_CAP_KM:
        return Nearest(None, DISTANCE_CAP_KM, {})
    props = idx.props[i]
    return Nearest(props.get("name"), float(d[i]), props, float(idx.lons[i]), float(idx.lats[i]))


def segment_distances_km(lat: float, lon: float, seg: SegmentIndex) -> np.ndarray:
    """Point-to-segment distance for every segment, using a local equirectangular projection."""
    kx = km_per_deg_lon(lat)
    ax, ay = (seg.ax - lon) * kx, (seg.ay - lat) * KM_PER_DEG_LAT
    bx, by = (seg.bx - lon) * kx, (seg.by - lat) * KM_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(seg2 == 0, 0.0, np.clip(-(ax * dx + ay * dy) / seg2, 0.0, 1.0))
    return np.hypot(ax + t * dx, ay + t * dy)


def nearest_line(lat: float, lon: float) -> Nearest:
    seg = segment_index()
    if len(seg.ax) == 0:
        return Nearest(None, DISTANCE_CAP_KM, {})
    d = segment_distances_km(lat, lon, seg)
    i = int(d.argmin())
    if d[i] >= DISTANCE_CAP_KM:
        return Nearest(None, DISTANCE_CAP_KM, {})
    props = seg.props[seg.owner[i]]
    return Nearest(props.get("name"), float(d[i]), props)


def nearest_town(lat: float, lon: float) -> Nearest:
    return _nearest_point("towns", lat, lon)


def nearest_substation(lat: float, lon: float) -> Nearest:
    return _nearest_point("substations", lat, lon)


def nearest_static_source(lat: float, lon: float) -> Nearest:
    return _nearest_point("static_sources", lat, lon)


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def in_flint_hills(lat: float, lon: float) -> bool:
    return any(
        _point_in_ring(lon, lat, f["geometry"]["coordinates"][0])
        for f in load_layer("flint_hills")["features"]
    )


def place_label(lat: float, lon: float) -> tuple[str, str | None, str | None]:
    """Returns (label, nearest town, county), e.g. '8 mi SW of Ashland, Clark Co.'"""
    town = nearest_town(lat, lon)
    if town.name is None:
        return f"{lat:.3f}, {lon:.3f}", None, None
    county = town.props.get("county")
    county_txt = f", {county} Co." if county else ""
    miles = town.distance_km / KM_PER_MILE
    if miles < 1:
        return f"Near {town.name}{county_txt}", town.name, county
    direction = compass(bearing_deg(town.lat, town.lon, lat, lon))
    return f"{miles:.0f} mi {direction} of {town.name}{county_txt}", town.name, county


def nearest_assets(lat: float, lon: float, limit_km: float = 30.0) -> list[dict]:
    out = []
    for kind, n in (
        ("town", nearest_town(lat, lon)),
        ("power_line", nearest_line(lat, lon)),
        ("substation", nearest_substation(lat, lon)),
        ("static_source", nearest_static_source(lat, lon)),
    ):
        if n.name is not None and n.distance_km <= limit_km:
            out.append({"kind": kind, "name": n.name, "distance_km": round(n.distance_km, 2)})
    return sorted(out, key=lambda a: a["distance_km"])
