"""Judge v2's example pool from development disagreements, and its selection (B7 Decisions
10 and 11).

`build_pool` writes `<artifact root>/judge-examples/<pool_id>/pool.json` once, from one
development assessment:

- The assessment must be kind `development`, with its human reference frozen
  (`human_reference.load_reference`) and a complete measured judge v1 run on it (a run
  without an example pool). An `arm` assessment is refused before anything else is read.
- The entries are the (blind id, dimension) pairs where the frozen human decision is
  resolved and differs from the judge's (`calibration.agreement`). Each entry holds the
  item's category, setup record and seven fields, that dimension's recorded check lines
  (from the verified gate report), the human decision and the rubric anchor for it (the
  pass anchor for 1, the fail anchor for 0). No label note, judge reason or judge decision
  enters the pool; the judge's wrong reason is never shown as an example.
- One vector per pooled item embeds `question + "\\n" + answer` with the gate's embedding
  model (every source collection's `embedding_model`); another model is refused, under the
  one-embedding-model rule. Each item also keeps its trace id and payload hash, which are
  never rendered and serve only to refuse a judged assessment that shares an item.
- The pool is sealed (`sha256` over the rest) and records its source assessment, reference,
  judge run, rubric and embedding model.

The pool is computed from the development evidence only: no calibration report, and no
file of an `arm` assessment, is ever read here.

`select_examples` takes, for each judged item, the `k` pool entries nearest to its vector by
cosine similarity, ties broken by entry id. `render_examples` renders the chosen entries for
the `{examples}` placeholder: per entry, the dimension, the setup record, only the item
fields that dimension scores (`EXAMPLE_FIELDS`), its check lines, the human decision and
the anchor for it, each entry in a fenced block whose code depends on the rendered text.

Nothing here calls a model endpoint except through the embedder a caller passes in, and
nothing is overwritten or repaired.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import ValidationError

from bonsai_help import calibration, human_reference, judge
from bonsai_help.assessment import (
    Assessment,
    AssessmentError,
    BlindItem,
    SetupRecord,
    load_assessment,
)
from bonsai_help.collection import DOC_SOURCES, FIXTURES, CollectionError, load_collection
from bonsai_help.config import REPOSITORY
from bonsai_help.doc_sources import load_config
from bonsai_help.evaluation_schemas import DIMENSIONS, Decisions, Judgment
from bonsai_help.judge_config import JudgeConfig
from bonsai_help.model_client import EmbeddingClient, EmbeddingError
from bonsai_help.rubric import Rubric, rubric_sha256
from bonsai_help.schemas import QAItem
from bonsai_help.tracing import digest, now, run_directory

POOLS = "judge-examples"
POOL_FILE = "pool.json"
SCHEMA_VERSION = "1"
EMBEDDING_TEXT = 'question + "\\n" + answer'
EXAMPLES_FENCE_DOMAIN = "bonsai-judge-examples-fence-v1"
ENTRY_ID = "E-{:03d}"
# The item fields each dimension's example shows: the fields its rubric check scores
# (B7 Task 6, with refinement 2: D4 and D5 also rest on the steps).
EXAMPLE_FIELDS: dict[str, tuple[str, ...]] = {
    "D1": ("question", "answer", "steps"),
    "D2": ("steps", "safety_info"),
    "D3": ("answer", "tools_required", "steps"),
    "D4": ("question", "answer", "steps"),
    "D5": ("answer", "steps"),
    "D6": ("steps", "tips"),
}
POOL_FIELDS = frozenset(
    {
        "schema_version",
        "pool_id",
        "created_at",
        "source",
        "embedding",
        "items",
        "entries",
        "sha256",
    }
)
SOURCE_FIELDS = frozenset(
    {
        "assessment_id",
        "assessment_sha256",
        "kind",
        "reference_sha256",
        "judge_run_id",
        "judge_fingerprint",
        "judge_prompt_version",
        "judge_prompt_sha256",
        "rubric_version",
        "rubric_sha256",
    }
)
ITEM_FIELDS = frozenset({"trace_id", "payload_sha256", "vector"})
ENTRY_FIELDS = frozenset(
    {"entry_id", "blind_id", "dimension", "category", "setup", "item", "checks", "human", "anchor"}
)
INSPECT = "preserve and inspect it; a pool is never repaired or replaced"
_POOL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


class PoolError(ValueError):
    """An example pool, its source or a selection from it is refused; nothing was written."""


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ----------------------------------------------------------------------- helpers


def embedder_for(
    config: JudgeConfig, *, _transport: httpx.BaseTransport | None = None
) -> EmbeddingClient:
    """The embedding client a judge config names (judge v2's selection and the pool):
    its embedding endpoint, model and credential source. No call is made here."""
    if config.embedding_model is None:
        raise PoolError("the judge config has no embedding_model (judge v2 only)")
    return EmbeddingClient(
        base_url=config.embedding_endpoint(),
        model=config.embedding_model,
        api_key=config.embedding_api_key(),
        timeout_seconds=config.timeout_seconds,
        _transport=_transport,
    )


def embedding_text(item: QAItem) -> str:
    """The text embedded for an item, pooled or judged: its question and its answer."""
    return f"{item.question}\n{item.answer}"


def pool_path(root: Path, pool_id: str) -> Path:
    """`root/judge-examples/<pool_id>/pool.json`; under runs/ or outside the repository."""
    root = Path(root)
    if not isinstance(pool_id, str) or not _POOL_ID.fullmatch(pool_id):
        raise PoolError("pool id must be 1-64 letters, digits, underscores or hyphens")
    resolved = root.resolve()
    if resolved.is_relative_to(REPOSITORY) and not resolved.is_relative_to(REPOSITORY / "runs"):
        raise PoolError("example pools must stay under runs/ or outside the repository")
    if (root / POOLS).is_symlink():
        raise PoolError(f"a symlinked {POOLS} directory is not supported")
    try:
        directory = run_directory(root / POOLS, pool_id)
    except ValueError:
        raise PoolError("pool id must be 1-64 letters, digits, underscores or hyphens") from None
    return directory / POOL_FILE


def _sealed(pool: dict) -> str:
    return digest({k: v for k, v in pool.items() if k != "sha256"})


def _dumps(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _check_vector(vector: object, width: int | None = None) -> list[float]:
    if (
        not isinstance(vector, list)
        or not vector
        or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in vector)
    ):
        raise PoolError("an embedding vector is not a list of numbers")
    if width is not None and len(vector) != width:
        raise PoolError(
            f"an embedding vector has {len(vector)} dimensions, the pool's have {width}"
        )
    values = [float(x) for x in vector]
    if not all(math.isfinite(x) for x in values) or not any(values):
        raise PoolError("an embedding vector is zero or non-finite")
    return values


def _embed(embedder: Embedder, texts: list[str], width: int | None = None) -> list[list[float]]:
    """Vectors for the texts, in order; a failed call or a malformed reply is refused."""
    try:
        vectors = embedder.embed(list(texts))
    except EmbeddingError as exc:
        raise PoolError(f"embedding failed: {exc}") from None
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise PoolError(
            f"embedding returned {len(vectors) if isinstance(vectors, list) else 'no'} "
            f"vectors for {len(texts)} texts"
        )
    checked = [_check_vector(v, width) for v in vectors]
    if len({len(v) for v in checked}) > 1:
        raise PoolError("embedding vectors have mismatched dimensions")
    return checked


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(math.fsum(x * x for x in vector))
    return [x / norm for x in vector]


def gate_embedding_models(root: Path, made: Assessment) -> set[str]:
    """The embedding model each source collection's gate used (its recorded settings)."""
    models: set[str] = set()
    for source in made.manifest["sources"]:
        try:
            _, manifest = load_collection(Path(root), source["collection_id"])
        except (CollectionError, ValueError) as exc:
            raise PoolError(f"source collection: {exc}") from None
        models.add(manifest["identity"]["settings"]["embedding_model"])
    return models


def check_gate_model(root: Path, made: Assessment, embedding_model: object) -> None:
    """Refuse an embedding model other than the gate's (one embedding model for every
    vector)."""
    models = gate_embedding_models(root, made)
    if models != {embedding_model}:
        raise PoolError(
            "the embedding model must be the gate's own (one embedding model for every "
            "vector); this one differs from a source collection's"
        )


# --------------------------------------------------------------------- the pool


def _assessment(root: Path, assessment_id: str) -> Assessment:
    try:
        return load_assessment(
            Path(root), assessment_id, fixtures_dir=FIXTURES, doc_config=load_config(DOC_SOURCES)
        )
    except (AssessmentError, ValueError) as exc:
        raise PoolError(f"assessment: {exc}") from None


def _development(made: Assessment) -> None:
    if made.manifest["kind"] != "development":
        raise PoolError(
            "an example pool comes only from a development assessment; "
            f"{made.manifest['assessment_id']!r} is kind {made.manifest['kind']} and is never "
            "a source of judge examples"
        )


def _reference(made: Assessment) -> dict:
    try:
        return human_reference.load_reference(made)
    except human_reference.HumanReferenceError as exc:
        raise PoolError(f"the pool needs the development reference frozen first: {exc}") from None


def _v1_run(made: Assessment, judge_run_id: str, reference: dict) -> tuple[dict, dict]:
    """The verified, complete, measured judge v1 run: its manifest and valid judgments."""
    try:
        directory = judge.judge_directory(made.directory, judge_run_id)
    except judge.JudgeError as exc:
        raise PoolError(str(exc)) from None
    if not directory.is_dir():
        raise PoolError(f"no judge run {judge_run_id!r} for this assessment")
    if (directory / judge.LOCK).exists() or (directory / judge.LOCK).is_symlink():
        raise PoolError(
            f"{judge.LOCK} exists: the judge run is active, or one stopped abruptly; inspect "
            "it (it is never removed by code)"
        )
    try:
        manifest, _, _, successful = judge.validate_judge(directory, made)
    except judge.JudgeError as exc:
        raise PoolError(f"judge run {judge_run_id!r}: {exc}") from None
    identity = manifest["identity"]
    if manifest["purpose"] != "measured":
        raise PoolError("the pool needs a measured judge run; a smoke run is diagnostic only")
    if manifest["status"] != "complete":
        raise PoolError(
            f"the pool needs a complete judge run; {judge_run_id!r} is {manifest['status']}"
        )
    if identity.get("examples") is not None:
        raise PoolError(
            "the pool needs a judge v1 run (no example pool); this run already used examples"
        )
    if identity.get("reference_sha256") != reference["sha256"]:
        raise PoolError(f"the judge run's reference differs from the frozen one; {INSPECT}")
    judgments = {b: Judgment.model_validate(a["judgment"]) for b, a in successful.items()}
    return manifest, judgments


def build_pool(
    root: Path,
    assessment_id: str,
    judge_run_id: str,
    pool_id: str,
    *,
    embedder: Embedder,
    embedding_model: str,
) -> dict:
    """Build and write the example pool once (B7 Decision 10); return it.

    Every refusal comes before any write: an existing pool id, a non-development
    assessment, an unfrozen reference, a judge run that is not a complete measured v1 run,
    an embedding model other than the gate's, no disagreement, and a failed embedding."""
    root = Path(root)
    path = pool_path(root, pool_id)
    if path.parent.exists() or path.parent.is_symlink():
        raise PoolError(f"example pool {pool_id!r} already exists; choose a new id")
    made = _assessment(root, assessment_id)
    _development(made)
    reference = _reference(made)
    manifest, judgments = _v1_run(made, judge_run_id, reference)
    check_gate_model(root, made, embedding_model)
    order = list(made.manifest["display_order"])
    decisions = {b: Decisions.model_validate(reference["labels"][b]["decisions"]) for b in order}
    found = calibration.agreement(order, decisions, judgments)["disagreements"]
    if not found:
        raise PoolError(
            "the judge run agrees with every resolved human decision: there is no "
            "development disagreement to draw examples from"
        )
    queue = {entry.blind_id: entry for entry in made.queue}
    try:
        checks = judge.item_checks(made)
    except judge.JudgeError as exc:
        raise PoolError(str(exc)) from None
    anchors = {d.id: (d.fail_anchor, d.pass_anchor) for d in made.rubric.dimensions}
    entries = []
    for number, disagreement in enumerate(found, 1):
        entry, dimension = queue[disagreement["blind_id"]], disagreement["dimension"]
        human = disagreement["human"]
        entries.append(
            {
                "entry_id": ENTRY_ID.format(number),
                "blind_id": entry.blind_id,
                "dimension": dimension,
                "category": entry.category,
                "setup": entry.setup.model_dump(mode="json"),
                "item": entry.item.model_dump(mode="json"),
                "checks": [
                    judge.check_line(c)
                    for c in checks[entry.blind_id]
                    if c["dimension"] == dimension
                ],
                "human": human,
                "anchor": anchors[dimension][human],
            }
        )
    pooled = [b for b in order if any(e["blind_id"] == b for e in entries)]
    vectors = _embed(embedder, [embedding_text(queue[b].item) for b in pooled])
    pool = {
        "schema_version": SCHEMA_VERSION,
        "pool_id": pool_id,
        "created_at": now(),
        "source": {
            "assessment_id": assessment_id,
            "assessment_sha256": made.manifest["sha256"],
            "kind": made.manifest["kind"],
            "reference_sha256": reference["sha256"],
            "judge_run_id": judge_run_id,
            "judge_fingerprint": manifest["fingerprint"],
            "judge_prompt_version": manifest["identity"]["prompt_version"],
            "judge_prompt_sha256": manifest["identity"]["prompt_sha256"],
            "rubric_version": made.rubric.version,
            "rubric_sha256": rubric_sha256(made.rubric),
        },
        "embedding": {
            "model": embedding_model,
            "text": EMBEDDING_TEXT,
            "dimensions": len(vectors[0]),
        },
        "items": {
            b: {
                "trace_id": queue[b].trace_id,
                "payload_sha256": queue[b].payload_sha256,
                "vector": vector,
            }
            for b, vector in zip(pooled, vectors, strict=True)
        },
        "entries": entries,
    }
    pool["sha256"] = _sealed(pool)
    verify_pool(pool)
    path.parent.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.mkdir()
    except FileExistsError:
        raise PoolError(f"example pool {pool_id!r} already exists; choose a new id") from None
    _write_once(path, _dumps(pool), pool_id)
    return pool


def _write_once(path: Path, data: bytes, pool_id: str) -> None:
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
        raise PoolError(f"example pool {pool_id!r} already exists; choose a new id") from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def _changed(what: str = "the example pool") -> PoolError:
    return PoolError(f"{what} changed or is malformed; {INSPECT}")


def verify_pool(pool: object) -> None:
    """Refuse a pool whose fields, seal, entries or vectors are not as `build_pool` writes
    them. Reads no file; `load_pool` also re-checks the pool against its source."""
    if not isinstance(pool, dict) or set(pool) != POOL_FIELDS:
        raise _changed()
    if pool["sha256"] != _sealed(pool) or pool["schema_version"] != SCHEMA_VERSION:
        raise _changed()
    source, embedding = pool["source"], pool["embedding"]
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
        raise _changed()
    if source["kind"] != "development":
        raise PoolError(
            "the example pool does not come from a development assessment; judge examples "
            "come only from development disagreements"
        )
    if (
        not isinstance(embedding, dict)
        or set(embedding) != {"model", "text", "dimensions"}
        or not isinstance(embedding["model"], str)
        or embedding["text"] != EMBEDDING_TEXT
        or type(embedding["dimensions"]) is not int
    ):
        raise _changed()
    items, entries = pool["items"], pool["entries"]
    if not isinstance(items, dict) or not items or not isinstance(entries, list) or not entries:
        raise _changed()
    for item in items.values():
        if not isinstance(item, dict) or set(item) != ITEM_FIELDS:
            raise _changed()
        _check_vector(item["vector"], embedding["dimensions"])
    seen: set[str] = set()
    for number, entry in enumerate(entries, 1):
        if (
            not isinstance(entry, dict)
            or set(entry) != ENTRY_FIELDS
            or entry["entry_id"] != ENTRY_ID.format(number)
            or entry["blind_id"] not in items
            or entry["dimension"] not in DIMENSIONS
            or entry["human"] not in (0, 1)
            or isinstance(entry["human"], bool)
            or (entry["blind_id"], entry["dimension"]) in seen
        ):
            raise _changed()
        seen.add((entry["blind_id"], entry["dimension"]))
    if {e["blind_id"] for e in entries} != set(items):
        raise _changed()


def load_pool(root: Path, pool_id: str) -> dict:
    """The written pool, verified: its fields and seal, and its source: the development
    assessment (kind and hash), every pooled item against that assessment's queue, and
    every entry's human decision against its frozen reference."""
    root = Path(root)
    path = pool_path(root, pool_id)
    if not path.parent.is_dir():
        raise PoolError(f"no example pool {pool_id!r}")
    if path.is_symlink():
        raise PoolError(f"{POOL_FILE} is a symlink; {INSPECT}")
    if not path.exists():
        raise PoolError(
            f"example pool {pool_id!r} has no {POOL_FILE}: its build was interrupted; {INSPECT}"
        )
    try:
        pool = json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise _changed() from None
    verify_pool(pool)
    if pool["pool_id"] != pool_id:
        raise _changed()
    source = pool["source"]
    made = _assessment(root, source["assessment_id"])
    _development(made)
    if made.manifest["sha256"] != source["assessment_sha256"]:
        raise PoolError(f"the pool's source assessment changed since the pool; {INSPECT}")
    reference = _reference(made)
    if reference["sha256"] != source["reference_sha256"]:
        raise PoolError(f"the pool's reference differs from the frozen one; {INSPECT}")
    queue = {entry.blind_id: entry for entry in made.queue}
    for blind_id, item in pool["items"].items():
        entry = queue.get(blind_id)
        if (
            entry is None
            or item["trace_id"] != entry.trace_id
            or item["payload_sha256"] != entry.payload_sha256
        ):
            raise PoolError(f"a pooled item differs from its source assessment; {INSPECT}")
    for entry in pool["entries"]:
        blind = queue[entry["blind_id"]]
        human = reference["labels"][entry["blind_id"]]["decisions"][entry["dimension"]]
        if (
            entry["human"] != human
            or entry["category"] != blind.category
            or entry["setup"] != blind.setup.model_dump(mode="json")
            or entry["item"] != blind.item.model_dump(mode="json")
        ):
            raise PoolError(
                f"a pool entry differs from its source assessment or frozen reference; {INSPECT}"
            )
    return pool


def check_independent(pool: dict, queue: Sequence[BlindItem]) -> None:
    """Refuse judging items that share a trace id or a payload hash with a pooled item."""
    traces = {item["trace_id"] for item in pool["items"].values()}
    payloads = {item["payload_sha256"] for item in pool["items"].values()}
    if any(e.trace_id in traces or e.payload_sha256 in payloads for e in queue):
        raise PoolError(
            "the example pool shares an item (trace id or payload hash) with the judged "
            "assessment; examples never come from the items being judged"
        )


# -------------------------------------------------------------------- selection


def _k(k: object, pool: dict) -> int:
    if type(k) is not int or k < 1:
        raise PoolError("examples_k must be a positive integer")
    if k > len(pool["entries"]):
        raise PoolError(
            f"examples_k is {k} but the pool has {len(pool['entries'])} entries; every judged "
            "item gets exactly examples_k examples"
        )
    return k


def select_examples(pool: dict, vectors: dict[str, list[float]], k: int) -> dict[str, list[str]]:
    """For each judged blind id, the `k` nearest pool entries by cosine similarity of the
    vectors, ties broken by entry id (B7 Decision 11)."""
    k = _k(k, pool)
    width = pool["embedding"]["dimensions"]
    units = {b: _unit(_check_vector(item["vector"], width)) for b, item in pool["items"].items()}
    selection: dict[str, list[str]] = {}
    for blind_id, vector in vectors.items():
        target = _unit(_check_vector(vector, width))
        scored = []
        for entry in pool["entries"]:
            unit = units[entry["blind_id"]]
            similarity = math.fsum(a * b for a, b in zip(target, unit, strict=True))
            scored.append((-similarity, entry["entry_id"]))
        selection[blind_id] = [entry_id for _, entry_id in sorted(scored)[:k]]
    return selection


def select_for(
    pool: dict, queue: Sequence[BlindItem], embedder: Embedder, k: int
) -> tuple[dict[str, list[float]], dict[str, list[str]]]:
    """Embed every judged item (question and answer) and select its examples; returns the
    judged vectors and the selection, both by blind id."""
    _k(k, pool)
    entries = list(queue)
    vectors = _embed(
        embedder, [embedding_text(e.item) for e in entries], pool["embedding"]["dimensions"]
    )
    by_id = {e.blind_id: v for e, v in zip(entries, vectors, strict=True)}
    return by_id, select_examples(pool, by_id, k)


# -------------------------------------------------------------------- rendering


def _example_body(entry: dict, rubric: Rubric) -> str:
    dimension = next((d for d in rubric.dimensions if d.id == entry["dimension"]), None)
    if dimension is None:
        raise PoolError("a pool entry names a dimension the rubric does not have")
    human = entry["human"]
    expected = dimension.pass_anchor if human == 1 else dimension.fail_anchor
    if entry["anchor"] != expected:
        raise PoolError(
            "a pool entry's anchor differs from the rubric's; the pool was built under "
            "another rubric"
        )
    try:
        setup = SetupRecord.model_validate(entry["setup"])
        item = QAItem.model_validate(entry["item"])
    except ValidationError:
        raise _changed("a pool entry") from None
    checks = entry["checks"]
    if not isinstance(checks, list) or any(not isinstance(c, str) for c in checks):
        raise _changed("a pool entry")
    lines = [
        f"Dimension: {dimension.id} {judge.one_line(dimension.name)}",
        "Setup record:",
        judge.setup_lines(setup),
        "Item fields this dimension scores:",
        judge.render_fields(item, EXAMPLE_FIELDS[dimension.id]),
        f"Checks for {dimension.id}:",
        *([judge.one_line(c) for c in checks] or ["(no check recorded for this dimension)"]),
        f"Human decision: {human} ({'pass' if human == 1 else 'fail'})",
        f"Rubric anchor for this decision: {judge.one_line(expected)}",
    ]
    return "\n".join(lines)


def render_examples(pool: dict, entry_ids: Sequence[str], rubric: Rubric) -> str:
    """The `{examples}` text for the chosen entries, in the given order.

    Each entry is one block, `<<<BEGIN {code} EXAMPLE n>>>` … `<<<END {code} EXAMPLE n>>>`,
    holding `Dimension:`, the five setup lines, the fields `EXAMPLE_FIELDS` gives for the
    dimension (headed and indented as in the judged item's block), the dimension's check
    lines, `Human decision: 0 (fail)` or `1 (pass)` and the rubric anchor for that
    decision. The code is the first 16 hex characters of the SHA-256 of the canonical
    JSON of `{"domain": EXAMPLES_FENCE_DOMAIN, "examples": [bodies]}`, so entry text
    cannot hold it; if it does anyway, the rendering is refused."""
    ids = list(entry_ids)
    if not ids or len(set(ids)) != len(ids):
        raise PoolError("examples need one or more distinct entry ids")
    by_id = {e.get("entry_id"): e for e in pool.get("entries", []) if isinstance(e, dict)}
    missing = [entry_id for entry_id in ids if entry_id not in by_id]
    if missing:
        raise PoolError(f"no pool entry {missing[0]!r}")
    bodies = [_example_body(by_id[entry_id], rubric) for entry_id in ids]
    code = judge.fence_code({"domain": EXAMPLES_FENCE_DOMAIN, "examples": bodies})
    if any(code in body for body in bodies):
        raise PoolError("the examples' block code occurs in their text; they cannot be fenced")
    return "\n\n".join(
        f"<<<BEGIN {code} EXAMPLE {n}>>>\n{body}\n<<<END {code} EXAMPLE {n}>>>"
        for n, body in enumerate(bodies, 1)
    )
