"""Deterministic pre-checks: one rule per test, synthetic items on real lexicon ids."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
from fakes import synthetic_item

from bonsai_help import checks, sampler
from bonsai_help.checks import CheckResult, Lexicons, load_lexicons
from bonsai_help.doc_sources import CATEGORIES, load_config
from bonsai_help.schemas import CitedSection, GeneratedItem

ROOT = Path(__file__).resolve().parents[1]
LEX = load_lexicons(ROOT / "reference")
FIXTURES = ROOT / "tests/fixtures/docs"
_PAGE = "bonsai-docs:src/bonsai/docs/guides/authoring/starting_new_project.rst"
# Two real fixture-slice sections; the item offers both and cites the first.
SECTION_IDS = (f"{_PAGE}#L6-L13", f"{_PAGE}#L14-L18")
GOOD_QUOTE = "This ensures there are no lingering connections or data from previous projects."
_RECORDS = {
    r["id"]: r
    for r in sampler.fixture_sections(load_config(ROOT / "config/doc-sources.json"), FIXTURES)
}


def fixture_section(section_id: str) -> CitedSection:
    r = _RECORDS[section_id]
    return CitedSection(
        id=r["id"], page_sha256=r["page_sha256"], source=r["source"], pin_id=r["pin_id"]
    )


def _section(n: int) -> CitedSection:
    return fixture_section(SECTION_IDS[n - 1])


_TEXTS: dict[tuple, dict[str, str]] = {}


def offered_texts(rec: GeneratedItem) -> dict[str, str]:
    """The record's offered sections read as the gate reads them (cached per section list)."""
    key = tuple(s.model_dump_json() for s in rec.offered_sections)
    if key not in _TEXTS:
        _TEXTS[key] = sampler.section_texts(rec.offered_sections, FIXTURES)
    return _TEXTS[key]


def run_checks(rec, lexicons, unoffered_citations=(), **kwargs):
    """`checks.run_checks` with the record's offered text from the fixture slice."""
    kwargs.setdefault("section_texts", offered_texts(rec))
    return checks.run_checks(rec, lexicons, unoffered_citations, **kwargs)


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


def record(quotes=None, **changes) -> GeneratedItem:
    item = good_item()
    item.update(changes)
    if quotes is None:
        quotes = [{"section_id": SECTION_IDS[0], "text": GOOD_QUOTE}]
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
        generated_at="2026-11-24T00:00:00+00:00",
        offered_sections=[_section(1), _section(2)],
        cited_sections=[_section(1)],
        quotes=quotes,
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


def _menu(steps: list[str], line: str = "VL-current") -> CheckResult:
    rec = record(steps=[*steps, "Second step goes here.", "Third step goes here."])
    return by_name(
        run_checks(rec.model_copy(update={"version_line": line}), LEX), "menu_paths_known"
    )


@pytest.mark.parametrize(
    ("step", "invented"),
    [
        (
            "Open Imaginary Wizard > Fabricated Settings > Bogus Exporter.",
            ["Bogus Exporter", "Fabricated Settings", "Open Imaginary Wizard"],
        ),
        (
            "Go to Nonexistent Panel > Teleport Building.",
            ["Go to Nonexistent Panel", "Teleport Building"],
        ),
        ("Click Zorbo > Flimflam Toolbar.", ["Click Zorbo", "Flimflam Toolbar"]),
        ("Open Bogus Settings > Add Fake Wall.", ["Add Fake Wall", "Open Bogus Settings"]),
    ],
)
def test_invented_menu_labels_are_flagged_even_when_they_contain_lexicon_words(step, invented):
    # Each invented label contains a short lexicon segment ("pan", "port", "tool",
    # "settings", "add") as a substring or a word; none is a lexicon label.
    result = _menu([step])
    assert (result.passed, result.drop) == (False, False)
    assert result.detail == f"not in the pinned UI lexicons: {invented}"


def _lexicon_paths(name: str) -> list[str]:
    import json

    data = json.loads((ROOT / "reference" / "lexicons" / f"{name}.json").read_bytes())
    return sorted(
        e["value"]
        for e in data["entries"]
        if e["kind"] in ("menu_path", "ui_path")
        and checks._MENU_SPLIT.search(e["value"])
        and not any(c in e["value"] for c in ".;:\n")
    )


@pytest.mark.parametrize(
    ("line", "names"),
    [
        ("VL-current", ("blender-manual", "bonsai-docs")),
        ("VL-older", ("blender-manual-4-5", "bonsai-docs-0-8-5-post1")),
    ],
)
def test_every_pinned_manual_and_bonsai_docs_path_passes(line, names):
    paths = [p for name in names for p in _lexicon_paths(name)]
    assert len(paths) > 100
    flagged = [p for p in paths if not _menu([p], line).passed]
    assert flagged == []
    wrapped = [
        p
        for p in paths
        for step in (f"In the editor, open {p} and confirm.", f"Open {p}.", f"Go to {p}.")
        if not _menu([step], line).passed
    ]
    assert wrapped == []


