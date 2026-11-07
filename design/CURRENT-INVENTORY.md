# Current build inventory (shane branch, MODE=sample)

Captured 2026-11-06 at 1440x900. Screens in `design/screens/png/`. Facts only, from the code and from running the app.

How it ran: backend `MODE=sample` (port 8011, because 8000 was already taken by another local Node process), Vite dev server on 5173 proxying `/api` to the backend. On startup the backend loads all 9 fixtures from `backend/data/samples/` through the real pipeline (cluster, enrich, score), so the dashboard is never empty. The Replay button clears sample data and re-feeds the fixtures over 60 s (`POST /api/sample/replay`).

Routes (frontend/src/App.tsx): `/` and `/alerts/:id` (Dashboard; drawer open when an id is present), `/alerts/:id/3d` (Spread3D). Nothing else. Desktop-only layout; no responsive or phone layout exists.

## Screen 1: Dashboard (current-01-dashboard.png, 06-suppressed-tab, 08/09 replay)
- Shows: top bar (FIREWATCH, "SAMPLE REPLAY" badge, per-source status chips FIRMS and WX showing "SAMPLE", UTC and Central clock, operator name field, Replay button); left Alert queue with tabs Active / Escalate / Suppressed and counts; MapLibre map of Kansas with alert diamonds (red = escalate, amber = investigate, hollow square = monitor), score labels, transmission lines, known heat sources, optional Flint Hills layer, layer/symbology panel; footer counts (ESC, INV, SUPPRESSED breakdown), key hints, "PUBLIC DATA ONLY", sync time.
- Sample data seen: 4 active, all ESC (FW-0001 94 Englewood Clark Co. 2017; FW-0008 87 Paradise Russell Co. 2021; FW-0005 79 Kiowa Barber Co. 2016; FW-0009 78 Hays Ellis Co. 2025) and 5 suppressed (1 static heat source El Dorado, 3 likely prescribed burns Chase Co., 1 low signal Nickerson).
- Replay states: early replay shows a single INV 56 alert that later grows to ESC 94 (score rises with more satellite passes); mid-replay 2 INV, 4 suppressed.
- User can: switch tabs, click footer suppressed summary to toggle the Suppressed tab, hover/click queue items or map markers, toggle map layers, edit operator name (stored in localStorage), press Replay. Queue polls every 5 s; health every 15 s.
- Data source: sample fixtures only (dates are historical: 2016, 2017, 2021, 2024, 2025). Times are shown in CST/CDT labels.

## Screen 2: Alert drawer (current-02-alert-drawer, 04-scrolled, 07-suppressed-drawer)
- Shows: track id (FW-000N), big 0-100 score, recommendation chip (Escalate / Investigate / Monitor), status (NEW etc.), place label (distance and bearing to nearest town, county), lat/lon, first/last seen, scorer (`rules-v0`), data tag (SAMPLE); "Why this score" list of signed point contributions with bars and score trend (e.g. 56 > 88 > 94); optional guardrail note; optional degraded-mode warning when weather missing; Conditions (fire danger index band + GFDI, wind speed/direction, gust, temp, RH, 72 h rain, source "open-meteo-archive"); Nearby assets with distance (power line 3.1 km, substation 8.9 km, town 13.2 km; static source for El Dorado refinery 0.1 km); Detections table (satellite, sensor, time, FRP MW, confidence); Log of actions with operator and note ("Track opened by pipeline").
- User can: Ack, Escalate, Dismiss (buttons plus keys A, E, D), Reopen (for non-new status), free-text note with 4 quick chips (Paged VFD, Known Rx burn, Industrial site, Called landowner), open 3D (key V), close (Esc). Actions are recorded under the typed operator name. Dismiss has no confirm and no visible undo other than Reopen.
- Data source: `GET /api/alerts/{id}` from fixtures through scoring.

