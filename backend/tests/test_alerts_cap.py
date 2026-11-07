import xml.etree.ElementTree as ET

from app.alerts.cap import NS, to_cap
from app.alerts.common import scenario
from app.db import connect

N = {"c": NS}


def seed(is_sample=1, rec="escalate"):
    ig = scenario()["ignition"]
    with connect() as conn:
        conn.execute(
            "INSERT INTO events(id, lat, lon, first_seen, last_seen, place_label, is_sample, score, recommendation, updated_at, features_json) "
            "VALUES (1, ?, ?, '2026-03-17T18:50:00Z', '2026-03-17T19:05:00Z', 'Rd K & <CR 12>', ?, 87, ?, '2026-03-17T19:05:00Z', ?)",
            (ig["lat"], ig["lon"], is_sample, rec,
             '{"wind_kmh": 56.3, "wind_dir_deg": 180, "temp_c": 25.5, "rh_pct": 11, "curing_pct": 95}'))
        conn.execute("INSERT INTO scores(event_id, scored_at, score, recommendation, scorer, reasons_json) VALUES (1,'x',87,?,'rules',"
                     "'[{\"label\": \"Line fault & red flag\", \"contribution\": 5}]')", (rec,))


def event(**kw):
    from app.alerts.common import load_event
    seed(**kw)
    return load_event(1)


def test_cap_parses_with_required_elements():
    root = ET.fromstring(to_cap(event()))
    assert root.tag == f"{{{NS}}}alert"
    g = lambda p: root.find(p, N).text
    for tag in ("identifier", "sender", "sent", "status", "msgType", "scope"):
        assert g(f"c:{tag}")
    assert g("c:status") == "Exercise" and g("c:msgType") == "Alert" and g("c:scope") == "Public"
    assert g("c:sent").endswith("-05:00")
    assert g("c:info/c:category") == "Fire" and g("c:info/c:event") == "Grass fire"
    assert (g("c:info/c:urgency"), g("c:info/c:severity"), g("c:info/c:certainty")) == ("Immediate", "Severe", "Likely")
    assert "Line fault & red flag" in g("c:info/c:description")
    assert g("c:info/c:instruction")
    area = root.find("c:info/c:area", N)
    assert area.find("c:circle", N).text.endswith(" 1.0")
    poly = area.find("c:polygon", N).text.split()
    assert len(poly) >= 4 and poly[0] == poly[-1]


def test_actual_when_not_sample_and_text_escaped():
    xml = to_cap(event(is_sample=0, rec="monitor"))
    assert "&lt;CR 12&gt;" in xml
    root = ET.fromstring(xml)
    assert root.find("c:status", N).text == "Actual"
    assert root.find("c:info/c:severity", N).text == "Minor"
