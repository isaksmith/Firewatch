import asyncio
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

T0 = parse_iso("2026-03-17T18:50:00Z")
FIRE = (37.3821, -99.4681)
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
def radio(monkeypatch):
    r = FakeRadio()
    with connect() as conn:
        sync_roster(conn)
        conn.execute("UPDATE contacts SET mesh_id = ? WHERE phone = ?", (mesh.node_id(DUTY_RADIO), DUTY))
        conn.execute("UPDATE contacts SET mesh_id = ? WHERE phone = ?", (mesh.node_id(SAM_RADIO), SAM))
    monkeypatch.setattr(mesh, "TX_GAP_S", 0)
    bridge = mesh.MeshBridge(r)
    bridge.spawn = lambda fn, *args: fn(*args)
    mesh.set_bridge(bridge)
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


def test_channel_chatter_is_not_parsed(radio):
    with connect() as conn:
        for chatter in ("no idea, heading in", "fire looks bigger from here", "page me later"):
            assert mesh.handle_packet(conn, _packet(DUTY_RADIO, "TEXT_MESSAGE_APP", to=0xFFFFFFFF, text=chatter), GATEWAY) is None
        other_channel = {**_packet(DUTY_RADIO, "TEXT_MESSAGE_APP", to=0xFFFFFFFF, text="PAGE"), "channel": 1}
        assert mesh.handle_packet(conn, other_channel, GATEWAY) is None
        assert not conn.execute("SELECT 1 FROM messages WHERE direction = 'in'").fetchone()
    assert radio.sent == []


def test_page_from_the_channel_and_texts_copied_to_it(radio):
    with connect() as conn:
        eid = _escalated_event(conn)
        posts = [s["text"] for s in radio.sent if s["to"] == mesh.BROADCAST_ID]
        assert any(p.startswith("FIREWATCH FIRE") for p in posts), "the duty officer's alert is on the channel too"
        radio.sent.clear()
        pkt = {**_packet(DUTY_RADIO, "TEXT_MESSAGE_APP", text="Page"), "to": mesh.BROADCAST}
        assert mesh.handle_packet(conn, pkt, GATEWAY) == "channel_text"
        state = notify._state(conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone())
        assert state["decision"] == "page" and state["decision_by"] == "Lt. Ana Reyes (duty officer)"
    dms = [s for s in radio.sent if s["to"] != mesh.BROADCAST_ID]
    posts = [s["text"] for s in radio.sent if s["to"] == mesh.BROADCAST_ID]
    assert any("Paged." in s["text"] and s["to"] == mesh.node_id(DUTY_RADIO) for s in dms)
    assert "Firewatch: Paged. Dispatch and crews notified." in posts
    assert len(posts) == len(set(posts)), "the same text to several radios is posted once"


def test_fire_report_from_a_radio_uses_its_gps(radio):
    where = (37.4244, -99.509)
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
    dm = [s for s in radio.sent if s["to"] != mesh.BROADCAST_ID][-1]
    assert dm["to"] == mesh.node_id(STRANGER) and "report received" in dm["text"]


def test_stale_position_does_not_locate_a_report(radio):
    with connect() as conn:
        mesh.handle_packet(conn, _position(STRANGER, 37.4121, -99.5079), GATEWAY)
        conn.execute("UPDATE mesh_nodes SET position_at = ?", (iso(utcnow() - timedelta(hours=2)),))
        assert mesh.live_position(conn, mesh.node_id(STRANGER)) is None
        r = notify.handle_inbound(conn, mesh.node_id(STRANGER), "FIRE", utcnow(), channel="mesh")
    assert r["action"] == "report_unlocated"


def test_alert_lists_crew_positions(radio):
    with connect() as conn:
        eid = _escalated_event(conn)
        mesh.handle_packet(conn, _position(SAM_RADIO, 37.4121, -99.4283), GATEWAY)
    crew = TestClient(app).get(f"/api/alerts/{eid}").json()["response"]["crew"]
    assert [c["name"] for c in crew] == ["Sam Ortiz"]
    assert crew[0]["mi"] > 0 and crew[0]["from_fire"]


def _replay_with_radio(monkeypatch, reply: str | None, timeout_s: float) -> dict:
    from app import scenario

    real_sync = scenario.sync_roster

    def sync(conn, district=None):
        real_sync(conn, district)
        conn.execute("UPDATE contacts SET mesh_id = ? WHERE phone = ?", (mesh.node_id(DUTY_RADIO), DUTY))

    monkeypatch.setattr(scenario, "sync_roster", sync)
    monkeypatch.setattr(scenario, "LIVE_REPLY_TIMEOUT_S", timeout_s)
    monkeypatch.setattr(scenario, "LIVE_REPLY_POLL_S", 0.02)
    seen: dict = {}

    async def run():
        task = asyncio.create_task(scenario._replay("cottonwood-creek", 0))
        while "waiting" not in scenario._clock:
            assert not task.done(), "the replay never held for the radio"
            await asyncio.sleep(0.01)
        seen["waiting"] = dict(scenario._clock["waiting"])
        seen["t_min"] = scenario._clock["t_min"]
        if reply:
            def answer():
                with connect() as conn:
                    mesh.handle_packet(conn, _packet(DUTY_RADIO, "TEXT_MESSAGE_APP", text=reply), GATEWAY)

            await asyncio.to_thread(answer)
        await task

    asyncio.run(run())
    seen["status"] = scenario.status("cottonwood-creek")
    with connect() as conn:
        seen["pages_in"] = [dict(r) for r in conn.execute(
            "SELECT phone, channel FROM messages WHERE direction = 'in' AND upper(body) = 'PAGE'"
        )]
    return seen


