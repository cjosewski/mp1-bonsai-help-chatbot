"""Strict human-label and judge contracts for the six rubric dimensions (D1–D6).

A human decision per dimension is `0`, `1` or `None` (unresolved). Every key is required,
so `None` is accepted only when written explicitly; booleans, floats and strings are
refused. Unresolved is reported, never a pass, and the item stays in its denominator:
`Decisions.overall` delegates to `rubric.overall_pass`, which returns `None` or `False`,
never `True`, while a decision is missing.

A judge decision (`DimensionJudgment`) is only `0` or `1`, with a nonblank reason. A judge
that cannot decide has a failed or missing attempt, which later stages report as
unresolved; it never has a `None` decision.

`HumanLabel` carries the label pins (assessment hash, trace id, payload hash, rubric version
and hash, UTC timestamp) and no provenance: no run id, item id, arm, model or prompt
variant. Its `notes` are free text that stays in the local ledger and never enters Git.
Validation errors never echo the input, so a note or other label text cannot leak through an
error message. Every model is strict, forbids extra keys and is frozen.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from bonsai_help import rubric
from bonsai_help.schemas import NonBlank, Timestamp

DIMENSIONS = rubric.DIMENSION_IDS


def _strict_config() -> ConfigDict:
    return ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


Binary = Annotated[int, Field(strict=True, ge=0, le=1)]
Decision = Binary | None


def _matching(pattern: str, description: str):
    compiled = re.compile(pattern)

    def check(value: str) -> str:
        # fullmatch with ASCII classes: no trailing newline and no non-ASCII digits pass.
        if not compiled.fullmatch(value):
            raise ValueError(f"must be {description}")
        return value

    return AfterValidator(check)


def _blind_id(value: str) -> str:
    if value == "L-000":
        raise ValueError("blind ids start at L-001")
    return value


def _uuid4(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ValueError("must be a UUID4 in canonical lower-case text") from None
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("must be a UUID4 in canonical lower-case text")
    return value


def _utc(value: str) -> str:
    if datetime.fromisoformat(value).utcoffset() != timedelta(0):
        raise ValueError("must be in UTC (offset zero)")
    return value


Sha256 = Annotated[str, _matching(r"[0-9a-f]{64}", "64 lower-case hexadecimal characters")]
BlindId = Annotated[str, _matching(r"L-[0-9]{3}", "a blind id L-NNN"), AfterValidator(_blind_id)]
LabelId = Annotated[str, AfterValidator(_uuid4)]
# The safe-id rule of `tracing.run_directory`.
AssessmentId = Annotated[
    str, _matching(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", "1-64 letters, digits, _ or -")
]
RubricVersion = Annotated[str, _matching(r"bonsai-rubric-v[1-9][0-9]*", "a rubric version")]
UtcTimestamp = Annotated[Timestamp, AfterValidator(_utc)]


class Decisions(BaseModel):
    """One human decision per dimension; `None` (unresolved) only when written explicitly."""

    model_config = _strict_config()

    D1: Decision
    D2: Decision
    D3: Decision
    D4: Decision
    D5: Decision
    D6: Decision

    def values(self) -> dict[str, int | None]:
        return {key: getattr(self, key) for key in DIMENSIONS}

    def unresolved(self) -> tuple[str, ...]:
        return tuple(key for key in DIMENSIONS if getattr(self, key) is None)

    def overall(self) -> bool | None:
        """True only if all six pass; False if any fails; otherwise None, never a pass."""
        return rubric.overall_pass(self.values())


class DimensionJudgment(BaseModel):
    model_config = _strict_config()

    decision: Binary
    reason: NonBlank


class Judgment(BaseModel):
    """The judge's six binary decisions, each with a reason."""

    model_config = _strict_config()

    D1: DimensionJudgment
    D2: DimensionJudgment
    D3: DimensionJudgment
    D4: DimensionJudgment
    D5: DimensionJudgment
    D6: DimensionJudgment

    def decisions(self) -> Decisions:
        return Decisions.model_validate({key: getattr(self, key).decision for key in DIMENSIONS})


class HumanLabel(BaseModel):
    """One interactive human label for one blind item; corrections supersede, never edit."""

    model_config = _strict_config()

    schema_version: Literal["1"]
    label_id: LabelId
    assessment_id: AssessmentId
    assessment_sha256: Sha256
    blind_id: BlindId
    trace_id: NonBlank
    payload_sha256: Sha256
    rubric_version: RubricVersion
    rubric_sha256: Sha256
    reviewer: NonBlank
    timestamp: UtcTimestamp
    decisions: Decisions
    notes: str = ""
    supersedes_label_id: LabelId | None
    review_stage: Literal["blind", "post_review"]
    entry: Literal["interactive"]

    @model_validator(mode="after")
    def _supersedes_another(self) -> HumanLabel:
        if self.supersedes_label_id == self.label_id:
            raise ValueError("a label cannot supersede itself")
        return self
