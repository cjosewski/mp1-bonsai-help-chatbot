"""Assessment, labeling, judge and calibration commands: `assessment create | status`,
`label`, `label-status`, `freeze-human-reference`, `judge`, `judge-status`, `judge-qualify`,
`judge-examples`, `calibrate`, `judge-freeze`.

Every command takes `--artifact-root` (default `runs`; `runs/` or a path outside the
repository) and `--assessment-id`. Summaries are one JSON object on stdout and are blind:
totals, blind ids, label ids and pins, never a run, item or trace id, an arm, a count per
arm, a model or a prompt.

- `assessment create --cohort ID [--cohort ID ...] --count N --seed S
  [--exclude-assessment ID ...] [--rubric PATH]` selects and seals a new assessment
  (`assessment.create_assessment`); the rubric must be `chad_accepted`. It writes no label.
- `assessment status` re-verifies the assessment against its cohorts and reports whether
  the repository's current rubric still has the pinned hash, and the ledger's state.
- `label --reviewer NAME [--amend L-NNN --supersedes LABEL_ID]` is the reviewer's
  interactive session (`labels.interactive_label`), gated by the rubric pin against the
  repository's `config/rubric.json`.
- `label-status` is blind progress (`labels.label_status`).
- `freeze-human-reference --reviewer NAME --declare-blind` freezes the labels once
  (`human_reference.freeze_reference`) after the typed confirmation `freeze <id>`.

`label` and `freeze-human-reference` record the reviewer's own decisions, so they refuse
unless both stdin and stdout are terminals, before anything is read or shown. No flag or
environment variable bypasses that check and there is no non-interactive decision path.
Only Chad runs them, in his own terminal; an assistant never runs them, interactively or
through a pseudo-terminal (AGENTS.md; code cannot enforce that part).

The judge and calibration commands (MP1 Steps 4 and 6, B7) also take `--artifact-root`.
Those with `--config` (a `judge_config.JudgeConfig` file) default it to the config's
`artifact_root`; a different `--artifact-root` is a usage error, so the root the run
identity records is the root written to.

- `judge --config PATH --assessment-id ID --judge-run-id ID [--qualification ID]
  [--examples POOL_ID] [--frozen-judge SELECTION_ID] [--resume]` runs or resumes one
  judge run (`judge.judge_run`). A measured run needs a frozen human reference and a
  qualification receipt, both checked before any directory or call; a smoke run is
  refused on an `arm` assessment. `--examples` (judge v2) selects each item's examples
  through the config's embedding model before any chat call. `--frozen-judge` must match
  the judge a `judge-freeze` selection froze, exactly. It prints the run's blind status.
- `judge-status` verifies a judge run and prints its blind status: counts, unknown
  outcomes, unresolved blind ids and reported model ids, never a decision or reason.
- `judge-qualify --config PATH --smoke-assessment-id ID --smoke-judge-run-id ID
  --qualification-id ID` writes a qualification receipt once (`qualification.qualify`);
  it makes no model call.
- `judge-examples --config PATH --assessment-id ID --judge-run-id ID --pool-id ID` builds
  judge v2's example pool once from a development assessment's disagreements
  (`judge_examples.build_pool`), calling only the embedding endpoint.
- `calibrate --report-id ID` writes a calibration report and its separate disagreements
  file once (`calibration.calibration_report`) and prints only the aggregate figures,
  the status on the first line (`status: diagnostic (never calibration)` for a smoke run
  or a development assessment).
- `judge-freeze --report-id ID --selection-id ID` freezes the judge of a `ready` report
  (`calibration.freeze_judge`), only the one Decision 13's pre-registered rule chooses
  (`calibration.preregistered_choice`) and only once per assessment.

Exit codes: 0 done, labeling complete, a complete judge run, a `ready` report or a
`diagnostic` one (the planned outcome on a development assessment or a smoke run, never
calibration); 1 a refused or pending state (a rubric not accepted or changed, a ledger that
is not intact or is locked, an incomplete selection, an unmet freeze precondition or an
unmatched confirmation, changed or missing cohort, assessment or judge evidence, an
unfrozen reference, a spent judge-run budget, a qualification mismatch, a `pending`
report, which is still written, a freeze of a report that is not `ready` or not the
pre-registered rule's choice, a second selection for an assessment, a lock, an id that
already exists); 2 usage or configuration error, a stdin or stdout that is not a
terminal included; 3 controlled exhaustion (a judge run left `incomplete`); 130
interrupted (check `label-status`, `judge-status` or `assessment status` and inspect
before continuing). Errors are one `error:` line on stderr with every absolute path
redacted (`cli._redact`) and every credential value read scrubbed, never a traceback; the
`instructor` logger is silenced while a command runs (each attempt's error is in the
attempt ledger). Only `judge` and `judge-examples` call a model endpoint, and only the
configured local one.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

import httpx
from pydantic import ValidationError

from bonsai_help import (
    assessment,
    calibration,
    human_reference,
    judge,
    judge_examples,
    labels,
    qualification,
)
from bonsai_help.collection import CollectionError
from bonsai_help.collection_cli import (
    QUIET_LOGGERS,
    _artifact_root,
    _repo_path,
    _root_reasons,
    _Secrets,
)
from bonsai_help.config import REPOSITORY
from bonsai_help.doc_sources import ConfigError
from bonsai_help.doc_sources import load_config as load_doc_sources
from bonsai_help.judge_config import JudgeConfig, load_judge_config, load_judge_prompt
from bonsai_help.rubric import RUBRIC
from bonsai_help.setup import SetupProfiles

LABEL_COMMANDS = ("assessment", "label", "label-status", "freeze-human-reference")
JUDGE_COMMANDS = (
    "judge",
    "judge-status",
    "judge-qualify",
    "judge-examples",
    "calibrate",
    "judge-freeze",
)
COMMANDS = (*LABEL_COMMANDS, *JUDGE_COMMANDS)
ARTIFACTS = Path("runs")
FIXTURES = Path("tests/fixtures/docs")
PROFILES = Path("reference/setup-profiles.json")
DOC_SOURCES = Path("config/doc-sources.json")
TERMINAL = (
    "{command} records the reviewer's own decisions and needs an interactive terminal: "
    "Chad runs it himself (AGENTS.md); nothing was read or written"
)
REFUSED = (
    assessment.AssessmentError,
    labels.LabelError,
    human_reference.HumanReferenceError,
    CollectionError,
    judge.JudgeError,
    qualification.QualificationError,
    judge_examples.PoolError,
    calibration.CalibrationError,
)
# A judge run's status to its exit code: `incomplete` is controlled exhaustion.
JUDGE_EXIT = {"complete": 0, "incomplete": 3}
# A calibration report's status to its exit code: `diagnostic` is a planned outcome.
REPORT_EXIT = {"ready": 0, "diagnostic": 0, "pending": 1}


class _Usage(ValueError):
    """A usage error: exit 2."""


class _Refused(ValueError):
    """A refused state: exit 1."""


def add_commands(commands) -> None:
    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--artifact-root",
            type=Path,
            default=ARTIFACTS,
            help=f"artifact root: {ARTIFACTS}/ or outside the repository (default {ARTIFACTS})",
        )
        sub.add_argument("--assessment-id", required=True)

    parser = commands.add_parser("assessment", help="blind labeling selections from frozen cohorts")
    actions = parser.add_subparsers(dest="action", required=True)
    sub = actions.add_parser("create", help="select and seal a new assessment (writes no label)")
    common(sub)
    sub.add_argument(
        "--cohort",
        action="append",
        required=True,
        help="a frozen cohort, one per arm (repeatable)",
    )
    sub.add_argument("--count", type=int, required=True, help="items per cohort, a multiple of 5")
    sub.add_argument("--seed", required=True, help="selection and display-order seed")
    sub.add_argument(
        "--exclude-assessment",
        action="append",
        default=[],
        help="leave out the items this assessment selected (repeatable)",
    )
    sub.add_argument(
        "--rubric", type=Path, help=f"rubric, which must be chad_accepted (default {RUBRIC})"
    )
    sub = actions.add_parser("status", help="verify an assessment; blind totals and pins only")
    common(sub)

    sub = commands.add_parser(
        "label", help="the reviewer's blind labeling session (interactive terminal only)"
    )
    common(sub)
    sub.add_argument("--reviewer", required=True, help="the reviewer's name")
    sub.add_argument("--amend", metavar="L-NNN", help="label this blind id again (a correction)")
    sub.add_argument(
        "--supersedes", metavar="LABEL_ID", help="the current label id that --amend replaces"
    )
    sub = commands.add_parser("label-status", help="blind labeling progress")
    common(sub)
    sub = commands.add_parser(
        "freeze-human-reference",
        help="freeze the blind labels once, before any judge (interactive terminal only)",
    )
    common(sub)
    sub.add_argument("--reviewer", required=True, help="the reviewer whose labels are frozen")
    sub.add_argument(
        "--declare-blind",
        action="store_true",
        help="declare that no judge output, model feedback or other label was consulted",
    )
    _add_judge_commands(commands)


def _add_judge_commands(commands) -> None:
    def root(sub: argparse.ArgumentParser, *, from_config: bool = False) -> None:
        if from_config:
            sub.add_argument(
                "--config", type=Path, required=True, help="judge config (JSON, git-ignored)"
            )
            sub.add_argument(
                "--artifact-root",
                type=Path,
                help="artifact root; must equal the config's artifact_root (default: the "
                "config's artifact_root)",
            )
        else:
            sub.add_argument(
                "--artifact-root",
                type=Path,
                default=ARTIFACTS,
                help=f"artifact root: {ARTIFACTS}/ or outside the repository (default {ARTIFACTS})",
            )

    sub = commands.add_parser(
        "judge", help="run or resume one blind, bounded judge run on an assessment"
    )
    root(sub, from_config=True)
    sub.add_argument("--assessment-id", required=True)
    sub.add_argument("--judge-run-id", required=True)
    sub.add_argument(
        "--qualification", metavar="ID", help="the judge's qualification receipt (measured)"
    )
    sub.add_argument("--examples", metavar="POOL_ID", help="judge v2: the development example pool")
    sub.add_argument(
        "--frozen-judge",
        metavar="SELECTION_ID",
        help="the judge-freeze selection this measured run must match exactly",
    )
    sub.add_argument("--resume", action="store_true", help="continue an unfinished judge run")

    sub = commands.add_parser("judge-status", help="verify a judge run; blind counts only")
    root(sub)
    sub.add_argument("--assessment-id", required=True)
    sub.add_argument("--judge-run-id", required=True)

    sub = commands.add_parser(
        "judge-qualify", help="write a judge qualification receipt from a smoke run (no call)"
    )
    root(sub, from_config=True)
    sub.add_argument("--smoke-assessment-id", required=True)
    sub.add_argument("--smoke-judge-run-id", required=True)
    sub.add_argument("--qualification-id", required=True)

    sub = commands.add_parser(
        "judge-examples",
        help="build judge v2's example pool from development disagreements (once)",
    )
    root(sub, from_config=True)
    sub.add_argument("--assessment-id", required=True)
    sub.add_argument("--judge-run-id", required=True)
    sub.add_argument("--pool-id", required=True)

    sub = commands.add_parser(
        "calibrate",
        help="write a calibration report once; prints the aggregate figures only",
    )
    root(sub)
    sub.add_argument("--assessment-id", required=True)
    sub.add_argument("--judge-run-id", required=True)
    sub.add_argument("--report-id", required=True)

    sub = commands.add_parser(
        "judge-freeze",
        help="freeze the judge the pre-registered rule chooses (once per assessment)",
    )
    root(sub)
    sub.add_argument("--assessment-id", required=True)
    sub.add_argument("--report-id", required=True)
    sub.add_argument("--selection-id", required=True)


class _Context:
    """One command's artifact root, once known, and the credential values it read."""

    def __init__(self) -> None:
        self.root: Path | None = None
        self.secrets = _Secrets()

    def shown(self, text: str) -> str:
        """Scrub every credential value read, then redact every absolute path."""
        from bonsai_help.cli import _redact  # cli imports this module

        roots = [(REPOSITORY, ".")]
        if self.root is not None:
            roots.append((self.root, "<artifact-root>"))
        return _redact(self.secrets.scrub(text), roots)


