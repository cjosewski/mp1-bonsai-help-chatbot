"""Bounded multi-batch collection; failed and incomplete batches stay immutable evidence.

A collection is a sequence of batches. Each batch is one `generate_run` of `batch_count`
slots followed by one `gate_run`. The collection is ready when the union of retained
items across its gated batches (exact duplicate questions across batches dropped, first
kept) reaches `target_retained` with every category at `MIN_PER_CATEGORY` or more. A batch
is committed to the collection manifest before its first request, so a resume can never
reset the batch budget. A failed or incomplete batch is never rewritten; it counts toward
`max_batches`, and its numbers stay in every summary.

Each batch samples with its own seed, derived from the run seed and the batch number and
recorded in the collection manifest, so later batches are offered other sections. After a
batch is gated, its retained items are screened against every item the collection already
accepted, with the gate's embedder and threshold; the decisions are recorded so that
`collection_status` and the cohort verify them without an endpoint.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bonsai_help import gate, generate
from bonsai_help.checks import load_lexicons, normalize
from bonsai_help.config import REPOSITORY, RunConfig, load_prompt
from bonsai_help.doc_sources import CATEGORIES, load_config
from bonsai_help.model_client import EmbeddingError
from bonsai_help.setup import SetupProfiles
from bonsai_help.tracing import (
    artifact_hashes,
    digest,
    exclusive,
    now,
    read_json,
    read_records,
    run_directory,
    write_checkpoint,
)

MIN_PER_CATEGORY = 10
MAX_COLLECTION_ID = 55  # the batch suffix "-bNN" keeps run IDs within 64 characters
MAX_BATCHES = 20
LOCK = ".collection.lock"
FROZEN = "frozen.json"
DOC_SOURCES = REPOSITORY / "config/doc-sources.json"
FIXTURES = REPOSITORY / "tests/fixtures/docs"
REFERENCE = REPOSITORY / "reference"


class CollectionError(RuntimeError):
    """Collection or cohort evidence is missing, changed or not ready; inspect it."""


def policy(target_retained: int, batch_count: int, max_batches: int) -> dict:
    """The collection budget; part of its identity, so a resume cannot change it."""
    if type(target_retained) is not int or target_retained < 1:
        raise ValueError("target_retained must be a positive integer")
    if type(max_batches) is not int or not 1 <= max_batches <= MAX_BATCHES:
        raise ValueError(f"max_batches must be between 1 and {MAX_BATCHES}")
    generate._check_count(batch_count)
    return {
        "target_retained": target_retained,
        "batch_count": batch_count,
        "max_batches": max_batches,
        "min_per_category": MIN_PER_CATEGORY,
    }


def collection_directory(root: Path, collection_id: str) -> Path:
    if len(collection_id) > MAX_COLLECTION_ID:
        raise ValueError(f"collection ID must be at most {MAX_COLLECTION_ID} characters")
    if (root / "collections").is_symlink():
        raise ValueError("a symlinked collections directory is not supported")
    return run_directory(root / "collections", collection_id)


def batch_id(collection_id: str, number: int) -> str:
    return f"{collection_id}-b{number:02d}"


def batch_seed(seed: int, number: int) -> int:
    """The sampler seed of batch `number`: distinct per batch, reproducible from the run seed."""
    return int(digest({"seed": seed, "batch": number})[:15], 16)


def _text(record: dict) -> str:
    return f"{record['item']['question']}\n{record['item']['answer']}"


def _sealed(manifest: dict) -> str:
    return digest({k: v for k, v in manifest.items() if k != "sha256"})


def checkpoint(directory: Path, manifest: dict) -> None:
    manifest["sha256"] = _sealed(manifest)
    write_checkpoint(directory / "manifest.json", manifest)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_collection(root: Path, collection_id: str) -> tuple[Path, dict]:
    """The verified collection manifest; any edit or budget change is refused."""
    directory = collection_directory(root, collection_id)
    try:
        manifest = read_json(directory / "manifest.json")
    except FileNotFoundError:
        raise CollectionError(f"no collection {collection_id!r}") from None
    if manifest.get("sha256") != _sealed(manifest):
        raise CollectionError("collection manifest changed; inspect it")
    if manifest.get("collection_id") != collection_id:
        raise CollectionError("collection manifest names a different collection")
    budget = manifest["identity"]["policy"]
    batches = manifest["batches"]
    if len(batches) > budget["max_batches"] or [b["run_id"] for b in batches] != [
        batch_id(collection_id, n + 1) for n in range(len(batches))
    ]:
        raise CollectionError("collection batch membership or budget changed")
    if any(b.get("gated") is None for b in batches[:-1]):
        raise CollectionError("only the last batch of a collection can be ungated")
    seed = manifest["identity"]["settings"]["seed"]
    if any(b.get("seed") != batch_seed(seed, n + 1) for n, b in enumerate(batches)):
        raise CollectionError("collection batch seeds changed")
    return directory, manifest


def _batch(root: Path, entry: dict, identity: dict) -> dict:
    """One batch's verified manifest, items and gate report (None until gated)."""
    run_id = entry["run_id"]
    directory = run_directory(root, run_id)
    try:
        manifest = read_json(directory / "manifest.json")
    except FileNotFoundError:
        if entry.get("gated") is not None:
            raise CollectionError(f"{run_id}: gated batch is missing") from None
        return {"run_id": run_id, "manifest": None, "items": [], "gate": None}
    settings = identity["settings"] | {"seed": entry["seed"]}
    if (
        manifest.get("run_id") != run_id
        or manifest.get("settings") != settings
        or manifest.get("count") != identity["policy"]["batch_count"]
        or manifest.get("prompt_sha256") != identity["prompt_sha256"]
        or manifest.get("implementation", {}).get("source_tree_sha256")
        != identity["implementation"]
    ):
        raise CollectionError(f"{run_id}: batch differs from the frozen collection inputs")
    gated = entry.get("gated")
    if gated is None:
        return {"run_id": run_id, "manifest": manifest, "items": [], "gate": None}
    ledgers = artifact_hashes(directory)
    if any(ledgers.get(name) != gated["ledgers_sha256"].get(name) for name in generate.LEDGERS):
        raise CollectionError(f"{run_id}: batch ledgers changed after gating")
    if manifest.get("artifacts_sha256") != gated["ledgers_sha256"]:
        raise CollectionError(f"{run_id}: batch manifest changed after gating")
    report_path = directory / gate.REPORT
    if not report_path.exists() or _file_sha(report_path) != gated["gate_report_sha256"]:
        raise CollectionError(f"{run_id}: gate report changed or missing")
    report = read_json(report_path)
    items = read_records(directory / generate.ITEMS)
    if report.get("run_id") != run_id or set(report["per_item"]) != {i["item_id"] for i in items}:
        raise CollectionError(f"{run_id}: gate report does not match the batch items")
    return {"run_id": run_id, "manifest": manifest, "items": items, "gate": report}


