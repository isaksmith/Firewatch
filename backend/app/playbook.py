"""Playbook: a dynamic run card. For the decision in front of the dispatcher, the three options with the lowest
expected loss side by side, the best one recommended, each with what it would cost, what it would do, and a
receipt once done. The model is in decision.py (docs/DESIGN.md section 5.9).

"Heads-up downwind" texts the stations whose area the fire could reach in the next two hours (worst case of the
ensemble forecast): no trucks roll, but they are ready, which shortens mutual aid's arrival.
"""

import math
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from . import decision, notify, scenario
from .db import iso, loads, parse_iso, utcnow
from .district import VOLUNTEER_ROLES, load_district
from .fire_weather import gfdi, gfdi_band
from .geo import KM_PER_DEG_LAT, KM_PER_MILE, compass, km_per_deg_lon
from .sim.ensemble import forecast
from .sim.fuels import FUEL_KEYS
from .sim.spread import Domain, interp_weather
from .situation import Curing, Ignition, Provenance, Situation, Weather, WeatherHour, scenario_situation

CENTRAL = ZoneInfo("America/Chicago")
HA_PER_ACRE = 0.404686
HEADS_UP_WINDOW_MIN = 120  # stations the worst case reaches within 2 hours
STATION_AREA_KM = 15.0  # a station's first-due area, for "could reach your area"


# ---------- the fire, as the forecast sees it ----------

def situation_for_event(ev) -> Situation:
    """Scenario events use the scenario; others are established fires at the event's weather, held constant."""
    if ev["sample_slug"]:
        try:
            return scenario_situation(ev["sample_slug"])
        except FileNotFoundError:
            pass
    f = loads(ev["features_json"], {})
    w = loads(ev["weather_json"], {})
    t0 = parse_iso(ev["first_seen"])
    hour = dict(wind_kmh=w.get("wind_kmh", f.get("wind_kmh", 0.0)) or 0.0,
                wind_from_deg=(w.get("wind_dir_deg", f.get("wind_dir_deg", 0.0)) or 0.0) % 360,
                temp_c=w.get("temp_c", f.get("temp_c", 15.0)), rh_pct=w.get("rh_pct", f.get("rh_pct", 50.0)),
                gust_kmh=w.get("gust_kmh"))
    src = Provenance(source="event weather" if w else "defaults", kind="observed" if w else "assumed")
    return Situation(
        ignition=Ignition(lat=ev["lat"], lon=ev["lon"], time=t0, fire_age_min=None,
                          provenance=Provenance(source="first detection", kind="observed")),
        weather=Weather(hours=[WeatherHour(time=t0 + timedelta(hours=h), **hour) for h in (-1, 6)], provenance=src),
        curing=Curing(pct=f["curing_pct"], provenance=Provenance(source="seasonal table", kind="assumed"))
        if "curing_pct" in f else None,
    )


def now_for(ev) -> datetime:
    """Scenario events run on the scenario clock (its end if it was loaded instantly); historical samples at
    their last detection; live events now."""
    if ev["sample_slug"]:
        now = scenario.clock_now(ev["sample_slug"])
        if now is not None:
            return now
        try:
            sc = scenario.load_scenario(ev["sample_slug"])
            return parse_iso(sc["t0"]) + timedelta(minutes=sc["duration_min"])
        except KeyError:
            pass
    return parse_iso(ev["last_seen"]) if ev["is_sample"] else utcnow()


_fc_cache: dict[tuple, dict] = {}


def _forecast(ev, sit: Situation, horizon: int) -> dict:
    key = (ev["sample_slug"] or ev["id"], ev["last_seen"], horizon)
    if key not in _fc_cache:
        if len(_fc_cache) > 32:
            _fc_cache.clear()
        _fc_cache[key] = forecast(sit, horizon)
    return _fc_cache[key]


def _acres(grid: np.ndarray, dom: Domain, minute: float) -> int:
    return int(round(float((grid <= minute).sum()) * dom.cell_m**2 / 10_000 / HA_PER_ACRE))


