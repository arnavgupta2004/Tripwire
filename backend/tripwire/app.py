"""Assemble a running Tripwire: models, gateway, skills, planner, session."""

from agent.planner import Planner
from skills.registry import build_skills
from tripwire.classifier import NemotronClassifier
from tripwire.config import Settings
from tripwire.events import EventBus
from tripwire.explainer import AsyncExplainer
from tripwire.gateway import Gateway
from tripwire.judge import NemotronJudge
from tripwire.models import ModelRouter
from tripwire.policy.engine import PolicyEngine
from tripwire.policy.user_rules import UserRuleStore
from tripwire.session import Session


def build_session(settings: Settings, *, shield: bool = True, max_steps: int | None = None,
                  explain_blocks: bool = True, guard=None, rules_path=None, **skill_overrides) -> Session:
    bus = EventBus()
    router = ModelRouter(settings, bus, guard=guard)
    skills = build_skills(settings, router, bus, **skill_overrides)
    # Protected: hardened prompt + quarantined reader + gateway. Naive agent: all three off.
    skills.set_quarantine(shield)
    rules_store = UserRuleStore(rules_path) if rules_path is not None else UserRuleStore()
    engine = PolicyEngine.load(rules_store.load())
    judge = NemotronJudge(router)
    explainer = AsyncExplainer(judge, bus) if explain_blocks else None
    gateway = Gateway(skills.registry, engine, NemotronClassifier(router), judge, bus, explainer)
    planner = Planner(router, gateway, settings, shield=shield, max_steps=max_steps)
    return Session(settings, bus, router, gateway, skills, planner, rules_store=rules_store,
                   approval_timeout=settings.approval_timeout)
