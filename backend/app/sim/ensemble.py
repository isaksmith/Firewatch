"""Ensemble spread forecast: one fire, many plausible weathers, reported as ranges instead of one line.

Each member perturbs the whole weather series by a constant wind-speed factor, wind-direction
offset and humidity offset, plus a fuel-load factor. The spreads are planning assumptions sized to
typical hourly forecast error, not calibrated values. Member 0 is the unperturbed central run.
"""

from dataclasses import dataclass

import numpy as np

from ..geo import KM_PER_DEG_LAT, km_per_deg_lon
from ..situation import Situation
from .fuels import fuel_mix
from .spread import (
    Domain, SpreadInput, _blocks, _contours, _rings, assumptions, block_rates, build_domain,
    impacts, interp_weather, isochrones, propagate,
)

WIND_SPEED_SD = 0.15  # lognormal sigma on wind speed
WIND_DIR_SD_DEG = 15.0
RH_SD_PCT = 3.0
FUEL_SD = 0.15  # lognormal sigma on fuel load / grazing
PROBABILITY_LEVELS = (0.1, 0.5, 0.9)
UNBURNED = 1e6  # arrival minutes for cells a member never reaches (percentiles of inf give NaN)
CHECKPOINTS_MIN = (15, 30, 60, 90, 120)
ENSEMBLE_GRID_N = 400  # finer than a single run: the fire is narrow and the domain covers the fastest member


@dataclass
class Member:
    wind_scale: float
    dir_offset: float
    rh_offset: float
    fuel_scale: float
    gust_rule: bool = False  # on dry, gusty days run at 20% of gust speed (spread.GUST_RULE_*)


GUST_RULE_SHARE = 0.25


def draw_members(n: int, seed: int) -> list[Member]:
    """Member 0 is the central run. The last quarter use the extreme-day gust rule, so the worst case (10th
    percentile) reflects it on days it applies, and the median doesn't."""
    rng = np.random.default_rng(seed)
    out = [Member(1.0, 0.0, 0.0, 1.0)]
    n_gust = int(n * GUST_RULE_SHARE)
    for i in range(1, n):
        out.append(Member(
            wind_scale=float(np.exp(rng.normal(0, WIND_SPEED_SD))),
            dir_offset=float(rng.normal(0, WIND_DIR_SD_DEG)),
            rh_offset=float(rng.normal(0, RH_SD_PCT)),
            fuel_scale=float(np.exp(rng.normal(0, FUEL_SD))),
            gust_rule=i >= n - n_gust,
        ))
    return out


def spread_input(sit: Situation, minutes: int) -> SpreadInput:
    first = interp_weather(sit.weather_steps(), 0.0)
    ig = sit.ignition
    return SpreadInput(
        lat=ig.lat, lon=ig.lon, wind_kmh=first.wind_kmh, wind_from_deg=first.wind_from_deg, temp_c=first.temp_c,
        rh_pct=first.rh_pct, curing_pct=sit.curing_or_default().pct, minutes=minutes,
        ignitions=ig.points or [(ig.lat, ig.lon)], use_terrain=sit.use_terrain, weather=sit.weather_steps(),
        use_fuel=sit.use_fuel_map, month=ig.time.month, fire_age_min=ig.fire_age_min, grid_n=ENSEMBLE_GRID_N,
    )


