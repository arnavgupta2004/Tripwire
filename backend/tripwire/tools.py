"""Tool declarations: side effects, output labeling and destinations.

The gateway only reasons about tools through these declarations, so adding a
tool means declaring how risky it is, not editing the policy engine.
"""

import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tripwire.labels import (
    Label,
    Labeled,
    file_label,
    join,
    web_label,
)


class SideEffect(StrEnum):
    NONE = "none"  # read-only
    LOCAL = "local"  # changes state on this machine (notes, memory)
    OUTBOUND = "outbound"  # sends data off the machine


class Capability(StrEnum):
    """What a tool can do, independent of its name. Composition rules (R3) match these."""

    READS_PRIVATE = "reads_private"  # returns the user's private data (files, memory)
    SENDS_EXTERNAL = "sends_external"  # pushes data to arbitrary internet endpoints (URLs, webhooks)
    WRITES_MEMORY = "writes_memory"  # writes to long-term memory that later turns trust
    FETCHES_UNTRUSTED = "fetches_untrusted"  # brings in content authored outside the user's control


class Destination(StrEnum):
    SELF = "self"  # the user's own verified channel, or local storage
    EXTERNAL = "external"


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: Mapping[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"c_{secrets.token_hex(6)}")


# (args, data_label) -> raw result. data_label is the label of everything that
# could have influenced the call, so stateful tools (remember) can store it.
Handler = Callable[[Mapping[str, Any], Label], Any]
# (call, raw_result, data_label) -> label for the result.
OutputLabeler = Callable[[ToolCall, Any, Label], Label]
DestinationFn = Callable[[ToolCall], Destination]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    side_effect: SideEffect
    output_label: OutputLabeler
    handler: Handler
    destination: DestinationFn | None = None
    # The call's arguments (a search query, a URL) leave the machine even if the
    # tool is read-only, so private specifics in them would leak.
    egress: bool = False
    capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.side_effect is SideEffect.OUTBOUND and self.destination is None:
            raise ValueError(f"outbound tool {self.name!r} needs a destination classifier")
        unknown = set(self.capabilities) - {c.value for c in Capability}
        if unknown:
            raise ValueError(f"tool {self.name!r} has unknown capabilities {sorted(unknown)}")

    def destination_of(self, call: ToolCall) -> Destination | None:
        if self.side_effect is SideEffect.NONE:
            return None
        if self.side_effect is SideEffect.LOCAL:
            return Destination.SELF
        assert self.destination is not None
        return self.destination(call)


class UnknownToolError(KeyError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(name) from None

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)


# --- output label policies -------------------------------------------------


def fixed_label(make: Callable[[ToolCall, Any], Label]) -> OutputLabeler:
    """Label every result the same way, with sources derived from the call."""
    return lambda call, result, data_label: make(call, result)


def stored_label(call: ToolCall, result: Any, data_label: Label) -> Label:
    """Results carry their own labels (e.g. recalled memories): join them."""
    items = [result] if isinstance(result, Labeled) else list(result or [])
    if not items:
        return Label(sources=frozenset({"memory"}))
    return join(*(item.label for item in items))


def status_label(call: ToolCall, result: Any, data_label: Label) -> Label:
    """Side-effect tools return a status we generated ourselves."""
    return Label(sources=frozenset({f"tool:{call.tool}"}))


def _urls(result: Any) -> Iterable[str]:
    if isinstance(result, list):
        return [r["url"] for r in result if isinstance(r, Mapping) and "url" in r]
    return []


def _web_label_for_search(call: ToolCall, result: Any) -> Label:
    urls = list(_urls(result)) or [f"tavily_search?q={call.args.get('query', '')}"]
    return web_label(*urls)


def _web_label_for_extract(call: ToolCall, result: Any) -> Label:
    urls = call.args.get("urls") or [call.args.get("url", "unknown")]
    return web_label(*([urls] if isinstance(urls, str) else urls))


