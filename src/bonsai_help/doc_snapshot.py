"""Build and check pinned, hashed documentation snapshots and the committed fixture slice.

Layout under the data root (outside Git):

    git/<repository-key>/                    disposable bare partial-clone cache
    snapshots/<source-id>/<pin-id>/files/    raw blob bytes, exactly as committed upstream
    snapshots/<source-id>/<pin-id>/manifest.json, receipt.json (written last)
    snapshots/<source-id>/.staging-*         an interrupted build, left for inspection
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bonsai_help import __version__
from bonsai_help.doc_sources import (
    CATEGORIES,
    ConfigError,
    DocSources,
    PinMismatch,
    Refused,
    Repository,
    SnapshotError,
    Source,
    canonical,
    code_span_path,
    glob_match,
    pin_id,
    privacy_matches,
    sha256_hex,
    tag_for,
)
from bonsai_help.git_fetch import (
    REGULAR_MODES,
    Git,
    RefObservation,
    TreeEntry,
    ensure_cache,
    ensure_commit,
    fetch_blobs,
    git_blob_id,
    list_tree,
    read_blobs,
    resolve_ref,
)

MANIFEST_SCHEMA = "doc-manifest-v1"
FIXTURES_SCHEMA = "doc-fixtures-v1"
RECEIPT_SCHEMA = "doc-snapshot-receipt-v1"
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
PYTHON_CODE = re.compile(
    rb"^[ \t]*\.\.[ \t]+(?:(?:code-block|code|sourcecode|highlight)::[ \t]*"
    rb"(?:python\d*|py\d*|pycon|ipython\d*)\b|literalinclude::)",
    re.MULTILINE,
)


class CheckFailed(SnapshotError):
    exit_code = 1


@dataclass(frozen=True)
class Problem:
    source: str
    path: str
    message: str

    def __str__(self) -> str:
        return (
            f"{self.source}: {self.path}: {self.message}"
            if self.path
            else f"{self.source}: {self.message}"
        )


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- canonical files -------------------------------------------------------------------


def _scalar(value: object) -> bool:
    return not isinstance(value, dict | list)


def _render(value: object, depth: int) -> str:
    if _scalar(value):
        return json.dumps(value, ensure_ascii=False)
    if not value or all(
        _scalar(item) for item in (value.values() if isinstance(value, dict) else value)
    ):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(", ", ": "))
    pad, inner = "  " * depth, "  " * (depth + 1)
    if isinstance(value, dict):
        body = ",\n".join(
            f"{inner}{json.dumps(key, ensure_ascii=False)}: {_render(value[key], depth + 1)}"
            for key in sorted(value)
        )
        return "{\n" + body + "\n" + pad + "}"
    return "[\n" + ",\n".join(inner + _render(item, depth + 1) for item in value) + "\n" + pad + "]"


def dump_json(value: object) -> bytes:
    """Canonical layout: sorted keys, two-space indent, flat records on one line."""
    return (_render(value, 0) + "\n").encode()


def _digest_of(document: dict, key: str) -> str:
    return sha256_hex(canonical({name: item for name, item in document.items() if name != key}))


def _with_digest(document: dict, key: str) -> dict:
    return {**document, key: _digest_of(document, key)}


def load_canonical(
    path: Path, schema: str, digest_key: str, label: str
) -> tuple[dict | None, list[Problem]]:
    """Read a committed JSON file; absent gives (None, []). Layout, schema and digest are checked."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, []
    try:
        document = json.loads(raw)
    except ValueError as error:
        return None, [Problem(label, path.name, f"not valid JSON: {error}")]
    if not isinstance(document, dict) or document.get("schema") != schema:
        return None, [Problem(label, path.name, f"schema is not {schema}")]
    problems = []
    if raw != dump_json(document):
        problems.append(
            Problem(label, path.name, "not in canonical layout (rewrite it with the tool)")
        )
    if document.get(digest_key) != _digest_of(document, digest_key):
        problems.append(Problem(label, path.name, f"{digest_key} does not match its content"))
    return document, problems


def load_manifest(path: Path) -> tuple[dict | None, list[Problem]]:
    return load_canonical(path, MANIFEST_SCHEMA, "manifest_digest", "manifest")


# --- selection and manifest entries ----------------------------------------------------


@dataclass(frozen=True)
class Selection:
    pages: dict[str, str]
    evidence: dict[str, str]
    not_selected: dict[str, int]


def _kind(entry: TreeEntry) -> str:
    if entry.type == "commit":
        return "(submodule)"
    if entry.mode == "120000":
        return "(symlink)"
    name = entry.path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name[1:] else "(none)"


def _regular(entry: TreeEntry) -> bool:
    return entry.type == "blob" and entry.mode in REGULAR_MODES


def _safe(path: str) -> bool:
    segments = path.split("/")
    try:
        path.encode()
    except UnicodeEncodeError:
        return False
    return "\\" not in path and all(segment not in ("", ".", "..") for segment in segments)


