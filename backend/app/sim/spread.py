"""Simplified grass-fire spread: arrival-time grid + isochrones. See docs/DESIGN.md section 6."""

import heapq
import math
from dataclasses import dataclass

import contourpy
import numpy as np

from ..fire_weather import head_ros_kmh, length_to_breadth
from ..geo import KM_PER_DEG_LAT, km_per_deg_lon
from ..layers import point_index, segment_index
from ..terrain import TerrainUnavailable, elevation_grid

GRID_N = 200
STEP_MINUTES = 5
MAX_SLOPE_DEG = 20.0
NEIGHBORS = [
    (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1),
    (1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1),
]


@dataclass
class SpreadInput:
    lat: float
    lon: float
    wind_kmh: float
    wind_from_deg: float
    temp_c: float
    rh_pct: float
    curing_pct: float
    minutes: int = 60
    ignitions: list[tuple[float, float]] | None = None  # (lat, lon)
    use_terrain: bool = True


@dataclass
class Grid:
    arrival: np.ndarray  # minutes since ignition; inf where the fire does not reach within the run
    lats: np.ndarray
    lons: np.ndarray
    cell_m: float
    ros_kmh: float
    lb: float
    terrain_note: str


def simulate(inp: SpreadInput, points: list[tuple[float, float]] | None = None) -> dict:
    """Isochrones and impacts. `points` (lat, lon) adds `point_minutes`: arrival at each, None if not reached."""
    g = arrival_grid(inp)
    out = {
        "assumptions": {
            "wind_kmh": round(inp.wind_kmh, 1),
            "wind_from_deg": round(inp.wind_from_deg % 360),
            "temp_c": round(inp.temp_c, 1),
            "rh_pct": round(inp.rh_pct),
            "curing_pct": round(inp.curing_pct),
            "fuel": "grassland",
            "model": "CSIRO grassland + elliptical + slope",
            "terrain": g.terrain_note,
        },
        "head_ros_kmh": round(g.ros_kmh, 2),
        "length_to_breadth": round(g.lb, 2),
        "isochrones": _isochrones(g.arrival, g.lats, g.lons, inp.minutes, g.cell_m),
        "impacts": _impacts(g.arrival, g.lats, g.lons, inp.minutes),
        "wind_vector": {"from_deg": round(inp.wind_from_deg % 360), "kmh": round(inp.wind_kmh, 1)},
        "grid": {"cell_m": round(g.cell_m, 1), "n": GRID_N},
    }
    if points is not None:
        t = _arrival_many(g.arrival, g.lats, g.lons, np.array([p[0] for p in points]), np.array([p[1] for p in points]))
        out["point_minutes"] = [round(float(x), 1) if x <= inp.minutes else None for x in t]
    return out


def growth_curve(inp: SpreadInput) -> list[dict]:
    """Burned area and head-fire distance from ignition at each whole minute up to inp.minutes."""
    g = arrival_grid(inp)
    kx, ky = km_per_deg_lon(inp.lat), KM_PER_DEG_LAT
    yy, xx = np.meshgrid((g.lats - inp.lat) * ky, (g.lons - inp.lon) * kx, indexing="ij")
    dist = np.hypot(yy, xx)
    cell_ha = g.cell_m**2 / 10_000
    out = []
    for m in range(inp.minutes + 1):
        burned = g.arrival <= m
        out.append({
            "minute": m,
            "area_ha": round(float(burned.sum()) * cell_ha, 1),
            "head_km": round(float(dist[burned].max()) if burned.any() else 0.0, 2),
        })
    return out


