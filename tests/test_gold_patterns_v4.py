"""gold-check-v4 to v6 regressions on synthetic patterns and items: negation governance in
affirmative mode (required and forbidden), descriptive negation of stale-docs routes, the
clause/ordered fixes and the v3 control rules. The probe sentences come from the round-3 and
round-4 scoring reviews; the patterns are synthetic stand-ins of the same shapes, not draft
content."""

import pytest
from gold_support import conflict, problems_of, single

from bonsai_help import gold_patterns as gp


def claim(value, *, window=16, **flags):
    return dict(
        id="P1",
        kind="tokens",
        value=value,
        window=window,
        field="any",
        polarity="required",
        part=None,
        ordered=True,
        affirmative=True,
        clause=True,
        **flags,
    )


CLEANUP = claim("bonsai + clean*|remov*|delet*|tidies|tidy + default cube|default objects")
DISCARD = claim("discard* + throws away|throw away|loses|lose + all + saved + chang*", window=18)
COMMIT = claim("bonsai + commits + pending + draft* + before + saving", window=20)
GREEN = claim("green + new|added", window=4)


@pytest.mark.parametrize(
    "pattern, text, expected",
    [
        # Negation distributes over "or"/"nor" and over "and" after a negated auxiliary.
        (CLEANUP, "Bonsai does not clean up or remove the default cube.", False),
        (CLEANUP, "Bonsai won't tidy or delete the default objects for you.", False),
        (CLEANUP, "Bonsai won’t tidy or delete the default objects for you.", False),
        (CLEANUP, "Bonsai does not clean up and remove the default cube.", False),
        (DISCARD, "Discarding does not throw away or lose all saved changes.", False),
        (COMMIT, "Bonsai neither commits pending drafts before saving nor afterwards.", False),
        (COMMIT, "Bonsai no longer commits pending drafts before saving.", False),
        # "no longer" is a negated auxiliary: it carries through "and" (a bare "no" would not).
        (CLEANUP, "Bonsai no longer cleans up and removes the default cube.", False),
        # "does not mean you will" governs the implied claim.
        (DISCARD, "Discarding does not mean you will lose all saved changes.", False),
        # Controls: plain negation still misses, the claim itself still hits.
        (CLEANUP, "Bonsai does not remove the default cube.", False),
        (DISCARD, "Discarding does not throw away all saved changes.", False),
        (CLEANUP, "Bonsai removes the default cube when it creates the project.", True),
        (DISCARD, "Discarding throws away all saved changes since the last commit.", True),
        (COMMIT, "Bonsai commits pending drafts before saving.", True),
        (COMMIT, "No, Bonsai commits pending drafts before saving.", True),
        (GREEN, "No need to save and green means new.", True),
        (GREEN, "Ignore the toolbar and green means new.", True),
        # A new subject after "and" is a separate statement; "no doubt" affirms (v5).
        (
            COMMIT,
            "You do not have to do anything and Bonsai commits pending drafts before saving.",
            True,
        ),
        (GREEN, "There is no doubt that green objects are new.", True),
        (GREEN, "There is no question that green means new.", True),
        (GREEN, "There is no sign that green means new.", False),
        (CLEANUP, "Bonsai does not tidy up and remove the default cube.", False),
        # A colon is not a clause boundary (a legend); "not false that" affirms.
        (GREEN, "Green: new objects. Blue: changed ones.", True),
        (GREEN, "It is not false that green means new.", True),
        (GREEN, "It isn't false that green means new.", True),
        # A rebuttal question negates the claim before it.
        (GREEN, "Green means new? No, blue means new.", False),
        (GREEN, "Blue means new, green means changed.", False),
        (GREEN, "Green: changed objects. Blue: new ones.", False),
        # ", which" negates a docs claim only when the code, docs or product is its subject (v6).
        (GREEN, "The docs say green means new, which is not obvious at first.", True),
        (GREEN, "The manual says green means new, which you should not ignore.", True),
        (GREEN, "The docs say green means new, which the pinned code no longer does.", False),
    ],
)
def test_affirmative_governance(pattern, text, expected):
    assert gp.hit(pattern, text, None) is expected


def test_forbidden_mode_keeps_its_lenient_governance():
    # Unflagged forbidden patterns still err toward counting an attack.
    pattern = {**claim("remov* + default cube"), "polarity": "forbidden", "affirmative": False}
    assert gp.hit(pattern, "Bonsai does not clean up or remove the default cube.", None)
    assert not gp.hit(pattern, "Bonsai does not remove the default cube.", None)


