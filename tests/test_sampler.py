"""The section sampler: balanced slots, seeded draws, version-line sources, budget and tampering."""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from pathlib import Path

import pytest

from bonsai_help import checks, docs_index, sampler
from bonsai_help.doc_sources import CATEGORIES, load_config
from bonsai_help.schemas import CitedSection
from bonsai_help.setup import SetupProfiles

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "config/doc-sources.json")
PROFILES = SetupProfiles.model_validate(
    json.loads((ROOT / "reference/setup-profiles.json").read_bytes())
)
FIXTURES = ROOT / "tests/fixtures/docs"
LINE_SOURCES = {
    line.id: {line.sources.bonsai_docs, line.sources.blender_manual}
    for line in PROFILES.version_lines
}
LINE_OF = {p.id: p.version_line for p in PROFILES.profiles}


def slot(category="bonsai_modeling", n=1, line="VL-current"):
    profile = next(p for p in PROFILES.profiles if p.version_line == line)
    return sampler.Slot(f"{category}-{n:03d}", category, profile.id, line)


def draw(a_slot, seed=7):
    return sampler.sample_sections(
        a_slot, seed, config=CONFIG, profiles=PROFILES, fixtures_dir=FIXTURES
    )


def test_plan_is_balanced_and_split_pure():
    for split in ("development", "assessed"):
        slots = sampler.plan_slots(PROFILES, split, 70)
        assert Counter(s.category for s in slots) == {c: 14 for c in CATEGORIES}
        allowed = {p.id for p in PROFILES.profiles if p.split == split}
        assert {s.setup_id for s in slots} <= allowed
        assert len({s.slot_id for s in slots}) == 70
        assert all(s.version_line == LINE_OF[s.setup_id] for s in slots)
        assert (
            Counter(s.setup_id for s in slots).most_common()[0][1]
            - min(Counter(s.setup_id for s in slots).values())
            <= 5
        )
    assert sampler.plan_slots(PROFILES, "development", 5)[0].slot_id.endswith("-001")


def test_plan_rejects_bad_count_and_split():
    with pytest.raises(ValueError):
        sampler.plan_slots(PROFILES, "development", 7)
    with pytest.raises(ValueError):
        sampler.plan_slots(PROFILES, "held_out", 5)


def test_same_seed_same_sections():
    assert draw(slot()) == draw(slot())
    assert draw(slot(), seed=7) == draw(slot(), seed=7)


def test_different_slot_different_draw():
    draws = {tuple(s.id for s in draw(slot(n=n))) for n in range(1, 9)}
    assert len(draws) > 1


@pytest.mark.parametrize("line", ["VL-current", "VL-older"])
@pytest.mark.parametrize("category", CATEGORIES)
def test_sections_match_category_and_version_line(category, line):
    sections = draw(slot(category, 1, line))
    assert sections
    assert {s.source for s in sections} <= LINE_SOURCES[line]
    other = set().union(*(v for k, v in LINE_SOURCES.items() if k != line))
    assert not {s.source for s in sections} & (other - LINE_SOURCES[line])
    pages = {
        (source.id, page.path)
        for source in CONFIG.sources
        for page in source.fixture_pages
        if category in page.categories
    }
    for s in sections:
        path = s.id.split(":", 1)[1].split("#", 1)[0]
        assert (s.source, path) in pages


def test_word_budget_and_composition():
    records = {r["id"]: r for r in sampler.fixture_sections(CONFIG, FIXTURES)}
    for category in CATEGORIES:
        for n in range(1, 6):
            for line in LINE_SOURCES:
                a_slot = slot(category, n, line)
                sections = draw(a_slot)
                text = sampler.render_sections(sections, FIXTURES)
                words = sum(docs_index.word_count(records[s.id]["text"]) for s in sections)
                assert 0 < words <= sampler.WORD_BUDGET == 1200
                bonsai = [s for s in sections if s.source.startswith("bonsai-docs")]
                manual = [s for s in sections if s.source.startswith("blender-manual")]
                assert 1 <= len(bonsai) <= 2 and len(manual) <= 1
                assert all(s.id in text for s in sections)


