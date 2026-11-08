"""Historical FIRMS -> events (the app's own clustering) -> labels (WFIGS + static mask) -> feature snapshots.

    .venv/bin/python -m ml.build_dataset [--rebuild-history] [--max-static 400] [--max-weak-rx 400]

Steps:
1. Replay every Kansas detection through `pipeline.insert_detections` + `cluster.assign_detection` into
   ml/data/history.sqlite, so training events are built exactly like live ones.
2. Derive persistent heat sources (1 km cells active on many days in many calendar months, plus FIRMS
   type=2) and write them to data/layers/static_sources.geojson for serving.
3. Label events: WFIGS wildfire (WF) = 1, WFIGS prescribed (RX) = 0, persistent heat source = 0 (kept
   for evaluating the full pipeline; the app handles them with a guardrail), and unreported Flint Hills
   spring fires = 0 (weak label, kind rx_weak). Other unmatched events are left out.
4. For each labeled event, build features as of each early pass (first 24 h, up to 3 snapshots) with
   `enrich.build_features(..., as_of=...)` and archive weather from Open-Meteo, mirroring live scoring.
"""

import argparse
import csv
import io
import json
import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx

from app.db import connect, init_db, iso, parse_iso
from app.features.cluster import assign_detection
from app.features.enrich import build_features
from app.geo import haversine_km
from app.ingest.firms import parse_csv
from app.ingest.weather import weather_at
from app.layers import in_flint_hills, load_layer, nearest_town, point_index
from app.pipeline import insert_detections

from .download import SENSORS
from .paths import DATASET_PATH, FIRMS_DIR, HISTORY_DB, LAYERS_DIR, WEATHER_CACHE, WFIGS_PATH, WORK_DIR

log = logging.getLogger("ml.build_dataset")

MATCH_KM = 3.0
MATCH_BEFORE = timedelta(hours=12)  # detections may precede the reported discovery
MATCH_AFTER = timedelta(hours=48)
STATIC_CELL_DEG = 0.01
STATIC_MIN_DAYS = 15
STATIC_MIN_MONTHS = 6
STATIC_MERGE_KM = 2.0
STATIC_LABEL_KM = 1.0
WEAK_RX_CLEAR_KM = 10.0
WEAK_RX_CLEAR_DAYS = 3
SNAPSHOT_HOURS = 24
MAX_SNAPSHOTS = 3


# ---------------------------------------------------------------- 1. history

def _db() -> str:
    return str(HISTORY_DB)


def build_history(rebuild: bool) -> None:
    if HISTORY_DB.exists() and not rebuild:
        log.info("history db exists, skipping replay (use --rebuild-history to redo)")
        return
    for suffix in ("", "-wal", "-shm"):
        HISTORY_DB.with_name(HISTORY_DB.name + suffix).unlink(missing_ok=True)
    init_db(_db())

    dets: list[dict] = []
    types: dict[str, int] = {}
    for path in sorted(FIRMS_DIR.glob("*_ks.csv")):
        folder = path.name.rsplit("_", 2)[0]
        source = SENSORS[folder][0]
        text = path.read_text()
        parsed = parse_csv(text, source)
        for d, row in zip(parsed, csv.DictReader(io.StringIO(text))):
            t = int(row.get("type") or 0)
            if t == 3:  # offshore
                continue
            d["firms_type"] = t
            dets.append(d)
    dets.sort(key=lambda d: d["acq_time"])
    log.info("replaying %d detections through the clustering pipeline", len(dets))

    start = time.perf_counter()
    with connect(_db()) as conn:
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("CREATE TABLE IF NOT EXISTS firms_type (detection_id INTEGER PRIMARY KEY, type INTEGER)")
        batch = 5000
        for i in range(0, len(dets), batch):
            chunk = dets[i : i + batch]
            ids = insert_detections(conn, chunk)
            # insert_detections skips duplicates, so map ids back by dedupe key
            for det_id in ids:
                assign_detection(conn, det_id)
            keyed = {f"{d['source']}|{d['lat']:.4f}|{d['lon']:.4f}|{d['acq_time']}": d["firms_type"] for d in chunk}
            rows = conn.execute(
                f"SELECT id, dedupe_key FROM detections WHERE id IN ({','.join('?' * len(ids))})", ids
            ).fetchall() if ids else []
            conn.executemany(
                "INSERT OR REPLACE INTO firms_type VALUES (?, ?)", [(r["id"], keyed.get(r["dedupe_key"], 0)) for r in rows]
            )
            conn.commit()
            done = i + len(chunk)
            rate = done / (time.perf_counter() - start)
            log.info("  %d / %d detections (%s) %.0f/s", done, len(dets), chunk[-1]["acq_time"][:10], rate)
        n_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    log.info("history: %d detections -> %d events", len(dets), n_events)


