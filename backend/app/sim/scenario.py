"""System simulation of the Cottonwood Creek alarm chain: today vs. Firewatch.

Pure Python, no DB, no network. Times are minutes since local midnight
(1:50 pm = 830). The model is a chain of delays; each stage adds a delay to the
previous stage, and the sweep varies the uncertain ones. Nothing about the
Firewatch outcome is hard-coded: it falls out of the inputs in `Params`.

Sources: docs/PLAN.md 2a/2b, design/SCENARIO.md, docs/RESEARCH.md. Every number
not traced to those is marked "assumption" in PARAM_DOCS.
"""
from __future__ import annotations

import itertools
import math
import statistics
from dataclasses import dataclass, fields, replace

Event = tuple  # (minute, actor, event)

# ---- Source or "assumption" for every Params field (tests check coverage) ----
PARAM_DOCS = {
    "ignition_min": "SCENARIO.md: line falls 1:50 pm (830 min since midnight).",
    "fault_telemetry": "PLAN 2a: co-op may or may not see the fault; 40-year-old oil-lease taps may have only fuses. Swept on/off.",
    "fault_notice_delay": "assumption: 1 min for a co-op SCADA fault event to reach us.",
    "goes_delay": "RESEARCH.md: GOES scans every 5-10 min, FIRMS relay 20-30 min (not used). Default 10 matches SCENARIO.md first look ~2:00. Swept 5/10/20/30.",
    "rescan_delay": "assumption: without fault corroboration a lone hotspot waits one more GOES scan (RESEARCH: scans every 5-10 min; 5 used).",
    "score_confirm": "assumption: 1.5 min to ingest, score and match against the burn-call log.",
    "channel": "PLAN 2c: push, sms, pager or mesh. Delay in CHANNEL_DELAY.",
    "chief_response": "assumption: minutes for the chief to read the push and tap 'page district'. Swept 1/3/6.",
    "turnout": "SCENARIO.md: page 2:23 to Brush 1 rolling 2:34 = 11 min.",
    "drive": "SCENARIO.md: roll 2:34 to on scene 2:52 = 18 min (11 mi of gravel).",
    "first_smoke_seen": "SCENARIO.md: driver sees smoke 2:17 = 27 min after ignition.",
    "no_signal_walk": "SCENARIO.md: no signal for 3 mi, 911 call at 2:21 = 4 min after the sighting.",
    "call_911_to_page": "SCENARIO.md: 911 call 2:21 to district paged 2:23 = 2 min.",
    "head_rate_mph": "PLAN/SCENARIO: head about 3 mph in the scenario wind. Held constant from ignition (assumption: no ramp-up).",
    "length_width_ratio": "SCENARIO.md: 60-min forecast is ~3 mi long by 1.2 mi wide = 2.5. Applied to the fire at any age (assumption).",
}

# Delivery delay in minutes per channel (all assumption except where noted).
CHANNEL_DELAY = {
    "push": 0.5,   # assumption: one bar of cell, small payload (PLAN 2c)
    "sms": 1.5,    # assumption: carrier queue on one bar
    "pager": 1.0,  # assumption: county radio pager
    "mesh": 3.0,   # assumption: store-and-forward relay
}
CHANNELS = tuple(CHANNEL_DELAY)


@dataclass(frozen=True)
class Params:
    ignition_min: float = 830.0
    fault_telemetry: bool = True
    fault_notice_delay: float = 1.0
    goes_delay: float = 10.0
    rescan_delay: float = 5.0
    score_confirm: float = 1.5
    channel: str = "push"
    chief_response: float = 3.0
    turnout: float = 11.0
    drive: float = 18.0
    first_smoke_seen: float = 27.0
    no_signal_walk: float = 4.0
    call_911_to_page: float = 2.0
    head_rate_mph: float = 3.0
    length_width_ratio: float = 2.5


def fmt(minute: float) -> str:
    """Minutes since midnight -> '2:52 pm' (rounded to the nearest minute)."""
    m = int(round(minute))
    h, mm = divmod(m, 60)
    suffix = "pm" if 12 <= h % 24 else "am"
    h12 = h % 12 or 12
    return f"{h12}:{mm:02d} {suffix}"


