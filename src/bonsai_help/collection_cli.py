"""Generation commands: `generate`, `gate`, `collect`, `collection-status`, `cohort`,
`cohort-status`.

Each prints one JSON summary on stdout. Exit codes: 0 done; 1 check failed, not ready, or
evidence to inspect (changed ledgers, a leftover lock, a refused gate); 2 usage or
configuration error (bad run config, missing credential, invalid count or ID, an ID that
already exists); 3 controlled exhaustion (a generation run left `incomplete`, or a
collection out of batches). Ctrl-C returns 130 with the evidence kept for `--resume`;
an interrupt that carries a note (the interrupted checkpoint failed) shows the note
instead of the resume advice. Errors are one `error:` line on stderr, the exception's
notes appended, never a traceback, and never contain the API key; the `instructor`
logger is silenced while a command runs (each attempt's error is in the attempt ledger).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

from bonsai_help import cohort, collection, gate, generate
from bonsai_help.checks import load_lexicons
from bonsai_help.config import REPOSITORY, load_config, load_prompt
from bonsai_help.doc_sources import ConfigError
from bonsai_help.doc_sources import load_config as load_doc_sources
from bonsai_help.model_client import EmbeddingClient, InstructorClient
from bonsai_help.sampler import FixtureError, SamplerError
from bonsai_help.schemas import GenerationOutput
from bonsai_help.setup import SetupProfiles
from bonsai_help.tracing import run_directory

COMMANDS = ("generate", "gate", "collect", "collection-status", "cohort", "cohort-status")
FIXTURES = Path("tests/fixtures/docs")
REFERENCE = Path("reference")
ARTIFACTS = Path("runs")
# ValueErrors (ValidationErrors among them) raised while verifying saved evidence are
# check failures (1); every other ValueError comes from settings, arguments or IDs and is
# a usage error (2).
EVIDENCE_FUNCTIONS = frozenset(
    {
        "validate_evidence",
        "recover_items",
        "_load_run",
        "_verify_gate_report",
        "read_records",
        "read_json",
    }
)


def add_commands(commands) -> None:
    def run_config(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--config", type=Path, required=True, help="run config (JSON)")

    def inputs(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--fixtures-dir", type=Path, default=FIXTURES, help=f"default {FIXTURES}")
        sub.add_argument(
            "--reference-dir", type=Path, default=REFERENCE, help=f"default {REFERENCE}"
        )

    def artifact_root(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--artifact-root",
            type=Path,
            default=ARTIFACTS,
            help=f"raw run root: {ARTIFACTS}/ or outside the repository (default {ARTIFACTS})",
        )

    sub = commands.add_parser("generate", help="generate one bounded, resumable run")
    run_config(sub)
    sub.add_argument("--run-id", required=True)
    sub.add_argument("--count", type=int, default=5, help="slots, a multiple of 5 (default 5)")
    sub.add_argument("--resume", action="store_true", help="continue an unfinished run")
    inputs(sub)
    sub = commands.add_parser("gate", help="first-pass gate of a saved run (writes once)")
    run_config(sub)
    sub.add_argument("--run-id", required=True)
    inputs(sub)
    sub = commands.add_parser("collect", help="bounded batches until enough items are retained")
    run_config(sub)
    sub.add_argument("--collection-id", required=True)
    sub.add_argument("--target-retained", type=int, default=50, help="default 50")
    sub.add_argument("--batch-count", type=int, default=70, help="slots per batch (default 70)")
    sub.add_argument("--max-batches", type=int, default=3, help="batch budget (default 3)")
    sub.add_argument("--resume", action="store_true", help="continue within the same budget")
    inputs(sub)
    sub = commands.add_parser("collection-status", help="verify a collection and show its budget")
    sub.add_argument("--collection-id", required=True)
    artifact_root(sub)
    sub = commands.add_parser("cohort", help="freeze a ready collection into a 50-item cohort")
    sub.add_argument("--collection-id", required=True)
    sub.add_argument("--cohort-id", required=True)
    artifact_root(sub)
    sub = commands.add_parser("cohort-status", help="verify a frozen cohort against its evidence")
    sub.add_argument("--cohort-id", required=True)
    artifact_root(sub)


def _repo_path(value: Path) -> Path:
    return (value if value.is_absolute() else REPOSITORY / value).resolve()


def _artifact_root(value: Path) -> Path:
    root = _repo_path(value)
    if root.is_relative_to(REPOSITORY) and not root.is_relative_to(REPOSITORY / ARTIFACTS):
        raise ValueError("--artifact-root must be runs/ or a path outside the repository")
    return root


class _Secrets:
    """The credential once read, so every message can be scrubbed of it."""

    def __init__(self) -> None:
        self.values: list[str] = []

    def key(self, config) -> str:
        value = config.api_key()
        self.values.append(value)
        return value

    def scrub(self, text: str) -> str:
        for value in self.values:
            text = text.replace(value, "[REDACTED]")
        return text


QUIET_LOGGERS = ("instructor",)


def run(args, *, transport: httpx.BaseTransport | None = None) -> int:
    """Run one command; library loggers stay quiet (the attempt ledger is the record)."""
    loggers = [logging.getLogger(name) for name in QUIET_LOGGERS]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.CRITICAL + 1)
    try:
        return _run(args, transport)
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.setLevel(level)


def _run(args, transport) -> int:
    secrets = _Secrets()
    try:
        result, code = _dispatch(args, secrets, transport)
    except KeyboardInterrupt as error:
        if _notes(error):  # e.g. the interrupted checkpoint failed: resume may refuse the run
            return _error(secrets, "interrupted", 130, error)
        return _error(secrets, "interrupted; the evidence is kept, continue with --resume", 130)
    except ValidationError as error:
        fields = ", ".join(
            sorted({".".join(map(str, e["loc"])) or "(root)" for e in error.errors()})
        )
        if _from_evidence(error):  # a saved record, not the config, fails its schema
            message = f"saved run evidence fails validation: {fields}; inspect the run"
            return _error(secrets, message, 1, error)
        return _error(secrets, f"invalid run config: {fields}", 2, error)
    except (collection.CollectionError, gate.GateError, FixtureError) as error:
        return _error(secrets, str(error), 1, error)
    except (SamplerError, ConfigError) as error:
        return _error(secrets, str(error), 2, error)
    except FileExistsError as error:
        name = Path(error.filename or "").name
        if name.endswith(".lock"):
            return _error(secrets, f"lock {name} present: a writer is active; inspect", 1, error)
        return _error(secrets, f"{name or 'target'} already exists; choose a new ID", 2, error)
    except ValueError as error:
        return _error(secrets, str(error), 1 if _from_evidence(error) else 2, error)
    except OSError as error:
        name = Path(error.filename).name if error.filename else "a file"
        message = f"cannot read {name}: {error.strerror or type(error).__name__}"
        return _error(secrets, message, 2, error)
    print(secrets.scrub(json.dumps(result, indent=2, ensure_ascii=False)))
    return code


def _from_evidence(error: BaseException) -> bool:
    trace = error.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code.co_name in EVIDENCE_FUNCTIONS:
            return True
        trace = trace.tb_next
    return False


def _notes(error: BaseException) -> list[str]:
    return [note for note in getattr(error, "__notes__", ()) if isinstance(note, str)]


def _error(secrets: _Secrets, message: str, code: int, error: BaseException | None = None) -> int:
    """One scrubbed `error:` line; an exception's notes follow its message."""
    notes = _notes(error) if error is not None else []
    line = " ".join(secrets.scrub("; ".join([message, *notes])).split())
    print(f"error: {line}", file=sys.stderr)
    return code


