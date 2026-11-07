"""Alert load: how many texts would Firewatch have sent a district in a burn-heavy Kansas spring?

    .venv/bin/python -m ml.alert_load [--radius-mi 12] [--out ml/data/alert_load_events.json]

Needs ml/data/history.sqlite (built by `ml.build_dataset.build_history` from the FIRMS archives) and
ml/data/wfigs_ks.json (from `ml.download`). Nothing here writes to the app DB, the model, or the layers.

For every satellite event first seen in March or April (2016 to 2025) with its centroid inside the circle
around each stand-in district center, it reproduces what live scoring would see after each early pass
(`build_features(..., as_of=...)`, the same snapshots training uses), scores it with the real
`score_features` (model plus guardrails), and levels it with the real `confirm.decide_level` with no
signals, no burn registry and no district settings (a satellite-only replay). The headline level is the
highest over the snapshots, since re-leveling in the app can only raise an event.

Each Investigate or Escalate event is matched to WFIGS the same way the training labels are: a reported
WF or RX incident within 3 km of a detection, discovered within [-12 h, +48 h] of the event's life.
"""

import argparse
import json
import logging
import math
from collections import Counter, defaultdict
from datetime import date, timedelta

from app.confirm import decide_level
from app.db import connect, iso, parse_iso
from app.features.enrich import build_features
from app.geo import haversine_km
from app.scoring.score import score_features

from .build_dataset import MATCH_AFTER, MATCH_BEFORE, MATCH_KM, WeatherCache, load_incidents, snapshot_times
from .paths import HISTORY_DB, WORK_DIR

log = logging.getLogger("ml.alert_load")

DISTRICTS = {
    "Comanche County": (37.19, -99.27),
    "Clark County": (37.24, -99.82),
    "Barber County": (37.23, -98.68),
    "Chase County (Flint Hills)": (38.30, -96.59),
}
KM_PER_MILE = 1.609344
YEARS = range(2016, 2026)
TEST_FROM = 2023  # the model trained on years before this
RANK = {"monitor": 0, "investigate": 1, "escalate": 2}


def candidate_events(conn, name, lat, lon, radius_km):
    dlat = radius_km / 110.574 + 0.01
    dlon = radius_km / (111.32 * math.cos(math.radians(lat))) + 0.01
    rows = conn.execute(
        "SELECT id, lat, lon, first_seen, last_seen FROM events WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (lat - dlat, lat + dlat, lon - dlon, lon + dlon),
    ).fetchall()
    out = []
    for r in rows:
        t = parse_iso(r["first_seen"])
        if t.month in (3, 4) and t.year in YEARS and haversine_km(lat, lon, r["lat"], r["lon"]) <= radius_km:
            out.append(r)
    return out


def match_wfigs(conn, ev, incidents):
    """Returns 'wf', 'rx', 'both' or 'none' using the training-label rule."""
    dets = conn.execute("SELECT lat, lon FROM detections WHERE event_id = ?", (ev["id"],)).fetchall()
    first, last = parse_iso(ev["first_seen"]), parse_iso(ev["last_seen"])
    kinds = set()
    for inc in incidents:
        lo, hi = inc["discovered"] - MATCH_BEFORE, inc["discovered"] + MATCH_AFTER
        if not (first <= hi and last >= lo):
            continue
        if any(haversine_km(inc["lat"], inc["lon"], d["lat"], d["lon"]) <= MATCH_KM for d in dets):
            kinds.add(inc["type"].lower())
    if kinds == {"wf", "rx"}:
        return "both"
    return next(iter(kinds)) if kinds else "none"


def evaluate(radius_mi: float) -> list[dict]:
    radius_km = radius_mi * KM_PER_MILE
    incidents = load_incidents()
    cache = WeatherCache()
    rows = []
    with connect(str(HISTORY_DB)) as conn:
        for name, (lat, lon) in DISTRICTS.items():
            events = candidate_events(conn, name, lat, lon, radius_km)
            log.info("%s: %d March/April events in %.1f km", name, len(events), radius_km)
            for n, ev in enumerate(events, 1):
                evrow = conn.execute("SELECT * FROM events WHERE id = ?", (ev["id"],)).fetchone()
                levels, scores, degraded_any, scorer = [], [], False, None
                for as_of in snapshot_times(conn, ev["id"]):
                    weather = cache.get(ev["lat"], ev["lon"], as_of)
                    feats, degraded = build_features(conn, ev["id"], weather, as_of=as_of)
                    sat = score_features(feats, degraded)
                    level, _reason, _evidence, _supp = decide_level(conn, evrow, feats, sat, None)
                    levels.append(level)
                    scores.append(sat.score)
                    degraded_any |= degraded
                    scorer = sat.scorer
                match = match_wfigs(conn, ev, incidents) if max(map(RANK.get, levels)) > 0 else None
                rows.append({
                    "district": name, "event_id": ev["id"], "first_seen": ev["first_seen"],
                    "year": parse_iso(ev["first_seen"]).year, "month": parse_iso(ev["first_seen"]).month,
                    "first_pass_level": levels[0], "level": max(levels, key=RANK.get),
                    "max_score": max(scores), "degraded": degraded_any, "scorer": scorer, "wfigs": match,
                })
                if n % 100 == 0:
                    log.info("  %d / %d", n, len(events))
            cache.save()
    cache.save()
    return rows


# ------------------------------------------------------------------ aggregation

