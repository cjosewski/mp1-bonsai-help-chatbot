"""Human/judge agreement, calibration reports and the frozen judge (B7 Decisions 8, 9, 13, 16).

`agreement` compares the frozen human decisions with a judge run's decisions, per dimension,
over every selected blind id `n`:

- `matching` counts the items whose human decision (0 or 1) equals the judge's. A human
  `None` (unresolved) and a missing judgment (an exhausted item) are in `n`, never match,
  and are counted (`human_unresolved`, `judge_missing`).
- The confusion counts are over the pairs where both decisions exist. TPR is
  `h1_j1 / (h1_j1 + h1_j0)` (of the items the human passed, the share the judge passed) and
  TNR `h0_j0 / (h0_j0 + h0_j1)`. Agreement, TPR and TNR each carry an exact
  `stats.clopper_pearson` interval at the rubric's confidence; a zero denominator is
  undefined (null), never 0 or 1.
- Whether a dimension meets the rubric minimum is `acceptance.acceptance_result`'s call
  (exact fractions, inclusive): 24 of 30 meets 0.8 and 23 of 30 does not.

`calibration_report` writes two files once under `<assessment dir>/calibration/`:
`<report_id>.json` holds the status, reasons, aggregate figures (per dimension, per category
without a threshold, per arm from the key), the disclosed unknown outcomes and the pins;
`<report_id>.disagreements.json` holds only the per-item disagreements (blind id,
dimension, human decision, judge decision, judge reason), and the main report pins its
SHA-256. Whoever writes a later judge prompt reads only the main report of an `arm`
assessment, never its disagreements file; `report_lines` prints only aggregate figures.

**Status.** `diagnostic` (never calibration, whatever the agreement) for a development
assessment, a smoke run or a judge that is the same model as a source generator. Otherwise
`ready` only if every condition of Decision 9 holds, else `pending` with every reason:
a frozen, verified reference (labels amended after the freeze are not used), a complete
measured run, a valid qualification, every reply reporting the configured judge model, a
judge temperature below every source generator's, the rubric pin equal to the reference's,
and every dimension at or above the minimum. An unknown outcome (a start with no completion)
is disclosed with its attempt id and does not block readiness by itself: it used up its
attempt, and an item left without a valid judgment makes the run incomplete. Evidence that
cannot be verified (a tampered judge run, or a measured run whose frozen reference is gone)
is refused and nothing is written.

`freeze_judge` accepts only a `ready` report, and only the one Decision 13's pre-registered
rule chooses (`preregistered_choice`): once `judge-v1` and `judge-v2` have each been measured
once on the assessment, no other prompt version has been measured on it, and every measured
run has a calibration report, the frozen judge is v2 if its report is `ready`, else v1 if
its report is `ready`. A measured run of any other version (a `judge-v3`, or a
`judge-v1.1`) is outside the rule and is refused: it needs Chad's dated decision and a new
rule. Every report on the assessment is verified and re-derived from the evidence (a change
since a report was written is refused), and an assessment gets at most one frozen
selection. If no report is `ready`, Phase A is not met and the plain freeze refuses;
`preregistered_choice` still names the judge the rule carries forward under Open question
7(c) (more dimensions at or above the minimum, then the higher minimum per-dimension
agreement, then v2 over v1). On Chad's dated decision for (c) (November 25, 2026),
`freeze_judge(..., phase_a_not_met=True, decision_ref=TEXT)` freezes exactly that run:
it refuses when any report on the assessment is `ready` (the plain freeze then applies),
any report of another run, a missing or blank decision reference and a second selection,
and its basis has status `pending`, every reason of the report and the decision
reference. A calibration report on a run matched to such a selection (`--frozen-judge`,
B8) puts `Phase A not met` first among its reasons and on its status line, pins the
selection under `pins.frozen_judge`, and is never `ready`; a run matched to an identity
that no selection holds is refused, and so is a run matched to the judge frozen from its
own assessment (re-checking the selection re-derives every report there, so such a run is
never calibrated). The selection is written once to
`<artifact root>/judge-selections/<selection_id>.json` with the report's SHA-256 and the
run's frozen identity (`judge.frozen_identity`), which a later `--frozen-judge` run must
match exactly. `load_selection` re-checks every receipt against the evidence: it must be
its assessment's only selection; its run, prompt version and frozen identity must be its
report's; a `ready` basis needs a `ready` report; and `preregistered_choice`, re-run, must
still choose that report's run, with Phase A met for a `ready` basis and not met for
option (c)'s `pending` one.

**Void** (Chad's decision of November 25, 2026, "Void it, keep all files (Recommended)").
`void_judge_run` writes one write-once record, `<judge run>/void.json`, sealed by SHA-256,
for a judge run whose own ledgers show no completed attempt (valid or not) and that has no
calibration report; it holds the decision reference, the time, the counts it verified and
pins of the run's manifest and ledgers. It deletes, edits or moves no file and leaves a
`.judge.lock` in place. `preregistered_choice` (and so the freeze) skips a run only when its
void verifies on every load: the seal, the fields, and the run re-verified from its own
evidence with the same counts and pins and still no completed attempt. A void that does
not verify is refused, never skipped. The seal has no key: a resealed change to anything
re-derived from the run is refused, while the decision reference, the time and the lock
flag are protected only by the seal; a voided run is never calibrated, and a report that names one is
refused. The voided run still counts toward `judge.py`'s three measured runs per assessment.
Nothing here calls a model endpoint, and nothing is overwritten or repaired.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from contextvars import ContextVar
from fractions import Fraction
from pathlib import Path

from bonsai_help import acceptance, human_reference, judge, qualification
from bonsai_help import rubric as rubric_module
from bonsai_help.assessment import (
    Assessment,
    AssessmentError,
    assessment_directory,
    load_assessment,
    load_key,
)
from bonsai_help.collection import DOC_SOURCES, FIXTURES
from bonsai_help.config import REPOSITORY
from bonsai_help.doc_sources import CATEGORIES, load_config
from bonsai_help.evaluation_schemas import DIMENSIONS, Decisions, Judgment
from bonsai_help.judge_config import JudgeConfig
from bonsai_help.stats import CONFIDENCE, clopper_pearson
from bonsai_help.tracing import digest, exclusive, now, run_directory

CALIBRATION = "calibration"
SELECTIONS = "judge-selections"
SCHEMA_VERSION = "1"
SCOPE = "calibration on the selected items, not generalization"
STATUSES = ("ready", "pending", "diagnostic")
DISAGREEMENTS_SUFFIX = ".disagreements.json"
DISAGREEMENT_FIELDS = ("blind_id", "dimension", "human", "judge", "judge_reason")
LOCK = ".calibrate.lock"
SELECTION_LOCK = ".freeze.lock"
DEVELOPMENT_GROUP = "development"
CONFUSION = ("h1_j1", "h1_j0", "h0_j1", "h0_j0")
INSPECT = "preserve and inspect the files; a report or selection is never repaired or replaced"
# Decision 13's rule names exactly these prompt versions, each measured once, in order of
# preference: a measured run of any other version on the assessment is refused.
PREREGISTERED_VERSIONS = ("judge-v1", "judge-v2")
SELECTION_BASIS = {
    "status": "ready",
    "rule": (
        "B7 Decision 13, pre-registered: after judge-v1 and judge-v2 have each been measured "
        "once and no other prompt version measured, v2 if its calibration report is ready, "
        "else v1 if its report is ready; one frozen selection per assessment"
    ),
}
# Open question 7(c), built on Chad's dated decision of November 25, 2026 (DECISIONS.md,
# "Phase A not met; judge v2 carried to B8 (Chad's option (c))"): when no report is ready,
# `freeze_judge(..., phase_a_not_met=True, decision_ref=TEXT)` freezes the run the
# pre-registered tie-break carries forward, with a basis whose status is `pending`.
PHASE_A_NOT_MET = "Phase A not met"
PHASE_A_NOT_MET_RULE = (
    "B7 Decision 13, Open question 7(c), pre-registered: no calibration report on the "
    "assessment is ready, so Phase A is not met; among the measured runs of judge-v1 and "
    "judge-v2, the judge carried forward has more dimensions at or above the minimum, then "
    "the higher minimum per-dimension agreement, then the later prompt version; it is "
    "frozen only on Chad's dated decision, never as calibrated; one frozen selection per "
    "assessment"
)
PHASE_A_BASIS_FIELDS = frozenset({"status", "phase_a", "rule", "decision_ref", "reasons"})
DECISION_REF_MAX = 500
# The void of a judge run with no completed attempt (Chad, November 25, 2026: "Void it, keep
# all files (Recommended)"). It is written once inside the run's directory, never a
# `*.jsonl` file, so the run's own ledger hashes (`tracing.artifact_hashes`) are unchanged.
VOID = "void.json"
VOID_KIND = "judge_run_void"
VOID_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "assessment_id",
        "judge_run_id",
        "created_at",
        "decision_ref",
        "verified",
        "pins",
        "lock_present_at_void",
        "effect",
        "sha256",
    }
)
VOID_EFFECT = (
    "voided on Chad's dated decision: excluded from B7 Decision 13's pre-registered rule "
    "(calibration.preregistered_choice) and so from judge-freeze, and never calibrated; no "
    "file of the run was deleted, edited or moved, and a .judge.lock stays where it was; the "
    "run still counts toward the measured judge runs an assessment allows; its started "
    "requests stay disclosed as unknown outcomes"
)
# The assessments whose pre-registered choice is being re-checked by `load_selection`, so a
# selection is never re-checked from inside its own re-check.
_RECHECKING: ContextVar[frozenset[str]] = ContextVar("_RECHECKING", default=frozenset())
# Fields of a report that `freeze_judge` re-derives from the evidence and compares.
_DERIVED_EXCLUDED = frozenset({"report_id", "created_at", "sha256"})
REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "report_id",
        "created_at",
        "assessment_id",
        "kind",
        "judge_run_id",
        "purpose",
        "judge_status",
        "status",
        "reasons",
        "scope",
        "population",
        "judged",
        "unknown_outcomes",
        "reported_models",
        "confidence",
        "dimensions",
        "categories",
        "arms",
        "acceptance",
        "pins",
        "sha256",
    }
)
SELECTION_FIELDS = frozenset(
    {
        "schema_version",
        "selection_id",
        "created_at",
        "assessment_id",
        "judge_run_id",
        "report_id",
        "report_sha256",
        "basis",
        "prompt_version",
        "frozen_identity",
        "implementation",
        "sha256",
    }
)
# Placeholder credential sources for re-validating a recorded config; never read.
_RECORDED_KEY_ENV = "CALIBRATION_RECORDED_SETTINGS_UNUSED"
_RECORDED_KEY_FILE = "recorded-settings-credential-never-read"


class CalibrationError(ValueError):
    """A calibration report or judge selection is refused; nothing was written."""


# ------------------------------------------------------------------- agreement


def _rate(count: int, n: int, confidence) -> dict:
    """A rate with its exact interval; a zero denominator is undefined (null)."""
    if n == 0:
        return {"count": count, "n": n, "value": None, "interval": None}
    return {
        "count": count,
        "n": n,
        "value": count / n,
        "interval": list(clopper_pearson(count, n, confidence)),
    }


def _check_inputs(blind_ids: object, decisions: object, judgments: object) -> list[str]:
    if isinstance(blind_ids, (str, bytes)) or not isinstance(blind_ids, Sequence):
        raise ValueError("blind ids must be a list of distinct strings")
    order = list(blind_ids)
    if any(type(b) is not str for b in order) or len(set(order)) != len(order):
        raise ValueError("blind ids must be a list of distinct strings")
    if not isinstance(decisions, Mapping) or not isinstance(judgments, Mapping):
        raise ValueError("decisions and judgments must map blind ids to their records")
    selected = set(order)
    foreign = sorted((set(decisions) | set(judgments)) - selected, key=str)
    if foreign:
        raise ValueError(
            "decisions or judgments for blind ids outside the selection: "
            + ", ".join(map(str, foreign))
        )
    if any(not isinstance(value, Decisions) for value in decisions.values()):
        raise ValueError("each human decision must be a Decisions record")
    if any(not isinstance(value, Judgment) for value in judgments.values()):
        raise ValueError("each judgment must be a Judgment record")
    return order


def agreement(
    blind_ids: Sequence[str],
    decisions: Mapping[str, Decisions],
    judgments: Mapping[str, Judgment],
    *,
    confidence: float | Fraction = CONFIDENCE,
) -> dict:
    """Per-dimension agreement over every selected blind id (B7 Decision 8).

    Returns `{n, dimensions, disagreements}`. Each dimension row holds `n`, `matching`,
    `agreement` and its `interval`, `human_unresolved`, `judge_missing`, the `confusion`
    counts and `tpr` / `tnr` (`count`, `n`, `value`, `interval`). A blind id without human
    decisions is unresolved in every dimension; one without a judgment is missing. The
    disagreements are the resolved pairs that differ, in dimension then selection order,
    each with the judge's reason. Raises ValueError for foreign, duplicate or mistyped
    inputs."""
    order = _check_inputs(blind_ids, decisions, judgments)
    dimensions: dict[str, dict] = {}
    disagreements: list[dict] = []
    for dimension in DIMENSIONS:
        confusion = dict.fromkeys(CONFUSION, 0)
        human_unresolved = judge_missing = 0
        for blind_id in order:
            human = decisions[blind_id].values()[dimension] if blind_id in decisions else None
            verdict = judgments.get(blind_id)
            machine = getattr(verdict, dimension) if verdict is not None else None
            if human is None:
                human_unresolved += 1
            if machine is None:
                judge_missing += 1
            if human is None or machine is None:
                continue
            confusion[f"h{human}_j{machine.decision}"] += 1
            if human != machine.decision:
                disagreements.append(
                    {
                        "blind_id": blind_id,
                        "dimension": dimension,
                        "human": human,
                        "judge": machine.decision,
                        "judge_reason": machine.reason,
                    }
                )
        n = len(order)
        matching = confusion["h1_j1"] + confusion["h0_j0"]
        overall = _rate(matching, n, confidence)
        dimensions[dimension] = {
            "n": n,
            "matching": matching,
            "agreement": overall["value"],
            "interval": overall["interval"],
            "human_unresolved": human_unresolved,
            "judge_missing": judge_missing,
            "confusion": confusion,
            "tpr": _rate(confusion["h1_j1"], confusion["h1_j1"] + confusion["h1_j0"], confidence),
            "tnr": _rate(confusion["h0_j0"], confusion["h0_j0"] + confusion["h0_j1"], confidence),
        }
    return {"n": len(order), "dimensions": dimensions, "disagreements": disagreements}


# ------------------------------------------------------------------ evidence


def _assessment(root: Path, assessment_id: str) -> Assessment:
    try:
        return load_assessment(
            root, assessment_id, fixtures_dir=FIXTURES, doc_config=load_config(DOC_SOURCES)
        )
    except (AssessmentError, ValueError) as exc:
        raise CalibrationError(f"assessment: {exc}") from None


def _judge_run(made: Assessment, judge_run_id: str) -> tuple[dict, list, list, dict]:
    try:
        directory = judge.judge_directory(made.directory, judge_run_id)
    except judge.JudgeError as exc:
        raise CalibrationError(str(exc)) from None
    if not directory.is_dir():
        raise CalibrationError(f"no judge run {judge_run_id!r} for this assessment")
    if (directory / judge.LOCK).exists() or (directory / judge.LOCK).is_symlink():
        raise CalibrationError(
            f"{judge.LOCK} exists: the judge run is active, or one stopped abruptly; inspect "
            "it (it is never removed by code)"
        )
    try:
        return judge.validate_judge(directory, made)
    except judge.JudgeError as exc:
        raise CalibrationError(f"judge run {judge_run_id!r}: {exc}") from None


def _names(model: object, identity: object) -> set[str]:
    return {v.strip().casefold() for v in (model, identity) if isinstance(v, str)}


def _same_model(settings: dict, generator: dict) -> bool:
    return bool(
        _names(settings.get("model"), settings.get("model_identity"))
        & _names(generator.get("model"), generator.get("model_identity"))
    ) or (
        settings.get("model_sha256") is not None
        and settings.get("model_sha256") == generator.get("model_sha256")
    )


def _recorded_config(settings: dict) -> JudgeConfig:
    """The judge config a run recorded, rebuilt from its public settings (no credential is
    recorded, so placeholder sources stand in; they are never read). Refuses settings that
    the rebuilt config does not reproduce exactly."""
    values = {
        k: v for k, v in settings.items() if k not in ("authentication", "embedding_authentication")
    }
    if settings.get("authentication") == "file":
        values["api_key_file"] = _RECORDED_KEY_FILE
    else:
        values["api_key_env"] = _RECORDED_KEY_ENV
    if settings.get("embedding_authentication") == "file":
        values["embedding_api_key_file"] = _RECORDED_KEY_FILE
    elif settings.get("embedding_authentication") == "environment":
        values["embedding_api_key_env"] = _RECORDED_KEY_ENV
    config = JudgeConfig.model_validate(values)
    if config.public_settings() != settings:
        raise ValueError("the judge run's recorded settings do not form a judge config")
    return config


def _qualification_reason(
    root: Path, identity: dict, settings: dict, generators: list[dict]
) -> str | None:
    pinned = identity.get("qualification")
    if not isinstance(pinned, dict) or not isinstance(pinned.get("qualification_id"), str):
        return "the measured run pins no qualification receipt"
    try:
        qualification.validate_qualification(
            _recorded_config(settings), pinned["qualification_id"], generators, root
        )
    except ValueError as exc:
        return f"the qualification is not valid: {exc}"
    return None


def _model_reasons(attempts: list[dict], settings: dict, generators: list[dict]) -> list[str]:
    """Every reply must report the configured judge model; a generator's id is named."""
    model = settings.get("model")
    other = [
        a
        for a in attempts
        if a["error_type"] == "ModelIdentityMismatch"
        or (a["response_model"] is not None and a["response_model"] != model)
    ]
    if not other:
        return []
    aliases = [
        a for a in other if any(_same_model({"model": a["response_model"]}, g) for g in generators)
    ]
    reason = (
        f"{len(other)} judge repl{'y' if len(other) == 1 else 'ies'} reported a model id "
        "other than the configured judge model"
    )
    if aliases:
        reason += f" ({len(aliases)} of them a source generator's model id)"
    return [reason]


