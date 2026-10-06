"""In-process event bus. Phase 4 streams these events to the UI over WebSocket.

Events are dataclasses with a `kind` and a `to_dict()`: GatewayEvent here,
ModelCallEvent in models.py, EgressEvent in skills.
"""

import logging
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewayEvent:
    call_id: str
    tool: str
    args_summary: str
    labels: dict[str, dict[str, Any]]  # "args", "context", "data" -> Label.to_dict()
    verdict: str
    policy_verdict: str
    rule_id: str
    reason: str
    models: tuple[str, ...]
    destination: str | None = None
    explanation: str | None = None
    evidence: str | None = None
    kind: str = "decision"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BlockExplanation:
    """A plain-English explanation generated in the background for a deterministic
    block, after the block already happened. Attached to the decision by call_id."""

    call_id: str
    explanation: str
    evidence: str
    rule_id: str
    kind: str = "block_explanation"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Subscriber = Callable[[Any], None]


class EventBus:
    def __init__(self, keep: int = 500) -> None:
        self._subscribers: list[Subscriber] = []
        self.recent: deque[Any] = deque(maxlen=keep)

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        self._subscribers.append(fn)
        return lambda: self._subscribers.remove(fn)

    def publish(self, event: Any) -> None:
        self.recent.append(event)
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception:
                # A broken UI listener must never break enforcement.
                log.exception("event subscriber failed")


CANARY = re.compile(r"CANARY-[A-Z0-9]+")


@dataclass(frozen=True)
class EgressEvent:
    """Something tried to leave the machine (a message, a URL fetch). Logged
    whether or not it was actually delivered, so demos and evals can show it."""

    tool: str
    target: str
    delivered: bool
    note: str
    preview: str
    canaries: tuple[str, ...]
    kind: str = "egress"
    ts: float = field(default_factory=time.time)

    @classmethod
    def build(cls, tool: str, target: str, payload: str, delivered: bool, note: str) -> "EgressEvent":
        canaries = tuple(sorted(set(CANARY.findall(payload))))
        preview = payload if len(payload) <= 200 else payload[:199] + "…"
        return cls(tool, target, delivered, note, preview, canaries)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
