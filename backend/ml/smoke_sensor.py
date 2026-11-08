"""Sensor smoke model v1: how much a mesh node's smoke reading should move P(fire).

    .venv/bin/python -m ml.smoke_sensor        # fit, write data/model/smoke_sensor.json + report

The tower smoke rule (app/sensors.py) decides *whether* a reading is smoke. This module measures *how much* that
should count, so the decision model (app/decision.py) can use a fitted likelihood ratio instead of the assumed x15:

  particulate  PM2.5 rise over the node's own baseline -> likelihood ratio of a local fire. Fitted on the Flint Hills
               2022 PurpleAir campaign (36 sensors, hourly, Mar-May) against expert daily smoke designations that
               separate *local* smoke from *transported* haze (Sablan et al. 2024, GeoHealth).
  gas          metal-oxide gas resistance relative to the node's baseline (R/R0) -> likelihood ratio of smoke.
               Fitted on outdoor BME688/BME690 recordings 100 m from vegetation burns (Mendeley 48j7mm8k56).

Both are one-feature logistic curves: the analysis below shows extra features don't add out-of-sample skill.

Data (put in backend/ml/data/sensors/; gitignored):
  flinthills_2022_purpleair.csv    https://doi.org/10.5061/dryad.9p8cz8wqd  PurpleAirData.csv      (CC0)
  flinthills_2022_smoke_days.csv   https://doi.org/10.5061/dryad.4mw6m90h7  SmokeDesignations.csv  (CC0)
  mendeley/Dataset Smoke Detection https://doi.org/10.17632/48j7mm8k56.1    RAR, extract here      (CC BY 4.0)
Dryad serves files behind a browser check, so download those two by hand from the dataset pages.
The Mendeley archive is fetched automatically if `bsdtar` (macOS, libarchive) can extract it.
"""

import json
import logging
import math
import subprocess
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import LeaveOneGroupOut

from .paths import MODEL_DIR, WORK_DIR

log = logging.getLogger("smoke_sensor")
DATA = WORK_DIR / "sensors"
PM_PATH = DATA / "flinthills_2022_purpleair.csv"
LABEL_PATH = DATA / "flinthills_2022_smoke_days.csv"
GAS_DIR = DATA / "mendeley" / "Dataset Smoke Detection"
GAS_URL = ("https://data.mendeley.com/public-files/datasets/48j7mm8k56/files/"
           "26539d66-40f4-43ef-ad62-fe72ff3a107f/file_downloaded")
MODEL_PATH = MODEL_DIR / "smoke_sensor.json"
REPO_DIR = MODEL_DIR.parent.parent.parent
REPORT_PATH = REPO_DIR / "docs" / "research" / "sensor-smoke-model-v1.md"
FIG_DIR = REPO_DIR / "docs" / "research" / "figures" / "sensor-smoke"

BASELINE_HOURS = 3  # app/sensors.py: median of the previous 3 h
RULE_RISE = 50.0  # app/sensors.py DEFAULTS["smoke_pm25_rise"]
REGIONAL_KM = (15.0, 60.0)  # "distant" sensors, as far as a district's own towers would be
LOCAL = (1, 3)  # designations: 0 smoke-free, 1 local, 2 transported, 3 local + transported
PM_LR_MAX = 20.0  # the curve overshoots the observed ratio above ~50 µg/m³ (x19 at 100+)
GAS_SMOKE = (1002, 1006)  # Mendeley phases with smoke at the sensors; see report for the phase reading
GAS_CLEAN = 0
GAS_TRIGGER = 0.5  # R/R0 at or below this, on two readings in a row
GAS_LR_MAX = 3.0
BOOT = 1000
SEED = 7


# ---------- particulate ----------

