"""Opt-in scoring constraints on synthetic claims; no draft or gold mutations."""

import json

import pytest
from gold_support import context, derive, problems_of, single

from bonsai_help import gold, gold_review
from bonsai_help import gold_patterns as gp


def rule(value="green + new|added", **flags):
    return dict(
        id="P1",
        kind="tokens",
        value=value,
        window=12,
        field="any",
        polarity="required",
        part=None,
        **flags,
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Green means new, blue means changed.", True),
        ("Green marks newly added objects.", True),
        ("Green objects are new to the current model.", True),
        ("Blue means new, green means changed.", False),
        ("New objects are green.", False),
        ("Green is not new.", False),
        ("Green is never new.", False),
        ("Green means new is false.", False),
        ("It is false that green means new.", False),
        ("It is not true that green means new.", False),
        ("Green is not only new but also highlighted.", True),
        ("Do not save yet; green means new.", True),
        ("Do not save yet but green means new.", True),
        ("No need to save and green means new.", True),
    ],
)
def test_ordered_affirmative_clause_associations(text, expected):
    assert gp.hit(rule(ordered=True, affirmative=True, clause=True), text, None) is expected


@pytest.mark.parametrize("separator", [", ", "; ", " but ", " however ", " | "])
def test_clause_prevents_cross_clause_colour_pairing(separator):
    text = "Blue means new" + separator + "green means changed."
    assert not gp.matches(rule(clause=True), text, None)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Click the checkmark.", True),
        ("Never click the checkmark.", False),
        ("Do not click the checkmark.", False),
        ("Clicking the checkmark is false.", False),
        ("Do not hesitate to click the checkmark.", True),
        ("Ignore the warning and click the checkmark.", True),
        ("Without saving first you can click the checkmark.", True),
        ("Do not only click the checkmark but also inspect the result.", True),
    ],
)
def test_affirmative_actions(text, expected):
    assert gp.matches(rule("click* + checkmark", affirmative=True), text, None) is expected


def test_negative_claims_remain_available_without_affirmative():
    claim = rule("fetch + not automatically merge", ordered=True, clause=True)
    assert gp.matches(claim, "Fetch does not automatically merge branches.", None)
    assert not gp.matches(claim, "Fetched branches cannot merge.", None)


def test_any_of_alternatives_add_constraints_and_inherit_parent_constraints():
    alternatives = [
        dict(kind="tokens", value="green + new|added", window=10, ordered=True),
        dict(kind="tokens", value="new|added + green", window=10, ordered=True),
    ]
    pattern = {
        **rule(),
        "kind": "any_of",
        "alternatives": alternatives,
        "affirmative": True,
        "clause": True,
    }
    for text in ("New objects are shown in green.", "Green marks added objects."):
        assert gp.matches(pattern, text, (None, None))
    for text in ("Blue means new, green means changed.", "New objects are not green."):
        assert not gp.matches(pattern, text, (None, None))
    pattern["ordered"] = True
    alternatives[0]["ordered"] = False
    assert gp.effective_alternative(pattern, alternatives[0])["ordered"] is True
    # A flag on an alternative is enforced without a parent flag too.
    pattern.pop("affirmative")
    for alternative in alternatives:
        alternative["affirmative"] = True
    assert not gp.matches(pattern, "Green is not new.", (None, None))


@pytest.mark.parametrize("field", ["any", *gp.FIELDS])
def test_forbidden_outdated_instruction_in_every_scored_field(field):
    pattern = {
        **rule(),
        "kind": "phrase",
        "value": "Unload Project",
        "polarity": "forbidden",
        "field": field,
    }
    payload_field = "answer" if field == "any" else field
    for text, passed in [
        ("Click Unload Project.", False),
        ("Do not use Unload Project.", True),
        ("Never click Unload Project.", True),
    ]:
        assert gp.score([pattern], {payload_field: text}, {})["all_pass"] is passed
    assert gp.score([pattern], {"question": "Click Unload Project."}, {})["all_pass"]


@pytest.mark.parametrize("field", ["any", *gp.FIELDS])
def test_checker_scopes_forbidden_tools_to_instructions_unless_affirmative(field):
    item = single()
    item["patterns"][2]["field"] = field
    found = problems_of(item)
    if field in gp.INSTRUCTION_FIELDS:
        assert found == []
    else:
        assert found == [
            "pattern P3: a forbidden tool or stale-docs (role conflict) pattern scores steps or "
            "tools_required, or is affirmative in every alternative, so an answer may explain "
            "the docs-versus-code difference"
        ]
    item["patterns"][2]["affirmative"] = True
    assert problems_of(item) == []


def test_false_defaults_preserve_serialized_content_and_digest():
    lane = single()
    before = derive(lane).model_dump()
    for pattern in lane["patterns"]:
        pattern.update(dict.fromkeys(gp.MATCH_FLAGS, False))
    assert derive(lane).model_dump() == before
    legacy = dict(kind="tokens", value="green + new", window=8, support=[])
    assert gold.Alternative(**legacy).model_dump() == legacy
    assert gold.Alternative(**legacy, **dict.fromkeys(gp.MATCH_FLAGS, False)).model_dump() == legacy
    assert gold.Pattern(**rule(ordered=True)).model_dump()["ordered"] is True
    assert '"affirmative"' not in gold.Pattern(**rule()).model_dump_json()
    assert gold.CHECKER == "gold-check-v4"


