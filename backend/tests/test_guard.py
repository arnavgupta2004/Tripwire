import pytest

from fakes.openai_client import FakeClient, completion
from tripwire.guard import RateLimiter, SpendGuard, SpendStateError
from tripwire.models import SpendCapReached


class Clock:
    def __init__(self, t=1_791_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_spend_guard_blocks_after_cap(tmp_path):
    g = SpendGuard(0.01, tmp_path / "spend.json", clock=Clock())
    g.check()
    g.add(0.006)
    g.check()
    g.add(0.005)
    assert g.exhausted
    with pytest.raises(SpendCapReached):
        g.check()
    assert g.status()["remaining_usd"] == 0.0


def test_spend_guard_persists_and_resets_daily(tmp_path):
    clock = Clock()
    path = tmp_path / "spend.json"
    SpendGuard(1.0, path, clock=clock).add(0.4)
    assert SpendGuard(1.0, path, clock=clock).spent_today == pytest.approx(0.4)  # survives restart
    clock.t += 86_400  # next UTC day
    assert SpendGuard(1.0, path, clock=clock).spent_today == 0.0


def test_lifetime_cap_spans_days_and_restarts(tmp_path):
    clock = Clock()
    path = tmp_path / "spend.json"
    SpendGuard(1.0, path, clock=clock, lifetime_cap_usd=1.5).add(0.9)
    clock.t += 86_400
    g = SpendGuard(1.0, path, clock=clock, lifetime_cap_usd=1.5)  # new day, after a restart
    assert g.spent_today == 0.0 and g.spent_lifetime == pytest.approx(0.9)
    g.add(0.6)
    assert g.lifetime_exhausted and g.spent_today < 1.0
    with pytest.raises(SpendCapReached, match="lifetime"):
        g.check()
    clock.t += 86_400
    assert SpendGuard(1.0, path, clock=clock, lifetime_cap_usd=1.5).exhausted  # never resets
    assert g.status()["remaining_usd"] == 0.0


def test_spend_state_that_cannot_persist_fails_loudly(tmp_path):
    bad = tmp_path / "spend.json"
    bad.write_text("not json")
    with pytest.raises(SpendStateError):
        SpendGuard(1.0, bad)
    blocked = tmp_path / "file"
    blocked.write_text("")
    with pytest.raises(SpendStateError):
        SpendGuard(1.0, blocked / "spend.json")  # parent is a file: not writable


def test_router_charges_and_respects_guard(make_router, tmp_path):
    guard = SpendGuard(0.0005, clock=Clock())
    client = FakeClient([completion("ok", tokens_in=1000, tokens_out=1000)] * 3)
    router = make_router(client, guard=guard)
    router.chat("nano", [], purpose="t")  # $0.0001 + $0.0004 = $0.0005 at the test prices
    assert guard.exhausted
    with pytest.raises(SpendCapReached):
        router.chat("nano", [], purpose="t")
    assert len(client.requests) == 1  # the blocked call never reached the API


def test_rate_limiter_sliding_window():
    clock = Clock(0.0)
    rl = RateLimiter(2, 60, clock=clock)
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    assert rl.allow("b")  # per key
    assert rl.retry_after("a") == pytest.approx(60)
    clock.t = 61
    assert rl.allow("a")
