"""Train and evaluate the wildfire scorer; export the model the backend serves.

    .venv/bin/python -m ml.train

- The model learns wildfire vs prescribed burn (WFIGS RX plus unreported Flint Hills spring fires).
  Known industrial heat sources are left to the app's guardrail and only used to evaluate the pipeline.
- Evaluation: temporal split (train <= 2022, test >= 2023); logistic regression baseline, the rules-v0
  scorer, and XGBoost, all on the same rows, with recommendations after the app's own guardrails.
- Calibration: Platt scaling on out-of-fold XGBoost margins (folds grouped by event so snapshots of one
  fire never straddle train and validation).
- Deployment: refit on all years, write data/model/xgb_v1.json + meta.json, and ml/report.md.
"""

import json
import logging
import math
from datetime import datetime, timezone
from statistics import median

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.scoring.rules import score_rules
from app.scoring.score import apply_guardrails

from .paths import DATASET_PATH, MODEL_DIR, REPORT_PATH, WORK_DIR

log = logging.getLogger("ml.train")

# dist_static_km is left out on purpose: heat sources are a guardrail, and as a model input it became a
# "far from a refinery means wildfire" shortcut.
FEATURES = [
    "frp_max", "frp_sum", "brightness_max", "conf_high_frac", "pixel_km2_min", "n_detections", "n_satellites",
    "minutes_active", "frp_growth", "is_night", "local_hour", "doy_sin", "doy_cos",
    "wind_kmh", "gust_kmh", "rh_pct", "temp_c", "precip_72h_mm", "thunder_24h", "gfdi",
    "elevation_m", "slope_deg", "dist_line_km", "dist_substation_km", "dist_town_km",
    "in_flint_hills", "nearby_events_24h",
]
MODEL_KINDS = ("wf", "rx", "rx_weak")
KIND_LABELS = {
    "wf": "Reported wildfires",
    "rx": "Reported prescribed burns",
    "rx_weak": "Unreported Flint Hills spring fires",
    "static": "Industrial heat sources",
}
TEST_FROM_YEAR = 2023
PARAMS = dict(
    n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
    min_child_weight=2, reg_lambda=1.0, eval_metric="logloss", tree_method="hist", random_state=7,
)


def weights(df: pd.DataFrame) -> np.ndarray:
    """Weak negatives count as much in total as reported prescribed burns, so they inform the Flint Hills
    case without drowning out the reported burns elsewhere in the state."""
    n_rx, n_weak = int((df["kind"] == "rx").sum()), int((df["kind"] == "rx_weak").sum())
    return np.where(df["kind"] == "rx_weak", n_rx / n_weak if n_weak else 1.0, 1.0)


def fit_xgb(df: pd.DataFrame) -> xgb.XGBClassifier:
    w, y = weights(df), df["label"].to_numpy()
    model = xgb.XGBClassifier(**PARAMS, scale_pos_weight=(w * (1 - y)).sum() / max((w * y).sum(), 1e-9))
    model.fit(df[FEATURES], y, sample_weight=w)
    return model


def margins(model: xgb.XGBClassifier, X: pd.DataFrame) -> np.ndarray:
    return model.get_booster().predict(xgb.DMatrix(X), output_margin=True)


def platt(df: pd.DataFrame) -> tuple[float, float]:
    """Fit p = sigmoid(a * margin + b) on out-of-fold margins, to an even wildfire/burn prior so the
    score doesn't depend on how many of each kind happened to be sampled."""
    oof = np.zeros(len(df))
    for tr, va in GroupKFold(n_splits=5).split(df, df["label"], df["event_id"]):
        m = fit_xgb(df.iloc[tr])
        oof[va] = margins(m, df.iloc[va][FEATURES])
    w, y = weights(df), df["label"].to_numpy()
    w = np.where(y == 1, w / w[y == 1].sum(), w / w[y == 0].sum())
    lr = LogisticRegression(C=1e6).fit(oof.reshape(-1, 1), y, sample_weight=w * len(y))
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def to_score(margin: np.ndarray, a: float, b: float) -> np.ndarray:
    return np.rint(100 / (1 + np.exp(-(a * margin + b))))


