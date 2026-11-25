"""Calibration and the frozen judge (B7 Task 5), on synthetic evidence under `tmp_path`.

No model endpoint is called. Every judge is a scripted fake returning synthetic
`AttemptResult`s; it recognises an item only by the question text in its blind message.
Every label is written through the library by "synthetic-reviewer" with a visibly synthetic
note, every reference is frozen from those synthetic labels, and every `chad_accepted`
rubric is a synthetic copy. No figure here is a measurement: these reports are fixtures.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from fractions import Fraction
from pathlib import Path

import pytest
from evaluation_support import SOURCES, fresh_root, write_rubric
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

from bonsai_help import acceptance, calibration, human_reference, judge, labels, stats
from bonsai_help.calibration import CalibrationError
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.evaluation_schemas import DIMENSIONS, Decisions, Judgment
from bonsai_help.judge_config import load_judge_prompt
from bonsai_help.model_client import AttemptResult

REPO = Path(__file__).resolve().parents[1]
CORRECTED = SOURCES["corrected"]
BASELINE2 = SOURCES["baseline2"]
REASON = "synthetic judge reason"
NOTE = "synthetic label note, not a real review"
DEV_LABELS = "dev-labels"


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


def decisions(**values) -> Decisions:
    return Decisions.model_validate({d: values.get(d, 1) for d in DIMENSIONS})


def judged(blind_id: str = "item", **values) -> Judgment:
    return Judgment.model_validate(
        {
            d: {"decision": values.get(d, 1), "reason": f"{REASON} {d} {blind_id}"}
            for d in DIMENSIONS
        }
    )


def reply(blind_id: str, model: str | None = JUDGE_MODEL, **values) -> AttemptResult:
    return AttemptResult(
        judged(blind_id, **values), {"synthetic": "judge reply"}, None, None, model
    )


def broken(blind_id: str) -> AttemptResult:
    return AttemptResult(None, "synthetic malformed reply", "synthetic invalid", "ValidationError")


def by_item(made, decide) -> FakeJudge:
    """A synthetic judge that finds the item by its question (the judge sees no id)."""
    questions = {entry.item.question: entry.blind_id for entry in made.queue}

    def script(number, messages):
        content = messages[0]["content"]
        found = [b for q, b in questions.items() if f"    {q}\n" in content]
        assert len(found) == 1, found
        attempt = int(re.search(r"attempt (\d+) of", messages[1]["content"])[1])
        return decide(found[0], attempt)

    return FakeJudge(script)


def agreeing(made) -> FakeJudge:
    return by_item(made, lambda blind_id, attempt: reply(blind_id))


def frozen_with(
    root, accepted, decide=None, *, assessment_id=ARM, cohorts=(BASELINE.cohort_id,), count=20
):
    """A synthetic assessment labeled by the synthetic reviewer and frozen."""
    made = create(root, accepted, assessment_id, list(cohorts), count)
    for entry in made.queue:
        values = decide(entry.blind_id) if decide else {}
        labels.record_label(
            made, entry.blind_id, decisions(**values), REVIEWER, rubric_path=accepted, notes=NOTE
        )
    human_reference.freeze_reference(made, REVIEWER, declare_blind=True, rubric_path=accepted)
    return made


def ids(n: int) -> list[str]:
    return [f"L-{i:03d}" for i in range(1, n + 1)]


def report(root, assessment_id, judge_run_id, report_id, **kwargs):
    return calibration.calibration_report(root, assessment_id, judge_run_id, report_id, **kwargs)


def report_paths(root, assessment_id, report_id) -> tuple[Path, Path]:
    directory = root / "assessments" / assessment_id / calibration.CALIBRATION
    return directory / f"{report_id}.json", directory / f"{report_id}.disagreements.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interval(count: int, n: int) -> list[float]:
    return list(stats.clopper_pearson(count, n))


def tamper_smoke_evidence(root) -> None:
    """Change the qualification's smoke run after the fact (a byte appended to a ledger)."""
    with (run_dir(root, SMOKE, "smoke-1") / judge.STARTS).open("a", encoding="utf-8") as stream:
        stream.write("\n")