def _km(lat1, lon1, lat2, lon2):
    p1, p2, dl = np.radians(lat1), np.radians(lat2), np.radians(lon2 - lon1)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def pm_hours() -> pd.DataFrame:
    """One row per sensor-hour with the features the app can compute at that moment (trailing data only)."""
    d = pd.read_csv(PM_PATH)
    d["t"] = pd.to_datetime(d.local_time, format="%m/%d/%y %H:%M")
    d["ID"] = d.ID.astype(str)
    # Uncorrected PM2.5 is the Plantower "atm" number, the same one the PMSA003I sends as pm25Environmental.
    pm = d.pivot_table(index="t", columns="ID", values="Uncorrected_PM25").asfreq("h")
    base = pm.shift(1).rolling(BASELINE_HOURS, min_periods=2).median()
    rise = pm - base
    loc = d.groupby("ID")[["Latitude", "Longitude"]].first().loc[pm.columns]
    dist = _km(loc.Latitude.values[:, None], loc.Longitude.values[:, None], loc.Latitude.values[None], loc.Longitude.values[None])
    far = (dist > REGIONAL_KM[0]) & (dist <= REGIONAL_KM[1])
    R = rise.to_numpy()
    reg = np.full_like(R, np.nan)
    for j in range(R.shape[1]):
        sub = R[:, far[j]]
        ok = (~np.isnan(sub)).sum(1) > 0
        reg[ok, j] = np.nanmedian(sub[ok], 1)
    out = pd.DataFrame({
        "t": np.repeat(pm.index.values, pm.shape[1]), "ID": np.tile(pm.columns, pm.shape[0]),
        "pm": pm.to_numpy().ravel(), "base": base.to_numpy().ravel(), "rise": R.ravel(), "reg_rise": reg.ravel(),
    }).dropna(subset=["rise"])
    out = out.sort_values(["ID", "t"])
    out["rise_prev"] = out.groupby("ID").rise.shift(1)
    rh = d.rename(columns={"humidity": "rh"})[["t", "ID", "rh"]]
    return out.merge(rh, on=["t", "ID"], how="left")


def pm_days(hours: pd.DataFrame) -> pd.DataFrame:
    """One row per labelled sensor-day: the hour with the largest rise, and the expert designation."""
    hours = hours.assign(date=hours.t.dt.normalize())
    peak = hours.loc[hours.groupby(["ID", "date"]).rise.idxmax()]
    lab = pd.read_csv(LABEL_PATH).melt(id_vars="date", var_name="ID", value_name="designation").dropna()
    lab["date"] = pd.to_datetime(lab.date, format="%m/%d/%y")
    df = peak.merge(lab, on=["ID", "date"])
    df["y"] = df.designation.isin(LOCAL).astype(int)
    df["x"] = np.log1p(df.rise.clip(lower=0))
    df["week"] = df.date.dt.isocalendar().week.astype(int)
    return df.reset_index(drop=True)


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def fit_curve(x: np.ndarray, y: np.ndarray) -> dict:
    """Logistic fit; LR(x) = odds(p(x)) / odds(training prior) = exp(a + b*x - logit(prior))."""
    m = LogisticRegression(C=1e6, max_iter=1000).fit(x.reshape(-1, 1), y)
    return {"a": float(m.intercept_[0]), "b": float(m.coef_[0][0]), "prior": float(y.mean())}


def curve_lr(c: dict, x, lr_max: float = math.inf):
    return np.minimum(np.exp(c["a"] + c["b"] * np.asarray(x, float) - _logit(c["prior"])), lr_max)


def _oof(df: pd.DataFrame, cols: list[str], groups: str) -> np.ndarray:
    X = df[cols].copy()
    for c in cols:
        if X[c].isna().any():
            X[c + "_missing"] = X[c].isna().astype(int)
            X[c] = X[c].fillna(0)
    out = np.zeros(len(df))
    for tr, te in LeaveOneGroupOut().split(X, df.y, df[groups]):
        mu, sd = X.iloc[tr].mean(), X.iloc[tr].std().replace(0, 1)
        m = LogisticRegression(max_iter=2000).fit((X.iloc[tr] - mu) / sd, df.y.iloc[tr])
        out[te] = m.predict_proba((X.iloc[te] - mu) / sd)[:, 1]
    return out


