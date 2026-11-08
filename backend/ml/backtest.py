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
import time
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
    "ranger-road-2026": {
        "title": "Ranger Road fire, Beaver Co. OK (February 17, 2026; 283,283 ac)",
        # 2026 isn't in the yearly archive files yet: the FIRMS area API (needs FIRMS_MAP_KEY) and GOES-19 instead.
        # The box leaves out the Stevens fire (Texas Co. OK) and Andrew Lane fire (Seward Co. KS) to the west.
        "api": {"date": "2026-02-17", "days": 2, "sources": ["VIIRS_NOAA20_SP", "VIIRS_NOAA21_NRT", "MODIS_SP", "VIIRS_SNPP_SP"]},
        "box": (36.4, 37.7, -100.6, -99.2),
        "goes": "noaa-goes19",
        "discovered": "2026-02-17T17:19:00+00:00",  # WFIGS FireDiscoveryDateTime
        "packet_first_hour_acres": 15000,  # competitor packet: "burned 15,000 acres in its first hour"
    },
}
GOES_EVERY_MIN = 30
GOES_HOURS = 8
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
    if "api" in f:
        rows = _api_detections(f)
    for folder, year in f.get("sources", []):
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


def _api_detections(f: dict) -> list[dict]:
    """FIRMS area API (recent years not yet in the yearly files). A source that keeps failing is skipped."""
    from app.config import get_settings

    key = get_settings().firms_map_key
    if not key:
        raise RuntimeError("FIRMS_MAP_KEY is needed for this fire (set it in .env)")
    s, n, w, e = f["box"]
    api = f["api"]
    rows = []
    for src in api["sources"]:
        for attempt in range(3):
            try:
                r = httpx.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{w},{s},{e},{n}/{api['days']}/{api['date']}",
                              timeout=240)
                if r.status_code == 200 and r.text.startswith("latitude"):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(20 * (attempt + 1))
        else:
            log.warning("FIRMS %s unavailable; skipped", src)
            continue
        for x in csv.DictReader(io.StringIO(r.text)):
            t = datetime.strptime(f"{x['acq_date']} {x['acq_time'].zfill(4)}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
            rows.append({"lat": float(x["latitude"]), "lon": float(x["longitude"]), "t": t.isoformat(), "sensor": src.lower(),
                         "conf": x.get("confidence"), "frp": float(x.get("frp") or 0)})
    return rows


def goes_looks(slug: str, t0: datetime, horizon_min: float) -> list[dict]:
    """GOES-R fire pixels (ABI FDCC, 2 km) every GOES_EVERY_MIN minutes after t0, inside the fire's box."""
    from app.ingest import goes_fire, s3

    f = FIRES[slug]
    path = OUT_DIR / f"{slug}-goes.json"
    if path.exists():
        cached = json.loads(path.read_text())
        return [c | {"t": datetime.fromisoformat(c["t"])} for c in cached]
    s, n, w, e = f["box"]
    goes_fire.in_bbox = lambda lon, lat: s <= lat <= n and w <= lon <= e  # the feed filters to the Kansas box
    out = []
    for k in range(1, int(min(horizon_min, GOES_HOURS * 60) // GOES_EVERY_MIN) + 1):
        want = t0 + timedelta(minutes=k * GOES_EVERY_MIN)
        keys = s3.list_keys(f["goes"], s3.hour_prefix(goes_fire.PRODUCT, want))
        if not keys:
            continue
        key = min(keys, key=lambda kk: abs((s3.scan_start(kk) - want).total_seconds()))
        px = goes_fire.parse(s3.get_bytes(f["goes"], key), f["goes"].split("-")[-1])
        if px:
            out.append({"t": s3.scan_start(key), "points": [(p["lat"], p["lon"]) for p in px]})
    path.write_text(json.dumps([o | {"t": o["t"].isoformat()} for o in out]))
    return out


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
              "sensors": sorted({r["sensor"] for r in rs}), "goes": False}
             for t, rs in ls[1:] if (t - t0).total_seconds() / 60 <= HORIZON_MIN]
    if FIRES[slug].get("goes"):
        evals += [{"t": g["t"], "minutes": (g["t"] - t0).total_seconds() / 60, "points": g["points"],
                   "sensors": [FIRES[slug]["goes"].split("-")[-1]], "goes": True}
                  for g in goes_looks(slug, t0, max([e["minutes"] for e in evals] or [HORIZON_MIN]))]
        evals.sort(key=lambda e: e["minutes"])
    return {"slug": slug, "t0": t0, "start": [p for c in starts for p in c], "start_clusters": len(starts),
            "anchor": starts[0], "first_sensors": sorted({r["sensor"] for r in first}), "evals": evals}


def situation(case: dict) -> Situation:
    lat = float(np.mean([p[0] for p in case["anchor"]]))
    lon = float(np.mean([p[1] for p in case["anchor"]]))
    t0 = case["t0"]
    series, _ = weather_series(lat, lon, t0 - timedelta(hours=1), HORIZON_MIN // 60 + 2)
    src = Provenance(source="open-meteo archive (hourly, at the fire)", kind="observed")
    return Situation(
        ignition=Ignition(lat=lat, lon=lon, time=t0, points=case["start"], fire_age_min=None,
                          provenance=Provenance(source="FIRMS first look", kind="observed")),
        weather=Weather(hours=[WeatherHour(**h) for h in series], provenance=src),
    )


# ---------- scoring ----------

FRONT_WINDOW_MIN = 60


def _head_km(grid: np.ndarray, dom, starts: list[tuple[float, float]], minute: float) -> float:
    """Distance from the nearest start pixel that covers 90% of the forecast's ACTIVE FRONT: cells that caught fire
    in the last hour. Satellites see active flame, not burned-out interior, so this is the like-for-like measure."""
    front = (grid <= minute) & (grid > minute - FRONT_WINDOW_MIN)
    if not front.any():
        front = grid <= minute  # the fire stopped: fall back to its whole footprint
    if not front.any():
        return 0.0
    ii, jj = np.nonzero(front)
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
            "sensors": e["sensors"], "goes": e["goes"],
            "v2_reached_median": round(reached(a["t50"], dom.lats, dom.lons), 3),
            "v2_reached_worst": round(reached(a["t10"], dom.lats, dom.lons), 3),
            "v1_reached": round(reached(v1_arr, v1_dom.lats, v1_dom.lons), 3),
            "head_observed_km": round(obs_head, 1),
            "head_v2_km": [round(_head_km(a[k], dom, case["start"], m), 1) for k in ("t90", "t50", "t10")],
            "head_v1_km": round(_head_km(v1_arr, v1_dom, case["start"], m), 1),
        })
    _figure(case, fc, sit)
    w = sit.weather_steps()
    first_hour = _first_hour(case, sit) if FIRES[case["slug"]].get("discovered") else None
    return {
        "first_hour": first_hour,
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


def _first_hour(case: dict, sit: Situation) -> dict:
    """Start a new point ignition at the reported discovery time, at the upwind end of the first look, and
    compare its first-hour size with the packet's figure and its reach at the first look with what was seen."""
    f = FIRES[case["slug"]]
    t_disc = datetime.fromisoformat(f["discovered"])
    lead = (case["t0"] - t_disc).total_seconds() / 60
    series, _ = weather_series(sit.ignition.lat, sit.ignition.lon, t_disc - timedelta(hours=1), int(lead // 60) + 3)
    w0 = min(series, key=lambda h: abs((h["time"] - t_disc).total_seconds()))
    down = math.radians((w0["wind_from_deg"] + 180) % 360)
    ref = case["anchor"][0]
    kx = km_per_deg_lon(ref[0])

    def along(p):  # km downwind of the reference pixel
        return (p[1] - ref[1]) * kx * math.sin(down) + (p[0] - ref[0]) * KM_PER_DEG_LAT * math.cos(down)

    ign = min(case["anchor"], key=along)
    sit0 = Situation(
        ignition=Ignition(lat=ign[0], lon=ign[1], time=t_disc, fire_age_min=0,
                          provenance=Provenance(source="upwind end of the first satellite look (assumed ignition)", kind="inferred")),
        weather=Weather(hours=[WeatherHour(**h) for h in series], provenance=sit.weather.provenance),
    )
    horizon = int(math.ceil(lead / 10) * 10)
    fc = forecast(sit0, max(60, horizon), MEMBERS)
    cp = {c["minutes"]: c for c in fc["checkpoints"]}
    a = fc["_arrival"]
    seen = float(np.percentile([_km(ign, p) for p in case["anchor"]], 90))
    reach = [round(_head_km(a[k], a["domain"], [ign], lead), 1) for k in ("t90", "t50", "t10")]
    to_ac = 1 / 0.404686
    return {
        "discovered": t_disc.strftime("%H:%MZ"), "first_look": case["t0"].strftime("%H:%MZ"), "lead_min": round(lead),
        "ignition": [round(ign[0], 4), round(ign[1], 4)], "wind_at_start": f"{round(w0['wind_kmh'])} km/h from {round(w0['wind_from_deg'])}°",
        "acres_60": {k: round(v * to_ac) for k, v in cp[60]["area_ha"].items()} if 60 in cp else None,
        "packet_acres_60": f["packet_first_hour_acres"],
        "reach_at_first_look_km": {"seen": round(seen, 1), "forecast_p90_p50_p10": reach},
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
    totals = {g: {"v2m": [], "v2w": [], "v1": [], "n": []} for g in ("polar", "goes")}
    for r in results:
        rows = []
        for lk in r["looks"]:
            lo, mid, hi = lk["head_v2_km"]
            tag = " GOES" if lk.get("goes") else ""
            rows.append(f"| {lk['look']} (+{lk['hours']} h){tag} | {lk['detections']} | {pct(lk['v2_reached_median'])} | "
                        f"{pct(lk['v2_reached_worst'])} | {pct(lk['v1_reached'])} | **{lk['head_observed_km']}** | "
                        f"{lo}–{mid}–{hi} | {lk['head_v1_km']} |")
            t = totals["goes" if lk.get("goes") else "polar"]
            for k, src in (("v2m", "v2_reached_median"), ("v2w", "v2_reached_worst"), ("v1", "v1_reached")):
                t[k].append(lk[src] * lk["detections"])
            t["n"].append(lk["detections"])
        fh = r.get("first_hour")
        first = "" if not fh else f"""
**First hour.** A new fire started at the reported discovery time ({fh['discovered']}) at the upwind end of the first look ({fh['ignition'][0]}, {fh['ignition'][1]}; assumed ignition), wind {fh['wind_at_start']}:
- size at 60 minutes, forecast p10 / median / p90: **{fh['acres_60']['p10']:,} / {fh['acres_60']['p50']:,} / {fh['acres_60']['p90']:,} ac**, against the packet's **{fh['packet_acres_60']:,} ac**
- reach at the first satellite look ({fh['first_look']}, {fh['lead_min']} min after discovery): seen {fh['reach_at_first_look_km']['seen']} km; forecast {'–'.join(str(x) for x in fh['reach_at_first_look_km']['forecast_p90_p50_p10'])} km (p90–p50–p10 runs)
"""
        w = r["weather"]
        sections.append(f"""### {r['title']}

Started from the {r['t0']} look: {r['start_pixels']} pixels in {r['start_clusters']} cluster(s) ({', '.join(r['first_sensors'])}), largest at {r['origin'][0]}, {r['origin'][1]}. Weather over the window: wind {w['wind_kmh'][0]}–{w['wind_kmh'][1]} km/h, from {w['wind_from_first_last'][0]}° at the start to {w['wind_from_first_last'][1]}° at the end; minimum RH {w['rh_min']}%. Fuel: {r['fuel']}. Grid {r['cell_m']:.0f} m.

| Later look | Pixels | v2 had fire there (median) | v2 (worst case) | v1 | Fire's reach seen (km) | v2 reach p90–p50–p10 (km) | v1 reach (km) |
|---|---|---|---|---|---|---|---|
""" + "\n".join(rows) + f"""
{first}
![{r['slug']}](figures/spread-backtest/{r['slug']}.png)
""")
    n = sum(totals["polar"]["n"]) or 1
    overall = {k: sum(v) / n for k, v in totals["polar"].items() if k != "n"}
    ng = sum(totals["goes"]["n"])
    goes_line = "" if not ng else (
        f" On {ng} GOES pixels (2 km, every 30 min): v2 median {sum(totals['goes']['v2m']) / ng:.0%}, worst case "
        f"{sum(totals['goes']['v2w']) / ng:.0%}, v1 {sum(totals['goes']['v1']) / ng:.0%}.")
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
   - **Reach:** the distance from the start pixels that covers 90% of the look's detections, against the same measure over the forecast's **active front** (cells that caught fire in the hour before the look). Satellites see active flame, not the burned-out interior, so comparing against the whole forecast footprint would understate the forecast's reach. It's 90% rather than the farthest pixel because on multi-fire days the farthest detection is often a different fire.
7. **Ranger Road 2026** isn't in the yearly archive yet. Its detections come from the FIRMS area API, plus GOES-19 fire pixels (2 km) every 30 minutes for the first 8 hours, scored separately. A first-hour check starts a new fire at the reported discovery time at the upwind end of the first look; that ignition point is assumed, since WFIGS has no coordinates.

## Overall

Across {n} later polar-orbiter detections (VIIRS 375 m, MODIS 1 km): v2's median forecast had fire at **{overall['v2m']:.0%}** of them, v2's worst case at **{overall['v2w']:.0%}**, and v1 at **{overall['v1']:.0%}**.{goes_line}

## What it showed (run of 2026-11-07, with the extreme-day runs; update this section when the model changes)

1. **v2 places fire where satellites later found it far more often than v1:** 59% vs 34% of later polar-orbiter detections (median forecast), **77% with the worst case**. On GOES pixels every 30 minutes: 41% median, 66% worst case, vs 37% for v1. The biggest gain is Anderson Creek's next-afternoon look, 75% vs 25%, where the fuel map and the changing wind both matter.
2. **On extreme-wind days the grassfire formula alone runs 2–4× too slow.** Starbuck and Ranger Road ran at about 20% of their 80–90 km/h gusts. Testing ruled out the fuel map (Ranger Road's path was 97% grass) and curing.
   - The fix: 6 of the 24 runs spread at 20% of gust speed on dry, gusty days (spread.GUST_RULE_*).
   - Ranger Road: the worst case at +12–14 h now reaches 53–57 km against 49–51 km seen. Before the fix it was 43–44 km.
   - Starbuck: closer (36–41 km against 50–57) but still short. Part of the gap is separate fires to the south that count as misses.
   - The median is barely changed, by design.
3. **On a moist night (Anderson Creek) the forecast runs long:** 41 km median vs 24 km seen at 15 h. The extreme-day rule doesn't apply there, and the best-case runs (29 km) are closest.
4. **Ranger Road's first hour is still under-called:** 1,306 ac (median) to 3,387 ac (upper) against the packet's 15,000 ac. GOES saw nothing of the fire until 1–2 hours after its reported discovery.
5. **Data note:** in this run 8 land-cover tiles at the far edges of the Starbuck and Ranger Road map areas failed to download and were filled in as grass (the fuel line in each section says so).
6. **Next:** more fires with GOES 5-minute data (2018 and later) to calibrate the main formula, instead of only widening the worst case.

**For the pitch:** started from the first satellite look of three real Plains fires, the forecast's range contained 77% of where satellites found fire over the next 15 hours, against 34% for a simple estimate. Where it fell short, on extreme-wind days, we found out why and changed it.

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