def _selected(source: Source, path: str) -> bool:
    return any(glob_match(glob, path) for glob in source.include) and not any(
        glob_match(glob, path) for glob in source.exclude
    )


def select(source: Source, entries: list[TreeEntry]) -> Selection:
    """Apply the source's rules to a tree listing; no blob is needed."""
    under = [entry for entry in entries if entry.path.startswith(source.root + "/")]
    if not under:
        raise PinMismatch(f"{source.id}: root {source.root} is absent at the pinned commit")
    pages: dict[str, str] = {}
    not_selected: Counter[str] = Counter()
    bad, denied = [], []
    for entry in under:
        if not _selected(source, entry.path):
            not_selected[_kind(entry)] += 1
        elif not _safe(entry.path):
            bad.append(f"{entry.path!r} is not a safe UTF-8 path")
        elif not _regular(entry):
            bad.append(f"{entry.path} is mode {entry.mode} {entry.type}, not a regular file")
        elif any(glob_match(glob, entry.path) for glob in source.deny):
            denied.append(entry.path)
        else:
            pages[entry.path] = entry.oid
    if denied:
        raise ConfigError(
            f"{source.id}: include selects {len(denied)} denied files, e.g. {denied[0]}; narrow include"
        )
    if bad:
        raise PinMismatch(f"{source.id}: " + "; ".join(bad[:5]))
    if not pages:
        raise PinMismatch(f"{source.id}: include selects no page at the pinned commit")
    by_path = {entry.path: entry for entry in entries}
    evidence = {}
    for item in source.license_evidence:
        entry = by_path.get(item.path)
        if entry is None or not _regular(entry):
            raise PinMismatch(f"{source.id}: license evidence {item.path} is absent or not a file")
        if entry.oid != item.blob:
            raise PinMismatch(
                f"{source.id}: license evidence {item.path} is {entry.oid}, pinned {item.blob}"
            )
        evidence[item.path] = entry.oid
    for page in source.fixture_pages:
        if page.path in pages:
            continue
        if page.path in by_path:
            raise ConfigError(f"{source.id}: fixture page {page.path} is not selected by include")
        raise PinMismatch(f"{source.id}: fixture page {page.path} is absent at the pinned commit")
    return Selection(pages, evidence, dict(sorted(not_selected.items())))


def repository_block(repository: Repository) -> dict:
    ref = repository.ref.model_dump(exclude_none=repository.ref.kind == "branch")
    return {"url": repository.url, "ref": ref, "commit": repository.commit}


def _record(path: str, oid: str, data: bytes) -> dict:
    if git_blob_id(data) != oid:
        raise PinMismatch(f"{path}: bytes do not hash to blob {oid}")
    if data.startswith(LFS_POINTER):
        raise PinMismatch(f"{path}: is a Git LFS pointer, not content")
    return {"path": path, "blob": oid, "sha256": sha256_hex(data), "bytes": len(data)}


def source_digest(entry: dict) -> str:
    def rows(records: list[dict]) -> list[list]:
        return [[item["path"], item["blob"], item["sha256"], item["bytes"]] for item in records]

    content = {
        "pin_id": entry["pin_id"],
        "pages": rows(entry["pages"]),
        "license_evidence": rows(entry["license_evidence"]),
    }
    return sha256_hex(canonical(content))


def source_entry(
    source: Source, repository: Repository, selection: Selection, blobs: dict[str, bytes]
) -> dict:
    pages = [_record(path, oid, blobs[oid]) for path, oid in sorted(selection.pages.items())]
    evidence = [_record(path, oid, blobs[oid]) for path, oid in sorted(selection.evidence.items())]
    entry = {
        "pin_id": pin_id(source, repository),
        "repository": repository_block(repository),
        "root": source.root,
        "pages": pages,
        "license_evidence": evidence,
        "not_selected": selection.not_selected,
        "totals": {"pages": len(pages), "bytes": sum(page["bytes"] for page in pages)},
    }
    return {**entry, "source_digest": source_digest(entry)}


def build_manifest(entries: dict[str, dict]) -> dict:
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "sources": entries,
        "totals": {
            "sources": len(entries),
            "pages": sum(entry["totals"]["pages"] for entry in entries.values()),
            "bytes": sum(entry["totals"]["bytes"] for entry in entries.values()),
        },
    }
    return _with_digest(manifest, "manifest_digest")


def tag_counts(source: Source, entry: dict) -> dict[str, int]:
    return dict(sorted(Counter(tag_for(source, page["path"]) for page in entry["pages"]).items()))


# --- committed checks ------------------------------------------------------------------


