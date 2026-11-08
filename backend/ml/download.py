"""Download historical FIRMS detections (filtered to Kansas) and WFIGS Kansas incidents.

    .venv/bin/python -m ml.download [--years 2016-2024]
"""

import argparse
import csv
import io
import json
import logging

import httpx

from .paths import FIRMS_DIR, KS_BBOX, WFIGS_PATH

log = logging.getLogger("ml.download")

FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/data/country/{folder}/{year}/{folder}_{year}_United_States.csv"
# folder name -> (live source name, first year with data)
SENSORS = {
    "viirs-snpp": ("VIIRS_SNPP_NRT", 2012),
    "modis": ("MODIS_NRT", 2000),
    "viirs-jpss1": ("VIIRS_NOAA20_NRT", 2018),
    "viirs-jpss2": ("VIIRS_NOAA21_NRT", 2023),
}
WFIGS_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations/FeatureServer/0/query"
)


def download_firms(years: range, force: bool = False) -> None:
    FIRMS_DIR.mkdir(parents=True, exist_ok=True)
    w, s, e, n = KS_BBOX
    with httpx.Client(timeout=300, follow_redirects=True) as client:
        for folder, (_, first_year) in SENSORS.items():
            for year in years:
                if year < first_year:
                    continue
                out = FIRMS_DIR / f"{folder}_{year}_ks.csv"
                if out.exists() and not force:
                    log.info("skip %s (exists)", out.name)
                    continue
                url = FIRMS_URL.format(folder=folder, year=year)
                resp = client.get(url)
                if resp.status_code == 404:
                    log.info("no archive for %s %s", folder, year)
                    continue
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                kept = [
                    row for row in reader
                    if w <= float(row["longitude"]) <= e and s <= float(row["latitude"]) <= n
                ]
                with out.open("w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=reader.fieldnames or [])
                    writer.writeheader()
                    writer.writerows(kept)
                log.info("%s %s: %d Kansas detections", folder, year, len(kept))


def download_wfigs() -> None:
    params = {
        "where": "POOState='US-KS'",
        "outFields": "IncidentName,IncidentTypeCategory,FireDiscoveryDateTime,IncidentSize,POOCounty,"
        "InitialLatitude,InitialLongitude,UniqueFireIdentifier",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "json",
        "resultRecordCount": 2000,
    }
    resp = httpx.get(WFIGS_URL, params=params, timeout=60)
    resp.raise_for_status()
    feats = resp.json()["features"]
    out = []
    for feat in feats:
        a = feat["attributes"]
        geom = feat.get("geometry") or {}
        lat = a.get("InitialLatitude") or geom.get("y")
        lon = a.get("InitialLongitude") or geom.get("x")
        if lat is None or lon is None or a.get("FireDiscoveryDateTime") is None:
            continue
        out.append({
            "id": a.get("UniqueFireIdentifier"),
            "name": a.get("IncidentName"),
            "type": a.get("IncidentTypeCategory"),
            "discovered_ms": a["FireDiscoveryDateTime"],
            "acres": a.get("IncidentSize"),
            "county": a.get("POOCounty"),
            "lat": lat,
            "lon": lon,
        })
    WFIGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WFIGS_PATH.write_text(json.dumps(out, indent=1))
    by_type: dict[str, int] = {}
    for r in out:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    log.info("WFIGS Kansas incidents: %d %s", len(out), by_type)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--years", default="2016-2025")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    a, b = (int(x) for x in args.years.split("-"))
    download_wfigs()
    download_firms(range(a, b + 1), force=args.force)


if __name__ == "__main__":
    main()
