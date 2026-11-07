"""Region planner: where to put a mixed bare/rich sensor network, its relays, and the station bridge.

The design is sensors/README.md (bare and rich node tiers, the illustrative seven-bare/two-rich mix per
15-acre planning plot, separately powered repeaters, one station bridge) sited with the region's own
geography and climate. docs/DESIGN.md section 5.9 has the reasoning; in short:

1. Grid the region and score each cell for how likely a wildfire starts there (reported wildfire history,
   satellite-detected burning, transmission lines and substations, towns) and how much it matters
   (towns downwind under fire-weather winds), with tallgrass counted as heavier fuel.
2. A sensor only smells a fire it is downwind of, so a site's catchment is a wedge upwind of it, weighted
   by the fire-weather wind rose. Greedily pick plot sites that cover the most priority.
3. Lay out each plot's bare and rich nodes on its downwind edges, one rich node per fire-wind mode.
4. Connect every plot to the station through elevators, water towers, substations, or high ground, with a
   terrain line-of-sight check per link, adding as few relays as it can.

Detection distances are planning assumptions, not measurements: the README says the nodes have no proven
detection radius. Every assumption is in PARAMS and returned with the plan, so field trials can replace them.
"""

import heapq
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import pairwise

import numpy as np

from . import climate as climate_mod
from .config import DATA_DIR
from .district import DISTRICTS_DIR
from .geo import KM_PER_DEG_LAT, KM_PER_MILE, compass, haversine_km, km_per_deg_lon
from .layers import (
    in_flint_hills,
    load_layer,
    nearest_static_source,
    nearest_substation,
    nearest_town,
    place_label,
    segment_index,
)
from .terrain import TerrainUnavailable, elevation_grid

PARAMS = {
    "sites": 10,  # plots; sensors/README.md's county example is 70 bare + 20 rich = 10 plots of 7 + 2
    "bare_per_site": 7,
    "rich_per_site": 2,
    "plot_acres": 15.0,
    "site_min_sep_km": 3.0,
    "rich_range_km": 3.0,  # PM sensor catches smoke this far downwind (hardware-pricing.txt says 3-5 km)
    "rich_half_angle_deg": 20.0,  # plume half-width either side of the wind direction
    "rich_catch": 0.8,  # chance a rich node in the plume catches it (sampling gaps, plume meander)
    "bare_fetch_km": 0.4,  # gas head catches fires this far upwind of the plot (Dryad spaces 100 m)
    "budget_usd": None,
}
COSTS = {"bare": 175, "rich": 240, "relay": 105, "station": 45}
CUSTOM_PCB = {"bare": 130.5, "rich": 197.5}  # midpoints of the README's ~100-unit estimates
SPARES = 0.10

WEIGHTS = {"history": 0.30, "burns": 0.25, "lines": 0.25, "people": 0.20}
TALLGRASS_FUEL, MIXED_FUEL = 1.0, 0.7
HISTORY_SIGMA_KM = 4.0
BURN_SIGMA_KM = 3.0
LINE_SCALE_KM, SUBSTATION_SCALE_KM, TOWN_SCALE_KM = 1.0, 1.5, 3.0
DOWNWIND_TOWN_KM = 12.0
MAX_CELLS = 2500
CANDIDATES = 400

# Mesh links, by mount class. Ranges are hardware-pricing.txt's planning figures; terrain is checked separately.
MOUNTS = {"tower": 30.0, "mast": 10.0, "ground": 2.0}
RANGE_KM = {
    ("tower", "tower"): 25.0, ("mast", "tower"): 15.0, ("mast", "mast"): 10.0,
    ("ground", "tower"): 7.0, ("ground", "mast"): 5.0, ("ground", "ground"): 3.0,
}
RELAY_COST = {"town": 1.0, "substation": 1.1, "high_point": 1.4, "site_mast": 1.6}
HOP_COST = 0.15
HOP_LIMIT = 3  # Meshtastic default
TERRAIN_ZOOM = 10  # ~150 m pixels: enough for 250 m line-of-sight steps, and a county is a few dozen tiles
FREQ_GHZ = 0.915
K_FACTOR = 4 / 3
EARTH_R_KM = 6371.0

# Energy, from sensors/README.md. Base load is an assumption until the bench trial measures it.
PANEL_W = {"bare": 2.0, "rich": 5.0}
PACK_WH = {"bare": 16.3, "rich": 24.4}
BASE_WH_DAY = 1.5
PM_WH_DAY_CONTINUOUS = 12.0
PM_DUTY = 0.25
SOLAR_YIELD = 0.6
USABLE_PACK = 0.8

ASSUMPTIONS = [
    (
        "Detection distances are planning figures: no FireWatch node has a measured detection radius yet. "
        "Replace rich_range_km and bare_fetch_km with the detection trial's results."
    ),
    (
        "Power lines are OpenStreetMap transmission lines (115 kV and up). Distribution feeders, which start most "
        "line fires, aren't public: load the co-op's feeder map before a real site assessment."
    ),
    (
        "Reported wildfire history is NIFC WFIGS, which misses most small Kansas fires; satellite-detected burning "
        "fills some of that gap but mixes in prescribed and crop burns."
    ),
    (
        "Radio ranges are flat-ground planning figures checked against ~150 m terrain; trees, buildings, and "
        "grain bins aren't modeled. Survey every link at the real mount height before buying."
    ),
    f"Node base load is assumed at {BASE_WH_DAY} Wh/day until measured; PM draw is the README's 0.5 W.",
]