def outcomes(df: pd.DataFrame, score: np.ndarray) -> dict:
    """Share of each kind at each recommendation, after the app's guardrails."""
    recs = np.array([apply_guardrails(f, int(s))[0] for f, s in zip(df.to_dict("records"), score)])
    out = {}
    for kind in KIND_LABELS:
        m = (df["kind"] == kind).to_numpy()
        if m.any():
            out[kind] = {"n": int(m.sum()), **{r: float((recs[m] == r).mean()) for r in ("monitor", "investigate", "escalate")}}
    return out


def metrics(y: np.ndarray, s: np.ndarray, w: np.ndarray | None = None) -> dict:
    if len(set(y)) < 2:
        return {"roc_auc": None, "pr_auc": None, "n": int(len(y))}
    return {
        "roc_auc": round(float(roc_auc_score(y, s, sample_weight=w)), 3),
        "pr_auc": round(float(average_precision_score(y, s, sample_weight=w)), 3),
        "n": int(len(y)),
    }


def by_year_cv(train: pd.DataFrame) -> dict:
    """Leave-one-year-out on the training years: a second, larger look at year-to-year generalization."""
    oof = {"xgboost": np.zeros(len(train)), "logistic": np.zeros(len(train))}
    for tr, va in LeaveOneGroupOut().split(train, train["label"], train["year"]):
        a, b = train.iloc[tr], train.iloc[va]
        oof["xgboost"][va] = margins(fit_xgb(a), b[FEATURES])
        oof["logistic"][va] = fit_logistic(a).predict_proba(b[FEATURES])[:, 1]
    y, rx = train["label"].to_numpy(), train["kind"].isin(("wf", "rx")).to_numpy()
    return {
        name: {"wildfire_vs_burns": metrics(y, s, weights(train)), "wildfire_vs_reported_rx": metrics(y[rx], s[rx])}
        for name, s in oof.items()
    }


def fit_logistic(df: pd.DataFrame):
    lr = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=3000, class_weight="balanced"))
    return lr.fit(df[FEATURES], df["label"], logisticregression__sample_weight=weights(df))


def evaluate(df: pd.DataFrame) -> dict:
    model_rows = df["kind"].isin(MODEL_KINDS)
    train = df[model_rows & (df["year"] < TEST_FROM_YEAR)]
    test_all = df[df["year"] >= TEST_FROM_YEAR]
    log.info("train %d rows %s; test %d rows %s", len(train), train["kind"].value_counts().to_dict(), len(test_all), test_all["kind"].value_counts().to_dict())

    model = fit_xgb(train)
    a, b = platt(train)
    lr = fit_logistic(train)
    scores = {
        "xgboost": to_score(margins(model, test_all[FEATURES]), a, b),
        "logistic": np.rint(lr.predict_proba(test_all[FEATURES])[:, 1] * 100),
        "rules-v0": np.array([score_rules(r)[0] for r in test_all.to_dict("records")], dtype=float),
    }

    kind = test_all["kind"]
    y = test_all["label"].to_numpy()
    subsets = {
        "wildfire_vs_burns": kind.isin(MODEL_KINDS),
        "first_pass_only": kind.isin(MODEL_KINDS) & (test_all["snapshot"] == 0),
        "wildfire_vs_reported_rx": kind.isin(("wf", "rx")),
        "flint_hills_spring": kind.isin(MODEL_KINDS) & (test_all["in_flint_hills"] == 1) & test_all["month"].isin((3, 4)),
    }
    result = {
        "train_rows": len(train),
        "test_counts": kind.value_counts().to_dict(),
        "by_year_cv": by_year_cv(train.reset_index(drop=True)),
        "models": {},
    }
    for name, s in scores.items():
        result["models"][name] = {
            **{k: metrics(y[m.to_numpy()], s[m.to_numpy()]) for k, m in subsets.items()},
            "outcomes": outcomes(test_all, s),
        }
    return result


