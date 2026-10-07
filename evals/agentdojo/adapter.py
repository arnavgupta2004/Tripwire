"""Tripwire as an AgentDojo defense.

AgentDojo runs an LLM in a loop with a ToolsExecutor that executes tool calls.
Tripwire replaces that executor: every call goes through Tripwire's gateway
(labels, the unchanged policy in rules.yaml, the Nano classifier and the judge)
before it runs, using the per-tool facts declared in mapping.yaml.

Conditions, all on the same LLM element (Nemotron Super) and system message:
  none            AgentDojo's plain ToolsExecutor
  spotlighting    AgentDojo's built-in spotlighting_with_delimiting defense
  tripwire_gw     Tripwire gateway only
  tripwire_full   Tripwire gateway + quarantined reader on untrusted outputs
"""

import json
import re
import sys
import time
from ast import literal_eval
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from agentdojo.agent_pipeline import AgentPipeline, InitQuery, PipelineConfig, SystemMessage, ToolsExecutionLoop  # noqa: E402
from agentdojo.agent_pipeline.agent_pipeline import load_system_message  # noqa: E402
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement  # noqa: E402
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import ToolsExecutor, tool_result_to_str  # noqa: E402
from agentdojo.models import MODEL_NAMES  # noqa: E402
from agentdojo.types import ChatToolResultMessage, text_content_block_from_string  # noqa: E402
from openai import OpenAI  # noqa: E402

from tripwire.classifier import NemotronClassifier  # noqa: E402
from tripwire.config import Settings  # noqa: E402
from tripwire.decision import Verdict  # noqa: E402
from tripwire.events import EventBus  # noqa: E402
from tripwire.gateway import Gateway  # noqa: E402
from tripwire.judge import NemotronJudge  # noqa: E402
from tripwire.labels import Confidentiality, Integrity, Label, TurnContext  # noqa: E402
from tripwire.models import ModelRouter  # noqa: E402
from tripwire.policy.engine import PolicyEngine  # noqa: E402
from tripwire.reader import QuarantinedReader  # noqa: E402
from tripwire.tools import Destination, SideEffect, ToolCall, ToolRegistry, ToolSpec, status_label  # noqa: E402

MAPPING_PATH = Path(__file__).with_name("mapping.yaml")
PIPELINE_NAME = "nemotron-3-super"
CONDITIONS = ("none", "spotlighting", "tripwire_gw", "tripwire_full")

# important_instructions addresses the target model by name; AgentDojo has no
# entry for Nemotron. Registering one keeps the published template unchanged.
MODEL_NAMES.setdefault(PIPELINE_NAME, "Nemotron")

READER_SCHEMAS: dict[str, dict[str, Any]] = {
    "messages": {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"sender": {"type": "string"}, "recipient": {"type": "string"},
                                   "summary": {"type": "string"}},
                },
            },
            "links": {"type": "array", "items": {"type": "string"}},
        },
    },
    "page": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "key_facts": {"type": "array", "items": {"type": "string"}},
            "links": {"type": "array", "items": {"type": "string"}},
        },
    },
    "records": {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "sender": {"type": "string"},
                                   "recipient": {"type": "string"}, "amount": {"type": "number"},
                                   "date": {"type": "string"}, "subject_summary": {"type": "string"},
                                   "recurring": {"type": "boolean"}},
                },
            },
        },
    },
}


# --- Token Factory client used by every condition ------------------------------


@dataclass
class Usage:
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0


class TokenFactoryClient:
    """Wraps the OpenAI client for AgentDojo's OpenAILLM, identically for every condition:
    - maps the `developer` role to `system` (Token Factory rejects `developer`),
    - turns Nemotron reasoning off (same setting as Tripwire's planner),
    - records token usage for cost accounting."""

    def __init__(self, settings: Settings) -> None:
        self._inner = OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=4)
        self.usage = Usage()
        outer = self

        class _Completions:
            def create(self, **kw):
                kw["messages"] = [{**m, "role": "system"} if m.get("role") == "developer" else m
                                  for m in kw["messages"]]
                kw.setdefault("extra_body", {})["chat_template_kwargs"] = {"enable_thinking": False}
                start = time.perf_counter()
                resp = outer._inner.chat.completions.create(**kw)
                outer.usage.calls += 1
                outer.usage.seconds += time.perf_counter() - start
                if resp.usage:
                    outer.usage.tokens_in += resp.usage.prompt_tokens
                    outer.usage.tokens_out += resp.usage.completion_tokens
                return resp

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# --- mapping -----------------------------------------------------------------