def test_bonsai_docs_install_path_passes():
    # Verbatim from the pinned Bonsai docs (quickstart/installation.rst).
    path = "Topbar --> Edit --> Preferences --> Get Extensions --> Install from Disk"
    assert _menu([f"Go to {path}."]).passed


def test_menu_path_prose_around_a_real_path_passes():
    assert _menu(["In Object Mode, open Object > Apply > All Transforms and confirm."]).passed
    assert _menu(["Open Object > Apply > Scale."]).passed


def test_menu_path_lead_in_must_end_at_a_label_boundary():
    # A real label preceded by an invented capitalized word is not a known path.
    assert not _menu(["Open Bogus Object > Apply."]).passed
    assert not _menu(["Open Object > Apply Bogus."]).passed


@pytest.mark.parametrize(
    "op",
    [
        "bim.fetch_object_passport",
        "bim.select_ifc_clash_results",
        "bim.assign_structural_load_case",
        "bim.annotation_tool",
        "bim.wall_tool",
    ],
)
def test_d3_unregistered_operator_classes_and_workspace_tools_fail(op):
    for line in ("VL-current", "VL-older"):
        rec = record(tools_required=[op]).model_copy(update={"version_line": line})
        result = by_name(run_checks(rec, LEX), "bim_operators_known")
        assert (result.passed, result.drop) == (False, True)
        assert op in result.detail


@pytest.mark.parametrize(
    "op", ["bim.override_move_macro", "bim.enable_editing_roof", "bim.assign_class"]
)
def test_d3_registered_operators_and_macros_pass(op):
    result = by_name(run_checks(record(tools_required=[op]), LEX), "bim_operators_known")
    assert result.passed


@pytest.mark.parametrize("op", ["view3d.select_box", "mesh.select_circle", "object.location_clear"])
def test_wildcard_manual_operators_match_concrete_ids(op):
    results = run_checks(record(steps=[f"Run {op} here.", "Two.", "Three."]), LEX)
    assert by_name(results, "blender_operators_known").passed


def test_wildcard_manual_operators_do_not_accept_unrelated_ids():
    results = run_checks(record(steps=["Run view3d.select_bogus_xyz here.", "Two.", "Three."]), LEX)
    result = by_name(results, "blender_operators_known")
    assert (result.passed, result.drop) == (False, False)
    assert "view3d.select_bogus_xyz" in result.detail


def test_failing_every_evidence_only_check_drops_nothing():
    steps = ["Run object.zzyzx_not_real here.", "Open Zorbo Wizard > Bogus Exporter.", "Three."]
    results = run_checks(record(steps=steps), LEX)
    assert sorted(failed(results)) == ["blender_operators_known", "menu_paths_known"]
    assert [r.name for r in results if r.drop] == []


@pytest.mark.parametrize(
    "step",
    [
        "Fabricated Settings > Export.",
        "Hyper Tool > Wall.",
        "Imaginary Properties > Object > Transform.",
        "Quantum Edit > Preferences > Add-ons.",
        "Teleport Object > Apply > Scale.",
        "Step 1: Fake Object > Apply.",
        "Teleport Mesh > Add > Cube.",
    ],
)
def test_invented_first_word_before_a_real_label_is_flagged(step):
    # The word before the label starts the path, but it is neither lowercase prose nor
    # a lead-in verb, so it is part of an invented label.
    result = _menu([step])
    assert (result.passed, result.drop) == (False, False)


@pytest.mark.parametrize(
    "step",
    [
        "Open Object > Apply > Scale.",
        "Click Object > Apply > Scale.",
        "Select Object > Apply > Scale.",
        "Navigate to Edit > Preferences > Add-ons.",
        "open Object > Apply > Scale.",
        "1) Open Object > Apply > Scale.",
        "Finally, File > Export.",
        "Now, Object > Apply > Scale.",
        "Using Edit > Preferences > Add-ons, enable it.",
        "Access File > Export.",
        "Enter Edit > Preferences > Add-ons.",
        "First open Object > Apply > Scale.",
        "Also File > Export.",
        "Right Click Object > Apply > Scale.",
        "Double Click Object > Apply > Scale.",
        "Afterwards, Object > Apply > Scale.",
    ],
)
def test_lead_in_verb_before_a_real_label_passes(step):
    assert _menu([step]).passed


