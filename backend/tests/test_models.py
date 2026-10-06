import httpx
import pytest
from openai import APITimeoutError, BadRequestError, RateLimitError

from fakes.openai_client import FakeClient, completion, json_reply
from tripwire.config import Settings
from tripwire.events import EventBus
from tripwire.models import (
    ModelCallEvent,
    ModelError,
    Pricing,
    parse_json_object,
    strip_reasoning,
    summarize_usage,
)

REQUEST = httpx.Request("POST", "https://api.tokenfactory.nebius.com/v1/chat/completions")


def rate_limited(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    return RateLimitError("slow down", response=httpx.Response(429, headers=headers, request=REQUEST), body=None)


def bad_request() -> BadRequestError:
    return BadRequestError("bad", response=httpx.Response(400, request=REQUEST), body=None)


def test_routes_tiers_to_configured_models(make_router):
    client = FakeClient([completion("a"), completion("b")])
    router = make_router(client)
    router.chat("nano", [{"role": "user", "content": "hi"}], purpose="t")
    router.chat("ultra", [{"role": "user", "content": "hi"}], purpose="t", reasoning=True)
    assert [r["model"] for r in client.requests] == ["nvidia/nano-test", "nvidia/ultra-test"]


def test_reasoning_toggle_is_sent_as_chat_template_flag(make_router):
    client = FakeClient([completion("a"), completion("b")])
    router = make_router(client)
    router.chat("nano", [], purpose="t")
    router.chat("ultra", [], purpose="t", reasoning=True)
    assert client.requests[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert client.requests[1]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}


def test_reasoning_content_and_think_tags_are_separated(make_router):
    router = make_router(FakeClient([completion("<think>hmm</think> answer", reasoning="deep thoughts")]))
    result = router.chat("ultra", [], purpose="t", reasoning=True)
    assert result.content == "answer"
    assert result.reasoning == "deep thoughts"


def test_missing_tier_raises(make_router, settings):
    router = make_router(FakeClient([]), settings=Settings(api_key="x", models={"nano": "n"}))
    with pytest.raises(ModelError, match="NEMOTRON_SUPER_MODEL"):
        router.chat("super", [], purpose="t")


def test_records_usage_cost_and_publishes_event(make_router):
    bus = EventBus()
    router = make_router(FakeClient([completion("x", tokens_in=1000, tokens_out=500)]), bus=bus)
    router.chat("nano", [], purpose="classifier.align")
    record = router.records[0]
    assert (record.tier, record.model, record.purpose) == ("nano", "nvidia/nano-test", "classifier.align")
    assert (record.tokens_in, record.tokens_out, record.ok, record.attempts) == (1000, 500, True, 1)
    assert record.cost_usd == pytest.approx((1000 * 0.1 + 500 * 0.4) / 1e6)
    assert record.latency_ms >= 0
    assert bus.recent[-1] is record and record.kind == "model_call"


def test_unpriced_model_has_null_cost(make_router):
    router = make_router(FakeClient([completion("x")]))
    assert router.chat("super", [], purpose="t").record.cost_usd is None


def test_retries_transient_errors_then_succeeds(make_router):
    timeout = APITimeoutError(request=REQUEST)
    router = make_router(FakeClient([timeout, rate_limited(), completion("ok")]))
    result = router.chat("nano", [], purpose="t")
    assert result.content == "ok" and result.record.attempts == 3


def test_honours_retry_after(make_router, settings):
    waits = []
    from tripwire.models import ModelRouter

    router = ModelRouter(settings, client=FakeClient([rate_limited("7"), completion("ok")]), sleep=waits.append)
    router.chat("nano", [], purpose="t")
    assert waits == [7.0]


def test_gives_up_after_max_retries_and_logs_failure(make_router):
    router = make_router(FakeClient([APITimeoutError(request=REQUEST)] * 4), max_retries=3)
    with pytest.raises(ModelError, match="after 4 attempts"):
        router.chat("nano", [], purpose="t")
    assert router.records[-1].ok is False and router.records[-1].attempts == 4


def test_non_retryable_errors_fail_fast(make_router):
    client = FakeClient([bad_request(), completion("never")])
    router = make_router(client)
    with pytest.raises(ModelError):
        router.chat("nano", [], purpose="t")
    assert len(client.requests) == 1


def test_chat_json_sends_strict_schema_and_parses(make_router):
    client = FakeClient([json_reply({"aligned": True})])
    router = make_router(client)
    schema = {"type": "object", "properties": {"aligned": {"type": "boolean"}}, "required": ["aligned"]}
    data, _ = router.chat_json("nano", [], schema, purpose="classifier.align")
    assert data == {"aligned": True}
    fmt = client.requests[0]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == schema


def test_chat_json_falls_back_when_response_format_rejected(make_router):
    client = FakeClient([bad_request(), completion('Sure! ```json\n{"aligned": false}\n```')])
    router = make_router(client)
    data, _ = router.chat_json("nano", [], {"type": "object"}, purpose="t")
    assert data == {"aligned": False}
    assert "response_format" not in client.requests[1]


def test_chat_json_returns_none_on_garbage(make_router):
    data, result = make_router(FakeClient([completion("I think it is aligned.")])).chat_json(
        "nano", [], {"type": "object"}, purpose="t"
    )
    assert data is None and result.content


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('<think>{"no": 1}</think>{"a": 1}', {"a": 1}),
        ('prefix {"a": {"b": 2}} suffix', {"a": {"b": 2}}),
        ("[1, 2]", None),
        ("nothing here", None),
        ('{"broken": ', None),
    ],
)
def test_parse_json_object(text, expected):
    assert parse_json_object(text) == expected


