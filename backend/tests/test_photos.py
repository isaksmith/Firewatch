import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import public_app
from app.db import connect, iso, utcnow
from app.main import app
from app.ratelimit import Limiter
from tests.test_routes_posts import _fire_with_event, hd, ids, member, post, pub


def jpeg_bytes(size=(3000, 2000), exif=True, fmt="JPEG"):
    img = Image.new("RGB", size, (200, 80, 20))
    kw = {}
    if exif and fmt == "JPEG":
        ex = Image.Exif()
        ex[0x010F] = "TestCam"
        ex[0x8825] = {1: "N", 2: (37.0, 46.0, 0.0), 3: "W", 4: (96.0, 40.0, 0.0)}
        kw["exif"] = ex
    out = io.BytesIO()
    img.save(out, fmt, **kw)
    return out.getvalue()


def up(c, tok, pid, data, ctype="image/jpeg"):
    return c.post(f"/api/board/posts/{pid}/photo", content=data, headers={**hd(tok), "content-type": ctype})


def stored(pid):
    with connect() as conn:
        return conn.execute("SELECT * FROM post_photos WHERE post_id = ?", (pid,)).fetchone()


@pytest.fixture
def pc():
    public_app.app.state.limiter = Limiter()
    with TestClient(public_app.app) as c:
        yield c


def test_upload_strips_exif_and_resizes():
    raw = jpeg_bytes()
    assert len(Image.open(io.BytesIO(raw)).getexif()) > 0
    with TestClient(app) as c:
        tok = member("Author")
        pid = post(c, tok)
        r = up(c, tok, pid, raw)
        assert r.status_code == 200, r.text
        row = stored(pid)
    img = Image.open(io.BytesIO(row["jpeg"]))
    assert len(img.getexif()) == 0
    assert b"Exif" not in row["jpeg"][:64]
    assert max(img.size) <= 1600
    assert r.json() == {"ok": True, "width": img.width, "height": img.height}


def test_author_station_and_conflict():
    with TestClient(app) as c:
        tok = member("Author")
        pid = post(c, tok)
        assert up(c, member("Other"), pid, jpeg_bytes((50, 50))).status_code == 403
        assert up(c, tok, 9999, jpeg_bytes((50, 50))).status_code == 404
        assert up(c, "", pid, jpeg_bytes((50, 50))).status_code == 401
        assert up(c, member("Duty", "duty_officer"), pid, jpeg_bytes((50, 50))).status_code == 200
        assert up(c, tok, pid, jpeg_bytes((50, 50))).status_code == 409


def test_too_big_main_app():
    with TestClient(app) as c:
        tok = member("Author")
        pid = post(c, tok)
        assert up(c, tok, pid, b"\xff\xd8" + b"0" * (2 * 1024 * 1024)).status_code == 413


def test_too_big_public_app(pc):
    tok = pc.post("/api/board/device").json()["token"]
    big = b"\xff\xd8" + b"0" * (2 * 1024 * 1024 + 8000)
    assert up(pc, tok, 1, big).status_code == 413


def test_public_app_other_route_cap_still_16k(pc):
    tok = pc.post("/api/board/device").json()["token"]
    r = pc.post("/api/board/posts", content=b'{"body": "' + b"x" * 17000 + b'"}', headers={**hd(tok), "content-type": "application/json"})
    assert r.status_code == 413


def test_wrong_type_415():
    with TestClient(app) as c:
        tok = member("Author")
        pid = post(c, tok)
        assert up(c, tok, pid, b"hello, not an image at all").status_code == 415
        assert up(c, tok, pid, jpeg_bytes((50, 50), fmt="PNG")).status_code == 415
        assert up(c, tok, pid, jpeg_bytes((50, 50)), "text/plain").status_code == 415
        assert stored(pid) is None
        assert up(c, tok, pid, jpeg_bytes((50, 50), fmt="PNG"), "image/png").status_code == 200


def test_rate_limit_11th(pc):
    tok = pc.post("/api/board/device").json()["token"]
    codes = [up(pc, tok, 1, b"junk").status_code for _ in range(11)]
    assert 429 not in codes[:10] and codes[10] == 429


