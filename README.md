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

```mermaid
flowchart LR
  subgraph Detect
    LF["Co-op line fault<br/>(lockout, High fire danger)"]
    SAT["Satellite hotspot<br/>VIIRS / MODIS / GOES"]
    TXT["Texted report<br/>FIRE"]
  end

  subgraph Confirm
    EV["One event per fire<br/>(3 km / 6 h)"]
    ML["ML score + guardrails"]
    BURN{"Registered burn,<br/>not escaped?"}
    LVL{"Independent<br/>sources"}
    ASK["Ask 3 nearest neighbors<br/>1 smoke · 2 no · 3 my burn"]
  end

  subgraph Respond
    MON["Monitor<br/>texts nobody"]
    FYI["Investigate<br/>duty officer FYI"]
    ESC["Escalate<br/>duty officer: Reply PAGE"]
    LAD["No answer:<br/>chief at 3 min, dispatch at 9 min"]
    PAGE["PAGE<br/>county dispatch + volunteers"]
    DW["Downwind ranchers:<br/>arrival estimate"]
    EQ["Water truck / disc:<br/>can you help?"]
    MA["Mutual aid draft<br/>chief replies SEND"]
  end

  LF --> EV
  SAT --> EV
  TXT --> EV
  SAT --> ML --> EV
  EV --> BURN
  BURN -- yes --> MON
  BURN -- no --> LVL
  LVL -- none --> MON
  LVL -- one --> FYI
  FYI --> ASK
  ASK -- "reply 1" --> EV
  LVL -- "two, or strong satellite" --> ESC
  ESC -.-> LAD
  ESC -- "duty officer replies PAGE" --> PAGE
  PAGE --> DW
  PAGE --> EQ
  PAGE -- "too big for 2 trucks,<br/>or under 2 responding" --> MA
```

For the whole system, open the [system map](docs/system-map.html) or read the [system flows](docs/SYSTEM-FLOWS.md).
In the Cottonwood Creek replay this chain pages at T+9 instead of today's 911 call at T+31. The first truck arrives at T+40 to about 220 acres instead of 520 at T+62 (spread model estimate, not field data).

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
```

Public board (the only thing a tunnel may point at). The tunnel points at port 8012 and never at the main API or Vite. The main server must also run for timers and alerts. Set `FORWARDED_IP_HEADER` (for example `cf-connecting-ip`) so rate limits see the visitor, not the tunnel. Run `npm run build` in frontend first.

```
.venv/bin/uvicorn app.public_app:app --host 127.0.0.1 --port 8012
```

```
.venv/bin/pytest                 # tests

