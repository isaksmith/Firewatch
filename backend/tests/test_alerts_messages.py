from app.alerts import messages
from app.alerts.common import scenario

BAD = set("^{}[]|\\\u20ac")  # "~" allowed: scenario text uses it, costs 2 septets


def ev(**kw):
    sc = scenario()["ignition"]
    base = {"id": 1, "lat": sc["lat"], "lon": sc["lon"], "score": 87, "recommendation": "escalate",
            "heading": "N", "speed_mph": 3, "next_crossing": {"name": "CR 14", "time": "2:29"}, "red_flag": True}
    return {**base, **kw}


def gsm_safe(s):
    return all(32 <= ord(c) < 127 and c not in BAD for c in s)


def test_chief_matches_scenario():
    assert messages.chief_text(ev()) == (
        "FIRE 87/100 Rd K half mi S of CR 12, 11mi NW of station. Head going N ~3mph. CR 14 by 2:29. Reply 1=on it 2=not a fire")


def test_chief_limits_and_charset():
    t = messages.chief_text(ev(), lambda a, b: "A very long road description " * 6)
    assert messages.septets(t) <= 160 and gsm_safe(t) and t.endswith("Reply 1=on it 2=not a fire")


def test_chief_from_wind_features():
    e = ev(heading=None, speed_mph=None, features={"wind_kmh": 56, "wind_dir_deg": 180, "temp_c": 25, "rh_pct": 11, "curing_pct": 95})
    t = messages.chief_text(e)
    assert "Head going N" in t and len(t) <= 160


def test_landowner_matches_scenario():
    miller = next(p for p in scenario()["places"] if p["id"] == "miller-house")
    t = messages.landowner_text(miller, "2:49", ev())
    assert t == miller["sms"]
    assert len(t) <= 160 and gsm_safe(t)


def test_quiet_notice_matches_scenario():
    t = messages.quiet_notice(ev())
    assert t == ("Possible fire: power-line fault near Rd K and CR 12 on a red flag day. "
                 "No smoke seen yet. We'll page if the satellite confirms.")
    assert gsm_safe(t)


def test_curly_quotes_are_replaced():
    assert gsm_safe(messages._ascii("it’s “fine” — ok"))
