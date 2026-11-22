"""Build and check the committed lexicons (`reference/lexicons/<source-id>.json`).

Operator sources give the Bonsai lexicon (`lexicon_bonsai`); docs sources give the RST
lexicon (`lexicon_rst`) over their section records. Both are derived from verified
snapshots only, written in the B1 canonical layout with a digest, and must carry no
privacy-pattern match at all.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from bonsai_help import lexicon_bonsai, lexicon_rst
from bonsai_help.doc_snapshot import (
    CheckFailed,
    Problem,
    Report,
    check_snapshot,
    dump_json,
    fixture_plan,
    load_canonical,
    snapshot_dir,
    write_new,
)
from bonsai_help.doc_sources import DocSources, Source, canonical, privacy_matches, sha256_hex
from bonsai_help.docs_index import Diagnostics, index_from_snapshot, split_page

SCHEMAS = {"operator-source": lexicon_bonsai.SCHEMA, "docs": lexicon_rst.SCHEMA}
EXTRACTORS = {"operator-source": lexicon_bonsai.EXTRACTOR, "docs": lexicon_rst.EXTRACTOR}


def file_name(source: Source) -> str:
    return f"{source.id}.json"


def _document(source: Source, entry: dict, body: dict) -> dict:
    document = {
        "schema": SCHEMAS[source.role],
        "source": source.id,
        "pin_id": entry["pin_id"],
        "commit": entry["repository"]["commit"],
        "source_digest": entry["source_digest"],
        "extractor": EXTRACTORS[source.role],
        "license": source.license,
        **body,
    }
    return {**document, "digest": sha256_hex(canonical(document))}


def _operator_files(source: Source, entry: dict, snapshot: Path) -> dict[str, bytes]:
    files = snapshot / "files"
    prefix = source.root + "/"
    return {
        page["path"][len(prefix) :]: (files / page["path"]).read_bytes() for page in entry["pages"]
    }


def build_documents(config: DocSources, manifest: dict, data_root: Path) -> dict[str, dict]:
    """Every lexicon, extracted from snapshots verified against the committed manifest."""
    documents: dict[str, dict] = {}
    for built in index_from_snapshot(config, manifest, data_root):
        source = built.source
        body = lexicon_rst.extract(built.records)
        documents[file_name(source)] = _document(source, manifest["sources"][source.id], body)
    for source in config.sources:
        if source.role != "operator-source":
            continue
        entry = manifest["sources"][source.id]
        snapshot = snapshot_dir(data_root, source, config.repository_of(source))
        shown = f"snapshots/{source.id}/{snapshot.name}"
        if not snapshot.is_dir():
            raise CheckFailed(f"{source.id}: {shown} not built (run snapshot build)")
        problems = check_snapshot(source, entry, snapshot, shown)
        if problems:
            raise CheckFailed("; ".join(map(str, problems[:3])))
        try:
            body = lexicon_bonsai.extract(_operator_files(source, entry, snapshot))
        except CheckFailed as error:
            raise CheckFailed(f"{source.id}: {error}") from None
        documents[file_name(source)] = _document(source, entry, body)
    return dict(sorted(documents.items()))


def build(
    config: DocSources, manifest: dict, data_root: Path, lexicon_dir: Path, *, write: bool
) -> Report:
    report = Report()
    documents = build_documents(config, manifest, data_root)
    differing = []
    for name, document in documents.items():
        data = dump_json(document)
        target = lexicon_dir / name
        size = f"{len(data):,} bytes"
        if target.is_file() and target.read_bytes() == data:
            report.lines.append(f"{name}: unchanged ({size})")
        elif write:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}")
            write_new(temporary, data)
            os.replace(temporary, target)
            report.lines.append(f"{name}: written ({size})")
        else:
            differing.append(name)
    if differing:
        raise CheckFailed(
            f"{', '.join(differing)} differ from a rebuild; run lexicon build --write after a pin change"
        )
    return report


def _fixture_records(source: Source, entry: dict, fixtures_dir: Path) -> list[dict] | None:
    pages = frozenset(page["path"] for page in entry["pages"])
    records = []
    for path in fixture_plan(source):
        if path not in pages:
            continue
        target = fixtures_dir / source.id / path
        if not target.is_file():
            return None
        records += split_page(
            source,
            entry["pin_id"],
            entry["repository"]["commit"],
            path,
            target.read_bytes(),
            pages,
            Diagnostics(),
        )
    return records


def _check_bonsai(name: str, document: dict) -> list[Problem]:
    problems = []
    entries = document.get("entries", [])
    keys = [(e["kind"], e["id"], e["file"], e["line"]) for e in entries]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        problems.append(Problem("lexicon", name, "entries are not sorted and unique"))
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    if document["summary"].get("entries") != dict(sorted(counts.items())):
        problems.append(Problem("lexicon", name, "summary entry counts differ from the entries"))
    texts = [(u["id"], u["text"], u["file"], u["line"]) for u in document.get("ui_texts", [])]
    if texts != sorted(texts) or document["summary"].get("ui_texts") != len(texts):
        problems.append(Problem("lexicon", name, "ui_texts are not sorted or not counted"))
    ids = {e["id"] for e in entries}
    if any(u["id"] not in ids for u in document.get("ui_texts", [])):
        problems.append(Problem("lexicon", name, "a ui_text names an operator with no entry"))
    return problems


def _check_rst(name: str, document: dict, source: Source, entry: dict, fixtures_dir: Path):
    problems = []
    table = document.get("records", [])
    if table != sorted(set(table)) or any(
        not record.startswith(f"{source.id}:") for record in table
    ):
        problems.append(Problem("lexicon", name, "records are not sorted, unique and own"))
    entries = document.get("entries", [])
    keys = [(e["kind"], e["value"], e["label"] or "") for e in entries]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        problems.append(Problem("lexicon", name, "entries are not sorted and unique"))
    used = {i for e in entries for i in e["locations"]}
    if any(not 0 <= i < len(table) for i in used) or used != set(range(len(table))):
        problems.append(Problem("lexicon", name, "locations and the records table disagree"))
    if document["summary"].get("entries") != len(entries):
        problems.append(Problem("lexicon", name, "summary entry count differs from the entries"))
    if problems:
        return problems
    records = _fixture_records(source, entry, fixtures_dir)
    if records is None:
        return [Problem("lexicon", name, "fixture pages missing; run snapshot check --committed")]
    expected = lexicon_rst.resolved(lexicon_rst.extract(records))
    if lexicon_rst.restrict(document, {r["id"] for r in records}) != expected:
        problems.append(
            Problem("lexicon", name, "entries for fixture pages differ from a re-extraction")
        )
    return problems


def check_committed(
    config: DocSources, manifest: dict, lexicon_dir: Path, fixtures_dir: Path
) -> list[Problem]:
    problems: list[Problem] = []
    expected = {file_name(source): source for source in config.sources}
    present = {path.name for path in lexicon_dir.glob("*")} if lexicon_dir.is_dir() else set()
    for extra in sorted(present - set(expected)):
        problems.append(Problem("lexicon", extra, "unexpected file"))
    for name, source in sorted(expected.items()):
        path = lexicon_dir / name
        document, found = load_canonical(path, SCHEMAS[source.role], "digest", "lexicon")
        problems += found
        if document is None:
            if not found:
                problems.append(Problem("lexicon", name, "missing (run lexicon build --write)"))
            continue
        entry = manifest["sources"][source.id]
        for key, want in (
            ("source", source.id),
            ("pin_id", entry["pin_id"]),
            ("commit", entry["repository"]["commit"]),
            ("source_digest", entry["source_digest"]),
            ("extractor", EXTRACTORS[source.role]),
        ):
            if document.get(key) != want:
                problems.append(Problem("lexicon", name, f"{key} differs from the config"))
        for pattern, count in privacy_matches(path.read_bytes().decode("utf-8", "replace")).items():
            problems.append(Problem("privacy", name, f"{count} {pattern} match(es)"))
        try:
            if source.role == "operator-source":
                problems += _check_bonsai(name, document)
            else:
                problems += _check_rst(name, document, source, entry, fixtures_dir)
        except (KeyError, TypeError, AttributeError) as error:
            problems.append(Problem("lexicon", name, f"malformed ({error})"))
    return problems
