"""GOES-19 ABI fire detections (product ABI-L2-FDCC) from NOAA's public S3 bucket. No key needed.

Mask codes (checked against the file's own flag_meanings attribute):
10 good, 11 saturated, 12 cloud contaminated, 13 high prob, 14 medium prob, 15 low prob;
30-35 are the same six categories after temporal filtering.
"""

import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np

BUCKET_URL = "https://noaa-goes19.s3.amazonaws.com"
PRODUCT = "ABI-L2-FDCC"
SOURCE = "GOES19_FDC"
SATELLITE = "G19"
FIRE_CODES = (10, 11, 12, 13, 14, 15, 30, 31, 32, 33, 34, 35)
_CONF = {10: "high", 11: "high", 13: "high", 14: "nominal", 12: "low", 15: "low"}
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_TS = re.compile(r"_s(\d{14})_e(\d{14})_c(\d{14})")


def confidence_from_mask(code: int) -> str:
    code = int(code)
    return _CONF.get(code - 20 if code >= 30 else code, "low")


def parse_goes_time(s: str) -> datetime:
    """GOES filename time: YYYYDDDHHMMSSt (t = tenths of a second)."""
    return datetime.strptime(s[:13], "%Y%j%H%M%S").replace(tzinfo=timezone.utc) + timedelta(seconds=int(s[13]) / 10)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def scan_times(key: str) -> tuple[datetime, datetime]:
    m = _TS.search(key)
    if not m:
        raise RuntimeError("GOES: unexpected file name")
    return parse_goes_time(m.group(1)), parse_goes_time(m.group(2))


def pixel_to_latlon(x, y, proj: dict) -> tuple:
    """Fixed-grid scan angles (radians) to geodetic lat/lon (degrees), per GOES-R PUG vol. 3 section 4.2.8.
    Accepts scalars or numpy arrays. Off-Earth pixels give NaN."""
    req = proj["semi_major_axis"]
    rpol = proj["semi_minor_axis"]
    H = proj["perspective_point_height"] + req
    lon0 = math.radians(proj["longitude_of_projection_origin"])
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    sin_x, cos_x, sin_y, cos_y = np.sin(x), np.cos(x), np.sin(y), np.cos(y)
    ratio = (req ** 2) / (rpol ** 2)
    a = sin_x ** 2 + cos_x ** 2 * (cos_y ** 2 + ratio * sin_y ** 2)
    b = -2.0 * H * cos_x * cos_y
    c = H ** 2 - req ** 2
    disc = b ** 2 - 4.0 * a * c
    with np.errstate(invalid="ignore"):
        rs = (-b - np.sqrt(disc)) / (2.0 * a)
        sx = rs * cos_x * cos_y
        sy = -rs * sin_x
        sz = rs * cos_x * sin_y
        lat = np.degrees(np.arctan(ratio * sz / np.sqrt((H - sx) ** 2 + sy ** 2)))
        lon = np.degrees(lon0 - np.arctan(sy / (H - sx)))
    if lat.ndim == 0:
        return float(lat), float(lon)
    return lat, lon


def parse_fire_pixels(mask, power, x, y, proj: dict, bbox: tuple, acq_time: str) -> list[dict]:
    """mask/power: 2-D arrays (y, x); x/y: 1-D scan angles in radians. Returns detection dicts inside bbox."""
    mask = np.ma.filled(np.ma.asarray(mask), -99)
    rows, cols = np.nonzero(np.isin(mask, FIRE_CODES))
    if rows.size == 0:
        return []
    lat, lon = pixel_to_latlon(np.asarray(x)[cols], np.asarray(y)[rows], proj)
    w, s, e, n = bbox
    out = []
    for i in range(rows.size):
        if not (np.isfinite(lat[i]) and w <= lon[i] <= e and s <= lat[i] <= n):
            continue
        frp = None
        if power is not None:
            p = np.ma.filled(np.ma.asarray(power)[rows[i], cols[i]], np.nan)
            if np.isfinite(p) and p >= 0:
                frp = round(float(p), 2)
        code = int(mask[rows[i], cols[i]])
        out.append({
            "source": SOURCE,
            "satellite": SATELLITE,
            "lat": round(float(lat[i]), 5),
            "lon": round(float(lon[i]), 5),
            "acq_time": acq_time,
            "brightness_k": None,
            "frp_mw": frp,
            "confidence": confidence_from_mask(code),
            "scan_km": 2.0,
            "track_km": 2.0,
            "daynight": None,
            "mask_code": code,
        })
    return out


