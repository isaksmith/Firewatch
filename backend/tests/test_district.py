import asyncio

import pytest

from app import scenario
from app.district import load_district

SLUG = "cottonwood-creek-packet"


def _override_scenario(monkeypatch, **overrides):
    sc = scenario.load_scenario(SLUG)
    sc = {**sc, "settings": overrides}
    monkeypatch.setattr(scenario, "load_scenario", lambda slug: sc)
    return sc


def test_overrides_are_invisible_outside_the_scenario_context_during_a_replay(monkeypatch):
    base = load_district().settings
    key = "ask_miles" if "ask_miles" in base else next(iter(base))
    marker = "OVERRIDE-MARKER"
    _override_scenario(monkeypatch, **{key: marker})
    seen = {}

    async def run():
        task = asyncio.create_task(scenario._replay(SLUG, 0.05))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if scenario._clock.get("running"):
                break
        # Our own context is not the replay task's: it must not see the override.
        seen["outside"] = load_district().settings[key]
        await task

    asyncio.run(run())
    assert seen["outside"] != marker
    assert load_district().settings[key] != marker


def test_overrides_reach_the_replay_workers(monkeypatch):
    base = load_district().settings
    key = next(iter(base))
    marker = "OVERRIDE-MARKER"
    _override_scenario(monkeypatch, **{key: marker})
    seen = []
    real = scenario._minute

    def spy(conn, sc, t):
        seen.append(load_district().settings[key])
        return real(conn, sc, t)

    monkeypatch.setattr(scenario, "_minute", spy)
    asyncio.run(scenario._replay(SLUG, 0))
    assert seen and all(v == marker for v in seen)


def test_overrides_clear_after_a_replay_that_raises(monkeypatch):
    base = load_district().settings
    key = next(iter(base))
    _override_scenario(monkeypatch, **{key: "OVERRIDE-MARKER"})

    def boom(conn, sc, t):
        raise RuntimeError("boom")

    monkeypatch.setattr(scenario, "_minute", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(scenario._replay(SLUG, 0))
    assert load_district().settings[key] == base[key]
    assert scenario._clock["running"] is False


def test_overrides_clear_after_run_now_raises(monkeypatch):
    base = load_district().settings
    key = next(iter(base))
    _override_scenario(monkeypatch, **{key: "OVERRIDE-MARKER"})
    monkeypatch.setattr(scenario, "_minute", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        scenario.run_now(SLUG)
    assert load_district().settings[key] == base[key]


def test_status_firewatch_agrees_with_replay_minutes_for_ring_on():
    from app.db import connect, loads, parse_iso
    from scripts.replay_minutes import measure

    slug = "cottonwood-creek-packet-ring-on"
    scenario.run_now(slug)
    t0 = parse_iso(scenario.load_scenario(slug)["t0"])
    fw = {m["key"]: m["t"] for m in scenario.status(slug)["firewatch"]}
    inv, esc = [], []
    with connect() as conn:
        for ev in conn.execute("SELECT suppression, response_json FROM events WHERE sample_slug = ?", (slug,)):
            st = loads(ev["response_json"], {}) or {}
            if ev["suppression"] == "registered_burn":
                continue
            for key, out in (("investigate_at", inv), ("escalate_at", esc)):
                if st.get(key):
                    out.append(round((parse_iso(st[key]) - t0).total_seconds() / 60, 1))
    assert fw["investigate"] == min(inv)
    assert fw["escalate"] == min(esc)

    measured = measure(slug)
    assert fw["investigate"] == measured["investigate"]
    assert fw["escalate"] == measured["escalate"]