def _groups(root: Path, made: Assessment, order: list[str]) -> dict[str, list[str]]:
    if made.manifest["kind"] != "arm":
        return {DEVELOPMENT_GROUP: list(order)}
    try:
        key = load_key(root, made.manifest["assessment_id"])
    except (AssessmentError, ValueError) as exc:
        raise CalibrationError(f"assessment key: {exc}") from None
    groups: dict[str, list[str]] = {}
    for blind_id in order:
        groups.setdefault(key[blind_id]["arm"], []).append(blind_id)
    return groups


def _segment(blind_ids, decisions, judgments, confidence) -> dict:
    wanted = set(blind_ids)
    return agreement(
        blind_ids,
        {b: v for b, v in decisions.items() if b in wanted},
        {b: v for b, v in judgments.items() if b in wanted},
        confidence=confidence,
    )["dimensions"]


def _derive(root: Path, made: Assessment, judge_run_id: str) -> tuple[dict, list[dict]]:
    """The report body (no id, time or seal) and the disagreements, from verified evidence."""
    manifest_record = made.manifest
    kind = manifest_record["kind"]
    order = list(manifest_record["display_order"])
    rubric = made.rubric
    diagnostic: list[str] = []
    reasons: list[str] = []
    if kind != "arm":
        diagnostic.append(
            f"the assessment is kind {kind}: a development assessment's agreement is "
            "diagnostic only, never calibration"
        )
    reference = None
    try:
        reference = human_reference.load_reference(made)
    except human_reference.HumanReferenceError as exc:
        reasons.append(f"the human reference is not frozen and verified: {exc}")
    # A measured run is verified against its frozen reference: without it, refused here.
    manifest, starts, attempts, successful = _judge_run(made, judge_run_id)
    identity = manifest["identity"]
    settings = identity["settings"]
    purpose = manifest["purpose"]
    # A run matched to a frozen judge (B8) carries its selection's basis: a judge carried
    # forward with Phase A not met is disclosed first, and the report is never ready.
    frozen_pin = None
    disclosed: list[str] = []
    if identity.get("frozen_judge_sha256") is not None:
        matched = _frozen_selections(
            root, identity["frozen_judge_sha256"], manifest_record["assessment_id"]
        )
        carried = [s for s in matched if phase_a_not_met(s)]
        frozen_pin = {
            "selection_ids": [s["selection_id"] for s in matched],
            "phase_a_met": not carried,
        }
        disclosed = [_phase_a_disclosure(s) for s in carried]
    if purpose != "measured":
        diagnostic.append("a smoke judge run is diagnostic only, never calibration")
    try:
        generators = qualification.source_generators(root, manifest_record["sources"])
    except qualification.QualificationError as exc:
        raise CalibrationError(str(exc)) from None
    if any(_same_model(settings, g) for g in generators):
        diagnostic.append(
            "the judge is the same model as a source generator (model, model_identity or "
            "model_sha256): same model judging is diagnostic only"
        )
    if manifest["status"] != "complete":
        missing = len([b for b in order if b not in successful])
        reasons.append(
            f"the judge run is {manifest['status']}, not complete: {missing} of {len(order)} "
            "selected items have no valid judgment"
        )
    if purpose == "measured":
        found = _qualification_reason(root, identity, settings, generators)
        if found:
            reasons.append(found)
    reasons += _model_reasons(attempts, settings, generators)
    temperature = settings.get("temperature")
    for generator in generators:
        if not (
            isinstance(temperature, (int, float))
            and isinstance(generator.get("temperature"), (int, float))
            and temperature < generator["temperature"]
        ):
            reasons.append(
                f"the judge temperature {temperature} is not below the temperature of source "
                f"collection {generator['collection_id']} ({generator.get('temperature')})"
            )
    rubric_sha = rubric_module.rubric_sha256(rubric)
    if reference is not None and (
        reference["rubric_sha256"] != rubric_sha or reference["rubric_version"] != rubric.version
    ):
        reasons.append("the assessment's rubric pin differs from the reference's")

    confidence = rubric.thresholds.intervals.confidence
    dimensions = categories = arms = accepted = None
    disagreements: list[dict] = []
    if reference is not None:
        decisions = {
            b: Decisions.model_validate(reference["labels"][b]["decisions"]) for b in order
        }
        judgments = {b: Judgment.model_validate(a["judgment"]) for b, a in successful.items()}
        overall = agreement(order, decisions, judgments, confidence=confidence)
        disagreements = overall["disagreements"]
        accepted = acceptance.acceptance_result(overall["dimensions"], rubric)
        failing = accepted["failing_dimensions"]
        dimensions = {
            d: row | {"meets_minimum": d not in failing} for d, row in overall["dimensions"].items()
        }
        if failing:
            minimum = rubric.thresholds.human_judge_agreement.per_dimension_minimum
            reasons.append(
                f"dimensions below the per-dimension agreement minimum {minimum}: "
                + ", ".join(failing)
            )
        by_category = {c: [e.blind_id for e in made.queue if e.category == c] for c in CATEGORIES}
        categories = {
            c: _segment(members, decisions, judgments, confidence)
            for c, members in by_category.items()
        }
        arms = {
            group: _segment(members, decisions, judgments, confidence)
            for group, members in _groups(root, made, order).items()
        }
    completed = {a["attempt_id"] for a in attempts}
    unknown = [s["attempt_id"] for s in starts if s["attempt_id"] not in completed]
    status = "diagnostic" if diagnostic else ("pending" if disclosed or reasons else "ready")
    disagreements_bytes = _dumps(disagreements)
    pins = {
        "assessment_sha256": manifest_record["sha256"],
        "reference_sha256": None if reference is None else reference["sha256"],
        "judge_manifest_sha256": digest(manifest),
        "judge_fingerprint": manifest["fingerprint"],
        "judge_artifacts_sha256": manifest["artifacts_sha256"],
        "judge_identity": identity,
        "qualification": identity.get("qualification"),
        "rubric_version": rubric.version,
        "rubric_sha256": rubric_sha,
        "disagreements_sha256": hashlib.sha256(disagreements_bytes).hexdigest(),
    }
    if frozen_pin is not None:
        # Only a run matched to a frozen judge has this pin, so the reports written before
        # any selection existed (Phase A's) still re-derive byte for byte.
        pins["frozen_judge"] = frozen_pin
    body = {
        "schema_version": SCHEMA_VERSION,
        "assessment_id": manifest_record["assessment_id"],
        "kind": kind,
        "judge_run_id": judge_run_id,
        "purpose": purpose,
        "judge_status": manifest["status"],
        "status": status,
        "reasons": disclosed + diagnostic + reasons,
        "scope": SCOPE,
        "population": len(order),
        "judged": len(successful),
        "unknown_outcomes": {"count": len(unknown), "attempt_ids": unknown},
        "reported_models": sorted(
            {a["response_model"] for a in attempts if a["response_model"] is not None}
        ),
        "confidence": confidence,
        "dimensions": dimensions,
        "categories": categories,
        "arms": arms,
        "acceptance": accepted,
        "pins": pins,
    }
    return body, disagreements


