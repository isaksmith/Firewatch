"""A/B replay of the Cottonwood Creek packet scenario: without and with community-board activity.

Usage (from backend/):  .venv/bin/python -m scripts.replay_board_ab

Run A is the scenario as written (run for the packet scenario and its no-fault variant). Run B adds two board actions at ASSUMED minutes (the packet has no board):
  minute 27: a registered member near the fire posts "smoke" (27 is when the packet says the propane driver
             actually saw smoke; the board lets a witness post it the moment it is seen).
  minute 30: a second registered member taps "I see it too" (three minutes later, one minute before the
             packet's own 911 call at 31).
The two members are the first two registered, located roster contacts. Their posts are placed at the ignition
point, as a phone's location would place them. Only the two board times and the placement are assumed; every
minute printed is what the real scenario code produced in a throwaway sample database.
"""

import os
import tempfile
from pathlib import Path

SLUGS = ["cottonwood-creek-packet", "cottonwood-creek-packet-no-fault"]
POST_MIN = 27     # ASSUMED
CONFIRM_MIN = 30  # ASSUMED


def measure(SLUG: str, with_board: bool) -> dict:
    from app import posts, scenario
    from app.config import get_settings
    from app.db import connect, init_db, loads, parse_iso
    from app.district import sync_roster

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DB_PATH"] = str(Path(tmp) / "ab.sqlite")
        os.environ["MODE"] = "sample"
        get_settings.cache_clear()
        init_db()
        sc = scenario.load_scenario(SLUG)
        t0 = parse_iso(sc["t0"])
        at = (sc["ignition"]["lat"], sc["ignition"]["lon"])
        scenario.clear()
        with scenario._district_settings(sc), connect() as conn:
            sync_roster(conn, sc["district"])
            members = conn.execute(
                "SELECT * FROM contacts WHERE registered = 1 AND lat IS NOT NULL ORDER BY id LIMIT 2"
            ).fetchall()
            pid = None
            for t in [*scenario._pre_steps(sc), *range(sc["duration_min"] + 1)]:
                if with_board and t == POST_MIN:
                    from datetime import timedelta
                    now = t0 + timedelta(minutes=t)
                    c = members[0]
                    r = posts.create(conn, c, c["phone"], "Smoke across the road", "smoke", False, now,
                                     is_sample=True, channel="web", at=at)
                    pid = r["post_id"]
                if with_board and t == CONFIRM_MIN and pid:
                    from datetime import timedelta
                    now = t0 + timedelta(minutes=t)
                    posts.confirm(conn, pid, members[1], "see", now, is_sample=True, lat=at[0], lon=at[1])
                scenario._minute(conn, sc, t)
                conn.execute("UPDATE events SET sample_slug = ? WHERE is_sample = 1 AND sample_slug IS NULL", (SLUG,))
            inv, esc, page = [], [], []
            for ev in conn.execute("SELECT response_json FROM events WHERE is_sample = 1"):
                state = loads(ev["response_json"], {}) or {}
                for key, out in (("investigate_at", inv), ("escalate_at", esc)):
                    if state.get(key):
                        out.append(round((parse_iso(state[key]) - t0).total_seconds() / 60, 1))
            for m in conn.execute("SELECT purpose, created_at FROM messages WHERE direction = 'out' AND is_sample = 1 "
                                  "AND purpose NOT IN ('ask_neighbor') ORDER BY id"):
                page.append((m["purpose"], round((parse_iso(m["created_at"]) - t0).total_seconds() / 60, 1)))
            asked = conn.execute("SELECT COUNT(*) n FROM messages WHERE direction='out' AND purpose='ask_neighbor' AND is_sample=1").fetchone()["n"]
        get_settings.cache_clear()
    return {"investigate": min(inv, default=None), "escalate": min(esc, default=None), "messages": page, "asked": asked}


def main() -> None:
    print(f"Board times are ASSUMED: post at minute {POST_MIN}, 'I see it too' at minute {CONFIRM_MIN}.")
    for slug, (label, flag) in ((s, x) for s in SLUGS for x in (("A: as written", False), ("B: with board (ASSUMED minutes)", True))):
        r = measure(slug, flag)
        print(f"\n{slug}  {label}")
        print(f"  first Investigate: minute {r['investigate']}")
        print(f"  first Escalate:    minute {r['escalate']}")
        print(f"  asked neighbours:  {r['asked']}")
        print(f"  other texts out (purpose, minute): {r['messages']}")


if __name__ == "__main__":
    main()