@pytest.mark.parametrize(
    "step",
    [
        "Fabricated Settings > Export.",
        "Hyper Tool > Wall.",
        "Open Bogus Object > Apply.",
        "Finally, Bogus File > Export.",
        "Right Click Bogus Object > Apply.",
        "Teleport Click Object > Apply > Scale.",
        "Now Bogus, Object > Apply > Scale.",
    ],
)
def test_lead_ins_do_not_admit_invented_words_before_a_label(step):
    # A clause break or lead-in opens the step; a capitalized word after it that is not
    # part of a lexicon label still makes the label invented.
    result = _menu([step])
    assert (result.passed, result.drop) == (False, False)


def test_first_word_ending_in_a_colon_is_a_clause_break():
    # The step-level path pattern already ends a path at ":", so this exercises the
    # part check directly for a part that carries one.
    segments = LEX.menu_segments["VL-current"]
    assert checks._menu_part_known("Afterwards: File", segments, first=True, last=False)
    assert not checks._menu_part_known("Afterwards File", segments, first=True, last=False)


@pytest.mark.parametrize("line", ["VL-current", "VL-older"])
def test_manual_operator_labels_are_menu_labels(line):
    assert _menu(["Click Add > Mesh > Cube, then scale it."], line).passed
    result = _menu(["Click Add > Mesh > Bogus Cube."], line)
    assert (result.passed, result.detail) == (
        False,
        "not in the pinned UI lexicons: ['Bogus Cube']",
    )


@pytest.mark.parametrize("op", ["object.clear", "object.bogusclear", "curve.primitiveadd"])
def test_wildcard_manual_operators_need_a_whole_word_in_the_wildcard(op):
    results = run_checks(record(steps=[f"Run {op} here.", "Two.", "Three."]), LEX)
    result = by_name(results, "blender_operators_known")
    assert (result.passed, result.drop) == (False, False)
    assert op in result.detail


@pytest.mark.parametrize(
    "op",
    [
        "object.rotation_clear",
        "curve.primitive_bezier_curve_add",
        "surface.primitive_nurbs_surface_torus_add",
    ],
)
def test_wildcard_manual_operators_accept_whole_words(op):
    results = run_checks(record(steps=[f"Run {op} here.", "Two.", "Three."]), LEX)
    assert by_name(results, "blender_operators_known").passed


@pytest.mark.parametrize(
    "tip",
    [
        "Take your time to set the CRS before the false origin.",
        "Be careful with Purge: it deletes unused types.",
    ],
)
def test_short_specific_tip_with_a_stock_phrase_is_not_generic(tip):
    # Every remaining word counts toward the residual, so a short specific tip that
    # opens with a stock phrase is not dropped as generic.
    assert by_name(run_checks(record(tips=[tip]), LEX), "tip_not_generic").passed


def test_two_paths_joined_by_prose_are_checked_separately():
    assert _menu(["Go to Edit > Preferences, then Add-ons > Install."]).passed
    result = _menu(["Go to Edit > Preferences, then Bogus Wizard > Install."])
    assert result.detail == "not in the pinned UI lexicons: ['then Bogus Wizard']"


# --- quotes_verbatim (D3, drop): quotes against the offered fixture text ----------------

JOIN = "blender-manual:manual/scene_layout/object/editing/join.rst#L1-L26"


def quoted(*quotes: tuple[str, str], cited: list[str] | None = None) -> CheckResult:
    """The quote check on the good record with these (section id, text) quotes."""
    rec = record(quotes=[{"section_id": sid, "text": text} for sid, text in quotes])
    if cited is not None:
        sections = [fixture_section(s) for s in cited]
        rec = rec.model_copy(update={"offered_sections": sections, "cited_sections": sections})
    return by_name(run_checks(rec, LEX), "quotes_verbatim")


def test_quote_copied_from_a_cited_section_passes():
    result = quoted((SECTION_IDS[0], GOOD_QUOTE))
    assert (result.dimension, result.passed, result.drop) == ("D3", True, False)
    assert result.detail == "1 quotes verbatim"
    # A passage across the section's line breaks and list markup is still verbatim.
    assert quoted((SECTION_IDS[0], "- Launch a fresh instance of Blender. This ensures")).passed


def test_quote_from_an_offered_but_uncited_section_fails():
    text = "There are two main methods to create a new IFC project:"
    result = quoted((SECTION_IDS[1], text))
    assert (result.dimension, result.passed, result.drop) == ("D3", False, True)
    assert result.detail == f"quote 0: section {SECTION_IDS[1]!r} is offered but not cited"