# --------------------------------------------------------------------- files


def _dumps(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _sealed(record: dict) -> str:
    return digest({k: v for k, v in record.items() if k != "sha256"})


def _write_once(path: Path, data: bytes, what: str, hint: str = "choose a new id") -> None:
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
        raise CalibrationError(f"{what} already exists; {hint}") from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def _locked(path: Path, holder: str) -> ExitStack:
    stack = ExitStack()
    try:
        stack.enter_context(exclusive(path))
    except FileExistsError:
        raise CalibrationError(
            f"{path.name} exists: {holder} stopped abruptly; inspect it (it is never removed "
            "by code)"
        ) from None
    return stack


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _report_paths(assessment_dir: Path, report_id: str) -> tuple[Path, Path]:
    directory = Path(assessment_dir) / CALIBRATION
    if directory.is_symlink():
        raise CalibrationError(f"a symlinked {CALIBRATION} directory is not supported")
    try:
        target = run_directory(directory, report_id)
    except ValueError:
        raise CalibrationError(
            "report id must be 1-64 letters, digits, underscores or hyphens"
        ) from None
    return (
        target.with_name(f"{report_id}.json"),
        target.with_name(f"{report_id}{DISAGREEMENTS_SUFFIX}"),
    )


def calibration_report(
    root: Path, assessment_id: str, judge_run_id: str, report_id: str, *, write: bool = True
) -> dict:
    """Compute a judge run's calibration against the frozen human reference; with `write`,
    write the report and its disagreements file once (B7 Decisions 9 and 16).

    Returns the main report (no per-item disagreement). Every refusal comes before any
    write; a preview (`write=False`) writes nothing."""
    root = Path(root)
    made = _assessment(root, assessment_id)
    main, side = _report_paths(made.directory, report_id)
    if _present(_run_directory(made, judge_run_id) / VOID):
        raise CalibrationError(
            f"judge run {judge_run_id!r} is voided (its {VOID}): a voided run is never "
            "calibrated; nothing was written"
        )
    if write and (_present(main) or _present(side)):
        raise CalibrationError(
            f"calibration report {report_id!r} already exists (or an interrupted write left "
            f"one of its files); {INSPECT}"
        )
    body, disagreements = _derive(root, made, judge_run_id)
    report = {"report_id": report_id, "created_at": now(), **body}
    report["sha256"] = _sealed(report)
    if not write:
        return report
    main.parent.mkdir(exist_ok=True)
    with _locked(main.parent / LOCK, "a calibration report is being written, or a write"):
        if _present(main) or _present(side):
            raise CalibrationError(f"calibration report {report_id!r} already exists; {INSPECT}")
        _write_once(side, _dumps(disagreements), f"calibration report {report_id!r}")
        _write_once(main, _dumps(report), f"calibration report {report_id!r}")
    return report


def _read_json(path: Path, what: str) -> tuple[object, bytes]:
    if path.is_symlink():
        raise CalibrationError(f"{what} is a symlink; {INSPECT}")
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise CalibrationError(f"no {what}") from None
    except OSError:
        raise CalibrationError(f"{what} is unreadable; {INSPECT}") from None
    try:
        return json.loads(data), data
    except ValueError:
        raise CalibrationError(f"{what} is not JSON; {INSPECT}") from None


def _disagreements_valid(entries: object) -> bool:
    return isinstance(entries, list) and all(
        isinstance(e, dict) and list(e) == list(DISAGREEMENT_FIELDS) for e in entries
    )


def load_report(root: Path, assessment_id: str, report_id: str) -> dict:
    """A written calibration report, verified: its seal, its fields and the SHA-256 of its
    disagreements file. Returns the main report only."""
    try:
        directory = assessment_directory(Path(root), assessment_id)
    except ValueError as exc:
        raise CalibrationError(f"assessment: {exc}") from None
    main, side = _report_paths(directory, report_id)
    report, _ = _read_json(main, f"calibration report {report_id!r}")
    if (
        not isinstance(report, dict)
        or set(report) != REPORT_FIELDS
        or report["sha256"] != _sealed(report)
        or report["schema_version"] != SCHEMA_VERSION
        or report["report_id"] != report_id
        or report["assessment_id"] != assessment_id
        or report["status"] not in STATUSES
        or not isinstance(report["pins"], dict)
    ):
        raise CalibrationError(f"calibration report {report_id!r} changed; {INSPECT}")
    entries, data = _read_json(side, f"disagreements file of calibration report {report_id!r}")
    if hashlib.sha256(data).hexdigest() != report["pins"].get(
        "disagreements_sha256"
    ) or not _disagreements_valid(entries):
        raise CalibrationError(
            f"the disagreements file of calibration report {report_id!r} changed; {INSPECT}"
        )
    return report


def _percent(value: float | None) -> str:
    return "undefined" if value is None else f"{value * 100:.1f}%"


def _shown(rate: dict) -> str:
    text = f"{rate['count']}/{rate['n']} = {_percent(rate['value'])}"
    if rate["interval"] is not None:
        low, high = rate["interval"]
        text += f" [{_percent(low)}, {_percent(high)}]"
    return text


def _row_line(name: str, row: dict) -> str:
    overall = _shown(
        {
            "count": row["matching"],
            "n": row["n"],
            "value": row["agreement"],
            "interval": row["interval"],
        }
    )
    c = row["confusion"]
    line = f"  {name}: agreement {overall}"
    if "meets_minimum" in row:
        line += "; meets the minimum" if row["meets_minimum"] else "; BELOW the minimum"
    return (
        f"{line}; TPR {_shown(row['tpr'])}; TNR {_shown(row['tnr'])}; human unresolved "
        f"{row['human_unresolved']}, judge missing {row['judge_missing']}; confusion h1j1 "
        f"{c['h1_j1']}, h1j0 {c['h1_j0']}, h0j1 {c['h0_j1']}, h0j0 {c['h0_j0']}"
    )


def report_lines(report: dict) -> list[str]:
    """The aggregate figures a report prints: no blind id paired with a decision, no judge
    reason and no model id. The first line is the status."""
    status = report["status"]
    line = (
        "status: diagnostic (never calibration)" if status == "diagnostic" else f"status: {status}"
    )
    frozen = report["pins"].get("frozen_judge")
    if isinstance(frozen, dict) and frozen.get("phase_a_met") is False:
        line += (
            f" ({PHASE_A_NOT_MET}: the judge was carried forward under Chad's option (c) "
            "and is never calibration)"
        )
    lines = [line]
    lines += (
        ["reasons:", *(f"  - {r}" for r in report["reasons"])]
        if report["reasons"]
        else ["reasons: none"]
    )
    unknown = report["unknown_outcomes"]
    lines += [
        f"scope: {report['scope']}",
        f"assessment {report['assessment_id']} (kind {report['kind']}), judge run "
        f"{report['judge_run_id']} ({report['purpose']}, {report['judge_status']}): "
        f"{report['population']} items, {report['judged']} judged",
        f"unknown outcomes (disclosed, each used up its attempt): {unknown['count']}"
        + (f" ({', '.join(unknown['attempt_ids'])})" if unknown["attempt_ids"] else ""),
    ]
    if report["dimensions"] is None:
        lines.append("no agreement figures: there is no frozen human reference")
        return lines
    confidence = report["confidence"]
    minimum = report["acceptance"]["policy"]["minimum"]
    lines.append(
        f"per-dimension agreement (minimum {minimum}, inclusive; {confidence * 100:g}% "
        "Clopper-Pearson intervals):"
    )
    lines += [_row_line(d, row) for d, row in report["dimensions"].items()]
    lines.append("per category (no threshold):")
    for category, rows in report["categories"].items():
        lines += [_row_line(f"{category} {d}", row) for d, row in rows.items()]
    lines.append("per arm (no threshold):")
    for group, rows in report["arms"].items():
        lines += [_row_line(f"{group} {d}", row) for d, row in rows.items()]
    lines.append(
        f"per-item disagreements are in {report['report_id']}{DISAGREEMENTS_SUFFIX} (not shown)"
    )
    return lines


# ------------------------------------------------------------------ the void


def _run_directory(made: Assessment, judge_run_id: str) -> Path:
    try:
        return judge.judge_directory(made.directory, judge_run_id)
    except judge.JudgeError as exc:
        raise CalibrationError(str(exc)) from None


def _void_evidence(made: Assessment, directory: Path) -> tuple[dict, dict, tuple]:
    """What a void verifies, derived from the run's own evidence (its lock is not read):
    the counts, the pins and `judge.validate_judge`'s result."""
    try:
        verified_run = judge.validate_judge(directory, made)
    except judge.JudgeError as exc:
        raise CalibrationError(f"judge run {directory.name!r}: {exc}") from None
    manifest, starts, attempts, _ = verified_run
    completed = {a["attempt_id"] for a in attempts}
    counts = {
        "purpose": manifest["purpose"],
        "run_status": manifest["status"],
        "prompt_version": manifest["identity"]["prompt_version"],
        "started_attempts": len(starts),
        "completed_attempts": len(attempts),
        "unknown_outcomes": [s["attempt_id"] for s in starts if s["attempt_id"] not in completed],
    }
    pins = {
        "assessment_sha256": made.manifest["sha256"],
        "judge_manifest_sha256": digest(manifest),
        "judge_fingerprint": manifest["fingerprint"],
        "judge_artifacts_sha256": manifest["artifacts_sha256"],
    }
    return counts, pins, verified_run


def _refuse_completed(judge_run_id: str, attempts: list[dict], now_or_then: str) -> None:
    if attempts:
        valid = sum(1 for a in attempts if a["valid"] is True)
        raise CalibrationError(
            f"judge run {judge_run_id!r} {now_or_then} {len(attempts)} completed attempt(s) "
            f"({valid} valid, {len(attempts) - valid} not) in its own ledgers; only a run with "
            "no completed attempt can be voided"
        )


def _verified_void(made: Assessment, judge_run_id: str) -> tuple[dict, tuple] | None:
    """A judge run's void and its re-verified evidence, or None when the run has no void.
    A void that does not verify now (a record changed without a reseal, a resealed change
    to anything re-derived from the run, a changed run, or a run that has a completed
    attempt since) is refused, never treated as absent. The unkeyed seal alone protects
    the decision reference, the time and the lock flag."""
    directory = _run_directory(made, judge_run_id)
    path = directory / VOID
    if not _present(path):
        return None
    what = f"the void of judge run {judge_run_id!r}"
    record, _ = _read_json(path, what)
    if (
        not isinstance(record, dict)
        or set(record) != VOID_FIELDS
        or record["sha256"] != _sealed(record)
        or record["schema_version"] != SCHEMA_VERSION
        or record["kind"] != VOID_KIND
        or record["assessment_id"] != made.manifest["assessment_id"]
        or record["judge_run_id"] != judge_run_id
        or record["effect"] != VOID_EFFECT
        or type(record["lock_present_at_void"]) is not bool
        or not isinstance(record["created_at"], str)
    ):
        raise CalibrationError(f"{what} changed; {INSPECT}")
    try:
        _decision_ref(record["decision_ref"], needed_by="judge-void")
    except CalibrationError:
        raise CalibrationError(f"{what} changed; {INSPECT}") from None
    counts, pins, verified_run = _void_evidence(made, directory)
    _refuse_completed(judge_run_id, verified_run[2], "is voided, but now has")
    if record["verified"] != counts or record["pins"] != pins:
        raise CalibrationError(f"{what} no longer matches the run's evidence; {INSPECT}")
    return record, verified_run


def void_judge_run(root: Path, assessment_id: str, judge_run_id: str, decision_ref: str) -> dict:
    """Void a judge run with no completed attempt, on Chad's dated decision (which
    `decision_ref` names): write `<judge run>/void.json` once and nothing else.

    Refuses a missing, blank or multi-line decision reference, a run whose own ledgers
    (verified by `judge.validate_judge`, whatever its lock) hold any completed attempt,
    valid or not, a run with a calibration report and a second void. Every refusal comes
    before the write. No file of the run is deleted, edited or moved, and a `.judge.lock`
    stays in place."""
    root = Path(root)
    decision_ref = _decision_ref(decision_ref, needed_by="judge-void")
    made = _assessment(root, assessment_id)
    directory = _run_directory(made, judge_run_id)
    if not directory.is_dir():
        raise CalibrationError(f"no judge run {judge_run_id!r} for this assessment")
    path = directory / VOID
    if _present(path):
        raise CalibrationError(
            f"judge run {judge_run_id!r} already has a void ({VOID}); a void is written once"
        )
    counts, pins, verified_run = _void_evidence(made, directory)
    _refuse_completed(judge_run_id, verified_run[2], "has")
    reports = sorted(
        r for r, w in _written_reports(root, made).items() if w["judge_run_id"] == judge_run_id
    )
    if reports:
        raise CalibrationError(
            f"judge run {judge_run_id!r} has calibration report(s) {', '.join(reports)}; a run "
            "with a report is never voided"
        )
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": VOID_KIND,
        "assessment_id": made.manifest["assessment_id"],
        "judge_run_id": judge_run_id,
        "created_at": now(),
        "decision_ref": decision_ref,
        "verified": counts,
        "pins": pins,
        "lock_present_at_void": _present(directory / judge.LOCK),
        "effect": VOID_EFFECT,
    }
    record["sha256"] = _sealed(record)
    _write_once(
        path, _dumps(record), f"the void of judge run {judge_run_id!r}", "a void is written once"
    )
    return record