# ---------------------------------------------------------------- 2. static sources

def derive_static_sources() -> list[dict]:
    with connect(_db()) as conn:
        rows = conn.execute(
            "SELECT d.lat, d.lon, d.acq_time, COALESCE(t.type, 0) AS type FROM detections d "
            "LEFT JOIN firms_type t ON t.detection_id = d.id"
        ).fetchall()
    cells: dict[tuple[int, int], dict] = defaultdict(lambda: {"days": set(), "months": set(), "type2": 0, "lat": 0.0, "lon": 0.0, "n": 0})
    for r in rows:
        key = (round(r["lat"] / STATIC_CELL_DEG), round(r["lon"] / STATIC_CELL_DEG))
        c = cells[key]
        c["days"].add(r["acq_time"][:10])
        c["months"].add(r["acq_time"][5:7])
        c["type2"] += r["type"] == 2
        c["lat"] += r["lat"]
        c["lon"] += r["lon"]
        c["n"] += 1
    static = [
        {"lat": c["lat"] / c["n"], "lon": c["lon"] / c["n"], "n": c["n"], "days": len(c["days"]), "months": len(c["months"]), "type2": c["type2"]}
        for c in cells.values()
        if (len(c["days"]) >= STATIC_MIN_DAYS and len(c["months"]) >= STATIC_MIN_MONTHS) or (c["type2"] >= 3 and len(c["days"]) >= 5)
    ]
    static.sort(key=lambda c: -c["n"])

    groups: list[dict] = []
    for c in static:
        for g in groups:
            if haversine_km(c["lat"], c["lon"], g["lat"], g["lon"]) <= STATIC_MERGE_KM:
                w = g["n"] + c["n"]
                g["lat"] = (g["lat"] * g["n"] + c["lat"] * c["n"]) / w
                g["lon"] = (g["lon"] * g["n"] + c["lon"] * c["n"]) / w
                g["n"] = w
                g["days"] = max(g["days"], c["days"])
                g["type2"] += c["type2"]
                break
        else:
            groups.append(dict(c))

    features = []
    for i, g in enumerate(groups):
        town = nearest_town(g["lat"], g["lon"]).name
        features.append({
            "type": "Feature",
            "properties": {
                "id": f"static/{i}",
                "name": f"Persistent heat source near {town}" if town else "Persistent heat source",
                "kind": "persistent",
                "detections": g["n"],
                "max_days": g["days"],
                "firms_static_flags": g["type2"],
            },
            "geometry": {"type": "Point", "coordinates": [round(g["lon"], 5), round(g["lat"], 5)]},
        })
    path = LAYERS_DIR / "static_sources.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")))
    load_layer.cache_clear()
    point_index.cache_clear()
    log.info("static sources: %d cells -> %d sources -> %s", len(static), len(groups), path.name)
    return features


# ---------------------------------------------------------------- 3. labels

def load_incidents() -> list[dict]:
    out = []
    for r in json.loads(WFIGS_PATH.read_text()):
        if r["type"] not in ("WF", "RX"):
            continue
        r["discovered"] = datetime.fromtimestamp(r["discovered_ms"] / 1000, tz=timezone.utc)
        out.append(r)
    return out


