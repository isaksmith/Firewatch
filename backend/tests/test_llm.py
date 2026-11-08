from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from app import ask, bulletin, llm, mesh, notify
from app.config import get_settings
from app.confirm import evaluate_event
from app.db import connect, iso, parse_iso
from app.district import sync_roster
from app.signals import add_signal

T0 = parse_iso("2026-03-17T18:50:00Z")
FIRE = (37.3821, -99.4681)
WEATHER = {"wind_kmh": 26, "gust_kmh": 45, "wind_dir_deg": 200, "rh_pct": 18, "temp_c": 24, "precip_72h_mm": 0, "thunder_24h": 0}
DUTY, WES, GARY = "+13165550101", "+13165550131", "+13165550135"


def _at(minutes: float):
    return T0 + timedelta(minutes=minutes)


def _line_fault(conn) -> int:
    eid = add_signal(conn, "line_fault", *FIRE, iso(T0), "coop:feeder-4", "lockout", is_sample=True)
    evaluate_event(conn, eid, WEATHER, T0)
    return eid


def _out(conn, purpose: str) -> list:
    return conn.execute("SELECT * FROM messages WHERE direction = 'out' AND purpose = ? ORDER BY id", (purpose,)).fetchall()


@pytest.fixture(autouse=True)
def fresh_bulletins():
    # every test's fire is event 1 first seen at T0, so earlier tests' updates would look like this one's
    bulletin._last.clear()
    bulletin._checked.clear()


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class Jobs(list):
    """Worker jobs, run by the test once the text that started them is committed."""

    def run(self):
        while self:
            fn, args = self.pop(0)
            fn(*args)


@pytest.fixture
def jobs(monkeypatch):
    queue = Jobs()
    monkeypatch.setattr(ask, "spawn", lambda fn, *args: queue.append((fn, args)))
    return queue


@pytest.fixture
def model(monkeypatch):
    """The model's words: set .reply (None = the call failed); .calls records what it was asked."""
    m = SimpleNamespace(reply="It is west of you and not confirmed yet.", calls=[])

    def complete(system, facts, request, max_chars):
        m.calls.append({"system": system, "facts": facts, "request": request, "max_chars": max_chars})
        return m.reply

    monkeypatch.setattr(llm, "complete", complete)
    return m


class FakeRadio:
    def __init__(self):
        self.myInfo = SimpleNamespace(my_node_num=0x0A0A0A0A)
        self.sent: list[dict] = []

    def sendText(self, text, destinationId, wantAck, channelIndex):
        self.sent.append({"text": text, "to": destinationId})
        return SimpleNamespace(id=1000 + len(self.sent))

    def close(self):
        pass


@pytest.fixture
def radio(monkeypatch):
    r = FakeRadio()
    monkeypatch.setattr(mesh, "TX_GAP_S", 0)
    bridge = mesh.MeshBridge(r)
    bridge.spawn = lambda fn, *args: fn(*args)
    mesh.set_bridge(bridge)
    yield r
    mesh.set_bridge(None)


# --- the model's words -----------------------------------------------------------------------------------


def test_clean_makes_one_ascii_line_and_cuts_at_a_sentence():
    assert llm.clean("**Fire\u2019s** heading\n NE \u2014 fast.", 100) == "Fire's heading NE - fast."
    assert llm.clean("First sentence here. Second one is far too long to fit.", 30) == "First sentence here."
    assert llm.clean("one long clause with no stop at all", 10) is None
    assert llm.clean("0.9\u202fmi west, in 2\u202fhours.", 100) == "0.9 mi west, in 2 hours."


def test_grounded_refuses_numbers_the_facts_dont_have():
    facts = "Fire 4, 12 mi NW of Coldwater. About 1,250 acres now."
    assert llm.grounded("Fire 4 is about 1250 acres. Call 911 if in danger.", facts)
    assert not llm.grounded("It could reach you in 20 minutes.", facts)