def test_quote_from_a_section_never_offered_fails():
    result = quoted((SECTION_IDS[0], GOOD_QUOTE), ("bonsai-docs:invented.rst#L1-L2", GOOD_QUOTE))
    assert not result.passed and result.drop
    assert result.detail == "quote 1: section 'bonsai-docs:invented.rst#L1-L2' was not offered"


def test_quote_of_fewer_than_five_words_fails():
    result = quoted((SECTION_IDS[0], "no lingering connections or"))
    assert not result.passed and result.drop
    assert result.detail == "quote 0: 4 words, need 5"
    assert quoted((SECTION_IDS[0], "there are no lingering connections")).passed


@pytest.mark.parametrize(
    "text",
    [
        "This makes sure there are no lingering connections or data.",  # paraphrase
        "This ensures there are no lingering connections or data from earlier projects.",
        "Close any open Blender windows. This ensures",  # joined from two places
        "this ensures there are no lingering connections",  # case differs
    ],
)
def test_paraphrased_or_altered_quote_fails(text):
    result = quoted((SECTION_IDS[0], text))
    assert not result.passed and result.drop
    assert result.detail == "quote 0: not verbatim in its section"


@pytest.mark.parametrize(
    "text",
    [
        "nsures there are no lingering connections",  # starts inside "ensures"
        "This ensures there are no linger",  # ends inside "lingering"
        "ensures there are no lingering connections or data from previous project",
    ],
)
def test_quote_that_starts_or_ends_inside_a_word_fails(text):
    result = quoted((SECTION_IDS[0], text))
    assert not result.passed and result.drop
    assert result.detail == "quote 0: starts or ends inside a word of its section"


def test_quote_whose_whitespace_differs_only_passes():
    text = "This  ensures there\nare no\tlingering \u00a0connections or data"
    assert quoted((SECTION_IDS[0], text)).passed


def test_quote_in_another_unicode_normalization_form_passes():
    composed = "each one will keep its subtype (NURBS or Bézier)."
    decomposed = unicodedata.normalize("NFD", composed)
    assert decomposed != composed
    assert quoted((JOIN, composed), cited=[JOIN]).passed
    assert quoted((JOIN, decomposed), cited=[JOIN]).passed


def test_quote_detail_names_each_failing_quote_and_never_echoes_long_text():
    long_id = "bonsai-docs:" + "x" * 200 + ".rst#L1-L2"
    secret = "A long synthetic passage that the detail must never repeat " * 5
    result = quoted(
        (SECTION_IDS[0], GOOD_QUOTE),
        (SECTION_IDS[0], secret),
        (long_id, GOOD_QUOTE),
    )
    assert not result.passed
    first, second = result.detail.split("; ")
    assert first == "quote 1: not verbatim in its section"
    assert second.startswith("quote 2: section 'bonsai-docs:xxx")
    assert second.endswith("…' was not offered")
    assert "A long synthetic passage" not in result.detail
    assert len(second) < 80 + len("quote 2: section '' was not offered") + 1


def test_quote_check_reads_the_text_it_is_given_not_the_record():
    # The texts come from the fixture slice; another text for the same id changes the result.
    rec = record()
    texts = dict(offered_texts(rec))
    assert by_name(run_checks(rec, LEX, section_texts=texts), "quotes_verbatim").passed
    texts[SECTION_IDS[0]] = "Some other section text that says something else entirely."
    assert not by_name(run_checks(rec, LEX, section_texts=texts), "quotes_verbatim").passed
    with pytest.raises(ValueError, match="no offered text"):
        run_checks(rec, LEX, section_texts={})


# Synthetic section text: an operator id, a file name and sentence periods.
TOKENS = (
    "Start with the tool. Use bim.add_wall here, then save it as model.ifc. Then close the file."
)


def quoted_in(section_text: str, text: str) -> CheckResult:
    """The quote check on a quote of the good record's cited section, read as `section_text`."""
    rec = record(quotes=[{"section_id": SECTION_IDS[0], "text": text}])
    texts = dict(offered_texts(rec))
    texts[SECTION_IDS[0]] = section_text
    return by_name(run_checks(rec, LEX, section_texts=texts), "quotes_verbatim")


@pytest.mark.parametrize(
    "text",
    [
        "with the tool. Use bim",  # ends inside the operator id bim.add_wall
        "with the tool. Use bim.",  # the period joins bim and add_wall
        "add_wall here, then save it",  # starts inside bim.add_wall
        ".add_wall here, then save it",
        "here, then save it as model",  # ends inside the file name model.ifc
        "ifc. Then close the file.",  # starts inside model.ifc
    ],
)
def test_quote_may_not_start_or_end_inside_an_operator_id_or_file_name(text):
    result = quoted_in(TOKENS, text)
    assert not result.passed and result.drop
    assert result.detail == "quote 0: starts or ends inside a word of its section"