def test_replay_holds_for_the_duty_officer_radio(radio, monkeypatch):
    seen = _replay_with_radio(monkeypatch, reply="PAGE", timeout_s=30)
    assert seen["t_min"] == 9 and seen["waiting"]["name"].startswith("Lt. Ana Reyes")
    assert seen["waiting"]["mesh_id"] == mesh.node_id(DUTY_RADIO)
    assert seen["pages_in"] == [{"phone": mesh.node_id(DUTY_RADIO), "channel": "mesh"}], "the script's PAGE was skipped"
    page = next(m for m in seen["status"]["firewatch"] if m["key"] == "page")
    assert page["t"] == 9, "the clock held, so the page lands on the scenario's timeline"
    assert seen["status"]["waiting"] is None


def test_replay_plays_the_script_if_nobody_answers(radio, monkeypatch):
    seen = _replay_with_radio(monkeypatch, reply=None, timeout_s=0.1)
    assert seen["pages_in"] == [{"phone": DUTY, "channel": "sms"}]
    assert next(m for m in seen["status"]["firewatch"] if m["key"] == "page")["t"] == 9


def test_no_radio_plugged_in_is_mesh_down_not_exit(monkeypatch):
    import meshtastic.util

    monkeypatch.setenv("MESH_GATEWAY", "serial")
    monkeypatch.setenv("MESH_DEVICE", "")
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(meshtastic.util, "findPorts", lambda *_: [])
    assert mesh.start() is False
    h = mesh.health()
    assert h["status"] == "down" and "no Meshtastic radio" in h["last_error"]


def _report(conn, text, num=DUTY_RADIO):
    return mesh.handle_packet(conn, {**_packet(num, "TEXT_MESSAGE_APP", to=0xFFFFFFFF, text=text), "channel": 0}, GATEWAY)


def test_phone_fire_report_with_coordinates_uses_them(radio):
    with connect() as conn:
        mesh.handle_packet(conn, _position(DUTY_RADIO, 37.30, -99.30), GATEWAY)  # node position is elsewhere
        assert _report(conn, "FIRE 37.3821,-99.4681") == "channel_text"
        s = conn.execute("SELECT lat, lon, kind FROM signals ORDER BY id DESC LIMIT 1").fetchone()
        assert (s["kind"], s["lat"], s["lon"]) == ("report", 37.3821, -99.4681)


def test_phone_fire_report_without_coordinates_uses_node_position(radio):
    with connect() as conn:
        mesh.handle_packet(conn, _position(DUTY_RADIO, 37.30, -99.30), GATEWAY)
        assert _report(conn, "FIRE smoke by the road") == "channel_text"
        s = conn.execute("SELECT lat, lon FROM signals ORDER BY id DESC LIMIT 1").fetchone()
        assert (s["lat"], s["lon"]) == (37.30, -99.30)


@pytest.mark.parametrize("where", ["40.0001,-80.5", "0.0,0.0"])
def test_phone_fire_report_outside_the_box_is_rejected(radio, where):
    with connect() as conn:
        mesh.handle_packet(conn, _position(DUTY_RADIO, 37.30, -99.30), GATEWAY)
        assert _report(conn, f"FIRE {where}") == "channel_text"
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0
        reply = conn.execute("SELECT body, channel FROM messages WHERE direction = 'out' AND purpose = 'reply'").fetchone()
        assert reply["channel"] == "mesh" and "outside the district" in reply["body"]
    assert any("outside the district" in s["text"] for s in radio.sent)


def test_fw1_code_goes_to_the_channel_once_per_change(radio):
    from app import fw1
    with connect() as conn:
        eid = _escalated_event(conn)
        codes = [r["code"] for r in conn.execute("SELECT code FROM fw1_feed WHERE event_id = ? ORDER BY seq", (eid,))]
        assert codes and all(fw1.decode(c, (37.2689, -99.3268))["id"] == eid for c in codes)
        posts = [s["text"] for s in radio.sent if s["to"] == mesh.BROADCAST_ID and s["text"].startswith("FW1.")]
        assert posts == codes, "each change is posted once, as the bare code"
        assert all(len(p.encode()) <= mesh.MESH_MAX_BYTES for p in posts)
        rows = conn.execute("SELECT body, channel, is_sample FROM messages WHERE purpose = 'fw1'").fetchall()
        assert [r["body"] for r in rows] == codes and {r["channel"] for r in rows} == {"mesh"} and rows[0]["is_sample"] == 1
        evaluate_event(conn, eid, WEATHER, T0 + timedelta(minutes=9))  # nothing changed: nothing new
        assert conn.execute("SELECT COUNT(*) FROM fw1_feed").fetchone()[0] == len(codes)
