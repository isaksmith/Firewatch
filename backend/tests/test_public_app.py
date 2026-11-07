from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import scenario
from app.config import get_settings
from app.db import connect, iso, parse_iso, utcnow
from app.main import app
from tests.test_routes_posts import PT, hd, member, post

SLUG = "cottonwood-creek-packet"
TOKEN = "s3cret-token"

TOKEN_ROUTES = [
    ("POST", "/api/ingest/run"),
    ("POST", "/api/sample/replay"),
    ("POST", "/api/sample/load"),
    (("POST"), f"/api/scenario/{SLUG}/run"),
    ("POST", f"/api/scenario/{SLUG}/load"),
    ("GET", "/api/contacts"),
    ("POST", "/api/sms/inbound"),
]


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("method,path", TOKEN_ROUTES)
def test_token_routes_refuse_without_token(secured, method, path):
    with TestClient(app) as c:
        assert c.request(method, path, json={"from": "+15550001111", "body": "hi"}).status_code == 401
        assert c.request(method, path, headers={"X-Firewatch-Token": "wrong"}, json={}).status_code == 401
        r = c.request(method, path, headers={"X-Firewatch-Token": TOKEN}, json={"from": "+15550001111", "body": "hi"})
        assert r.status_code != 401


def _write_clock(slug, t_min, running, age_s=0):
    with connect() as conn:
        conn.execute("DELETE FROM replay_clock")
        conn.execute("INSERT INTO replay_clock(id, slug, t_min, running, updated_at) VALUES (1,?,?,?,?)",
                     (slug, t_min, int(running), iso(utcnow() - timedelta(seconds=age_s))))


def test_run_now_writes_clock_row():
    scenario.run_now(SLUG, 3)
    with connect() as conn:
        row = conn.execute("SELECT * FROM replay_clock").fetchone()
    assert row["slug"] == SLUG and row["t_min"] == 3 and row["running"] == 0


def test_running_now_reads_row_in_other_process(monkeypatch):
    monkeypatch.setattr(scenario, "_clock", {})
    _write_clock(SLUG, 7, True)
    t0 = parse_iso(scenario.load_scenario(SLUG)["t0"])
    assert scenario.running_now() == t0 + timedelta(minutes=7)


def test_running_now_ignores_stale_row(monkeypatch):
    monkeypatch.setattr(scenario, "_clock", {})
    _write_clock(SLUG, 7, True, age_s=200)
    assert scenario.running_now() is None


def test_running_now_ignores_stopped_row(monkeypatch):
    monkeypatch.setattr(scenario, "_clock", {})
    _write_clock(SLUG, 7, False)
    assert scenario.running_now() is None


def test_lifespan_stops_stored_clock(monkeypatch):
    _write_clock(SLUG, 7, True)
    with TestClient(app):
        pass
    with connect() as conn:
        assert conn.execute("SELECT running FROM replay_clock").fetchone()["running"] == 0


def test_admin_post_list_shows_station_view():
    m = member("Wes", "spotter", 1)
    with TestClient(app) as c:
        post(c, m, "fire", "Smoke over the ridge")
        r = c.get("/api/board/admin/posts", headers={"X-Firewatch-Token": TOKEN})
        assert r.status_code == 200
        item = r.json()[0]
        assert item["lat"] == PT[0] and item["lon"] == PT[1]
        assert "held" in item and "event_id" in item


# ---- public_app ----

import json as _json

from app import public_app
from app.ratelimit import Limiter, client_ip

ALLOWED = {
    ("GET", "/api/board/me"), ("POST", "/api/board/device"), ("GET", "/api/board/posts"), ("POST", "/api/board/posts"),
    ("POST", "/api/board/posts/{post_id}/confirm"), ("POST", "/api/board/posts/{post_id}/station"),
    ("GET", "/"), ("GET", "/board"), ("GET", "/favicon.svg"), ("GET", "/icons.svg"),
}


@pytest.fixture
def pub():
    public_app.app.state.limiter = Limiter()
    return TestClient(public_app.app)


def _routes():
    out = set()
    for r in public_app.app.routes:
        if hasattr(r, "methods"):
            out.update((m, r.path) for m in r.methods if m != "HEAD")
    return out | _api_routes()


def _api_routes():
    from fastapi.routing import APIRoute
    from app import routes_posts
    out = set()
    for r in routes_posts.public_router.routes:
        if isinstance(r, APIRoute):
            out.update((m, "/api" + r.path) for m in r.methods if m != "HEAD")
    return out


