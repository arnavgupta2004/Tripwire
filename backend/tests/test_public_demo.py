"""Public demo: per-visitor isolation, rate limits and the daily spend cap."""

from dataclasses import replace

from fastapi.testclient import TestClient

from api.main import CAP_MESSAGE, LIFETIME_CAP_MESSAGE, STATE_MESSAGE, create_app
from api.visitors import PUBLIC_SELF_CHAT, VisitorSessions, public_settings
from tests.test_api import FakeRouter
from tests.test_session import FakePlanner, _settings, _skills, done
from tripwire.events import EventBus
from tripwire.guard import SpendGuard
from tripwire.labels import user_label
from tripwire.models import SpendCapReached
from tripwire.session import Session
from tripwire.tools import build_default_registry

A, B = "visitor-aaaaaaaa", "visitor-bbbbbbbb"


class G:
    registry = build_default_registry("")
    engine = None


def make(script_for=lambda vid: [done(f"hi {vid}")] * 20, *, cap=5.0, per_visitor=8, everyone=60,
         max_sessions=50):
    base = replace(_settings(), public_demo=True, chat_rate_per_visitor=per_visitor,
                   chat_rate_global=everyone)
    guard = SpendGuard(cap)
    planners: dict[str, FakePlanner] = {}

    def factory(vid, directory):
        settings = public_settings(base, directory)
        planners[vid] = FakePlanner(script_for(vid))
        return Session(settings, EventBus(), FakeRouter(), G(), _skills(settings), planners[vid])

    sessions = VisitorSessions(factory, max_sessions=max_sessions)
    client = TestClient(create_app(sessions, settings=base, guard=guard))
    return client, sessions, planners, guard


def chat(client, visitor, msg="hello"):
    r = client.post("/chat", json={"message": msg}, headers={"X-Tripwire-Visitor": visitor})
    return [line[6:] for line in r.text.splitlines() if line.startswith("data: ")][-1]


def test_public_settings_lock_the_demo_down(tmp_path):
    s = public_settings(replace(_settings(), telegram_bot_token="tok", telegram_chat_id="1",
                                demo_mode=False), tmp_path)
    assert s.demo_mode and s.telegram_bot_token == "" and s.telegram_chat_id == PUBLIC_SELF_CHAT
    assert s.fetch_allowlist == ("127.0.0.1", "localhost")
    assert s.data_dir == tmp_path / "data"


def test_send_to_self_is_never_delivered(tmp_path):
    from skills.messaging import TelegramSender

    s = public_settings(_settings(), tmp_path)
    out = TelegramSender(s.telegram_bot_token, s.telegram_chat_id, EventBus(), demo_mode=s.demo_mode).send("hi")
    assert out["to"] == "self" and out["delivered"] is False and "not sent" in out["note"]


def test_visitors_get_isolated_sessions():
    client, sessions, planners, _ = make()
    assert "hi visitor-aaaaaaaa" in chat(client, A)
    assert "hi visitor-bbbbbbbb" in chat(client, B)
    mem_a = sessions.get(A).skills.memory
    mem_a.remember("A's secret preference", user_label())
    facts_b = client.get("/memory", headers={"X-Tripwire-Visitor": B}).json()["facts"]
    facts_a = client.get("/memory", headers={"X-Tripwire-Visitor": A}).json()["facts"]
    assert facts_b == [] and facts_a[0]["fact"] == "A's secret preference"
    assert sessions.get(A) is not sessions.get(B)
    assert sessions.get(A).skills.memory is not sessions.get(B).skills.memory


def test_missing_or_bad_visitor_is_rejected():
    client, *_ = make()
    assert client.get("/memory").status_code == 400
    assert client.get("/memory", headers={"X-Tripwire-Visitor": "../../etc"}).status_code == 400


def test_health_without_visitor_reports_budget():
    client, *_ = make(cap=2.0)
    body = client.get("/health").json()
    assert body["public_demo"] is True and body["budget"]["cap_usd"] == 2.0 and "mode" not in body


def test_rate_limit_answers_kindly_without_calling_the_model():
    client, sessions, planners, _ = make(per_visitor=2)
    chat(client, A)
    chat(client, A)
    third = chat(client, A)
    assert "faster than the public demo allows" in third
    assert len(planners[A].script) == 18  # only two turns reached the planner
    assert "hi visitor-bbbbbbbb" in chat(client, B)  # limits are per visitor


def test_spend_cap_blocks_before_any_model_call():
    client, sessions, planners, guard = make(cap=0.01)
    guard.add(0.02)
    reply = chat(client, A)
    assert "today's model budget" in reply
    assert A not in planners or len(planners[A].script) == 20


def test_lifetime_cap_has_its_own_message():
    client, sessions, planners, guard = make(cap=5.0)
    guard.lifetime_cap = 0.01
    guard.add(0.02)
    assert LIFETIME_CAP_MESSAGE[:40] in chat(client, A)
    assert client.get("/health").json()["budget"]["lifetime_cap_usd"] == 0.01


def test_unsaveable_spend_pauses_chat_with_its_own_message():
    class Broken:
        healthy = False

        def load(self):
            return None

        def save(self, state, *, urgent=False):
            pass

        def flush(self):
            pass

    client, sessions, planners, guard = make()
    guard.store = Broken()
    assert STATE_MESSAGE[:40] in chat(client, A)
    assert A not in planners or len(planners[A].script) == 20


def test_spend_cap_hit_mid_turn_gives_the_same_message():
    class CapPlanner(FakePlanner):
        def send(self, text):
            raise SpendCapReached("cap")

    base = replace(_settings(), public_demo=True)
    guard = SpendGuard(5.0)

    def factory(vid, directory):
        settings = public_settings(base, directory)
        return Session(settings, EventBus(), FakeRouter(), G(), _skills(settings), CapPlanner([]))

    client = TestClient(create_app(VisitorSessions(factory), settings=base, guard=guard))
    assert chat(client, A).find(CAP_MESSAGE[:40]) >= 0


def test_idle_and_excess_visitors_are_evicted():
    now = [0.0]
    sessions = VisitorSessions(lambda vid, d: object(), max_sessions=2, idle_ttl_s=100, clock=lambda: now[0])
    sessions.get("visitor-1111111a")
    sessions.get("visitor-2222222b")
    sessions.get("visitor-3333333c")  # over the cap: the oldest is dropped
    assert len(sessions) == 2
    now[0] = 500  # everything idle past the TTL
    sessions.get("visitor-4444444d")
    assert len(sessions) == 1


def test_demo_load_url_includes_mount_prefix():
    client, sessions, planners, _ = make()
    r = client.post("/demo/load", headers={"X-Tripwire-Visitor": A})
    assert "/demo-pages/informations.html" in r.json()["suggested_prompt"]