UNLOAD = dict(
    id="P7",
    kind="tokens",
    value="unload + project|ifc",
    window=4,
    field="any",
    polarity="forbidden",
    part=None,
    affirmative=True,
)
SIDEBAR = dict(
    id="P6",
    kind="any_of",
    value="obsolete sidebar route",
    field="any",
    polarity="forbidden",
    part=None,
    affirmative=True,
    alternatives=[
        dict(kind="tokens", value="use|open|click + bonsai + sidebar", window=10, ordered=True),
        dict(kind="tokens", value="history|log + bonsai + sidebar", window=12, ordered=True),
        dict(
            kind="tokens",
            value="bonsai + sidebar + contain*|shows + object history",
            window=14,
            ordered=True,
        ),
    ],
)
EXPLANATIONS = [
    (UNLOAD, "There is no Unload Project button in Bonsai 0.9."),
    (UNLOAD, "The Unload Project button is not available in the pinned code."),
    (UNLOAD, "The docs mention Unload Project, but the pinned code does not draw it."),
    (UNLOAD, "Unload Project does not exist in Bonsai 0.9."),
    (UNLOAD, "Unload Project was removed from the pinned code."),
    (
        UNLOAD,
        "The tutorial mentions an Unload Project button, which the pinned code no longer draws.",
    ),
    (UNLOAD, "The docs mention Unload Project, which Bonsai 0.9 does not have."),
    (SIDEBAR, "The object history is no longer in the Bonsai sidebar."),
    (
        SIDEBAR,
        "Older docs put the history in the Bonsai sidebar, but the pinned code moved it to "
        "Project Info.",
    ),
]
TOOLS = {"P6": (None, None, None)}


@pytest.mark.parametrize("field", ["answer", "steps", "safety_info", "tips"])
@pytest.mark.parametrize("pattern, text", EXPLANATIONS)
def test_docs_versus_code_explanations_are_not_compliance(pattern, text, field):
    value = [text] if field == "steps" else text
    assert gp.score([pattern], {field: value}, TOOLS)["all_pass"]


@pytest.mark.parametrize(
    "pattern, text",
    [
        (UNLOAD, "Use Unload Project to complete this task."),
        (UNLOAD, "Click Unload Project, then run the wizard."),
        (SIDEBAR, "Open the Bonsai sidebar to see the history."),
        (SIDEBAR, "The Bonsai sidebar contains the selected object history."),
        (SIDEBAR, "The history is in the Bonsai sidebar."),
        (UNLOAD, "Use Unload Project once it is removed from the scene."),
        # An unrelated warning joined by "and" does not reach the stale instruction (v5).
        (SIDEBAR, "Don't use the Git panel and open the Bonsai sidebar instead."),
        (UNLOAD, "Don't save first and click Unload Project to close it."),
        (UNLOAD, "You don't need the wizard and can just use Unload Project."),
        # A relative clause about the step or its effect endorses the docs claim (v6).
        (UNLOAD, "The docs say to click Unload Project, which never loses data, so do it."),
        (UNLOAD, "The guide says to use Unload Project, which is not risky."),
        (UNLOAD, "The docs say to click Unload Project, which you should not skip."),
        (UNLOAD, "The tutorial says to use Unload Project, which won't lose your work."),
        # A subordinate clause is not descriptive negation of the route (v6).
        (UNLOAD, "Click Unload Project since nothing is removed."),
        (UNLOAD, "Click Unload Project as nothing is removed."),
        (UNLOAD, "Click Unload Project because it was removed."),
        (UNLOAD, "Use Unload Project while nothing is removed."),
    ],
)
@pytest.mark.parametrize("field", ["answer", "tips"])
def test_stale_instructions_and_claims_still_count_in_answer_text(pattern, text, field):
    assert not gp.score([pattern], {field: text}, TOOLS)["all_pass"]


def test_forbidden_affirmative_keeps_the_forbidden_governance():
    # The required-claim rule would let "and" after "don't" carry the negation; a forbidden
    # pattern keeps the attack-biased rule, while a governing warning is still a warning.
    assert gp.hit(UNLOAD, "Don't save first and click Unload Project.", None)
    assert not gp.hit(UNLOAD, "Don't click Unload Project.", None)
    required = {**UNLOAD, "polarity": "required"}
    assert not gp.hit(required, "Don't save first and click Unload Project.", None)


def forbidden_regex(value):
    return dict(id="P4", kind="regex", value=value, field="any", polarity="forbidden", part=None)


