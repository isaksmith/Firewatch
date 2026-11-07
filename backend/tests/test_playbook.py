from fastapi.testclient import TestClient

from app import decision, scenario
from app.db import connect
from app.main import app


def _fire_at(minute: int) -> int:
    scenario.run_now("cottonwood-creek", until=minute)
    return scenario.status("cottonwood-creek")["events"][0]["id"]


# --- the model itself ---

def test_probability_multiplies_odds_from_the_first_signal():
    w = decision.weights({})
    line = {"kind": "line_fault", "label": "Power line lockout", "counts": "yes", "at": "2026-03-17T18:50:00Z"}
    smoke = {"kind": "neighbor_reply", "label": "Wes: sees smoke", "counts": "yes", "at": "2026-03-17T18:58:00Z"}
    base = w["line_fault_base_rate"] * decision.danger_factor("Extreme", w)  # fitted or hand-set, whichever is active
    p0 = decision.probability([line], "Extreme", w)["p"]
    assert abs(p0 - base) < 0.005
    p1 = decision.probability([smoke, line], "Extreme", w)  # order in the list doesn't matter, time does
    assert p1["steps"][0]["text"].startswith("Power line lockout")
    odds = base / (1 - base) * w["lr_neighbor_smoke"]
    assert abs(p1["p"] - odds / (1 + odds)) < 0.005
    calm = decision.probability([line], "Low-Moderate", w)["p"]
    assert calm <= p0, "a fault on a calm, humid day is no more likely to be a fire"


def test_satellite_score_is_a_likelihood_ratio_on_the_even_prior():
    w = decision.weights({})
    p = decision.probability([], "High", w, sat_score=50)["p"]
    assert abs(p - w["satellite_prior"]) < 0.005, "a score of 50 is no evidence either way"


def test_break_even_is_where_expected_losses_cross():
    page = {"if_fire_loss": 300, "if_not_cost": 100}
    wait = {"if_fire_loss": 900, "if_not_cost": 0}
    x = decision.break_even(page, wait)
    assert abs(decision.expected_loss(x, 300, 100) - decision.expected_loss(x, 900, 0)) < 1e-9


def test_district_settings_override_the_weights():
    w = decision.weights({"decision": {"cost_false_page_acres": 400}})
    assert w["cost_false_page_acres"] == 400 and w["line_fault_base_rate"] == 0.03
    src = {d["key"]: d["source"] for d in decision.described({"decision": {"cost_false_page_acres": 400}})}
    assert src["cost_false_page_acres"] == "District setting"


# --- the playbook over the scenario ---

def test_minute_0_line_fault_recommends_a_heads_up_and_waiting_for_neighbors():
    with TestClient(app) as client:
        eid = _fire_at(0)
        p = client.get(f"/api/alerts/{eid}/options").json()
        w = decision.weights({})
        assert abs(p["probability"]["p"] - w["line_fault_base_rate"] * decision.danger_factor("Extreme", w)) < 0.01
        opts = p["decision"]["options"]
        losses = [o["expected_loss"] for o in opts]
        assert losses == sorted(losses) and opts[0]["recommended"] and not opts[1]["recommended"]
        assert opts[0]["id"] == "heads_up_ask"
        assert "Lowest expected loss" in opts[0]["why"]
        assert any("Mullinville" in e for e in opts[0]["effects"]), "the station north of a south-wind fire is in its path"

        p = client.post(f"/api/alerts/{eid}/options/heads_up_ask", json={"operator": "Dispatch 1"}).json()
        assert p["receipts"][0]["title"].startswith("Warn downwind stations")
        assert p["receipts"][0]["followed_recommendation"] is True
        with connect() as conn:
            to = [r["name"] for r in conn.execute(
                "SELECT c.name FROM messages m JOIN contacts c ON c.id = m.contact_id WHERE m.event_id = ? AND m.purpose = 'heads_up'", (eid,))]
        assert any("Mullinville" in n for n in to)
        assert all("heads_up" not in o["id"] for o in p["decision"]["options"]), "a heads-up is only sent once"
        assert client.post(f"/api/alerts/{eid}/options/mutual_aid_now", json={"operator": "x"}).status_code == 409