def smoke_on_labeled(root, made, judge_run_id, judge_config, client) -> None:
    """Forge what the code forbids: a smoke run on a labeled assessment. The label files
    are moved aside while the smoke run is made, then restored byte for byte."""
    aside = root.parent / f"aside-{judge_run_id}"
    aside.mkdir()
    names = (labels.LEDGER, labels.CHECKPOINT, labels.REFERENCE)
    for name in names:
        shutil.move(made.directory / name, aside / name)
    try:
        judge.judge_run(root, made.manifest["assessment_id"], judge_run_id, judge_config, client)
    finally:
        for name in names:
            shutil.move(aside / name, made.directory / name)


@pytest.fixture
def arm(root, accepted):
    """A frozen 20-item arm assessment (every human decision 1) and a qualified judge."""
    made = frozen_with(root, accepted)
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    return made, judge_config


def run(root, made, run_id, judge_config, client, **kwargs):
    return judge.judge_run(
        root,
        made.manifest["assessment_id"],
        run_id,
        judge_config,
        client,
        qualification_id="q-1",
        **kwargs,
    )


# ------------------------------------------------------------------- agreement


def test_agreement_counts_and_confusion():
    blind = ids(8)
    d1_human = [1, 1, 1, 0, 0, None, 1, 0]
    d1_judge = [1, 0, 1, 0, 1, 1, None, 0]
    human = {b: decisions(D1=h) for b, h in zip(blind, d1_human, strict=True)}
    judge_side = {b: judged(b, D1=j) for b, j in zip(blind, d1_judge, strict=True) if j is not None}
    result = calibration.agreement(blind, human, judge_side)
    assert result["n"] == 8
    d1 = result["dimensions"]["D1"]
    assert d1["n"] == 8 and d1["matching"] == 4 and d1["agreement"] == 0.5
    assert d1["human_unresolved"] == 1 and d1["judge_missing"] == 1
    assert d1["confusion"] == {"h1_j1": 2, "h1_j0": 1, "h0_j1": 1, "h0_j0": 2}
    assert d1["interval"] == interval(4, 8)
    d2 = result["dimensions"]["D2"]
    assert d2["matching"] == 7 and d2["judge_missing"] == 1 and d2["human_unresolved"] == 0
    assert d2["confusion"] == {"h1_j1": 7, "h1_j0": 0, "h0_j1": 0, "h0_j0": 0}
    # Only resolved pairs that differ are disagreements, each with the judge's reason.
    assert result["disagreements"] == [
        {
            "blind_id": "L-002",
            "dimension": "D1",
            "human": 1,
            "judge": 0,
            "judge_reason": f"{REASON} D1 L-002",
        },
        {
            "blind_id": "L-005",
            "dimension": "D1",
            "human": 0,
            "judge": 1,
            "judge_reason": f"{REASON} D1 L-005",
        },
    ]
    with pytest.raises(ValueError, match="outside the selection"):
        calibration.agreement(blind[:-1], human, judge_side)
    with pytest.raises(ValueError, match="distinct"):
        calibration.agreement(blind + blind[:1], human, judge_side)
    with pytest.raises(ValueError, match="Decisions"):
        calibration.agreement(blind, {"L-001": {"D1": 1}}, {})
    with pytest.raises(ValueError, match="Judgment"):
        calibration.agreement(blind, {}, {"L-001": {"D1": {"decision": 1}}})
    # A blind id with no human decisions at all is unresolved in every dimension.
    empty = calibration.agreement(["L-001"], {}, {"L-001": judged("L-001")})
    assert empty["dimensions"]["D1"]["human_unresolved"] == 1
    assert empty["dimensions"]["D1"]["matching"] == 0


def _row(n: int, matching: int) -> dict:
    blind = ids(n)
    human = {b: decisions() for b in blind}
    judge_side = {b: judged(b, D4=1 if i < matching else 0) for i, b in enumerate(blind)}
    return calibration.agreement(blind, human, judge_side)["dimensions"]