def summarize(rows: list[dict], years: list[int]) -> dict:
    rows = [r for r in rows if r["year"] in years]
    ny = len(years)
    c = Counter(r["level"] for r in rows)
    texts = [r for r in rows if r["level"] != "monitor"]
    esc = [r for r in rows if r["level"] == "escalate"]
    out = {
        "years": ny, "events": len(rows), "monitor": c["monitor"], "investigate": c["investigate"], "escalate": c["escalate"],
        "texts": len(texts),
        "first_pass_texts": sum(r["first_pass_level"] != "monitor" for r in rows),
        "degraded": sum(r["degraded"] for r in rows),
        "wf": sum(r["wfigs"] in ("wf", "both") for r in texts),
        "rx_only": sum(r["wfigs"] == "rx" for r in texts),
        "none": sum(r["wfigs"] == "none" for r in texts),
        "esc_wf": sum(r["wfigs"] in ("wf", "both") for r in esc),
        "esc_rx_only": sum(r["wfigs"] == "rx" for r in esc),
        "esc_none": sum(r["wfigs"] == "none" for r in esc),
        "by_month": {},
    }
    for m in (3, 4):
        mr = [r for r in rows if r["month"] == m]
        out["by_month"][m] = {
            "events": len(mr), "texts": sum(r["level"] != "monitor" for r in mr),
            "investigate": sum(r["level"] == "investigate" for r in mr), "escalate": sum(r["level"] == "escalate" for r in mr),
        }
    out["worst_week"] = worst_week(texts, years)
    return out


def worst_week(texts: list[dict], years: list[int]) -> dict:
    """Highest count of Investigate+Escalate events in any 7 consecutive days (UTC first_seen date)."""
    best = {"texts": 0, "start": None, "escalate": 0}
    days = defaultdict(list)
    for r in texts:
        days[date.fromisoformat(r["first_seen"][:10])].append(r["level"])
    for y in years:
        d = date(y, 3, 1)
        while d <= date(y, 4, 30):
            window = [lv for k in range(7) for lv in days.get(d + timedelta(days=k), [])]
            if len(window) > best["texts"]:
                best = {"texts": len(window), "start": d.isoformat(), "escalate": window.count("escalate")}
            d += timedelta(days=1)
    return best


def table(rows: list[dict], years: list[int]) -> str:
    ny = len(years)
    names = list(DISTRICTS) + ["All four"]
    head = ("| District | Events/season | Monitor | Investigate | Escalate | Texts/season | Texts/month | "
            "Texts matched to WF | Texts matched to RX only | Texts unmatched | Not-WF share | Worst 7 days |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    lines = []
    for nm in names:
        sub = rows if nm == "All four" else [r for r in rows if r["district"] == nm]
        s = summarize(sub, years)
        t = s["texts"]
        share = f"{100 * (s['rx_only'] + s['none']) / t:.0f}%" if t else "n/a"
        w = s["worst_week"]
        lines.append(
            f"| {nm} | {s['events'] / ny:.1f} | {s['monitor'] / ny:.1f} | {s['investigate'] / ny:.1f} | {s['escalate'] / ny:.1f} | "
            f"{t / ny:.1f} | {t / ny / 2:.1f} | {s['wf'] / ny:.1f} | {s['rx_only'] / ny:.1f} | {s['none'] / ny:.1f} | {share} | "
            f"{w['texts']} ({w['escalate']} Escalate) from {w['start']} |"
        )
    return head + "\n".join(lines)


def month_table(rows: list[dict], years: list[int]) -> str:
    ny = len(years)
    head = "| District | March texts/yr | April texts/yr | March Escalate/yr | April Escalate/yr |\n|---|---|---|---|---|\n"
    lines = []
    for nm in list(DISTRICTS) + ["All four"]:
        sub = rows if nm == "All four" else [r for r in rows if r["district"] == nm]
        s = summarize(sub, years)["by_month"]
        lines.append(f"| {nm} | {s[3]['texts'] / ny:.1f} | {s[4]['texts'] / ny:.1f} | {s[3]['escalate'] / ny:.1f} | {s[4]['escalate'] / ny:.1f} |")
    return head + "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "app.features.enrich"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    p = argparse.ArgumentParser()
    p.add_argument("--radius-mi", type=float, default=12.0)
    p.add_argument("--out", default=str(WORK_DIR / "alert_load_events.json"))
    p.add_argument("--reuse", action="store_true", help="aggregate a previous --out file instead of rescoring")
    args = p.parse_args()
    if args.reuse:
        rows = json.loads(open(args.out).read())
    else:
        rows = evaluate(args.radius_mi)
        open(args.out, "w").write(json.dumps(rows))
    print(f"scorers: {dict(Counter(r['scorer'] for r in rows))}; degraded events: {sum(r['degraded'] for r in rows)} of {len(rows)}")
    overlap = len(rows) - len({r["event_id"] for r in rows})
    print(f"events counted in more than one district: {overlap}")
    for label, yrs in (("2023-2025 (held out, honest)", [2023, 2024, 2025]),
                       ("2016-2022 (model trained on these)", list(range(2016, 2023))),
                       ("2016-2025 (all)", list(YEARS))):
        print(f"\n### {label}, per season averages\n")
        print(table(rows, yrs))
        print()
        print(month_table(rows, yrs))
        s = summarize(rows, yrs)
        print(f"\nfirst-pass-only texts/season (all four): {s['first_pass_texts'] / len(yrs):.1f}; "
              f"Escalate matched WF {s['esc_wf']}, RX only {s['esc_rx_only']}, none {s['esc_none']} (season totals)")
    print("\nper year, all four, texts (Escalate):")
    for y in YEARS:
        s = summarize(rows, [y])
        print(f"  {y}: events {s['events']}, texts {s['texts']} ({s['escalate']})")


if __name__ == "__main__":
    main()
