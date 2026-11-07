"""Build region packs (`fwpack/1`, docs/mobile/FW1-CODEC.md) for the phone app.

    .venv/bin/python -m scripts.build_pack --district cottonwood-creek      # pack "cwc"
    .venv/bin/python -m scripts.build_pack --county "Comanche,KS"           # pack "ks-comanche"
    .venv/bin/python -m scripts.build_pack --all                            # cwc plus Comanche, Clark, Barber

Roads come from OpenStreetMap (Overpass), cached under data/cache/overpass/ so a rerun works offline. If Overpass
is down and nothing is cached, the pack is built without roads and says so. Packs carry no phone numbers and no
people: places are stations and scenario spots only.
"""

import argparse
import gzip
import hashlib
import json
import logging
import math
import sys
import time
from datetime import date
from pathlib import Path

import httpx

from app.config import DATA_DIR
from app.district import _dir, load_district

log = logging.getLogger("build_pack")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "Firewatch-pack-builder/1 (hackathon)"}
CACHE_DIR = DATA_DIR / "cache" / "overpass"
PACKS_DIR = DATA_DIR / "packs"
TARGET_GZ = 1_500_000
PAD_DISTRICT_KM = 10.0
PAD_COUNTY_KM = 2.0
SIMPLIFY_M = 15.0
KM_LAT = 110.574
ROAD_KINDS = {
    "motorway": "highway", "motorway_link": "highway", "trunk": "highway", "trunk_link": "highway",
    "primary": "state", "primary_link": "state", "secondary": "state", "secondary_link": "state",
    "tertiary": "county", "tertiary_link": "county", "unclassified": "county",
    "residential": "local", "living_street": "local", "service": "local", "track": "track",
}
COUNTY_PACKS = [("Comanche", "KS"), ("Clark", "KS"), ("Barber", "KS")]
STATE_NAMES = {"KS": "Kansas"}


# --- geometry --------------------------------------------------------------------------------------------


def _xy(p, lat0):
    return p[0] * 111.320 * 1000 * math.cos(math.radians(lat0)), p[1] * KM_LAT * 1000