def test_complete_calls_openrouter_and_checks_the_answer(key, monkeypatch):
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, json=json)
        req = httpx.Request("POST", url)
        return httpx.Response(200, request=req, json={"choices": [{"message": {"content": sent["reply"]}}]})

    monkeypatch.setattr(llm.httpx, "post", post)
    sent["reply"] = "Fire 4 is 12 mi NW of Coldwater."
    assert llm.complete("sys", "Fire 4, 12 mi NW of Coldwater.", "Q", 100) == "Fire 4 is 12 mi NW of Coldwater."
    assert sent["url"] == llm.URL and sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["json"]["model"] == get_settings().openrouter_model

    sent["reply"] = "It will reach you in 15 minutes."
    assert llm.complete("sys", "Fire 4, 12 mi NW of Coldwater.", "Q", 100) is None, "15 is not in the facts"


def test_a_model_that_must_think_is_asked_again_with_thinking_on(key, monkeypatch):
    bodies = []

    def post(url, headers, json, timeout):
        bodies.append(json)
        req = httpx.Request("POST", url)
        if "reasoning" in json:
            return httpx.Response(400, request=req, json={"error": {"message": "Reasoning is mandatory for this endpoint"}})
        return httpx.Response(200, request=req, json={"choices": [{"message": {"content": "Fire 4 is out."}}]})

    monkeypatch.setattr(llm.httpx, "post", post)
    assert llm.complete("sys", "Fire 4.", "Q", 100) == "Fire 4 is out."
    assert len(bodies) == 2 and bodies[1]["max_tokens"] > bodies[0]["max_tokens"]


def test_complete_is_off_without_a_key_and_quiet_on_errors(monkeypatch):
    called = []
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: called.append(1))
    assert llm.complete("sys", "facts", "Q", 100) is None and not called

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()

    def down(url, **kw):
        raise httpx.ConnectTimeout("slow", request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", down)
    assert llm.complete("sys", "facts", "Q", 100) is None
    get_settings.cache_clear()


# --- questions -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("where is the fire?", True), ("Is it heading toward Coldwater", True), ("status", True),
    ("whats going on", True), ("smoke north of the river", False), ("fire", False), ("thanks", False),
])
def test_is_question(text, expected):
    assert ask.is_question(text) is expected


def test_question_is_answered_from_the_facts_not_filed_as_a_report(key, jobs, model):
    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn)
        r = notify.handle_inbound(conn, GARY, "Where is the fire? Is it coming my way?", _at(5), is_sample=True)
        assert r["action"] == "question" and r["reply"] is None
        assert not conn.execute("SELECT 1 FROM signals WHERE kind = 'report'").fetchone(), "a question is not a sighting"
    jobs.run()
    with connect() as conn:
        (a,) = _out(conn, "answer")
        assert a["body"] == f"Firewatch: {model.reply} Call 911 if in danger." and a["event_id"] == eid
        assert conn.execute("SELECT event_id FROM messages WHERE direction = 'in'").fetchone()["event_id"] == eid
    (call,) = model.calls
    assert f"Fire {eid}, " in call["facts"] and "mi " in call["facts"] and "of the person asking" in call["facts"]
    assert "Wind: from the" in call["facts"] and "acres now" in call["facts"]
    assert "Is it coming my way?" in call["request"] and call["max_chars"] == 160 - len(ask.PREFIX) - len(ask.SAFETY)


def test_answer_falls_back_to_the_template(key, jobs, model):
    model.reply = None
    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn)
        notify.handle_inbound(conn, GARY, "is it coming my way?", _at(5), is_sample=True)
    jobs.run()
    with connect() as conn:
        (a,) = _out(conn, "answer")
    assert a["body"].startswith(f"Firewatch: fire {eid} ") and "possible fire, being checked" in a["body"]
    assert a["body"].endswith("Call 911 if in danger.") and len(a["body"]) <= 160


def test_no_open_fire_says_so(key, jobs, model):
    model.reply = None
    with connect() as conn:
        sync_roster(conn)
        notify.handle_inbound(conn, GARY, "any fires today?", _at(5), is_sample=True)
    jobs.run()
    with connect() as conn:
        (a,) = _out(conn, "answer")
    assert "no open fire near you" in a["body"] and a["event_id"] is None


