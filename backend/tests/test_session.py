import threading
import time
from dataclasses import replace

import pytest

from agent.planner import PendingApproval, Step, TurnResult
from tripwire.decision import Decision, Verdict
from tripwire.events import EventBus
from tripwire.session import ApprovalBroker, Session, parse_brief_request
from tripwire.tools import build_default_registry

HELD = Decision(Verdict.NEEDS_APPROVAL, "R2.private_outbound", "would send private data to external",
                explanation="It would send your tax file to a stranger.", evidence="file:tax.txt")


def pending(tool="send_telegram", **args):
    return PendingApproval(tool, args or {"chat_id": "666", "text": "x"}, HELD)


def done(reply="ok", steps=None):
    return TurnResult("done", reply, steps or [])


def paused(p=None):
    return TurnResult("paused", pending=p or pending())


class FakePlanner:
    """Returns scripted TurnResults; records resume(bool) answers."""

    def __init__(self, script):
        self.script = list(script)
        self.resumes: list[bool] = []
        self.shield = True

    def send(self, text):
        self._text = text
        return self.script.pop(0)

    def resume(self, approved):
        self.resumes.append(approved)
        return self.script.pop(0)

    def reset(self):
        self.resumes.append("reset")

    @property
    def context_label(self):
        from tripwire.labels import BOTTOM
        return BOTTOM


def make_session(script, **kw):
    bus = EventBus()
    planner = FakePlanner(script)

    class G:
        registry = build_default_registry("1001")
        engine = None

    settings = kw.pop("settings", _settings())
    s = Session(settings, bus, router=None, gateway=G(), skills=_skills(settings), planner=planner,
                rules_store=kw.pop("rules", None), approval_timeout=kw.pop("timeout", 0.2))
    return s, planner, bus


def _settings():
    import tempfile
    from pathlib import Path

    from tripwire.config import Settings

    d = Path(tempfile.mkdtemp())
    return Settings(api_key="x", models={"nano": "n", "super": "s"}, demo_mode=True,
                    data_dir=d, notes_dir=d / "n")


def _skills(settings):
    from skills.registry import build_skills

    return build_skills(settings, router=_Router(), bus=EventBus(),
                        http=None, tavily=None, reader=_NoReader())


class _Router:
    def __init__(self):
        self.records = []

    def chat(self, *a, **k):
        raise AssertionError("router should not be called in these tests")


class _NoReader:
    quarantined = True

    def read(self, *a, **k):  # pragma: no cover
        raise AssertionError


# --- broker ------------------------------------------------------------------


def test_broker_open_pending_resolve():
    broker = ApprovalBroker()
    info = broker.open(pending(), source="api")
    assert info.tool == "send_telegram" and info.explanation and info.rule_id == "R2.private_outbound"
    assert [p.id for p in broker.pending()] == [info.id]
    assert broker.resolve(info.id, "allow") is True
    assert broker.wait(info.id, 0.1) == "allow"
    assert broker.pending() == []  # answered ones drop out


def test_broker_first_answer_wins():
    broker = ApprovalBroker()
    info = broker.open(pending(), source="api")
    assert broker.resolve(info.id, "deny") is True
    assert broker.resolve(info.id, "allow") is False  # too late
    assert broker.get(info.id).answer == "deny"


def test_broker_wait_times_out():
    broker = ApprovalBroker()
    info = broker.open(pending(), source="api")
    assert broker.wait(info.id, 0.05) is None


def test_broker_publishes_event():
    bus = EventBus()
    broker = ApprovalBroker(bus)
    broker.open(pending(), source="telegram")
    assert bus.recent[-1].kind == "approval_opened"


# --- session chat / approvals ------------------------------------------------


def test_chat_plain():
    s, planner, _ = make_session([done("hello", [Step("read_file", {}, HELD, True)])])
    outcome = s.chat("hi", approver=lambda info: "allow")
    assert outcome.reply == "hello" and len(outcome.steps) == 1 and outcome.approvals == []


def test_chat_inline_approver_allow():
    s, planner, _ = make_session([paused(), done("sent")])
    outcome = s.chat("send it", approver=lambda info: "allow")
    assert planner.resumes == [True] and outcome.reply == "sent"
    assert len(outcome.approvals) == 1


def test_chat_inline_approver_deny():
    s, planner, _ = make_session([paused(), done("ok")])
    s.chat("send it", approver=lambda info: "deny")
    assert planner.resumes == [False]


def test_chat_external_resolution_wins_over_timeout():
    s, planner, bus = make_session([paused(), done("sent")], timeout=2.0)
    ids: list = []
    bus.subscribe(lambda e: ids.append(e.call_id) if e.kind == "approval_opened" else None)
    t = threading.Thread(target=lambda: s.chat("send it"))  # no inline approver
    t.start()
    while not ids:
        time.sleep(0.01)
    assert s.broker.resolve(ids[0], "allow") is True
    t.join(timeout=3)
    assert planner.resumes == [True]


def test_chat_times_out_to_deny():
    s, planner, _ = make_session([paused(), done("ok")], timeout=0.05)
    s.chat("send it")  # nobody answers
    assert planner.resumes == [False]


