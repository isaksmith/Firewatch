"""Turn features into a score, recommendation, reasons, and guardrails; persist the result."""

import json
import sqlite3
from dataclasses import dataclass

from ..config import get_settings
from ..db import iso, utcnow
from .rules import SCORER_NAME, score_rules

LEVELS = ("monitor", "investigate", "escalate")


@dataclass
class ScoreResult:
    score: int
    recommendation: str
    reasons: list[dict]
    scorer: str
    guardrail: str | None
    suppression: str | None


def recommend(score: int) -> str:
    s = get_settings()
    if score >= s.threshold_escalate:
        return "escalate"
    if score >= s.threshold_investigate:
        return "investigate"
    return "monitor"


def score_features(f: dict, degraded: bool) -> ScoreResult:
    # The ML model plugs in here; the rules scorer is also the fallback when weather is missing.
    score, reasons = score_rules(f)
    scorer = SCORER_NAME
    rec = recommend(score)
    guardrail = None

    is_static = f["dist_static_km"] <= 0.5
    if not is_static and rec == "monitor" and (f["dist_town_km"] <= 1 or f["dist_line_km"] <= 0.5):
        rec = "investigate"
        guardrail = "Raised to Investigate: very close to a town or transmission line"
    if is_static and f["frp_growth"] < 2 and rec != "monitor":
        rec = "monitor"
        guardrail = "Capped at Monitor: known industrial heat source, not growing"

    suppression = None
    if rec == "monitor":
        if f["dist_static_km"] <= 1:
            suppression = "static_source"
        elif (f["in_flint_hills"] and f["month"] in (3, 4)) or f["nearby_events_24h"] >= 3:
            suppression = "likely_prescribed"
        else:
            suppression = "low_signal"

    reasons = sorted(reasons, key=lambda r: abs(r["contribution"]), reverse=True)
    return ScoreResult(score, rec, reasons, scorer, guardrail, suppression)


def persist_score(conn: sqlite3.Connection, event_id: int, f: dict, degraded: bool, weather: dict | None) -> ScoreResult:
    result = score_features(f, degraded)
    prev = conn.execute("SELECT status, recommendation FROM events WHERE id = ?", (event_id,)).fetchone()
    now = iso(utcnow())

    conn.execute(
        "INSERT INTO scores(event_id, scored_at, score, recommendation, scorer, reasons_json, guardrail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_id, now, result.score, result.recommendation, result.scorer, json.dumps(result.reasons), result.guardrail),
    )

    status, reraised = prev["status"], 0
    if (
        status == "dismissed"
        and prev["recommendation"] in LEVELS
        and LEVELS.index(result.recommendation) > LEVELS.index(prev["recommendation"])
    ):
        status, reraised = "new", 1

    conn.execute(
        "UPDATE events SET features_json = ?, weather_json = ?, score = ?, recommendation = ?, degraded = ?, "
        "guardrail = ?, suppression = ?, status = ?, reraised = MAX(reraised, ?), updated_at = ? WHERE id = ?",
        (
            json.dumps(f), json.dumps(weather or {}), result.score, result.recommendation, int(degraded),
            result.guardrail, result.suppression, status, reraised, now, event_id,
        ),
    )
    return result
