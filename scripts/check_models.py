"""Check Nebius Token Factory access and the three Nemotron 3 tiers.

Lists every model from the OpenAI-compatible /models endpoint, finds the
Nemotron 3 Nano / Super / Ultra IDs, and makes one tiny chat completion to
each, printing latency and token usage. Exits non-zero if any tier is missing
or any call fails.

Usage: uv run python scripts/check_models.py
"""

import os
import re
import sys
import time

from _common import load_env, require
from openai import APIError, AuthenticationError, OpenAI

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
TIERS = ("nano", "super", "ultra")
# "nemotron-3", "nemotron_3", "Nemotron 3", "nemotron3" -- but not "nemotron-30b".
NEMOTRON_3 = re.compile(r"nemotron[-_ ]?3(?!\d)")


def tier_candidates(nemotron_ids: list[str], tier: str) -> list[str]:
    matches = [m for m in nemotron_ids if NEMOTRON_3.search(m.lower()) and tier in m.lower()]
    # Prefer instruct/chat variants over base checkpoints, then shorter IDs.
    return sorted(matches, key=lambda m: ("base" in m.lower(), len(m), m))


def describe(extra: dict) -> str:
    """Price per 1M tokens and features from the verbose model listing."""
    parts = []
    pricing = extra.get("pricing") or {}
    try:
        per_m_in = float(pricing.get("prompt")) * 1e6
        per_m_out = float(pricing.get("completion")) * 1e6
        parts.append(f"${per_m_in:.2f} in / ${per_m_out:.2f} out per 1M")
    except (TypeError, ValueError):
        pass
    if extra.get("supported_features"):
        parts.append("features: " + ", ".join(extra["supported_features"]))
    return f"  ({'; '.join(parts)})" if parts else ""


def ping(client: OpenAI, model: str) -> bool:
    start = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly one word: ok"}],
            max_tokens=128,
            temperature=0,
        )
    except APIError as exc:
        print(f"    FAILED: {exc}")
        return False
    latency_ms = (time.perf_counter() - start) * 1000

    usage = resp.usage
    content = (resp.choices[0].message.content or "").strip()
    reply = content[:60] if content else "(empty -- reasoning may have used up max_tokens)"
    print(f"    latency   {latency_ms:,.0f} ms")
    if usage:
        print(
            f"    tokens    in={usage.prompt_tokens}  out={usage.completion_tokens}"
            f"  total={usage.total_tokens}"
        )
    else:
        print("    tokens    (no usage returned)")
    print(f"    reply     {reply!r}")
    return True


def main() -> int:
    load_env()
    api_key = require("NEBIUS_API_KEY")
    base_url = os.getenv("TOKEN_FACTORY_BASE_URL", "").strip() or DEFAULT_BASE_URL
    client = OpenAI(api_key=api_key, base_url=base_url)

    print(f"Token Factory: {base_url}")
    try:
        listing = list(client.models.list(extra_query={"verbose": "true"}))
        all_ids = sorted(m.id for m in listing)
        details = {m.id: (m.model_extra or {}) for m in listing}
    except AuthenticationError:
        print("error: authentication failed. Check NEBIUS_API_KEY.")
        return 1
    except APIError as exc:
        print(f"error: could not list models: {exc}")
        return 1
    print(f"{len(all_ids)} models available.\n")

    nemotron_ids = [m for m in all_ids if "nemotron" in m.lower()]
    print(f"Nemotron models ({len(nemotron_ids)}):")
    for m in nemotron_ids:
        print(f"  {m}{describe(details.get(m, {}))}")
    print()

    chosen: dict[str, str] = {}
    missing: list[str] = []
    for tier in TIERS:
        env_name = f"NEMOTRON_{tier.upper()}_MODEL"
        override = os.getenv(env_name, "").strip()
        candidates = tier_candidates(nemotron_ids, tier)
        if override:
            if override not in all_ids:
                print(f"warning: {env_name}={override} is not in the /models list")
            chosen[tier] = override
            print(f"{tier:>5}: {override}  (from {env_name})")
        elif candidates:
            chosen[tier] = candidates[0]
            print(f"{tier:>5}: {candidates[0]}")
            if len(candidates) > 1:
                print(f"       {len(candidates)} matches; set {env_name} in .env to pick another:")
                for c in candidates[1:]:
                    print(f"         {c}")
        else:
            missing.append(tier)
            print(f"{tier:>5}: MISSING -- no Nemotron 3 {tier.title()} model found")
    print()

    failed: list[str] = []
    for tier, model in chosen.items():
        print(f"[{tier}] {model}")
        if not ping(client, model):
            failed.append(tier)
        print()

    if missing or failed:
        if missing:
            print(f"FAIL: missing tier(s): {', '.join(missing)}.")
            print("      Check the Nemotron list above, then set NEMOTRON_<TIER>_MODEL in .env.")
        if failed:
            print(f"FAIL: chat completion failed for tier(s): {', '.join(failed)}.")
        return 1

    print("OK: all three Nemotron 3 tiers respond. Add these to .env:")
    for tier, model in chosen.items():
        print(f"  NEMOTRON_{tier.upper()}_MODEL={model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