class Fire:
    """What the options are computed from: the forecast, the clock, the district."""

    def __init__(self, conn: sqlite3.Connection, ev):
        self.ev = ev
        self.sit = situation_for_event(ev)
        self.t0 = self.sit.ignition.time
        self.now = now_for(ev)
        self.now_min = max(0.0, (self.now - self.t0).total_seconds() / 60)
        span = self.now_min
        if ev["sample_slug"]:
            try:
                span = max(span, float(scenario.load_scenario(ev["sample_slug"])["duration_min"]))
            except KeyError:
                pass
        # One forecast covers the whole decision window (and a replay's whole run).
        self.horizon = min(300, int(math.ceil((span + HEADS_UP_WINDOW_MIN + 15) / 15) * 15))
        fc = _forecast(ev, self.sit, self.horizon)
        a = fc["_arrival"]
        self.dom: Domain = a["domain"]
        self.t10, self.t50 = a["t10"], a["t50"]
        self.d = load_district()
        self.cfg = self.d.settings
        self.state = loads(ev["response_json"], {}) or {}
        w = interp_weather(self.sit.weather_steps(), self.now_min)
        self.wind = f"{compass(w.wind_from_deg)} {round(w.wind_kmh / KM_PER_MILE)} mph"
        curing = self.sit.curing_or_default().pct
        self.gfdi = gfdi(curing, w.temp_c, w.rh_pct, w.wind_kmh)
        self.danger = gfdi_band(self.gfdi)
        i = int(np.clip(np.searchsorted(self.dom.lats, self.sit.ignition.lat), 0, self.dom.n - 1))
        j = int(np.clip(np.searchsorted(self.dom.lons, self.sit.ignition.lon), 0, self.dom.n - 1))
        self.fuel = FUEL_KEYS[int(self.dom.fuel.fuel_class[i, j])]
        self.turnout = self.cfg.get("turnout_min", 11)
        self.drive = self.cfg.get("drive_min", 18)
        self.cap_ha = self.cfg.get("capacity_ha_60min", 150)
        self.w = decision.weights(self.cfg)

    def clock(self, minute: float) -> str:
        return (self.t0 + timedelta(minutes=minute)).astimezone(CENTRAL).strftime("%-I:%M")

    def acres_at(self, minute: float) -> int:
        return _acres(self.t50, self.dom, minute)

    def first_truck(self, page_min: float) -> float:
        return page_min + self.turnout + self.drive

    def stations_in_path(self, conn) -> list[dict]:
        """Stations (other than ours) whose area the worst case reaches within the heads-up window."""
        limit = self.now_min + HEADS_UP_WINDOW_MIN
        reach = self.t10 <= limit
        if not reach.any():
            return []
        out = []
        ky = KM_PER_DEG_LAT
        for c in conn.execute("SELECT * FROM contacts WHERE role = 'station' AND lat IS NOT NULL AND opted_in = 1"):
            kx = km_per_deg_lon(c["lat"])
            dy = (self.dom.lats[:, None] - c["lat"]) * ky
            dx = (self.dom.lons[None, :] - c["lon"]) * kx
            near = (np.hypot(dx, dy) <= STATION_AREA_KM) & reach
            if near.any():
                eta = max(0, round(float(self.t10[near].min()) - self.now_min))
                out.append({"contact": c, "eta": eta})
        return sorted(out, key=lambda s: s["eta"])


# ---------- the decision ----------

def risk_context(f: Fire) -> list[str]:
    """What makes this fire dangerous, for the panel header (not used to choose)."""
    out = [f"{f.danger} fire danger (GFDI {f.gfdi:.0f})"]
    if f.sit.red_flag:
        out.append("Red flag warning")
    out.append({"grass": "Cured grass at the fire", "shrub": "Shrub and grass at the fire"}.get(
        f.fuel, f"Fuel at the fire: {f.fuel.replace('_', ' ')}"))
    likely = f.acres_at(f.now_min + 60)
    out.append(f"Likely ~{likely:,} ac in an hour; 2 trucks hold ~{round(f.cap_ha / HA_PER_ACRE)}")
    hist = decision.large_fire_share(f.danger)
    if hist:
        out.append(f"On {f.danger} days, {hist['p']:.0%} of reported Kansas wildfires grew past 1,000 ac ({hist['k']} of {hist['n']}, 2016-2025)")
    return out


