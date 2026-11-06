"""Sample mode: frozen fixtures fed through the real pipeline (see docs/DESIGN.md section 10)."""

import asyncio
import json
import logging

from .config import DATA_DIR
from .db import connect
from .pipeline import process_detections

log = logging.getLogger(__name__)
SAMPLES_DIR = DATA_DIR / "samples"

_replay_task: asyncio.Task | None = None


def load_fixtures() -> list[dict]:
    fixtures = [json.loads(p.read_text()) for p in sorted(SAMPLES_DIR.glob("*.json"))]
    return sorted(fixtures, key=lambda f: f.get("replay_offset_s", 0))


def clear_sample_data() -> None:
    with connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM events WHERE is_sample = 1")]
        for table in ("scores", "actions"):
            conn.executemany(f"DELETE FROM {table} WHERE event_id = ?", [(i,) for i in ids])
        conn.execute("DELETE FROM detections WHERE is_sample = 1")
        conn.execute("DELETE FROM events WHERE is_sample = 1")


def _ingest_pass(fixture: dict, detections: list[dict]) -> None:
    with connect() as conn:
        touched = process_detections(conn, detections, is_sample=True, weather=fixture["weather"])
        for event_id in touched:
            conn.execute("UPDATE events SET sample_slug = ? WHERE id = ?", (fixture["slug"], event_id))


def load_all_now() -> int:
    """Load every fixture immediately (used on startup so the dashboard is never empty)."""
    clear_sample_data()
    fixtures = load_fixtures()
    for fx in fixtures:
        for p in fx["passes"]:
            _ingest_pass(fx, p["detections"])
    return len(fixtures)


def has_sample_events() -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM events WHERE is_sample = 1 LIMIT 1").fetchone() is not None


async def _replay(duration_s: float) -> None:
    fixtures = load_fixtures()
    schedule = []
    for fx in fixtures:
        for p in fx["passes"]:
            schedule.append((fx.get("replay_offset_s", 0) + p["offset_s"], fx, p["detections"]))
    schedule.sort(key=lambda s: s[0])
    last = max((s[0] for s in schedule), default=1) or 1
    scale = duration_s / last

    clear_sample_data()
    elapsed = 0.0
    for at, fx, dets in schedule:
        wait = at * scale - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
            elapsed += wait
        await asyncio.to_thread(_ingest_pass, fx, dets)
    log.info("sample replay finished")


def start_replay(duration_s: float = 60.0) -> None:
    global _replay_task
    if _replay_task and not _replay_task.done():
        _replay_task.cancel()
    _replay_task = asyncio.create_task(_replay(duration_s))


def replay_running() -> bool:
    return bool(_replay_task and not _replay_task.done())
