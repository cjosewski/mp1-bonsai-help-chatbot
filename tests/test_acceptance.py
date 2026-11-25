"""The course acceptance policy: every dimension must reach the rubric's agreement minimum."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bonsai_help import acceptance, rubric
from bonsai_help.acceptance import COURSE_POLICY, acceptance_result

REPO = Path(__file__).resolve().parents[1]
COMMITTED = REPO / "config" / "rubric.json"
RESULT_KEYS = {"policy", "policy_sha256", "threshold_met", "failing_dimensions"}


@pytest.fixture(scope="module")
def course_rubric() -> rubric.Rubric:
    return rubric.load_rubric(COMMITTED)


def rows(counts: dict[str, tuple[int, int]]) -> dict[str, dict]:
    """Per-dimension figures in calibration's shape: `matching` of `n`, plus other fields
    the policy must ignore."""
    return {
        dimension: {"matching": matching, "n": n, "human_unresolved": 0, "judge_missing": 0}
        for dimension, (matching, n) in counts.items()
    }


def uniform(matching: int, n: int) -> dict[str, dict]:
    return rows({dimension: (matching, n) for dimension in rubric.DIMENSION_IDS})


def test_each_dimension_required_despite_high_overall(course_rubric):
    counts = {dimension: (100, 100) for dimension in rubric.DIMENSION_IDS}
    counts["D4"] = (79, 100)
    result = acceptance_result(rows(counts), course_rubric)
    assert set(result) == RESULT_KEYS
    # 579 of 600 overall is 96.5%, yet one dimension below the minimum fails the policy.
    assert result["threshold_met"] is False
    assert result["failing_dimensions"] == ["D4"]

    counts["D4"] = (80, 100)
    passed = acceptance_result(rows(counts), course_rubric)
    assert passed["threshold_met"] is True
    assert passed["failing_dimensions"] == []


@pytest.mark.parametrize(
    ("matching", "n", "met"),
    [(24, 30, True), (23, 30, False), (16, 20, True), (15, 20, False), (4, 5, True)],
)
def test_minimum_is_inclusive_and_exact(course_rubric, matching, n, met):
    result = acceptance_result(uniform(matching, n), course_rubric)
    assert result["threshold_met"] is met
    assert result["failing_dimensions"] == ([] if met else list(rubric.DIMENSION_IDS))


def test_failing_dimensions_follow_rubric_order(course_rubric):
    counts = {dimension: (30, 30) for dimension in rubric.DIMENSION_IDS}
    counts["D6"] = (0, 30)
    counts["D2"] = (23, 30)
    result = acceptance_result(dict(reversed(rows(counts).items())), course_rubric)
    assert result["failing_dimensions"] == ["D2", "D6"]


def test_empty_or_unknown_policy_cannot_pass(course_rubric):
    empty = acceptance_result({}, course_rubric)
    assert empty["threshold_met"] is False
    assert empty["failing_dimensions"] == list(rubric.DIMENSION_IDS)

    # A dimension with no compared items has undefined agreement, which is never a pass.
    no_items = acceptance_result(uniform(0, 0), course_rubric)
    assert no_items["threshold_met"] is False
    assert no_items["failing_dimensions"] == list(rubric.DIMENSION_IDS)

    # A dimension left out of the figures fails; perfect figures elsewhere do not help.
    partial = uniform(30, 30)
    del partial["D3"]
    missing = acceptance_result(partial, course_rubric)
    assert missing["threshold_met"] is False
    assert missing["failing_dimensions"] == ["D3"]

    for policy_id in ("", "arbitrary-policy", "course-per-dimension-80-v2", COURSE_POLICY.upper()):
        with pytest.raises(ValueError, match="unknown acceptance policy"):
            acceptance_result(uniform(30, 30), course_rubric, policy_id)


@pytest.mark.parametrize(
    "bad",
    [
        {"D7": {"matching": 30, "n": 30}},
        {"D1": {"n": 30}},
        {"D1": {"matching": 30}},
        {"D1": {"matching": 31, "n": 30}},
        {"D1": {"matching": -1, "n": 30}},
        {"D1": {"matching": True, "n": 1}},
        {"D1": {"matching": 24.0, "n": 30}},
        {"D1": {"matching": "24", "n": 30}},
        {"D1": "24/30"},
    ],
)
def test_malformed_figures_are_refused(course_rubric, bad):
    figures = uniform(30, 30)
    figures.update(bad)
    with pytest.raises(ValueError):
        acceptance_result(figures, course_rubric)


def test_minimum_is_read_from_the_rubric(course_rubric, tmp_path):
    document = json.loads(COMMITTED.read_text(encoding="utf-8"))
    document["thresholds"]["human_judge_agreement"]["per_dimension_minimum"] = 0.7
    path = tmp_path / "rubric.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.raises(rubric.RubricError, match="per_dimension_minimum"):
        rubric.load_rubric(path)

    # The course value stands, and the policy records the rubric's own figure.
    result = acceptance_result(uniform(24, 30), course_rubric)
    minimum = course_rubric.thresholds.human_judge_agreement.per_dimension_minimum
    assert result["policy"]["minimum"] == minimum == 0.8
    assert result["policy"]["dimensions"] == list(rubric.dimension_ids(course_rubric))

    # A rubric object built past `load_rubric`'s check cannot move the course policy either.
    lowered = course_rubric.model_copy(
        update={
            "thresholds": course_rubric.thresholds.model_copy(
                update={
                    "human_judge_agreement": course_rubric.thresholds.human_judge_agreement.model_copy(
                        update={"per_dimension_minimum": 0.7}
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="differs from the course criterion"):
        acceptance_result(uniform(22, 30), lowered)


def test_policy_names_no_owner_and_is_pinned(course_rubric):
    first = acceptance_result(uniform(24, 30), course_rubric)
    second = acceptance_result(uniform(30, 30), course_rubric)
    policy = first["policy"]
    assert policy["id"] == COURSE_POLICY
    assert first["policy"] == second["policy"]
    assert first["policy_sha256"] == second["policy_sha256"]
    assert len(first["policy_sha256"]) == 64
    text = json.dumps(first).lower()
    for word in ("owner", "amendment", "authority", "chad", "approved"):
        assert word not in text
    assert acceptance.POLICIES == (COURSE_POLICY,)
