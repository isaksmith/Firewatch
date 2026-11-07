"""Spread forecast back-test v1: start the forecast from a real fire's first satellite look and score it against
what later looks saw.

    .venv/bin/python -m ml.backtest      # downloads FIRMS archive rows (cached), runs, writes the report

For each fire:
  1. The first satellite look with detections is t0. Its pixels are the burning area (an established fire).
  2. Weather is the Open-Meteo archive's hourly series at the fire for the next 13 hours (what a forecast would
     have had, minus forecast error, which the ensemble's spread stands in for).
  3. The ensemble forecast (v2: hourly wind, fuel map, terrain, 24 members) and the original single run (v1:
     constant wind from the first hour, all grass) both run to the last look within 12 hours.
  4. Every later look is scored: did the forecast have fire at each detected pixel by then (median and
     worst case), and how far did the head run compared with the farthest detection?

Scoring is by study area, not by fire: the forecast starts from every cluster burning at the first look, and every
later detection in the area counts. A fire that starts after the first look counts as a miss, so the scores are
conservative. (Telling spread from new ignitions with satellite data alone isn't possible on multi-fire days,
which is why the Dec 15, 2021 outbreak is listed but not scored.)
"""

import csv
import io
import json
import logging
import math
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np

from app.geo import KM_PER_DEG_LAT, km_per_deg_lon
from app.ingest.weather import weather_series
from app.sim.ensemble import forecast
from app.sim.spread import SpreadInput, _arrival_many, run
from app.situation import Ignition, Provenance, Situation, Weather, WeatherHour

from .paths import MODEL_DIR, WORK_DIR

log = logging.getLogger("backtest")
OUT_DIR = WORK_DIR / "backtest"
REPO_DIR = MODEL_DIR.parent.parent.parent
REPORT_PATH = REPO_DIR / "docs" / "research" / "spread-backtest-v1.md"
RESULTS_PATH = REPO_DIR / "docs" / "research" / "spread-backtest-v1.json"
FIG_DIR = REPO_DIR / "docs" / "research" / "figures" / "spread-backtest"
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/data/country/{folder}/{year}/{folder}_{year}_United_States.csv"

HORIZON_MIN = 16 * 60
LOOK_GAP_MIN = 20  # detections within 20 min of each other are one satellite "look"
FIRST_CLUSTER_KM = 4.0
MIN_START_PIXELS = 5
MEMBERS = 24

FIRES = {
    "anderson-creek-2016": {
        "title": "Anderson Creek fire, Woods Co. OK into Barber Co. KS (March 2016)",
        "dates": ("2016-03-22", "2016-03-24"), "box": (36.3, 37.7, -99.8, -98.0),
        "sources": [("viirs-snpp", 2016), ("modis", 2016)],
    },
    "starbuck-2017": {
        "title": "Starbuck fire, Beaver Co. OK into Clark Co. KS (March 2017)",
        "dates": ("2017-03-06", "2017-03-08"), "box": (36.55, 37.8, -100.6, -99.3),
        "sources": [("viirs-snpp", 2017), ("modis", 2017)],
    },
}
NOT_SCORED = {
    "trego-dec-2021": {
        "why": "Downed lines started several separate fires across Trego, Ellis and Russell counties after the first "
               "satellite look (Hays Post, KCUR). Overnight detections 50-110 km downwind can't be told apart from "
               "new ignitions, so scoring it would measure ignitions, not spread.",
        "title": "Wind-event fire near WaKeeney, Trego Co. KS (Dec 15, 2021)",
        "dates": ("2021-12-15", "2021-12-16"), "box": (38.6, 39.8, -100.9, -98.6),
        "sources": [("viirs-snpp", 2021), ("viirs-jpss1", 2021), ("modis", 2021)],
    },
}


# ---------- data ----------