def forecast(sit: Situation, minutes: int = 120, members: int = 24, seed: int = 7) -> dict:
    inp = spread_input(sit, minutes)
    steps = inp.weather or []
    blocks = _blocks(steps, minutes)
    draws = draw_members(members, seed)
    member_rates, member_heads = [], []
    for m in draws:
        rates, heads = block_rates(blocks, inp.curing_pct, m.wind_scale, m.dir_offset, m.rh_offset, m.gust_rule)
        member_rates.append([[r * m.fuel_scale for r in row] for row in rates])
        member_heads.append([h * m.fuel_scale for h in heads])
    dom = build_domain(inp, blocks, max(max(h) for h in member_heads))

    arrivals = [propagate(dom, r, inp.ignitions, minutes, inp.fire_age_min) for r in member_rates]
    stack = np.minimum(np.stack(arrivals), UNBURNED).astype(np.float32)  # (members, n, n)

    t10, t50, t90 = np.percentile(stack, (10, 50, 90), axis=0)
    p_burn = (stack <= minutes).mean(axis=0)
    first = interp_weather(steps, 0.0)
    return {
        "assumptions": assumptions(inp, first, dom, steps) | {
            "ensemble": f"{members} members: wind speed ±{round(WIND_SPEED_SD * 100)}%, direction ±{round(WIND_DIR_SD_DEG)}°, "
                        f"RH ±{round(RH_SD_PCT)} pts, fuel load ±{round(FUEL_SD * 100)}% (1 sigma); "
                        f"{int(members * GUST_RULE_SHARE)} runs spread at 20% of gust speed on dry days with gusts of 60+ km/h",
        },
        "provenance": {
            "weather": sit.weather.provenance.model_dump(mode="json"),
            "curing": sit.curing_or_default().provenance.model_dump(mode="json"),
            "ignition": sit.ignition.provenance.model_dump(mode="json"),
            "fuel": {"source": dom.fuel.source, "kind": "inferred"},
            "spread": {"source": "Firewatch ensemble spread model", "kind": "simulated"},
        },
        "start_time": sit.ignition.time.isoformat(),
        "minutes": minutes,
        "members": members,
        "head_ros_kmh": _range([h[0] for h in member_heads]),
        "isochrones": isochrones(t50, dom, minutes),  # median arrival
        "isochrones_early": isochrones(t10, dom, minutes),  # 1 in 10 members get there this soon
        "probability": _probability_contours(p_burn, dom),
        "checkpoints": _checkpoints(stack, dom, inp),
        "impacts": _impacts(stack, dom, minutes),
        "fuel_mix": fuel_mix(dom.fuel, p_burn >= 0.5),
        "weather": [
            {"t_min": round(b.t_min), "wind_kmh": round(b.wind_kmh, 1), "wind_from_deg": round(b.wind_from_deg),
             "temp_c": round(b.temp_c, 1), "rh_pct": round(b.rh_pct)}
            for b in blocks if b.t_min <= minutes
        ],
        "wind_shift_deg": round(sit.wind_shift_deg(minutes)),
        "wind_vector": {"from_deg": round(first.wind_from_deg % 360), "kmh": round(first.wind_kmh, 1)},
        "grid": {"cell_m": round(dom.cell_m, 1), "n": dom.n},
        "_arrival": {"t10": t10, "t50": t50, "t90": t90, "p_burn": p_burn, "domain": dom},
    }


def _range(values) -> dict:
    p10, p50, p90 = np.percentile(np.asarray(values, dtype=float), (10, 50, 90))
    return {"p10": round(float(p10), 2), "p50": round(float(p50), 2), "p90": round(float(p90), 2)}


def _probability_contours(p_burn: np.ndarray, dom: Domain) -> dict:
    """Outlines of 'burned by the end of the forecast' at 10, 50 and 90 % of members."""
    gen = _contours(-p_burn, dom)  # contour on -p so 'inside' means at least p
    features = []
    for p in PROBABILITY_LEVELS:
        rings = _rings(gen, -p + 1e-6)
        if rings:
            features.append({"type": "Feature", "properties": {"probability": p},
                             "geometry": {"type": "MultiPolygon", "coordinates": rings}})
    return {"type": "FeatureCollection", "features": features}


def _checkpoints(stack: np.ndarray, dom: Domain, inp: SpreadInput) -> list[dict]:
    """Burned area and head distance from the ignition at fixed times, as ranges across members."""
    ky, kx = KM_PER_DEG_LAT, km_per_deg_lon(inp.lat)
    dy = (dom.lats[:, None] - inp.lat) * ky
    dx = (dom.lons[None, :] - inp.lon) * kx
    dist = np.hypot(dx, dy)
    cell_ha = dom.cell_m**2 / 10_000
    out = []
    for m in CHECKPOINTS_MIN:
        if m > inp.minutes:
            break
        burned = stack <= m
        areas = burned.sum(axis=(1, 2)) * cell_ha
        runs = np.array([dist[b].max() if b.any() else 0.0 for b in burned])
        out.append({"minutes": m, "area_ha": _range(areas), "head_km": _range(runs)})
    return out


def _impacts(stack: np.ndarray, dom: Domain, minutes: int) -> list[dict]:
    """Per asset: share of members that reach it, and arrival minutes (p10 / p50 / p90 over all members)."""
    per_asset: dict[str, dict] = {}
    times: dict[str, list[float]] = {}
    for arrival in stack:
        for imp in impacts(arrival, dom.lats, dom.lons, minutes):
            per_asset.setdefault(imp["id"], {k: imp[k] for k in ("kind", "id", "name")})
            times.setdefault(imp["id"], []).append(imp["minutes"])
    n = len(stack)
    out = []
    for key, base in per_asset.items():
        ts = times[key] + [UNBURNED] * (n - len(times[key]))
        p10, p50, p90 = (float(v) if v < UNBURNED else None for v in np.percentile(ts, (10, 50, 90), method="nearest"))
        out.append(base | {
            "probability": round(len(times[key]) / n, 2),
            "minutes": round(p50 if p50 is not None else min(times[key])),
            "minutes_p10": None if p10 is None else round(p10),
            "minutes_p50": None if p50 is None else round(p50),
            "minutes_p90": None if p90 is None else round(p90),
        })
    return sorted(out, key=lambda a: (a["minutes_p10"] is None, a["minutes_p10"] or 0))