def read_fire_file(data: bytes, bbox: tuple, acq_time: str) -> list[dict]:
    """Read a downloaded FDCC netCDF (bytes) with netCDF4 and return detections inside bbox."""
    import netCDF4

    try:
        ds = netCDF4.Dataset("fdcc.nc", mode="r", memory=data)
    except Exception as e:
        raise RuntimeError(f"GOES: could not read file ({type(e).__name__})") from None
    try:
        p = ds["goes_imager_projection"]
        proj = {k: float(p.getncattr(k)) for k in (
            "perspective_point_height", "semi_major_axis", "semi_minor_axis", "longitude_of_projection_origin")}
        power = ds["Power"][:] if "Power" in ds.variables else None
        return parse_fire_pixels(ds["Mask"][:], power, ds["x"][:], ds["y"][:], proj, bbox, acq_time)
    finally:
        ds.close()


def parse_listing(xml_text: str) -> list[dict]:
    """S3 ListObjectsV2 XML to [{key, last_modified (datetime), size}], oldest first."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise RuntimeError("GOES: bad listing response") from None
    out = []
    for c in root.iter(f"{_S3_NS}Contents"):
        key = c.findtext(f"{_S3_NS}Key") or ""
        lm = c.findtext(f"{_S3_NS}LastModified") or ""
        if not key.endswith(".nc"):
            continue
        out.append({
            "key": key,
            "last_modified": datetime.strptime(lm, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc),
            "size": int(c.findtext(f"{_S3_NS}Size") or 0),
        })
    return sorted(out, key=lambda f: f["key"].rsplit("/", 1)[-1])


def _get(url: str, params: dict | None = None) -> httpx.Response:
    try:
        resp = httpx.get(url, params=params, timeout=60)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"GOES: HTTP {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise RuntimeError(f"GOES: {type(e).__name__}") from None
    return resp


def list_hour(when: datetime) -> list[dict]:
    prefix = f"{PRODUCT}/{when:%Y}/{when:%j}/{when:%H}/"
    return parse_listing(_get(BUCKET_URL + "/", {"list-type": "2", "prefix": prefix}).text)


def newest_files(n: int = 1, now: datetime | None = None, max_hours: int = 6) -> list[dict]:
    """Newest n files, newest last. Walks back hour by hour until it has n."""
    now = now or datetime.now(timezone.utc)
    files: list[dict] = []
    for h in range(max_hours):
        files = list_hour(now - timedelta(hours=h)) + files
        if len(files) >= n:
            break
    return files[-n:]


def latency_record(entry: dict, ingest_time: datetime | None = None) -> dict:
    """Scan start/end, S3 LastModified and our ingest time, with the minutes between them."""
    ingest = ingest_time or datetime.now(timezone.utc)
    start, end = scan_times(entry["key"])
    lm = entry["last_modified"]
    mins = lambda a, b: round((b - a).total_seconds() / 60, 1)  # noqa: E731
    return {
        "key": entry["key"],
        "scan_start": _iso(start),
        "scan_end": _iso(end),
        "s3_last_modified": _iso(lm),
        "ingest_time": _iso(ingest),
        "scan_duration_min": mins(start, end),
        "scan_end_to_s3_min": mins(end, lm),
        "s3_to_ingest_min": mins(lm, ingest),
        "scan_start_to_ingest_min": mins(start, ingest),
        "scan_end_to_ingest_min": mins(end, ingest),
    }


def latest_detections(bbox: tuple, now: datetime | None = None) -> tuple[list[dict], dict]:
    """Download the newest FDCC file and return (detections inside bbox, latency record)."""
    files = newest_files(1, now)
    if not files:
        raise RuntimeError("GOES: no files found in the last few hours")
    entry = files[0]
    data = _get(f"{BUCKET_URL}/{entry['key']}").content
    ingest = datetime.now(timezone.utc)
    start, _ = scan_times(entry["key"])
    dets = read_fire_file(data, bbox, _iso(start))
    return dets, latency_record(entry, ingest)
