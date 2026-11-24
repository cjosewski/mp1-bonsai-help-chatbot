"""The committed generator prompts: v1 is frozen, v1.1 changes only the answer length."""

import difflib
import re
from pathlib import Path

from bonsai_help import config as config_module
from bonsai_help.checks import MIN_ANSWER_WORDS
from bonsai_help.config import RunConfig, load_prompt

REPO = Path(config_module.__file__).resolve().parents[2]
V1 = "prompts/generator-v1.md"
V1_1 = "prompts/generator-v1.1.md"
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
