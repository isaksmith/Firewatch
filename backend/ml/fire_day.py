"""Fire-day model v1: how fire danger changes the odds that a fire starts, and that it gets large.

    .venv/bin/python -m ml.fire_day            # download (cached), fit, write data/model/fire_day.json + report

Question 1 (ignition): on a day at fire-danger level B, how many more reported wildfires start than on a "High"
day, per unit of land and time? Answer: the relative rate RR(B) = (fires on B-days / B point-days) /
(fires on High days / High point-days). It replaces the hand-set danger multiplier on the line-fault base rate
in the decision model (app/decision.py).

Question 2 (consequence): of the fires that started at level B, what share grew past 300 and 1,000 acres?
Shown to the dispatcher as a historical check next to the spread forecast; not used in the expected loss
(the forecast already gives this fire's acres, and using both would count the weather twice).

Data and method, and every limit, are written into the report (docs/research/fire-day-model-v1.md):
  fires    WFIGS incident locations, Kansas, wildfires (IncidentTypeCategory = WF), discovered 2016-2025
  weather  Open-Meteo archive (ERA5-based) daily Tmax, min RH, max wind, on a 1-degree grid over Kansas
  danger   McArthur GFDI from those daily values with the app's seasonal curing table, banded as in the app
"""

import json
import logging
import math
import time
from collections import Counter
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import numpy as np

from app.fire_weather import default_curing, gfdi, gfdi_band

from .paths import KS_BBOX, MODEL_DIR, WORK_DIR

log = logging.getLogger("fire_day")
CENTRAL = ZoneInfo("America/Chicago")
OUT_DIR = WORK_DIR / "fire_day"
MODEL_PATH = MODEL_DIR / "fire_day.json"
REPO_DIR = MODEL_DIR.parent.parent.parent
REPORT_PATH = REPO_DIR / "docs" / "research" / "fire-day-model-v1.md"
FIG_DIR = REPO_DIR / "docs" / "research" / "figures" / "fire-day"

WFIGS_URL = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
             "WFIGS_Incident_Locations/FeatureServer/0/query")
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START, END = date(2016, 1, 1), date(2025, 12, 31)
GRID_STEP = 1.0
DAILY = "temperature_2m_max,relative_humidity_2m_min,wind_speed_10m_max,wind_gusts_10m_max,precipitation_sum"
BANDS = ("Low-Moderate", "High", "Very High", "Severe", "Extreme")
REFERENCE = "High"
MIN_FIRES = 5  # a band with fewer fires is pooled with the band below it before it is used
LARGE = (300, 1000)


# ---------- data ----------

