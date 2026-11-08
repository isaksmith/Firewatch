"""Prefetch land-cover tiles around each scenario so forecasts run offline (demo venue Wi-Fi, flaky CDL).

    .venv/bin/python -m scripts.fetch_fuels            # NLCD + CDL for every scenario
    .venv/bin/python -m scripts.fetch_fuels --no-cdl   # NLCD only (fast)

Tiles land in data/cache/{nlcd,cdl}. The CDL service often takes minutes or returns 502, so it is
tried one tile at a time with a long timeout; NLCD alone is enough to run.
"""

import argparse
import logging

import httpx
import numpy as np

from app.geo import KM_PER_DEG_LAT, km_per_deg_lon
from app.sim.fuels import FuelUnavailable, _cdl_path, _nlcd_path, download_cdl, download_nlcd, tiles_for
from app.situation import list_scenarios, load_scenario

log = logging.getLogger("fetch_fuels")
RADIUS_KM = 30.0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cdl", action="store_true")
    args = ap.parse_args()

    tiles: set[tuple[int, int]] = set()
    for s in list_scenarios():
        _, sit = load_scenario(s["slug"])
        lat, lon = sit.ignition.lat, sit.ignition.lon
        dlat, dlon = RADIUS_KM / KM_PER_DEG_LAT, RADIUS_KM / km_per_deg_lon(lat)
        tiles |= set(tiles_for(np.array([lat - dlat, lat + dlat]), np.array([lon - dlon, lon + dlon])))
    log.info("%d tiles cover %d scenarios", len(tiles), len(list_scenarios()))

    for name, path_fn, fetch, skip in (
        ("NLCD", _nlcd_path, download_nlcd, False),
        ("CDL", _cdl_path, download_cdl, args.no_cdl),
    ):
        if skip:
            continue
        done = failed = 0
        for tx, ty in sorted(tiles):
            if path_fn(tx, ty).exists():
                done += 1
                continue
            try:
                fetch(tx, ty)
                done += 1
            except (httpx.HTTPError, FuelUnavailable) as e:
                failed += 1
                log.warning("%s tile %s,%s failed: %s", name, tx, ty, e)
        log.info("%s: %d cached, %d failed", name, done, failed)


if __name__ == "__main__":
    main()
