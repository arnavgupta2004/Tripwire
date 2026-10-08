import pytest

from tripwire.decision import Decision, Verdict
from tripwire.labels import BOTTOM, CallRecord, file_label, join, user_label, web_label
from tripwire.policy.engine import (
    Classify,
    PolicyEngine,
    PolicyError,
    call_facts,
    policy_file,
    record_facts,
)
from tripwire.tools import build_default_registry

USER = user_label()
WEB = web_label("https://a.example")
FILE = file_label("/home/u/tax.pdf")
OK = Decision(Verdict.ALLOW, "test", "test")


@pytest.fixture(scope="module")
def engine() -> PolicyEngine:
    return PolicyEngine.from_yaml()


@pytest.fixture
def strict() -> PolicyEngine:
    return PolicyEngine.from_yaml(policy_file("strict"))


REGISTRY = build_default_registry("1001")


def caps(tool):
    """Capability tags of Tripwire's real tools (empty for names not in the registry)."""
    return REGISTRY.get(tool).capabilities if tool in REGISTRY else frozenset()


def facts(tool, side_effect, destination=None, context=USER, args=BOTTOM):
    return call_facts(tool, side_effect, destination, context, args, capabilities=caps(tool))


def ran(tool, side_effect, output, destination=None, data=USER):
    rec = CallRecord("c", tool, {}, side_effect, destination, data, OK, output_label=output, capabilities=caps(tool))
    return record_facts(rec)


# --- R4 fast path ------------------------------------------------------------


def test_r4_read_only_with_trusted_context_allows(engine):
    d = engine.evaluate(facts("read_file", "none"))
    assert d.verdict is Verdict.ALLOW and d.rule_id == "R4.read_only_trusted"


def test_r4_does_not_apply_to_untrusted_context(engine):
    d = engine.evaluate(facts("read_file", "none", context=join(USER, WEB)))
    assert d.rule_id != "R4.read_only_trusted"
    assert d.verdict is Verdict.ALLOW  # still a read; caught later if it flows out


def test_r4_does_not_apply_to_side_effects(engine):
    d = engine.evaluate(facts("write_note", "local", "self"))
    assert d.rule_id != "R4.read_only_trusted"


# --- R3 composition ----------------------------------------------------------


def test_r3_read_file_then_fetch_url_is_exfiltration(strict):
    engine = strict
    history = [ran("read_file", "none", FILE)]
    ctx = join(USER, FILE)
    d = engine.evaluate(facts("fetch_url", "outbound", "external", context=ctx), history)
    assert d.verdict is Verdict.BLOCK
    assert d.rule_id == "R3.exfiltration_chain"
    assert "read_file → fetch_url" in d.reason


def test_r3_exfiltration_allows_gaps_between_steps(strict):
    engine = strict
    history = [
        ran("read_file", "none", FILE),
        ran("tavily_search", "none", WEB),
        ran("write_note", "local", BOTTOM, "self"),
    ]
    ctx = join(USER, FILE, WEB)
    d = engine.evaluate(facts("fetch_url", "outbound", "external", context=ctx), history)
    assert d.rule_id == "R3.exfiltration_chain"
    assert "read_file → fetch_url" in d.reason


def test_r3_fetch_url_without_private_read_is_not_exfiltration(engine):
    history = [ran("tavily_search", "none", WEB)]
    d = engine.evaluate(facts("fetch_url", "outbound", "external", context=join(USER, WEB)), history)
    assert isinstance(d, Classify)  # falls through to R1, not R3


def test_r3_order_matters(engine):
    # fetch first, private read after: the pattern is read → fetch, so a past
    # fetch_url doesn't trigger on a later read.
    history = [ran("fetch_url", "outbound", WEB, "external")]
    d = engine.evaluate(facts("read_file", "none"), history)
    assert d.verdict is Verdict.ALLOW


def test_r3_tavily_extract_then_remember_escalates(engine):
    history = [ran("tavily_extract", "none", WEB)]
    d = engine.evaluate(facts("remember", "local", "self", context=join(USER, WEB)), history)
    assert d.verdict is Verdict.ESCALATE
    assert d.rule_id == "R3.memory_poisoning"


