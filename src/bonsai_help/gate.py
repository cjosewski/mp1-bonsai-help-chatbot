"""First-pass gate: which generated items go on to labels and the judge.

Order: per-item deterministic checks, exact duplicates, then near duplicates by embedding
similarity. Dropped items are never embedded. Category counts and the distribution are
computed over the final retained set. The gate screens heuristically and never certifies
rubric quality, so ``quality_status`` stays pending; the report is written exactly once.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from bonsai_help.checks import Lexicons, normalize, run_checks
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.generate import ITEMS, LEDGERS, split_citations
from bonsai_help.model_client import EmbeddingError
from bonsai_help.schemas import CitedSection, GeneratedItem
from bonsai_help.tracing import (
    artifact_hashes,
    exclusive,
    read_json,
    read_records,
    run_directory,
    write_checkpoint,
)

REPORT = "gate-report.json"
DEFAULT_THRESHOLD = 0.92
DEFAULT_MIN_SHARE = 0.18
GATEABLE = ("complete", "incomplete")
DENOMINATOR = "schema-valid items entering the gate"
EXACT, NEAR = "exact_duplicate", "near_duplicate"


class GateError(RuntimeError):
    """The gate could not run or could not finish; no report was written."""


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def evaluate_gate(
    records: list[GeneratedItem],
    *,
    lexicons: Lexicons,
    embedder: Embedder,
    embedding_model: str,
    threshold: float = DEFAULT_THRESHOLD,
    min_share: float = DEFAULT_MIN_SHARE,
    unoffered_citations: Mapping[str, Sequence[str]] | None = None,
) -> dict:
    """Screen validated items; ``unoffered_citations`` maps item id to its attempt's list."""
    unoffered = unoffered_citations or {}
    ordered = sorted(records, key=lambda r: r.item_id)
    if len({r.item_id for r in ordered}) != len(ordered):
        raise ValueError("gate input contains duplicate item_id")
    per_item: dict[str, dict] = {}
    drops: dict[str, int] = {}
    for record in ordered:
        results = run_checks(record, lexicons, unoffered.get(record.item_id, ()))
        dropped = [f"{r.dimension}:{r.name}" for r in results if r.drop]
        for r in results:
            drops.setdefault(r.name, 0)
            drops[r.name] += r.drop
        per_item[record.item_id] = {
            "category": record.category,
            "checks": [asdict(r) for r in results],
            "retained": not dropped,
            "dropped_by": dropped,
        }
    drops[EXACT] = drops[NEAR] = 0

    exact: list[dict] = []
    seen: dict[str, str] = {}
    candidates: list[GeneratedItem] = []
    for record in ordered:
        if not per_item[record.item_id]["retained"]:
            continue
        key = normalize(record.item.question)
        if key in seen:
            exact.append({"kept": seen[key], "dropped": record.item_id})
            per_item[record.item_id].update(retained=False, dropped_by=[EXACT])
            drops[EXACT] += 1
        else:
            seen[key] = record.item_id
            candidates.append(record)

    near: list[dict] = []
    if candidates:
        texts = [f"{r.item.question}\n{r.item.answer}" for r in candidates]
        try:
            vectors = embedder.embed(texts)
        except EmbeddingError as error:
            raise GateError(f"embedding failed: {error}") from None
        if len(vectors) != len(texts):
            raise GateError(f"expected {len(texts)} vectors, received {len(vectors)}")
        if len({len(v) for v in vectors}) != 1:
            raise GateError("embedding vectors have mismatched dimensions")
        kept: list[tuple[str, Sequence[float]]] = []
        for record, vector in zip(candidates, vectors, strict=True):
            best = max(((_cosine(vector, v), k) for k, v in kept), default=None)
            if best is not None and best[0] >= threshold:
                near.append({"kept": best[1], "dropped": record.item_id, "score": best[0]})
                per_item[record.item_id].update(retained=False, dropped_by=[NEAR])
                drops[NEAR] += 1
            else:
                kept.append((record.item_id, vector))

    retained_ids = [i for i, v in per_item.items() if v["retained"]]
    total = len(retained_ids)
    per_category = {}
    for category in CATEGORIES:
        count = sum(1 for v in per_item.values() if v["retained"] and v["category"] == category)
        per_category[category] = {
            "input": sum(1 for r in ordered if r.category == category),
            "retained": count,
            "share": count / total if total else 0.0,
        }
    return {
        "schema_version": "1",
        "status_scope": "implemented deterministic checks and duplicate screens only",
        "quality_status": "pending",
        "course_acceptance": "not_evaluated",
        "input_count": len(ordered),
        "per_item": per_item,
        "drops_per_check": drops,
        "exact_duplicates": exact,
        "near_duplicates": near,
        "per_category": per_category,
        "distribution": {
            "min_share": min_share,
            "passed": all(c["share"] >= min_share for c in per_category.values()),
        },
        "retained_ids": retained_ids,
        "gate_pass_rate": total / len(ordered) if ordered else None,
        "embedding_model": embedding_model,
        "threshold": threshold,
    }