def _at_fpr(y: np.ndarray, s: np.ndarray, fpr: float) -> float:
    return float((s[y == 1] >= np.quantile(s[y == 0], 1 - fpr)).mean())


def _boot_days(df: pd.DataFrame, stat, n: int = BOOT) -> tuple[float, float]:
    """95% interval resampling whole days: sensors on one day share weather and smoke, so they aren't independent."""
    rng = np.random.default_rng(SEED)
    days = df.date.unique()
    by_day = {d: g for d, g in df.groupby("date")}
    vals = []
    for _ in range(n):
        v = stat(pd.concat([by_day[d] for d in rng.choice(days, len(days))]))
        if np.isfinite(v):
            vals.append(v)
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def _rule_lr(df: pd.DataFrame, thr: float = RULE_RISE) -> float:
    hit = df.rise >= thr
    tpr, fpr = hit[df.y == 1].mean(), hit[df.y == 0].mean()
    return tpr / fpr if fpr > 0 else math.inf


def evaluate_pm() -> dict:
    df = pm_days(pm_hours())
    y = df.y.to_numpy()
    log.info("particulate: %d sensor-days, %d local smoke", len(df), y.sum())

    thresholds = []
    for thr in (10, 20, 30, 50, 75, 100):
        hit = df.rise >= thr
        tpr, fpr = float(hit[y == 1].mean()), float(hit[y == 0].mean())
        lo, hi = _boot_days(df, lambda d, t=thr: _rule_lr(d, t))
        thresholds.append({"rise": thr, "tpr": tpr, "fpr": fpr, "lr": tpr / fpr, "ci": [lo, hi]})

    bins = [-math.inf, 5, 10, 20, 35, 50, 100, math.inf]
    df["bin"] = pd.cut(df.rise, bins, right=False)
    pos, neg = df[df.y == 1].bin.value_counts(normalize=True), df[df.y == 0].bin.value_counts(normalize=True)
    binned = []
    for b in df.bin.cat.categories:
        sub = df[df.bin == b]
        binned.append({"lo": b.left, "hi": b.right, "n": int(len(sub)), "local": int(sub.y.sum()),
                       "lr": float(pos.get(b, 0) / neg.get(b, np.nan)), "mid_x": float(np.log1p(max(sub.rise.clip(lower=0).median(), 0)))})

    variants = {
        "PM2.5 rise (shipped)": ["x"],
        "+ PM2.5 level and baseline": ["x", "pm", "base"],
        "+ previous hour's rise": ["x", "rise_prev"],
        "+ sensors 15-60 km away": ["x", "reg_rise"],
        "+ relative humidity": ["x", "rh"],
    }
    compare = []
    for name, cols in variants.items():
        s = _oof(df, cols, "week")
        compare.append({"model": name, "auc": float(roc_auc_score(y, s)),
                        "tpr_at_rule_fpr": _at_fpr(y, s, thresholds[3]["fpr"]), "tpr_at_5pct": _at_fpr(y, s, 0.05)})
    curve = fit_curve(df.x.to_numpy(), y)
    lo, hi = _boot_days(df, lambda d: roc_auc_score(d.y, d.x) if d.y.nunique() == 2 else np.nan)
    return {
        "df": df, "curve": curve, "thresholds": thresholds, "binned": binned, "compare": compare,
        "auc": float(roc_auc_score(y, df.x)), "auc_ci": [lo, hi],
        "data": {"sensor_days": int(len(df)), "local_days": int(y.sum()), "sensors": int(df.ID.nunique()),
                 "period": [str(df.date.min().date()), str(df.date.max().date())],
                 "designations": {str(int(k)): int(v) for k, v in df.designation.value_counts().sort_index().items()}},
    }


# ---------- gas ----------

