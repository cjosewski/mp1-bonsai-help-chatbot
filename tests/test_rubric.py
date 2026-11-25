"""The B5 rubric: strict shape, the course criteria, the hash pin and the scoring helpers."""

from __future__ import annotations

import copy
import json
import math
from fractions import Fraction
from pathlib import Path

import pytest

from bonsai_help import cli, rubric

REPO = Path(__file__).resolve().parents[1]
COMMITTED = REPO / "config" / "rubric.json"
# Plan §6.2 "Course name" column and AGENTS.md Criteria, in their sentence case.
COURSE_NAMES = [
    "Answer completeness",
    "Safety specificity",
    "Tool realism",
    "Scope appropriateness",
    "Context clarity",
    "Tip usefulness",
]
ALL_PASS = {f"D{n}": 1 for n in range(1, 7)}


def committed() -> dict:
    return json.loads(COMMITTED.read_text(encoding="utf-8"))


def write(tmp_path: Path, document: dict | str, name: str = "rubric.json") -> Path:
    path = tmp_path / name
    text = document if isinstance(document, str) else json.dumps(document, indent=2)
    path.write_text(text, encoding="utf-8")
    return path


def mutated(change) -> dict:
    document = copy.deepcopy(committed())
    change(document)
    return document


# --- the committed rubric ---------------------------------------------------------------


def test_committed_rubric_is_accepted_by_chad_with_the_course_criteria():
    loaded = rubric.load_rubric(COMMITTED)
    assert loaded.version == "bonsai-rubric-v1"
    assert loaded.status == "chad_accepted"
    assert loaded.review is not None
    assert str(loaded.review.decided_on) == "2026-11-24"
    assert loaded.review.words == "Accept as drafted"
    assert rubric.dimension_ids(loaded) == ("D1", "D2", "D3", "D4", "D5", "D6")
    assert [d.name for d in loaded.dimensions] == COURSE_NAMES
    assert rubric.thresholds(loaded) == {
        "D1": 0.85,
        "D2": 0.90,
        "D3": 0.95,
        "D4": 0.95,
        "D5": 0.90,
        "D6": 0.85,
    }
    limits = loaded.thresholds
    assert limits.structural_validity.minimum == 0.95
    assert limits.structural_validity.denominator == "initial_attempts"
    assert limits.baseline_overall_failure.minimum == 0.15
    assert limits.human_judge_agreement.per_dimension_minimum == 0.80
    assert limits.corrected_overall_pass.minimum == 0.80
    assert limits.relative_failure_reduction.operator == ">"
    assert limits.relative_failure_reduction.value == 0.80
    assert limits.relative_failure_reduction.equality == "does_not_pass"
    assert limits.blind_labels.minimum_per_arm == 20
    assert limits.intervals.confidence == 0.95


@pytest.mark.parametrize("name", ["Tool Realism", "TOOL REALISM", "tool realism", "Tool realism "])
def test_course_names_must_match_the_plan_spelling_exactly(tmp_path, name):
    # The plan and AGENTS.md give sentence case ("Tool realism"); any other casing or
    # spacing is a different name and is refused, so the hash cannot drift on case alone.
    path = write(tmp_path, mutated(_set_dimension(2, "name", name)))
    with pytest.raises(rubric.RubricError, match="course name 'Tool realism'"):
        rubric.load_rubric(path)


def test_d2_doc_confirmation_applies_to_the_typical_hazards_only():
    # Plan §6.3: the typical candidates are each "used in scoring only after it is
    # confirmed against the docs, with the page cited", and "An answer passes D2 when it
    # names the hazard that applies to its own steps." The condition is not widened to
    # every risk: a task-specific risk read from the item's own steps and setup counts.
    d2 = rubric.load_rubric(COMMITTED).dimensions[1]
    hazards = [note for note in d2.labeling_notes.check if "plan §6.3" in note]
    assert len(hazards) == 1
    assert (
        "used in scoring only after it is confirmed against the docs, with the page cited"
        in hazards[0]
    )
    assert "Only these typical hazards need that confirmation." in hazards[0]
    assert "own steps and setup record" in hazards[0]
    fails = d2.labeling_notes.common_fail_patterns
    unconfirmed = [note for note in fails if "not confirmed" in note]
    assert len(unconfirmed) == 1
    assert "typical hazard" in unconfirmed[0]
    assert "own steps and setup record" in unconfirmed[0]
    every_note = " ".join(
        d2.labeling_notes.check + fails + d2.labeling_notes.borderline + (d2.pass_anchor,)
    )
    assert "an unconfirmed risk is not a pass" not in every_note
    assert "even when it is one of the typical hazards" not in every_note


