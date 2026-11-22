"""Command line: `bonsai-help snapshot | docs | lexicon | setup | gold`.

Exit codes: 0 success; 1 check failed; 2 usage or invalid config; 3 git or network
failure; 4 upstream differs from the pins; 5 refused to write.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import secrets
import sys
from pathlib import Path

from pydantic import ValidationError

from bonsai_help import doc_snapshot, docs_index, gold, gold_review, lexicons, setup, setup_review
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
GOLD = Path("reference/gold")


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
    review = actions.add_parser(
        "review", help="Chad's review of the fact rows, profiles and version lines (packets)"
    )
    steps = review.add_subparsers(dest="step", required=True)
    for name, text in (
        ("export", "write packets of pending records"),
        ("import", "record Chad's decisions (interactive terminal only)"),
        ("apply", "write Chad's decisions into the setup files (compare unless --write)"),
    ):
        sub = steps.add_parser(name, help=text)
        paths(sub, fixtures=True)
        sub.add_argument("--profiles", type=Path, help=f"setup profiles (default {PROFILES})")
        sub.add_argument("--facts", type=Path, help=f"setup facts (default {FACTS})")
        if name == "export":
            sub.add_argument("--size", type=int, default=setup_review.DEFAULT_SIZE)
            sub.add_argument("--records", nargs="+", help="re-export these records")
        if name == "import":
            sub.add_argument("packet", help="SR-NNN or its .md file")
            sub.add_argument("--decided-on", help="decision date, YYYY-MM-DD (default today)")
            sub.add_argument(
                "--skip-stale", action="store_true", help="import the blocks that are current"
            )
        if name == "apply":
            sub.add_argument("--write", action="store_true", help="write the setup files")

    gold_parser = commands.add_parser("gold", help="gold set: slots, drafts, review, publish")
    actions = gold_parser.add_subparsers(dest="action", required=True)

    def gold_paths(sub: argparse.ArgumentParser, *, data: bool = True) -> None:
        paths(sub, data=data, fixtures=True)
        sub.add_argument("--gold", type=Path, help=f"published gold files (default {GOLD})")
        sub.add_argument("--profiles", type=Path, help=f"setup profiles (default {PROFILES})")
        sub.add_argument("--facts", type=Path, help=f"setup facts (default {FACTS})")
        sub.add_argument("--lexicons", type=Path, help=f"committed lexicons (default {LEXICONS})")
        sub.add_argument("--digest", type=Path, help=f"docs-index digest (default {DOCS_INDEX})")

    sub = actions.add_parser("slots", help="regenerate the slot plan and compare or write it")
    gold_paths(sub, data=False)
    sub.add_argument("--write", action="store_true", help="write reference/gold/slots.json")
    sub = actions.add_parser("ingest", help="validate a lane batch and write its drafts")
    gold_paths(sub)
    sub.add_argument("batch", type=Path)
    sub.add_argument(
        "--supersede-accepted",
        action="store_true",
        help="replace a head Chad accepted (the item returns to pending)",
    )
    sub = actions.add_parser("check", help="check the published files (and drafts)")
    gold_paths(sub)
    committed(sub)
    sub.add_argument("--complete", action="store_true", help="every slot published (B3 acceptance)")
    sub.add_argument("--drafts", action="store_true", help="also check every draft head")
    sub = actions.add_parser("status", help="per slot: head, check, decision, published")
    gold_paths(sub)
    packet = actions.add_parser("packet", help="review packets for Chad")
    steps = packet.add_subparsers(dest="step", required=True)
    sub = steps.add_parser("export", help="write packets of pending items")
    gold_paths(sub)
    sub.add_argument("--split", required=True, choices=("development", "held_out"))
    sub.add_argument("--size", type=int, default=gold_review.DEFAULT_SIZE)
    sub.add_argument("--items", nargs="+", help="re-export these items for a re-decision")
    sub = steps.add_parser("import", help="record Chad's decisions (interactive terminal only)")
    gold_paths(sub)
    sub.add_argument("packet", help="GP-NNN or its .md file")
    sub.add_argument("--decided-on", help="decision date, YYYY-MM-DD (default today)")
    sub.add_argument("--skip-stale", action="store_true", help="import the blocks that are current")
    sub = actions.add_parser("publish", help="build reference/gold from Chad's decisions")
    gold_paths(sub)
    sub.add_argument("--write", action="store_true", help="write the published files")
    sub = actions.add_parser("score", help="pattern scores of development items (JSON lines)")
    gold_paths(sub, data=False)
    sub.add_argument("answers", type=Path, help='JSON lines: {"item_id": ..., "fields": {...}}')
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
            command = {"docs": _docs, "lexicon": _lexicon, "setup": _setup, "gold": _gold}
            report = command[args.command](args, config, manifest, data_root, base)
    except SnapshotError as error:
        for problem in getattr(error, "problems", []):
            print(f"problem: {_redact(problem, shown_roots)}", file=sys.stderr)
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
    if args.action == "review":
        return _setup_review(args, config, manifest, data_root, base, profiles, facts)
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


def _setup_review(args, config, manifest, data_root, base, profiles_path, facts_path):
    confirm = None
    if args.step == "import":
        confirm = _interactive_confirm(Path(args.packet).name.removesuffix(".md"))
    _fail(_committed_files(args, config, base))
    records = docs_index.load_index(config, manifest, data_root)
    state = setup_review.SetupState(
        config=config,
        manifest=manifest,
        profiles=_load_reference(profiles_path, setup.PROFILES_SCHEMA, setup.SetupProfiles),
        facts=_load_reference(facts_path, setup.FACTS_SCHEMA, setup.SetupFacts),
        read=_snapshot_reader(config, manifest, data_root),
        index={r["id"]: r["sha256"] for r in records},
    )
    store = gold_review.Store(data_root / "setup-review")
    today = datetime.date.today().isoformat()
    if args.step == "export":
        return setup_review.export_packets(
            store, state, size=args.size, records=args.records, exported_on=today
        )
    if args.step == "import":
        return setup_review.import_packet(
            store,
            state,
            Path(args.packet).name.removesuffix(".md"),
            decided_on=args.decided_on or today,
            skip_stale=args.skip_stale,
            confirm=confirm,
        )
    return setup_review.apply(store, state, profiles_path, facts_path, write=args.write)


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


def _interactive_confirm(packet_id: str):
    """Import records Chad's decisions, so it runs only from his own interactive terminal and
    after he types the confirmation; agent shells are not interactive."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ConfigError(
            "packet import needs an interactive terminal: Chad runs it himself (AGENTS.md)"
        )

    def confirm(summary: str) -> bool:
        print(summary)
        wanted = f"import {packet_id}"
        return input(f'Type "{wanted}" to record these decisions as yours: ').strip() == wanted

    return confirm


