"""Bounded multi-batch collection and the frozen cohort, with synthetic models only."""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
from test_gate import FakeEmbedder, good_item
from test_generation import FIXTURES, offered_ids

from bonsai_help import cohort, collection, gate, generate
from bonsai_help.checks import load_lexicons
from bonsai_help.collection import CollectionError, collect, collection_status
from bonsai_help.config import RunConfig, load_prompt
from bonsai_help.doc_sources import CATEGORIES, load_config
from bonsai_help.model_client import AttemptResult, EmbeddingError
from bonsai_help.schemas import GenerationOutput
from bonsai_help.setup import SetupProfiles

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


def standalone_run(config, run_id, count=5):
    """A run made by `generate`, outside any collection (its seed is not a batch seed)."""
    prompt, prompt_sha256 = load_prompt(config)
    generate.generate_run(
        config,
        prompt,
        prompt_sha256,
        count=count,
        run_id=run_id,
        client=UniqueClient(),
        profiles=SetupProfiles.model_validate(
            json.loads((REFERENCE / "setup-profiles.json").read_bytes())
        ),
        doc_config=load_config(collection.DOC_SOURCES),
        fixtures_dir=FIXTURES,
    )
    return config.artifact_path() / run_id


def test_new_collection_refuses_a_foreign_run_with_a_batch_id(config):
    foreign = standalone_run(config, "col-1-b02")
    before = hashes(foreign)
    with pytest.raises(ValueError, match="col-1-b02 already exists"):
        run_collect(config, UniqueClient(), max_batches=3)
    # Refused before anything is written: no collection, the foreign run unchanged.
    assert not (config.artifact_path() / "collections").exists()
    assert hashes(foreign) == before and not (foreign / gate.REPORT).exists()


def test_collection_never_adopts_a_run_created_after_it_started(config):
    with pytest.raises(KeyboardInterrupt):
        run_collect(config, UniqueClient(interrupt_call=1), max_batches=3)
    foreign = standalone_run(config, "col-1-b02")
    before = hashes(foreign)
    with pytest.raises(CollectionError, match="col-1-b02 already exists"):
        run_collect(config, UniqueClient(), max_batches=3, resume=True)
    assert hashes(foreign) == before and not (foreign / gate.REPORT).exists()
    manifest = json.loads((config.artifact_path() / "collections/col-1/manifest.json").read_text())
    assert [b["run_id"] for b in manifest["batches"]] == ["col-1-b01"]


def test_foreign_run_under_a_committed_batch_id_is_never_gated(config):
    with pytest.raises(KeyboardInterrupt):
        run_collect(config, UniqueClient(interrupt_call=1), max_batches=3)
    root = config.artifact_path()
    # Synthetic setup: the committed batch's run is replaced by an unrelated standalone run.
    shutil.rmtree(root / "col-1-b01")
    foreign = standalone_run(config, "col-1-b01", count=30)
    before = hashes(foreign)
    client = UniqueClient()
    with pytest.raises(CollectionError, match="differs from the frozen collection inputs"):
        run_collect(config, client, max_batches=3, resume=True)
    assert client.calls == 0
    assert hashes(foreign) == before and not (foreign / gate.REPORT).exists()


class OperatorClient(UniqueClient):
    """Synthetic items whose steps name a Bonsai operator, so lexicons decide a check."""

    def generate(self, messages):
        result = super().generate(messages)
        if result.item is None:
            return result
        steps = [*result.item.item.steps, "Run bim.align_wall from the Bonsai wall tool panel."]
        output = result.item.model_copy(
            update={"item": result.item.item.model_copy(update={"steps": steps})}
        )
        return AttemptResult(output, result.raw_response, None, None, result.response_model)


