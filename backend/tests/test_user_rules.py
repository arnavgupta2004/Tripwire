import pytest

from tripwire.decision import Verdict
from tripwire.labels import BOTTOM, join, user_label, web_label
from tripwire.policy.engine import PolicyEngine, call_facts
from tripwire.policy.user_rules import UserRuleStore, deny_rule, pattern_id


def facts(tool, side_effect, destination=None, context=None):
    return call_facts(tool, side_effect, destination, context or user_label(), BOTTOM)


def test_deny_rule_shape():
    rule = deny_rule("send_telegram", "external")
    assert rule["id"] == "U.deny_send_telegram_external"
    assert rule["when"] == {"tool": "send_telegram", "destination": "external"}
    assert rule["then"] == "BLOCK"


def test_store_appends_and_dedupes(tmp_path):
    store = UserRuleStore(tmp_path / "user_rules.yaml")
    assert store.load() == []
    assert store.add_deny("send_telegram", "external") is True
    assert store.add_deny("send_telegram", "external") is False  # same pattern
    assert store.add_deny("fetch_url", "external") is True
    ids = {r["id"] for r in store.load()}
    assert ids == {"U.deny_send_telegram_external", "U.deny_fetch_url_external"}


def test_store_persists_across_instances(tmp_path):
    path = tmp_path / "user_rules.yaml"
    UserRuleStore(path).add_deny("write_note", None)
    assert any(r["id"] == pattern_id("write_note", None) for r in UserRuleStore(path).load())


def test_store_remove(tmp_path):
    store = UserRuleStore(tmp_path / "user_rules.yaml")
    store.add_deny("fetch_url", "external")
    assert store.remove("U.deny_fetch_url_external") is True
    assert store.remove("U.deny_fetch_url_external") is False
    assert store.load() == []


def test_engine_loads_user_rules_first():
    # Without a user rule, a public fetch to external is allowed by a default rule.
    plain = PolicyEngine.load()
    assert plain.evaluate(facts("fetch_url", "outbound", "external")).verdict is not Verdict.BLOCK

    engine = PolicyEngine.load([deny_rule("fetch_url", "external")])
    decision = engine.evaluate(facts("fetch_url", "outbound", "external"))
    assert decision.verdict is Verdict.BLOCK
    assert decision.rule_id == "U.deny_fetch_url_external"


def test_user_deny_wins_over_classifier_path():
    # send_telegram under untrusted context would normally go to the classifier (R1);
    # a user deny for that pattern blocks it outright first.
    engine = PolicyEngine.load([deny_rule("send_telegram", "self")])
    ctx = join(user_label(), web_label("https://a.example"))
    decision = engine.evaluate(facts("send_telegram", "outbound", "self", context=ctx))
    assert decision.verdict is Verdict.BLOCK and decision.rule_id == "U.deny_send_telegram_self"


def test_store_roundtrips_through_engine(tmp_path):
    store = UserRuleStore(tmp_path / "user_rules.yaml")
    store.add_deny("send_telegram", "external")
    engine = PolicyEngine.load(store.load())
    assert engine.evaluate(facts("send_telegram", "outbound", "external")).rule_id == "U.deny_send_telegram_external"


def test_bad_user_rule_is_rejected_on_load():
    from tripwire.policy.engine import PolicyError

    with pytest.raises(PolicyError):
        PolicyEngine.load([{"id": "U.bad", "then": "MAYBE", "reason": "x"}])