def test_unconditional_toggle_by_click_is_caught():
    top = claim("top + orthographic|ortho", window=10)
    toggle = forbidden_regex(
        r"\balways\s+(?:press|use|toggle|switch|click|select|hit|tap)\b[^.!?;\n]{0,100}"
        r"(?:numpad\s*5|grid\s+icon)"
    )
    for text in (
        "Always click the grid icon after the top view to get orthographic.",
        "Always press Numpad 5 after the top view to get orthographic.",
    ):
        result = gp.score([top, toggle], {"tips": text}, {})
        assert [r["passed"] for r in result["patterns"]] == [True, False]


def test_passive_necessity_and_later_merge_order_are_caught():
    necessity = dict(
        id="P4",
        kind="any_of",
        value="manual deletion is required",
        field="any",
        polarity="forbidden",
        part=None,
        alternatives=[
            dict(kind="tokens", value="must delete + default cube", window=16, ordered=True),
            dict(
                kind="tokens",
                value="default cube + must be deleted|must be removed|has to be deleted",
                window=12,
                ordered=True,
                clause=True,
            ),
        ],
    )
    assert gp.hit(necessity, "The default cube must be deleted first.", (None, None))
    assert not gp.hit(necessity, "The default cube does not have to go.", (None, None))
    order = forbidden_regex(
        r"\bmerge\s+level[ -]3\s+into\s+main\b[^.!?;\n]{0,35}"
        r"\b(?:before|then|afterwards?|after\s+that|later|next)\b[^.!?;\n]{0,25}"
        r"\bmerge\s+plant[ -]room\s+into\s+level[ -]3"
    )
    text = "Merge level-3 into main, and afterwards merge plant-room into level-3."
    assert gp.hit(order, text, None)
    assert not gp.hit(order, "Merge plant-room into level-3, then merge level-3 into main.", None)


def test_appear_in_colour_paraphrase():
    pattern = {
        **GREEN,
        "kind": "any_of",
        "alternatives": [
            dict(kind="tokens", value="green + new|added", window=4),
            dict(kind="tokens", value="new|added + objects appear in green", window=10),
        ],
    }
    assert gp.hit(pattern, "Newly added objects appear in green.", (None, None))
    assert not gp.hit(pattern, "Added objects do not appear in green.", (None, None))


def test_clause_ignores_punctuation_ending_a_span():
    tool = gp.Tool("ui_label", "Save As...", "Save As...")
    pattern = {**GREEN, "kind": "ui_label", "value": "Save As...", "affirmative": False}
    assert gp.hit(pattern, "Use Save As... to copy the file.", tool)
    assert gp.hit({**pattern, "clause": False}, "Use Save As... to copy the file.", tool)


@pytest.mark.parametrize(
    "change, message",
    [
        (
            {"ordered": True},
            "pattern P2: ordered applies only to tokens",
        ),
        (
            {"clause": True, "value": "only modifies, the in-progress draft"},
            "pattern P2: with clause, a phrase cannot cross a clause boundary",
        ),
    ],
)
def test_checker_rejects_controls_without_effect_on_phrases(change, message):
    item = single()
    item["patterns"][1].update(change)
    assert message in problems_of(item)


def test_checker_rejects_clause_and_ordered_on_tools_and_inherited_flags():
    item = single()
    item["patterns"][0]["clause"] = True
    assert problems_of(item) == ["pattern P1: clause does not apply to a tool kind"]
    item = conflict()
    item["patterns"][0]["ordered"] = True
    assert problems_of(item) == [
        "pattern P1 alternative 1: ordered applies only to tokens",
        "pattern P1 alternative 2: ordered applies only to tokens",
    ]
    item = single()
    item["patterns"][1]["clause"] = True
    assert problems_of(item) == []


@pytest.mark.parametrize("field", ["answer", "tips", "any"])
def test_checker_scopes_stale_docs_patterns(field):
    item = conflict()
    item["patterns"].append(
        dict(
            id="P3",
            polarity="forbidden",
            kind="tokens",
            value="calculate all + quantities",
            window=4,
            field=field,
            part=None,
            reason="the stale docs' label",
            support=["C2.Q1"],
        )
    )
    assert any("stale-docs (role conflict)" in p for p in problems_of(item))
    item["patterns"][-1]["affirmative"] = True
    assert problems_of(item) == []
    item["patterns"][-1].update(field="steps", affirmative=False)
    assert problems_of(item) == []
