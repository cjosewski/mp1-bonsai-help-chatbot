"""A frozen 50-item cohort: 10 retained items per category from a ready collection.

The selection is seeded from the collection ID, so the same evidence always gives the
same cohort. `cohort.json` is written once, and the collection gets a freeze receipt, so
it can neither resume nor be frozen a second time. The receipt is written before the
cohort file: a freeze that fails between the two leaves a frozen collection whose cohort
is missing, evidence to inspect, and never a collection free to freeze a second cohort.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from bonsai_help.collection import (
    FROZEN,
    LOCK,
    CollectionError,
    load_collection,
    summarize,
)
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.tracing import digest, exclusive, now, read_json, run_directory

PER_CATEGORY = 10
COHORT = "cohort.json"


def cohort_directory(root: Path, cohort_id: str) -> Path:
    if (root / "cohorts").is_symlink():
        raise ValueError("a symlinked cohorts directory is not supported")
    return run_directory(root / "cohorts", cohort_id)


def _sealed(manifest: dict) -> str:
    return digest({k: v for k, v in manifest.items() if k != "sha256"})


def _select(collection_id: str, members: list[dict]) -> list[dict]:
    """`PER_CATEGORY` members of each category, seeded from the collection ID."""
    rng = random.Random(int(digest(collection_id)[:16], 16))
    chosen: list[dict] = []
    for category in CATEGORIES:
        pool = sorted((m for m in members if m["category"] == category), key=lambda m: m["item_id"])
        if len(pool) < PER_CATEGORY:
            raise CollectionError(f"collection is not ready: {category} has {len(pool)} items")
        chosen.extend(sorted(rng.sample(pool, PER_CATEGORY), key=lambda m: m["item_id"]))
    return chosen


def _compact(summary: dict) -> dict:
    return {k: v for k, v in summary.items() if k not in {"members", "decisions"}}


def freeze_cohort(root: Path, collection_id: str, cohort_id: str) -> dict:
    """Freeze a ready collection into `cohorts/<cohort_id>/cohort.json`; once only."""
    parent, collection = load_collection(root, collection_id)
    target = cohort_directory(root, cohort_id)
    with exclusive(parent / LOCK):
        if (parent / FROZEN).exists():
            raise CollectionError("collection already frozen; inspect the existing cohort")
        summary = summarize(root, collection)
        if summary["status"] != "ready":
            raise CollectionError("collection is not ready: " + ", ".join(summary["reasons"]))
        items = _select(collection_id, summary["members"])
        manifest = {
            "schema_version": "1",
            "cohort_id": cohort_id,
            "created_at": now(),
            "collection_id": collection_id,
            "collection_sha256": collection["sha256"],
            "selection": f"{PER_CATEGORY} per category, seeded by sha256(collection_id)",
            "per_category": {c: sum(i["category"] == c for i in items) for c in CATEGORIES},
            "item_ids": [i["item_id"] for i in items],
            "collection_summary_sha256": digest(_compact(summary)),
            "quality_status": "pending",
            "items": items,
        }
        manifest["sha256"] = _sealed(manifest)
        target.mkdir(parents=True, exist_ok=False)  # an existing cohort ID writes nothing
        _write_once(parent / FROZEN, {"cohort_id": cohort_id, "sha256": manifest["sha256"]})
        _write_once(target / COHORT, manifest)
        return manifest


def _write_once(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def load_cohort(root: Path, cohort_id: str) -> dict:
    """The cohort after re-verifying it against its collection's saved evidence."""
    directory = cohort_directory(root, cohort_id)
    try:
        manifest = read_json(directory / COHORT)
    except FileNotFoundError:
        raise CollectionError(f"no cohort {cohort_id!r}") from None
    if manifest.get("cohort_id") != cohort_id or manifest.get("sha256") != _sealed(manifest):
        raise CollectionError("cohort file changed; inspect it")
    parent, collection = load_collection(root, manifest["collection_id"])
    if collection["sha256"] != manifest["collection_sha256"]:
        raise CollectionError("cohort source collection changed")
    try:
        receipt = read_json(parent / FROZEN)
    except FileNotFoundError:
        raise CollectionError("cohort freeze receipt is missing") from None
    if receipt != {"cohort_id": cohort_id, "sha256": manifest["sha256"]}:
        raise CollectionError("cohort freeze receipt differs")
    summary = summarize(root, collection)
    items = _select(manifest["collection_id"], summary["members"])
    if (
        summary["status"] != "ready"
        or digest(_compact(summary)) != manifest["collection_summary_sha256"]
        or items != manifest["items"]
        or [i["item_id"] for i in items] != manifest["item_ids"]
    ):
        raise CollectionError("cohort source evidence changed")
    return manifest
