from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import mesh, notify
from app.confirm import evaluate_event
from app.db import connect, iso, parse_iso, utcnow
from app.district import sync_roster
from app.main import app
from app.signals import add_signal

T0 = parse_iso("2026-03-14T18:50:00Z")
FIRE = (37.77, -96.66)
WEATHER = {"wind_kmh": 26, "gust_kmh": 45, "wind_dir_deg": 200, "rh_pct": 18, "temp_c": 24, "precip_72h_mm": 0, "thunder_24h": 0}
DUTY, WES, SAM = "+13165550101", "+13165550131", "+13165550111"
GATEWAY, DUTY_RADIO, SAM_RADIO, STRANGER = 0x0A0A0A0A, 0x0000BEEF, 0x0000CAFE, 0x00ABCDEF


class FakeRadio:
    def __init__(self):
        self.myInfo = SimpleNamespace(my_node_num=GATEWAY)
        self.sent: list[dict] = []
        self.nodes = {}

    def sendText(self, text, destinationId, wantAck, channelIndex):
        self.sent.append({"text": text, "to": destinationId, "want_ack": wantAck})
        return SimpleNamespace(id=1000 + len(self.sent))

    def close(self):
        pass


@pytest.fixture
def radio():
    r = FakeRadio()
    with connect() as conn:
        sync_roster(conn)
        conn.execute("UPDATE contacts SET mesh_id = ? WHERE phone = ?", (mesh.node_id(DUTY_RADIO), DUTY))
        conn.execute("UPDATE contacts SET mesh_id = ? WHERE phone = ?", (mesh.node_id(SAM_RADIO), SAM))
    mesh.set_bridge(mesh.MeshBridge(r))
    yield r
    mesh.set_bridge(None)


def _packet(num: int, port: str, to: int = GATEWAY, **decoded) -> dict:
    return {"from": num, "to": to, "fromId": mesh.node_id(num), "rxSnr": 5.5, "decoded": {"portnum": port, **decoded}}


def _position(num: int, lat: float, lon: float) -> dict:
    return _packet(num, "POSITION_APP", to=0xFFFFFFFF, position={"latitude": lat, "longitude": lon})


def _escalated_event(conn) -> int:
    eid = add_signal(conn, "line_fault", *FIRE, iso(T0), "coop:feeder-4", "lockout", is_sample=True)
    evaluate_event(conn, eid, WEATHER, T0)
    notify.handle_inbound(conn, WES, "1", T0 + timedelta(minutes=8), is_sample=True)
    assert conn.execute("SELECT recommendation FROM events WHERE id = ?", (eid,)).fetchone()[0] == "escalate"
    return eid


def test_alerts_go_out_by_sms_and_mesh_with_ack(radio):
    with connect() as conn:
        eid = _escalated_event(conn)
        rows = conn.execute(
            "SELECT channel, phone, status, gateway_id FROM messages WHERE event_id = ? AND purpose = 'duty_escalate'", (eid,)
        ).fetchall()
    assert {r["channel"] for r in rows} == {"sms", "mesh"}
    sent = [s for s in radio.sent if s["text"].startswith("FIREWATCH FIRE")]
    assert sent and sent[0]["to"] == mesh.node_id(DUTY_RADIO) and sent[0]["want_ack"]

    gid = next(r["gateway_id"] for r in rows if r["channel"] == "mesh")
    req = int(gid.removeprefix("mesh-"))
    with connect() as conn:
        assert mesh.handle_packet(conn, _packet(GATEWAY, "ROUTING_APP", requestId=req, routing={}), GATEWAY) == "ack"
        assert conn.execute("SELECT status FROM messages WHERE gateway_id = ?", (gid,)).fetchone()[0] == "relayed"
        mesh.handle_packet(conn, _packet(DUTY_RADIO, "ROUTING_APP", requestId=req, routing={"errorReason": "NONE"}), GATEWAY)
        assert conn.execute("SELECT status FROM messages WHERE gateway_id = ?", (gid,)).fetchone()[0] == "delivered"
        mesh.handle_packet(conn, _packet(DUTY_RADIO, "ROUTING_APP", requestId=req, routing={"errorReason": "MAX_RETRANSMIT"}), GATEWAY)
        assert conn.execute("SELECT status FROM messages WHERE gateway_id = ?", (gid,)).fetchone()[0] == "delivered"
        assert mesh.handle_packet(conn, _packet(DUTY_RADIO, "ROUTING_APP", requestId=1, routing={}), GATEWAY) == "ack_unmatched"


