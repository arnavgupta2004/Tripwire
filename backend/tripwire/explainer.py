"""Background explanations for deterministic blocks.

A deterministic rule (e.g. the exfiltration chain) blocks a call instantly with
no model call. This runs the judge afterwards, off the hot path, to attach a
plain-English explanation to that block. One explanation per blocked call.
"""

import logging
import threading
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Protocol

from tripwire.events import BlockExplanation, EventBus
from tripwire.gateway import JudgeCase

log = logging.getLogger(__name__)


class SupportsExplain(Protocol):
    def explain_block(self, case: JudgeCase) -> object: ...


class InlineExecutor:
    """Runs work immediately in the calling thread (used in tests)."""

    def submit(self, fn, *args, **kwargs):  # noqa: ANN001 - matches Executor.submit
        fn(*args, **kwargs)
        return None


class AsyncExplainer:
    def __init__(self, judge: SupportsExplain, bus: EventBus, executor: Executor | InlineExecutor | None = None) -> None:
        self.judge = judge
        self.bus = bus
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="tripwire-explain")
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def request(self, case: JudgeCase) -> None:
        """Schedule one explanation for this blocked call, unless already requested."""
        call_id = case.call.id
        with self._lock:
            if call_id in self._seen:
                return
            self._seen.add(call_id)
        self.executor.submit(self._run, case)

    def _run(self, case: JudgeCase) -> None:
        try:
            ruling = self.judge.explain_block(case)
        except Exception:  # a background explanation must never crash anything
            log.exception("block explanation failed")
            return
        self.bus.publish(
            BlockExplanation(
                call_id=case.call.id,
                explanation=getattr(ruling, "explanation", ""),
                evidence=getattr(ruling, "evidence", ""),
                rule_id=case.escalation.rule_id,
            )
        )
