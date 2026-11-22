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


def test_every_row_profile_and_version_line_is_an_assistant_draft_pending_review():
    facts, profiles = load(FACTS), load(PROFILES)
    assert len(facts["rows"]) >= 12 and facts["not_citable"]
    for item in [*facts["rows"], *profiles["profiles"], *profiles["version_lines"]]:
        assert item["status"] == "assistant_drafted" and item["review"] is None


def test_version_lines_carry_chads_cited_pairings_and_matching_manuals():
    lines = {line["id"]: line for line in load(PROFILES)["version_lines"]}
    for line_id, blender, sources, pairing in (
        ("VL-current", "5.2", ("bonsai-docs", "bonsai-source", "blender-manual"), "SF-012"),
        (
            "VL-older",
            "4.5",
            ("bonsai-docs-0-8-5-post1", "bonsai-source-0-8-5-post1", "blender-manual-4-5"),
            "SF-013",
        ),
    ):
        line = lines[line_id]
        assert line["origin"] == "Chad, 2026-11-22" and line["blender"] == blender
        assert (
            line["sources"]["bonsai_docs"],
            line["sources"]["bonsai_source"],
            line["sources"]["blender_manual"],
        ) == sources
        assert line["pairing_status"] == "cited" and pairing in line["claims"]


@pytest.mark.parametrize(
    "line, blender, status, message",
    [
        (0, "5.3", "cited", "VL-current: a cited pairing needs a version_claim"),
        (1, "4", "cited", "VL-older: a cited pairing needs a version_claim"),
        (1, "4.2 LTS", "cited", "VL-older: a cited pairing needs a version_claim"),
        (0, "5.3", "conflict", None),
    ],
    ids=["unlisted-release", "inside-a-longer-token", "old-default", "conflict-is-not-checked"],
)
def test_a_cited_pairing_needs_a_version_claim_naming_the_release(
    tmp_path, line, blender, status, message
):
    profiles = load(PROFILES)
    profiles["version_lines"][line].update(blender=blender, pairing_status=status)
    found = problems(tmp_path, profiles=profiles)
    # The line's Manual no longer matches its release either; that check is tested below.
    pairing = [p for p in found if "Manual branch" not in p]
    assert len(found) - len(pairing) == 1, found
    if message is None:
        assert pairing == [], found
    else:
        assert len(pairing) == 1 and message in pairing[0] and f"Blender {blender} " in pairing[0]


@pytest.mark.parametrize(
    "manuals, message",
    [
        (
            ("blender-manual-4-5", "blender-manual"),
            [
                "VL-current: blender_manual blender-manual-4-5 pins branch blender-v4.5-release, "
                "not the Blender 5.2 Manual branch blender-v5.2-release",
                "VL-older: blender_manual blender-manual pins branch blender-v5.2-release, "
                "not the Blender 4.5 Manual branch blender-v4.5-release",
            ],
        ),
        (
            ("blender-manual", "blender-manual"),
            [
                "VL-older: blender_manual blender-manual pins branch blender-v5.2-release, "
                "not the Blender 4.5 Manual branch blender-v4.5-release",
            ],
        ),
        (
            ("blender-manual-4-5", "blender-manual-4-5"),
            [
                "VL-current: blender_manual blender-manual-4-5 pins branch blender-v4.5-release, "
                "not the Blender 5.2 Manual branch blender-v5.2-release",
            ],
        ),
    ],
    ids=["swapped", "both-5.2", "both-4.5"],
)
def test_each_line_names_the_manual_of_its_own_blender_release(tmp_path, manuals, message):
    profiles = load(PROFILES)
    for line, manual in zip(profiles["version_lines"], manuals, strict=True):
        line["sources"]["blender_manual"] = manual
    found = [p for p in problems(tmp_path, profiles=profiles) if "Manual branch" in p]
    assert found == [f"setup: setup-profiles.json: {m}" for m in message], found


NEW_SOURCE = "VL-current: bonsai_source bonsai-source-0-8-5-post1 pins tag bonsai-0.8.5-post1"
OLD_SOURCE = "VL-older: bonsai_source bonsai-source pins tag bonsai-0.9.0post1"
NEW_DOCS = "VL-current: bonsai_docs bonsai-docs-0-8-5-post1 pins tag bonsai-0.8.5-post1"
OLD_DOCS = "VL-older: bonsai_docs bonsai-docs pins tag bonsai-0.9.0post1"
NOT_NEW, NOT_OLD = (
    ", not the line's Bonsai tag bonsai-0.9.0post1",
    ", not the line's Bonsai tag bonsai-0.8.5-post1",
)


