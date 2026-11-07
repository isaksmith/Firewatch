"""NWS active alerts at a point: is a Red Flag Warning in effect? https://www.weather.gov/documentation/services-web-api"""

from datetime import datetime, timezone

import httpx

ALERTS_URL = "https://api.weather.gov/alerts/active"
USER_AGENT = "Firewatch hackathon demo (github.com/isaksmith/Firewatch)"
EVENT = "Red Flag Warning"


def parse_alerts(payload: dict, fetched_at: str) -> dict:
    """Turn an NWS alerts GeoJSON payload into the red-flag status record."""
    feats = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(feats, list) or not all(
        isinstance(f, dict) and isinstance(f.get("properties"), dict) for f in feats
    ):
        raise RuntimeError("NWS: malformed response")
    flags = [f["properties"] for f in feats if f["properties"].get("event") == EVENT]
    if not flags:
        return {"red_flag": False, "headline": None, "expires": None, "fetched_at": fetched_at}
    p = flags[0]
    return {
        "red_flag": True,
        "headline": p.get("headline"),
        "expires": p.get("expires") or p.get("ends"),
        "fetched_at": fetched_at,
    }


def red_flag_at(lat: float, lon: float) -> dict:
    """Return {red_flag, headline, expires, fetched_at}. Raises RuntimeError on any failure:
    the caller decides how to show the gap. A failure is never reported as red_flag False."""
    try:
        resp = httpx.get(
            ALERTS_URL,
            params={"point": f"{lat:.4f},{lon:.4f}"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"NWS alerts: HTTP {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise RuntimeError(f"NWS alerts: {type(e).__name__}") from None
    except ValueError:
        raise RuntimeError("NWS alerts: unreadable response") from None
    return parse_alerts(payload, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