def _notes(error: BaseException) -> list[str]:
    return [note for note in getattr(error, "__notes__", ()) if isinstance(note, str)]


def _error(message: str, code: int, context: _Context, error: BaseException | None = None) -> int:
    notes = _notes(error) if error is not None else []
    line = " ".join(context.shown("; ".join([message, *notes])).split())
    print(f"error: {line}", file=sys.stderr)
    return code


def run(args, *, transport: httpx.BaseTransport | None = None) -> int:
    """Run one command; library loggers stay quiet (the attempt ledgers are the record)."""
    loggers = [logging.getLogger(name) for name in QUIET_LOGGERS]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.CRITICAL + 1)
    try:
        return _run(args, transport)
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.setLevel(level)


def _interrupted(command: str) -> str:
    if command in JUDGE_COMMANDS:
        return (
            "interrupted; check judge-status and inspect the files before continuing; a judge "
            "run continues under its own id with --resume (nothing is repaired)"
        )
    return (
        "interrupted; check label-status or assessment status and inspect the files "
        "before continuing (nothing is repaired)"
    )


def _run(args, transport) -> int:
    """Every failure is one redacted `error:` line and an exit code."""
    context = _Context()
    try:
        if args.command in ("label", "freeze-human-reference"):
            _require_terminal(args.command)
        if args.command in JUDGE_COMMANDS:
            result, code = _judge_dispatch(args, context, transport)
        else:
            context.root = _artifact_root(args.artifact_root)
            result, code = _dispatch(args, context.root)
    except KeyboardInterrupt as error:
        return _error(_interrupted(args.command), 130, context, error)
    except (_Usage, assessment.UsageError, ConfigError) as error:
        return _error(str(error), 2, context, error)
    except (_Refused, *REFUSED) as error:
        return _error(str(error), 1, context, error)
    except FileExistsError as error:
        name = Path(error.filename or "").name or "a file"
        if name.endswith(".lock"):
            return _error(f"lock {name} present: a writer is active; inspect it", 1, context)
        return _error(f"{name} already exists; preserve and inspect it", 1, context)
    except ValidationError as error:
        fields = ", ".join(
            sorted({".".join(map(str, e["loc"])) or "(root)" for e in error.errors()})
        )
        return _error(f"invalid reference or configuration file: {fields}", 2, context)
    except ValueError as error:
        return _error(str(error), 2, context, error)
    except OSError as error:
        name = Path(error.filename).name if error.filename else "a file"
        message = f"cannot read {name}: {error.strerror or type(error).__name__}"
        return _error(message, 2, context)
    text = result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False)
    print(context.shown(text))
    return code


