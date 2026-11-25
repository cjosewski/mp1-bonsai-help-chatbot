"""Freeze an assessment's blind human labels once, before any judge evidence exists.

`freeze_reference` writes `human-reference.json` beside the assessment, once, and never
replaces it. It needs all of the following, and every refusal comes before any write:

- the reviewer's explicit declaration (`declare_blind is True`; the command adds the typed
  confirmation and the terminal check) and a nonblank reviewer name;
- the rubric gate of `labels.check_rubric_gate`: the stored copy matches the pin, is
  `chad_accepted`, and the current rubric still has the pinned hash;
- an intact ledger (`labels.load_labels`) and no writer lock (the freeze holds the labels'
  lock, so no label is appended while it runs; a leftover lock is reported, never removed);
- an effective label for every selected blind id, every one `blind` and every one the
  declaring reviewer's own;
- for kind `arm`, at least the rubric's `thresholds.blind_labels.minimum_per_arm` labeled
  items in each arm of the assessment, each a rubric arm (kind `development`: at least
  `assessment.DEVELOPMENT_MINIMUM`);
- no judge evidence under the assessment (`JUDGES`, the directory where B7's judge writes).

The reference holds the effective labels, the SHA-256 and line count of the ledger prefix
they come from, the assessment and rubric pins, the kind, and counts. Labeling is complete,
so the counts are read from the assessment's key (`assessment.load_key`): items and
unresolved decisions per dimension, in total and per group (each arm for kind `arm`, the one
group `development` for kind `development`). Unresolved decisions do not block a freeze:
they are reported, never a pass, and the items stay in every denominator.

`load_reference` re-verifies the reference against the whole ledger, its frozen prefix, the
pins and the key. Labels appended after the freeze are `post_review` (`labels.record_label`
marks them so once this file exists); they never change the frozen reference, and a `blind`
label after the prefix is refused. Development references are never an arm's denominator.

Obligation for B7: an assessed judge run calls `load_reference` first and refuses without a
frozen reference, and writes its evidence only under `JUDGES`, so judge evidence can never
come before the frozen labels. Nothing here calls a model endpoint, and an assistant never
runs the freeze on real evidence: Chad runs `freeze-human-reference` in his own terminal.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path

from pydantic import ValidationError

from bonsai_help import assessment as assessments
from bonsai_help.assessment import DEVELOPMENT_MINIMUM, Assessment, AssessmentError
from bonsai_help.evaluation_schemas import DIMENSIONS, HumanLabel
from bonsai_help.labels import (
    LEDGER,
    LOCK,
    REFERENCE,
    LabelError,
    check_rubric_gate,
    load_labels,
)
from bonsai_help.tracing import digest, exclusive, now, read_json

JUDGES = "judges"
DEVELOPMENT = "development"
REFERENCE_FIELDS = frozenset(
    {
        "schema_version",
        "assessment_id",
        "assessment_sha256",
        "kind",
        "created_at",
        "reviewer",
        "declared_blind",
        "rubric_version",
        "rubric_sha256",
        "minimum_per_group",
        "ledger_prefix_sha256",
        "ledger_prefix_lines",
        "display_order",
        "labels",
        "counts",
        "sha256",
    }
)
INSPECT = "preserve and inspect the files; nothing was repaired"


class HumanReferenceError(ValueError):
    """The human reference is refused: freezing wrote nothing, or loading found a change."""


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _sealed(reference: dict) -> str:
    return digest({k: v for k, v in reference.items() if k != "sha256"})


def _root(assessment: Assessment) -> Path:
    # `assessment.assessment_directory` puts an assessment at `<root>/assessments/<id>`.
    return assessment.directory.parent.parent


def _key(assessment: Assessment) -> dict[str, dict]:
    try:
        key = assessments.load_key(_root(assessment), assessment.manifest["assessment_id"])
    except (AssessmentError, ValueError) as exc:
        raise HumanReferenceError(f"assessment key: {exc}") from None
    if list(key) != assessment.manifest["display_order"]:
        raise HumanReferenceError(f"the assessment key differs from its queue; {INSPECT}")
    return key


def _group(kind: str, entry: dict) -> str:
    return entry["arm"] if kind == "arm" else DEVELOPMENT


def _tally(selected: list[HumanLabel]) -> dict:
    unresolved = {
        d: sum(1 for x in selected if x.decisions.values()[d] is None) for d in DIMENSIONS
    }
    return {
        "items": len(selected),
        "unresolved_items": sum(1 for x in selected if x.decisions.unresolved()),
        "unresolved_by_dimension": unresolved,
    }


def _counts(kind: str, order: list[str], effective: dict[str, HumanLabel], key: dict) -> dict:
    """Items and unresolved decisions, in total and per group; every item stays counted."""
    groups: dict[str, list[HumanLabel]] = {}
    for blind_id in order:
        groups.setdefault(_group(kind, key[blind_id]), []).append(effective[blind_id])
    return {
        "total": _tally([effective[b] for b in order]),
        "groups": {name: _tally(groups[name]) for name in sorted(groups)},
    }


def _minimum(assessment: Assessment) -> int:
    if assessment.manifest["kind"] == "arm":
        return assessments.minimum_per_arm(assessment.rubric)
    return DEVELOPMENT_MINIMUM


def _check_groups(assessment: Assessment, counts: dict) -> None:
    """Each group has the rubric's minimum; for kind `arm`, exactly the sources' arms."""
    manifest = assessment.manifest
    minimum = _minimum(assessment)
    groups = counts["groups"]
    if manifest["kind"] == "arm":
        allowed = set(assessment.rubric.thresholds.blind_labels.arms)
        arms = {source["arm"] for source in manifest["sources"]}
        if set(groups) != arms or not arms <= allowed:
            raise HumanReferenceError(
                f"the key's arms differ from the assessment's sources or the rubric; {INSPECT}"
            )
    elif set(groups) != {DEVELOPMENT}:
        raise HumanReferenceError(f"a development reference has one group; {INSPECT}")
    short = [f"{name} has {g['items']}" for name, g in groups.items() if g["items"] < minimum]
    if short:
        noun = "arm" if manifest["kind"] == "arm" else "development assessment"
        raise HumanReferenceError(
            f"too few labeled items: {', '.join(short)}; the rubric needs at least {minimum} "
            f"per {noun}"
        )


def _check_labels(effective: dict[str, HumanLabel], order: list[str], reviewer: str) -> None:
    pending = [blind_id for blind_id in order if blind_id not in effective]
    if pending:
        raise HumanReferenceError(
            f"{len(order) - len(pending)} of {len(order)} selected items have labels; label "
            f"every selected item before freezing (next pending: {pending[0]})"
        )
    if set(effective) != set(order):
        raise HumanReferenceError(f"a label is outside the selection; {INSPECT}")
    if any(label.review_stage != "blind" for label in effective.values()):
        raise HumanReferenceError("the reference needs blind labels only")
    if any(label.reviewer != reviewer for label in effective.values()):
        raise HumanReferenceError(
            "every effective label must be the declaring reviewer's own; the reviewer named "
            "here differs from a label's reviewer"
        )


def _judge_evidence(directory: Path) -> None:
    if _present(directory / JUDGES):
        raise HumanReferenceError(
            f"judge evidence exists ({JUDGES}/ under the assessment): blind labels are frozen "
            "only before any judge output; create a new assessment"
        )


def _locked(directory: Path) -> ExitStack:
    stack = ExitStack()
    try:
        stack.enter_context(exclusive(directory / LOCK))
    except FileExistsError:
        raise HumanReferenceError(
            f"{LOCK} exists: a labeling session is saving, or one stopped abruptly; "
            "preserve and inspect it (it is never removed by code)"
        ) from None
    return stack


def _dumps(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _write_once(path: Path, data: bytes) -> None:
    """Write a complete file, then link it into place: never a partial or replaced file."""
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except FileExistsError:
        raise HumanReferenceError(
            f"{REFERENCE} already exists; a frozen reference is never replaced"
        ) from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def freeze_reference(
    assessment: Assessment, reviewer: str, *, declare_blind: bool, rubric_path: Path
) -> dict:
    """Freeze the effective blind labels as the human reference; written once, sealed."""
    if declare_blind is not True:
        raise HumanReferenceError(
            "the reviewer must declare that the labels were made blind, with no judge output, "
            "model feedback or other label consulted (--declare-blind)"
        )
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise HumanReferenceError("the reviewer name must be nonblank")
    reviewer = reviewer.strip()
    try:
        reviewer.encode("utf-8")
    except UnicodeEncodeError:
        raise HumanReferenceError("the reviewer name cannot be stored as UTF-8") from None
    directory = assessment.directory
    manifest = assessment.manifest
    try:
        check_rubric_gate(assessment, rubric_path)
    except LabelError as exc:
        raise HumanReferenceError(str(exc)) from None
    with _locked(directory):
        if _present(directory / REFERENCE):
            raise HumanReferenceError(
                f"{REFERENCE} already exists; a frozen reference is never replaced"
            )
        _judge_evidence(directory)
        try:
            effective = load_labels(assessment)
        except LabelError as exc:
            raise HumanReferenceError(str(exc)) from None
        order = list(manifest["display_order"])
        _check_labels(effective, order, reviewer)
        key = _key(assessment)
        counts = _counts(manifest["kind"], order, effective, key)
        _check_groups(assessment, counts)
        # Read under the lock that `load_labels` verified it under: no append in between.
        ledger = (directory / LEDGER).read_bytes()
        reference = {
            "schema_version": "1",
            "assessment_id": manifest["assessment_id"],
            "assessment_sha256": manifest["sha256"],
            "kind": manifest["kind"],
            "created_at": now(),
            "reviewer": reviewer,
            "declared_blind": True,
            "rubric_version": manifest["rubric_version"],
            "rubric_sha256": manifest["rubric_sha256"],
            "minimum_per_group": _minimum(assessment),
            "ledger_prefix_sha256": hashlib.sha256(ledger).hexdigest(),
            "ledger_prefix_lines": len(_prefix(ledger, ledger.count(b"\n"))[1]),
            "display_order": order,
            "labels": {b: effective[b].model_dump(mode="json") for b in order},
            "counts": counts,
        }
        reference["sha256"] = _sealed(reference)
        _write_once(directory / REFERENCE, _dumps(reference))
        return reference


def _read_reference(directory: Path) -> dict:
    path = directory / REFERENCE
    if path.is_symlink():
        raise HumanReferenceError(f"{REFERENCE} is a symlink; {INSPECT}")
    if not path.exists():
        raise HumanReferenceError(
            f"no frozen human reference ({REFERENCE}): the reviewer freezes it with "
            "freeze-human-reference after labeling every selected item"
        )
    try:
        reference = read_json(path)
    except (OSError, ValueError):
        raise HumanReferenceError(
            f"{REFERENCE} is unreadable or not a JSON object; {INSPECT}"
        ) from None
    if set(reference) != REFERENCE_FIELDS or reference["sha256"] != _sealed(reference):
        raise HumanReferenceError(f"{REFERENCE} changed after it was frozen; {INSPECT}")
    return reference


def _prefix(ledger: bytes, lines: object) -> tuple[bytes, list[HumanLabel], list[HumanLabel]]:
    """The frozen prefix's bytes and labels, and the labels appended after it."""
    parts = ledger.split(b"\n")
    if parts[-1] != b"" or type(lines) is not int or not 1 <= lines <= len(parts) - 1:
        raise HumanReferenceError(f"the frozen ledger prefix is not in {LEDGER}; {INSPECT}")
    records = parts[:-1]
    try:
        parsed = [HumanLabel.model_validate(json.loads(line)["label"]) for line in records]
    except (ValueError, TypeError, KeyError, ValidationError):
        raise HumanReferenceError(f"{LEDGER} has a line that is not a label; {INSPECT}") from None
    prefix = b"".join(line + b"\n" for line in records[:lines])
    return prefix, parsed[:lines], parsed[lines:]


