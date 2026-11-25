"""Synthetic contract fixtures for decisions, judgments and labels; no real label is entered."""

import json
import uuid

import pytest
from pydantic import ValidationError

from bonsai_help import rubric, tracing
from bonsai_help.evaluation_schemas import (
    DIMENSIONS,
    Decisions,
    DimensionJudgment,
    HumanLabel,
    Judgment,
)

NOTE = "synthetic note that must stay local"


def decisions(**changes):
    return dict.fromkeys(DIMENSIONS, 1) | changes


def judgment(**changes):
    value = {d: {"decision": 1, "reason": f"synthetic reason for {d}"} for d in DIMENSIONS}
    return value | changes


def label(**changes):
    value = {
        "schema_version": "1",
        "label_id": str(uuid.uuid4()),
        "assessment_id": "synthetic-assessment-1",
        "assessment_sha256": "a" * 64,
        "blind_id": "L-001",
        "trace_id": "synthetic-trace-1",
        "payload_sha256": "b" * 64,
        "rubric_version": "bonsai-rubric-v1",
        "rubric_sha256": "c" * 64,
        "reviewer": "synthetic-reviewer",
        "timestamp": "2026-11-24T12:00:00+00:00",
        "decisions": decisions(),
        "notes": NOTE,
        "supersedes_label_id": None,
        "review_stage": "blind",
        "entry": "interactive",
    }
    return value | changes


def test_dimensions_are_the_rubric_dimensions_and_the_model_fields():
    assert DIMENSIONS == rubric.DIMENSION_IDS
    assert tuple(Decisions.model_fields) == DIMENSIONS
    assert tuple(Judgment.model_fields) == DIMENSIONS


@pytest.mark.parametrize("dimension", DIMENSIONS)
@pytest.mark.parametrize("value", [True, False, 1.0, 0.0, "1", "0", 2, -1, [1], {"v": 1}])
def test_decisions_reject_nonbinary_and_coerced_values(dimension, value):
    with pytest.raises(ValidationError):
        Decisions.model_validate(decisions(**{dimension: value}))
    with pytest.raises(ValidationError):
        Decisions.model_validate_json(json.dumps(decisions(**{dimension: value})))


def test_decisions_require_every_dimension_key():
    for dimension in DIMENSIONS:
        value = decisions()
        value.pop(dimension)
        with pytest.raises(ValidationError):
            Decisions.model_validate(value)
        with pytest.raises(ValidationError):
            Decisions.model_validate_json(json.dumps(value))
    with pytest.raises(ValidationError):
        Decisions.model_validate(decisions(D7=1))
    explicit = Decisions.model_validate_json(json.dumps(decisions(D4=None)))
    assert explicit.values()["D4"] is None
    assert json.loads(explicit.model_dump_json())["D4"] is None


def test_unresolved_is_never_a_pass():
    passing = Decisions.model_validate(decisions())
    assert passing.overall() is True
    assert passing.unresolved() == ()
    assert passing.values() == dict.fromkeys(DIMENSIONS, 1)

    one_missing = Decisions.model_validate(decisions(D5=None))
    assert one_missing.overall() is None
    assert one_missing.unresolved() == ("D5",)

    fail_and_missing = Decisions.model_validate(decisions(D2=0, D6=None))
    assert fail_and_missing.overall() is False
    assert fail_and_missing.unresolved() == ("D6",)

    all_missing = Decisions.model_validate(dict.fromkeys(DIMENSIONS))
    assert all_missing.overall() is None
    assert all_missing.unresolved() == DIMENSIONS

    single_fail = Decisions.model_validate(decisions(D3=0))
    assert single_fail.overall() is False
    assert single_fail.unresolved() == ()


def test_judgment_requires_six_reasoned_binary_decisions():
    valid = Judgment.model_validate(judgment(D2={"decision": 0, "reason": "synthetic fail"}))
    assert valid.decisions() == Decisions.model_validate(decisions(D2=0))
    assert valid.decisions().overall() is False

    missing = judgment()
    missing.pop("D3")
    bad = [
        missing,
        judgment(D6={"decision": 1, "reason": "   "}),
        judgment(D6={"decision": 1, "reason": ""}),
        judgment(D1={"decision": None, "reason": "cannot decide"}),
        judgment(D1={"decision": True, "reason": "synthetic"}),
        judgment(D1={"decision": 1}),
        judgment(D1={"decision": 1, "reason": "synthetic", "confidence": 0.9}),
        judgment(D7={"decision": 1, "reason": "synthetic"}),
    ]
    for value in bad:
        with pytest.raises(ValidationError):
            Judgment.model_validate(value)
        with pytest.raises(ValidationError):
            Judgment.model_validate_json(json.dumps(value))
    with pytest.raises(ValidationError):
        DimensionJudgment.model_validate({"decision": 2, "reason": "synthetic"})


