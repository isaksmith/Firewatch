"""Expected-loss decision model behind the playbook's recommendations (docs/DESIGN.md section 5.7).

For each option:

    expected loss = P(fire) x acres burned before enough help is on scene
                  + (1 - P(fire)) x what a false alarm costs, in acre-equivalents

The option with the lowest expected loss is recommended. Everything is in one unit (acres) so the chief can
read the trade: "a false page costs us about as much as 100 acres burned".

P(fire) starts from a base rate for the first signal and multiplies the odds by a likelihood ratio for each
independent piece of evidence. Every number below is a planning assumption with its source, and a district can
override any of them under "decision" in its settings.json. Until outcomes are logged and the ratios are
re-fitted, treat the probabilities as consistent rankings, not measured frequencies.
"""

import json
import re
from functools import lru_cache

from .config import DATA_DIR

FIRE_DAY_PATH = DATA_DIR / "model" / "fire_day.json"

DEFAULTS: dict[str, dict] = {
    # --- how likely is it a fire ---
    "line_fault_base_rate": {"value": 0.03, "source": "PG&E: reportable ignitions were 2.2-3.6% of fire-season outages (CPUC 2021)"},
    "danger_multiplier": {"value": {"Low-Moderate": 0.3, "High": 1.0, "Very High": 1.5, "Severe": 2.0, "Extreme": 3.0},
                          "source": "Assumption: line faults on high-wind, dry days ignite more often (Plains megafires)"},
    "danger_exponent": {"value": 0.5, "source": "Assumption: the fire-day model measures fire starts per day; on windy days line faults rise too, so the per-fault multiplier is RR^0.5 (half the effect, in log terms). 0 = weather doesn't change per-fault odds, 1 = all of the increase is per fault"},
    "satellite_prior": {"value": 0.15, "source": "Assumption: training set had 224 wildfires vs 490 burns (31%); most burns go unrecorded, so the real share is lower"},
    "other_prior": {"value": 0.05, "source": "Assumption: base rate when the first signal is a text or camera"},
    "lr_neighbor_smoke": {"value": 20.0, "source": "Assumption: a registered neighbor nearby saying they see smoke"},
    "lr_neighbor_no_smoke": {"value": 0.4, "source": "Assumption: a neighbor nearby sees nothing (smoke may be hidden by terrain)"},
    "lr_neighbor_my_burn": {"value": 0.1, "source": "Assumption: a neighbor says it's their burn"},
    "lr_report_registered": {"value": 10.0, "source": "Assumption: a texted fire report from a registered number"},
    "lr_report_unregistered": {"value": 2.0, "source": "Assumption: a texted report from an unknown number"},
    "lr_line_fault": {"value": 10.0, "source": "Assumption: a line lockout next to an already-detected fire"},
    "lr_camera": {"value": 8.0, "source": "Assumption: camera smoke detection"},
    "lr_registered_burn": {"value": 0.05, "source": "Assumption: inside a registered burn that hasn't escaped"},
    # satellite: Michael's scorer is calibrated to an even wildfire/burn prior, so score s is a likelihood ratio s/(100-s)
    # --- what a false alarm costs, in acres burned we'd accept to avoid it ---
    "cost_false_page_acres": {"value": 100.0, "source": "Assumption, set by the chief: 18 volunteers leave work; budget is 2 false pages a month"},
    "cost_false_mutual_aid_acres": {"value": 250.0, "source": "Assumption: pulls a neighbor's crew off its own red-flag day"},
    "cost_heads_up_acres": {"value": 3.0, "source": "Assumption: a no-action text to a station"},
    "cost_neighbor_text_acres": {"value": 1.0, "source": "Assumption: one 'see smoke?' text to a neighbor"},
    # --- timing ---
    "second_source_min": {"value": 8, "source": "Scenario: a neighbor answered 'see smoke?' 8 min after the fault"},
    "next_pass_min": {"value": 30, "source": "Assumption: next satellite look at a weak hotspot"},
    "call_911_min": {"value": 31, "source": "Packet: today's 911 call comes 31 min after ignition"},
    "mutual_aid_travel_min": {"value": 35, "source": "Packet: mutual aid is 30-40 min out"},
    "heads_up_saves_min": {"value": 10, "source": "Assumption: a station given a heads-up is staffed and rolls ~10 min sooner"},
    "approve_mutual_aid_min": {"value": 5, "source": "Assumption: after a page, the chief approves the mutual-aid draft within ~5 min"},
    "size_up_min": {"value": 5, "source": "Assumption: Brush 1 sizes up the fire within 5 min of arriving"},
    "hold_window_min": {"value": 30, "source": "Assumption: 2 trucks hold a fire only if it stays under their capacity for 30 min after they arrive"},
}


@lru_cache(maxsize=1)
def fire_day_model() -> dict | None:
    """The fitted fire-day model (ml/fire_day.py), or None if it hasn't been built."""
    try:
        return json.loads(FIRE_DAY_PATH.read_text())
    except (OSError, ValueError):
        return None


def _fitted() -> dict:
    """Weights that come from a fitted model, with their source, when the model file exists."""
    m = fire_day_model()
    if m is None:
        return {}
    d = m["data"]
    return {"danger_multiplier": {
        "value": m["danger_multiplier"],
        "source": f"Fire-day model v1: Kansas wildfire starts per day by fire danger, relative to {m['reference_band']}; "
                  f"{d['fires_used']} WFIGS wildfires {d['period'][0][:4]}-{d['period'][1][:4]} (docs/research/fire-day-model-v1.md)",
    }}