def fetch_wfigs() -> list[dict]:
    path = OUT_DIR / "wfigs_ks_wildfires.json"
    if path.exists():
        return json.loads(path.read_text())
    fields = ("UniqueFireIdentifier,IncidentName,FireDiscoveryDateTime,IncidentSize,FinalAcres,DiscoveryAcres,"
              "FireCause,FireCauseGeneral,InitialLatitude,InitialLongitude")
    out, offset = [], 0
    while True:
        r = httpx.get(WFIGS_URL, params={
            "where": "POOState='US-KS' AND IncidentTypeCategory='WF'", "outFields": fields, "returnGeometry": "true",
            "outSR": 4326, "f": "json", "resultOffset": offset, "resultRecordCount": 1000,
            "orderByFields": "FireDiscoveryDateTime"}, timeout=90)
        r.raise_for_status()
        js = r.json()
        for feat in js["features"]:
            a, g = feat["attributes"], feat.get("geometry") or {}
            out.append({
                "id": a["UniqueFireIdentifier"], "name": a["IncidentName"], "discovered_ms": a["FireDiscoveryDateTime"],
                "acres": a["FinalAcres"] if a["FinalAcres"] is not None else a["IncidentSize"],
                "cause": a["FireCause"], "cause_general": a["FireCauseGeneral"],
                "lat": a["InitialLatitude"] or g.get("y"), "lon": a["InitialLongitude"] or g.get("x"),
            })
        if not js.get("exceededTransferLimit"):
            break
        offset += len(js["features"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def grid_points() -> list[tuple[float, float]]:
    w, s, e, n = KS_BBOX
    lons = np.arange(w + GRID_STEP / 2, e, GRID_STEP)
    lats = np.arange(s + GRID_STEP / 2, n, GRID_STEP)
    return [(round(float(la), 3), round(float(lo), 3)) for la in lats for lo in lons]


def fetch_weather(points: list[tuple[float, float]]) -> dict:
    """{(lat, lon): {date iso: (tmax, rhmin, wind_max, gust_max, precip)}}, cached per point."""
    cache_dir = OUT_DIR / "weather"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for lat, lon in points:
        path = cache_dir / f"{lat}_{lon}.json"
        if not path.exists():
            for attempt in range(5):
                r = httpx.get(ARCHIVE_URL, params={
                    "latitude": lat, "longitude": lon, "start_date": START.isoformat(), "end_date": END.isoformat(),
                    "daily": DAILY, "wind_speed_unit": "kmh", "timezone": "America/Chicago"}, timeout=120)
                if r.status_code == 429:
                    log.info("rate limited, waiting %ds", 30 * (attempt + 1))
                    time.sleep(30 * (attempt + 1))
                    continue
                r.raise_for_status()
                path.write_text(r.text)
                break
            else:
                raise RuntimeError(f"Open-Meteo kept rate-limiting {lat},{lon}")
            log.info("weather %s,%s cached", lat, lon)
        d = json.loads(path.read_text())["daily"]
        out[(lat, lon)] = {t: tuple(d[k][i] for k in DAILY.split(",")) for i, t in enumerate(d["time"])}
    return out


def daily_band(month: int, tmax, rhmin, wind_max) -> tuple[float, str] | None:
    if None in (tmax, rhmin, wind_max):
        return None
    g = gfdi(default_curing(month), tmax, rhmin, wind_max)
    return g, gfdi_band(g)


# ---------- statistics ----------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate_ratio(k: int, e: float, k0: int, e0: float, z: float = 1.96) -> tuple[float, float, float] | None:
    """Ratio of two Poisson rates (k/e) / (k0/e0) with a log-normal 95% interval."""
    if k == 0 or k0 == 0:
        return None
    rr = (k / e) / (k0 / e0)
    se = math.sqrt(1 / k + 1 / k0)
    return rr, rr * math.exp(-z * se), rr * math.exp(z * se)


def fit() -> dict:
    fires = fetch_wfigs()
    points = grid_points()
    wx = fetch_weather(points)
    pts = np.array(points)

    # exposure: point-days in each band, and each point-day's band for the fires to look up
    exposure: Counter = Counter()
    band_of: dict[tuple, tuple[float, str]] = {}
    gfdi_by_band: dict[str, list[float]] = {b: [] for b in BANDS}
    for p, days in wx.items():
        for day, (tmax, rhmin, wmax, _gust, _pr) in days.items():
            r = daily_band(int(day[5:7]), tmax, rhmin, wmax)
            if r is None:
                continue
            band_of[(p, day)] = r
            exposure[r[1]] += 1
            gfdi_by_band[r[1]].append(r[0])

    used, skipped = [], Counter()
    for f in fires:
        if f["lat"] is None or f["lon"] is None or f["discovered_ms"] is None:
            skipped["no location or date"] += 1
            continue
        local = datetime.fromtimestamp(f["discovered_ms"] / 1000, timezone.utc).astimezone(CENTRAL).date()
        if not (START <= local <= END):
            skipped["outside 2016-2025"] += 1
            continue
        w, s, e, n = KS_BBOX
        if not (w <= f["lon"] <= e and s <= f["lat"] <= n):
            skipped["outside Kansas box"] += 1
            continue
        k = int(np.argmin((pts[:, 0] - f["lat"]) ** 2 + (pts[:, 1] - f["lon"]) ** 2))
        r = band_of.get((points[k], local.isoformat()))
        if r is None:
            skipped["no weather that day"] += 1
            continue
        used.append(f | {"date": local.isoformat(), "gfdi": round(r[0], 1), "band": r[1]})

    fires_by_band = Counter(f["band"] for f in used)
    total_exp = sum(exposure.values())
    bands = {}
    for b in BANDS:
        sized = [f for f in used if f["band"] == b and f["acres"] is not None]
        large = {str(t): {"k": sum(1 for f in sized if f["acres"] >= t), "n": len(sized)} for t in LARGE}
        for v in large.values():
            v["p"] = round(v["k"] / v["n"], 3) if v["n"] else None
            v["ci"] = [round(x, 3) for x in wilson(v["k"], v["n"])]
        rr = rate_ratio(fires_by_band[b], exposure[b], fires_by_band[REFERENCE], exposure[REFERENCE])
        g = gfdi_by_band[b]
        bands[b] = {
            "point_days": exposure[b], "share_of_days": round(exposure[b] / total_exp, 4) if total_exp else 0,
            "gfdi_range": [round(min(g), 1), round(max(g), 1)] if g else None,
            "fires": fires_by_band[b],
            "fires_per_10k_point_days": round(fires_by_band[b] / exposure[b] * 1e4, 2) if exposure[b] else None,
            "rr": round(rr[0], 2) if rr else None, "rr_ci": [round(rr[1], 2), round(rr[2], 2)] if rr else None,
            "large": large,
        }

    multiplier, pooled_from = _multiplier(bands)
    model = {
        "version": "fire-day-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {
            "fires_source": "NIFC WFIGS Incident Locations, POOState = US-KS, IncidentTypeCategory = WF",
            "weather_source": "Open-Meteo historical archive (daily Tmax, min RH, max 10 m wind)",
            "period": [START.isoformat(), END.isoformat()], "grid_step_deg": GRID_STEP, "grid_points": len(points),
            "fires_downloaded": len(fires), "fires_used": len(used), "fires_skipped": dict(skipped),
            "causes": dict(Counter(f["cause"] for f in used)),
            "cause_general": dict(Counter(f["cause_general"] for f in used)),
        },
        "reference_band": REFERENCE,
        "bands": bands,
        "danger_multiplier": multiplier,
        "pooled": pooled_from,
    }
    MODEL_PATH.write_text(json.dumps(model, indent=1))
    _figures(model)
    REPORT_PATH.write_text(report(model))
    log.info("wrote %s and %s", MODEL_PATH, REPORT_PATH)
    return model


def _multiplier(bands: dict) -> tuple[dict, dict]:
    """The relative rates the decision model uses: bands with too few fires take the rate of the band below,
    and the result is made non-decreasing (more danger never lowers the odds; small counts can't prove it does)."""
    out, pooled, last = {}, {}, None
    for b in BANDS:
        rr = bands[b]["rr"]
        if bands[b]["fires"] < MIN_FIRES or rr is None:
            if last is not None:
                pooled[b] = f"only {bands[b]['fires']} fires: uses the {last[0]} rate"
                rr = last[1]
            else:
                rr = 1.0
        if last is not None and rr < last[1]:
            pooled[b] = pooled.get(b, f"raw rate {rr} is below {last[0]}'s; held at {last[1]}")
            rr = last[1]
        out[b] = round(rr, 2)
        last = (b, rr)
    out[REFERENCE] = 1.0
    return out, pooled


def _figures(m: dict) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib not installed; skipping figures")
        return
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    bs = [b for b in BANDS if m["bands"][b]["rr"] is not None]
    rr = [m["bands"][b]["rr"] for b in bs]
    lo = [rr[i] - m["bands"][b]["rr_ci"][0] for i, b in enumerate(bs)]
    hi = [m["bands"][b]["rr_ci"][1] - rr[i] for i, b in enumerate(bs)]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.bar(bs, rr, color="#ff4b2b", alpha=0.8)
    ax.errorbar(bs, rr, yerr=[lo, hi], fmt="none", ecolor="#222", capsize=4)
    ax.scatter(BANDS, [m["danger_multiplier"][b] for b in BANDS], color="#111", zorder=5, label="multiplier used")
    ax.axhline(1, color="#888", lw=0.8, ls="--")
    ax.set_ylabel(f"Fire starts per day vs. {REFERENCE}")
    ax.set_title("Kansas wildfire starts by fire-danger level, 2016-2025 (95% CI)")
    ax.set_xticks(range(len(bs)), [f"{b}\n{m['bands'][b]['fires']} fires" for b in bs])
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "ignition_rate_by_band.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.6))
    x = np.arange(len(BANDS))
    for j, (t, c) in enumerate(zip(LARGE, ("#ffb21a", "#ff4b2b"))):
        ps = [(m["bands"][b]["large"][str(t)]["p"] or 0) * 100 for b in BANDS]
        cis = [m["bands"][b]["large"][str(t)]["ci"] for b in BANDS]
        err = [[p - ci[0] * 100 for p, ci in zip(ps, cis)], [ci[1] * 100 - p for p, ci in zip(ps, cis)]]
        ax.bar(x + (j - 0.5) * 0.38, ps, 0.38, color=c, label=f"grew past {t:,} ac")
        ax.errorbar(x + (j - 0.5) * 0.38, ps, yerr=err, fmt="none", ecolor="#222", capsize=3)
    ax.set_xticks(x, [f"{b}\n{m['bands'][b]['large']['300']['n']} fires" for b in BANDS])
    ax.set_ylabel("% of reported wildfires")
    ax.set_title("Share of Kansas wildfires that got large, by fire danger on the start day (95% CI)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "large_fire_share_by_band.png", dpi=150)
    plt.close(fig)


# ---------- report ----------

def report(m: dict) -> str:
    d, B = m["data"], m["bands"]

    def ci(x):
        return f"{x[0]:.2f}–{x[1]:.2f}" if x else "—"

    rows = "\n".join(
        f"| {b} | {B[b]['gfdi_range'][0] if B[b]['gfdi_range'] else '—'}–{B[b]['gfdi_range'][1] if B[b]['gfdi_range'] else '—'} "
        f"| {B[b]['point_days']:,} ({B[b]['share_of_days']:.1%}) | {B[b]['fires']} | {B[b]['fires_per_10k_point_days'] or '—'} "
        f"| {B[b]['rr'] if B[b]['rr'] is not None else '—'} | {ci(B[b]['rr_ci'])} | **{m['danger_multiplier'][b]}** |"
        for b in BANDS)
    large_rows = "\n".join(
        f"| {b} | {B[b]['large']['300']['n']} | "
        + " | ".join(
            f"{B[b]['large'][str(t)]['k']} ({(B[b]['large'][str(t)]['p'] or 0):.0%}, {B[b]['large'][str(t)]['ci'][0]:.0%}–{B[b]['large'][str(t)]['ci'][1]:.0%})"
            for t in LARGE) + " |"
        for b in BANDS)
    per_fault = "\n".join(
        f"| {b} | {m['danger_multiplier'][b]} | {m['danger_multiplier'][b] ** 0.5:.2f} | {min(0.9, 0.03 * m['danger_multiplier'][b] ** 0.5):.1%} |"
        for b in BANDS)
    pooled = "\n".join(f"- **{b}:** {why}" for b, why in m["pooled"].items()) or "- None."
    skipped = ", ".join(f"{v} {k}" for k, v in d["fires_skipped"].items()) or "none"
    causes = ", ".join(f"{k or 'blank'}: {v}" for k, v in sorted(d["causes"].items(), key=lambda kv: -kv[1]))
    general = ", ".join(f"{k or 'blank'}: {v}" for k, v in sorted(d["cause_general"].items(), key=lambda kv: -kv[1]))
    return f"""# Fire-day model v1

Generated {m['generated_at']} by `backend/ml/fire_day.py`. Model file: `backend/data/model/fire_day.json`.

This model answers two questions about the **day**, not the individual fire:

1. **Ignition:** on a day at a given fire-danger level, how many more wildfires start than on a {REFERENCE} day? The answer replaces the hand-set "danger multiplier" in the recommendation model (see [How Firewatch recommends actions](../RECOMMENDATIONS.md)).
2. **Consequence:** of the fires that started at that level, what share grew past 300 and 1,000 acres? It's shown next to the spread forecast as a historical check, but not used in the expected loss.

## Data

| | |
|---|---|
| Fires | {d['fires_source']}. Downloaded {d['fires_downloaded']}; used **{d['fires_used']}** (skipped: {skipped}). |
| Period | {d['period'][0]} to {d['period'][1]} (discovery date, Central time) |
| Weather | {d['weather_source']}, on a {d['grid_step_deg']:g}° grid over the Kansas box ({d['grid_points']} points). Each fire takes its nearest grid point's weather on its discovery date. |
| Fire danger | McArthur grassland fire danger index (the app's `fire_weather.gfdi`) from daily max temperature, min humidity and max wind, with the app's seasonal grass-curing table, banded as the app bands it. |
| Causes in the data | FireCause: {causes}. FireCauseGeneral: {general}. |

## Method

**Exposure.** Every grid point on every day is one point-day, banded by that day's fire danger. Points are evenly spaced, so a band's share of point-days is its share of Kansas land-time.

**Ignition rate.** For each band, divide the fires that started on that band's days by the band's point-days. Then divide by the same rate for {REFERENCE} days to get the relative rate (RR). The 95% interval treats both counts as Poisson: log-normal, with standard error √(1/k + 1/k₀).

**Multiplier used by the app.** The RR, with two guards:
- a band with fewer than {MIN_FIRES} fires uses the band below's rate
- the multiplier never decreases as danger rises, since small counts can't show that more danger means fewer fires

{REFERENCE} is fixed at 1.

**Large fires.** The share of each band's fires (those with a reported size) at or above 300 and 1,000 acres, with Wilson 95% intervals.

## Results

### Ignition: fire starts per day, relative to {REFERENCE}

| Danger | GFDI seen | Point-days (share) | Fires | Fires per 10k point-days | RR | 95% CI | Multiplier used |
|---|---|---|---|---|---|---|---|
{rows}

![Ignition rate by band](figures/fire-day/ignition_rate_by_band.png)

Adjustments made before use:
{pooled}

### Consequence: share of fires that got large

| Danger on start day | Fires with a size | ≥ 300 ac (share, 95% CI) | ≥ 1,000 ac (share, 95% CI) |
|---|---|---|---|
{large_rows}

![Large-fire share by band](figures/fire-day/large_fire_share_by_band.png)

## From fire starts per day to odds per line fault

The RR above counts fire starts per day of land. The recommendation model needs something else: the chance that **one line fault** starts a fire. On a windy, dry day both of these rise:

> fire starts per day from lines = line faults per day × chance each fault ignites

The RR measures their product. Public data can't split it (co-op outage logs would), so the app gives each factor half of the increase in log terms:

> per-fault multiplier = RR ^ `danger_exponent`, default 0.5

| Danger | RR (per day) | Per-fault multiplier (^0.5) | Lockout's starting P(fire) at the 3% base rate |
|---|---|---|---|
{per_fault}

**Does the exponent matter?** On the Cottonwood Creek scenario (an Extreme day), the starting P(fire) for the lockout is 3% at exponent 0, 13% at 0.5 and 53% at 1. **The recommendation is the same at every point under all three:**
- minute 0: heads-up downwind and wait for the neighbors
- minute 8, after a neighbor sees smoke: page
- minute 9: request mutual aid now

Only the stated confidence changes. The exponent is a district setting (`decision.danger_exponent`) and is listed under "How this is decided" in the app.

## How the app uses it

- `app/decision.py` loads `danger_multiplier` from the model file. If the file is missing, it falls back to hand-set per-fault values (Low-Mod 0.3, High 1, Very High 1.5, Severe 2, Extreme 3). The line-fault base rate is multiplied by the per-fault multiplier above.
- The large-fire share for today's band is shown on the alert ("On days like this, X% of reported Kansas wildfires grew past 1,000 ac"). It isn't part of the expected loss: the spread forecast already gives this fire's likely acres from its own wind, fuel and terrain, and adding the historical share would count the weather twice.

## Limits (read before quoting a number)

- **Reporting bias.** WFIGS records only fires that reached a federal or state incident system. Kansas fire departments respond to thousands of fires a year that never appear in it. Bigger fires are likelier to be reported, and fires on bad days are likelier to be big, so the RR at high danger is probably **overstated**. Absolute rates (fires per point-day) mean nothing; only the ratios are used.
- **Not power-line specific.** The cause fields are almost all "Human" or blank, so the RR is for all causes. The app applies it to line faults on the assumption that weather raises line-fault ignitions at least as much as all ignitions, which the Plains megafires suggest. It can't be checked with public data, and co-op outage records would be needed.
- **Coarse weather.** A 1° grid with daily extremes (max temperature, min humidity, max wind) that don't happen at the same hour. Daily-extreme GFDI runs higher than an afternoon reading, so bands shift up for everyone. That affects numerator and denominator alike, so ratios hold up better than levels.
- **Curing is a seasonal table,** not observed greenness. Drought years and green springs are treated alike.
- **Our GFDI is the Australian McArthur index,** not the NWS Grassland Fire Danger Index that Kansas forecasters publish. The bands have the same names but different scales.
- **Small counts** at the extreme end: see the intervals. The multiplier guards keep a noisy band from producing a nonsensical value; they don't make it precise.

## Rebuild

```bash
cd backend
.venv/bin/pip install -r requirements-ml.txt
.venv/bin/python -m ml.fire_day     # first run downloads ~{d['grid_points']} weather series (cached in ml/data/fire_day/)
```
"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    fit()
