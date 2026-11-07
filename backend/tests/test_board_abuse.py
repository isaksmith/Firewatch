"""M4 judge evidence: the board abuse claims, driven through the public server (the one on the internet)."""
import pytest
from fastapi.testclient import TestClient

from app import public_app
from app.db import connect
from app.ratelimit import Limiter
from tests.test_posts import duty, mk

NEAR = {"lat": 37.7712, "lon": -96.6634}
FAR = {"lat": 40.7, "lon": -96.66}  # about 200 miles north


@pytest.fixture
def pub():
    public_app.app.state.limiter = Limiter()
    return TestClient(public_app.app)


def anon(pub):
    return {"X-Firewatch-Device": pub.post("/api/board/device").json()["token"]}


def smoke(pub, h, **kw):
    return pub.post("/api/board/posts", json={"category": "smoke", "body": "Smoke on the ridge", **NEAR, **kw}, headers=h)


def outbound(purpose=None):
    with connect() as conn:
        q = "SELECT purpose FROM messages WHERE direction = 'out'"
        return [r["purpose"] for r in conn.execute(q) if purpose is None or r["purpose"] == purpose]


def test_100_anonymous_posts_page_nobody(pub):
    with connect() as conn:
        duty(conn)
        for _ in range(3):
            mk(conn)
    accepted = limited = 0
    h = anon(pub)
    sent_on_device = 0
    for _ in range(100):
        if sent_on_device == 6:
            h, sent_on_device = anon(pub), 0
        r = smoke(pub, h)
        sent_on_device += 1
        if r.status_code == 200:
            accepted += 1
        else:
            assert r.status_code == 429
            limited += 1
            h, sent_on_device = anon(pub) if pub.post("/api/board/device").status_code == 200 else h, 0
    print(f"\nABUSE anonymous posts: accepted={accepted} limited={limited} pages={len(outbound('page'))} texts={len(outbound())}")
    assert accepted + limited == 100
    assert accepted == 30  # the per-IP cap
    assert not outbound("page")
    assert not [p for p in outbound() if p in ("duty_escalate", "ladder")]
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_cannot_confirm_own_post(pub):
    h = anon(pub)
    pid = smoke(pub, h).json()["post_id"]
    r = pub.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", **NEAR}, headers=h)
    print("\nABUSE own post confirm:", r.json())
    assert r.status_code == 200 and r.json() == {"ok": False, "reason": "own_post"}
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM post_confirms WHERE post_id = ? AND counted = 1", (pid,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_confirm_from_200_miles_counts_for_nothing(pub):
    pid = smoke(pub, anon(pub)).json()["post_id"]
    r = pub.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", **FAR}, headers=anon(pub))
    assert r.json()["counted"] is False and r.json()["reason"] == "too_far"
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0


def _levels():
    with connect() as conn:
        return [r["recommendation"] for r in conn.execute("SELECT recommendation FROM events")]


def test_two_strangers_stay_at_investigate(pub):
    pid = smoke(pub, anon(pub)).json()["post_id"]
    for _ in range(2):
        r = pub.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", **NEAR}, headers=anon(pub))
        assert r.status_code == 200
    lv = _levels()
    print(f"\nABUSE two strangers: levels={lv} pages={len(outbound('page'))}")
    assert lv and set(lv) <= {"investigate", "monitor"}
    assert not outbound("page")


def test_anonymous_tap_never_counts_as_full_source(pub):
    with connect() as conn:
        duty(conn)
        m = mk(conn)
    from tests.test_routes_posts import hd, member, post
    mtoken = member("Wes")
    pid = post(pub, mtoken, category="smoke", body="Smoke on the ridge")
    r = pub.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", **NEAR}, headers=anon(pub))
    assert r.status_code == 200
    lv = _levels()
    print(f"\nABUSE member post + anonymous tap: levels={lv}")
    assert "escalate" not in lv
    assert not outbound("page")


def test_board_ab_replay_no_fault_alarms_earlier_with_assumed_board_activity():
    """Board minutes are ASSUMED (post at 27, tap at 30). Rerun: .venv/bin/python -m scripts.replay_board_ab"""
    from scripts.replay_board_ab import measure

    a = measure("cottonwood-creek-packet-no-fault", False)
    b = measure("cottonwood-creek-packet-no-fault", True)
    print(f"\nAB no-fault: A investigate {a['investigate']} escalate {a['escalate']}; B investigate {b['investigate']} escalate {b['escalate']}")
    assert (a["investigate"], a["escalate"]) == (31.0, 38.0)
    assert (b["investigate"], b["escalate"]) == (27.0, 30.0)
    # With the co-op fault the alarm is already at minute 0, so the board changes nothing there.
    assert measure("cottonwood-creek-packet", True)["escalate"] == 0.0
