"""Shared synthetic fakes: a fake model transport and Bonsai-flavoured completions.

Everything here is clearly synthetic. It is never model evidence and never submitted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

FAKE_KEY = "synthetic-test-credential-do-not-log"
FAKE_BASE_URL = "http://127.0.0.1:8080/v1"
FAKE_MODEL = "explicit-test-model"
FAKE_MESSAGES = [{"role": "user", "content": "Generate a synthetic test Q&A item."}]


def synthetic_item() -> dict[str, Any]:
    """A schema-valid, synthetic seven-field payload."""
    return {
        "question": "How do I add a wall to a synthetic Bonsai test project?",
        "answer": "Open the synthetic project, choose a wall type, then add the wall in the viewport.",
        "equipment_problem": "A synthetic project has no walls yet.",
        "tools_required": ["Bonsai add-on"],
        "steps": [
            "Open the Bonsai project properties panel.",
            "Select a wall type in the Type Library.",
            "Click Add Wall in the viewport and save a copy.",
        ],
        "safety_info": "Save a copy first so an undo-unfriendly edit cannot lose the test file.",
        "tips": ["Name the wall type clearly so it is easy to find in the library later."],
    }


def synthetic_generation(cited: list[str] | None = None) -> dict[str, Any]:
    """A schema-valid synthetic GenerationOutput payload."""
    return {
        "item": synthetic_item(),
        "cited_section_ids": cited if cited is not None else ["synthetic-section-1"],
    }


def completion(
    content: str, *, tool_name: str | None = None, model: str = "synthetic-model-revision"
):
    """A chat-completion envelope; with tool_name, the content rides in a tool call."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_name:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "test-call-1",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": content},
                }
            ],
        }
    return {
        "id": "test-completion-1",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def embedding_response(vectors: list[list[float]], model: str = "synthetic-embedding") -> dict:
    return {
        "object": "list",
        "model": model,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


class FakeTransport:
    """An httpx.MockTransport that records every request it receives."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.calls: list[httpx.Request] = []
        self._handler = handler
        self.transport = httpx.MockTransport(self._record)

    def _record(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self._handler(request)

    def bodies(self) -> list[Any]:
        return [json.loads(call.content) for call in self.calls]


def fake_transport(handler: Callable[[httpx.Request], httpx.Response]) -> FakeTransport:
    return FakeTransport(handler)


def fixed_response(body: Any, status: int = 200) -> FakeTransport:
    """A transport that answers every request with the same JSON body."""
    return FakeTransport(lambda request: httpx.Response(status, json=body))