def validate_entry(source: Source, repository: Repository, entry: object) -> list[Problem]:
    """A committed manifest entry agrees with the config and with itself."""
    sid = source.id
    if not isinstance(entry, dict):
        return [Problem(sid, "", "no manifest entry")]
    try:
        problems = []
        if entry["pin_id"] != pin_id(source, repository):
            problems.append(
                Problem(
                    sid,
                    "",
                    f"pin_id {entry['pin_id']} differs from the config's {pin_id(source, repository)}",
                )
            )
        if entry["repository"] != repository_block(repository) or entry["root"] != source.root:
            problems.append(Problem(sid, "", "repository or root differs from the config"))
        if entry["source_digest"] != source_digest(entry):
            problems.append(Problem(sid, "", "source_digest does not match the page list"))
        pages = entry["pages"]
        paths = [page["path"] for page in pages]
        if paths != sorted(set(paths)):
            problems.append(Problem(sid, "", "pages are not sorted and unique"))
        for path in paths:
            if not _selected(source, path) or not path.startswith(source.root + "/"):
                problems.append(Problem(sid, path, "page is not selected by the config's rules"))
        totals = {"pages": len(pages), "bytes": sum(page["bytes"] for page in pages)}
        if entry["totals"] != totals:
            problems.append(Problem(sid, "", "totals do not match the page list"))
        declared = sorted([item.path, item.blob] for item in source.license_evidence)
        if sorted([item["path"], item["blob"]] for item in entry["license_evidence"]) != declared:
            problems.append(Problem(sid, "", "license evidence differs from the config"))
        for page in source.fixture_pages:
            if page.path not in paths:
                problems.append(Problem(sid, page.path, "fixture page is not in the manifest"))
        return problems
    except (KeyError, TypeError) as error:
        return [Problem(sid, "", f"malformed manifest entry ({error})")]


def check_manifest(
    config: DocSources, manifest: dict | None, problems: list[Problem]
) -> list[Problem]:
    problems = list(problems)
    if manifest is None:
        return problems or [Problem("manifest", "", "committed manifest is missing")]
    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        return [*problems, Problem("manifest", "", "has no sources")]
    for source in config.sources:
        problems += validate_entry(source, config.repository_of(source), sources.get(source.id))
    for extra in sorted(set(sources) - {source.id for source in config.sources}):
        problems.append(Problem("manifest", extra, "source is not in the config"))
    return problems


def _files_by_path(entry: dict) -> dict[str, dict]:
    return {item["path"]: item for item in [*entry["pages"], *entry["license_evidence"]]}


def fixture_plan(source: Source) -> dict[str, dict]:
    """Every file of the source's fixture slice: path -> roles and categories."""
    plan = {
        page.path: {"roles": ["page"], "categories": sorted(page.categories)}
        for page in source.fixture_pages
    }
    for item in source.license_evidence:
        if item.commit_copy:
            plan.setdefault(item.path, {"roles": [], "categories": []})["roles"].append("license")
    for value in plan.values():
        value["roles"].sort()
    return dict(sorted(plan.items()))


def slice_lines(data: bytes, line_start: int, line_end: int) -> bytes | None:
    """Lines `line_start` to `line_end` (1-based, inclusive) with their line ends, or None."""
    lines = data.splitlines(keepends=True)
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        return None
    return b"".join(lines[line_start - 1 : line_end])


def span_refusal(data: bytes) -> str | None:
    """Why a code span could never join the fixture slice: a code span carries no privacy
    match at all (no allowance applies; the file headers' addresses stay out of Git)."""
    found = privacy_matches(data.decode("utf-8", "replace"))
    if found:
        return ", ".join(f"{count} {pattern} match(es)" for pattern, count in found.items())
    return None


def _span_record(span, entry: dict, recorded: dict | None) -> dict:
    page = _files_by_path(entry).get(span.path)
    return {
        "path": span.path,
        "line_start": span.line_start,
        "line_end": span.line_end,
        "file_sha256": page["sha256"] if page else None,
        "blob": recorded.get("blob") if recorded else None,
        "sha256": recorded.get("sha256") if recorded else None,
        "bytes": recorded.get("bytes") if recorded else None,
    }


def committed_spans(document: dict | None) -> dict[tuple[str, str], dict]:
    """The code-span records of a fixtures document by (source id, fixture path)."""
    found = {}
    for sid, value in ((document or {}).get("sources") or {}).items():
        for record in value.get("code_spans", []) if isinstance(value, dict) else []:
            if isinstance(record, dict):
                key = code_span_path(
                    str(record.get("path")), record.get("line_start"), record.get("line_end")
                )
                found[(sid, key)] = record
    return found


