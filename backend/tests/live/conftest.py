"""Live tests against Token Factory. Skipped unless NEBIUS_API_KEY is set."""

import json
from dataclasses import replace

import pytest

from tripwire.config import REPO_ROOT, Settings
from tripwire.events import EventBus
from tripwire.models import ModelRouter

REPORT = REPO_ROOT / "data" / "live_report.json"


def pytest_collection_modifyitems(items):
    settings = Settings.from_env()
    if settings.api_key and all(t in settings.models for t in ("nano", "super")):
        return
    skip = pytest.mark.skip(reason="live test: needs NEBIUS_API_KEY and Nemotron model IDs in .env")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def live_settings(tmp_path_factory) -> Settings:
    tmp = tmp_path_factory.mktemp("live")
    return replace(
        Settings.from_env(),
        demo_mode=True,
        files_dir=REPO_ROOT / "demo" / "private",
        data_dir=tmp / "data",
        notes_dir=tmp / "notes",
        fetch_allowlist=("127.0.0.1",),
        telegram_chat_id="1001",
        telegram_bot_token="test-token",
    )


@pytest.fixture(scope="session")
def live_bus() -> EventBus:
    return EventBus(keep=5000)


@pytest.fixture(scope="session")
def live_router(live_settings, live_bus):
    router = ModelRouter(live_settings, live_bus)
    yield router
    summary = router.usage_summary()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, indent=2))
    print("\n\nLIVE USAGE:", summary["headline"])
    for tier, t in summary["tiers"].items():
        if t["calls"]:
            print(f"  {tier:5} calls={t['calls']:3} p50={t['latency_p50_ms']:6.0f}ms p95={t['latency_p95_ms']:6.0f}ms "
                  f"in={t['tokens_in']} out={t['tokens_out']} cost=${t['cost_usd']:.5f}")