@pytest.mark.parametrize(
    "role, pins, message",
    [
        (
            "bonsai_source",
            ("bonsai-source-0-8-5-post1", "bonsai-source"),
            [NEW_SOURCE + NOT_NEW, OLD_SOURCE + NOT_OLD],
        ),
        ("bonsai_source", ("bonsai-source", "bonsai-source"), [OLD_SOURCE + NOT_OLD]),
        (
            "bonsai_source",
            ("bonsai-source-0-8-5-post1", "bonsai-source-0-8-5-post1"),
            [NEW_SOURCE + NOT_NEW],
        ),
        (
            "bonsai_docs",
            ("bonsai-docs-0-8-5-post1", "bonsai-docs"),
            [NEW_DOCS + NOT_NEW, OLD_DOCS + NOT_OLD],
        ),
        ("bonsai_docs", ("bonsai-docs", "bonsai-docs"), [OLD_DOCS + NOT_OLD]),
    ],
    ids=["source-swapped", "source-both-0.9", "source-both-0.8.5", "docs-swapped", "docs-both-0.9"],
)
def test_each_line_names_the_bonsai_pins_of_its_own_release(tmp_path, role, pins, message):
    profiles = load(PROFILES)
    for line, pin in zip(profiles["version_lines"], pins, strict=True):
        line["sources"][role] = pin
    # A moved docs pin also leaves some rows and the cited pairing without their own docs.
    found = [p for p in problems(tmp_path, profiles=profiles) if "Bonsai tag" in p]
    assert found == [f"setup: setup-profiles.json: {m}" for m in message], found


@pytest.mark.parametrize(
    "change, message",
    [
        (
            {"bonsai_tag": "bonsai-0.9.0post1"},
            [
                "VL-older: bonsai_docs bonsai-docs-0-8-5-post1 pins tag bonsai-0.8.5-post1, "
                "not the line's Bonsai tag bonsai-0.9.0post1",
                "VL-older: bonsai_source bonsai-source-0-8-5-post1 pins tag bonsai-0.8.5-post1, "
                "not the line's Bonsai tag bonsai-0.9.0post1",
                "VL-older: bonsai_tag bonsai-0.9.0post1 is not the tag of Bonsai 0.8.5-post1",
            ],
        ),
        (
            {"bonsai": "0.9.0-post1"},
            ["VL-older: bonsai_tag bonsai-0.8.5-post1 is not the tag of Bonsai 0.9.0-post1"],
        ),
        ({"bonsai": "0.8.5post1"}, []),
    ],
    ids=["tag-of-another-release", "release-of-another-tag", "same-release-spelled-apart"],
)
def test_a_lines_bonsai_tag_is_its_release_and_its_pins_tag(tmp_path, change, message):
    profiles = load(PROFILES)
    profiles["version_lines"][1].update(change)
    found = problems(tmp_path, profiles=profiles)
    assert found == [f"setup: setup-profiles.json: {m}" for m in message], found


def test_a_cited_pairing_counts_only_its_own_bonsai_docs_pin(tmp_path):
    facts = load(FACTS)
    # SF-012 moved onto the older docs pin no longer cites VL-current's own docs.
    citation = row(facts, "SF-012")["citations"][0]
    citation["source"] = "bonsai-docs-0-8-5-post1"
    found = problems(tmp_path, facts=facts)
    assert any("VL-current: a cited pairing needs a version_claim" in p for p in found), found


@pytest.mark.parametrize("status, valid", [("partly cited", True), ("partly_cited", False)])
def test_pairing_status_spells_partly_cited_as_the_enum_basis_does(tmp_path, status, valid):
    profiles = load(PROFILES)
    profiles["version_lines"][0]["pairing_status"] = status
    found = problems(tmp_path, profiles=profiles)
    assert (found == []) is valid, found


