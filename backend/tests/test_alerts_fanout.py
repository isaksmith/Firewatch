import apprise
import pytest

from app.alerts import fanout

SECRET = "ntfys://user:hunter2-TOKEN@ntfy.example.org/cottonwood-creek-demo"
EVENT = {"id": 1, "lat": 37.3, "lon": -99.8, "score": 87, "recommendation": "escalate",
         "heading": "N", "speed_mph": 3}
RECIP = [{"name": "Chief", "phone": "+15550100001", "text": "hello"}]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("FIREWATCH_NOTIFY_LIVE", raising=False)
    monkeypatch.setenv("FIREWATCH_NOTIFY_URLS", SECRET + ",mailto://pager:pw123@mail.example.org?to=page@x.org,twilio://AC1:tok9@+15551230000/+15550100001")


def test_dry_run_makes_no_network_and_returns_rows(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(apprise.Apprise, "notify", boom)
    rows = fanout.send(EVENT, RECIP, ["push", "sms", "pager", "mesh"])
    assert [r["channel"] for r in rows] == ["push", "sms", "pager", "mesh"]
    assert all(r["status"] == "dry_run" and r["error"] is None and r["text"] == "hello" for r in rows)
    blob = repr(rows)
    for secret in ("hunter2", "TOKEN", "pw123", "tok9", "AC1", SECRET):
        assert secret not in blob
    assert "ntfys://nt***" in blob


def test_live_failure_never_leaks_url(monkeypatch, caplog):
    monkeypatch.setenv("FIREWATCH_NOTIFY_LIVE", "1")

    def boom(self, *a, **k):
        raise RuntimeError(f"cannot reach {SECRET} (bad token hunter2-TOKEN)")
    monkeypatch.setattr(apprise.Apprise, "notify", boom)
    rows = fanout.send(EVENT, RECIP, ["push"])
    assert rows[0]["status"] == "failed"
    blob = repr(rows) + caplog.text
    assert SECRET not in blob and "ntfys://user" not in blob
    assert "ntfys://nt***" in rows[0]["error"]


def test_live_sent(monkeypatch):
    monkeypatch.setenv("FIREWATCH_NOTIFY_LIVE", "1")
    monkeypatch.setattr(apprise.Apprise, "notify", lambda self, *a, **k: True)
    assert fanout.send(EVENT, RECIP, ["pager"])[0]["status"] == "sent"


def test_live_without_url_fails_plainly(monkeypatch):
    monkeypatch.setenv("FIREWATCH_NOTIFY_LIVE", "1")
    monkeypatch.setenv("FIREWATCH_NOTIFY_URLS", "")
    r = fanout.send(EVENT, RECIP, ["push"])[0]
    assert r["status"] == "failed" and "no destination" in r["error"]


def test_mesh_stub_records_when_live(monkeypatch):
    monkeypatch.setenv("FIREWATCH_NOTIFY_LIVE", "1")
    fanout.MESH_QUEUE.clear()
    r = fanout.send(EVENT, RECIP, ["mesh"])[0]
    assert r["error"] == "queued for mesh" and len(fanout.MESH_QUEUE) == 1


def test_mask_url():
    assert fanout.mask_url(SECRET) == "ntfys://nt***"


def test_apprise_own_logs_carry_no_secrets(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("FIREWATCH_NOTIFY_LIVE", "1")
    monkeypatch.setenv("FIREWATCH_NOTIFY_URLS", "json://user:pw@127.0.0.1:1/?auth=apikeyZZZ,notaurl-hunter2pass")
    caplog.set_level(logging.DEBUG)
    # apprise logs through logging.getLogger("apprise"); make sure it really does log without our filter
    logging.getLogger("apprise").error("control notaurl-hunter2pass")
    assert "hunter2pass" in caplog.text
    caplog.clear()
    rows = fanout.send(EVENT, RECIP, ["sms"])
    blob = caplog.text + repr(rows)
    for secret in ("apikeyZZZ", "hunter2pass", "user:pw"):
        assert secret not in blob
    assert rows[0]["status"] == "failed"
