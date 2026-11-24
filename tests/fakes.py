"""Shared synthetic fakes: a fake model transport and Bonsai-flavoured completions.

Everything here is clearly synthetic. It is never model evidence and never submitted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

FAKE_KEY = "synthetic-test-credential-do-not-log"
FAKE_BASE_URL = "http://127.0.0.1:8080/v1"
# A separate local embedding server, as the run config's optional embedding_base_url.
FAKE_EMBEDDING_BASE_URL = "http://127.0.0.1:8081/v1"
FAKE_EMBEDDING_KEY = "synthetic-embedding-credential-do-not-log"
FAKE_MODEL = "explicit-test-model"
FAKE_MESSAGES = [{"role": "user", "content": "Generate a synthetic test Q&A item."}]
FIXTURES = Path(__file__).resolve().parent / "fixtures/docs"
QUOTE_WORDS = 6
_SECTION = re.compile(r"(?P<source>[^:]+):(?P<path>.+)#L(?P<first>\d+)-L(?P<last>\d+)")


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


def fixture_quote(section_id: str) -> str:
    """QUOTE_WORDS whole words (tokens with a letter or digit) from a fixture section's lines.

    The words come from the section's first line that has that many (or, failing that,
    from the start of the section), so the quote occurs verbatim and on word boundaries in
    the text the sampler offers. One pair of brackets around the id is ignored.
    """
    if section_id.startswith("[") and section_id.endswith("]"):
        section_id = section_id[1:-1]
    match = _SECTION.fullmatch(section_id)
    if match is None:
        raise ValueError(f"not a fixture section id: {section_id!r}")
    page = FIXTURES / match["source"] / match["path"]
    lines = page.read_text(encoding="utf-8").split("\n")[
        int(match["first"]) - 1 : int(match["last"])
    ]
    for line in lines:
        if not line.lstrip().startswith(".."):
            quote = _first_words(line.split())
            if quote is not None:
                return quote
    return _first_words(" ".join(lines).split()) or " ".join(" ".join(lines).split())


def _first_words(words: list[str]) -> str | None:
    """The shortest leading run with QUOTE_WORDS tokens that have a letter or digit."""
    counted = 0
    for end, word in enumerate(words, 1):
        counted += any(ch.isalnum() for ch in word)
        if counted == QUOTE_WORDS:
            return " ".join(words[:end])
    return None


def synthetic_generation(
    cited: list[str] | None = None, *, quotes: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """A schema-valid synthetic GenerationOutput payload.

    Unless `quotes` is given, the payload quotes the first cited id that names a fixture
    section, with words copied from that section; a list with no fixture section id gets
    one clearly synthetic quote (it would fail the quote check, which such tests never run).
    """
    cited = cited if cited is not None else ["synthetic-section-1"]
    quotes = grounded_quotes(cited) if quotes is None else quotes
    return {"item": synthetic_item(), "cited_section_ids": cited, "quotes": quotes}


def grounded_quotes(cited: list[str]) -> list[dict[str, str]]:
    """One quote from the first cited fixture section, or a synthetic one if none is."""
    for section_id in cited:
        if _fixture_section(section_id):
            bare = section_id[1:-1] if section_id.startswith("[") else section_id
            return [{"section_id": bare, "text": fixture_quote(section_id)}]
    return [{"section_id": cited[0], "text": "a synthetic quote of six words"}]


def _fixture_section(section_id: str) -> bool:
    try:
        fixture_quote(section_id)
    except (ValueError, OSError):
        return False
    return True


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