def explain_global(model: xgb.XGBClassifier, X: pd.DataFrame) -> list[dict]:
    contribs = model.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)[:, :-1]
    mean_abs = np.abs(contribs).mean(axis=0)
    order = np.argsort(-mean_abs)
    return [{"feature": FEATURES[i], "mean_abs_contribution": round(float(mean_abs[i]), 4)} for i in order]


def lead_time_stats() -> dict:
    path = WORK_DIR / "wf_lead_times.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text())
    diffs = [r["detection_minus_discovery_min"] for r in rows]
    if not diffs:
        return {}
    return {
        "matched_wildfires": len(diffs),
        "median_detection_minus_discovery_min": median(diffs),
        "share_detected_before_discovery": round(sum(d < 0 for d in diffs) / len(diffs), 3),
        "share_within_1h_after": round(sum(0 <= d <= 60 for d in diffs) / len(diffs), 3),
    }


def pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def write_report(df: pd.DataFrame, ev: dict, importance: list[dict], lead: dict, meta: dict) -> None:
    events = df.groupby("kind")["event_id"].nunique().to_dict()
    lines = [
        "# Firewatch scorer v1: evaluation report",
        "",
        f"Generated {meta['trained_at']} by `ml/train.py`. Numbers are from real Kansas data; small samples, read accordingly.",
        "",
        "## Data",
        "",
        f"- FIRMS Kansas archive, VIIRS (Suomi NPP, NOAA-20) and MODIS, {int(df['year'].min())}–{int(df['year'].max())}, replayed through the app's own clustering.",
        f"- Positives: **{events.get('wf', 0)} wildfire events** matched to NIFC WFIGS wildfire incidents.",
        f"- Negatives: **{events.get('rx', 0)} prescribed burns** matched to WFIGS, plus **{events.get('rx_weak', 0)} unreported Flint Hills fires in March–April** "
        "(weak label: ranchers burn about 2 million acres there each spring and almost none of it is reported; anything within 10 km and 3 days of a reported wildfire is excluded). "
        "They're weighted so that in total they count the same as the reported prescribed burns; at full weight they drowned out the reported burns, which are mostly outside the Flint Hills.",
        f"- Evaluation only: **{events.get('static', 0)} events at persistent industrial heat sources** (refineries, plants). The model never trains on these; the app caps them at Monitor with a guardrail.",
        "- Other unreported fires are left out, because most Kansas rural fires never reach WFIGS and we can't tell what they were.",
        f"- Each event contributes up to 3 rows: its features as of the first pass, the second pass, and the last pass within 24 h ({len(df)} rows total). This matches how live scoring sees a fire.",
        f"- Temporal split: train ≤ {TEST_FROM_YEAR - 1}, test ≥ {TEST_FROM_YEAR}. Test rows: {ev['test_counts']}.",
        "",
        "## Ranking quality on the held-out years (ROC-AUC)",
        "",
        "| Scorer | Wildfire vs all burns | PR-AUC | First pass only | Wildfire vs reported prescribed burns | Flint Hills, March–April |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in ev["models"].items():
        lines.append(
            f"| {name} | {m['wildfire_vs_burns']['roc_auc']} | {m['wildfire_vs_burns']['pr_auc']} | {m['first_pass_only']['roc_auc']} | "
            f"{m['wildfire_vs_reported_rx']['roc_auc']} | {m['flint_hills_spring']['roc_auc']} |"
        )
    cv = ev["by_year_cv"]
    lines += [
        "",
        f"Second look, leave-one-year-out across the training years ({int(df['year'].min())}–{TEST_FROM_YEAR - 1}, each year held out in turn):",
        "",
        "| Scorer | Wildfire vs all burns | Wildfire vs reported prescribed burns |",
        "|---|---|---|",
        *[f"| {name} | {m['wildfire_vs_burns']['roc_auc']} | {m['wildfire_vs_reported_rx']['roc_auc']} |" for name, m in cv.items()],
        "",
        "With about 100 events per year the two views can disagree on which model is ahead; both are reported rather than picking the flattering one.",
        "",
        "## What a dispatcher would see (after guardrails; Escalate ≥ 70, Investigate ≥ 40)",
        "",
        "| Scorer | Wildfires escalated | Wildfires at Investigate+ | " + " | ".join(f"{KIND_LABELS[k]} at Monitor" for k in ("rx", "rx_weak", "static")) + " |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in ev["models"].items():
        o = m["outcomes"]
        wf = o.get("wf", {})
        cells = [pct(wf.get("escalate")), pct(wf["escalate"] + wf["investigate"]) if wf else "–"]
        cells += [pct(o.get(k, {}).get("monitor")) for k in ("rx", "rx_weak", "static")]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## What drives the score (deployed model, mean |contribution| in log-odds)",
        "",
        "| Feature | Mean abs. contribution |",
        "|---|---|",
        *[f"| `{r['feature']}` | {r['mean_abs_contribution']} |" for r in importance[:12]],
        "",
    ]
    if lead:
        lines += [
            "## Satellite detection vs reported discovery (matched wildfires)",
            "",
            f"- Matched wildfires: {lead['matched_wildfires']}",
            f"- Median first detection minus WFIGS discovery: **{lead['median_detection_minus_discovery_min']:.0f} min** (negative = satellite first)",
            f"- Detected before the reported discovery: {pct(lead['share_detected_before_discovery'])}; within 1 h after: {pct(lead['share_within_1h_after'])}",
            "",
            "WFIGS discovery times are often entered after the fact, so treat this as indicative.",
            "",
        ]
    lines += [
        "## Caveats",
        "",
        "- Reported wildfires skew toward fires near people (that's who reports them), so distance-to-town partly measures reporting, not risk.",
        "- The Flint Hills weak labels are mostly right but not all: an unreported escaped burn would be labeled prescribed. The column for reported prescribed burns is the strict test.",
        "- Elevation and time of year partly encode region and burn season (Flint Hills prescribed burns cluster in March–April at 300–500 m), so they act as proxies, not causes.",
        "- The persistent-heat-source layer is derived from all years, including the test years.",
        "- Scores are calibrated to an even wildfire/burn prior, not to the real share of wildfires among all detections, which is far lower. Use them to rank and to pick thresholds, not as literal probabilities.",
        "",
        f"Deployed model: refit on all {meta['rows']} training rows; Platt calibration a={meta['platt']['a']:.3f}, b={meta['platt']['b']:.3f}.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    df = pd.read_csv(DATASET_PATH)
    n = len(df)
    # Degraded rows are scored by the rules fallback in the app; 0 m elevation means a terrain fetch failed.
    df = df.dropna(subset=FEATURES)
    df = df[(df["degraded"] == 0) & (df["elevation_m"] > 0)]
    log.info("dataset: %d rows (%d dropped as degraded), %d events", len(df), n - len(df), df["event_id"].nunique())

    ev = evaluate(df)
    for name, m in ev["models"].items():
        log.info("%-9s %s", name, {k: v["roc_auc"] for k, v in m.items() if k != "outcomes"})
        log.info("%-9s at monitor: %s", "", {k: round(v["monitor"], 2) for k, v in m["outcomes"].items()})

    train = df[df["kind"].isin(MODEL_KINDS)]
    model = fit_xgb(train)
    a, b = platt(train)
    importance = explain_global(model, train[FEATURES])
    lead = lead_time_stats()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.get_booster().save_model(MODEL_DIR / "xgb_v1.json")
    meta = {
        "name": "xgb-v1",
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "features": FEATURES,
        "platt": {"a": a, "b": b},
        "rows": len(train),
        "events_by_kind": df.groupby("kind")["event_id"].nunique().to_dict(),
        "years": [int(df["year"].min()), int(df["year"].max())],
        "evaluation": ev,
        "importance": importance,
        "lead_time": lead,
    }
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=1, default=lambda o: o if not isinstance(o, float) or math.isfinite(o) else None))
    write_report(df, ev, importance, lead, meta)
    log.info("wrote %s, %s", MODEL_DIR / "xgb_v1.json", REPORT_PATH)


if __name__ == "__main__":
    main()
