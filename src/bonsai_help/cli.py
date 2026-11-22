"""Command line: `bonsai-help snapshot | docs | lexicon | setup`.

Exit codes: 0 success; 1 check failed; 2 usage or invalid config; 3 git or network
failure; 4 upstream differs from the pins; 5 refused to write.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

from pydantic import ValidationError

from bonsai_help import doc_snapshot, docs_index, lexicons, setup
from bonsai_help.doc_sources import ConfigError, SnapshotError, load_config
from bonsai_help.git_fetch import Git, Runner, subprocess_runner

CONFIG = Path("config/doc-sources.json")
MANIFEST = Path("config/doc-manifest.json")
DATA = Path("data")
FIXTURES = Path("tests/fixtures/docs")
NOTICE = Path("NOTICE.md")
DOCS_INDEX = Path("reference/docs-index.json")
LEXICONS = Path("reference/lexicons")
PROFILES = Path("reference/setup-profiles.json")
FACTS = Path("reference/setup-facts.json")


def repository_root(start: Path) -> Path | None:
    """The nearest directory at or above `start` that holds this project's pin config."""
    for directory in [start, *start.parents]:
        if (directory / "pyproject.toml").is_file() and (directory / CONFIG).is_file():
            return directory
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bonsai-help", description="Bonsai help chatbot tools.")
    commands = parser.add_subparsers(dest="command", required=True)

    def paths(sub: argparse.ArgumentParser, *, data: bool = True, fixtures: bool = False) -> None:
        sub.add_argument("--config", type=Path, help=f"pin config (default {CONFIG})")
        sub.add_argument("--manifest", type=Path, help=f"committed manifest (default {MANIFEST})")
        if data:
            sub.add_argument(
                "--data-root", type=Path, help=f"snapshot and cache root (default {DATA}/)"
            )
        if fixtures:
            sub.add_argument("--fixtures", type=Path, help=f"fixture slice (default {FIXTURES})")
            sub.add_argument("--notice", type=Path, help=f"attribution notice (default {NOTICE})")

    def committed(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--committed", action="store_true", help="committed files only; no data root"
        )

    snapshot = commands.add_parser("snapshot", help="pinned documentation snapshots")
    actions = snapshot.add_subparsers(dest="action", required=True)
    build = actions.add_parser(
        "build", help="the one command: fetch and write absent snapshots, verify present ones"
    )
    paths(build)
    build.add_argument(
        "--write-manifest",
        action="store_true",
        help="write the manifest from the fetched bytes instead of comparing (once per pin change)",
    )
    check = actions.add_parser("check", help="verify the committed files and the built snapshots")
    paths(check, fixtures=True)
    committed(check)
    fixtures = actions.add_parser("fixtures", help="copy the fixture slice from verified snapshots")
    paths(fixtures, fixtures=True)
    fixtures.add_argument(
        "--replace", action="store_true", help="replace differing or extra fixtures"
    )

    docs = commands.add_parser("docs", help="section records and search over the snapshots")
    actions = docs.add_subparsers(dest="action", required=True)
    index = actions.add_parser("index", help="section index (data/index/) and its digest")
    steps = index.add_subparsers(dest="step", required=True)
    for name, text in (("build", "build or verify the index"), ("check", "check the index")):
        sub = steps.add_parser(name, help=text)
        paths(sub)
        sub.add_argument("--digest", type=Path, help=f"committed digest (default {DOCS_INDEX})")
        if name == "build":
            sub.add_argument(
                "--write-digest", action="store_true", help="write the digest (once per pin change)"
            )
        else:
            committed(sub)
    search = actions.add_parser("search", help="BM25 over passages of the built index")
    paths(search)
    search.add_argument("query")
    search.add_argument("--source", action="append", help="limit to a source id (repeatable)")
    search.add_argument("--tag", action="append", help="limit to a retrieval tag (repeatable)")
    search.add_argument("--top", type=int, default=10, help="results to print (default 10)")
    section = actions.add_parser("section", help="print one section record of the built index")
    paths(section)
    section.add_argument("record_id")

    lexicon = commands.add_parser("lexicon", help="operator, menu and hotkey lexicons")
    actions = lexicon.add_subparsers(dest="action", required=True)
    for name, text in (
        ("build", "extract every lexicon and compare it with the committed files"),
        ("check", "check the committed lexicons (and a rebuild unless --committed)"),
    ):
        sub = actions.add_parser(name, help=text)
        paths(sub, fixtures=name == "check")
        sub.add_argument("--lexicons", type=Path, help=f"committed lexicons (default {LEXICONS})")
        if name == "build":
            sub.add_argument("--write", action="store_true", help="write the lexicon files")
        else:
            committed(sub)

    setup_parser = commands.add_parser("setup", help="setup profiles and cited setup facts")
    actions = setup_parser.add_subparsers(dest="action", required=True)
    for name, text in (
        ("candidates", "print candidate lines for fact rows (JSON lines on stdout)"),
        ("check", "verify the profiles and every fact citation"),
        ("format", "validate and rewrite both files in canonical layout with digests"),
    ):
        sub = actions.add_parser(name, help=text)
        paths(sub, data=name != "format", fixtures=name == "check")
        sub.add_argument("--profiles", type=Path, help=f"setup profiles (default {PROFILES})")
        sub.add_argument("--facts", type=Path, help=f"setup facts (default {FACTS})")
        if name == "candidates":
            sub.add_argument("--source", action="append", help="limit to a source id")
        if name == "check":
            committed(sub)
    return parser