def _check_screen(run_id: str, screen: dict | None, screened: list[str], accepted: set, model):
    """A recorded cross-batch screen must match the batch's candidates and the settings."""
    if screen is None:
        raise CollectionError(f"{run_id}: gated batch has no cross-batch screen")
    dropped = [pair["dropped"] for pair in screen["near_duplicates"]]
    if (
        screen.get("screened") != screened
        or screen.get("embedding_model") != model
        or screen.get("threshold") != gate.DEFAULT_THRESHOLD
        or screen.get("compared_with") != len(accepted)
        or len(set(dropped)) != len(dropped)
        or not set(dropped) <= set(screened)
        or any(pair["kept"] not in accepted for pair in screen["near_duplicates"])
        or any(pair["score"] < gate.DEFAULT_THRESHOLD for pair in screen["near_duplicates"])
    ):
        raise CollectionError(f"{run_id}: recorded cross-batch screen differs from the batch")
    return {pair["dropped"]: pair["kept"] for pair in screen["near_duplicates"]}


def summarize(root: Path, manifest: dict, *, pending: bool = False) -> dict:
    """Readiness, budget and the three denominators kept apart; reads only saved files.

    With `pending`, a last batch that is gated but not yet screened across batches is
    returned as `unscreened` candidates (not members); otherwise that is refused.
    """
    identity = manifest["identity"]
    budget = identity["policy"]
    counts = dict.fromkeys(CATEGORIES, 0)
    members: list[dict] = []
    decisions: list[dict] = []
    batches: list[dict] = []
    seen: dict[str, str] = {}
    reasons: list[str] = []
    unscreened: list[dict] = []
    model = identity["settings"]["embedding_model"]
    totals = dict.fromkeys(
        (
            "initial_slots",
            "initial_valid",
            "retry_recovered",
            "exhausted",
            "unknown_outcomes",
            "gate_input",
            "gate_retained",
        ),
        0,
    )
    for number, entry in enumerate(manifest["batches"], 1):
        batch = _batch(root, entry, identity)
        run = batch["manifest"]
        report = batch["gate"]
        if run is None:
            reasons.append("batch_not_started")
            continue
        metrics = run.get("metrics") or {}
        if report is None:
            reasons.append("batch_not_gated")
        else:
            for key in ("initial_slots", "initial_valid", "retry_recovered", "exhausted"):
                totals[key] += metrics[key]
            totals["unknown_outcomes"] += metrics["unknown_outcomes"]
            totals["gate_input"] += report["input_count"]
            totals["gate_retained"] += len(report["retained_ids"])
        batches.append(
            {
                "run_id": batch["run_id"],
                "status": run["status"],
                "initial_slots": metrics.get("initial_slots"),
                "initial_valid": metrics.get("initial_valid"),
                "retry_recovered": metrics.get("retry_recovered"),
                "exhausted": metrics.get("exhausted"),
                "unknown_outcomes": metrics.get("unknown_outcomes"),
                "gated": report is not None,
                "gate_input": report["input_count"] if report else None,
                "retained": len(report["retained_ids"]) if report else None,
                "distribution_passed": report["distribution"]["passed"] if report else None,
            }
        )
        if report is None:
            continue
        retained = set(report["retained_ids"])
        candidates = []
        batch_decisions = []
        for record in sorted(batch["items"], key=lambda r: r["item_id"]):
            if record["item_id"] not in retained:
                continue
            key = normalize(record["item"]["question"])
            exact = seen.get(key)
            if exact is None:
                seen[key] = record["item_id"]
                candidates.append(record)
            batch_decisions.append((record, key, exact))
        screen = entry["gated"].get("cross_batch")
        if screen is None and pending and number == len(manifest["batches"]):
            unscreened = candidates
            reasons.append("batch_not_screened")
            continue
        near = _check_screen(
            batch["run_id"],
            screen,
            [c["item_id"] for c in candidates],
            {m["item_id"] for m in members},
            model,
        )
        for record, key, exact in batch_decisions:
            if exact is not None:
                rejection, duplicate_of = ["cross_batch_duplicate"], exact
            elif record["item_id"] in near:
                rejection = ["cross_batch_near_duplicate"]
                duplicate_of = near[record["item_id"]]
            else:
                rejection, duplicate_of = [], None
            decisions.append(
                {
                    "item_id": record["item_id"],
                    "run_id": batch["run_id"],
                    "category": record["category"],
                    "retained": not rejection,
                    "reasons": rejection,
                    "duplicate_of": duplicate_of,
                }
            )
            if not rejection:
                members.append(record)
                counts[record["category"]] += 1
    if len(members) < budget["target_retained"]:
        reasons.append("below_target")
    if any(n < budget["min_per_category"] for n in counts.values()):
        reasons.append("category_deficits")
    slots = totals["initial_slots"]
    return {
        "collection_id": manifest["collection_id"],
        "status": "ready" if not reasons else "incomplete",
        "reasons": sorted(set(reasons)),
        "policy": budget,
        "counts": counts,
        "retained": len(members),
        "remaining_batches": budget["max_batches"] - len(manifest["batches"]),
        **totals,
        "initial_validity": totals["initial_valid"] / slots if slots else None,
        "initial_denominator": "all planned slots of the gated batches",
        "gate_retention": (
            totals["gate_retained"] / totals["gate_input"] if totals["gate_input"] else None
        ),
        "near_duplicates_scope": (
            "within each batch by the gate; across batches against every earlier accepted "
            "item, same embedder and threshold (recorded decisions)"
        ),
        "quality_status": "pending",
        "batches": batches,
        "decisions": decisions,
        "members": members,
    } | ({"unscreened": unscreened} if pending else {})


