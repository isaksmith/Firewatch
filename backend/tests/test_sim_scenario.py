from dataclasses import fields

from app.sim.scenario import PARAM_DOCS, Params, fmt, run_firewatch, run_today, sweep


def test_today_defaults_reproduce_packet():
    t = run_today(Params())
    assert fmt(t["page"]) == "2:23 pm"
    assert fmt(t["roll"]) == "2:34 pm"
    assert fmt(t["on_scene"]) == "2:52 pm"
    assert t["fire_age"] == 62


def test_firewatch_defaults_near_targets():
    f = run_firewatch(Params())
    assert abs(f["page"] - 845) <= 1.5  # about 2:05 pm
    assert abs(f["on_scene"] - 874) <= 2  # about 2:34 pm
    assert 42 <= f["fire_age"] <= 46


def test_sweep_size_and_never_later():
    grid = {"fault_telemetry": [True, False], "goes_delay": [5, 10, 20, 30],
            "channel": ["push", "sms", "pager"], "chief_response": [1, 3, 6]}
    res = sweep(grid)
    assert len(res) == 2 * 4 * 3 * 3
    assert all(r["minutes_saved"] >= 0 for r in res)
    assert all(r["firewatch"]["acres"] <= r["today"]["acres"] + 1e-9 for r in res)


def test_worst_case_saves_nothing():
    res = sweep({"fault_telemetry": [False], "goes_delay": [30]})
    assert res[0]["minutes_saved"] == 0


def test_params_documented():
    assert {f.name for f in fields(Params)} <= set(PARAM_DOCS)
    assert all(len(v) > 10 for v in PARAM_DOCS.values())
