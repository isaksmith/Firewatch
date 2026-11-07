import asyncio

from app.config import Settings, get_settings
from app.db import connect
from app.main import _source_loop
from app.pipeline import insert_detections


def _det(source, lat, lon, acq="2026-11-06T18:30:00Z", frp=5.0):
    return {"source": source, "satellite": "N", "lat": lat, "lon": lon, "acq_time": acq,
            "brightness_k": 330.0, "frp_mw": frp, "confidence": 80.0, "scan_km": 0.4,
            "track_km": 0.4, "daynight": "D"}


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]


def test_rt_then_processed_does_not_double_count():
    with connect() as conn:
        assert len(insert_detections(conn, [_det("VIIRS_SNPP_RT", 38.5000, -98.7000)])) == 1
        # processed row, coordinates shifted by about 100 m, different source name
        insert_detections(conn, [_det("VIIRS_SNPP_NRT", 38.5008, -98.7006, frp=6.0)])
        assert count(conn) == 1
        row = conn.execute("SELECT source, lat, frp_mw FROM detections").fetchone()
        assert row["source"] == "VIIRS_SNPP_NRT" and abs(row["lat"] - 38.5008) < 1e-9 and row["frp_mw"] == 6.0
        # a later standard-product row for the same pixel also does not add a row
        insert_detections(conn, [_det("VIIRS_SNPP_SP", 38.5008, -98.7006)])
        assert count(conn) == 1


def test_processed_then_rt_is_dropped_and_other_sensors_kept():
    with connect() as conn:
        insert_detections(conn, [_det("VIIRS_SNPP_NRT", 38.5, -98.7)])
        insert_detections(conn, [_det("VIIRS_SNPP_RT", 38.5004, -98.7003)])
        assert count(conn) == 1
        # different sensor, same place and time, is a real second detection
        insert_detections(conn, [_det("VIIRS_NOAA20_NRT", 38.5, -98.7)])
        # nearby but distinct pixel of the same sensor is kept
        insert_detections(conn, [_det("VIIRS_SNPP_NRT", 38.51, -98.7)])
        assert count(conn) == 3


def test_intervals_and_legacy_poll_minutes(monkeypatch):
    monkeypatch.delenv("POLL_MINUTES", raising=False)
    s = Settings(_env_file=None)
    assert s.source_intervals["firms"] == 60
    assert s.nws_user_agent == "firewatch-hackathon" and "@" not in s.nws_user_agent
    monkeypatch.setenv("POLL_MINUTES", "5")
    get_settings.cache_clear()
    assert Settings(_env_file=None).source_intervals["firms"] == 300


def test_failing_source_is_isolated_and_recorded():
    calls = {"good": 0}

    def bad():
        raise RuntimeError("boom")

    def good():
        calls["good"] += 1
        return "ok"

    async def run():
        tasks = [asyncio.create_task(_source_loop("bad_src", 0.01, bad)),
                 asyncio.create_task(_source_loop("good_src", 0.01, good))]
        await asyncio.sleep(0.15)
        for t in tasks:
            t.cancel()
        assert not any(t.done() and not t.cancelled() for t in tasks)

    asyncio.run(run())
    assert calls["good"] >= 2
    with connect() as conn:
        r = conn.execute("SELECT last_error FROM source_health WHERE source = 'bad_src'").fetchone()
    assert r and "boom" in r["last_error"]