@dataclass
class Region:
    key: str
    name: str
    kind: str
    rings: list[list[tuple[float, float]]]
    station: dict | None = None
    settings: dict = field(default_factory=dict)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        pts = [p for r in self.rings for p in r]
        return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)

    def geojson(self) -> dict:
        return {
            "type": "Feature",
            "properties": {"name": self.name, "kind": self.kind},
            "geometry": {"type": "MultiPolygon", "coordinates": [[[list(p) for p in r]] for r in self.rings]},
        }


def _rings(geom: dict) -> list[list[tuple[float, float]]]:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return [[tuple(p[:2]) for p in poly[0]] for poly in polys]


@lru_cache
def _counties() -> dict:
    return json.loads((DATA_DIR / "layers" / "counties.geojson").read_text())


def list_regions() -> dict:
    districts = []
    for d in sorted(DISTRICTS_DIR.iterdir()):
        if (d / "boundary.geojson").exists():
            settings = json.loads((d / "settings.json").read_text())
            districts.append({"key": f"district:{d.name}", "name": settings.get("name", d.name)})
    counties = [
        {"key": f"county:{f['properties']['name']}", "name": f"{f['properties']['name']} County"}
        for f in _counties()["features"]
    ]
    return {"districts": districts, "counties": counties}


def resolve_region(key: str, geometry: dict | None = None) -> Region:
    if geometry is not None:
        geom = geometry.get("geometry", geometry)
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("geometry must be a Polygon or MultiPolygon")
        return Region("custom", geometry.get("properties", {}).get("name", "Custom area"), "custom", _rings(geom))
    kind, _, name = key.partition(":")
    if kind == "district":
        d = DISTRICTS_DIR / name
        if not (d / "boundary.geojson").exists():
            raise KeyError(key)
        settings = json.loads((d / "settings.json").read_text())
        boundary = json.loads((d / "boundary.geojson").read_text())
        rings = [r for f in boundary["features"] for r in _rings(f["geometry"])]
        return Region(key, settings.get("name", name), "district", rings, settings.get("station"), settings)
    if kind == "county":
        for f in _counties()["features"]:
            if f["properties"]["name"].lower() == name.lower():
                return Region(key, f"{f['properties']['name']} County", "county", _rings(f["geometry"]))
    raise KeyError(key)


# ---------------------------------------------------------------- local plane

@dataclass(frozen=True)
class Plane:
    lon0: float
    lat0: float

    @property
    def kx(self) -> float:
        return km_per_deg_lon(self.lat0)

    def xy(self, lon, lat):
        return (np.asarray(lon) - self.lon0) * self.kx, (np.asarray(lat) - self.lat0) * KM_PER_DEG_LAT

    def lonlat(self, x, y):
        return self.lon0 + np.asarray(x) / self.kx, self.lat0 + np.asarray(y) / KM_PER_DEG_LAT


def _inside(lons: np.ndarray, lats: np.ndarray, rings) -> np.ndarray:
    out = np.zeros(lons.shape, dtype=bool)
    for ring in rings:
        hit = np.zeros(lons.shape, dtype=bool)
        for (x1, y1), (x2, y2) in pairwise(ring):
            if y1 == y2:
                continue
            crosses = (y1 > lats) != (y2 > lats)
            xint = (x2 - x1) * (lats - y1) / (y2 - y1) + x1
            hit ^= crosses & (lons < xint)
        out |= hit
    return out


def _bearing(dx, dy):
    return (np.degrees(np.arctan2(dx, dy)) + 360.0) % 360.0


def _angle_diff(a, b):
    return np.abs((a - b + 180.0) % 360.0 - 180.0)


def _norm(v: np.ndarray) -> np.ndarray:
    ref = np.percentile(v, 95) if v.size else 0
    return np.clip(v / ref, 0, 1) if ref > 0 else np.zeros_like(v)


# ---------------------------------------------------------------- layers

@lru_cache
def _wildfires() -> list[dict]:
    feats = json.loads((DATA_DIR / "layers" / "wildfire_history.geojson").read_text())["features"]
    return [
        {**f["properties"], "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
        for f in feats
    ]


@lru_cache
def _burn_cells() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    d = json.loads((DATA_DIR / "layers" / "burn_activity.json").read_text())
    c = np.array(d["cells"], dtype=float).reshape(-1, 4)
    lat0, lon0 = d["origin"]
    lats = lat0 + (c[:, 0] + 0.5) * d["cell_deg"]
    lons = lon0 + (c[:, 1] + 0.5) * d["cell_deg"]
    return lons, lats, c[:, 2], c[:, 3], d["years"]


def _points(layer: str):
    feats = load_layer(layer)["features"]
    return [(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1], f["properties"]) for f in feats]


def _segments_xy(plane: Plane, bbox, pad_deg: float = 0.1):
    seg = segment_index()
    w, s, e, n = bbox
    keep = (
        (np.maximum(seg.ax, seg.bx) >= w - pad_deg) & (np.minimum(seg.ax, seg.bx) <= e + pad_deg)
        & (np.maximum(seg.ay, seg.by) >= s - pad_deg) & (np.minimum(seg.ay, seg.by) <= n + pad_deg)
    )
    ax, ay = plane.xy(seg.ax[keep], seg.ay[keep])
    bx, by = plane.xy(seg.bx[keep], seg.by[keep])
    return ax, ay, bx, by, [seg.props[i] for i in seg.owner[keep]]


def _seg_dist(px, py, ax, ay, bx, by):
    """Distance from each point (N) to each segment (M): returns (N, M) distances and the nearest point."""
    px, py = px[:, None], py[:, None]
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(seg2 == 0, 0.0, np.clip(((px - ax) * dx + (py - ay) * dy) / seg2, 0, 1))
    cx, cy = ax + t * dx, ay + t * dy
    return np.hypot(px - cx, py - cy), cx, cy


