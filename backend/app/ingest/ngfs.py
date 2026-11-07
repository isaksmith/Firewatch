"""NOAA NGFS (Next Generation Fire System) detections, a context feed.

Public OGC API, no key. GOES-East and GOES-West rows are kept apart and labeled by
satellite. Context only: rows never go through process_detections, so they cannot
reach the model, the 27 features, gfdi or scoring. The model trained on VIIRS and
MODIS only. NOAA labels this service beta, informational only.

Three traps handled here:
1. The API sits behind CloudFront with max-age=3600, so an identical URL returns a
   stale body. The datetime window is rebuilt every poll, END truncated to the minute.
2. Without a datetime the API returns only about the last hour, so one is always sent.
3. Results are paged: when numberMatched exceeds numberReturned, follow rel=next (max 5 pages).
"""

import logging
from datetime import datetime, timedelta, timezone

from ..config import get_settings
from .feedlib import get_json, in_bbox, run_feed

log = logging.getLogger(__name__)

BASE = "https://fire.data.nesdis.noaa.gov/api/ogc/detections"
COLLECTIONS = tuple(
    f"ngfs_schema.ngfs_detections_{s}"
    for s in ("scene_east_conus", "east_mesoscale1", "east_mesoscale2",
              "west_conus", "west_mesoscale1", "west_mesoscale2")
)
WINDOW_HOURS = 6
MAX_PAGES = 5
LIMIT = 1000
KEEP = ("acq_date_time", "satellite", "scan_domain", "confidence", "frp", "type", "type_description",
        "state", "county", "known_incident_name", "feature_tracking_id", "feature_detection_duration",
        "land_cover", "quality_flag", "daynight")
NOTICE = "NOAA beta, informational only. Data may be delayed or unavailable. Not for operational decisions."


def window(now: datetime | None = None) -> str:
    """START/END for the last 6 hours, UTC, END truncated to the minute so the URL changes every poll."""
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(hours=WINDOW_HOURS)
    f = "%Y-%m-%dT%H:%M:%SZ"
    return f"{start.strftime(f)}/{end.strftime(f)}"


def parse(payload: dict) -> list[dict]:
    """Rows inside the AOI, keeping only the context fields."""
    out = []
    for feat in payload.get("features") or []:
        p = feat.get("properties") or {}
        lon, lat = p.get("longitude"), p.get("latitude")
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or not in_bbox(lon, lat):
            continue
        out.append({"lon": round(lon, 5), "lat": round(lat, 5), **{k: p.get(k) for k in KEEP}})
    return out


def _next_href(payload: dict) -> str | None:
    for link in payload.get("links") or []:
        if link.get("rel") == "next" and link.get("href"):
            return link["href"]
    return None


def fetch_collection(cid: str, dt: str) -> list[dict]:
    w, s, e, n = get_settings().bbox_tuple
    url = f"{BASE}/collections/{cid}/items"
    params = {"f": "json", "limit": LIMIT, "bbox": f"{w},{s},{e},{n}", "datetime": dt, "sortby": "-acq_date_time"}
    rows: list[dict] = []
    for _ in range(MAX_PAGES):
        payload = get_json(url, params)
        rows += parse(payload)
        nxt = _next_href(payload)
        if not nxt or not payload.get("numberMatched", 0) > payload.get("numberReturned", 0):
            break
        url, params = nxt, None  # the next link carries its own query
    else:
        log.warning("ngfs %s hit the %d page cap", cid, MAX_PAGES)
    return rows


def snapshot(points: list[dict], collections: list[dict], dt: str) -> dict:
    newest = max((p["acq_date_time"] for p in points if p.get("acq_date_time")), default=None)
    return {
        "count": len(points),
        "tracked_features": len({p["feature_tracking_id"] for p in points if p.get("feature_tracking_id")}),
        "wildland_count": sum(p.get("type_description") == "Possible Wildland Fire" for p in points),
        "industrial_count": sum(p.get("type_description") == "Industrial" for p in points),
        "newest_acq": newest,
        "window": dt,
        "notice": NOTICE,
        "collections": collections,
        "points": points,
    }


def fetch(now: datetime | None = None) -> dict:
    dt = window(now)
    points: list[dict] = []
    cols = []
    for cid in COLLECTIONS:
        short = cid.removeprefix("ngfs_schema.ngfs_detections_")
        try:
            rows = fetch_collection(cid, dt)
            points += rows
            cols.append({"collection": short, "count": len(rows)})
        except Exception as e:  # one sector down must not blank the others; empty mesoscale is normal
            log.warning("ngfs %s failed: %s", short, e)
            cols.append({"collection": short, "error": str(e)[:120]})
    if all("error" in c for c in cols):
        raise RuntimeError("; ".join(f"{c['collection']}: {c['error']}" for c in cols))
    return snapshot(points, cols, dt)


def poll() -> dict:
    return run_feed("ngfs", fetch())