def test_exact_80_percent_boundary(root, accepted):
    made = frozen_with(root, accepted, count=30)
    rubric = made.rubric
    for n, matching, met in ((30, 24, True), (30, 23, False), (20, 16, True)):
        dimensions = _row(n, matching)
        assert dimensions["D4"]["matching"] == matching and dimensions["D4"]["n"] == n
        result = acceptance.acceptance_result(dimensions, rubric)
        assert result["threshold_met"] is met
        assert result["failing_dimensions"] == ([] if met else ["D4"])

    # End to end on a 30-item arm: 24 of 30 is ready, 23 of 30 is pending.
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    order = made.manifest["display_order"]
    for run_id, wrong in (("meets", 6), ("misses", 7)):
        failed = set(order[:wrong])
        client = by_item(
            made, lambda b, attempt, failed=failed: reply(b, D3=0 if b in failed else 1)
        )
        assert run(root, made, run_id, judge_config, client)["status"] == "complete"
    met = report(root, ARM, "meets", "r-meets")
    assert met["status"] == "ready" and met["reasons"] == []
    d3 = met["dimensions"]["D3"]
    assert (d3["matching"], d3["n"], d3["meets_minimum"]) == (24, 30, True)
    assert d3["interval"] == interval(24, 30)
    missed = report(root, ARM, "misses", "r-misses")
    assert missed["status"] == "pending"
    assert missed["dimensions"]["D3"]["matching"] == 23
    assert missed["dimensions"]["D3"]["meets_minimum"] is False
    assert any("D3" in reason and "minimum" in reason for reason in missed["reasons"])
    assert missed["acceptance"]["failing_dimensions"] == ["D3"]


def test_unresolved_or_missing_counts_against_agreement(root, accepted):
    unresolved = set(ids(4))
    made = frozen_with(root, accepted, lambda b: {"D2": None} if b in unresolved else {})
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    last = made.manifest["display_order"][-1]
    client = by_item(made, lambda b, attempt: broken(b) if b == last else reply(b))
    assert run(root, made, "v1", judge_config, client)["status"] == "incomplete"
    result = report(root, ARM, "v1", "r-1")
    d2 = result["dimensions"]["D2"]
    # 4 unresolved human decisions and 1 missing judgment: in n, never matching.
    assert (d2["n"], d2["matching"], d2["human_unresolved"], d2["judge_missing"]) == (20, 15, 4, 1)
    assert d2["agreement"] == 0.75 and d2["meets_minimum"] is False
    d1 = result["dimensions"]["D1"]
    assert (d1["n"], d1["matching"], d1["judge_missing"]) == (20, 19, 1)
    assert d1["confusion"] == {"h1_j1": 19, "h1_j0": 0, "h0_j1": 0, "h0_j0": 0}
    assert result["status"] == "pending"
    assert any("incomplete" in reason for reason in result["reasons"])
    assert any("D2" in reason and "minimum" in reason for reason in result["reasons"])
    assert result["judged"] == 19 and result["population"] == 20
    # An unresolved human decision is never a disagreement either.
    side = json.loads(report_paths(root, ARM, "r-1")[1].read_text(encoding="utf-8"))
    assert side == []