def collection_status(root: Path, collection_id: str) -> dict:
    """Verify a collection's saved evidence and summarize it; never writes."""
    directory, manifest = load_collection(root, collection_id)
    if (directory / LOCK).exists():
        raise CollectionError("collection lock present: a writer is active or was interrupted")
    return summarize(root, manifest)


def _inputs(reference_dir: Path) -> dict:
    files = [reference_dir / "setup-profiles.json", *sorted((reference_dir / "lexicons").glob("*"))]
    return {
        "reference_sha256": digest(
            {p.relative_to(reference_dir).as_posix(): _file_sha(p) for p in files if p.is_file()}
        ),
        "doc_sources_sha256": _file_sha(DOC_SOURCES),
    }


def collect(
    config: RunConfig,
    collection_id: str,
    client,
    embedder,
    *,
    target_retained: int = 50,
    batch_count: int = 70,
    max_batches: int = 3,
    resume: bool = False,
    fixtures_dir: Path = FIXTURES,
    reference_dir: Path = REFERENCE,
) -> dict:
    """Run batches until the collection is ready or its batch budget is spent."""
    budget = policy(target_retained, batch_count, max_batches)
    root = config.artifact_path()
    directory = collection_directory(root, collection_id)
    prompt, prompt_sha256 = load_prompt(config)
    profiles = SetupProfiles.model_validate(
        json.loads((reference_dir / "setup-profiles.json").read_bytes())
    )
    lexicons = load_lexicons(reference_dir)
    doc_config = load_config(DOC_SOURCES)
    identity = {
        "settings": config.public_settings(),
        "prompt_sha256": prompt_sha256,
        "implementation": generate.implementation_identity(config.prompt_file())[
            "source_tree_sha256"
        ],
        "inputs": _inputs(reference_dir),
        "policy": budget,
    }
    if resume:
        if not (directory / "manifest.json").exists():
            raise ValueError(f"no collection {collection_id!r} to resume")
    else:
        directory.mkdir(parents=True, exist_ok=False)
        checkpoint(
            directory,
            {
                "schema_version": "1",
                "collection_id": collection_id,
                "created_at": now(),
                "identity": identity,
                "batches": [],
            },
        )
    with exclusive(directory / LOCK):
        _, manifest = load_collection(root, collection_id)
        if manifest["identity"] != identity:
            raise ValueError("resume requires identical collection inputs, policy and code")
        if (directory / FROZEN).exists():
            raise ValueError("a frozen collection cannot resume")
        while True:
            summary = summarize(root, manifest)
            if summary["status"] == "ready":
                return summary
            last = manifest["batches"][-1] if manifest["batches"] else None
            if last is None or last["gated"] is not None:
                if len(manifest["batches"]) == budget["max_batches"]:
                    return summary
                number = len(manifest["batches"]) + 1
                last = {
                    "run_id": batch_id(collection_id, number),
                    "seed": batch_seed(config.seed, number),
                    "gated": None,
                }
                manifest["batches"].append(last)
                checkpoint(directory, manifest)  # commit the budget before any request
            _run_batch(
                config.model_copy(update={"seed": last["seed"]}),
                root,
                last["run_id"],
                prompt,
                prompt_sha256,
                client=client,
                embedder=embedder,
                lexicons=lexicons,
                profiles=profiles,
                doc_config=doc_config,
                fixtures_dir=fixtures_dir,
                count=budget["batch_count"],
            )
            batch_dir = run_directory(root, last["run_id"])
            last["gated"] = {
                "gate_report_sha256": _file_sha(batch_dir / gate.REPORT),
                "ledgers_sha256": artifact_hashes(batch_dir),
            }
            pending = summarize(root, manifest, pending=True)
            last["gated"]["cross_batch"] = _screen(
                pending["members"], pending["unscreened"], embedder, config.embedding_model
            )
            checkpoint(directory, manifest)


