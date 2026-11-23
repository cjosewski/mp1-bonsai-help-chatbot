"""Explicit run configuration; credentials never enter manifests or error text."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

REPOSITORY = Path(__file__).resolve().parents[2]
PROMPT_PLACEHOLDERS = ("{category}", "{setup}", "{sections}")


def _resolve(value: str) -> Path:
    """Resolve a relative path against the repository root, not the working directory."""
    path = Path(value)
    return (path if path.is_absolute() else REPOSITORY / path).resolve()


class RunConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, hide_input_in_errors=True
    )

    base_url: Nonblank
    model: Nonblank
    embedding_model: Nonblank
    model_identity: Nonblank | None = None
    model_sha256: Nonblank | None = None
    purpose: Literal["smoke", "baseline", "corrected"] = "smoke"
    split: Literal["development", "assessed"] = "development"
    prompt_path: Nonblank = "prompts/generator-v1.md"
    prompt_variant: Literal["baseline", "corrected"] = "baseline"
    api_key_env: Nonblank | None = "BONSAI_HELP_API_KEY"
    api_key_file: Nonblank | None = None
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
        _check_endpoint(self.base_url, self.hosted)
        if self.hosted:
            if not self.hosted_authorization:
                raise ValueError("a hosted endpoint needs hosted_authorization")
            if self.cost_cap_usd is None or self.cost_cap_usd <= 0:
                raise ValueError("a hosted endpoint needs cost_cap_usd above zero")
        if bool(self.api_key_env) == bool(self.api_key_file):
            raise ValueError("set exactly one of api_key_env and api_key_file")
        if self.model_sha256 is not None and not re.fullmatch("[a-f0-9]{64}", self.model_sha256):
            raise ValueError("model_sha256 must be a lowercase SHA-256 checksum")
        return self

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

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
        if self.api_key_file:
            try:
                value = Path(self.api_key_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ValueError("cannot read configured API-key file") from exc
        else:
            import os

            value = os.environ.get(self.api_key_env or "", "").strip()
        if not value:
            raise ValueError("configured API key is missing or empty")
        return value

    def public_settings(self) -> dict:
        return self.model_dump(exclude={"api_key_env", "api_key_file"}) | {
            "authentication": "file" if self.api_key_file else "environment"
        }


def _check_endpoint(value: str, hosted: bool) -> None:
    url = urlsplit(value)
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise ValueError("base_url must be an explicit HTTP(S) endpoint")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("base_url cannot contain credentials, a query or a fragment")
    try:
        port = url.port
    except ValueError as exc:
        raise ValueError("invalid endpoint port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("invalid endpoint port")
    if url.path.rstrip("/") != "/v1":
        raise ValueError("base_url must end in /v1")
    if hosted:
        if url.scheme != "https":
            raise ValueError("a hosted endpoint must use https")
        return
    if url.hostname != "localhost":
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError as exc:
            raise ValueError("use localhost or an explicit private/loopback IP") from exc
        if not (address.is_loopback or address.is_private) or address.is_unspecified:
            raise ValueError("only explicit local endpoints are allowed unless hosted is true")


def load_config(path: Path) -> RunConfig:
    return RunConfig.model_validate_json(path.read_text(encoding="utf-8"))


def load_prompt(config: RunConfig) -> tuple[str, str]:
    """Return the prompt text and the SHA-256 of its file bytes."""
    try:
        raw = _resolve(config.prompt_path).read_bytes()
    except OSError as exc:
        raise ValueError("cannot read the generator prompt") from exc
    text = raw.decode("utf-8")
    missing = [p for p in PROMPT_PLACEHOLDERS if p not in text]
    if missing:
        raise ValueError(f"generator prompt must include the placeholders {', '.join(missing)}")
    return text, hashlib.sha256(raw).hexdigest()
