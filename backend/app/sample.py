"""Sample mode: frozen fixtures fed through the real pipeline (see docs/DESIGN.md section 10)."""

import asyncio
import json
import logging

from .config import DATA_DIR
from .db import connect
from .geo import haversine_km
from .pipeline import add_burn, process_detections, process_line_fault, process_report

log = logging.getLogger(__name__)
SAMPLES_DIR = DATA_DIR / "samples"

_replay_task: asyncio.Task | None = None


def load_fixtures() -> list[dict]:
    """Fixtures in replay order. A fixture may list `companions` (extra events it produces, such as the
    permitted burns in the Cottonwood Creek story); each becomes its own entry with its own `expected`."""
    fixtures = []
    for p in sorted(SAMPLES_DIR.glob("*.json")):
        fx = json.loads(p.read_text())
        fixtures.append(fx)
        for c in fx.get("companions", []):
            fixtures.append({
                "slug": c["slug"], "title": c["title"], "expected": c["expected"], "story": c.get("story"),
                "synthetic": fx.get("synthetic"), "approximate": fx.get("approximate"),
                "replay_offset_s": fx.get("replay_offset_s", 0), "virtual": True,
            })
    return sorted(fixtures, key=lambda f: f.get("replay_offset_s", 0))


def clear_sample_data() -> None:
    with connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM events WHERE is_sample = 1")]
        for table in ("scores", "actions"):
            conn.executemany(f"DELETE FROM {table} WHERE event_id = ?", [(i,) for i in ids])
        conn.execute("DELETE FROM signals WHERE is_sample = 1")
        conn.execute("DELETE FROM burns WHERE is_sample = 1")
        conn.execute("DELETE FROM detections WHERE is_sample = 1")
        conn.execute("DELETE FROM events WHERE is_sample = 1")


def timeline(fixture: dict) -> list[tuple[float, str, dict]]:
    """Burns, signals and detection passes in time order (ties: burn log, then signals, then satellites)."""
    items = []
    for kind, rank, rows in (("burn", 0, fixture.get("burns", [])), ("signal", 1, fixture.get("signals", [])),
                             ("pass", 2, fixture.get("passes", []))):
        for i, row in enumerate(rows):
            items.append((row["offset_s"], rank, i, kind, row))
    items.sort(key=lambda x: x[:3])
    return [(o, kind, row) for o, _, _, kind, row in items]


def _slug_for(fixture: dict, conn, event_id: int) -> str:
    """The main slug, unless the event sits on one of the fixture's companion events (the permitted burns)."""
    ev = conn.execute("SELECT lat, lon FROM events WHERE id = ?", (event_id,)).fetchone()
    for c in fixture.get("companions", []):
        if haversine_km(ev["lat"], ev["lon"], c["lat"], c["lon"]) <= 3.0:
            return c["slug"]
    return fixture["slug"]


def _apply(fixture: dict, kind: str, row: dict) -> None:
    with connect() as conn:
        touched: set[int] = set()
        if kind == "pass":
            touched = process_detections(conn, row["detections"], is_sample=True, weather=fixture["weather"])
        elif kind == "burn":
            add_burn(conn, row["lat"], row["lon"], row["start"], row["end"], row["called_in"], row["caller"],
                     row.get("label"), is_sample=True)
        elif row["kind"] == "line_fault":
            r = process_line_fault(conn, row["lat"], row["lon"], row["time"], row["circuit"], row.get("fault_kind", "fault"),
                                   is_sample=True, weather=fixture["weather"])
            touched = {r["event_id"]} if r["event_id"] else set()
        else:
            r = process_report(conn, row["lat"], row["lon"], row["time"], row["text"], row.get("phone"),
                               is_sample=True, weather=fixture["weather"])
            touched = {r["event_id"]}
        for event_id in touched:
            if conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone():
                conn.execute("UPDATE events SET sample_slug = ? WHERE id = ?", (_slug_for(fixture, conn, event_id), event_id))


def scenario_weather() -> dict | None:
    """Weather for signals posted by hand in sample mode: the first fixture that carries signals."""
    for fx in load_fixtures():
        if fx.get("signals") and fx.get("weather"):
            return fx["weather"]
    return None


def load_all_now() -> int:
    """Load every fixture immediately (used on startup so the dashboard is never empty)."""
    clear_sample_data()
    fixtures = load_fixtures()
    for fx in fixtures:
        for _, kind, row in timeline(fx):
            _apply(fx, kind, row)
    return len(fixtures)


def sample_is_current() -> bool:
    """True when every fixture slug already has an event, so an older database still picks up new fixtures."""
    with connect() as conn:
        have = {r[0] for r in conn.execute("SELECT DISTINCT sample_slug FROM events WHERE is_sample = 1")}
    return {fx["slug"] for fx in load_fixtures()} <= have


def has_sample_events() -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM events WHERE is_sample = 1 LIMIT 1").fetchone() is not None


async def _replay(duration_s: float) -> None:
    fixtures = load_fixtures()
    schedule = []
    for fx in fixtures:
        for at, kind, row in timeline(fx):
            schedule.append((fx.get("replay_offset_s", 0) + at, fx, kind, row))
    schedule.sort(key=lambda s: s[0])
    last = max((s[0] for s in schedule), default=1) or 1
    scale = duration_s / last

    clear_sample_data()
    elapsed = 0.0
    for at, fx, kind, row in schedule:
        wait = at * scale - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
            elapsed += wait
        await asyncio.to_thread(_apply, fx, kind, row)
    log.info("sample replay finished")


def start_replay(duration_s: float = 60.0) -> None:
    global _replay_task
    if _replay_task and not _replay_task.done():
        _replay_task.cancel()
    _replay_task = asyncio.create_task(_replay(duration_s))


def replay_running() -> bool:
    return bool(_replay_task and not _replay_task.done())
