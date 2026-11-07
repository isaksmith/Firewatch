"""Meshtastic LoRa bridge (docs/DESIGN.md section 5.7).

One radio attached to the server talks to the radios volunteers and trucks carry (SenseCAP T1000-E). Alerts go out
as acknowledged direct messages alongside the SMS, replies come back through the same parser as texts, and GPS
positions put people on the map where the roster has no address. None of it needs a cell bar, only LoRa range to
the server's radio or a relay.
"""

import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from . import sensors
from .config import get_settings
from .db import connect, iso, parse_iso, utcnow
from .geo import KM_PER_MILE, bearing_deg, compass, haversine_km

log = logging.getLogger(__name__)
MESH_MAX_BYTES = 233  # meshtastic 2.7.11 DATA_PAYLOAD_LEN: the radio refuses a longer text payload
OPEN_TIMEOUT_S = 15.0  # no radio found must be a clear error this soon, not a hang
POSITION_PAD_KM = 40.0  # inbound GPS fixes must fall inside the district box padded by this much
POSITION_FRESH = timedelta(minutes=30)
QUIET_MIN = 15
ACK_RETRY_S = 2.0
ACK_RETRIES = 3
BROADCAST = 0xFFFFFFFF
BROADCAST_ID = "^all"
FEED_REPEAT_S = 60
TX_GAP_S = 2.0
# The channel is also people talking ("no idea", "fire looks bigger"), so there a reply word must be the whole
# message, and FIRE/BURN/JOIN with details must be typed in capitals.
CHANNEL_REPLIES = {"PAGE", "NO", "SEND", "R", "STOP", "START", "1", "2", "3", "FIRE", "BURN", "JOIN"}
CHANNEL_REPORTS = ("FIRE", "BURN", "JOIN")

_bridge: "MeshBridge | None" = None
_error: str | None = None


def node_id(num: int) -> str:
    return f"!{num:08x}"


def _fit(body: str) -> str:
    """At most MESH_MAX_BYTES of UTF-8, cut on a character boundary (never mid-character)."""
    raw = body.encode()
    if len(raw) <= MESH_MAX_BYTES:
        return body
    cut = MESH_MAX_BYTES
    while cut > 0 and (raw[cut] & 0xC0) == 0x80:  # raw[cut] is a continuation byte: step back to the lead byte
        cut -= 1
    return raw[:cut].decode()


def _district_box() -> tuple[float, float, float, float] | None:
    """(south, west, north, east) of the district boundary padded by POSITION_PAD_KM; None if there is no district."""
    from .district import load_district
    from .geo import KM_PER_DEG_LAT, km_per_deg_lon

    try:
        pts = [p for ring in load_district().rings for p in ring]
    except FileNotFoundError:
        return None
    if not pts:
        return None
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    mid = (min(lats) + max(lats)) / 2
    dlat, dlon = POSITION_PAD_KM / KM_PER_DEG_LAT, POSITION_PAD_KM / km_per_deg_lon(mid)
    return min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon


def plausible_position(lat, lon) -> bool:
    """A usable GPS fix: real numbers, not 0,0 (no fix), and inside the padded district box."""
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    if lat != lat or lon != lon or (lat == 0 and lon == 0):
        return False
    box = _district_box()
    if box is None:
        return abs(lat) <= 90 and abs(lon) <= 180
    s, w, n, e = box
    return s <= lat <= n and w <= lon <= e


