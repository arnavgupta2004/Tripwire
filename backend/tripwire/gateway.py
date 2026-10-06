"""The Tripwire gateway: every planner tool call passes through here.

check(): label lookup → policy rules → intent classifier / judge when the
rules ask for them → Decision (and an event on the bus).
call(): check(), then execute the tool if allowed, label its output and fold
that label into the turn context.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from tripwire.decision import Decision, Verdict
from tripwire.events import EventBus, GatewayEvent
from tripwire.labels import BOTTOM, CallRecord, Label, Labeled, TurnContext, join
from tripwire.policy.engine import (
    Classify,
    Facts,
    PolicyEngine,
    call_facts,
    record_facts,
)
from tripwire.tools import ToolCall, ToolRegistry, ToolSpec, UnknownToolError

HANDLE = re.compile(r"\bh_[0-9a-f]{12}\b")
ARGS_SUMMARY_LIMIT = 200


@dataclass(frozen=True)
class Intent:
    aligned: bool
    rationale: str
    confidence: float | None = None


@dataclass(frozen=True)
class Leak:
    leaking: bool
    rationale: str


@dataclass(frozen=True)
class Ruling:
    verdict: Verdict
    explanation: str
    evidence: str = ""


@dataclass(frozen=True)
class JudgeCase:
    """Everything the judge sees about an escalated call."""

    call: ToolCall
    instruction: str
    facts: Facts
    escalation: Decision
    history: Sequence[CallRecord]
    data_label: Label


class IntentClassifier(Protocol):
    """Does the proposed call serve the user's trusted instruction? (Nemotron Nano in Phase 2.)"""

    tier: str

    def classify(self, call: ToolCall, instruction: str, facts: Facts) -> Intent: ...

    def check_leak(self, call: ToolCall, private_texts: list[str], facts: Facts) -> Leak:
        """Do the call's arguments (query, URL) contain private specifics from these texts?"""
        ...


class Judge(Protocol):
    """Rules on escalations with a plain-English explanation. (Nemotron Ultra in Phase 2.)"""

    tier: str

    def judge(self, case: JudgeCase) -> Ruling: ...


@dataclass(frozen=True)
class CallResult:
    decision: Decision
    output: Labeled[Any] | None = None


def _handles_in(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(HANDLE.findall(value))
    if isinstance(value, Mapping):
        return set().union(*(_handles_in(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return set().union(*(_handles_in(v) for v in value)) if value else set()
    return set()


def _summarize(args: Mapping[str, Any]) -> str:
    text = json.dumps(args, default=str, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= ARGS_SUMMARY_LIMIT else text[: ARGS_SUMMARY_LIMIT - 1] + "…"


@dataclass(frozen=True)
class _Assessment:
    spec: ToolSpec | None
    destination: str | None
    context_label: Label
    args_label: Label
    decision: Decision

    @property
    def data_label(self) -> Label:
        return self.context_label.join(self.args_label)


class Gateway:
    def __init__(
        self,
        registry: ToolRegistry,
        engine: PolicyEngine,
        classifier: IntentClassifier,
        judge: Judge,
        bus: EventBus | None = None,
    ) -> None:
        self.registry = registry
        self.engine = engine
        self.classifier = classifier
        self.judge = judge
        self.bus = bus or EventBus()

    def check(self, call: ToolCall, ctx: TurnContext) -> Decision:
        return self._assess(call, ctx).decision

    def call(self, call: ToolCall, ctx: TurnContext) -> CallResult:
        a = self._assess(call, ctx)
        output: Labeled[Any] | None = None
        if a.decision.allowed:
            assert a.spec is not None
            raw = a.spec.handler(call.args, a.data_label)
            output = Labeled(raw, a.spec.output_label(call, raw, a.data_label))
            ctx.observe(output)
        ctx.record(
            CallRecord(
                call_id=call.id,
                tool=call.tool,
                args=dict(call.args),
                side_effect=str(a.spec.side_effect) if a.spec else "unknown",
                destination=a.destination,
                data_label=a.data_label,
                decision=a.decision,
                output_label=output.label if output else None,
            )
        )
        return CallResult(a.decision, output)

    # --- internals ---------------------------------------------------------

    def _assess(self, call: ToolCall, ctx: TurnContext) -> _Assessment:
        try:
            spec = self.registry.get(call.tool)
        except UnknownToolError:
            decision = Decision(Verdict.BLOCK, "G0.unknown_tool", f"{call.tool} is not a registered tool.")
            a = _Assessment(None, None, ctx.label, BOTTOM, decision)
            self._emit(call, a)
            return a

        destination = spec.destination_of(call)
        args_label = join(*(v.label for v in ctx.lookup_all(_handles_in(call.args))))
        facts = call_facts(call.tool, spec.side_effect, destination, ctx.label, args_label, spec.egress)
        history = [record_facts(r) for r in ctx.executed]

        decision = self._decide(call, ctx, facts, history, ctx.label.join(args_label))
        a = _Assessment(spec, destination, ctx.label, args_label, decision)
        self._emit(call, a)
        return a

    def _decide(
        self, call: ToolCall, ctx: TurnContext, facts: Facts, history: list[Facts], data_label: Label
    ) -> Decision:
        instruction = ctx.instruction.value
        models: list[str] = []

        result = self.engine.evaluate(facts, history)
        if isinstance(result, Classify):
            if result.rule.classifier == "leak":
                private_texts = [str(v.value) for v in ctx.private_values()]
                leak = self.classifier.check_leak(call, private_texts, facts)
                signals, rationale = {"leaking": leak.leaking}, leak.rationale
            else:
                intent = self.classifier.classify(call, instruction, facts)
                signals, rationale = {"aligned": intent.aligned}, intent.rationale
            models.append(self.classifier.tier)
            resolved = self.engine.resolve(result, facts, signals)
            result = Decision(
                resolved.verdict,
                resolved.rule_id,
                f"{resolved.reason} Classifier: {rationale}",
                models=tuple(models),
            )

        if result.verdict is not Verdict.ESCALATE:
            return result

        ruling = self.judge.judge(JudgeCase(call, instruction, facts, result, list(ctx.history), data_label))
        models.append(self.judge.tier)
        # The judge can only block or ask the user; it never silently allows.
        verdict = ruling.verdict if ruling.verdict in (Verdict.BLOCK, Verdict.NEEDS_APPROVAL) else Verdict.NEEDS_APPROVAL
        return Decision(
            verdict,
            result.rule_id,
            f"{result.reason} Judge: {ruling.explanation}",
            policy_verdict=Verdict.ESCALATE,
            models=tuple(models),
            explanation=ruling.explanation,
            evidence=ruling.evidence or None,
        )

    def _emit(self, call: ToolCall, a: _Assessment) -> None:
        self.bus.publish(
            GatewayEvent(
                call_id=call.id,
                tool=call.tool,
                args_summary=_summarize(call.args),
                labels={
                    "args": a.args_label.to_dict(),
                    "context": a.context_label.to_dict(),
                    "data": a.data_label.to_dict(),
                },
                verdict=str(a.decision.verdict),
                policy_verdict=str(a.decision.policy_verdict),
                rule_id=a.decision.rule_id,
                reason=a.decision.reason,
                models=a.decision.models,
                destination=a.destination,
                explanation=a.decision.explanation,
                evidence=a.decision.evidence,
            )
        )