@pytest.mark.parametrize("change", ["embedding_model", "lexicons"])
def test_batch_gated_outside_the_collection_is_refused(config, change):
    def start():
        return collect(
            config,
            "col-1",
            OperatorClient(),
            embedder,
            batch_count=5,
            max_batches=2,
            fixtures_dir=FIXTURES,
            reference_dir=REFERENCE,
            resume=resume,
        )

    embedder, resume = FakeEmbedder(fail=True), False
    with pytest.raises(gate.GateError, match="embedding failed"):
        start()
    root = config.artifact_path()
    lexicons = load_lexicons(REFERENCE)
    model = "synthetic-embedding"
    if change == "embedding_model":
        model = "OTHER-synthetic-embedding"
    else:
        lexicons = dataclasses.replace(
            lexicons, bim_ids={line: frozenset() for line in lexicons.bim_ids}
        )
    gate.gate_run(
        root, "col-1-b01", lexicons=lexicons, embedder=FakeEmbedder(), embedding_model=model
    )
    embedder, resume = FakeEmbedder(), True
    with pytest.raises(CollectionError, match="gate report"):
        start()
    manifest = json.loads((root / "collections/col-1/manifest.json").read_text())
    assert manifest["batches"][0]["gated"] is None
    assert not (root / "col-1-b02").exists()


@pytest.mark.parametrize(
    "edit",
    [
        {"metrics": {"initial_valid": 30, "retry_recovered": 0}},
        {"metrics": {"exhausted": 0, "exhausted_slot_ids": []}},
        {"status": "complete"},
    ],
)
def test_batch_metrics_are_recomputed_from_the_ledgers(config, edit):
    # Batch 1: slot 1 is exhausted and slot 2 recovers on its third attempt.
    summary = run_collect(config, UniqueClient(fail_first=5), max_batches=3)
    first = summary["batches"][0]
    assert first["initial_valid"] == 28 and first["retry_recovered"] == 1
    assert first["exhausted"] == 1 and first["status"] == "incomplete"
    root = config.artifact_path()
    path = root / "col-1-b01/manifest.json"
    run = json.loads(path.read_text())
    run["metrics"] |= edit.get("metrics", {})
    run["status"] = edit.get("status", run["status"])
    path.write_text(json.dumps(run))  # a plain edit: the run manifest itself is not sealed
    with pytest.raises(CollectionError, match="col-1-b01: batch .*ledgers"):
        collection_status(root, "col-1")
    with pytest.raises(CollectionError, match="ledgers"):
        cohort.freeze_cohort(root, "col-1", "cohort-1")


def test_assessed_collect_without_model_identity_writes_nothing(tmp_path):
    config = make_config(tmp_path, purpose="baseline", model="synthetic-model")
    with pytest.raises(ValueError, match="model_identity and model_sha256") as refused:
        run_collect(config, UniqueClient(), batch_count=5, max_batches=1)
    assert not (config.artifact_path() / "collections").exists()
    # The collection refuses exactly as a standalone generation run does.
    with pytest.raises(type(refused.value)) as standalone:
        standalone_run(config, "solo")
    assert str(standalone.value) == str(refused.value)
    assert not (config.artifact_path() / "solo").exists()
    # The corrected config can start the same collection ID: nothing was burned.
    fixed = make_config(
        tmp_path,
        purpose="baseline",
        model="synthetic-model",
        model_identity="synthetic-model-identity",
        model_sha256="a" * 64,
    )
    summary = run_collect(fixed, UniqueClient(), batch_count=5, max_batches=1)
    assert summary["retained"] == 5


class DroppedQuestionClient(UniqueClient):
    """Batches of 5. Call 1 (A) and call 6 (D) are near-twins by their answers; call 11 (Q)
    repeats D's question with an ordinary answer, near to nothing."""

    SHARED = "How do I add a synthetic shared slab question to this Bonsai project?"

    def generate(self, messages):
        result = super().generate(messages)
        changes = {}
        if self.calls in (1, 6):
            changes["answer"] = result.item.item.answer + " Check the twin wall afterwards."
        if self.calls in (6, 11):
            changes["question"] = self.SHARED
        if changes:
            item = result.item.item.model_copy(update=changes)
            output = result.item.model_copy(update={"item": item})
            result = AttemptResult(output, result.raw_response, None, None, "synthetic-model")
        return result