def fixtures_document(
    config: DocSources, manifest: dict, spans: dict[tuple[str, str], dict] | None = None
) -> dict:
    """The fixture list. An operator-source lists its code spans; their own hashes come from
    `spans` (the export's snapshot bytes, or the committed record that the span files are then
    checked against), the file hash from the manifest."""
    sources = {}
    for source in config.sources:
        entry = manifest["sources"][source.id]
        known = _files_by_path(entry)
        files = [
            {
                **plan,
                "path": path,
                "blob": known[path]["blob"],
                "sha256": known[path]["sha256"],
                "bytes": known[path]["bytes"],
            }
            for path, plan in fixture_plan(source).items()
        ]
        sources[source.id] = {
            "pin_id": entry["pin_id"],
            "source_digest": entry["source_digest"],
            "files": files,
        }
        if source.role == "operator-source":
            sources[source.id]["code_spans"] = [
                _span_record(span, entry, (spans or {}).get((source.id, span.fixture_path)))
                for span in sorted(
                    source.fixture_code_spans, key=lambda s: (s.path, s.line_start, s.line_end)
                )
            ]
    return _with_digest({"schema": FIXTURES_SCHEMA, "sources": sources}, "digest")


def _walk_files(base: Path) -> tuple[dict[str, Path], list[str]]:
    """Regular files under base by relative path, plus anything that is not a regular file."""
    files, odd = {}, []
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        for name in [*dirnames, *filenames]:
            path = Path(directory, name)
            relative = path.relative_to(base).as_posix()
            if path.is_symlink():
                odd.append(relative)
            elif name in filenames:
                if path.is_file():
                    files[relative] = path
                else:
                    odd.append(relative)
        dirnames[:] = [name for name in dirnames if not Path(directory, name).is_symlink()]
    return files, odd


def _compare_files(sid: str, base: Path, expected: dict[str, dict], shown: str) -> list[Problem]:
    problems = []
    found, odd = _walk_files(base) if base.is_dir() else ({}, [])
    problems += [
        Problem(sid, f"{shown}/{path}", "is a symlink or not a regular file") for path in odd
    ]
    problems += [
        Problem(sid, f"{shown}/{path}", "unexpected file")
        for path in sorted(set(found) - set(expected))
    ]
    problems += [
        Problem(sid, f"{shown}/{path}", "missing") for path in sorted(set(expected) - set(found))
    ]
    for path in sorted(set(found) & set(expected)):
        data, want = found[path].read_bytes(), expected[path]
        if (
            len(data) != want["bytes"]
            or sha256_hex(data) != want["sha256"]
            or git_blob_id(data) != want["blob"]
        ):
            problems.append(Problem(sid, f"{shown}/{path}", "bytes differ from the manifest"))
    return problems


def check_fixtures(config: DocSources, manifest: dict, fixtures_dir: Path) -> list[Problem]:
    label = "fixtures"
    document, problems = load_canonical(
        fixtures_dir / "fixtures.json", FIXTURES_SCHEMA, "digest", label
    )
    if document is None:
        return problems or [Problem(label, "fixtures.json", "missing")]
    recorded = committed_spans(document)
    if {key: value for key, value in document.items() if key != "digest"} != {
        key: value
        for key, value in fixtures_document(config, manifest, recorded).items()
        if key != "digest"
    }:
        problems.append(
            Problem(
                label, "fixtures.json", "differs from the config's fixture list and the manifest"
            )
        )
    expected_top = {source.id for source in config.sources} | {"fixtures.json"}
    for child in sorted(fixtures_dir.iterdir()):
        if child.name not in expected_top or child.is_symlink():
            problems.append(Problem(label, child.name, "unexpected entry"))
    for source in config.sources:
        known = _files_by_path(manifest["sources"][source.id])
        plan = fixture_plan(source)
        expected = {path: known[path] for path in plan}
        for span in source.fixture_code_spans:
            record = recorded.get((source.id, span.fixture_path))
            if record and all(record.get(k) is not None for k in ("blob", "sha256", "bytes")):
                expected[span.fixture_path] = record
        base = fixtures_dir / source.id
        problems += _compare_files(source.id, base, expected, f"fixtures/{source.id}")
        for category in CATEGORIES:
            count = sum(category in value["categories"] for value in plan.values())
            if count < source.fixture_min_per_category:
                problems.append(
                    Problem(
                        source.id,
                        "",
                        f"fixture slice has {count} {category} pages, needs {source.fixture_min_per_category}",
                    )
                )
        if source.fixture_forbid_python:
            for path in plan:
                target = base / path
                if (
                    target.is_file()
                    and not target.is_symlink()
                    and PYTHON_CODE.search(target.read_bytes())
                ):
                    problems.append(
                        Problem(
                            source.id,
                            path,
                            "fixture contains Python code, excluded from this source's license",
                        )
                    )
    return problems