def _is_keyword(text: str) -> bool:
    words = re.findall(r"[A-Za-z0-9]+", text)
    if len(words) == 1:
        return words[0].upper() in CHANNEL_REPLIES
    return bool(words) and words[0] in CHANNEL_REPORTS


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
        self._next_tx = 0.0
        self._posted_lock = threading.Lock()
        self._posted: dict[str, float] = {}
        self.spawn = lambda fn, *args: threading.Thread(target=fn, args=args, daemon=True).start()

    @property
    def node_id(self) -> str | None:
        return node_id(self.my_num) if self.my_num is not None else None

    def send(self, to: str, body: str) -> str:
        body = _fit(body)
        pkt = self._transmit(body, to, want_ack=True)
        if get_settings().mesh_channel_feed:
            self.spawn(self._post_quietly, body)
        return f"mesh-{pkt.id}"

    def post(self, body: str) -> None:
        """Broadcast on the district channel, once per text per minute (a page goes to many radios at once)."""
        body = _fit(body)
        now = time.monotonic()
        with self._posted_lock:
            self._posted = {b: t for b, t in self._posted.items() if now - t < FEED_REPEAT_S}
            if body in self._posted:
                return
            self._posted[body] = now
        # want_ack on a broadcast makes the radio resend it until it hears a neighbour repeat it.
        pkt = self._transmit(body, BROADCAST_ID, want_ack=True)
        log.info("mesh channel post %s: %s", pkt.id, body[:40])

    def _post_quietly(self, body: str) -> None:
        try:
            self.post(body)
        except Exception as e:
            log.warning("mesh channel post failed: %s", e)

    def _transmit(self, body: str, to: str, want_ack: bool):
        # The T1000-E drops a packet handed to it within about a second of the previous one.
        with self._lock:
            wait = self._next_tx - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                return self.iface.sendText(body, destinationId=to, wantAck=want_ack, channelIndex=get_settings().mesh_channel_index)
            finally:
                self._next_tx = time.monotonic() + TX_GAP_S

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
        if plausible_position(lat, lon):  # 0,0 means no GPS fix; a fix far outside the district is a bad one
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
    if port == "TEXT_MESSAGE_APP" and num != my_num:
        text = decoded.get("text")
        if text is None:
            text = bytes(decoded.get("payload") or b"").decode(errors="ignore")
        if packet.get("to") == my_num:
            _inbound(conn, nid, text)
            return "text"
        on_our_channel = packet.get("channel", 0) == get_settings().mesh_channel_index
        if packet.get("to") == BROADCAST and on_our_channel and _is_keyword(text):
            _inbound(conn, nid, text)
            return "channel_text"
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
    cur = conn.execute(
        "UPDATE messages SET status = ? WHERE gateway_id = ? AND channel = 'mesh' AND status != 'delivered'",
        (status, f"mesh-{decoded['requestId']}"),
    )
    if cur.rowcount:
        return "ack"
    known = conn.execute("SELECT 1 FROM messages WHERE gateway_id = ?", (f"mesh-{decoded['requestId']}",)).fetchone()
    return "ack" if known else "ack_unmatched"


COORDS = re.compile(r"(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)")
BAD_POSITION_REPLY = "Firewatch: that position is outside the district, so I did not use it. Send FIRE alone to use your radio's last position."


def report_position(text: str) -> tuple[tuple[float, float] | None, str, bool]:
    """For a FIRE/BURN/JOIN text with a "lat,lon" in it: (position or None, the text without it, saw_coordinates).
    The phone app sends `FIRE 37.3821,-99.4681` after its position fix. A position outside the district box (or 0,0)
    is not used."""
    words = re.findall(r"[A-Za-z0-9]+", text)
    m = COORDS.search(text)
    if not words or words[0].upper() not in CHANNEL_REPORTS or not m:
        return None, text, False
    lat, lon = float(m.group(1)), float(m.group(2))
    rest = (text[: m.start()] + " " + text[m.end():]).strip()
    return ((lat, lon) if plausible_position(lat, lon) else None), rest, True


def _inbound(conn, nid: str, text: str) -> None:
    from . import notify, scenario

    replay_now = scenario.running_now()
    now = replay_now or utcnow()
    sample = replay_now is not None or get_settings().mode == "sample"
    at, text_out, saw = report_position(text)
    if saw and at is None:
        # Bad coordinates: say so plainly and do not guess. The message is still logged.
        contact = conn.execute("SELECT * FROM contacts WHERE phone = ? OR mesh_id = ?", (nid, nid)).fetchone()
        conn.execute(
            "INSERT INTO messages(event_id, contact_id, phone, direction, purpose, body, status, is_sample, created_at, channel) "
            "VALUES (NULL, ?, ?, 'in', NULL, ?, 'received', ?, ?, 'mesh')",
            (contact["id"] if contact else None, nid, text, int(sample), iso(now)),
        )
        target = contact or {"id": None, "phone": nid, "name": nid, "opted_in": 1, "mesh_id": nid}
        notify.send(conn, target, BAD_POSITION_REPLY, "reply", None, now, sample, channels=("mesh",))
        return
    notify.handle_inbound(
        conn, nid, text_out, now, is_sample=sample, channel="mesh", at=at or live_position(conn, nid),
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
        if not plausible_position(lat, lon):
            lat = lon = None
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
                lat, lon, at if lat is not None else None,
                (node.get("deviceMetrics") or {}).get("batteryLevel"), node.get("snr"), at,
            ),
        )
        n += 1
    return n


# --- lifecycle -------------------------------------------------------------------------------------------


def _open_interface():
    """Open the radio, or raise within OPEN_TIMEOUT_S. meshtastic 2.7.11 returns an unconnected interface when
    a serial device is missing, and a TCP host that does not answer can hang, so both run on a worker thread."""
    box: dict = {}

    def work():
        try:
            box["iface"] = _open_raw()
        except (Exception, SystemExit) as e:
            box["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(OPEN_TIMEOUT_S)
    if t.is_alive():
        raise RuntimeError(f"no Meshtastic radio answered within {OPEN_TIMEOUT_S:g} s")
    if "error" in box:
        raise box["error"]
    iface = box["iface"]
    connected = getattr(iface, "isConnected", None)
    if connected is not None and not connected.is_set():
        try:
            iface.close()
        except Exception:
            pass
        raise RuntimeError("no Meshtastic radio found (the interface did not connect)")
    return iface


def _open_raw():
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