def test_exact_duplicates_are_decided_against_members_only(config):
    summary = collect(
        config,
        "col-1",
        DroppedQuestionClient(),
        TwinEmbedder(),
        batch_count=5,
        max_batches=3,
        fixtures_dir=FIXTURES,
        reference_dir=REFERENCE,
    )
    members = {m["item_id"] for m in summary["members"]}
    by_run = {}
    for decision in summary["decisions"]:
        by_run.setdefault(decision["run_id"], []).append(decision)
    near = [d for d in by_run["col-1-b02"] if d["reasons"] == ["cross_batch_near_duplicate"]]
    assert len(near) == 1 and near[0]["duplicate_of"] in members
    # Q matches only D's question, and D is not a member: Q is screened and retained.
    assert all(d["retained"] for d in by_run["col-1-b03"])
    assert summary["retained"] == 14
    assert all(d["duplicate_of"] in members for d in summary["decisions"] if d["duplicate_of"])
    assert collection_status(config.artifact_path(), "col-1") == summary


def test_modules_do_not_import_cli_or_assessment():
    for module in (collection, cohort):
        text = Path(module.__file__).read_text()
        assert "bonsai_help.cli" not in text and "assessment" not in text


@pytest.mark.parametrize("edit", ["extra_key", "missing_key", "not_an_object", "not_text"])
def test_malformed_slot_entry_of_a_gated_batch_is_refused(config, edit):
    run_collect(config, UniqueClient(), batch_count=5, max_batches=1)
    root = config.artifact_path()
    path = root / "col-1-b01/manifest.json"
    run = json.loads(path.read_text())
    slot = run["slots"][0]
    if edit == "extra_key":
        slot["extra"] = "synthetic"
    elif edit == "missing_key":
        del slot["version_line"]
    elif edit == "not_an_object":
        run["slots"][0] = "synthetic-slot"
    else:
        slot["setup_id"] = ["synthetic"]
    path.write_text(json.dumps(run))  # a plain edit: the run manifest itself is not sealed
    with pytest.raises(CollectionError, match="col-1-b01: batch slot plan is malformed"):
        collection_status(root, "col-1")


class ShortFirstClient(UniqueClient):
    """Call 1 has a too-short answer, so the gate's answer_length check drops it."""

    def generate(self, messages):
        result = super().generate(messages)
        if self.calls == 1:
            item = result.item.item.model_copy(update={"answer": "Too short."})
            output = result.item.model_copy(update={"item": item})
            result = AttemptResult(output, result.raw_response, None, None, "synthetic-model")
        return result


def _tamper(report: dict, edit: str) -> None:
    per_item = report["per_item"]
    kept = report["retained_ids"]
    dropped = next(i for i, v in per_item.items() if not v["retained"])
    if edit == "retained_ids":
        report["retained_ids"] = kept[1:]
    elif edit == "dropped_item_retained":
        per_item[dropped].update(retained=True, dropped_by=[])
        report["retained_ids"] = sorted([*kept, dropped])
    elif edit == "dropped_by":
        per_item[dropped]["dropped_by"] = ["D2:safety_length"]
    elif edit == "unfounded_exact_duplicate":
        per_item[kept[0]].update(retained=False, dropped_by=[gate.EXACT])
        report["retained_ids"] = kept[1:]
        report["exact_duplicates"].append({"kept": kept[1], "dropped": kept[0]})
    elif edit == "category":
        other = next(c for c in CATEGORIES if c != per_item[kept[0]]["category"])
        per_item[kept[0]]["category"] = other
    elif edit == "distribution":
        report["distribution"]["passed"] = not report["distribution"]["passed"]
    elif edit == "per_category":
        category = per_item[kept[0]]["category"]
        report["per_category"][category]["retained"] += 1
    # Malformed shapes: each must give the same refusal, never a TypeError.
    elif edit == "near_duplicates_not_a_list":
        report["near_duplicates"] = 5
    elif edit == "near_pair_not_text":
        report["near_duplicates"] = [{"kept": [kept[0]], "dropped": [dropped], "score": 1.0}]
    elif edit == "per_item_entry_not_an_object":
        per_item[dropped] = "synthetic"
    elif edit == "per_item_not_an_object":
        report["per_item"] = 5
    elif edit == "distribution_not_an_object":
        report["distribution"] = "synthetic"