def _load_run(directory: Path) -> tuple[list[GeneratedItem], dict[str, list[str]], dict]:
    """Items, each item's recomputed unoffered citations and run facts, after verification."""
    try:
        manifest = read_json(directory / "manifest.json")
    except FileNotFoundError:
        raise GateError(f"no run at {directory.name!r}") from None
    if manifest.get("status") not in GATEABLE:
        raise GateError(f"run status {manifest.get('status')!r} cannot be gated")
    recorded = manifest.get("artifacts_sha256", {})
    actual = artifact_hashes(directory)
    for name in LEDGERS:
        if name not in recorded or actual.get(name) != recorded[name]:
            raise ValueError(f"changed or missing {name}; preserve the run for inspection")
    successful: dict[str, dict] = {}
    for a in read_records(directory / "attempts.jsonl"):
        if a.get("schema_valid") is True:
            successful[a["record"]["item_id"]] = a
    items: list[GeneratedItem] = []
    unoffered: dict[str, list[str]] = {}
    for raw in read_records(directory / ITEMS):
        item = GeneratedItem.model_validate(raw)
        attempt = successful.get(item.item_id)
        if attempt is None or attempt["record"] != item.model_dump(mode="json"):
            raise ValueError(f"item {item.item_id} differs from its successful attempt")
        offered = [CitedSection.model_validate(s) for s in attempt["record"]["offered_sections"]]
        _, computed = split_citations(offered, attempt.get("cited_section_ids") or [])
        if attempt.get("unoffered_citations") != computed:
            raise ValueError(f"item {item.item_id} has inconsistent unoffered_citations")
        items.append(item)
        unoffered[item.item_id] = computed
    if {i.item_id for i in items} != set(successful) or len(items) != len(successful):
        raise ValueError("successful attempts and items.jsonl disagree; inspect the run")
    slots = manifest.get("slots") or []
    done = {i.slot_id for i in items}
    facts = {
        "run_status": manifest["status"],
        "slot_count": len(slots),
        "exhausted_slots": [s["slot_id"] for s in slots if s["slot_id"] not in done],
    }
    return items, unoffered, facts


def gate_run(
    root: Path,
    run_id: str,
    *,
    lexicons: Lexicons,
    embedder: Embedder,
    embedding_model: str,
    threshold: float = DEFAULT_THRESHOLD,
    min_share: float = DEFAULT_MIN_SHARE,
) -> dict:
    """Gate a saved run and write ``gate-report.json`` once; never overwrites."""
    directory = run_directory(root, run_id)
    if not directory.is_dir():
        raise GateError(f"no run at {run_id!r}")
    if (directory / REPORT).exists():
        raise GateError(f"{REPORT} already exists; a run is gated once")
    try:
        with exclusive(directory / ".gate.lock"):
            if (directory / ".generation.lock").exists():
                raise GateError("generation lock present; inspect before gating")
            items, unoffered, facts = _load_run(directory)
            report = evaluate_gate(
                items,
                lexicons=lexicons,
                embedder=embedder,
                embedding_model=embedding_model,
                threshold=threshold,
                min_share=min_share,
                unoffered_citations=unoffered,
            ) | {"run_id": run_id, **facts, "gate_pass_rate_denominator": DENOMINATOR}
            if (directory / REPORT).exists():
                raise GateError(f"{REPORT} already exists; a run is gated once")
            write_checkpoint(directory / REPORT, report)
            return report
    except FileExistsError:
        raise GateError("a gate lock is present; inspect before gating") from None