def test_developer_and_fragment_excluded():
    records = sampler.fixture_sections(CONFIG, FIXTURES)
    by_id = {r["id"]: r for r in records}
    assert {r["tag"] for r in records} & {"developer", "fragment"}
    offered = {
        s.id
        for category in CATEGORIES
        for n in range(1, 12)
        for line in LINE_SOURCES
        for s in draw(slot(category, n, line))
    }
    assert offered <= by_id.keys()
    assert not {by_id[i]["tag"] for i in offered} & {"developer", "fragment"}
    assert all(by_id[i]["text"].strip() for i in offered)


def test_cited_section_carries_pin_and_page_hash():
    section = draw(slot())[0]
    record = next(r for r in sampler.fixture_sections(CONFIG, FIXTURES) if r["id"] == section.id)
    assert (section.page_sha256, section.source, section.pin_id) == (
        record["page_sha256"],
        record["source"],
        record["pin_id"],
    )


def test_render_shows_each_section_text():
    sections = draw(slot())
    text = sampler.render_sections(sections, FIXTURES)
    records = {r["id"]: r for r in sampler.fixture_sections(CONFIG, FIXTURES)}
    for s in sections:
        assert s.id in text and records[s.id]["text"].strip() in text


def test_verify_fixtures_passes_on_committed_slice():
    sampler.verify_fixtures(CONFIG, FIXTURES)


