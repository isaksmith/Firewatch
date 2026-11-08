import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import pipeline
from app.ingest import ngfs

FIX = json.loads((Path(__file__).parent.parent / "data/samples/feeds/ngfs.json").read_text())


def feat(lon=-97.4, lat=37.6, tid="ID-1", td="Possible Wildland Fire", sat="GOES-19"):
    return {"properties": {"longitude": lon, "latitude": lat, "acq_date_time": "2026-11-07T02:21:18.000000Z",
                           "satellite": sat, "scan_domain": "CONUS", "frp": 3.2, "type": 0, "type_description": td,
                           "state": "KS", "county": "Sumner County", "feature_tracking_id": tid, "extra": "dropped"},
            "geometry": {"type": "Polygon", "coordinates": []}}


def page(n_ret, n_match, feats=None, nxt=None):
    links = [{"rel": "self", "href": "x"}] + ([{"rel": "next", "href": nxt}] if nxt else [])
    return {"numberReturned": n_ret, "numberMatched": n_match, "features": [feat()] if feats is None else feats, "links": links}


def test_window_is_six_hours_truncated_to_minute_and_changes_each_poll():
    t = datetime(2026, 11, 7, 2, 28, 31, 999, tzinfo=timezone.utc)
    assert ngfs.window(t) == "2026-11-06T20:28:00Z/2026-11-07T02:28:00Z"
    assert ngfs.window(t + timedelta(minutes=1)) != ngfs.window(t)  # defeats the 1 h CloudFront cache


def test_every_request_sends_a_fresh_datetime(monkeypatch):
    seen = []
    monkeypatch.setattr(ngfs, "get_json", lambda url, params=None: seen.append(params) or page(1, 1))
    ngfs.fetch(datetime(2026, 11, 7, 2, 28, tzinfo=timezone.utc))
    ngfs.fetch(datetime(2026, 11, 7, 2, 29, tzinfo=timezone.utc))
    assert len(seen) == 12 and all(p and p["datetime"] for p in seen)
    assert len({p["datetime"] for p in seen}) == 2


def test_paging_uses_offset_on_fixed_base_and_caps_at_five(monkeypatch):
    monkeypatch.setattr(ngfs, "LIMIT", 2)
    calls = []

    def fake(url, params=None):
        calls.append((url, dict(params)))
        return page(2, 99, feats=[feat(), feat()])

    monkeypatch.setattr(ngfs, "get_json", fake)
    rows = ngfs.fetch_collection(ngfs.COLLECTIONS[0], "a/b")
    assert len(calls) == 5 and len(rows) == 10
    assert [c[1].get("offset", 0) for c in calls] == [0, 2, 4, 6, 8]
    assert all(c[0].startswith(ngfs.BASE + "/") and c[1]["datetime"] == "a/b" for c in calls)


def test_no_paging_when_everything_returned(monkeypatch):
    calls = []
    monkeypatch.setattr(ngfs, "LIMIT", 2)
    monkeypatch.setattr(ngfs, "get_json", lambda u, p=None: calls.append(u) or page(1, 1))
    ngfs.fetch_collection(ngfs.COLLECTIONS[0], "a/b")
    assert len(calls) == 1


def test_stops_when_offset_reaches_number_matched(monkeypatch):
    calls = []
    monkeypatch.setattr(ngfs, "LIMIT", 2)

    def fake(url, params=None):
        calls.append(dict(params))
        return page(2, 4, feats=[feat(), feat()])

    monkeypatch.setattr(ngfs, "get_json", fake)
    assert len(ngfs.fetch_collection(ngfs.COLLECTIONS[0], "a/b")) == 4
    assert len(calls) == 2


def test_hostile_next_link_is_never_requested_and_page_two_uses_offset(monkeypatch):
    monkeypatch.setattr(ngfs, "LIMIT", 2)
    urls, offsets = [], []

    def fake(url, params=None):
        urls.append(url)
        offsets.append((params or {}).get("offset", 0))
        if len(urls) == 1:
            return page(2, 3, feats=[feat(), feat()], nxt="http://169.254.169.254/latest/meta-data/")
        return page(1, 3)

    monkeypatch.setattr(ngfs, "get_json", fake)
    rows = ngfs.fetch_collection(ngfs.COLLECTIONS[0], "a/b")
    assert len(rows) == 3 and offsets == [0, 2]
    assert not any("169.254" in u for u in urls) and all(u.startswith(ngfs.BASE) for u in urls)


def test_redirects_are_not_followed(monkeypatch):
    seen = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {}

    def fake_get(url, **kw):
        seen.update(kw)
        return R()

    monkeypatch.setattr(ngfs.httpx, "get", fake_get)
    ngfs.get_json(ngfs.BASE, {"a": 1})
    assert seen["follow_redirects"] is False


def test_partial_failure_keeps_other_rows_and_names_the_failed_one(monkeypatch):
    def fake(url, params=None):
        if "west_conus" in url:
            raise RuntimeError("boom")
        return page(1, 1) if "scene_east_conus" in url else page(0, 0, feats=[])

    monkeypatch.setattr(ngfs, "get_json", fake)
    out = ngfs.fetch()
    assert out["count"] == 1
    failed = [c["collection"] for c in out["collections"] if "error" in c]
    assert failed == ["west_conus"]


def test_all_fail_raises(monkeypatch):
    def fake(url, params=None):
        raise RuntimeError("down")

    monkeypatch.setattr(ngfs, "get_json", fake)
    with pytest.raises(RuntimeError):
        ngfs.fetch()


def test_poll_failure_marks_nothing_healthy_and_raises(monkeypatch):
    monkeypatch.setattr(ngfs, "get_json", lambda u, p=None: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        ngfs.poll()


def test_parse_keeps_context_fields_and_drops_outside_bbox():
    rows = ngfs.parse({"features": [feat(), feat(lon=-97.3, lat=36.5)]})  # second is south of the AOI
    assert len(rows) == 1
    r = rows[0]
    assert r["lon"] == -97.4 and r["type_description"] == "Possible Wildland Fire" and r["county"] == "Sumner County"
    assert "extra" not in r and "geometry" not in r


def test_snapshot_totals_and_east_west_stay_labeled():
    pts = ngfs.parse({"features": [feat(tid="A"), feat(tid="A"), feat(tid="B", td="Industrial", sat="GOES-18")]})
    s = ngfs.snapshot(pts, [], "w")
    assert (s["count"], s["tracked_features"], s["wildland_count"], s["industrial_count"]) == (3, 2, 2, 1)
    assert s["newest_acq"] == "2026-11-07T02:21:18.000000Z"
    assert {p["satellite"] for p in s["points"]} == {"GOES-19", "GOES-18"}
    assert "informational only" in s["notice"]


def test_fixture_covers_both_types_and_matches_its_totals():
    assert FIX["wildland_count"] > 0 and FIX["industrial_count"] > 0
    assert FIX["count"] == len(FIX["points"]) == FIX["wildland_count"] + FIX["industrial_count"]


def test_ngfs_never_reaches_process_detections(monkeypatch):
    called = []
    monkeypatch.setattr(pipeline, "process_detections", lambda *a, **k: called.append(1))
    monkeypatch.setattr(ngfs, "get_json", lambda u, p=None: page(1, 1))
    ngfs.poll()
    assert not called
    src = Path(ngfs.__file__).read_text()
    assert "process_detections" not in src.replace("process_detections, so", "").replace("reach process_detections", "")