def void_status(root: Path, assessment_id: str, judge_run_id: str) -> dict | None:
    """A voided judge run's blind status (`judge.judge_status`'s fields, `status` voided,
    the run's own status as `run_status`, and the void), verified; None for a run with no
    void."""
    made = _assessment(Path(root), assessment_id)
    found = _verified_void(made, judge_run_id)
    if found is None:
        return None
    record, (manifest, starts, attempts, successful) = found
    summary = judge._summary(manifest, made, starts, attempts, successful)
    summary["status"] = "voided"
    summary["run_status"] = manifest["status"]
    summary["void"] = {
        "decision_ref": record["decision_ref"],
        "created_at": record["created_at"],
        "lock_present_at_void": record["lock_present_at_void"],
        "sha256": record["sha256"],
    }
    return summary


# ---------------------------------------------------------------- the freeze


def selection_path(root: Path, selection_id: str) -> Path:
    """`root/judge-selections/<id>.json`; under runs/ or outside the repository."""
    root = Path(root)
    resolved = root.resolve()
    if resolved.is_relative_to(REPOSITORY) and not resolved.is_relative_to(REPOSITORY / "runs"):
        raise CalibrationError("judge selections must stay under runs/ or outside the repository")
    if (root / SELECTIONS).is_symlink():
        raise CalibrationError(f"a symlinked {SELECTIONS} directory is not supported")
    try:
        target = run_directory(root / SELECTIONS, selection_id)
    except ValueError:
        raise CalibrationError(
            "selection id must be 1-64 letters, digits, underscores or hyphens"
        ) from None
    return target.with_name(f"{selection_id}.json")


