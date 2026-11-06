from app import sample
from app.db import connect


def test_every_fixture_produces_its_expected_recommendation():
    sample.load_all_now()
    expected = {fx["slug"]: fx["expected"] for fx in sample.load_fixtures()}
    with connect() as conn:
        rows = conn.execute("SELECT sample_slug, recommendation FROM events").fetchall()
    got = {r["sample_slug"]: r["recommendation"] for r in rows}
    assert len(rows) == len(expected), "each fixture should cluster into exactly one event"
    assert got == expected
