"""Meshtastic LoRa bridge (docs/DESIGN.md section 5.7).

One radio attached to the server talks to the radios volunteers and trucks carry (SenseCAP T1000-E). Alerts go out
as acknowledged direct messages alongside the SMS, replies come back through the same parser as texts, and GPS
positions put people on the map where the roster has no address. None of it needs a cell bar, only LoRa range to
the server's radio or a relay.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

from . import sensors
from .config import get_settings
from .db import connect, iso, parse_iso, utcnow
from .geo import KM_PER_MILE, bearing_deg, compass, haversine_km

log = logging.getLogger(__name__)
MESH_MAX_BYTES = 200
POSITION_FRESH = timedelta(minutes=30)
QUIET_MIN = 15
ACK_RETRY_S = 2.0
ACK_RETRIES = 3

_bridge: "MeshBridge | None" = None
_error: str | None = None


def node_id(num: int) -> str:
    return f"!{num:08x}"


class MeshBridge:
    """A connected meshtastic interface (serial or TCP). Tests pass a fake with `sendText` and `myInfo`."""

    name = "mesh"

    def __init__(self, iface):
        self.iface = iface
        info = getattr(iface, "myInfo", None)
        self.my_num: int | None = info.my_node_num if info else None
        self.connected = True
        self.last_packet_at: str | None = None
        self._lock = threading.Lock()

    @property
    def node_id(self) -> str | None:
        return node_id(self.my_num) if self.my_num is not None else None

    def send(self, to: str, body: str) -> str:
        raw = body.encode()
        if len(raw) > MESH_MAX_BYTES:
            body = raw[:MESH_MAX_BYTES].decode(errors="ignore")
        with self._lock:
            pkt = self.iface.sendText(body, destinationId=to, wantAck=True, channelIndex=get_settings().mesh_channel_index)
        return f"mesh-{pkt.id}"

    # pubsub listeners: the signature must match what meshtastic publishes, and every bridge hears every
    # interface's topics, so each ignores interfaces that aren't its own (an old one closing after a reconnect).
    def on_receive(self, packet, interface) -> None:
        if interface is self.iface:
            self.last_packet_at = iso(utcnow())
            self._handle(packet, 0)

    def on_lost(self, interface) -> None:
        if interface is self.iface:
            self.connected = False
            log.warning("mesh radio disconnected")

    def _handle(self, packet: dict, attempt: int) -> None:
        try:
            with connect() as conn:
                kind = handle_packet(conn, packet, self.my_num)
        except Exception:
            log.exception("mesh packet from %s failed", packet.get("fromId"))
            return
        if kind == "ack_unmatched" and attempt < ACK_RETRIES:
            # The ACK can beat the commit of the message it acknowledges; look again shortly.
            threading.Timer(ACK_RETRY_S, self._handle, (packet, attempt + 1)).start()

    def close(self) -> None:
        try:
            self.iface.close()
        except Exception:
            pass


def get_bridge() -> MeshBridge | None:
    b = _bridge
    return b if b is not None and b.connected else None


def set_bridge(bridge: MeshBridge | None) -> None:
    global _bridge
    _bridge = bridge


# --- packets ---------------------------------------------------------------------------------------------


def handle_packet(conn, packet: dict, my_num: int | None) -> str | None:
    """Record one packet from the radio. Returns its kind: text, position, nodeinfo, telemetry, ack, or None."""
    num = packet.get("from")
    decoded = packet.get("decoded")
    if num is None or not decoded:
        return None  # encrypted on a channel this radio doesn't have
    nid = packet.get("fromId") or node_id(num)
    _touch(conn, nid, packet.get("rxSnr"))
    port = decoded.get("portnum")
    if port == "POSITION_APP":
        p = decoded.get("position") or {}
        lat = p.get("latitude", p.get("latitudeI", 0) * 1e-7)
        lon = p.get("longitude", p.get("longitudeI", 0) * 1e-7)
        if lat or lon:  # 0,0 means no GPS fix
            conn.execute(
                "UPDATE mesh_nodes SET lat = ?, lon = ?, position_at = ? WHERE node_id = ?",
                (round(lat, 6), round(lon, 6), iso(utcnow()), nid),
            )
        return "position"
    if port == "NODEINFO_APP":
        u = decoded.get("user") or {}
        conn.execute(
            "UPDATE mesh_nodes SET long_name = ?, short_name = ?, hw_model = ? WHERE node_id = ?",
            (u.get("longName"), u.get("shortName"), u.get("hwModel"), nid),
        )
        return "nodeinfo"
    if port == "TELEMETRY_APP":
        t = decoded.get("telemetry") or {}
        m = t.get("deviceMetrics") or {}
        if "batteryLevel" in m:
            conn.execute("UPDATE mesh_nodes SET battery_pct = ? WHERE node_id = ?", (min(int(m["batteryLevel"]), 100), nid))
        sensors.record(conn, nid, t)
        return "telemetry"
    if port == "ROUTING_APP" and decoded.get("requestId") is not None:
        return _ack(conn, decoded, num, my_num)
    if port == "TEXT_MESSAGE_APP" and num != my_num and packet.get("to") == my_num:
        text = decoded.get("text")
        if text is None:
            text = bytes(decoded.get("payload") or b"").decode(errors="ignore")
        _inbound(conn, nid, text)
        return "text"
    return None


def _touch(conn, nid: str, snr: float | None) -> None:
    conn.execute(
        "INSERT INTO mesh_nodes(node_id, snr, last_heard) VALUES (?, ?, ?) "
        "ON CONFLICT(node_id) DO UPDATE SET snr = COALESCE(excluded.snr, mesh_nodes.snr), last_heard = excluded.last_heard",
        (nid, snr, iso(utcnow())),
    )


def _ack(conn, decoded: dict, from_num: int, my_num: int | None) -> str:
    reason = (decoded.get("routing") or {}).get("errorReason", "NONE")
    if reason != "NONE":
        status = "failed"
    elif from_num == my_num:
        status = "relayed"  # implicit ACK: another radio rebroadcast it, the recipient hasn't confirmed
    else:
        status = "delivered"
    # Only the recipient can say delivered. An ack from any other radio is a rebroadcast at best.
    cur = conn.execute(
        "UPDATE messages SET status = CASE WHEN ? = 'delivered' AND lower(phone) != lower(?) THEN 'relayed' ELSE ? END "
        "WHERE gateway_id = ? AND channel = 'mesh' AND status != 'delivered'",
        (status, node_id(from_num), status, f"mesh-{decoded['requestId']}"),
    )
    if cur.rowcount:
        return "ack"
    known = conn.execute("SELECT 1 FROM messages WHERE gateway_id = ?", (f"mesh-{decoded['requestId']}",)).fetchone()
    return "ack" if known else "ack_unmatched"


def _inbound(conn, nid: str, text: str) -> None:
    from . import notify, scenario

    replay_now = scenario.running_now()
    notify.handle_inbound(
        conn, nid, text, replay_now or utcnow(),
        is_sample=replay_now is not None or get_settings().mode == "sample",
        channel="mesh", at=live_position(conn, nid),
    )


# --- positions -------------------------------------------------------------------------------------------


def live_position(conn, nid: str | None) -> tuple[float, float] | None:
    """The radio's last GPS fix, if it is recent enough to stand for where the person is now."""
    if not nid:
        return None
    r = conn.execute("SELECT lat, lon, position_at FROM mesh_nodes WHERE node_id = ?", (nid,)).fetchone()
    if r is None or r["lat"] is None or not r["position_at"]:
        return None
    if utcnow() - parse_iso(r["position_at"]) > POSITION_FRESH:
        return None
    return r["lat"], r["lon"]