def test_tpr_tnr_and_intervals():
    blind = ids(10)
    human = {b: decisions(D1=1 if i < 6 else 0, D4=0) for i, b in enumerate(blind)}
    d1_judge = [1, 1, 1, 1, 0, 0, 0, 0, 0, 1]
    judge_side = {b: judged(b, D1=j, D4=0) for b, j in zip(blind, d1_judge, strict=True)}
    result = calibration.agreement(blind, human, judge_side)
    d1 = result["dimensions"]["D1"]
    assert d1["tpr"] == {"count": 4, "n": 6, "value": 4 / 6, "interval": interval(4, 6)}
    assert d1["tnr"] == {"count": 3, "n": 4, "value": 3 / 4, "interval": interval(3, 4)}
    assert d1["matching"] == 7 and d1["interval"] == interval(7, 10)
    # Every human decision 1: no failed item, so TNR is undefined (null), never 0 or 1.
    d2 = result["dimensions"]["D2"]
    assert d2["tnr"] == {"count": 0, "n": 0, "value": None, "interval": None}
    assert d2["tpr"]["value"] == 1.0 and d2["tpr"]["interval"] == interval(10, 10)
    # Every human decision 0: TPR is undefined.
    d4 = result["dimensions"]["D4"]
    assert d4["tpr"] == {"count": 0, "n": 0, "value": None, "interval": None}
    assert d4["tnr"]["count"] == 10
    # No items at all: agreement is undefined too.
    none = calibration.agreement([], {}, {})["dimensions"]["D1"]
    assert none["n"] == 0 and none["agreement"] is None and none["interval"] is None
    # A confidence other than 0.95 is passed through to the interval.
    wide = calibration.agreement(blind, human, judge_side, confidence=Fraction(99, 100))
    assert wide["dimensions"]["D1"]["interval"] == list(stats.clopper_pearson(7, 10, 0.99))


# ------------------------------------------------------------------- readiness


def test_diagnostic_agreement_never_certifies(root, accepted):
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    # A smoke run on an unlabeled development assessment: no reference, no figures.
    smoke = report(root, SMOKE, "smoke-1", "r-smoke")
    assert smoke["status"] == "diagnostic" and smoke["dimensions"] is None
    assert any("smoke" in reason for reason in smoke["reasons"])
    assert any("human reference" in reason for reason in smoke["reasons"])

    dev = frozen_with(root, accepted, assessment_id=DEV_LABELS, cohorts=(DEVELOPMENT.cohort_id,))
    # (a) A measured run with perfect agreement on a development assessment.
    assert run(root, dev, "dev-v1", judge_config, agreeing(dev))["status"] == "complete"
    # (b) A smoke run with perfect agreement, forged onto the labeled assessment.
    smoke_on_labeled(root, dev, "dev-smoke", config(root), agreeing(dev))
    # (c) A same-model smoke judge with perfect agreement.
    same = config(
        root,
        model=DEVELOPMENT.model,
        model_identity=DEVELOPMENT.model_identity,
        model_sha256=DEVELOPMENT.model_sha256,
    )
    same_client = by_item(dev, lambda b, attempt: reply(b, model=DEVELOPMENT.model))
    smoke_on_labeled(root, dev, "dev-same", same, same_client)

    expected = {
        "dev-v1": ["development"],
        "dev-smoke": ["development", "smoke"],
        "dev-same": ["development", "smoke", "same model"],
    }
    for run_id, words in expected.items():
        result = report(root, DEV_LABELS, run_id, f"r-{run_id}")
        assert result["status"] == "diagnostic", run_id
        for d in DIMENSIONS:
            row = result["dimensions"][d]
            assert row["matching"] == row["n"] == 20 and row["agreement"] == 1.0
        assert result["acceptance"]["threshold_met"] is True  # perfect, still not ready
        for word in words:
            assert any(word in reason for reason in result["reasons"]), (run_id, word)
        lines = calibration.report_lines(result)
        assert lines[0] == "status: diagnostic (never calibration)"
        with pytest.raises(CalibrationError, match="ready"):
            calibration.freeze_judge(root, DEV_LABELS, f"r-{run_id}", f"sel-{run_id}")
    with pytest.raises(CalibrationError, match="ready"):
        calibration.freeze_judge(root, SMOKE, "r-smoke", "sel-smoke")
    assert not (root / calibration.SELECTIONS).exists()


