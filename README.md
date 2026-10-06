# Tripwire

**A personal AI assistant that can't be turned against you.**

Tripwire researches, reads your files, remembers things and messages you. Every
piece of data it touches carries a provenance label, and a flow firewall between
the agent and its tools blocks prompt-injection attacks before they turn into
side effects.

Built for the Nebius x NVIDIA Global AI Hackathon (Personal AI track). Inference
runs on Nebius Token Factory with three NVIDIA Nemotron 3 tiers (Nano, Super,
Ultra).

> Status: early development. This is a new codebase written during the
> submission period.

## Setup (development)

```bash
uv sync
cp .env.example .env   # then fill in the keys
uv run python scripts/check_models.py
uv run python scripts/check_tavily.py
uv run python scripts/check_telegram.py
```

## Try it

```bash
uv run tripwire chat                    # interactive; prints every gateway decision
uv run tripwire chat --shield off       # naive baseline (DEMO_MODE=true only)
uv run python scripts/serve_demo.py     # local page with a hidden injection
```

Tests: `uv run pytest` (unit, runs in CI) and `uv run pytest -m live -s` (real
Nemotron calls on Token Factory; needs `.env`).

Docs: [models and Token Factory notes](docs/models.md),
[NemoClaw/OpenShell notes](docs/nemoclaw-notes.md).

## License

MIT. See [LICENSE](LICENSE).
