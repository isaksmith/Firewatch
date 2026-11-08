"""XGBoost scorer v1, trained by ml/train.py. See backend/ml/report.md for how it was evaluated."""

import calendar
import json
import logging
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..config import DATA_DIR
from ..fire_weather import gfdi_band

log = logging.getLogger(__name__)

MODEL_DIR = DATA_DIR / "model"
KMH_PER_MPH = 1.609344
# Reasons are log-odds contributions scaled by the sigmoid's slope at 50, so one point is roughly one
# score point in the middle of the scale. They explain direction and size; they don't sum to the score.
POINTS_PER_LOGIT = 25.0


@dataclass(frozen=True)
class Model:
    name: str
    booster: object
    features: tuple[str, ...]
    a: float
    b: float


@lru_cache(maxsize=1)
def load_model() -> Model | None:
    meta_path, model_path = MODEL_DIR / "meta.json", MODEL_DIR / "xgb_v1.json"
    if not (meta_path.exists() and model_path.exists()):
        return None
    try:
        import xgboost
    except ImportError:
        log.warning("xgboost not installed; using the rules scorer")
        return None
    meta = json.loads(meta_path.read_text())
    booster = xgboost.Booster()
    booster.load_model(str(model_path))
    return Model(meta["name"], booster, tuple(meta["features"]), meta["platt"]["a"], meta["platt"]["b"])


def _km(v: float) -> str:
    return "50+ km" if v >= 50 else f"{v:.1f} km"


def _label(k: str, v: float, f: dict) -> str:
    match k:
        case "frp_max":
            return f"Peak heat {v:.0f} MW"
        case "frp_sum":
            return f"Total heat {v:.0f} MW"
        case "brightness_max":
            return f"Brightness {v:.0f} K"
        case "conf_high_frac":
            return "High-confidence detection" if v > 0 else "No high-confidence pixels"
        case "pixel_km2_min":
            return f"Pixel size {v:.2f} km²"
        case "n_detections":
            return f"{int(v)} detection{'s' if v != 1 else ''}"
        case "n_satellites":
            return f"Seen by {int(v)} satellite{'s' if v != 1 else ''}"
        case "minutes_active":
            return "Single pass so far" if v == 0 else f"Active {v / 60:.1f} h" if v >= 60 else f"Active {v:.0f} min"
        case "frp_growth":
            return "No growth data yet" if v == 1 else f"Heat changed {v:.1f}x between passes"
        case "is_night":
            return "Night detection" if v else "Daytime detection"
        case "local_hour":
            return f"Local time {int(v):02d}:00"
        case "season":
            return f"Time of year ({calendar.month_name[int(f['month'])]})"
        case "wind_kmh":
            return f"Wind {v:.0f} km/h"
        case "gust_kmh":
            return f"Gusts {v:.0f} km/h ({v / KMH_PER_MPH:.0f} mph)"
        case "rh_pct":
            return f"Humidity {v:.0f}%"
        case "temp_c":
            return f"Temperature {v:.0f}°C"
        case "precip_72h_mm":
            return "No rain in past 72 h" if v == 0 else f"{v:.0f} mm rain in past 72 h"
        case "thunder_24h":
            return "Thunderstorms in past 24 h" if v else "No thunderstorms in past 24 h"
        case "gfdi":
            return f"Fire danger {gfdi_band(v)} ({v:.0f})"
        case "elevation_m":
            return f"Elevation {v:.0f} m"
        case "slope_deg":
            return f"Slope {v:.0f}°"
        case "dist_line_km":
            return f"{_km(v)} from a transmission line"
        case "dist_substation_km":
            return f"{_km(v)} from a substation"
        case "dist_town_km":
            return f"{_km(v)} from a town"
        case "dist_static_km":
            return "At a known industrial heat source" if v <= 1 else f"{_km(v)} from a known heat source"
        case "in_flint_hills":
            return "Inside the Flint Hills" if v else "Outside the Flint Hills"
        case "nearby_events_24h":
            return f"{int(v)} other fire{'s' if v != 1 else ''} within 25 km in 24 h"
    return f"{k} = {v}"


def score_model(m: Model, f: dict) -> tuple[int, list[dict]]:
    import xgboost

    x = np.array([[float(f[k]) for k in m.features]], dtype=float)
    contribs = m.booster.predict(xgboost.DMatrix(x, feature_names=list(m.features)), pred_contribs=True)[0]
    margin = float(contribs.sum())
    score = round(100 / (1 + math.exp(-(m.a * margin + m.b))))

    by_feature = dict(zip(m.features, contribs[:-1]))
    if "doy_sin" in by_feature and "doy_cos" in by_feature:
        by_feature["season"] = by_feature.pop("doy_sin") + by_feature.pop("doy_cos")

    reasons = []
    for k, c in by_feature.items():
        points = round(float(c) * m.a * POINTS_PER_LOGIT)
        if points == 0:
            continue
        reasons.append({"feature": k, "label": _label(k, f.get(k, 0.0), f), "contribution": points})
    return max(0, min(100, score)), reasons