# ---------------------------------------------------------------- grid and risk

@dataclass
class Grid:
    plane: Plane
    cell_km: float
    x: np.ndarray
    y: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    comps: dict = field(default_factory=dict)
    likelihood: np.ndarray | None = None
    consequence: np.ndarray | None = None
    priority: np.ndarray | None = None
    line_dist: np.ndarray | None = None
    line_near: tuple | None = None
    line_name: list | None = None


def build_grid(region: Region) -> Grid:
    w, s, e, n = region.bbox
    plane = Plane((w + e) / 2, (s + n) / 2)
    x0, y0 = plane.xy(w, s)
    x1, y1 = plane.xy(e, n)
    probe = 0.5
    xs, ys = np.arange(x0 + probe / 2, x1, probe), np.arange(y0 + probe / 2, y1, probe)
    gx, gy = np.meshgrid(xs, ys)
    lon, lat = plane.lonlat(gx.ravel(), gy.ravel())
    area = _inside(lon, lat, region.rings).sum() * probe * probe
    cell = max(1.0, math.ceil(math.sqrt(area / MAX_CELLS) * 4) / 4)
    xs, ys = np.arange(x0 + cell / 2, x1, cell), np.arange(y0 + cell / 2, y1, cell)
    gx, gy = np.meshgrid(xs, ys)
    lon, lat = plane.lonlat(gx.ravel(), gy.ravel())
    keep = _inside(lon, lat, region.rings)
    if not keep.any():
        raise ValueError("region is smaller than one planning cell")
    return Grid(plane, cell, gx.ravel()[keep], gy.ravel()[keep], lon[keep], lat[keep])


def _town_weight(props: dict) -> float:
    return min(1.0, math.log10(max(props.get("population") or 100, 10)) / 4)


def score_cells(g: Grid, region: Region, clim: dict) -> None:
    w, s, e, n = region.bbox
    pad = 0.3

    fires = [f for f in _wildfires() if f["type"] == "WF" and w - pad <= f["lon"] <= e + pad and s - pad <= f["lat"] <= n + pad]
    if fires:
        fx, fy = g.plane.xy([f["lon"] for f in fires], [f["lat"] for f in fires])
        d2 = (g.x[:, None] - fx) ** 2 + (g.y[:, None] - fy) ** 2
        history = np.exp(-d2 / (2 * HISTORY_SIGMA_KM**2)).sum(axis=1)
    else:
        history = np.zeros_like(g.x)

    blon, blat, bn, _, years = _burn_cells()
    near = (blon >= w - pad) & (blon <= e + pad) & (blat >= s - pad) & (blat <= n + pad)
    if near.any():
        bx, by = g.plane.xy(blon[near], blat[near])
        d2 = (g.x[:, None] - bx) ** 2 + (g.y[:, None] - by) ** 2
        burns = (np.exp(-d2 / (2 * BURN_SIGMA_KM**2)) * bn[near] / years).sum(axis=1)
    else:
        burns = np.zeros_like(g.x)

    ax, ay, bx2, by2, props = _segments_xy(g.plane, region.bbox)
    if len(ax):
        d, cx, cy = _seg_dist(g.x, g.y, ax, ay, bx2, by2)
        j = d.argmin(axis=1)
        rows = np.arange(len(g.x))
        g.line_dist = d[rows, j]
        g.line_near = (cx[rows, j], cy[rows, j])
        g.line_name = [props[k].get("name") or f"{props[k].get('voltage_kv') or ''} kV line".strip() for k in j]
    else:
        g.line_dist = np.full_like(g.x, 50.0)
    subs = [p for p in _points("substations") if w - pad <= p[0] <= e + pad and s - pad <= p[1] <= n + pad]
    sub_term = np.zeros_like(g.x)
    if subs:
        sx, sy = g.plane.xy([p[0] for p in subs], [p[1] for p in subs])
        sub_term = np.exp(-np.hypot(g.x[:, None] - sx, g.y[:, None] - sy).min(axis=1) / SUBSTATION_SCALE_KM)
    lines = np.maximum(np.exp(-g.line_dist / LINE_SCALE_KM), 0.8 * sub_term)

    towns = [p for p in _points("towns") if w - pad <= p[0] <= e + pad and s - pad <= p[1] <= n + pad]
    people = np.zeros_like(g.x)
    consequence = np.zeros_like(g.x)
    if towns:
        tx, ty = g.plane.xy([t[0] for t in towns], [t[1] for t in towns])
        tw = np.array([_town_weight(t[2]) for t in towns])
        dx, dy = tx - g.x[:, None], ty - g.y[:, None]
        dist = np.hypot(dx, dy)
        people = np.clip((tw * np.exp(-dist / TOWN_SCALE_KM)).sum(axis=1), 0, 1)
        to_town = _bearing(dx, dy)
        for dw, share in climate_mod.sector_vectors(clim["fire_wind_rose"]):
            hit = (dist <= DOWNWIND_TOWN_KM) & (_angle_diff(to_town, dw) <= 22.5)
            consequence += share * (hit * tw).max(axis=1)

    fuel = np.array([TALLGRASS_FUEL if in_flint_hills(la, lo) else MIXED_FUEL for la, lo in zip(g.lat, g.lon)])
    g.comps = {
        "history": _norm(history), "burns": _norm(burns), "lines": lines, "people": people,
        "fuel": fuel, "history_raw": history, "burns_per_year": burns,
    }
    g.likelihood = fuel * sum(WEIGHTS[k] * g.comps[k] for k in WEIGHTS)
    g.consequence = np.clip(consequence, 0, 1)
    g.priority = g.likelihood * (0.6 + 0.4 * g.consequence)


