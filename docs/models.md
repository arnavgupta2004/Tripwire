# Models: Token Factory + Nemotron 3

How Tripwire calls models, and what the docs say about each capability. Items
marked **(live: pending)** still need confirming against the real endpoint with
`scripts/check_models.py` and the `live` tests.

## Endpoint

- OpenAI-compatible base URL: `https://api.tokenfactory.nebius.com/v1/`, with
  Bearer auth ([quickstart](https://docs.tokenfactory.nebius.com/quickstart),
  [API reference](https://docs.tokenfactory.nebius.com/api-reference)).
- `GET /v1/models?verbose=true` adds `pricing` (`prompt`, `completion`, …) and
  `supported_features` for each model
  ([list models](https://docs.tokenfactory.nebius.com/api-reference/models/list-models)).
  `check_models.py` prints both. Copy prices into `config/pricing.yaml` (USD per
  1M tokens).
- Rate limits start at 60 RPM / 400k TPM and scale up automatically. Over the
  limit you get HTTP 429 with a `Retry-After` header
  ([rate limits](https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits)).
  `ModelRouter` retries 429, 5xx, timeouts and connection errors up to 3 times,
  with exponential backoff plus jitter, and honours `Retry-After` (capped at 30s).
  The SDK's own retries are turned off so every attempt is counted.

## Function calling

- Token Factory supports OpenAI-format `tools`, with `tool_choice` set to
  `"auto"` or a named function. The model returns tool calls but doesn't run them
  ([function calling](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling)).
  The docs don't list which models support it. Check each model's
  `supported_features` in the verbose model list. **(live: pending)**
- Nemotron 3 Nano and Super use the Qwen3-Coder tool-call format in vLLM/SGLang
  (`--tool-call-parser qwen3_coder`)
  ([Nano card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16),
  [Super deployment notes](https://docs.vast.ai/examples/text-generation/nemotron-3-super)).
  Whether Token Factory exposes these as native `tool_calls` is what decides the
  planner mode. **(live: pending)**
- The planner supports both modes (`PLANNER_TOOL_MODE=native|json`). JSON mode
  describes the tools in the prompt and asks for one JSON action per step. The
  planner also switches to JSON mode for the rest of the session if a native
  request is rejected.

## Structured (JSON) output

- `response_format: {"type": "json_schema", ...}` and `{"type": "json_object"}`
  are supported. The docs recommend putting the schema in both the prompt and
  `json_schema`, and say not every model is equally good at it (look for the
  "JSON mode" tag)
  ([structured output](https://docs.tokenfactory.nebius.com/ai-models-inference/json)).
- Tripwire sends `json_schema` with `strict: true` *and* describes the schema in
  the prompt. If the endpoint rejects `response_format` (HTTP 400), the call is
  retried once without it. The reply is then parsed tolerantly: `<think>` blocks
  and code fences are stripped, and the first JSON object is taken. Every caller
  fails closed when parsing fails.

## Reasoning on/off

- All three Nemotron 3 tiers toggle reasoning with a chat-template flag:
  `extra_body={"chat_template_kwargs": {"enable_thinking": true|false}}`.
  Reasoning is on by default.
  - Super also accepts `low_effort: true`, and Nano/Super accept
    `reasoning_budget`
    ([Super notes](https://docs.vast.ai/examples/text-generation/nemotron-3-super),
    [Nano card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16),
    [Ultra card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16)).
- Reasoning text arrives in `message.reasoning_content`, separate from
  `content`. Some deployments leave `<think>…</think>` inline, so the router
  strips that from `content` either way.
- Token Factory's docs have no reasoning page, so whether it forwards
  `chat_template_kwargs` is **(live: pending)**. If it doesn't, Nano calls will
  show reasoning tokens in `tokens_out` and higher latency.
- Tripwire sets the flag on every call:

| Role | Tier | Reasoning | Temperature | Why |
|---|---|---|---|---|
| Intent classifier (ALIGN / LEAK) | Nano | off | 0 | called often; latency matters; deterministic |
| Quarantined reader | Nano | off | 0 | called on every page; extraction, not reasoning |
| Planner | Super | off | 0.6, top_p 0.95 | NVIDIA's tool-calling setting; keeps turns fast |
| Escalation judge | Ultra (Super fallback) | **on** | 1.0, top_p 0.95 | rare; worth the thinking |

NVIDIA recommends temperature 1.0 / top_p 0.95 for Super in general, and
0.6 / 0.95 for Nano tool calling. We use 0 for the classifier and reader because
we want repeatable labels, not creative text.

## Judge fallback

`JUDGE_TIER=ultra|super|nano` (default `ultra`). If Ultra is selected but
`NEMOTRON_ULTRA_MODEL` isn't set, the judge falls back to Super automatically
(`Settings.effective_judge_tier`).

## Cost and usage logging

Every call produces a `ModelCallEvent` with tier, model, purpose, tokens in/out,
latency, attempts, whether reasoning was on, and estimated cost from
`config/pricing.yaml`. A model with no price shows `null` cost. Each event is
published on the EventBus. `ModelRouter.usage_summary()` returns per-tier counts,
tokens, cost and p50/p95 latency, plus a headline like
`This session: 41 Nano, 6 Super, 1 Ultra — $0.0040`.