def crew_positions(conn, lat: float, lon: float) -> list[dict]:
    """Roster contacts whose radios have a fresh fix, nearest the fire first."""
    out = []
    for r in conn.execute(
        "SELECT c.id, c.name, c.role, n.lat, n.lon, n.position_at FROM contacts c "
        "JOIN mesh_nodes n ON n.node_id = c.mesh_id WHERE n.lat IS NOT NULL AND n.position_at IS NOT NULL"
    ):
        age = utcnow() - parse_iso(r["position_at"])
        if age > POSITION_FRESH:
            continue
        km = haversine_km(lat, lon, r["lat"], r["lon"])
        out.append({
            "contact_id": r["id"], "name": r["name"], "role": r["role"], "lat": r["lat"], "lon": r["lon"],
            "mi": round(km / KM_PER_MILE, 1), "from_fire": compass(bearing_deg(lat, lon, r["lat"], r["lon"])),
            "position_min_ago": round(age.total_seconds() / 60),
        })
    return sorted(out, key=lambda c: c["mi"])


def list_nodes(conn) -> list[dict]:
    me = _bridge.node_id if _bridge else None
    now = utcnow()
    out = []
    for r in conn.execute(
        "SELECT n.*, c.id AS contact_id, c.name AS contact_name, c.role AS contact_role "
        "FROM mesh_nodes n LEFT JOIN contacts c ON c.mesh_id = n.node_id ORDER BY n.last_heard DESC"
    ):
        d = dict(r)
        d["is_gateway"] = r["node_id"] == me
        d["heard_min_ago"] = round((now - parse_iso(r["last_heard"])).total_seconds() / 60)
        d["position_min_ago"] = (
            round((now - parse_iso(r["position_at"])).total_seconds() / 60) if r["position_at"] else None
        )
        d["sensors"] = sensors.latest_readings(conn, r["node_id"]) or None
        out.append(d)
    return out


