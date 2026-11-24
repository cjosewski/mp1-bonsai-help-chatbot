"""Explicit run configuration; credentials never enter manifests or error text."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from bonsai_help.doc_sources import ConfigError

Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

REPOSITORY = Path(__file__).resolve().parents[2]
PROMPT_PLACEHOLDERS = ("{category}", "{setup}", "{sections}")
# An environment-variable NAME: upper case, digits and underscores, not a pasted key.
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
# Credentials are scrubbed from evidence by exact match; a shorter key would match
# ordinary words in generated text, so it is refused rather than redacted.
MIN_API_KEY_LENGTH = 16
HOSTED_REFUSED = (
    "hosted: true is refused: the hosted path is not implemented, and it stays refused "
    "until Chad authorizes one with an enforced cost cap (cost_cap_usd is not enforced)"
)
# Local model hosts: loopback, RFC 1918 IPv4 and IPv6 unique local addresses. Link-local
# (169.254.0.0/16, fe80::/10) is refused: it holds cloud metadata services and is not a
# plausible model host. Tunnel and translation prefixes (6to4, Teredo, NAT64), CGNAT and
# documentation ranges are not on this list, so they are refused too.
LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)


class HostedRefused(ConfigError):
    """A run config asks for the hosted path, which is not implemented (exit 2)."""


def _resolve(value: str) -> Path:
    """Resolve a relative path against the repository root, not the working directory."""
    path = Path(value)
    return (path if path.is_absolute() else REPOSITORY / path).resolve()


class RunConfig(BaseModel):
    """One run's settings.

    The embedding endpoint is optional: ``embedding_base_url`` None means the chat
    endpoint (``base_url``) serves embeddings too, and with neither
    ``embedding_api_key_env`` nor ``embedding_api_key_file`` the embedding client uses
    the chat credential source. Both endpoints pass the same local-endpoint rules.
    """

    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, hide_input_in_errors=True
    )

    base_url: Nonblank
    model: Nonblank
    embedding_model: Nonblank
    embedding_base_url: Nonblank | None = None
    model_identity: Nonblank | None = None
    model_sha256: Nonblank | None = None
    purpose: Literal["smoke", "baseline", "corrected"] = "smoke"
    split: Literal["development", "assessed"] = "development"
    prompt_path: Nonblank = "prompts/generator-v1.md"
    prompt_variant: Literal["baseline", "corrected"] = "baseline"
    api_key_env: Nonblank | None = "BONSAI_HELP_API_KEY"
    api_key_file: Nonblank | None = None
    embedding_api_key_env: Nonblank | None = None
    embedding_api_key_file: Nonblank | None = None
    mode: Literal["json", "tools"] = "json"
    temperature: float = Field(default=0.6, ge=0, le=2)
    timeout_seconds: float = Field(default=120, gt=0, le=300)
    max_tokens: int = Field(default=2000, ge=1, le=8192)
    max_attempts: int = Field(default=3, ge=1, le=5)
    artifact_root: Nonblank = "runs"
    seed: int
    hosted: bool = False
    hosted_authorization: Nonblank | None = None
    cost_cap_usd: float | None = None

    @model_validator(mode="after")
    def endpoint_and_credentials(self):
        if self.hosted:
            # Not a ValueError, so Pydantic does not fold it into a ValidationError
            # whose CLI summary would only name "(root)".
            raise HostedRefused(HOSTED_REFUSED)
        _check_endpoint(self.base_url, "base_url")
        if self.embedding_base_url is not None:
            _check_endpoint(self.embedding_base_url, "embedding_base_url")
        if bool(self.api_key_env) == bool(self.api_key_file):
            raise ValueError("set exactly one of api_key_env and api_key_file")
        if self.embedding_api_key_env and self.embedding_api_key_file:
            raise ValueError(
                "set at most one of embedding_api_key_env and embedding_api_key_file "
                "(neither uses the chat credential source)"
            )
        if self.model_sha256 is not None and not re.fullmatch("[a-f0-9]{64}", self.model_sha256):
            raise ValueError("model_sha256 must be a lowercase SHA-256 checksum")
        return self

    @field_validator("api_key_env", "embedding_api_key_env")
    @classmethod
    def names_an_environment_variable(cls, value: str | None, info: ValidationInfo) -> str | None:
        # hide_input_in_errors keeps the rejected value out of the error text.
        if value is not None and not ENV_NAME.fullmatch(value):
            raise ValueError(
                f"{info.field_name} must name an environment variable (A-Z, 0-9 and _, "
                "at most 64 characters), not hold a key value"
            )
        return value

    @field_validator("base_url", "embedding_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value is not None else None

    @field_validator("artifact_root")
    @classmethod
    def raw_runs_stay_out_of_git(cls, value: str) -> str:
        root = _resolve(value)
        if root.is_relative_to(REPOSITORY) and not root.is_relative_to(REPOSITORY / "runs"):
            raise ValueError(
                "artifact_root must be runs/ (git-ignored) or a path outside the repository"
            )
        return value

    def api_key(self) -> str:
        return _read_key(self.api_key_env, self.api_key_file, "chat")

    def _embedding_credential_shared(self) -> bool:
        return not (self.embedding_api_key_env or self.embedding_api_key_file)

    def embedding_api_key(self) -> str:
        """The embedding credential: its own source if configured, else the chat one."""
        if self._embedding_credential_shared():
            return self.api_key()
        return _read_key(self.embedding_api_key_env, self.embedding_api_key_file, "embedding")

    def embedding_endpoint(self) -> str:
        """The endpoint that serves embeddings: ``embedding_base_url`` or ``base_url``."""
        return self.embedding_base_url or self.base_url

    def artifact_path(self) -> Path:
        """The validated artifact root, resolved against the repository root."""
        return _resolve(self.artifact_root)

    def prompt_file(self) -> Path:
        """The prompt file, resolved against the repository root."""
        return _resolve(self.prompt_path)

    def public_settings(self) -> dict:
        """Settings that identify a run, without any credential value, name or path.

        ``embedding_base_url`` is the endpoint actually used for embeddings, so leaving it
        out and naming ``base_url`` are the same identity. ``embedding_authentication`` is
        ``shared`` (the chat credential source), ``environment`` or ``file``.
        """
        secret = {"api_key_env", "api_key_file", "embedding_api_key_env", "embedding_api_key_file"}
        if self._embedding_credential_shared():
            embedding_authentication = "shared"
        else:
            embedding_authentication = "file" if self.embedding_api_key_file else "environment"
        return self.model_dump(exclude=secret) | {
            "authentication": "file" if self.api_key_file else "environment",
            "embedding_base_url": self.embedding_endpoint(),
            "embedding_authentication": embedding_authentication,
        }


def _read_key(env: str | None, file: str | None, which: Literal["chat", "embedding"]) -> str:
    """Read one credential source; messages name the key (chat or embedding) and the source
    kind, never its value."""
    if file:
        try:
            value = Path(file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"cannot read configured {which} API-key file") from exc
    else:
        value = os.environ.get(env or "", "").strip()
    if not value:
        raise ValueError(f"configured {which} API key is missing or empty")
    check_api_key_length(value, which)
    return value


def check_api_key_length(value: str, which: Literal["chat", "embedding"]) -> None:
    """Refuse a key too short to scrub from evidence without editing ordinary text.

    The message names which key is short (chat or embedding), never its value."""
    if which not in ("chat", "embedding"):
        raise ValueError("which must be 'chat' or 'embedding'")
    if len(value) < MIN_API_KEY_LENGTH:
        raise ValueError(
            f"the {which} API key must be at least {MIN_API_KEY_LENGTH} characters; a local "
            "server that ignores the key still needs a long random placeholder"
        )


def _is_local(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in LOCAL_NETWORKS)


def _check_endpoint(value: str, field: str) -> None:
    """Accept only an explicit local endpoint; the hosted path is refused earlier.

    Messages name the field, never the value.
    """
    url = urlsplit(value)
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise ValueError(f"{field} must be an explicit HTTP(S) endpoint")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError(f"{field} cannot contain credentials, a query or a fragment")
    try:
        port = url.port
    except ValueError as exc:
        raise ValueError(f"{field}: invalid endpoint port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"{field}: invalid endpoint port")
    if url.path.rstrip("/") != "/v1":
        raise ValueError(f"{field} must end in /v1")
    if url.hostname != "localhost":
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError as exc:
            raise ValueError(f"{field}: use localhost or an explicit private/loopback IP") from exc
        if not _is_local(address):
            raise ValueError(
                f"{field}: only loopback, RFC 1918 or IPv6 unique local endpoints are allowed"
            )


def load_config(path: Path) -> RunConfig:
    return RunConfig.model_validate_json(path.read_text(encoding="utf-8"))


def load_prompt(config: RunConfig) -> tuple[str, str]:
    """Return the prompt text and the SHA-256 of its file bytes."""
    try:
        raw = config.prompt_file().read_bytes()
    except OSError as exc:
        raise ValueError("cannot read the generator prompt") from exc
    text = raw.decode("utf-8")
    missing = [
        p for p in PROMPT_PLACEHOLDERS if not re.search(rf"(?<!\{{)\{{{p[1:-1]}\}}(?!\}})", text)
    ]
    if missing:
        raise ValueError(f"generator prompt must include the placeholders {', '.join(missing)}")
    return text, hashlib.sha256(raw).hexdigest()
