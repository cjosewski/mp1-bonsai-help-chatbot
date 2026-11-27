"""The committed generator prompts: v1 is frozen, v1.1 changes only the answer length,
v1.2 (the Phase B correction) adds only the context paragraph, and v2 is the rewrite in
the reference prompt shape (prompts/reference/)."""

import difflib
import re
from pathlib import Path

from bonsai_help import config as config_module
from bonsai_help.checks import MIN_ANSWER_WORDS
from bonsai_help.config import RunConfig, load_prompt

REPO = Path(config_module.__file__).resolve().parents[2]
V1 = "prompts/generator-v1.md"
V1_1 = "prompts/generator-v1.1.md"
V1_2 = "prompts/generator-v1.2.md"
V2 = "prompts/generator-v2.md"
# The baseline collection baseline-2026-11-24-r2 used this text.
V1_1_SHA256 = "ee1dc9a122740ddd7540091da2dd9acd4ea1975278e87590286418b9bcbd75b1"
# Pre-registered for Phase B (DECISIONS.md, November 26, 2026) before any corrected run.
V1_2_SHA256 = "09cb41086f4c164e56d0038950fd58d04ca6e52753d0ee22543bceb111055b63"
# Approved by Chad on November 26, 2026 ("Approved as drafted"), before any run.
V2_SHA256 = "af6d28ffa194cec408a10c537782c1e623c09ee307913c756d1380485ab682f3"
# Runs smoke-2026-11-24-a, smoke-2026-11-24-b and baseline-2026-11-24 used this text.
V1_SHA256 = "04c6d155b534226f51b1256d787e8d715b073e1017e9533d5cd5ee62ec548b36"
FIELDS = (
    "question",
    "answer",
    "equipment_problem",
    "tools_required",
    "steps",
    "safety_info",
    "tips",
    "cited_section_ids",
    "quotes",
    "section_id",
)


def make(prompt_path):
    return RunConfig.model_validate(
        {
            "base_url": "http://127.0.0.1:8080/v1",
            "model": "local-model",
            "embedding_model": "local-embed",
            "seed": 7,
            "api_key_env": "BONSAI_HELP_API_KEY",
            "prompt_path": prompt_path,
        }
    )


def lines(path):
    return (REPO / path).read_text(encoding="utf-8").splitlines(keepends=True)


def test_v1_is_frozen_after_recorded_runs():
    text, digest = load_prompt(make(V1))
    assert digest == V1_SHA256
    assert "60 words" not in text


def test_v1_1_loads_renders_and_names_every_field():
    text, digest = load_prompt(make(V1_1))
    assert digest != V1_SHA256
    rendered = text.format(category="c", setup="k: v", sections="S")
    for field in FIELDS:
        assert field in rendered
    for placeholder in ("{category}", "{setup}", "{sections}"):
        assert placeholder not in rendered


def test_v1_1_states_the_gates_answer_minimum_in_the_instruction_and_the_field():
    text, _ = load_prompt(make(V1_1))
    stated = {int(n) for n in re.findall(r"at least (\d+) words", text)}
    assert stated == {MIN_ANSWER_WORDS}
    assert (
        f'"answer": "a direct answer for the stated setup, at least {MIN_ANSWER_WORDS} words"'
        in text
    )
    instruction = text.split("\n\n", 1)[0]
    assert f"answer it for the\nstated setup in at least {MIN_ANSWER_WORDS} words.\n" in instruction


def test_v1_1_keeps_v1s_wording_and_adds_only_the_length():
    text, _ = load_prompt(make(V1_1))
    assert "complete" not in text
    v1_text, _ = load_prompt(make(V1))
    assert text.count("direct answer") == v1_text.count("direct answer") == 1


def test_v1_1_differs_from_v1_only_in_the_answer_lines():
    diff = [
        line
        for line in difflib.unified_diff(lines(V1), lines(V1_1), n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    removed = [line[1:] for line in diff if line.startswith("-")]
    added = [line[1:] for line in diff if line.startswith("+")]
    assert removed == [
        "stated setup. Phrase the question the way real users ask, not as a docs heading: in their\n",
        '    "answer": "a direct answer for the stated setup",\n',
    ]
    # Only the length is added; the rest of the rewrapped line survives unchanged.
    assert added == [
        f"stated setup in at least {MIN_ANSWER_WORDS} words.\n",
        "Phrase the question the way real users ask, not as a docs heading: in their\n",
        f'    "answer": "a direct answer for the stated setup, at least {MIN_ANSWER_WORDS} words",\n',
    ]


def test_v1_1_is_frozen_after_the_baseline():
    _, digest = load_prompt(make(V1_1))
    assert digest == V1_1_SHA256


def test_v1_2_is_pinned_as_pre_registered():
    _, digest = load_prompt(make(V1_2))
    assert digest == V1_2_SHA256


def test_v1_2_loads_renders_and_names_every_field():
    text, _ = load_prompt(make(V1_2))
    rendered = text.format(category="c", setup="k: v", sections="S")
    for field in FIELDS:
        assert field in rendered
    for placeholder in ("{category}", "{setup}", "{sections}"):
        assert placeholder not in rendered


def test_v1_2_adds_only_the_context_paragraph_to_v1_1():
    diff = [
        line
        for line in difflib.unified_diff(lines(V1_1), lines(V1_2), n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    assert not [line for line in diff if line.startswith("-")]
    added = "".join(line[1:] for line in diff)
    # One paragraph of five lines and its blank separator (difflib may place it first).
    assert sorted(added.splitlines())[0] == "" and len(added.splitlines()) == 6
    assert added.strip().count("\n\n") == 0
    # One paragraph, aimed at D5 (both clauses of its pass anchor): the setup comes from
    # the setup record, and the assumptions the steps rely on are stated.
    words = " ".join(added.split())
    for phrase in (
        "In `answer`, state in plain words the setup",
        "the Blender and Bonsai versions, the IFC schema, the discipline and the model state",
        "any assumption the steps rely on",
        "Take the setup from the Setup, not from the sections",
        "need not be in the sections",
    ):
        assert phrase in words


def test_v1_2_paragraph_follows_the_citation_instruction():
    text, _ = load_prompt(make(V1_2))
    citation = text.index("without the brackets.\n\nIn `answer`, state in plain words")
    assert citation < text.index("In `quotes`, give 1 to 3")


def test_v2_is_pinned_as_approved():
    _, digest = load_prompt(make(V2))
    assert digest == V2_SHA256


def test_v2_renders_with_its_tagged_sections_and_input_last():
    text, _ = load_prompt(make(V2))
    rendered = text.format(category="CAT", setup="k: v", sections="SECTIONS")
    for field in FIELDS:
        assert field in rendered
    # Each section opens on its own line; tag names in the prose do not count.
    order = [
        rendered.index(f"{tag}\n")
        for tag in ("<role>", "<context>", "<rules>", "<output_format>", "\n<category>")
    ]
    assert order == sorted(order)
    assert rendered.index("<category>\nCAT\n</category>") < rendered.index(
        "<setup>\nk: v\n</setup>"
    )
    assert rendered.index("<setup>") < rendered.index("<documents>\nSECTIONS\n</documents>")
    assert "Bonzai" not in text


def test_v2_keeps_the_gates_answer_minimum_and_the_d5_setup_rule():
    text, _ = load_prompt(make(V2))
    assert {int(n) for n in re.findall(r"at least (\d+) words", text)} == {MIN_ANSWER_WORDS}
    words = " ".join(text.split())
    assert "state in plain words the setup it applies to" in words
    assert "any assumption the steps rely on" in words
