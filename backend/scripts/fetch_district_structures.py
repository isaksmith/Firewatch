"""Pull buildings around a district from OpenStreetMap and group them into sites (farmsteads, town blocks) in
data/districts/<slug>/structures.geojson.

    .venv/bin/python -m scripts.fetch_district_structures [slug]

The recommendation model counts sites a fire reaches before enough help is there (docs/RECOMMENDATIONS.md).
Buildings are grouped because a farmstead is one place to protect, whether it has two sheds or twelve.
"""

import json
import logging
import math
import sys

from app.district import _dir, load_district
from scripts.fetch_osm_layers import overpass

log = logging.getLogger("fetch_district_structures")
MARGIN_DEG = 0.25
SITE_M = 150  # buildings this close are one site


def sites(buildings: list[dict]) -> list[dict]:
    """Single-linkage groups of buildings within SITE_M, via a grid of SITE_M cells."""
    ky = 110_574
    kx = 111_320 * math.cos(math.radians(sum(b["lat"] for b in buildings) / len(buildings)))
    cell = {}
    for i, b in enumerate(buildings):
        cell.setdefault((int(b["lon"] * kx // SITE_M), int(b["lat"] * ky // SITE_M)), []).append(i)
    parent = list(range(len(buildings)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for (cx, cy), members in cell.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cell.get((cx + dx, cy + dy), []):
                    for i in members:
                        a, b = buildings[i], buildings[j]
                        if math.hypot((a["lon"] - b["lon"]) * kx, (a["lat"] - b["lat"]) * ky) <= SITE_M:
                            parent[find(i)] = find(j)
    groups: dict[int, list[dict]] = {}
    for i, b in enumerate(buildings):
        groups.setdefault(find(i), []).append(b)
    out = []
    for g in groups.values():
        out.append({
            "lat": round(sum(b["lat"] for b in g) / len(g), 5), "lon": round(sum(b["lon"] for b in g) / len(g), 5),
            "buildings": len(g), "houses": sum(1 for b in g if b["kind"] in ("house", "residential", "farm", "detached")),
        })
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    d = load_district(sys.argv[1] if len(sys.argv) > 1 else None)
    lons = [p[0] for r in d.rings for p in r]
    lats = [p[1] for r in d.rings for p in r]
    s, w = min(lats) - MARGIN_DEG, min(lons) - MARGIN_DEG
    n, e = max(lats) + MARGIN_DEG, max(lons) + MARGIN_DEG
    data = overpass(f'[out:json][timeout:240];(way["building"]({s},{w},{n},{e});node["building"]({s},{w},{n},{e}););out center tags;')
    buildings = []
    for el in data["elements"]:
        c = el.get("center") or el
        if "lat" in c:
            buildings.append({"lat": c["lat"], "lon": c["lon"], "kind": el.get("tags", {}).get("building", "yes")})
    grouped = sites(buildings)
    feats = [{"type": "Feature", "properties": {k: g[k] for k in ("buildings", "houses")},
              "geometry": {"type": "Point", "coordinates": [g["lon"], g["lat"]]}} for g in grouped]
    out = _dir(d.slug) / "structures.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "source": "OpenStreetMap buildings (ODbL)", "features": feats},
                              separators=(",", ":")))
    log.info("%d buildings -> %d sites -> %s", len(buildings), len(grouped), out)


if __name__ == "__main__":
    main()
