"""CAP 1.2 export (OASIS Common Alerting Protocol). Built with ElementTree so text is always escaped."""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ..db import parse_iso
from .common import local_tz, scenario
from .inpath import clock_now, footprint

NS = "urn:oasis:names:tc:emergency:cap:1.2"
SENDER = "firewatch@cottonwood-creek.example"
# recommendation -> (urgency, severity, certainty)
LEVELS = {
    "escalate": ("Immediate", "Severe", "Likely"),
    "investigate": ("Expected", "Moderate", "Possible"),
    "monitor": ("Future", "Minor", "Unlikely"),
}
MAX_POINTS = 60


def _sub(parent, tag, text=None):
    el = ET.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        el.text = str(text)
    return el


def _ring(feature: dict | None) -> list[list[float]] | None:
    if not feature:
        return None
    rings = [p[0] for p in feature["geometry"]["coordinates"]]
    ring = max(rings, key=len)
    step = max(1, len(ring) // MAX_POINTS)
    pts = ring[::step]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def to_cap(event: dict, now: datetime | None = None, area_polygon: list | None = None) -> str:
    """Return a CAP 1.2 alert as an XML string. Sample events are marked Exercise."""
    ET.register_namespace("", NS)
    tz = local_tz()
    sent = now or (parse_iso(event["last_seen"]) if event.get("last_seen") else datetime.now(timezone.utc))
    sent = sent.astimezone(tz)
    rec = event.get("recommendation") or "monitor"
    urgency, severity, certainty = LEVELS.get(rec, LEVELS["monitor"])
    place = event.get("place_label") or scenario()["district"]
    reasons = [r.get("label") for r in event.get("reasons", []) if r.get("label")]

    alert = ET.Element(f"{{{NS}}}alert")
    _sub(alert, "identifier", f"firewatch-{event['id']}-{sent.strftime('%Y%m%dT%H%M%S')}")
    _sub(alert, "sender", SENDER)
    _sub(alert, "sent", sent.isoformat(timespec="seconds"))
    _sub(alert, "status", "Exercise" if event.get("is_sample") else "Actual")
    _sub(alert, "msgType", "Alert")
    _sub(alert, "scope", "Public")
    info = _sub(alert, "info")
    _sub(info, "language", "en-US")
    _sub(info, "category", "Fire")
    _sub(info, "event", "Grass fire")
    _sub(info, "urgency", urgency)
    _sub(info, "severity", severity)
    _sub(info, "certainty", certainty)
    _sub(info, "senderName", "Firewatch for Cottonwood Creek Fire District")
    _sub(info, "headline", f"Grass fire near {place} (score {event.get('score', 0)} of 100)")
    desc = f"Satellite and line data point to a grass fire near {place}. "
    desc += "Why: " + "; ".join(reasons) + "." if reasons else "Reasons are not available yet."
    _sub(info, "description", desc)
    _sub(info, "instruction",
         "Stay away from the fire area. Move livestock and vehicles out of the path if it is safe. "
         "Follow directions from the fire district and the sheriff.")
    area = _sub(info, "area")
    _sub(area, "areaDesc", f"Forecast 60-minute path of the fire near {place}")
    ring = area_polygon or _ring(footprint(event, 60, clock_now(event)))
    if ring:
        _sub(area, "polygon", " ".join(f"{lat:.5f},{lon:.5f}" for lon, lat in ring))
    _sub(area, "circle", f"{event['lat']:.5f},{event['lon']:.5f} 1.0")
    ET.indent(alert)
    return ET.tostring(alert, encoding="unicode", xml_declaration=False).join(
        ['<?xml version="1.0" encoding="UTF-8"?>\n', "\n"])
