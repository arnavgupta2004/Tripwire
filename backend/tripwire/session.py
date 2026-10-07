"""The long-running assistant: one core that the CLI, API and Telegram all drive.

A turn can pause for approval. The ApprovalBroker makes that pause answerable
from any channel, with first-answer-wins. Standing tasks (the daily brief) run
on a scheduler through the same gated pipeline.
"""

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from agent.planner import PendingApproval, Planner, Step
from skills.registry import Skills
from tripwire.config import Settings
from tripwire.events import EventBus
from tripwire.gateway import Gateway
from tripwire.models import ModelRouter
from tripwire.policy.engine import PolicyEngine
from tripwire.policy.user_rules import UserRuleStore
from tripwire.tools import ToolCall

log = logging.getLogger(__name__)

Answer = Literal["allow", "deny", "always_deny"]
Approver = Callable[["ApprovalInfo"], Answer]
DEFAULT_APPROVAL_TIMEOUT = 300.0

# "every morning brief me on AI safety", "each day at 7:30 brief me about markets"
BRIEF_RE = re.compile(
    r"(?:every|each)\s+(?:morning|day|weekday|week day)"
    r"(?:\s+at\s+(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?)?"
    r".*?\bbrief\s+me\s+(?:on|about)\s+(?P<topic>.+?)[.!]?$",
    re.IGNORECASE,
)


def parse_brief_request(text: str) -> tuple[str, int, int] | None:
    """Parse 'every morning brief me on X' into (topic, hour, minute)."""
    m = BRIEF_RE.search(text.strip())
    if not m:
        return None
    hour, minute = 8, 0
    if m.group("h"):
        hour, minute = int(m.group("h")), int(m.group("m") or 0)
        ap = (m.group("ap") or "").lower()
        if ap == "pm" and hour < 12:
            hour += 12
        if ap == "am" and hour == 12:
            hour = 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return m.group("topic").strip(), hour, minute


@dataclass
class ApprovalInfo:
    id: str
    tool: str
    args: dict[str, Any]
    reason: str
    explanation: str | None
    evidence: str | None
    rule_id: str
    source: str
    created_at: float = field(default_factory=time.time)
    answer: Answer | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "tool": self.tool, "args": self.args, "reason": self.reason,
            "explanation": self.explanation, "evidence": self.evidence, "rule_id": self.rule_id,
            "source": self.source, "created_at": self.created_at, "answered": self.answer is not None,
        }


@dataclass
class _Pending:
    info: ApprovalInfo
    event: threading.Event