def _written_reports(root: Path, made: Assessment) -> dict[str, dict]:
    """Every calibration report of the assessment, verified. Anything else in the
    calibration directory (a lock, a leftover temporary file, a disagreements file with no
    main report) is an interrupted or active write to inspect, and is refused."""
    directory = made.directory / CALIBRATION
    if directory.is_symlink():
        raise CalibrationError(f"a symlinked {CALIBRATION} directory is not supported")
    if not directory.is_dir():
        return {}
    names = {path.name for path in directory.iterdir()}
    if LOCK in names:
        raise CalibrationError(
            f"{LOCK} exists: a calibration report is being written, or a write stopped "
            "abruptly; inspect it (it is never removed by code)"
        )
    reports: dict[str, dict] = {}
    for name in sorted(names):
        if name.endswith(DISAGREEMENTS_SUFFIX):
            report_id = name[: -len(DISAGREEMENTS_SUFFIX)]
            if f"{report_id}.json" not in names:
                raise CalibrationError(
                    f"calibration report {report_id!r} has a disagreements file but no main "
                    f"report: its write was interrupted; {INSPECT}"
                )
            continue
        if name.startswith(".") or not name.endswith(".json"):
            raise CalibrationError(
                f"unexpected file {name!r} among the calibration reports (an interrupted "
                f"write?); {INSPECT}"
            )
        report_id = name.removesuffix(".json")
        reports[report_id] = load_report(root, made.manifest["assessment_id"], report_id)
    return reports