def _resolve(value: Path | None, default: Path, root: Path) -> Path:
    return (value if value is not None else root / default).absolute()


def _data_root(value: Path, root: Path | None) -> Path:
    resolved = value.resolve()
    if root is not None:
        repo = root.resolve()
        if resolved.is_relative_to(repo) and not resolved.is_relative_to(repo / "data"):
            raise ConfigError(
                "--data-root must be under the repository's data/ or outside the repository"
            )
    return resolved


def _redact(text: str, roots: list[tuple[Path, str]]) -> str:
    """Messages never carry absolute paths: known roots become labels, the home directory `~`."""
    for root, label in sorted(((str(path), label) for path, label in roots), reverse=True):
        text = text.replace(root, label)
    home = os.path.expanduser("~")
    return text.replace(home, "~") if home not in ("~", "/") else text


def main(
    argv: list[str] | None = None, *, allow_file_urls: bool = False, runner: Runner | None = None
) -> int:
    args = _parser().parse_args(argv)
    root = repository_root(Path.cwd())
    base = root or Path.cwd()
    shown_roots: list[tuple[Path, str]] = []
    try:
        config_path = _resolve(args.config, CONFIG, base)
        manifest_path = _resolve(args.manifest, MANIFEST, base)
        data_root = None
        if hasattr(args, "data_root") and not getattr(args, "committed", False):
            data_root = _data_root(_resolve(args.data_root, DATA, base), root)
            shown_roots.append((data_root, "<data-root>"))
        shown_roots.append((base.resolve(), "."))
        config = load_config(config_path, allow_file_urls=allow_file_urls)
        if args.command == "snapshot":
            report = _snapshot(
                args, config, config_path, manifest_path, data_root, base, runner, allow_file_urls
            )
        else:
            manifest, problems = doc_snapshot.load_manifest(manifest_path)
            problems = doc_snapshot.check_manifest(config, manifest, problems)
            if problems or manifest is None:
                raise doc_snapshot.CheckFailed("; ".join(map(str, problems[:3])))
            command = {"docs": _docs, "lexicon": _lexicon, "setup": _setup}[args.command]
            report = command(args, config, manifest, data_root, base)
    except SnapshotError as error:
        print(f"error: {_redact(str(error), shown_roots)}", file=sys.stderr)
        return error.exit_code
    for warning in report.warnings:
        print(f"warning: {_redact(warning, shown_roots)}", file=sys.stderr)
    for line in report.lines:
        print(_redact(line, shown_roots))
    return 0


