"""The fire district Firewatch texts for: boundary, chief-tuned settings, and the contact roster."""

import csv
import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR, get_settings
from .layers import _point_in_ring

DISTRICTS_DIR = DATA_DIR / "districts"
LADDER_ROLES = ("duty_officer", "chief")
NEIGHBOR_ROLES = ("rancher", "pumper", "water_truck", "disc")
VOLUNTEER_ROLES = ("duty_officer", "chief", "volunteer")


@dataclass(frozen=True)
class District:
    slug: str
    settings: dict
    rings: tuple[tuple[tuple[float, float], ...], ...]

    def __getattr__(self, key: str):
        try:
            return self.settings[key]
        except KeyError:
            raise AttributeError(key) from None

    def contains(self, lat: float, lon: float) -> bool:
        return any(_point_in_ring(lon, lat, list(r)) for r in self.rings)


def _dir(slug: str) -> Path:
    return DISTRICTS_DIR / slug


# Per-scenario settings overrides (for example a baseline run at the old 3 mile ask). Held in a ContextVar so
# only code running inside the scenario's own context sees them (asyncio.to_thread and create_task copy that
# context; a caller in another context does not). Merged outside the lru_cache so the cached District is never
# mutated.
_OVERRIDES: ContextVar[dict] = ContextVar("district_overrides", default={})


@contextmanager
def overrides(settings: dict | None):
    """Apply settings overrides for the current context, always reset on exit."""
    token = _OVERRIDES.set(dict(settings or {}))
    try:
        yield
    finally:
        _OVERRIDES.reset(token)


def load_district(slug: str | None = None) -> District:
    d = _load_district(slug)
    ov = _OVERRIDES.get()
    if not ov:
        return d
    return District(d.slug, {**d.settings, **ov}, d.rings)


@lru_cache(maxsize=4)
def _load_district(slug: str | None = None) -> District:
    slug = slug or get_settings().district
    d = _dir(slug)
    settings = json.loads((d / "settings.json").read_text())
    boundary = json.loads((d / "boundary.geojson").read_text())
    rings = []
    for f in boundary["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        rings += [tuple(tuple(p) for p in poly[0]) for poly in polys]
    return District(slug, settings, tuple(rings))


def boundary_geojson(slug: str | None = None) -> dict:
    return json.loads((_dir(slug or get_settings().district) / "boundary.geojson").read_text())


def sync_roster(conn: sqlite3.Connection, slug: str | None = None) -> int:
    """Upsert the district roster CSV into contacts (keyed by phone). Opt-outs survive a re-sync."""
    path = _dir(slug or get_settings().district) / "roster.csv"
    n = 0
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            conn.execute(
                "INSERT INTO contacts(name, phone, role, lat, lon, weekday_avail, ladder_rank, mesh_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(phone) DO UPDATE SET name = excluded.name, "
                "role = excluded.role, lat = excluded.lat, lon = excluded.lon, "
                "weekday_avail = excluded.weekday_avail, ladder_rank = excluded.ladder_rank, "
                "mesh_id = excluded.mesh_id, registered = 1",
                (
                    row["name"], row["phone"], row["role"],
                    float(row["lat"]) if row["lat"] else None, float(row["lon"]) if row["lon"] else None,
                    int(row["weekday_avail"] or 0), int(row["ladder_rank"]) if row["ladder_rank"] else None,
                    (row.get("mesh_id") or "").strip().lower() or None,
                ),
            )
            n += 1
    return n
