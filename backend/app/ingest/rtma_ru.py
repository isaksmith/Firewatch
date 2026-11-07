"""RTMA-RU 2.5 km near-surface analysis (noaa-rtma-pds), sampled onto the risk grid.

Uses the 2dvaranl analysis file (not 2dvarges, which is the first guess). Only the three
messages needed (surface pressure, 2 m temperature, 2 m dew point) are fetched, by byte
range from the .idx file, so each cycle costs about 20 MB instead of the whole file.
RH is derived from temperature and dew point with the same Magnus formula METAR uses.
"""

import logging
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import s3
from .feedlib import run_feed
from .metar import rh_from_dewpoint
from .risk_grid import grid_points

log = logging.getLogger("firewatch.rtma_ru")

BUCKET = "noaa-rtma-pds"
SUFFIX = ".2dvaranl_ndfd.grb2"
WANTED = {"PRES:surface": "p", "TMP:2 m above ground": "t", "DPT:2 m above ground": "d"}
_KEY_TIME = re.compile(r"rtma2p5_ru\.(\d{8})/rtma2p5_ru\.t(\d{2})(\d{2})z")

_cache: dict[str, dict] = {}  # newest key -> result


def key_time(key: str) -> datetime | None:
    m = _KEY_TIME.search(key)
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2) + m.group(3), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)


def newest_key(now: datetime | None = None) -> str | None:
    """Newest analysis file, looking in the current hour and then the previous one."""
    now = now or datetime.now(timezone.utc)
    for back in range(2):
        t = now - timedelta(hours=back)
        got = [k for k in s3.list_keys(BUCKET, f"rtma2p5_ru.{t:%Y%m%d}/rtma2p5_ru.t{t:%H}") if k.endswith(SUFFIX)]
        if got:
            return got[-1]
    return None


def byte_ranges(idx_text: str) -> dict[str, tuple[int, int]]:
    """Map p/t/d to (start, end) byte ranges. A message ends where the next one begins."""
    rows = [ln.split(":") for ln in idx_text.splitlines() if ln.count(":") >= 5]
    out = {}
    for i, r in enumerate(rows):
        tag = WANTED.get(f"{r[3]}:{r[4]}")
        if tag and i + 1 < len(rows):
            out[tag] = (int(r[1]), int(rows[i + 1][1]) - 1)
    return out


def sample(fields: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]) -> list[dict]:
    """Nearest grid cell of each risk-grid point. fields maps p/t/d to (values, lats, lons)."""
    t, lats, lons = fields["t"]
    d, p = fields["d"][0], fields["p"][0]
    out = []
    for lat, lon in grid_points():
        k = float(np.cos(np.radians(lat)))
        i = np.unravel_index(np.argmin((lats - lat) ** 2 + ((lons - lon) * k) ** 2), lats.shape)
        tc, dc = float(t[i]) - 273.15, float(d[i]) - 273.15
        out.append({"lat": lat, "lon": lon, "temp_c": round(tc, 1), "dew_c": round(dc, 1),
                    "rh": round(rh_from_dewpoint(tc, min(dc, tc)), 1), "p_hpa": round(float(p[i]) / 100, 1)})
    return out


def parse(blob: bytes) -> list[dict]:
    """Read the concatenated GRIB messages and sample them. Reads from a temp file for pygrib."""
    import pygrib
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rtma.grb2"
        path.write_bytes(blob)
        grbs = pygrib.open(str(path))
        try:
            by = {"sp": "p", "2t": "t", "2d": "d"}
            fields = {}
            w, s, e, n = _crop_box()
            for m in grbs:
                tag = by.get(m.shortName)
                if tag:
                    lats, lons = m.latlons()
                    sel = (lats >= s) & (lats <= n) & (lons >= w) & (lons <= e)
                    rows, cols = np.nonzero(sel)
                    r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
                    fields[tag] = (np.ma.filled(m.values, np.nan)[r0:r1, c0:c1], lats[r0:r1, c0:c1], lons[r0:r1, c0:c1])
        finally:
            grbs.close()
    if set(fields) != {"p", "t", "d"}:
        raise RuntimeError(f"RTMA-RU file missing fields, got {sorted(fields)}")
    return sample(fields)


def _crop_box() -> tuple[float, float, float, float]:
    from ..config import get_settings
    w, s, e, n = get_settings().bbox_tuple
    return w - 0.5, s - 0.5, e + 0.5, n + 0.5


def fetch(now: datetime | None = None) -> dict:
    key = newest_key(now)
    if not key:
        raise RuntimeError("no RTMA-RU analysis file in last 2 hours")
    if key not in _cache:
        idx = s3.get_bytes(BUCKET, key + ".idx").decode()
        rng = byte_ranges(idx)
        if set(rng) != {"p", "t", "d"}:
            raise RuntimeError(f"RTMA-RU idx missing messages, got {sorted(rng)}")
        blob = b"".join(s3.get_bytes(BUCKET, key, rng[tag]) for tag in ("p", "t", "d"))
        _cache.clear()
        _cache[key] = {"points": parse(blob)}
    valid = key_time(key)
    return {"count": len(_cache[key]["points"]), "valid_time": valid.isoformat() if valid else None,
            "key": key.rsplit("/", 1)[-1], "points": _cache[key]["points"]}


def poll() -> dict:
    return run_feed("rtma_ru", fetch())
