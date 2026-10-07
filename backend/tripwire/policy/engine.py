"""Deterministic, declarative flow policy.

The engine knows nothing about specific tools. It matches rules from YAML
against "facts": flat string maps describing the proposed call and, for
sequence rules, the calls that already ran this turn.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tripwire.decision import Decision, Verdict
from tripwire.labels import CallRecord, Label

DEFAULT_RULES = Path(__file__).with_name("rules.yaml")
CLASSIFY = "CLASSIFY"

Facts = Mapping[str, str]
Condition = Mapping[str, frozenset[str]]

CALL_KEYS = frozenset(
    {
        "tool",
        "side_effect",
        "destination",
        "egress",
        "cap.reads_private",
        "cap.sends_external",
        "cap.writes_memory",
        "cap.fetches_untrusted",
        "context.confidentiality",
        "context.integrity",
        "data.confidentiality",
        "data.integrity",
        "args.confidentiality",
        "args.integrity",
    }
)
HISTORY_KEYS = CALL_KEYS | {"output.confidentiality", "output.integrity"}
OUTCOME_KEYS = CALL_KEYS | {"aligned", "leaking"}
CLASSIFIER_MODES = ("align", "leak")


class PolicyError(ValueError):
    pass


# --- facts -----------------------------------------------------------------


def _label_facts(prefix: str, label: Label) -> dict[str, str]:
    return {
        f"{prefix}.confidentiality": str(label.confidentiality),
        f"{prefix}.integrity": str(label.integrity),
    }


CAPABILITIES = ("reads_private", "sends_external", "writes_memory", "fetches_untrusted")


def _capability_facts(capabilities: frozenset[str] | set[str] | tuple[str, ...]) -> dict[str, str]:
    caps = set(capabilities)
    return {f"cap.{c}": str(c in caps).lower() for c in CAPABILITIES}


def call_facts(
    tool: str,
    side_effect: str,
    destination: str | None,
    context: Label,
    args: Label,
    egress: bool = False,
    capabilities: frozenset[str] = frozenset(),
) -> dict[str, str]:
    return {
        "tool": tool,
        "side_effect": str(side_effect),
        "destination": str(destination) if destination else "none",
        "egress": str(egress).lower(),
        **_capability_facts(capabilities),
        **_label_facts("context", context),
        **_label_facts("args", args),
        **_label_facts("data", context.join(args)),
    }


def record_facts(record: CallRecord) -> dict[str, str]:
    facts = {
        "tool": record.tool,
        "side_effect": str(record.side_effect),
        "destination": str(record.destination) if record.destination else "none",
        **_capability_facts(record.capabilities),
        **_label_facts("data", record.data_label),
    }
    if record.output_label is not None:
        facts.update(_label_facts("output", record.output_label))
    return facts


def matches(condition: Condition, facts: Facts) -> bool:
    return all(facts.get(key) in allowed for key, allowed in condition.items())


# --- rules -----------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    when: Condition
    then: Verdict
    reason: str


@dataclass(frozen=True)
class Rule:
    id: str
    then: str  # a Verdict value or CLASSIFY
    reason: str
    when: Condition
    unless: Condition | None = None
    sequence: tuple[Condition, ...] = ()
    outcomes: tuple[Outcome, ...] = ()
    classifier: str = "align"  # CLASSIFY rules: "align" (intent) or "leak" (query egress)


@dataclass(frozen=True)
class Classify:
    """The matched rule wants the intent classifier before deciding."""

    rule: Rule
    reason: str


class _Template(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render(template: str, facts: Facts, chain: str = "") -> str:
    return template.format_map(
        _Template(tool=facts.get("tool", "?"), destination=facts.get("destination", "?"), chain=chain)
    )


def _parse_condition(raw: Any, allowed: frozenset[str], where: str) -> Condition:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise PolicyError(f"{where}: condition must be a mapping")
    unknown = set(raw) - allowed
    if unknown:
        raise PolicyError(f"{where}: unknown condition key(s) {sorted(unknown)}")
    parsed = {}
    for key, value in raw.items():
        values = value if isinstance(value, list) else [value]
        parsed[key] = frozenset(str(v).lower() if isinstance(v, bool) else str(v) for v in values)
    return parsed


def _parse_verdict(raw: Any, where: str, allow_classify: bool) -> str:
    valid = {v.value for v in Verdict} | ({CLASSIFY} if allow_classify else set())
    if raw not in valid:
        raise PolicyError(f"{where}: 'then' must be one of {sorted(valid)}, got {raw!r}")
    return raw


def _require_reason(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise PolicyError(f"{where}: a non-empty 'reason' is required")
    return raw


def _parse_rule(raw: Mapping[str, Any]) -> Rule:
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise PolicyError(f"rule without an id: {raw!r}")
    where = f"rule {rule_id}"
    then = _parse_verdict(raw.get("then"), where, allow_classify=True)
    reason = _require_reason(raw.get("reason"), where)

    steps = raw.get("sequence") or []
    if steps and len(steps) < 2:
        raise PolicyError(f"{where}: a sequence needs at least two steps")
    sequence = tuple(
        _parse_condition(step, HISTORY_KEYS if i < len(steps) - 1 else CALL_KEYS, f"{where} step {i + 1}")
        for i, step in enumerate(steps)
    )

    outcomes = []
    for i, out in enumerate(raw.get("outcomes") or []):
        ow = f"{where} outcome {i + 1}"
        outcomes.append(
            Outcome(
                when=_parse_condition(out.get("when"), OUTCOME_KEYS, ow),
                then=Verdict(_parse_verdict(out.get("then"), ow, allow_classify=False)),
                reason=_require_reason(out.get("reason"), ow),
            )
        )
    if then == CLASSIFY and not outcomes:
        raise PolicyError(f"{where}: CLASSIFY rules need outcomes")
    if outcomes and then != CLASSIFY:
        raise PolicyError(f"{where}: only CLASSIFY rules may have outcomes")
    classifier = raw.get("classifier", "align")
    if classifier not in CLASSIFIER_MODES:
        raise PolicyError(f"{where}: 'classifier' must be one of {CLASSIFIER_MODES}")

    return Rule(
        id=rule_id,
        then=then,
        reason=reason,
        when=_parse_condition(raw.get("when"), CALL_KEYS, where),
        unless=_parse_condition(raw["unless"], CALL_KEYS, f"{where} unless") if "unless" in raw else None,
        sequence=sequence,
        outcomes=tuple(outcomes),
        classifier=classifier,
    )


def _find_chain(steps: Sequence[Condition], history: Sequence[Facts]) -> list[Facts] | None:
    """Match steps, in order, against a subsequence of history (gaps allowed)."""
    found: list[Facts] = []
    i = 0
    for facts in history:
        if i == len(steps):
            break
        if matches(steps[i], facts):
            found.append(facts)
            i += 1
    return found if i == len(steps) else None


class PolicyEngine:
    def __init__(self, rules: Sequence[Rule]) -> None:
        ids = [r.id for r in rules]
        if len(ids) != len(set(ids)):
            raise PolicyError("rule ids must be unique")
        self.rules = tuple(rules)

    @classmethod
    def from_yaml_text(cls, text: str) -> "PolicyEngine":
        doc = yaml.safe_load(text) or {}
        raw_rules = doc.get("rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise PolicyError("policy must define a non-empty 'rules' list")
        return cls([_parse_rule(r) for r in raw_rules])

    @classmethod
    def from_yaml(cls, path: Path | str = DEFAULT_RULES) -> "PolicyEngine":
        return cls.from_yaml_text(Path(path).read_text())

    @classmethod
    def load(cls, user_rules: Sequence[Mapping[str, Any]] = (), base: Path | str = DEFAULT_RULES) -> "PolicyEngine":
        """Built-in rules, with user deny rules (if any) evaluated first."""
        doc = yaml.safe_load(Path(base).read_text()) or {}
        base_rules = doc.get("rules")
        if not isinstance(base_rules, list) or not base_rules:
            raise PolicyError("policy must define a non-empty 'rules' list")
        rules = [_parse_rule(r) for r in user_rules] + [_parse_rule(r) for r in base_rules]
        return cls(rules)

    def evaluate(self, facts: Facts, history: Sequence[Facts] = ()) -> Decision | Classify:
        """First matching rule wins. `history` holds facts of calls that ran this turn."""
        for rule in self.rules:
            if not matches(rule.when, facts):
                continue
            if rule.unless is not None and matches(rule.unless, facts):
                continue
            chain = ""
            if rule.sequence:
                *earlier, last = rule.sequence
                if not matches(last, facts):
                    continue
                prior = _find_chain(earlier, history)
                if prior is None:
                    continue
                chain = " → ".join([f["tool"] for f in prior] + [facts["tool"]])
            reason = _render(rule.reason, facts, chain)
            if rule.then == CLASSIFY:
                return Classify(rule, reason)
            return Decision(Verdict(rule.then), rule.id, reason)
        return Decision(Verdict.BLOCK, "R0.no_match", "No policy rule matched this call; failing closed.")

    def resolve(self, pending: Classify, facts: Facts, signals: Mapping[str, bool]) -> Decision:
        """Pick the outcome of a CLASSIFY rule given the classifier's answer,
        e.g. signals={"aligned": True} or {"leaking": False}."""
        with_intent = {**facts, **{k: str(v).lower() for k, v in signals.items()}}
        for outcome in pending.rule.outcomes:
            if matches(outcome.when, with_intent):
                return Decision(outcome.then, pending.rule.id, _render(outcome.reason, facts))
        return Decision(
            Verdict.ESCALATE,
            pending.rule.id,
            f"{pending.reason} No classifier outcome matched; escalating.",
        )