def test_r3_remember_without_web_read_is_fine(engine):
    d = engine.evaluate(facts("remember", "local", "self"), [ran("read_file", "none", FILE)])
    assert d.verdict is Verdict.ALLOW
    assert d.rule_id == "R0.trusted_side_effect"


def test_r3_benign_read_file_then_write_note_allows(engine):
    history = [ran("read_file", "none", FILE)]
    d = engine.evaluate(facts("write_note", "local", "self", context=join(USER, FILE)), history)
    assert d.verdict is Verdict.ALLOW


def test_r3_patterns_come_from_yaml():
    engine = PolicyEngine.from_yaml_text(
        """
rules:
  - id: X.note_then_send
    sequence:
      - tool: write_note
      - tool: send_telegram
    then: BLOCK
    reason: "custom chain {chain}"
  - id: X.default
    then: ALLOW
    reason: "fallthrough"
"""
    )
    history = [ran("write_note", "local", BOTTOM, "self")]
    d = engine.evaluate(facts("send_telegram", "outbound", "self"), history)
    assert (d.verdict, d.rule_id, d.reason) == (Verdict.BLOCK, "X.note_then_send", "custom chain write_note → send_telegram")
    assert engine.evaluate(facts("send_telegram", "outbound", "self")).rule_id == "X.default"


# --- R2 private data out -----------------------------------------------------


def test_r2_private_to_external_needs_approval(engine):
    d = engine.evaluate(facts("send_telegram", "outbound", "external", context=join(USER, FILE)))
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert d.rule_id == "R2.private_outbound"


def test_r2_private_via_argument_handle_counts(engine):
    d = engine.evaluate(facts("send_telegram", "outbound", "external", args=FILE))
    assert d.rule_id == "R2.private_outbound"


def test_r2_private_to_self_from_trusted_context_allows(engine):
    d = engine.evaluate(facts("send_telegram", "outbound", "self", context=join(USER, FILE)))
    assert d.verdict is Verdict.ALLOW
    assert d.rule_id == "R0.trusted_side_effect"


def test_r2_private_to_self_with_untrusted_context_escalates(engine):
    d = engine.evaluate(facts("send_telegram", "outbound", "self", context=join(USER, FILE, WEB)))
    assert d.verdict is Verdict.ESCALATE
    assert d.rule_id == "R2.private_outbound_untrusted"


def test_r2_private_to_external_with_untrusted_context_escalates(engine):
    d = engine.evaluate(facts("send_telegram", "outbound", "external", context=join(USER, FILE, WEB)))
    assert d.verdict is Verdict.ESCALATE
    assert d.rule_id == "R2.private_outbound_untrusted"


def test_r2_trusted_context_is_plain_approval_not_escalation(engine):
    d = engine.evaluate(facts("send_telegram", "outbound", "external", context=join(USER, FILE)))
    assert (d.verdict, d.rule_id) == (Verdict.NEEDS_APPROVAL, "R2.private_outbound")


# --- R5 query egress ---------------------------------------------------------


@pytest.mark.parametrize("tool", ["tavily_search", "tavily_extract"])
def test_r5_search_with_private_context_goes_to_leak_check(engine, tool):
    pending = engine.evaluate(call_facts(tool, "none", None, join(USER, FILE), BOTTOM, egress=True))
    assert isinstance(pending, Classify)
    assert pending.rule.id == "R5.query_egress"
    assert pending.rule.classifier == ("leak",)


def test_r5_no_leak_allows_and_leak_needs_approval(engine):
    f = call_facts("tavily_search", "none", None, join(USER, FILE), BOTTOM, egress=True)
    pending = engine.evaluate(f)
    assert engine.resolve(pending, f, {"leaking": False}).verdict is Verdict.ALLOW
    leak = engine.resolve(pending, f, {"leaking": True})
    assert (leak.verdict, leak.rule_id) == (Verdict.NEEDS_APPROVAL, "R5.query_egress")


def test_r5_not_triggered_without_private_data(engine):
    d = engine.evaluate(call_facts("tavily_search", "none", None, USER, BOTTOM, egress=True))
    assert d.rule_id == "R4.read_only_trusted"


