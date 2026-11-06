import json
from dataclasses import dataclass
from functools import lru_cache

from .config import DATA_DIR
from .geo import KM_PER_MILE, bearing_deg, compass, haversine_km, point_segment_km

LAYER_NAMES = ("towns", "power_lines", "substations", "static_sources", "flint_hills")
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


def _nearest_point(layer: str, lat: float, lon: float) -> Nearest:
    best = Nearest(None, DISTANCE_CAP_KM, {})
    for feat in load_layer(layer)["features"]:
        x, y = feat["geometry"]["coordinates"]
        d = haversine_km(lat, lon, y, x)
        if d < best.distance_km:
            best = Nearest(feat["properties"].get("name"), d, feat["properties"])
    return best


def _line_segments(feat: dict):
    geom = feat["geometry"]
    lines = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
    for coords in lines:
        for a, b in zip(coords, coords[1:]):
            yield a, b


def nearest_line(lat: float, lon: float) -> Nearest:
    best = Nearest(None, DISTANCE_CAP_KM, {})
    for feat in load_layer("power_lines")["features"]:
        for a, b in _line_segments(feat):
            d = point_segment_km(lat, lon, a, b)
            if d < best.distance_km:
                best = Nearest(feat["properties"].get("name"), d, feat["properties"])
    return best


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
    tx, ty = None, None
    for feat in load_layer("towns")["features"]:
        if feat["properties"].get("name") == town.name:
            tx, ty = feat["geometry"]["coordinates"]
            break
    direction = compass(bearing_deg(ty, tx, lat, lon))
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