def test_photo_visibility_public_and_admin():
    with TestClient(app) as c:
        pid, eid = _fire_with_event(c)
        assert up(c, "tok-Reporter-spotter-1", pid, jpeg_bytes((300, 200))).status_code == 200
        r = c.get(f"/api/board/posts/{pid}/photo")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "private, max-age=300"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert Image.open(io.BytesIO(r.content)).size == (300, 200)
        with connect() as conn:
            conn.execute("UPDATE events SET status = 'dismissed' WHERE id = ?", (eid,))
        assert pid not in ids(pub(c))
        assert c.get(f"/api/board/posts/{pid}/photo").status_code == 404
        r = c.get(f"/api/board/admin/posts/{pid}/photo")
        assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
        assert c.get(f"/api/board/admin/posts/{pid + 50}/photo").status_code == 404


def test_no_photo_404():
    with TestClient(app) as c:
        pid = post(c, member("Author"))
        assert c.get(f"/api/board/posts/{pid}/photo").status_code == 404


def _child(parent_id):
    now = iso(utcnow())
    with connect() as conn:
        return conn.execute("INSERT INTO posts(contact_id, phone, channel, category, body, status, parent_id, is_sample, created_at, updated_at) "
                            "VALUES (NULL, NULL, 'web', 'other', 'reply', 'open', ?, 1, ?, ?)", (parent_id, now, now)).lastrowid


def test_item_fields_both_views():
    with TestClient(app) as c:
        tok = member("Author")
        root = post(c, tok)
        solo = post(c, tok, body="Another report")
        kids = [_child(root), _child(root)]
        assert up(c, tok, root, jpeg_bytes((50, 50))).status_code == 200
        duty = member("Duty", "duty_officer")
        for items in (pub(c), c.get("/api/board/posts", headers=hd(duty)).json(), c.get("/api/board/admin/posts").json()):
            by = {i["id"]: i for i in items}
            for pid in [root, *kids]:
                assert by[pid]["thread_size"] == 3
            assert by[solo]["thread_size"] == 1
            assert by[root]["has_photo"] is True and by[solo]["has_photo"] is False
            assert all(isinstance(i["age_min"], int) and i["age_min"] >= 0 for i in items)


def test_too_many_pixels_refused_before_decode():
    """48 million pixels compress to a small PNG; Pillow only warns under 80 million, so it would decode it."""
    m = member("Big")
    with TestClient(app) as c:
        pid = post(c, m, "fire", "Smoke column")
        out = io.BytesIO()
        Image.new("L", (8000, 6000)).save(out, "PNG")
        assert len(out.getvalue()) < 2 * 1024 * 1024
        assert up(c, m, pid, out.getvalue(), "image/png").status_code == 415
        assert stored(pid) is None


def test_public_photo_follows_the_list_window_and_sample_flag():
    m = member("Window")
    with TestClient(app) as c:
        pid = post(c, m, "fire", "Smoke column")
        assert up(c, m, pid, jpeg_bytes((200, 100), exif=False)).status_code == 200
        assert c.get(f"/api/board/posts/{pid}/photo").status_code == 200
        with connect() as conn:
            conn.execute("UPDATE posts SET is_sample = 0 WHERE id = ?", (pid,))
        assert c.get(f"/api/board/posts/{pid}/photo").status_code == 404
        with connect() as conn:
            conn.execute("UPDATE posts SET is_sample = 1, created_at = '2020-01-01T00:00:00Z' WHERE id = ?", (pid,))
        assert c.get(f"/api/board/posts/{pid}/photo").status_code == 404
        assert c.get(f"/api/board/admin/posts/{pid}/photo").status_code == 200


def test_sample_clear_removes_photos():
    from app import sample
    m = member("Clear")
    with TestClient(app) as c:
        pid = post(c, m, "fire", "Smoke column")
        assert up(c, m, pid, jpeg_bytes((200, 100), exif=False)).status_code == 200
    sample.clear_sample_data()
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM post_photos").fetchone()["n"] == 0


def test_photo_ip_limit_30_an_hour(pc):
    small = jpeg_bytes((64, 64), exif=False)
    codes = []
    for i in range(4):
        m = member(f"Ip{i}")
        for _ in range(8):
            codes.append(up(pc, m, post(pc, m, "fire", "Smoke column"), small).status_code)
    assert codes[:30] == [200] * 30 and codes[30] == 429


def test_at_most_two_decodes_at_once(monkeypatch):
    import threading
    import time
    from app import routes_posts
    active, peak, lock = [0], [0], threading.Lock()
    real = routes_posts.ImageOps.exif_transpose

    def slow(img):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return real(img)

    monkeypatch.setattr(routes_posts.ImageOps, "exif_transpose", slow)
    raw = jpeg_bytes((64, 64), exif=False)
    threads = [threading.Thread(target=routes_posts._reencode, args=(raw, "image/jpeg")) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] <= 2
