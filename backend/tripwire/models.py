"""Token Factory client: tier routing, retries, structured output, usage logging.

Every model call goes through ModelRouter.chat(), which records tier, model,
tokens, latency and estimated cost, and publishes a ModelCallEvent.
"""

import json
import logging
import random
import re
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from tripwire.config import TIERS, Settings
from tripwire.events import EventBus

log = logging.getLogger(__name__)

RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)
DEFAULT_TIMEOUTS = {"nano": 30.0, "super": 90.0, "ultra": 180.0}
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class ModelError(RuntimeError):
    """A model call failed after retries, or the tier isn't configured."""


@dataclass(frozen=True)
class ModelCallEvent:
    tier: str
    model: str
    purpose: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd: float | None
    ok: bool
    attempts: int
    reasoning: bool
    error: str | None = None
    kind: str = "model_call"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: list[Any]
    reasoning: str | None
    record: ModelCallEvent
    message: Any  # the raw SDK message, for appending to a conversation


class Pricing:
    """USD per 1M tokens, keyed by model id (config/pricing.yaml)."""

    def __init__(self, prices: Mapping[str, Mapping[str, float]] | None = None) -> None:
        self.prices = {k: dict(v) for k, v in (prices or {}).items()}

    @classmethod
    def from_file(cls, path: Path) -> "Pricing":
        if not path.exists():
            return cls()
        doc = yaml.safe_load(path.read_text()) or {}
        return cls(doc.get("models") or {})

    def cost(self, model: str, tokens_in: int, tokens_out: int) -> float | None:
        p = self.prices.get(model)
        if not p:
            return None
        return (tokens_in * p.get("input_per_m", 0.0) + tokens_out * p.get("output_per_m", 0.0)) / 1_000_000


def strip_reasoning(text: str | None) -> str:
    """Drop <think> blocks some deployments leave inline in content."""
    return THINK_BLOCK.sub("", text or "").strip()


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort: the first JSON object in a model reply (tolerates code fences)."""
    text = strip_reasoning(text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : i + 1])
                        return value if isinstance(value, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


class ModelRouter:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus | None = None,
        client: Any | None = None,
        pricing: Pricing | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.bus = bus or EventBus()
        # The SDK's own retries are off so every attempt is counted and logged here.
        self.client = client or OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=0)
        self.pricing = pricing or Pricing.from_file(settings.pricing_file)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.sleep = sleep
        self.records: list[ModelCallEvent] = []

    def model_for(self, tier: str) -> str:
        model = self.settings.models.get(tier)
        if not model:
            raise ModelError(f"no model configured for tier {tier!r}; set NEMOTRON_{tier.upper()}_MODEL")
        return model

    @property
    def judge_tier(self) -> str:
        return self.settings.effective_judge_tier

    def chat(
        self,
        tier: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        purpose: str,
        reasoning: bool = False,
        tools: list[dict[str, Any]] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int = 1024,
        timeout: float | None = None,
    ) -> ChatResult:
        model = self.model_for(tier)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "timeout": timeout or DEFAULT_TIMEOUTS.get(tier, 60.0),
            # Nemotron 3 reasoning switch (chat template flag).
            "extra_body": {"chat_template_kwargs": {"enable_thinking": reasoning}},
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": purpose.replace(".", "_"), "schema": json_schema, "strict": True},
            }

        start = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except RETRYABLE as exc:
                if attempts > self.max_retries:
                    self._record(tier, model, purpose, None, start, attempts, reasoning, exc)
                    raise ModelError(f"{tier} call failed after {attempts} attempts: {exc}") from exc
                self.sleep(self._backoff(attempts, exc))
            except APIStatusError as exc:
                self._record(tier, model, purpose, None, start, attempts, reasoning, exc)
                raise ModelError(f"{tier} call rejected: {exc}") from exc

        record = self._record(tier, model, purpose, resp, start, attempts, reasoning)
        message = resp.choices[0].message
        # Token Factory returns reasoning as `reasoning_content` (Super, Ultra) or `reasoning` (Nano).
        extra = getattr(message, "model_extra", None) or {}
        reasoning_text = (
            getattr(message, "reasoning_content", None) or extra.get("reasoning_content") or extra.get("reasoning")
        )
        return ChatResult(
            content=strip_reasoning(message.content),
            tool_calls=list(message.tool_calls or []),
            reasoning=reasoning_text,
            record=record,
            message=message,
        )

    def chat_json(
        self,
        tier: str,
        messages: Sequence[Mapping[str, Any]],
        schema: dict[str, Any],
        *,
        purpose: str,
        **kwargs: Any,
    ) -> tuple[dict[str, Any] | None, ChatResult]:
        """Structured output. Returns (None, result) if the reply isn't a JSON object.

        Callers also describe the schema in the prompt (Token Factory's advice), so
        if the endpoint rejects `response_format` we retry once without it.
        """
        try:
            result = self.chat(tier, messages, purpose=purpose, json_schema=schema, **kwargs)
        except ModelError as exc:
            if not isinstance(exc.__cause__, BadRequestError):
                raise
            log.warning("%s: response_format rejected, retrying without it: %s", purpose, exc)
            result = self.chat(tier, messages, purpose=purpose, **kwargs)
        return parse_json_object(result.content), result

    def _backoff(self, attempt: int, exc: Exception) -> float:
        retry_after = None
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                retry_after = float(response.headers.get("retry-after", ""))
            except (TypeError, ValueError):
                retry_after = None
        if retry_after is not None:
            return min(retry_after, 30.0)
        return self.backoff_base * (2 ** (attempt - 1)) + random.uniform(0, self.backoff_base)

    def _record(
        self,
        tier: str,
        model: str,
        purpose: str,
        resp: Any,
        start: float,
        attempts: int,
        reasoning: bool,
        error: Exception | None = None,
    ) -> ModelCallEvent:
        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0
        record = ModelCallEvent(
            tier=tier,
            model=model,
            purpose=purpose,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=(time.perf_counter() - start) * 1000,
            cost_usd=self.pricing.cost(model, tokens_in, tokens_out),
            ok=error is None,
            attempts=attempts,
            reasoning=reasoning,
            error=None if error is None else f"{type(error).__name__}: {error}",
        )
        self.records.append(record)
        self.bus.publish(record)
        return record

    def usage_summary(self) -> dict[str, Any]:
        return summarize_usage(self.records)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(pct) - 1]


def summarize_usage(records: Sequence[ModelCallEvent]) -> dict[str, Any]:
    tiers: dict[str, Any] = {}
    for tier in TIERS:
        rs = [r for r in records if r.tier == tier]
        latencies = [r.latency_ms for r in rs if r.ok]
        priced = [r.cost_usd for r in rs if r.cost_usd is not None]
        tiers[tier] = {
            "calls": len(rs),
            "failed": sum(not r.ok for r in rs),
            "tokens_in": sum(r.tokens_in for r in rs),
            "tokens_out": sum(r.tokens_out for r in rs),
            "cost_usd": sum(priced),
            "unpriced_calls": len(rs) - len(priced),
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
        }
    total_cost = sum(t["cost_usd"] for t in tiers.values())
    unpriced = sum(t["unpriced_calls"] for t in tiers.values())
    counts = ", ".join(f"{tiers[t]['calls']} {t.title()}" for t in TIERS)
    cost = f"${total_cost:.4f}" + (" + unpriced calls" if unpriced else "")
    return {
        "tiers": tiers,
        "total_calls": len(records),
        "total_cost_usd": total_cost,
        "headline": f"This session: {counts} — {cost}",
    }
