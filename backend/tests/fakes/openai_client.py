"""A stand-in for the OpenAI client: scripted chat completion responses."""

import json
from collections.abc import Callable
from typing import Any

from openai.types.chat import ChatCompletion


def completion(
    content: str | None = "",
    *,
    tool_calls: list[tuple[str, dict[str, Any]]] | None = None,
    reasoning: str | None = None,
    tokens_in: int = 10,
    tokens_out: int = 5,
    model: str = "fake-model",
) -> ChatCompletion:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    if tool_calls:
        message["tool_calls"] = [
            {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for i, (name, args) in enumerate(tool_calls)
        ]
    return ChatCompletion.model_validate(
        {
            "id": "cmpl",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out, "total_tokens": tokens_in + tokens_out},
        }
    )


def json_reply(obj: dict[str, Any], **kwargs: Any) -> ChatCompletion:
    return completion(json.dumps(obj), **kwargs)


Responder = Callable[[dict[str, Any]], Any]


class FakeClient:
    """`responses` is a list (served in order) or a function of the request kwargs.
    An item that is an Exception is raised instead of returned."""

    def __init__(self, responses: list[Any] | Responder) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responses = responses
        self.chat = self
        self.completions = self

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        item = self._responses(kwargs) if callable(self._responses) else self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
