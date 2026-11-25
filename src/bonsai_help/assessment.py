"""Immutable, seeded and blind labeling selections drawn from frozen cohorts.

An assessment draws from one or more frozen cohorts (`cohort.load_cohort`, which
re-verifies the collection evidence), one cohort per arm. The arm comes from the cohort's
collection identity, never from the operator: its `purpose` must be `baseline` or
`corrected` and equal its `prompt_variant` (`smoke` is refused). Split `assessed` makes an
arm source and split `development` a development source; an assessment is all one kind
(`arm` or `development`), never a mix.

Selection (`sha256-stratified-v2`, per source): leave out the items that the listed
excluded assessments selected; in each category sort the rest by `sha256(seed, cohort_id,
item_id)` and take `count / 5`. `count` is per source, a multiple of 5 and at least the
rubric's `thresholds.blind_labels.minimum_per_arm` (kind `arm`) or `DEVELOPMENT_MINIMUM`
(kind `development`). A shortfall in any category is refused, never padded. The selected
items of every source are put in one order by `sha256(seed, "order", trace_id)`, and the
blind ids `L-001`, ... are positions in that order, so a blind id carries no source. Each
`sha256(a, b, c)` is the SHA-256 of the UTF-8 JSON array `[a, b, c]` (`json.dumps`, its
default separators, `ensure_ascii=False`).

Files, each written once (an existing assessment id is refused):

- `queue.json`: what the labeler may see, per blind id: the item's seven fields, its
  category, its setup record (Blender and Bonsai versions, IFC schema, discipline, model
  state; no setup id), the model's quotes and the cited `CitedSection` references, with the
  trace id and payload hash the label pins need. No run id, item id, arm, prompt, model or
  generation time.
- `key.json`: blind id to `source_index`, `item_id`, `run_id` and `arm`. `load_assessment`
  never reads it; only `load_key` does (the human reference after labeling, and B7+).
- `rubric.json`: a byte copy of the rubric, which must be `chad_accepted`; the manifest
  pins its version and `rubric.rubric_sha256`.
- `manifest.json`: sources, selection, display order, the queue, key and profile hashes,
  the rubric pin, the implementation identity and the seal `sha256`. It is written last: a
  directory without it is an interrupted create, reported for inspection and never
  repaired or reused.

No label file is written here; the first saved label creates the ledger. Nothing here
calls a model endpoint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bonsai_help import generate
from bonsai_help.cohort import load_cohort
from bonsai_help.collection import CollectionError, load_collection
from bonsai_help.config import REPOSITORY
from bonsai_help.doc_sources import CATEGORIES, Category, DocSources
from bonsai_help.evaluation_schemas import BlindId, Sha256
from bonsai_help.rubric import Rubric, RubricError, load_rubric, rubric_sha256
from bonsai_help.sampler import SamplerError, section_texts, verify_fixtures
from bonsai_help.schemas import CitedSection, NonBlank, QAItem, Quote
from bonsai_help.setup import SetupProfiles
from bonsai_help.tracing import digest, now, read_json, run_directory

ALGORITHM = "sha256-stratified-v2"
DEVELOPMENT_MINIMUM = 5
ASSESSED_PURPOSES = ("baseline", "corrected")
KINDS = {"assessed": "arm", "development": "development"}
MANIFEST = "manifest.json"
QUEUE = "queue.json"
KEY = "key.json"
RUBRIC_COPY = "rubric.json"
ACCEPTED = "chad_accepted"
KEY_FIELDS = frozenset({"source_index", "item_id", "run_id", "arm"})
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "assessment_id",
        "kind",
        "created_at",
        "sources",
        "selection",
        "display_order",
        "queue_sha256",
        "key_sha256",
        "rubric_version",
        "rubric_sha256",
        "rubric_status",
        "profiles_sha256",
        "implementation",
        "sha256",
    }
)
INSPECT = "preserve and inspect it"


class AssessmentError(ValueError):
    """An assessment, its sources or its rubric are refused; nothing was written."""


class UsageError(AssessmentError):
    """A malformed request (id, seed, cohort list or count); a usage error."""


def _strict() -> ConfigDict:
    return ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


class SetupRecord(BaseModel):
    """The setup the labeler sees: versions and profile values, never the setup id."""

    model_config = _strict()

    blender: NonBlank
    bonsai: NonBlank
    ifc_schema: NonBlank
    discipline: NonBlank
    model_state: NonBlank


class BlindItem(BaseModel):
    """One queue entry: only what the blind display and the label pins need."""

    model_config = _strict()

    blind_id: BlindId
    trace_id: NonBlank
    payload_sha256: Sha256
    category: Category
    item: QAItem
    setup: SetupRecord
    quotes: Annotated[list[Quote], Field(min_length=1)]
    cited_sections: Annotated[list[CitedSection], Field(min_length=1)]


@dataclass(frozen=True)
class Assessment:
    """A verified assessment. `current_rubric_sha256` is the hash of the rubric at the
    `rubric_path` given to `load_assessment` (None if none was given or it is unreadable or
    invalid); the labeling gate compares it with the pin."""

    directory: Path
    manifest: dict
    queue: list[BlindItem]
    rubric: Rubric
    current_rubric_sha256: str | None


def minimum_per_arm(rubric: Rubric) -> int:
    """The rubric's minimum number of blind labels per arm (B6 and B8)."""
    return rubric.thresholds.blind_labels.minimum_per_arm


