from app import sample
from app.config import get_settings
from app.db import connect


def _run(scorer: str, monkeypatch) -> tuple[dict, dict, set]:
    monkeypatch.setenv("SCORER", scorer)
    get_settings.cache_clear()
    sample.load_all_now()
    expected = {fx["slug"]: fx["expected"] for fx in sample.load_fixtures()}
    with connect() as conn:
        rows = conn.execute(
            "SELECT e.sample_slug, e.recommendation, s.scorer FROM events e JOIN scores s ON s.event_id = e.id"
        ).fetchall()
    got = {r["sample_slug"]: r["recommendation"] for r in rows}
    assert len(got) == len(expected), "each fixture should cluster into exactly one event"
    return expected, got, {r["scorer"] for r in rows}


def test_rules_scorer_matches_every_fixture(monkeypatch):
    expected, got, scorers = _run("rules", monkeypatch)
    assert got == expected
    assert scorers == {"rules-v0"}


def test_model_escalates_wildfires_and_nothing_else(monkeypatch):
    # A learned model may put a burn at Investigate; it must never miss a wildfire or escalate a burn.
    expected, got, scorers = _run("model", monkeypatch)
    assert scorers == {"xgb-v1"}
    assert {s for s, r in got.items() if r == "escalate"} == {s for s, e in expected.items() if e == "escalate"}