def _load_reference(path: Path, schema: str, model):
    document, problems = doc_snapshot.load_canonical(path, schema, "digest", "setup")
    if document is None:
        raise doc_snapshot.CheckFailed(f"{path.name}: missing or unreadable")
    if problems:
        raise doc_snapshot.CheckFailed("; ".join(map(str, problems[:3])))
    try:
        return model.model_validate(document)
    except ValidationError as error:
        raise doc_snapshot.CheckFailed(f"{path.name}: invalid: {gold.validation_message(error)}")


def _gold_context(args, config, manifest, data_root, base, *, offline: bool) -> gold.Context:
    profiles = _load_reference(
        _resolve(args.profiles, PROFILES, base), setup.PROFILES_SCHEMA, setup.SetupProfiles
    )
    facts = _load_reference(_resolve(args.facts, FACTS, base), setup.FACTS_SCHEMA, setup.SetupFacts)
    gold_dir = _resolve(args.gold, GOLD, base)
    slots, problems = gold.check_slots(gold_dir, profiles)
    _fail(problems)
    lexicon_dir = _resolve(args.lexicons, LEXICONS, base)
    _fail(
        lexicons.check_committed(
            config, manifest, lexicon_dir, _resolve(args.fixtures, FIXTURES, base)
        )
    )
    documents = {
        source.id: json.loads((lexicon_dir / f"{source.id}.json").read_bytes())
        for source in config.sources
    }
    digests = gold.current_digests(
        config, manifest, lexicon_dir, _resolve(args.digest, DOCS_INDEX, base), slots
    )
    if offline:
        read, index = setup.page_bytes_offline(_resolve(args.fixtures, FIXTURES, base)), None
    else:
        records = docs_index.load_index(config, manifest, data_root)
        index = {r["id"]: r["sha256"] for r in records}
        read = _snapshot_reader(config, manifest, data_root)
    return gold.Context(
        config=config,
        manifest=manifest,
        profiles=profiles,
        facts=facts,
        slots={slot["id"]: slot for slot in slots["slots"]},
        lexicons=gold.gp.Lexicons(documents),
        read=read,
        digests=digests,
        index=index,
    )


def _gold(args, config, manifest, data_root, base) -> doc_snapshot.Report:
    gold_dir = _resolve(args.gold, GOLD, base)
    if args.action == "slots":
        profiles = _load_reference(
            _resolve(args.profiles, PROFILES, base), setup.PROFILES_SCHEMA, setup.SetupProfiles
        )
        return gold.write_slots(gold_dir, profiles, write=args.write)
    if args.action == "check" and args.drafts and data_root is None:
        raise ConfigError("--drafts reads the draft heads in the data root; drop --committed")
    confirm = None
    if args.action == "packet" and args.step == "import":
        confirm = _interactive_confirm(Path(args.packet).name.removesuffix(".md"))
    _fail(_committed_files(args, config, base))
    offline = data_root is None
    ctx = _gold_context(args, config, manifest, data_root, base, offline=offline)
    if args.action == "score":
        return gold.score_file(gold_dir, ctx, args.answers)
    if args.action == "check":
        problems, warnings = gold.check_committed_set(gold_dir, ctx, complete=args.complete)
        if args.drafts:
            store = gold_review.Store(data_root / "gold")
            heads = store.head_items(store.heads())
            problems += gold_review.check_heads(heads, heads, ctx)
        _fail(problems)
        report = doc_snapshot.Report(warnings=warnings)
        scope = "fixture slice" if offline else "snapshots and built index"
        drafts = " and every draft head" if args.drafts else ""
        report.lines.append(
            f"check passed: slot plan and published gold items{drafts} against the {scope}"
        )
        return report
    store = gold_review.Store(data_root / "gold")
    if args.action == "ingest":
        return gold_review.ingest(
            store, ctx, args.batch.absolute(), supersede_accepted=args.supersede_accepted
        )
    if args.action == "status":
        return gold_review.status(store, ctx, gold_dir)
    if args.action == "publish":
        return gold_review.publish(store, ctx, gold_dir, write=args.write)
    today = datetime.date.today().isoformat()
    if args.step == "export":
        return gold_review.export_packets(
            store, ctx, args.split, size=args.size, items=args.items, exported_on=today
        )
    return gold_review.import_packet(
        store,
        ctx,
        Path(args.packet).name.removesuffix(".md"),
        decided_on=args.decided_on or today,
        skip_stale=args.skip_stale,
        confirm=confirm,
    )
