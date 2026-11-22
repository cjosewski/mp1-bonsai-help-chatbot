"""The gold slot plan: counts, splits, balance, determinism, substitutions and the committed file."""

from __future__ import annotations

import json
import shutil
from collections import Counter

import pytest
from gold_support import GOLD, PROFILES

from bonsai_help import cli, gold
from bonsai_help.doc_snapshot import CheckFailed, dump_json
from bonsai_help.doc_sources import CATEGORIES, canonical, sha256_hex

SLOTS, _ = gold.plan_slots(PROFILES)
SPLIT_OF = {p.id: p.split for p in PROFILES.profiles}


def test_exact_counts_per_kind_split_and_category():
    counts = Counter((s["kind"], s["split"], s["category"]) for s in SLOTS)
    for (kind, split), target in gold.TARGETS.items():
        for category in CATEGORIES:
            assert counts[(kind, split, category)] == target // len(CATEGORIES)
    assert len(SLOTS) == 100


def test_held_out_slots_use_only_assessed_profiles_and_development_the_others():
    for s in SLOTS:
        assert (s["split"] == "held_out") == (SPLIT_OF[s["profile"]] == "assessed")


def test_profile_spread_lines_and_categories_are_balanced():
    for kind, split in gold.TARGETS:
        mine = [s for s in SLOTS if (s["kind"], s["split"]) == (kind, split)]
        per_profile = Counter(s["profile"] for s in mine)
        assert max(per_profile.values()) - min(per_profile.values()) <= 1
        for category in CATEGORIES:
            lines = {s["version_line"] for s in mine if s["category"] == category}
            if sum(s["category"] == category for s in mine) >= 2:
                assert lines == {"VL-current", "VL-older"}
    for split in ("development", "held_out"):
        singles = [s for s in SLOTS if (s["kind"], s["split"]) == ("single", split)]
        for profile in {s["profile"] for s in singles}:
            categories = [s["category"] for s in singles if s["profile"] == profile]
            assert len(categories) == len(set(categories))


def test_injection_vectors_and_kind_scoped_ids():
    vectors = Counter(s["vector"] for s in SLOTS if s["kind"] == "injection")
    assert vectors == gold.VECTOR_TARGETS
    assert all(s["vector"] is None for s in SLOTS if s["kind"] != "injection")
    assert [s["id"] for s in SLOTS][:2] == ["GS-SD-001", "GS-SD-002"]
    assert SLOTS[-1]["id"] == "GS-IH-010"


def test_changing_one_kinds_count_renumbers_no_other_slot(monkeypatch):
    targets = dict(gold.TARGETS)
    targets[("multi_part", "held_out")] = 6
    monkeypatch.setattr(gold, "TARGETS", targets)
    changed, _ = gold.plan_slots(PROFILES)
    before = {s["id"]: s for s in SLOTS}
    after = {s["id"]: s for s in changed}
    assert set(after) - set(before) == {"GS-MH-006"}
    assert all(after[i] == before[i] for i in before)


def test_the_plan_is_deterministic_and_ignores_review_status():
    assert gold.plan_slots(PROFILES) == gold.plan_slots(PROFILES)
    raw = json.loads((GOLD.parent / "setup-profiles.json").read_bytes())
    raw["profiles"][0].update(
        status="chad_accepted", review={"decided_on": "2026-11-23", "words": "approve"}
    )
    reviewed = type(PROFILES).model_validate(raw)
    assert gold.profiles_digest(reviewed) == gold.profiles_digest(PROFILES)


def test_committed_plan_equals_a_regeneration_and_hand_edits_are_found(tmp_path):
    document, problems = gold.check_slots(GOLD, PROFILES)
    assert problems == [] and document["slots"] == SLOTS
    copy = tmp_path / "gold"
    shutil.copytree(GOLD, copy)
    edited = json.loads((copy / "slots.json").read_bytes())
    edited["slots"][0]["profile"] = "SP-03"
    body = {k: v for k, v in edited.items() if k != "digest"}
    (copy / "slots.json").write_bytes(dump_json({**body, "digest": sha256_hex(canonical(body))}))
    _, problems = gold.check_slots(copy, PROFILES)
    assert ["differs from a regeneration" in p.message for p in problems] == [True]
    (copy / "slots.json").write_bytes(json.dumps(edited).encode())
    _, problems = gold.check_slots(copy, PROFILES)
    assert any("canonical layout" in p.message for p in problems)


@pytest.mark.parametrize(
    "profile, message",
    [
        ("SP-03", None),
        ("SP-11", "on another version line"),
        ("SP-01", "in the other split"),
        ("SP-02", "equals the planned one"),
    ],
)
def test_a_substitution_keeps_kind_split_category_and_line(tmp_path, profile, message):
    target = SLOTS[0]
    assert target["profile"] == "SP-02"
    copy = tmp_path / "gold"
    copy.mkdir()
    (copy / "slot-substitutions.json").write_text(
        json.dumps(
            {
                "schema": gold.SUBSTITUTIONS_SCHEMA,
                "substitutions": [
                    {"slot": target["id"], "profile": profile, "reason": "no apt section"}
                ],
            }
        )
    )
    if message is not None:
        with pytest.raises(CheckFailed, match=message):
            gold.write_slots(copy, PROFILES, write=True)
        return
    report = gold.write_slots(copy, PROFILES, write=True)
    assert report.lines[0] == "slot-substitutions.json: rewritten"
    document, problems = gold.check_slots(copy, PROFILES)
    assert problems == []
    first = document["slots"][0]
    assert first["profile"] == "SP-03" and first["substitution"]["planned_profile"] == "SP-02"
    assert Counter(s["category"] for s in document["slots"]) == Counter(
        s["category"] for s in SLOTS
    )


def test_gold_slots_cli_compares_without_writing(capsys, monkeypatch):
    monkeypatch.chdir(GOLD.parents[1] / "tests")
    assert cli.main(["gold", "slots"]) == 0
    assert "slots.json: unchanged (100 slots)" in capsys.readouterr().out