def weights(settings: dict) -> dict:
    """Defaults, replaced by fitted values where a model exists, then by the district's settings['decision']."""
    over, fitted = settings.get("decision", {}), _fitted()
    return {k: over.get(k, fitted.get(k, v)["value"]) for k, v in DEFAULTS.items()}


def described(settings: dict) -> list[dict]:
    over, fitted = settings.get("decision", {}), _fitted()
    out = []
    for k, v in DEFAULTS.items():
        src = fitted.get(k, v)
        out.append({"key": k, "value": over.get(k, src["value"]),
                    "source": "District setting" if k in over else src["source"]})
    return out


def danger_factor(band: str, w: dict) -> float:
    """How much the danger level multiplies the odds that a line fault starts a fire.

    With the fitted fire-day model, its per-day rate ratio raised to `danger_exponent`; the hand-set fallback
    values are already per fault."""
    rr = w["danger_multiplier"].get(band, 1.0)
    return rr ** w["danger_exponent"] if "danger_multiplier" in _fitted() else rr


def large_fire_share(band: str) -> dict | None:
    """Historical share of reported Kansas wildfires that started on a `band` day and grew past 1,000 ac."""
    m = fire_day_model()
    if m is None or band not in m["bands"]:
        return None
    v = m["bands"][band]["large"]["1000"]
    return v if v["n"] else None


def _odds(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return p / (1 - p)


def _p(odds: float) -> float:
    return odds / (1 + odds)


SCORE_RE = re.compile(r"score (\d+)")


def probability(evidence: list[dict], danger: str, w: dict, sat_score: int | None = None) -> dict:
    """P(fire) and the steps that got there. Evidence items are confirm.py's {kind, label, counts, note}."""
    items = sorted(evidence, key=lambda e: e.get("at") or "9999")  # the earliest signal sets the base rate
    if sat_score is not None and not any(e["kind"] == "satellite" for e in items):
        items.insert(0, {"kind": "satellite", "label": f"Satellite: score {sat_score}", "counts": "yes"})
    steps: list[dict] = []
    first = next((e for e in items if e["kind"] in ("line_fault", "satellite") and e.get("counts") != "no"), None)
    if first is not None and first["kind"] == "line_fault":
        mult = danger_factor(danger, w)
        p0 = min(0.9, w["line_fault_base_rate"] * mult)
        if "danger_multiplier" in _fitted():
            rr = w["danger_multiplier"].get(danger, 1.0)
            how = f"fire-day model: {rr:g}x the fire starts of a High day, ^{w['danger_exponent']:g} per line fault"
        else:
            how = "assumed"
        steps.append({"text": f"{first['label']}: base rate {w['line_fault_base_rate']:.0%} x{mult:.2g} for {danger} danger ({how})",
                      "p": p0})
    elif first is not None:
        p0 = w["satellite_prior"]
        steps.append({"text": f"Satellite detections in Kansas: base rate {p0:.0%}", "p": p0})
    else:
        p0 = w["other_prior"]
        steps.append({"text": f"No line or satellite signal: base rate {p0:.0%}", "p": p0})
    odds = _odds(p0)

    for e in items:
        if e is first and e["kind"] == "line_fault":
            continue
        lr, why = _likelihood_ratio(e, w)
        if lr == 1.0:
            continue
        odds *= lr
        steps.append({"text": f"{e['label']}{why}", "factor": round(lr, 2), "p": _p(odds)})
    p = _p(odds)
    return {"p": round(p, 3), "steps": [s | {"p": round(s["p"], 3)} for s in steps]}


def _likelihood_ratio(e: dict, w: dict) -> tuple[float, str]:
    kind, counts, label = e["kind"], e.get("counts"), e.get("label", "")
    if kind == "satellite":
        m = SCORE_RE.search(label)
        if not m:
            return 1.0, ""
        s = min(max(int(m.group(1)), 1), 99)
        return s / (100 - s), f" (score {s} = x{s / (100 - s):.2g} on the scorer's even prior)"
    if kind == "line_fault":
        return (w["lr_line_fault"], "") if counts == "yes" else (1.0, "")
    if kind == "neighbor_reply":
        if "sees smoke" in label:
            return w["lr_neighbor_smoke"], ""
        if "no smoke" in label:
            return w["lr_neighbor_no_smoke"], ""
        if "their burn" in label:
            return w["lr_neighbor_my_burn"], ""
        return 1.0, ""
    if kind == "report":
        return (w["lr_report_registered"], "") if counts == "yes" else (w["lr_report_unregistered"], "")
    if kind == "camera_smoke":
        return w["lr_camera"], ""
    if kind == "burn_notice":
        return (1.0, "") if str(e.get("note", "")).startswith("escaped") else (w["lr_registered_burn"], " (not escaped)")
    return 1.0, ""


def expected_loss(p: float, acres_if_fire: float, cost_if_not: float) -> float:
    return p * acres_if_fire + (1 - p) * cost_if_not


def break_even(best: dict, other: dict) -> float | None:
    """P(fire) at which `other` and `best` have equal expected loss, or None if they never cross in (0, 1)."""
    a1, f1, a2, f2 = best["if_fire_acres"], best["if_not_cost"], other["if_fire_acres"], other["if_not_cost"]
    denom = (a1 - f1) - (a2 - f2)
    if denom == 0:
        return None
    x = (f2 - f1) / denom
    return x if 0 < x < 1 else None