def _snapshot(
    args, config, config_path, manifest_path, data_root, base, runner, allow_file_urls
) -> doc_snapshot.Report:
    if args.action == "build":
        git = Git(
            runner or subprocess_runner, allow_protocol="file" if allow_file_urls else "https"
        )
        return doc_snapshot.build(
            config, manifest_path, data_root, write_manifest=args.write_manifest, git=git
        )
    if args.action == "fixtures":
        return doc_snapshot.export_fixtures(
            config,
            manifest_path,
            data_root,
            _resolve(args.fixtures, FIXTURES, base),
            replace=args.replace,
        )
    return _check(args, config, config_path, manifest_path, data_root, base)


def _fail(problems: list) -> None:
    if problems:
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        raise doc_snapshot.CheckFailed(f"{len(problems)} problem(s) found")


def _docs(args, config, manifest, data_root, base) -> doc_snapshot.Report:
    report = doc_snapshot.Report()
    if args.action == "index":
        digest = _resolve(args.digest, DOCS_INDEX, base)
        if args.step == "build":
            return docs_index.build_index(
                config, manifest, data_root, digest, write_digest=args.write_digest
            )
        _fail(docs_index.check_index(config, manifest, data_root, digest))
        scope = "committed digest" if data_root is None else "committed digest and built index"
        report.lines.append(f"check passed: {scope}")
        return report
    records = docs_index.load_index(config, manifest, data_root)
    if args.action == "section":
        record = next((r for r in records if r["id"] == args.record_id), None)
        if record is None:
            raise doc_snapshot.CheckFailed(f"no such section: {args.record_id}")
        report.lines += [
            f"{record['id']} ({' > '.join(record['heading_path']) or '(page head)'})",
            record["text"].rstrip("\n"),
        ]
        return report
    if args.top < 1:
        raise ConfigError("--top must be at least 1")
    known = {source.id for source in docs_index.docs_sources(config)}
    for name in args.source or []:
        if name not in known:
            raise ConfigError(f"--source {name} is not a docs source")
    chosen = [
        r
        for r in records
        if (not args.source or r["source"] in args.source)
        and (not args.tag or r["tag"] in args.tag)
    ]
    order = {source.id: i for i, source in enumerate(config.sources)}
    rows, _ = docs_index.passages(chosen, order)
    kept, _ = docs_index.finalize_passages(rows)
    by_id = {r["id"]: r for r in chosen}
    for rank, hit in enumerate(docs_index.search(kept, args.query, args.top), 1):
        record = by_id[hit.passage.record_id]
        heading = " > ".join(record["heading_path"]) or "(page head)"
        report.lines.append(
            f"{rank}\t{hit.score:.4f}\t{hit.passage.record_id}\tL{hit.passage.start}-L{hit.passage.end}\t{heading}"
        )
    if not report.lines:
        report.lines.append("no passage matches the query")
    return report


def _lexicon(args, config, manifest, data_root, base) -> doc_snapshot.Report:
    directory = _resolve(args.lexicons, LEXICONS, base)
    if args.action == "build":
        return lexicons.build(config, manifest, data_root, directory, write=args.write)
    fixtures = _resolve(args.fixtures, FIXTURES, base)
    _fail(_committed_files(args, config, base))
    _fail(lexicons.check_committed(config, manifest, directory, fixtures))
    report = doc_snapshot.Report()
    if data_root is not None:
        lexicons.build(config, manifest, data_root, directory, write=False)
    scope = "committed lexicons" if data_root is None else "committed lexicons and a rebuild"
    report.lines.append(f"check passed: {scope}")
    return report


