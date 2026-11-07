"""The Cottonwood Creek afternoon (design/SCENARIO.md) played through the real pipeline."""
import json

import pytest

from app import sample
from app.db import connect

SLUG = "cottonwood-creek"


@pytest.fixture
def scenario():
    sample.load_all_now()
    with connect() as conn:
        yield conn


def _event(conn, slug):
    return conn.execute("SELECT * FROM events WHERE sample_slug = ?", (slug,)).fetchone()


def _reasons(conn, event_id, nth=-1):
    rows = conn.execute("SELECT * FROM scores WHERE event_id = ? ORDER BY id", (event_id,)).fetchall()
    return rows[nth], [r["label"] for r in json.loads(rows[nth]["reasons_json"])]


def test_real_fire_escalates_near_87(scenario):
    ev = _event(scenario, SLUG)
    assert ev["recommendation"] == "escalate"
    assert abs(ev["score"] - 87) <= 3
    # At 2:05, before the driver's text, the page already went out.
    rows = scenario.execute("SELECT score, recommendation FROM scores WHERE event_id = ? ORDER BY id", (ev["id"],)).fetchall()
    assert [r["recommendation"] for r in rows] == ["investigate", "escalate", "escalate", "escalate"]
    assert abs(rows[2]["score"] - 87) <= 3


def test_line_fault_alone_is_investigate(scenario):
    ev = _event(scenario, SLUG)
    first, labels = _reasons(scenario, ev["id"], 0)
    assert first["recommendation"] == "investigate"
    assert labels[0] == "A power-line fault on the Ortiz lease line at 1:50. No satellite has seen heat yet"


def test_fault_and_goes_are_one_event_and_escalate(scenario):
    ev = _event(scenario, SLUG)
    kinds = [r["kind"] for r in scenario.execute("SELECT kind FROM signals WHERE event_id = ?", (ev["id"],))]
    assert sorted(kinds) == ["line_fault", "report"]
    dets = scenario.execute("SELECT source FROM detections WHERE event_id = ?", (ev["id"],)).fetchall()
    assert [d["source"] for d in dets] == ["GOES19_FDC", "GOES19_FDC"]
    _, rows = _reasons(scenario, ev["id"], 1)
    assert rows[0] == "A power-line fault on the Ortiz lease line at 1:50, 0.3 mi away"
    assert ev["recommendation"] == "escalate"


def test_reasons_in_story_order(scenario):
    _, labels = _reasons(scenario, _event(scenario, SLUG)["id"], 2)
    assert labels[:4] == [
        "A power-line fault on the Ortiz lease line at 1:50, 0.3 mi away",
        "The satellite saw new heat at 2:00, and again at 2:05; it is growing",
        "Red Flag Warning: wind 35 mph gusting 55, humidity 11%",
        "No burn has been called in near here",
    ]


def test_public_report_joins_the_fire(scenario):
    ev = _event(scenario, SLUG)
    _, labels = _reasons(scenario, ev["id"])
    assert any(label.startswith("A person reported smoke at 2:21") for label in labels)
    assert scenario.execute("SELECT COUNT(*) FROM events WHERE sample_slug LIKE 'cottonwood%'").fetchone()[0] == 3


@pytest.mark.parametrize("slug,called_in", [
    ("cottonwood-creek-henderson", "10:40"), ("cottonwood-creek-ortiz-burn", "11:15"),
])
def test_both_permitted_burns_stay_quiet(scenario, slug, called_in):
    ev = _event(scenario, slug)
    assert ev["recommendation"] == "monitor"
    assert ev["suppression"] == "logged_burn"
    _, labels = _reasons(scenario, ev["id"])
    assert f"Matches a burn called in to dispatch at {called_in}" in labels


def test_alert_detail_lists_data_age_per_source():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        alerts = client.get("/api/alerts").json()["alerts"]
        fire = next(a for a in alerts if a["sample_slug"] == SLUG)
        detail = client.get(f"/api/alerts/{fire['id']}").json()
        age = {row["label"]: row for row in detail["data_age"]}
        assert set(age) == {"Satellite", "Line fault", "Public report", "Weather (Medicine Lodge airport)"}
        assert age["Satellite"]["last_seen"] == "2026-03-17T19:05:00Z"
        assert age["Line fault"]["source"] == "Ortiz lease line"
        assert "+1555" not in json.dumps(detail)  # the reporter's phone number is not sent out
        suppressed = client.get("/api/alerts").json()["suppressed"]
        assert suppressed["logged_burn"] == 2


def test_old_database_picks_up_new_fixtures_at_startup():
    from fastapi.testclient import TestClient
    from app.main import app
    sample.load_all_now()
    with connect() as conn:  # make it look like a database from before Cottonwood existed
        ids = [r[0] for r in conn.execute("SELECT id FROM events WHERE sample_slug LIKE 'cottonwood%'")]
        for table in ("scores", "detections", "signals", "actions"):
            conn.executemany(f"DELETE FROM {table} WHERE event_id = ?", [(i,) for i in ids])
        conn.execute("DELETE FROM burns")
        conn.executemany("DELETE FROM events WHERE id = ?", [(i,) for i in ids])
    assert not sample.sample_is_current()
    with TestClient(app) as client:
        slugs = {a["sample_slug"] for a in client.get("/api/alerts").json()["alerts"]}
        assert "cottonwood-creek" in slugs
    assert sample.sample_is_current()


def _fire_score_and_labels(conn):
    ev = _event(conn, SLUG)
    return ev["score"], _reasons(conn, ev["id"])[1], ev


def _add_burn(conn, start, end):
    from app.pipeline import add_burn
    add_burn(conn, 37.30, -99.80, start, end, "2026-03-10T15:00:00Z", "Someone", "Test burn", is_sample=True)


def test_burn_on_another_day_leaves_the_fire_score_alone(scenario):
    _add_burn(scenario, "2026-03-10T16:00:00Z", "2026-03-10T21:00:00Z")
    score, labels, _ = _fire_score_and_labels(scenario)
    assert score == 88
    assert "No burn has been called in near here" in labels


def test_burn_in_a_non_overlapping_window_same_day_leaves_score_alone(scenario):
    _add_burn(scenario, "2026-03-17T14:00:00Z", "2026-03-17T16:00:00Z")  # 9 to 11 am local, long before 1:50
    score, labels, _ = _fire_score_and_labels(scenario)
    assert score == 88 and "No burn has been called in near here" in labels


def test_burn_with_an_overlapping_window_still_removes_the_reason(scenario):
    _add_burn(scenario, "2026-03-17T18:00:00Z", "2026-03-17T22:00:00Z")
    score, labels, ev = _fire_score_and_labels(scenario)
    assert "No burn has been called in near here" not in labels
    # the fire is growing 2x across looks, so the burn does not hold it: it escapes with the call-the-burner reason
    assert any("growing past it" in x for x in labels) and score == 95


def test_sample_burns_still_score_zero_monitor(scenario):
    for slug in ("cottonwood-creek-henderson", "cottonwood-creek-ortiz-burn"):
        ev = _event(scenario, slug)
        assert ev["score"] == 0 and ev["recommendation"] == "monitor"
