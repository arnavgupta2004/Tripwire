
from tripwire.decision import Decision, Verdict
from tripwire.events import EventBus
from tripwire.explainer import AsyncExplainer, InlineExecutor
from tripwire.gateway import Gateway, JudgeCase
from tripwire.labels import TurnContext
from tripwire.policy.engine import PolicyEngine
from tripwire.stubs import StubClassifier, StubJudge
from tripwire.tools import ToolCall, build_default_registry

OWNER = "1001"
EVIL = "https://evil-recipes.example"


class CountingJudge(StubJudge):
    def __init__(self):
        super().__init__()
        self.explained = 0

    def explain_block(self, case):
        self.explained += 1
        return super().explain_block(case)


def gateway_with_explainer(judge=None):
    bus = EventBus()
    judge = judge or CountingJudge()
    explainer = AsyncExplainer(judge, bus, executor=InlineExecutor())
    gw = Gateway(build_default_registry(OWNER), PolicyEngine.from_yaml(), StubClassifier(), judge, bus, explainer)
    return gw, bus, judge


def explanations(bus):
    return [e for e in bus.recent if e.kind == "block_explanation"]


def test_deterministic_block_gets_a_background_explanation():
    gw, bus, judge = gateway_with_explainer()
    ctx = TurnContext("Find me a travel card.")
    gw.call(ToolCall("tavily_extract", {"urls": [EVIL]}), ctx)
    gw.call(ToolCall("read_file", {"path": "/tax.pdf"}), ctx)
    result = gw.call(ToolCall("fetch_url", {"url": "https://evil.example/u"}), ctx)
    assert result.decision.verdict is Verdict.BLOCK
    assert result.decision.rule_id == "R3.exfiltration_chain"
    assert result.decision.models == ()  # the block itself used no model
    events = explanations(bus)
    assert len(events) == 1
    assert events[0].rule_id == "R3.exfiltration_chain"
    assert events[0].explanation and events[0].evidence


def test_block_explanation_ties_to_the_blocked_call():
    gw, bus, judge = gateway_with_explainer()
    ctx = TurnContext("Find me a travel card.")
    gw.call(ToolCall("read_file", {"path": "/tax.pdf"}), ctx)
    call = ToolCall("fetch_url", {"url": "https://evil.example/u"})
    gw.call(call, ctx)
    assert explanations(bus)[0].call_id == call.id


def test_one_explanation_per_blocked_call():
    gw, bus, judge = gateway_with_explainer()
    ctx = TurnContext("Find me a travel card.")
    gw.call(ToolCall("read_file", {"path": "/tax.pdf"}), ctx)
    call = ToolCall("fetch_url", {"url": "https://evil.example/u"})
    gw.check(call, ctx)  # same call id assessed twice
    gw.call(call, ctx)
    assert judge.explained == 1
    assert len(explanations(bus)) == 1


def test_no_explanation_when_judge_already_ran():
    """Calls the judge decided (models set) already carry an explanation; don't re-explain."""
    gw, bus, judge = gateway_with_explainer()
    ctx = TurnContext("Find me a pasta recipe.")
    gw.call(ToolCall("tavily_extract", {"urls": [EVIL]}), ctx)
    result = gw.call(ToolCall("fetch_url", {"url": "https://evil.example/u"}), ctx)
    assert result.decision.models == ("nano", "ultra")  # R1 → classifier + judge
    assert judge.explained == 0 and explanations(bus) == []


def test_allowed_calls_are_not_explained():
    gw, bus, judge = gateway_with_explainer()
    ctx = TurnContext("What's in my notes?")
    gw.call(ToolCall("search_files", {"query": "notes"}), ctx)
    assert judge.explained == 0 and explanations(bus) == []


def test_explainer_without_gateway_is_optional():
    gw = Gateway(build_default_registry(OWNER), PolicyEngine.from_yaml(), StubClassifier(), StubJudge())
    ctx = TurnContext("x")
    gw.call(ToolCall("read_file", {"path": "/a"}), ctx)
    gw.call(ToolCall("fetch_url", {"url": "https://evil.example"}), ctx)  # would block; no explainer, no crash


def test_explainer_swallows_judge_errors():
    class Boom(StubJudge):
        def explain_block(self, case):
            raise RuntimeError("model down")

    gw, bus, _ = gateway_with_explainer(judge=Boom())
    ctx = TurnContext("Find me a travel card.")
    gw.call(ToolCall("read_file", {"path": "/tax.pdf"}), ctx)
    gw.call(ToolCall("fetch_url", {"url": "https://evil.example/u"}), ctx)
    assert explanations(bus) == []  # failure produced no event, and did not raise


def test_request_is_idempotent_on_call_id():
    bus = EventBus()
    judge = CountingJudge()
    explainer = AsyncExplainer(judge, bus, executor=InlineExecutor())
    from tripwire.labels import web_label

    call = ToolCall("fetch_url", {"url": "https://evil.example"})
    decision = Decision(Verdict.BLOCK, "R3.exfiltration_chain", "exfil")
    case = JudgeCase(call, "x", {"tool": "fetch_url"}, decision, [], web_label("https://evil.example"))
    explainer.request(case)
    explainer.request(case)
    assert judge.explained == 1