def test_route_inventory_is_allow_list():
    got = _routes()
    assert got == ALLOWED, got ^ ALLOWED
    assert not any(p.startswith("/api/board/admin") for _, p in got)


@pytest.mark.parametrize("path", ["/api/alerts", "/api/contacts", "/api/messages", "/api/members/pending",
                                  "/api/board/admin/posts", "/api/sms/inbound", "/api/scenarios", "/docs", "/openapi.json"])
def test_other_paths_404(pub, path):
    assert pub.get(path).status_code == 404
    assert pub.post(path).status_code in (404, 405)


def _walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _clean(payload):
    for k, v in _walk(payload):
        assert k not in ("held", "event_id", "event_status", "contact_id", "phone", "level"), k
        if k in ("lat", "lon") and v is not None:
            assert round(v, 2) == v, (k, v)


def test_anonymous_views_leak_nothing(pub):
    m = member("Wes")
    pid = post(pub, m, lat=37.71561, lon=-96.60912)
    anon = pub.post("/api/board/device").json()["token"]
    stranger = pub.post("/api/board/device").json()["token"]
    sp = pub.post("/api/board/posts", json={"category": "hazard", "body": "Smoke over the ridge", "lat": 37.71561, "lon": -96.60912},
                  headers=hd(stranger))
    assert sp.status_code == 200
    _clean(sp.json())
    other = pub.post("/api/board/device").json()["token"]
    c = pub.post(f"/api/board/posts/{sp.json()['post_id']}/confirm", json={"kind": "see", "lat": 37.7, "lon": -96.6}, headers=hd(other))
    _clean(c.json())
    lst = pub.get("/api/board/posts", headers=hd(anon)).json()
    assert lst
    _clean(lst)
    c2 = pub.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", "lat": 37.7, "lon": -96.6}, headers=hd(anon))
    _clean(c2.json())
    assert pub.get("/api/board/posts", headers=hd(anon)).json() and True


def test_station_still_exact_on_public_app(pub):
    m = member("Wes")
    post(pub, m, lat=37.71561, lon=-96.60912)
    st = member("Chief", role="chief")
    items = pub.get("/api/board/posts", headers=hd(st)).json()
    assert any(i["lat"] == 37.71561 and i["lon"] == -96.60912 for i in items)


def test_device_limit_per_ip_and_global(pub):
    for _ in range(20):
        assert pub.post("/api/board/device").status_code == 200
    r = pub.post("/api/board/device")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_anonymous_post_limit_6_per_device(pub):
    t = pub.post("/api/board/device").json()["token"]
    for _ in range(6):
        assert pub.post("/api/board/posts", json={"category": "hazard", "body": "Smoke near the road"}, headers=hd(t)).status_code == 200
    r = pub.post("/api/board/posts", json={"category": "hazard", "body": "Smoke near the road"}, headers=hd(t))
    assert r.status_code == 429
    assert r.json()["detail"] == "Too many reports from this device. If there is a fire, call 911."
    assert int(r.headers["retry-after"]) > 0


def test_member_not_ip_limited(pub):
    m = member("Wes")
    for _ in range(31):
        r = pub.post("/api/board/posts", json={"category": "hazard", "body": "Smoke near the road"}, headers=hd(m))
        if r.status_code == 429:
            break
    assert r.status_code == 429  # device limit of 30, not the IP limit of 30 hit sooner
    assert pub.app.state.limiter._hits[f"post_member:dev:{_cid(m)}"].__len__() == 30
    assert not any(k.startswith("post_member:ip") for k in pub.app.state.limiter._hits)


def _cid(token):
    with connect() as conn:
        return conn.execute("SELECT contact_id FROM post_devices WHERE token_hash = ?", (__import__("app.routes_posts", fromlist=["_hash"])._hash(token),)).fetchone()[0]


def test_anonymous_ip_post_limit_30(pub):
    for i in range(5):
        t = pub.post("/api/board/device").json()["token"]
        for _ in range(6):
            assert pub.post("/api/board/posts", json={"category": "hazard", "body": "Smoke near the road"}, headers=hd(t)).status_code == 200
    t = pub.post("/api/board/device").json()["token"]
    assert pub.post("/api/board/posts", json={"category": "hazard", "body": "Smoke near the road"}, headers=hd(t)).status_code == 429