def check_privacy(config: DocSources, written: list[Path], fixtures_dir: Path) -> list[Problem]:
    """Repository-written files: no match at all. Upstream fixture bytes: reviewed allowances only."""
    problems = []
    for path in written:
        if path.is_file():
            for pattern, count in privacy_matches(
                path.read_bytes().decode("utf-8", "replace")
            ).items():
                problems.append(Problem("privacy", path.name, f"{count} {pattern} match(es)"))
    allowances = {(item.source, item.path, item.pattern): item for item in config.privacy_allowlist}
    used = set()
    for source in config.sources:
        for path in fixture_plan(source):
            target = fixtures_dir / source.id / path
            if not target.is_file() or target.is_symlink():
                continue
            data = target.read_bytes()
            for pattern, count in privacy_matches(data.decode("utf-8", "replace")).items():
                allowance = allowances.get((source.id, path, pattern))
                if allowance and allowance.sha256 == sha256_hex(data) and allowance.count == count:
                    used.add((source.id, path, pattern))
                else:
                    problems.append(
                        Problem(
                            source.id,
                            path,
                            f"{count} {pattern} match(es) without a reviewed allowance",
                        )
                    )
    for source in config.sources:
        for span in source.fixture_code_spans:
            target = fixtures_dir / source.id / span.fixture_path
            if target.is_file() and not target.is_symlink():
                refusal = span_refusal(target.read_bytes())
                if refusal:
                    problems.append(
                        Problem(source.id, span.fixture_path, f"code span holds {refusal}")
                    )
    for key in sorted(set(allowances) - used):
        problems.append(
            Problem(key[0], key[1], f"privacy allowance for {key[2]} no longer matches")
        )
    return problems


def fixture_refusal(config: DocSources, source: Source, path: str, data: bytes) -> str | None:
    """Why a page could never join the source's fixture slice, or None.

    The rules of `check_privacy` and `check_fixtures`: a privacy-pattern match needs a reviewed
    allowance for these exact bytes, and a source that forbids Python code in fixtures refuses
    a page holding a Python code block."""
    allowances = {(item.source, item.path, item.pattern): item for item in config.privacy_allowlist}
    for pattern, count in privacy_matches(data.decode("utf-8", "replace")).items():
        allowance = allowances.get((source.id, path, pattern))
        if not (allowance and allowance.sha256 == sha256_hex(data) and allowance.count == count):
            return f"{count} {pattern} match(es) without a reviewed allowance"
    if source.fixture_forbid_python and PYTHON_CODE.search(data):
        return "contains Python code, excluded from this source's license"
    return None


def check_notice(config: DocSources, notice_path: Path) -> list[Problem]:
    try:
        text = " ".join(notice_path.read_text(encoding="utf-8").split())
    except FileNotFoundError:
        return [Problem("notice", notice_path.name, "missing")]
    return [
        Problem(source.id, notice_path.name, "does not carry the source's attribution")
        for source in config.sources
        if " ".join(source.attribution.split()) not in text
    ]


def check_committed(
    config: DocSources,
    config_path: Path,
    manifest_path: Path,
    fixtures_dir: Path,
    notice_path: Path,
) -> list[Problem]:
    manifest, problems = load_manifest(manifest_path)
    problems = check_manifest(config, manifest, problems)
    if problems or manifest is None:
        return problems
    problems += check_fixtures(config, manifest, fixtures_dir)
    problems += check_notice(config, notice_path)
    written = [config_path, manifest_path, fixtures_dir / "fixtures.json", notice_path]
    return problems + check_privacy(config, written, fixtures_dir)


# --- snapshot checks -------------------------------------------------------------------


def snapshot_dir(data_root: Path, source: Source, repository: Repository) -> Path:
    return data_root / "snapshots" / source.id / pin_id(source, repository)


def check_snapshot(source: Source, entry: dict, snapshot: Path, shown: str) -> list[Problem]:
    """The snapshot holds exactly the entry's files, byte for byte, and is complete."""
    sid = source.id
    problems = []
    try:
        json.loads((snapshot / "receipt.json").read_bytes())
    except (OSError, ValueError):
        problems.append(
            Problem(sid, f"{shown}/receipt.json", "missing or unreadable (incomplete build)")
        )
    try:
        own = json.loads((snapshot / "manifest.json").read_bytes())
        # Every field but the repository block, which follows the config (see _own_entry),
        # so fields outside source_digest, such as not_selected, are compared too.
        if canonical({**own, "repository": None}) != canonical({**entry, "repository": None}):
            problems.append(
                Problem(sid, f"{shown}/manifest.json", "differs from the committed entry")
            )
        elif source_digest(own) != own["source_digest"]:
            problems.append(
                Problem(sid, f"{shown}/manifest.json", "source_digest does not match its pages")
            )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        problems.append(Problem(sid, f"{shown}/manifest.json", "missing or malformed"))
    return problems + _compare_files(
        sid, snapshot / "files", _files_by_path(entry), f"{shown}/files"
    )


def stale_staging(data_root: Path, config: DocSources) -> list[str]:
    found = []
    for source in config.sources:
        parent = data_root / "snapshots" / source.id
        if parent.is_dir():
            found += [
                f"{source.id}: interrupted build left snapshots/{source.id}/{child.name}; inspect it"
                for child in sorted(parent.glob(".staging-*"))
            ]
    return found


