import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
  id            INTEGER PRIMARY KEY,
  dedupe_key    TEXT UNIQUE NOT NULL,
  source        TEXT NOT NULL,
  satellite     TEXT,
  lat           REAL NOT NULL,
  lon           REAL NOT NULL,
  acq_time      TEXT NOT NULL,
  brightness_k  REAL,
  frp_mw        REAL,
  confidence    TEXT,
  scan_km       REAL,
  track_km      REAL,
  daynight      TEXT,
  event_id      INTEGER REFERENCES events(id),
  is_sample     INTEGER NOT NULL DEFAULT 0,
  ingested_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detections_event ON detections(event_id);
CREATE INDEX IF NOT EXISTS idx_detections_time ON detections(acq_time);

CREATE TABLE IF NOT EXISTS events (
  id               INTEGER PRIMARY KEY,
  lat              REAL NOT NULL,
  lon              REAL NOT NULL,
  first_seen       TEXT NOT NULL,
  last_seen        TEXT NOT NULL,
  county           TEXT,
  nearest_town     TEXT,
  place_label      TEXT,
  status           TEXT NOT NULL DEFAULT 'new',
  is_sample        INTEGER NOT NULL DEFAULT 0,
  sample_slug      TEXT,
  features_json    TEXT,
  weather_json     TEXT,
  score            INTEGER,
  recommendation   TEXT,
  degraded         INTEGER NOT NULL DEFAULT 0,
  guardrail        TEXT,
  suppression      TEXT,                   -- static_source | likely_prescribed | logged_burn | low_signal (monitor only)
  reraised         INTEGER NOT NULL DEFAULT 0,
  updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
  id             INTEGER PRIMARY KEY,
  event_id       INTEGER NOT NULL REFERENCES events(id),
  scored_at      TEXT NOT NULL,
  score          INTEGER NOT NULL,
  recommendation TEXT NOT NULL,
  scorer         TEXT NOT NULL,
  reasons_json   TEXT NOT NULL,
  guardrail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_scores_event ON scores(event_id);

CREATE TABLE IF NOT EXISTS actions (
  id          INTEGER PRIMARY KEY,
  event_id    INTEGER NOT NULL REFERENCES events(id),
  action      TEXT NOT NULL,
  operator    TEXT NOT NULL,
  note        TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS burns (
  id          INTEGER PRIMARY KEY,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  "start"     TEXT NOT NULL,           -- UTC ISO, burn window opens
  "end"       TEXT NOT NULL,           -- UTC ISO, burn window closes
  called_in   TEXT NOT NULL,           -- UTC ISO, when it was called in to dispatch
  caller      TEXT NOT NULL,
  label       TEXT,
  is_sample   INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_burns_sample ON burns(is_sample);

CREATE TABLE IF NOT EXISTS signals (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL,         -- line_fault | report
  lat           REAL NOT NULL,
  lon           REAL NOT NULL,
  time          TEXT NOT NULL,         -- UTC ISO
  payload_json  TEXT,                  -- circuit/kind for faults; text/phone for reports
  event_id      INTEGER REFERENCES events(id),
  is_sample     INTEGER NOT NULL DEFAULT 0,
  ingested_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_event ON signals(event_id);

CREATE TABLE IF NOT EXISTS source_health (
  source        TEXT PRIMARY KEY,
  last_ok       TEXT,
  last_error    TEXT,
  last_error_at TEXT
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connect(path: str | None = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(path or get_settings().db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def loads(s: str | None, default=None):
    return json.loads(s) if s else default


def mark_source(conn: sqlite3.Connection, source: str, ok: bool, error: str | None = None) -> None:
    now = iso(utcnow())
    if ok:
        conn.execute(
            "INSERT INTO source_health(source, last_ok) VALUES (?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_ok = excluded.last_ok",
            (source, now),
        )
    else:
        conn.execute(
            "INSERT INTO source_health(source, last_error, last_error_at) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_error = excluded.last_error, last_error_at = excluded.last_error_at",
            (source, error, now),
        )
