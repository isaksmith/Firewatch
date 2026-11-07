"""FIRMS LANDSAT_NRT detections (30 m, US and Canada). Context feed only: never enters
process_detections, because the model was trained on VIIRS and MODIS only.
Needs the free FIRMS map key. UNTESTED LIVE: written against the documented CSV."""

import csv
import io

from ..config import get_settings
from .feedlib import run_feed
from .firms import AREA_URL, fetch_text


def parse(text: str) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text or "")):
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, ValueError, TypeError):
            continue
        out.append({"lat": lat, "lon": lon, "acq_date": row.get("acq_date"), "acq_time": row.get("acq_time"),
                    "satellite": row.get("satellite"), "confidence": row.get("confidence")})
    return out


def poll() -> dict:
    s = get_settings()
    if not s.firms_map_key:
        raise RuntimeError("FIRMS_MAP_KEY not set")
    w, so, e, n = s.bbox_tuple
    url = AREA_URL.format(key=s.firms_map_key, source="LANDSAT_NRT", bbox=f"{w},{so},{e},{n}", days=s.firms_days)
    text = fetch_text(url, "LANDSAT_NRT")
    if "latitude" not in text[:300] and text.strip():
        raise ValueError(text.strip()[:120])  # FIRMS returns plain-text errors with HTTP 200
    pts = parse(text)
    return run_feed("landsat_nrt", {"count": len(pts), "points": pts})
