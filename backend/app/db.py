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
  suppression      TEXT,                   -- static_source | likely_prescribed | registered_burn | low_signal (monitor only)
  reraised         INTEGER NOT NULL DEFAULT 0,
  evidence_json    TEXT,                   -- [{kind, label, at, counts}] behind the level
  level_reason     TEXT,
  response_json    TEXT,                   -- notification state: ladder, decision, page, mutual aid
  updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_last_seen ON events(last_seen);

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

CREATE TABLE IF NOT EXISTS source_health (
  source        TEXT PRIMARY KEY,
  last_ok       TEXT,
  last_error    TEXT,
  last_error_at TEXT
);

CREATE TABLE IF NOT EXISTS feed_snapshots (
  source     TEXT PRIMARY KEY,
  fetched_at TEXT NOT NULL,
  payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  phone         TEXT UNIQUE NOT NULL,
  role          TEXT NOT NULL,
  lat           REAL,
  lon           REAL,
  weekday_avail INTEGER NOT NULL DEFAULT 0,
  ladder_rank   INTEGER,
  opted_in      INTEGER NOT NULL DEFAULT 1,
  registered    INTEGER NOT NULL DEFAULT 1,
  mesh_id       TEXT,                      -- Meshtastic node ID (!a1b2c3d4) of the radio they carry
  app           INTEGER NOT NULL DEFAULT 0 -- 1 = uses the phone app: also gets the firewatch:// link text
);

CREATE TABLE IF NOT EXISTS signals (
  id           INTEGER PRIMARY KEY,
  event_id     INTEGER REFERENCES events(id),
  kind         TEXT NOT NULL,              -- line_fault | report | neighbor_reply | camera_smoke | ngfs | sensor_smoke
  lat          REAL NOT NULL,
  lon          REAL NOT NULL,
  observed_at  TEXT NOT NULL,
  source       TEXT NOT NULL,
  value        TEXT,
  contact_id   INTEGER REFERENCES contacts(id),
  is_sample    INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL,
  meta_json    TEXT                        -- sensor_smoke: {pm_lr, gas_lr, via} from the sensor smoke model
);
CREATE INDEX IF NOT EXISTS idx_signals_event ON signals(event_id);
CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(observed_at);

CREATE TABLE IF NOT EXISTS messages (
  id          INTEGER PRIMARY KEY,
  event_id    INTEGER REFERENCES events(id),
  contact_id  INTEGER REFERENCES contacts(id),
  phone       TEXT NOT NULL,               -- phone number, or mesh node ID on the mesh channel
  direction   TEXT NOT NULL,               -- out | in
  purpose     TEXT,
  body        TEXT NOT NULL,
  status      TEXT NOT NULL,               -- sent | failed | received; mesh adds relayed | delivered
  gateway_id  TEXT,
  is_sample   INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  channel     TEXT NOT NULL DEFAULT 'sms'  -- sms | mesh
);
CREATE INDEX IF NOT EXISTS idx_messages_event ON messages(event_id);