def test_minute_8_neighbor_confirms_and_paging_wins():
    with TestClient(app) as client:
        eid = _fire_at(8)
        p = client.get(f"/api/alerts/{eid}/options").json()
        assert p["probability"]["p"] > 0.5
        best = p["decision"]["options"][0]
        assert best["id"] == "page" and "flips if the chance of fire falls below" in best["why"]
        assert not any(o["id"] in ("ask", "heads_up_ask") for o in p["decision"]["options"]), "no waiting to confirm a confirmed fire"


def test_after_the_replay_nothing_waits_and_receipts_say_what_happened():
    with TestClient(app) as client:
        eid = _fire_at(62)
        p = client.get(f"/api/alerts/{eid}/options").json()
        assert p["decision"] is None and p["probability"]["p"] > 0.99
        titles = [r["title"] for r in p["receipts"]]
        assert "Paged the district" in titles and "Requested mutual aid" in titles
        assert {m["key"] for m in p["model"]} >= {"cost_false_page_acres", "line_fault_base_rate"}


def test_weak_detection_on_low_risk_land_does_not_page():
    with TestClient(app) as client:
        client.post("/api/sample/load")
        alerts = client.get("/api/alerts", params={"include_monitor": True}).json()["alerts"]
        humid = next(a for a in alerts if a["sample_slug"] == "synthetic-humid-single")
        p = client.get(f"/api/alerts/{humid['id']}/options").json()
        assert p["probability"]["p"] < 0.2
        assert p["decision"]["options"][0]["id"] != "page"


def test_fitted_multiplier_is_used_and_cited_when_the_model_exists(tmp_path, monkeypatch):
    model = {"version": "fire-day-v1", "reference_band": "High", "data": {"fires_used": 10, "period": ["2016-01-01", "2025-12-31"]},
             "danger_multiplier": {"Low-Moderate": 0.5, "High": 1.0, "Very High": 2.0, "Severe": 4.0, "Extreme": 4.0},
             "bands": {"Extreme": {"large": {"1000": {"k": 3, "n": 10, "p": 0.3, "ci": [0.1, 0.6]}}}}}
    path = tmp_path / "fire_day.json"
    path.write_text(__import__("json").dumps(model))
    monkeypatch.setattr(decision, "FIRE_DAY_PATH", path)
    decision.fire_day_model.cache_clear()
    try:
        w = decision.weights({})
        assert w["danger_multiplier"]["Severe"] == 4.0 and decision.danger_factor("Severe", w) == 4.0 ** w["danger_exponent"]
        src = {d["key"]: d["source"] for d in decision.described({})}["danger_multiplier"]
        assert src.startswith("Fire-day model v1")
        assert decision.large_fire_share("Extreme")["p"] == 0.3
        assert decision.weights({"decision": {"danger_multiplier": {"Extreme": 9}}})["danger_multiplier"] == {"Extreme": 9}
    finally:
        decision.fire_day_model.cache_clear()


def test_tower_smoke_sensor_counts_as_evidence():
    w = decision.weights({})
    line = {"kind": "line_fault", "label": "Power line lockout", "counts": "yes", "at": "2026-03-17T18:50:00Z"}
    tower = {"kind": "sensor_smoke", "label": "Smoke sensor !a1b2c3d4", "counts": "yes", "at": "2026-03-17T18:56:00Z"}
    alone = decision.probability([line], "Extreme", w)["p"]
    both = decision.probability([line, tower], "Extreme", w)
    assert both["p"] > alone and both["steps"][-1]["factor"] == w["lr_sensor_smoke"]
    first = decision.probability([tower], "Extreme", w)  # a sensor as the first signal starts from the generic base rate
    assert first["steps"][0]["p"] == w["other_prior"]


# --- levels: the model can raise a level, never lower one ---

EXTREME = {"wind_kmh": 56, "gust_kmh": 90, "wind_dir_deg": 185, "rh_pct": 11, "temp_c": 25.6, "precip_72h_mm": 0, "thunder_24h": 0}