def _file_label_for_search(call: ToolCall, result: Any) -> Label:
    items = result if isinstance(result, list) else []
    paths = [r["path"] if isinstance(r, Mapping) else r for r in items if isinstance(r, (str, Mapping))]
    paths = [p for p in paths if isinstance(p, str)]
    return file_label(*(paths or [f"search?q={call.args.get('query', '')}"]))


# --- default tool set (stub handlers; Phase 3 wires the real skills) ---------


def build_default_registry(
    owner_chat_id: str,
    handlers: Mapping[str, Handler] | None = None,
) -> ToolRegistry:
    """Register Tripwire's tools. `handlers` overrides stub handlers by tool name."""
    memory: dict[str, Labeled[str]] = {}

    def remember(args: Mapping[str, Any], data_label: Label) -> str:
        fact = Labeled(str(args.get("fact", "")), data_label)
        memory[fact.id] = fact
        return fact.id

    def recall(args: Mapping[str, Any], data_label: Label) -> list[Labeled[str]]:
        query = str(args.get("query", "")).lower()
        return [f for f in memory.values() if query in f.value.lower()]

    def telegram_destination(call: ToolCall) -> Destination:
        owner = str(owner_chat_id or "")
        chat_id = str(call.args.get("chat_id") or owner)
        return Destination.SELF if owner and chat_id == owner else Destination.EXTERNAL

    stubs: dict[str, Handler] = {
        "tavily_search": lambda a, _: [],
        "tavily_extract": lambda a, _: [],
        "read_file": lambda a, _: f"<contents of {a.get('path')}>",
        "search_files": lambda a, _: [],
        "remember": remember,
        "recall": recall,
        "send_telegram": lambda a, _: "sent",
        "write_note": lambda a, _: f"notes/{a.get('title', 'note')}.md",
        "fetch_url": lambda a, _: "",
    }
    stubs.update(handlers or {})

    def private_file(call: ToolCall, result: Any) -> Label:
        return file_label(str(call.args.get("path", "unknown")))

    def fetched_page(call: ToolCall, result: Any) -> Label:
        return web_label(str(call.args.get("url", "unknown")))

    C = Capability
    untrusted_in = frozenset({C.FETCHES_UNTRUSTED})
    private_in = frozenset({C.READS_PRIVATE})
    specs = [
        ToolSpec("tavily_search", SideEffect.NONE, fixed_label(_web_label_for_search), stubs["tavily_search"],
                 egress=True, capabilities=untrusted_in),
        ToolSpec("tavily_extract", SideEffect.NONE, fixed_label(_web_label_for_extract), stubs["tavily_extract"],
                 egress=True, capabilities=untrusted_in),
        ToolSpec("read_file", SideEffect.NONE, fixed_label(private_file), stubs["read_file"], capabilities=private_in),
        ToolSpec("search_files", SideEffect.NONE, fixed_label(_file_label_for_search), stubs["search_files"],
                 capabilities=private_in),
        ToolSpec("recall", SideEffect.NONE, stored_label, stubs["recall"], capabilities=private_in),
        ToolSpec("remember", SideEffect.LOCAL, status_label, stubs["remember"],
                 capabilities=frozenset({C.WRITES_MEMORY})),
        ToolSpec("write_note", SideEffect.LOCAL, status_label, stubs["write_note"]),
        # Messaging a person is not sends_external: a user may legitimately share with
        # someone, so R2 holds it for approval or the judge rather than blocking outright.
        ToolSpec("send_telegram", SideEffect.OUTBOUND, status_label, stubs["send_telegram"],
                 destination=telegram_destination),
        ToolSpec("fetch_url", SideEffect.OUTBOUND, fixed_label(fetched_page), stubs["fetch_url"],
                 destination=lambda call: Destination.EXTERNAL, egress=True,
                 capabilities=frozenset({C.SENDS_EXTERNAL, C.FETCHES_UNTRUSTED})),
    ]
    registry = ToolRegistry()
    for spec in specs:
        registry.register(spec)
    return registry

