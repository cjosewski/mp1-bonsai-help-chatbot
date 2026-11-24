"""Synthetic contract fixtures, not generated or human-labeled assessment data."""

import json

import pytest
from pydantic import ValidationError

from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.schemas import CitedSection, GeneratedItem, GenerationOutput, QAItem


def payload():
    return {
        "question": "How do I assign a wall type to a selected wall in a Bonsai project?",
        "answer": "Select the wall, open the Object properties tab, and assign a type.",
        "equipment_problem": "Wall has no type assigned in a synthetic project",
        "tools_required": ["Bonsai add-on in Blender"],
        "steps": [
            "Select the wall in the 3D viewport.",
            "Open Properties > Object > Type.",
            "Pick the wall type and confirm.",
        ],
        "safety_info": "Changing a type updates every occurrence; save a copy of the project first.",
        "tips": ["Check the type name in the spreadsheet view before assigning it widely."],
    }


def section(sid="s1"):
    return {"id": sid, "page_sha256": "a" * 64, "source": "bonsai-docs", "pin_id": "pin-1"}


def quote(sid="s1", text="assign a type to the selected wall"):
    return {"section_id": sid, "text": text}


def envelope():
    return {
        "run_id": "run-1",
        "trace_id": "trace-1",
        "item_id": "item-1",
        "attempt_id": "attempt-1",
        "parent_attempt_id": None,
        "slot_id": "slot-1",
        "category": CATEGORIES[0],
        "setup_id": "SP-001",
        "version_line": "VL-current",
        "prompt_variant": "baseline",
        "prompt_hash": "b" * 64,
        "model": "synthetic-test-fixture",
        "sampler_seed": 7,
        "generated_at": "2026-11-24T12:00:00.000001+00:00",
        "offered_sections": [section("s1"), section("s2")],
        "cited_sections": [section("s1")],
        "quotes": [quote()],
        "item": payload(),
    }


def test_seven_fields_exactly():
    item = QAItem.model_validate(payload())
    assert set(item.model_dump()) == set(payload())
    assert set(QAItem.model_json_schema()["properties"]) == set(payload())
    with pytest.raises(ValidationError):
        QAItem.model_validate({**payload(), "trace_id": "wrong-layer"})
    with pytest.raises(ValidationError):
        QAItem.model_validate({**payload(), "extra": "x"})


@pytest.mark.parametrize("field", list(payload()))
def test_every_field_required(field):
    data = payload()
    del data[field]
    with pytest.raises(ValidationError):
        QAItem.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("steps", ["One", "Two"]),
        ("tools_required", []),
        ("tips", []),
        ("tools_required", "Bonsai"),
        ("question", 5),
    ],
)
def test_minimum_counts(field, value):
    with pytest.raises(ValidationError):
        QAItem.model_validate({**payload(), field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("question", " \n"),
        ("answer", ""),
        ("equipment_problem", "\t"),
        ("safety_info", " "),
        ("steps", ["One", " ", "Three"]),
        ("tips", [" "]),
    ],
)
def test_blank_strings_rejected(field, value):
    with pytest.raises(ValidationError):
        QAItem.model_validate({**payload(), field: value})


def test_legacy_problem_normalized_and_conflict_rejected():
    data = payload()
    data["problem"] = data.pop("equipment_problem")
    before = json.dumps(data)
    item = QAItem.model_validate(data)
    assert item.equipment_problem == payload()["equipment_problem"]
    assert json.dumps(data) == before
    equal = QAItem.model_validate({**payload(), "problem": payload()["equipment_problem"]})
    assert equal == item
    with pytest.raises(ValidationError, match="conflicting problem"):
        QAItem.model_validate({**payload(), "problem": "A different problem"})


@pytest.mark.parametrize(
    "legacy,current",
    [
        ("A synthetic project has no walls yet.", "A synthetic project has no walls yet. "),
        ("  A synthetic project has no walls yet.", "A synthetic project has no walls yet.\n"),
    ],
)
def test_legacy_problem_differing_only_in_surrounding_whitespace_is_not_a_conflict(legacy, current):
    item = QAItem.model_validate({**payload(), "problem": legacy, "equipment_problem": current})
    assert item.equipment_problem == "A synthetic project has no walls yet."


@pytest.mark.parametrize(
    "legacy,current",
    [
        ("A synthetic project has no walls yet.", "A synthetic project has no doors yet. "),
        ("A synthetic project has no walls yet.", "A synthetic project  has no walls yet."),
        (" ", "A synthetic project has no walls yet."),
    ],
)
def test_legacy_problem_with_a_real_difference_is_still_a_conflict(legacy, current):
    with pytest.raises(ValidationError, match="conflicting problem"):
        QAItem.model_validate({**payload(), "problem": legacy, "equipment_problem": current})