def test_page_by_radio_reply(radio):
    with connect() as conn:
        eid = _escalated_event(conn)
        radio.sent.clear()
        assert mesh.handle_packet(conn, _packet(DUTY_RADIO, "TEXT_MESSAGE_APP", text="page"), GATEWAY) == "text"
        state = notify._state(conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone())
        assert state["decision"] == "page" and state["decision_by"] == "Lt. Ana Reyes (duty officer)"
        reply = conn.execute("SELECT channel FROM messages WHERE purpose = 'reply' ORDER BY id DESC").fetchall()
        assert [r["channel"] for r in reply][:1] == ["mesh"], "a radio reply is answered on the radio only"
        assert any(s["to"] == mesh.node_id(SAM_RADIO) and s["text"].startswith("FIRE ") for s in radio.sent), "volunteer page over mesh"


def test_broadcast_chatter_is_not_parsed(radio):
    with connect() as conn:
        assert mesh.handle_packet(conn, _packet(DUTY_RADIO, "TEXT_MESSAGE_APP", to=0xFFFFFFFF, text="PAGE"), GATEWAY) is None
        assert not conn.execute("SELECT 1 FROM messages WHERE direction = 'in'").fetchone()


def test_fire_report_from_a_radio_uses_its_gps(radio):
    where = (37.8123, -96.7011)
    with connect() as conn:
        mesh.handle_packet(conn, _position(STRANGER, *where), GATEWAY)
        mesh.handle_packet(conn, _packet(STRANGER, "NODEINFO_APP", to=0xFFFFFFFF,
                                         user={"longName": "Lease truck 3", "shortName": "LT3", "hwModel": "TRACKER_T1000_E"}), GATEWAY)
        mesh.handle_packet(conn, _packet(STRANGER, "TEXT_MESSAGE_APP", text="FIRE smoke north of the tank battery"), GATEWAY)
        sig = conn.execute("SELECT * FROM signals WHERE kind = 'report'").fetchone()
        assert (sig["lat"], sig["lon"]) == where and sig["contact_id"] is None
        assert sig["source"] == f"mesh:{mesh.node_id(STRANGER)}"
        ev = conn.execute("SELECT recommendation FROM events WHERE id = ?", (sig["event_id"],)).fetchone()
        assert ev["recommendation"] == "investigate", "an unregistered radio can't escalate alone"
        node = next(n for n in mesh.list_nodes(conn) if n["node_id"] == mesh.node_id(STRANGER))
        assert node["long_name"] == "Lease truck 3" and node["contact_id"] is None
    assert radio.sent[-1]["to"] == mesh.node_id(STRANGER) and "report received" in radio.sent[-1]["text"]


def test_stale_position_does_not_locate_a_report(radio):
    with connect() as conn:
        mesh.handle_packet(conn, _position(STRANGER, 37.8, -96.7), GATEWAY)
        conn.execute("UPDATE mesh_nodes SET position_at = ?", (iso(utcnow() - timedelta(hours=2)),))
        assert mesh.live_position(conn, mesh.node_id(STRANGER)) is None
        r = notify.handle_inbound(conn, mesh.node_id(STRANGER), "FIRE", utcnow(), channel="mesh")
    assert r["action"] == "report_unlocated"


def test_alert_lists_crew_positions(radio):
    with connect() as conn:
        eid = _escalated_event(conn)
        mesh.handle_packet(conn, _position(SAM_RADIO, 37.80, -96.62), GATEWAY)
    crew = TestClient(app).get(f"/api/alerts/{eid}").json()["response"]["crew"]
    assert [c["name"] for c in crew] == ["Sam Ortiz"]
    assert crew[0]["mi"] > 0 and crew[0]["from_fire"]


def test_no_radio_plugged_in_is_mesh_down_not_exit(monkeypatch):
    import meshtastic.util

    monkeypatch.setenv("MESH_GATEWAY", "serial")
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(meshtastic.util, "findPorts", lambda *_: [])
    assert mesh.start() is False
    h = mesh.health()
    assert h["status"] == "down" and "no Meshtastic radio" in h["last_error"]
