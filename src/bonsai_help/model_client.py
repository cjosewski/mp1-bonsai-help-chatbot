"""One audited model attempt; the generation stage owns the retry budget."""

from __future__ import annotations

import logging
import math
import re
import traceback
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal

import httpx
import instructor
from openai import OpenAI
from pydantic import BaseModel

from bonsai_help.config import check_api_key_length

CREDENTIAL_ECHO = "CredentialEcho"
AUTH_FIELDS = frozenset(
    {"authorization", "proxy-authorization", "api-key", "x-api-key", "cookie", "set-cookie"}
)
REDACTED = "[REDACTED]"
ESCAPED_ECHO = "[REDACTED: credential echo]"
# A JSON string escape: \uXXXX or a backslash before any one character.
_JSON_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)", re.DOTALL)
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}
# Bound on nested escaping (an escaped string inside an escaped string, and so on).
_MAX_UNESCAPE_DEPTH = 4


def _unescape_once(text: str) -> str:
    def decode(match: re.Match[str]) -> str:
        token = match.group(1)
        if len(token) == 5:
            return chr(int(token[1:], 16))
        return _SIMPLE_ESCAPES.get(token, token)

    return _JSON_ESCAPE.sub(decode, text)


class _Credential:
    """Find and redact one configured credential, plain or JSON-escaped.

    A model may write the key inside its JSON output with escapes; the decoded
    HTTP body then still holds the escaped text. Such a string is replaced whole,
    because the escaped span cannot be cut out exactly. Exact replacement of the
    plain key is safe because keys shorter than MIN_API_KEY_LENGTH are refused.
    """

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    def occurs_in(self, text: str) -> bool:
        if self._key in text:
            return True
        for _ in range(_MAX_UNESCAPE_DEPTH):
            if "\\" not in text:
                return False
            decoded = _unescape_once(text)
            if decoded == text:
                return False
            if self._key in decoded:
                return True
            text = decoded
        return False

    def redact_text(self, text: str) -> str:
        text = text.replace(self._key, REDACTED)
        return ESCAPED_ECHO if self.occurs_in(text) else text


def _check_endpoint_settings(
    *, model: str, api_key: str, timeout_seconds: float, which: Literal["chat", "embedding"]
) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if not api_key or not api_key.strip():
        raise ValueError("api_key must be supplied explicitly")
    check_api_key_length(api_key, which)
    if not model or not model.strip():
        raise ValueError("model must be supplied explicitly")


def _openai_sdk(
    *,
    base_url: str,
    api_key: str,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None,
    event_hooks: dict[str, list[Callable[..., Any]]] | None = None,
) -> OpenAI:
    """One SDK client: no SDK retries, no redirects, and no proxy or other
    settings read from the environment (``trust_env=False``)."""
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        max_retries=0,
        timeout=timeout_seconds,
        http_client=httpx.Client(
            transport=transport,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            event_hooks=event_hooks,
        ),
    )


@dataclass(frozen=True)
class AttemptResult:
    item: BaseModel | None
    raw_response: dict[str, Any] | str | None
    error: str | None
    error_type: str | None
    response_model: str | None = None


class _CredentialLogFilter(logging.Filter):
    """Redact provider-echoed credentials without suppressing diagnostic logs."""

    def __init__(self, redact: Callable[[str], str]) -> None:
        super().__init__()
        self._redact = redact

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = self._redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self._redact(record.exc_text)
        return True