def simplify(line: list, tol_m: float = SIMPLIFY_M) -> list:
    """Douglas-Peucker on [lon, lat] points, tolerance in metres (iterative, so long roads cannot overflow the stack)."""
    if len(line) < 3:
        return line
    lat0 = line[0][1]
    pts = [_xy(p, lat0) for p in line]
    keep = [False] * len(line)
    keep[0] = keep[-1] = True
    stack = [(0, len(line) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        best, idx = -1.0, None
        for i in range(a + 1, b):
            px, py = pts[i]
            d = math.hypot(px - ax, py - ay) if norm == 0 else abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol_m:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(line, keep) if k]


def r5(line: list) -> list:
    out = []
    for lon, lat in line:
        p = [round(lon, 5), round(lat, 5)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def bbox_of(rings: list, pad_km: float) -> list:
    pts = [p for r in rings for p in r]
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    mid = (min(lats) + max(lats)) / 2
    dlat, dlon = pad_km / KM_LAT, pad_km / (111.320 * math.cos(math.radians(mid)))
    return [round(min(lons) - dlon, 4), round(min(lats) - dlat, 4), round(max(lons) + dlon, 4), round(max(lats) + dlat, 4)]


def in_box(lon, lat, box) -> bool:
    return box[0] <= lon <= box[2] and box[1] <= lat <= box[3]


def touches(line: list, box) -> bool:
    return any(in_box(x, y, box) for x, y in line)


# --- sources ---------------------------------------------------------------------------------------------


def fetch_roads(code: str, box: list) -> tuple[list | None, str]:
    """Overpass ways for the box. Returns (elements or None, note). Cached per pack code and box."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{code}.json"
    key = ",".join(f"{v:.4f}" for v in box)
    if cache.exists():
        c = json.loads(cache.read_text())
        if c.get("box") == key:
            return c["elements"], "roads from the Overpass cache"
    s, w, n, e = box[1], box[0], box[3], box[2]
    kinds = "|".join(k for k in ROAD_KINDS)
    q = f'[out:json][timeout:240];way["highway"~"^({kinds})$"]({s},{w},{n},{e});out tags geom;'
    last = None
    for attempt in range(3):
        try:
            r = httpx.post(OVERPASS_URL, data={"data": q}, headers=HEADERS, timeout=300)
            r.raise_for_status()
            els = r.json()["elements"]
            cache.write_text(json.dumps({"box": key, "elements": els}))
            return els, "roads from Overpass (fresh)"
        except (httpx.HTTPError, ValueError, KeyError) as ex:
            last = ex
            log.warning("Overpass attempt %d failed: %s", attempt + 1, type(ex).__name__)
            time.sleep(8 * (attempt + 1))
    return None, f"Overpass failed ({type(last).__name__}); built WITHOUT roads"


def build_roads(elements: list, tol_m: float, drop: set) -> list:
    roads = []
    for el in elements:
        tags = el.get("tags", {})
        kind = ROAD_KINDS.get(tags.get("highway", ""))
        if not kind or kind in drop or not el.get("geometry"):
            continue
        line = r5(simplify([[g["lon"], g["lat"]] for g in el["geometry"]], tol_m))
        if len(line) < 2:
            continue
        road = {"kind": kind, "line": line}
        name = tags.get("name") or tags.get("ref")
        if name:
            road = {"name": name, "kind": kind, "line": line}
        roads.append(road)
    return roads


def layer(name: str) -> list:
    return json.loads((DATA_DIR / "layers" / f"{name}.geojson").read_text())["features"]


def lines_in(features: list, box) -> list:
    out = []
    for f in features:
        g = f["geometry"]
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for part in parts:
            if touches(part, box):
                line = r5(simplify(part, SIMPLIFY_M))
                if len(line) >= 2:
                    out.append({"line": line})
    return out


def buildings_in(slug: str, box) -> list:
    path = _dir(slug) / "structures.geojson"
    if not path.exists():
        return []
    out = []
    for f in json.loads(path.read_text())["features"]:
        lon, lat = f["geometry"]["coordinates"]
        if not in_box(lon, lat, box):
            continue
        p = f["properties"]
        kind = "home" if p.get("houses", 0) >= 1 else "farm" if p.get("buildings", 0) >= 3 else "other"
        out.append({"lon": round(lon, 5), "lat": round(lat, 5), "kind": kind})
    return out


def places_for(slug: str, box) -> list:
    """Stations (not people) and scenario spots. No names of private individuals, no phone numbers."""
    import csv

    places = []
    path = _dir(slug) / "roster.csv"
    if path.exists():
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row["role"] == "station" and row["lat"] and in_box(float(row["lon"]), float(row["lat"]), box):
                    places.append({"name": row["name"].replace(" (stand-in)", ""), "kind": "station",
                                   "lon": round(float(row["lon"]), 5), "lat": round(float(row["lat"]), 5)})
    sc = DATA_DIR / "scenarios" / f"{slug}.json"
    ig = json.loads(sc.read_text()).get("ignition") if sc.exists() else None
    if ig and in_box(ig["lon"], ig["lat"], box):
        places.append({"name": "Lease line ignition", "kind": "spot", "lon": round(ig["lon"], 5), "lat": round(ig["lat"], 5)})
    for i, p in enumerate(places, 1):
        p["id"] = f"p{i}"
    return [{"id": p["id"], "name": p["name"], "kind": p["kind"], "lon": p["lon"], "lat": p["lat"]} for p in places]


# --- packs -----------------------------------------------------------------------------------------------


def size_of(pack: dict) -> tuple[bytes, int]:
    raw = json.dumps(pack, separators=(",", ":"), ensure_ascii=False).encode()
    return raw, len(gzip.compress(raw, 9, mtime=0))


def finish(pack: dict, elements: list | None) -> tuple[dict, list]:
    """Fill roads; if the gzipped pack is over target, drop driveway-class roads and then coarsen."""
    notes = []
    if elements is not None:
        for tol, drop in ((SIMPLIFY_M, set()), (SIMPLIFY_M, {"local"}), (30.0, {"local"}), (30.0, {"local", "track"})):
            pack["roads"] = build_roads(elements, tol, drop)
            _, gz = size_of(pack)
            if gz <= TARGET_GZ:
                break
            notes.append(f"over target; retried with tol={tol:g} m, dropped={sorted(drop) or 'none'}")
    return pack, notes


def build(code: str, name: str, state: str, counties: list, boundary: dict, origin: dict, box: list, slug: str | None,
          stations: list) -> dict:
    pack = {
        "format": "fwpack/1", "code": code, "name": name, "state": state, "counties": counties,
        "version": f"{date.today().isoformat()}.1", "tz": "America/Chicago",
        "origin": origin, "bbox": box, "boundary": boundary, "roads": [],
        "towns": [
            {"name": f["properties"]["name"], "lon": round(f["geometry"]["coordinates"][0], 5), "lat": round(f["geometry"]["coordinates"][1], 5)}
            for f in layer("towns") if f["properties"].get("name") and in_box(*f["geometry"]["coordinates"][:2], box)
        ],
        "buildings": buildings_in(slug, box) if slug else [],
        "stations": stations,
        "power_lines": lines_in(layer("power_lines") + layer("distribution_lines"), box),
        "places": places_for(slug, box) if slug else [],
    }
    if not slug:  # a county pack borrows the stand-in district's data where the two overlap
        pack["buildings"] = buildings_in("cottonwood-creek", box)
        pack["places"] = places_for("cottonwood-creek", box)
        pack["stations"] = [s for s in stations if in_box(s["lon"], s["lat"], box)]
    return pack


def district_pack(slug: str) -> tuple[dict, str]:
    d = load_district(slug)
    code = {"cottonwood-creek": "cwc"}.get(slug, slug)
    b = json.loads((_dir(slug) / "boundary.geojson").read_text())["features"][0]["geometry"]
    rings = [poly[0] for poly in ([b["coordinates"]] if b["type"] == "Polygon" else b["coordinates"])]
    box = bbox_of(rings, PAD_DISTRICT_KM)
    st = d.settings["station"]
    origin = {"lat": st["lat"], "lon": st["lon"]}
    stations = [{"name": st["name"], "lon": st["lon"], "lat": st["lat"]}]
    pack = build(code, d.settings["name"], "KS", ["Comanche"], b, origin, box, slug, stations)
    return pack, code


def county_pack(county: str, state: str) -> tuple[dict, str]:
    feat = next(f for f in layer("counties") if f["properties"]["name"].lower() == county.lower())
    g = feat["geometry"]
    rings = [poly[0] for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"])]
    box = bbox_of(rings, PAD_COUNTY_KM)
    boundary = {"type": "Polygon", "coordinates": [r5(simplify(rings[0], 100.0))]} if g["type"] == "Polygon" else g
    lons, lats = [p[0] for p in rings[0]], [p[1] for p in rings[0]]
    origin = {"lat": round(sum(lats) / len(lats), 4), "lon": round(sum(lons) / len(lons), 4)}
    st = load_district("cottonwood-creek").settings["station"]
    stations = [{"name": st["name"], "lon": st["lon"], "lat": st["lat"]}]
    code = f"{state.lower()}-{county.lower()}"
    pack = build(code, f"{county} County, {state}", state, [county], boundary, origin, box, None, stations)
    return pack, code


def write_pack(pack: dict, code: str, note: str, elements: list | None) -> dict:
    pack, notes = finish(pack, elements)
    raw, gz = size_of(pack)
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    (PACKS_DIR / f"{code}.json").write_bytes(raw)
    meta = {"code": code, "name": pack["name"], "state": pack["state"], "counties": pack["counties"],
            "version": pack["version"], "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    print(f"{code}: {len(raw):,} bytes raw, {gz:,} gzipped ({'OK' if gz <= TARGET_GZ else 'OVER 1.5 MB TARGET'}); "
          f"roads={len(pack['roads'])} towns={len(pack['towns'])} buildings={len(pack['buildings'])} "
          f"stations={len(pack['stations'])} power_lines={len(pack['power_lines'])} places={len(pack['places'])}; {note}; {'; '.join(notes)}")
    return meta


def write_index(metas: list) -> None:
    path = PACKS_DIR / "index.json"
    have = {m["code"]: m for m in (json.loads(path.read_text()) if path.exists() else [])}
    have.update({m["code"]: m for m in metas})
    path.write_text(json.dumps(sorted(have.values(), key=lambda m: m["code"]), indent=2) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--district")
    ap.add_argument("--county", help='for example "Comanche,KS"')
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    jobs = []
    if a.district or a.all:
        jobs.append(lambda: district_pack(a.district or "cottonwood-creek"))
    for c, s in ([tuple(x.strip() for x in a.county.split(","))] if a.county else []) + (COUNTY_PACKS if a.all else []):
        jobs.append(lambda c=c, s=s: county_pack(c, s))
    if not jobs:
        ap.error("give --district, --county or --all")
    metas = []
    for job in jobs:
        pack, code = job()
        elements, note = fetch_roads(code, pack["bbox"])
        metas.append(write_pack(pack, code, note, elements))
    write_index(metas)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
