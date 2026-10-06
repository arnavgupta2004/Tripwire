"""Provenance labels and the per-turn context that propagates them.

A Label says how secret a value is (confidentiality), how far it can be trusted
to give instructions (integrity), and where it came from (sources). Labels form
a join-semilattice: combining two values yields a value at least as secret and
at most as trusted as either input.
"""

import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from functools import reduce
from typing import Any

from tripwire.decision import Decision


class Confidentiality(IntEnum):
    PUBLIC = 0
    PRIVATE = 1

    def __str__(self) -> str:
        return self.name.lower()


class Integrity(IntEnum):
    UNTRUSTED = 0
    TRUSTED = 1

    def __str__(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Label:
    confidentiality: Confidentiality = Confidentiality.PUBLIC
    integrity: Integrity = Integrity.TRUSTED
    sources: frozenset[str] = frozenset()

    def join(self, other: "Label") -> "Label":
        return Label(
            confidentiality=max(self.confidentiality, other.confidentiality),
            integrity=min(self.integrity, other.integrity),
            sources=self.sources | other.sources,
        )

    __or__ = join

    @property
    def is_private(self) -> bool:
        return self.confidentiality is Confidentiality.PRIVATE

    @property
    def badge(self) -> str:
        """Short tag for the parts that aren't the safe default, e.g. 'untrusted·private'."""
        flags = []
        if not self.is_trusted:
            flags.append("untrusted")
        if self.is_private:
            flags.append("private")
        return "·".join(flags)

    @property
    def is_trusted(self) -> bool:
        return self.integrity is Integrity.TRUSTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidentiality": str(self.confidentiality),
            "integrity": str(self.integrity),
            "sources": sorted(self.sources),
        }


# Identity element for join: public, trusted, no sources.
BOTTOM = Label()


def join(*labels: Label) -> Label:
    return reduce(Label.join, labels, BOTTOM)


def user_label() -> Label:
    return Label(Confidentiality.PUBLIC, Integrity.TRUSTED, frozenset({"user"}))


def file_label(*paths: str) -> Label:
    return Label(Confidentiality.PRIVATE, Integrity.TRUSTED, frozenset(f"file:{p}" for p in paths))


def web_label(*urls: str) -> Label:
    return Label(Confidentiality.PUBLIC, Integrity.UNTRUSTED, frozenset(f"web:{u}" for u in urls))


def new_handle() -> str:
    return f"h_{secrets.token_hex(6)}"


@dataclass(frozen=True)
class Labeled[T]:
    """A value with its label and a stable handle the planner can refer to."""

    value: T
    label: Label
    id: str = field(default_factory=new_handle)


@dataclass(frozen=True)
class CallRecord:
    """One tool call in a turn, whatever the gateway decided."""

    call_id: str
    tool: str
    args: Mapping[str, Any]
    side_effect: str
    destination: str | None
    data_label: Label
    decision: Decision
    output_label: Label | None = None  # set only when the call executed

    @property
    def executed(self) -> bool:
        return self.output_label is not None


class TurnContext:
    """Everything the planner has seen in one turn, joined into a single label.

    Propagation is deliberately coarse: every tool call inherits the join of all
    labels observed so far this turn.
    """

    def __init__(self, instruction: str) -> None:
        self.instruction: Labeled[str] = Labeled(instruction, user_label())
        self.label: Label = self.instruction.label
        self.history: list[CallRecord] = []
        self._values: dict[str, Labeled[Any]] = {self.instruction.id: self.instruction}

    def observe(self, item: Labeled[Any]) -> None:
        self._values[item.id] = item
        self.label = self.label.join(item.label)

    def lookup(self, handle: str) -> Labeled[Any] | None:
        return self._values.get(handle)

    def private_values(self) -> list[Labeled[Any]]:
        return [v for v in self._values.values() if v.label.is_private]

    def lookup_all(self, handles: Iterable[str]) -> list[Labeled[Any]]:
        return [v for h in handles if (v := self._values.get(h)) is not None]

    def record(self, record: CallRecord) -> None:
        self.history.append(record)

    @property
    def executed(self) -> list[CallRecord]:
        return [r for r in self.history if r.executed]
