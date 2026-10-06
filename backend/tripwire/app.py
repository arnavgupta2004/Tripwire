"""Assemble a running Tripwire: models, gateway, skills, planner."""

from dataclasses import dataclass

from agent.planner import Planner
from skills.registry import Skills, build_skills
from tripwire.classifier import NemotronClassifier
from tripwire.config import Settings
from tripwire.events import EventBus
from tripwire.gateway import Gateway
from tripwire.judge import NemotronJudge
from tripwire.models import ModelRouter
from tripwire.policy.engine import PolicyEngine


@dataclass
class App:
    settings: Settings
    bus: EventBus
    router: ModelRouter
    gateway: Gateway
    skills: Skills
    planner: Planner


def build_app(settings: Settings, *, shield: bool = True, max_steps: int | None = None, **skill_overrides) -> App:
    bus = EventBus()
    router = ModelRouter(settings, bus)
    skills = build_skills(settings, router, bus, **skill_overrides)
    gateway = Gateway(
        skills.registry, PolicyEngine.from_yaml(), NemotronClassifier(router), NemotronJudge(router), bus
    )
    planner = Planner(router, gateway, settings, shield=shield, max_steps=max_steps)
    return App(settings, bus, router, gateway, skills, planner)