def test_legacy_problem_type_errors_are_left_to_the_field_check():
    with pytest.raises(ValidationError) as caught:
        QAItem.model_validate({**payload(), "problem": 7, "equipment_problem": 7})
    assert "conflicting" not in str(caught.value)
    with pytest.raises(ValidationError, match="conflicting problem"):
        QAItem.model_validate({**payload(), "problem": 7, "equipment_problem": "7"})


def test_payload_never_serializes_problem():
    data = payload()
    data["problem"] = data.pop("equipment_problem")
    dumped = QAItem.model_validate(data).model_dump()
    assert "problem" not in dumped
    assert "equipment_problem" in dumped
    assert '"problem"' not in QAItem.model_validate(data).model_dump_json()


def test_envelope_round_trip_keeps_lineage_and_payload_clean():
    original = GeneratedItem.model_validate({**envelope(), "parent_attempt_id": "attempt-0"})
    restored = GeneratedItem.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.schema_version == "1"
    assert restored.parent_attempt_id == "attempt-0"
    assert restored.cited_sections == [CitedSection.model_validate(section("s1"))]
    assert "trace_id" not in restored.item.model_dump()


def test_envelope_requires_a_generation_timestamp():
    data = envelope()
    del data["generated_at"]
    with pytest.raises(ValidationError, match="generated_at"):
        GeneratedItem.model_validate(data)
    record = GeneratedItem.model_validate(envelope())
    assert record.generated_at == envelope()["generated_at"]
    assert record.model_dump(mode="json")["generated_at"] == envelope()["generated_at"]
    assert "generated_at" not in record.item.model_dump()


@pytest.mark.parametrize(
    "value",
    [" ", "", "yesterday", "2026-11-24T12:00:00", "2026-11-24", 1764000000, None],
)
def test_envelope_rejects_a_blank_naive_or_non_iso_timestamp(value):
    with pytest.raises(ValidationError, match="generated_at"):
        GeneratedItem.model_validate({**envelope(), "generated_at": value})


def test_envelope_rejects_unknown_category():
    with pytest.raises(ValidationError):
        GeneratedItem.model_validate({**envelope(), "category": "unknown"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("trace_id", " "),
        ("schema_version", "2"),
        ("parent_attempt_id", ""),
        ("prompt_variant", "other"),
        ("sampler_seed", "7"),
        ("offered_sections", [{"id": "s1"}]),
    ],
)
def test_envelope_rejects_invalid_metadata(field, value):
    with pytest.raises(ValidationError):
        GeneratedItem.model_validate({**envelope(), field: value})


def test_envelope_requires_fields_and_forbids_unknown():
    data = envelope()
    del data["slot_id"]
    with pytest.raises(ValidationError):
        GeneratedItem.model_validate(data)
    with pytest.raises(ValidationError):
        GeneratedItem.model_validate({**envelope(), "secret": "x"})


def output(**changes):
    return {"item": payload(), "cited_section_ids": ["s1"], "quotes": [quote()]} | changes


def test_generation_output_needs_citations_and_valid_item():
    out = GenerationOutput.model_validate(output())
    assert out.cited_section_ids == ["s1"]
    for bad in ([], [" "]):
        with pytest.raises(ValidationError):
            GenerationOutput.model_validate(output(cited_section_ids=bad))
    with pytest.raises(ValidationError):
        GenerationOutput.model_validate(output(item={**payload(), "steps": ["a"]}))
    with pytest.raises(ValidationError):
        GenerationOutput.model_validate({**output(), "x": 1})


def test_generation_output_requires_at_least_one_quote():
    data = output()
    del data["quotes"]
    with pytest.raises(ValidationError, match="quotes"):
        GenerationOutput.model_validate(data)
    with pytest.raises(ValidationError, match="quotes"):
        GenerationOutput.model_validate(output(quotes=[]))


@pytest.mark.parametrize(
    "bad",
    [
        {"section_id": "s1"},
        {"text": "assign a type to the selected wall"},
        {**quote(), "page": 3},
        quote(sid=" "),
        quote(text=" \n "),
        quote(text=7),
        "assign a type to the selected wall",
    ],
)
def test_quote_needs_exactly_a_section_id_and_nonblank_text(bad):
    with pytest.raises(ValidationError, match="quotes"):
        GenerationOutput.model_validate(output(quotes=[quote(), bad]))
    with pytest.raises(ValidationError, match="quotes"):
        GeneratedItem.model_validate({**envelope(), "quotes": [bad]})


def test_quotes_stay_out_of_the_seven_field_payload():
    record = GeneratedItem.model_validate(envelope())
    assert record.model_dump(mode="json")["quotes"] == [quote()]
    assert "quotes" not in record.item.model_dump()
    with pytest.raises(ValidationError):
        QAItem.model_validate({**payload(), "quotes": [quote()]})
    data = envelope()
    del data["quotes"]
    with pytest.raises(ValidationError, match="quotes"):
        GeneratedItem.model_validate(data)
    with pytest.raises(ValidationError, match="quotes"):
        GeneratedItem.model_validate({**envelope(), "quotes": []})