# ---------------------------------------------------------------- detection and siting

def site_cover(g: Grid, sx: float, sy: float, clim: dict, p: dict) -> np.ndarray:
    """Chance a fire starting in each cell is caught by a plot at (sx, sy), from its rich and bare nodes."""
    dx, dy = sx - g.x, sy - g.y
    dist = np.hypot(dx, dy)
    to_site = _bearing(dx, dy)
    wedge = np.zeros_like(g.x)
    for dw, share in climate_mod.sector_vectors(clim["fire_wind_rose"]):
        wedge += share * (_angle_diff(to_site, dw) <= p["rich_half_angle_deg"] + 11.25)
    wedge = np.where(dist <= p["rich_range_km"], wedge, 0.0)
    own = dist <= g.cell_km / 2
    wedge = np.where(own, np.maximum(wedge, 0.5), wedge)
    rich = 1 - (1 - p["rich_catch"] * wedge) ** p["rich_per_site"] if p["rich_per_site"] else np.zeros_like(wedge)
    side_km = math.sqrt(p["plot_acres"] * 4046.86) / 1000
    bare_area = side_km * (side_km + p["bare_fetch_km"]) * min(1.0, p["bare_per_site"] / 7)
    bare = np.where(own, min(1.0, bare_area / g.cell_km**2), 0.0) if p["bare_per_site"] else np.zeros_like(wedge)
    return 1 - (1 - rich) * (1 - bare)


def _site_point(g: Grid, i: int) -> tuple[float, float, str]:
    """Where in the cell to put the plot: on the power line if one crosses the cell, else the cell center."""
    if g.line_near is not None and g.line_dist[i] <= g.cell_km / 2:
        return float(g.line_near[0][i]), float(g.line_near[1][i]), "line"
    return float(g.x[i]), float(g.y[i]), "cell"


def choose_sites(g: Grid, clim: dict, p: dict, n: int) -> tuple[list[dict], list[float]]:
    order = np.argsort(-g.priority)[:CANDIDATES]
    cands = []
    for i in order:
        sx, sy, how = _site_point(g, int(i))
        cands.append((int(i), sx, sy, how, site_cover(g, sx, sy, clim, p)))
    total = float(g.priority.sum()) or 1.0
    miss = np.ones_like(g.x)
    chosen, curve = [], [0.0]
    limit = max(n, min(2 * n, 40), 10)
    for _ in range(limit):
        best, gain = None, 0.0
        for c in cands:
            if any(math.hypot(c[1] - s["x"], c[2] - s["y"]) < p["site_min_sep_km"] for s in chosen):
                continue
            gn = float((g.priority * miss * c[4]).sum())
            if gn > gain:
                best, gain = c, gn
        if best is None:
            break
        miss *= 1 - best[4]
        chosen.append({"cell": best[0], "x": best[1], "y": best[2], "on": best[3], "cover": best[4], "gain": gain / total})
        curve.append(round(1 - float((g.priority * miss).sum()) / total, 4))
    return chosen, curve


def plot_layout(sx: float, sy: float, clim: dict, p: dict) -> list[dict]:
    """Bare and rich node positions in one plot: downwind edges first, a rich node per fire-wind mode."""
    side = math.sqrt(p["plot_acres"] * 4046.86) / 1000
    modes = clim["fire_wind_modes"]
    steps = np.linspace(-side / 2, side / 2, 4)
    pts = [(u, v) for u in steps for v in steps]

    def score(pt, dws):
        r = math.hypot(*pt)
        if r == 0:
            return 0.0
        ang = math.degrees(math.atan2(pt[0], pt[1])) % 360
        return sum(sh * max(0.0, math.cos(math.radians(ang - dw))) for dw, sh in dws) * r / side

    rose = climate_mod.sector_vectors(clim["fire_wind_rose"])
    nodes, used = [], set()
    for k in range(p["rich_per_site"]):
        mode = modes[k % len(modes)] if len(modes) > 1 else modes[0]
        dws = [(climate_mod.downwind_deg(mode["from_deg"]), 1.0)]
        free = [i for i in range(len(pts)) if i not in used]
        if not free:
            break
        best = max(free, key=lambda i: score(pts[i], dws) - 0.3 * sum(
            math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) < side / 2.5 for j in used))
        used.add(best)
        nodes.append(("rich", pts[best], mode["from"]))
    for _ in range(p["bare_per_site"]):
        free = [i for i in range(len(pts)) if i not in used]
        if not free:
            break
        best = max(free, key=lambda i: score(pts[i], rose))
        used.add(best)
        nodes.append(("bare", pts[best], None))
    return [{"tier": t, "x": sx + u, "y": sy + v, "faces": f} for t, (u, v), f in nodes]


# ---------------------------------------------------------------- terrain and mesh

@dataclass
class Terrain:
    x0: float
    y0: float
    step: float
    z: np.ndarray | None

    def at(self, x, y):
        if self.z is None:
            return np.zeros_like(np.asarray(x, dtype=float))
        fx = np.clip((np.asarray(x) - self.x0) / self.step, 0, self.z.shape[1] - 1.001)
        fy = np.clip((np.asarray(y) - self.y0) / self.step, 0, self.z.shape[0] - 1.001)
        i, j = fy.astype(int), fx.astype(int)
        ty, tx = fy - i, fx - j
        z = self.z
        return (z[i, j] * (1 - tx) * (1 - ty) + z[i, j + 1] * tx * (1 - ty)
                + z[i + 1, j] * (1 - tx) * ty + z[i + 1, j + 1] * tx * ty)