@pytest.mark.parametrize(
    "text",
    [
        "Start with the tool. Use bim.add_wall",  # a whole operator id
        "bim.add_wall here, then save it",
        "then save it as model.ifc.",  # the last period ends the sentence
        "then save it as model.ifc",
        "model.ifc. Then close the file.",  # a whole file name, to the section's end
        "Start with the tool. Use",
    ],
)
def test_quote_of_whole_operator_ids_file_names_and_sentences_passes(text):
    assert quoted_in(TOKENS, text).passed


@pytest.mark.parametrize(
    "text",
    [
        "Session --------------------------- - Close any",  # heading adornment and a bullet
        "--------------------------- - Close any open",
    ],
)
def test_adornment_and_bullets_do_not_count_toward_the_quote_minimum(text):
    # The real fixture section: a heading, its RST underline and a bullet list.
    result = quoted((SECTION_IDS[0], text))
    assert not result.passed and result.drop
    assert result.detail == "quote 0: 3 words, need 5"


def test_symbol_only_tokens_never_make_up_the_minimum():
    section = "Some list:\n\n* - === Use bim.add_wall here, then save it."
    # Use, bim.add_wall, here, then, save: five words; the operator id is one word.
    assert quoted_in(section, "* - === Use bim.add_wall here, then save").passed
    result = quoted_in(section, "* - === Use bim.add_wall here,")
    assert result.detail == "quote 0: 3 words, need 5"


GIT = "bonsai-docs:src/bonsai/docs/guides/authoring/git_support.rst#L97-L128"


@pytest.mark.parametrize(
    "text",
    [
        "emojis etc... Branch names can",  # cuts "can't" to "can", dropping the negation
        "t contain spaces, and have some",  # starts inside "can't"
        "options, but don't want to mess",  # ends inside "mess-up"
        "up the primary design, you can",  # starts inside "mess-up"
    ],
)
def test_quote_may_not_cut_a_word_at_an_apostrophe_or_hyphen(text):
    # The real fixture section: "Branch names can't contain spaces" and "mess-up".
    result = quoted((GIT, text), cited=[GIT])
    assert not result.passed and result.drop
    assert result.detail == "quote 0: starts or ends inside a word of its section"


@pytest.mark.parametrize(
    "text",
    [
        "Branch names can't contain spaces, and",
        "but don't want to mess-up the primary design,",
        "have some other minor limitations - Bonsai will not",  # a spaced dash is a boundary
        "select the revision you are interested-in and switch as before.",
    ],
)
def test_quote_of_whole_contractions_and_hyphenated_words_passes(text):
    assert quoted((GIT, text), cited=[GIT]).passed


# Synthetic section text: a curly apostrophe, a slash path, a negating prefix, possessives.
JOINED = (
    "Branch names can’t contain spaces. Choose File/Import, then pick the IFC file. "
    "Use the non-destructive workflow to keep edits. Check the walls' types and the "
    "'Walls' panel before export."
)


@pytest.mark.parametrize(
    "text",
    [
        "can\u2019t contain spaces. Choose File",  # ends inside File/Import
        "Import, then pick the IFC file.",  # starts inside File/Import
        "destructive workflow to keep edits.",  # drops the negating prefix "non-"
        "t contain spaces. Choose File/Import,",  # starts inside can\u2019t
    ],
)
def test_quote_may_not_cut_a_curly_contraction_a_slash_path_or_a_prefix(text):
    result = quoted_in(JOINED, text)
    assert not result.passed and result.drop
    assert result.detail == "quote 0: starts or ends inside a word of its section"


@pytest.mark.parametrize(
    "text",
    [
        "Branch names can’t contain spaces.",
        "spaces. Choose File/Import, then pick",
        "Use the non-destructive workflow to keep",
        "keep edits. Check the walls",  # a trailing possessive apostrophe is a boundary
        "Check the walls' types and the 'Walls'",  # quote marks around a word
        "the 'Walls' panel before export.",
    ],
)
def test_quote_of_whole_joined_words_or_ending_at_a_possessive_passes(text):
    assert quoted_in(JOINED, text).passed


_GEO = "bonsai-docs:src/bonsai/docs/guides/authoring/advanced_modeling/georeferencing.rst"
GEO_CRS, GEO_LIMITS = f"{_GEO}#L10-L42", f"{_GEO}#L231-L255"
LARGE = "bonsai-docs:src/bonsai/docs/guides/viewing/dealing_with_large_models.rst#L1-L20"
SAVING = f"{_PAGE}#L86-L133"


