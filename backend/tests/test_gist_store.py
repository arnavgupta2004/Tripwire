"""Spend caps persisted in a secret GitHub gist (hosts without a disk)."""

import json

import httpx
import pytest

from tripwire.guard import GIST_DESCRIPTION, GIST_FILE, GistSpendStore, SpendGuard, SpendStateError
from tripwire.models import SpendCapReached


class Clock:
    def __init__(self, t=1_791_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeGitHub:
    """Just enough of the gists API, with switches to make it fail."""

    def __init__(self, content="{}", exists=True):
        self.gists = {"g1": {"id": "g1", "description": GIST_DESCRIPTION,
                             "files": {GIST_FILE: {"content": content}}}} if exists else {}
        self.down = False
        self.writes = 0
        self.auth = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.auth.append(request.headers.get("authorization"))
        if self.down:
            return httpx.Response(503)
        path, method = request.url.path, request.method
        if path == "/gists" and method == "GET":
            return httpx.Response(200, json=list(self.gists.values()))
        if path == "/gists" and method == "POST":
            body = json.loads(request.content)
            gid = f"g{len(self.gists) + 1}"
            self.gists[gid] = {"id": gid, **body}
            return httpx.Response(201, json=self.gists[gid])
        gid = path.rsplit("/", 1)[-1]
        if gid not in self.gists:
            return httpx.Response(404)
        if method == "PATCH":
            self.writes += 1
            for name, f in json.loads(request.content)["files"].items():
                self.gists[gid]["files"][name] = f
        return httpx.Response(200, json=self.gists[gid])

    def state(self, gid="g1"):
        return json.loads(self.gists[gid]["files"][GIST_FILE]["content"])


def store(gh, *, gist_id="g1", interval=30.0, clock=None):
    http = httpx.Client(transport=httpx.MockTransport(gh))
    return GistSpendStore("tok", gist_id, http=http, min_interval_s=interval, max_failure_s=120,
                          clock=clock or Clock(0.0), background=False)


def test_restart_restores_the_counter():
    gh, clock = FakeGitHub(), Clock()
    g = SpendGuard(0.75, clock=clock, lifetime_cap_usd=15, store=store(gh, interval=0))
    g.add(0.30)
    restarted = SpendGuard(0.75, clock=clock, lifetime_cap_usd=15, store=store(gh, interval=0))
    assert restarted.spent_today == pytest.approx(0.30)
    assert restarted.spent_lifetime == pytest.approx(0.30)
    assert gh.auth[0] == "Bearer tok"


def test_writes_are_batched_but_flushed_on_shutdown_and_near_a_cap():
    gh, mono = FakeGitHub(), Clock(0.0)
    g = SpendGuard(0.75, clock=Clock(), lifetime_cap_usd=15, store=store(gh, clock=mono))
    startup_writes = gh.writes
    g.add(0.01)
    g.add(0.01)
    assert gh.writes == startup_writes  # within 30s of the last write: held back
    g.flush()  # shutdown
    assert gh.writes == startup_writes + 1 and gh.state()["spent_usd"] == pytest.approx(0.02)
    g.add(0.70)  # leaves $0.03 of today's cap: written at once
    assert gh.state()["spent_usd"] == pytest.approx(0.72)


@pytest.mark.parametrize("gh", [FakeGitHub(content="not json"), FakeGitHub(exists=False)])
def test_unreadable_gist_refuses_startup(gh):
    with pytest.raises(SpendStateError):
        SpendGuard(0.75, clock=Clock(), lifetime_cap_usd=15, store=store(gh))


def test_github_down_at_startup_refuses_startup():
    gh = FakeGitHub()
    gh.down = True
    with pytest.raises(SpendStateError):
        SpendGuard(0.75, clock=Clock(), store=store(gh))


def test_missing_token_refuses_startup():
    with pytest.raises(SpendStateError):
        GistSpendStore("", "g1")


def test_lifetime_cap_never_resets():
    gh, clock = FakeGitHub(), Clock()
    SpendGuard(10.0, clock=clock, lifetime_cap_usd=1.0, store=store(gh, interval=0)).add(1.0)
    for _ in range(3):  # later days, each after a restart
        clock.t += 86_400
        g = SpendGuard(10.0, clock=clock, lifetime_cap_usd=1.0, store=store(gh, interval=0))
        assert g.spent_today == 0.0 and g.lifetime_exhausted
        with pytest.raises(SpendCapReached, match="lifetime"):
            g.check()


def test_writes_failing_for_too_long_stop_model_calls():
    gh, mono = FakeGitHub(), Clock(0.0)
    g = SpendGuard(0.75, clock=Clock(), store=store(gh, interval=0, clock=mono))
    gh.down = True
    g.add(0.01)
    assert not g.state_unavailable  # a brief outage is tolerated
    mono.t += 121
    assert g.state_unavailable
    with pytest.raises(SpendCapReached, match="can't be saved"):
        g.check()
    gh.down = False
    g.flush()  # GitHub is back: the held state is written and calls resume
    assert not g.state_unavailable and gh.state()["spent_usd"] == pytest.approx(0.01)


def test_finds_its_gist_or_creates_one():
    gh = FakeGitHub()
    assert store(gh, gist_id="").gist_id == "g1"
    empty = FakeGitHub(exists=False)
    s = store(empty, gist_id="")
    assert empty.gists[s.gist_id]["public"] is False
    assert store(empty, gist_id="").gist_id == s.gist_id  # a restart finds the same gist