def fire_probability(f: Fire) -> dict:
    evidence = [e for e in loads(f.ev["evidence_json"], []) if not e.get("at") or parse_iso(e["at"]) <= f.now]
    return decision.probability(evidence, f.danger, f.w, f.ev["score"])


def _heads_up_sent(conn, f: Fire) -> bool:
    return conn.execute("SELECT 1 FROM messages WHERE event_id = ? AND purpose = 'heads_up' AND created_at <= ?",
                        (f.ev["id"], iso(f.now))).fetchone() is not None


def holdable(f: Fire, arrive_min: float) -> bool:
    """Two trucks hold the fire if, left alone, it stays under their capacity for the hold window after they arrive."""
    return f.acres_at(arrive_min + f.w["hold_window_min"]) <= f.cap_ha / HA_PER_ACRE


def _texts(n: int) -> str:
    return f"{n} text{'' if n == 1 else 's'}, nobody rolls"


def outcome(f: Fire, page_min: float, ma_request_min: float | None, heads_up: bool) -> dict:
    """If it is a fire: when enough help is on scene, and how big the fire is by then."""
    w = f.w
    first = f.first_truck(page_min)
    if holdable(f, first):
        return {"help_min": first, "acres": f.acres_at(first), "help": "first truck; 2 trucks can hold it"}
    if ma_request_min is None:
        return {"help_min": None, "acres": f.acres_at(f.horizon), "help": "no mutual aid: grows past what 2 trucks hold"}
    travel = w["mutual_aid_travel_min"] - (w["heads_up_saves_min"] if heads_up else 0)
    t = max(first, ma_request_min + travel)
    return {"help_min": t, "acres": f.acres_at(t), "help": "mutual aid" + (" (heads-up given)" if heads_up else "")}