def _minimum_agreement(dimensions: dict | None) -> tuple[int, Fraction | None, dict | None]:
    """Dimensions at or above the minimum, and the lowest per-dimension agreement."""
    if not dimensions:
        return 0, None, None
    lowest = min(dimensions.values(), key=lambda row: Fraction(row["matching"], row["n"] or 1))
    meeting = sum(1 for row in dimensions.values() if row["meets_minimum"])
    return (
        meeting,
        Fraction(lowest["matching"], lowest["n"] or 1),
        {"matching": lowest["matching"], "n": lowest["n"]},
    )


def preregistered_choice(root: Path, assessment_id: str) -> dict:
    """The judge Decision 13's pre-registered rule chooses on this assessment.

    The rule applies only once each of `PREREGISTERED_VERSIONS` has been measured exactly
    once, no other prompt version has been measured on the assessment (a third measured
    run, such as a `judge-v3` or a `judge-v1.1`, needs Chad's dated decision and a new
    rule), and every measured run has a written calibration report. Every report is
    verified and re-derived from the evidence. The choice is v2 if its report is `ready`,
    else v1 if its report is `ready` (`phase_a_met` true). Otherwise Phase A is not met
    (`phase_a_met` false), and the choice is the run the rule would carry forward under
    Open question 7(c): more dimensions at or above the minimum, then the higher minimum
    per-dimension agreement, then the later prompt version (v2 over v1). A judge run whose
    void verifies (`void_judge_run`) is left out and listed under `voided`; a void that does
    not verify is refused. Returns `{phase_a_met, judge_run_id, prompt_version, report_ids,
    runs, voided}`; raises CalibrationError when the rule cannot be applied."""
    root = Path(root)
    made = _assessment(root, assessment_id)
    reports = _written_reports(root, made)
    judges_dir = made.directory / judge.JUDGES
    run_ids = (
        sorted(p.name for p in judges_dir.iterdir() if not p.name.startswith("."))
        if judges_dir.is_dir()
        else []
    )
    measured: dict[str, dict] = {}
    voided: list[str] = []
    for run_id in run_ids:
        # A run is skipped only when its void verifies now; a void that does not is refused.
        if _verified_void(made, run_id) is not None:
            voided.append(run_id)
            continue
        manifest = _judge_run(made, run_id)[0]
        if manifest["purpose"] == "measured":
            measured[run_id] = manifest
    seen: dict[str, str] = {}
    for run_id, manifest in measured.items():
        version = manifest["identity"]["prompt_version"]
        if version not in PREREGISTERED_VERSIONS:
            raise CalibrationError(
                f"measured judge run {run_id!r} is {version}, outside Decision 13's "
                "pre-registered rule, which names only "
                + " and ".join(PREREGISTERED_VERSIONS)
                + "; a measured run of another prompt version (a third measured run) needs "
                "Chad's dated decision and a new rule before any judge is frozen on this "
                "assessment"
            )
        if version in seen:
            raise CalibrationError(
                f"{version} was measured more than once on this assessment (judge runs "
                f"{seen[version]!r} and {run_id!r}); Decision 13's rule compares one measured "
                "run per prompt version, so a freeze needs a new dated decision"
            )
        seen[version] = run_id
    derived: dict[str, dict] = {}
    for report_id, written in reports.items():
        run_id = written["judge_run_id"]
        if run_id in voided:
            raise CalibrationError(
                f"calibration report {report_id!r} is of the voided judge run {run_id!r}; a "
                f"voided run is never calibrated; {INSPECT}"
            )
        if run_id not in derived:
            derived[run_id] = _derive(root, made, run_id)[0]
        stored = {k: v for k, v in written.items() if k not in _DERIVED_EXCLUDED}
        if derived[run_id] != stored:
            raise CalibrationError(
                f"the evidence of calibration report {report_id!r} changed since it was "
                f"written (now {derived[run_id]['status']}); {INSPECT}"
            )
    runs: list[dict] = []
    for run_id, manifest in measured.items():
        version = manifest["identity"]["prompt_version"]
        report_ids = [r for r, written in reports.items() if written["judge_run_id"] == run_id]
        if not report_ids:
            raise CalibrationError(
                f"measured judge run {run_id!r} ({version}) has no calibration report; "
                "Decision 13's rule needs every measured run's report (run calibrate first)"
            )
        body = derived[run_id]
        meeting, lowest, shown = _minimum_agreement(body["dimensions"])
        runs.append(
            {
                "judge_run_id": run_id,
                "prompt_version": version,
                "status": body["status"],
                "report_ids": report_ids,
                "dimensions_at_minimum": meeting,
                "minimum_agreement": shown,
                "_order": (
                    meeting,
                    lowest if lowest is not None else Fraction(-1),
                    PREREGISTERED_VERSIONS.index(version),
                ),
            }
        )
    versions = {run["prompt_version"] for run in runs}
    missing = [v for v in PREREGISTERED_VERSIONS if v not in versions]
    if missing:
        raise CalibrationError(
            "Decision 13's rule applies after "
            + " and ".join(PREREGISTERED_VERSIONS)
            + " have each been measured once on this assessment; not yet measured: "
            + ", ".join(missing)
        )
    by_version = {run["prompt_version"]: run for run in runs}
    # v2 if its report is ready, else v1 if its report is ready.
    ready = [
        by_version[v]
        for v in reversed(PREREGISTERED_VERSIONS)
        if by_version[v]["status"] == "ready"
    ]
    if ready:
        chosen = ready[0]
    else:
        chosen = max(runs, key=lambda run: run["_order"])
    for run in runs:
        del run["_order"]
    return {
        "phase_a_met": bool(ready),
        "judge_run_id": chosen["judge_run_id"],
        "prompt_version": chosen["prompt_version"],
        "report_ids": chosen["report_ids"],
        "runs": runs,
        "voided": voided,
    }