def test_labeling_rules_never_skip_an_item_and_keep_it_in_its_denominator():
    # A skipped item would leave its arm's denominator and bias the failure rate down.
    # AGENTS.md: "A missing judgment is unresolved, not a pass."
    rules = rubric.load_rubric(COMMITTED).labeling_rules
    text = " ".join(rules)
    assert "skip the item" not in text
    undecided = [rule for rule in rules if "unresolved" in rule]
    assert len(undecided) == 1
    assert "every dimension" in undecided[0]
    assert "never counted as a pass" in undecided[0]
    assert "denominator" in undecided[0]
    assert "never skipped" in undecided[0]


# --- shape refusals ---------------------------------------------------------------------


def _swap_d2_d3(d):
    d["dimensions"][1], d["dimensions"][2] = d["dimensions"][2], d["dimensions"][1]


def _set_dimension(index, key, value):
    def change(d):
        d["dimensions"][index][key] = value

    return change


def _set_threshold(group, key, value):
    def change(d):
        d["thresholds"][group][key] = value

    return change


REFUSALS = {
    "wrong order": (_swap_d2_d3, "D1-D6 in course order"),
    "missing dimension": (lambda d: d["dimensions"].pop(), "D1-D6 in course order"),
    "duplicated dimension": (
        lambda d: d["dimensions"].__setitem__(5, copy.deepcopy(d["dimensions"][4])),
        "D1-D6 in course order",
    ),
    "unknown dimension id": (_set_dimension(5, "id", "D7"), "dimensions.5.id"),
    "renamed dimension": (_set_dimension(2, "name", "API Realism"), "'Tool realism'"),
    "course name with extra words": (
        _set_dimension(0, "name", "Answer completeness and depth"),
        "course name",
    ),
    "extra top-level key": (lambda d: d.update(approved_by="someone"), "approved_by"),
    "extra dimension key": (_set_dimension(0, "original_name", "x"), "original_name"),
    "extra notes key": (
        lambda d: d["dimensions"][0]["labeling_notes"].update(examples=["x"]),
        "examples",
    ),
    "threshold 0": (_set_dimension(0, "pass_rate_minimum", 0), "pass_rate_minimum"),
    "threshold above 1": (_set_dimension(1, "pass_rate_minimum", 1.5), "pass_rate_minimum"),
    "threshold as a boolean": (_set_dimension(1, "pass_rate_minimum", True), "pass_rate_minimum"),
    "weaker dimension threshold": (
        _set_dimension(0, "pass_rate_minimum", 0.80),
        "differs from the course criterion 0.85",
    ),
    "stricter dimension threshold": (
        _set_dimension(3, "pass_rate_minimum", 0.99),
        "differs from the course criterion 0.95",
    ),
    "blank pass anchor": (_set_dimension(2, "pass_anchor", "   "), "pass_anchor"),
    "empty fail anchor": (_set_dimension(4, "fail_anchor", ""), "fail_anchor"),
    "missing anchor": (lambda d: d["dimensions"][1].pop("pass_anchor"), "pass_anchor"),
    "empty labeling notes": (
        lambda d: d["dimensions"][3]["labeling_notes"].__setitem__("borderline", []),
        "borderline",
    ),
    "blank labeling note": (
        lambda d: d["dimensions"][3]["labeling_notes"].__setitem__("check", [" "]),
        "check",
    ),
    "status not allowed": (lambda d: d.update(status="approved"), "status"),
    "accepted without Chad's review": (
        lambda d: (d.update(status="chad_accepted"), d.pop("review", None)),
        "review",
    ),
    "draft carrying a review": (
        lambda d: d.update(
            status="assistant_drafted",
            review={"decided_on": "2026-11-24", "words": "approve", "decisions_entry": "x"},
        ),
        "review",
    ),
    "other version name": (lambda d: d.update(version="engineering-v1"), "version"),
    "label values widened": (lambda d: d.update(label_values=[0, 1, 2]), "label_values"),
    "label values as booleans": (lambda d: d.update(label_values=[False, True]), "label_values"),
    "label values reversed": (lambda d: d.update(label_values=[1, 0]), "label_values"),
    "label values as floats": (lambda d: d.update(label_values=[0.0, 1.0]), "label_values"),
    "overall rule loosened": (
        lambda d: d["overall_pass"].update(missing_decision="counts_as_pass"),
        "missing_decision",
    ),
    "structural threshold lowered": (
        _set_threshold("structural_validity", "minimum", 0.90),
        "course criterion 0.95",
    ),
    "structural denominator changed": (
        _set_threshold("structural_validity", "denominator", "retained_items"),
        "denominator",
    ),
    "baseline failure lowered": (
        _set_threshold("baseline_overall_failure", "minimum", 0.10),
        "course criterion 0.15",
    ),
    "agreement lowered": (
        _set_threshold("human_judge_agreement", "per_dimension_minimum", 0.75),
        "course criterion 0.8",
    ),
    "corrected pass lowered": (
        _set_threshold("corrected_overall_pass", "minimum", 0.70),
        "course criterion 0.8",
    ),
    "reduction made inclusive": (
        _set_threshold("relative_failure_reduction", "operator", ">="),
        "operator",
    ),
    "reduction equality passes": (
        _set_threshold("relative_failure_reduction", "equality", "passes"),
        "equality",
    ),
    "reduction value lowered": (
        _set_threshold("relative_failure_reduction", "value", 0.5),
        "course criterion 0.8",
    ),
    "fewer blind labels": (
        _set_threshold("blind_labels", "minimum_per_arm", 10),
        "course criterion 20",
    ),
    "fewer retained items": (
        _set_threshold("retained_items", "minimum_per_run", 40),
        "course criterion 50",
    ),
    "intervals dropped": (_set_threshold("intervals", "beside_every_rate", False), "intervals"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_load_refuses_a_rubric_that_departs_from_the_shape_or_the_course(tmp_path, case):
    change, message = REFUSALS[case]
    path = write(tmp_path, mutated(change))
    with pytest.raises(rubric.RubricError) as caught:
        rubric.load_rubric(path)
    assert message in str(caught.value)
    assert "\n" not in str(caught.value)


@pytest.mark.parametrize(
    "text, message",
    [
        ('{"schema_version": "1", "schema_version": "1"}', "duplicate key"),
        ("{not json", "not valid JSON"),
        ('{"label_values": [NaN]}', "not valid JSON"),
        ("[]", "(root)"),
    ],
)
def test_load_refuses_malformed_json(tmp_path, text, message):
    with pytest.raises(rubric.RubricError, match=message.replace("(", r"\(").replace(")", r"\)")):
        rubric.load_rubric(write(tmp_path, text))


def test_load_refuses_bytes_that_are_not_utf8(tmp_path):
    path = tmp_path / "rubric.json"
    path.write_bytes(b'{"version": "\xff"}')
    with pytest.raises(rubric.RubricError, match="UTF-8"):
        rubric.load_rubric(path)


def test_an_accepted_rubric_needs_chads_dated_review_record(tmp_path):
    document = mutated(
        lambda d: d.update(
            status="chad_accepted",
            review={
                "decided_on": "2026-12-01",
                "words": "synthetic test words",
                "decisions_entry": "synthetic test entry",
            },
        )
    )
    loaded = rubric.load_rubric(write(tmp_path, document))
    assert loaded.status == "chad_accepted"
    assert str(loaded.review.decided_on) == "2026-12-01"
    document["review"]["words"] = " "
    with pytest.raises(rubric.RubricError, match="review.words"):
        rubric.load_rubric(write(tmp_path, document))


def test_unreadable_rubric_is_an_os_error_not_a_check_failure(tmp_path):
    with pytest.raises(OSError):
        rubric.load_rubric(tmp_path / "absent.json")


# --- the hash pin -----------------------------------------------------------------------


def test_sha256_is_stable_across_layout_and_changes_with_content(tmp_path):
    pinned = rubric.rubric_sha256(rubric.load_rubric(COMMITTED))
    assert len(pinned) == 64 and int(pinned, 16) >= 0
    assert pinned == rubric.rubric_sha256(rubric.load_rubric(COMMITTED))

    document = committed()
    reordered = {key: document[key] for key in reversed(list(document))}
    compact = write(tmp_path, json.dumps(reordered, separators=(",", ":")), "compact.json")
    assert rubric.rubric_sha256(rubric.load_rubric(compact)) == pinned

    reworded = mutated(
        lambda d: d["dimensions"][5].update(pass_anchor=d["dimensions"][5]["pass_anchor"] + " ")
    )
    changed = rubric.rubric_sha256(rubric.load_rubric(write(tmp_path, reworded, "worded.json")))
    assert changed != pinned

    note = mutated(lambda d: d["labeling_rules"].append("A synthetic extra rule."))
    noted = rubric.rubric_sha256(rubric.load_rubric(write(tmp_path, note, "note.json")))
    assert noted not in (pinned, changed)


# --- overall pass -----------------------------------------------------------------------


def test_overall_pass_needs_all_six_passes():
    assert rubric.overall_pass(ALL_PASS) is True
    assert rubric.overall_pass(ALL_PASS | {"D4": 0}) is False


@pytest.mark.parametrize(
    "decisions",
    [
        {k: v for k, v in (ALL_PASS | {"D1": 0}).items() if k != "D5"},
        ALL_PASS | {"D2": 0, "D3": None, "D6": None},
        {"D4": 0},
        {"D1": None, "D2": None, "D3": None, "D4": None, "D5": None, "D6": 0},
    ],
    ids=["a fail and a missing", "a fail and two None", "only a fail", "a fail, rest None"],
)
def test_overall_pass_with_a_fail_has_failed_even_when_a_decision_is_missing(decisions):
    # "Passes overall only if it passes all six": one 0 settles the item as failed,
    # whatever the missing decisions turn out to be.
    assert rubric.overall_pass(decisions) is False


@pytest.mark.parametrize(
    "decisions",
    [
        {k: v for k, v in ALL_PASS.items() if k != "D3"},
        ALL_PASS | {"D6": None},
        {"D1": 1},
        {},
    ],
    ids=["one missing", "one None", "only a pass", "empty"],
)
def test_overall_pass_with_a_missing_decision_and_no_fail_is_unresolved_not_a_pass(decisions):
    outcome = rubric.overall_pass(decisions)
    assert outcome is None
    assert not outcome  # never truthy, so a naive check cannot count it as a pass


@pytest.mark.parametrize(
    "decisions",
    [ALL_PASS | {"D7": 1}, ALL_PASS | {"D2": 2}, ALL_PASS | {"D2": True}, ALL_PASS | {"D2": "1"}],
    ids=["unknown dimension", "not binary", "boolean", "string"],
)
def test_overall_pass_refuses_unknown_dimensions_and_non_binary_values(decisions):
    with pytest.raises(ValueError):
        rubric.overall_pass(decisions)


# --- relative failure reduction ---------------------------------------------------------


def rate(failures: int, total: int) -> Fraction:
    return Fraction(failures, total)


@pytest.mark.parametrize(
    "baseline, corrected",
    [
        (rate(1, 2), rate(1, 10)),
        (rate(15, 50), rate(3, 50)),
        (rate(10, 21), rate(2, 21)),
        (rate(15, 21), rate(3, 21)),
        (rate(35, 63), rate(7, 63)),
        (rate(5, 23), rate(1, 23)),
    ],
)
def test_reduction_of_exactly_080_does_not_pass(baseline, corrected):
    result = rubric.relative_reduction(baseline, corrected)
    assert result.value == Fraction(4, 5)
    assert result.passes is False


def test_reduction_above_080_passes_and_below_fails():
    above = rubric.relative_reduction(rate(25, 50), rate(4, 50))
    assert above.value == Fraction(21, 25) and above.passes is True
    below = rubric.relative_reduction(rate(10, 50), rate(3, 50))
    assert below.value == Fraction(7, 10) and below.passes is False
    worse = rubric.relative_reduction(rate(2, 10), rate(3, 10))
    assert worse.value < 0 and worse.passes is False


def test_reduction_with_zero_baseline_failure_is_undefined():
    result = rubric.relative_reduction(0, 0)
    assert result.value is None and result.passes is None
    assert rubric.relative_reduction(rate(0, 21), rate(2, 21)).passes is None


def test_reduction_reads_its_minimum_from_the_rubric():
    loaded = rubric.load_rubric(COMMITTED)
    minimum = loaded.thresholds.relative_failure_reduction.value
    exact = (rate(10, 21), rate(2, 21))
    assert rubric.relative_reduction(*exact, minimum=minimum).passes is False
    assert rubric.relative_reduction(*exact, minimum=0.7).passes is True
    assert rubric.relative_reduction(*exact, minimum=Fraction(4, 5)).passes is False


@pytest.mark.parametrize(
    "baseline, corrected",
    [(10 / 21, rate(2, 21)), (rate(10, 21), 2 / 21), (0.5, 0.1), (0.0, 0)],
    ids=["float baseline", "float corrected", "decimal floats", "float zero"],
)
def test_reduction_refuses_float_rates_because_they_are_not_exact(baseline, corrected):
    # 10/21 against 2/21 is exactly 0.80; as floats it would compare above 0.80 and pass.
    with pytest.raises(TypeError, match="exact"):
        rubric.relative_reduction(baseline, corrected)


@pytest.mark.parametrize(
    "baseline, corrected",
    [
        (rate(6, 5), rate(1, 10)),
        (rate(1, 2), rate(-1, 10)),
        (2, 0),
        (True, rate(1, 10)),
        ("0.5", rate(1, 10)),
        (math.nan, rate(1, 10)),
    ],
)
def test_reduction_refuses_rates_outside_zero_to_one(baseline, corrected):
    with pytest.raises((ValueError, TypeError)):
        rubric.relative_reduction(baseline, corrected)


@pytest.mark.parametrize("minimum", [math.nan, math.inf, 1.5, True, "0.8"])
def test_reduction_refuses_an_unusable_minimum(minimum):
    with pytest.raises((ValueError, TypeError)):
        rubric.relative_reduction(rate(1, 2), rate(1, 10), minimum=minimum)


# --- command line -----------------------------------------------------------------------


def test_cli_check_prints_version_status_and_hash(capsys):
    assert cli.main(["rubric", "check", "--rubric", str(COMMITTED)]) == 0
    out, err = capsys.readouterr()
    sha = rubric.rubric_sha256(rubric.load_rubric(COMMITTED))
    assert "version: bonsai-rubric-v1" in out
    assert "status: chad_accepted" in out
    assert f"sha256: {sha}" in out
    assert "warning:" not in err


def test_cli_check_warns_while_a_rubric_is_only_a_draft(tmp_path, capsys):
    draft = mutated(lambda d: (d.update(status="assistant_drafted"), d.pop("review", None)))
    path = write(tmp_path, draft)
    assert cli.main(["rubric", "check", "--rubric", str(path)]) == 0
    out, err = capsys.readouterr()
    assert "status: assistant_drafted" in out
    assert "warning:" in err and "not accepted" in err


def test_cli_check_uses_the_repository_rubric_by_default(capsys, monkeypatch):
    monkeypatch.chdir(REPO / "src")
    assert cli.main(["rubric", "check"]) == 0
    assert "version: bonsai-rubric-v1" in capsys.readouterr().out


def test_cli_check_fails_on_an_invalid_rubric_with_one_line_and_no_path(tmp_path, capsys):
    path = write(tmp_path, mutated(_set_dimension(2, "name", "API Realism")))
    assert cli.main(["rubric", "check", "--rubric", str(path)]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    lines = err.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("error: rubric.json: ")
    assert "Tool realism" in lines[0]
    assert str(tmp_path) not in err


def test_cli_check_missing_rubric_is_a_usage_error(tmp_path, capsys, monkeypatch):
    assert cli.main(["rubric", "check", "--rubric", str(tmp_path / "absent.json")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: absent.json: cannot read") and str(tmp_path) not in err
    monkeypatch.chdir(tmp_path)  # no repository here: the default path does not exist
    assert cli.main(["rubric", "show"]) == 2


def test_cli_show_prints_every_dimension_with_its_anchors(capsys):
    assert cli.main(["rubric", "show", "--rubric", str(COMMITTED)]) == 0
    out = capsys.readouterr().out
    loaded = rubric.load_rubric(COMMITTED)
    assert "status: chad_accepted" in out
    assert "review: 2026-11-24 'Accept as drafted'" in out
    for dimension in loaded.dimensions:
        assert f"{dimension.id} {dimension.name}" in out
        assert dimension.pass_anchor in out and dimension.fail_anchor in out
    assert "> 0.8" in out and "0.8 exactly does not pass" in out


def test_cli_show_fails_on_an_invalid_rubric(tmp_path, capsys):
    path = write(tmp_path, mutated(lambda d: d["dimensions"].pop()))
    assert cli.main(["rubric", "show", "--rubric", str(path)]) == 1
    assert capsys.readouterr().out == ""


def test_cli_rubric_needs_an_action(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["rubric"])
    assert caught.value.code == 2
