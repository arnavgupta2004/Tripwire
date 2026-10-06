"""User-authored deny rules, persisted to config/user_rules.yaml.

These come from the user clicking "Always deny this pattern" on an approval
card. They are loaded ahead of the built-in rules so a user deny wins.
"""

from pathlib import Path
from typing import Any

import yaml

from tripwire.config import REPO_ROOT

DEFAULT_PATH = REPO_ROOT / "config" / "user_rules.yaml"


def pattern_id(tool: str, destination: str | None) -> str:
    return f"U.deny_{tool}_{destination or 'any'}"


def deny_rule(tool: str, destination: str | None) -> dict[str, Any]:
    """A rule that blocks future calls matching this (tool, destination) pattern."""
    when: dict[str, str] = {"tool": tool}
    if destination and destination != "none":
        when["destination"] = destination
    where = f"{tool} to {destination}" if destination and destination != "none" else tool
    return {
        "id": pattern_id(tool, destination),
        "when": when,
        "then": "BLOCK",
        "reason": f"You chose to always deny this: {where}.",
    }


class UserRuleStore:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        doc = yaml.safe_load(self.path.read_text()) or {}
        rules = doc.get("rules")
        return list(rules) if isinstance(rules, list) else []

    def add_deny(self, tool: str, destination: str | None) -> bool:
        """Persist a deny rule for this pattern. Returns False if it already exists."""
        rules = self.load()
        rule = deny_rule(tool, destination)
        if any(r.get("id") == rule["id"] for r in rules):
            return False
        rules.append(rule)
        self._write(rules)
        return True

    def remove(self, rule_id: str) -> bool:
        rules = self.load()
        kept = [r for r in rules if r.get("id") != rule_id]
        if len(kept) == len(rules):
            return False
        self._write(kept)
        return True

    def _write(self, rules: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = "# User deny rules, written by \"Always deny this pattern\". Loaded before the built-in rules.\n"
        self.path.write_text(header + yaml.safe_dump({"rules": rules}, sort_keys=False))