def _require_terminal(command: str) -> None:
    """Both stdin and stdout must be terminals; checked before anything is read or shown."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise _Usage(TERMINAL.format(command=command))


def _rubric() -> Path:
    return _repo_path(RUBRIC)


def _fixtures() -> Path:
    return _repo_path(FIXTURES)


def _doc_config():
    return load_doc_sources(_repo_path(DOC_SOURCES))


def _load(root: Path, assessment_id: str) -> assessment.Assessment:
    return assessment.load_assessment(
        root,
        assessment_id,
        fixtures_dir=_fixtures(),
        doc_config=_doc_config(),
        rubric_path=_rubric(),
    )


def _blind_summary(root: Path, assessment_id: str) -> dict:
    return assessment.assessment_summary(root, assessment_id)


def _dispatch(args, root: Path) -> tuple[dict, int]:
    command = args.command
    if command == "assessment" and args.action == "create":
        rubric_path = _repo_path(args.rubric) if args.rubric is not None else _rubric()
        profiles = SetupProfiles.model_validate(json.loads(_repo_path(PROFILES).read_bytes()))
        assessment.create_assessment(
            root,
            args.assessment_id,
            args.cohort,
            count=args.count,
            seed=args.seed,
            rubric_path=rubric_path,
            profiles=profiles,
            doc_config=_doc_config(),
            fixtures_dir=_fixtures(),
            exclude=args.exclude_assessment,
        )
        return _blind_summary(root, args.assessment_id), 0
    if command == "assessment":
        loaded = _load(root, args.assessment_id)
        summary = _blind_summary(root, args.assessment_id)
        current = loaded.current_rubric_sha256 == loaded.manifest["rubric_sha256"]
        state = labels.ledger_state(loaded.directory)
        return summary | {"rubric_matches_current": current, "ledger": state.state}, 0
    if command == "label-status":
        status = labels.label_status(_load(root, args.assessment_id))
        return status, 0 if status["status"] == "complete" else 1
    if command == "label":
        return _label(args, root)
    return _freeze(args, root)


def _label(args, root: Path) -> tuple[dict, int]:
    if (args.amend is None) != (args.supersedes is None):
        raise _Usage("an amendment needs both --amend L-NNN and --supersedes LABEL_ID")
    loaded = _load(root, args.assessment_id)
    status = labels.interactive_label(
        loaded,
        args.reviewer,
        rubric_path=_rubric(),
        fixtures_dir=_fixtures(),
        input_fn=input,
        output=print,
        amend=args.amend,
        supersedes=args.supersedes,
    )
    return status, 0 if status["status"] == "complete" else 1


def _freeze(args, root: Path) -> tuple[dict, int]:
    if not args.declare_blind:
        raise _Refused(
            "the reviewer must declare that the labels were made blind, with no judge output, "
            "model feedback or other label consulted (--declare-blind); nothing was frozen"
        )
    reviewer = args.reviewer.strip()
    if not reviewer:
        raise _Usage("the reviewer name must be nonblank")
    loaded = _load(root, args.assessment_id)
    labels.check_rubric_gate(loaded, _rubric())
    if (loaded.directory / labels.REFERENCE).exists():
        raise _Refused(f"{labels.REFERENCE} already exists; a frozen reference is never replaced")
    status = labels.label_status(loaded)
    if status["status"] == "not_intact":
        raise _Refused(f"{status['problem']}")
    if status["status"] != "complete":
        raise _Refused(
            f"{status['completed']} of {status['selected']} selected items have labels; label "
            "every selected item before freezing"
        )
    assessment_id = loaded.manifest["assessment_id"]
    print(
        f"Freezing the blind human reference of {assessment_id}: {status['selected']} labels, "
        f"{status['unresolved_decisions']} unresolved decision(s). The labels are recorded as "
        f"the reviewer {reviewer}'s own, made blind, with no judge output, model feedback or "
        "other label consulted."
    )
    wanted = f"freeze {assessment_id}"
    try:
        answer = input(f"Type '{wanted}' to freeze: ")
    except (EOFError, KeyboardInterrupt):
        answer = None
    if answer is None or answer.strip() != wanted:
        raise _Refused("the confirmation did not match; nothing was frozen")
    reference = human_reference.freeze_reference(
        loaded, reviewer, declare_blind=True, rubric_path=_rubric()
    )
    total = reference["counts"]["total"]
    return {
        "assessment_id": reference["assessment_id"],
        "kind": reference["kind"],
        "reviewer": reference["reviewer"],
        "declared_blind": reference["declared_blind"],
        "labels": len(reference["labels"]),
        "unresolved_items": total["unresolved_items"],
        "unresolved_by_dimension": total["unresolved_by_dimension"],
        "rubric_version": reference["rubric_version"],
        "rubric_sha256": reference["rubric_sha256"],
        "sha256": reference["sha256"],
    }, 0


# ------------------------------------------------------------ judge and calibration


def _judge_config(path: Path) -> JudgeConfig:
    """Load a judge config; a refused config names fields and reasons, never values."""
    try:
        return load_judge_config(_repo_path(path))
    except ValidationError as error:
        fields = ", ".join(
            sorted({".".join(map(str, e["loc"])) or "(root)" for e in error.errors()})
        )
        raise _Usage(f"invalid judge config: {fields}{_root_reasons(error)}") from None


def _config_root(value: Path | None, config: JudgeConfig) -> Path:
    """The config's artifact root; an `--artifact-root` must name the same directory."""
    configured = _artifact_root(config.artifact_path())
    if value is not None and _artifact_root(value) != configured:
        raise _Usage(
            "--artifact-root differs from the judge config's artifact_root; the run identity "
            "records the config's, so set it there"
        )
    return configured


