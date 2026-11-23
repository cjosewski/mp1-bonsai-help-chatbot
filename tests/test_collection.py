"""Bounded multi-batch collection and the frozen cohort, with synthetic models only."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from test_gate import FakeEmbedder, good_item
from test_generation import FIXTURES, offered_ids

from bonsai_help import cohort, collection
from bonsai_help.collection import CollectionError, collect, collection_status
from bonsai_help.config import RunConfig
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.model_client import AttemptResult
from bonsai_help.schemas import GenerationOutput

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference"


class UniqueClient:
    """Synthetic model: a distinct, check-passing item per call, unless told to fail."""

    def __init__(self, *, fail_first=0, interrupt_call=None):
        self.calls = 0
        self.fail_first = fail_first
        self.interrupt_call = interrupt_call

    def generate(self, messages):
        self.calls += 1
        if self.calls == self.interrupt_call:
            raise KeyboardInterrupt
        if self.calls <= self.fail_first:
            return AttemptResult(None, "{synthetic-broken-json", "invalid JSON", "ValidationError")
        slot = re.search(r"slot (\S+), attempt", messages[-1]["content"])[1]
        body = {
            "item": good_item(self.calls)
            | {"question": f"How do I add synthetic wall {self.calls} for slot {slot} here?"},
            "cited_section_ids": offered_ids(messages)[:1],
        }
        output = GenerationOutput.model_validate(body)
        return AttemptResult(output, {"synthetic": True}, None, None, "synthetic-model")


@pytest.fixture
def config(tmp_path):
    return make_config(tmp_path)


def make_config(tmp_path, **changes):
    return RunConfig.model_validate(
        {
            "base_url": "http://127.0.0.1:8080/v1",
            "model": "explicit-test-model",
            "embedding_model": "synthetic-embedding",
            "seed": 7,
            "artifact_root": str(tmp_path / "runs"),
        }
        | changes
    )


def run_collect(config, client, collection_id="col-1", **kwargs):
    kwargs.setdefault("batch_count", 30)
    return collect(
        config,
        collection_id,
        client,
        FakeEmbedder(),
        fixtures_dir=FIXTURES,
        reference_dir=REFERENCE,
        **kwargs,
    )


def hashes(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file()
    }


def test_collect_stops_at_target(config):
    client = UniqueClient()
    summary = run_collect(config, client, max_batches=3)
    root = config.artifact_path()
    assert summary["status"] == "ready"
    assert [b["run_id"] for b in summary["batches"]] == ["col-1-b01", "col-1-b02"]
    assert not (root / "col-1-b03").exists()
    assert client.calls == 60
    assert summary["counts"] == dict.fromkeys(CATEGORIES, 12)
    assert summary["retained"] == 60 >= summary["policy"]["target_retained"] == 50
    assert summary["remaining_batches"] == 1
    # Initial-attempt validity, retry recovery and gate retention are reported apart.
    assert summary["initial_slots"] == 60 and summary["initial_valid"] == 60
    assert summary["retry_recovered"] == 0
    assert summary["gate_input"] == 60 and summary["gate_retained"] == 60
    assert collection_status(root, "col-1") == summary


def test_failed_batch_is_immutable_and_counted(config):
    # Batch 1: every attempt of every slot fails (30 slots x 3 attempts).
    summary = run_collect(config, UniqueClient(fail_first=90), max_batches=2)
    root = config.artifact_path()
    assert summary["status"] == "incomplete"
    assert summary["remaining_batches"] == 0
    assert "category_deficits" in summary["reasons"]
    first, second = summary["batches"]
    assert first["status"] == "incomplete" and first["retained"] == 0
    assert first["exhausted"] == 30
    assert second["status"] == "complete" and second["retained"] == 30
    assert summary["initial_slots"] == 60 and summary["initial_valid"] == 30
    before = hashes(root / "col-1-b01")
    # Resume cannot reset the budget: no new batch, no request, nothing rewritten.
    client = UniqueClient()
    again = run_collect(config, client, max_batches=2, resume=True)
    assert client.calls == 0
    assert again == summary
    assert hashes(root / "col-1-b01") == before
    assert not (root / "col-1-b03").exists()


def test_failed_batch_is_replaced_within_the_budget(config):
    summary = run_collect(config, UniqueClient(fail_first=90), max_batches=3)
    assert summary["status"] == "ready"
    assert [b["retained"] for b in summary["batches"]] == [0, 30, 30]
    manifest = json.loads((config.artifact_path() / "collections/col-1/manifest.json").read_text())
    recorded = manifest["batches"][0]["gated"]
    current = hashes(config.artifact_path() / "col-1-b01")
    assert recorded["gate_report_sha256"] == current["gate-report.json"]


def test_interrupted_batch_resumes_without_new_budget(config):
    with pytest.raises(KeyboardInterrupt):
        run_collect(config, UniqueClient(interrupt_call=5), max_batches=3)
    root = config.artifact_path()
    assert json.loads((root / "col-1-b01/manifest.json").read_text())["status"] == "interrupted"
    with pytest.raises(ValueError, match="identical"):
        run_collect(config, UniqueClient(), max_batches=2, resume=True)
    summary = run_collect(config, UniqueClient(), max_batches=3, resume=True)
    assert summary["status"] == "ready"
    assert [b["run_id"] for b in summary["batches"]] == ["col-1-b01", "col-1-b02"]
    # The interrupted request is disclosed as an unknown outcome, not hidden.
    assert summary["batches"][0]["unknown_outcomes"] == 1


def test_new_collection_never_overwrites(config):
    run_collect(config, UniqueClient(), max_batches=1)
    with pytest.raises(FileExistsError):
        run_collect(config, UniqueClient(), max_batches=1)
    with pytest.raises(ValueError, match="no collection"):
        run_collect(config, UniqueClient(), collection_id="col-2", resume=True)


def test_collection_parameters_are_checked(config):
    with pytest.raises(ValueError, match="count"):
        run_collect(config, UniqueClient(), batch_count=7)
    with pytest.raises(ValueError, match="max_batches"):
        run_collect(config, UniqueClient(), max_batches=0)
    with pytest.raises(ValueError, match="target_retained"):
        run_collect(config, UniqueClient(), target_retained=0)
    with pytest.raises(ValueError, match="55"):
        run_collect(config, UniqueClient(), collection_id="c" * 56)
    assert not (config.artifact_path() / "collections").exists()


def test_cross_batch_exact_duplicates_are_rejected(config):
    class Repeating(UniqueClient):
        def generate(self, messages):
            result = super().generate(messages)
            item = result.item.item.model_copy(
                update={"question": f"How do I add synthetic wall {self.calls % 30} here?"}
            )
            output = result.item.model_copy(update={"item": item})
            return AttemptResult(output, result.raw_response, None, None, result.response_model)

    summary = run_collect(config, Repeating(), max_batches=2)
    assert summary["retained"] == 30
    rejected = [d for d in summary["decisions"] if d["reasons"] == ["cross_batch_duplicate"]]
    assert len(rejected) == 30
    assert all(d["run_id"] == "col-1-b02" for d in rejected)


def test_tampered_or_locked_collection_is_refused(config):
    run_collect(config, UniqueClient(), max_batches=1)
    root = config.artifact_path()
    lock = root / "collections/col-1/.collection.lock"
    lock.write_text("synthetic leftover")
    with pytest.raises(CollectionError, match="lock"):
        collection_status(root, "col-1")
    lock.unlink()
    report = root / "col-1-b01/gate-report.json"
    data = json.loads(report.read_text())
    data["retained_ids"] = data["retained_ids"][:1]
    report.write_text(json.dumps(data))
    with pytest.raises(CollectionError, match="gate report"):
        collection_status(root, "col-1")


def test_cohort_requires_ready_collection_and_balance(tmp_path):
    small = make_config(tmp_path / "a")
    run_collect(small, UniqueClient(), max_batches=1)
    with pytest.raises(CollectionError, match="not ready"):
        cohort.freeze_cohort(small.artifact_path(), "col-1", "cohort-1")
    assert not (small.artifact_path() / "cohorts/cohort-1").exists()

    picks = []
    for name in ("b", "c"):
        config = make_config(tmp_path / name)
        run_collect(config, UniqueClient(), max_batches=3)
        root = config.artifact_path()
        frozen = cohort.freeze_cohort(root, "col-1", "cohort-1")
        assert len(frozen["item_ids"]) == 50
        assert frozen["per_category"] == dict.fromkeys(CATEGORIES, 10)
        assert {i["item_id"] for i in frozen["items"]} == set(frozen["item_ids"])
        assert cohort.load_cohort(root, "cohort-1") == frozen
        picks.append(frozen["item_ids"])
    # Seeded from the collection id: the same evidence gives the same selection.
    assert picks[0] == picks[1]

    with pytest.raises(CollectionError, match="already frozen"):
        cohort.freeze_cohort(root, "col-1", "cohort-2")
    with pytest.raises(ValueError, match="frozen"):
        run_collect(config, UniqueClient(), max_batches=3, resume=True)
    path = root / "cohorts/cohort-1/cohort.json"
    data = json.loads(path.read_text())
    data["item_ids"].reverse()
    path.write_text(json.dumps(data))
    with pytest.raises(CollectionError, match="cohort"):
        cohort.load_cohort(root, "cohort-1")


def test_batches_sample_with_their_own_recorded_seed(config):
    run_collect(config, UniqueClient(), max_batches=3)
    root = config.artifact_path()
    manifest = json.loads((root / "collections/col-1/manifest.json").read_text())
    seeds = [b["seed"] for b in manifest["batches"]]
    assert seeds == [collection.batch_seed(7, 1), collection.batch_seed(7, 2)]
    assert len(set(seeds) | {7}) == 3
    offered = []
    for entry in manifest["batches"]:
        run = json.loads((root / entry["run_id"] / "manifest.json").read_text())
        assert run["settings"]["seed"] == entry["seed"]
        starts = (root / entry["run_id"] / "starts.jsonl").read_text().splitlines()
        offered.append(
            {(r := json.loads(line))["slot_id"]: r["offered_sections"] for line in starts}
        )
    assert offered[0].keys() == offered[1].keys()
    differing = [slot for slot in offered[0] if offered[0][slot] != offered[1][slot]]
    assert len(differing) > len(offered[0]) // 2


class TwinEmbedder:
    """Texts containing "twin" share one vector; every other text gets its own."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        width = len(texts) + 2
        return [
            [1.0 if j == (0 if "twin" in text else i + 1) else 0.0 for j in range(width)]
            for i, text in enumerate(texts)
        ]


