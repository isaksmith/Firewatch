"""NASA FIRMS Area API client: https://firms.modaps.eosdis.nasa.gov/api/area/"""

import csv
import io
from datetime import datetime, timezone

import httpx

AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{days}"


def normalize_confidence(raw: str) -> str:
    raw = (raw or "").strip().lower()
    if raw in ("l", "low"):
        return "low"
    if raw in ("h", "high"):
        return "high"
    if raw in ("n", "nominal"):
        return "nominal"
    try:
        value = float(raw)
    except ValueError:
        return "nominal"
    if value < 30:
        return "low"
    return "high" if value >= 80 else "nominal"


def _float(row: dict, *keys: str) -> float | None:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def parse_csv(text: str, source: str) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        if "latitude" not in row:
            continue
        hhmm = row.get("acq_time", "0000").zfill(4)
        acq = datetime.strptime(f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
        out.append({
            "source": source,
            "satellite": row.get("satellite") or source,
            "lat": float(row["latitude"]),
            "lon": float(row["longitude"]),
            "acq_time": acq.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "brightness_k": _float(row, "bright_ti4", "brightness"),
            "frp_mw": _float(row, "frp"),
            "confidence": normalize_confidence(row.get("confidence", "")),
            "scan_km": _float(row, "scan"),
            "track_km": _float(row, "track"),
            "daynight": row.get("daynight") or None,
        })
    return out


def fetch_area(key: str, source: str, bbox: tuple[float, float, float, float], days: int = 1) -> list[dict]:
    url = AREA_URL.format(key=key, source=source, bbox=",".join(str(v) for v in bbox), days=days)
    # The MAP_KEY sits in the URL path, and httpx error strings include the URL,
    # so never let a raw httpx exception escape: it would be logged and stored.
    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"FIRMS {source}: HTTP {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise RuntimeError(f"FIRMS {source}: {type(e).__name__}") from None
    text = resp.text
    if text.lower().startswith("invalid") or "error" in text[:200].lower():
        snippet = text[:200].replace(key, "***") if key else text[:200]
        raise RuntimeError(f"FIRMS error for {source}: {snippet}")
    return parse_csv(text, source)
