"""Research analyses on the scorer v1 training run: uncertainty, per-year stability, calibration, threshold
trade-offs, ablations, hyperparameter sensitivity, error cases, and lead time.

    .venv/bin/python -m ml.analyze

Reads ml/data/dataset.csv (built by ml.build_dataset), reuses ml.train's features, weights, split, and
calibration, and writes ml/analysis.json plus figures under docs/research/figures/scorer-v1/.
"""

import json
import logging
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import LeaveOneGroupOut

from app.scoring.rules import score_rules
from app.scoring.score import apply_guardrails, recommend

from .paths import BACKEND_DIR, DATASET_PATH, ML_DIR, WFIGS_PATH, WORK_DIR
from .train import FEATURES, KIND_LABELS, MODEL_KINDS, PARAMS, TEST_FROM_YEAR, fit_logistic, platt, to_score, weights

log = logging.getLogger("ml.analyze")

FIG_DIR = BACKEND_DIR.parent / "docs" / "research" / "figures" / "scorer-v1"
RESULTS_PATH = ML_DIR / "analysis.json"
LEVELS = ("monitor", "investigate", "escalate")
KIND_COLORS = {"wf": "#c8102e", "rx": "#1f77b4", "rx_weak": "#7fb8e0", "static": "#8d8d8d"}
SCORER_COLORS = {"xgboost": "#e07a1f", "logistic": "#6a4c93", "rules-v0": "#7a7a7a"}
N_BOOT = 2000
SEEDS = range(10)

SATELLITE = ["frp_max", "frp_sum", "brightness_max", "conf_high_frac", "pixel_km2_min", "n_detections",
             "n_satellites", "minutes_active", "frp_growth", "is_night", "local_hour"]
WEATHER = ["wind_kmh", "gust_kmh", "rh_pct", "temp_c", "precip_72h_mm", "thunder_24h", "gfdi"]
INFRA = ["dist_line_km", "dist_substation_km", "dist_town_km"]
REGION_SEASON = ["in_flint_hills", "elevation_m", "slope_deg", "doy_sin", "doy_cos"]
ABLATIONS = {
    "All 27 features (v1)": FEATURES,
    "Without in_flint_hills": [f for f in FEATURES if f != "in_flint_hills"],
    "Without region and season proxies": [f for f in FEATURES if f not in REGION_SEASON],
    "Without distance to town": [f for f in FEATURES if f != "dist_town_km"],
    "Without infrastructure distances": [f for f in FEATURES if f not in INFRA],
    "Without weather": [f for f in FEATURES if f not in WEATHER],
    "Satellite only": SATELLITE,
    "Weather only": WEATHER,
    "Place and season only": REGION_SEASON + INFRA + ["nearby_events_24h"],
}


# ---------------------------------------------------------------- helpers

def fit(df: pd.DataFrame, features: list[str] = FEATURES, sample_weight: np.ndarray | None = None, **overrides) -> xgb.XGBClassifier:
    w, y = weights(df) if sample_weight is None else sample_weight, df["label"].to_numpy()
    model = xgb.XGBClassifier(**{**PARAMS, **overrides}, scale_pos_weight=(w * (1 - y)).sum() / max((w * y).sum(), 1e-9))
    model.fit(df[features], y, sample_weight=w)
    return model


def margin(model: xgb.XGBClassifier, X: pd.DataFrame) -> np.ndarray:
    return model.get_booster().predict(xgb.DMatrix(X), output_margin=True)


def auc(y: np.ndarray, s: np.ndarray, w: np.ndarray | None = None) -> float | None:
    if len(np.unique(y)) < 2:
        return None
    return round(float(roc_auc_score(y, s, sample_weight=w)), 3)


def two_views(df: pd.DataFrame, s: np.ndarray) -> dict:
    """AUC for wildfire vs all burns (unweighted, as in report.md) and vs reported prescribed burns only."""
    y, kind = df["label"].to_numpy(), df["kind"].to_numpy()
    m = np.isin(kind, MODEL_KINDS)
    rx = np.isin(kind, ("wf", "rx"))
    return {"wildfire_vs_burns": auc(y[m], s[m]), "wildfire_vs_reported_rx": auc(y[rx], s[rx])}


def loyo(train: pd.DataFrame, features: list[str] = FEATURES, **overrides) -> np.ndarray:
    oof = np.zeros(len(train))
    for tr, va in LeaveOneGroupOut().split(train, groups=train["year"]):
        oof[va] = margin(fit(train.iloc[tr], features, **overrides), train.iloc[va][features])
    return oof


def loyo_logistic(train: pd.DataFrame) -> np.ndarray:
    oof = np.zeros(len(train))
    for tr, va in LeaveOneGroupOut().split(train, groups=train["year"]):
        oof[va] = fit_logistic(train.iloc[tr]).predict_proba(train.iloc[va][FEATURES])[:, 1]
    return oof