def _candidates(conn, f: Fire, decision_id: str) -> list[dict]:
    w, now = f.w, f.now_min
    vols = conn.execute(f"SELECT COUNT(*) n FROM contacts WHERE opted_in = 1 AND role IN ({','.join('?' * len(VOLUNTEER_ROLES))})",
                        VOLUNTEER_ROLES).fetchone()["n"]
    big = not holdable(f, f.first_truck(now))
    hu_sent = _heads_up_sent(conn, f)
    asked = bool(f.state.get("asked"))
    stations = [] if hu_sent else f.stations_in_path(conn)
    neighbors = [] if asked else notify.nearest_neighbors(conn, f.ev)
    ma_name = f.d.settings.get("neighbor_district", "the neighboring district")
    out = []

    def add(oid, title, page_min, ma_min, heads_up, if_not, if_not_text, effects):
        o = outcome(f, page_min, ma_min, heads_up)
        out.append({"id": oid, "title": title, "page_min": page_min, "if_fire_acres": o["acres"], "help_min": o["help_min"],
                    "help": o["help"], "if_not_cost": if_not, "if_not_text": if_not_text, "effects": effects,
                    "stations": len(stations) if heads_up and not hu_sent else 0})

    hu_effect = "Heads-up text (no action needed) to " + ", ".join(
        f"{s['contact']['name'].replace(' (stand-in)', '')} (area in ~{s['eta']} min)" for s in stations)
    ask_effect = ("Neighbors were already asked; wait for their answers" if asked else
                  "Ask " + ", ".join(f"{c['name']} ({km / KM_PER_MILE:.1f} mi)" for km, c in neighbors) + ': "See smoke?"'
                  if neighbors else "No opted-in neighbors within the ask radius")
    texts = len(neighbors) * w["cost_neighbor_text_acres"]
    hu_cost = len(stations) * w["cost_heads_up_acres"]

    if decision_id == "respond":
        ma_after = lambda page: page + w["approve_mutual_aid_min"]  # noqa: E731 - Michael's flow drafts mutual aid at the page
        false_page = w["cost_false_page_acres"] + (w["cost_false_mutual_aid_acres"] if big else 0) + hu_cost
        add("page", "Page the district now", now, ma_after(now), hu_sent or bool(stations), false_page,
            f"{vols} volunteers leave work" + (", and a neighbor's crew drives out" if big else ""),
            [f"Page {vols} volunteers through county dispatch",
             "Text people in the fire's path with an arrival time; ask nearby water trucks and discs to help"]
            + ([hu_effect] if stations else [])
            + ([f"Draft a mutual-aid request to {ma_name} (fire likely outgrows 2 trucks)"] if big else []))
        confirmed = f.ev["recommendation"] == "escalate"  # two independent sources (or a strong satellite hit) already agree
        asked_at = (parse_iso(f.state["investigate_at"]) - f.t0).total_seconds() / 60 if asked and f.state.get("investigate_at") else now
        conf = max(now + 2, asked_at + w["second_source_min"])
        if confirmed:
            stations_only = [hu_effect, "Keep watching; page on the next signal or the 911 call"]
            if stations:
                call = max(now, w["call_911_min"] + 2)
                add("heads_up_only", "Heads-up downwind only; don't page yet", call, ma_after(call), True, hu_cost,
                    _texts(len(stations)), stations_only)
        else:
            add("ask", "Wait for the neighbors' answers" if asked else "Ask the nearest neighbors first", conf, ma_after(conf),
                hu_sent, texts, f"{len(neighbors)} 'see smoke?' text{'' if len(neighbors) == 1 else 's'}" if neighbors else "nothing",
                [ask_effect])
            if stations:
                add("heads_up_ask", "Heads-up downwind + " + ("wait for neighbors" if asked else "ask neighbors"), conf,
                    ma_after(conf), True, texts + hu_cost, _texts(len(stations) + len(neighbors)),
                    [hu_effect, ask_effect])
                nxt = now + w["next_pass_min"]
                add("heads_up_recheck", "Heads-up downwind + recheck on the next pass", nxt, ma_after(nxt), True, hu_cost,
                    _texts(len(stations)),
                    [hu_effect, f"Re-score on the next satellite look (~{w['next_pass_min']} min)"])
        call = max(now, w["call_911_min"] + 2)
        add("watch", "Watch; don't page yet", call, ma_after(call), hu_sent, 0.0, "nothing",
            ["Nothing is sent; the alert is re-scored as signals arrive. If it is a fire, today's 911 call pages the district"])
    else:  # mutual aid, after the page
        page = _page_min(f) or now
        add("mutual_aid_now", "Request mutual aid now", page, now, hu_sent, w["cost_false_mutual_aid_acres"],
            "a neighbor's crew drives out for nothing", [f"Request {ma_name} + county EM"])
        size_up_at = f.first_truck(page) + w["size_up_min"]
        add("size_up", "Wait for Brush 1's size-up, then decide", page, max(now, size_up_at), hu_sent, 0.0, "nothing",
            [f"Nothing now; decide when Brush 1 reports (~{f.clock(size_up_at)})"])
        add("no_mutual_aid", "Don't request mutual aid", page, None, hu_sent, 0.0, "nothing", ["Nothing sent"])
    return out