def fetch_gas() -> None:
    if GAS_DIR.exists():
        return
    rar = DATA / "mendeley_smoke.rar"
    if not rar.exists():
        import httpx

        DATA.mkdir(parents=True, exist_ok=True)
        r = httpx.get(GAS_URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        rar.write_bytes(r.content)
    (DATA / "mendeley").mkdir(exist_ok=True)
    subprocess.run(["bsdtar", "-xf", str(rar), "-C", str(DATA / "mendeley")], check=True)


def gas_samples() -> pd.DataFrame:
    """Every gas reading with R/R0 against its own sensor and heater step's clean-air median.

    The app's BME680 telemetry is one heater step whose temperature isn't known here, so only the ratio to the
    node's own baseline transfers, not the absolute resistance; pooling all steps fits a step-agnostic curve."""
    fetch_gas()
    rows = []
    for f in sorted(GAS_DIR.glob("NODE*/*.csv")):
        d = pd.read_csv(f)
        rows.append(d.assign(node=f.parent.name, file=f.name))
    d = pd.concat(rows, ignore_index=True)
    d = d[d.error_code == 0]
    key = ["file", "sensor_index", "heater_profile_step_index"]
    r0 = d[d.label_tag == GAS_CLEAN].groupby(key).resistance_gassensor.median().rename("r0")
    d = d.join(r0, on=key)
    d["x"] = np.log(d.resistance_gassensor / d.r0)
    d["session"] = np.where(d.real_time_clock < 1.7e9, "2021-02", "2025-02")
    return d


def evaluate_gas() -> dict:
    d = gas_samples()
    phases = d.groupby("label_tag").agg(n=("x", "size"), median_ratio=("x", lambda v: float(np.exp(v.median()))))
    s = d[(d.label_tag == GAS_CLEAN) | d.label_tag.between(*GAS_SMOKE)].copy()
    s["y"] = (s.label_tag != GAS_CLEAN).astype(int)
    y = s.y.to_numpy()
    per_node, oof = {}, np.zeros(len(s))
    for n in sorted(s.node.unique()):
        tr, te = (s.node != n).to_numpy(), (s.node == n).to_numpy()
        c = fit_curve(s.x.to_numpy()[tr], y[tr])
        oof[te] = c["a"] + c["b"] * s.x.to_numpy()[te]
        per_node[n] = float(roc_auc_score(y[te], oof[te]))
    table = []
    for r in (0.9, 0.7, 0.5, 0.3):
        hit = s.x <= math.log(r)
        tpr, fpr = float(hit[y == 1].mean()), float(hit[y == 0].mean())
        # two readings in a row: consecutive readings of one sensor and heater step
        table.append({"ratio": r, "tpr": tpr, "fpr": fpr, "lr": tpr / fpr if fpr else math.inf})
    prev = s.sort_values("real_time_clock").groupby(["file", "sensor_index", "heater_profile_step_index"]).x.shift(1)
    both = ((s.x <= math.log(GAS_TRIGGER)) & (prev.reindex(s.index) <= math.log(GAS_TRIGGER))).to_numpy()
    trig = {"tpr": float(both[y == 1].mean()), "fpr": float(both[y == 0].mean())}
    return {
        "df": d, "curve": fit_curve(s.x.to_numpy(), y), "auc_lono": float(roc_auc_score(y, oof)), "per_node": per_node,
        "table": table, "trigger": trig, "phases": phases,
        "data": {"samples": int(len(s)), "smoke": int(y.sum()), "clean": int((y == 0).sum()), "nodes": int(s.node.nunique()),
                 "sessions": sorted(s.session.unique()), "hours": float(d.groupby("file").real_time_clock.agg(np.ptp).sum() / 3600)},
    }


# ---------- export ----------

def fit() -> dict:
    pm, gas = evaluate_pm(), evaluate_gas()
    rule = next(t for t in pm["thresholds"] if t["rise"] == RULE_RISE)
    model = {
        "name": "sensor-smoke-v1",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pm": {
            "feature": "ln(1 + max(PM2.5 - baseline, 0)), µg/m³", **pm["curve"], "lr_max": PM_LR_MAX,
            "lr_at_rise": {str(r): round(float(curve_lr(pm["curve"], math.log1p(r), PM_LR_MAX)), 2) for r in (20, 50, 100, 150, 250)},
            "rule": {"rise": RULE_RISE, "tpr": rule["tpr"], "fpr": rule["fpr"], "lr": round(rule["lr"], 2),
                     "ci": [round(v, 1) for v in rule["ci"]]},
            "auc": round(pm["auc"], 3), "data": pm["data"],
        },
        "gas": {
            "feature": "ln(R / R0), R0 = node's own baseline", **gas["curve"], "lr_max": GAS_LR_MAX,
            "trigger_ratio": GAS_TRIGGER,
            "lr_at_ratio": {str(r): round(float(curve_lr(gas["curve"], math.log(r), GAS_LR_MAX)), 2) for r in (0.5, 0.4, 0.3)},
            "auc_leave_one_node_out": round(gas["auc_lono"], 3), "data": gas["data"],
        },
    }
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(model, indent=1))
    _figures(pm, gas, model)
    REPORT_PATH.write_text(report(pm, gas, model))
    log.info("wrote %s and %s", MODEL_PATH, REPORT_PATH)
    return model


