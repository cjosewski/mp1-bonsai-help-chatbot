"""The rubric (`config/rubric.json`): D1–D6 with Bonsai anchors and targets, pinned by hash.

`load_rubric` validates the file strictly: the six course dimensions in course order with
the course names exactly as plan §6.2 and `AGENTS.md` write them (case-sensitive), nonblank
anchors and labeling notes, a status from `STATUSES`, and every threshold equal to the course criterion in `AGENTS.md`. A threshold that differs
is refused: a change needs a dated amendment in `docs/DECISIONS.md`, a new rubric version
and a matching change here, never a silent edit. `chad_accepted` needs Chad's dated review
record; the assistant never sets it.

`rubric_sha256` is the hash later stages pin (labels carry the rubric version and this
hash). `overall_pass` and `relative_reduction` are the course's scoring rules: one failed
dimension fails the item; otherwise a missing decision leaves it unresolved, never a pass;
a reduction of exactly 0.80 does not pass; a
baseline failure of 0 leaves the reduction undefined. Rates are exact (`Fraction` or
`int`, built from counts); a float rate is refused, because a float such as 10/21 is not
exact and an exactly 0.80 reduction could then compare above 0.80.

Command line: `bonsai-help rubric check | show [--rubric PATH]`. Exit codes: 0 valid;
1 the rubric fails its check (invalid JSON or shape, or a departure from the course
criteria); 2 usage error, including a rubric file that cannot be read. Errors are one
`error:` line on stderr naming the file, never its absolute path.
"""

from __future__ import annotations

import datetime
import json
import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from numbers import Rational
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    model_validator,
)

from bonsai_help.doc_sources import canonical, sha256_hex

RUBRIC = Path("config/rubric.json")
DIMENSION_IDS = ("D1", "D2", "D3", "D4", "D5", "D6")
# Plan §6.2 "Course name" column and AGENTS.md Criteria, matched exactly (case-sensitive).
COURSE_NAMES = {
    "D1": "Answer completeness",
    "D2": "Safety specificity",
    "D3": "Tool realism",
    "D4": "Scope appropriateness",
    "D5": "Context clarity",
    "D6": "Tip usefulness",
}
LABEL_VALUES = (0, 1)
COURSE_MINIMUMS = {"D1": 0.85, "D2": 0.90, "D3": 0.95, "D4": 0.95, "D5": 0.90, "D6": 0.85}
# (group, field) -> course value, from AGENTS.md Criteria and Pipeline.
COURSE_THRESHOLDS = {
    ("structural_validity", "minimum"): 0.95,
    ("baseline_overall_failure", "minimum"): 0.15,
    ("human_judge_agreement", "per_dimension_minimum"): 0.80,
    ("corrected_overall_pass", "minimum"): 0.80,
    ("relative_failure_reduction", "value"): 0.80,
    ("blind_labels", "minimum_per_arm"): 20,
    ("retained_items", "minimum_per_run"): 50,
    ("intervals", "confidence"): 0.95,
}
STATUSES = ("assistant_drafted", "chad_accepted")
AMENDMENT = "a change needs a dated amendment in docs/DECISIONS.md and a new rubric version"


class RubricError(ValueError):
    """The rubric file is not a valid rubric (a check failure, exit 1)."""


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


Nonblank = Annotated[str, AfterValidator(_nonblank)]
Notes = Annotated[tuple[Nonblank, ...], Field(min_length=1)]
Rate = Annotated[float, Field(gt=0, le=1)]
Count = Annotated[int, Field(ge=1)]


def _label_values(value: tuple[int, int]) -> tuple[int, int]:
    if value != LABEL_VALUES:
        raise ValueError(f"must be {list(LABEL_VALUES)}")
    return value


LabelValues = Annotated[tuple[StrictInt, StrictInt], AfterValidator(_label_values)]


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False, hide_input_in_errors=True
    )


class LabelingNotes(_Strict):
    check: Notes
    common_fail_patterns: Notes
    borderline: Notes