def test_strip_reasoning():
    assert strip_reasoning("<think>\nx\n</think>\n\nhello") == "hello"
    assert strip_reasoning(None) == ""


def test_judge_tier_falls_back_to_super():
    assert Settings(models={"super": "s", "ultra": "u"}).effective_judge_tier == "ultra"
    assert Settings(models={"super": "s"}).effective_judge_tier == "super"
    assert Settings(models={"super": "s", "ultra": "u"}, judge_tier="super").effective_judge_tier == "super"


def test_settings_from_env(monkeypatch, tmp_path):
    for k, v in {
        "NEBIUS_API_KEY": "k",
        "NEMOTRON_NANO_MODEL": "n",
        "NEMOTRON_SUPER_MODEL": "s",
        "JUDGE_TIER": "SUPER",
        "DEMO_MODE": "true",
        "FETCH_ALLOWLIST": "Example.com, demo.test",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("NEMOTRON_ULTRA_MODEL", raising=False)
    s = Settings.from_env(env_file=None)
    assert s.models == {"nano": "n", "super": "s"}
    assert s.judge_tier == "super" and s.demo_mode is True
    assert s.fetch_allowlist == ("example.com", "demo.test")
    monkeypatch.setenv("JUDGE_TIER", "mega")
    with pytest.raises(ValueError):
        Settings.from_env(env_file=None)


def _rec(tier, latency, cost, ok=True):
    return ModelCallEvent(tier, "m", "p", 100, 10, latency, cost, ok, 1, False)


def test_usage_summary():
    summary = summarize_usage(
        [_rec("nano", 100, 0.001), _rec("nano", 300, 0.001), _rec("super", 900, None), _rec("ultra", 0, None, ok=False)]
    )
    nano = summary["tiers"]["nano"]
    assert (nano["calls"], nano["tokens_in"], nano["cost_usd"]) == (2, 200, pytest.approx(0.002))
    assert nano["latency_p50_ms"] == pytest.approx(200)
    assert summary["tiers"]["ultra"]["failed"] == 1
    assert summary["headline"] == "This session: 2 Nano, 1 Super, 1 Ultra — $0.0020 + unpriced calls"


def test_pricing_from_file(tmp_path):
    p = tmp_path / "pricing.yaml"
    p.write_text("models:\n  m: {input_per_m: 1.0, output_per_m: 2.0}\n")
    assert Pricing.from_file(p).cost("m", 1_000_000, 1_000_000) == 3.0
    assert Pricing.from_file(tmp_path / "missing.yaml").cost("m", 1, 1) is None