def load_reference(assessment: Assessment) -> dict:
    """The frozen human reference, re-verified against the ledger, its prefix, pins and key.

    Labels appended after the freeze must be `post_review`; they are ignored here and never
    change the reference. Any difference is refused.
    """
    directory = assessment.directory
    manifest = assessment.manifest
    reference = _read_reference(directory)
    order = list(manifest["display_order"])
    if (
        reference["schema_version"] != "1"
        or reference["assessment_id"] != manifest["assessment_id"]
        or reference["assessment_sha256"] != manifest["sha256"]
        or reference["kind"] != manifest["kind"]
        or reference["rubric_version"] != manifest["rubric_version"]
        or reference["rubric_sha256"] != manifest["rubric_sha256"]
        or reference["declared_blind"] is not True
        or reference["display_order"] != order
        or reference["minimum_per_group"] != _minimum(assessment)
    ):
        raise HumanReferenceError(f"{REFERENCE} does not match its assessment; {INSPECT}")
    try:
        load_labels(assessment)
        ledger = (directory / LEDGER).read_bytes()
    except LabelError as exc:
        raise HumanReferenceError(str(exc)) from None
    except OSError:
        raise HumanReferenceError(f"{LEDGER} is missing or unreadable; {INSPECT}") from None
    prefix, frozen, later = _prefix(ledger, reference["ledger_prefix_lines"])
    if hashlib.sha256(prefix).hexdigest() != reference["ledger_prefix_sha256"]:
        raise HumanReferenceError(f"the frozen ledger prefix changed; {INSPECT}")
    if any(label.review_stage != "post_review" for label in later):
        raise HumanReferenceError(f"a label after the frozen prefix is not post-review; {INSPECT}")
    effective: dict[str, HumanLabel] = {}
    for label in frozen:
        effective[label.blind_id] = label
    try:
        _check_labels(effective, order, reference["reviewer"])
    except HumanReferenceError as exc:
        raise HumanReferenceError(f"the frozen ledger prefix is refused: {exc}") from None
    if reference["labels"] != {b: effective[b].model_dump(mode="json") for b in order}:
        raise HumanReferenceError(
            f"{REFERENCE} labels differ from its frozen ledger prefix; {INSPECT}"
        )
    counts = _counts(manifest["kind"], order, effective, _key(assessment))
    if reference["counts"] != counts:
        raise HumanReferenceError(f"{REFERENCE} counts differ from the key; {INSPECT}")
    _check_groups(assessment, counts)
    return reference