def test_human_label_round_trips_through_json():
    original = HumanLabel.model_validate(label(decisions=decisions(D1=None, D2=0)))
    again = HumanLabel.model_validate_json(original.model_dump_json())
    assert again == original
    assert again.decisions.unresolved() == ("D1",)
    assert again.decisions.overall() is False
    dumped = json.loads(original.model_dump_json())
    assert dumped["decisions"]["D1"] is None
    assert dumped["supersedes_label_id"] is None


def test_human_label_requires_utc_timestamp_and_pins():
    for timestamp in ("2026-11-24T12:00:00+00:00", "2026-11-24T12:00:00Z", tracing.now()):
        assert HumanLabel.model_validate(label(timestamp=timestamp)).timestamp == timestamp
    bad = {
        "timestamp": [
            "2026-11-24T12:00:00+02:00",
            "2026-11-24T12:00:00-05:00",
            "2026-11-24T12:00:00",
            "2026-11-24",
            "yesterday",
        ],
        "blind_id": ["L-1", "L-0001", "l-001", "L-000", "X-001", "L-٠٠١", "L-001\n"],
        "assessment_sha256": ["a" * 63, "A" * 64, "g" * 64, ""],
        "payload_sha256": ["b" * 65],
        "rubric_sha256": ["c" * 32, "C" * 64],
        "rubric_version": ["", "rubric-v1", "bonsai-rubric-v0"],
        "label_id": ["", "not-a-uuid", str(uuid.uuid1()), str(uuid.uuid4()).upper()],
        "assessment_id": ["", "../escape", "has space", "-leading"],
        "reviewer": ["", "   "],
        "trace_id": ["", "  "],
        "review_stage": ["unknown", None],
        "entry": ["command_line", "imported", None],
        "schema_version": ["2", 1],
        "notes": [None, 3],
    }
    for field, values in bad.items():
        for value in values:
            with pytest.raises(ValidationError):
                HumanLabel.model_validate(label(**{field: value}))
    for field in ("timestamp", "rubric_sha256", "rubric_version", "trace_id", "entry"):
        value = label()
        value.pop(field)
        with pytest.raises(ValidationError):
            HumanLabel.model_validate(value)


def test_supersession_names_another_label():
    earlier = str(uuid.uuid4())
    amended = HumanLabel.model_validate(label(supersedes_label_id=earlier))
    assert amended.supersedes_label_id == earlier
    own = str(uuid.uuid4())
    for value in (own, "   ", "not-a-uuid"):
        with pytest.raises(ValidationError):
            HumanLabel.model_validate(label(label_id=own, supersedes_label_id=value))
    explicit = label()
    explicit.pop("supersedes_label_id")
    with pytest.raises(ValidationError):
        HumanLabel.model_validate(explicit)


@pytest.mark.parametrize(
    "field",
    ["arm", "run_id", "item_id", "model", "prompt_variant", "prompt_hash", "judge", "category"],
)
def test_human_label_has_no_provenance_fields(field):
    with pytest.raises(ValidationError):
        HumanLabel.model_validate(label(**{field: "sentinel-provenance"}))
    assert field not in HumanLabel.model_fields


def test_validation_errors_do_not_echo_label_text():
    with pytest.raises(ValidationError) as caught:
        HumanLabel.model_validate(label(timestamp="2026-11-24T12:00:00+02:00", arm="x"))
    assert NOTE not in str(caught.value)
    assert "+02:00" not in str(caught.value)


def test_labels_and_decisions_are_frozen():
    value = HumanLabel.model_validate(label())
    with pytest.raises(ValidationError):
        value.reviewer = "someone-else"
    with pytest.raises(ValidationError):
        value.decisions.D1 = 0
