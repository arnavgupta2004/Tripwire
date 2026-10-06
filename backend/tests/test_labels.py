import pytest
from hypothesis import given
from hypothesis import strategies as st

from tripwire.decision import Decision, Verdict
from tripwire.labels import (
    BOTTOM,
    CallRecord,
    Confidentiality,
    Integrity,
    Label,
    Labeled,
    TurnContext,
    file_label,
    join,
    user_label,
    web_label,
)

labels = st.builds(
    Label,
    confidentiality=st.sampled_from(Confidentiality),
    integrity=st.sampled_from(Integrity),
    sources=st.frozensets(st.sampled_from(["user", "file:a", "web:b", "memory:c", "web:d"])),
)


@given(labels, labels, labels)
def test_join_is_associative(a, b, c):
    assert join(join(a, b), c) == join(a, join(b, c))


@given(labels, labels)
def test_join_is_commutative(a, b):
    assert join(a, b) == join(b, a)


@given(labels)
def test_join_is_idempotent(a):
    assert join(a, a) == a


@given(labels)
def test_bottom_is_identity(a):
    assert join(a, BOTTOM) == a
    assert join() == BOTTOM


@given(labels, labels)
def test_join_is_an_upper_bound(a, b):
    j = a | b
    assert j.confidentiality >= max(a.confidentiality, b.confidentiality)
    assert j.integrity <= min(a.integrity, b.integrity)
    assert j.sources >= a.sources | b.sources


def test_join_takes_most_secret_and_least_trusted():
    j = join(file_label("/tax.pdf"), web_label("https://evil.example"))
    assert j.confidentiality is Confidentiality.PRIVATE
    assert j.integrity is Integrity.UNTRUSTED
    assert j.sources == {"file:/tax.pdf", "web:https://evil.example"}


def test_ordering_matches_lattice():
    assert Confidentiality.PUBLIC < Confidentiality.PRIVATE
    assert Integrity.UNTRUSTED < Integrity.TRUSTED


def test_label_to_dict():
    assert file_label("/a").to_dict() == {
        "confidentiality": "private",
        "integrity": "trusted",
        "sources": ["file:/a"],
    }


def test_labeled_handles_are_stable_and_unique():
    a = Labeled("x", user_label())
    b = Labeled("x", user_label())
    assert a.id == a.id and a.id.startswith("h_")
    assert a.id != b.id


def test_labeled_is_immutable():
    a = Labeled("x", user_label())
    with pytest.raises(AttributeError):
        a.value = "y"  # type: ignore[misc]


def test_turn_context_starts_trusted_from_user():
    ctx = TurnContext("research X")
    assert ctx.label == user_label()
    assert ctx.lookup(ctx.instruction.id) is ctx.instruction


def test_turn_context_observe_joins_labels():
    ctx = TurnContext("research X")
    page = Labeled("page text", web_label("https://a.example"))
    ctx.observe(page)
    assert ctx.label.integrity is Integrity.UNTRUSTED
    assert "web:https://a.example" in ctx.label.sources
    assert ctx.lookup(page.id) is page
    # Observing a trusted value afterwards never restores trust.
    ctx.observe(Labeled("more", user_label()))
    assert ctx.label.integrity is Integrity.UNTRUSTED


def test_turn_context_history_and_executed():
    ctx = TurnContext("x")
    allow = Decision(Verdict.ALLOW, "R4", "read-only")
    block = Decision(Verdict.BLOCK, "R3", "exfil")
    ran = CallRecord("c1", "read_file", {}, "none", None, BOTTOM, allow, output_label=BOTTOM)
    stopped = CallRecord("c2", "fetch_url", {}, "outbound", "external", BOTTOM, block)
    ctx.record(ran)
    ctx.record(stopped)
    assert ctx.history == [ran, stopped]
    assert ctx.executed == [ran]


def test_decision_requires_rule_and_reason():
    with pytest.raises(ValueError):
        Decision(Verdict.ALLOW, "", "reason")
    with pytest.raises(ValueError):
        Decision(Verdict.ALLOW, "R4", "  ")
    d = Decision(Verdict.BLOCK, "R3", "exfil")
    assert d.policy_verdict is Verdict.BLOCK
