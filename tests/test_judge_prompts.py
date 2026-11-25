"""Judge prompt v1: the accepted rubric verbatim, exact placeholders, true check premises."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from fakes import synthetic_item

from bonsai_help import checks, rubric, sampler
from bonsai_help.config import REPOSITORY
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.doc_sources import load_config as load_doc_sources
from bonsai_help.evaluation_schemas import Judgment
from bonsai_help.judge_config import (
    JUDGE_PLACEHOLDERS,
    JudgeConfig,
    load_judge_prompt,
)
from bonsai_help.schemas import CitedSection, GeneratedItem

V1 = REPOSITORY / "prompts" / "judge-v1.md"
RUBRIC = rubric.load_rubric(REPOSITORY / "config" / "rubric.json")
FIXTURES = REPOSITORY / "tests" / "fixtures" / "docs"
LEX = checks.load_lexicons(REPOSITORY / "reference")
LINE = "VL-current"
_PAGE = "bonsai-docs:src/bonsai/docs/guides/authoring/starting_new_project.rst"
SECTION_ID = f"{_PAGE}#L6-L13"
QUOTE = "This ensures there are no lingering connections or data from previous projects."
REQUIRED = ("category", "setup", "item", "quotes", "sections", "checks", "fence")
# Pinned on November 25, 2026, after Chad's answers to B7 Open questions 1, 3 and 4
# (docs/DECISIONS.md, judge v1 iteration-log record); every judge run uses this text.
V1_SHA256 = "d8d1604f94d40a40b28a0973257b0db82654549665f3f9b279862d2d04342471"


def config_for(prompt: Path | str) -> JudgeConfig:
    return JudgeConfig.model_validate(
        {
            "base_url": "http://127.0.0.1:8082/v1",
            "model": "synthetic-judge-model",
            "purpose": "smoke",
            "api_key_env": "BONSAI_HELP_JUDGE_API_KEY",
            "prompt_path": str(prompt),
        }
    )


def v1_text() -> str:
    text, _, _ = load_judge_prompt(config_for("prompts/judge-v1.md"), with_examples=False)
    return text


def rendered_v1() -> str:
    return v1_text().format(**{name: f"<{name} value>" for name in REQUIRED})


def section(text: str, heading: str) -> str:
    """The body of one `## heading` section of a prompt, up to the next `## ` heading."""
    start = text.index(f"\n## {heading}\n") + len(f"\n## {heading}\n")
    end = text.find("\n## ", start)
    return text[start:] if end < 0 else text[start:end]


def write_prompt(tmp_path: Path, body: str, name: str = "judge-v9.md") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def all_placeholders(*names: str) -> str:
    return " ".join("{" + name + "}" for name in names) + " {{literal braces}}"


# --- placeholders -------------------------------------------------------------------------


def test_judge_prompt_placeholders(tmp_path):
    assert JUDGE_PLACEHOLDERS == REQUIRED
    good = write_prompt(tmp_path, all_placeholders(*REQUIRED) + " {fence} again")
    text, digest, version = load_judge_prompt(config_for(good), with_examples=False)
    assert digest == hashlib.sha256(good.read_bytes()).hexdigest()
    assert version == "judge-v9" and text.startswith("{category}")
    with_pool = write_prompt(tmp_path, all_placeholders(*REQUIRED, "examples"), "judge-v10.md")
    assert load_judge_prompt(config_for(with_pool), with_examples=True)[2] == "judge-v10"

    for missing in REQUIRED:
        bad = write_prompt(tmp_path, all_placeholders(*(n for n in REQUIRED if n != missing)))
        with pytest.raises(ValueError, match=f"missing.*{{{missing}}}"):
            load_judge_prompt(config_for(bad), with_examples=False)
    for unknown in ("{seed}", "{0}", "{}", "{setup.id}", "{item[0]}", "{model}"):
        bad = write_prompt(tmp_path, all_placeholders(*REQUIRED) + " " + unknown)
        with pytest.raises(ValueError, match="unknown placeholder"):
            load_judge_prompt(config_for(bad), with_examples=False)
    for malformed in ("{fence", "fence}", "{fence!r}", "{fence:>20}", "{{fence}"):
        bad = write_prompt(tmp_path, all_placeholders(*REQUIRED) + " " + malformed)
        with pytest.raises(ValueError, match="malformed"):
            load_judge_prompt(config_for(bad), with_examples=False)
    # An escaped placeholder is literal text, so the real one is still missing.
    escaped = write_prompt(tmp_path, all_placeholders(*REQUIRED).replace("{fence}", "{{fence}}"))
    with pytest.raises(ValueError, match="missing.*{fence}"):
        load_judge_prompt(config_for(escaped), with_examples=False)
    # {examples} if and only if the run has an example pool.
    with pytest.raises(ValueError, match="no example pool"):
        load_judge_prompt(config_for(with_pool), with_examples=False)
    with pytest.raises(ValueError, match="missing.*{examples}"):
        load_judge_prompt(config_for(good), with_examples=True)


def test_judge_prompt_file_errors_name_no_path(tmp_path):
    absent = tmp_path / "secret-dir-sentinel" / "judge-v1.md"
    with pytest.raises(ValueError, match="cannot read the judge prompt") as caught:
        load_judge_prompt(config_for(absent), with_examples=False)
    assert "secret-dir-sentinel" not in str(caught.value)
    latin = tmp_path / "judge-v1.md"
    latin.write_bytes(all_placeholders(*REQUIRED).encode() + b" \xe9")
    with pytest.raises(ValueError, match="not UTF-8"):
        load_judge_prompt(config_for(latin), with_examples=False)


def test_judge_v1_loads_and_renders_every_placeholder():
    text, digest, version = load_judge_prompt(config_for(V1), with_examples=False)
    assert version == "judge-v1"
    assert digest == hashlib.sha256(V1.read_bytes()).hexdigest()
    rendered = rendered_v1()
    for name in REQUIRED:
        assert f"<{name} value>" in rendered
        assert "{" + name + "}" not in rendered


# --- the rubric, verbatim -----------------------------------------------------------------


def rubric_strings() -> list[str]:
    strings = list(RUBRIC.labeling_rules)
    for dimension in RUBRIC.dimensions:
        notes = dimension.labeling_notes
        strings += [dimension.pass_anchor, dimension.fail_anchor]
        strings += [*notes.check, *notes.common_fail_patterns, *notes.borderline]
    return strings


def test_judge_v1_hash_is_pinned():
    _, digest, version = load_judge_prompt(config_for(V1), with_examples=False)
    assert (version, digest) == ("judge-v1", V1_SHA256)
    assert hashlib.sha256(V1.read_bytes()).hexdigest() == V1_SHA256


def test_judge_v1_carries_the_accepted_rubric_verbatim():
    assert RUBRIC.status == "chad_accepted"
    raw, rendered = V1.read_text(encoding="utf-8"), rendered_v1()
    strings = rubric_strings()
    assert len(strings) == 5 + 6 * 2 + sum(
        len(d.labeling_notes.check)
        + len(d.labeling_notes.common_fail_patterns)
        + len(d.labeling_notes.borderline)
        for d in RUBRIC.dimensions
    )
    missing = [s for s in strings if s not in rendered or s not in raw]
    assert missing == []
    assert f"rubric {RUBRIC.version}" in rendered
    for dimension in RUBRIC.dimensions:
        assert f"\n## {dimension.id} {dimension.name}\n" in rendered
        body = section(rendered, f"{dimension.id} {dimension.name}")
        assert f"Pass (1): {dimension.pass_anchor}\n" in body
        assert f"Fail (0): {dimension.fail_anchor}\n" in body


def test_judge_v1_has_no_examples():
    raw = V1.read_text(encoding="utf-8")
    assert "{examples}" not in raw
    headings = re.findall(r"^#+ (.+)$", raw, flags=re.MULTILINE)
    assert not [h for h in headings if "example" in h.casefold()]
    assert "Rules from development disagreements" not in raw
    with pytest.raises(ValueError, match="missing.*{examples}"):
        load_judge_prompt(config_for(V1), with_examples=True)


# --- the reply template matches the schema Instructor sends -------------------------------


def reply_template(rendered: str) -> dict:
    body = section(rendered, "Your reply")
    match = re.search(r"^\{\n.*?^\}$", body, flags=re.MULTILINE | re.DOTALL)
    assert match, "the reply section holds a JSON template"
    return json.loads(match.group(0).replace("<0 or 1>", "0"))


def test_judge_prompt_template_matches_schema_order():
    schema = Judgment.model_json_schema()
    order = list(schema["$defs"]["DimensionJudgment"]["properties"])
    assert sorted(order) == ["decision", "reason"]
    assert list(schema["properties"]) == list(rubric.DIMENSION_IDS)
    template = reply_template(rendered_v1())
    assert list(template) == list(rubric.DIMENSION_IDS)
    for dimension, value in template.items():
        assert list(value) == order, dimension
        assert value["reason"].strip()
        Judgment.model_validate({d: {"decision": 1, "reason": "synthetic"} for d in template})
    paragraph = section(rendered_v1(), "Your reply").strip().split("\n\n", 1)[0]
    words = re.findall(r"\b(reason|decision)\b", paragraph)
    assert words, "the reply paragraph names the reason and the decision"
    # The paragraph names them in the schema's order, and asks for the reason first only
    # when the schema puts it first.
    assert list(dict.fromkeys(words)) == order
    assert ("first write the reason" in paragraph) == (order[0] == "reason")


# --- the rendered format, as the prompt describes it --------------------------------------


def test_judge_v1_describes_the_rendered_format():
    item_section = section(v1_text(), "The item")
    flat = " ".join(item_section.split())
    assert "five lines, not indented, in this order" in flat
    setup = [m for m in re.findall(r"`([^`]+): <[^`]+>`", item_section)]
    assert setup[:5] == ["Blender", "Bonsai", "IFC schema", "Discipline", "Model state"]
    assert "Setup record:\n{setup}\n" in item_section
    assert "`<<<BEGIN {fence} NAME>>>`" in item_section
    assert "`<<<END {fence} NAME>>>`" in item_section
    assert "indented by four spaces" in flat
    for heading in (
        "Question:",
        "Answer:",
        "Equipment problem:",
        "Tools required:",
        "Steps:",
        "Safety info:",
        "Tips:",
    ):
        assert f"`{heading}`" in item_section
    assert "`- `" in item_section and "`N. `" in item_section
    assert "`[<section id>] <quote>`" in item_section
    assert r"shown as \n" in flat
    assert "`<dimension> <name>: passed (<detail>)`" in item_section
    assert "`<dimension> <name>: failed (<detail>)`" in item_section
    for block in ("ITEM", "QUOTES", "SECTION", "CHECKS"):
        assert block in item_section
    assert "Source, Path and Heading lines" in flat
    for name in ("{item}", "{quotes}", "{sections}", "{checks}", "{category}"):
        assert name in item_section


# --- the D3 adaptation states what the frozen checks report, and no more -------------------

_RECORDS = {
    r["id"]: r
    for r in sampler.fixture_sections(
        load_doc_sources(REPOSITORY / "config/doc-sources.json"), FIXTURES
    )
}


def _cited() -> CitedSection:
    r = _RECORDS[SECTION_ID]
    return CitedSection(
        id=r["id"], page_sha256=r["page_sha256"], source=r["source"], pin_id=r["pin_id"]
    )


def results_for(**changes) -> dict[str, checks.CheckResult]:
    item = synthetic_item()
    item["answer"] = " ".join(["Open the synthetic project and add the wall from the library"] * 7)
    item.update(changes)
    record = GeneratedItem(
        run_id="synthetic-run",
        trace_id="synthetic-trace",
        item_id="synthetic-item",
        attempt_id="synthetic-attempt",
        slot_id="synthetic-slot",
        category=CATEGORIES[0],
        setup_id="SP-1",
        version_line=LINE,
        prompt_variant="baseline",
        prompt_hash="synthetic",
        model="synthetic",
        sampler_seed=1,
        generated_at="2026-11-24T00:00:00+00:00",
        offered_sections=[_cited()],
        cited_sections=[_cited()],
        quotes=[{"section_id": SECTION_ID, "text": QUOTE}],
        item=item,
    )
    texts = sampler.section_texts(record.offered_sections, FIXTURES)
    results = checks.run_checks(record, LEX, section_texts=texts)
    return {r.name: r for r in results}


STEPS = ["Open the synthetic project.", "Choose the synthetic wall type.", "Add the wall."]


def test_judge_v1_check_premises_hold():
    adaptation = " ".join(section(v1_text(), "How these rules apply to you").split())
    named = ("bim_operators_known", "blender_operators_known", "menu_paths_known")
    for name in named:
        assert f"`{name}`" in adaptation

    # Each name the prompt names is a D3 check that run_checks produces.
    plain = results_for(steps=STEPS)
    for name in named:
        assert plain[name].dimension == "D3"
    # Exactly the two the prompt calls evidence only are evidence only.
    assert checks.EVIDENCE_ONLY == {"blender_operators_known", "menu_paths_known"}
    assert "are evidence only, and neither confirms a name" in adaptation

    # With no dotted id and no ">" path, both evidence-only checks pass with "ok".
    for name in ("blender_operators_known", "menu_paths_known"):
        assert (plain[name].passed, plain[name].detail) == (True, "ok")
    assert (plain["bim_operators_known"].passed, plain["bim_operators_known"].detail) == (
        True,
        "0 ids checked",
    )

    # A bim. id only in the answer is not examined; in steps it is.
    fake_bim = "bim.synthetic_not_registered_xyz"
    answer = f"Run {fake_bim} first. " + " ".join(["Then add the synthetic wall here"] * 10)
    in_answer = results_for(steps=STEPS, answer=answer)["bim_operators_known"]
    assert (in_answer.passed, in_answer.detail) == (True, "0 ids checked")
    in_steps = results_for(steps=[f"Run {fake_bim} now.", *STEPS[1:]])["bim_operators_known"]
    assert not in_steps.passed and fake_bim in in_steps.detail

    # A passed bim_operators_known detail is a count and names no id.
    known = sorted(LEX.bim_ids[LINE])[0]
    passed = results_for(tools_required=[known], steps=[f"Run {known}.", *STEPS[1:]])
    assert passed["bim_operators_known"].passed
    assert passed["bim_operators_known"].detail == "1 ids checked"
    assert known not in passed["bim_operators_known"].detail

    # An unknown dotted Blender id with a Manual-lexicon prefix: not examined in the
    # answer, failed (and named) in steps; an id with another prefix is never examined.
    prefixes = {o.split(".")[0] for o in LEX.blender_operators[LINE] if "." in o}
    assert "object" in prefixes and "zzqq" not in prefixes
    fake_op = "object.synthetic_not_in_manual_xyz"
    answer = f"Run {fake_op} first. " + " ".join(["Then add the synthetic wall here"] * 10)
    assert results_for(steps=STEPS, answer=answer)["blender_operators_known"].detail == "ok"
    failed = results_for(steps=[f"Run {fake_op} now.", *STEPS[1:]])["blender_operators_known"]
    assert not failed.passed and not failed.drop and fake_op in failed.detail
    other = results_for(steps=["Run zzqq.synthetic_op now.", *STEPS[1:]])
    assert (other["blender_operators_known"].passed, other["blender_operators_known"].detail) == (
        True,
        "ok",
    )

    # Two real labels in a wrong order still pass the menu check: each part is matched
    # on its own. An invented label fails, and its detail names it.
    segments = LEX.menu_segments[LINE]
    assert {"file", "export"} <= segments
    for path in ("File > Export", "Export > File"):
        menu = results_for(steps=[f"Open {path}.", *STEPS[1:]])["menu_paths_known"]
        assert (menu.passed, menu.detail) == (True, "ok"), path
    assert "real labels in a wrong path or order still give" in adaptation
    invented = results_for(steps=["Open Zorbo Wizard > Bogus Exporter.", *STEPS[1:]])
    assert not invented["menu_paths_known"].passed
    assert "Bogus Exporter" in invented["menu_paths_known"].detail
    # A menu path outside the steps is never examined.
    answer = "Open Zorbo Wizard > Bogus Exporter. " + " ".join(["Then add the wall here"] * 10)
    assert results_for(steps=STEPS, answer=answer)["menu_paths_known"].detail == "ok"
    assert 'paths written with ">" or an arrow in the steps' in adaptation
