"""Print the Cottonwood Creek system simulation: timelines, sweep, summary."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.sim.scenario import Params, fmt, run_firewatch, run_today, summarize, sweep  # noqa: E402


def _strip(o):
    d = {k: v for k, v in o.items() if k != "timeline"}
    d["timeline"] = [[round(m, 2), a, e] for m, a, e in o["timeline"]]
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine output")
    a = ap.parse_args()
    p = Params()
    t, f = run_today(p), run_firewatch(p)
    res = sweep()
    s = summarize(res)
    line = (f"minutes saved: {s['saved_min']:.0f} / {s['saved_median']:.0f} / {s['saved_max']:.0f} "
            f"(min / median / max); fire size at arrival: today {s['today_acres']:.0f} acres, "
            f"Firewatch {s['firewatch_acres_min']:.0f} to {s['firewatch_acres_max']:.0f} acres")
    if a.json:
        print(json.dumps({"default_today": _strip(t), "default_firewatch": _strip(f),
                          "sweep": [{"params": r["params"], "minutes_saved": r["minutes_saved"],
                                     "on_scene": fmt(r["firewatch"]["on_scene"]),
                                     "acres": r["firewatch"]["acres"]} for r in res],
                          "summary": s, "summary_line": line}, indent=2))
        return
    for name, o in (("TODAY (911 only)", t), ("FIREWATCH (defaults)", f)):
        print(f"\n{name}")
        for m, actor, ev in o["timeline"]:
            print(f"  {fmt(m):>8}  {actor:<10} {ev}")
        print(f"  page {fmt(o['page'])}, on scene {fmt(o['on_scene'])}, fire age {o['fire_age']:.0f} min, "
              f"head {o['head_mi']:.1f} mi out, {o['acres']:.0f} acres")
    print(f"\nSWEEP ({len(res)} cases)")
    print(f"{'fault':<6}{'goes':>5}  {'channel':<7}{'chief':>5}  {'page':>8}  {'on scene':>9}  {'saved':>5}  {'acres':>6}")
    for r in res:
        q, w = r["params"], r["firewatch"]
        print(f"{'on' if q['fault_telemetry'] else 'off':<6}{q['goes_delay']:>5.0f}  {q['channel']:<7}"
              f"{q['chief_response']:>5.0f}  {fmt(w['page']):>8}  {fmt(w['on_scene']):>9}  "
              f"{r['minutes_saved']:>5.1f}  {w['acres']:>6.0f}")
    zero = [r for r in res if r["minutes_saved"] == 0]
    print(f"\nWorst case: {len(zero)} of {len(res)} cases save 0 min (the 911 page wins, Firewatch adds nothing), "
          "e.g. a GOES first look of 30 min, with or without fault telemetry.")
    print("\n" + line)


if __name__ == "__main__":
    main()
