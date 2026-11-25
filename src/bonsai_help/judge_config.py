"""The judge's own configuration and prompt loading (B7 Decisions 1 and 2).

`JudgeConfig` is separate from `config.RunConfig`: the frozen judge pins the code that
renders the judge's messages, while B8 may still change `RunConfig`, and the generation
fields (`split`, `prompt_variant`, `seed`) mean nothing to a judge. It reuses the
endpoint and credential rules of `config.py`: local endpoints only, exactly one
credential source, no value in config, settings or error text, and `hosted: true`
refused at load.

A `measured` judge must name its `model_identity` and `model_sha256`; both are recorded
only under the git-ignored artifact root, never in Git. The rule that the judge runs
below every source generator's temperature is checked when a run is created, against
each source collection's recorded settings.
"""

from __future__ import annotations

import hashlib
import re
import string
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from bonsai_help.config import (
    ENV_NAME,
    HOSTED_REFUSED,
    REPOSITORY,
    HostedRefused,
    Nonblank,
    _check_endpoint,
    _read_key,
    _resolve,
)

# The placeholders every judge prompt holds (Decision 2); `{examples}` is added if and
# only if the run has an example pool (judge v2).
JUDGE_PLACEHOLDERS = ("category", "setup", "item", "quotes", "sections", "checks", "fence")
EXAMPLES_PLACEHOLDER = "examples"
DEFAULT_PROMPT = "prompts/judge-v1.md"
# The prompt version is the file stem, so the stem has to read as one.
PROMPT_VERSION = re.compile(r"judge-v[1-9][0-9]*(?:\.[0-9]+)?")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_SECRET_FIELDS = frozenset(
    {"api_key_env", "api_key_file", "embedding_api_key_env", "embedding_api_key_file"}
)


class JudgeConfig(BaseModel):
    """One judge's settings.

    ``purpose`` is ``smoke`` (diagnostic only, never calibration) or ``measured``.
    ``enable_thinking`` None (the default) sends nothing; True or False is sent as the
    chat template's ``enable_thinking``. The embedding settings serve judge v2's example
    selection only: without ``embedding_model`` none of them may be set, and with it the
    chat endpoint and credential serve embeddings unless their own are given, as in
    ``RunConfig``.
    """

    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, hide_input_in_errors=True
    )

    base_url: Nonblank
    model: Nonblank
    model_identity: Nonblank | None = None
    model_sha256: Nonblank | None = None
    purpose: Literal["smoke", "measured"]
    prompt_path: Nonblank = DEFAULT_PROMPT
    mode: Literal["json", "tools"] = "json"
    temperature: float = Field(default=0.0, ge=0, le=2)
    enable_thinking: bool | None = None
    # A 70B judge on local hardware is slow; the ceiling stays bounded (Open question 2).
    timeout_seconds: float = Field(default=300, gt=0, le=600)
    max_tokens: int = Field(default=1500, ge=1, le=8192)
    max_attempts: int = Field(default=2, ge=1, le=3)
    api_key_env: Nonblank | None = None
    api_key_file: Nonblank | None = None
    embedding_base_url: Nonblank | None = None
    embedding_model: Nonblank | None = None
    embedding_api_key_env: Nonblank | None = None
    embedding_api_key_file: Nonblank | None = None
    examples_k: int = Field(default=4, ge=1, le=6)
    artifact_root: Nonblank = "runs"
    hosted: bool = False

    @model_validator(mode="after")
    def endpoint_identity_and_credentials(self):
        if self.hosted:
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
        if self.embedding_model is None and (
            self.embedding_base_url or self.embedding_api_key_env or self.embedding_api_key_file
        ):
            raise ValueError(
                "embedding_base_url and the embedding credential are used only with "
                "embedding_model (judge v2's example selection); set it or remove them"
            )
        if self.model_sha256 is not None and not _SHA256.fullmatch(self.model_sha256):
            raise ValueError("model_sha256 must be a lowercase SHA-256 checksum")
        if self.purpose == "measured" and (
            self.model_identity is None or self.model_sha256 is None
        ):
            raise ValueError(
                "a measured judge must set model_identity and model_sha256 (kept in a "
                "git-ignored local config, never in Git)"
            )
        return self

    @field_validator("api_key_env", "embedding_api_key_env")
    @classmethod
    def names_an_environment_variable(cls, value: str | None, info: ValidationInfo) -> str | None:
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

    def embedding_endpoint(self) -> str | None:
        """The endpoint that serves embeddings, or None without an embedding model."""
        if self.embedding_model is None:
            return None
        return self.embedding_base_url or self.base_url

    def embedding_api_key(self) -> str:
        """The embedding credential: its own source if configured, else the chat one."""
        if self.embedding_model is None:
            raise ValueError("this judge config has no embedding model (judge v2 only)")
        if self._embedding_credential_shared():
            return self.api_key()
        return _read_key(self.embedding_api_key_env, self.embedding_api_key_file, "embedding")

    def artifact_path(self) -> Path:
        """The validated artifact root, resolved against the repository root."""
        return _resolve(self.artifact_root)

    def prompt_file(self) -> Path:
        """The prompt file, resolved against the repository root."""
        return _resolve(self.prompt_path)

    def public_settings(self) -> dict:
        """Settings that identify a judge, without any credential value, name or path.

        ``authentication`` is ``environment`` or ``file``. ``embedding_base_url`` is the
        endpoint actually used for embeddings, and ``embedding_authentication`` is
        ``shared``, ``environment`` or ``file``; both are None without an embedding model.
        """
        if self.embedding_model is None:
            embedding_authentication = None
        elif self._embedding_credential_shared():
            embedding_authentication = "shared"
        else:
            embedding_authentication = "file" if self.embedding_api_key_file else "environment"
        return self.model_dump(exclude=set(_SECRET_FIELDS)) | {
            "authentication": "file" if self.api_key_file else "environment",
            "embedding_base_url": self.embedding_endpoint(),
            "embedding_authentication": embedding_authentication,
        }


