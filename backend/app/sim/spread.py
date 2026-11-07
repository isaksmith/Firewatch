"""Grass-fire spread: arrival-time grid + isochrones. See docs/DESIGN.md section 6.

The grid is built once per forecast (`build_domain`: extent, terrain, fuel map) and fire is then
propagated over it (`propagate`) with weather that can change during the run, so an ensemble can
reuse one domain for many members.
"""

import heapq
import math
from dataclasses import dataclass, field

import contourpy
import numpy as np

from ..fire_weather import head_ros_kmh, length_to_breadth
from ..geo import KM_PER_DEG_LAT, km_per_deg_lon
from ..layers import point_index, segment_index
from ..terrain import TerrainUnavailable, elevation_grid
from .fuels import FuelGrid, fuel_grid, fuel_mix, uniform_grass

GRID_N = 200
STEP_MINUTES = 5
WEATHER_BLOCK_MIN = 10  # spread rates are recomputed from the weather every 10 minutes
MAX_SLOPE_DEG = 20.0
# Point-ignition acceleration toward the equilibrium rate, ROS(t) = ROS * (1 - exp(-a t)), with
# a = 0.115 / min for open fuels (Canadian FBP System, Forestry Canada Fire Danger Group 1992).
ACCEL_PER_MIN = 0.115
NEIGHBORS = [
    (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1),
    (1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1),
]


@dataclass
class WeatherStep:
    t_min: float  # minutes after the forecast start; values in between are interpolated
    wind_kmh: float
    wind_from_deg: float
    temp_c: float
    rh_pct: float


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
    weather: list[WeatherStep] | None = None  # overrides the scalar weather fields when given
    use_fuel: bool = False
    month: int = 3  # selects the fuel season
    fire_age_min: float | None = None  # None = established fire; 0 = new point ignition (accelerates)
    grid_n: int = GRID_N


@dataclass
class Domain:
    lats: np.ndarray
    lons: np.ndarray
    n: int
    cell_m: float
    elev: np.ndarray | None
    fuel: FuelGrid
    terrain_note: str
    # Per neighbor, flat (N*N) multiplier for moving INTO each cell: fuel there x slope of the step.
    step_mult: list[list[float]] = field(default_factory=list)


def interp_weather(steps: list[WeatherStep], t: float) -> WeatherStep:
    """Linear in time; wind direction interpolated along the shorter arc."""
    if t <= steps[0].t_min:
        return steps[0]
    if t >= steps[-1].t_min:
        return steps[-1]
    k = next(i for i in range(1, len(steps)) if steps[i].t_min >= t)
    a, b = steps[k - 1], steps[k]
    w = (t - a.t_min) / (b.t_min - a.t_min) if b.t_min > a.t_min else 0.0
    d = (b.wind_from_deg - a.wind_from_deg + 180) % 360 - 180
    return WeatherStep(
        t, a.wind_kmh + w * (b.wind_kmh - a.wind_kmh), (a.wind_from_deg + w * d) % 360,
        a.temp_c + w * (b.temp_c - a.temp_c), a.rh_pct + w * (b.rh_pct - a.rh_pct),
    )


def weather_steps(inp: SpreadInput) -> list[WeatherStep]:
    if inp.weather:
        return sorted(inp.weather, key=lambda s: s.t_min)
    return [WeatherStep(0.0, inp.wind_kmh, inp.wind_from_deg, inp.temp_c, inp.rh_pct)]


def _blocks(steps: list[WeatherStep], minutes: int) -> list[WeatherStep]:
    """Weather at the middle of each WEATHER_BLOCK_MIN block of the run."""
    n = math.ceil(minutes / WEATHER_BLOCK_MIN) + 1
    return [interp_weather(steps, (b + 0.5) * WEATHER_BLOCK_MIN) for b in range(n)]


