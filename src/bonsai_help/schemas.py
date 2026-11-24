"""Canonical generated payload, generation output and its provenance envelope."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from bonsai_help.doc_sources import Category

NonBlank = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]


def _aware_iso_timestamp(value: str) -> str:
    """Keep the exact text (it must equal the attempt's `completed_at`); check its form."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("must be an ISO-8601 date and time") from None
    if parsed.tzinfo is None or "T" not in value:
        raise ValueError("must be an ISO-8601 date and time with a UTC offset")
    return value


Timestamp = Annotated[NonBlank, AfterValidator(_aware_iso_timestamp)]


class QAItem(BaseModel):
    """The seven payload fields; legacy spelling never appears in serialized output."""

    model_config = ConfigDict(strict=True, extra="forbid")

    question: NonBlank
    answer: NonBlank
    equipment_problem: NonBlank
    tools_required: Annotated[list[NonBlank], Field(min_length=1)]
    steps: Annotated[list[NonBlank], Field(min_length=3)]
    safety_info: NonBlank
    tips: Annotated[list[NonBlank], Field(min_length=1)]

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_problem(cls, value: Any) -> Any:
        """Accept the legacy key explicitly, without mutating the raw input."""
        if not isinstance(value, dict) or "problem" not in value:
            return value
        normalized = dict(value)
        legacy = normalized.pop("problem")
        if "equipment_problem" in normalized:
            current = normalized["equipment_problem"]
            # Both are stripped by NonBlank later, so values that differ only in surrounding
            # whitespace store the same text and do not conflict. Non-strings are compared
            # as given; the strict field check then rejects their type.
            if isinstance(current, str) and isinstance(legacy, str):
                same = current.strip() == legacy.strip()
            else:
                same = current == legacy
            if not same:
                raise ValueError("conflicting problem and equipment_problem values")
        else:
            normalized["equipment_problem"] = legacy
        return normalized


class Quote(BaseModel):
    """A passage copied from one cited section; metadata, never part of the payload."""

    model_config = ConfigDict(strict=True, extra="forbid")

    section_id: NonBlank
    text: NonBlank


class GenerationOutput(BaseModel):
    """What the model returns: the payload, the ids of the sections it cites, its quotes."""

    model_config = ConfigDict(strict=True, extra="forbid")

    item: QAItem
    cited_section_ids: Annotated[list[NonBlank], Field(min_length=1)]
    quotes: Annotated[list[Quote], Field(min_length=1)]


class CitedSection(BaseModel):
    """A docs-index section reference stored in the envelope."""

    model_config = ConfigDict(strict=True, extra="forbid")

    id: NonBlank
    page_sha256: NonBlank
    source: NonBlank
    pin_id: NonBlank


class GeneratedItem(BaseModel):
    """One schema-valid result, with provenance outside the seven-field item."""

    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    run_id: NonBlank
    trace_id: NonBlank
    item_id: NonBlank
    attempt_id: NonBlank
    parent_attempt_id: NonBlank | None = None
    slot_id: NonBlank
    category: Category
    setup_id: NonBlank
    version_line: NonBlank
    prompt_variant: Literal["baseline", "corrected"]
    prompt_hash: NonBlank
    model: NonBlank
    sampler_seed: int
    # When the completion was recorded: the same text as the attempt's `completed_at`.
    generated_at: Timestamp
    offered_sections: list[CitedSection]
    cited_sections: list[CitedSection]
    # The model's quotes in its order: each section id resolved as a citation is
    # (`generate.resolve_quotes`), each text as the model wrote it.
    quotes: Annotated[list[Quote], Field(min_length=1)]
    item: QAItem