def levels(df: pd.DataFrame, scores: np.ndarray, guardrails: bool = True) -> np.ndarray:
    recs = df.to_dict("records")
    if guardrails:
        return np.array([apply_guardrails(f, int(s))[0] for f, s in zip(recs, scores)])
    return np.array([recommend(int(s)) for s in scores])


def savefig(fig: plt.Figure, name: str) -> None:
    fig.savefig(FIG_DIR / name, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- analyses

def data_profile(raw: pd.DataFrame, df: pd.DataFrame) -> dict:
    na = raw[FEATURES].isna().any(axis=1)
    degraded = ~na & (raw["degraded"] != 0)
    no_terrain = ~na & ~degraded & (raw["elevation_m"] <= 0)
    first = df[df["snapshot"] == 0]
    by_kind = {}
    for kind, g in first.groupby("kind"):
        by_kind[kind] = {
            "events": int(g["event_id"].nunique()),
            "rows": int((df["kind"] == kind).sum()),
            "in_flint_hills": round(float(g["in_flint_hills"].mean()), 3),
            "march_april": round(float(g["month"].isin((3, 4)).mean()), 3),
            "median_dist_town_km": round(float(g["dist_town_km"].median()), 1),
            "median_frp_max": round(float(g["frp_max"].median()), 1),
            "median_gust_kmh": round(float(g["gust_kmh"].median()), 1),
            "median_rh_pct": round(float(g["rh_pct"].median()), 1),
            "median_n_detections": float(g["n_detections"].median()),
        }
    events_by_year = first.groupby(["year", "kind"])["event_id"].nunique().unstack(fill_value=0)

    fig, ax = plt.subplots(figsize=(9, 3.8))
    bottom = np.zeros(len(events_by_year))
    for kind in ("wf", "rx", "rx_weak", "static"):
        vals = events_by_year.get(kind, pd.Series(0, index=events_by_year.index)).to_numpy()
        ax.bar(events_by_year.index, vals, bottom=bottom, color=KIND_COLORS[kind], label=KIND_LABELS[kind])
        bottom += vals
    ax.axvline(TEST_FROM_YEAR - 0.5, color="black", ls="--", lw=1)
    ax.text(TEST_FROM_YEAR - 0.4, bottom.max() * 0.95, "test years →", fontsize=9)
    ax.set_xticks(events_by_year.index)
    ax.set_ylabel("Events")
    ax.set_title("Labeled events per year (after dropping degraded rows)")
    ax.legend(frameon=False, fontsize=8, ncols=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    savefig(fig, "dataset_by_year.png")

    return {
        "raw_rows": len(raw),
        "rows": len(df),
        "dropped": {"missing_features": int(na.sum()), "degraded_weather": int(degraded.sum()), "no_terrain": int(no_terrain.sum())},
        "events": int(df["event_id"].nunique()),
        "rows_by_snapshot": {int(k): int(v) for k, v in df["snapshot"].value_counts().sort_index().items()},
        "by_kind": by_kind,
        "events_by_year": {int(y): {k: int(v) for k, v in r.items()} for y, r in events_by_year.iterrows()},
    }


def headline(train: pd.DataFrame, test: pd.DataFrame) -> tuple[dict, dict, xgb.XGBClassifier, tuple[float, float]]:
    model = fit(train)
    a, b = platt(train)
    lr = fit_logistic(train)
    scores = {
        "xgboost": to_score(margin(model, test[FEATURES]), a, b),
        "logistic": np.rint(lr.predict_proba(test[FEATURES])[:, 1] * 100),
        "rules-v0": np.array([score_rules(r)[0] for r in test.to_dict("records")], dtype=float),
    }
    out = {name: two_views(test, s) for name, s in scores.items()}

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
    y, kind = test["label"].to_numpy(), test["kind"].to_numpy()
    for ax, (title, mask) in zip(axes, [
        ("Wildfire vs all burns", np.isin(kind, MODEL_KINDS)),
        ("Wildfire vs reported prescribed burns", np.isin(kind, ("wf", "rx"))),
    ]):
        for name, s in scores.items():
            fpr, tpr, _ = roc_curve(y[mask], s[mask])
            ax.plot(fpr, tpr, color=SCORER_COLORS[name], lw=2, label=f"{name} (AUC {auc(y[mask], s[mask]):.3f})")
        ax.plot([0, 1], [0, 1], color="#cccccc", lw=1, ls="--")
        ax.set_title(f"{title}, {TEST_FROM_YEAR}–{int(test['year'].max())}", fontsize=10)
        ax.set_xlabel("Share of burns flagged")
        ax.set_ylabel("Share of wildfires flagged")
        ax.legend(frameon=False, fontsize=8, loc="lower right")
    savefig(fig, "roc_test.png")
    return out, scores, model, (a, b)


def bootstrap(test: pd.DataFrame, scores: dict) -> dict:
    """Event-level bootstrap on the test years (all snapshots of an event are resampled together)."""
    m = test["kind"].isin(MODEL_KINDS).to_numpy()
    t = test[m]
    s = {k: v[m] for k, v in scores.items()}
    y, kind = t["label"].to_numpy(), t["kind"].to_numpy()
    _, inv = np.unique(t["event_id"].to_numpy(), return_inverse=True)
    rows_of = [np.flatnonzero(inv == i) for i in range(inv.max() + 1)]
    rng = np.random.default_rng(7)
    draws: dict[str, list] = {f"{n}|{v}": [] for n in s for v in ("all", "rx")}
    diffs: dict[str, list] = {f"xgboost-{o}|{v}": [] for o in ("logistic", "rules-v0") for v in ("all", "rx")}
    for _ in range(N_BOOT):
        rows = np.concatenate([rows_of[i] for i in rng.integers(0, len(rows_of), len(rows_of))])
        yy, kk = y[rows], kind[rows]
        rx = np.isin(kk, ("wf", "rx"))
        vals = {}
        for n, sc in s.items():
            vals[f"{n}|all"] = roc_auc_score(yy, sc[rows])
            vals[f"{n}|rx"] = roc_auc_score(yy[rx], sc[rows][rx])
        for k, v in vals.items():
            draws[k].append(v)
        for o in ("logistic", "rules-v0"):
            for v in ("all", "rx"):
                diffs[f"xgboost-{o}|{v}"].append(vals[f"xgboost|{v}"] - vals[f"{o}|{v}"])

    def ci(x: list) -> dict:
        lo, mid, hi = np.percentile(x, [2.5, 50, 97.5])
        return {"low": round(float(lo), 3), "median": round(float(mid), 3), "high": round(float(hi), 3),
                "share_above_zero": round(float(np.mean(np.array(x) > 0)), 3)}

    out = {"n_events": len(rows_of), "n_boot": N_BOOT, "auc": {k: ci(v) for k, v in draws.items()}, "diff": {k: ci(v) for k, v in diffs.items()}}

    fig, axes = plt.subplots(1, 2, figsize=(10, 2.8), sharey=True)
    names = list(s)
    for ax, (v, title) in zip(axes, [("all", "Wildfire vs all burns"), ("rx", "Wildfire vs reported prescribed burns")]):
        for i, n in enumerate(names):
            c = out["auc"][f"{n}|{v}"]
            ax.errorbar(c["median"], i, xerr=[[c["median"] - c["low"]], [c["high"] - c["median"]]], fmt="o",
                        color=SCORER_COLORS[n], capsize=4, lw=2)
            ax.text(c["high"] + 0.01, i, f"{c['low']:.2f}–{c['high']:.2f}", va="center", fontsize=8)
        ax.axvline(0.5, color="#cccccc", ls="--", lw=1)
        ax.set_xlim(0.45, 1.0)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("ROC-AUC (95% interval)")
    axes[0].set_yticks(range(len(names)), names)
    axes[0].invert_yaxis()
    savefig(fig, "bootstrap_auc.png")
    return out


def by_year(train: pd.DataFrame, test: pd.DataFrame, test_scores: dict) -> dict:
    """Unweighted AUC per year: leave-one-year-out for 2016–2022, the held-out model for the test years."""
    oof = {"xgboost": loyo(train), "logistic": loyo_logistic(train),
           "rules-v0": np.array([score_rules(r)[0] for r in train.to_dict("records")], dtype=float)}
    pooled = {
        name: {
            "wildfire_vs_burns_weighted": auc(train["label"].to_numpy(), s, weights(train)),
            **two_views(train, s),
        }
        for name, s in oof.items()
    }
    rows = []
    for year in sorted(train["year"].unique()):
        mk = (train["year"] == year).to_numpy()
        g = train[mk]
        rows.append({"year": int(year), "split": "loyo", **Counter(g.drop_duplicates("event_id")["kind"]),
                     **{name: two_views(g, s[mk]) for name, s in oof.items()}})
    mt = test["kind"].isin(MODEL_KINDS).to_numpy()
    for year in sorted(test["year"].unique()):
        mk = mt & (test["year"] == year).to_numpy()
        g = test[mk]
        rows.append({"year": int(year), "split": "test", **Counter(g.drop_duplicates("event_id")["kind"]),
                     **{name: two_views(g, s[mk]) for name, s in test_scores.items()}})

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    years = [r["year"] for r in rows]
    for ax, (view, title) in zip(axes, [("wildfire_vs_burns", "Wildfire vs all burns"),
                                         ("wildfire_vs_reported_rx", "Wildfire vs reported prescribed burns\n(years with ≥ 5 reported burns)")]):
        for name in ("xgboost", "logistic", "rules-v0"):
            vals = [r[name][view] if r[name][view] is not None and (view == "wildfire_vs_burns" or r.get("rx", 0) >= 5) else np.nan
                    for r in rows]
            ax.plot(years, vals, marker="o", color=SCORER_COLORS[name], label=name, lw=1.8)
        ax.axvline(TEST_FROM_YEAR - 0.5, color="black", ls="--", lw=1)
        ax.axhline(0.5, color="#cccccc", lw=1)
        ax.text(TEST_FROM_YEAR - 0.6, 0.42, "leave-one-year-out ", fontsize=8, ha="right")
        ax.text(TEST_FROM_YEAR - 0.4, 0.42, "test", fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.set_xticks(years, [str(y) for y in years], rotation=45)
        ax.set_ylim(0.4, 1.0)
    axes[0].set_ylabel("ROC-AUC")
    axes[1].legend(frameon=False, fontsize=8, loc="lower right")
    savefig(fig, "auc_by_year.png")
    return {"pooled_loyo": pooled, "years": rows}


def seed_spread(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    vals = [two_views(test, margin(fit(train, random_state=s), test[FEATURES])) for s in SEEDS]
    out = {}
    for view in ("wildfire_vs_burns", "wildfire_vs_reported_rx"):
        x = np.array([v[view] for v in vals])
        out[view] = {"min": round(float(x.min()), 3), "max": round(float(x.max()), 3), "mean": round(float(x.mean()), 3), "sd": round(float(x.std()), 3)}
    return {"seeds": len(SEEDS), **out}


def hparams(train: pd.DataFrame) -> dict:
    grid = []
    for depth in (2, 3, 4, 6):
        for n in (100, 300, 600):
            s = loyo(train, max_depth=depth, n_estimators=n)
            grid.append({"max_depth": depth, "n_estimators": n,
                         "wildfire_vs_burns_weighted": auc(train["label"].to_numpy(), s, weights(train)), **two_views(train, s)})
            log.info("  depth %d, %d rounds: %s", depth, n, grid[-1])

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2))
    for ax, (view, title) in zip(axes, [("wildfire_vs_burns_weighted", "Wildfire vs all burns (weighted)"),
                                         ("wildfire_vs_reported_rx", "Wildfire vs reported prescribed burns")]):
        mat = np.array([[g[view] for g in grid if g["max_depth"] == d] for d in (2, 3, 4, 6)])
        im = ax.imshow(mat, cmap="Oranges", vmin=mat.min() - 0.02, vmax=mat.max())
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                bold = (2, 3, 4, 6)[i] == 3 and (100, 300, 600)[j] == 300
                ax.text(j, i, f"{mat[i, j]:.3f}", ha="center", va="center", fontsize=9, fontweight="bold" if bold else None)
        ax.set_xticks(range(3), ["100", "300", "600"])
        ax.set_yticks(range(4), ["2", "3", "4", "6"])
        ax.set_xlabel("Boosting rounds")
        ax.set_ylabel("Max depth")
        ax.set_title(title, fontsize=10)
        fig.colorbar(im, ax=ax, shrink=0.8)
    fig.suptitle("Leave-one-year-out ROC-AUC on 2016–2022 (v1 setting in bold)", fontsize=10, y=1.06)
    savefig(fig, "hparam_grid.png")
    return {"grid": grid}


def ablations(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    rows = []
    for name, feats in ABLATIONS.items():
        s = loyo(train, feats)
        t = margin(fit(train, feats), test[feats])
        rows.append({
            "name": name, "n_features": len(feats),
            "loyo": {"wildfire_vs_burns_weighted": auc(train["label"].to_numpy(), s, weights(train)), **two_views(train, s)},
            "test": two_views(test, t),
        })
        log.info("  %s: %s", name, rows[-1])

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    labels = [r["name"] for r in rows]
    yy = np.arange(len(rows))
    for ax, (view, title) in zip(axes, [("wildfire_vs_burns", "Wildfire vs all burns"),
                                         ("wildfire_vs_reported_rx", "Wildfire vs reported prescribed burns")]):
        lo = [r["loyo"][view] for r in rows]
        te = [r["test"][view] for r in rows]
        ax.barh(yy - 0.2, lo, height=0.4, color="#f4a261", label="Leave-one-year-out, 2016–2022")
        ax.barh(yy + 0.2, te, height=0.4, color="#e07a1f", label=f"Test, {TEST_FROM_YEAR}–{int(test['year'].max())}")
        ax.axvline(rows[0]["test"][view], color="#e07a1f", ls=":", lw=1)
        ax.set_xlim(0.5, 0.95)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("ROC-AUC (unweighted)")
    axes[0].set_yticks(yy, labels, fontsize=8)
    axes[0].invert_yaxis()
    axes[1].legend(frameon=False, fontsize=8, loc="lower right")
    savefig(fig, "ablations.png")
    return {"rows": rows}


def calibration(test: pd.DataFrame, scores: dict) -> dict:
    m = test["kind"].isin(MODEL_KINDS).to_numpy()
    t = test[m]
    y = t["label"].to_numpy()
    w = weights(t)
    w = np.where(y == 1, w / w[y == 1].sum(), w / w[y == 0].sum())
    out = {}
    fig, ax = plt.subplots(figsize=(4.8, 4.5))
    ax.plot([0, 100], [0, 100], color="#cccccc", ls="--", lw=1)
    for name in ("xgboost", "logistic"):
        s = scores[name][m]
        b = np.clip(s // 10, 0, 9).astype(int)
        bins = []
        for i in range(10):
            k = b == i
            if k.sum() < 5:
                continue
            bins.append({"bin": f"{i * 10}–{i * 10 + 9}", "n": int(k.sum()),
                         "mean_score": round(float(np.average(s[k], weights=w[k])), 1),
                         "observed_pct": round(float(100 * np.average(y[k], weights=w[k])), 1)})
        p = s / 100
        brier = float(np.average((p - y) ** 2, weights=w))
        ece = sum(abs(r["mean_score"] - r["observed_pct"]) * r["n"] for r in bins) / sum(r["n"] for r in bins) / 100
        out[name] = {"brier": round(brier, 3), "ece": round(ece, 3), "bins": bins}
        ax.plot([r["mean_score"] for r in bins], [r["observed_pct"] for r in bins], marker="o", color=SCORER_COLORS[name],
                label=f"{name} (Brier {brier:.3f})")
    ax.set_xlabel("Mean score in bin")
    ax.set_ylabel("Wildfire share in bin (%, even prior)")
    ax.set_title(f"Calibration on {TEST_FROM_YEAR}–{int(test['year'].max())}", fontsize=10)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    savefig(fig, "calibration.png")
    return out


def thresholds(test: pd.DataFrame, score: np.ndarray) -> dict:
    kind = test["kind"].to_numpy()
    ts = np.arange(0, 101)
    curves = {k: [float((score[kind == k] >= t).mean()) for t in ts] for k in KIND_LABELS}
    table = [{"threshold": int(t), **{k: round(curves[k][t], 3) for k in KIND_LABELS}} for t in (30, 40, 50, 60, 70, 80)]

    fig, ax = plt.subplots(figsize=(7, 3.8))
    for k in KIND_LABELS:
        ax.plot(ts, np.array(curves[k]) * 100, color=KIND_COLORS[k], lw=2, label=KIND_LABELS[k])
    for t, lab in ((40, "Investigate"), (70, "Escalate")):
        ax.axvline(t, color="black", lw=0.8, ls="--")
        ax.text(t + 1, 95, lab, fontsize=8)
    ax.set_xlabel("Score threshold (model score, before guardrails)")
    ax.set_ylabel("Share at or above threshold (%)")
    ax.set_title(f"Threshold trade-off, xgboost, {TEST_FROM_YEAR}–{int(test['year'].max())} (all snapshots)", fontsize=10)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    savefig(fig, "thresholds.png")

    fig, axes = plt.subplots(1, 4, figsize=(12, 2.6), sharex=True)
    for ax, k in zip(axes, KIND_LABELS):
        ax.hist(score[kind == k], bins=np.arange(0, 105, 5), color=KIND_COLORS[k])
        ax.axvline(40, color="black", lw=0.8, ls="--")
        ax.axvline(70, color="black", lw=0.8, ls="--")
        ax.set_title(f"{KIND_LABELS[k]}\n(n={int((kind == k).sum())} rows)", fontsize=9)
        ax.set_xlabel("Score")
    axes[0].set_ylabel("Rows")
    savefig(fig, "score_distributions.png")

    raw = levels(test, score, guardrails=False)
    guarded = levels(test, score, guardrails=True)
    effect = {}
    for k in KIND_LABELS:
        mk = kind == k
        effect[k] = {"n": int(mk.sum()),
                     "raised": int(sum(LEVELS.index(g) > LEVELS.index(r) for r, g in zip(raw[mk], guarded[mk]))),
                     "lowered": int(sum(LEVELS.index(g) < LEVELS.index(r) for r, g in zip(raw[mk], guarded[mk]))),
                     "investigate_plus_before_guardrails": round(float(np.isin(raw[mk], ("investigate", "escalate")).mean()), 3)}
    return {"table": table, "guardrail_effect": effect}


def event_level(test: pd.DataFrame, score: np.ndarray) -> dict:
    """Highest level an event reaches within its first 24 h (alerts fire when the level rises)."""
    lv = levels(test, score)
    t = test.assign(level=[LEVELS.index(x) for x in lv], score=score)
    ev = t.groupby("event_id").agg(kind=("kind", "first"), level=("level", "max"), score=("score", "max"),
                                   first_level=("level", lambda x: x.iloc[0]))
    out = {}
    for k, g in ev.groupby("kind"):
        out[k] = {"events": len(g),
                  **{f"max_{lvl}": round(float((g["level"] == i).mean()), 3) for i, lvl in enumerate(LEVELS)},
                  "first_pass_investigate_plus": round(float((g["first_level"] >= 1).mean()), 3)}
    return out


def snapshots(test: pd.DataFrame, scores: dict) -> dict:
    out = {}
    for snap in sorted(test["snapshot"].unique()):
        mk = (test["snapshot"] == snap).to_numpy()
        g = test[mk]
        out[int(snap)] = {"rows": int(g["kind"].isin(MODEL_KINDS).sum()),
                          **{name: two_views(g, s[mk])["wildfire_vs_burns"] for name, s in scores.items()}}
    return out


def subgroups(test: pd.DataFrame, scores: dict) -> dict:
    """Event-level outcomes split by inside/outside the Flint Hills, where the weak negatives all live."""
    out = {}
    for name, s in scores.items():
        lv = levels(test, s)
        t = test.assign(level=[LEVELS.index(x) for x in lv])
        ev = t.groupby("event_id").agg(kind=("kind", "first"), fh=("in_flint_hills", "first"), level=("level", "max"))
        out[name] = {
            f"{k}|{'inside' if fh else 'outside'}": {"events": len(g), "investigate_plus": round(float((g["level"] >= 1).mean()), 3),
                                                    "escalate": round(float((g["level"] == 2).mean()), 3)}
            for (k, fh), g in ev.groupby(["kind", "fh"]) if k in ("wf", "rx")
        }
    return out


def label_design(df: pd.DataFrame, train: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Retrain under alternative negative-label designs and compare on the same test rows."""
    no_weak = train[train["kind"] != "rx_weak"].reset_index(drop=True)
    no_fh = [f for f in FEATURES if f != "in_flint_hills"]
    designs = {
        "v1: weak negatives at reduced weight": (train, FEATURES, None),
        "Weak negatives at full weight": (train, FEATURES, np.ones(len(train))),
        "No weak negatives": (no_weak, FEATURES, np.ones(len(no_weak))),
        "No weak negatives, no in_flint_hills": (no_weak, no_fh, np.ones(len(no_weak))),
        "Weak negatives, no in_flint_hills": (train, no_fh, None),
    }
    mt = test["kind"].isin(MODEL_KINDS).to_numpy()
    t = test[mt].reset_index(drop=True)
    fh, kind, y = t["in_flint_hills"].to_numpy() == 1, t["kind"].to_numpy(), t["label"].to_numpy()
    rows = []
    for name, (d, feats, w) in designs.items():
        s = margin(fit(d, feats, sample_weight=w), t[feats])
        # Leave-one-year-out on 2016–2022, always scoring every held-out row so designs share one benchmark.
        oof = np.zeros(len(train))
        for year in sorted(train["year"].unique()):
            va = (train["year"] == year).to_numpy()
            tr = (d["year"] != year).to_numpy()
            oof[va] = margin(fit(d[tr], feats, sample_weight=None if w is None else w[tr]), train[va][feats])
        rx = np.isin(kind, ("wf", "rx"))
        rows.append({
            "name": name, **two_views(t, s),
            "loyo": two_views(train, oof),
            "wf_vs_rx_inside_fh": auc(y[rx & fh], s[rx & fh]),
            "wf_vs_rx_outside_fh": auc(y[rx & ~fh], s[rx & ~fh]),
            "wf_vs_rx_weak": auc(y[np.isin(kind, ("wf", "rx_weak"))], s[np.isin(kind, ("wf", "rx_weak"))]),
        })
        log.info("  %s", rows[-1])

    views = [("loyo_rx", "vs reported burns,\nleave-one-year-out"), ("wildfire_vs_reported_rx", "vs reported burns,\ntest"),
             ("wf_vs_rx_inside_fh", "vs reported burns,\ntest, Flint Hills"), ("wf_vs_rx_weak", "vs unreported Flint Hills\nspring fires, test")]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    xs = np.arange(len(views))
    width = 0.8 / len(rows)
    palette = ["#e07a1f", "#f4a261", "#2a9d8f", "#8ab17d", "#bc6c25"]
    for i, r in enumerate(rows):
        vals = [r["loyo"]["wildfire_vs_reported_rx"] if v == "loyo_rx" else r[v] for v, _ in views]
        ax.bar(xs + (i - (len(rows) - 1) / 2) * width, vals, width=width, color=palette[i], label=r["name"])
    ax.set_xticks(xs, [lab for _, lab in views], fontsize=8)
    ax.set_ylim(0.5, 0.95)
    ax.set_ylabel("Wildfire ROC-AUC")
    ax.set_title("Negative-label design: what the weak Flint Hills labels buy and cost", fontsize=10)
    ax.legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncols=3)
    savefig(fig, "label_design.png")
    return {"rows": rows, "test_events_inside_fh": {k: int(t[(kind == k) & fh]["event_id"].nunique()) for k in MODEL_KINDS}}


def by_size(test: pd.DataFrame, score: np.ndarray) -> dict:
    acres = {r["id"]: r["acres"] for r in json.loads(WFIGS_PATH.read_text())}
    lv = levels(test, score)
    t = test.assign(level=[LEVELS.index(x) for x in lv])
    wf = t[t["kind"] == "wf"].groupby("event_id").agg(level=("level", "max"), incident=("incident_id", "first"))
    wf["acres"] = wf["incident"].map(acres)
    out = []
    for lab, lo, hi in (("< 100 acres", 0, 100), ("100–999 acres", 100, 1000), ("≥ 1,000 acres", 1000, np.inf)):
        g = wf[(wf["acres"] >= lo) & (wf["acres"] < hi)]
        out.append({"size": lab, "events": len(g),
                    "investigate_plus": round(float((g["level"] >= 1).mean()), 3) if len(g) else None,
                    "escalate": round(float((g["level"] == 2).mean()), 3) if len(g) else None})
    return {"rows": out, "unknown_size": int(wf["acres"].isna().sum())}


def errors(test: pd.DataFrame, score: np.ndarray, model: xgb.XGBClassifier) -> dict:
    wfigs = {r["id"]: r for r in json.loads(WFIGS_PATH.read_text())}
    contribs = model.get_booster().predict(xgb.DMatrix(test[FEATURES]), pred_contribs=True)[:, :-1]
    t = test.assign(score=score).reset_index(drop=True)
    best = t.loc[t.groupby("event_id")["score"].idxmax()]

    def describe(r: pd.Series) -> dict:
        c = contribs[r.name]
        top = np.argsort(-np.abs(c))[:3]
        inc = wfigs.get(r["incident_id"], {})
        return {
            "incident": r["incident_name"] or None, "county": inc.get("county"), "acres": inc.get("acres"),
            "date": r["as_of"][:10], "score": int(r["score"]), "snapshot": int(r["snapshot"]),
            "in_flint_hills": int(r["in_flint_hills"]), "gust_kmh": r["gust_kmh"], "rh_pct": r["rh_pct"],
            "dist_town_km": round(r["dist_town_km"], 1), "frp_max": r["frp_max"],
            "top_contributions": [f"{FEATURES[i]} {c[i]:+.2f}" for i in top],
        }

    false_alarms = best[best["kind"] == "rx"].sort_values("score", ascending=False).head(8)
    misses = best[best["kind"] == "wf"].sort_values("score").head(8)
    weak_hi = best[best["kind"] == "rx_weak"]
    return {
        "highest_reported_rx": [describe(r) for _, r in false_alarms.iterrows()],
        "lowest_wildfires": [describe(r) for _, r in misses.iterrows()],
        "rx_weak_reaching_70": int((weak_hi["score"] >= 70).sum()),
        "rx_weak_events": len(weak_hi),
    }


def importance(df: pd.DataFrame) -> dict:
    train = df[df["kind"].isin(MODEL_KINDS)].reset_index(drop=True)
    model = fit(train)
    c = model.get_booster().predict(xgb.DMatrix(train[FEATURES]), pred_contribs=True)[:, :-1]
    mean_abs = np.abs(c).mean(axis=0)
    order = np.argsort(-mean_abs)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.barh(range(len(order)), mean_abs[order], color="#e07a1f")
    ax.set_yticks(range(len(order)), [FEATURES[i] for i in order], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Mean |contribution| (log-odds)")
    ax.set_title("What drives the deployed model", fontsize=10)
    savefig(fig, "importance.png")

    panels = ["gust_kmh", "dist_town_km", "wind_kmh", "rh_pct", "elevation_m", "frp_max"]
    fig, axes = plt.subplots(2, 3, figsize=(11, 6))
    kind = train["kind"].to_numpy()
    for ax, f in zip(axes.ravel(), panels):
        i = FEATURES.index(f)
        x = train[f].to_numpy()
        if f in ("frp_max", "dist_town_km"):
            x = np.clip(x, 0.1, None)
            ax.set_xscale("log")
        for k in MODEL_KINDS:
            mk = kind == k
            ax.scatter(x[mk], c[mk, i], s=6, alpha=0.5, color=KIND_COLORS[k], label=KIND_LABELS[k])
        ax.axhline(0, color="#999999", lw=0.8)
        ax.set_title(f, fontsize=9)
        ax.set_ylabel("Contribution (log-odds)", fontsize=8)
    axes[0, 0].legend(frameon=False, fontsize=7, markerscale=2)
    fig.suptitle("Feature effects in the deployed model (positive = toward wildfire)", fontsize=10)
    fig.tight_layout()
    savefig(fig, "dependence.png")

    fh = FEATURES.index("in_flint_hills")
    inside = train["in_flint_hills"].to_numpy() == 1
    return {
        "mean_abs": [{"feature": FEATURES[i], "mean_abs_contribution": round(float(mean_abs[i]), 4)} for i in order],
        "in_flint_hills_contribution": {"inside": round(float(c[inside, fh].mean()), 3), "outside": round(float(c[~inside, fh].mean()), 3)},
    }


def lead_time() -> dict:
    rows = json.loads((WORK_DIR / "wf_lead_times.json").read_text())
    d = np.array([r["detection_minus_discovery_min"] for r in rows], dtype=float)
    acres = np.array([r["acres"] or np.nan for r in rows], dtype=float)
    q = np.percentile(d, [10, 25, 50, 75, 90])

    fig, ax = plt.subplots(figsize=(7, 3.4))
    clipped = np.clip(d, -720, 720)
    ax.hist(clipped, bins=np.arange(-720, 760, 60), color="#c8102e", alpha=0.85)
    ax.axvline(0, color="black", lw=1)
    ticks = np.arange(-720, 721, 240)
    ax.set_xticks(ticks, [f"{x // 60:+d} h" if x else "0" for x in ticks])
    ax.set_xlabel("First satellite detection minus reported discovery (outer bars include everything beyond ±12 h)")
    ax.set_ylabel("Wildfires")
    ax.text(-700, ax.get_ylim()[1] * 0.9, "satellite first", fontsize=8)
    ax.text(420, ax.get_ylim()[1] * 0.9, "report first", fontsize=8)
    savefig(fig, "lead_time.png")

    big = acres >= 1000
    small = acres < 100
    return {
        "n": len(d),
        "quantiles_min": {p: float(v) for p, v in zip(("p10", "p25", "p50", "p75", "p90"), q)},
        "share_before": round(float((d < 0).mean()), 3),
        "share_more_than_1h_before": round(float((d < -60).mean()), 3),
        "share_more_than_6h_after": round(float((d > 360).mean()), 3),
        "median_ge_1000_acres": float(np.median(d[big])) if big.any() else None, "n_ge_1000_acres": int(big.sum()),
        "median_lt_100_acres": float(np.median(d[small])) if small.any() else None, "n_lt_100_acres": int(small.sum()),
    }


# ---------------------------------------------------------------- main

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(DATASET_PATH)
    df = raw.dropna(subset=FEATURES)
    df = df[(df["degraded"] == 0) & (df["elevation_m"] > 0)].reset_index(drop=True)
    train = df[df["kind"].isin(MODEL_KINDS) & (df["year"] < TEST_FROM_YEAR)].reset_index(drop=True)
    test = df[df["year"] >= TEST_FROM_YEAR].reset_index(drop=True)
    log.info("train %d rows, test %d rows", len(train), len(test))

    results: dict = {"profile": data_profile(raw, df)}
    results["headline"], scores, model, (a, b) = headline(train, test)
    results["platt_train"] = {"a": a, "b": b}
    log.info("headline %s", results["headline"])
    log.info("bootstrap")
    results["bootstrap"] = bootstrap(test, scores)
    log.info("by year")
    results["by_year"] = by_year(train, test, scores)
    results["seeds"] = seed_spread(train, test)
    log.info("hyperparameters")
    results["hparams"] = hparams(train)
    log.info("ablations")
    results["ablations"] = ablations(train, test)
    results["calibration"] = calibration(test, scores)
    results["thresholds"] = thresholds(test, scores["xgboost"])
    results["event_level"] = {name: event_level(test, s) for name, s in scores.items()}
    results["snapshots"] = snapshots(test, scores)
    results["subgroups"] = subgroups(test, scores)
    log.info("label design")
    results["label_design"] = label_design(df, train, test)
    results["by_size"] = by_size(test, scores["xgboost"])
    results["errors"] = errors(test, scores["xgboost"], model)
    results["importance"] = importance(df)
    results["lead_time"] = lead_time()
    RESULTS_PATH.write_text(json.dumps(results, indent=1, default=float))
    log.info("wrote %s and %d figures in %s", RESULTS_PATH, len(list(FIG_DIR.glob("*.png"))), FIG_DIR)


if __name__ == "__main__":
    main()