@pytest.mark.parametrize(
    ("section_id", "text"),
    [
        (GEO_LIMITS, "that lengths greater than 5"),  # "5,000" cut to "5"
        (GEO_LIMITS, "000 meters start to accumulate"),  # starts inside "5,000"
        (LARGE, "Number of elements exceeding 50"),  # "50,000" cut to "50"
        (LARGE, "000 loaded in the scene,"),
        (GEO_CRS, "56 will be named EPSG"),  # ends inside "EPSG:7856"
        (GEO_CRS, "7856. You can check whether"),  # starts inside "EPSG:7856"
        (SAVING, "Using the keyboard shortcut `Ctrl"),  # ends inside "Ctrl+S"
        (SAVING, "S` or `File > Save IFC Project`"),  # starts inside "Ctrl+S"
    ],
)
def test_quote_may_not_cut_a_number_a_code_or_a_key_combination(section_id, text):
    # The real fixture sections: "5,000 meters", "50,000 loaded", "EPSG:7856", "`Ctrl+S`".
    result = quoted((section_id, text), cited=[section_id])
    assert not result.passed and result.drop
    assert result.detail == "quote 0: starts or ends inside a word of its section"


@pytest.mark.parametrize(
    ("section_id", "text"),
    [
        (GEO_LIMITS, "that lengths greater than 5,000"),
        (GEO_LIMITS, "5,000 meters start to accumulate"),
        (LARGE, "Number of elements exceeding 50,000 loaded"),
        (GEO_CRS, "MGA Zone 56 will be named EPSG:7856."),  # sentence-final
        (GEO_CRS, "named EPSG:7856. You can check whether"),
        (SAVING, "Using the keyboard shortcut `Ctrl+S`"),
        (SAVING, "`Ctrl+S` or `File > Save IFC Project`"),
    ],
)
def test_quote_of_whole_numbers_codes_and_key_combinations_passes(section_id, text):
    assert quoted((section_id, text), cited=[section_id]).passed


# Synthetic section text: commas, colons and plus signs between letters or with spaces.
SPACED = (
    "Pick walls,slabs and roofs to begin. Note: press Ctrl + S to save the file. "
    "Set the origin to (0,0,0) first, then press Shift+click on the wall to select it."
)


@pytest.mark.parametrize(
    "text",
    [
        "Pick walls,slabs and roofs to begin.",  # a comma between letters is not a number
        "slabs and roofs to begin. Note: press",
        "Note: press Ctrl + S to",  # a spaced plus is a boundary
        "S to save the file.",
        "Set the origin to (0,0,0) first,",
        "then press Shift+click on the wall",
    ],
)
def test_quote_at_a_comma_between_letters_or_a_spaced_joiner_passes(text):
    assert quoted_in(SPACED, text).passed


@pytest.mark.parametrize(
    "text",
    [
        "the file. Set the origin to (0",  # ends inside "(0,0,0)"
        "0) first, then press Shift",  # starts inside "(0,0,0)", ends inside "Shift+click"
        "click on the wall to select it.",  # starts inside "Shift+click"
    ],
)
def test_quote_may_not_cut_a_coordinate_triple_or_a_modifier_click(text):
    result = quoted_in(SPACED, text)
    assert not result.passed and result.drop
    assert result.detail == "quote 0: starts or ends inside a word of its section"


# --- quotes_verbatim: RST inline markup is not part of the words --------------------------
# Batch 1 of the first baseline collection dropped 29 of 70 items on quotes_verbatim, with
# 47 failing quotes in those 29 items; 41 pass once inline markup is removed (bold, literal,
# roles, explicit targets, links, emphasis); 6 still fail, 4 paraphrased and 2 shorter than
# 5 words.

EXPLORE = "bonsai-docs:src/bonsai/docs/quickstart/explore_model.rst#L58-L120"


@pytest.mark.parametrize(
    "text",
    [
        # The real section: "(:kbd:`MMB`) to **Orbit**." and ":kbd:`Shift-MMB` to **Pan**."
        "panel and click and drag the Middle Mouse Button (MMB) to Orbit.",
        "Scroll the mousewheel to Zoom, and use Shift-MMB to Pan.",
        # A role that spans a line break in the section, and the arrow kept as prose.
        "by clicking on 3D Viewport --> View then Frame Selected.",
        # Markup kept on one side and dropped on the other.
        "Scroll the mousewheel to **Zoom**, and use Shift-MMB to Pan.",
    ],
)
def test_quote_that_drops_rst_inline_markup_passes(text):
    result = quoted((EXPLORE, text), cited=[EXPLORE])
    assert result.passed, result.detail