def _screen(accepted: list[dict], candidates: list[dict], embedder, model: str) -> dict:
    """Drop a candidate whose cosine to an earlier accepted item reaches the gate threshold."""
    threshold = gate.DEFAULT_THRESHOLD
    record = {
        "embedding_model": model,
        "threshold": threshold,
        "text": "question, newline, answer",
        "screened": [c["item_id"] for c in candidates],
        "compared_with": len(accepted),
        "near_duplicates": [],
    }
    if not accepted or not candidates:
        return record
    texts = [_text(r) for r in accepted + candidates]
    try:
        vectors = embedder.embed(texts)
    except EmbeddingError as error:
        raise CollectionError(f"cross-batch embedding failed: {error}") from None
    if len(vectors) != len(texts) or len({len(v) for v in vectors}) != 1:
        raise CollectionError("cross-batch embedding returned mismatched vectors")
    earlier = list(zip((a["item_id"] for a in accepted), vectors[: len(accepted)], strict=True))
    for candidate, vector in zip(candidates, vectors[len(accepted) :], strict=True):
        score, kept = max((gate._cosine(vector, v), item_id) for item_id, v in earlier)
        if score >= threshold:
            record["near_duplicates"].append(
                {"kept": kept, "dropped": candidate["item_id"], "score": score}
            )
    return record


def _run_batch(config, root, run_id, prompt, prompt_sha256, *, count, **inputs) -> None:
    """Generate (or resume) a batch and gate it; a terminal batch is never regenerated."""
    directory = run_directory(root, run_id)
    status = None
    if (directory / "manifest.json").exists():
        status = read_json(directory / "manifest.json").get("status")
    elif directory.exists():
        raise CollectionError(f"{run_id}: batch directory without a manifest; inspect it")
    if status not in gate.GATEABLE:
        generate.generate_run(
            config,
            prompt,
            prompt_sha256,
            count=count,
            run_id=run_id,
            client=inputs["client"],
            profiles=inputs["profiles"],
            doc_config=inputs["doc_config"],
            fixtures_dir=inputs["fixtures_dir"],
            resume=status is not None,
        )
    if not (directory / gate.REPORT).exists():
        gate.gate_run(
            root,
            run_id,
            lexicons=inputs["lexicons"],
            embedder=inputs["embedder"],
            embedding_model=config.embedding_model,
        )