def _selections_for(root: Path, assessment_id: str) -> list[str]:
    """The selection ids already written for this assessment (any unreadable selection is
    refused, since it might be this assessment's)."""
    directory = Path(root) / SELECTIONS
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith("."):
            continue
        try:
            record = json.loads(path.read_bytes()) if not path.is_symlink() else None
        except (OSError, ValueError):
            record = None
        if not isinstance(record, dict):
            raise CalibrationError(f"judge selection file {path.name!r} is unreadable; {INSPECT}")
        if record.get("assessment_id") == assessment_id:
            found.append(path.name.removesuffix(".json"))
    return found


def _refuse_second_selection(root: Path, assessment_id: str) -> None:
    existing = _selections_for(root, assessment_id)
    if existing:
        raise CalibrationError(
            f"assessment {assessment_id!r} already has a frozen judge selection "
            f"({', '.join(existing)}); a second selection is never written"
        )


def _decision_ref(value: object, needed_by: str = "--phase-a-not-met") -> str:
    """The reference to Chad's dated decision: one nonblank line of printable text."""
    if not isinstance(value, str) or not value.strip():
        raise CalibrationError(
            f"{needed_by} needs --decision-ref, a reference to Chad's dated decision "
            "(for example its DECISIONS.md entry); nothing was written"
        )
    text = value.strip()
    if len(text) > DECISION_REF_MAX or not text.isprintable():
        raise CalibrationError(
            f"the decision reference must be one line of at most {DECISION_REF_MAX} printable "
            "characters; nothing was written"
        )
    return text


def _phase_a_basis(report: dict, decision_ref: str) -> dict:
    return {
        "status": "pending",
        "phase_a": "not met",
        "rule": PHASE_A_NOT_MET_RULE,
        "decision_ref": decision_ref,
        "reasons": list(report["reasons"]),
    }


def phase_a_not_met(selection: dict) -> bool:
    """Whether a selection carried a judge forward with Phase A not met (option (c))."""
    basis = selection.get("basis")
    return isinstance(basis, dict) and basis.get("status") == "pending"


def _phase_a_disclosure(selection: dict) -> str:
    basis = selection["basis"]
    return (
        f"{PHASE_A_NOT_MET}: this judge was carried forward under Chad's option (c) (judge "
        f"selection {selection['selection_id']}, basis status pending, from calibration "
        f"report {selection['report_id']} on assessment {selection['assessment_id']}; "
        f"decision: {basis['decision_ref']}); no Phase A report met the per-dimension "
        "agreement minimum, so a report made with this judge is never calibration"
    )


def _check_phase_a_not_met(root: Path, assessment_id: str, report: dict) -> None:
    """Option (c)'s preconditions: no report on the assessment is ready, and the report is
    one of the run that Decision 13's tie-break carries forward."""
    choice = preregistered_choice(root, assessment_id)
    ready = sorted(
        r
        for r, written in _written_reports(root, _assessment(root, assessment_id)).items()
        if written["status"] == "ready"
    )
    if choice["phase_a_met"] or ready:
        raise CalibrationError(
            "a calibration report on this assessment is ready ("
            + (", ".join(ready) or choice["judge_run_id"])
            + "): Phase A is met, so --phase-a-not-met is refused and the normal judge-freeze "
            "applies"
        )
    if choice["judge_run_id"] != report["judge_run_id"]:
        raise CalibrationError(
            f"with Phase A not met, Decision 13's pre-registered tie-break carries judge run "
            f"{choice['judge_run_id']!r} ({choice['prompt_version']}) forward, not "
            f"{report['judge_run_id']!r}; use one of its reports "
            f"({', '.join(choice['report_ids'])})"
        )
    if report["status"] != "pending":
        raise CalibrationError(
            f"--phase-a-not-met carries forward only a pending report of a measured run; "
            f"{report['report_id']!r} is {report['status']}"
        )


def freeze_judge(
    root: Path,
    assessment_id: str,
    report_id: str,
    selection_id: str,
    *,
    phase_a_not_met: bool = False,
    decision_ref: str | None = None,
) -> dict:
    """Freeze the judge of a `ready` calibration report (B7 Decision 13); written once.

    The report must be the one Decision 13's pre-registered rule chooses
    (`preregistered_choice`), and the assessment must have no frozen selection yet. Every
    report on the assessment is verified and re-derived from the evidence; any difference
    since it was written is refused. The selection pins the report's SHA-256 and the run's
    frozen identity, which a later `--frozen-judge` run must match exactly.

    With `phase_a_not_met` (Open question 7(c), on Chad's dated decision, which
    `decision_ref` names), no report on the assessment may be ready, and the report must be
    one of the run the pre-registered tie-break carries forward. The selection's basis then
    has status `pending`, every reason of that report and the decision reference, and every
    later calibration report made with the judge states that Phase A was not met."""
    root = Path(root)
    path = selection_path(root, selection_id)
    if _present(path):
        raise CalibrationError(f"judge selection {selection_id!r} already exists; choose a new id")
    if phase_a_not_met:
        decision_ref = _decision_ref(decision_ref)
    elif decision_ref is not None:
        raise CalibrationError(
            "--decision-ref is only for --phase-a-not-met (a ready report needs no decision "
            "reference); nothing was written"
        )
    report = load_report(root, assessment_id, report_id)
    if phase_a_not_met:
        _refuse_second_selection(root, assessment_id)
        _check_phase_a_not_met(root, assessment_id, report)
        basis = _phase_a_basis(report, decision_ref)
    else:
        if report["status"] != "ready":
            hint = (
                "; with no ready report Phase A is not met, and carrying a judge forward needs "
                "Chad's dated decision and --phase-a-not-met --decision-ref"
                if report["status"] == "pending"
                else ""
            )
            raise CalibrationError(
                f"judge-freeze accepts only a ready calibration report; {report_id!r} is "
                f"{report['status']}{hint}"
            )
        _refuse_second_selection(root, assessment_id)
        choice = preregistered_choice(root, assessment_id)
        if choice["judge_run_id"] != report["judge_run_id"]:
            raise CalibrationError(
                f"Decision 13's pre-registered rule chooses judge run "
                f"{choice['judge_run_id']!r} ({choice['prompt_version']}), not "
                f"{report['judge_run_id']!r}; freeze one of its reports "
                f"({', '.join(choice['report_ids'])})"
            )
        basis = dict(SELECTION_BASIS)
    made = _assessment(root, assessment_id)
    main, _ = _report_paths(made.directory, report_id)
    report_sha256 = hashlib.sha256(main.read_bytes()).hexdigest()
    identity = report["pins"]["judge_identity"]
    selection = {
        "schema_version": SCHEMA_VERSION,
        "selection_id": selection_id,
        "created_at": now(),
        "assessment_id": assessment_id,
        "judge_run_id": report["judge_run_id"],
        "report_id": report_id,
        "report_sha256": report_sha256,
        "basis": basis,
        "prompt_version": identity["prompt_version"],
        "frozen_identity": identity["frozen_identity"],
        "implementation": identity["implementation"],
    }
    selection["sha256"] = _sealed(selection)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path.parent / SELECTION_LOCK, "a judge selection is being written, or a write"):
        _refuse_second_selection(root, assessment_id)
        _write_once(path, _dumps(selection), f"judge selection {selection_id!r}")
    return selection