@pytest.mark.parametrize(
    "text",
    [
        "panel and click and drag the Middle Mouse Button (:kbd:`MMB`) to **Orbit**.",
        "Scroll the mousewheel to **Zoom**, and use :kbd:`Shift-MMB` to **Pan**.",
        # Cut inside a role or a strong span, as the check allowed before.
        "can use the **Navigate Gizmo** on the top right corner of the",
        "and use :kbd:`Shift-MMB` to **Pan**",
    ],
)
def test_quote_that_keeps_rst_inline_markup_still_passes(text):
    result = quoted((EXPLORE, text), cited=[EXPLORE])
    assert result.passed, result.detail


@pytest.mark.parametrize(
    "text",
    [
        "drag the Middle Mouse Button (MMB) to orbit the view.",  # paraphrase
        "Scroll the mouse wheel to Zoom, and use Shift-MMB to Pan.",
        "Use Shift-MMB to Pan and the mousewheel to Zoom.",  # reordered
        "Middle Mouse Button (kbd MMB) to Orbit.",  # the role name is not a word of it
    ],
)
def test_paraphrase_still_fails_once_markup_is_removed(text):
    result = quoted((EXPLORE, text), cited=[EXPLORE])
    assert not result.passed and result.drop
    assert result.detail == "quote 0: not verbatim in its section"


@pytest.mark.parametrize(
    "text",
    [
        "MMB to Pan. If you have a",  # starts inside :kbd:`Shift-MMB`
        "and use Shift to Pan. If",  # not verbatim either way
        "use Shift-MMB to Pa",  # ends inside **Pan**
    ],
)
def test_markup_removal_never_lets_a_partial_token_quote_pass(text):
    result = quoted((EXPLORE, text), cited=[EXPLORE])
    assert not result.passed and result.drop


def test_partial_token_quote_reports_the_boundary_after_markup_removal():
    result = quoted((EXPLORE, "MMB to Pan. If you have a"), cited=[EXPLORE])
    assert result.detail == "quote 0: starts or ends inside a word of its section"


# Synthetic section text with every inline-markup form the normalisation removes.
MARKUP = (
    "Select **Walls** and *slabs* first. Run ``bim.add_wall`` or the `default role` text. "
    "Press :kbd:`Ctrl-S` and see :ref:`the saving guide <saving-target>` for details. "
    "Read the `Bonsai docs`_ and `the manual <https://example.org/>`__ before you start."
)


@pytest.mark.parametrize(
    "text",
    [
        "Select Walls and slabs first.",
        "Run bim.add_wall or the default role text.",
        "Press Ctrl-S and see the saving guide for details.",
        "Read the Bonsai docs and the manual before you start.",
        "Select **Walls** and slabs first.",
    ],
)
def test_every_inline_markup_form_is_removed_but_its_text_kept(text):
    assert quoted_in(MARKUP, text).passed


@pytest.mark.parametrize(
    "text",
    [
        "see the saving guide saving-target for details.",  # an explicit target is not text
        "Press kbd Ctrl-S and see",
        "Read the Bonsai docs_ and the manual",
        "Run bim add_wall or the default",  # the operator id is kept whole
    ],
)
def test_markup_removal_keeps_no_role_names_targets_or_split_ids(text):
    assert not quoted_in(MARKUP, text).passed


@pytest.mark.parametrize(
    "text",
    [
        # A target the section does not have, hidden in a role the section uses.
        "Press :ref:`Ctrl-S <and then delete every wall in the model>` and see the saving guide",
        # A target the section does not have, hidden in a link or in interpreted text.
        "Press `Ctrl-S <evil fabricated target words>`_ and see the saving guide",
        "Press `Ctrl-S <evil fabricated target words>` and see the saving guide",
        # A role the section never uses: its name is not a word of the section.
        "Press :madeup_claim_here:`Ctrl-S` and see the saving guide",
    ],
)
def test_quote_cannot_add_words_inside_markup_it_made_up(text):
    section = "Press :kbd:`Ctrl-S` and see :ref:`the saving guide <saving-target>` for details."
    result = quoted_in(section, text)
    assert not result.passed and result.drop
    assert result.detail == "quote 0: not verbatim in its section"


@pytest.mark.parametrize(
    "text",
    [
        # The section's own target, in the same place, with other markup dropped.
        "Press Ctrl-S and see :ref:`the saving guide <saving-target>` for details.",
        "Press Ctrl-S and see the saving guide <saving-target> for details.",
        # A role the section uses, around words the section has.
        "Press :kbd:`Ctrl-S` and see the saving guide for details.",
        "Press Ctrl-S and see :ref:`the saving guide` for details.",
    ],
)
def test_quote_may_keep_the_sections_own_markup_and_targets(text):
    section = "Press :kbd:`Ctrl-S` and see :ref:`the saving guide <saving-target>` for details."
    assert quoted_in(section, text).passed


