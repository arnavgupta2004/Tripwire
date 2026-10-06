"""Gateway verdicts and decisions."""

from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"  # hand to the judge; never a final gateway verdict
    NEEDS_APPROVAL = "NEEDS_APPROVAL"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    rule_id: str
    reason: str
    # What the deterministic rules said before the classifier/judge ran.
    # Equal to `verdict` when no model was consulted.
    policy_verdict: Verdict | None = None
    # Model tiers consulted for this decision (stubs report the tier they stand in for).
    models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("Decision.rule_id must be non-empty")
        if not self.reason.strip():
            raise ValueError("Decision.reason must be non-empty")
        if self.policy_verdict is None:
            object.__setattr__(self, "policy_verdict", self.verdict)

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW
