"""Judge v2's development example pool and its selection (B7 Task 6), under `tmp_path`.

No model or embedding endpoint is called. Judges are scripted fakes returning synthetic
`AttemptResult`s and embedders are scripted fakes returning fixed synthetic vectors. Every
assessment, label and reference is synthetic: labels are written through the library by
"synthetic-reviewer" with visibly synthetic notes, and every `chad_accepted` rubric is a
synthetic copy. The v2 prompt here is a synthetic test copy, never `prompts/judge-v2.md`.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pytest
from evaluation_support import (
    doc_config,
    fresh_root,
    profiles,
    provenance_sentinels,
    write_rubric,
)
from fakes import embedding_response, fixed_response
from test_calibration import (
    NOTE,
    broken,
    by_item,
    frozen_with,
    judged,
    smoke_on_labeled,
)
from test_judge import (
    ARM,
    BASELINE,
    DEVELOPMENT,
    JUDGE_MODEL,
    KEY_ENV,
    KEY_SENTINEL,
    REVIEWER,
    SMOKE,
    FakeJudge,
    config,
    create,
    measured,
    qualify,
    run_dir,
)

from bonsai_help import assessment, human_reference, judge, judge_examples, labels
from bonsai_help.assessment import load_assessment
from bonsai_help.collection import DOC_SOURCES, FIXTURES
from bonsai_help.doc_sources import load_config
from bonsai_help.evaluation_schemas import DIMENSIONS, Decisions, Judgment
from bonsai_help.judge import JudgeError
from bonsai_help.judge_examples import PoolError
from bonsai_help.model_client import AttemptResult, EmbeddingError
from bonsai_help.tracing import digest, read_records

REPO = Path(__file__).resolve().parents[1]
DEV = "dev-labels"
OTHER = "dev-other"
EMBEDDING = "synthetic-embedding"  # the synthetic collections' gate embedding model
REASON_SENTINEL = "synthetic-judge-reason-sentinel-zq8"
FIELD_ORDER = (
    "question",
    "answer",
    "equipment_problem",
    "tools_required",
    "steps",
    "safety_info",
    "tips",
)
HEADINGS = {
    "question": "Question:",
    "answer": "Answer:",
    "equipment_problem": "Equipment problem:",
    "tools_required": "Tools required:",
    "steps": "Steps:",
    "safety_info": "Safety info:",
    "tips": "Tips:",
}
# The field map of `render_examples`, pinned (Task 6 with refinement 2: D4 and D5 also
# show the steps, on which both rubric checks rest).
EXPECTED_FIELDS = {
    "D1": ("question", "answer", "steps"),
    "D2": ("steps", "safety_info"),
    "D3": ("answer", "tools_required", "steps"),
    "D4": ("question", "answer", "steps"),
    "D5": ("answer", "steps"),
    "D6": ("steps", "tips"),
}
# Synthetic human decisions on the development assessment, by display position, and the
# synthetic judge's decisions that differ from 1.
HUMAN = {1: {"D1": 0}, 2: {"D3": 0, "D5": 0}, 3: {"D2": None, "D6": 0}}
JUDGE = {3: {"D6": 0, "D2": 1}, 4: {"D4": 0}}
# The resolved pairs that differ, in dimension then display order (the entry order).
EXPECTED_ENTRIES = [(1, "D1", 0), (2, "D3", 0), (4, "D4", 1), (2, "D5", 0)]


# ------------------------------------------------------------------------- helpers


@pytest.fixture
def root(tmp_path, tmp_path_factory):
    return fresh_root(tmp_path, tmp_path_factory)


@pytest.fixture
def accepted(tmp_path):
    return write_rubric(tmp_path, name="accepted-rubric.json")


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(KEY_ENV, KEY_SENTINEL)


class TableEmbedder:
    """Synthetic embedder: a fixed vector for each listed question (the first line of the
    text), a default vector otherwise, or a synthetic failure."""

    def __init__(self, table=None, default=(1.0, 0.0, 0.0), fail=False):
        self.table = dict(table or {})
        self.default = tuple(default)
        self.fail = fail
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise EmbeddingError("synthetic embedding failure")
        return [list(self.table.get(text.split("\n", 1)[0], self.default)) for text in texts]


def position(blind_id: str) -> int:
    return int(blind_id.split("-")[1])


def reason_reply(blind_id: str, attempt: int) -> AttemptResult:
    values = JUDGE.get(position(blind_id), {})
    verdict = judged(blind_id, **values).model_dump(mode="json")
    for d in DIMENSIONS:
        verdict[d]["reason"] = f"{REASON_SENTINEL} {d} {blind_id}"
    return AttemptResult(
        Judgment.model_validate(verdict), {"synthetic": "judge reply"}, None, None, JUDGE_MODEL
    )


def development(root, accepted, *, count=10):
    """A frozen synthetic development assessment with mixed decisions, a qualified judge
    config and a complete measured v1 run (`dev-v1`) on it."""
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    made = frozen_with(
        root,
        accepted,
        lambda blind_id: HUMAN.get(position(blind_id), {}),
        assessment_id=DEV,
        cohorts=(DEVELOPMENT.cohort_id,),
        count=count,
    )
    status = judge.judge_run(
        root, DEV, "dev-v1", judge_config, by_item(made, reason_reply), qualification_id="q-1"
    )
    assert status["status"] == "complete"
    return made, judge_config


def other_development(root, accepted):
    """A second frozen synthetic development assessment that shares no item with DEV."""
    assessment.create_assessment(
        root,
        OTHER,
        [DEVELOPMENT.cohort_id],
        count=10,
        seed="synthetic-seed-judge",
        rubric_path=accepted,
        profiles=profiles(),
        doc_config=doc_config(),
        fixtures_dir=FIXTURES,
        exclude=[DEV, SMOKE],
    )
    made = load(root, OTHER)
    values = Decisions.model_validate(dict.fromkeys(DIMENSIONS, 1))
    for entry in made.queue:
        labels.record_label(
            made, entry.blind_id, values, REVIEWER, rubric_path=accepted, notes=NOTE
        )
    human_reference.freeze_reference(made, REVIEWER, declare_blind=True, rubric_path=accepted)
    return made


def build(root, embedder=None, *, pool_id="pool-1", run_id="dev-v1", **kwargs):
    return judge_examples.build_pool(
        root,
        kwargs.pop("assessment_id", DEV),
        run_id,
        pool_id,
        embedder=embedder or TableEmbedder(),
        embedding_model=kwargs.pop("embedding_model", EMBEDDING),
    )


def pool_dir(root, pool_id="pool-1") -> Path:
    return root / judge_examples.POOLS / pool_id


def v2_prompt(tmp_path) -> Path:
    """A synthetic test v2 prompt: judge v1 plus an `{examples}` section."""
    directory = tmp_path / "synthetic-prompts"
    directory.mkdir(exist_ok=True)
    path = directory / "judge-v2.md"
    text = (REPO / "prompts/judge-v1.md").read_text(encoding="utf-8")
    path.write_text(
        text + "\n## Synthetic test examples\n\n{examples}\n<!-- synthetic test prompt -->\n",
        encoding="utf-8",
    )
    return path


def v2_config(root, tmp_path, **overrides):
    values = {
        "prompt_path": str(v2_prompt(tmp_path)),
        "embedding_model": EMBEDDING,
        "examples_k": 2,
    }
    values.update(overrides)
    return measured(root, **values)


def v2_run(root, assessment_id, run_id, judge_config, client, embedder, **kwargs):
    return judge.judge_run(
        root,
        assessment_id,
        run_id,
        judge_config,
        client,
        qualification_id="q-1",
        pool_id=kwargs.pop("pool_id", "pool-1"),
        embedder=embedder,
        **kwargs,
    )


def load(root, assessment_id):
    return load_assessment(
        root, assessment_id, fixtures_dir=FIXTURES, doc_config=load_config(DOC_SOURCES)
    )


def synthetic_entry(dimension: str, human: int, rubric) -> dict:
    """A pool entry whose seven fields each hold their own visibly synthetic marker."""
    found = next(d for d in rubric.dimensions if d.id == dimension)
    return {
        "entry_id": "E-001",
        "blind_id": "L-001",
        "dimension": dimension,
        "category": "bonsai_modeling",
        "setup": {
            "blender": "synthetic-blender",
            "bonsai": "synthetic-bonsai",
            "ifc_schema": "IFC4",
            "discipline": "synthetic-discipline",
            "model_state": "synthetic-state",
        },
        "item": {
            "question": "synthetic-marker-question?",
            "answer": "synthetic-marker-answer",
            "equipment_problem": "synthetic-marker-equipment_problem",
            "tools_required": ["synthetic-marker-tools_required"],
            "steps": [
                "synthetic-marker-steps one",
                "synthetic-marker-steps two",
                "synthetic-marker-steps three",
            ],
            "safety_info": "synthetic-marker-safety_info",
            "tips": ["synthetic-marker-tips"],
        },
        "checks": [f"{dimension} synthetic_check: passed (synthetic detail)"],
        "human": human,
        "anchor": found.pass_anchor if human == 1 else found.fail_anchor,
    }


# ------------------------------------------------------------------ pool sources


def test_pool_refuses_arm_assessment(root, accepted):
    made = frozen_with(root, accepted)
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    client = by_item(made, lambda blind_id, attempt: reason_reply(blind_id, attempt))
    judge.judge_run(root, ARM, "arm-v1", judge_config, client, qualification_id="q-1")
    embedder = TableEmbedder()
    with pytest.raises(PoolError, match="development"):
        build(root, embedder, assessment_id=ARM, run_id="arm-v1")
    assert embedder.calls == []
    assert not (root / judge_examples.POOLS).exists()


def test_pool_requires_frozen_dev_reference_and_complete_v1_run(root, accepted, tmp_path):
    embedder = TableEmbedder()
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    # A development assessment with no frozen reference (the never-labeled smoke one).
    with pytest.raises(PoolError, match="frozen"):
        build(root, embedder, assessment_id=SMOKE, run_id="smoke-1")
    made = frozen_with(
        root,
        accepted,
        lambda blind_id: HUMAN.get(position(blind_id), {}),
        assessment_id=DEV,
        cohorts=(DEVELOPMENT.cohort_id,),
        count=10,
    )
    # No such judge run.
    with pytest.raises(PoolError, match="no judge run"):
        build(root, embedder, run_id="dev-none")
    # An incomplete measured run: one item's attempts all fail.
    first = made.manifest["display_order"][0]

    def partly(blind_id, attempt):
        return broken(blind_id) if blind_id == first else reason_reply(blind_id, attempt)

    status = judge.judge_run(
        root, DEV, "dev-partial", judge_config, by_item(made, partly), qualification_id="q-1"
    )
    assert status["status"] == "incomplete"
    with pytest.raises(PoolError, match="complete"):
        build(root, embedder, run_id="dev-partial")
    # A smoke run (forged onto the labeled assessment) is not a measured v1 run.
    smoke_on_labeled(root, made, "dev-smoke", config(root), by_item(made, reason_reply))
    with pytest.raises(PoolError, match="measured"):
        build(root, embedder, run_id="dev-smoke")
    # A run that already had an example pool (a v2 run) is not judge v1.
    status = judge.judge_run(
        root, DEV, "dev-v1", judge_config, by_item(made, reason_reply), qualification_id="q-1"
    )
    assert status["status"] == "complete"
    build(root, TableEmbedder(), pool_id="pool-seed")
    other = other_development(root, accepted)
    v2 = v2_config(root, tmp_path)
    client = by_item(other, reason_reply)
    v2_run(root, OTHER, "other-v2", v2, client, TableEmbedder(), pool_id="pool-seed")
    with pytest.raises(PoolError, match="judge v1"):
        build(root, embedder, assessment_id=OTHER, run_id="other-v2")
    assert embedder.calls == []
    assert sorted(p.name for p in (root / judge_examples.POOLS).iterdir()) == ["pool-seed"]


def test_pool_holds_only_disagreements_with_human_decisions(root, accepted):
    made, _ = development(root, accepted)
    pool = build(root)
    order = made.manifest["display_order"]
    found = [(position(e["blind_id"]), e["dimension"], e["human"]) for e in pool["entries"]]
    assert found == EXPECTED_ENTRIES
    assert [e["entry_id"] for e in pool["entries"]] == ["E-001", "E-002", "E-003", "E-004"]
    # The unresolved D2 of item 3 (the judge passed it) and the agreed D6 (both 0) are out.
    assert not any(position(e["blind_id"]) == 3 for e in pool["entries"])
    rubric = {d.id: d for d in made.rubric.dimensions}
    queue = {e.blind_id: e for e in made.queue}
    for entry in pool["entries"]:
        blind = queue[entry["blind_id"]]
        dimension = rubric[entry["dimension"]]
        assert entry["anchor"] == (
            dimension.pass_anchor if entry["human"] == 1 else dimension.fail_anchor
        )
        assert entry["category"] == blind.category
        assert entry["item"] == blind.item.model_dump(mode="json")
        assert entry["setup"] == blind.setup.model_dump(mode="json")
        assert entry["checks"] and all(
            line.startswith(f"{entry['dimension']} ") for line in entry["checks"]
        )
    # One vector per item that has an entry, embedded from its question and answer.
    assert sorted(pool["items"]) == sorted({order[0], order[1], order[3]})
    assert pool["embedding"]["model"] == EMBEDDING
    assert pool["source"]["kind"] == "development"
    assert pool["source"]["judge_run_id"] == "dev-v1"


def test_pool_holds_no_notes_or_judge_reasons(root, accepted):
    made, _ = development(root, accepted)
    embedder = TableEmbedder()
    build(root, embedder)
    text = (pool_dir(root) / judge_examples.POOL_FILE).read_text(encoding="utf-8")
    sentinels = provenance_sentinels(root) | {NOTE, REASON_SENTINEL, "synthetic-reviewer"}
    leaked = sorted(s for s in sentinels if s in text)
    assert not leaked, leaked
    assert '"reason"' not in text and '"notes"' not in text and '"judge"' not in text
    # The embedder saw only each item's question and answer.
    queue = {e.item.question: e for e in made.queue}
    for sent in embedder.calls[0]:
        question, answer = sent.split("\n", 1)
        assert queue[question].item.answer == answer


_OPENED: list[str] | None = None


def _audit(event, args):
    if _OPENED is not None and event == "open" and isinstance(args[0], (str, bytes, Path)):
        _OPENED.append(str(Path(args[0] if not isinstance(args[0], bytes) else args[0].decode())))


sys.addaudithook(_audit)


def test_pool_never_reads_arm_calibration_files(root, accepted):
    global _OPENED
    development(root, accepted)
    arm = create(root, accepted, ARM, [BASELINE.cohort_id], 20)
    calibration_dir = arm.directory / "calibration"
    calibration_dir.mkdir()
    sentinel = "synthetic-arm-calibration-sentinel-zq0"
    (calibration_dir / "r-arm.json").write_text(
        json.dumps({"status": "pending", "note": sentinel}), encoding="utf-8"
    )
    (calibration_dir / "r-arm.disagreements.json").write_text(
        json.dumps(
            [
                {
                    "blind_id": "L-001",
                    "dimension": "D3",
                    "human": 0,
                    "judge": 1,
                    "judge_reason": sentinel,
                }
            ]
        ),
        encoding="utf-8",
    )
    _OPENED = []
    try:
        build(root)
    finally:
        opened, _OPENED = _OPENED, None
    assert opened, "the audit hook saw no file being opened"
    touched = [p for p in opened if Path(p).resolve().is_relative_to(arm.directory.resolve())]
    assert touched == []
    assert not any("/calibration/" in p for p in opened)
    text = (pool_dir(root) / judge_examples.POOL_FILE).read_text(encoding="utf-8")
    assert sentinel not in text


# --------------------------------------------------------------------- selection


def test_selection_is_deterministic_by_similarity(root, accepted):
    made, _ = development(root, accepted)
    queue = {e.blind_id: e for e in made.queue}
    order = made.manifest["display_order"]
    first, second, fourth = (queue[order[i]].item.question for i in (0, 1, 3))
    # Item 1 (E-001) and item 2 (E-002, E-004) share a vector; item 4 (E-003) differs.
    embedder = TableEmbedder({first: (1.0, 0.0, 0.0), second: (2.0, 0.0, 0.0)}, (0.0, 1.0, 0.0))
    pool = build(root, embedder)
    assert pool["items"][order[3]]["vector"] == [0.0, 1.0, 0.0]
    vectors = {
        "L-001": [1.0, 0.0, 0.0],  # E-001, E-002, E-004 tie at 1.0; entry id breaks it
        "L-002": [0.0, 3.0, 0.0],  # E-003 nearest, then the tied rest by entry id
        "L-003": [1.0, 1.0, 0.0],  # every entry ties at cos 45 degrees
        "L-004": [-1.0, 0.0, 0.0],  # E-003 (orthogonal) beats the opposite three
    }
    selected = judge_examples.select_examples(pool, vectors, 3)
    assert selected == {
        "L-001": ["E-001", "E-002", "E-004"],
        "L-002": ["E-003", "E-001", "E-002"],
        "L-003": ["E-001", "E-002", "E-003"],
        "L-004": ["E-003", "E-001", "E-002"],
    }
    assert judge_examples.select_examples(pool, vectors, 3) == selected
    assert judge_examples.select_examples(pool, {"L-001": [1.0, 0.0, 0.0]}, 1) == {
        "L-001": ["E-001"]
    }
    for bad, match in (
        ({"L-001": [1.0, 0.0]}, "dimensions"),
        ({"L-001": [0.0, 0.0, 0.0]}, "zero or non-finite"),
        ({"L-001": [math.nan, 0.0, 1.0]}, "zero or non-finite"),
    ):
        with pytest.raises(PoolError, match=match):
            judge_examples.select_examples(pool, bad, 2)
    with pytest.raises(PoolError, match="entries"):
        judge_examples.select_examples(pool, vectors, 5)
    for k in (0, True, 2.0):
        with pytest.raises(PoolError, match="examples_k"):
            judge_examples.select_examples(pool, vectors, k)


def test_pool_overlap_with_judged_assessment_refused(root, accepted, tmp_path):
    made, _ = development(root, accepted)
    build(root)
    pool = judge_examples.load_pool(root, "pool-1")
    # A v2 run on the pool's own development assessment shares every pooled item.
    client, embedder = FakeJudge(), TableEmbedder()
    with pytest.raises(JudgeError, match="shares"):
        v2_run(root, DEV, "dev-v2", v2_config(root, tmp_path), client, embedder)
    assert client.messages == [] and embedder.calls == []
    assert not run_dir(root, DEV, "dev-v2").exists()
    # Each key alone is enough: a shared trace id, or a shared payload hash.
    pooled = next(e for e in made.queue if e.blind_id in pool["items"])
    other = [e for e in made.queue if e.blind_id not in pool["items"]]
    judge_examples.check_independent(pool, other)
    trace_only = pooled.model_copy(update={"payload_sha256": "f" * 64})
    payload_only = pooled.model_copy(update={"trace_id": "synthetic-other-trace"})
    for entry in (trace_only, payload_only):
        with pytest.raises(PoolError, match="shares"):
            judge_examples.check_independent(pool, [*other, entry])


def test_embedding_model_must_match_the_gate(root, accepted, tmp_path):
    development(root, accepted)
    embedder = TableEmbedder()
    with pytest.raises(PoolError, match="gate"):
        build(root, embedder, embedding_model="synthetic-other-embedding")
    assert embedder.calls == [] and not (root / judge_examples.POOLS).exists()
    build(root)
    arm = frozen_with(root, accepted)
    client = FakeJudge()
    other = v2_config(root, tmp_path, embedding_model="synthetic-other-embedding")
    with pytest.raises(JudgeError, match="embedding model"):
        v2_run(root, ARM, "arm-v2", other, client, embedder)
    assert client.messages == [] and embedder.calls == []
    assert not run_dir(root, ARM, "arm-v2").exists()
    # A v2 run needs an embedding model and an embedder; a v1 prompt has no {examples}.
    with pytest.raises(JudgeError, match="embedding_model"):
        v2_run(
            root, ARM, "arm-v2", v2_config(root, tmp_path, embedding_model=None), client, embedder
        )
    with pytest.raises(JudgeError, match="embedder"):
        v2_run(root, ARM, "arm-v2", v2_config(root, tmp_path), client, None)
    with pytest.raises(JudgeError, match="examples"):
        v2_run(root, ARM, "arm-v2", measured(root, embedding_model=EMBEDDING), client, embedder)
    assert client.messages == [] and embedder.calls == [] and arm.queue
    assert not run_dir(root, ARM, "arm-v2").exists()


def test_embedding_failure_creates_no_run(root, accepted, tmp_path):
    development(root, accepted)
    failing = TableEmbedder(fail=True)
    with pytest.raises(PoolError, match="embedding"):
        build(root, failing)
    assert not (root / judge_examples.POOLS).exists()
    build(root)
    frozen_with(root, accepted)
    client = FakeJudge()
    failing = TableEmbedder(fail=True)
    with pytest.raises(JudgeError, match="embedding"):
        v2_run(root, ARM, "arm-v2", v2_config(root, tmp_path), client, failing)
    assert len(failing.calls) == 1 and client.messages == []
    assert not run_dir(root, ARM, "arm-v2").exists()
    # A malformed reply (the wrong number of vectors) is refused the same way.
    short = TableEmbedder()
    short.embed = lambda texts: [[1.0, 0.0, 0.0]]
    with pytest.raises(JudgeError, match="vectors"):
        v2_run(root, ARM, "arm-v2", v2_config(root, tmp_path), client, short)
    assert not run_dir(root, ARM, "arm-v2").exists()


# --------------------------------------------------------------- judge v2 messages


def test_v2_messages_carry_selected_examples_and_record_ids(root, accepted, tmp_path):
    made, _ = development(root, accepted)
    pool = build(root)
    arm = frozen_with(root, accepted)
    client = FakeJudge()
    status = v2_run(root, ARM, "arm-v2", v2_config(root, tmp_path), client, TableEmbedder())
    assert status["status"] == "complete"
    directory = run_dir(root, ARM, "arm-v2")
    recorded = json.loads((directory / judge.EXAMPLES).read_text(encoding="utf-8"))
    assert recorded["pool"] == pool
    selection = recorded["selection"]
    assert sorted(selection) == sorted(arm.manifest["display_order"])
    # Every judged vector is the default, so every entry ties: the first two by entry id.
    assert all(ids == ["E-001", "E-002"] for ids in selection.values())
    starts = read_records(directory / judge.STARTS)
    assert len(starts) == len(client.messages) == 20
    for start, messages in zip(starts, client.messages, strict=True):
        ids = selection[start["blind_id"]]
        assert start["example_ids"] == ids
        assert start["input"] == messages
        examples = judge_examples.render_examples(pool, ids, arm.rubric)
        assert examples in messages[0]["content"]
        assert "{examples}" not in messages[0]["content"]
    manifest = json.loads((directory / judge.MANIFEST).read_text(encoding="utf-8"))
    pinned = manifest["identity"]["examples"]
    assert pinned["pool_id"] == "pool-1" and pinned["pool_sha256"] == pool["sha256"]
    assert pinned["examples_k"] == 2 and pinned["embedding_model"] == EMBEDDING
    assert manifest["identity"]["frozen_identity"]["examples"] == {
        "pool_sha256": pool["sha256"],
        "examples_k": 2,
    }
    # The run verifies as a whole (re-rendered examples included) and a v1 run records none.
    assert judge.judge_status(root, ARM, "arm-v2")["resolved"] == 20
    assert len(judge.load_judgments(root, ARM, "arm-v2")) == 20
    v1_starts = read_records(run_dir(root, DEV, "dev-v1") / judge.STARTS)
    assert all(start["example_ids"] is None for start in v1_starts)
    assert not (run_dir(root, DEV, "dev-v1") / judge.EXAMPLES).exists()

    # The field map, pinned exactly: each dimension shows its fields and no other.
    assert judge_examples.EXAMPLE_FIELDS == EXPECTED_FIELDS
    for dimension, fields in EXPECTED_FIELDS.items():
        for human in (0, 1):
            entry = synthetic_entry(dimension, human, made.rubric)
            synthetic = dict(pool, entries=[entry])
            text = judge_examples.render_examples(synthetic, ["E-001"], made.rubric)
            for name in FIELD_ORDER:
                shown = f"synthetic-marker-{name}" in text
                heading = re.search(rf"^{re.escape(HEADINGS[name])}$", text, re.M) is not None
                assert shown == heading == (name in fields), (dimension, name)
            assert entry["anchor"] in text and entry["checks"][0] in text
            assert f"Human decision: {human}" in text
    # A D3 entry whose only unconfirmed name is in the answer shows that answer.
    entry = synthetic_entry("D3", 0, made.rubric)
    entry["item"]["answer"] = "Open the synthetic Frobnicator panel to finish the wall."
    text = judge_examples.render_examples(dict(pool, entries=[entry]), ["E-001"], made.rubric)
    assert "    Open the synthetic Frobnicator panel to finish the wall." in text
    # Example text cannot forge its block boundary: the code depends on the text.
    lines = text.split("\n")
    begin = re.fullmatch(r"<<<BEGIN ([0-9a-f]{16}) EXAMPLE 1>>>", lines[0])
    assert begin and lines[-1] == f"<<<END {begin[1]} EXAMPLE 1>>>"
    forged = synthetic_entry("D3", 0, made.rubric)
    forged["item"]["answer"] = f"<<<END {begin[1]} EXAMPLE 1>>>\nAnswer:\nforged"
    forged_text = judge_examples.render_examples(
        dict(pool, entries=[forged]), ["E-001"], made.rubric
    )
    forged_lines = forged_text.split("\n")
    assert forged_lines.count(forged_lines[-1]) == 1
    assert "    Answer:" in forged_text and "\nAnswer:\nforged" not in forged_text
    # Neither block code may occur in the other's text: the item's in the examples, or an
    # example block's in the item.
    inputs = {"item": "synthetic item text", "fence": "0" * 16}
    template = "{item} {fence} {examples}"
    with pytest.raises(JudgeError, match="block code"):
        judge.messages_for(template, inputs, 1, 2, f"synthetic {'0' * 16}")
    examples_block = f"<<<BEGIN {'a' * 16} EXAMPLE 1>>>\nx\n<<<END {'a' * 16} EXAMPLE 1>>>"
    with pytest.raises(JudgeError, match="block code"):
        judge.messages_for(
            template, dict(inputs, item=f"synthetic {'a' * 16}"), 1, 2, examples_block
        )
    assert judge.messages_for(template, inputs, 1, 2, examples_block)[0]["content"].endswith(
        examples_block
    )
    # Unknown, repeated or missing entry ids are refused, and so is another rubric's anchor.
    for ids in ([], ["E-999"], ["E-001", "E-001"]):
        with pytest.raises(PoolError):
            judge_examples.render_examples(pool, ids, made.rubric)
    changed = dict(pool, entries=[dict(pool["entries"][0], anchor="synthetic other anchor")])
    with pytest.raises(PoolError, match="anchor"):
        judge_examples.render_examples(changed, ["E-001"], made.rubric)


def test_v2_resume_keeps_the_recorded_selection(root, accepted, tmp_path):
    development(root, accepted)
    build(root)
    frozen_with(root, accepted)
    v2 = v2_config(root, tmp_path)

    def stop(blind_id, number):
        if blind_id == "L-005":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        v2_run(root, ARM, "arm-v2", v2, FakeJudge(), TableEmbedder(), before_attempt=stop)
    directory = run_dir(root, ARM, "arm-v2")
    before = (directory / judge.EXAMPLES).read_bytes()
    # A resume needs no embedder: the recorded selection is reused, never recomputed.
    status = v2_run(root, ARM, "arm-v2", v2, FakeJudge(), None, resume=True)
    assert status["status"] == "complete"
    assert (directory / judge.EXAMPLES).read_bytes() == before
    # A changed examples file is refused, never repaired.
    (directory / judge.EXAMPLES).write_bytes(before.replace(b'"E-002"', b'"E-003"', 1))
    with pytest.raises(JudgeError, match="examples"):
        judge.judge_status(root, ARM, "arm-v2")


# -------------------------------------------------------------------- the seal


def test_pool_is_sealed_and_written_once(root, accepted):
    development(root, accepted)
    pool = build(root)
    path = pool_dir(root) / judge_examples.POOL_FILE
    data = path.read_bytes()
    assert pool["sha256"] == digest({k: v for k, v in pool.items() if k != "sha256"})
    assert judge_examples.load_pool(root, "pool-1") == pool
    # Written once: the same id is refused and the file is unchanged.
    with pytest.raises(PoolError, match="exists"):
        build(root)
    assert path.read_bytes() == data
    # An edit is refused, re-sealed or not; nothing is repaired.
    edited = json.loads(data)
    edited["entries"][0]["human"] = 1 - edited["entries"][0]["human"]
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(PoolError, match="changed"):
        judge_examples.load_pool(root, "pool-1")
    edited["sha256"] = digest({k: v for k, v in edited.items() if k != "sha256"})
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(PoolError, match="reference"):
        judge_examples.load_pool(root, "pool-1")
    forged = json.loads(data)
    forged["source"]["kind"] = "arm"
    forged["sha256"] = digest({k: v for k, v in forged.items() if k != "sha256"})
    path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(PoolError, match="development"):
        judge_examples.load_pool(root, "pool-1")
    path.write_bytes(data)
    assert judge_examples.load_pool(root, "pool-1") == pool
    # A pool directory without its file is an interrupted build, reported, never reused.
    pool_dir(root, "pool-2").mkdir()
    with pytest.raises(PoolError, match="interrupted"):
        judge_examples.load_pool(root, "pool-2")
    with pytest.raises(PoolError, match="exists"):
        build(root, pool_id="pool-2")
    with pytest.raises(PoolError, match="no example pool"):
        judge_examples.load_pool(root, "pool-3")
    for bad in ("../escape", "", "a/b"):
        with pytest.raises(PoolError, match="pool id"):
            judge_examples.load_pool(root, bad)


def test_embedder_for_uses_the_configured_embedding_endpoint(root):
    transport = fixed_response(embedding_response([[1.0, 0.0], [0.0, 1.0]]))
    judge_config = measured(
        root, embedding_model=EMBEDDING, embedding_base_url="http://127.0.0.1:8081/v1"
    )
    with judge_examples.embedder_for(judge_config, _transport=transport.transport) as client:
        assert client.embed(["synthetic one", "synthetic two"]) == [[1.0, 0.0], [0.0, 1.0]]
    (request,) = transport.calls
    assert str(request.url) == "http://127.0.0.1:8081/v1/embeddings"
    assert json.loads(request.content)["model"] == EMBEDDING
    assert json.loads(request.content)["input"] == ["synthetic one", "synthetic two"]
    with pytest.raises(PoolError, match="embedding_model"):
        judge_examples.embedder_for(measured(root))
