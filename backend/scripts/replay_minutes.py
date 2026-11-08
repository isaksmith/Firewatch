"""Measured minutes for each packet scenario: first Investigate, first Escalate, who was asked, texts sent.

Usage (from backend/):  .venv/bin/python -m scripts.replay_minutes
Runs the real scenario code in sample mode against a throwaway database. No network, no live weather.
Prints only what the replay produced.
"""

import os
import tempfile
from pathlib import Path

SLUGS = [
    "cottonwood-creek-packet",
    "cottonwood-creek-packet-no-fault",
    "cottonwood-creek-packet-ring-off",
    "cottonwood-creek-packet-ring-on",
]


def measure(slug: str) -> dict:
    from app import scenario
    from app.config import get_settings
    from app.db import connect, init_db, loads, parse_iso

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DB_PATH"] = str(Path(tmp) / "replay.sqlite")
        os.environ["MODE"] = "sample"
        get_settings.cache_clear()
        init_db()
        scenario.run_now(slug)
        st = scenario.status(slug)
        t0 = parse_iso(scenario.load_scenario(slug)["t0"])
        inv, esc = [], []
        with connect() as conn:
            for ev in conn.execute("SELECT response_json FROM events WHERE sample_slug = ?", (slug,)):
                state = loads(ev["response_json"], {}) or {}
                for key, out in (("investigate_at", inv), ("escalate_at", esc)):
                    if state.get(key):
                        out.append(round((parse_iso(state[key]) - t0).total_seconds() / 60, 1))
            asked = [
                r["name"]
                for r in conn.execute(
                    "SELECT c.name FROM messages m JOIN events e ON e.id = m.event_id "
                    "LEFT JOIN contacts c ON c.id = m.contact_id "
                    "WHERE e.sample_slug = ? AND m.direction = 'out' AND m.purpose = 'ask_neighbor' ORDER BY m.id",
                    (slug,),
                )
            ]
        get_settings.cache_clear()
    # Earliest across all events. scenario.status() reports only the last event that has investigate_at,
    # which here is the registered-burn event at minute 38, so it cannot be used for the first minute.
    return {"slug": slug, "investigate": min(inv, default=None), "escalate": min(esc, default=None),
            "asked": asked, "texts": st["texts_sent"]}


def main() -> None:
    for slug in SLUGS:
        r = measure(slug)
        print(slug)
        print(f"  first Investigate: minute {r['investigate']}")
        print(f"  first Escalate:    minute {r['escalate']}")
        print(f"  asked ({len(r['asked'])}): {', '.join(map(str, r['asked'])) or 'nobody'}")
        print(f"  texts sent:        {r['texts']}")


if __name__ == "__main__":
    main()