def test_readiness_requires_frozen_reference_complete_run_and_qualification(arm, root):
    made, judge_config = arm
    assert run(root, made, "v1", judge_config, agreeing(made))["status"] == "complete"
    ready = report(root, ARM, "v1", "r-ready")
    assert ready["status"] == "ready" and ready["reasons"] == []
    assert calibration.report_lines(ready)[0] == "status: ready"

    # An item with no valid judgment: the run is incomplete.
    last = made.manifest["display_order"][-1]
    client = by_item(made, lambda b, attempt: broken(b) if b == last else reply(b))
    assert run(root, made, "v1-gap", judge_config, client)["status"] == "incomplete"
    gap = report(root, ARM, "v1-gap", "r-gap")
    assert gap["status"] == "pending"
    assert any("incomplete" in reason for reason in gap["reasons"])

    # The qualification's smoke evidence changes after the run: no longer valid.
    tamper_smoke_evidence(root)
    unqualified = report(root, ARM, "v1", "r-unqualified")
    assert unqualified["status"] == "pending"
    assert any("qualification" in reason for reason in unqualified["reasons"])
    assert unqualified["dimensions"] == ready["dimensions"]

    # Without the frozen reference, a measured run cannot be verified: refused, unwritten.
    reference = made.directory / labels.REFERENCE
    reference.rename(made.directory / "reference-aside.json")
    with pytest.raises(CalibrationError, match="frozen human reference"):
        report(root, ARM, "v1", "r-no-reference")
    assert not report_paths(root, ARM, "r-no-reference")[0].exists()
    assert not report_paths(root, ARM, "r-no-reference")[1].exists()


def test_post_review_amendments_do_not_change_agreement(arm, root, accepted):
    made, judge_config = arm
    run(root, made, "v1", judge_config, agreeing(made))
    before = report(root, ARM, "v1", "r-before")
    first = made.manifest["display_order"][0]
    current = labels.load_labels(made)[first]
    labels.record_label(
        made,
        first,
        decisions(D1=0, D2=0),
        REVIEWER,
        rubric_path=accepted,
        notes="synthetic post-review amendment",
        supersedes=current.label_id,
    )
    amended = labels.load_labels(made)[first]
    assert amended.review_stage == "post_review" and amended.decisions.D1 == 0
    after = report(root, ARM, "v1", "r-after")
    assert after["dimensions"] == before["dimensions"]
    assert after["pins"]["reference_sha256"] == before["pins"]["reference_sha256"]
    assert after["status"] == before["status"] == "ready"


def test_generator_alias_reply_blocks_readiness(arm, root):
    made, judge_config = arm
    alias = made.manifest["display_order"][2]

    def decide(blind_id, attempt):
        if blind_id == alias and attempt == 1:
            return reply(blind_id, model=BASELINE.model)  # the generator's id
        return reply(blind_id)

    assert run(root, made, "v1", judge_config, by_item(made, decide))["status"] == "complete"
    result = report(root, ARM, "v1", "r-alias")
    assert result["status"] == "pending"
    assert all(result["dimensions"][d]["matching"] == 20 for d in DIMENSIONS)
    assert any("source generator" in reason for reason in result["reasons"])
    assert BASELINE.model in result["reported_models"]
    # The printed lines name no model id.
    assert BASELINE.model not in "\n".join(calibration.report_lines(result))


def test_category_segments_reported_without_threshold(root, accepted):
    made = frozen_with(
        root, accepted, assessment_id="mixed", cohorts=(BASELINE.cohort_id, CORRECTED.cohort_id)
    )
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    category = made.queue[0].category
    members = [e.blind_id for e in made.queue if e.category == category]
    wrong = set(members[: math.ceil(len(members) / 2) + 1])
    client = by_item(made, lambda b, attempt: reply(b, D6=0 if b in wrong else 1))
    assert run(root, made, "v1", judge_config, client)["status"] == "complete"
    result = report(root, "mixed", "v1", "r-1")
    assert list(result["categories"]) == list(CATEGORIES)
    assert sum(rows["D1"]["n"] for rows in result["categories"].values()) == 40
    segment = result["categories"][category]["D6"]
    assert segment["n"] == len(members) and segment["matching"] == len(members) - len(wrong)
    assert segment["matching"] / segment["n"] < 0.8
    for rows in result["categories"].values():
        for row in rows.values():
            assert "meets_minimum" not in row
    # The overall D6 still meets the minimum; a category below it is no reason.
    assert result["dimensions"]["D6"]["meets_minimum"] is True
    assert result["status"] == "ready" and result["reasons"] == []
    # Per-arm figures come from the key.
    assert sorted(result["arms"]) == ["baseline", "corrected"]
    assert result["arms"]["baseline"]["D1"]["n"] == result["arms"]["corrected"]["D1"]["n"] == 20