def load_terrain(g: Grid, region: Region, pad_km: float = 8.0) -> tuple[Terrain, str | None]:
    w, s, e, n = region.bbox
    x0, y0 = g.plane.xy(w, s)
    x1, y1 = g.plane.xy(e, n)
    x0, y0, x1, y1 = x0 - pad_km, y0 - pad_km, x1 + pad_km, y1 + pad_km
    step = max(0.25, max(x1 - x0, y1 - y0) / 180)
    xs, ys = np.arange(x0, x1 + step, step), np.arange(y0, y1 + step, step)
    lons, _ = g.plane.lonlat(xs, np.zeros_like(xs))
    _, lats = g.plane.lonlat(np.zeros_like(ys), ys)
    try:
        return Terrain(float(x0), float(y0), step, elevation_grid(lats, lons, z=TERRAIN_ZOOM)), None
    except TerrainUnavailable as e:
        return Terrain(float(x0), float(y0), step, None), f"Terrain tiles unavailable ({e}); links assume flat ground."


def link(t: Terrain, a: dict, b: dict) -> dict | None:
    """Whether a and b can hear each other: in range for their mount heights and with line of sight."""
    d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
    rng = RANGE_KM[tuple(sorted((a["mount"], b["mount"])))]
    if d > rng or d == 0:
        return None
    f = np.linspace(0.02, 0.98, max(8, int(d / max(t.step, 0.1)) * 2))
    xs, ys = a["x"] + f * (b["x"] - a["x"]), a["y"] + f * (b["y"] - a["y"])
    ha = float(t.at(a["x"], a["y"])) + MOUNTS[a["mount"]]
    hb = float(t.at(b["x"], b["y"])) + MOUNTS[b["mount"]]
    d1, d2 = f * d, (1 - f) * d
    ray = ha + f * (hb - ha)
    bulge = d1 * d2 / (2 * K_FACTOR * EARTH_R_KM) * 1000
    fresnel = 17.32 * np.sqrt(d1 * d2 / (FREQ_GHZ * d))
    clear = ray - (t.at(xs, ys) + bulge)
    if (clear < 0).any():
        return None
    margin = float((clear / fresnel).min())
    return {"km": round(d, 2), "fresnel": round(margin, 2), "quality": "clear" if margin >= 0.6 else "marginal"}


def relay_candidates(g: Grid, region: Region, t: Terrain) -> list[dict]:
    w, s, e, n = region.bbox
    pad = 0.08
    out = []
    for lon, lat, props in _points("towns"):
        if w - pad <= lon <= e + pad and s - pad <= lat <= n + pad:
            out.append({"kind": "town", "name": f"{props['name']} elevator or water tower", "lon": lon, "lat": lat,
                        "mount": "tower", "power": "mains"})
    for lon, lat, props in _points("substations"):
        if w - pad <= lon <= e + pad and s - pad <= lat <= n + pad:
            label = props.get("name") or "Substation"
            out.append({"kind": "substation", "name": label, "lon": lon, "lat": lat, "mount": "tower", "power": "mains"})
    if t.z is not None:
        z = t.z
        k = max(2, round(2.5 / t.step))
        peaks = []
        for i in range(k, z.shape[0] - k, k):
            for j in range(k, z.shape[1] - k, k):
                win = z[i - k:i + k + 1, j - k:j + k + 1]
                ii, jj = np.unravel_index(win.argmax(), win.shape)
                pi, pj = i - k + ii, j - k + jj
                wide = z[max(0, pi - 2 * k):pi + 2 * k + 1, max(0, pj - 2 * k):pj + 2 * k + 1]
                peaks.append((float(z[pi, pj] - wide.mean()), pi, pj))
        peaks.sort(reverse=True)
        taken = []
        for prom, pi, pj in peaks:
            x, y = t.x0 + pj * t.step, t.y0 + pi * t.step
            lon, lat = g.plane.lonlat(x, y)
            if prom < 5 or not (w <= lon <= e and s <= lat <= n):
                continue
            if any(math.hypot(x - a, y - b) < 3.0 for a, b in taken):
                continue
            taken.append((x, y))
            where = place_label(float(lat), float(lon))[0].split(",")[0]
            out.append({"kind": "high_point", "name": f"High ground {where[0].lower()}{where[1:]} "
                        f"({prom:.0f} m above surroundings)", "lon": float(lon), "lat": float(lat),
                        "mount": "mast", "power": "solar"})
            if len(taken) >= 25:
                break
    seen, uniq = [], []
    for c in out:
        c["x"], c["y"] = (float(v) for v in g.plane.xy(c["lon"], c["lat"]))
        if any(math.hypot(c["x"] - u["x"], c["y"] - u["y"]) < 0.5 for u in seen):
            continue
        seen.append(c)
        uniq.append(c)
    return uniq


def pick_station(g: Grid, region: Region) -> dict:
    st = region.station
    if st:
        x, y = g.plane.xy(st["lon"], st["lat"])
        return {"name": st.get("name", "Station"), "lon": st["lon"], "lat": st["lat"], "x": float(x), "y": float(y),
                "mount": "mast"}
    towns = [t for t in _points("towns") if _inside(np.array([t[0]]), np.array([t[1]]), region.rings)[0]]
    if towns:
        lon, lat, props = max(towns, key=lambda t: t[2].get("population") or 0)
        name = f"{props['name']} fire station"
    else:
        lon, lat = (float(v) for v in g.plane.lonlat(0.0, 0.0))
        name = "Station (region center)"
    x, y = g.plane.xy(lon, lat)
    return {"name": name, "lon": lon, "lat": lat, "x": float(x), "y": float(y), "mount": "mast"}