def test_r5_not_triggered_for_non_egress_reads(engine):
    d = engine.evaluate(facts("read_file", "none", context=join(USER, FILE)))
    assert d.rule_id == "R4.read_only_trusted"


def test_r3_still_wins_over_r5_for_fetch_after_private_read(engine):
    history = [ran("read_file", "none", FILE)]
    f = call_facts("fetch_url", "outbound", "external", join(USER, FILE), BOTTOM, egress=True,
                   capabilities=caps("fetch_url"))
    pending = engine.evaluate(f, history)
    assert isinstance(pending, Classify) and pending.rule.id == "R3.exfiltration_chain"


# --- R3 v3: classified, not a blanket block ------------------------------------


def _fetch_after_private_read(engine):
    history = [ran("read_file", "none", FILE)]
    f = facts("fetch_url", "outbound", "external", context=join(USER, FILE))
    return f, engine.evaluate(f, history)


def test_v3_r3_runs_both_checks(engine):
    _, pending = _fetch_after_private_read(engine)
    assert isinstance(pending, Classify)
    assert pending.rule.id == "R3.exfiltration_chain" and pending.rule.classifier == ("align", "leak")


@pytest.mark.parametrize("aligned, leaking, verdict", [
    (True, False, Verdict.ALLOW),            # the user asked, nothing private goes out
    (True, True, Verdict.NEEDS_APPROVAL),    # the user asked, but private data would go out
    (False, False, Verdict.ESCALATE),        # not asked for: the judge decides
    (False, True, Verdict.BLOCK),            # not asked for and carries private data
])
def test_v3_r3_outcomes(engine, aligned, leaking, verdict):
    f, pending = _fetch_after_private_read(engine)
    d = engine.resolve(pending, f, {"aligned": aligned, "leaking": leaking})
    assert (d.verdict, d.rule_id) == (verdict, "R3.exfiltration_chain")


def test_strict_profile_keeps_the_v2_hard_block(strict, engine):
    _, d = _fetch_after_private_read(strict)
    assert (d.verdict, d.rule_id) == (Verdict.BLOCK, "R3.exfiltration_chain")
    assert (strict.version, engine.version) == ("2", "3")
    assert [r.id for r in strict.rules if r.id != "R3.exfiltration_chain"] == \
        [r.id for r in engine.rules if r.id != "R3.exfiltration_chain"]  # only R3 differs


def test_outcome_needs_its_check():
    with pytest.raises(PolicyError, match="leak check"):
        PolicyEngine.from_yaml_text("""
rules:
  - id: X
    then: CLASSIFY
    reason: r
    outcomes:
      - when: {leaking: true}
        then: BLOCK
        reason: r
""")


def test_unknown_profile_is_rejected():
    with pytest.raises(PolicyError):
        policy_file("lenient")


def test_r2_public_outbound_is_not_r2(engine):
    d = engine.evaluate(facts("send_telegram", "outbound", "external"))
    assert d.rule_id != "R2.private_outbound"


def test_r2_private_local_write_is_not_r2(engine):
    d = engine.evaluate(facts("write_note", "local", "self", context=join(USER, FILE)))
    assert d.rule_id != "R2.private_outbound"


# --- R1 untrusted influence --------------------------------------------------


def classify(engine, f):
    pending = engine.evaluate(f)
    assert isinstance(pending, Classify), pending
    assert pending.rule.id == "R1.untrusted_side_effect"
    return pending


def test_r1_side_effect_with_untrusted_context_goes_to_classifier(engine):
    classify(engine, facts("send_telegram", "outbound", "self", context=join(USER, WEB)))
    classify(engine, facts("write_note", "local", "self", context=join(USER, WEB)))


def test_r1_not_triggered_by_trusted_context(engine):
    d = engine.evaluate(facts("send_telegram", "outbound", "self"))
    assert isinstance(d, Decision) and d.verdict is Verdict.ALLOW


def test_r1_not_triggered_by_reads(engine):
    d = engine.evaluate(facts("tavily_extract", "none", context=join(USER, WEB)))
    assert isinstance(d, Decision)


def test_r1_aligned_public_self_allows(engine):
    f = facts("send_telegram", "outbound", "self", context=join(USER, WEB))
    d = engine.resolve(classify(engine, f), f, {"aligned": True})
    assert d.verdict is Verdict.ALLOW and d.rule_id == "R1.untrusted_side_effect"