class TwinClient(UniqueClient):
    """Call 1 (batch 1) and call 31 (batch 2, same slot id) are distinct near-twins."""

    def generate(self, messages):
        result = super().generate(messages)
        if self.calls in (1, 31):
            question = f"How do I add twin wall variant {self.calls} to a Bonsai project?"
            item = result.item.item.model_copy(update={"question": question})
            output = result.item.model_copy(update={"item": item})
            result = AttemptResult(output, result.raw_response, None, None, "synthetic-model")
        return result


def test_near_duplicate_across_batches_is_excluded_from_union_and_cohort(config):
    embedder = TwinEmbedder()
    summary = collect(
        config,
        "col-1",
        TwinClient(),
        embedder,
        batch_count=30,
        max_batches=3,
        fixtures_dir=FIXTURES,
        reference_dir=REFERENCE,
    )
    root = config.artifact_path()
    assert summary["status"] == "ready" and summary["retained"] == 59
    dropped = [d for d in summary["decisions"] if d["reasons"] == ["cross_batch_near_duplicate"]]
    assert len(dropped) == 1
    first, second = dropped[0]["duplicate_of"], dropped[0]["item_id"]
    assert first.startswith("col-1-b01-") and second.startswith("col-1-b02-")
    assert first.removeprefix("col-1-b01-") == second.removeprefix("col-1-b02-")
    assert second not in {m["item_id"] for m in summary["members"]}
    manifest = json.loads((root / "collections/col-1/manifest.json").read_text())
    screen = manifest["batches"][1]["gated"]["cross_batch"]
    assert screen["embedding_model"] == "synthetic-embedding"
    assert screen["threshold"] == 0.92 and screen["compared_with"] == 30
    assert screen["near_duplicates"] == [{"kept": first, "dropped": second, "score": 1.0}]
    assert manifest["batches"][0]["gated"]["cross_batch"]["near_duplicates"] == []
    # Status and cohort verify the recorded decisions without an endpoint.
    assert collection_status(root, "col-1") == summary
    frozen = cohort.freeze_cohort(root, "col-1", "cohort-1")
    assert second not in frozen["item_ids"]
    assert cohort.load_cohort(root, "cohort-1") == frozen


def test_unscreened_gated_batch_is_refused(config):
    run_collect(config, UniqueClient(), max_batches=1)
    root = config.artifact_path()
    path = root / "collections/col-1/manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["batches"][0]["gated"]["cross_batch"]
    collection.checkpoint(path.parent, manifest)
    with pytest.raises(CollectionError, match="cross-batch screen"):
        collection_status(root, "col-1")


def test_modules_do_not_import_cli_or_assessment():
    for module in (collection, cohort):
        text = Path(module.__file__).read_text()
        assert "bonsai_help.cli" not in text and "assessment" not in text