def label_events(static: list[dict]) -> tuple[dict[int, dict], list[dict]]:
    """Returns ({event_id: label info}, matched WF incident stats for the lead-time stat)."""
    incidents = load_incidents()
    labels: dict[int, dict] = {}
    conflicts: set[int] = set()
    lead_stats = []
    with connect(_db()) as conn:
        for inc in incidents:
            lo, hi = inc["discovered"] - MATCH_BEFORE, inc["discovered"] + MATCH_AFTER
            dlat, dlon = MATCH_KM / 110.574, MATCH_KM / (111.32 * 0.79)
            rows = conn.execute(
                "SELECT d.event_id, d.lat, d.lon, d.acq_time FROM detections d JOIN events e ON e.id = d.event_id "
                "WHERE e.first_seen <= ? AND e.last_seen >= ? AND d.lat BETWEEN ? AND ? AND d.lon BETWEEN ? AND ?",
                (iso(hi), iso(lo), inc["lat"] - dlat, inc["lat"] + dlat, inc["lon"] - dlon, inc["lon"] + dlon),
            ).fetchall()
            matched = {r["event_id"] for r in rows if haversine_km(inc["lat"], inc["lon"], r["lat"], r["lon"]) <= MATCH_KM}
            if not matched:
                continue
            for eid in matched:
                prev = labels.get(eid)
                if prev and prev["kind"] != inc["type"].lower():
                    conflicts.add(eid)
                labels[eid] = {"kind": inc["type"].lower(), "incident_id": inc["id"], "incident_name": inc["name"], "acres": inc["acres"]}
            if inc["type"] == "WF":
                first = min(
                    conn.execute("SELECT MIN(acq_time) FROM detections WHERE event_id = ?", (eid,)).fetchone()[0]
                    for eid in matched
                )
                lead_stats.append({
                    "incident": inc["name"], "acres": inc["acres"], "discovered": iso(inc["discovered"]),
                    "first_detection": first,
                    "detection_minus_discovery_min": round((parse_iso(first) - inc["discovered"]).total_seconds() / 60),
                })
        for eid in conflicts:
            labels.pop(eid, None)

        n_wf = sum(v["kind"] == "wf" for v in labels.values())
        n_rx = sum(v["kind"] == "rx" for v in labels.values())
        log.info("WFIGS matches: %d wildfire events, %d prescribed events, %d conflicts dropped", n_wf, n_rx, len(conflicts))

        sx = [(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]) for f in static]
        n_static = 0
        for e in conn.execute("SELECT id, lat, lon FROM events").fetchall():
            if e["id"] in labels:
                continue
            if any(haversine_km(e["lat"], e["lon"], la, lo_) <= STATIC_LABEL_KM for la, lo_ in sx):
                labels[e["id"]] = {"kind": "static", "incident_id": None, "incident_name": None, "acres": None}
                n_static += 1
        log.info("static-source events: %d", n_static)

        # Weak negatives: unreported Flint Hills fires in March–April. Ranchers burn ~2M acres there each
        # spring and almost none of it reaches WFIGS, so without these the labels say most spring Flint
        # Hills fires are wildfires. Skip anything near a reported wildfire in space and time.
        wf = [i for i in incidents if i["type"] == "WF"]
        n_weak = 0
        for e in conn.execute("SELECT id, lat, lon, first_seen FROM events").fetchall():
            t = parse_iso(e["first_seen"])
            if e["id"] in labels or t.month not in (3, 4) or not in_flint_hills(e["lat"], e["lon"]):
                continue
            if any(
                abs((t - i["discovered"]).total_seconds()) <= WEAK_RX_CLEAR_DAYS * 86400
                and haversine_km(e["lat"], e["lon"], i["lat"], i["lon"]) <= WEAK_RX_CLEAR_KM
                for i in wf
            ):
                continue
            labels[e["id"]] = {"kind": "rx_weak", "incident_id": None, "incident_name": None, "acres": None}
            n_weak += 1
        log.info("weak prescribed-burn candidates (unreported Flint Hills, Mar–Apr): %d", n_weak)
    return labels, lead_stats


# ---------------------------------------------------------------- 4. features