def detections(slug: str) -> list[dict]:
    path = OUT_DIR / f"{slug}.json"
    if path.exists():
        return json.loads(path.read_text())
    f = FIRES[slug]
    s, n, w, e = f["box"]
    rows = []
    for folder, year in f["sources"]:
        text = httpx.get(FIRMS_URL.format(folder=folder, year=year), timeout=300, follow_redirects=True).text
        for r in csv.DictReader(io.StringIO(text)):
            if not (f["dates"][0] <= r["acq_date"] <= f["dates"][1]):
                continue
            lat, lon = float(r["latitude"]), float(r["longitude"])
            if s <= lat <= n and w <= lon <= e:
                t = datetime.strptime(f"{r['acq_date']} {r['acq_time'].zfill(4)}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
                rows.append({"lat": lat, "lon": lon, "t": t.isoformat(), "sensor": folder,
                             "conf": r.get("confidence"), "frp": float(r.get("frp") or 0)})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * KM_PER_DEG_LAT, (a[1] - b[1]) * km_per_deg_lon(a[0]))


def looks(rows: list[dict]) -> list[tuple[datetime, list[dict]]]:
    rows = sorted(rows, key=lambda r: r["t"])
    out: list[tuple[datetime, list[dict]]] = []
    for r in rows:
        t = datetime.fromisoformat(r["t"])
        if out and (t - out[-1][0]).total_seconds() / 60 <= LOOK_GAP_MIN:
            out[-1][1].append(r)
        else:
            out.append((t, [r]))
    return out


def _chain(seed: list[tuple[float, float]], pool: list[tuple[float, float]], km: float) -> set[int]:
    """Indices of pool points connected to the seed through steps of at most `km`."""
    member, frontier = set(), list(seed)
    while frontier:
        p = frontier.pop()
        for i, q in enumerate(pool):
            if i not in member and _km(p, q) <= km:
                member.add(i)
                frontier.append(q)
    return member


def clusters(pts: list[tuple[float, float]], km: float) -> list[list[tuple[float, float]]]:
    out, seen = [], set()
    for i, p in enumerate(pts):
        if i in seen:
            continue
        member = _chain([p], pts, km)
        seen |= member
        out.append([pts[j] for j in sorted(member)])
    return sorted(out, key=len, reverse=True)


def fire_case(slug: str) -> dict:
    ls = looks(detections(slug))
    t0, first = ls[0]
    pts = [(r["lat"], r["lon"]) for r in first]
    starts = [c for c in clusters(pts, FIRST_CLUSTER_KM) if len(c) >= MIN_START_PIXELS]
    evals = [{"t": t, "minutes": (t - t0).total_seconds() / 60, "points": [(r["lat"], r["lon"]) for r in rs],
              "sensors": sorted({r["sensor"] for r in rs})}
             for t, rs in ls[1:] if (t - t0).total_seconds() / 60 <= HORIZON_MIN]
    return {"slug": slug, "t0": t0, "start": [p for c in starts for p in c], "start_clusters": len(starts),
            "anchor": starts[0], "first_sensors": sorted({r["sensor"] for r in first}), "evals": evals}


def situation(case: dict) -> Situation:
    lat = float(np.mean([p[0] for p in case["anchor"]]))
    lon = float(np.mean([p[1] for p in case["anchor"]]))
    t0 = case["t0"]
    series, _ = weather_series(lat, lon, t0 - timedelta(hours=1), 14)
    src = Provenance(source="open-meteo archive (hourly, at the fire)", kind="observed")
    return Situation(
        ignition=Ignition(lat=lat, lon=lon, time=t0, points=case["start"], fire_age_min=None,
                          provenance=Provenance(source="FIRMS first look", kind="observed")),
        weather=Weather(hours=[WeatherHour(**h) for h in series], provenance=src),
    )


# ---------- scoring ----------