def test_r1_aligned_private_needs_approval(engine):
    # A local write of private data under untrusted context (R2 only covers outbound).
    f = facts("write_note", "local", "self", context=join(USER, WEB, FILE))
    d = engine.resolve(classify(engine, f), f, {"aligned": True})
    assert d.verdict is Verdict.NEEDS_APPROVAL


def test_r1_aligned_external_needs_approval(engine):
    f = facts("fetch_url", "outbound", "external", context=join(USER, WEB))
    d = engine.resolve(classify(engine, f), f, {"aligned": True})
    assert d.verdict is Verdict.NEEDS_APPROVAL


def test_r1_misaligned_escalates(engine):
    f = facts("send_telegram", "outbound", "self", context=join(USER, WEB))
    d = engine.resolve(classify(engine, f), f, {"aligned": False})
    assert d.verdict is Verdict.ESCALATE


# --- engine behaviour --------------------------------------------------------


def test_no_match_fails_closed():
    engine = PolicyEngine.from_yaml_text(
        "rules:\n  - id: only\n    when: {tool: read_file}\n    then: ALLOW\n    reason: r\n"
    )
    d = engine.evaluate(facts("fetch_url", "outbound", "external"))
    assert d.verdict is Verdict.BLOCK and d.rule_id == "R0.no_match"


def test_unmatched_outcome_escalates():
    engine = PolicyEngine.from_yaml_text(
        """
rules:
  - id: C
    then: CLASSIFY
    reason: r
    outcomes:
      - when: {aligned: true}
        then: ALLOW
        reason: ok
"""
    )
    f = facts("write_note", "local", "self")
    d = engine.resolve(engine.evaluate(f), f, {"aligned": False})
    assert d.verdict is Verdict.ESCALATE


@pytest.mark.parametrize(
    "text,message",
    [
        ("rules: []", "non-empty"),
        ("rules:\n  - then: ALLOW\n    reason: r", "without an id"),
        ("rules:\n  - id: a\n    then: MAYBE\n    reason: r", "'then' must be"),
        ("rules:\n  - id: a\n    then: ALLOW", "reason"),
        ("rules:\n  - id: a\n    when: {colour: red}\n    then: ALLOW\n    reason: r", "unknown condition"),
        ("rules:\n  - id: a\n    then: CLASSIFY\n    reason: r", "need outcomes"),
        (
            "rules:\n  - id: a\n    then: CLASSIFY\n    classifier: vibes\n    reason: r\n    outcomes: [{when: {aligned: true}, then: ALLOW, reason: r}]",
            "classifier",
        ),
        ("rules:\n  - id: a\n    sequence: [{tool: x}]\n    then: BLOCK\n    reason: r", "two steps"),
        (
            "rules:\n  - id: a\n    sequence: [{tool: x}, {output.integrity: untrusted}]\n    then: BLOCK\n    reason: r",
            "unknown condition",
        ),
        ("rules:\n  - {id: a, then: ALLOW, reason: r}\n  - {id: a, then: BLOCK, reason: r}", "unique"),
    ],
)
def test_invalid_policies_are_rejected(text, message):
    with pytest.raises(PolicyError, match=message):
        PolicyEngine.from_yaml_text(text)


def test_default_rules_cover_every_tool_shape(engine):
    """Every combination of the inputs gets a decision with a rule and a reason."""
    contexts = [USER, join(USER, WEB), join(USER, FILE), join(USER, WEB, FILE)]
    shapes = [("read_file", "none", None), ("write_note", "local", "self"),
              ("send_telegram", "outbound", "self"), ("fetch_url", "outbound", "external")]
    for ctx in contexts:
        for tool, effect, dest in shapes:
            result = engine.evaluate(facts(tool, effect, dest, context=ctx))
            if isinstance(result, Classify):
                assert result.reason
                for aligned in (True, False):
                    d = engine.resolve(result, facts(tool, effect, dest, context=ctx), {"aligned": aligned, "leaking": aligned})
                    assert d.rule_id and d.reason
            else:
                assert result.rule_id != "R0.no_match", (tool, ctx)
                assert result.reason and "{" not in result.reason