def route_mesh(t: Terrain, station: dict, gateways: list[dict], cands: list[dict]) -> dict:
    """Greedy Steiner tree: repeatedly connect the cheapest unconnected plot, paying for new relays only."""
    nodes = [station] + cands
    nc = len(nodes)
    adj: dict[int, list[tuple[int, dict]]] = {i: [] for i in range(nc)}
    for i in range(nc):
        for j in range(i + 1, nc):
            ln = link(t, nodes[i], nodes[j])
            if ln:
                adj[i].append((j, ln))
                adj[j].append((i, ln))
    gw_links = []
    for gw in gateways:
        gw_links.append([(i, ln) for i in range(nc) if (ln := link(t, gw, nodes[i]))])

    depth = {0: 0}  # relays between a tree node and the station, counting itself
    parent: dict[int, tuple[int, dict]] = {}
    attach: dict[int, tuple[int, dict]] = {}
    pending = set(range(len(gateways)))

    def grow(limit: float) -> bool:
        # Search over (node, relays to station) so a cheap path can't hide a shorter one under the hop limit.
        cost = {(t, d): 0.0 for t, d in depth.items()}
        prev: dict[tuple[int, int], tuple[tuple[int, int], dict]] = {}
        heap = [(0.0, t, d) for t, d in depth.items()]
        while heap:
            c, u, du = heapq.heappop(heap)
            if c > cost.get((u, du), math.inf):
                continue
            for v, ln in adj[u]:
                if v in depth or du + 1 > limit:
                    continue
                nc_ = c + RELAY_COST[nodes[v]["kind"]] + HOP_COST + ln["km"] * 1e-3
                if nc_ < cost.get((v, du + 1), math.inf):
                    cost[(v, du + 1)], prev[(v, du + 1)] = nc_, ((u, du), ln)
                    heapq.heappush(heap, (nc_, v, du + 1))
        best = None
        for gi in pending:
            for i, ln in gw_links[gi]:
                for (n_, d), c in cost.items():
                    if n_ == i and d <= limit and (best is None or c + ln["km"] * 1e-3 < best[0]):
                        best = (c + ln["km"] * 1e-3, gi, (i, d), ln)
        if best is None:
            return False
        _, gi, state, ln = best
        attach[gi] = (state[0], ln)
        while state[0] not in depth:
            up, l2 = prev[state]
            parent[state[0]] = (up[0], l2)
            depth[state[0]] = state[1]
            state = up
        pending.discard(gi)
        return True

    while pending and grow(HOP_LIMIT):
        pass
    over = set(pending)
    while pending and grow(math.inf):
        pass

    return {
        "relays": sorted(i for i in depth if i != 0),
        "parent": parent, "attach": attach, "unreached": sorted(pending), "nodes": nodes,
        "hops": {gi: depth[i] for gi, (i, _) in attach.items()},
        "over_hop_limit": sorted(over - pending),
    }


# ---------------------------------------------------------------- energy

def power_check(clim: dict) -> dict:
    sun = clim["sun_hours"]
    out = {}
    for tier in ("bare", "rich"):
        need = BASE_WH_DAY + (PM_WH_DAY_CONTINUOUS * PM_DUTY if tier == "rich" else 0.0)
        rows = {}
        for label, key in (("fire_season_worst_week", "fire_season_worst_week"), ("winter_worst_week", "winter_worst_week")):
            made = PANEL_W[tier] * sun[key] * SOLAR_YIELD
            deficit = max(0.0, need - made)
            rows[label] = {
                "sun_hours": sun[key], "made_wh_day": round(made, 2), "need_wh_day": round(need, 2),
                "days_on_battery": None if deficit == 0 else round(PACK_WH[tier] * USABLE_PACK / deficit, 1),
            }
        entry = {"panel_w": PANEL_W[tier], "pack_wh": PACK_WH[tier], **rows}
        if tier == "rich":
            made = PANEL_W[tier] * sun["fire_season_worst_week"] * SOLAR_YIELD
            entry["max_pm_duty_fire_season"] = round(max(0.0, min(1.0, (made - BASE_WH_DAY) / PM_WH_DAY_CONTINUOUS)), 2)
        out[tier] = entry
    return out


# ---------------------------------------------------------------- explanations

def _reasons(g: Grid, i: int, lon: float, lat: float, clim: dict, region_fires: list[dict]) -> list[str]:
    out = []
    near = [f for f in region_fires if haversine_km(lat, lon, f["lat"], f["lon"]) <= 8]
    if near:
        big = max(near, key=lambda f: f.get("acres") or 0)
        out.append(f"{len(near)} reported wildfire{'s' if len(near) > 1 else ''} within 5 mi since 2014 "
                   f"(largest {big['name']}, {big.get('acres') or 0:,.0f} ac, {big['date'][:4]})")
    bpy = g.comps["burns_per_year"][i]
    if bpy >= 0.5:
        out.append(f"About {bpy:.0f} satellite-detected fires a year nearby (burning that can escape)")
    if g.line_dist is not None and g.line_dist[i] <= 2:
        out.append(f"{g.line_name[i]} {g.line_dist[i] / KM_PER_MILE:.1f} mi away")
    if g.consequence[i] >= 0.2:
        m = clim["fire_wind_modes"][0]
        out.append(f"Fire-weather winds (mostly from the {m['from']}) carry a fire here toward town")
    if g.comps["fuel"][i] == TALLGRASS_FUEL:
        out.append("Flint Hills tallgrass: continuous fuel")
    return out or ["Fills a coverage gap between higher-risk sites"]