CREATE TABLE IF NOT EXISTS fw1_feed (          -- one row per alert change; the phone app's tiny feed (docs/mobile)
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  pack        TEXT NOT NULL,
  event_id    INTEGER NOT NULL,
  kind        TEXT NOT NULL,               -- alert | clear | notfire
  level       TEXT NOT NULL,
  flags       INTEGER NOT NULL DEFAULT 0,
  code        TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fw1_feed_pack ON fw1_feed(pack, seq);
CREATE INDEX IF NOT EXISTS idx_fw1_feed_event ON fw1_feed(event_id, seq);

CREATE TABLE IF NOT EXISTS mesh_nodes (
  node_id      TEXT PRIMARY KEY,           -- !a1b2c3d4
  long_name    TEXT,
  short_name   TEXT,
  hw_model     TEXT,
  lat          REAL,
  lon          REAL,
  position_at  TEXT,
  battery_pct  INTEGER,
  snr          REAL,
  last_heard   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sensor_readings (   -- telemetry from mesh sensor nodes
  id           INTEGER PRIMARY KEY,
  node_id      TEXT NOT NULL,
  at           TEXT NOT NULL,              -- wall-clock receive time
  temp_c       REAL,
  rh_pct       REAL,
  pm25         REAL,                       -- µg/m³, PM2.5 (atmospheric units when the sensor sends them)
  pm10         REAL                        -- µg/m³, PM10
);
CREATE INDEX IF NOT EXISTS idx_sensor_node_time ON sensor_readings(node_id, at);

CREATE TABLE IF NOT EXISTS sensor_nodes (    -- surveyed field hardware: sensor nodes, relays, the station bridge
  node_id       TEXT PRIMARY KEY,            -- the radio's mesh id, same as mesh_nodes
  kind          TEXT NOT NULL,               -- sensor | relay | bridge
  tier          TEXT,                        -- bare | rich (sensors only)
  site          INTEGER,                     -- region planner plot number
  label         TEXT NOT NULL,
  lat           REAL NOT NULL,
  lon           REAL NOT NULL,
  via           TEXT,                        -- node_id its packets reach the station through
  installed_at  TEXT NOT NULL,
  baseline_json TEXT,                        -- readings logged at commissioning (gas resistance)
  simulated     INTEGER NOT NULL DEFAULT 0,
  sim_json      TEXT                         -- simulator state: charge, injected faults
);

CREATE TABLE IF NOT EXISTS burn_notices (
  id          INTEGER PRIMARY KEY,
  contact_id  INTEGER REFERENCES contacts(id),   -- NULL for a burn the dispatcher logged by phone (see caller)
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  radius_km   REAL NOT NULL DEFAULT 1.5,
  burn_date   TEXT NOT NULL,               -- local date, YYYY-MM-DD (a logged burn: the date it starts)
  is_sample   INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,               -- a logged burn: when it was called in
  start_at    TEXT,                        -- logged burns only: the window, UTC ISO (NULL = the whole burn_date)
  end_at      TEXT,
  caller      TEXT,
  label       TEXT
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY, contact_id INTEGER REFERENCES contacts(id), phone TEXT,
  channel TEXT NOT NULL,
  category TEXT NOT NULL,
  body TEXT NOT NULL, lat REAL, lon REAL,
  estimated INTEGER NOT NULL DEFAULT 0,
  hearsay INTEGER NOT NULL DEFAULT 0, flagged INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  event_id INTEGER REFERENCES events(id), parent_id INTEGER REFERENCES posts(id),
  duty_told_at TEXT, ack_level TEXT, ack_by TEXT, ack_at TEXT, ack_until TEXT,
  is_sample INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_confirms (
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id),
  contact_id INTEGER NOT NULL REFERENCES contacts(id),
  kind TEXT NOT NULL,
  channel TEXT NOT NULL, lat REAL, lon REAL, ip_hash TEXT,
  counted INTEGER NOT NULL DEFAULT 0, reason TEXT, created_at TEXT NOT NULL,
  UNIQUE(post_id, contact_id)
);
CREATE TABLE IF NOT EXISTS post_photos (
  post_id INTEGER PRIMARY KEY REFERENCES posts(id), jpeg BLOB NOT NULL,
  width INTEGER NOT NULL, height INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_devices (
  token_hash TEXT PRIMARY KEY, contact_id INTEGER NOT NULL REFERENCES contacts(id),
  created_at TEXT NOT NULL, last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS post_asks (
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id),
  contact_id INTEGER NOT NULL REFERENCES contacts(id), asked_at TEXT NOT NULL, answered_at TEXT,
  UNIQUE(post_id, contact_id)
);
CREATE TABLE IF NOT EXISTS replay_clock (
  id INTEGER PRIMARY KEY CHECK (id = 1), slug TEXT, t_min INTEGER,
  running INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
);
"""

# Columns added after the first release; ALTER them onto older databases.
MIGRATIONS = {
    "events": {"evidence_json": "TEXT", "level_reason": "TEXT", "response_json": "TEXT",
               "ack_level": "TEXT", "ack_by": "TEXT", "ack_at": "TEXT", "ack_until": "TEXT",
               "ack_mark_det": "INTEGER", "ack_mark_sig": "INTEGER"},
    "contacts": {"mesh_id": "TEXT", "app": "INTEGER NOT NULL DEFAULT 0"},
    "messages": {"channel": "TEXT NOT NULL DEFAULT 'sms'", "post_id": "INTEGER"},
    "burn_notices": {"start_at": "TEXT", "end_at": "TEXT", "caller": "TEXT", "label": "TEXT"},
    "posts": {"client_key": "TEXT", "queued_min": "INTEGER"},
    "sensor_readings": {"gas_kohm": "REAL", "pressure_hpa": "REAL", "pack_v": "REAL", "pack_ma": "REAL",
                        "solar_v": "REAL", "solar_ma": "REAL", "env_seq": "INTEGER", "pm_seq": "INTEGER"},
    "signals": {"meta_json": "TEXT"},
}
POST_MIGRATION = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_mesh ON contacts(mesh_id);
CREATE INDEX IF NOT EXISTS idx_messages_gateway ON messages(gateway_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_client_key ON posts(contact_id, client_key) WHERE client_key IS NOT NULL;
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
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        _burn_contact_nullable(conn)
        # Errors stored before keys were redacted can hold a FIRMS URL with the key in it.
        conn.execute("UPDATE source_health SET last_error = NULL WHERE last_error LIKE '%/api/area/csv/%'")
        conn.executescript(POST_MIGRATION)


def _burn_contact_nullable(conn: sqlite3.Connection) -> None:
    """Older databases made burn_notices.contact_id NOT NULL; a logged burn has no contact, so rebuild the table."""
    col = next((r for r in conn.execute("PRAGMA table_info(burn_notices)") if r["name"] == "contact_id"), None)
    if col is None or not col["notnull"]:
        return
    conn.executescript(
        "ALTER TABLE burn_notices RENAME TO burn_notices_old;"
        "CREATE TABLE burn_notices (id INTEGER PRIMARY KEY, contact_id INTEGER REFERENCES contacts(id), "
        "lat REAL NOT NULL, lon REAL NOT NULL, radius_km REAL NOT NULL DEFAULT 1.5, burn_date TEXT NOT NULL, "
        "is_sample INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, start_at TEXT, end_at TEXT, caller TEXT, label TEXT);"
        "INSERT INTO burn_notices(id, contact_id, lat, lon, radius_km, burn_date, is_sample, created_at, start_at, end_at, caller, label) "
        "SELECT id, contact_id, lat, lon, radius_km, burn_date, is_sample, created_at, start_at, end_at, caller, label "
        "FROM burn_notices_old;"
        "DROP TABLE burn_notices_old;"
    )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def loads(s: str | None, default=None):
    return json.loads(s) if s else default


def redact(text: str | None) -> str | None:
    """Health is unauthenticated, so a key must never be stored or served."""
    key = get_settings().firms_map_key
    return text.replace(key, "***") if text and key else text


def mark_source(conn: sqlite3.Connection, source: str, ok: bool, error: str | None = None) -> None:
    now = iso(utcnow())
    error = redact(error)
    if ok:
        conn.execute(
            "INSERT INTO source_health(source, last_ok) VALUES (?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_ok = excluded.last_ok, "
            "last_error = NULL, last_error_at = NULL",
            (source, now),
        )
    else:
        conn.execute(
            "INSERT INTO source_health(source, last_error, last_error_at) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_error = excluded.last_error, last_error_at = excluded.last_error_at",
            (source, error, now),
        )


def save_snapshot(conn, source: str, data) -> str:
    """Store the latest payload for a context feed (one row per source)."""
    import json

    now = iso(utcnow())
    conn.execute(
        "INSERT INTO feed_snapshots(source, fetched_at, payload) VALUES (?, ?, ?) "
        "ON CONFLICT(source) DO UPDATE SET fetched_at = excluded.fetched_at, payload = excluded.payload",
        (source, now, json.dumps(data)),
    )
    return now


def load_snapshot(conn, source: str) -> dict | None:
    import json

    r = conn.execute("SELECT fetched_at, payload FROM feed_snapshots WHERE source = ?", (source,)).fetchone()
    if r is None:
        return None
    return {"fetched_at": r["fetched_at"], "data": json.loads(r["payload"])}
