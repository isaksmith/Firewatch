# Notes for coding agents

FireWatch: a FastAPI backend (`backend/`), a React + Vite console (`frontend/`), an Expo phone app (`mobile/`), and sensor hardware designs (`sensors/`). Setup is in [README.md](README.md#quick-start); the full design is in [docs/DESIGN.md](docs/DESIGN.md).

## Run it

All settings live in the repo-root `.env`, copied from `.env.example`. Both servers read it.

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000   # API under /api
cd frontend && npm run dev                                          # console on http://localhost:5173
```

- **Sample mode** (`MODE=sample`, the default) needs no keys. Fixtures and scenarios replay offline, and admin routes work without a token.
- **Live demo** (`MODE=live`) needs `FIRMS_MAP_KEY` and `API_TOKEN`. Add `SENSOR_SIM=true` for the simulated FireNode sensor network. `OPENROUTER_API_KEY` is optional and turns on the LLM. See [README "Live demo"](README.md#live-demo).
- Without `API_TOKEN`, live mode refuses admin routes with `503 set API_TOKEN to use admin routes`. In the console, Run scenario and Ingest then do nothing.
- The Vite proxy reads `API_TOKEN` only at startup, so restart the frontend after changing it. Never put the token in a `VITE_` variable: those are compiled into the browser bundle.
- Any environment variable overrides `.env`, so `MODE=live SENSOR_SIM=1 uvicorn ...` works without editing the file.

## Test it

```bash
cd backend && .venv/bin/pytest          # about 650 tests, 2.5 min
cd frontend && npx tsc -b --noEmit && npx vite build
```

`.github/workflows/ci.yml` runs these, plus `npm run lint` and `node sensors/viewer/verify.mjs`, on every push to `main` and every pull request, from a clean checkout with no `frontend/dist` or data cache. The backend deploys only after its tests pass.

`backend/tests/conftest.py` gives every test its own database in sample mode and blanks the OpenRouter key, the radio, `API_TOKEN` and `SENSOR_SIM`, so a local `.env` can't leak into tests.

## Things that aren't obvious

- **Sample vs live data.** Rows have `is_sample`. Evidence joins only events with the same flag, so sample evidence never merges into a real alert, and sample events never send real texts. In live mode the alert list hides sample events, except scenario replays and smoke from simulated sensors.
- **Scenarios are scripted.** `backend/data/scenarios/*.json` holds made-up timelines with their own weather. They run through the real decision code but call no live APIs.
- **Simulated sensors** (`backend/app/sensor_sim.py`) send their telemetry through `mesh.handle_packet`, the same path real radios use. Node health is in `sensor_health.py`. Radio link down and stale sensors are separate verdicts (DESIGN.md section 5.12).
- **Tier views.** The Free / Paid / Offline switch (`frontend/src/lib/tier.ts`) only changes what the console shows. It isn't access control.
- **Product names in the UI:** FireWatchOS (the system), FireCast and FireCast Plus (the recommendation engine, plus the LLM), FireNode, made up of FireSense (sensors) and FireMesh (the network), and FireWatch Mobile. The wordmark stays FIREWATCH. See [docs/FEATURES.md](docs/FEATURES.md).
- **The LLM** (`llm.py`, `ask.py`, `bulletin.py`) writes only texted answers and channel updates, never the alerts themselves, and every use falls back to a template.
- **Be honest about status.** The docs mark unvalidated hardware and assumed numbers. Keep doing that: never present simulated or assumed values as measured.
