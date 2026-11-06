"""Replace approximate weather in historical sample fixtures with Open-Meteo archive values.

Usage (from backend/):  .venv/bin/python -m scripts.backfill_sample_weather
Synthetic fixtures are left alone.
"""

import json

from app.db import parse_iso
from app.ingest.weather import weather_at
from app.sample import SAMPLES_DIR


def main() -> None:
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        fx = json.loads(path.read_text())
        if fx.get("synthetic"):
            print(f"skip   {fx['slug']} (synthetic)")
            continue
        first = fx["passes"][0]["detections"][0]
        w = weather_at(first["lat"], first["lon"], parse_iso(first["acq_time"]))
        w["source"] = "open-meteo-archive"
        old = fx["weather"]
        fx["weather"] = w
        path.write_text(json.dumps(fx, indent=2) + "\n")
        print(
            f"update {fx['slug']}: wind {old.get('wind_kmh')} -> {w['wind_kmh']} km/h, "
            f"gust {old.get('gust_kmh')} -> {w['gust_kmh']}, RH {old.get('rh_pct')} -> {w['rh_pct']}%, "
            f"dir {old.get('wind_dir_deg')} -> {w['wind_dir_deg']}"
        )


if __name__ == "__main__":
    main()