class ApprovalBroker:
    """Pending approvals, answerable from any channel. First answer wins."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def open(self, pending: PendingApproval, source: str) -> ApprovalInfo:
        with self._lock:
            self._counter += 1
            approval_id = f"ap_{self._counter}"
            d = pending.decision
            info = ApprovalInfo(approval_id, pending.tool, dict(pending.args), d.reason,
                                d.explanation, d.evidence, d.rule_id, source)
            self._pending[approval_id] = _Pending(info, threading.Event())
        if self.bus is not None:
            from tripwire.events import GatewayEvent

            self.bus.publish(GatewayEvent(
                call_id=approval_id, tool=info.tool, args_summary=str(info.args)[:200],
                labels={}, verdict="NEEDS_APPROVAL", policy_verdict="NEEDS_APPROVAL",
                rule_id=info.rule_id, reason=info.reason, models=(), destination=None,
                explanation=info.explanation, evidence=info.evidence, kind="approval_opened"))
        return info

    def pending(self) -> list[ApprovalInfo]:
        with self._lock:
            return [p.info for p in self._pending.values() if p.info.answer is None]

    def get(self, approval_id: str) -> ApprovalInfo | None:
        p = self._pending.get(approval_id)
        return p.info if p else None

    def resolve(self, approval_id: str, answer: Answer) -> bool:
        """Record an answer. Returns True only for the first answer to win."""
        with self._lock:
            p = self._pending.get(approval_id)
            if p is None or p.info.answer is not None:
                return False
            p.info.answer = answer
            p.event.set()
            return True

    def wait(self, approval_id: str, timeout: float | None) -> Answer | None:
        p = self._pending.get(approval_id)
        if p is None:
            return None
        if p.event.wait(timeout):
            return p.info.answer
        return None

    def close(self, approval_id: str) -> None:
        with self._lock:
            self._pending.pop(approval_id, None)


@dataclass
class Outcome:
    reply: str
    steps: list[Step]
    approvals: list[ApprovalInfo] = field(default_factory=list)


class Session:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        router: ModelRouter,
        gateway: Gateway,
        skills: Skills,
        planner: Planner,
        *,
        rules_store: UserRuleStore | None = None,
        approval_timeout: float = DEFAULT_APPROVAL_TIMEOUT,
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.router = router
        self.gateway = gateway
        self.skills = skills
        self.planner = planner
        self.broker = ApprovalBroker(bus)
        self.rules = rules_store or UserRuleStore()
        self.approval_timeout = approval_timeout
        self._lock = threading.Lock()
        self._scheduler: Any | None = None

    # --- conversation --------------------------------------------------------

    def chat(self, text: str, source: str = "api", approver: Approver | None = None,
             timeout: float | None = None) -> Outcome:
        """Run one turn to completion. Approvals pause the turn; an answer may come
        from `approver` (inline) or from any channel via the broker (first wins)."""
        with self._lock:
            result = self.planner.send(text)
            approvals: list[ApprovalInfo] = []
            while result.status == "paused":
                info = self.broker.open(result.pending, source)
                approvals.append(info)
                if approver is not None:
                    try:
                        self.broker.resolve(info.id, approver(info))
                    except Exception:
                        log.exception("approver callback failed")
                answer = self.broker.wait(info.id, self.approval_timeout if timeout is None else timeout) or "deny"
                self.broker.close(info.id)
                if answer == "always_deny":
                    self.deny_pattern(result.pending.tool, result.pending.args)
                result = self.planner.resume(answer == "allow")
            return Outcome(result.reply, result.steps, approvals)

    def new_thread(self) -> None:
        with self._lock:
            self.planner.reset()

    def set_shield(self, on: bool) -> None:
        """on = Protected by Tripwire; off = naive agent (plain prompt, no reader, no gateway)."""
        if not on and not self.settings.demo_mode:
            raise ValueError("the naive agent requires DEMO_MODE=true")
        with self._lock:
            self.planner.shield = on
            self.skills.set_quarantine(on)

    @property
    def mode(self) -> str:
        return "protected" if self.planner.shield else "naive"

    @property
    def shield(self) -> bool:
        return self.planner.shield

    # --- user deny rules -----------------------------------------------------

    def deny_pattern(self, tool: str, args: dict[str, Any]) -> bool:
        """Persist 'always deny this pattern' and reload the policy with it in front."""
        try:
            destination = self.gateway.registry.get(tool).destination_of(ToolCall(tool, args))
        except Exception:
            destination = None
        added = self.rules.add_deny(tool, str(destination) if destination else None)
        self.gateway.engine = PolicyEngine.load(self.rules.load())
        return added

    # --- standing tasks / scheduler -----------------------------------------

    def maybe_schedule_brief(self, text: str) -> str | None:
        """If the message sets up a recurring brief, store and schedule it."""
        parsed = parse_brief_request(text)
        if parsed is None:
            return None
        topic, hour, minute = parsed
        self.schedule_brief(topic, hour, minute)
        return f"Done. I'll brief you on {topic} every day at {hour:02d}:{minute:02d}."

    def schedule_brief(self, topic: str, hour: int = 8, minute: int = 0) -> None:
        task = self.skills.memory.add_task("daily_brief", topic, f"{hour:02d}:{minute:02d}")
        if self._scheduler is not None:
            self._add_job(task.id, topic, hour, minute)

    def start_scheduler(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        if self._scheduler is not None:
            return
        self._scheduler = BackgroundScheduler(daemon=True)
        for task in self.skills.memory.tasks():
            if task.kind == "daily_brief":
                hour, minute = (int(x) for x in task.schedule.split(":"))
                self._add_job(task.id, task.topic, hour, minute)
        self._scheduler.start()

    def stop_scheduler(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def _add_job(self, task_id: str, topic: str, hour: int, minute: int) -> None:
        self._scheduler.add_job(self.run_brief, "cron", hour=hour, minute=minute, args=[topic],
                                id=task_id, replace_existing=True)

    def run_brief(self, topic: str | None = None) -> Outcome:
        """Run a brief now, through the full gated pipeline, to the user's own chat.
        Scheduled/auto runs never pause for approval (they auto-deny instead of hanging)."""
        if topic is None:
            tasks = self.skills.memory.tasks()
            if not tasks:
                return Outcome("No daily brief is set up yet.", [])
            topic = tasks[0].topic
        prompt = (f"Research {topic} and send me a short brief on Telegram. "
                  "Keep it to the key points from the last day or so.")
        return self.chat(prompt, source="scheduler", approver=lambda info: "deny")
