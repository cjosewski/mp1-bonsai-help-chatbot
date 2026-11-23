"""Exercise the real SDK/Instructor boundary with synthetic HTTP responses."""

import json
import logging
from copy import deepcopy

import httpx
import pytest
from fakes import (
    FAKE_BASE_URL,
    FAKE_KEY,
    FAKE_MESSAGES,
    FAKE_MODEL,
    completion,
    embedding_response,
    fake_transport,
    fixed_response,
    synthetic_generation,
)

from bonsai_help.model_client import EmbeddingClient, EmbeddingError, InstructorClient
from bonsai_help.schemas import GenerationOutput

KEY = FAKE_KEY
MESSAGES = FAKE_MESSAGES


def make_client(transport, **kwargs):
    return InstructorClient(
        base_url=FAKE_BASE_URL,
        model=FAKE_MODEL,
        api_key=KEY,
        response_model=GenerationOutput,
        _transport=transport.transport,
        **kwargs,
    )


@pytest.mark.parametrize("mode", ["json", "tools"])
def test_valid_response_uses_one_request_and_retains_completion(mode):
    tool = "GenerationOutput" if mode == "tools" else None
    fake = fixed_response(completion(json.dumps(synthetic_generation()), tool_name=tool))
    messages = deepcopy(MESSAGES)
    with make_client(fake, mode=mode, timeout_seconds=2.5) as client:
        result = client.generate(messages)

    assert len(fake.calls) == 1
    assert str(fake.calls[0].url) == FAKE_BASE_URL + "/chat/completions"
    body = fake.bodies()[0]
    assert body["model"] == FAKE_MODEL
    assert body["temperature"] == 0.6
    assert body["max_tokens"] == 1200
    assert fake.calls[0].extensions["timeout"]["read"] == 2.5
    assert result.item.model_dump() == synthetic_generation()
    assert result.raw_response["id"] == "test-completion-1"
    assert result.raw_response["usage"]["total_tokens"] == 30
    assert result.response_model == "synthetic-model-revision"
    assert result.error is None
    assert messages == MESSAGES


@pytest.mark.parametrize(
    "content", ["not valid JSON", json.dumps({"item": {"question": "Missing fields"}})]
)
def test_malformed_or_invalid_output_is_returned_without_hidden_retry(content):
    fake = fixed_response(completion(content))
    with make_client(fake) as client:
        result = client.generate(MESSAGES)

    assert len(fake.calls) == 1
    assert result.item is None
    assert result.error
    assert result.error_type
    assert result.raw_response["choices"][0]["message"]["content"] == content


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_failures_are_one_attempt_and_preserve_error_body(status):
    fake = fixed_response({"error": {"message": "synthetic server error"}}, status)
    with make_client(fake) as client:
        result = client.generate(MESSAGES)

    assert len(fake.calls) == 1
    assert result.item is None
    assert result.error
    assert "synthetic server error" in json.dumps(result.raw_response)