class WeatherCache:
    def __init__(self) -> None:
        self.data: dict[str, dict] = json.loads(WEATHER_CACHE.read_text()) if WEATHER_CACHE.exists() else {}
        self.dirty = 0

    def get(self, lat: float, lon: float, when: datetime) -> dict | None:
        key = f"{lat:.1f},{lon:.1f},{when:%Y-%m-%dT%H}"
        if key in self.data:
            return self.data[key]
        for attempt in range(5):
            try:
                w = weather_at(lat, lon, when)
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = 30 * (attempt + 1)
                    log.warning("Open-Meteo rate limit; sleeping %ds", wait)
                    time.sleep(wait)
                    continue
                log.warning("weather failed %s: %s", key, e)
                return None
            except httpx.HTTPError as e:
                log.warning("weather failed %s: %s", key, e)
                time.sleep(2)
        else:
            return None
        time.sleep(0.12)
        self.data[key] = w
        self.dirty += 1
        if self.dirty >= 25:
            self.save()
        return w

    def save(self) -> None:
        WEATHER_CACHE.write_text(json.dumps(self.data))
        self.dirty = 0


def snapshot_times(conn, event_id: int) -> list[datetime]:
    times = [parse_iso(r[0]) for r in conn.execute(
        "SELECT DISTINCT acq_time FROM detections WHERE event_id = ? ORDER BY acq_time", (event_id,)
    ).fetchall()]
    early = [t for t in times if t <= times[0] + timedelta(hours=SNAPSHOT_HOURS)]
    picks = [early[0]]
    if len(early) > 1:
        picks.append(early[1])
    if len(early) > 2:
        picks.append(early[-1])
    return picks[:MAX_SNAPSHOTS]


def build_rows(labels: dict[int, dict], caps: dict[str, int], seed: int) -> list[dict]:
    chosen: list[int] = []
    for kind in ("wf", "rx", "static", "rx_weak"):
        ids = sorted(eid for eid, v in labels.items() if v["kind"] == kind)
        keep = random.Random(seed).sample(ids, min(caps[kind], len(ids))) if kind in caps else ids
        log.info("%s: %d of %d events", kind, len(keep), len(ids))
        chosen += keep
    chosen.sort()
    log.info("building features for %d events", len(chosen))

    cache = WeatherCache()
    rows = []
    with connect(_db()) as conn:
        for n, eid in enumerate(chosen, 1):
            ev = conn.execute("SELECT lat, lon FROM events WHERE id = ?", (eid,)).fetchone()
            lab = labels[eid]
            for k, as_of in enumerate(snapshot_times(conn, eid)):
                weather = cache.get(ev["lat"], ev["lon"], as_of)
                feats, degraded = build_features(conn, eid, weather, as_of=as_of)
                rows.append({
                    "event_id": eid,
                    "snapshot": k,
                    "as_of": iso(as_of),
                    "year": as_of.year,
                    "label": int(lab["kind"] == "wf"),
                    "kind": lab["kind"],
                    "incident_id": lab["incident_id"] or "",
                    "incident_name": lab["incident_name"] or "",
                    "degraded": int(degraded),
                    **feats,
                })
            if n % 50 == 0:
                log.info("  %d / %d events", n, len(chosen))
    cache.save()
    return rows


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "app.features.enrich"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    p = argparse.ArgumentParser()
    p.add_argument("--rebuild-history", action="store_true")
    p.add_argument("--max-static", type=int, default=400)
    p.add_argument("--max-weak-rx", type=int, default=400)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    build_history(args.rebuild_history)
    static = derive_static_sources()
    labels, lead_stats = label_events(static)
    (WORK_DIR / "wf_lead_times.json").write_text(json.dumps(lead_stats, indent=1))

    rows = build_rows(labels, {"static": args.max_static, "rx_weak": args.max_weak_rx}, args.seed)
    with DATASET_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    by_kind: dict[str, int] = defaultdict(int)
    for r in rows:
        by_kind[r["kind"]] += 1
    log.info("dataset: %d rows %s -> %s", len(rows), dict(by_kind), DATASET_PATH)


if __name__ == "__main__":
    main()
