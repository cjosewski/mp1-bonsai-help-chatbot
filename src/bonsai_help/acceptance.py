"""The acceptance policy for human/judge agreement, kept separate from the rubric.

There is one policy, `COURSE_POLICY`: the course criterion that every dimension's
human/judge agreement reaches the rubric's `thresholds.human_judge_agreement.
per_dimension_minimum` (0.8, inclusive, Phase A before Phase B). A high overall agreement
never makes up for one dimension below the minimum.

The minimum and the dimension ids are read from the pinned rubric, never typed here. A
rubric whose minimum differs from the course criterion is refused, by `rubric.load_rubric`
and again here, so a rubric object built past that check cannot move the policy. Each
dimension is compared exactly, as the fraction `matching / n` against the rubric's decimal
minimum (0.8 is 4/5): 24 of 30 meets it and 23 of 30 does not. A dimension with no items,
or one missing from the figures, has no agreement and fails. Unresolved human decisions
and missing judge decisions are in `n` and never in `matching`; calibration counts them so.

The result names no owner, approval or amendment. A later change to the policy is a dated
entry in `docs/DECISIONS.md` plus a new policy id.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

from bonsai_help import rubric as rubric_module
from bonsai_help.rubric import Rubric
from bonsai_help.tracing import digest

COURSE_POLICY = "course-per-dimension-80-v1"
POLICIES = (COURSE_POLICY,)
_COURSE_MINIMUM = rubric_module.COURSE_THRESHOLDS[
    ("human_judge_agreement", "per_dimension_minimum")
]


def _count(dimension: str, name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{dimension} {name} must be a count (an int of at least 0)")
    return value


def _policy(rubric: Rubric, policy_id: str) -> dict:
    if policy_id not in POLICIES:
        raise ValueError(f"unknown acceptance policy: {policy_id!r}")
    agreement = rubric.thresholds.human_judge_agreement
    if agreement.per_dimension_minimum != _COURSE_MINIMUM:
        raise ValueError(
            f"rubric per_dimension_minimum {agreement.per_dimension_minimum} differs from the "
            f"course criterion {_COURSE_MINIMUM}; {rubric_module.AMENDMENT}"
        )
    return {
        "id": policy_id,
        "aggregation": "each_dimension",
        "dimensions": list(rubric_module.dimension_ids(rubric)),
        "minimum": agreement.per_dimension_minimum,
        "minimum_source": "rubric thresholds.human_judge_agreement.per_dimension_minimum",
        "comparison": "matching / n >= minimum, exact fractions, inclusive",
        "phase": agreement.phase,
        "missing_decisions": "counted in n, never matching",
        "no_items": "not met",
    }


def acceptance_result(dimensions: dict, rubric: Rubric, policy_id: str = COURSE_POLICY) -> dict:
    """Apply the acceptance policy to per-dimension figures `{id: {"matching", "n", ...}}`.

    Returns `{policy, policy_sha256, threshold_met, failing_dimensions}`; the failing
    dimensions are listed in rubric order. Other fields of each row are ignored: the policy
    decides from the counts alone. Raises ValueError for an unknown policy, a rubric that
    departs from the course criterion, an unknown dimension or a malformed row."""
    policy = _policy(rubric, policy_id)
    if not isinstance(dimensions, Mapping):
        raise ValueError("dimensions must map each dimension id to its figures")
    ids = policy["dimensions"]
    unknown = sorted(set(dimensions) - set(ids), key=str)
    if unknown:
        raise ValueError(f"unknown dimension(s): {', '.join(map(str, unknown))}")
    minimum = Fraction(repr(policy["minimum"]))  # the rubric's decimal, read exactly
    failing = []
    for dimension in ids:
        if dimension not in dimensions:
            failing.append(dimension)
            continue
        row = dimensions[dimension]
        if not isinstance(row, Mapping):
            raise ValueError(f"{dimension} figures must be a mapping with matching and n")
        if "matching" not in row or "n" not in row:
            raise ValueError(f"{dimension} figures need both matching and n")
        matching = _count(dimension, "matching", row["matching"])
        n = _count(dimension, "n", row["n"])
        if matching > n:
            raise ValueError(f"{dimension} matching {matching} exceeds n {n}")
        if n == 0 or Fraction(matching, n) < minimum:
            failing.append(dimension)
    return {
        "policy": policy,
        "policy_sha256": digest(policy),
        "threshold_met": not failing,
        "failing_dimensions": failing,
    }