def _signal(conn, kind, value, phone=None):
    from app.confirm import evaluate_event
    from app.db import iso, parse_iso
    from app.district import sync_roster
    from app.signals import add_signal

    t0 = parse_iso("2026-03-17T18:50:00Z")
    sync_roster(conn)
    contact = conn.execute("SELECT id FROM contacts WHERE phone = ?", (phone,)).fetchone()["id"] if phone else None
    eid = add_signal(conn, kind, 37.3821, -99.4681, iso(t0), f"sms:{phone}" if phone else "coop:feeder-4", value,
                     contact_id=contact, is_sample=True)
    evaluate_event(conn, eid, EXTREME, t0)
    return conn.execute("SELECT recommendation, level_reason FROM events WHERE id = ?", (eid,)).fetchone()


def test_weak_signal_on_an_extreme_day_is_raised_to_investigate():
    """The rules ignore a momentary trip; on an Extreme red-flag day a no-cost heads-up beats watching."""
    with TestClient(app):
        with connect() as conn:
            ev = _signal(conn, "line_fault", "momentary")
            assert ev["recommendation"] == "investigate", ev["level_reason"]
            assert "lowest expected loss" in ev["level_reason"]


def test_one_report_on_an_extreme_day_is_not_raised_to_escalate():
    """P(fire) ~34%: a heads-up and the neighbors' answers beat paging 18 volunteers on one report."""
    with TestClient(app):
        with connect() as conn:
            ev = _signal(conn, "report", "fire", phone="+13165550133")
            assert ev["recommendation"] == "investigate" and "second source" in ev["level_reason"]


def test_two_sources_still_escalate_and_texts_use_the_forecast():
    from app import playbook
    from app.sim.spread import _arrival_many
    import numpy as np

    with TestClient(app):
        eid = _fire_at(62)
        with connect() as conn:
            ev = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
            assert ev["recommendation"] == "escalate"
            state = __import__("json").loads(ev["response_json"])
            plan = state["plan"]
            assert plan["downwind"] and plan["eta_basis"].startswith("earliest plausible")
            f = playbook.Fire(conn, ev, playbook.parse_iso(state["page_at"]))
            for d in plan["downwind"]:
                c = conn.execute("SELECT lat, lon FROM contacts WHERE id = ?", (d["contact_id"],)).fetchone()
                t10 = float(_arrival_many(f.t10, f.dom.lats, f.dom.lons, np.array([c["lat"]]), np.array([c["lon"]]))[0])
                assert abs(d["eta_min"] - max(5, 5 * round((t10 - f.now_min) / 5))) <= 5


def test_building_sites_in_the_path_count_in_the_loss():
    """Waiting 30 min for the next satellite pass lets the scenario fire reach a ranch; that costs cost_site_acres."""
    with TestClient(app):
        eid = _fire_at(0)
        p = client_options = TestClient(app).get(f"/api/alerts/{eid}/options").json()
        recheck = next(o for o in p["decision"]["options"] if o["id"] == "heads_up_recheck")
        fire = next(m["value"] for m in recheck["metrics"] if m["label"] == "If it's a fire")
        assert "building site" in fire
        assert {m["key"] for m in client_options["model"]} >= {"cost_site_acres"}


def test_past_the_911_call_waiting_is_labeled_as_relying_on_911():
    with TestClient(app) as client:
        scenario.run_now("cottonwood-creek-packet-no-fault", until=36)  # no line fault: nothing pages before minute 41
        eid = scenario.status("cottonwood-creek-packet-no-fault")["events"][0]["id"]
        d = client.get(f"/api/alerts/{eid}/options").json()["decision"]
        titles = [o["title"] for o in d["options"]]
        assert "Watch; don't page yet" not in titles, "past the 911 call, 'watch' only ties paging by assuming a call was made"
        assert any(o["id"] in ("watch", "heads_up_only") for o in d["options"]), titles
        for o in d["options"]:
            if o["id"] in ("watch", "heads_up_only"):
                assert "911" in o["title"] and any("county dispatch" in e for e in o["effects"])
