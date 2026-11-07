# Firewatch

**Detect → Confirm → Respond** for rural Kansas volunteer fire districts, built around SMS so it works on one bar of cell.

Built for [Firewatch 2026](https://wsuinnovationworks.com/) (WSU Innovation Works × Lockheed Martin Skunk Works, Nov 6–8, 2026).

## The problem

In the challenge scenario (Cottonwood Creek Fire District: 450 sq mi, 18 volunteers, one bar of cell), a downed line starts a grass fire at 1:50. Nobody sees it until 2:17, 911 is called at 2:21, and the first truck arrives at 2:52, when the fire is 2–3 miles long. The 31 minutes before anyone knows are the ones that matter. Satellites alone don't win them: across 10 years of Kansas wildfires, they saw the fire a median 8 minutes *after* it was reported. And a system that cries wolf over March pasture burns gets switched off by April.

## What Firewatch does

- **Detect:** combines cheap signals into one event per fire: electric co-op line faults on fire-weather days, satellite hotspots (VIIRS, MODIS, GOES), and texted reports from ranchers and lease pumpers.
- **Confirm without a drive-out:** an ML score separates wildfires from prescribed burns and refinery flares. Escalation needs two independent signals. Registered burns are suppressed. The nearest neighbors are asked by text: "See smoke? 1 yes, 2 no, 3 it's my burn."
- **Respond before the first engine:** the duty officer gets one text and replies PAGE. Paging goes through county dispatch. The downwind rancher, the lease water truck, and disc owners get a text with direction and an arrival estimate from the spread model, and mutual aid is drafted if too few volunteers respond.

Humans decide every page. Every signal, text, and decision is logged on the event.

**Status:** the satellite path (ingest, clustering, enrichment, ML scoring, map, 3D spread, logged actions) is built and evaluated on real Kansas data. The whole chain also runs end to end in the **Cottonwood Creek replay**: line fault, neighbor texts, two-source confirmation, PAGE by text, downwind warnings with arrival estimates, mutual aid, and a registered burn that texts nobody. Texts go to a simulated outbox. Twilio sending is written but not yet tried on a real phone. The plan, honest cost numbers, and failure modes are in [docs/PLAN.md](docs/PLAN.md).

## Docs

- [Build plan](docs/PLAN.md): the scenario in minutes, whole-chain design, constraints, failure modes, cost and who pays, evidence, weekend scope, next step.
- [Design](docs/DESIGN.md): data model, pipeline, signals and confirmation rules, scoring, response planner and messaging, spread model, API, UI.

## Stack

| Layer | Tech |
|---|---|
| Backend / ML | Python, FastAPI, pandas, scikit-learn, XGBoost, SQLite |
| Frontend | React, Vite, TypeScript, MapLibre GL JS, deck.gl, Tailwind |
| 3D | MapLibre terrain (AWS Terrain Tiles) + deck.gl overlays |
| Data | NASA FIRMS, Open-Meteo, NWS, NIFC WFIGS, OpenStreetMap |

Every data source is free and needs no map token. The only data key is a free [FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/). Twilio is the one paid service (about 1 cent per text), used only for live texting; sample mode and the scenario use a simulated outbox.

## Repository layout

```
backend/app/   FastAPI app: ingestion, clustering, enrichment, scoring, spread simulation
backend/ml/    Historical download, training-set builder, model training, evaluation report
frontend/      React dashboard and 3D spread preview
docs/          Plan and design
```

## Getting started

Requires Python 3.12+ and Node 22+.

```bash
cp .env.example .env            # add FIRMS_MAP_KEY for MODE=live; MODE=sample works without it

# backend (http://127.0.0.1:8000, API under /api)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/pytest                 # tests

# frontend (http://localhost:5173)
cd frontend
npm install && npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000` (override with `API_PROXY_TARGET`). It uses `127.0.0.1` rather than `localhost` so it can't hit some other service bound to IPv6 port 8000.

`MODE=sample` replays historical and synthetic Kansas events through the full pipeline offline, so it's the default for development and demos. On first start the backend loads all fixtures from `backend/data/samples/`; **Replay sample** in the top bar re-feeds them pass by pass over 60 seconds. Fixture weather was backfilled from the Open-Meteo archive with `.venv/bin/python -m scripts.backfill_sample_weather`.

**Run scenario** in the top bar replays the Cottonwood Creek incident (1:50 pm line fault on a High fire-danger Saturday) at 2 seconds per scenario minute. A strip under the top bar compares today's timeline (on scene at T+62) with Firewatch's as it happens, and the drawer shows the evidence, the response, and every text. The district (a 450 sq mi stand-in boundary in Butler County, its settings, and a fictional roster) lives in `backend/data/districts/cottonwood-creek/`, and the script in `backend/data/scenarios/cottonwood-creek.json`.

On macOS, XGBoost needs OpenMP: `brew install libomp`.

### Map layers and the scorer

`backend/data/layers/` holds real Kansas data: transmission lines ≥ 115 kV, transmission substations, and towns from OpenStreetMap (counties from Census boundaries), plus persistent industrial heat sources derived from ten years of FIRMS detections. `backend/data/model/` holds the trained scorer. Both are committed, so the app runs without rebuilding them. To rebuild:

```bash
cd backend
.venv/bin/pip install -r requirements-ml.txt
.venv/bin/python -m scripts.fetch_osm_layers          # OSM lines, substations, towns (~1 min)
.venv/bin/python -m ml.download                        # FIRMS Kansas archive 2016–2025 + WFIGS incidents (~5 min)
.venv/bin/python -m ml.build_dataset --rebuild-history # replay history, derive heat sources, label, build features (~15 min)
.venv/bin/python -m ml.train                           # evaluate, export data/model/, write ml/report.md
.venv/bin/python -m ml.analyze                         # deeper analyses + figures for the research report (~2 min)
```

Results are in [backend/ml/report.md](backend/ml/report.md); the full analysis of the v1 training run is in [docs/research/scorer-v1-training-run.md](docs/research/scorer-v1-training-run.md). `SCORER=auto` (default) uses the model when it's present and weather is available, and falls back to the rules scorer otherwise.

| Path | What it is |
|---|---|
| `backend/app/ingest/` | FIRMS CSV fetch and parse, Open-Meteo weather |
| `backend/app/features/` | Event clustering (2 km / 12 h) and feature enrichment |
| `backend/app/scoring/` | XGBoost scorer v1 with per-alert reasons, rules fallback, guardrails, suppression reasons |
| `backend/ml/` | Training pipeline and evaluation report |
| `backend/app/sim/` | Grass-fire spread estimate (arrival-time grid → isochrones, impacts) |
| `backend/app/signals.py`, `confirm.py` | Line faults and texted reports on events; the two-source level rules and burn registry |
| `backend/app/notify.py` | SMS gateway (outbox / Twilio), templates, neighbor asks, no-answer ladder, PAGE / NO / SEND, downwind warnings, mutual aid, inbound keywords |
| `backend/app/scenario.py` | Scenario replay on its own clock |
| `backend/app/main.py` | FastAPI routes: alerts, actions, decisions, signals, SMS, simulate, layers, district, scenario, health, sample replay |
| `frontend/src/pages/Dashboard.tsx` | Alert list, map, detail drawer, actions, scenario strip |
| `frontend/src/pages/Spread3D.tsx` | 3D terrain spread preview with wind override |

## Data sources and APIs

Every data source is free with no paid tier. "Fresh" figures are single readings taken on 2026-11-07 unless noted, not guarantees. Twilio is the one paid service, but it is a texting service, not a data source (see the last row).

Status values:
- `on map`: fetched and shown behind a toggle in the Layers panel.
- `background`: used by the app, no toggle.
- `needs key`: built but off until a free FIRMS MAP_KEY is set.
- `script`: fetched once by a script in `backend/scripts`, not polled.
- `training only`: used by `backend/ml` or build scripts.
- `planned`: not wired yet.

| API | What it provides | Why we use it | How fresh | Key needed | Cost and license | Status |
|---|---|---|---|---|---|---|
| NASA FIRMS Area API | VIIRS and MODIS fire detections (plus `LANDSAT_NRT` and the real-time `*_RT` feeds) | Core detection stream | Real time, under 60 seconds after overpass (NASA figure) | Yes (free MAP_KEY) | Free, NASA open data | needs key |
| NASA FIRMS yearly CSVs | US detections back to 2016 | Model training history | Yearly | No | Free, NASA open data | training only |
| Open-Meteo forecast | Hourly wind, humidity, temperature, gusts, dew point, pressure, VPD | Fire weather for alerts and the dry-air grid | Hourly model run, about 2 hours behind | No | Free tier is non-commercial only, CC BY 4.0. A sold product would self-host it (AGPLv3) | on map |
| Open-Meteo archive | Historical hourly weather | Model training features | Days behind | No | Same as above | training only |
| AWS Terrain Tiles | Terrarium elevation tiles | Terrain, slope, 3D view | Static | No | Free, open data (USGS and other sources) | background |
| OSM Overpass (`overpass-api.de` and `overpass.kumi.systems`) | Power lines, substations, towns, distribution lines | Line exposure and context layers | Fetched once by script | No | Free, ODbL, (c) OpenStreetMap contributors | script |
| Plotly counties GeoJSON | US county boundaries (Census) | County names | Static | No | Free, public domain Census data | script |
| NIFC WFIGS incident locations (training copy) | Historical reported wildfires and prescribed burns | Training labels | Static download | No | Free, public domain | training only |
| OpenFreeMap | Dark vector basemap | Base map | Continuous | No | Free, no limits, OpenStreetMap data (ODbL) | background |
| USGS Imagery Only (The National Map) | Aerial imagery tiles | 3D view imagery | Imagery 2017 to 2021, zoom 16 max | No | Free, public domain | background |
| NASA FIRMS Landsat NRT (`LANDSAT_NRT`) | 30 m fire detections from Landsat overpasses | Fine-resolution cross-check | A few hours after overpass | Yes (same free MAP_KEY) | Free, NASA open data | needs key |
| OSM distribution lines (`power=minor_line`) | Lower-voltage lines, partial coverage in Kansas | Context layer only, never used for the model's line distance | Fetched once by script | No | Free, ODbL, (c) OpenStreetMap contributors | script |
| NWS alerts (`api.weather.gov`) | Fire, wind, smoke and dust warnings for Kansas | Official hazard alerts | Real time | No (User-Agent required) | Free, US government | on map |
| Iowa Mesonet storm reports (LSR) | Human reports of fires and downed lines or poles | Ground truth hints | As issued | No | Free | on map |
| NIFC WFIGS incidents, current | Currently known incident points | New known incidents | Last edit 14 min old when sampled | No | Free, public domain | on map |
| NIFC WFIGS perimeters, current | Known fire footprints | Avoid re-alerting on known fires | Last edit 38 min old when sampled | No | Free, public domain | on map |
| METAR via aviationweather.gov (backup: Iowa Mesonet ASOS) | Temperature, dew point, pressure, wind at 54 Kansas stations | Measured humidity | Hourly plus specials, about 6 min old when sampled | No | Free, US government | on map |
| NOAA SPC fire weather outlooks | Official dry thunderstorm and wind/RH risk areas | Official risk areas | A few issues a day | No | Free, NOAA does not endorse this app | on map |
| NOAA HMS fire points | Analyst-checked fire detections | Cross-check detections | Last update 80 min old when sampled | No | Free, NOAA open data | on map |
| GOES-19 and GOES-18 fire detection (`ABI-L2-FDCC`, `noaa-goes19`, `noaa-goes18` on S3) | Geostationary fire pixels | Fastest free fire signal | Every 5 min, 3.5 min after scan start when sampled (fetch about 1 s) | No | Free, NOAA open data | on map |
| GOES lightning (`GLM-L2-LCFA`, `noaa-goes19`) | Lightning flashes | Near-instant ignition clue | 20-second files, 15 newest (5 min window) polled every 60 s; cold fetch about 5 s, cached 0.4 s | No | Free, NOAA open data | on map |
| GOES smoke (`ABI-L2-ADPC`, `noaa-goes19`) | Smoke mask | Smoke detection, daytime only | Every 5 min, polled every 300 s; scan start about 4.4 min old at fetch, fetch about 1 s; night returns 0 points with a notice | No | Free, NOAA open data | on map |
| RTMA-RU 2.5 km (`noaa-rtma-pds`) | Gridded near-surface analysis | Freshest dry-air map, blends real observations | `2dvaranl` file read by `.idx` byte range (3 messages, about 19 MB); polled every 900 s; file valid 01:45 UTC was listed by about 02:03 (about 18 min lag), fetch about 3 s; feeds `/api/risk/grid` when under 2 h old, else Open-Meteo | No | Free, NOAA open data | on map |
| NOAA HMS smoke polygons (`satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/`) | Analyst-drawn smoke, KML or shapefile | Smoke context | 1 to 2 updates a day | No | Free, NOAA open data | planned |
| gridMET | ERC and fuel moisture, daily NetCDF | Fire danger and fuel state | Daily | No | Free, CC0 | planned |
| US Drought Monitor | Weekly drought GeoJSON | Long-term dryness | Weekly | No | Free, credit required: "courtesy of NDMC, via https://droughtmonitor.unl.edu" | planned |
| USDA CropScape Cropland Data Layer | Land cover | Tells pasture from crop stubble, cutting false alarms | Yearly | No | Free, public domain | planned |
| LANDFIRE fuels | Fuel type | Fuel type for spread | Versioned releases | No | Free, public domain | planned |
| NOAA Storm Events | Reported storm and fire events, monthly CSV | Validation | 2 to 3 month lag | No | Free, US government | planned |
| Iowa Mesonet ASOS history | Historical station CSV | Wind history for validation | Archive | No | Free | planned |
| Twilio SMS (service, not a data source) | Sends texts to contacts | Neighbor asks, PAGE, downwind warnings | On send | Yes (account SID, token, number) | Paid, about 1 cent per message. Only used when `MODE=live` and `SMS_GATEWAY=twilio`; otherwise simulated outbox (`backend/app/notify.py` `gateway_for`) | background |

The free Open-Meteo tier is for non-commercial use only; a commercial product would self-host Open-Meteo (AGPLv3) instead.

Later (all free): NEXRAD radar, HRRR-Smoke, AirNow, OpenAQ, Copernicus.

Not used, on purpose: Kansas Mesonet, Synoptic, restricted MADIS and PurpleAir (each needs a key, a paid tier, or terms that block this use).

## Data attribution

NASA FIRMS (LANCE) · Open-Meteo (CC BY 4.0) · NOAA / National Weather Service · NIFC WFIGS / IRWIN · © OpenStreetMap contributors (ODbL) · AWS Terrain Tiles · US Census TIGER · EPA ecoregions.