def _site_checks(lon: float, lat: float, g: Grid, i: int, clim: dict) -> list[str]:
    out = []
    sub = nearest_substation(lat, lon)
    if sub.name and sub.distance_km <= 0.5:
        out.append("Substation within 0.5 km: mount a rich node on mains power and run the PM fan continuously")
    town = nearest_town(lat, lon)
    if town.name and town.distance_km <= 1.0:
        out.append(f"{town.name} within 1 km: exhaust and heating will move the gas baseline; record nuisance events")
    static = nearest_static_source(lat, lon)
    if static.name and static.distance_km <= 5:
        out.append(f"{static.name} {static.distance_km:.0f} km away: check the gas and PM baseline before trusting alerts")
    if g.comps["fuel"][i] == TALLGRASS_FUEL:
        out.append("Flint Hills burn season (March-April) raises PM everywhere; expect regional-smoke suppressions")
    if clim["fire_season_fog_morning_share"] >= 0.1:
        out.append(f"Fog on {clim['fire_season_fog_morning_share']:.0%} of fire-season mornings can read as PM")
    return out


# ---------------------------------------------------------------- plan

def _feature(geom: dict, **props) -> dict:
    return {"type": "Feature", "geometry": geom, "properties": props}


def _pt(lon, lat) -> dict:
    return {"type": "Point", "coordinates": [round(float(lon), 5), round(float(lat), 5)]}


