"""NOAA HMS analyst-checked fire points (daily text file, updated through the day)."""

from datetime import datetime, timedelta, timezone

import httpx

from .feedlib import get_text, in_bbox, run_feed

URL = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Fire_Points/Text/{y}/{m}/hms_fire{ymd}.txt"


def parse(text: str) -> list[dict]:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines or "lon" not in lines[0].lower():
        raise ValueError("unexpected HMS file header")
    head = [h.strip().lower() for h in lines[0].split(",")]
    out = []
    for ln in lines[1:]:
        row = dict(zip(head, (c.strip() for c in ln.split(","))))
        try:
            lon, lat = float(row["lon"]), float(row["lat"])
        except (KeyError, ValueError):
            continue
        if not in_bbox(lon, lat):
            continue
        try:
            frp = float(row.get("frp", ""))
        except ValueError:
            frp = None
        out.append({"lon": lon, "lat": lat, "yearday": row.get("yearday"), "time_utc": row.get("time"),
                    "satellite": row.get("satellite"), "method": row.get("method"), "frp_mw": frp})
    return out


def fetch(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    last = None
    for back in (0, 1):  # today's file may not exist yet right after UTC midnight
        d = now - timedelta(days=back)
        try:
            text = get_text(URL.format(y=d.year, m=f"{d.month:02d}", ymd=d.strftime("%Y%m%d")))
            pts = parse(text)
            return {"count": len(pts), "file_date": d.strftime("%Y-%m-%d"), "points": pts}
        except httpx.HTTPStatusError as e:
            last = e
            if e.response.status_code != 404:
                raise
    raise last


def poll() -> dict:
    return run_feed("hms", fetch())
