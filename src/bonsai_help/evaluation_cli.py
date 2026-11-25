"""Assessment and labeling commands: `assessment create | status`, `label`, `label-status`,
`freeze-human-reference`.

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

Exit codes: 0 done, or labeling complete; 1 a refused state (a rubric not accepted or
changed, a ledger that is not intact or is locked, an incomplete selection, an unmet
freeze precondition or an unmatched confirmation, changed or missing cohort or assessment
evidence); 2 usage or configuration error, a stdin or stdout that is not a terminal
included; 130 interrupted (run `label-status` and inspect before continuing). Errors are
one `error:` line on stderr with every absolute path redacted (`cli._redact`), never a
traceback. Nothing here calls a model endpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from bonsai_help import assessment, human_reference, labels
from bonsai_help.collection import CollectionError
from bonsai_help.collection_cli import _artifact_root, _repo_path
from bonsai_help.config import REPOSITORY
from bonsai_help.doc_sources import ConfigError
from bonsai_help.doc_sources import load_config as load_doc_sources
from bonsai_help.rubric import RUBRIC
from bonsai_help.setup import SetupProfiles

COMMANDS = ("assessment", "label", "label-status", "freeze-human-reference")
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
)


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


def _error(message: str, code: int, root: Path | None) -> int:
    from bonsai_help.cli import _redact  # cli imports this module

    shown = [(REPOSITORY, ".")]
    if root is not None:
        shown.append((root, "<artifact-root>"))
    line = " ".join(_redact(message, shown).split())
    print(f"error: {line}", file=sys.stderr)
    return code


def run(args) -> int:
    """Run one command; every failure is one redacted `error:` line and an exit code."""
    root = None
    try:
        if args.command in ("label", "freeze-human-reference"):
            _require_terminal(args.command)
        root = _artifact_root(args.artifact_root)
        result, code = _dispatch(args, root)
    except KeyboardInterrupt:
        return _error(
            "interrupted; check label-status or assessment status and inspect the files "
            "before continuing (nothing is repaired)",
            130,
            root,
        )
    except (_Usage, assessment.UsageError, ConfigError) as error:
        return _error(str(error), 2, root)
    except (_Refused, *REFUSED) as error:
        return _error(str(error), 1, root)
    except FileExistsError as error:
        name = Path(error.filename or "").name or "a file"
        return _error(f"{name} already exists; preserve and inspect it", 1, root)
    except ValidationError as error:
        fields = ", ".join(
            sorted({".".join(map(str, e["loc"])) or "(root)" for e in error.errors()})
        )
        return _error(f"invalid reference or configuration file: {fields}", 2, root)
    except ValueError as error:
        return _error(str(error), 2, root)
    except OSError as error:
        name = Path(error.filename).name if error.filename else "a file"
        return _error(f"cannot read {name}: {error.strerror or type(error).__name__}", 2, root)
    print(json.dumps(result, indent=2, ensure_ascii=False))
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