def check_snapshots(config: DocSources, manifest: dict, data_root: Path) -> list[Problem]:
    problems = []
    for source in config.sources:
        repository = config.repository_of(source)
        snapshot = snapshot_dir(data_root, source, repository)
        shown = f"snapshots/{source.id}/{snapshot.name}"
        if not snapshot.is_dir():
            problems.append(Problem(source.id, shown, "not built (run snapshot build)"))
        else:
            problems += check_snapshot(source, manifest["sources"][source.id], snapshot, shown)
    return problems


def span_from_snapshot(source: Source, manifest: dict, snapshot: Path, span) -> tuple[bytes, str]:
    """A code span's bytes from a built snapshot, or a problem (file hash, range, privacy)."""
    page = _files_by_path(manifest["sources"][source.id]).get(span.path)
    target = snapshot / "files" / span.path
    if page is None or not target.is_file() or sha256_hex(target.read_bytes()) != page["sha256"]:
        return b"", "file missing from the snapshot or its hash differs from the manifest"
    data = slice_lines(target.read_bytes(), span.line_start, span.line_end)
    if data is None:
        return b"", "line span is outside the file"
    refusal = span_refusal(data)
    if refusal:
        return b"", f"code span holds {refusal}; it cannot join the fixture slice"
    return data, ""


def read_code_span(
    config: DocSources,
    manifest: dict,
    read,
    source_id: str,
    path: str,
    line_start: int,
    line_end: int,
) -> bytes | str:
    """A code span's bytes, or a problem. `read(source, path)` gives a snapshot file (full
    mode: hash-checked against the manifest, then sliced) or, offline, nothing for the file and
    the span's own fixture (`<path>.L<first>-L<last>`, which `check_fixtures` hash-checks)."""
    source = next((s for s in config.sources if s.id == source_id), None)
    if source is None or source.role != "operator-source":
        return f"unknown add-on source {source_id}"
    page = _files_by_path(manifest["sources"][source_id]).get(path)
    if page is None:
        return f"{source_id}:{path} is not a file of the pin"
    data = read(source_id, path)
    if data is not None:
        if sha256_hex(data) != page["sha256"]:
            return f"{source_id}:{path}: file hash differs from the manifest"
        span = slice_lines(data, line_start, line_end)
        return span if span is not None else f"{source_id}:{path}: lines outside the file"
    span = read(source_id, code_span_path(path, line_start, line_end))
    if span is None:
        return (
            f"{source_id}:{path}#L{line_start}-L{line_end} is not in the fixture slice "
            "(add it to fixture_code_spans and run snapshot fixtures, or check against the snapshots)"
        )
    return span


def check_code_spans(config: DocSources, manifest: dict, data_root: Path, fixtures_dir: Path):
    """Every committed code span equals its lines in the built snapshot."""
    problems = []
    for source in config.sources:
        snapshot = snapshot_dir(data_root, source, config.repository_of(source))
        for span in source.fixture_code_spans:
            data, problem = span_from_snapshot(source, manifest, snapshot, span)
            target = fixtures_dir / source.id / span.fixture_path
            if problem:
                problems.append(Problem(source.id, span.fixture_path, problem))
            elif not target.is_file() or target.read_bytes() != data:
                problems.append(
                    Problem(source.id, span.fixture_path, "differs from the snapshot's lines")
                )
    return problems


# --- build -----------------------------------------------------------------------------


def write_new(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)


def fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_snapshot(
    data_root: Path, source_id: str, entry: dict, files: dict[str, bytes], receipt: dict
) -> None:
    """Write into a fresh staging directory, then rename it into place; never overwrite."""
    parent = data_root / "snapshots" / source_id
    parent.mkdir(parents=True, exist_ok=True)
    final = parent / entry["pin_id"]
    staging = parent / f".staging-{entry['pin_id']}-{secrets.token_hex(4)}"
    shown = f"snapshots/{source_id}/{staging.name}"
    os.mkdir(staging)
    try:
        for path, data in sorted(files.items()):
            target = staging / "files" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            write_new(target, data)
        write_new(staging / "manifest.json", dump_json(entry))
        os.sync()
        write_new(staging / "receipt.json", dump_json(receipt))
        fsync_dir(staging)
    except OSError as error:
        raise Refused(
            f"{source_id}: writing {shown} failed ({error.strerror}); inspect it"
        ) from None
    if final.exists():
        raise Refused(
            f"{source_id}: snapshots/{source_id}/{final.name} appeared during the build; left {shown}"
        )
    try:
        os.rename(staging, final)
    except OSError as error:
        raise Refused(
            f"{source_id}: could not move {shown} into place ({error.strerror})"
        ) from None
    fsync_dir(parent)


