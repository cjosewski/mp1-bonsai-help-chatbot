"""Judge qualification receipts: why a judge model may judge (B7 Decision 7).

A measured judge run needs a receipt, written once by `qualify` to
`<artifact root>/judge-qualifications/<id>.json`. The receipt records:

- `judge`: the judge's public settings, `model_identity` and `model_sha256` included
  (the artifact root is git-ignored or outside the repository; no credential value, name
  or path is ever recorded);
- `basis`: `distinct_model`, with the decision reference `BASIS["decision"]` (Chad chose a
  judge model of another family). The judge's `model`, `model_identity` and
  `model_sha256` must each differ from every source generator's, and a model name never
  equals a generator's model name or identity, in any letter case. PORTING-MAP's
  same-model basis (same model, another prompt, lower temperature) is not built; adding it
  is a new dated entry in `docs/DECISIONS.md`;
- `smoke_generators`: the generators of the smoke assessment, read from their recorded
  collection settings, against which the judge was found distinct;
- `evidence`: a complete smoke judge run on a development assessment (one that is never
  labeled), judged with the same model and the same `QUALIFIED_SETTINGS` (any prompt),
  in which every reply reported the configured model id and at least one reply exists.
  Unknown outcomes are allowed and recorded: their replies were never read.

The smoke run is read through `judge.judge_status` (imported when called, because the
judge in turn calls `validate_qualification`). Qualification needs these fields of that
status, `SMOKE_STATUS_FIELDS`: `status` (`complete` when every selected item has a valid
judgment), `purpose`, `settings` (the run's judge public settings), `population`,
`resolved`, `unresolved` (blind ids), `unknown_outcomes` (attempt ids) and
`reported_models` (every model id a reply reported). The receipt pins their SHA-256, and
`validate_qualification` re-reads the smoke run and refuses any change.

`validate_qualification` checks a receipt against a measured judge config (each of
`QUALIFIED_SETTINGS` must equal the receipt's) and against every source generator of the
assessment being judged (`source_generators`). The prompt, the example-pool settings and
the artifact root are not qualified: the evidence concerns the model and how it is called.

Nothing here calls a model endpoint, and a receipt is never overwritten or repaired.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from bonsai_help.assessment import Assessment, AssessmentError, load_assessment
from bonsai_help.collection import DOC_SOURCES, FIXTURES, CollectionError, load_collection
from bonsai_help.config import REPOSITORY
from bonsai_help.doc_sources import load_config
from bonsai_help.judge_config import JudgeConfig
from bonsai_help.tracing import digest, now, run_directory

QUALIFICATIONS = "judge-qualifications"
SCHEMA_VERSION = "1"
BASIS = {
    "kind": "distinct_model",
    "decision": "DECISIONS.md, November 24, 2026: judge model",
}
# The judge settings a smoke run must share with the qualified judge: the model and how
# it is called. `purpose`, `prompt_path`, the embedding settings, `examples_k`,
# `artifact_root` and `hosted` (always false) are not among them.
QUALIFIED_SETTINGS = (
    "base_url",
    "model",
    "model_identity",
    "model_sha256",
    "mode",
    "temperature",
    "enable_thinking",
    "timeout_seconds",
    "max_tokens",
    "max_attempts",
    "authentication",
)
SMOKE_STATUS_FIELDS = (
    "status",
    "purpose",
    "settings",
    "population",
    "resolved",
    "unresolved",
    "unknown_outcomes",
    "reported_models",
)
GENERATOR_FIELDS = ("model", "model_identity", "model_sha256")
RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "qualification_id",
        "created_at",
        "judge",
        "basis",
        "smoke_generators",
        "evidence",
        "sha256",
    }
)
EVIDENCE_FIELDS = frozenset(
    {
        "assessment_id",
        "assessment_sha256",
        "judge_run_id",
        "population",
        "unknown_outcomes",
        "reported_models",
        "status_sha256",
    }
)
INSPECT = "preserve and inspect it; a receipt is never repaired or replaced"


class QualificationError(ValueError):
    """A judge qualification is refused, missing or changed; nothing was written."""


def _sealed(receipt: dict) -> str:
    return digest({k: v for k, v in receipt.items() if k != "sha256"})


def _dumps(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def receipt_path(root: Path, qualification_id: str) -> Path:
    """`root/judge-qualifications/<id>.json`; under runs/ or outside the repository."""
    root = Path(root)
    resolved = root.resolve()
    if resolved.is_relative_to(REPOSITORY) and not resolved.is_relative_to(REPOSITORY / "runs"):
        raise QualificationError(
            "judge qualifications must stay under runs/ or outside the repository"
        )
    if (root / QUALIFICATIONS).is_symlink():
        raise QualificationError(f"a symlinked {QUALIFICATIONS} directory is not supported")
    try:
        target = run_directory(root / QUALIFICATIONS, qualification_id)
    except ValueError:
        raise QualificationError(
            "qualification id must be 1-64 letters, digits, underscores or hyphens"
        ) from None
    return target.with_name(f"{qualification_id}.json")


def _names(record: dict) -> set[str]:
    return {
        record[field].strip().casefold()
        for field in ("model", "model_identity")
        if isinstance(record.get(field), str)
    }


def _check_distinct(config: JudgeConfig, sources: list[dict]) -> None:
    names = _names({"model": config.model, "model_identity": config.model_identity})
    for source in sources:
        if names & _names(source) or config.model_sha256 == source["model_sha256"]:
            raise QualificationError(
                "the judge is the same model as a source generator (model, model_identity "
                "or model_sha256); the basis distinct_model needs a model of another family"
            )


def _check_sources(sources: object) -> list[dict]:
    if not isinstance(sources, list) or not sources:
        raise QualificationError(
            "at least one source generator is needed to show that the judge is distinct"
        )
    for source in sources:
        if (
            not isinstance(source, dict)
            or any(field not in source for field in GENERATOR_FIELDS)
            or not isinstance(source["model"], str)
            or not source["model"].strip()
            or any(
                source[field] is not None and not isinstance(source[field], str)
                for field in ("model_identity", "model_sha256")
            )
        ):
            raise QualificationError(
                "each source generator must give its model, model_identity and model_sha256"
            )
    return sources


def source_generators(root: Path, sources: list[dict]) -> list[dict]:
    """The generator of each assessment source, from its collection's recorded settings.

    `sources` is an assessment manifest's `sources`. Each entry gives the collection id,
    `model`, `model_identity`, `model_sha256` and the generator `temperature`; a source
    whose recorded `model_sha256` differs from its collection's is refused."""
    generators = []
    for source in sources:
        try:
            _, collection = load_collection(Path(root), source["collection_id"])
        except (CollectionError, ValueError) as exc:
            raise QualificationError(f"source collection: {exc}") from None
        settings = collection["identity"]["settings"]
        if settings.get("model_sha256") != source.get("model_sha256"):
            raise QualificationError(
                f"source collection {source['collection_id']}: its model_sha256 differs "
                "from the assessment's record"
            )
        generators.append(
            {
                "collection_id": source["collection_id"],
                **{field: settings.get(field) for field in GENERATOR_FIELDS},
                "temperature": settings["temperature"],
            }
        )
    return generators