def build_domain(inp: SpreadInput, blocks: list[WeatherStep], max_ros_kmh: float) -> Domain:
    """Grid sized so the fastest plausible run stays in frame, shifted toward the mean downwind side."""
    run_km = max_ros_kmh * inp.minutes / 60
    ux = sum(math.sin(math.radians(b.wind_from_deg + 180)) for b in blocks) / len(blocks)
    uy = sum(math.cos(math.radians(b.wind_from_deg + 180)) for b in blocks) / len(blocks)
    steady = math.hypot(ux, uy)  # 1 = wind never changes direction, 0 = it swings all the way round
    half_km = max(6.0, run_km * (1 - 0.4 * steady) + 2.0)
    kx, ky = km_per_deg_lon(inp.lat), KM_PER_DEG_LAT
    c_lat = inp.lat + 0.4 * run_km * uy / ky
    c_lon = inp.lon + 0.4 * run_km * ux / kx
    n = inp.grid_n
    lats = np.linspace(c_lat - half_km / ky, c_lat + half_km / ky, n)
    lons = np.linspace(c_lon - half_km / kx, c_lon + half_km / kx, n)
    cell_m = 2 * half_km * 1000 / (n - 1)

    terrain_note = "flat (terrain disabled)"
    elev = None
    if inp.use_terrain:
        try:
            elev = elevation_grid(lats, lons)
            terrain_note = "AWS Terrain Tiles z12"
        except TerrainUnavailable:
            terrain_note = "flat (terrain tiles unavailable)"

    fuel = fuel_grid(lats, lons, inp.month) if inp.use_fuel else uniform_grass((n, n))
    dom = Domain(lats, lons, n, cell_m, elev, fuel, terrain_note)
    dom.step_mult = _step_multipliers(dom)
    return dom


def _step_multipliers(dom: Domain) -> list[list[float]]:
    n = dom.n
    out = []
    for di, dj in NEIGHBORS:
        mult = dom.fuel.multiplier.copy()
        if dom.elev is not None:
            # slope of the step that arrives at each cell, from the cell it came from
            src = np.full((n, n), np.nan)
            si = slice(max(0, -di), n - max(0, di))
            sj = slice(max(0, -dj), n - max(0, dj))
            ti = slice(max(0, di), n - max(0, -di))
            tj = slice(max(0, dj), n - max(0, -dj))
            src[ti, tj] = dom.elev[si, sj]
            dist = math.hypot(di, dj) * dom.cell_m
            slope = np.degrees(np.arctan2(dom.elev - np.nan_to_num(src, nan=0.0), dist))
            slope = np.where(np.isnan(src), 0.0, np.clip(slope, -MAX_SLOPE_DEG, MAX_SLOPE_DEG))
            mult = mult * np.exp(0.069 * slope)
        out.append(mult.ravel().tolist())
    return out


def block_rates(blocks: list[WeatherStep], curing_pct: float, wind_scale: float = 1.0,
                dir_offset: float = 0.0, rh_offset: float = 0.0) -> tuple[list[list[float]], list[float]]:
    """Per block: spread rate (m/min, before fuel and slope) along each neighbor step; and head ROS (km/h)."""
    rates, heads = [], []
    for b in blocks:
        wind = b.wind_kmh * wind_scale
        rh = max(b.rh_pct + rh_offset, 3.0)
        ros = head_ros_kmh(wind, b.temp_c, rh, curing_pct)
        lb = length_to_breadth(wind)
        ecc = math.sqrt(1 - 1 / lb**2)
        downwind = math.radians((b.wind_from_deg + dir_offset + 180) % 360)
        head_m_min = ros * 1000 / 60
        row = []
        for di, dj in NEIGHBORS:
            cos_t = math.cos(math.atan2(dj, di) - downwind)  # i = north (lat index), j = east (lon index)
            row.append(head_m_min * (1 - ecc) / (1 - ecc * cos_t))
        rates.append(row)
        heads.append(ros)
    return rates, heads


