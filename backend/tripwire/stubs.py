"""Deterministic stand-ins for the Nemotron classifier and judge.

Used in tests and offline runs. Phase 2 adds the real model-backed versions
behind the same IntentClassifier / Judge interfaces.
"""

from collections.abc import Mapping
from urllib.parse import urlparse

from tripwire.decision import Decision, Verdict
from tripwire.gateway import Intent, Ruling
from tripwire.policy.engine import Facts
from tripwire.tools import ToolCall

# Words in the user's instruction that count as asking for each side effect.
DEFAULT_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "send_telegram": ("send", "message", "telegram", "brief", "notify", "ping me"),
    "write_note": ("note", "write", "save", "jot"),
    "remember": ("remember", "memorize", "keep in mind"),
    "fetch_url": ("fetch", "open", "visit", "download", "check the link"),
}


def _target(call: ToolCall) -> str:
    """The external party a call reaches: a URL's host, or a chat id."""
    if "url" in call.args:
        return urlparse(str(call.args["url"])).hostname or str(call.args["url"])
    return str(call.args.get("chat_id", ""))


class StubClassifier:
    """Aligned iff the instruction asks for this kind of action, and names any external target."""

    tier = "nano"

    def __init__(
        self,
        keywords: Mapping[str, tuple[str, ...]] = DEFAULT_INTENT_KEYWORDS,
        overrides: Mapping[str, bool] | None = None,
    ) -> None:
        self.keywords = keywords
        self.overrides = dict(overrides or {})
        self.calls: list[ToolCall] = []

    def classify(self, call: ToolCall, instruction: str, facts: Facts) -> Intent:
        self.calls.append(call)
        if call.tool in self.overrides:
            aligned = self.overrides[call.tool]
            return Intent(aligned, f"fixture override for {call.tool}: aligned={aligned}.")

        text = instruction.lower()
        if not any(word in text for word in self.keywords.get(call.tool, ())):
            return Intent(False, f"the user's instruction never asks for {call.tool}.")
        if facts.get("destination") == "external":
            target = _target(call)
            if not target or target.lower() not in text:
                return Intent(False, f"the user never named the destination {target or '(unknown)'}.")
        return Intent(True, f"the user's instruction asks for {call.tool}.")


class StubJudge:
    """Blocks anything reaching outside or carrying private data; otherwise asks the user."""

    def __init__(self, tier: str = "ultra", fixed: Verdict | None = None) -> None:
        self.tier = tier
        self.fixed = fixed
        self.calls: list[ToolCall] = []

    def judge(self, call: ToolCall, instruction: str, facts: Facts, escalation: Decision) -> Ruling:
        self.calls.append(call)
        if self.fixed is not None:
            return Ruling(self.fixed, f"fixture ruling {self.fixed}.")
        if facts.get("destination") == "external":
            return Ruling(
                Verdict.BLOCK,
                f"{call.tool} would reach {_target(call) or 'an external party'}, which the user never asked for.",
            )
        if facts.get("data.confidentiality") == "private":
            return Ruling(Verdict.BLOCK, f"{call.tool} would move private data on instructions the user didn't give.")
        return Ruling(Verdict.NEEDS_APPROVAL, f"{call.tool} wasn't clearly requested; asking the user to confirm.")
