"""Pin configuration for the documentation snapshots (`config/doc-sources.json`)."""

from __future__ import annotations

import hashlib
import json
import re
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

CATEGORIES = (
    "bonsai_project_setup",
    "bonsai_modeling",
    "ifc_data_and_materials",
    "model_exploration",
    "files_versions_troubleshooting",
)
Category = Literal[
    "bonsai_project_setup",
    "bonsai_modeling",
    "ifc_data_and_materials",
    "model_exploration",
    "files_versions_troubleshooting",
]
ALLOWED_HOSTS = frozenset({"github.com", "projects.blender.org"})
OBJECT_ID = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SOURCE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REF_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
PRIVACY_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "home-path": re.compile(r"/home/|/Users/"),
    "ipv4": re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"),
}


class SnapshotError(Exception):
    """A controlled failure with a documented exit code."""

    exit_code = 1


class ConfigError(SnapshotError):
    exit_code = 2


class FetchError(SnapshotError):
    exit_code = 3


class PinMismatch(SnapshotError):
    exit_code = 4


class Refused(SnapshotError):
    exit_code = 5


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _object_id(value: str) -> str:
    if not OBJECT_ID.fullmatch(value):
        raise ValueError("must be 40 lower-case hex characters")
    return value


def _relative_path(value: str, *, glob: bool) -> str:
    segments = value.split("/")
    if not value or value.startswith("/") or "\\" in value or "\0" in value:
        raise ValueError(f"{value!r} must be a relative POSIX path")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError(f"{value!r} has an empty, '.' or '..' segment")
    if not glob and any(char in value for char in "*?["):
        raise ValueError(f"{value!r} must not contain glob characters")
    return value


def _under(path: str, root: str) -> bool:
    return path.startswith(root + "/")


class Ref(_Model):
    kind: Literal["tag", "branch"]
    name: str
    tag_object: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not REF_NAME.fullmatch(value) or ".." in value or value.endswith((".lock", "/")):
            raise ValueError(f"invalid ref name {value!r}")
        return value

    @field_validator("tag_object")
    @classmethod
    def _tag_object(cls, value: str | None) -> str | None:
        return None if value is None else _object_id(value)

    @model_validator(mode="after")
    def _branch_has_no_tag_object(self) -> Ref:
        if self.kind == "branch" and self.tag_object is not None:
            raise ValueError("a branch ref has no tag_object")
        return self


class Repository(_Model):
    url: str
    ref: Ref
    commit: str

    @field_validator("commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        return _object_id(value)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str, info: ValidationInfo) -> str:
        parts = urlsplit(value)
        if not parts.path.endswith(".git") or parts.query or parts.fragment:
            raise ValueError("url must end in .git and have no query or fragment")
        allow_file = bool((info.context or {}).get("allow_file_urls"))
        if parts.scheme == "file" and allow_file and not parts.netloc:
            return value
        if parts.scheme != "https":
            raise ValueError("url must use https")
        if parts.username is not None or parts.password is not None or parts.port is not None:
            raise ValueError("url must not carry credentials or a port")
        if parts.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"url host must be one of {sorted(ALLOWED_HOSTS)}")
        return value


class LicenseEvidence(_Model):
    path: str
    blob: str
    commit_copy: bool
    note: str | None = None

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _relative_path(value, glob=False)

    @field_validator("blob")
    @classmethod
    def _blob(cls, value: str) -> str:
        return _object_id(value)


class TagRule(_Model):
    glob: str
    tag: str = Field(pattern=r"^[a-z][a-z0-9-]*$")

    @field_validator("glob")
    @classmethod
    def _glob(cls, value: str) -> str:
        return _relative_path(value, glob=True)


class FixturePage(_Model):
    path: str
    categories: list[Category]

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _relative_path(value, glob=False)


MAX_CODE_SPAN_LINES = 60


class CodeSpan(_Model):
    """A line span of an operator-source file that a gold item or fact row cites. Only the
    span's own lines enter the fixture slice (`<path>.L<first>-L<last>`), unmodified, because
    the files' license headers name contributors' contact addresses."""

    path: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _relative_path(value, glob=False)

    @model_validator(mode="after")
    def _span(self) -> CodeSpan:
        if self.line_end < self.line_start:
            raise ValueError("line_end is before line_start")
        if self.line_end - self.line_start + 1 > MAX_CODE_SPAN_LINES:
            raise ValueError(f"a code span is at most {MAX_CODE_SPAN_LINES} lines")
        return self

    @property
    def fixture_path(self) -> str:
        return code_span_path(self.path, self.line_start, self.line_end)


def code_span_path(path: str, line_start: int, line_end: int) -> str:
    """Where a code span's lines sit in the fixture slice, beside nothing else of the file."""
    return f"{path}.L{line_start}-L{line_end}"


class AutoSectionLabel(_Model):
    """Sphinx `autosectionlabel` settings read from the source's own `conf.py`."""

    prefix_document: bool
    maxdepth: int = Field(ge=0)