class InstructorClient:
    """Synchronous Chat Completions adapter without hidden request retries.

    ``enable_thinking`` True or False adds ``chat_template_kwargs`` with that value to
    each chat request body; None (the default) adds nothing.

    Instructor 1.17's v2 path counts retries after the initial attempt, so both
    Instructor and the OpenAI SDK use ``max_retries=0``. Failed model
    output is returned to the caller so it can be retained before any retry.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        mode: str = "json",
        timeout_seconds: float = 60,
        max_tokens: int = 1200,
        temperature: float = 0.6,
        enable_thinking: bool | None = None,
        response_model: type[BaseModel],
        _transport: httpx.BaseTransport | None = None,
    ) -> None:
        modes = {"json": instructor.Mode.JSON, "tools": instructor.Mode.TOOLS}
        if mode not in modes:
            raise ValueError("mode must be 'json' or 'tools'")
        _check_endpoint_settings(
            model=model, api_key=api_key, timeout_seconds=timeout_seconds, which="chat"
        )
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError("temperature must be finite and between 0 and 2")
        if enable_thinking is not None and not isinstance(enable_thinking, bool):
            raise ValueError("enable_thinking must be true, false or unset (None)")

        self._credential = _Credential(api_key)
        self._output_type = response_model
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        # The OpenAI SDK merges extra_body into the request JSON; None sends nothing.
        self._extra = (
            {}
            if enable_thinking is None
            else {"extra_body": {"chat_template_kwargs": {"enable_thinking": enable_thinking}}}
        )
        self._timeout_seconds = timeout_seconds
        self._last_http_body: dict[str, Any] | str | None = None
        self._last_http_echo = False
        self._sdk = _openai_sdk(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=_transport,
            event_hooks={"response": [self._capture_response]},
        )
        self._client = instructor.from_openai(self._sdk, mode=modes[mode])

    def _capture_response(self, response: httpx.Response) -> None:
        # Capture the body before SDK/Instructor parsing, including malformed
        # completion envelopes. Request/response headers are never recorded.
        response.read()
        try:
            body = response.json()
        except ValueError:
            body = response.text
        self._last_http_echo = self._echoes(body)
        self._last_http_body = self._raw(body)

    def _echoes(self, value: Any) -> bool:
        """Whether the credential occurs anywhere in a value, its dict keys included,
        plain or JSON-escaped."""
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        if isinstance(value, str):
            return self._credential.occurs_in(value)
        if isinstance(value, dict):
            return any(self._echoes(str(k)) or self._echoes(v) for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return any(self._echoes(entry) for entry in value)
        return False

    def _redact(self, value: Any) -> Any:
        """Retain response structure without credential values or auth fields.

        Only evidence (raw bodies, diagnostics) is redacted. A parsed item is never
        rewritten: an echoed credential makes the attempt fail instead.
        """
        if isinstance(value, str):
            return self._credential.redact_text(value)
        if isinstance(value, dict):
            result = {}
            for key, entry in value.items():
                normalized = str(key).lower().replace("_", "-")
                safe_key = self._redact(str(key))
                if normalized in AUTH_FIELDS:
                    result[safe_key] = REDACTED
                else:
                    result[safe_key] = self._redact(entry)
            return result
        if isinstance(value, (list, tuple)):
            return [self._redact(entry) for entry in value]
        return value

    def _raw(self, completion: Any) -> dict[str, Any] | str | None:
        if completion is None:
            return None
        if hasattr(completion, "model_dump"):
            completion = completion.model_dump(mode="json")
        if isinstance(completion, (dict, str)):
            return self._redact(completion)
        if isinstance(completion, (list, tuple)):
            return {"body": self._redact(completion)}
        return self._redact(str(completion))

    def _diagnostic(self, message: str) -> str:
        # Pydantic abbreviates long input values before rendering diagnostics.
        # Exact-key replacement cannot catch those exposed credential fragments.
        # Keep field/type/error details; sanitized raw responses remain separate.
        return re.sub(
            r"input_value=.*?(?=,\s*input_type=)",
            "input_value=[REDACTED]",
            self._redact(message),
            flags=re.DOTALL,
        )

    def _response_model(self, completion: Any) -> str | None:
        model = getattr(completion, "model", None)
        return self._redact(model) if isinstance(model, str) else None

    def generate(self, messages: list[dict[str, str]]) -> AttemptResult:
        # Instructor emits validation details before returning its exception.
        # Scope redaction to this call and retain the log level and diagnostics.
        logger = logging.getLogger("instructor.v2.retry")
        credential_filter = _CredentialLogFilter(self._diagnostic)
        logger.addFilter(credential_filter)
        try:
            return self._generate_once(messages)
        finally:
            logger.removeFilter(credential_filter)

    def _generate_once(self, messages: list[dict[str, str]]) -> AttemptResult:
        self._last_http_body = None
        self._last_http_echo = False
        completion = None
        try:
            item, completion = self._client.create_with_completion(
                model=self._model,
                response_model=self._output_type,
                messages=deepcopy(messages),
                max_retries=0,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                timeout=self._timeout_seconds,
                **deepcopy(self._extra),
            )
            captured = self._last_http_body is not None
            raw_response = self._last_http_body if captured else self._raw(completion)
            echoed = self._echoes(item) or (
                self._last_http_echo if captured else self._echoes(completion)
            )
            if echoed:
                # The response cannot be kept verbatim, and rewriting the item would
                # store text the model did not produce. Fail the attempt instead,
                # keeping the redacted raw body as its evidence.
                return AttemptResult(
                    item=None,
                    raw_response=raw_response,
                    error="the response echoed the configured credential; the raw "
                    "response is kept redacted and the item is not kept",
                    error_type=CREDENTIAL_ECHO,
                    response_model=self._response_model(completion),
                )
            return AttemptResult(
                item=item,
                raw_response=raw_response,
                error=None,
                error_type=None,
                response_model=self._response_model(completion),
            )
        except Exception as error:
            # This is the external-provider boundary: preserve failures, including
            # unexpected malformed completion shapes, for the caller's audit log.
            # KeyboardInterrupt and other BaseExceptions still propagate.
            cause = error
            completion = getattr(error, "last_completion", completion)
            # Instructor's legacy and current provider paths use different
            # wrapper classes. Read their evidence rather than importing a
            # private exception type; the HTTP hook retains the body either way.
            failed_attempts = getattr(error, "failed_attempts", None)
            last_attempt = failed_attempts[-1] if failed_attempts else None
            nested = getattr(last_attempt, "exception", None)
            if nested is None:
                nested = getattr(error, "last_exception", None)
            if nested is None:
                nested = error.__cause__
            if isinstance(nested, Exception):
                cause = nested
            if completion is None:
                completion = getattr(last_attempt, "completion", None)
            if completion is None:
                completion = getattr(cause, "raw_response", None)
            if completion is None:
                completion = getattr(cause, "body", None)
            return AttemptResult(
                item=None,
                raw_response=self._last_http_body
                if self._last_http_body is not None
                else self._raw(completion),
                error=self._diagnostic(str(cause)),
                error_type=type(cause).__name__,
                response_model=self._response_model(completion),
            )

    def close(self) -> None:
        self._sdk.close()

    def __enter__(self) -> InstructorClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class EmbeddingError(RuntimeError):
    """The embedding call failed or returned vectors of an unusable shape."""


class EmbeddingClient:
    """Embeddings from the configured endpoint: one request per call, no retries."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 60,
        _transport: httpx.BaseTransport | None = None,
    ) -> None:
        _check_endpoint_settings(
            model=model, api_key=api_key, timeout_seconds=timeout_seconds, which="embedding"
        )
        self._credential = _Credential(api_key)
        self._model = model
        self._sdk = _openai_sdk(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=_transport,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self._sdk.embeddings.create(
                model=self._model, input=list(texts), encoding_format="float"
            )
            vectors = [list(entry.embedding) for entry in response.data]
        except Exception as error:  # provider boundary: type every failure
            message = self._credential.redact_text(str(error))
            raise EmbeddingError(f"{type(error).__name__}: {message}") from None
        if len(vectors) != len(texts):
            raise EmbeddingError(f"expected {len(texts)} vectors, received {len(vectors)}")
        width = len(vectors[0])
        if width == 0 or any(len(vector) != width for vector in vectors):
            raise EmbeddingError("embedding vectors are empty or have ragged dimensions")
        return vectors

    def close(self) -> None:
        self._sdk.close()

    def __enter__(self) -> EmbeddingClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
