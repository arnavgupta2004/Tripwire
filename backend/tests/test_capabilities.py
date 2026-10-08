"""R3 composition rules match tool capabilities, not names."""

import pytest

from tripwire.decision import Decision, Verdict
from tripwire.labels import BOTTOM, CallRecord, file_label, join, user_label, web_label
from tripwire.policy.engine import PolicyEngine, call_facts, policy_file, record_facts
from tripwire.tools import Capability, SideEffect, ToolSpec, build_default_registry, status_label

OK = Decision(Verdict.ALLOW, "test", "test")
FILE = file_label("/vault/secret.txt")
WEB = web_label("https://a.example")


@pytest.fixture(scope="module")
def engine():
    return PolicyEngine.from_yaml()


def ran(tool, caps, output):
    return record_facts(CallRecord("c", tool, {}, "none", None, user_label(), OK, output_label=output,
                                   capabilities=frozenset(caps)))


def test_exfiltration_chain_fires_for_arbitrary_tool_names(engine):
    history = [ran("vault_read", {"reads_private"}, FILE)]
    f = call_facts("webhook_post", "outbound", "external", join(user_label(), FILE), BOTTOM,
                   capabilities=frozenset({"sends_external"}))
    pending = engine.evaluate(f, history)  # v3: classified
    assert pending.rule.id == "R3.exfiltration_chain" and "vault_read → webhook_post" in pending.reason
    d = PolicyEngine.from_yaml(policy_file("strict")).evaluate(f, history)  # strict: blocked outright
    assert (d.verdict, d.rule_id) == (Verdict.BLOCK, "R3.exfiltration_chain")


def test_exfiltration_needs_the_capabilities_not_the_names(engine):
    # Same names as Tripwire's tools, but without the tags: R3 must not fire.
    history = [ran("read_file", set(), FILE)]
    f = call_facts("fetch_url", "outbound", "external", join(user_label(), FILE), BOTTOM)
    assert engine.evaluate(f, history).rule_id != "R3.exfiltration_chain"


def test_sends_external_to_self_is_not_exfiltration(engine):
    history = [ran("vault_read", {"reads_private"}, FILE)]
    f = call_facts("webhook_post", "outbound", "self", join(user_label(), FILE), BOTTOM,
                   capabilities=frozenset({"sends_external"}))
    assert engine.evaluate(f, history).rule_id != "R3.exfiltration_chain"


def test_memory_poisoning_fires_for_arbitrary_tool_names(engine):
    history = [ran("rss_reader", {"fetches_untrusted"}, WEB)]
    f = call_facts("save_preference", "local", "self", join(user_label(), WEB), BOTTOM,
                   capabilities=frozenset({"writes_memory"}))
    d = engine.evaluate(f, history)
    assert (d.verdict, d.rule_id) == (Verdict.ESCALATE, "R3.memory_poisoning")


def test_messaging_a_person_stays_with_r2_not_r3(engine):
    reg = build_default_registry("1001")
    history = [ran("read_file", reg.get("read_file").capabilities, FILE)]
    f = call_facts("send_telegram", "outbound", "external", join(user_label(), FILE), BOTTOM,
                   capabilities=reg.get("send_telegram").capabilities)
    assert engine.evaluate(f, history).rule_id == "R2.private_outbound"


def test_tripwire_tools_are_tagged():
    reg = build_default_registry("1001")
    tags = {name: set(reg.get(name).capabilities) for name in reg.names}
    assert tags["read_file"] == tags["search_files"] == tags["recall"] == {"reads_private"}
    assert tags["tavily_search"] == tags["tavily_extract"] == {"fetches_untrusted"}
    assert tags["fetch_url"] == {"sends_external", "fetches_untrusted"}
    assert tags["remember"] == {"writes_memory"}
    assert tags["send_telegram"] == tags["write_note"] == set()


def test_unknown_capability_rejected():
    with pytest.raises(ValueError, match="unknown capabilities"):
        ToolSpec("x", SideEffect.LOCAL, status_label, lambda a, _: None, capabilities=frozenset({"flies"}))


def test_capability_facts_present_on_calls_and_records():
    f = call_facts("t", "none", None, user_label(), BOTTOM, capabilities=frozenset({Capability.READS_PRIVATE}))
    assert f["cap.reads_private"] == "true" and f["cap.sends_external"] == "false"
    r = ran("t", {"writes_memory"}, BOTTOM)
    assert r["cap.writes_memory"] == "true" and r["cap.fetches_untrusted"] == "false"


def test_rules_yaml_r3_has_no_tool_names():
    import yaml

    from tripwire.policy.engine import DEFAULT_RULES

    rules = yaml.safe_load(DEFAULT_RULES.read_text())["rules"]
    for rule in rules:
        if rule["id"].startswith("R3."):
            assert all("tool" not in step for step in rule["sequence"]), rule["id"]