class Source(_Model):
    id: str
    repository: str
    root: str
    role: Literal["docs", "operator-source"] = "docs"
    autosectionlabel: AutoSectionLabel | None = None
    include: list[str] = Field(min_length=1)
    exclude: list[str] = []
    deny: list[str] = []
    tags: list[TagRule] = []
    default_tag: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    license: str
    license_note: str | None = None
    license_evidence: list[LicenseEvidence] = Field(min_length=1)
    attribution: str = Field(min_length=1)
    permitted_use: str = Field(min_length=1)
    fixture_pages: list[FixturePage] = []
    fixture_code_spans: list[CodeSpan] = []
    fixture_min_per_category: int = Field(default=0, ge=0)
    fixture_forbid_python: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not SOURCE_ID.fullmatch(value):
            raise ValueError("source id must match [a-z0-9]+(-[a-z0-9]+)*")
        return value

    @field_validator("root")
    @classmethod
    def _root(cls, value: str) -> str:
        return _relative_path(value, glob=False)

    @field_validator("include", "exclude", "deny")
    @classmethod
    def _globs(cls, value: list[str]) -> list[str]:
        return [_relative_path(item, glob=True) for item in value]

    @model_validator(mode="after")
    def _consistent(self) -> Source:
        outside = [glob for glob in self.include if not _under(glob, self.root)]
        if outside:
            raise ValueError(f"include globs outside root {self.root!r}: {outside}")
        paths = [page.path for page in self.fixture_pages]
        if len(paths) != len(set(paths)):
            raise ValueError("fixture_pages paths must be unique")
        outside = [path for path in paths if not _under(path, self.root)]
        if outside:
            raise ValueError(f"fixture_pages outside root {self.root!r}: {outside}")
        evidence = [item.path for item in self.license_evidence]
        if len(evidence) != len(set(evidence)):
            raise ValueError("license_evidence paths must be unique")
        if self.role == "operator-source" and (self.fixture_pages or self.autosectionlabel):
            raise ValueError("an operator-source has no fixture_pages and no autosectionlabel")
        if self.role != "operator-source" and self.fixture_code_spans:
            raise ValueError("only an operator-source has fixture_code_spans")
        spans = [(s.path, s.line_start, s.line_end) for s in self.fixture_code_spans]
        if len(spans) != len(set(spans)):
            raise ValueError("fixture_code_spans must be unique")
        outside = [s.path for s in self.fixture_code_spans if not _under(s.path, self.root)]
        if outside:
            raise ValueError(f"fixture_code_spans outside root {self.root!r}: {outside}")
        return self


class PrivacyAllowance(_Model):
    """A reviewed privacy-pattern match inside an unmodified upstream fixture file."""

    source: str
    path: str
    sha256: str
    pattern: Literal["email", "home-path", "ipv4"]
    count: int = Field(ge=1)
    reason: str = Field(min_length=1)

    @field_validator("sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if not SHA256.fullmatch(value):
            raise ValueError("must be 64 lower-case hex characters")
        return value


class DocSources(_Model):
    schema_: Literal["doc-sources-v1"] = Field(alias="schema")
    pins_verified_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    repositories: dict[str, Repository]
    sources: list[Source] = Field(min_length=1)
    privacy_allowlist: list[PrivacyAllowance] = []

    @model_validator(mode="after")
    def _references(self) -> DocSources:
        ids = [source.id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source ids must be unique")
        for key in self.repositories:
            if not SOURCE_ID.fullmatch(key):
                raise ValueError(f"repository key {key!r} must match [a-z0-9]+(-[a-z0-9]+)*")
        for source in self.sources:
            if source.repository not in self.repositories:
                raise ValueError(f"source {source.id!r} names unknown repository")
        for allowance in self.privacy_allowlist:
            if allowance.source not in ids:
                raise ValueError(f"privacy_allowlist names unknown source {allowance.source!r}")
        return self

    def source(self, source_id: str) -> Source:
        return next(source for source in self.sources if source.id == source_id)

    def repository_of(self, source: Source) -> Repository:
        return self.repositories[source.repository]


def load_config(path: Path, *, allow_file_urls: bool = False) -> DocSources:
    try:
        data = json.loads(path.read_bytes())
    except FileNotFoundError:
        raise ConfigError(f"config not found: {path.name}") from None
    except (OSError, ValueError) as error:
        raise ConfigError(f"config {path.name} is not readable JSON: {error}") from None
    try:
        return DocSources.model_validate(data, context={"allow_file_urls": allow_file_urls})
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '(root)'}: {item['msg']}"
            for item in error.errors()
        )
        raise ConfigError(f"invalid config {path.name}: {details}") from None


def glob_match(pattern: str, path: str) -> bool:
    """Match a `/`-separated path: `**` is zero or more segments, `*` never crosses `/`."""
    return _match(pattern.split("/"), path.split("/"))


def _match(pattern: list[str], segments: list[str]) -> bool:
    if not pattern:
        return not segments
    if pattern[0] == "**":
        return any(_match(pattern[1:], segments[index:]) for index in range(len(segments) + 1))
    return (
        bool(segments)
        and fnmatchcase(segments[0], pattern[0])
        and _match(pattern[1:], segments[1:])
    )


def tag_for(source: Source, path: str) -> str:
    """Retrieval tag of a page: the first matching rule, otherwise `default_tag`."""
    return next(
        (rule.tag for rule in source.tags if glob_match(rule.glob, path)), source.default_tag
    )


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pin_id(source: Source, repository: Repository) -> str:
    """Snapshot identity: only what decides the selected bytes (not tags, deny or metadata)."""
    spec = {
        "schema": "doc-snapshot-v1",
        "url": repository.url,
        "commit": repository.commit,
        "root": source.root,
        "include": source.include,
        "exclude": source.exclude,
        "license_evidence": sorted([item.path, item.blob] for item in source.license_evidence),
    }
    return f"{source.id}-{sha256_hex(canonical(spec))[:16]}"


def privacy_matches(text: str) -> dict[str, int]:
    found = {name: len(pattern.findall(text)) for name, pattern in PRIVACY_PATTERNS.items()}
    return {name: count for name, count in found.items() if count}