def options(conn: sqlite3.Connection, ev) -> dict:
    f = Fire(conn, ev)
    st = f.state
    paged = _page_min(f) is not None
    ma = st.get("mutual_aid") or {}
    ma_sent = bool(ma.get("sent_at")) and parse_iso(ma["sent_at"]) <= f.now
    prob = fire_probability(f)
    p = prob["p"]

    decision_id = None
    if not paged and st.get("decision") != "no" and ev["status"] != "dismissed":
        decision_id, question = "respond", "How should we respond?"
    elif paged and not ma_sent:
        decision_id, question = "mutual_aid", "Do we need mutual aid?"

    dec = None
    if decision_id:
        cands = _candidates(conn, f, decision_id)
        for c in cands:
            c["expected_loss"] = decision.expected_loss(p, c["if_fire_acres"], c["if_not_cost"])
        cands.sort(key=lambda c: c["expected_loss"])
        shown = cands[:3]
        best = shown[0]
        for c in shown:
            c["recommended"] = c is best
            c["done"] = _done(f, decision_id, c["id"])
            c["why"] = _why(best, cands, p) if c is best else None
            c["metrics"] = _metrics(f, c, decision_id)
        dec = {"id": decision_id, "question": question,
               "options": [{k: c[k] for k in ("id", "title", "recommended", "why", "metrics", "effects", "done", "expected_loss")}
                           for c in shown]}

    return {
        "event_id": ev["id"],
        "clock": f.clock(f.now_min),
        "minutes_since_start": round(f.now_min),
        "probability": prob,
        "risk": risk_context(f),
        "decision": dec,
        "receipts": receipts(conn, f),
        "model": decision.described(f.cfg),
    }


def _why(best: dict, cands: list[dict], p: float) -> str:
    others = [c for c in cands if c is not best]
    lead = f"Lowest expected loss: ~{best['expected_loss']:,.0f} ac-equivalent"
    if others:
        runner = others[0]
        lead += f", vs ~{runner['expected_loss']:,.0f} for “{runner['title']}”"
        x = decision.break_even(best, runner)
        if x is not None:
            lead += (f". That flips if P(fire) {'rises above' if x > p else 'falls below'} {x:.0%}")
    return lead + "."


def _metrics(f: Fire, c: dict, decision_id: str) -> list[dict]:
    out = []
    if decision_id == "respond":
        out.append({"label": "District paged", "value": "now" if c["page_min"] <= f.now_min + 0.5 else f"~{f.clock(c['page_min'])} if confirmed"})
    help_at = f"~{f.clock(c['help_min'])}" if c["help_min"] is not None else "never"
    out += [
        {"label": "If it's a fire", "value": f"~{c['if_fire_acres']:,} ac by the time enough help is there ({help_at}, {c['help']})"},
        {"label": "If it's not", "value": f"{c['if_not_text']} (~{c['if_not_cost']:,.0f} ac-eq)"},
        {"label": "Expected loss", "value": f"~{c['expected_loss']:,.0f} ac-equivalent"},
    ]
    if c["stations"]:
        out.append({"label": "Stations warned ahead", "value": str(c["stations"])})
    return out


def _done(f: Fire, decision_id: str, option_id: str) -> str | None:
    """When this option was already chosen for this decision (scenario clock), or None."""
    for p in f.state.get("playbook", []):
        if p["decision"] == decision_id and p["option"] == option_id and parse_iso(p["at"]) <= f.now:
            return f.clock((parse_iso(p["at"]) - f.t0).total_seconds() / 60)
    return None


def _page_min(f: Fire) -> float | None:
    at = f.state.get("page_at")
    return (parse_iso(at) - f.t0).total_seconds() / 60 if at and parse_iso(at) <= f.now else None


# ---------- doing it, and the receipt ----------