def _setup(args, config, manifest, data_root, base) -> doc_snapshot.Report:
    profiles = _resolve(args.profiles, PROFILES, base)
    facts = _resolve(args.facts, FACTS, base)
    report = doc_snapshot.Report()
    if args.action == "format":
        for path, schema, model in (
            (profiles, setup.PROFILES_SCHEMA, setup.SetupProfiles),
            (facts, setup.FACTS_SCHEMA, setup.SetupFacts),
        ):
            try:
                data = setup.format_document(path, schema, model)
            except OSError:
                raise doc_snapshot.CheckFailed(f"{path.name}: cannot be read") from None
            except ValidationError as error:
                first = error.errors()[0]
                where = ".".join(str(part) for part in first["loc"])
                raise doc_snapshot.CheckFailed(
                    f"{path.name}: invalid: {where}: {first['msg']}"
                ) from None
            except ValueError as error:
                raise doc_snapshot.CheckFailed(f"{path.name}: {error}") from None
            if path.read_bytes() != data:
                temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
                doc_snapshot.write_new(temporary, data)
                os.replace(temporary, path)
                report.lines.append(f"{path.name}: rewritten")
            else:
                report.lines.append(f"{path.name}: unchanged")
        return report
    if args.action == "candidates":
        records = docs_index.load_index(config, manifest, data_root)
        for row in setup.candidates(records, args.source):
            report.lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return report
    fixtures = _resolve(args.fixtures, FIXTURES, base)
    _fail(_committed_files(args, config, base))
    if data_root is None:
        read, index = setup.page_bytes_offline(fixtures), None
    else:
        records = docs_index.load_index(config, manifest, data_root)
        index = {r["id"]: r["sha256"] for r in records}
        read = _snapshot_reader(config, manifest, data_root)
    _fail(setup.check_setup(config, manifest, profiles, facts, read, index))
    scope = "fixture slice" if data_root is None else "snapshots and built index"
    report.lines.append(f"check passed: profiles and every fact citation against the {scope}")
    return report


def _committed_files(args, config, base) -> list:
    """The B1 committed checks, so fixture pages read later are hash-verified."""
    return doc_snapshot.check_committed(
        config,
        _resolve(args.config, CONFIG, base),
        _resolve(args.manifest, MANIFEST, base),
        _resolve(args.fixtures, FIXTURES, base),
        _resolve(args.notice, NOTICE, base),
    )


def _snapshot_reader(config, manifest, data_root):
    for source in docs_index.docs_sources(config):
        snapshot = doc_snapshot.snapshot_dir(data_root, source, config.repository_of(source))
        shown = f"snapshots/{source.id}/{snapshot.name}"
        _fail(doc_snapshot.check_snapshot(source, manifest["sources"][source.id], snapshot, shown))

    def read(source_id: str, path: str) -> bytes | None:
        source = config.source(source_id)
        target = doc_snapshot.snapshot_dir(data_root, source, config.repository_of(source))
        target = target / "files" / path
        return target.read_bytes() if target.is_file() else None

    return read


def _check(
    args, config, config_path: Path, manifest_path: Path, data_root: Path | None, base: Path
):
    fixtures_dir = _resolve(args.fixtures, FIXTURES, base)
    notice_path = _resolve(args.notice, NOTICE, base)
    problems = doc_snapshot.check_committed(
        config, config_path, manifest_path, fixtures_dir, notice_path
    )
    report = doc_snapshot.Report()
    if not problems and data_root is not None:
        manifest, _ = doc_snapshot.load_manifest(manifest_path)
        problems = doc_snapshot.check_snapshots(config, manifest, data_root)
        report.warnings += doc_snapshot.stale_staging(data_root, config)
    if problems:
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        raise doc_snapshot.CheckFailed(f"{len(problems)} problem(s) found")
    scope = "committed files" if data_root is None else "committed files and snapshots"
    report.lines.append(f"check passed: {scope} for {len(config.sources)} sources")
    return report
