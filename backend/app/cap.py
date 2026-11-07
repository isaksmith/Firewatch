"""CAP 1.2 export (OASIS Common Alerting Protocol) for one alert. Built with ElementTree so text is always escaped.

Status is "Exercise" for scenario, replay and sample events (is_sample) and "Actual" for live ones.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .db import parse_iso
from .district import load_district

NS = "urn:oasis:names:tc:emergency:cap:1.2"
CENTRAL = ZoneInfo("America/Chicago")
# level -> (urgency, severity, certainty)
LEVELS = {
    "escalate": ("Immediate", "Severe", "Likely"),
    "investigate": ("Expected", "Moderate", "Possible"),
    "monitor": ("Future", "Minor", "Unlikely"),
}
MAX_POINTS = 60
CIRCLE_KM = 1.0


def _sub(parent, tag, text=None):
    el = ET.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        el.text = str(text)
    return el


def ring_from_multipolygon(coords: list) -> list[list[float]] | None:
    """The biggest outer ring of a GeoJSON MultiPolygon's coordinates ([lon, lat] pairs), thinned and closed."""
    rings = [p[0] for p in coords if p and p[0]]
    if not rings:
        return None
    ring = max(rings, key=len)
    pts = ring[:: max(1, len(ring) // MAX_POINTS)]
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    return pts


def to_cap(alert: dict, area_ring: list | None = None, now: datetime | None = None) -> str:
    """A CAP 1.2 alert as XML. `alert` is the dict GET /api/alerts/{id} returns; `area_ring` is an optional
    [lon, lat] outline (the 60-minute forecast); the area always has a circle on the fire."""
    ET.register_namespace("", NS)
    try:
        d = load_district()
        sender, org = f"firewatch@{d.slug}.example", d.settings.get("name", "the fire district")
    except FileNotFoundError:
        sender, org = "firewatch@example.invalid", "the fire district"
    sent = now or (parse_iso(alert["last_seen"]) if alert.get("last_seen") else datetime.now(timezone.utc))
    sent = sent.astimezone(CENTRAL)
    level = alert.get("recommendation") or "monitor"
    urgency, severity, certainty = LEVELS.get(level, LEVELS["monitor"])
    place = alert.get("place_label") or "the district"
    reasons = [r["label"] for r in alert.get("reasons", []) if r.get("label")]
    if alert.get("level_reason"):
        reasons.insert(0, alert["level_reason"])

    root = ET.Element(f"{{{NS}}}alert")
    _sub(root, "identifier", f"firewatch-{alert['id']}-{sent.strftime('%Y%m%dT%H%M%S')}")
    _sub(root, "sender", sender)
    _sub(root, "sent", sent.isoformat(timespec="seconds"))
    _sub(root, "status", "Exercise" if alert.get("is_sample") else "Actual")
    _sub(root, "msgType", "Alert")
    _sub(root, "scope", "Public")
    info = _sub(root, "info")
    _sub(info, "language", "en-US")
    _sub(info, "category", "Fire")
    _sub(info, "event", "Grass fire")
    _sub(info, "urgency", urgency)
    _sub(info, "severity", severity)
    _sub(info, "certainty", certainty)
    _sub(info, "senderName", f"Firewatch for {org}")
    score = alert.get("score")
    _sub(info, "headline", f"Grass fire near {place}" + (f" (score {score} of 100)" if score is not None else ""))
    _sub(info, "description", f"Satellite and line data point to a grass fire near {place}. "
         + ("Why: " + "; ".join(reasons) + "." if reasons else "Reasons are not available yet."))
    _sub(info, "instruction", "Stay away from the fire area. Move livestock and vehicles out of the path if it is safe. "
         "Follow directions from the fire district and the sheriff.")
    area = _sub(info, "area")
    _sub(area, "areaDesc", f"Fire near {place}" + (", with its forecast 60-minute path" if area_ring else ""))
    if area_ring:
        _sub(area, "polygon", " ".join(f"{lat:.5f},{lon:.5f}" for lon, lat in area_ring))  # CAP wants lat,lon
    _sub(area, "circle", f"{alert['lat']:.5f},{alert['lon']:.5f} {CIRCLE_KM}")
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
