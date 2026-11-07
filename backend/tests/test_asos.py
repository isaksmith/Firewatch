from pathlib import Path

import httpx
import pytest

from app.ingest import asos

FIX = Path(__file__).parent / "fixtures"


def _patch(monkeypatch, files=None, status=200, exc=None):
    files = files or {}

    def fake_get(url, params=None, timeout=None):
        req = httpx.Request("GET", url)
        if exc:
            raise exc(f"failed {url}", request=req)
        name = files.get(params["station"])
        return httpx.Response(status, content=(FIX / name).read_bytes() if name else b"nope", request=req)

    monkeypatch.setattr(asos.httpx, "get", fake_get)


def test_parse_row_converts_knots(monkeypatch):
    _patch(monkeypatch, {"K51": "iem_currents_k51.json"})
    o = asos.latest_obs("K51")
    assert o["station"] == "K51" and o["obs_time"].endswith("Z")
    assert o["wind_mph"] == pytest.approx(5.0 * 1.15078, abs=0.1)
    assert o["gust_mph"] is None
    assert o["wind_dir_deg"] == 40.0 and o["rh_pct"] == 100.0 and o["temp_f"] == 42.8
    assert o["age_min"] > 0


def test_gust_converted():
    row = {"station": "K51", "utc_valid": "2026-11-07T00:35:00Z", "sknt": 20, "gust": 30, "drct": 200, "relh": 12, "tmpf": 80}
    o = asos.parse_row(row)
    assert o["wind_mph"] == 23.0 and o["gust_mph"] == 34.5


def test_empty_station_raises(monkeypatch):
    _patch(monkeypatch, {"3K8": "iem_currents_empty.json"})
    with pytest.raises(RuntimeError, match="3K8"):
        asos.latest_obs("3K8")


def test_one_bad_station_does_not_hide_the_other(monkeypatch):
    _patch(monkeypatch, {"K51": "iem_currents_k51.json", "3K8": "iem_currents_empty.json"})
    r = asos.latest_observations()
    assert [o["station"] for o in r["observations"]] == ["K51"]
    assert "3K8" in r["errors"]


@pytest.mark.parametrize("kwargs", [{"status": 500, "files": {"K51": "iem_currents_empty.json"}},
                                    {"exc": httpx.ConnectError}, {"files": {}}])
def test_failures_scrubbed(monkeypatch, kwargs):
    _patch(monkeypatch, **kwargs)
    with pytest.raises(RuntimeError) as e:
        asos.latest_obs("K51")
    msg = str(e.value)
    assert "iastate" not in msg and "http" not in msg.lower().replace("http 500", "")


@pytest.mark.parametrize("body", [b'{"data": null}', b'{"data": "abc"}', b'{"data": [1]}', b'[1]', b'{}'])
def test_malformed_rows_raise(monkeypatch, body):
    monkeypatch.setattr(asos.httpx, "get", lambda url, **kw: httpx.Response(200, content=body, request=httpx.Request("GET", url)))
    with pytest.raises(RuntimeError, match="K51"):
        asos.latest_obs("K51")


def test_bad_obs_time_fails_one_station_not_the_poll(monkeypatch):
    import pytest as _pytest
    from app.ingest import asos as _asos

    for bad in ("yesterday", None):
        good = _asos.parse_row
        monkeypatch.setattr(_asos, "parse_row", lambda row, _b=bad: {**{"obs_time": _b}})
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"data": [{"utc_valid": bad}]}
        monkeypatch.setattr(_asos.httpx, "get", lambda *a, **k: R())
        with _pytest.raises(RuntimeError):
            _asos.latest_obs("K51")
        monkeypatch.setattr(_asos, "parse_row", good)