class Dimension(_Strict):
    id: Literal["D1", "D2", "D3", "D4", "D5", "D6"]
    name: Nonblank
    pass_anchor: Nonblank
    fail_anchor: Nonblank
    labeling_notes: LabelingNotes
    pass_rate_minimum: Rate


class OverallPass(_Strict):
    rule: Literal["all_six_dimensions_pass"]
    missing_decision: Literal["unresolved_not_pass"]


class StructuralValidity(_Strict):
    minimum: Rate
    denominator: Literal["initial_attempts"]
    note: Nonblank


class BaselineFailure(_Strict):
    minimum: Rate
    below_minimum: Literal["report_honestly"]
    note: Nonblank


class Agreement(_Strict):
    per_dimension_minimum: Rate
    phase: Literal["A_before_B"]
    missing_labels: Literal["unresolved_not_pass"]


class CorrectedPass(_Strict):
    minimum: Rate


class ReductionRule(_Strict):
    formula: Literal["(baseline_failure - corrected_failure) / baseline_failure"]
    operator: Literal[">"]
    value: Rate
    equality: Literal["does_not_pass"]
    zero_baseline: Literal["undefined"]


class BlindLabels(_Strict):
    minimum_per_arm: Count
    arms: tuple[Literal["baseline"], Literal["corrected"]]


class RetainedItems(_Strict):
    minimum_per_run: Count


class Intervals(_Strict):
    confidence: Rate
    beside_every_rate: Literal[True]


class Thresholds(_Strict):
    structural_validity: StructuralValidity
    baseline_overall_failure: BaselineFailure
    human_judge_agreement: Agreement
    corrected_overall_pass: CorrectedPass
    relative_failure_reduction: ReductionRule
    blind_labels: BlindLabels
    retained_items: RetainedItems
    intervals: Intervals


class Review(_Strict):
    """Chad's decision on the rubric: the date, his own words and the DECISIONS entry."""

    decided_on: datetime.date
    words: Nonblank
    decisions_entry: Nonblank


class Rubric(_Strict):
    schema_version: Literal["1"]
    version: Annotated[str, Field(pattern=r"^bonsai-rubric-v[1-9][0-9]*$")]
    status: Literal["assistant_drafted", "chad_accepted"]
    review: Review | None = None
    basis: Nonblank
    label_values: LabelValues
    labeling_rules: Notes
    dimensions: tuple[Dimension, ...]
    overall_pass: OverallPass
    thresholds: Thresholds

    @model_validator(mode="after")
    def _course_criteria(self) -> Rubric:
        ids = tuple(d.id for d in self.dimensions)
        if ids != DIMENSION_IDS:
            raise ValueError(f"dimensions must be D1-D6 in course order, found {', '.join(ids)}")
        for d in self.dimensions:
            if d.name != COURSE_NAMES[d.id]:
                raise ValueError(
                    f"{d.id} name must be the course name {COURSE_NAMES[d.id]!r}, found {d.name!r}"
                )
            if d.pass_rate_minimum != COURSE_MINIMUMS[d.id]:
                raise ValueError(
                    f"{d.id} pass_rate_minimum {d.pass_rate_minimum} differs from the course "
                    f"criterion {COURSE_MINIMUMS[d.id]}; {AMENDMENT}"
                )
        for (group, field), course in COURSE_THRESHOLDS.items():
            value = getattr(getattr(self.thresholds, group), field)
            if value != course:
                raise ValueError(
                    f"thresholds.{group}.{field} {value} differs from the course criterion "
                    f"{course}; {AMENDMENT}"
                )
        if self.status == "chad_accepted" and self.review is None:
            raise ValueError("status chad_accepted needs Chad's review record (review)")
        if self.status == "assistant_drafted" and self.review is not None:
            raise ValueError("an assistant_drafted rubric carries no review")
        return self


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise RubricError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not allowed")