def _selection_differences(source: Source, selection: Selection, entry: dict) -> list[str]:
    differences = []
    for kind, upstream, records in (
        ("page", selection.pages, entry["pages"]),
        ("license evidence", selection.evidence, entry["license_evidence"]),
    ):
        committed = {item["path"]: item["blob"] for item in records}
        differences += [
            f"upstream {kind} {path} is not in the manifest"
            for path in sorted(set(upstream) - set(committed))
        ]
        differences += [
            f"manifest {kind} {path} is absent upstream"
            for path in sorted(set(committed) - set(upstream))
        ]
        differences += [
            f"{kind} {path} is blob {upstream[path]} upstream, {committed[path]} in the manifest"
            for path in sorted(set(upstream) & set(committed))
            if upstream[path] != committed[path]
        ]
    return differences


def _receipt(
    source: Source, entry: dict, observation: RefObservation, git_version: str, fetched: int
) -> dict:
    return {
        "schema": RECEIPT_SCHEMA,
        "source": source.id,
        "pin_id": entry["pin_id"],
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git_version,
        "package_version": __version__,
        "ref_observed": observation.record(),
        "blobs_fetched_for_repository": fetched,
    }


def _own_entry(source: Source, repository: Repository, snapshot: Path, shown: str) -> dict:
    try:
        own = json.loads((snapshot / "manifest.json").read_bytes())
        return {**own, "repository": repository_block(repository)}
    except (OSError, ValueError, TypeError):
        raise Refused(
            f"{source.id}: existing {shown} has no readable manifest.json; refusing to overwrite; inspect it"
        ) from None


def build(
    config: DocSources, manifest_path: Path, data_root: Path, *, write_manifest: bool, git: Git
) -> Report:
    """The one command: verify present snapshots offline, fetch and write absent ones."""
    report = Report()
    committed, problems = load_manifest(manifest_path)
    if problems:
        if write_manifest:
            raise Refused(
                "committed manifest is invalid; inspect it: " + "; ".join(map(str, problems[:3]))
            )
        raise CheckFailed("; ".join(map(str, problems[:5])))
    committed_entries = committed["sources"] if committed else {}
    if not write_manifest:
        for source in config.sources:
            entry = committed_entries.get(source.id)
            if not isinstance(entry, dict) or entry.get("pin_id") != pin_id(
                source, config.repository_of(source)
            ):
                raise ConfigError(
                    f"{source.id}: no committed manifest entry for pin {pin_id(source, config.repository_of(source))};"
                    " run snapshot build --write-manifest"
                )
        manifest_problems = check_manifest(config, committed, [])
        if manifest_problems:
            raise CheckFailed("; ".join(map(str, manifest_problems[:5])))

    entries: dict[str, dict] = {}
    absent: list[Source] = []
    for source in config.sources:
        repository = config.repository_of(source)
        snapshot = snapshot_dir(data_root, source, repository)
        shown = f"snapshots/{source.id}/{snapshot.name}"
        if not snapshot.exists():
            absent.append(source)
            continue
        reference = (
            _own_entry(source, repository, snapshot, shown)
            if write_manifest
            else committed_entries[source.id]
        )
        failures = check_snapshot(source, reference, snapshot, shown)
        if failures:
            details = "; ".join(map(str, failures[:3]))
            raise Refused(
                f"{source.id}: existing {shown} fails its check; refusing to overwrite; inspect it: {details}"
            )
        entries[source.id] = reference
        report.lines.append(f"{source.id}: {shown} present, verified, not rebuilt")

    pending: dict[str, tuple[dict, dict[str, bytes], dict]] = {}
    if absent:
        git_version = git.require_feature()
        for key in dict.fromkeys(source.repository for source in absent):
            repository = config.repositories[key]
            sources = [source for source in absent if source.repository == key]
            cache = data_root / "git" / key
            ensure_cache(git, cache, repository.url, f"git/{key}")
            observation = resolve_ref(git, cache, repository)
            if not observation.matches:
                if write_manifest and repository.ref.kind == "tag":
                    raise PinMismatch(f"{key}: {observation.problem}")
                report.warnings.append(f"{key}: {observation.problem}")
            ensure_commit(git, cache, repository.commit)
            listing = list_tree(git, cache, repository.commit)
            selections = {source.id: select(source, listing) for source in sources}
            if not write_manifest:
                for source in sources:
                    differences = _selection_differences(
                        source, selections[source.id], committed_entries[source.id]
                    )
                    if differences:
                        raise PinMismatch(
                            f"{source.id}: "
                            + "; ".join(differences[:5])
                            + f" ({len(differences)} in all)"
                        )
            wanted = {
                oid
                for selection in selections.values()
                for oid in [*selection.pages.values(), *selection.evidence.values()]
            }
            fetched = fetch_blobs(git, cache, wanted)
            blobs = read_blobs(git, cache, wanted)
            for source in sources:
                selection = selections[source.id]
                entry = source_entry(source, repository, selection, blobs)
                files = {
                    path: blobs[oid]
                    for path, oid in [*selection.pages.items(), *selection.evidence.items()]
                }
                pending[source.id] = (
                    entry,
                    files,
                    _receipt(source, entry, observation, git_version, fetched),
                )

    for source_id, (entry, _, _) in pending.items():
        old = committed_entries.get(source_id)
        if not write_manifest and canonical(entry) != canonical(old):
            raise PinMismatch(f"{source_id}: rebuilt entry differs from the committed manifest")
    if write_manifest:
        for source_id, entry in [
            *entries.items(),
            *((key, value[0]) for key, value in pending.items()),
        ]:
            old = committed_entries.get(source_id)
            if (
                isinstance(old, dict)
                and old.get("pin_id") == entry["pin_id"]
                and old.get("source_digest") != entry["source_digest"]
            ):
                raise Refused(
                    f"{source_id}: committed manifest has pin {entry['pin_id']} with different bytes; inspect it"
                )

    for source in config.sources:
        if source.id not in pending:
            continue
        entry, files, receipt = pending[source.id]
        write_snapshot(data_root, source.id, entry, files, receipt)
        snapshot = data_root / "snapshots" / source.id / entry["pin_id"]
        shown = f"snapshots/{source.id}/{snapshot.name}"
        failures = check_snapshot(source, entry, snapshot, shown)
        if failures:
            raise CheckFailed("; ".join(map(str, failures[:5])))
        entries[source.id] = entry
        counts = ", ".join(f"{tag} {count}" for tag, count in tag_counts(source, entry).items())
        report.lines.append(
            f"{source.id}: built {shown}: {entry['totals']['pages']} pages, {entry['totals']['bytes']} bytes ({counts})"
        )

    if write_manifest:
        manifest = build_manifest({source.id: entries[source.id] for source in config.sources})
        data = dump_json(manifest)
        if manifest_path.is_file() and manifest_path.read_bytes() == data:
            report.lines.append(f"{manifest_path.name} unchanged")
        else:
            temporary = manifest_path.with_name(f".{manifest_path.name}.{secrets.token_hex(4)}")
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            write_new(temporary, data)
            os.replace(temporary, manifest_path)
            report.lines.append(
                f"{manifest_path.name} written: {manifest['totals']['pages']} pages"
            )
    return report