# frontend (http://localhost:5173)
cd frontend
npm install && npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000` (override with `API_PROXY_TARGET`). It uses `127.0.0.1` rather than `localhost` so it can't hit some other service bound to IPv6 port 8000.

`MODE=sample` replays historical and synthetic Kansas events through the full pipeline offline, so it's the default for development and demos. On first start the backend loads all fixtures from `backend/data/samples/`; **Replay sample** in the top bar re-feeds them pass by pass over 60 seconds. Fixture weather was backfilled from the Open-Meteo archive with `.venv/bin/python -m scripts.backfill_sample_weather`.

**Run scenario** in the top bar, in sample and live mode, replays the scenario picked beside it: the three packet replays, or the Cottonwood Creek incident (1:50 pm line fault on a High fire-danger Saturday) at 2 seconds per scenario minute. A strip under the top bar compares today's timeline (on scene at T+62) with Firewatch's as it happens, and the drawer shows the evidence, the response, and every text. The district (a 450 sq mi stand-in boundary in Butler County, its settings, and a fictional roster) lives in `backend/data/districts/cottonwood-creek/`, and the script in `backend/data/scenarios/cottonwood-creek.json`.

Replays record SMS in the outbox and never send a real text, in any mode. A radio linked in the roster still gets its mesh message, so a demo can show one. The packet replays use the packet's facts: nobody answers, the driver has no signal until minute 31, and nobody is within 4 miles.

On macOS, XGBoost needs OpenMP: `brew install libomp`.

### Mesh radios (Meshtastic)

Firewatch can send its texts over a Meshtastic LoRa mesh, for volunteers and trucks out of cell coverage, and take replies and GPS positions back. It's built for the SenseCAP T1000-E, but any Meshtastic radio works. See [DESIGN.md section 5.7](docs/DESIGN.md#57-mesh-radios-meshtastic).

1. On each radio, use the Meshtastic phone app to set the LoRa region to **US** and put both radios on the same primary channel. A real district would use a private channel with its own key. On the field radio, shorten the position broadcast interval so the map stays current.
2. Plug the station radio into the server with its USB cable. Run `backend/.venv/bin/meshtastic --info` to confirm it's connected and read its node ID. Keep phones off the station radio while the server is using it.
3. Put the field radio's node ID (`!a1b2c3d4`, shown in the Meshtastic app) in the `mesh_id` column of `backend/data/districts/cottonwood-creek/roster.csv`, on the row of whoever carries it. For the demo, use the duty officer. The radio also appears at `GET /api/mesh/nodes` once the station has heard it.
4. Set `MESH_GATEWAY=serial` in `.env` (and `MESH_DEVICE=/dev/cu.usbmodem…` if the server has more than one serial device), then restart the backend. **MESH** appears in the top bar.
5. Run the scenario. The field radio buzzes with the duty officer's texts. Reply `PAGE` in the Meshtastic app's direct-message thread from the station radio. Each mesh text in the drawer shows **DELIVERED** once that radio acknowledges it.

### Tower sensor nodes (temperature, humidity, smoke)

Mesh relays on elevators and water towers can report temperature, humidity, and PM2.5/PM10, and raise a smoke-sensor signal. See [DESIGN.md section 5.8](docs/DESIGN.md#58-tower-sensor-nodes). Rough parts list per node:

| Part | ~Cost |
|---|---|
| RAK WisBlock starter kit (RAK19007 base with solar charger + RAK4631 nRF52840/LoRa core), from a US distributor | $35 |
| Weatherproof junction box + 2–3 W, 6 V solar panel | $25 |
| Two 18650 cells | $10 |
| Outdoor 915 MHz antenna + pigtail adapter | $27 |
| RAK12039 particulate sensor (Plantower PMSA003I, I²C; Meshtastic doesn't read the cheaper serial version) | $38 |
| RAK1901 temperature/humidity sensor (SHTC3) | $9 |
| Vented radiation shield for the sensors (they can't sit inside the sealed box) | $5 |
| Mount, cable, wiring | $8 |
| **Per node** | **~$157** |

A county: 6 nodes ($942) + a station radio (~$45) + an optional duty-officer T1000-E ($51) ≈ **$1,040**, about $1,140 with spares. No monthly fees. Costs, coverage, grants, and a comparison with Dryad Silvanet are in [docs/research/hardware-pricing.txt](docs/research/hardware-pricing.txt).

1. Flash Meshtastic, set region **US** and the district's channel, role **Router**.
2. Enable telemetry: environment metrics and air quality, both on a 5-minute interval.
3. Set a **fixed position** at the tower's coordinates. Without one, the node's readings are stored but it raises no smoke signals.
4. Mount the sensors in the shield, facing open air, with the antenna as high as the structure allows.

The map shows each node's latest PM2.5, °C, and RH. Thresholds are in `backend/data/districts/<district>/settings.json` (`smoke_pm25_rise`, `smoke_fine_ratio`, `smoke_regional_share`, `smoke_repeat_min`).

### Region planner (where to put a sensor network)

Open **Planner** in the top bar (`/planner`) and pick a fire district or any Kansas county. It lays out the mixed bare/rich design from [sensors/README.md](sensors/README.md):
- where each 15-acre plot of 7 bare and 2 rich nodes goes;
- where the nodes sit inside the plot;
- which elevators, substations, or high ground relay them to the station bridge;
- what it costs.

It's built from the region's geography and climate:
- reported wildfires and ten years of satellite-detected burning;
- power lines, substations, towns, and Flint Hills tallgrass;
- terrain line of sight for every radio link;
- ten years of hourly fire-weather winds, so sensors sit downwind of what they watch;
- winter and fire-season sun, to check the solar budget.

Change the plot count or switch to a budget, the nodes per plot, and the assumed detection ranges, and the plan updates. Each plot lists why it was chosen and what to check on site. The method and its limits are in [DESIGN.md section 5.9](docs/DESIGN.md#59-region-planner).

Climate summaries are cached per 0.25° cell in `backend/data/climate/`. A county that isn't cached yet is fetched once from the Open-Meteo archive, which takes a few seconds. Terrain tiles are fetched once and cached. The planner's history layers (`wildfire_history.geojson`, `burn_activity.json`, `counties.geojson`) are rebuilt from the ML downloads with `.venv/bin/python -m ml.planner_layers`.

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
| `backend/app/mesh.py` | Meshtastic bridge: texts out as acknowledged direct messages, replies in, radio positions and crew distances |
| `backend/app/sensors.py` | Tower sensor telemetry: readings, the smoke rule (baseline, dust check, regional check), local temperature and humidity |
| `backend/app/planner.py`, `climate.py` | Region planner: priority grid, wind-weighted plot siting, plot layout, relay routing with terrain line of sight, power check, bill of materials; fire-weather climatology |
| `backend/app/scenario.py` | Scenario replay on its own clock |
| `backend/app/main.py` | FastAPI routes: alerts, actions, decisions, signals, SMS, simulate, layers, district, scenario, health, sample replay |
| `frontend/src/pages/Dashboard.tsx` | Alert list, map, detail drawer, actions, scenario strip |
| `frontend/src/pages/Spread3D.tsx` | 3D terrain spread preview with wind override |
| `frontend/src/pages/Planner.tsx` | Region planner page: controls, climate, power, plots, relays, bill of materials, map |

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
| NOAA HMS fire points | Analyst-checked fire detections | Most sensitive free fire source found: most of its points come from NOAA's NGFS system, which we also pull directly (see the NGFS row). Slower than raw GOES | Last update 80 min old when sampled | No | Free, NOAA open data | on map |
| GOES-19 and GOES-18 fire detection (`ABI-L2-FDCC`, `noaa-goes19`, `noaa-goes18` on S3) | Geostationary fire pixels | Fast signal for large, hot fires. Less sensitive than NGFS: on 2026-11-06 it showed 0 Kansas pixels in about 24 sampled afternoon scans while HMS logged 7 Kansas sites, mostly from NGFS. Locations matched HMS within 0.1 km (median) | Every 5 min, 3.5 min after scan start when sampled (fetch about 1 s) | No | Free, NOAA open data | on map |
| NOAA NGFS detections (`fire.data.nesdis.noaa.gov/api/ogc/detections`, six `ngfs_schema.ngfs_detections_scene_*` collections) | GOES East and West fire detections with type (`Possible Wildland Fire`, `Industrial`, Oil/Gas and others), county and FRP | Off by default on the map. Never fed to the model, the 27 features, gfdi or scoring (the model trained on VIIRS and MODIS only). It can add one signal to the confirmation rule: a tracked feature labeled `Possible Wildland Fire`, seen in two separate scans and not covered by a registered burn. That signal counts as a satellite, so NGFS alone reaches Investigate (an FYI text to the duty officer) and never escalates alone; a person decides every page. It catches fires GOES FDC misses. NOAA beta, informational only. Data may be delayed or unavailable. Not for operational decisions. | NOAA states every 5 minutes. Newest GOES East row nationwide was 5.2 and 8.9 minutes behind the clock (2 samples, 2026-11-07). Kansas rows appear only when Kansas has a detection | No | Free NOAA service, no key. The portal states the data is provided as is, for information only; no license is asserted here | on map (off by default) |
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

NGFS vs GOES, measured: NGFS GOES East CONUS, 24 hours ending 2026-11-07 02:28 UTC, returned 84 Kansas rows in 3 tracked features (Sumner County 35, Sedgwick County 34, Riley County 15); 50 were `Possible Wildland Fire` and 34 `Industrial`. The HMS file for 2026-11-06 in a Kansas box had 56 rows: 50 with the NGFS method and 6 VIIRS. The two windows differ by a few hours, so read this as scale, not an exact match. Field note: the NGFS rows carry `feature_detection_duration`; earlier notes called it `feature_tracking_duration`.

The free Open-Meteo tier is for non-commercial use only; a commercial product would self-host Open-Meteo (AGPLv3) instead.

Later (all free): NEXRAD radar, HRRR-Smoke, AirNow, OpenAQ, Copernicus.

Not used, on purpose: Kansas Mesonet, Synoptic, restricted MADIS and PurpleAir (each needs a key, a paid tier, or terms that block this use).

## Data attribution

NASA FIRMS (LANCE) · Open-Meteo (CC BY 4.0), including ERA5 reanalysis (Copernicus Climate Change Service) · NOAA / National Weather Service · NIFC WFIGS / IRWIN · © OpenStreetMap contributors (ODbL) · AWS Terrain Tiles · US Census TIGER · EPA ecoregions.
