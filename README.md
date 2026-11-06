# Firewatch Confirmation Layer

**Early wildfire detection → ML confirmation → 3D response preview** for Kansas rural fire districts.

Built for [Firewatch 2026](https://wsuinnovationworks.com/) (WSU Innovation Works × Lockheed Martin Skunk Works, Nov 6–8, 2026).

## The problem

Most Kansas wildfires are found by a 911 call, minutes to hours after ignition, when the cheap window to stop them has closed. Satellites see many of them sooner, but raw satellite hotspots are noisy: on a spring day the Flint Hills produce dozens of detections from prescribed pasture burns, and refineries and ethanol plants show up as permanent "fires." A dispatcher can't triage that, so the data goes unused.

## What Firewatch does

1. **Ingests** NASA FIRMS satellite hotspots (VIIRS, MODIS, GOES) for Kansas every 5 minutes.
2. **Groups** pixels into events, so one fire produces one alert.
3. **Enriches** each event with wind, humidity, a grassland fire danger index, terrain, and distance to towns, power lines, and known industrial heat sources.
4. **Scores** each event 0–100 for "uncontrolled wildfire worth a response," with a recommendation (Monitor / Investigate / Escalate) and the top reasons behind it.
5. **Previews** likely spread over the next 60 minutes on 3D terrain, driven by wind and slope, with what it reaches and when.
6. **Logs** dispatcher actions (acknowledge / escalate / dismiss) for review and retraining.

Humans decide. Firewatch ranks, explains, and previews.

## Docs

- [Build plan](docs/PLAN.md): goals, data sources, milestones, team workstreams, demo script, cost and failure story.
- [Design](docs/DESIGN.md): data model, pipeline, feature spec, scoring, spread model, API contract, UI design.

## Stack

| Layer | Tech |
|---|---|
| Backend / ML | Python, FastAPI, pandas, scikit-learn, XGBoost, SQLite |
| Frontend | React, Vite, TypeScript, MapLibre GL JS, deck.gl, Tailwind |
| 3D | MapLibre terrain (AWS Terrain Tiles) + deck.gl overlays |
| Data | NASA FIRMS, Open-Meteo, NWS, NIFC WFIGS, OpenStreetMap |

No paid services or map tokens are required. The only key is a free [FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/).

## Repository layout

```
backend/    FastAPI app: ingestion, clustering, enrichment, scoring, spread simulation
ml/         Training-set builder, model training, evaluation report
frontend/   React dashboard and 3D spread preview
docs/       Plan and design
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

The power lines, substations, and refineries in `backend/data/layers/` are hand-drawn placeholders, not real infrastructure.

| Path | What it is |
|---|---|
| `backend/app/ingest/` | FIRMS CSV fetch and parse, Open-Meteo weather |
| `backend/app/features/` | Event clustering (2 km / 12 h) and feature enrichment |
| `backend/app/scoring/` | Rules scorer v0, guardrails, suppression reasons |
| `backend/app/sim/` | Grass-fire spread estimate (arrival-time grid → isochrones, impacts) |
| `backend/app/main.py` | FastAPI routes: alerts, actions, simulate, layers, health, sample replay |
| `frontend/src/pages/Dashboard.tsx` | Alert list, map, detail drawer, actions |
| `frontend/src/pages/Spread3D.tsx` | 3D terrain spread preview with wind override |

## Data attribution

NASA FIRMS (LANCE) · Open-Meteo (CC BY 4.0) · NOAA / National Weather Service · NIFC WFIGS / IRWIN · © OpenStreetMap contributors (ODbL) · AWS Terrain Tiles · US Census TIGER · EPA ecoregions.