def fire_size(age_min: float, p: Params) -> tuple:
    """(head distance in miles, area in acres) at a given fire age.

    Head travels at head_rate_mph; the burn is an ellipse whose long axis is
    the head distance and whose short axis is length / ratio. Area = pi/4*L*W.
    """
    length = p.head_rate_mph * age_min / 60.0
    width = length / p.length_width_ratio
    return length, math.pi / 4 * length * width * 640.0


def _outcome(p: Params, timeline: list, page: float) -> dict:
    roll = page + p.turnout
    arrive = roll + p.drive
    timeline.append((roll, "Brush 1", "rolls"))
    timeline.append((arrive, "Brush 1", "on scene"))
    timeline.sort(key=lambda e: e[0])
    age = arrive - p.ignition_min
    head, acres = fire_size(age, p)
    return {
        "timeline": timeline, "page": page, "roll": roll, "on_scene": arrive,
        "fire_age": age, "head_mi": head, "acres": acres,
    }


def _today_page(p: Params, timeline: list) -> float:
    seen = p.ignition_min + p.first_smoke_seen
    call = seen + p.no_signal_walk
    page = call + p.call_911_to_page
    timeline.append((p.ignition_min, "Fire", "line falls, ignition"))
    timeline.append((seen, "Driver", "sees smoke, no signal"))
    timeline.append((call, "Driver", "reaches a bar, calls 911"))
    timeline.append((page, "Dispatch", "district paged"))
    return page


def run_today(p: Params) -> dict:
    """Today's chain: smoke seen -> walk to signal -> 911 -> page -> turnout -> drive."""
    tl: list = []
    page = _today_page(p, tl)
    return _outcome(p, tl, page)


def run_firewatch(p: Params) -> dict:
    """Firewatch chain; the 911 chain keeps running, so we page at the earlier of the two.

    Satellite path: GOES first look -> (no fault corroboration: wait one more
    scan) -> score and confirm -> delivery channel -> chief taps page.
    A fault alone is only a quiet 'watch' push (PLAN 2a), never a page.
    """
    tl: list = []
    t0 = p.ignition_min
    tl.append((t0, "Fire", "line falls, ignition"))
    look = t0 + p.goes_delay
    if p.fault_telemetry:
        tl.append((t0 + p.fault_notice_delay, "Co-op feed", "fault seen, quiet 'watch' push (no page)"))
        tl.append((look, "GOES", "hotspot at the fault, corroborated"))
        confirm_start = look
    else:
        tl.append((look, "GOES", "lone hotspot, low confidence, waits for next scan"))
        confirm_start = look + p.rescan_delay
        tl.append((confirm_start, "GOES", "second scan confirms"))
    scored = confirm_start + p.score_confirm
    tl.append((scored, "Firewatch", "scored and confirmed, burns ruled out"))
    delivered = scored + CHANNEL_DELAY[p.channel]
    tl.append((delivered, "Chief", f"alert arrives by {p.channel}"))
    sat_page = delivered + p.chief_response
    tl.append((sat_page, "Chief", "pages district, requests mutual aid"))
    today_page = _today_page(p, [])
    page = min(sat_page, today_page)
    if today_page < sat_page:
        tl.append((today_page, "Dispatch", "911 page beats the satellite path"))
    return _outcome(p, tl, page)


DEFAULT_GRID = {
    "fault_telemetry": [True, False],
    "goes_delay": [5.0, 10.0, 20.0, 30.0],
    "channel": ["push", "sms", "pager"],
    "chief_response": [1.0, 3.0, 6.0],
}


def sweep(grid: dict | None = None, base: Params | None = None) -> list:
    """Run every combination of the grid. Returns one dict per case."""
    grid = DEFAULT_GRID if grid is None else grid
    base = base or Params()
    keys = list(grid)
    out = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        over = dict(zip(keys, combo))
        p = replace(base, **over)
        t, f = run_today(p), run_firewatch(p)
        out.append({
            "params": over, "today": t, "firewatch": f,
            "minutes_saved": t["on_scene"] - f["on_scene"],
        })
    return out


def summarize(results: list) -> dict:
    saved = [r["minutes_saved"] for r in results]
    fw = [r["firewatch"]["acres"] for r in results]
    return {
        "cases": len(results),
        "saved_min": min(saved), "saved_median": statistics.median(saved), "saved_max": max(saved),
        "today_acres": results[0]["today"]["acres"],
        "firewatch_acres_min": min(fw), "firewatch_acres_max": max(fw),
    }