def test_always_deny_writes_user_rule(tmp_path):
    from tripwire.policy.user_rules import UserRuleStore

    store = UserRuleStore(tmp_path / "user_rules.yaml")
    s, planner, _ = make_session([paused(pending("send_telegram", chat_id="666", text="x")), done("ok")], rules=store)
    s.chat("send it", approver=lambda info: "always_deny")
    assert planner.resumes == [False]  # denied this turn too
    assert any(r["id"] == "U.deny_send_telegram_external" for r in store.load())


def test_new_thread_and_shield_toggle():
    s, planner, _ = make_session([done("ok")])
    s.new_thread()
    assert planner.resumes[-1] == "reset"
    s.set_shield(False)
    assert planner.shield is False
    s.set_shield(True)
    assert planner.shield is True


def test_shield_off_requires_demo_mode():
    s, planner, _ = make_session([], settings=replace(_settings(), demo_mode=False))
    with pytest.raises(ValueError):
        s.set_shield(False)


# --- brief scheduling --------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("every morning brief me on AI safety", ("AI safety", 8, 0)),
        ("each day at 7:30 brief me about the markets", ("the markets", 7, 30)),
        ("every weekday at 9am brief me on crypto news", ("crypto news", 9, 0)),
        ("every day at 6 pm brief me about football", ("football", 18, 0)),
        ("send me a brief on pasta", None),
        ("what's the weather", None),
    ],
)
def test_parse_brief_request(text, expected):
    assert parse_brief_request(text) == expected


def test_maybe_schedule_brief_stores_task():
    s, planner, _ = make_session([])
    msg = s.maybe_schedule_brief("every morning brief me on AI safety")
    assert msg and "AI safety" in msg
    assert [t.topic for t in s.skills.memory.tasks()] == ["AI safety"]
    assert s.maybe_schedule_brief("hello there") is None


def test_scheduler_fires_a_brief_through_the_session():
    """A scheduled daily brief runs run_brief, which drives a full gated turn."""
    s, planner, _ = make_session([done("Here is your brief.")])
    s.schedule_brief("AI safety", hour=8, minute=0)
    s.start_scheduler()
    try:
        # Replace the cron trigger with one that fires in ~0.2s, same job function.
        import datetime as dt

        job = s._scheduler.get_jobs()[0]
        run_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=0.2)
        s._scheduler.modify_job(job.id, next_run_time=run_at)
        time.sleep(0.6)
    finally:
        s.stop_scheduler()
    # run_brief sent a chat through the planner (the fake returned a done result).
    assert planner.__dict__["_text"].startswith("Research AI safety")


def test_run_brief_without_task():
    s, planner, _ = make_session([])
    assert "No daily brief" in s.run_brief().reply


def test_run_brief_uses_stored_topic():
    s, planner, _ = make_session([done("brief!")])
    s.skills.memory.add_task("daily_brief", "markets", "08:00")
    outcome = s.run_brief()
    assert outcome.reply == "brief!"
    assert planner._text.startswith("Research markets")


def test_switching_to_naive_turns_off_every_layer():
    s, planner, _ = make_session([])
    s.set_security("high")
    s.set_shield(False)
    assert s.mode == "naive" and planner.shield is False
    assert s.skills.fetcher.reader.quarantined is False  # raw page text
    s.set_shield(True)
    assert s.mode == "protected" and s.skills.fetcher.reader.quarantined is True  # high-security returns


def test_standard_is_the_default_and_has_no_reader():
    s, planner, _ = make_session([])
    assert s.security == "standard" and s.mode == "protected"
    assert s.skills.fetcher.reader.quarantined is False and planner.quarantined is False


def test_high_security_adds_the_reader_and_standard_removes_it():
    s, planner, _ = make_session([])
    s.set_security("high")
    assert s.skills.fetcher.reader.quarantined is True and planner.quarantined is True
    s.set_security("standard")
    assert s.skills.fetcher.reader.quarantined is False and planner.quarantined is False


def test_high_security_has_no_effect_on_the_naive_agent():
    s, planner, _ = make_session([])
    s.set_shield(False)
    s.set_security("high")
    assert s.skills.fetcher.reader.quarantined is False and s.security == "high"


def test_unknown_security_level_is_rejected():
    s, _, _ = make_session([])
    with pytest.raises(ValueError):
        s.set_security("paranoid")


def test_demo_runs_in_high_security():
    s, _, _ = make_session([])
    assert s.seed_demo()["security"] == "high" and s.skills.fetcher.reader.quarantined is True


def test_seed_demo_resets_and_seeds():
    s, planner, _ = make_session([])
    s.skills.memory.remember("old fact", __import__("tripwire.labels", fromlist=["user_label"]).user_label())
    info = s.seed_demo()
    assert "demo-pages" in info["suggested_prompt"]
    facts = [f.value for f in s.skills.memory.all()]
    assert "old fact" not in facts and len(facts) == 3
    assert planner.resumes[-1] == "reset"


def test_new_thread_moves_the_thread_start():
    s, planner, _ = make_session([])
    before = s.thread_started
    time.sleep(0.01)
    s.new_thread()
    assert s.thread_started > before
