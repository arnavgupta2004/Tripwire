import pytest

from tripwire.config import Settings
from tripwire.events import EventBus
from tripwire.models import ModelRouter, Pricing

MODELS = {"nano": "nvidia/nano-test", "super": "nvidia/super-test", "ultra": "nvidia/ultra-test"}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        api_key="test",
        models=dict(MODELS),
        files_dir=tmp_path / "files",
        notes_dir=tmp_path / "notes",
        data_dir=tmp_path / "data",
        pricing_file=tmp_path / "pricing.yaml",
    )


@pytest.fixture
def make_router(settings):
    def make(client, **kwargs) -> ModelRouter:
        pricing = kwargs.pop("pricing", Pricing({MODELS["nano"]: {"input_per_m": 0.1, "output_per_m": 0.4}}))
        return ModelRouter(
            kwargs.pop("settings", settings), kwargs.pop("bus", EventBus()), client=client,
            pricing=pricing, sleep=lambda s: None, **kwargs,
        )
    return make