def _figures(pm: dict, gas: dict, model: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 4.2))
    xs = np.linspace(0, math.log1p(400), 200)
    ax.plot(np.expm1(xs), curve_lr(pm["curve"], xs), color="#c0392b", label="Fitted curve (uncapped)")
    ax.plot(np.expm1(xs), curve_lr(pm["curve"], xs, PM_LR_MAX), color="#c0392b", ls="--", lw=1, label=f"Used by the app (cap ×{PM_LR_MAX:g})")
    for b in pm["binned"]:
        if b["n"] >= 20 and np.isfinite(b["lr"]) and b["lr"] > 0:
            mid = np.expm1(b["mid_x"])
            ax.scatter(mid, b["lr"], color="#2c3e50", zorder=3)
            ax.annotate(f"n={b['n']}", (mid, b["lr"]), textcoords="offset points", xytext=(4, -12), fontsize=7, color="#555")
    ax.axvline(RULE_RISE, color="#888", lw=1, ls=":")
    ax.text(RULE_RISE + 3, 0.15, "rule trigger", fontsize=8, color="#666")
    ax.axhline(1, color="#bbb", lw=0.8)
    ax.set_xscale("symlog", linthresh=10)
    ax.set_yscale("log")
    ax.set_xlim(0, 400)
    ax.set_xlabel("PM2.5 rise over the node's 3 h baseline, peak hour of the day (µg/m³)")
    ax.set_ylabel("Likelihood ratio, local smoke")
    ax.set_title("Particulate: how much a rise should count", fontsize=11)
    ax.scatter([], [], color="#2c3e50", label="Observed, binned")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "pm_likelihood_ratio.png", dpi=150)
    plt.close(fig)

    d = gas["df"]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    order = sorted(d.label_tag.unique())
    data = [np.exp(d[d.label_tag == t].x.clip(-6, 3)) for t in order]
    colors = ["#27ae60" if t == GAS_CLEAN else "#c0392b" if GAS_SMOKE[0] <= t <= GAS_SMOKE[1] else "#95a5a6" for t in order]
    bp = ax.boxplot(data, showfliers=False, patch_artist=True, widths=0.6)
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.6)
    ax.set_xticks(range(1, len(order) + 1), [str(t) for t in order], fontsize=8)
    ax.set_yscale("log")
    ax.axhline(GAS_TRIGGER, color="#888", ls=":", lw=1)
    ax.text(0.6, GAS_TRIGGER * 0.9, f"trigger {GAS_TRIGGER}", fontsize=8, color="#666", va="top", ha="left")
    ax.set_xlabel("Phase tag in the recording (green = clean air, red = used as smoke, grey = not used)")
    ax.set_ylabel("Gas resistance / clean-air baseline")
    ax.set_title("Gas: resistance falls when smoke reaches the sensor", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "gas_ratio_by_phase.png", dpi=150)
    plt.close(fig)