def execute(conn: sqlite3.Connection, ev, option_id: str, operator: str) -> dict:
    current = options(conn, ev)["decision"]
    if current is None or option_id not in {o["id"] for o in current["options"]}:
        raise ValueError(f"{option_id!r} is not an option right now")
    if next(o for o in current["options"] if o["id"] == option_id)["done"]:
        raise ValueError("already done")
    f = Fire(conn, ev)
    now, eid = f.now, ev["id"]
    before = conn.execute("SELECT COALESCE(MAX(id), 0) m FROM messages").fetchone()["m"]
    sample = bool(ev["is_sample"])

    if option_id in ("page", "heads_up_ask", "heads_up_recheck", "heads_up_only") and not _heads_up_sent(conn, f):
        for s in f.stations_in_path(conn):
            notify.send(conn, s["contact"], notify.t_heads_up(ev, s["contact"], s["eta"], f.wind), "heads_up", eid, now, sample)
    if option_id == "page":
        notify.decide(conn, eid, "page", operator, now)
    elif option_id == "mutual_aid_now":
        notify.decide(conn, eid, "send", operator, now)
    elif option_id in ("ask", "heads_up_ask"):
        state = notify._state(notify._event(conn, eid))
        if not state.get("asked"):
            asked = notify.ask_neighbors(conn, ev, now)
            state["asked"] = [x["contact_id"] for x in asked]
            notify._save(conn, eid, state)

    sent = conn.execute(
        "SELECT m.purpose, COUNT(*) n FROM messages m WHERE m.id > ? AND m.event_id = ? AND m.direction = 'out' GROUP BY m.purpose",
        (before, eid)).fetchall()
    state = notify._state(notify._event(conn, eid))
    title = next(o["title"] for o in current["options"] if o["id"] == option_id)
    rec = next(o["id"] for o in current["options"] if o["recommended"])
    state.setdefault("playbook", []).append({
        "decision": current["id"], "option": option_id, "title": title, "by": operator, "at": iso(now),
        "followed_recommendation": option_id == rec, "sent": {r["purpose"]: r["n"] for r in sent},
    })
    notify._save(conn, eid, state)
    conn.execute("INSERT INTO actions(event_id, action, operator, note, created_at) VALUES (?, ?, ?, ?, ?)",
                 (eid, f"playbook:{option_id}", operator, title, iso(now)))
    return options(conn, notify._event(conn, eid))


PURPOSE_LABEL = {
    "page": "volunteers paged", "page_dispatch": "dispatch told to tone out", "downwind": "people in the path warned",
    "helper": "helpers asked", "mutual_aid": "mutual-aid request sent", "mutual_aid_draft": "mutual-aid draft to the chief",
    "ask_neighbor": "neighbors asked", "heads_up": "stations given a heads-up", "duty_fyi": "duty officer told",
    "duty_escalate": "duty officer asked to page",
}


def receipts(conn: sqlite3.Connection, f: Fire) -> list[dict]:
    """Everything that has been done for this fire, newest first: playbook choices and the automatic steps."""
    eid, t0 = f.ev["id"], f.t0
    out = []
    for p in f.state.get("playbook", []):
        if parse_iso(p["at"]) > f.now:
            continue
        out.append({"at": p["at"], "clock": f.clock((parse_iso(p["at"]) - t0).total_seconds() / 60), "by": p["by"],
                    "title": p["title"], "followed_recommendation": p["followed_recommendation"],
                    "results": [f"{n} {PURPOSE_LABEL.get(k, k)}" for k, n in p["sent"].items()] or ["Logged"]})
    chosen = {p["at"] for p in f.state.get("playbook", [])}
    # Steps that happened without a playbook choice (automatic, or a text reply like PAGE from the duty officer)
    rows = conn.execute(
        "SELECT purpose, created_at, COUNT(*) n FROM messages WHERE event_id = ? AND direction = 'out' "
        "GROUP BY purpose, created_at ORDER BY created_at", (eid,)).fetchall()
    grouped: dict[str, list[str]] = {}
    for r in rows:
        if r["created_at"] in chosen or parse_iso(r["created_at"]) > f.now:
            continue
        grouped.setdefault(r["created_at"], []).append(f"{r['n']} {PURPOSE_LABEL.get(r['purpose'], r['purpose'])}")
    st = f.state
    for at, results in grouped.items():
        by = st.get("decision_by") if at == st.get("decision_at") else (
            (st.get("mutual_aid") or {}).get("sent_by") if at == (st.get("mutual_aid") or {}).get("sent_at") else "Firewatch (automatic)")
        title = "Paged the district" if at == st.get("decision_at") and st.get("decision") == "page" else (
            "Requested mutual aid" if at == (st.get("mutual_aid") or {}).get("sent_at") else "Automatic step")
        out.append({"at": at, "clock": f.clock((parse_iso(at) - t0).total_seconds() / 60), "by": by, "title": title,
                    "followed_recommendation": None, "results": results})
    return sorted(out, key=lambda r: r["at"], reverse=True)
