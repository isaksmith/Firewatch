import gzip
import hashlib
import json

from fastapi.testclient import TestClient

from app import fw1, scenario
from app.db import connect
from app.main import app

ORIGIN = (37.2689, -99.3268)
client = TestClient(app)


def test_packs_index_and_pack_with_etag():
    idx = client.get("/api/m/packs")
    assert idx.status_code == 200
    codes = {p["code"] for p in idx.json()}
    assert {"cwc", "ks-comanche", "ks-clark", "ks-barber"} <= codes
    r = client.get("/api/m/packs/cwc", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    pack = r.json()
    assert pack["format"] == "fwpack/1" and pack["code"] == "cwc" and pack["origin"] == {"lat": 37.2689, "lon": -99.3268}
    meta = next(p for p in idx.json() if p["code"] == "cwc")
    etag = r.headers["etag"]
    assert etag == f'"{meta["sha256"]}"'
    assert client.get("/api/m/packs/cwc", headers={"If-None-Match": etag}).status_code == 304
    assert "+1316" not in json.dumps(pack) and "phone" not in json.dumps(pack)


def test_unknown_pack_is_404_in_plain_words():
    r = client.get("/api/m/packs/nope")
    assert r.status_code == 404 and "don't have a map pack" in r.json()["detail"]
    assert client.get("/api/m/packs/..%2Findex").status_code == 404


def test_packs_stay_under_target_and_have_no_phone_numbers():
    from app.config import DATA_DIR

    for p in json.loads((DATA_DIR / "packs" / "index.json").read_text()):
        raw = (DATA_DIR / "packs" / f"{p['code']}.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == p["sha256"] and len(raw) == p["bytes"]
        assert len(gzip.compress(raw)) <= 1_500_000 and b"+1316" not in raw


def test_replay_fills_the_feed_and_chief_gets_the_app_text():
    scenario.run_now("cottonwood-creek")
    r = client.get("/api/m/feed?pack=cwc&since=0")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    lines = r.text.strip().split("\n")
    assert 1 <= len(lines) <= 50
    seqs = [int(l.split(" ")[0]) for l in lines]
    assert seqs == sorted(seqs)
    decoded = [fw1.decode(l.split(" ")[1], ORIGIN) for l in lines]
    assert decoded[-1]["level"] == "escalate" and "exercise" in decoded[-1]["flags"] and "red_flag" in decoded[-1]["flags"]
    assert (decoded[-1]["lat"], decoded[-1]["lon"]) == (37.3821, -99.4681)
    # the head speed comes from the forecast's median, inside the forecast's own range
    esc = [d for d in decoded if d["level"] == "escalate"][0]
    assert esc["mph"] is not None and esc["toward_deg"] is not None
    rng = client.get("/api/scenario/cottonwood-creek/forecast").json()["head_ros_kmh"]
    lo, hi = rng["p10"] / 1.609344 - 0.5, rng["p90"] / 1.609344 + 0.5
    assert lo <= esc["mph"] <= hi, (esc["mph"], rng)
    assert [d["time"] for d in decoded] == sorted(d["time"] for d in decoded)
    # nothing newer than the last line, and the ETag short-circuits
    assert client.get(f"/api/m/feed?pack=cwc&since={seqs[-1]}").text == ""
    assert client.get("/api/m/feed?pack=cwc&since=0", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert client.get("/api/m/feed?pack=other&since=0").text == ""
    with connect() as conn:
        chief = conn.execute("SELECT id FROM contacts WHERE role = 'chief'").fetchone()["id"]
        msgs = conn.execute("SELECT body, is_sample, purpose FROM messages WHERE contact_id = ? AND direction = 'out' ORDER BY id", (chief,)).fetchall()
        links = [m for m in msgs if m["body"].startswith("Firewatch app: firewatch://a/")]
        assert links and all(m["is_sample"] == 1 for m in links)
        code = links[0]["body"].split("/a/")[1]
        assert fw1.decode(code, ORIGIN)["pack"] == "cwc"
        # people who are not app users get no second text
        other = conn.execute("SELECT COUNT(*) FROM messages m JOIN contacts c ON c.id = m.contact_id WHERE c.app = 0 AND m.body LIKE 'Firewatch app:%'").fetchone()[0]
        assert other == 0
