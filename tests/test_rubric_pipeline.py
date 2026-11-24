"""The committed rubric and the B4 pipeline agree: the dimensions the deterministic checks
flag are the rubric's, and the collection and cohort sizes meet its retained minimum."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import get_args

from bonsai_help import checks, cli, cohort, collection, rubric
from bonsai_help.doc_sources import CATEGORIES

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