## Screen 3: 3D spread preview (current-03-spread3d, 05-spread3d-wind-override)
- Shows: header (Back, track, score, place, recommendation), badge "ESTIMATE · NOT AN OPERATIONAL PREDICTION"; satellite-textured 3D terrain (AWS terrain tiles) with ignition point, animated 60-minute spread polygon, wind particles, power line and place labels; elapsed panel (T+ minutes, area in ha, head spread rate km/h, wind, speed); wind panel (observed wind, Override wind checkbox with speed and direction sliders); Impacts 60 min with ETA (e.g. "Sample 345 kV (hand-drawn) REACHED"); Assumptions (RH, temp, curing %, L:B ratio, terrain source); timeline scrubber 0-60 min with play/pause, 1x/4x, Reset, impact markers.
- User can: play/pause, scrub, change speed, reset, override wind speed and direction (re-runs `GET /alerts/{id}/simulate`), go back. No export, no share, no print.
- Starbuck-like event: FW-0001 (fixture 01-starbuck-2017, "8 mi ENE of Englewood, Clark Co."). At T+60 area 1,272 ha, head rate 8.64 km/h, 45 km/h SW wind reaches the 345 kV sample line.
- Data source: simulation run server-side from sample event features; spread model is "estimate"; sample power line is hand-drawn.

## Backend endpoints (backend/app/main.py, all under /api)
- `GET /alerts`: list scored events with filters (min_score, status, since_hours, include_monitor); returns alerts plus suppressed counts by reason.
- `GET /alerts/{id}`: full detail (features, weather, detections, score history, reasons, actions, nearest assets).
- `POST /alerts/{id}/actions`: acknowledge / escalate / dismiss / reopen with operator and optional note; enforces allowed status transitions.
- `GET /alerts/{id}/simulate`: 5-120 min spread simulation, optional wind speed/direction override, cached.
- `GET /layers/{name}`: map layers (towns, power_lines, substations, static_sources, flint_hills).
- `GET /health`: mode, FIRMS key present, replay running, per-source status (firms, open_meteo); in sample mode every source reports status "sample" with null age.
- `POST /ingest/run`: manual FIRMS poll (live mode only; 400 in sample mode).
- `POST /sample/replay`: start timed replay (5-600 s, default 60).
- `POST /sample/load`: load all fixtures immediately.
- `GET /sample/fixtures`: fixture slug, title, expected outcome, story.
- `GET /`: root.
- Live mode (not run): background loop polls FIRMS every `poll_minutes` (5); thresholds escalate 70, investigate 40.
- No endpoints for: notifications, users/roles, reports, logs export, CAP, timelines.

## Gaps against the proposed needs
- Phone view for a chief: none. Fixed desktop layout (240+ px queue, map, 400 px drawer, 10 px mono labels); no responsive breakpoints seen, no mobile route. Not tested at phone width.
- Text and radio-pager delivery: none. No SMS, email, push, pager or webhook code or endpoint; alerts are only visible to someone watching the dashboard (5 s poll).
- Burn-call log: none. Only per-alert action log with note; no log of burn permits or calls, no Rx-burn registry. "Known Rx burn" is a note chip and prescribed burns are suppressed by a heuristic.
- Line-fault input: none. Power lines are a static map layer and a nearby-asset distance; no utility fault feed or manual fault entry.
- Public reports: none. "PUBLIC DATA ONLY" in the footer; no 911 / citizen / social input.
- List of who is in the path: partial. Nearby assets (nearest power line, substation, town) and 3D "Impacts" (assets reached with ETA); no residences, people, roads, landowners, or responder list.
- Offline / one-bar behavior: none. No service worker, cache or offline state; if backend is down the footer shows "BACKEND UNREACHABLE" and the top bar flags it; map tiles load from the network (OSM/Carto, AWS terrain, satellite imagery); 3D view needs heavy tiles.
- Data-age per source: partial. Top bar has chips for FIRMS and WX with age in minutes and ok/stale/down (under 15 / under 60 / over); in sample mode shows "SAMPLE" and no age. No per-satellite age (VIIRS vs MODIS vs GOES), per-detection ages are only in the drawer table timestamps, and only two sources are tracked.
- CAP export: none. No Common Alerting Protocol or any export (CSV/PDF/JSON download) in the UI or API.
- Today-vs-Firewatch timeline: none. Drawer shows score trend and a log; 3D shows forward spread timeline. No comparison of "when 911/others knew" vs "when Firewatch detected".