def _seed_nodes(conn, iface) -> int:
    """Copy the radio's own node database, so the map has positions before anyone transmits again."""
    n = 0
    for nid, node in (getattr(iface, "nodes", None) or {}).items():
        heard = node.get("lastHeard")
        if not heard:
            continue
        at = iso(datetime.fromtimestamp(heard, tz=timezone.utc))
        u, p = node.get("user") or {}, node.get("position") or {}
        lat, lon = p.get("latitude"), p.get("longitude")
        conn.execute(
            "INSERT INTO mesh_nodes(node_id, long_name, short_name, hw_model, lat, lon, position_at, battery_pct, snr, last_heard) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(node_id) DO UPDATE SET "
            "long_name = excluded.long_name, short_name = excluded.short_name, hw_model = excluded.hw_model, "
            "lat = COALESCE(excluded.lat, mesh_nodes.lat), lon = COALESCE(excluded.lon, mesh_nodes.lon), "
            "position_at = COALESCE(excluded.position_at, mesh_nodes.position_at), "
            "battery_pct = COALESCE(excluded.battery_pct, mesh_nodes.battery_pct), snr = excluded.snr, "
            "last_heard = MAX(excluded.last_heard, mesh_nodes.last_heard)",
            (
                nid.lower(), u.get("longName"), u.get("shortName"), u.get("hwModel"),
                lat if lat or lon else None, lon if lat or lon else None, at if lat or lon else None,
                (node.get("deviceMetrics") or {}).get("batteryLevel"), node.get("snr"), at,
            ),
        )
        n += 1
    return n


# --- lifecycle -------------------------------------------------------------------------------------------


def _open_interface():
    s = get_settings()
    if s.mesh_gateway == "tcp":
        from meshtastic.tcp_interface import TCPInterface

        return TCPInterface(hostname=s.mesh_device or "meshtastic.local")
    from meshtastic.serial_interface import SerialInterface
    from meshtastic.util import findPorts

    port = s.mesh_device or None
    if port is None:
        # SerialInterface calls sys.exit when it finds zero or several ports, so pick one here.
        ports = findPorts(True)
        if not ports:
            raise RuntimeError("no Meshtastic radio on USB")
        port = ports[0]
    return SerialInterface(devPath=port)


def start() -> bool:
    """Connect the server's radio. Blocks a few seconds while the radio sends its node database."""
    global _error
    s = get_settings()
    if s.mesh_gateway not in ("serial", "tcp"):
        return False
    from pubsub import pub

    old = _bridge
    if old is not None:
        old.close()
    try:
        iface = _open_interface()
    except (Exception, SystemExit) as e:
        if str(e) != _error:
            log.warning("mesh radio unavailable: %s", e)
        _error = str(e)
        set_bridge(None)
        return False
    bridge = MeshBridge(iface)
    pub.subscribe(bridge.on_receive, "meshtastic.receive")
    pub.subscribe(bridge.on_lost, "meshtastic.connection.lost")
    with connect() as conn:
        n = _seed_nodes(conn, iface)
    set_bridge(bridge)
    _error = None
    log.info("mesh radio %s connected; %d nodes in its database", bridge.node_id, n)
    return True


def stop() -> None:
    if _bridge is not None:
        _bridge.close()
    set_bridge(None)


def health() -> dict | None:
    """Same shape as the other sources in /api/health; None when the mesh is off."""
    if get_settings().mesh_gateway not in ("serial", "tcp"):
        return None
    b = get_bridge()
    if b is None:
        return {"status": "down", "age_min": None, "last_ok": None, "last_error": _error or "radio disconnected"}
    age = None if b.last_packet_at is None else round((utcnow() - parse_iso(b.last_packet_at)).total_seconds() / 60)
    return {
        "status": "ok" if age is not None and age < QUIET_MIN else "stale",
        "age_min": age,
        "last_ok": b.last_packet_at,
        "last_error": None if age is not None else "connected; nothing heard yet",
        "node_id": b.node_id,
    }