def test_without_a_key_questions_go_through_the_old_path(jobs):
    with connect() as conn:
        sync_roster(conn)
        r = notify.handle_inbound(conn, GARY, "any news?", _at(5), is_sample=True)
    assert r["action"] != "question" and not jobs


def test_console_ask_answers_without_texting_anyone(key, model):
    from fastapi.testclient import TestClient

    from app.main import app

    with connect() as conn:
        sync_roster(conn)
        eid = _line_fault(conn)
    c = TestClient(app)
    r = c.post("/api/ask", json={"question": "is it heading toward Coldwater?", "lat": FIRE[0] + 0.05, "lon": FIRE[1]}).json()
    assert r["answer"] == f"Firewatch: {model.reply} Call 911 if in danger." and r["by_model"] is True
    assert [f["id"] for f in r["fires"]] == [eid] and r["llm_configured"] is True
    assert "heading toward Coldwater?" in model.calls[0]["request"]

    r = c.post("/api/ask", json={"question": "is it heading toward Coldwater?", "lat": FIRE[0] + 0.05, "lon": FIRE[1],
                                 "use_model": False}).json()
    assert r["by_model"] is False and r["answer"].startswith(f"Firewatch: fire {eid} ") and len(model.calls) == 1

    c.post("/api/ask", json={"question": "where is it?"})
    facts = model.calls[-1]["facts"]
    assert f"Fire {eid}, " in facts and "person asking" not in facts, "no location, so nothing about reaching the asker"
    with connect() as conn:
        assert not conn.execute("SELECT 1 FROM messages WHERE purpose = 'answer'").fetchone(), "nothing is sent"


def test_console_ask_falls_back_to_the_template_when_the_model_fails(key, model):
    from fastapi.testclient import TestClient

    from app.main import app

    model.reply = None
    r = TestClient(app).post("/api/ask", json={"question": "any fires?"}).json()
    assert r["by_model"] is False and "no open fire near you" in r["answer"] and r["fires"] == []


# --- channel updates -------------------------------------------------------------------------------------


def _paged(conn) -> int:
    sync_roster(conn)
    eid = _line_fault(conn)
    notify.handle_inbound(conn, WES, "1", _at(8), is_sample=True)
    notify.handle_inbound(conn, DUTY, "page", _at(9), is_sample=True)
    return eid


def test_page_posts_an_update_to_the_channel(key, jobs, model, radio):
    model.reply = "Crews are rolling to the fire west of Coldwater."
    with connect() as conn:
        eid = _paged(conn)
    jobs.run()
    (post,) = [p for p in radio.sent if p["to"] == mesh.BROADCAST_ID and p["text"].startswith("FIREWATCH update")]
    assert post["text"] == f"FIREWATCH update fire {eid}: Crews are rolling to the fire west of Coldwater."
    (call,) = model.calls
    assert call["facts"].startswith("WHAT JUST HAPPENED: Crews were just paged.")
    assert "Confirmed fire: crews were paged" in call["facts"] and "person asking" not in call["facts"]
    with connect() as conn:
        (m,) = _out(conn, "channel_update")
    assert m["event_id"] == eid and m["phone"] == mesh.BROADCAST_ID and m["channel"] == "mesh" and m["status"] == "sent"


def test_updates_repeat_on_the_clock(key, jobs, model, radio):
    model.reply = None
    with connect() as conn:
        eid = _paged(conn)
    jobs.run()
    for minute in (14, 20, 26):
        with connect() as conn:
            notify.tick(conn, _at(minute), is_sample=True)
        jobs.run()
    with connect() as conn:
        bodies = [m["body"] for m in _out(conn, "channel_update")]
    assert len(bodies) == 2, "the page at 9, then the regular update once 15 min had passed (at 26)"
    assert bodies[1].startswith(f"FIREWATCH update fire {eid} ") and "Regular update." in bodies[1]
    assert all(len(b) <= bulletin.MAX_CHARS for b in bodies)


def test_no_updates_without_a_radio_or_a_key(jobs, model):
    with connect() as conn:
        _paged(conn)
    assert not jobs and not model.calls