def _embedder(config: JudgeConfig, context: _Context, transport):
    if config.embedding_model is None:
        raise _Usage("the judge config has no embedding_model (judge v2's example selection)")
    context.secrets.embedding_key(config)
    return judge_examples.embedder_for(config, _transport=transport)


def _judge_dispatch(args, context: _Context, transport) -> tuple[dict | str, int]:
    command = args.command
    config = None
    if command in ("judge", "judge-qualify", "judge-examples"):
        config = _judge_config(args.config)
        context.root = _config_root(args.artifact_root, config)
    else:
        context.root = _artifact_root(args.artifact_root)
    root = context.root
    if command == "judge":
        return _judge(args, config, context, transport)
    if command == "judge-status":
        status = judge.judge_status(root, args.assessment_id, args.judge_run_id)
        return status, JUDGE_EXIT.get(status["status"], 1)
    if command == "judge-qualify":
        receipt = qualification.qualify(
            config,
            root,
            smoke_assessment_id=args.smoke_assessment_id,
            smoke_judge_run_id=args.smoke_judge_run_id,
            qualification_id=args.qualification_id,
        )
        return {
            "qualification_id": receipt["qualification_id"],
            "sha256": receipt["sha256"],
            "basis": receipt["basis"],
            "evidence": receipt["evidence"],
        }, 0
    if command == "judge-examples":
        return _examples(args, config, context, transport)
    if command == "calibrate":
        report = calibration.calibration_report(
            root, args.assessment_id, args.judge_run_id, args.report_id
        )
        return "\n".join(calibration.report_lines(report)), REPORT_EXIT[report["status"]]
    selection = calibration.freeze_judge(
        root, args.assessment_id, args.report_id, args.selection_id
    )
    return {
        key: selection[key]
        for key in (
            "selection_id",
            "sha256",
            "assessment_id",
            "judge_run_id",
            "report_id",
            "report_sha256",
            "prompt_version",
        )
    }, 0