def load_rubric(path: Path) -> Rubric:
    """Read and validate a rubric file; OSError if it cannot be read, RubricError if invalid."""
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RubricError("not UTF-8 text") from None
    try:
        json.loads(text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
    except RubricError:
        raise
    except ValueError as error:
        raise RubricError(f"not valid JSON: {error}") from None
    try:
        return Rubric.model_validate_json(text)
    except ValidationError as error:
        raise RubricError(_describe(error)) from None


def _describe(error: ValidationError) -> str:
    problems = []
    for item in error.errors()[:3]:
        where = ".".join(str(part) for part in item["loc"]) or "(root)"
        message = item["msg"].removeprefix("Value error, ")
        problems.append(f"{where}: {message}")
    more = error.error_count() - len(problems)
    text = "; ".join(problems) + (f" (and {more} more)" if more > 0 else "")
    return " ".join(text.split())


def canonical_bytes(rubric: Rubric) -> bytes:
    """Sorted keys, no whitespace: layout and key order do not change the pin, content does."""
    return canonical(rubric.model_dump(mode="json", exclude_none=True))


def rubric_sha256(rubric: Rubric) -> str:
    return sha256_hex(canonical_bytes(rubric))


def dimension_ids(rubric: Rubric) -> tuple[str, ...]:
    return tuple(d.id for d in rubric.dimensions)


def thresholds(rubric: Rubric) -> dict[str, float]:
    """Each dimension's minimum pass rate, by dimension id."""
    return {d.id: d.pass_rate_minimum for d in rubric.dimensions}


def overall_pass(decisions: Mapping[str, int | None]) -> bool | None:
    """True only if all six decisions are present and 1. False if any present decision is 0:
    an item passes overall only if it passes all six, so one fail settles it whatever the
    missing decisions turn out to be. None (unresolved, never a pass) only if no decision is
    0 and at least one is missing or None."""
    unknown = sorted(set(decisions) - set(DIMENSION_IDS))
    if unknown:
        raise ValueError(f"unknown dimension(s): {', '.join(map(str, unknown))}")
    for key, value in decisions.items():
        if value is not None and (type(value) is not int or value not in (0, 1)):
            raise ValueError(f"{key} decision must be 0 or 1, found {value!r}")
    values = [decisions.get(key) for key in DIMENSION_IDS]
    if any(value == 0 for value in values):
        return False
    if any(value is None for value in values):
        return None
    return True


@dataclass(frozen=True)
class Reduction:
    """`value` is exact; both fields are None when the baseline failure is 0 (undefined)."""

    value: Fraction | None
    passes: bool | None


def _rate(name: str, value: object) -> Fraction:
    """An exact rate in [0, 1]: a `Fraction` or an `int`, never a float or a boolean."""
    if isinstance(value, float):
        raise TypeError(
            f"{name} must be exact (a Fraction from counts, or an int), found float {value!r}"
        )
    if isinstance(value, bool) or not isinstance(value, Rational):
        raise TypeError(
            f"{name} must be exact (a Fraction or an int), found {type(value).__name__}"
        )
    exact = Fraction(value)
    if not 0 <= exact <= 1:
        raise ValueError(f"{name} must be between 0 and 1, found {value}")
    return exact


def _threshold(name: str, value: object) -> Fraction:
    """A threshold from the rubric. It is written there as a short decimal, so a float is read
    by its shortest decimal form (0.8 is 4/5); a `Fraction` or `int` is taken as it is."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        value = Fraction(repr(value))
    if isinstance(value, bool) or not isinstance(value, Rational):
        raise TypeError(f"{name} must be a number, found {type(value).__name__}")
    exact = Fraction(value)
    if not 0 < exact <= 1:
        raise ValueError(f"{name} must be above 0 and at most 1, found {value}")
    return exact


def relative_reduction(
    baseline_failure: Fraction | int,
    corrected_failure: Fraction | int,
    *,
    minimum: float | Fraction = COURSE_THRESHOLDS[("relative_failure_reduction", "value")],
) -> Reduction:
    """`(baseline_failure - corrected_failure) / baseline_failure`, passing only when strictly
    greater than `minimum` (exactly 0.80 does not pass); undefined when the baseline is 0.

    The failure rates must be exact, for example `Fraction(failures, labeled)`: a float is
    refused with TypeError, because 10/21 against 2/21 is exactly 0.80 but its floats are
    not. `minimum` is the rubric's decimal threshold and may be its float."""
    baseline = _rate("baseline_failure", baseline_failure)
    corrected = _rate("corrected_failure", corrected_failure)
    bound = _threshold("minimum", minimum)
    if baseline == 0:
        return Reduction(None, None)
    value = (baseline - corrected) / baseline
    return Reduction(value, value > bound)


# --- command line -----------------------------------------------------------------------


def add_commands(commands) -> None:
    parser = commands.add_parser("rubric", help="the labeling rubric (D1-D6) and its hash pin")
    actions = parser.add_subparsers(dest="action", required=True)
    for name, text in (
        ("check", "validate the rubric and print its version, status and sha256"),
        ("show", "print the rubric's dimensions, anchors, notes and thresholds"),
    ):
        sub = actions.add_parser(name, help=text)
        sub.add_argument("--rubric", type=Path, help=f"rubric file (default {RUBRIC})")


def run(args, *, root: Path) -> int:
    path = (args.rubric if args.rubric is not None else root / RUBRIC).absolute()
    try:
        loaded = load_rubric(path)
    except RubricError as error:
        return _error(f"{path.name}: {error}", 1)
    except OSError as error:
        return _error(f"{path.name}: cannot read: {error.strerror or type(error).__name__}", 2)
    lines = _summary(loaded) if args.action == "check" else _show(loaded)
    if loaded.status != "chad_accepted":
        print(
            f"warning: status {loaded.status}: Chad has not accepted this rubric", file=sys.stderr
        )
    print("\n".join(lines))
    return 0


def _error(message: str, code: int) -> int:
    print(f"error: {' '.join(message.split())}", file=sys.stderr)
    return code


def _summary(rubric: Rubric) -> list[str]:
    return [
        f"version: {rubric.version}",
        f"status: {rubric.status}",
        f"sha256: {rubric_sha256(rubric)}",
    ]


def _show(rubric: Rubric) -> list[str]:
    lines = _summary(rubric)
    if rubric.review is not None:
        lines.append(f"review: {rubric.review.decided_on} {rubric.review.words!r}")
    lines += ["", "Labeling rules:", *(f"  - {rule}" for rule in rubric.labeling_rules)]
    for d in rubric.dimensions:
        lines += [
            "",
            f"{d.id} {d.name} (pass rate at least {d.pass_rate_minimum})",
            f"  pass: {d.pass_anchor}",
            f"  fail: {d.fail_anchor}",
        ]
        for title, notes in (
            ("check", d.labeling_notes.check),
            ("common fail patterns", d.labeling_notes.common_fail_patterns),
            ("borderline", d.labeling_notes.borderline),
        ):
            lines += [f"  {title}:", *(f"    - {note}" for note in notes)]
    t = rubric.thresholds
    reduction = t.relative_failure_reduction
    lines += [
        "",
        "Overall: an item passes only if all six dimensions pass; one fail fails it, and "
        "otherwise a missing decision is unresolved, not a pass.",
        "Thresholds:",
        f"  structural validity (initial attempts): at least {t.structural_validity.minimum}",
        f"  baseline overall failure: at least {t.baseline_overall_failure.minimum}, "
        "reported honestly",
        f"  human/judge agreement per dimension: at least "
        f"{t.human_judge_agreement.per_dimension_minimum} (Phase A, before Phase B)",
        f"  corrected overall pass: at least {t.corrected_overall_pass.minimum}",
        f"  relative failure reduction {reduction.formula}: {reduction.operator} "
        f"{reduction.value} ({reduction.value} exactly does not pass; undefined when the "
        "baseline failure is 0)",
        f"  blind labels: at least {t.blind_labels.minimum_per_arm} per arm "
        f"({', '.join(t.blind_labels.arms)})",
        f"  retained items: at least {t.retained_items.minimum_per_run} per run",
        f"  intervals: {t.intervals.confidence:.0%} beside every rate",
    ]
    return lines