def test_unknown_outcome_disclosed_without_blocking_readiness(arm, root):
    made, judge_config = arm
    second = made.manifest["display_order"][1]

    def killed(blind_id, attempt):
        if blind_id == second:
            raise KeyboardInterrupt  # a hard stop after the start record, before any reply
        return reply(blind_id)

    with pytest.raises(KeyboardInterrupt):
        run(root, made, "u-1", judge_config, by_item(made, killed))
    resumed = run(root, made, "u-1", judge_config, agreeing(made), resume=True)
    assert resumed["status"] == "complete"
    result = report(root, ARM, "u-1", "r-u1")
    assert result["status"] == "ready" and result["reasons"] == []
    assert result["unknown_outcomes"] == {"count": 1, "attempt_ids": [f"u-1:{second}:1"]}
    assert any(f"u-1:{second}:1" in line for line in calibration.report_lines(result))

    # The unknown outcome used the first attempt, and the second fails: exhausted.
    with pytest.raises(KeyboardInterrupt):
        run(root, made, "u-2", judge_config, by_item(made, killed))
    failing = by_item(made, lambda b, attempt: broken(b) if b == second else reply(b))
    assert run(root, made, "u-2", judge_config, failing, resume=True)["status"] == "incomplete"
    exhausted = report(root, ARM, "u-2", "r-u2")
    assert exhausted["status"] == "pending"
    assert exhausted["unknown_outcomes"] == {"count": 1, "attempt_ids": [f"u-2:{second}:1"]}
    d1 = exhausted["dimensions"]["D1"]
    assert (d1["n"], d1["matching"], d1["judge_missing"]) == (20, 19, 1)


# --------------------------------------------------------------- report files


def test_disagreements_written_to_separate_file(root, accepted):
    human_fails = set(ids(3))
    made = frozen_with(root, accepted, lambda b: {"D2": 0} if b in human_fails else {})
    judge_config = measured(root)
    qualify(root, accepted, judge_config)
    client = by_item(made, lambda b, attempt: reply(b, D5=0 if b == "L-004" else 1))
    run(root, made, "v1", judge_config, client)
    result = report(root, ARM, "v1", "r-1")
    assert result["status"] == "ready"
    main, side = report_paths(root, ARM, "r-1")
    text = main.read_text(encoding="utf-8")
    assert REASON not in text and NOTE not in text
    assert not [b for b in made.manifest["display_order"] if b in text]
    assert result["pins"]["disagreements_sha256"] == sha(side)
    entries = json.loads(side.read_text(encoding="utf-8"))
    assert entries == [
        {
            "blind_id": b,
            "dimension": "D2",
            "human": 0,
            "judge": 1,
            "judge_reason": f"{REASON} D2 {b}",
        }
        for b in ids(3)
    ] + [
        {
            "blind_id": "L-004",
            "dimension": "D5",
            "human": 1,
            "judge": 0,
            "judge_reason": f"{REASON} D5 L-004",
        }
    ]
    printed = "\n".join(calibration.report_lines(result))
    assert REASON not in printed
    assert not [b for b in made.manifest["display_order"] if b in printed]
    assert calibration.load_report(root, ARM, "r-1") == result

    original = side.read_bytes()
    side.write_bytes(original.replace(b"L-004", b"L-005"))
    with pytest.raises(CalibrationError, match="disagreements"):
        calibration.load_report(root, ARM, "r-1")
    side.write_bytes(original)
    main.write_text(text.replace('"ready"', '"pending"', 1), encoding="utf-8")
    with pytest.raises(CalibrationError, match="changed"):
        calibration.load_report(root, ARM, "r-1")


