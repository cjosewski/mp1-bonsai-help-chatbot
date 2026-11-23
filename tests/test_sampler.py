"""The section sampler: balanced slots, seeded draws, version-line sources, budget and tampering."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from bonsai_help import docs_index, sampler
from bonsai_help.doc_sources import CATEGORIES, load_config
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
    for category in CATEGORIES:
        for n in range(1, 6):
            for line in LINE_SOURCES:
                a_slot = slot(category, n, line)
                sections = draw(a_slot)
                text = sampler.render_sections(sections, FIXTURES)
                records = {r["id"]: r for r in sampler.fixture_sections(CONFIG, FIXTURES)}
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