def test_quote_may_not_move_a_target_the_section_has():
    section = "Press :kbd:`Ctrl-S` and see :ref:`the saving guide <saving-target>` for details."
    text = "Press :ref:`Ctrl-S <saving-target>` and see the saving guide for details."
    result = quoted_in(section, text)
    assert not result.passed
    assert result.detail == "quote 0: not verbatim in its section"


# Synthetic section text: angle brackets in interpreted text that is not a hyperlink, and
# in a role that takes no target, are words a reader sees.
SHOWN = "Set the `IFC class <IfcWall>` field and press :kbd:`Shift <A>` to add walls to the model."


@pytest.mark.parametrize(
    "text",
    [
        "Set the IFC class <IfcWall> field and press Shift <A> to add",
        "Set the `IFC class <IfcWall>` field and press :kbd:`Shift <A>` to add",
    ],
)
def test_angle_brackets_outside_a_hyperlink_or_reference_are_kept(text):
    assert quoted_in(SHOWN, text).passed


@pytest.mark.parametrize(
    "text",
    [
        "Set the IFC class field and press",
        "field and press Shift to add walls",
    ],
)
def test_dropping_angle_brackets_a_reader_sees_still_fails(text):
    result = quoted_in(SHOWN, text)
    assert not result.passed
    assert result.detail == "quote 0: not verbatim in its section"


# Synthetic section text: asterisks and backticks that are not paired inline markup.
ORDINARY = (
    "Multiply 5 * 3 to get the count. Use bim.add_* wildcards with *args, as a list. "
    "* A bullet item. The file is C:/models/*.ifc in the `models folder. Type ``*.ifc`` here."
)


@pytest.mark.parametrize(
    "text",
    [
        "Multiply 5 * 3 to get the count.",
        "Use bim.add_* wildcards with *args, as",
        "* A bullet item. The file is C:/models/*.ifc in",
        "in the `models folder. Type",
        "the `models folder. Type *.ifc here.",  # a literal keeps the asterisk inside it
    ],
)
def test_unpaired_asterisks_and_backticks_are_kept(text):
    assert quoted_in(ORDINARY, text).passed


@pytest.mark.parametrize(
    "text",
    [
        "Multiply 5 3 to get the count.",
        "Use bim.add_ wildcards with args, as",
        "A bullet item. The file is C:/models/.ifc in",
        "in the models folder. Type",
        "the `models folder. Type .ifc here.",
    ],
)
def test_dropping_an_ordinary_asterisk_or_backtick_still_fails(text):
    assert not quoted_in(ORDINARY, text).passed


@pytest.mark.parametrize(
    ("raw", "plain"),
    [
        ("**Orbit**", "Orbit"),
        ("(:kbd:`MMB`)", "(MMB)"),
        (":kbd:`Ctrl` + :kbd:`Tab`", "Ctrl + Tab"),
        (":py:func:`ifcopenshell.open`", "ifcopenshell.open"),
        (":ref:`text <target>`", "text"),
        (":doc:`text <target>`", "text"),
        (":py:func:`open <ifcopenshell.open>`", "open"),
        ("`text <https://example.org/>`_", "text"),
        ("`text <target>`__", "text"),
        ("`text <target>`", "text <target>"),  # not a hyperlink: the reader sees the target
        (":kbd:`Shift <A>`", "Shift <A>"),  # :kbd: takes no target
        ("``*args*``", "*args*"),
        ("`Bonsai`_ and `docs`__", "Bonsai and docs"),
        ("5 * 3 and 2 ** 8", "5 * 3 and 2 ** 8"),
        ("a*b*c and x**y**z", "a*b*c and x**y**z"),
        ("bim.add_* and *.ifc", "bim.add_* and *.ifc"),
        ("C:/models/*.ifc and C:/other/*.ifc", "C:/models/*.ifc and C:/other/*.ifc"),
        ("**Shortcut**: :kbd:`Shift` + :kbd:`A`", "Shortcut: Shift + A"),
        ("snake_case_ and word_", "snake_case_ and word_"),
        ("** spaced ** and * spaced *", "** spaced ** and * spaced *"),
    ],
)
def test_inline_markup_form(raw, plain):
    assert checks.strip_inline_markup(raw) == plain


def test_inline_markup_never_pairs_across_a_blank_line():
    section = "Say *one thing here and now.\n\nThen two more things* follow it."
    assert quoted_in(section, "Say *one thing here and now. Then two").passed
    assert not quoted_in(section, "Say one thing here and now. Then two").passed
