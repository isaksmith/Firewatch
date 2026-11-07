"""Iowa Mesonet local storm reports (NWS LSR): https://mesonet.agron.iastate.edu/geojson/lsr.php"""

import re
from datetime import datetime, timedelta, timezone

from .feedlib import get_json, in_bbox, run_feed

URL = "https://mesonet.agron.iastate.edu/geojson/lsr.php"
WINDOW_H = 72
FIRE_RE = re.compile(r"wild\s?fire|grass\s?fire|brush\s?fire|\bfire\b|smoke|burn", re.I)
LINE_RE = re.compile(r"(power|utility|electric)[\s-]*(pole|line)|downed\s+(power|line|pole)|wires?\s+down|lines?\s+down", re.I)


def parse(payload: dict) -> dict:
    reports, total = [], 0
    for f in (payload or {}).get("features") or []:
        p = f.get("properties") or {}
        lon, lat = p.get("lon"), p.get("lat")
        if lon is None or lat is None or not in_bbox(lon, lat):
            continue
        total += 1
        text = f"{p.get('typetext') or ''} {p.get('remark') or ''}"
        fire, line = bool(FIRE_RE.search(text)), bool(LINE_RE.search(text))
        if not (fire or line):
            continue
        reports.append({
            "time": p.get("valid"), "type": p.get("typetext"), "remark": p.get("remark"),
            "city": p.get("city"), "county": p.get("county"), "lat": lat, "lon": lon,
            "fire": fire, "downed_line": line,
        })
    return {"count": len(reports), "total_reports": total, "window_h": WINDOW_H, "reports": reports}


def poll() -> dict:
    now = datetime.now(timezone.utc)
    params = {
        "sts": (now - timedelta(hours=WINDOW_H)).strftime("%Y-%m-%dT%H:%MZ"),
        "ets": now.strftime("%Y-%m-%dT%H:%MZ"),
        "wfo": "ALL", "state": "KS",
    }
    return run_feed("lsr", parse(get_json(URL, params)))
