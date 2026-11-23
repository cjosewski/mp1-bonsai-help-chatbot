"""Deterministic pre-checks: one rule per test, synthetic items on real lexicon ids."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import synthetic_item

from bonsai_help import checks
from bonsai_help.checks import CheckResult, Lexicons, load_lexicons, run_checks
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.schemas import CitedSection, GeneratedItem

ROOT = Path(__file__).resolve().parents[1]
LEX = load_lexicons(ROOT / "reference")


def _section(n: int) -> CitedSection:
    return CitedSection(
        id=f"bonsai-docs:synthetic/page{n}.rst#L1-L9",
        page_sha256="0" * 64,
        source="bonsai-docs",
        pin_id="synthetic-pin",
    )


def known_bim() -> str:
    return sorted(LEX.bim_ids["VL-current"])[0]


def good_item() -> dict:
    item = synthetic_item()
    item["answer"] = " ".join(["Open the project and add the wall using the type library."] * 7)
    item["question"] = "How do I add a wall to a new Bonsai project?"
    item["equipment_problem"] = "The project has no walls yet."
    item["safety_info"] = (
        "Save a copy of the project before editing so that an edit you cannot undo "
        "does not destroy the only version of the file."
    )
    item["tips"] = ["Name the wall type clearly so it is easy to find in the library later."]
    return item


def record(**changes) -> GeneratedItem:
    item = good_item()
    item.update(changes)
    return GeneratedItem(
        run_id="r",
        trace_id="t",
        item_id="i",
        attempt_id="a",
        slot_id="s",
        category=CATEGORIES[0],
        setup_id="SP-1",
        version_line="VL-current",
        prompt_variant="baseline",
        prompt_hash="h",
        model="m",
        sampler_seed=1,
        offered_sections=[_section(1), _section(2)],
        cited_sections=[_section(1)],
        item=item,
    )


def by_name(results: list[CheckResult], name: str) -> CheckResult:
    (match,) = [r for r in results if r.name == name]
    return match


def failed(results: list[CheckResult]) -> list[str]:
    return [r.name for r in results if not r.passed]


def test_good_item_passes_everything_and_covers_every_dimension():
    results = run_checks(record(), LEX)
    assert failed(results) == []
    assert not any(r.drop for r in results)
    assert {r.dimension for r in results} == {"D1", "D2", "D3", "D4", "D5", "D6"}


def test_d1_short_answer():
    results = run_checks(record(answer="Add a wall from the type library."), LEX)
    result = by_name(results, "answer_length")
    assert (result.dimension, result.passed, result.drop) == ("D1", False, True)


def test_d2_short_or_generic_safety():
    short = run_checks(record(safety_info="Be safe when you work."), LEX)
    assert not by_name(short, "safety_length").passed
    generic = run_checks(
        record(
            safety_info="Be careful. Stay safe. Use common sense. Good luck and take your time, really, yes."
        ),
        LEX,
    )
    assert by_name(generic, "safety_length").passed
    assert not by_name(generic, "safety_not_generic").passed
    assert by_name(generic, "safety_not_generic").dimension == "D2"


def test_d3_unknown_bim_operator():
    results = run_checks(
        record(steps=["Run bim.not_a_real_operator_xyz from the panel.", "Two.", "Three."]), LEX
    )
    result = by_name(results, "bim_operators_known")
    assert (result.dimension, result.passed, result.drop) == ("D3", False, True)
    assert "bim.not_a_real_operator_xyz" in result.detail


def test_d3_known_operator_passes():
    op = known_bim()
    results = run_checks(
        record(tools_required=[f"{op}"], steps=[f"Run {op.upper()} now.", "Two.", "Three."]), LEX
    )
    assert by_name(results, "bim_operators_known").passed


def test_d3_operator_is_checked_against_the_records_version_line():
    older_only = sorted(LEX.bim_ids["VL-older"] - LEX.bim_ids["VL-current"])
    assert older_only, "lexicons should differ between lines"
    results = run_checks(record(steps=[f"Run {older_only[0]}.", "Two.", "Three."]), LEX)
    assert not by_name(results, "bim_operators_known").passed


def test_uncited_section_fails_d3():
    assert by_name(run_checks(record(), LEX), "cited_sections_offered").passed
    results = run_checks(record(), LEX, unoffered_citations=["bonsai-docs:made/up.rst#L1-L2"])
    result = by_name(results, "cited_sections_offered")
    assert (result.dimension, result.passed, result.drop) == ("D3", False, True)
    assert "made/up.rst" in result.detail


def test_d4_refusal_boilerplate():
    results = run_checks(
        record(answer="As an AI, " + " ".join(["I describe the wall tool in this answer."] * 10)),
        LEX,
    )
    result = by_name(results, "no_refusal")
    assert (result.dimension, result.passed, result.drop) == ("D4", False, True)
    for phrase in checks.REFUSAL_PHRASES:
        assert phrase == phrase.lower()


def test_d5_thin_question():
    results = run_checks(record(question="Add wall?", equipment_problem="No walls"), LEX)
    assert not by_name(results, "question_length").passed
    assert not by_name(results, "problem_length").passed
    assert by_name(results, "question_length").dimension == "D5"


def test_d6_generic_short_or_step_copy_tip():
    short = run_checks(record(tips=["Save often."]), LEX)
    assert not by_name(short, "tip_length").passed
    generic = run_checks(record(tips=["Practice makes perfect, so take your time."]), LEX)
    assert not by_name(generic, "tip_not_generic").passed
    step = "Select a wall type in the Type Library and click Add Wall."
    copy = run_checks(
        record(
            steps=[step, "Second step goes here.", "Third step goes here."],
            tips=["Select a wall type in the Type Library, and click Add Wall!"],
        ),
        LEX,
    )
    assert not by_name(copy, "tip_not_step_copy").passed
    assert by_name(copy, "tip_not_step_copy").dimension == "D6"


def test_unknown_blender_menu_is_evidence_not_drop():
    results = run_checks(
        record(steps=["Open Zzyzx Menu > Qqq Panel > Wibble.", "Two.", "Three."]), LEX
    )
    result = by_name(results, "menu_paths_known")
    assert (result.passed, result.drop) == (False, False)
    unknown_op = run_checks(
        record(steps=["Run object.zzyzx_not_real here.", "Two.", "Three."]), LEX
    )
    result = by_name(unknown_op, "blender_operators_known")
    assert (result.passed, result.drop) == (False, False)


def test_known_blender_operator_passes():
    op = next(
        o for o in sorted(LEX.blender_operators["VL-current"]) if "." in o and not o.startswith("*")
    )
    results = run_checks(record(steps=[f"Run {op} here.", "Two.", "Three."]), LEX)
    assert by_name(results, "blender_operators_known").passed


def test_normalization_catches_fullwidth_generic_phrase():
    fullwidth = "Ｂｅ　ｃａｒｅｆｕｌ　and take your time, good luck!"
    results = run_checks(record(tips=[fullwidth]), LEX)
    assert not by_name(results, "tip_not_generic").passed


@pytest.mark.parametrize("phrase", ["be safe", "stay careful", "use common sense"])
def test_extra_generic_phrases_present(phrase):
    assert phrase in checks.GENERIC_PHRASES


def test_lexicons_type():
    assert isinstance(LEX, Lexicons)


@pytest.mark.parametrize("text", ["has an aisle", "was an aid", "has an air gap"])
def test_refusal_matches_whole_words_only(text):
    answer = "The room " + text + " of 1200 mm. " + " ".join(["Add the wall in Bonsai."] * 15)
    assert by_name(run_checks(record(answer=answer), LEX), "no_refusal").passed


def test_real_refusal_still_fails():
    answer = "As an AI, I cannot help. " + " ".join(["Add the wall in Bonsai."] * 15)
    assert not by_name(run_checks(record(answer=answer), LEX), "no_refusal").passed


def test_specific_safety_with_generic_phrase_passes_d2():
    text = (
        "Be careful to save before running Purge, which removes unused types "
        "permanently from the IFC."
    )
    assert by_name(run_checks(record(safety_info=text), LEX), "safety_not_generic").passed


def test_purely_generic_safety_fails_d2():
    text = "Be careful and stay safe. " * 4
    assert not by_name(run_checks(record(safety_info=text), LEX), "safety_not_generic").passed


def test_specific_tip_with_generic_phrase_passes_d6():
    tip = "Follow the steps in the Georeferencing panel in order, setting the CRS before the false origin"
    assert by_name(run_checks(record(tips=[tip]), LEX), "tip_not_generic").passed


def test_purely_generic_tip_fails_d6():
    assert not by_name(
        run_checks(record(tips=["Good luck, take your time!"]), LEX), "tip_not_generic"
    ).passed


def test_generic_phrase_needs_word_boundary():
    assert not checks._phrase_matches("be safe", "please be safely careful")
    assert checks.GENERIC_RESIDUAL_WORDS == 5


def test_unknown_version_line_raises():
    bad = record().model_copy(update={"version_line": "VL-nope"})
    with pytest.raises(ValueError, match="VL-nope"):
        run_checks(bad, LEX)