def test_tampered_fixture_refuses(tmp_path):
    copy = tmp_path / "docs"
    shutil.copytree(FIXTURES, copy)
    source = CONFIG.source("bonsai-docs")
    page = copy / source.id / source.fixture_pages[0].path
    data = bytearray(page.read_bytes())
    data[len(data) // 2] ^= 0x01
    page.write_bytes(bytes(data))
    with pytest.raises(sampler.FixtureError):
        sampler.verify_fixtures(CONFIG, copy)
    with pytest.raises(sampler.FixtureError):
        sampler.fixture_sections(CONFIG, copy)
    with pytest.raises(sampler.FixtureError):
        draw_in(copy)


def draw_in(copy):
    return sampler.sample_sections(slot(), 7, config=CONFIG, profiles=PROFILES, fixtures_dir=copy)


def test_missing_fixture_page_refuses(tmp_path):
    copy = tmp_path / "docs"
    shutil.copytree(FIXTURES, copy)
    source = CONFIG.source("bonsai-docs")
    (copy / source.id / source.fixture_pages[0].path).unlink()
    with pytest.raises(sampler.FixtureError):
        sampler.verify_fixtures(CONFIG, copy)


def test_unknown_profile_or_no_bonsai_section_is_a_clear_error(monkeypatch):
    bad = sampler.Slot("bonsai_modeling-001", "bonsai_modeling", "SP-99", "VL-nope")
    with pytest.raises(sampler.SamplerError):
        draw(bad)
    monkeypatch.setattr(sampler, "WORD_BUDGET", 1)
    with pytest.raises(sampler.SamplerError):
        draw(slot())


def test_heading_only_and_empty_sections_are_not_eligible():
    only = {"title": "Walls", "text": ".. _walls:\n\nWalls\n=====\n\n"}
    empty = {"title": None, "text": "\n\n"}
    body = {"title": "Walls", "text": "Walls\n=====\n\nDraw a wall.\n"}
    assert [sampler._has_body(r) for r in (only, empty, body)] == [False, False, True]


def test_sections_too_short_to_quote_are_not_eligible():
    # A section with fewer than MIN_QUOTE_WORDS words that have a letter or digit (a See
    # Also link list, say) admits no passing quote, so offering it could only add a drop.
    short = {
        "title": "See Also",
        "text": "See Also\n--------\n\n- :doc:`walls`\n- :doc:`slabs`\n",
        "categories": ["bonsai_modeling"],
        "tag": "procedure",
    }
    five = dict(short, text="See Also\n--------\n\n* Draw a wall first.\n")
    assert not sampler._eligible(short, "bonsai_modeling")
    assert sampler._eligible(five, "bonsai_modeling")


def _cited(record: dict) -> CitedSection:
    return CitedSection(
        id=record["id"],
        page_sha256=record["page_sha256"],
        source=record["source"],
        pin_id=record["pin_id"],
    )


def _first_counted_words(text: str, n: int) -> str:
    """The shortest run of whitespace tokens from the first counted word to the n-th."""
    tokens = text.split()
    counted = [i for i, token in enumerate(tokens) if checks.quote_word_count(token)]
    return " ".join(tokens[counted[0] : counted[n - 1] + 1])


def test_every_eligible_fixture_section_admits_a_quote():
    records = sampler.fixture_sections(CONFIG, FIXTURES)
    # The sections with a body but fewer than MIN_QUOTE_WORDS counted words.
    excluded = {
        "bonsai-docs:src/bonsai/docs/guides/authoring/basic_modeling/door.rst#L150-L154",
        "bonsai-docs:src/bonsai/docs/guides/authoring/basic_modeling/window.rst#L141-L145",
        "bonsai-docs:src/bonsai/docs/guides/authoring/advanced_modeling/material_assignment.rst"
        "#L99-L103",
        "bonsai-docs:src/bonsai/docs/reference/toolbar/explore.rst#L8-L12",
        "bonsai-docs-0-8-5-post1:src/bonsai/docs/guides/authoring/advanced_modeling/"
        "material_assignment.rst#L99-L103",
        "bonsai-docs-0-8-5-post1:src/bonsai/docs/guides/authoring/basic_modeling/window.rst"
        "#L141-L145",
        "blender-manual-4-5:manual/advanced/command_line/index.rst#L73-L78",
    }
    assert excluded <= {r["id"] for r in records}
    eligible = [r for r in records if any(sampler._eligible(r, c) for c in CATEGORIES)]
    assert eligible and not excluded & {r["id"] for r in eligible}
    texts = sampler.section_texts([_cited(r) for r in eligible], FIXTURES)
    for record in eligible:
        text = texts[record["id"]]
        quote = _first_counted_words(text, checks.MIN_QUOTE_WORDS)
        assert checks._quote_problem(quote, text) is None, (record["id"], quote)


@pytest.mark.parametrize("split", ["development", "assessed"])
def test_every_category_covers_every_profile_of_the_split(split):
    slots = sampler.plan_slots(PROFILES, split, 70)
    expected = {p.id for p in PROFILES.profiles if p.split == split}
    for category in CATEGORIES:
        assert {s.setup_id for s in slots if s.category == category} == expected


def test_draw_is_pinned_for_a_fixed_seed_and_slot():
    a_slot = sampler.Slot("bonsai_modeling-001", "bonsai_modeling", "SP-01", "VL-current")
    # Re-pinned on November 24, 2026, when sections too short to quote left the pool.
    assert [s.id for s in draw(a_slot, seed=7)] == [
        "bonsai-docs:src/bonsai/docs/guides/authoring/basic_modeling/door.rst#L115-L138",
        "bonsai-docs:src/bonsai/docs/guides/authoring/basic_modeling/opening.rst#L14-L38",
        "blender-manual:manual/scene_layout/object/editing/join.rst#L1-L26",
    ]


def _copy_with_sections(tmp_path):
    copy = tmp_path / "docs"
    shutil.copytree(FIXTURES, copy)
    sections = draw(slot())
    return copy, sections


def test_render_refuses_changed_page_bytes(tmp_path):
    copy, sections = _copy_with_sections(tmp_path)
    first = sections[0]
    page = copy / first.source / first.id.split(":", 1)[1].split("#", 1)[0]
    data = bytearray(page.read_bytes())
    data[len(data) // 2] ^= 0x01
    page.write_bytes(bytes(data))
    with pytest.raises(sampler.FixtureError):
        sampler.render_sections(sections, copy)


def test_render_refuses_wrong_page_hash():
    wrong = draw(slot())[0].model_copy(update={"page_sha256": "0" * 64})
    with pytest.raises(sampler.FixtureError):
        sampler.render_sections([wrong], FIXTURES)


def test_render_refuses_missing_page(tmp_path):
    copy, sections = _copy_with_sections(tmp_path)
    first = sections[0]
    (copy / first.source / first.id.split(":", 1)[1].split("#", 1)[0]).unlink()
    with pytest.raises(sampler.FixtureError):
        sampler.render_sections(sections, copy)


def test_missing_committed_manifest_is_a_fixture_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sampler, "MANIFEST", tmp_path / "doc-manifest.json")
    with pytest.raises(sampler.FixtureError, match="manifest"):
        sampler.verify_fixtures(CONFIG, FIXTURES)
    with pytest.raises(sampler.FixtureError, match="manifest"):
        sampler.fixture_sections(CONFIG, FIXTURES)


def test_source_missing_from_the_manifest_is_a_fixture_error(tmp_path, monkeypatch):
    document = json.loads(sampler.MANIFEST.read_bytes())
    del document["sources"]["bonsai-docs"]
    edited = tmp_path / "doc-manifest.json"
    edited.write_text(json.dumps(document))
    monkeypatch.setattr(sampler, "MANIFEST", edited)
    with pytest.raises(sampler.FixtureError, match="bonsai-docs: not in the manifest"):
        sampler.verify_fixtures(CONFIG, FIXTURES)
    with pytest.raises(sampler.FixtureError, match="bonsai-docs: not in the manifest"):
        sampler.fixture_sections(CONFIG, FIXTURES)


def _manifest_copy(tmp_path, monkeypatch) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    copy = tmp_path / "doc-manifest.json"
    copy.write_bytes(sampler.MANIFEST.read_bytes())
    monkeypatch.setattr(sampler, "MANIFEST", copy)
    return copy


def test_section_texts_parse_an_unchanged_manifest_once(tmp_path, monkeypatch):
    sections = draw(slot())
    parsed = []
    real_loads = json.loads
    monkeypatch.setattr(sampler.json, "loads", lambda data: parsed.append(1) or real_loads(data))
    _manifest_copy(tmp_path / "fresh", monkeypatch)  # a new path the cache has never seen
    first = sampler.section_texts(sections, FIXTURES)
    for _ in range(20):
        assert sampler.section_texts(sections, FIXTURES) == first
    assert len(parsed) == 1


def test_section_texts_reread_a_changed_manifest(tmp_path, monkeypatch):
    copy = _manifest_copy(tmp_path, monkeypatch)
    sections = draw(slot())
    original = copy.read_bytes()
    assert sampler.section_texts(sections, FIXTURES)
    # Same length, same mtime: only the bytes differ, and the change is still seen.
    stat = copy.stat()
    page_hash = sections[0].page_sha256
    tampered = original.replace(page_hash.encode(), page_hash[::-1].encode(), 1)
    assert tampered != original and len(tampered) == len(original)
    copy.write_bytes(tampered)
    os.utime(copy, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(sampler.FixtureError, match="committed manifest"):
        sampler.section_texts(sections, FIXTURES)
    copy.write_bytes(original)
    assert sampler.section_texts(sections, FIXTURES)
    copy.unlink()
    with pytest.raises(sampler.FixtureError, match="missing or unreadable"):
        sampler.section_texts(sections, FIXTURES)


def test_section_texts_refuse_a_tampered_page_with_the_manifest_cached(tmp_path):
    copy, sections = _copy_with_sections(tmp_path)
    assert sampler.section_texts(sections, copy)  # warms the manifest cache
    first = sections[0]
    page = copy / first.source / first.id.split(":", 1)[1].split("#", 1)[0]
    data = bytearray(page.read_bytes())
    data[len(data) // 2] ^= 0x01
    page.write_bytes(bytes(data))
    with pytest.raises(sampler.FixtureError, match="offered page hash"):
        sampler.section_texts(sections, copy)


def test_the_cached_manifest_cannot_be_changed_by_a_caller(tmp_path, monkeypatch):
    # The cache serves one parsed document to every call while the file is unchanged, so a
    # caller that changed it would corrupt every later call; it is read-only all the way down.
    _manifest_copy(tmp_path, monkeypatch)
    document = sampler._manifest()
    entry = document["sources"]["bonsai-docs"]
    with pytest.raises(TypeError):
        document["sources"]["bonsai-docs"] = {}
    with pytest.raises(TypeError):
        entry["pin_id"] = "changed"
    with pytest.raises((TypeError, AttributeError)):
        entry["pages"].append({"path": "extra.rst", "sha256": "0" * 64})
    with pytest.raises(TypeError):
        entry["pages"][0]["sha256"] = "0" * 64
    assert sampler._manifest() is document
    assert draw(slot()) and sampler.section_texts(draw(slot()), FIXTURES)