def plan_region(region: Region, overrides: dict | None = None, fetch_climate: bool = True) -> dict:
    p = {**PARAMS, **{k: v for k, v in (overrides or {}).items() if v is not None and k in PARAMS}}
    p["sites"] = int(p["sites"])
    p["bare_per_site"], p["rich_per_site"] = int(p["bare_per_site"]), int(p["rich_per_site"])
    warnings: list[str] = []

    g = build_grid(region)
    clat, clon = (float(v) for v in g.plane.lonlat(0.0, 0.0)[::-1])
    clim = climate_mod.climatology(clat, clon, fetch=fetch_climate)
    score_cells(g, region, clim)
    terrain, warn = load_terrain(g, region)
    if warn:
        warnings.append(warn)
    station = pick_station(g, region)
    cands = relay_candidates(g, region, terrain)
    site_cost = p["bare_per_site"] * COSTS["bare"] + p["rich_per_site"] * COSTS["rich"]

    def build(n: int):
        sites, curve = choose_sites(g, clim, p, n)
        sites = sites[:n]
        gws, masts = [], []
        for k, s in enumerate(sites):
            nodes = plot_layout(s["x"], s["y"], clim, p)
            s["nodes"] = nodes
            # The plot's gateway is its node nearest the station; plots are small enough to hear each other.
            gw = min(nodes, key=lambda nd: math.hypot(nd["x"] - station["x"], nd["y"] - station["y"]))
            gws.append({"x": gw["x"], "y": gw["y"], "mount": "ground"})
            mlon, mlat = (float(v) for v in g.plane.lonlat(s["x"], s["y"]))
            masts.append({"kind": "site_mast", "name": f"10 m mast at site {k + 1}", "x": s["x"], "y": s["y"],
                          "lon": mlon, "lat": mlat, "mount": "mast", "power": "solar"})
        mesh = route_mesh(terrain, station, gws, cands + masts)
        cost = len(sites) * site_cost + len(mesh["relays"]) * COSTS["relay"] + COSTS["station"]
        return sites, curve, mesh, cost

    n = p["sites"]
    if p["budget_usd"]:
        n = max(1, int((p["budget_usd"] - COSTS["station"]) / (site_cost * (1 + SPARES))))
    sites, curve, mesh, cost = build(n)
    while p["budget_usd"] and n > 1 and cost * (1 + SPARES) > p["budget_usd"]:
        n -= 1
        sites, curve, mesh, cost = build(n)
    p["sites"] = n

    region_fires = [f for f in _wildfires() if f["type"] == "WF"]
    site_out, node_feats = [], []
    for k, s in enumerate(sites):
        lon, lat = (float(v) for v in g.plane.lonlat(s["x"], s["y"]))
        label, _, _ = place_label(lat, lon)
        hop = mesh["hops"].get(k)
        via = None
        if k in mesh["attach"]:
            i, ln = mesh["attach"][k]
            via = {"name": mesh["nodes"][i]["name"], **ln}
        nodes = []
        for nd in s["nodes"]:
            nlon, nlat = (float(v) for v in g.plane.lonlat(nd["x"], nd["y"]))
            nodes.append({"tier": nd["tier"], "lon": round(nlon, 6), "lat": round(nlat, 6), "faces": nd["faces"]})
            node_feats.append(_feature(_pt(nlon, nlat), kind="sensor", tier=nd["tier"], site=k + 1))
        site_out.append({
            "id": k + 1, "label": label, "lon": round(lon, 5), "lat": round(lat, 5), "on": s["on"],
            "priority": round(float(g.priority[s["cell"]]), 3), "adds_coverage": round(s["gain"], 4),
            "reasons": _reasons(g, s["cell"], lon, lat, clim, region_fires),
            "checks": _site_checks(lon, lat, g, s["cell"], clim),
            "bare": sum(nd["tier"] == "bare" for nd in s["nodes"]),
            "rich": sum(nd["tier"] == "rich" for nd in s["nodes"]),
            "gateway": via, "hops": hop, "nodes": nodes,
        })
    for gi in mesh["unreached"]:
        warnings.append(f"Site {gi + 1} has no radio path to the station within planning range: survey a taller mount "
                        "or add a mast near it.")
    if mesh["over_hop_limit"]:
        ids = ", ".join(str(gi + 1) for gi in mesh["over_hop_limit"])
        warnings.append(f"Site {ids} needs more than {HOP_LIMIT} relays to reach the station; raise the Meshtastic "
                        "hop limit on those nodes or find a taller mount.")

    relays = []
    link_feats = []
    for i in mesh["relays"]:
        c = mesh["nodes"][i]
        up, ln = mesh["parent"][i]
        upn = mesh["nodes"][up]
        relays.append({"name": c["name"], "kind": c["kind"], "mount": c["mount"], "power": c["power"],
                       "lon": round(c["lon"], 5), "lat": round(c["lat"], 5), "uplink": upn["name"], **ln})
        link_feats.append(_feature({"type": "LineString", "coordinates": [[c["lon"], c["lat"]], [upn["lon"], upn["lat"]]]},
                                   kind="backbone", **ln))
    for k, s in enumerate(site_out):
        if k in mesh["attach"]:
            i, ln = mesh["attach"][k]
            nd = mesh["nodes"][i]
            link_feats.append(_feature({"type": "LineString", "coordinates": [[s["lon"], s["lat"]], [nd["lon"], nd["lat"]]]},
                                       kind="gateway", **ln))

    total = float(g.priority.sum()) or 1.0
    miss = np.ones_like(g.x)
    for s in sites:
        miss *= 1 - s["cover"]
    covered = 1 - miss
    cells = []
    h = g.cell_km / 2
    for i in range(len(g.x)):
        xs = [g.x[i] - h, g.x[i] + h, g.x[i] + h, g.x[i] - h, g.x[i] - h]
        ys = [g.y[i] - h, g.y[i] - h, g.y[i] + h, g.y[i] + h, g.y[i] - h]
        lo, la = g.plane.lonlat(xs, ys)
        cells.append(_feature(
            {"type": "Polygon", "coordinates": [[[round(float(a), 5), round(float(b), 5)] for a, b in zip(lo, la)]]},
            priority=round(float(g.priority[i]), 3), covered=round(float(covered[i]), 2),
        ))

    fires_in = [f for f in region_fires if _inside(np.array([f["lon"]]), np.array([f["lat"]]), region.rings)[0]]
    n_bare = sum(s["bare"] for s in site_out)
    n_rich = sum(s["rich"] for s in site_out)
    n_relay = len(relays)
    lines = [
        {"item": "Bare node (gas, temperature, humidity, pressure)", "qty": n_bare, "unit": COSTS["bare"]},
        {"item": "Rich node (bare plus PMSA003I particulate)", "qty": n_rich, "unit": COSTS["rich"]},
        {"item": "Relay (radio only, mast or tower mount)", "qty": n_relay, "unit": COSTS["relay"]},
        {"item": "Station bridge (USB to the FireWatch server)", "qty": 1, "unit": COSTS["station"]},
    ]
    for ln in lines:
        ln["total"] = ln["qty"] * ln["unit"]
    hardware = sum(ln["total"] for ln in lines)
    spares = round((n_bare * COSTS["bare"] + n_rich * COSTS["rich"] + n_relay * COSTS["relay"]) * SPARES)
    custom = n_bare * CUSTOM_PCB["bare"] + n_rich * CUSTOM_PCB["rich"] + n_relay * COSTS["relay"] + COSTS["station"]

    w, s_, e, n_ = region.bbox
    area_km2 = len(g.x) * g.cell_km**2
    return {
        "region": {"key": region.key, "name": region.name, "kind": region.kind, "area_km2": round(area_km2),
                   "area_sq_mi": round(area_km2 / KM_PER_MILE**2), "bbox": [w, s_, e, n_], "cell_km": g.cell_km,
                   "boundary": region.geojson()},
        "params": p,
        "climate": clim,
        "power": power_check(clim),
        "summary": {
            "sites": len(site_out), "bare": n_bare, "rich": n_rich, "relays": n_relay,
            "priority_covered": round(1 - float((g.priority * miss).sum()) / total, 3),
            "coverage_curve": curve,
            "reported_wildfires": len(fires_in),
            "burns_per_year": round(float(np.sum(_burns_inside(region)))),
            "max_hops": max(mesh["hops"].values()) if mesh["hops"] else None,
            "unreached_sites": [k + 1 for k in mesh["unreached"]],
            "prevailing_fire_wind": " / ".join(f"{m['from']} {m['share']:.0%}" for m in clim["fire_wind_modes"]),
            "fire_wind_compass": compass(clim["fire_wind_modes"][0]["from_deg"]),
        },
        "station": {k: station[k] for k in ("name", "lon", "lat")},
        "sites": site_out,
        "relays": relays,
        "bom": {"lines": lines, "hardware": hardware, "spares": spares, "total": hardware + spares,
                "custom_pcb_hardware": round(custom)},
        "geojson": {
            "cells": {"type": "FeatureCollection", "features": cells},
            "nodes": {"type": "FeatureCollection", "features": node_feats},
            "links": {"type": "FeatureCollection", "features": link_feats},
        },
        "assumptions": ASSUMPTIONS,
        "warnings": warnings,
    }


def _burns_inside(region: Region) -> np.ndarray:
    lons, lats, counts, _, years = _burn_cells()
    w, s, e, n = region.bbox
    box = (lons >= w) & (lons <= e) & (lats >= s) & (lats <= n)
    inside = np.zeros_like(box)
    inside[box] = _inside(lons[box], lats[box], region.rings)
    return counts[inside] / years