def test_the_schema_enum_is_cited_for_new_projects_only():
    basis = load(PROFILES)["enums"]["ifc_schema"]
    assert basis["basis"] == "partly cited" and basis["facts"] == ["SF-007"]
    assert basis["cited_for"] == ["new_project"]


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
        (lambda p: p["version_lines"][0]["claims"].append("SF-013"), "does not apply to it"),
        (lambda p: p["version_lines"][0]["claims"].remove("SF-015"), "not in VL-current's claims"),
        (lambda p: p["version_lines"][1]["sources"].update(blender_manual=None), "invalid"),
        (
            lambda p: p["version_lines"][1]["sources"].update(blender_manual="bonsai-source"),
            "blender_manual bonsai-source is not a docs",
        ),
        (lambda p: p["version_lines"][0].update(status="chad_accepted"), "needs a review"),
        (lambda p: p["enums"]["ifc_schema"].update(cited_for=[]), "cited_for is required"),
        (
            lambda p: p["enums"]["ifc_schema"].update(cited_for=list(setup.MODEL_STATES)),
            "leaves some model state out",
        ),
        (lambda p: p["enums"]["ifc_schema"].update(note=None), "needs a note"),
        (
            lambda p: p["enums"]["discipline"].update(cited_for=["new_project"]),
            "cited_for is required",
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
        "claim-line",
        "unlisted-version-row",
        "line-without-manual",
        "manual-role",
        "line-status",
        "partly-cited-without-states",
        "partly-cited-all-states",
        "partly-cited-without-note",
        "cited-for-on-a-default",
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


@pytest.mark.parametrize(
    "identifier, term",
    [("SF-008", "IFC"), ("SF-012", "Python 3.1"), ("SF-012", "Blender 5")],
    ids=["IFC-inside-IFC4", "3.1-inside-3.13", "5-inside-5.1"],
)
def test_a_key_term_inside_a_longer_token_is_in_no_quote(tmp_path, identifier, term):
    facts = load(FACTS)
    row(facts, identifier)["key_terms"].append(term)
    found = problems(tmp_path, facts=facts)
    assert found == [f"setup: {identifier}: key term {term!r} is in no quote on token boundaries"]


def test_a_version_line_needs_a_citation_from_its_own_sources(tmp_path):
    facts = load(FACTS)
    first = facts["rows"][0]
    first["citations"] = [c for c in first["citations"] if c["source"] == "bonsai-docs"]
    assert any("no citation from VL-older's sources" in p for p in problems(tmp_path, facts=facts))


@pytest.mark.parametrize(
    "manual, valid",
    [("blender-manual-4-5", True), ("blender-manual", False)],
    ids=["matching-4.5-manual", "5.2-manual-stands-in"],
)
def test_only_the_lines_own_manual_covers_the_older_line(tmp_path, manual, valid):
    # Each line's Blender steps come from its matching Manual: the 5.2 Manual does not
    # stand in for VL-older's Blender 4.5.
    facts = load(FACTS)
    target = row(facts, "SF-016")
    target["applies_to"]["version_lines"] = ["VL-older"]
    target["citations"] = [c for c in target["citations"] if c["source"] == manual]
    found = problems(tmp_path, facts=facts)
    assert found == ([] if valid else ["setup: SF-016: no citation from VL-older's sources"]), found


def test_fact_row_ids_must_be_unique(tmp_path):
    facts = load(FACTS)
    facts["rows"][1]["id"] = facts["rows"][0]["id"]
    assert any("fact row ids are not unique" in p for p in problems(tmp_path, facts=facts))


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


@pytest.mark.parametrize(
    "quote, expected",
    [
        ("supported in Blender 4.2 and are", "quote occurs only inside a longer token"),
        ("compatible with IFC2X3 files", "quote occurs only inside a longer token"),
        ("are unsupported in Blender 4", "quote occurs only inside a longer token"),
        ("are unsupported in Blender 4.2", (1, [1])),
        ("incompatible with IFC2X3 files", (1, [1])),
        ("Some features are unsupported", (1, [1])),
        ("(Blender 5.1 or 5.2) is fine", (2, [2])),
        ("Blender 5.1 or 5.2) is fine", (2, [2])),
    ],
)
def test_a_quote_must_start_and_end_on_token_boundaries(quote, expected):
    text = (
        "Some features are unsupported in Blender 4.2 and are incompatible with IFC2X3 files.\n"
        "Using (Blender 5.1 or 5.2) is fine.\n"
    )
    assert setup.locate_quote(text, 1, quote) == expected


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


def test_a_draft_may_cite_a_snapshot_page_outside_the_slice_only_when_asked(tmp_path):
    """`require_fixture=False` (gold drafts) skips only the slice rule; the page must still be
    hash-verified, so a reader that cannot supply it still fails."""
    data = (FIXTURES / "bonsai-docs/src/bonsai/docs/guides/troubleshooting.rst").read_bytes()
    entry = MANIFEST["sources"]["bonsai-docs"]
    pages = frozenset(page["path"] for page in entry["pages"])
    path = "src/bonsai/docs/guides/troubleshooting.rst"
    record = split_page(
        CONFIG.source("bonsai-docs"),
        entry["pin_id"],
        entry["repository"]["commit"],
        path,
        data,
        pages,
        Diagnostics(),
    )[0]
    quote = next(line for line in record["text"].splitlines() if len(line.strip()) > 30).strip()
    citation = setup.Citation(**setup.make_citation(record, quote))
    assert setup.verify_citation(citation, CONFIG, MANIFEST, READ, "x") == []
    moved = citation.model_copy(update={"path": "src/bonsai/docs/guides/authoring/drawings.rst"})
    found = setup.verify_citation(moved, CONFIG, MANIFEST, READ, "x")
    assert "outside the committed fixture slice" in str(found[0])
    found = setup.verify_citation(moved, CONFIG, MANIFEST, READ, "x", require_fixture=False)
    assert "page missing" in str(found[0])