def _generator(config, secrets, transport) -> InstructorClient:
    return InstructorClient(
        base_url=config.base_url,
        model=config.model,
        api_key=secrets.key(config),
        mode=config.mode,
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        response_model=GenerationOutput,
        _transport=transport,
    )


def _embedder(config, secrets, transport) -> EmbeddingClient:
    return EmbeddingClient(
        base_url=config.base_url,
        model=config.embedding_model,
        api_key=secrets.key(config),
        timeout_seconds=config.timeout_seconds,
        _transport=transport,
    )


def _compact(summary: dict) -> dict:
    return {k: v for k, v in summary.items() if k not in {"members", "decisions", "items"}}


def _dispatch(args, secrets: _Secrets, transport) -> tuple[dict, int]:
    command = args.command
    if command == "collection-status":
        summary = collection.collection_status(
            _artifact_root(args.artifact_root), args.collection_id
        )
        return _compact(summary), 0 if summary["status"] == "ready" else 1
    if command == "cohort":
        frozen = cohort.freeze_cohort(
            _artifact_root(args.artifact_root), args.collection_id, args.cohort_id
        )
        return _compact(frozen), 0
    if command == "cohort-status":
        frozen = cohort.load_cohort(_artifact_root(args.artifact_root), args.cohort_id)
        return _compact(frozen), 0

    config = load_config(args.config)
    reference = _repo_path(args.reference_dir)
    fixtures = _repo_path(args.fixtures_dir)
    if command == "gate":
        lexicons = load_lexicons(reference)
        with _embedder(config, secrets, transport) as embedder:
            report = gate.gate_run(
                config.artifact_path(),
                args.run_id,
                lexicons=lexicons,
                embedder=embedder,
                embedding_model=config.embedding_model,
                fixtures_dir=fixtures,
            )
        return {k: v for k, v in report.items() if k != "per_item"}, (
            0 if report["distribution"]["passed"] else 1
        )

    if command == "collect":
        collection.policy(args.target_retained, args.batch_count, args.max_batches)
        load_prompt(config)  # a bad prompt fails before the credential is read
        with (
            _generator(config, secrets, transport) as client,
            _embedder(config, secrets, transport) as embedder,
        ):
            summary = collection.collect(
                config,
                args.collection_id,
                client,
                embedder,
                target_retained=args.target_retained,
                batch_count=args.batch_count,
                max_batches=args.max_batches,
                resume=args.resume,
                fixtures_dir=fixtures,
                reference_dir=reference,
            )
        if summary["status"] == "ready":
            return _compact(summary), 0
        return _compact(summary), 3 if summary["remaining_batches"] == 0 else 1

    prompt, prompt_sha256 = load_prompt(config)
    profiles = SetupProfiles.model_validate(
        json.loads((reference / "setup-profiles.json").read_bytes())
    )
    doc_config = load_doc_sources(collection.DOC_SOURCES)
    run_directory(config.artifact_path(), args.run_id)  # a bad ID fails before the key is read
    with _generator(config, secrets, transport) as client:
        manifest = generate.generate_run(
            config,
            prompt,
            prompt_sha256,
            count=args.count,
            run_id=args.run_id,
            client=client,
            profiles=profiles,
            doc_config=doc_config,
            fixtures_dir=fixtures,
            resume=args.resume,
        )
    result = {
        "run_id": args.run_id,
        "status": manifest["status"],
        "count": manifest["count"],
        "metrics": manifest["metrics"],
    }
    return result, {"complete": 0, "incomplete": 3}.get(manifest["status"], 1)
