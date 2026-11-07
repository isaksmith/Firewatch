"""Build the region planner's committed layers from the local ML downloads.

    .venv/bin/python -m ml.planner_layers

Writes to backend/data/layers/:
- wildfire_history.geojson: reported Kansas wildfires and prescribed burns (NIFC WFIGS), one point each.
- burn_activity.json: satellite-detected fires 2016-2025 (FIRMS events from ml/build_dataset.py's history
  database, industrial heat sources removed), counted on a 0.05-degree grid.
- counties.geojson: Kansas county boundaries (US Census 1:20m, via plotly/datasets), so any county can be planned.
"""

import json
import logging
import sqlite3
from collections import Counter
from datetime import UTC, datetime

import httpx

from app.layers import nearest_static_source

from .paths import HISTORY_DB, KS_BBOX, LAYERS_DIR, WFIGS_PATH

log = logging.getLogger("ml.planner_layers")

GRID_DEG = 0.05
STATIC_KM = 2.0
COUNTIES_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"


def wildfire_history() -> dict:
    feats = []
    for inc in json.loads(WFIGS_PATH.read_text()):
        when = datetime.fromtimestamp(inc["discovered_ms"] / 1000, UTC)
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(inc["lon"], 5), round(inc["lat"], 5)]},
            "properties": {
                "id": inc["id"], "name": inc["name"], "type": inc["type"], "acres": inc.get("acres"),
                "county": inc.get("county"), "date": when.date().isoformat(),
            },
        })
    return {"type": "FeatureCollection", "source": "NIFC WFIGS incident locations", "features": feats}


def burn_activity() -> dict:
    conn = sqlite3.connect(HISTORY_DB)
    static_events = {
        r[0] for r in conn.execute(
            "SELECT d.event_id FROM detections d JOIN firms_type t ON t.detection_id = d.id "
            "GROUP BY d.event_id HAVING AVG(t.type = 2) > 0.5"
        )
    }
    cells: Counter = Counter()
    spring: Counter = Counter()
    for eid, lat, lon, first_seen in conn.execute("SELECT id, lat, lon, first_seen FROM events"):
        if eid in static_events or nearest_static_source(lat, lon).distance_km < STATIC_KM:
            continue
        key = (int((lat - KS_BBOX[1]) // GRID_DEG), int((lon - KS_BBOX[0]) // GRID_DEG))
        cells[key] += 1
        if first_seen[5:7] in ("03", "04"):
            spring[key] += 1
    return {
        "source": "NASA FIRMS (MODIS, VIIRS) Kansas 2016-2025, clustered into events; industrial heat removed",
        "years": 10,
        "origin": [KS_BBOX[1], KS_BBOX[0]],
        "cell_deg": GRID_DEG,
        "cells": [[i, j, n, spring[(i, j)]] for (i, j), n in sorted(cells.items())],
    }


def counties() -> dict:
    data = httpx.get(COUNTIES_URL, timeout=60).json()
    feats = []
    for f in data["features"]:
        if f["properties"].get("STATE") != "20":
            continue
        feats.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {"fips": f["id"], "name": f["properties"]["NAME"]},
        })
    feats.sort(key=lambda f: f["properties"]["name"])
    return {"type": "FeatureCollection", "source": "US Census cartographic boundary, 1:20m", "features": feats}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name, build, suffix in (
        ("wildfire_history", wildfire_history, "geojson"),
        ("burn_activity", burn_activity, "json"),
        ("counties", counties, "geojson"),
    ):
        out = LAYERS_DIR / f"{name}.{suffix}"
        out.write_text(json.dumps(build(), separators=(",", ":")))
        log.info("wrote %s (%.0f KB)", out.name, out.stat().st_size / 1024)


if __name__ == "__main__":
    main()
