"""NOAA NGFS (Next Generation Fire System) detections, a context feed.

Public OGC API, no key. GOES-East and GOES-West rows are kept apart and labeled by
satellite. Rows never go through process_detections, so they cannot reach the model,
the 27 features, gfdi or scoring. The model trained on VIIRS and MODIS only. NOAA labels
this service beta, informational only.

One narrow exception: after each poll, a tracked feature that is labeled "Possible Wildland
Fire", seen in at least two separate scans, and not covered by a registered burn becomes one
`ngfs` signal through add_signal (app/ngfs_signal.py). It counts as the satellite source class,
never as a strong detection, so NGFS alone reaches Investigate and a person decides every page.

Three traps handled here:
1. The API sits behind CloudFront with max-age=3600, so an identical URL returns a
   stale body. The datetime window is rebuilt every poll, END truncated to the minute.
2. Without a datetime the API returns only about the last hour, so one is always sent.
3. Results are paged locally on the fixed BASE with the offset parameter (max 5 pages).
   The response's own next link is never followed (SSRF) and redirects are not followed.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..config import get_settings
from .feedlib import TIMEOUT, client_headers, in_bbox, run_feed

log = logging.getLogger(__name__)

BASE = "https://fire.data.nesdis.noaa.gov/api/ogc/detections"
COLLECTIONS = tuple(
    f"ngfs_schema.ngfs_detections_{s}"
    for s in ("scene_east_conus", "scene_east_mesoscale1", "scene_east_mesoscale2",
              "scene_west_conus", "scene_west_mesoscale1", "scene_west_mesoscale2")
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


def get_json(url: str, params: dict | None = None):
    """Like feedlib.get_json but never follows redirects: this feed only talks to BASE."""
    r = httpx.get(url, params=params, headers=client_headers(), timeout=TIMEOUT, follow_redirects=False)
    r.raise_for_status()
    return r.json()


def fetch_collection(cid: str, dt: str) -> list[dict]:
    """Page on the fixed BASE URL with offset. The response's own next link is never followed."""
    w, s, e, n = get_settings().bbox_tuple
    url = f"{BASE}/collections/{cid}/items"
    params = {"f": "json", "limit": LIMIT, "bbox": f"{w},{s},{e},{n}", "datetime": dt, "sortby": "-acq_date_time"}
    rows: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        payload = get_json(url, {**params, "offset": offset} if offset else params)
        rows += parse(payload)
        returned = payload.get("numberReturned") or len(payload.get("features") or [])
        offset += returned
        if returned < LIMIT or offset >= (payload.get("numberMatched") or 0):
            break
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
        short = cid.removeprefix("ngfs_schema.ngfs_detections_scene_")
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
    result = run_feed("ngfs", fetch())
    try:
        from ..confirm import evaluate_event
        from ..db import connect, load_snapshot, utcnow
        from ..ngfs_signal import add_ngfs_signals

        with connect() as conn:
            snap = load_snapshot(conn, "ngfs")
            if snap:
                for eid in add_ngfs_signals(conn, snap["data"].get("points") or [], utcnow()):
                    evaluate_event(conn, eid)
    except Exception as e:  # a beta feed must never break the poll
        log.warning("ngfs signal step failed: %s", e)
    return result