def _pct(v: float) -> str:
    return f"{v:.1%}"


def report(pm: dict, gas: dict, m: dict) -> str:
    p, g = m["pm"], m["gas"]
    des = p["data"]["designations"]
    thr_rows = "\n".join(
        f"| ≥ {t['rise']:g} | {_pct(t['tpr'])} | {_pct(t['fpr'])} | {t['lr']:.1f} | {t['ci'][0]:.1f}–{t['ci'][1]:.1f} |"
        for t in pm["thresholds"])
    bin_rows = "\n".join(
        f"| {'< ' + format(b['hi'], 'g') if not np.isfinite(b['lo']) else ('≥ ' + format(b['lo'], 'g') if not np.isfinite(b['hi']) else format(b['lo'], 'g') + '–' + format(b['hi'], 'g'))} "
        f"| {b['n']} | {b['local']} | {b['lr']:.2f} |" for b in pm["binned"])
    cmp_rows = "\n".join(
        f"| {c['model']} | {c['auc']:.3f} | {_pct(c['tpr_at_rule_fpr'])} | {_pct(c['tpr_at_5pct'])} |" for c in pm["compare"])
    lr_rows = " · ".join(f"{k} µg/m³: ×{v:g}" for k, v in p["lr_at_rise"].items())
    gas_rows = "\n".join(f"| ≤ {t['ratio']:g} | {_pct(t['tpr'])} | {_pct(t['fpr'])} | {t['lr']:.1f} |" for t in gas["table"])
    node_auc = ", ".join(f"{k} {v:.2f}" for k, v in gas["per_node"].items())
    phase_rows = "\n".join(f"| {int(t)} | {int(r.n)} | {r.median_ratio:.2f} |" for t, r in gas["phases"].iterrows())
    glr = " · ".join(f"R/R0 {k}: ×{v:g}" for k, v in g["lr_at_ratio"].items())
    return f"""# Sensor smoke model v1

Generated {m['trained_at']} by `backend/ml/smoke_sensor.py`. Model file: `backend/data/model/smoke_sensor.json`.

The tower smoke rule ([DESIGN 5.8](../DESIGN.md)) decides whether a reading is smoke. Until now, a reading that passed counted ×15 toward P(fire), an assumption. This model measures that weight from open data, and adds a second, weaker weight for the gas sensor on bare nodes:

- **Particulate:** the PM2.5 rise over the node's own baseline becomes a likelihood ratio for a fire near the sensor. A bigger rise counts for more, up to ×{PM_LR_MAX:g}.
- **Gas:** the drop in metal-oxide gas resistance against the node's own baseline becomes a likelihood ratio, capped at ×{GAS_LR_MAX:g}. Gas alone never opens an event or counts as a source. It only adds weight to an event something else started.

The rules engine still decides *whether*: the PM2.5 trigger, the dust check and the regional-haze check are unchanged. The satellite scorer, these two curves and the people signals are separate models whose likelihood ratios multiply in `decision.probability`. All of one node's sensors together count once.

## Why not one joint model

No open dataset pairs satellite detections, ground sensors and fire labels for the same events. Each dataset below answers one question, so each becomes its own calibrated likelihood ratio, and the existing odds model combines them. That is the same structure the decision model already uses for every other kind of evidence.

## Data

| | Particulate | Gas |
|---|---|---|
| Source | Flint Hills 2022 prescribed-fire campaign, Colorado State University: [PurpleAir PM2.5](https://doi.org/10.5061/dryad.9p8cz8wqd) and [daily smoke designations](https://doi.org/10.5061/dryad.4mw6m90h7) (both CC0) | [Dataset Smoke Detection](https://doi.org/10.17632/48j7mm8k56.1), University of Cagliari (CC BY 4.0) |
| Sensors | {p['data']['sensors']} PurpleAir (Plantower PMS5003, the same sensor family as our PMSA003I), eastern Kansas | {g['data']['nodes']} nodes of Bosch BME688/BME690 dev kits, 100 m from the burns |
| Period | {p['data']['period'][0]} to {p['data']['period'][1]}, hourly | {' and '.join(g['data']['sessions'])} sessions, {g['data']['hours']:.0f} hours of recordings |
| Unit | sensor-day: the hour with the largest rise that day | single gas reading |
| Label | expert designation: **local** smoke (code 1 or 3) vs smoke-free (0) or transported haze only (2). Counts: {', '.join(f'{k}: {v}' for k, v in des.items())} | phase tag: clean air (0) vs phases 1002–1006 |
| Rows used | {p['data']['sensor_days']:,} sensor-days, {p['data']['local_days']:,} local | {g['data']['samples']:,} readings, {g['data']['smoke']:,} smoke |

The Flint Hills designations are exactly the distinction the app needs: smoke from a fire near the sensor vs regional haze from fires far away. They're the study authors' call for each monitor and day, published with their GeoHealth paper: a careful reference, not ground truth for every hour.

## Particulate

**Features.** The same as the app computes live: PM2.5 now, minus the median of the node's previous 3 hours. The day's peak hour is used because that's the reading most likely to cross the trigger. On a clean day, it's the reading that would cause a false alarm.

**The current rule, measured.** A PM2.5 rise of 50 or more catches {_pct(p['rule']['tpr'])} of local-smoke days and fires on {_pct(p['rule']['fpr'])} of the others. Its likelihood ratio is **×{p['rule']['lr']:.1f}** (95% CI {p['rule']['ci'][0]}–{p['rule']['ci'][1]}, resampling whole days). The assumed ×15 was close. The app now uses the measured value for any sensor signal without a model weight.

| Rise threshold (µg/m³) | Local days caught | Other days flagged | Likelihood ratio | 95% CI |
|---|---|---|---|---|
{thr_rows}

The table above is the trade a district makes if it lowers `smoke_pm25_rise`. For example, 20 µg/m³ catches three times as many local-smoke days, at about 6× the false flags.

**How much a given rise should count.** These are the likelihood ratios for each band of rise, not cumulative:

| Rise (µg/m³) | Sensor-days | Local | Likelihood ratio |
|---|---|---|---|
{bin_rows}

A logistic curve in ln(1 + rise) fits these bands (AUC {p['auc']:.3f}, 95% CI {pm['auc_ci'][0]:.3f}–{pm['auc_ci'][1]:.3f}). The app reads the weight off the curve: {lr_rows}. It caps the weight at ×{PM_LR_MAX:g} for two reasons. Above about 50 µg/m³ the curve runs ahead of the observed bands. And live readings are single samples, not hourly means, so they spike higher than anything in the training data.

![Particulate likelihood ratio](figures/sensor-smoke/pm_likelihood_ratio.png)

**Other features didn't help.** Each variant is a logistic regression scored by leave-one-week-out cross-validation. Recall is shown at the rule's false-flag rate ({_pct(p['rule']['fpr'])}) and at 5%:

| Model | AUC | Recall at rule's false-flag rate | Recall at 5% false flags |
|---|---|---|---|
{cmp_rows}

The rise alone carries the signal. Sensors 15–60 km away (the regional-haze idea) add nothing measurable here, partly because most sensors have only a few neighbors in that ring. The regional-haze check stays a hard rule, not a model feature. Humidity improves recall at 5% false flags, most likely because burn days are dry. That makes it a fire-weather signal, and the decision model already weighs fire weather, so counting it again through the sensor would double it. Humidity is left out.

## Gas

**What the data shows.** Resistance falls when smoke reaches the sensor, by 2–20× at the strongest phases:

| Phase tag | Readings | Median R/R0 |
|---|---|---|
{phase_rows}

The dataset doesn't document its phase tags. From the recordings, 0 is the first ~37 minutes in clean air, and the tags then run in time order. In 1001 resistance hasn't moved yet, and 1002–1006 show the drop. 1007–1009 come at the end. Resistance partly recovers in 1007 and drops again in the short 1008–1009, and the data doesn't say why. Only 0 (clean) and 1002–1006 (smoke) are used. 1001 and 1007–1009 are left out.

**Feature.** ln(R/R0): the reading over the node's own clean-air baseline, for each sensor and heater step. Our BME680 telemetry reports one heater step at a temperature we don't know, so the absolute resistance doesn't transfer, but the relative drop does. Humidity and temperature changes are left out: in this dataset they track time since the start of each session (the air warmed up while the burns went on), not smoke.

**Results.** Leave-one-node-out AUC is {g['auc_leave_one_node_out']:.3f} ({node_auc}).

| R/R0 at or below | Smoke readings caught | Clean readings flagged | Likelihood ratio in the experiment |
|---|---|---|---|
{gas_rows}

The app's trigger is R/R0 ≤ {GAS_TRIGGER} on **two readings in a row**, which catches {_pct(gas['trigger']['tpr'])} of smoke readings and flags {_pct(gas['trigger']['fpr'])} of clean ones in the experiment. The weight comes from a logistic curve in ln(R/R0), read at the smaller of the two drops ({glr}) and capped at ×{GAS_LR_MAX:g}. The table above is cumulative: everything at or below a ratio. The curve gives the weight of one exact ratio, which is why it's lower at 0.5.

![Gas ratio by phase](figures/sensor-smoke/gas_ratio_by_phase.png)

**Why the cap is so low.** The experiment's clean air is ~37 minutes per session from 2 sessions, so its false-flag rates can't speak for a grassland node over weeks. Over weeks, dew and humidity swings, vehicle exhaust, feedlots and heater warm-up after a power cycle all move a metal-oxide sensor. Until a supervised burn trial ([sensors/README.md](../../sensors/README.md)) measures field false alarms:

- gas evidence is capped at ×{GAS_LR_MAX:g};
- it never opens an event and never counts as a second source;
- on a node with a particulate sensor, the gas weight is raised to `sensor_gas_weight` (0.5) before it multiplies the PM2.5 weight, so a full ×3 adds ×1.7, because both sensors see the same plume.

## How the app uses it

- `app/sensor_model.py` loads `smoke_sensor.json` and turns a rise or a ratio into a likelihood ratio.
- `app/sensors.py` stores gas resistance and pressure from `environmentMetrics` alongside PM2.5. When the PM2.5 trigger fires, the signal carries the particulate weight, plus the gas weight if the gas is also down. A bare node's gas drop attaches only to an open event within 8 km.
- `app/decision.py` multiplies the odds by that weight, once for all sensors. A signal without a weight (no model file, a manual signal) uses `lr_sensor_smoke`, now the rule's measured ×{p['rule']['lr']:.1f}. A district can override `lr_sensor_smoke`, `lr_sensor_pm_max`, `lr_sensor_gas_max` and `sensor_gas_weight` under `"decision"` in `settings.json`.

## Limits

- **One season, one place.** Spring 2022 in eastern Kansas is mostly prescribed-burn smoke in the Flint Hills. Wildfire smoke on a windy winter day may look different at the sensor: faster, thinner plumes.
- **Daily labels.** A designation covers the whole day, but the feature is one hour, so a local-smoke day whose plume missed the peak-rise hour counts against the model. The ratios are probably conservative.
- **Hourly vs live readings.** Training uses hourly means. The app uses single readings, which spike higher, and the cap absorbs part of that.
- **Gas.** Two sessions, five nodes, a 100 m standoff, Mediterranean vegetation, and a dev-kit heater profile, not Meshtastic's. Treat it as evidence that a resistance drop means smoke, not as a measured false-alarm rate.
- **Refit when outcomes exist.** Once Firewatch logs sensor signals against confirmed fires and burns, refit both curves on the district's own nodes.
"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    fit()