def load_judge_config(path: Path) -> JudgeConfig:
    return JudgeConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _placeholders(text: str) -> set[str]:
    """Every replacement field of a `str.format` template; refuses malformed ones."""
    names: set[str] = set()
    try:
        fields = list(string.Formatter().parse(text))
    except ValueError as error:
        raise ValueError(f"judge prompt has a malformed placeholder: {error}") from None
    allowed = {*JUDGE_PLACEHOLDERS, EXAMPLES_PLACEHOLDER}
    for _, name, spec, conversion in fields:
        if name is None:
            continue
        if name not in allowed:
            shown = name if len(name) <= 40 else name[:40] + "..."
            raise ValueError(
                f"judge prompt has an unknown placeholder {{{shown}}}; allowed: "
                + ", ".join(f"{{{n}}}" for n in sorted(allowed))
            )
        if spec or conversion:
            raise ValueError(
                f"judge prompt has a malformed placeholder {{{name}...}}: no conversion or "
                "format spec is allowed"
            )
        names.add(name)
    return names


def load_judge_prompt(config: JudgeConfig, *, with_examples: bool) -> tuple[str, str, str]:
    """Return the prompt text, the SHA-256 of its file bytes and its version (file stem).

    The prompt must hold exactly the placeholders of ``JUDGE_PLACEHOLDERS``, plus
    ``{examples}`` if and only if ``with_examples`` (the run has an example pool). Any
    other placeholder, or a malformed one, is refused; ``{{`` and ``}}`` are literal
    braces. Messages never name the prompt's path.
    """
    path = config.prompt_file()
    version = path.stem
    if not PROMPT_VERSION.fullmatch(version):
        raise ValueError("the judge prompt's file name must be its version, such as judge-v1.md")
    try:
        raw = path.read_bytes()
    except OSError:
        raise ValueError("cannot read the judge prompt") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("the judge prompt is not UTF-8 text") from None
    found = _placeholders(text)
    if EXAMPLES_PLACEHOLDER in found and not with_examples:
        raise ValueError("judge prompt has {examples} but the run has no example pool")
    required = [*JUDGE_PLACEHOLDERS, *([EXAMPLES_PLACEHOLDER] if with_examples else [])]
    missing = [name for name in required if name not in found]
    if missing:
        raise ValueError(
            "judge prompt is missing the placeholders " + ", ".join(f"{{{n}}}" for n in missing)
        )
    return text, hashlib.sha256(raw).hexdigest(), version
