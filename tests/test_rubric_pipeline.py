"""The committed rubric and the pipeline agree: the dimensions the deterministic checks
flag are the rubric's, the collection and cohort sizes meet its retained minimum, and the
B7 judge runs below the generator, scores the rubric's dimensions and is held to the
rubric's per-dimension agreement minimum."""

from __future__ import annotations

import inspect
import math
from fractions import Fraction
from pathlib import Path
from typing import get_args

import pytest

from bonsai_help import acceptance, calibration, checks, cli, cohort, collection, judge, rubric
from bonsai_help.config import RunConfig, load_config
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.evaluation_schemas import DIMENSIONS, Decisions, Judgment
from bonsai_help.judge_config import JudgeConfig, load_judge_config

REPO = Path(__file__).resolve().parents[1]
COMMITTED = rubric.load_rubric(REPO / rubric.RUBRIC)


def test_checks_flag_exactly_the_rubric_dimensions():
    assert tuple(get_args(checks.Dimension)) == rubric.dimension_ids(COMMITTED)


def test_collection_defaults_reach_the_rubric_retained_minimum():
    minimum = COMMITTED.thresholds.retained_items.minimum_per_run
    default = inspect.signature(collection.collect).parameters["target_retained"].default
    assert default == minimum
    args = cli._parser().parse_args(["collect", "--config", "run.json", "--collection-id", "c"])
    assert args.target_retained == minimum
    assert collection.policy(args.target_retained, 70, 3)["target_retained"] == minimum


def test_a_frozen_cohort_holds_at_least_the_rubric_retained_minimum():
    size = cohort.PER_CATEGORY * len(CATEGORIES)
    assert size >= COMMITTED.thresholds.retained_items.minimum_per_run
    assert collection.MIN_PER_CATEGORY >= cohort.PER_CATEGORY


# ------------------------------------------------------------- B7 judge drift


def test_judge_default_temperature_below_generator_default():
    """The judge's defaults and committed example run below the generator's, and a judge at
    its default temperature is accepted for a generator at its default, never the reverse."""
    judge_default = JudgeConfig.model_fields["temperature"].default
    generator_default = RunConfig.model_fields["temperature"].default
    assert judge_default < generator_default
    judge_example = load_judge_config(REPO / "config" / "judge.example.json")
    generator_example = load_config(REPO / "config" / "run.example.json")
    assert judge_example.temperature < generator_example.temperature
    assert judge_example.temperature == judge_default
    judge._check_generators(judge_example, [{"temperature": generator_default}])
    with pytest.raises(judge.JudgeError, match="below every source generator"):
        judge._check_generators(judge_example, [{"temperature": judge_default}])


def _figures(n: int, matching: int) -> dict:
    """Agreement figures for `n` synthetic items where D1 matches on `matching` of them."""
    blind_ids = [f"synthetic-blind-{i:02d}" for i in range(n)]
    decisions = {b: Decisions.model_validate(dict.fromkeys(DIMENSIONS, 1)) for b in blind_ids}
    judgments = {
        b: Judgment.model_validate(
            {
                d: {"decision": int(d != "D1" or i < matching), "reason": "synthetic reason"}
                for d in DIMENSIONS
            }
        )
        for i, b in enumerate(blind_ids)
    }
    return calibration.agreement(blind_ids, decisions, judgments)["dimensions"]


def test_agreement_minimum_is_the_rubric_minimum():
    """The acceptance policy reads its minimum from the committed rubric, and the boundary
    it applies is that minimum, exactly: the fewest matches reaching it meet, one fewer not."""
    minimum = COMMITTED.thresholds.human_judge_agreement.per_dimension_minimum
    assert minimum == rubric.COURSE_THRESHOLDS[("human_judge_agreement", "per_dimension_minimum")]
    exact = Fraction(repr(minimum))
    for n in (20, 25, 30):
        fewest = math.ceil(exact * n)
        met = acceptance.acceptance_result(_figures(n, fewest), COMMITTED)
        assert met["policy"]["minimum"] == minimum
        assert met["threshold_met"] is True
        short = acceptance.acceptance_result(_figures(n, fewest - 1), COMMITTED)
        assert short["threshold_met"] is False
        assert short["failing_dimensions"] == ["D1"]


def test_judgment_dimensions_are_the_rubric_dimensions():
    """The judge's response model, the human decisions, calibration and the acceptance
    policy all use exactly the committed rubric's dimensions, in its order."""
    ids = rubric.dimension_ids(COMMITTED)
    assert tuple(Judgment.model_fields) == ids
    assert tuple(Decisions.model_fields) == ids
    assert DIMENSIONS == ids
    schema = Judgment.model_json_schema()
    assert tuple(schema["properties"]) == ids
    assert tuple(schema["required"]) == ids
    assert tuple(_figures(5, 5)) == ids
    policy = acceptance.acceptance_result(_figures(5, 5), COMMITTED)["policy"]
    assert tuple(policy["dimensions"]) == ids