def test_rendering_discloses_effective_flags_and_actual_alternative_result():
    lane = single()
    lane["patterns"] = [
        {
            **rule(),
            "kind": "any_of",
            "clause": True,
            "affirmative": True,
            "alternatives": [
                dict(kind="tokens", value="green + tick", window=8, ordered=True, support=[])
            ],
        }
    ]
    item = derive(lane)
    rendered, _ = gold_review.render_item(item, context(), None)
    row = next(line for line in rendered.splitlines() if line.startswith("| P1.1 |"))
    for flag in gp.MATCH_FLAGS:
        assert f"{flag}=true" in row
    assert "entry order" in row and "tokens of a clause" in row
    assert row.endswith("| yes |")
    lane["reference"]["steps"][2]["text"] = "Never click the green tick."
    item = derive(lane)
    rendered, _ = gold_review.render_item(item, context(), None)
    row = next(line for line in rendered.splitlines() if line.startswith("| P1.1 |"))
    assert row.endswith("| no |")


def test_default_published_development_content_roundtrips_without_new_flags():
    # Development only: do not use held-out content to develop the matcher.
    from gold_support import ROOT

    content = json.loads((ROOT / "reference/gold/development.json").read_text())
    for item in content["items"]:
        for pattern in item["patterns"]:
            assert gold.Pattern.model_validate(pattern).model_dump() == pattern


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "value, text",
    [
        ("green + new", "Green means changed{nl}Blue means new."),
        ("click* + checkmark", "Click Save{nl}The checkmark is disabled."),
    ],
)
def test_clause_preserves_line_boundaries_without_changing_legacy_matching(newline, value, text):
    text = text.format(nl=newline)
    pattern = rule(value, ordered=True, affirmative=True)
    assert gp.hit(pattern, text, None)  # Existing non-clause normalization is unchanged.
    assert not gp.hit({**pattern, "clause": True}, text, None)
    assert not gp.tokens_spans(text, value, 12, ordered=True, clause=True)
    assert gp.hit(
        {**rule("green + new"), "clause": True},
        f"Blue means changed{newline}Green means new.",
        None,
    )


@pytest.mark.parametrize(
    "kind, value",
    [
        ("phrase", "green means new"),
        ("regex", r"green.*new"),
        ("planted", "green means new"),
        ("ui_label", "green means new"),
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_clause_line_boundaries_apply_to_non_token_matches(kind, value, newline):
    pattern = {**rule(), "kind": kind, "value": value}
    tool = gp.Tool(kind, value, value) if kind == "ui_label" else None
    text = f"green means{newline}new"
    # Legacy phrase matching retains CR; do not change that behavior incidentally.
    assert gp.matches(pattern, text, tool) is (newline == "\n" or kind == "regex")
    assert not gp.matches({**pattern, "clause": True}, text, tool)
    assert gp.matches({**pattern, "clause": True}, f"Other text{newline}green means new", tool)


@pytest.mark.parametrize("placement", ["leaf", "parent", "alternative"])
@pytest.mark.parametrize(
    "text, counted",
    [
        ("Do not only click Unload Project but also restart.", True),
        ("Click Unload Project.", True),
        ("Do not click Unload Project.", False),
        ("Never click Unload Project.", False),
        ("'Unload Project' is false.", False),
    ],
)
def test_forbidden_opt_in_affirmative_policy_applied_once(placement, text, counted):
    leaf = dict(kind="phrase", value="Unload Project")
    pattern = {**rule(), **leaf, "polarity": "forbidden"}
    if placement == "leaf":
        pattern["affirmative"] = True
    else:
        pattern.update(kind="any_of", alternatives=[leaf])
        (pattern if placement == "parent" else leaf)["affirmative"] = True
    assert gp.hit(pattern, text, None) is counted
    assert gp.score([pattern], {"answer": text}, {})["all_pass"] is (not counted)


def test_mixed_alternatives_keep_their_own_affirmative_policy():
    pattern = {
        **rule(),
        "kind": "any_of",
        "polarity": "forbidden",
        "alternatives": [
            dict(kind="phrase", value="Unload Project", affirmative=True),
            dict(kind="phrase", value="Legacy Action"),
        ],
    }
    assert gp.hit(pattern, "Do not only click Unload Project but also restart.", None)
    # An unrelated opted-in alternative must not alter this legacy leaf's policy.
    assert not gp.hit(pattern, "Do not only click Legacy Action but also restart.", None)
    assert gp.hit(pattern, "Click Legacy Action.", None)
    assert not gp.hit(pattern, "Never click Legacy Action.", None)
    legacy = {**rule(), "kind": "phrase", "value": "Unload Project", "polarity": "forbidden"}
    assert not gp.hit(legacy, "Do not only click Unload Project but also restart.", None)
