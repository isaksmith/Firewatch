"""Sensor smoke model v1, fitted by ml/smoke_sensor.py (docs/research/sensor-smoke-model-v1.md).

Turns a tower's PM2.5 rise or gas-resistance drop into a likelihood ratio for decision.py. The smoke rule in
sensors.py still decides whether a reading is smoke; this only sets how much it counts.
"""

import json
import math
from functools import lru_cache

from .config import DATA_DIR

MODEL_PATH = DATA_DIR / "model" / "smoke_sensor.json"


@lru_cache(maxsize=1)
def load() -> dict | None:
    try:
        return json.loads(MODEL_PATH.read_text())
    except (OSError, ValueError):
        return None


def _lr(curve: dict, x: float) -> float:
    """Posterior odds over the training prior's odds: the curve's likelihood ratio at x, never below 1."""
    logit_prior = math.log(curve["prior"] / (1 - curve["prior"]))
    return max(1.0, math.exp(min(curve["a"] + curve["b"] * x - logit_prior, 50.0)))


def pm_lr(rise: float) -> float | None:
    """Likelihood ratio of a local fire for a PM2.5 rise (µg/m³) over the node's baseline, before any cap."""
    m = load()
    return None if m is None else round(_lr(m["pm"], math.log1p(max(rise, 0.0))), 2)


def gas_lr(ratio: float) -> float | None:
    """Likelihood ratio of smoke for gas resistance / the node's baseline, before any cap."""
    m = load()
    return None if m is None or ratio <= 0 else round(_lr(m["gas"], math.log(ratio)), 2)


def gas_trigger() -> float | None:
    m = load()
    return None if m is None else m["gas"]["trigger_ratio"]


def rule_lr() -> dict | None:
    """The PM2.5 rule's measured likelihood ratio, for signals that carry no model weight."""
    m = load()
    return None if m is None else {**m["pm"]["rule"], "data": m["pm"]["data"]}