def test_read_limit_120_per_minute(pub):
    for _ in range(120):
        assert pub.get("/api/board/posts").status_code == 200
    r = pub.get("/api/board/posts")
    assert r.status_code == 429 and "retry-after" in r.headers


def test_bad_token_creates_no_device_keys(pub):
    r = pub.post("/api/board/posts", json={"category": "hazard", "body": "Smoke near the road"}, headers=hd("nope"))
    assert r.status_code == 401
    r = pub.post("/api/board/posts/1/confirm", json={"kind": "see"}, headers=hd("nope"))
    assert r.status_code == 401
    assert len(pub.app.state.limiter) == 0


def test_main_app_never_limits():
    c = TestClient(app)
    assert not hasattr(app.state, "limiter")
    for _ in range(25):
        assert c.post("/api/board/device").status_code == 200


def test_limiter_unit():
    lim = Limiter()
    assert lim.hit("k", 2, 10, now=0) is None
    assert lim.hit("k", 2, 10, now=1) is None
    assert lim.hit("k", 2, 10, now=2) == 9
    assert lim.hit("k", 2, 10, now=3) is not None  # refused hits did not extend the window
    assert lim.hit("k", 2, 10, now=10.5) is None
    assert len(lim._hits["k"]) == 2


def test_limiter_caps_keys(monkeypatch):
    from app import ratelimit
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 5)
    lim = Limiter()
    for i in range(9):
        lim.hit(f"k{i}", 1, 100, now=0)
    assert len(lim) == 5 and "k0" not in lim._hits and "k8" in lim._hits


class _Req:
    def __init__(self, host, headers):
        self.client = type("C", (), {"host": host})() if host is not None else None
        self.headers = headers


def _setting(monkeypatch, header):
    monkeypatch.setenv("FORWARDED_IP_HEADER", header)
    get_settings.cache_clear()


def test_forwarded_ip_rules(monkeypatch):
    _setting(monkeypatch, "cf-connecting-ip")
    assert client_ip(_Req("10.0.0.5", {"cf-connecting-ip": "1.2.3.4"})) == "10.0.0.5"  # spoof from non-loopback
    assert client_ip(_Req("127.0.0.1", {"cf-connecting-ip": "1.2.3.4"})) == "1.2.3.4"
    assert client_ip(_Req("::1", {"cf-connecting-ip": "1.2.3.4"})) == "1.2.3.4"
    assert client_ip(_Req("127.0.0.1", {"cf-connecting-ip": "garbage"})) == "127.0.0.1"
    assert client_ip(_Req("127.0.0.1", {})) == "127.0.0.1"
    assert client_ip(_Req(None, {})) == "unknown"
    _setting(monkeypatch, "x-forwarded-for")
    assert client_ip(_Req("127.0.0.1", {"x-forwarded-for": "9.9.9.9, 1.2.3.4"})) == "1.2.3.4"
    _setting(monkeypatch, "")
    assert client_ip(_Req("127.0.0.1", {"cf-connecting-ip": "1.2.3.4"})) == "127.0.0.1"


def test_forwarded_ips_count_as_two_ips_for_confirms(monkeypatch):
    _setting(monkeypatch, "cf-connecting-ip")
    c = TestClient(public_app.app, client=("127.0.0.1", 50000))
    public_app.app.state.limiter = Limiter()
    m = member("Wes")
    pid = post(c, m, lat=37.7712, lon=-96.6634)
    a = c.post("/api/board/device", headers={"cf-connecting-ip": "1.1.1.1"}).json()["token"]
    b = c.post("/api/board/device", headers={"cf-connecting-ip": "2.2.2.2"}).json()["token"]
    ra = c.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", "lat": 37.77, "lon": -96.66}, headers={**hd(a), "cf-connecting-ip": "1.1.1.1"})
    rb = c.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", "lat": 37.77, "lon": -96.66}, headers={**hd(b), "cf-connecting-ip": "2.2.2.2"})
    assert ra.json()["counted"] and rb.json()["counted"]
    # same peer without the header: both devices share one IP, the second does not count
    c2 = TestClient(public_app.app, client=("10.1.1.1", 50000))
    x = c2.post("/api/board/device").json()["token"]
    y = c2.post("/api/board/device").json()["token"]
    pid2 = post(c2, member("Ann"), lat=37.7712, lon=-96.6634)
    r1 = see_(c2, x, pid2)
    r2 = see_(c2, y, pid2)
    assert r1.json()["counted"] and r2.json().get("duplicate")
    _clean(r2.json())


