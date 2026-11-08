"""NOAA SPC fire weather outlooks (Day 1 wind/RH, Day 1 dry thunderstorm, Day 2 dry thunderstorm)."""

from .feedlib import geom_overlaps_bbox, get_json, run_feed

BASE = "https://www.spc.noaa.gov/products/fire_wx/{name}.lyr.geojson"
OUTLOOKS = {"day1_wind_rh": "day1fw_windrh", "day1_dry_tstm": "day1fw_dryt", "day2_dry_tstm": "day2fw_dryt"}


def parse(name: str, payload: dict) -> list[dict]:
    areas = []
    for f in (payload or {}).get("features") or []:
        p = f.get("properties") or {}
        if str(p.get("LABEL", "")).strip().lower() in ("no areas", "") and not geom_overlaps_bbox(f.get("geometry")):
            continue  # SPC sends one empty "No Areas" feature when nothing is outlooked
        if not geom_overlaps_bbox(f.get("geometry")):
            continue
        areas.append({
            "outlook": name, "label": p.get("LABEL"), "label2": p.get("LABEL2"),
            "valid": p.get("VALID_ISO"), "expires": p.get("EXPIRE_ISO"), "issued": p.get("ISSUE_ISO"),
            "geometry": f.get("geometry"),
        })
    return areas


def fetch() -> dict:
    areas, errors = [], {}
    for name, slug in OUTLOOKS.items():
        try:
            areas += parse(name, get_json(BASE.format(name=slug)))
        except Exception as e:
            errors[name] = str(e)
    if len(errors) == len(OUTLOOKS):
        raise RuntimeError(f"all SPC outlooks failed: {errors}")
    return {"count": len(areas), "areas": areas, "errors": errors}


def poll() -> dict:
    return run_feed("spc", fetch())
