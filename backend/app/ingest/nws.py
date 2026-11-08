"""NWS active alerts for Kansas: https://api.weather.gov/alerts/active?area=KS (public domain)."""

from .feedlib import get_json, run_feed

URL = "https://api.weather.gov/alerts/active"
EVENTS = {
    "Fire Warning", "Extreme Fire Danger", "Evacuation - Immediate", "Red Flag Warning",
    "Fire Weather Watch", "High Wind Warning", "High Wind Watch", "Extreme Wind Warning",
    "Dust Storm Warning", "Dense Smoke Advisory", "Wind Advisory",
}


def parse(payload: dict) -> dict:
    alerts = []
    for f in (payload or {}).get("features") or []:
        p = f.get("properties") or {}
        if p.get("event") not in EVENTS:
            continue
        alerts.append({
            "id": p.get("id") or f.get("id"),
            "event": p["event"],
            "severity": p.get("severity"),
            "headline": p.get("headline"),
            "area": p.get("areaDesc"),
            "onset": p.get("onset") or p.get("effective"),
            "expires": p.get("expires") or p.get("ends"),
            "geometry": f.get("geometry"),  # can be null: NWS gives zones instead
        })
    return {"count": len(alerts), "alerts": alerts}


def poll() -> dict:
    return run_feed("nws_alerts", parse(get_json(URL, {"area": "KS"})))
