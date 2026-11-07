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

**Status:** the satellite path (ingest, clustering, enrichment, ML scoring, map, 3D spread, logged actions) is built and evaluated on real Kansas data. The line-fault, SMS, and response pieces are designed in [docs/DESIGN.md](docs/DESIGN.md) (sections 4.5 and 5.6) and are this weekend's build. The plan, honest cost numbers, and failure modes are in [docs/PLAN.md](docs/PLAN.md).

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

No paid services or map tokens are required. The only key is a free [FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/).

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
```

Results are in [backend/ml/report.md](backend/ml/report.md). `SCORER=auto` (default) uses the model when it's present and weather is available, and falls back to the rules scorer otherwise.

| Path | What it is |
|---|---|
| `backend/app/ingest/` | FIRMS CSV fetch and parse, Open-Meteo weather |
| `backend/app/features/` | Event clustering (2 km / 12 h) and feature enrichment |
| `backend/app/scoring/` | XGBoost scorer v1 with per-alert reasons, rules fallback, guardrails, suppression reasons |
| `backend/ml/` | Training pipeline and evaluation report |
| `backend/app/sim/` | Grass-fire spread estimate (arrival-time grid → isochrones, impacts) |
| `backend/app/main.py` | FastAPI routes: alerts, actions, simulate, layers, health, sample replay |
| `frontend/src/pages/Dashboard.tsx` | Alert list, map, detail drawer, actions |
| `frontend/src/pages/Spread3D.tsx` | 3D terrain spread preview with wind override |

## Data attribution

NASA FIRMS (LANCE) · Open-Meteo (CC BY 4.0) · NOAA / National Weather Service · NIFC WFIGS / IRWIN · © OpenStreetMap contributors (ODbL) · AWS Terrain Tiles · US Census TIGER · EPA ecoregions.
