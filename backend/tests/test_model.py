import json

from app.config import DATA_DIR
from app.scoring.model import load_model, score_model
from app.scoring.score import score_features


def _features(slug: str) -> dict:
    from app import sample
    from app.db import connect

    sample.load_all_now()
    with connect() as conn:
        row = conn.execute("SELECT features_json FROM events WHERE sample_slug = ?", (slug,)).fetchone()
    return json.loads(row["features_json"])


def test_model_artifact_loads():
    m = load_model()
    assert m is not None, f"expected a trained model in {DATA_DIR / 'model'}"
    assert m.name == "xgb-v1"
    assert "dist_static_km" not in m.features


def test_model_reasons_are_readable():
    f = _features("starbuck-2017")
    score, reasons = score_model(load_model(), f)
    assert 0 <= score <= 100
    assert reasons and all(isinstance(r["contribution"], int) and r["contribution"] != 0 for r in reasons)
    assert not any("=" in r["label"] for r in reasons), "every model feature needs a readable label"
    assert {"doy_sin", "doy_cos"}.isdisjoint(r["feature"] for r in reasons)


def test_degraded_events_fall_back_to_rules():
    f = _features("starbuck-2017")
    assert score_features(f, degraded=False).scorer == "xgb-v1"
    assert score_features(f, degraded=True).scorer == "rules-v0"