@pytest.mark.parametrize(
    "edit",
    [
        None,
        "retained_ids",
        "dropped_item_retained",
        "dropped_by",
        "unfounded_exact_duplicate",
        "category",
        "distribution",
        "per_category",
        "near_duplicates_not_a_list",
        "near_pair_not_text",
        "per_item_entry_not_an_object",
        "per_item_not_an_object",
        "distribution_not_an_object",
    ],
)
def test_gate_report_decisions_are_rederived_before_adoption(config, edit):
    def start(embedder, resume):
        return collect(
            config,
            "col-1",
            ShortFirstClient(),
            embedder,
            batch_count=5,
            max_batches=1,
            fixtures_dir=FIXTURES,
            reference_dir=REFERENCE,
            resume=resume,
        )

    with pytest.raises(gate.GateError, match="embedding failed"):
        start(FakeEmbedder(fail=True), False)
    root = config.artifact_path()
    # Gated outside the collection with the collection's own settings and lexicons.
    report = gate.gate_run(
        root,
        "col-1-b01",
        lexicons=load_lexicons(REFERENCE),
        embedder=FakeEmbedder(),
        embedding_model="synthetic-embedding",
    )
    dropped = [v for v in report["per_item"].values() if not v["retained"]]
    assert len(dropped) == 1 and "D1:answer_length" in dropped[0]["dropped_by"]
    if edit is not None:
        path = root / "col-1-b01" / gate.REPORT
        report = json.loads(path.read_text())
        _tamper(report, edit)
        path.write_text(json.dumps(report))
        with pytest.raises(CollectionError, match="col-1-b01: gate report decisions"):
            start(FakeEmbedder(), True)
        manifest = json.loads((root / "collections/col-1/manifest.json").read_text())
        assert manifest["batches"][0]["gated"] is None
    else:
        summary = start(FakeEmbedder(), True)
        assert summary["retained"] == 4 and summary["batches"][0]["gated"] is True


class InBatchDuplicateClient(UniqueClient):
    """Call 2 repeats call 1's question; calls 3 and 4 are near-twins (TwinEmbedder)."""

    def generate(self, messages):
        result = super().generate(messages)
        if self.calls == 1:
            self.first_question = result.item.item.question
        changes = {}
        if self.calls == 2:
            changes["question"] = self.first_question
        if self.calls in (3, 4):
            changes["question"] = f"How do I add twin wall variant {self.calls} here?"
        if changes:
            item = result.item.item.model_copy(update=changes)
            output = result.item.model_copy(update={"item": item})
            result = AttemptResult(output, result.raw_response, None, None, "synthetic-model")
        return result


def test_collection_adopts_its_own_in_batch_duplicate_decisions(config):
    client = InBatchDuplicateClient()
    summary = collect(
        config,
        "col-1",
        client,
        TwinEmbedder(),
        batch_count=5,
        max_batches=1,
        fixtures_dir=FIXTURES,
        reference_dir=REFERENCE,
    )
    root = config.artifact_path()
    report = json.loads((root / "col-1-b01" / gate.REPORT).read_text())
    assert len(report["exact_duplicates"]) == 1 and len(report["near_duplicates"]) == 1
    assert summary["retained"] == 3 and summary["batches"][0]["gated"] is True
    assert collection_status(root, "col-1") == summary


class FailOnCallEmbedder(FakeEmbedder):
    """FakeEmbedder whose call number `fail_call` (1-based) is a synthetic failure."""

    def __init__(self, fail_call):
        super().__init__()
        self.fail_call = fail_call

    def embed(self, texts):
        if len(self.calls) + 1 == self.fail_call:
            self.calls.append(list(texts))
            raise EmbeddingError("synthetic embedding failure")
        return super().embed(texts)