def test_report_is_written_once(arm, root):
    made, judge_config = arm
    run(root, made, "v1", judge_config, agreeing(made))
    report(root, ARM, "v1", "r-1")
    main, side = report_paths(root, ARM, "r-1")
    hashes = (sha(main), sha(side))
    with pytest.raises(CalibrationError, match="already exists"):
        report(root, ARM, "v1", "r-1")
    assert (sha(main), sha(side)) == hashes
    # A preview writes nothing.
    preview = report(root, ARM, "v1", "r-preview", write=False)
    assert preview["status"] == "ready"
    assert not any(p.exists() for p in report_paths(root, ARM, "r-preview"))
    # A leftover disagreements file (an interrupted write) is never overwritten.
    _, stray = report_paths(root, ARM, "r-2")
    shutil.copy2(side, stray)
    with pytest.raises(CalibrationError, match="already exists"):
        report(root, ARM, "v1", "r-2")
    assert not report_paths(root, ARM, "r-2")[0].exists()
    with pytest.raises(CalibrationError, match="report id"):
        report(root, ARM, "v1", "../escape")


def test_freeze_judge_requires_ready_report_and_pins_identity(arm, root, accepted, tmp_path):
    made, judge_config = arm
    run(root, made, "v1", judge_config, agreeing(made))
    last = made.manifest["display_order"][-1]
    gap = by_item(made, lambda b, attempt: broken(b) if b == last else reply(b))
    run(root, made, "v1-gap", judge_config, gap)
    ready = report(root, ARM, "v1", "r-ready")
    pending = report(root, ARM, "v1-gap", "r-pending")
    assert (ready["status"], pending["status"]) == ("ready", "pending")
    with pytest.raises(CalibrationError, match="ready"):
        calibration.freeze_judge(root, ARM, "r-pending", "sel-pending")

    selection = calibration.freeze_judge(root, ARM, "r-ready", "sel-1")
    prompt = load_judge_prompt(judge_config, with_examples=False)
    assert selection["frozen_identity"] == judge.frozen_identity(judge_config, prompt)
    main, _ = report_paths(root, ARM, "r-ready")
    assert selection["report_sha256"] == sha(main)
    assert (selection["assessment_id"], selection["judge_run_id"]) == (ARM, "v1")
    assert selection["prompt_version"] == "judge-v1"
    path = root / calibration.SELECTIONS / "sel-1.json"
    assert json.loads(path.read_text(encoding="utf-8")) == selection
    assert calibration.load_selection(root, "sel-1") == selection
    with pytest.raises(CalibrationError, match="already exists"):
        calibration.freeze_judge(root, ARM, "r-ready", "sel-1")

    # B8's measured run must match the frozen identity exactly.
    other = frozen_with(root, accepted, assessment_id="arm-2", cohorts=(BASELINE2.cohort_id,))
    frozen = selection["frozen_identity"]
    status = run(root, other, "b8-v1", judge_config, agreeing(other), frozen_judge=frozen)
    assert status["status"] == "complete"
    changed_prompt = tmp_path / "judge-v1.md"
    changed_prompt.write_text(
        (REPO / "prompts/judge-v1.md").read_text(encoding="utf-8") + "\nsynthetic change\n",
        encoding="utf-8",
    )
    changed = judge_config.model_copy(update={"prompt_path": str(changed_prompt)})
    with pytest.raises(judge.JudgeError, match="not the frozen judge"):
        run(root, other, "b8-v1b", changed, agreeing(other), frozen_judge=frozen)

    # A tampered selection is refused on load.
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace('"judge-v1"', '"judge-v2"', 1), encoding="utf-8")
    with pytest.raises(CalibrationError, match="changed"):
        calibration.load_selection(root, "sel-1")
    path.write_text(original, encoding="utf-8")

    # Evidence that changed after the report: the freeze re-checks it and refuses.
    tamper_smoke_evidence(root)
    with pytest.raises(CalibrationError, match="changed since"):
        calibration.freeze_judge(root, ARM, "r-ready", "sel-2")
    assert not (root / calibration.SELECTIONS / "sel-2.json").exists()