def test_timeout_returns_failure_without_transport_retry():
    def handler(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    fake = fake_transport(handler)
    with make_client(fake) as client:
        result = client.generate(MESSAGES)

    assert len(fake.calls) == 1
    assert result.item is None
    assert result.raw_response is None
    assert result.error_type == "APITimeoutError"


@pytest.mark.parametrize("kind", ["truncated", "broken_envelope", "not_json"])
def test_unparseable_or_truncated_completion_still_retains_response_body(kind):
    raw = completion('{"item":{"question":"truncated')
    raw["choices"][0]["finish_reason"] = "length"
    if kind == "broken_envelope":
        raw = {"unexpected": "not a chat completion"}

    def handler(request):
        if kind == "not_json":
            return httpx.Response(200, text="synthetic invalid HTTP response")
        return httpx.Response(200, json=raw)

    fake = fake_transport(handler)
    with make_client(fake) as client:
        result = client.generate(MESSAGES)

    assert len(fake.calls) == 1
    assert result.item is None
    assert result.error
    assert result.raw_response == ("synthetic invalid HTTP response" if kind == "not_json" else raw)


def test_successful_payload_and_raw_response_redact_echoed_credentials():
    payload = synthetic_generation()
    payload["item"]["answer"] += f" Echoed credential: {KEY}"
    raw = completion(json.dumps(payload))
    raw["extra_metadata"] = {"authorization": "Bearer unrelated-secret", "nested": [KEY]}
    with make_client(fixed_response(raw)) as client:
        result = client.generate(MESSAGES)

    assert result.item is not None
    serialized = json.dumps(result.raw_response) + result.item.model_dump_json()
    assert KEY not in serialized
    assert "unrelated-secret" not in serialized
    assert "[REDACTED]" in serialized


@pytest.mark.parametrize("prefix", ["", "malformed response containing "])
def test_failed_response_and_error_redact_echoed_credential(caplog, prefix):
    raw = completion(prefix + KEY)
    caplog.set_level(logging.ERROR, logger="instructor.v2.retry")
    with make_client(fixed_response(raw)) as client:
        result = client.generate(MESSAGES)

    assert result.item is None
    for fragment in (KEY, KEY[-16:]):
        assert fragment not in json.dumps(result.raw_response)
        assert fragment not in result.error
        assert fragment not in caplog.text
    assert "[REDACTED]" in json.dumps(result.raw_response)
    assert any(record.levelno == logging.ERROR for record in caplog.records)
    assert "[REDACTED]" in caplog.text
    assert "json_invalid" in caplog.text
    assert "json_invalid" in result.error


def test_schema_diagnostics_retain_field_details_without_echoed_input(caplog):
    payload = synthetic_generation()
    payload["item"]["steps"] = "long invalid list value containing " + KEY
    with make_client(fixed_response(completion(json.dumps(payload)))) as client:
        result = client.generate(MESSAGES)

    assert result.item is None
    for fragment in (KEY, KEY[-16:]):
        assert fragment not in result.error
        assert fragment not in caplog.text
    assert "steps" in result.error
    assert "list_type" in result.error
    assert "list_type" in caplog.text
    assert "input_value=[REDACTED]" in result.error


def test_http_error_redacts_credential_from_body_and_message(caplog):
    fake = fixed_response({"error": {"message": f"Invalid credential {KEY}"}}, 401)
    with make_client(fake) as client:
        result = client.generate(MESSAGES)

    assert KEY not in json.dumps(result.raw_response) + result.error
    assert "[REDACTED]" in result.error
    assert KEY not in caplog.text


def test_production_transport_ignores_environment_proxies(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
        monkeypatch.delenv(name.lower(), raising=False)
    for name in ("NO_PROXY", "no_proxy", "REQUEST_METHOD"):
        monkeypatch.delenv(name, raising=False)
    endpoint = httpx.URL(FAKE_BASE_URL + "/chat/completions")

    with httpx.Client(trust_env=True) as control:
        assert control._transport_for_url(endpoint) is not control._transport

    with InstructorClient(
        base_url=FAKE_BASE_URL,
        model=FAKE_MODEL,
        api_key=KEY,
        response_model=GenerationOutput,
    ) as client:
        transport_client = client._sdk._client
        assert transport_client._transport_for_url(endpoint) is transport_client._transport
        assert not transport_client._mounts


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "unsupported"},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"max_tokens": 0},
        {"max_tokens": True},
        {"temperature": float("nan")},
    ],
)
def test_invalid_client_settings_fail_before_network(kwargs):
    fake = fake_transport(lambda request: pytest.fail("No HTTP request should be made"))
    with pytest.raises(ValueError):
        make_client(fake, **kwargs)


def make_embedder(transport, **kwargs):
    return EmbeddingClient(
        base_url=FAKE_BASE_URL,
        model="synthetic-embedding",
        api_key=KEY,
        timeout_seconds=2.5,
        _transport=transport.transport,
        **kwargs,
    )


def test_embeddings_use_one_request_and_return_vectors():
    vectors = [[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]]
    fake = fixed_response(embedding_response(vectors))
    with make_embedder(fake) as embedder:
        result = embedder.embed(["first", "second"])

    assert result == vectors
    assert len(fake.calls) == 1
    assert str(fake.calls[0].url) == FAKE_BASE_URL + "/embeddings"
    body = fake.bodies()[0]
    assert body["model"] == "synthetic-embedding"
    assert body["input"] == ["first", "second"]


def test_embedding_empty_input_makes_no_request():
    fake = fake_transport(lambda request: pytest.fail("No HTTP request should be made"))
    with make_embedder(fake) as embedder:
        assert embedder.embed([]) == []


@pytest.mark.parametrize(
    "vectors",
    [
        [[0.1, 0.2]],  # wrong count for two texts
        [[0.1, 0.2], [0.1]],  # ragged
        [[], []],  # empty dimensions
        [[0.1, 0.2], [0.1, 0.2], [0.3, 0.4]],  # extra vector
    ],
)
def test_embedding_shape_errors(vectors):
    with make_embedder(fixed_response(embedding_response(vectors))) as embedder:
        with pytest.raises(EmbeddingError):
            embedder.embed(["first", "second"])


@pytest.mark.parametrize("status", [401, 500])
def test_embedding_transport_failure_is_typed_and_not_retried(status):
    fake = fixed_response({"error": {"message": f"synthetic failure {KEY}"}}, status)
    with make_embedder(fake) as embedder:
        with pytest.raises(EmbeddingError) as excinfo:
            embedder.embed(["first"])

    assert len(fake.calls) == 1
    assert KEY not in str(excinfo.value)


def test_embedding_timeout_is_typed():
    def handler(request):
        raise httpx.ConnectTimeout("synthetic timeout", request=request)

    fake = fake_transport(handler)
    with make_embedder(fake) as embedder:
        with pytest.raises(EmbeddingError):
            embedder.embed(["first"])
    assert len(fake.calls) == 1


def test_embedding_client_ignores_environment_proxies(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    endpoint = httpx.URL(FAKE_BASE_URL + "/embeddings")
    with EmbeddingClient(
        base_url=FAKE_BASE_URL, model="synthetic-embedding", api_key=KEY, timeout_seconds=2
    ) as embedder:
        http = embedder._sdk._client
        assert http._transport_for_url(endpoint) is http._transport