# --- fixtures --------------------------------------------------------------------------


def export_fixtures(
    config: DocSources, manifest_path: Path, data_root: Path, fixtures_dir: Path, *, replace: bool
) -> Report:
    """Copy the fixture slice from verified snapshots; never silently replace differing files."""
    manifest, problems = load_manifest(manifest_path)
    problems = check_manifest(config, manifest, problems)
    if problems or manifest is None:
        raise CheckFailed("; ".join(map(str, problems[:5])))
    snapshot_problems = check_snapshots(config, manifest, data_root)
    if snapshot_problems:
        raise CheckFailed("; ".join(map(str, snapshot_problems[:5])))
    desired: dict[str, bytes] = {}
    spans: dict[tuple[str, str], dict] = {}
    for source in config.sources:
        snapshot = snapshot_dir(data_root, source, config.repository_of(source))
        for path in fixture_plan(source):
            desired[f"{source.id}/{path}"] = (snapshot / "files" / path).read_bytes()
        for span in source.fixture_code_spans:
            data, problem = span_from_snapshot(source, manifest, snapshot, span)
            if problem:
                raise CheckFailed(f"{source.id}: {span.fixture_path}: {problem}")
            desired[f"{source.id}/{span.fixture_path}"] = data
            spans[(source.id, span.fixture_path)] = {
                "blob": git_blob_id(data),
                "sha256": sha256_hex(data),
                "bytes": len(data),
            }
    desired["fixtures.json"] = dump_json(fixtures_document(config, manifest, spans))
    found, odd = _walk_files(fixtures_dir) if fixtures_dir.is_dir() else ({}, [])
    conflicts = [
        path
        for path in sorted(set(found) & set(desired))
        if found[path].read_bytes() != desired[path]
    ]
    extras = sorted(set(found) - set(desired))
    if odd:
        raise Refused(f"fixtures: {odd[0]} is a symlink or not a regular file; inspect it")
    if (conflicts or extras) and not replace:
        shown = [
            *(f"{path} differs" for path in conflicts),
            *(f"{path} is extra" for path in extras),
        ]
        raise Refused(
            "fixtures: " + "; ".join(shown[:5]) + "; rerun with --replace to replace them"
        )
    for path in extras:
        found[path].unlink()
    written = 0
    for path, data in desired.items():
        if path in found and path not in conflicts:
            continue
        target = fixtures_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}")
        write_new(temporary, data)
        os.replace(temporary, target)
        written += 1
    return Report(
        lines=[
            f"fixtures: {written} written, {len(desired) - written} unchanged, {len(extras)} removed"
        ]
    )
