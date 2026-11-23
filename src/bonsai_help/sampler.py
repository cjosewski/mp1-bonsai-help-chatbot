"""Seeded section sampler: which pinned documentation sections a generation slot may cite.

Sections come only from committed fixture-slice pages that a source lists in `fixture_pages`
with the slot's category, from the Bonsai docs and Blender Manual of the slot's version line.
Every page is checked against the committed manifest before it is split, so a tampered or
missing page refuses instead of feeding the generator altered text.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from bonsai_help.doc_sources import (
    CATEGORIES,
    Category,
    DocSources,
    Source,
    canonical,
    sha256_hex,
)
from bonsai_help.docs_index import Diagnostics, is_adornment, split_page, word_count
from bonsai_help.schemas import CitedSection
from bonsai_help.setup import SetupProfiles

WORD_BUDGET = 1200
MAX_BONSAI = 2
MAX_MANUAL = 1
EXCLUDED_TAGS = frozenset({"developer", "fragment"})
SPLITS = ("development", "assessed")
_ID = re.compile(r"(?P<source>[^:]+):(?P<path>.+)#L(?P<first>\d+)-L(?P<last>\d+)")
MANIFEST = Path(__file__).resolve().parents[2] / "config" / "doc-manifest.json"

if tuple(get_args(Category)) != CATEGORIES:
    raise ImportError("doc_sources.Category and CATEGORIES disagree")


class SamplerError(Exception):
    """The sampler cannot offer sections for a slot."""


class FixtureError(SamplerError):
    """A fixture page is missing or differs from the committed manifest."""


@dataclass(frozen=True)
class Slot:
    slot_id: str
    category: Category
    setup_id: str
    version_line: str


def plan_slots(profiles: SetupProfiles, split: str, count: int) -> list[Slot]:
    """`count // 5` slots per category; profiles of `split` are assigned round-robin."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, not {split!r}")
    if count <= 0 or count % len(CATEGORIES):
        raise ValueError(f"count must be a positive multiple of {len(CATEGORIES)}")
    mine = sorted((p for p in profiles.profiles if p.split == split), key=lambda p: p.id)
    if not mine:
        raise ValueError(f"no setup profile in split {split!r}")
    slots: list[Slot] = []
    for n in range(1, count // len(CATEGORIES) + 1):
        for index, category in enumerate(CATEGORIES):
            # Within a category the slots cycle through every profile of the split.
            profile = mine[(n - 1 + index) % len(mine)]
            slots.append(Slot(f"{category}-{n:03d}", category, profile.id, profile.version_line))
    return slots


def _manifest(manifest: dict | None) -> dict:
    return manifest if manifest is not None else json.loads(MANIFEST.read_bytes())


def _read_verified(source: Source, entry: dict, fixtures_dir: Path, path: str) -> bytes:
    page = next((item for item in entry["pages"] if item["path"] == path), None)
    target = fixtures_dir / source.id / path
    if page is None:
        raise FixtureError(f"{source.id}:{path}: not in the manifest")
    if not target.is_file() or target.is_symlink():
        raise FixtureError(f"{source.id}:{path}: fixture page missing")
    data = target.read_bytes()
    if sha256_hex(data) != page["sha256"]:
        raise FixtureError(f"{source.id}:{path}: differs from the manifest")
    return data


def verify_fixtures(config: DocSources, fixtures_dir: Path, manifest: dict | None = None) -> None:
    """Raise FixtureError unless every listed fixture page matches its manifest hash."""
    document = _manifest(manifest)
    for source in config.sources:
        for page in source.fixture_pages:
            _read_verified(source, document["sources"][source.id], fixtures_dir, page.path)


def _has_body(record: dict) -> bool:
    """False for an empty or heading-only section (title, adornment, labels and blanks)."""
    for line in record["text"].split("\n"):
        stripped = line.strip()
        if not stripped or is_adornment(line) or stripped.startswith(".. _"):
            continue
        if record["title"] is not None and stripped == record["title"].strip():
            continue
        return True
    return False


def fixture_sections(
    config: DocSources, fixtures_dir: Path, manifest: dict | None = None
) -> list[dict]:
    """Section records of every fixture page of the docs sources, with `categories` added."""
    document = _manifest(manifest)
    records: list[dict] = []
    for source in config.sources:
        if source.role != "docs":
            continue
        entry = document["sources"][source.id]
        pages = frozenset(item["path"] for item in entry["pages"])
        for page in source.fixture_pages:
            data = _read_verified(source, entry, fixtures_dir, page.path)
            found = split_page(
                source,
                entry["pin_id"],
                entry["repository"]["commit"],
                page.path,
                data,
                pages,
                Diagnostics(),
            )
            records += [dict(r, categories=sorted(page.categories)) for r in found]
    return records


def _eligible(record: dict, category: str) -> bool:
    return (
        category in record["categories"]
        and record["tag"] not in EXCLUDED_TAGS
        and _has_body(record)
    )


def _rng(seed: int, slot_id: str) -> random.Random:
    digest = sha256_hex(canonical({"seed": seed, "slot": slot_id}))
    return random.Random(int(digest[:16], 16))


def sample_sections(
    slot: Slot,
    seed: int,
    *,
    config: DocSources,
    profiles: SetupProfiles,
    fixtures_dir: Path,
) -> list[CitedSection]:
    """Up to two Bonsai sections then up to one Manual section within the word budget."""
    line = next((v for v in profiles.version_lines if v.id == slot.version_line), None)
    if line is None:
        raise SamplerError(f"{slot.slot_id}: unknown version line {slot.version_line!r}")
    records = sorted(
        (r for r in fixture_sections(config, fixtures_dir) if _eligible(r, slot.category)),
        key=lambda r: r["id"],
    )
    rng = _rng(seed, slot.slot_id)
    chosen: list[dict] = []
    words = 0
    for source_id, limit in (
        (line.sources.bonsai_docs, MAX_BONSAI),
        (line.sources.blender_manual, MAX_MANUAL),
    ):
        pool = [r for r in records if r["source"] == source_id]
        rng.shuffle(pool)
        taken = 0
        for record in pool:
            size = word_count(record["text"])
            if taken < limit and words + size <= WORD_BUDGET:
                chosen.append(record)
                words += size
                taken += 1
        if source_id == line.sources.bonsai_docs and not taken:
            raise SamplerError(
                f"{slot.slot_id}: no eligible {source_id} section for {slot.category} "
                f"within {WORD_BUDGET} words"
            )
    return [
        CitedSection(
            id=r["id"], page_sha256=r["page_sha256"], source=r["source"], pin_id=r["pin_id"]
        )
        for r in chosen
    ]


def render_sections(sections: list[CitedSection], fixtures_dir: Path) -> str:
    """Prompt text: each offered section's id then its exact lines from the verified page."""
    blocks = []
    for section in sections:
        match = _ID.fullmatch(section.id)
        if match is None or match["source"] != section.source:
            raise SamplerError(f"{section.id}: not a section id of {section.source}")
        target = fixtures_dir / section.source / match["path"]
        if not target.is_file() or target.is_symlink():
            raise FixtureError(f"{section.id}: fixture page missing")
        data = target.read_bytes()
        if sha256_hex(data) != section.page_sha256:
            raise FixtureError(f"{section.id}: page differs from the offered page hash")
        lines = data.decode("utf-8").split("\n")
        first, last = int(match["first"]), int(match["last"])
        if not 1 <= first <= last <= len(lines):
            raise SamplerError(f"{section.id}: line range outside the page")
        blocks.append(f"[{section.id}]\n" + "\n".join(lines[first - 1 : last]).strip("\n"))
    return "\n\n".join(blocks)