def test_resume_after_a_gate_embedding_failure_regenerates_nothing(config):
    with pytest.raises(gate.GateError, match="embedding failed"):
        collect(
            config,
            "col-1",
            UniqueClient(),
            FakeEmbedder(fail=True),
            batch_count=30,
            max_batches=3,
            fixtures_dir=FIXTURES,
            reference_dir=REFERENCE,
        )
    root = config.artifact_path()
    before = hashes(root / "col-1-b01")
    assert gate.REPORT not in before
    client = UniqueClient()
    client.calls = 30  # its questions continue after batch 1's, so none repeats one
    summary = run_collect(config, client, max_batches=3, resume=True)
    assert summary["status"] == "ready" and summary["retained"] == 60
    assert client.calls == 60  # batch 2 only; batch 1 is gated, never regenerated
    after = hashes(root / "col-1-b01")
    assert {k: v for k, v in after.items() if k != gate.REPORT} == before
    assert collection_status(root, "col-1") == summary


def test_resume_after_a_cross_batch_embedding_failure_requests_nothing(config):
    # Embedding calls: 1 gates batch 1 (no screen, nothing accepted yet), 2 gates
    # batch 2, 3 screens batch 2 against batch 1 and fails.
    with pytest.raises(CollectionError, match="cross-batch embedding failed"):
        collect(
            config,
            "col-1",
            UniqueClient(),
            FailOnCallEmbedder(3),
            batch_count=30,
            max_batches=3,
            fixtures_dir=FIXTURES,
            reference_dir=REFERENCE,
        )
    root = config.artifact_path()
    manifest = json.loads((root / "collections/col-1/manifest.json").read_text())
    assert [b["gated"] is None for b in manifest["batches"]] == [False, True]
    before = hashes(root / "col-1-b02")
    assert gate.REPORT in before
    client = UniqueClient()
    summary = run_collect(config, client, max_batches=3, resume=True)
    assert client.calls == 0
    assert summary["status"] == "ready" and summary["retained"] == 60
    assert [b["run_id"] for b in summary["batches"]] == ["col-1-b01", "col-1-b02"]
    assert hashes(root / "col-1-b02") == before
    assert collection_status(root, "col-1") == summary


class UnusableOnCallEmbedder(FakeEmbedder):
    """FakeEmbedder whose call number `bad_call` returns `value` as the last vector."""

    def __init__(self, bad_call, value):
        super().__init__()
        self.bad_call = bad_call
        self.value = value

    def embed(self, texts):
        vectors = super().embed(texts)
        if len(self.calls) == self.bad_call:
            vectors[-1] = [self.value] * len(vectors[-1])
        return vectors


@pytest.mark.parametrize("value", [0.0, float("nan"), float("inf")])
def test_unusable_cross_batch_vector_is_a_collection_error(config, value):
    # Call 3 screens batch 2 against batch 1; its last vector is a candidate's.
    with pytest.raises(CollectionError, match="cross-batch embedding returned a zero or non"):
        collect(
            config,
            "col-1",
            UniqueClient(),
            UnusableOnCallEmbedder(3, value),
            batch_count=30,
            max_batches=3,
            fixtures_dir=FIXTURES,
            reference_dir=REFERENCE,
        )
    manifest = json.loads((config.artifact_path() / "collections/col-1/manifest.json").read_text())
    assert [b["gated"] is None for b in manifest["batches"]] == [False, True]


def test_failed_cohort_write_never_frees_the_collection_for_another_cohort(config, monkeypatch):
    run_collect(config, UniqueClient(), max_batches=3)
    root = config.artifact_path()
    write_once = cohort._write_once

    def full_disk(path, value):
        if path.name == cohort.COHORT:
            raise OSError(errno.ENOSPC, "synthetic: no space left on device")
        write_once(path, value)

    monkeypatch.setattr(cohort, "_write_once", full_disk)
    with pytest.raises(OSError, match="synthetic"):
        cohort.freeze_cohort(root, "col-1", "cohort-1")
    monkeypatch.setattr(cohort, "_write_once", write_once)
    assert not (root / "collections/col-1/.collection.lock").exists()
    # The failed freeze is evidence to inspect; a second cohort is never frozen.
    with pytest.raises(CollectionError, match="already frozen"):
        cohort.freeze_cohort(root, "col-1", "cohort-2")
    assert not (root / "cohorts/cohort-2").exists()
    with pytest.raises(CollectionError, match="no cohort"):
        cohort.load_cohort(root, "cohort-1")
    with pytest.raises(ValueError, match="frozen"):
        run_collect(config, UniqueClient(), max_batches=3, resume=True)