def load_mapping(path: Path = MAPPING_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def check_mapping(mapping: dict[str, Any], suite_name: str, tool_names: Sequence[str]) -> None:
    mapped = set(mapping["suites"][suite_name]["tools"])
    missing, extra = set(tool_names) - mapped, mapped - set(tool_names)
    if missing or extra:
        raise ValueError(f"{suite_name} mapping mismatch: missing={sorted(missing)} extra={sorted(extra)}")


def _fmt(template: str, args: dict[str, Any]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(args.get(m.group(1), "?")), template)


def _output_labeler(spec: Any):
    if spec == "status":
        return status_label

    def label(call: ToolCall, result: Any, data_label: Label) -> Label:
        return Label(
            Confidentiality[spec["confidentiality"].upper()],
            Integrity[spec["integrity"].upper()],
            frozenset({_fmt(spec["source"], dict(call.args))}),
        )

    return label


@dataclass
class TaskTrace:
    decisions: list[dict[str, Any]] = field(default_factory=list)
    held: int = 0
    blocked: int = 0
    reader_calls: int = 0


class TripwireExecutor(BasePipelineElement):
    """Drop-in replacement for AgentDojo's ToolsExecutor that gates every call."""

    name = "tripwire"

    def __init__(self, suite_name: str, mapping: dict[str, Any], router: ModelRouter, *,
                 use_reader: bool, trust_mode: str = "team", classifier: Any = None, judge: Any = None) -> None:
        assert trust_mode in ("team", "strict")
        self.suite_name = suite_name
        self.tools = mapping["suites"][suite_name]["tools"]
        self.trust_mode = trust_mode
        self.router = router
        self.reader = QuarantinedReader(router) if use_reader else None
        self.trace = TaskTrace()
        self._runtime: Any = None
        self._env: Any = None
        self.bus = EventBus(keep=2000)
        self.gateway = Gateway(self._registry(), PolicyEngine.load(), classifier or NemotronClassifier(router),
                               judge or NemotronJudge(router), self.bus)

    # destinations are resolved against the live environment
    def _destination(self, rule: Any, call: ToolCall) -> Destination:
        if isinstance(rule, dict):
            rule = rule[self.trust_mode]
        if rule == "self":
            return Destination.SELF
        if rule == "external":
            return Destination.EXTERNAL
        if rule == "by_mode":
            return Destination.SELF if self.trust_mode == "team" else Destination.EXTERNAL
        m = re.fullmatch(r"(workspace_member|own_account)\((\w+)\)", rule)
        if not m:
            raise ValueError(f"unknown destination rule {rule!r}")
        kind, arg = m.groups()
        value = str(call.args.get(arg, ""))
        if kind == "workspace_member":
            return Destination.SELF if value in list(self._env.slack.users) else Destination.EXTERNAL
        return Destination.SELF if value == str(self._env.bank_account.iban) else Destination.EXTERNAL

    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        for name, spec in self.tools.items():
            side = SideEffect(spec["side_effect"])
            dest_rule = spec.get("destination")
            registry.register(ToolSpec(
                name, side, _output_labeler(spec["output"]), self._handler(name),
                destination=(lambda call, r=dest_rule: self._destination(r, call)) if side is SideEffect.OUTBOUND else None,
                egress=bool(spec.get("egress", False)),
                capabilities=frozenset(spec.get("capabilities", [])),
            ))
        return registry

    def _handler(self, name: str):
        def run(args: dict[str, Any], data_label: Label) -> Any:
            result, error = self._runtime.run_function(self._env, name, dict(args))
            return {"__result__": result, "__error__": error}
        return run

    def _render(self, name: str, raw: dict[str, Any]) -> tuple[str, str | None]:
        result, error = raw["__result__"], raw["__error__"]
        text = tool_result_to_str(result) if result is not None else ""
        schema_name = self.tools[name].get("reader_schema")
        if self.reader is not None and schema_name and not error and text:
            self.trace.reader_calls += 1
            read = self.reader.read(text, READER_SCHEMAS[schema_name], source=name)
            text = json.dumps(read.to_dict(), ensure_ascii=False)
        return text, error

    def query(self, query, runtime, env, messages=(), extra_args={}):
        if not messages or messages[-1]["role"] != "assistant" or not messages[-1]["tool_calls"]:
            return query, runtime, env, messages, extra_args
        self._runtime, self._env = runtime, env
        ctx: TurnContext = extra_args.get("tripwire_ctx") or TurnContext(query)
        results = []
        for tc in messages[-1]["tool_calls"]:
            args = {k: (literal_eval(v) if isinstance(v, str) and v.startswith("[") and _is_list(v) else v)
                    for k, v in tc.args.items()}
            if tc.function not in self.tools:
                results.append(_tool_msg(tc, "", f"Invalid tool {tc.function} provided."))
                continue
            outcome = self.gateway.call(ToolCall(tc.function, args), ctx)
            d = outcome.decision
            self.trace.decisions.append({"tool": tc.function, "verdict": str(d.verdict), "rule": d.rule_id,
                                         "models": list(d.models)})
            if d.verdict is Verdict.ALLOW:
                text, error = self._render(tc.function, outcome.output.value)
                results.append(_tool_msg(tc, text, error))
            elif d.verdict is Verdict.NEEDS_APPROVAL:
                self.trace.held += 1
                results.append(_tool_msg(tc, "", f"Held by Tripwire for the user's approval and not executed: "
                                                 f"{d.explanation or d.reason}"))
            else:
                self.trace.blocked += 1
                results.append(_tool_msg(tc, "", f"Blocked by Tripwire: {d.explanation or d.reason}"))
        return query, runtime, env, [*messages, *results], {**extra_args, "tripwire_ctx": ctx}


def _is_list(s: str) -> bool:
    try:
        return isinstance(literal_eval(s), list)
    except (ValueError, SyntaxError):
        return False


def _tool_msg(tc: Any, text: str, error: str | None) -> ChatToolResultMessage:
    return ChatToolResultMessage(role="tool", content=[text_content_block_from_string(text)],
                                 tool_call_id=tc.id, tool_call=tc, error=error)


# --- pipelines ---------------------------------------------------------------


@dataclass
class Built:
    pipeline: AgentPipeline
    client: TokenFactoryClient
    executor: TripwireExecutor | None
    router: ModelRouter | None


def build_pipeline(condition: str, suite_name: str, settings: Settings, mapping: dict[str, Any],
                   trust_mode: str = "team") -> Built:
    """A fresh pipeline per task, so no state leaks between tasks."""
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}")
    client = TokenFactoryClient(settings)
    llm = OpenAILLM(client, settings.models["super"], temperature=0.0)
    llm.name = PIPELINE_NAME
    system = load_system_message(None)  # AgentDojo's default system message, for every condition

    if condition == "none":
        pipe = AgentPipeline([SystemMessage(system), InitQuery(), llm, ToolsExecutionLoop([ToolsExecutor(), llm])])
        pipe.name = PIPELINE_NAME
        return Built(pipe, client, None, None)
    if condition == "spotlighting":
        pipe = AgentPipeline.from_config(PipelineConfig(
            llm=llm, model_id=None, defense="spotlighting_with_delimiting", system_message_name=None,
            system_message=system, tool_output_format=None))
        pipe.name = PIPELINE_NAME
        return Built(pipe, client, None, None)

    router = ModelRouter(settings, EventBus(keep=2000))
    executor = TripwireExecutor(suite_name, mapping, router, use_reader=(condition == "tripwire_full"),
                                trust_mode=trust_mode)
    pipe = AgentPipeline([SystemMessage(system), InitQuery(), llm, ToolsExecutionLoop([executor, llm])])
    pipe.name = PIPELINE_NAME
    return Built(pipe, client, executor, router)