def _smoke_status(root: Path, assessment_id: str, judge_run_id: str) -> dict:
    from bonsai_help.judge import judge_status  # judge imports this module

    try:
        status = judge_status(root, assessment_id, judge_run_id)
    except ValueError as exc:
        raise QualificationError(f"smoke judge run {judge_run_id!r}: {exc}") from None
    if not isinstance(status, dict):
        raise QualificationError(f"smoke judge run {judge_run_id!r}: its status is unreadable")
    missing = [field for field in SMOKE_STATUS_FIELDS if field not in status]
    if missing:
        raise QualificationError(
            f"smoke judge run {judge_run_id!r}: its status gives no " + ", ".join(missing)
        )
    return {field: status[field] for field in SMOKE_STATUS_FIELDS}


def _smoke_assessment(root: Path, assessment_id: str) -> Assessment:
    """The verified smoke assessment, which must be a development one (never labeled)."""
    try:
        smoke = load_assessment(
            root, assessment_id, fixtures_dir=FIXTURES, doc_config=load_config(DOC_SOURCES)
        )
    except AssessmentError as exc:
        raise QualificationError(f"smoke assessment: {exc}") from None
    if smoke.manifest["kind"] != "development":
        raise QualificationError(
            "smoke evidence must come from a development assessment that is never labeled; "
            f"{assessment_id!r} is kind {smoke.manifest['kind']}"
        )
    return smoke


