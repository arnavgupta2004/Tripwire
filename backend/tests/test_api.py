import threading
import time

from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_session import FakePlanner, _settings, _skills, done, paused
from tripwire.events import EventBus, GatewayEvent
from tripwire.models import summarize_usage
from tripwire.session import Session
from tripwire.tools import build_default_registry


class FakeRouter:
    def __init__(self):
        self.records = []

    def usage_summary(self):
        return summarize_usage(self.records)


def build(script, **kw):
    bus = EventBus()
    settings = kw.pop("settings", _settings())

    class G:
        registry = build_default_registry("1001")
        engine = None

    session = Session(settings, bus, FakeRouter(), G(), _skills(settings), FakePlanner(script),
                      rules_store=kw.pop("rules", None), approval_timeout=kw.pop("timeout", 1.0))
    return session, TestClient(create_app(session))


def sse_events(response):
    """Parse an SSE response body into (event, data) blocks."""
    out = []
    event = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            out.append((event, line[6:]))
    return out


def test_health():
    _, client = build([])
    body = client.get("/health").json()
    assert body["ok"] is True and "shield" in body


def test_chat_streams_done():
    _, client = build([done("hello there")])
    events = sse_events(client.post("/chat", json={"message": "hi"}))
    assert events[-1][0] == "done"
    assert "hello there" in events[-1][1]


def test_chat_schedules_brief_without_running_planner():
    session, client = build([])
    events = sse_events(client.post("/chat", json={"message": "every morning brief me on AI safety"}))
    assert events[-1][0] == "done" and "AI safety" in events[-1][1]
    assert [t.topic for t in session.skills.memory.tasks()] == ["AI safety"]


def test_usage_endpoint():
    _, client = build([])
    body = client.get("/session/usage").json()
    assert "tiers" in body and body["total_calls"] == 0


def test_shield_toggle_and_demo_guard():
    session, client = build([])
    assert client.post("/shield", json={"on": False}).json() == {"ok": True, "shield": False, "mode": "naive"}
    assert session.planner.shield is False
    # With demo mode off, turning the shield off is refused.
    from dataclasses import replace

    session.settings = replace(session.settings, demo_mode=False)
    body = client.post("/shield", json={"on": False}).json()
    assert body["ok"] is False and "DEMO_MODE" in body["error"]


def test_security_level_endpoint():
    session, client = build([])
    assert client.get("/health").json()["security"] == "standard"
    assert client.post("/security", json={"level": "high"}).json() == {"ok": True, "security": "high"}
    assert session.skills.fetcher.reader.quarantined is True
    assert client.get("/health").json()["security"] == "high"
    bad = client.post("/security", json={"level": "max"}).json()
    assert bad["ok"] is False and session.security == "high"


def test_thread_new():
    session, client = build([])
    assert client.post("/thread/new").json() == {"ok": True}
    assert session.planner.resumes[-1] == "reset"


def test_memory_endpoints():
    session, client = build([])
    fact = session.skills.memory.remember("likes aisle seats", _trusted())
    session.skills.memory.add_task("daily_brief", "markets", "08:00")
    body = client.get("/memory").json()
    assert any(f["fact"] == "likes aisle seats" and f["trusted"] for f in body["facts"])
    assert body["tasks"][0]["topic"] == "markets"
    assert client.delete(f"/memory/{fact.id}").json() == {"ok": True}
    assert client.get("/memory").json()["facts"] == []


def test_untrusted_memory_is_flagged_over_the_api():
    session, client = build([])
    session.skills.memory.remember("bank is evil.example", _untrusted())
    fact = client.get("/memory").json()["facts"][0]
    assert fact["trusted"] is False and "instruction" in fact["provenance_warning"].lower()


def test_approval_endpoints_and_first_answer_wins():
    session, client = build([paused(), done("sent")], timeout=3.0)
    opened: list = []
    session.bus.subscribe(lambda e: opened.append(e.call_id) if e.kind == "approval_opened" else None)
    t = threading.Thread(target=lambda: session.chat("send it", source="telegram"))
    t.start()
    while not opened:
        time.sleep(0.01)
    approval_id = opened[0]

    listed = client.get("/approvals").json()
    assert listed and listed[0]["id"] == approval_id and listed[0]["tool"] == "send_telegram"
    assert client.get(f"/approvals/{approval_id}").json()["explanation"]

    assert client.post(f"/approvals/{approval_id}", json={"answer": "allow"}).json() == {"ok": True, "accepted": True}
    # A second answer loses (first wins).
    assert client.post(f"/approvals/{approval_id}", json={"answer": "deny"}).json() == {"ok": True, "accepted": False}
    t.join(timeout=3)
    assert session.planner.resumes == [True]


def test_approval_bad_answer_rejected():
    _, client = build([])
    body = client.post("/approvals/ap_1", json={"answer": "maybe"}).json()
    assert body["ok"] is False


def test_events_websocket_replays_and_streams():
    session, client = build([])
    session.bus.publish(_decision_event("read_file"))
    with client.websocket_connect("/events") as ws:
        first = ws.receive_json()  # replayed recent event
        assert first["tool"] == "read_file"
        session.bus.publish(_decision_event("send_telegram"))
        assert ws.receive_json()["tool"] == "send_telegram"


def _decision_event(tool):
    return GatewayEvent(call_id="c", tool=tool, args_summary="{}", labels={}, verdict="ALLOW",
                        policy_verdict="ALLOW", rule_id="R4.read_only_trusted", reason="ok", models=())


def _trusted():
    from tripwire.labels import user_label

    return user_label()


def _untrusted():
    from tripwire.labels import web_label

    return web_label("https://evil.example")




def test_context_endpoint():
    session, client = build([])
    body = client.get("/session/context").json()
    assert {k: body[k] for k in ("private", "untrusted", "sources", "badge")} == {"private": False, "untrusted": False, "sources": [], "badge": ""}
    assert body["thread_started"] > 0


def test_cors_headers_present():
    _, client = build([])
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_demo_load_seeds_state():
    from dataclasses import replace

    session, client = build([])
    session.settings = replace(session.settings, demo_mode=True)
    body = client.post("/demo/load").json()
    assert body["ok"] and "brief" in body["suggested_prompt"] and len(body["examples"]) == 2
    facts = client.get("/memory").json()["facts"]
    assert any(not f["trusted"] for f in facts) and any(f["trusted"] for f in facts)
    assert client.get("/memory").json()["tasks"][0]["topic"] == "AI safety news"