def arrival_grid(inp: SpreadInput) -> Grid:
    ros_kmh = head_ros_kmh(inp.wind_kmh, inp.temp_c, inp.rh_pct, inp.curing_pct)
    lb = length_to_breadth(inp.wind_kmh)
    ecc = math.sqrt(1 - 1 / lb**2)
    downwind = math.radians((inp.wind_from_deg + 180) % 360)
    run_km = ros_kmh * inp.minutes / 60

    half_km = max(6.0, 0.6 * run_km + 2.0)
    shift_km = 0.4 * run_km
    kx, ky = km_per_deg_lon(inp.lat), KM_PER_DEG_LAT
    c_lat = inp.lat + shift_km * math.cos(downwind) / ky
    c_lon = inp.lon + shift_km * math.sin(downwind) / kx
    lats = np.linspace(c_lat - half_km / ky, c_lat + half_km / ky, GRID_N)
    lons = np.linspace(c_lon - half_km / kx, c_lon + half_km / kx, GRID_N)
    cell_m = 2 * half_km * 1000 / (GRID_N - 1)

    terrain_note = "flat (terrain disabled)"
    elev = None
    if inp.use_terrain:
        try:
            elev = elevation_grid(lats, lons)
            terrain_note = "AWS Terrain Tiles z12"
        except TerrainUnavailable:
            terrain_note = "flat (terrain tiles unavailable)"

    head_m_per_min = ros_kmh * 1000 / 60
    dir_ros = []
    for di, dj in NEIGHBORS:
        bearing = math.atan2(dj, di)  # i = north (lat index), j = east (lon index)
        cos_t = math.cos(bearing - downwind)
        ros = head_m_per_min * (1 - ecc) / (1 - ecc * cos_t)
        dir_ros.append((di, dj, math.hypot(di, dj) * cell_m, ros))

    arrival = np.full((GRID_N, GRID_N), np.inf)
    heap: list[tuple[float, int, int]] = []
    for ilat, ilon in inp.ignitions or [(inp.lat, inp.lon)]:
        i = int(np.clip(np.searchsorted(lats, ilat), 0, GRID_N - 1))
        j = int(np.clip(np.searchsorted(lons, ilon), 0, GRID_N - 1))
        arrival[i, j] = 0.0
        heap.append((0.0, i, j))
    heapq.heapify(heap)

    limit = float(inp.minutes)
    while heap:
        t, i, j = heapq.heappop(heap)
        if t > arrival[i, j] or t > limit:
            continue
        for di, dj, dist, ros in dir_ros:
            ni, nj = i + di, j + dj
            if not (0 <= ni < GRID_N and 0 <= nj < GRID_N):
                continue
            rate = ros
            if elev is not None:
                slope = math.degrees(math.atan2(elev[ni, nj] - elev[i, j], dist))
                rate *= math.exp(0.069 * max(-MAX_SLOPE_DEG, min(MAX_SLOPE_DEG, slope)))
            if rate <= 0:  # fire cannot spread at rate 0
                continue
            nt = t + dist / rate
            if nt < arrival[ni, nj]:
                arrival[ni, nj] = nt
                heapq.heappush(heap, (nt, ni, nj))

    return Grid(arrival, lats, lons, cell_m, ros_kmh, lb, terrain_note)


def _isochrones(arrival: np.ndarray, lats: np.ndarray, lons: np.ndarray, minutes: int, cell_m: float) -> dict:
    z = np.where(np.isfinite(arrival), arrival, 1e6)
    gen = contourpy.contour_generator(lons, lats, z, line_type=contourpy.LineType.Separate)
    cell_ha = (cell_m**2) / 10_000
    features = []
    for m in range(STEP_MINUTES, minutes + 1, STEP_MINUTES):
        rings = []
        for line in gen.lines(m):
            if len(line) < 4:
                continue
            coords = [[round(float(x), 6), round(float(y), 6)] for x, y in line]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            rings.append([coords])
        if not rings:
            continue
        features.append({
            "type": "Feature",
            "properties": {"minutes": m, "area_ha": round(float((arrival <= m).sum()) * cell_ha, 1)},
            "geometry": {"type": "MultiPolygon", "coordinates": rings},
        })
    return {"type": "FeatureCollection", "features": features}


def _arrival_many(arrival: np.ndarray, lats: np.ndarray, lons: np.ndarray, plat: np.ndarray, plon: np.ndarray) -> np.ndarray:
    """Arrival minutes at many points (nearest cell); inf outside the grid. Assumes evenly spaced axes."""
    i = np.rint((plat - lats[0]) / (lats[1] - lats[0])).astype(int)
    j = np.rint((plon - lons[0]) / (lons[1] - lons[0])).astype(int)
    ok = (i >= 0) & (i < len(lats)) & (j >= 0) & (j < len(lons))
    out = np.full(plat.shape, np.inf)
    out[ok] = arrival[i[ok], j[ok]]
    return out


def _impacts(arrival: np.ndarray, lats: np.ndarray, lons: np.ndarray, minutes: int) -> list[dict]:
    out = []
    for kind, layer in (("town", "towns"), ("substation", "substations")):
        idx = point_index(layer)
        if len(idx.lons) == 0:
            continue
        t = _arrival_many(arrival, lats, lons, idx.lats, idx.lons)
        for k in np.nonzero(t <= minutes)[0]:
            props = idx.props[k]
            out.append({"kind": kind, "id": props.get("id", props["name"]), "name": props["name"], "minutes": round(float(t[k]))})

    seg = segment_index()
    lo_x, hi_x, lo_y, hi_y = lons[0], lons[-1], lats[0], lats[-1]
    near = (
        (np.maximum(seg.ax, seg.bx) >= lo_x) & (np.minimum(seg.ax, seg.bx) <= hi_x)
        & (np.maximum(seg.ay, seg.by) >= lo_y) & (np.minimum(seg.ay, seg.by) <= hi_y)
    )
    if near.any():
        s = np.linspace(0, 1, 200)[None, :]
        ax, ay, bx, by = (v[near][:, None] for v in (seg.ax, seg.ay, seg.bx, seg.by))
        t = _arrival_many(arrival, lats, lons, ay + s * (by - ay), ax + s * (bx - ax)).min(axis=1)
        best: dict[int, float] = {}
        for owner, tt in zip(seg.owner[near], t):
            best[owner] = min(best.get(owner, math.inf), float(tt))
        for owner, tt in best.items():
            if tt <= minutes:
                props = seg.props[owner]
                out.append({"kind": "power_line", "id": props.get("id", props["name"]), "name": props["name"], "minutes": round(tt)})
    return sorted(out, key=lambda a: a["minutes"])
