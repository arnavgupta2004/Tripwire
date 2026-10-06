"""In-process event bus. Phase 4 streams these events to the UI over WebSocket."""

import logging
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
    kind: str = "decision"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Subscriber = Callable[[GatewayEvent], None]


class EventBus:
    def __init__(self, keep: int = 500) -> None:
        self._subscribers: list[Subscriber] = []
        self.recent: deque[GatewayEvent] = deque(maxlen=keep)

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        self._subscribers.append(fn)
        return lambda: self._subscribers.remove(fn)

    def publish(self, event: GatewayEvent) -> None:
        self.recent.append(event)
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception:
                # A broken UI listener must never break enforcement.
                log.exception("event subscriber failed")