def _head_km(grid: np.ndarray, dom, starts: list[tuple[float, float]], minute: float) -> float:
    """Distance from the nearest start pixel that covers 90% of the burned cells (same measure as observed)."""
    burned = grid <= minute
    if not burned.any():
        return 0.0
    ii, jj = np.nonzero(burned)
    lat, lon = dom.lats[ii], dom.lons[jj]
    kx = km_per_deg_lon(float(np.mean(lat)))
    sl = np.array(starts)
    best = np.full(len(lat), np.inf)
    for s0, s1 in sl[:: max(1, len(sl) // 60)]:  # thin the start pixels; they are within a few km of each other
        best = np.minimum(best, np.hypot((lat - s0) * KM_PER_DEG_LAT, (lon - s1) * kx))
    return float(np.percentile(best, 90))


def score(case: dict) -> dict:
    sit = situation(case)
    lat0, lon0 = sit.ignition.lat, sit.ignition.lon
    horizon = int(math.ceil(max(e["minutes"] for e in case["evals"]) / 10) * 10)
    fc = forecast(sit, horizon, MEMBERS)
    a = fc["_arrival"]
    dom = a["domain"]
    first = sit.weather_steps()
    w0 = min(first, key=lambda s: abs(s.t_min))
    v1_dom, v1_arr, _ = run(SpreadInput(
        lat=lat0, lon=lon0, wind_kmh=w0.wind_kmh, wind_from_deg=w0.wind_from_deg, temp_c=w0.temp_c, rh_pct=w0.rh_pct,
        curing_pct=sit.curing_or_default().pct, minutes=horizon, ignitions=case["start"], use_terrain=True,
        use_fuel=False, fire_age_min=None, grid_n=400))

    rows = []
    for e in case["evals"]:
        m = e["minutes"]
        plat = np.array([p[0] for p in e["points"]])
        plon = np.array([p[1] for p in e["points"]])
        # how far the fire had run: distance from the nearest start pixel that covers 90% of this look's pixels
        # (the single farthest pixel is often a separate fire on these multi-fire days)
        thin = case["start"][:: max(1, len(case["start"]) // 60)]
        dists = sorted(min(_km(s, p) for s in thin) for p in e["points"])
        obs_head = float(np.percentile(dists, 90))

        def reached(grid, lats, lons):
            t = _arrival_many(grid, lats, lons, plat, plon)
            return float(np.mean(t <= m))

        rows.append({
            "look": e["t"].strftime("%Y-%m-%d %H:%MZ"), "hours": round(m / 60, 1), "detections": len(e["points"]),
            "sensors": e["sensors"],
            "v2_reached_median": round(reached(a["t50"], dom.lats, dom.lons), 3),
            "v2_reached_worst": round(reached(a["t10"], dom.lats, dom.lons), 3),
            "v1_reached": round(reached(v1_arr, v1_dom.lats, v1_dom.lons), 3),
            "head_observed_km": round(obs_head, 1),
            "head_v2_km": [round(_head_km(a[k], dom, case["start"], m), 1) for k in ("t90", "t50", "t10")],
            "head_v1_km": round(_head_km(v1_arr, v1_dom, case["start"], m), 1),
        })
    _figure(case, fc, sit)
    w = sit.weather_steps()
    return {
        "slug": case["slug"], "title": FIRES[case["slug"]]["title"],
        "t0": case["t0"].strftime("%Y-%m-%d %H:%MZ"), "start_pixels": len(case["start"]),
        "start_clusters": case["start_clusters"],
        "first_sensors": case["first_sensors"], "origin": [round(lat0, 4), round(lon0, 4)],
        "weather": {"wind_kmh": [round(min(s.wind_kmh for s in w)), round(max(s.wind_kmh for s in w))],
                    "wind_from_first_last": [round(w[0].wind_from_deg), round(w[-1].wind_from_deg)],
                    "rh_min": round(min(s.rh_pct for s in w))},
        "fuel": fc["assumptions"]["fuel"], "cell_m": fc["grid"]["cell_m"], "horizon_min": horizon,
        "looks": rows,
    }


def _figure(case: dict, fc: dict, sit: Situation) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    a = fc["_arrival"]
    dom = a["domain"]
    fig, ax = plt.subplots(figsize=(7, 6))
    colors = plt.cm.viridis(np.linspace(0, 0.9, max(1, len(case["evals"]))))
    for e, c in zip(case["evals"], colors):
        ax.contour(dom.lons, dom.lats, np.where(a["t50"] <= 1e5, a["t50"], 1e6), levels=[e["minutes"]], colors=[c], linewidths=1.6)
        ax.contour(dom.lons, dom.lats, np.where(a["t10"] <= 1e5, a["t10"], 1e6), levels=[e["minutes"]], colors=[c], linewidths=0.8, linestyles="dashed")
        ax.scatter([p[1] for p in e["points"]], [p[0] for p in e["points"]], s=6, color=c,
                   label=f"seen +{e['minutes'] / 60:.1f} h ({len(e['points'])})")
    ax.scatter([p[1] for p in case["start"]], [p[0] for p in case["start"]], s=10, color="red", label="first look (start)")
    pts = [p for e in case["evals"] for p in e["points"]] + case["start"]
    lo_x, hi_x = min(p[1] for p in pts), max(p[1] for p in pts)
    lo_y, hi_y = min(p[0] for p in pts), max(p[0] for p in pts)
    pad_x, pad_y = (hi_x - lo_x) * 0.25 + 0.05, (hi_y - lo_y) * 0.25 + 0.05
    ax.set_xlim(lo_x - pad_x, hi_x + pad_x)
    ax.set_ylim(lo_y - pad_y, hi_y + pad_y)
    ax.set_aspect(1 / math.cos(math.radians(sit.ignition.lat)))
    ax.set_title(f"{FIRES[case['slug']]['title']}\nlines: forecast reach at each look (solid median, dashed worst case)", fontsize=9)
    ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    fig.savefig(FIG_DIR / f"{case['slug']}.png", dpi=140)
    plt.close(fig)


# ---------- report ----------

def report(results: list[dict]) -> str:
    def pct(x):
        return f"{x:.0%}"

    sections = []
    totals = {"v2m": [], "v2w": [], "v1": [], "n": []}
    for r in results:
        rows = []
        for lk in r["looks"]:
            lo, mid, hi = lk["head_v2_km"]
            rows.append(f"| {lk['look']} (+{lk['hours']} h) | {lk['detections']} | {pct(lk['v2_reached_median'])} | "
                        f"{pct(lk['v2_reached_worst'])} | {pct(lk['v1_reached'])} | **{lk['head_observed_km']}** | "
                        f"{lo}–{mid}–{hi} | {lk['head_v1_km']} |")
            for k, src in (("v2m", "v2_reached_median"), ("v2w", "v2_reached_worst"), ("v1", "v1_reached")):
                totals[k].append(lk[src] * lk["detections"])
            totals["n"].append(lk["detections"])
        w = r["weather"]
        sections.append(f"""### {r['title']}

Started from the {r['t0']} look: {r['start_pixels']} pixels in {r['start_clusters']} cluster(s) ({', '.join(r['first_sensors'])}), largest at {r['origin'][0]}, {r['origin'][1]}. Weather over the window: wind {w['wind_kmh'][0]}–{w['wind_kmh'][1]} km/h, from {w['wind_from_first_last'][0]}° at the start to {w['wind_from_first_last'][1]}° at the end; minimum RH {w['rh_min']}%. Fuel: {r['fuel']}. Grid {r['cell_m']:.0f} m.

| Later look | Pixels | v2 had fire there (median) | v2 (worst case) | v1 | Fire's reach seen (km) | v2 reach p90–p50–p10 (km) | v1 reach (km) |
|---|---|---|---|---|---|---|---|
""" + "\n".join(rows) + f"""

![{r['slug']}](figures/spread-backtest/{r['slug']}.png)
""")
    n = sum(totals["n"]) or 1
    overall = {k: sum(v) / n for k, v in totals.items() if k != "n"}
    return f"""# Spread forecast back-test v1

Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `backend/ml/backtest.py`. Raw results: [spread-backtest-v1.json](spread-backtest-v1.json).

**Question:** if Firewatch had started forecasting from a real fire's first satellite look, would it have put fire where the later satellite looks found it, and about as far out as the fire actually ran?

## Method

1. **Fires.** Large Plains grass fires with real NASA FIRMS archive detections (VIIRS 375 m, MODIS 1 km): Anderson Creek 2016 and Starbuck 2017. The December 15, 2021 outbreak was examined but not scored; see below.
2. **Start (t0).** The first satellite look with detections in the study area. Every cluster of at least {MIN_START_PIXELS} pixels (pixels ≤ {FIRST_CLUSTER_KM:g} km apart) is burning, and the forecast starts from all of them as established fire.
3. **What's scored:** every detection in the study area at every later look within {HORIZON_MIN // 60} h. It's area-level, not fire-level, decided without the forecast. A fire that starts after t0 counts as a miss, so the scores are conservative.
4. **Weather.** The Open-Meteo archive's hourly values at the fire for the 13 hours after t0. That's the real weather, so this tests the fire model, not a weather forecast. The ensemble's ±15% wind / ±15° direction spread stands in for forecast error.
5. **Forecasts:**
   - **v2** (current): hourly wind, NLCD/CDL fuel map, terrain, 24-member ensemble
   - **v1** (original): one run, the first hour's wind held constant, everything treated as grass
6. **Scores, at each later look:**
   - **Reached:** the share of detected pixels where the forecast had fire by then. Median for v2, worst case (10th-percentile arrival) for v2, and the single run for v1. A detected pixel is burning at that moment, so the fire got there no later than the look.
   - **Reach:** the distance from the start pixels that covers 90% of the look's detections, against the same measure over the forecast's burned cells at that time. It's 90% rather than the farthest pixel because on multi-fire days the farthest detection is often a different fire.

## Overall

Across {n} later detections: v2's median forecast had fire at **{overall['v2m']:.0%}** of them, v2's worst case at **{overall['v2w']:.0%}**, and v1 at **{overall['v1']:.0%}**.

## What it showed (v1 run, 2026-11-07; update this section when the model changes)

1. **v2 places fire where satellites later found it far more often than v1:** 55% vs 29% of later detections (median forecast), 70% with the worst case. The biggest gain is Anderson Creek's next-afternoon look, **70% vs 25%**, where the fuel map and the changing wind both matter.
2. **Anderson Creek's reach was inside the forecast range.** At 14–15 h the fire had reached 22–24 km; v2's range (90th to 10th percentile of runs) was 14–41 km, with the median about 30% long. At +4 h, overnight, v2 was too slow (6 km vs 12 km), but its worst case matched.
3. **Starbuck was under-predicted by about 2×:** reach seen 50–57 km at 9–14 h, v2 22–26 km, and even the worst case was under. Part is the scoring: separate fires to the south, not connected to any starting cluster (see the map), count as misses. Part is real:
   - the archive's wind drops to ~8 km/h overnight and humidity recovers, so the model slows the fire, while the real fire kept running behind the cold front
   - the ensemble's spread (±15% wind) is too narrow to cover that
4. **What to change next (not done yet):**
   - widen the ensemble on frontal nights, or add a member that uses gusts instead of sustained wind
   - check the moisture function's overnight recovery
   - calibrate on more fires using GOES 5-minute fire data (2018 and later), which would give dozens of looks per fire instead of 3–5

**For the pitch:** on Anderson Creek, the forecast put fire where satellites found it 15 hours later 70–81% of the time, against 25% for a simple constant-wind estimate. On Starbuck it ran too slow overnight, and that's the next calibration target.

## By fire

""" + "\n".join(sections) + """
## Not scored

""" + "\n".join(f"- **{k}:** {v['title']}. {v['why']}" for k, v in NOT_SCORED.items()) + """

## How to read this, and its limits

- **"Reached" rewards over-prediction.** A forecast that burns the whole map scores 100%. That's why head run is reported next to it: a good forecast reaches the detections *and* has a head run close to the farthest one. A worst-case reach far beyond the observed head means the warning area was too big.
- **Satellites look rarely.** Polar orbiters pass a few times a day, so most later looks are 8–12 hours after the start, overnight. Fire that burned and went out between looks isn't seen. The head run seen is the farthest *active* fire at that look, a lower bound on how far the fire had run.
- **No suppression** in the model. Crews, dozer lines and roads stop real fires; the model's fire never stops except at water, towns and green fields.
- **Hindcast weather.** This uses the archive's actual weather, not the forecast that was available on the day, so real-time accuracy will be somewhat worse.
- **Two fires scored.** These are big, wind-driven Plains fires, the kind Firewatch is for, but they're a small sample. Calibrating the fuel multipliers and ensemble spread needs more fires (Michael's WFIGS list, Dec 2021 outbreak, 2024–2026 GOES data at 5-minute looks).

## Rebuild

```bash
cd backend && .venv/bin/python -m ml.backtest
```
"""


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    results = []
    for slug in FIRES:
        case = fire_case(slug)
        if not case["evals"]:
            log.warning("%s: no later looks within %d h", slug, HORIZON_MIN // 60)
            continue
        log.info("%s: t0 %s, %d start pixels, %d later looks", slug, case["t0"], len(case["start"]), len(case["evals"]))
        results.append(score(case))
    RESULTS_PATH.write_text(json.dumps(results, indent=1))
    REPORT_PATH.write_text(report(results))
    log.info("wrote %s", REPORT_PATH)


if __name__ == "__main__":
    main()
