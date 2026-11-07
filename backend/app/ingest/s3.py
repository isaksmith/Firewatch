"""Anonymous reads from NOAA open-data S3 buckets (no key, no boto3).

Listing uses the public ListObjectsV2 XML endpoint. Keys sort by time, so the
newest key is last. Callers fall back one hour when the current hour is empty.
"""

import re
from datetime import datetime, timedelta, timezone

import httpx

from .feedlib import client_headers

TIMEOUT = 40
_KEY = re.compile(r"<Key>([^<]+)</Key>")


def list_keys(bucket: str, prefix: str) -> list[str]:
    r = httpx.get(f"https://{bucket}.s3.amazonaws.com/", params={"list-type": "2", "prefix": prefix},
                  headers=client_headers(), timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return sorted(_KEY.findall(r.text))


def get_bytes(bucket: str, key: str, byte_range: tuple[int, int] | None = None) -> bytes:
    headers = dict(client_headers())
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    r = httpx.get(f"https://{bucket}.s3.amazonaws.com/{key}", headers=headers, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.content


def hour_prefix(product: str, when: datetime) -> str:
    return f"{product}/{when.year}/{when.timetuple().tm_yday:03d}/{when.hour:02d}/"


def recent_keys(bucket: str, product: str, now: datetime | None = None, hours: int = 2) -> list[str]:
    """Keys for the current hour, plus the previous hour when the current one is thin.

    Returned oldest to newest. `hours` is how many hourly folders to look back at most.
    """
    now = now or datetime.now(timezone.utc)
    keys: list[str] = []
    for back in range(hours):
        got = list_keys(bucket, hour_prefix(product, now - timedelta(hours=back)))
        keys = got + keys
        if got and back == 0 and hours > 1 and len(got) >= 3:
            break
    return keys


def scan_start(key: str) -> datetime | None:
    """Parse the sYYYYDDDHHMMSSt start stamp in a GOES file name."""
    m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})", key)
    if not m:
        return None
    y, doy, hh, mm, ss = (int(g) for g in m.groups())
    return datetime(y, 1, 1, hh, mm, ss, tzinfo=timezone.utc) + timedelta(days=doy - 1)
