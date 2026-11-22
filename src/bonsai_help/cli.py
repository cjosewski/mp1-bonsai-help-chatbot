"""Command line: `bonsai-help snapshot build | check | fixtures`.

Exit codes: 0 success; 1 check failed; 2 usage or invalid config; 3 git or network
failure; 4 upstream differs from the pins; 5 refused to write.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from bonsai_help import doc_snapshot
from bonsai_help.doc_sources import ConfigError, SnapshotError, load_config
from bonsai_help.git_fetch import Git, Runner, subprocess_runner

CONFIG = Path("config/doc-sources.json")
MANIFEST = Path("config/doc-manifest.json")
DATA = Path("data")
FIXTURES = Path("tests/fixtures/docs")
NOTICE = Path("NOTICE.md")


def repository_root(start: Path) -> Path | None:
    """The nearest directory at or above `start` that holds this project's pin config."""
    for directory in [start, *start.parents]:
        if (directory / "pyproject.toml").is_file() and (directory / CONFIG).is_file():
            return directory
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bonsai-help", description="Bonsai help chatbot tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="pinned documentation snapshots")
    actions = snapshot.add_subparsers(dest="action", required=True)

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
    check.add_argument(
        "--committed", action="store_true", help="committed files only; no data root"
    )
    fixtures = actions.add_parser("fixtures", help="copy the fixture slice from verified snapshots")
    paths(fixtures, fixtures=True)
    fixtures.add_argument(
        "--replace", action="store_true", help="replace differing or extra fixtures"
    )
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
        if args.action == "build":
            git = Git(
                runner or subprocess_runner, allow_protocol="file" if allow_file_urls else "https"
            )
            report = doc_snapshot.build(
                config, manifest_path, data_root, write_manifest=args.write_manifest, git=git
            )
        elif args.action == "fixtures":
            report = doc_snapshot.export_fixtures(
                config,
                manifest_path,
                data_root,
                _resolve(args.fixtures, FIXTURES, base),
                replace=args.replace,
            )
        else:
            report = _check(args, config, config_path, manifest_path, data_root, base)
    except SnapshotError as error:
        print(f"error: {_redact(str(error), shown_roots)}", file=sys.stderr)
        return error.exit_code
    for warning in report.warnings:
        print(f"warning: {_redact(warning, shown_roots)}", file=sys.stderr)
    for line in report.lines:
        print(_redact(line, shown_roots))
    return 0


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