def see_(c, t, pid):
    return c.post(f"/api/board/posts/{pid}/confirm", json={"kind": "see", "lat": 37.77, "lon": -96.66}, headers=hd(t))


def test_body_cap_content_length_and_streamed(pub):
    t = pub.post("/api/board/device").json()["token"]
    big = _json.dumps({"category": "hazard", "body": "x" * 20000})
    r = pub.post("/api/board/posts", content=big, headers={**hd(t), "content-type": "application/json"})
    assert r.status_code == 413

    def gen():
        for _ in range(20):
            yield b"x" * 1024

    r = pub.post("/api/board/posts", content=gen(), headers={**hd(t), "content-type": "application/json"})
    assert r.status_code == 413


def test_security_headers_and_no_cors(pub):
    for path in ("/api/board/posts", "/board", "/nothing"):
        r = pub.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert "access-control-allow-origin" not in r.headers
    assert pub.get("/api/board/posts").headers["cache-control"] == "no-store"
    r = pub.get("/api/board/posts", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_static_serving(pub, tmp_path, monkeypatch):
    monkeypatch.setattr(public_app, "DIST", tmp_path / "dist")
    assert pub.get("/board").status_code == 503
    assert pub.get("/assets/x.js").status_code == 404
    assert pub.get("/", follow_redirects=False).status_code == 307
    assert pub.get("/", follow_redirects=False).headers["location"] == "/board"
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>board</html>")
    (d / "assets" / "a.js").write_text("1")
    (tmp_path / "secret").write_text("no")
    assert pub.get("/board").text == "<html>board</html>"
    assert pub.get("/assets/a.js").status_code == 200
    assert pub.get("/assets/x.js").status_code == 404
    assert pub.get("/assets/../../secret").status_code == 404
    assert pub.get("/assets/%2e%2e/%2e%2e/secret").status_code == 404
    assert pub.get("/index.html").status_code == 404


REPLAY_ROUTES = [r for r in TOKEN_ROUTES if r[1] not in ("/api/contacts", "/api/sms/inbound")]


@pytest.fixture
def live_no_token(monkeypatch):
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("API_TOKEN", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("method,path", REPLAY_ROUTES)
def test_replay_routes_fail_closed_live_with_blank_token(live_no_token, method, path):
    assert TestClient(app).request(method, path).status_code == 503


def _shared_row_running():
    scenario._clock.clear()
    with connect() as conn:
        conn.execute("INSERT INTO replay_clock(id, slug, t_min, running, updated_at) VALUES (1,?,?,1,?) "
                     "ON CONFLICT(id) DO UPDATE SET slug = excluded.slug, t_min = excluded.t_min, running = 1, "
                     "updated_at = excluded.updated_at", (SLUG, 5, iso(utcnow())))


def test_live_mode_ignores_another_process_replay_clock(live_no_token):
    _shared_row_running()
    assert scenario.running_now() is None


def test_real_public_post_stays_real_during_a_replay(live_no_token):
    from app import public_app
    _shared_row_running()
    c = TestClient(public_app.app, client=("127.0.0.1", 50000))
    token = c.post("/api/board/device").json()["token"]
    r = c.post("/api/board/posts", json={"category": "fire", "body": "smoke over the ridge", "lat": 37.7, "lon": -96.6},
               headers={"X-Firewatch-Device": token})
    assert r.status_code == 200
    with connect() as conn:
        assert conn.execute("SELECT is_sample FROM posts WHERE id = ?", (r.json()["post_id"],)).fetchone()["is_sample"] == 0


def test_shutdown_clears_the_shared_clock():
    with TestClient(app):
        _shared_row_running()
    with connect() as conn:
        assert conn.execute("SELECT running FROM replay_clock WHERE id = 1").fetchone()["running"] == 0


def test_create_says_alerted_without_an_event_id():
    from app import public_app
    c = TestClient(public_app.app, client=("127.0.0.1", 50000))
    body = {"category": "fire", "body": "smoke", "lat": 37.7, "lon": -96.6}
    anon = c.post("/api/board/device").json()["token"]
    r = c.post("/api/board/posts", json=body, headers=hd(anon)).json()
    assert r["alerted"] is False and "event_id" not in r
    m = member("Wes")
    r = c.post("/api/board/posts", json=body, headers=hd(m)).json()
    assert r["alerted"] is True and "event_id" not in r
