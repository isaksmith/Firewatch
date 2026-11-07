"""Pull Kansas transmission lines, substations, and towns from OpenStreetMap (Overpass) into data/layers/.

    .venv/bin/python -m scripts.fetch_osm_layers
"""

import json
import logging
import time

import httpx

from app.config import DATA_DIR

log = logging.getLogger("fetch_osm_layers")

OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
COUNTIES_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
KANSAS_FIPS = "20"
MIN_LINE_KV = 115
LAYERS = DATA_DIR / "layers"

QUERY = """
[out:json][timeout:300];
area["ISO3166-2"="US-KS"]["admin_level"="4"]->.ks;
way["power"="line"]["voltage"](area.ks);
out tags geom;
(
  node["power"="substation"](area.ks);
  way["power"="substation"](area.ks);
  node["place"~"^(city|town|village)$"](area.ks);
);
out tags center;
"""
HEADERS = {"User-Agent": "firewatch-hackathon/0.1 (https://github.com/isaksmith/Firewatch)"}


def overpass(query: str) -> dict:
    last: Exception | None = None
    for url in OVERPASS_URLS:
        for attempt in range(3):
            try:
                resp = httpx.post(url, data={"data": query}, headers=HEADERS, timeout=360)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                last = e
                log.warning("%s attempt %d failed: %s", url, attempt + 1, e)
                time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass failed: {last}")


def max_kv(tags: dict) -> float:
    vals = []
    for part in str(tags.get("voltage", "")).replace(",", ";").split(";"):
        try:
            vals.append(float(part.strip()) / 1000)
        except ValueError:
            pass
    return max(vals, default=0.0)


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def load_counties() -> list[tuple[str, list[list]]]:
    data = httpx.get(COUNTIES_URL, timeout=60).json()
    out = []
    for f in data["features"]:
        if f["properties"].get("STATE") != KANSAS_FIPS:
            continue
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        out.append((f["properties"]["NAME"], [p[0] for p in polys]))
    return out


def county_of(lon: float, lat: float, counties) -> str | None:
    for name, rings in counties:
        if any(point_in_ring(lon, lat, r) for r in rings):
            return name
    return None


def fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def point(lon: float, lat: float, props: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    counties = load_counties()
    log.info("loaded %d Kansas counties", len(counties))
    elements = overpass(QUERY)["elements"]
    log.info("overpass returned %d elements", len(elements))

    lines, subs, towns = [], [], []
    for el in elements:
        tags = el.get("tags", {})
        if tags.get("power") == "line":
            kv = max_kv(tags)
            if kv < MIN_LINE_KV or "geometry" not in el:
                continue
            operator = tags.get("operator")
            label = f"{kv:.0f} kV line" + (f" ({operator})" if operator else "")
            lines.append({
                "type": "Feature",
                "properties": {"id": f"way/{el['id']}", "name": tags.get("name") or label, "voltage_kv": kv, "operator": operator},
                "geometry": {"type": "LineString", "coordinates": [[round(p["lon"], 5), round(p["lat"], 5)] for p in el["geometry"]]},
            })
        elif tags.get("power") == "substation":
            kv = max_kv(tags)
            if kv < MIN_LINE_KV and tags.get("substation") != "transmission":
                continue
            c = el if el["type"] == "node" else el.get("center")
            if not c:
                continue
            name = tags.get("name")
            label = f"{name} substation" if name else f"{kv:.0f} kV substation" if kv else "Transmission substation"
            subs.append(point(c["lon"], c["lat"], {"id": f"{el['type']}/{el['id']}", "name": label, "voltage_kv": kv or None, "operator": tags.get("operator")}))
        elif tags.get("place") in ("city", "town", "village") and tags.get("name"):
            county = county_of(el["lon"], el["lat"], counties)
            if county is None:
                continue
            pop = tags.get("population")
            towns.append(point(el["lon"], el["lat"], {
                "id": f"node/{el['id']}",
                "name": tags["name"],
                "county": county,
                "place": tags["place"],
                "population": int(pop) if pop and pop.isdigit() else None,
            }))

    for name, feats in (("power_lines", lines), ("substations", subs), ("towns", towns)):
        path = LAYERS / f"{name}.geojson"
        path.write_text(json.dumps(fc(feats), separators=(",", ":")))
        log.info("%s: %d features -> %s (%.0f KB)", name, len(feats), path.name, path.stat().st_size / 1024)


if __name__ == "__main__":
    main()
