import pytest

from tripwire.labels import BOTTOM, Confidentiality, Integrity, Label, file_label
from tripwire.tools import (
    Destination,
    SideEffect,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    UnknownToolError,
    build_default_registry,
    status_label,
)

OWNER = "1001"


@pytest.fixture
def registry() -> ToolRegistry:
    return build_default_registry(OWNER)


def run(registry, tool, data_label=BOTTOM, **args):
    spec = registry.get(tool)
    call = ToolCall(tool, args)
    result = spec.handler(call.args, data_label)
    return result, spec.output_label(call, result, data_label)


def test_all_tools_registered(registry):
    assert registry.names == sorted(
        [
            "tavily_search",
            "tavily_extract",
            "read_file",
            "search_files",
            "remember",
            "recall",
            "send_telegram",
            "write_note",
            "fetch_url",
        ]
    )


@pytest.mark.parametrize(
    "tool,effect",
    [
        ("tavily_search", SideEffect.NONE),
        ("tavily_extract", SideEffect.NONE),
        ("read_file", SideEffect.NONE),
        ("search_files", SideEffect.NONE),
        ("recall", SideEffect.NONE),
        ("remember", SideEffect.LOCAL),
        ("write_note", SideEffect.LOCAL),
        ("send_telegram", SideEffect.OUTBOUND),
        ("fetch_url", SideEffect.OUTBOUND),
    ],
)
def test_side_effects(registry, tool, effect):
    assert registry.get(tool).side_effect is effect


def test_telegram_destination_self_vs_external(registry):
    spec = registry.get("send_telegram")
    assert spec.destination_of(ToolCall("send_telegram", {"text": "hi"})) is Destination.SELF
    assert spec.destination_of(ToolCall("send_telegram", {"chat_id": OWNER})) is Destination.SELF
    assert spec.destination_of(ToolCall("send_telegram", {"chat_id": 1001})) is Destination.SELF
    assert spec.destination_of(ToolCall("send_telegram", {"chat_id": "666"})) is Destination.EXTERNAL


def test_fetch_url_is_always_external(registry):
    call = ToolCall("fetch_url", {"url": "https://example.com"})
    assert registry.get("fetch_url").destination_of(call) is Destination.EXTERNAL


def test_local_and_readonly_destinations(registry):
    assert registry.get("write_note").destination_of(ToolCall("write_note")) is Destination.SELF
    assert registry.get("read_file").destination_of(ToolCall("read_file")) is None


def test_read_file_output_is_private_trusted(registry):
    _, label = run(registry, "read_file", path="/home/u/tax.pdf")
    assert label == file_label("/home/u/tax.pdf")


def test_tavily_outputs_are_public_untrusted():
    registry = build_default_registry(
        OWNER, handlers={"tavily_search": lambda a, _: [{"url": "https://a.example", "title": "A"}]}
    )
    _, label = run(registry, "tavily_search", query="nemotron")
    assert label.confidentiality is Confidentiality.PUBLIC
    assert label.integrity is Integrity.UNTRUSTED
    assert label.sources == {"web:https://a.example"}

    _, label = run(registry, "tavily_extract", urls=["https://b.example"])
    assert label.integrity is Integrity.UNTRUSTED
    assert label.sources == {"web:https://b.example"}


def test_recall_returns_stored_labels(registry):
    poisoned = Label(Confidentiality.PUBLIC, Integrity.UNTRUSTED, frozenset({"web:https://evil.example"}))
    run(registry, "remember", data_label=poisoned, fact="my bank is evil.example")
    run(registry, "remember", data_label=file_label("/a"), fact="my bank PIN hint")
    facts, label = run(registry, "recall", query="bank")
    assert len(facts) == 2
    assert label.confidentiality is Confidentiality.PRIVATE
    assert label.integrity is Integrity.UNTRUSTED
    assert {f.label for f in facts} == {poisoned, file_label("/a")}


def test_recall_with_no_matches(registry):
    facts, label = run(registry, "recall", query="nothing")
    assert facts == []
    assert label.integrity is Integrity.TRUSTED


def test_side_effect_tools_return_status_labels(registry):
    _, label = run(registry, "send_telegram", data_label=file_label("/a"), text="x")
    assert label == Label(sources=frozenset({"tool:send_telegram"}))


def test_outbound_tool_requires_destination():
    with pytest.raises(ValueError):
        ToolSpec("leak", SideEffect.OUTBOUND, status_label, lambda a, _: None)


def test_unknown_and_duplicate_tools(registry):
    with pytest.raises(UnknownToolError):
        registry.get("rm_rf")
    with pytest.raises(ValueError):
        registry.register(registry.get("read_file"))


def test_no_owner_chat_means_nothing_is_self():
    spec = build_default_registry("").get("send_telegram")
    assert spec.destination_of(ToolCall("send_telegram", {"text": "hi"})) is Destination.EXTERNAL
    assert spec.destination_of(ToolCall("send_telegram", {"chat_id": "", "text": "hi"})) is Destination.EXTERNAL