def _qualified(settings: dict) -> dict:
    return {field: settings.get(field) for field in QUALIFIED_SETTINGS}


def _differing(expected: dict, actual: object) -> list[str]:
    if not isinstance(actual, dict):
        return list(QUALIFIED_SETTINGS)
    actual = _qualified(actual)
    return [field for field in QUALIFIED_SETTINGS if expected[field] != actual[field]]


def _check_evidence(config: JudgeConfig, status: dict, judge_run_id: str) -> None:
    run = f"smoke judge run {judge_run_id!r}"
    if status["purpose"] != "smoke":
        raise QualificationError(f"{run} is not a smoke run (purpose {status['purpose']!r})")
    population, resolved, unresolved = (
        status["population"],
        status["resolved"],
        status["unresolved"],
    )
    if (
        status["status"] != "complete"
        or type(population) is not int
        or population < 1
        or resolved != population
        or unresolved != []
    ):
        raise QualificationError(
            f"{run} is not complete: every selected item needs a valid judgment"
        )
    differing = _differing(_qualified(config.public_settings()), status["settings"])
    if differing:
        raise QualificationError(
            f"{run} was judged with other settings: {', '.join(differing)}; qualification "
            "needs the same model and settings (any prompt)"
        )
    reported = status["reported_models"]
    if not isinstance(reported, list) or not isinstance(status["unknown_outcomes"], list):
        raise QualificationError(f"{run}: its reported models or unknown outcomes are unreadable")
    if not reported:
        raise QualificationError(f"{run}: no reply reported a model id")
    if any(model != config.model for model in reported):
        raise QualificationError(
            f"{run}: a reply reported a model other than the configured judge model"
        )


def _check_config(config: JudgeConfig) -> None:
    if config.model_identity is None or config.model_sha256 is None:
        raise QualificationError(
            "qualification needs the judge's model_identity and model_sha256 (kept in a "
            "git-ignored local config)"
        )


def _write_once(path: Path, data: bytes) -> None:
    """Write a complete file, then link it into place: never a partial or replaced file."""
    path.parent.mkdir(parents=True, exist_ok=True)
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
        raise QualificationError(
            f"judge qualification {path.stem!r} already exists; choose a new id"
        ) from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def qualify(
    config: JudgeConfig,
    root: Path,
    *,
    smoke_assessment_id: str,
    smoke_judge_run_id: str,
    qualification_id: str,
) -> dict:
    """Check the smoke evidence and the distinct-model basis, then write the receipt once.

    Every refusal comes before any write. Makes no model call."""
    root = Path(root)
    path = receipt_path(root, qualification_id)
    if path.exists() or path.is_symlink():
        raise QualificationError(
            f"judge qualification {qualification_id!r} already exists; choose a new id"
        )
    _check_config(config)
    smoke = _smoke_assessment(root, smoke_assessment_id)
    generators = source_generators(root, smoke.manifest["sources"])
    _check_distinct(config, generators)
    status = _smoke_status(root, smoke_assessment_id, smoke_judge_run_id)
    _check_evidence(config, status, smoke_judge_run_id)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "qualification_id": qualification_id,
        "created_at": now(),
        "judge": config.public_settings(),
        "basis": dict(BASIS),
        "smoke_generators": generators,
        "evidence": {
            "assessment_id": smoke_assessment_id,
            "assessment_sha256": smoke.manifest["sha256"],
            "judge_run_id": smoke_judge_run_id,
            "population": status["population"],
            "unknown_outcomes": status["unknown_outcomes"],
            "reported_models": sorted(set(status["reported_models"])),
            "status_sha256": digest(status),
        },
    }
    receipt["sha256"] = _sealed(receipt)
    _write_once(path, _dumps(receipt))
    return receipt


