"""Setup profiles and the cited fact table: the committed files, and every check's failure mode."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bonsai_help import setup
from bonsai_help.doc_snapshot import dump_json
from bonsai_help.doc_sources import canonical, load_config, sha256_hex
from bonsai_help.docs_index import Diagnostics, split_page

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "config/doc-sources.json")
MANIFEST = json.loads((ROOT / "config/doc-manifest.json").read_bytes())
FIXTURES = ROOT / "tests/fixtures/docs"
PROFILES = ROOT / "reference/setup-profiles.json"
FACTS = ROOT / "reference/setup-facts.json"
READ = setup.page_bytes_offline(FIXTURES)


def load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def write(path: Path, document: dict) -> Path:
    body = {key: value for key, value in document.items() if key != "digest"}
    path.write_bytes(dump_json({**body, "digest": sha256_hex(canonical(body))}))
    return path


def problems(tmp_path: Path, facts: dict | None = None, profiles: dict | None = None, read=READ):
    facts_path = write(tmp_path / "setup-facts.json", facts or load(FACTS))
    profiles_path = write(tmp_path / "setup-profiles.json", profiles or load(PROFILES))
    found = setup.check_setup(CONFIG, MANIFEST, profiles_path, facts_path, read)
    return [str(problem) for problem in found]


def row(facts: dict, identifier: str) -> dict:
    return next(r for r in facts["rows"] if r["id"] == identifier)


def test_committed_profiles_and_facts_verify_offline():
    assert setup.check_setup(CONFIG, MANIFEST, PROFILES, FACTS, READ) == []


def test_every_row_and_profile_is_an_assistant_draft_pending_review():
    facts, profiles = load(FACTS), load(PROFILES)
    assert len(facts["rows"]) >= 12 and facts["not_citable"]
    for item in [*facts["rows"], *profiles["profiles"]]:
        assert item["status"] == "assistant_drafted" and item["review"] is None


def test_version_lines_carry_their_defaults_and_pairing_status():
    lines = {line["id"]: line for line in load(PROFILES)["version_lines"]}
    assert lines["VL-current"]["origin"] == "plan §2"
    assert lines["VL-older"]["origin"] == "O-3 default"
    assert lines["VL-older"]["sources"]["bonsai_docs"] == "bonsai-docs-0-8-5-post1"
    assert lines["VL-current"]["pairing_status"] == "uncited"
    assert lines["VL-older"]["pairing_status"] == "conflict"


def test_profiles_split_without_leakage():
    profiles = load(PROFILES)["profiles"]
    assert len(profiles) == 18 and len({p["id"] for p in profiles}) == 18
    development = [p for p in profiles if p["split"] == "development"]
    assessed = [p for p in profiles if p["split"] == "assessed"]
    assert len(assessed) == 6 and len(development) == 12
    assert not {p["id"] for p in development} & {p["id"] for p in assessed}
    for chosen in (development, assessed):
        for field, values in (
            ("ifc_schema", setup.SCHEMAS),
            ("model_state", setup.MODEL_STATES),
            ("discipline", setup.DISCIPLINES),
            ("version_line", ("VL-current", "VL-older")),
        ):
            assert {p[field] for p in chosen} == set(values)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda p: p["profiles"].pop(), "not a full schema x state factorial"),
        (lambda p: p["profiles"][0].update(discipline="structure"), "breaks the rotation"),
        (lambda p: p["profiles"][0].update(split="development"), "breaks the diagonal rule"),
        (lambda p: p["profiles"][1].update(id="SP-01"), "profile ids are not unique"),
        (lambda p: p["version_lines"][0]["claims"].append("SF-001"), "is not a version row"),
        (lambda p: p["enums"]["ifc_schema"].update(facts=["SF-999"]), "unknown fact row"),
        (
            lambda p: p["version_lines"][0]["sources"].update(bonsai_source="bonsai-docs"),
            "is not a operator-source",
        ),
    ],
    ids=[
        "factorial",
        "rotation",
        "split",
        "duplicate-id",
        "claim-kind",
        "enum-fact",
        "source-role",
    ],
)
def test_profile_rules(tmp_path, change, message):
    profiles = load(PROFILES)
    change(profiles)
    assert any(message in p for p in problems(tmp_path, profiles=profiles))


def first_citation(facts: dict) -> dict:
    return facts["rows"][0]["citations"][0]


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda c: c.update(source="nowhere"), "unknown docs source"),
        (lambda c: c.update(source="bonsai-source"), "unknown docs source"),
        (lambda c: c.update(pin_id="bonsai-docs-0000000000000000"), "stale pin"),
        (
            lambda c: c.update(path="src/bonsai/docs/guides/authoring/drawings.rst"),
            "outside the committed fixture slice",
        ),
        (lambda c: c.update(line_start=11), "no such section"),
        (lambda c: c.update(heading_path=["Georeferencing"]), "heading path mismatch"),
        (lambda c: c.update(section_sha256="0" * 64), "section hash mismatch"),
        (lambda c: c.update(record_id="bonsai-docs:x#L10-L42"), "record id mismatch"),
        (lambda c: c.update(quote="IFC2X3 models can be georeferenced."), "quote not found"),
        (lambda c: c.update(quote="IFC2X3 models"), "quote too short"),
        (lambda c: c.update(quote="**Projected CRS**"), "quote too short"),
        (lambda c: c.update(quote="the **Projected CRS**"), "must be once"),
        (lambda c: c.update(quote_line=20), "quote_line is 20"),
    ],
)
def test_each_citation_check_names_its_problem(tmp_path, change, message):
    facts = load(FACTS)
    change(first_citation(facts))
    assert any(message in p for p in problems(tmp_path, facts=facts)), problems(tmp_path, facts)


def test_quote_case_and_punctuation_must_match(tmp_path):
    facts = load(FACTS)
    first_citation(facts)["quote"] = "ifc2x3 models cannot be georeferenced."
    assert any("quote not found" in p for p in problems(tmp_path, facts=facts))


def test_a_quote_inside_an_rst_comment_is_refused(tmp_path):
    facts = load(FACTS)
    citation = first_citation(facts)
    path = "manual/editors/3dview/3d_cursor.rst"
    data = (FIXTURES / "blender-manual" / path).read_bytes()
    entry = MANIFEST["sources"]["blender-manual"]
    record = next(
        r
        for r in split_page(
            CONFIG.source("blender-manual"),
            entry["pin_id"],
            entry["repository"]["commit"],
            path,
            data,
            frozenset(p["path"] for p in entry["pages"]),
            Diagnostics(),
        )
        if ".. clear" in r["text"]
    )
    citation.clear()
    citation.update(
        setup.make_citation(record, "relative to the Cursor. .. container:: lead .. clear")
    )
    found = problems(tmp_path, facts=facts)
    assert any("inside an RST comment" in p for p in found), found


def test_a_tampered_fixture_page_is_a_page_hash_problem(tmp_path):
    def read(source, path):
        data = READ(source, path)
        return data.replace(b"georeferenced", b"Georeferenced", 1) if data else data

    assert any("page hash" in p for p in problems(tmp_path, read=read))


def test_key_terms_must_occur_in_a_quote(tmp_path):
    facts = load(FACTS)
    facts["rows"][0]["key_terms"].append("IFC4X3")
    assert any("key term 'IFC4X3' is in no quote" in p for p in problems(tmp_path, facts=facts))


def test_a_version_line_needs_a_citation_from_its_own_sources(tmp_path):
    facts = load(FACTS)
    first = facts["rows"][0]
    first["citations"] = [c for c in first["citations"] if c["source"] == "bonsai-docs"]
    assert any("no citation from VL-older's sources" in p for p in problems(tmp_path, facts=facts))


def absence_row(facts: dict) -> dict:
    return next(r for r in facts["rows"] if r["kind"] == "doc_absence")


def test_absence_must_hold_on_the_named_page(tmp_path):
    facts = load(FACTS)
    absence_row(facts)["absent_in"][0]["text"] = "Creating Walls"
    assert any("absence violated" in p for p in problems(tmp_path, facts=facts))


def test_absence_claim_must_say_not_documented_on_that_page(tmp_path):
    facts = load(FACTS)
    target = absence_row(facts)
    target["claim"] = "The interactive wall editing feature is absent in 0.8.5-post1."
    found = problems(tmp_path, facts=facts)
    assert any(
        "claim must say 'not documented in bonsai-0.8.5-post1 guides/authoring/basic_modeling"
        "/creating_walls.rst'" in p
        for p in found
    ), found


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda r: r.update(citations=[]), "citations"),
        (lambda r: r.update(claim=""), "claim"),
        (lambda r: r.update(status="chad_accepted"), "needs a review"),
        (
            lambda r: r.update(review={"decided_on": "2026-11-22", "words": "ok"}),
            "has no review",
        ),
        (lambda r: r.update(kind="doc_absence"), "absent_in is required"),
        (lambda r: r.update(kind="doc_conflict"), "conflicts_with is required"),
        (lambda r: r.update(extra="x"), "Extra inputs"),
    ],
    ids=["no-citations", "empty-claim", "status", "review", "absence", "conflict", "extra"],
)
def test_rows_that_cannot_exist(tmp_path, change, message):
    facts = copy.deepcopy(load(FACTS))
    change(facts["rows"][0])
    found = problems(tmp_path, facts=facts)
    assert any("invalid" in p and message in p for p in found), found


def test_non_canonical_or_redigested_files_are_detected(tmp_path):
    facts_path = tmp_path / "setup-facts.json"
    facts_path.write_text(json.dumps(load(FACTS)))
    found = setup.check_setup(CONFIG, MANIFEST, PROFILES, facts_path, READ)
    assert any("canonical layout" in str(p) for p in found)


def test_format_rewrites_a_hand_edited_file_canonically(tmp_path):
    facts = load(FACTS)
    path = tmp_path / "setup-facts.json"
    path.write_text(json.dumps(facts, indent=4))
    assert setup.format_document(path, setup.FACTS_SCHEMA, setup.SetupFacts) == FACTS.read_bytes()
    row(facts, "SF-001")["status"] = "chad_accepted"
    path.write_text(json.dumps(facts))
    with pytest.raises(ValueError, match="needs a review"):
        setup.format_document(path, setup.FACTS_SCHEMA, setup.SetupFacts)


def test_collapse_and_quote_location_rules():
    assert setup.collapse(" a\t\n b  c\n") == "a b c"
    assert setup.collapse("a b") == "a b"  # only ASCII space, tab and LF collapse
    text = "line one\nline two continues\n.. a comment here\n   still comment\n"
    assert setup.locate_quote(text, 10, "one line two continues") == (10, [10, 11])
    assert setup.comment_lines(text.split("\n")) == {2, 3}
    assert setup.comment_lines([".. note::", "   body", ".. _target:", "..", "   x"]) == {3, 4}


def test_candidates_cover_mentions_and_pin_differences():
    records = [
        {
            "id": f"{src}:p.rst#L1-L3",
            "source": src,
            "path": "p.rst",
            "heading_path": ["P"],
            "title_line": 1,
            "line_start": 1,
            "text": text,
            "sha256": sha256_hex(text.encode()),
        }
        for src, text in (
            ("bonsai-docs", "P\n=\nUse IFC4 with Blender 5.1.\n"),
            ("bonsai-docs-0-8-5-post1", "P\n=\nUse IFC4.\n"),
        )
    ]
    found = setup.candidates(records)
    rules = sorted((c["record"].split(":")[0], c["rule"]) for c in found)
    assert rules == [
        ("bonsai-docs", "pin-diff"),
        ("bonsai-docs", "schema-mention"),
        ("bonsai-docs", "version-mention"),
        ("bonsai-docs-0-8-5-post1", "pin-diff"),
        ("bonsai-docs-0-8-5-post1", "schema-mention"),
    ]