def _basis_valid(basis: object, report: object) -> bool:
    """A ready basis for a ready report, or option (c)'s pending basis holding its pending
    report's reasons."""
    if basis == SELECTION_BASIS:
        return isinstance(report, dict) and report.get("status") == "ready"
    if not isinstance(basis, dict) or set(basis) != PHASE_A_BASIS_FIELDS:
        return False
    try:
        decision_ref = _decision_ref(basis["decision_ref"])
    except CalibrationError:
        return False
    return (
        isinstance(report, dict)
        and report.get("status") == "pending"
        and isinstance(report.get("reasons"), list)
        and bool(report["reasons"])
        and basis == _phase_a_basis(report, decision_ref)
    )


def load_selection(root: Path, selection_id: str) -> dict:
    """A judge selection, verified: its seal and fields, the only selection of its
    assessment, its report's file SHA-256, its basis (ready for a ready report, or option
    (c)'s pending basis with that pending report's reasons), its binding to that report,
    and Decision 13's rule re-run on the evidence now (`preregistered_choice` must choose
    that report's run, with Phase A met for a ready basis and not met for a pending one).
    Its `frozen_identity` is what a `--frozen-judge` run passes to `judge.judge_run`;
    `phase_a_not_met` says whether it carried a judge forward with Phase A not met."""
    root = Path(root)
    path = selection_path(root, selection_id)
    selection, _ = _read_json(path, f"judge selection {selection_id!r}")
    if (
        not isinstance(selection, dict)
        or set(selection) != SELECTION_FIELDS
        or selection["sha256"] != _sealed(selection)
        or selection["schema_version"] != SCHEMA_VERSION
        or selection["selection_id"] != selection_id
        or not isinstance(selection["frozen_identity"], dict)
    ):
        raise CalibrationError(f"judge selection {selection_id!r} changed; {INSPECT}")
    if not isinstance(selection["assessment_id"], str):
        raise CalibrationError(f"judge selection {selection_id!r} changed; {INSPECT}")
    others = _selections_for(root, selection["assessment_id"])
    if len(others) > 1:
        raise CalibrationError(
            f"assessment {selection['assessment_id']!r} has more than one judge selection "
            f"({', '.join(others)}); one is written per assessment, so none of them is "
            f"used; {INSPECT}"
        )
    try:
        directory = assessment_directory(root, selection["assessment_id"])
        main, _ = _report_paths(directory, selection["report_id"])
    except (ValueError, TypeError) as exc:
        raise CalibrationError(f"judge selection {selection_id!r}: {exc}") from None
    report, data = _read_json(main, f"calibration report {selection['report_id']!r}")
    if hashlib.sha256(data).hexdigest() != selection["report_sha256"]:
        raise CalibrationError(
            f"the calibration report of judge selection {selection_id!r} changed; {INSPECT}"
        )
    if not _basis_valid(selection["basis"], report) or not _bound_to(selection, report):
        raise CalibrationError(f"judge selection {selection_id!r} changed; {INSPECT}")
    _recheck_rule(root, selection, report)
    return selection


def _bound_to(selection: dict, report: object) -> bool:
    """The selection's run, prompt version, frozen identity and implementation are its
    report's (what `freeze_judge` copied from it)."""
    pins = report.get("pins") if isinstance(report, dict) else None
    identity = pins.get("judge_identity") if isinstance(pins, dict) else None
    return (
        isinstance(identity, dict)
        and report.get("assessment_id") == selection["assessment_id"]
        and report.get("report_id") == selection["report_id"]
        and report.get("judge_run_id") == selection["judge_run_id"]
        and identity.get("prompt_version") == selection["prompt_version"]
        and identity.get("frozen_identity") == selection["frozen_identity"]
        and identity.get("implementation") == selection["implementation"]
    )


def _recheck_rule(root: Path, selection: dict, report: dict) -> None:
    """Every receipt holds only the run that Decision 13's rule, re-run on the evidence
    now, chooses: with Phase A met for a ready basis, and carried forward by the tie-break
    with Phase A not met for option (c)'s pending basis."""
    assessment_id = selection["assessment_id"]
    selection_id = selection["selection_id"]
    checking = _RECHECKING.get()
    if assessment_id in checking:
        raise CalibrationError(
            f"judge selection {selection_id!r} is re-checked from inside its own re-check: "
            f"a calibration report re-derived for {assessment_id!r}'s rule is of a run "
            "matched to a frozen judge whose own re-check leads back to it (a cycle of "
            f"selections across assessments), so none of them is used; {INSPECT}"
        )
    token = _RECHECKING.set(checking | {assessment_id})
    try:
        choice = preregistered_choice(root, assessment_id)
    except CalibrationError as exc:
        raise CalibrationError(
            f"judge selection {selection_id!r}: the pre-registered rule cannot be re-run on "
            f"its assessment: {exc}"
        ) from None
    finally:
        _RECHECKING.reset(token)
    pending = phase_a_not_met(selection)
    if choice["phase_a_met"] == pending or choice["judge_run_id"] != report["judge_run_id"]:
        if pending:
            verb = "carries"
            named = "none: Phase A is met" if choice["phase_a_met"] else None
        else:
            verb = "chooses"
            named = None if choice["phase_a_met"] else "none ready: Phase A is not met"
        raise CalibrationError(
            f"judge selection {selection_id!r} {verb} judge run {report['judge_run_id']!r} "
            f"forward, but Decision 13's pre-registered rule, re-run on the evidence, "
            f"{verb} {named or repr(choice['judge_run_id'])}; {INSPECT}"
        )


def _frozen_selections(root: Path, frozen_sha256: str, assessment_id: str) -> list[dict]:
    """The verified selections whose frozen identity a `--frozen-judge` run on
    `assessment_id` matched. A run matched to an identity that no selection holds is
    refused: whether Phase A was met for its judge cannot be stated. A run matched to the
    judge frozen from its own assessment is refused before that selection is loaded:
    re-checking the selection re-derives every report on that assessment, so such a run is
    never calibrated."""
    directory = Path(root) / SELECTIONS
    if directory.is_symlink():
        raise CalibrationError(f"a symlinked {SELECTIONS} directory is not supported")
    matched = []
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if path.name.startswith(".") or not path.name.endswith(".json"):
                continue
            selection_id = path.name.removesuffix(".json")
            raw, _ = _read_json(
                selection_path(root, selection_id), f"judge selection {selection_id!r}"
            )
            if (
                isinstance(raw, dict)
                and raw.get("assessment_id") == assessment_id
                and isinstance(raw.get("frozen_identity"), dict)
                and digest(raw["frozen_identity"]) == frozen_sha256
            ):
                raise CalibrationError(
                    f"the judge run is matched to judge selection {selection_id!r}, the judge "
                    f"frozen from its own assessment {assessment_id!r}; a run on that "
                    "assessment is never calibrated against it (the selection's re-check "
                    "re-derives every report there); judge B8's assessment with it instead"
                )
            selection = load_selection(root, selection_id)
            if digest(selection["frozen_identity"]) == frozen_sha256:
                matched.append(selection)
    if not matched:
        raise CalibrationError(
            "the judge run was matched to a frozen judge, but no judge selection under this "
            f"artifact root holds that identity, so whether Phase A was met cannot be stated; "
            f"{INSPECT}"
        )
    return matched