def _read_receipt(path: Path, qualification_id: str) -> tuple[dict, bytes]:
    if path.is_symlink():
        raise QualificationError(
            f"judge qualification {qualification_id!r} is a symlink; {INSPECT}"
        )
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise QualificationError(f"no judge qualification {qualification_id!r}") from None
    except OSError:
        raise QualificationError(
            f"judge qualification {qualification_id!r} is unreadable; {INSPECT}"
        ) from None
    try:
        receipt = json.loads(data)
    except ValueError:
        receipt = None
    if not isinstance(receipt, dict):
        raise QualificationError(
            f"judge qualification {qualification_id!r} is not a JSON object; {INSPECT}"
        )
    evidence = receipt.get("evidence")
    if (
        set(receipt) != RECEIPT_FIELDS
        or receipt["sha256"] != _sealed(receipt)
        or receipt["schema_version"] != SCHEMA_VERSION
        or receipt["qualification_id"] != qualification_id
        or receipt["basis"] != BASIS
        or not isinstance(receipt["judge"], dict)
        or not isinstance(evidence, dict)
        or set(evidence) != EVIDENCE_FIELDS
    ):
        raise QualificationError(
            f"judge qualification {qualification_id!r} receipt changed; {INSPECT}"
        )
    return receipt, data


def validate_qualification(
    config: JudgeConfig, receipt_id: str, sources: list[dict], root: Path
) -> dict:
    """Check a receipt against a measured judge config and every source generator.

    `sources` lists each generator of the judged assessment, with its `model`,
    `model_identity` and `model_sha256` (`source_generators` gives them). The smoke run is
    re-read and must be unchanged. Returns `{receipt, sha256}`, the SHA-256 of the
    receipt file's bytes, which a measured run pins."""
    root = Path(root)
    path = receipt_path(root, receipt_id)
    if config.purpose != "measured":
        raise QualificationError("a qualification is validated only for a measured judge")
    _check_config(config)
    sources = _check_sources(sources)
    receipt, data = _read_receipt(path, receipt_id)
    differing = _differing(_qualified(config.public_settings()), receipt["judge"])
    if differing:
        raise QualificationError(
            f"judge qualification {receipt_id!r} does not match the judge config: "
            f"{', '.join(differing)}; qualify the changed judge under a new id"
        )
    _check_distinct(config, sources)
    _check_distinct(config, _check_sources(receipt["smoke_generators"]))
    evidence = receipt["evidence"]
    smoke = _smoke_assessment(root, evidence["assessment_id"])
    if smoke.manifest["sha256"] != evidence["assessment_sha256"]:
        raise QualificationError(
            f"judge qualification {receipt_id!r}: the smoke evidence changed since the "
            f"receipt was written; {INSPECT}"
        )
    status = _smoke_status(root, evidence["assessment_id"], evidence["judge_run_id"])
    if digest(status) != evidence["status_sha256"]:
        raise QualificationError(
            f"judge qualification {receipt_id!r}: the smoke evidence changed since the "
            f"receipt was written; {INSPECT}"
        )
    _check_evidence(config, status, evidence["judge_run_id"])
    return {"receipt": receipt, "sha256": hashlib.sha256(data).hexdigest()}