def assessment_directory(root: Path, assessment_id: str) -> Path:
    """`root/assessments/<id>`; under runs/ or outside the repository, never a symlink."""
    resolved = Path(root).resolve()
    if resolved.is_relative_to(REPOSITORY) and not resolved.is_relative_to(REPOSITORY / "runs"):
        raise ValueError("assessments must stay under runs/ or outside the repository")
    if (Path(root) / "assessments").is_symlink():
        raise ValueError("a symlinked assessments directory is not supported")
    return run_directory(Path(root) / "assessments", assessment_id)


def _hash(*parts: str) -> str:
    return digest(json.dumps(list(parts), ensure_ascii=False))


def _file_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sealed(manifest: dict) -> str:
    return digest({k: v for k, v in manifest.items() if k != "sha256"})


def _dumps(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _write_once(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)


def _read(path: Path) -> bytes:
    if path.is_symlink():
        raise AssessmentError(f"{path.name} is a symlink; {INSPECT}")
    return path.read_bytes()


def _directory(root: Path, assessment_id: str) -> Path:
    try:
        return assessment_directory(root, assessment_id)
    except ValueError as exc:
        raise UsageError(str(exc)) from None


def _manifest(root: Path, assessment_id: str) -> tuple[Path, dict]:
    """The sealed manifest; a missing one in an existing directory is an interrupted create."""
    directory = _directory(root, assessment_id)
    if not directory.is_dir():
        raise AssessmentError(f"no assessment {assessment_id!r}")
    path = directory / MANIFEST
    if not path.exists():
        raise AssessmentError(
            f"assessment {assessment_id!r} is incomplete (no {MANIFEST}): its creation was "
            f"interrupted; {INSPECT}"
        )
    try:
        _read(path)
        manifest = read_json(path)
    except ValueError:
        raise AssessmentError(f"{MANIFEST} is not a JSON object; {INSPECT}") from None
    if (
        manifest.get("sha256") != _sealed(manifest)
        or manifest.get("assessment_id") != assessment_id
        or manifest.get("schema_version") != "1"
        or set(manifest) != MANIFEST_FIELDS
    ):
        raise AssessmentError(f"assessment manifest changed; {INSPECT}")
    return directory, manifest


def _load_rubric(path: Path) -> Rubric:
    try:
        return load_rubric(path)
    except OSError:
        raise AssessmentError(f"cannot read the rubric {Path(path).name}") from None
    except RubricError as exc:
        raise AssessmentError(f"rubric {Path(path).name} is invalid: {exc}") from None


def _check_usage(cohort_ids: list[str], count: object, seed: object, exclude: list[str]) -> None:
    if not isinstance(seed, str) or not seed.strip():
        raise UsageError("seed must be nonblank text")
    if not cohort_ids:
        raise UsageError("an assessment needs at least one cohort")
    for name, values in (("cohort", cohort_ids), ("excluded assessment", exclude)):
        if any(not isinstance(v, str) for v in values):
            raise UsageError(f"each {name} id must be text")
        if len(set(values)) != len(values):
            raise UsageError(f"a {name} is listed more than once")
    if type(count) is not int or count <= 0 or count % len(CATEGORIES):
        raise UsageError(f"count must be a positive multiple of {len(CATEGORIES)}")


def _source(root: Path, cohort_id: str) -> tuple[dict, list[dict]]:
    """The source description derived from the cohort's collection, and its items."""
    try:
        frozen = load_cohort(root, cohort_id)
        _, collection = load_collection(root, frozen["collection_id"])
    except CollectionError as exc:
        raise AssessmentError(f"cohort {cohort_id}: {exc}") from None
    except ValueError as exc:
        raise UsageError(f"cohort {cohort_id}: {exc}") from None
    identity = collection["identity"]
    settings = identity["settings"]
    purpose, variant = settings["purpose"], settings["prompt_variant"]
    if purpose not in ASSESSED_PURPOSES:
        raise AssessmentError(
            f"cohort {cohort_id}: a {purpose} collection cannot be assessed; "
            "only baseline or corrected collections can"
        )
    if variant != purpose:
        raise AssessmentError(
            f"cohort {cohort_id}: collection purpose {purpose} differs from its "
            f"prompt_variant {variant}"
        )
    items = frozen["items"]
    if any(
        i["prompt_variant"] != purpose
        or i["prompt_hash"] != identity["prompt_sha256"]
        or i["model"] != settings["model"]
        for i in items
    ):
        raise AssessmentError(f"cohort {cohort_id}: an item differs from its collection identity")
    source = {
        "cohort_id": cohort_id,
        "cohort_sha256": frozen["sha256"],
        "collection_id": frozen["collection_id"],
        "arm": purpose,
        "split": settings["split"],
        "prompt_hash": identity["prompt_sha256"],
        "model_sha256": settings["model_sha256"],
    }
    return source, items


def _kind(sources: list[dict]) -> str:
    kinds = {KINDS[s["split"]] for s in sources}
    if len(kinds) != 1:
        raise AssessmentError(
            "an assessment cannot mix assessed (arm) and development sources; "
            "create one assessment of each kind"
        )
    arms = [s["arm"] for s in sources]
    if len(set(arms)) != len(arms):
        raise AssessmentError("an assessment takes one cohort per arm")
    return kinds.pop()


def _check_minimum(kind: str, count: int, rubric: Rubric) -> None:
    minimum = minimum_per_arm(rubric) if kind == "arm" else DEVELOPMENT_MINIMUM
    if count < minimum:
        raise UsageError(f"count must be at least {minimum} per source for kind {kind}")


def _fixtures(doc_config: DocSources, fixtures_dir: Path) -> None:
    try:
        verify_fixtures(doc_config, fixtures_dir)
    except SamplerError as exc:
        raise AssessmentError(f"fixture slice: {exc}") from None


def _select(
    seed: str, cohort_id: str, items: list[dict], count: int, excluded: set[tuple[str, str]]
) -> list[dict]:
    per = count // len(CATEGORIES)
    chosen: list[dict] = []
    shortfalls: list[str] = []
    for category in CATEGORIES:
        pool = sorted(
            (
                i
                for i in items
                if i["category"] == category and (cohort_id, i["item_id"]) not in excluded
            ),
            key=lambda i: (_hash(seed, cohort_id, i["item_id"]), i["item_id"]),
        )
        if len(pool) < per:
            shortfalls.append(f"{category} has {len(pool)} of {per}")
        chosen.extend(pool[:per])
    if shortfalls:
        raise AssessmentError(
            f"selection shortfall in cohort {cohort_id}: {', '.join(shortfalls)} unselected "
            "items; a shortfall is refused, never padded"
        )
    return chosen


def _ordered(seed: str, picks: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
    traces = [record["trace_id"] for _, record in picks]
    if len(set(traces)) != len(traces):
        raise AssessmentError("two selected items share a trace id; inspect the cohorts")
    return sorted(picks, key=lambda p: (_hash(seed, "order", p[1]["trace_id"]), p[1]["trace_id"]))


def _blind_ids(count: int) -> list[str]:
    if count > 999:
        raise UsageError("an assessment holds at most 999 items")
    return [f"L-{n:03d}" for n in range(1, count + 1)]


def _setup(profiles: SetupProfiles, record: dict, split: str) -> SetupRecord:
    profile = next((p for p in profiles.profiles if p.id == record["setup_id"]), None)
    if profile is None or profile.split != split or profile.version_line != record["version_line"]:
        raise AssessmentError("an item's setup profile is unknown or outside its split")
    line = next(v for v in profiles.version_lines if v.id == profile.version_line)
    return SetupRecord(
        blender=line.blender,
        bonsai=line.bonsai,
        ifc_schema=profile.ifc_schema,
        discipline=profile.discipline,
        model_state=profile.model_state,
    )


def _content(record: dict) -> dict:
    """The queue fields an item contributes, apart from its blind id and setup record."""
    return {
        "trace_id": record["trace_id"],
        "payload_sha256": digest(record["item"]),
        "category": record["category"],
        "item": record["item"],
        "quotes": record["quotes"],
        "cited_sections": record["cited_sections"],
    }


def _check_sections(entries: list[BlindItem], fixtures_dir: Path) -> None:
    for entry in entries:
        try:
            section_texts(entry.cited_sections, fixtures_dir)
        except SamplerError as exc:
            raise AssessmentError(f"fixture slice: {exc}") from None


def _excluded(root: Path, assessment_ids: list[str]) -> tuple[set[tuple[str, str]], list[dict]]:
    """The (cohort id, item id) pairs the excluded assessments selected, and their pins."""
    pairs: set[tuple[str, str]] = set()
    pins: list[dict] = []
    for assessment_id in assessment_ids:
        directory, manifest = _manifest(root, assessment_id)
        key = _read_key(root, directory, manifest)
        pairs |= {
            (manifest["sources"][entry["source_index"]]["cohort_id"], entry["item_id"])
            for entry in key.values()
        }
        pins.append({"assessment_id": assessment_id, "sha256": manifest["sha256"]})
    return pairs, pins


def create_assessment(
    root: Path,
    assessment_id: str,
    cohort_ids: list[str],
    *,
    count: int,
    seed: str,
    rubric_path: Path,
    profiles: SetupProfiles,
    doc_config: DocSources,
    fixtures_dir: Path,
    exclude: list[str] | tuple[str, ...] = (),
) -> dict:
    """Select, write and seal a new assessment; every refusal comes before any write."""
    root = Path(root)
    directory = _directory(root, assessment_id)
    if directory.exists():
        raise AssessmentError(f"assessment {assessment_id!r} already exists; choose a new id")
    cohort_ids, exclude = list(cohort_ids), list(exclude)
    _check_usage(cohort_ids, count, seed, exclude)
    rubric = _load_rubric(rubric_path)
    if rubric.status != ACCEPTED:
        raise AssessmentError(
            f"rubric {rubric.version} is {rubric.status}, not {ACCEPTED}: labeling needs "
            "Chad's acceptance of the rubric first"
        )
    loaded = [_source(root, cohort_id) for cohort_id in cohort_ids]
    sources = [source for source, _ in loaded]
    kind = _kind(sources)
    _check_minimum(kind, count, rubric)
    _fixtures(doc_config, fixtures_dir)
    excluded, pins = _excluded(root, exclude)
    picks = [
        (index, record)
        for index, (source, items) in enumerate(loaded)
        for record in _select(seed, source["cohort_id"], items, count, excluded)
    ]
    ordered = _ordered(seed, picks)
    blind_ids = _blind_ids(len(ordered))
    queue: list[BlindItem] = []
    key: dict[str, dict] = {}
    for blind_id, (index, record) in zip(blind_ids, ordered, strict=True):
        split = sources[index]["split"]
        try:
            entry = BlindItem.model_validate(
                {"blind_id": blind_id, "setup": _setup(profiles, record, split)} | _content(record)
            )
        except ValidationError:
            raise AssessmentError("a selected item does not fit the blind queue") from None
        queue.append(entry)
        key[blind_id] = {
            "source_index": index,
            "item_id": record["item_id"],
            "run_id": record["run_id"],
            "arm": sources[index]["arm"],
        }
    _check_sections(queue, fixtures_dir)
    queue_bytes = _dumps([entry.model_dump(mode="json") for entry in queue])
    key_bytes = _dumps(key)
    rubric_bytes = Path(rubric_path).read_bytes()
    manifest = {
        "schema_version": "1",
        "assessment_id": assessment_id,
        "kind": kind,
        "created_at": now(),
        "sources": sources,
        "selection": {
            "algorithm": ALGORITHM,
            "seed": seed,
            "count_per_source": count,
            "excluded": pins,
        },
        "display_order": blind_ids,
        "queue_sha256": _file_sha(queue_bytes),
        "key_sha256": _file_sha(key_bytes),
        "rubric_version": rubric.version,
        "rubric_sha256": rubric_sha256(rubric),
        "rubric_status": rubric.status,
        "profiles_sha256": digest(profiles.model_dump(mode="json", by_alias=True)),
        "implementation": generate.implementation_identity()["source_tree_sha256"],
    }
    manifest["sha256"] = _sealed(manifest)
    directory.mkdir(parents=True, exist_ok=False)  # a concurrent create of the same id fails
    _write_once(directory / RUBRIC_COPY, rubric_bytes)
    _write_once(directory / KEY, key_bytes)
    _write_once(directory / QUEUE, queue_bytes)
    _write_once(directory / MANIFEST, _dumps(manifest))
    return manifest


def _queue(directory: Path, manifest: dict) -> list[BlindItem]:
    try:
        data = _read(directory / QUEUE)
    except OSError:
        raise AssessmentError(f"{QUEUE} is missing or unreadable; {INSPECT}") from None
    if _file_sha(data) != manifest["queue_sha256"]:
        raise AssessmentError(f"{QUEUE} changed; {INSPECT}")
    try:
        entries = [BlindItem.model_validate(entry) for entry in json.loads(data)]
    except (ValueError, TypeError):
        raise AssessmentError(f"{QUEUE} is malformed; {INSPECT}") from None
    order = [entry.blind_id for entry in entries]
    if order != manifest["display_order"] or order != _blind_ids(len(order)):
        raise AssessmentError(f"{QUEUE} order differs from the display order; {INSPECT}")
    return entries


def _pinned_rubric(directory: Path, manifest: dict) -> Rubric:
    path = directory / RUBRIC_COPY
    try:
        _read(path)
        pinned = load_rubric(path)
    except (OSError, RubricError):
        raise AssessmentError(f"rubric copy changed or unreadable; {INSPECT}") from None
    if (
        rubric_sha256(pinned) != manifest["rubric_sha256"]
        or pinned.version != manifest["rubric_version"]
        or pinned.status != manifest["rubric_status"]
        or pinned.status != ACCEPTED
    ):
        raise AssessmentError(f"rubric copy changed; {INSPECT}")
    return pinned


def _current_rubric(rubric_path: Path | None) -> str | None:
    if rubric_path is None:
        return None
    try:
        return rubric_sha256(load_rubric(rubric_path))
    except (OSError, RubricError):
        return None


def load_assessment(
    root: Path,
    assessment_id: str,
    *,
    fixtures_dir: Path,
    doc_config: DocSources,
    rubric_path: Path | None = None,
) -> Assessment:
    """Verify an assessment and return its blind queue; never reads its `key.json`.

    It checks the seal, the queue bytes, the rubric copy and its pin, and the source
    cohorts and collections (through `load_cohort`). It re-derives the selection and the
    display order from the cohorts (reading the keys of any excluded assessments, never its
    own) and the fixture slice, and refuses any difference.
    """
    root = Path(root)
    directory, manifest = _manifest(root, assessment_id)
    queue = _queue(directory, manifest)
    pinned = _pinned_rubric(directory, manifest)
    selection = manifest["selection"]
    if selection.get("algorithm") != ALGORITHM:
        raise AssessmentError(f"unknown selection algorithm; {INSPECT}")
    loaded = [_source(root, s["cohort_id"]) for s in manifest["sources"]]
    if [source for source, _ in loaded] != manifest["sources"]:
        raise AssessmentError("source cohort or collection identity changed since the selection")
    if _kind(manifest["sources"]) != manifest["kind"]:
        raise AssessmentError(f"assessment kind changed; {INSPECT}")
    ids = [pin["assessment_id"] for pin in selection["excluded"]]
    excluded, pins = _excluded(root, ids)
    if pins != selection["excluded"]:
        raise AssessmentError("an excluded assessment changed since this selection")
    count, seed = selection["count_per_source"], selection["seed"]
    picks = [
        (index, record)
        for index, (source, items) in enumerate(loaded)
        for record in _select(seed, source["cohort_id"], items, count, excluded)
    ]
    expected = [_content(record) for _, record in _ordered(seed, picks)]
    actual = [entry.model_dump(mode="json", exclude={"blind_id", "setup"}) for entry in queue]
    if actual != expected:
        raise AssessmentError("assessment queue differs from its source cohorts; inspect it")
    _fixtures(doc_config, fixtures_dir)
    _check_sections(queue, fixtures_dir)
    return Assessment(directory, manifest, queue, pinned, _current_rubric(rubric_path))


def _read_key(root: Path, directory: Path, manifest: dict) -> dict[str, dict]:
    try:
        data = _read(directory / KEY)
    except OSError:
        raise AssessmentError(f"{KEY} is missing or unreadable; {INSPECT}") from None
    if _file_sha(data) != manifest["key_sha256"]:
        raise AssessmentError(f"{KEY} changed; {INSPECT}")
    try:
        key = json.loads(data)
    except ValueError:
        raise AssessmentError(f"{KEY} is malformed; {INSPECT}") from None
    sources = manifest["sources"]
    if (
        not isinstance(key, dict)
        or list(key) != manifest["display_order"]
        or any(not isinstance(v, dict) or set(v) != KEY_FIELDS for v in key.values())
        or any(
            type(v["source_index"]) is not int or not 0 <= v["source_index"] < len(sources)
            for v in key.values()
        )
    ):
        raise AssessmentError(f"{KEY} is malformed; {INSPECT}")
    queue = {entry.blind_id: entry.trace_id for entry in _queue(directory, manifest)}
    items: dict[int, dict[str, dict]] = {}
    for blind_id, entry in key.items():
        index = entry["source_index"]
        if index not in items:
            _, records = _source(root, sources[index]["cohort_id"])
            items[index] = {r["item_id"]: r for r in records}
        record = items[index].get(entry["item_id"])
        if (
            record is None
            or record["trace_id"] != queue[blind_id]
            or record["run_id"] != entry["run_id"]
            or entry["arm"] != sources[index]["arm"]
        ):
            raise AssessmentError(f"{KEY} differs from the queue or its cohorts; {INSPECT}")
    return key


def load_key(root: Path, assessment_id: str) -> dict[str, dict]:
    """Blind id to `source_index`, `item_id`, `run_id` and `arm`, verified against the
    sealed hash, the queue and the source cohorts. Never called by labeling code."""
    directory, manifest = _manifest(Path(root), assessment_id)
    return _read_key(Path(root), directory, manifest)


def assessment_summary(root: Path, assessment_id: str) -> dict:
    """A blind summary: counts and pins only, nothing per item and nothing per arm."""
    directory, manifest = _manifest(Path(root), assessment_id)
    _queue(directory, manifest)
    return {
        "assessment_id": manifest["assessment_id"],
        "kind": manifest["kind"],
        "sources": len(manifest["sources"]),
        "selected": len(manifest["display_order"]),
        "rubric_version": manifest["rubric_version"],
        "rubric_sha256": manifest["rubric_sha256"],
        "created_at": manifest["created_at"],
    }