def propagate(dom: Domain, rates: list[list[float]], ignitions: list[tuple[float, float]], minutes: int,
              fire_age_min: float | None) -> np.ndarray:
    """Dijkstra over a 16-neighbor stencil with time-dependent rates. Returns arrival minutes (inf = unburned)."""
    n = dom.n
    arrival = [math.inf] * (n * n)
    heap: list[tuple[float, int]] = []
    for ilat, ilon in ignitions:
        i = int(np.clip(np.searchsorted(dom.lats, ilat), 0, n - 1))
        j = int(np.clip(np.searchsorted(dom.lons, ilon), 0, n - 1))
        arrival[i * n + j] = 0.0
        heap.append((0.0, i * n + j))
    heapq.heapify(heap)

    steps = [(di, dj, di * n + dj, math.hypot(di, dj) * dom.cell_m) for di, dj in NEIGHBORS]
    mult = dom.step_mult
    last_block = len(rates) - 1
    age = fire_age_min
    limit = float(minutes)
    while heap:
        t, idx = heapq.heappop(heap)
        if t > arrival[idx] or t > limit:
            continue
        i, j = divmod(idx, n)
        row = rates[min(int(t // WEATHER_BLOCK_MIN), last_block)]
        accel = 1.0
        if age is not None and t + age < 40:
            accel = 1 - math.exp(-ACCEL_PER_MIN * (t + age + 1.0))
        for k, (di, dj, didx, dist) in enumerate(steps):
            ni, nj = i + di, j + dj
            if ni < 0 or ni >= n or nj < 0 or nj >= n:
                continue
            nidx = idx + didx
            rate = row[k] * mult[k][nidx]
            if rate <= 0:
                continue
            dt = dist / (rate * accel)
            if accel < 1.0:  # re-evaluate acceleration at the middle of the step
                dt = dist / (rate * (1 - math.exp(-ACCEL_PER_MIN * (t + age + dt / 2))))
            nt = t + dt
            if nt < arrival[nidx]:
                arrival[nidx] = nt
                heapq.heappush(heap, (nt, nidx))
    return np.array(arrival).reshape(n, n)


def simulate(inp: SpreadInput) -> dict:
    steps = weather_steps(inp)
    blocks = _blocks(steps, inp.minutes)
    rates, heads = block_rates(blocks, inp.curing_pct)
    dom = build_domain(inp, blocks, max(heads))
    arrival = propagate(dom, rates, inp.ignitions or [(inp.lat, inp.lon)], inp.minutes, inp.fire_age_min)
    first = interp_weather(steps, 0.0)
    return {
        "assumptions": assumptions(inp, first, dom, steps),
        "head_ros_kmh": round(heads[0], 2),
        "length_to_breadth": round(length_to_breadth(first.wind_kmh), 2),
        "isochrones": isochrones(arrival, dom, inp.minutes),
        "impacts": impacts(arrival, dom.lats, dom.lons, inp.minutes),
        "fuel_mix": fuel_mix(dom.fuel, arrival <= inp.minutes),
        "wind_vector": {"from_deg": round(first.wind_from_deg % 360), "kmh": round(first.wind_kmh, 1)},
        "grid": {"cell_m": round(dom.cell_m, 1), "n": dom.n},
    }


def assumptions(inp: SpreadInput, first: WeatherStep, dom: Domain, steps: list[WeatherStep]) -> dict:
    return {
        "wind_kmh": round(first.wind_kmh, 1),
        "wind_from_deg": round(first.wind_from_deg % 360),
        "temp_c": round(first.temp_c, 1),
        "rh_pct": round(first.rh_pct),
        "curing_pct": round(inp.curing_pct),
        "weather": "constant" if len(steps) == 1 else f"time-varying ({len(steps)} steps)",
        "fuel": dom.fuel.source,
        "ignition": "established fire" if inp.fire_age_min is None else "new point ignition (accelerating)",
        "model": "CSIRO grassland + elliptical + slope + fuel map",
        "terrain": dom.terrain_note,
    }


def isochrones(arrival: np.ndarray, dom: Domain, minutes: int, step: int = STEP_MINUTES) -> dict:
    gen = _contours(arrival, dom)
    cell_ha = (dom.cell_m**2) / 10_000
    features = []
    for m in range(step, minutes + 1, step):
        rings = _rings(gen, m)
        if not rings:
            continue
        features.append({
            "type": "Feature",
            "properties": {"minutes": m, "area_ha": round(float((arrival <= m).sum()) * cell_ha, 1)},
            "geometry": {"type": "MultiPolygon", "coordinates": rings},
        })
    return {"type": "FeatureCollection", "features": features}


def _contours(z: np.ndarray, dom: Domain):
    z = np.where(np.isfinite(z), z, 1e6)
    return contourpy.contour_generator(dom.lons, dom.lats, z, line_type=contourpy.LineType.Separate)


def _rings(gen, level: float) -> list:
    rings = []
    for line in gen.lines(level):
        if len(line) < 4:
            continue
        coords = [[round(float(x), 6), round(float(y), 6)] for x, y in line]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        rings.append([coords])
    return rings


def _arrival_many(arrival: np.ndarray, lats: np.ndarray, lons: np.ndarray, plat: np.ndarray, plon: np.ndarray) -> np.ndarray:
    """Arrival minutes at many points (nearest cell); inf outside the grid. Assumes evenly spaced axes."""
    i = np.rint((plat - lats[0]) / (lats[1] - lats[0])).astype(int)
    j = np.rint((plon - lons[0]) / (lons[1] - lons[0])).astype(int)
    ok = (i >= 0) & (i < len(lats)) & (j >= 0) & (j < len(lons))
    out = np.full(plat.shape, np.inf)
    out[ok] = arrival[i[ok], j[ok]]
    return out


def impacts(arrival: np.ndarray, lats: np.ndarray, lons: np.ndarray, minutes: int) -> list[dict]:
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