def _judge(args, config: JudgeConfig, context: _Context, transport) -> tuple[dict, int]:
    root = context.root
    try:  # a bad prompt is a configuration error, refused before any credential is read
        load_judge_prompt(config, with_examples=args.examples is not None)
    except ValueError as error:
        raise _Usage(str(error)) from None
    frozen = None
    if args.frozen_judge is not None:
        frozen = calibration.load_selection(root, args.frozen_judge)["frozen_identity"]
    with ExitStack() as stack:
        embedder = None
        if args.examples is not None and not args.resume:
            embedder = stack.enter_context(_embedder(config, context, transport))
        context.secrets.key(config)
        client = stack.enter_context(judge.judge_client(config, _transport=transport))
        status = judge.judge_run(
            root,
            args.assessment_id,
            args.judge_run_id,
            config,
            client,
            qualification_id=args.qualification,
            pool_id=args.examples,
            embedder=embedder,
            frozen_judge=frozen,
            resume=args.resume,
        )
    return status, JUDGE_EXIT.get(status["status"], 1)


def _examples(args, config: JudgeConfig, context: _Context, transport) -> tuple[dict, int]:
    with _embedder(config, context, transport) as embedder:
        pool = judge_examples.build_pool(
            context.root,
            args.assessment_id,
            args.judge_run_id,
            args.pool_id,
            embedder=embedder,
            embedding_model=config.embedding_model,
        )
    dimensions = Counter(entry["dimension"] for entry in pool["entries"])
    return {
        "pool_id": pool["pool_id"],
        "sha256": pool["sha256"],
        "source": pool["source"],
        "embedding": pool["embedding"],
        "items": len(pool["items"]),
        "entries": len(pool["entries"]),
        "entries_by_dimension": dict(sorted(dimensions.items())),
    }, 0
