"""Immutable, seeded and blind assessments drawn from frozen synthetic cohorts.

No label is entered and no model is called: the cohorts come from the scripted fake model
in `evaluation_support`, and every rubric marked `chad_accepted` here is a synthetic copy
under `tmp_path` whose review says it is not Chad's.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from evaluation_support import (
    FIXTURES,
    REPO,
    SOURCES,
    doc_config,
    fresh_root,
    profiles,
    provenance_sentinels,
    write_rubric,
)

from bonsai_help import assessment, rubric
from bonsai_help.assessment import AssessmentError, UsageError
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.sampler import section_texts
from bonsai_help.schemas import CitedSection

BASELINE = SOURCES["baseline"].cohort_id
CORRECTED = SOURCES["corrected"].cohort_id
DEVELOPMENT = SOURCES["development"].cohort_id
BLIND_FIELDS = {
    "blind_id",
    "trace_id",
    "payload_sha256",
    "category",
    "item",
    "setup",
    "quotes",
    "cited_sections",
}
FILES = {"manifest.json", "queue.json", "key.json", "rubric.json"}


@pytest.fixture
def root(tmp_path, tmp_path_factory):
    return fresh_root(tmp_path, tmp_path_factory)


@pytest.fixture
def accepted(tmp_path):
    return write_rubric(tmp_path, name="accepted-rubric.json")


def create(root, accepted, assessment_id="a-1", cohorts=(BASELINE,), **kwargs):
    kwargs.setdefault("count", 20)
    kwargs.setdefault("seed", "synthetic-seed-1")
    kwargs.setdefault("fixtures_dir", FIXTURES)
    return assessment.create_assessment(
        root,
        assessment_id,
        list(cohorts),
        rubric_path=accepted,
        profiles=profiles(),
        doc_config=doc_config(),
        **kwargs,
    )


def load(root, assessment_id="a-1", *, fixtures_dir=FIXTURES, rubric_path=None):
    return assessment.load_assessment(
        root,
        assessment_id,
        fixtures_dir=fixtures_dir,
        doc_config=doc_config(),
        rubric_path=rubric_path,
    )


def cohort_items(root, cohort_id):
    path = root / "cohorts" / cohort_id / "cohort.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def by_trace(root, *cohort_ids):
    return {i["trace_id"]: i for c in cohort_ids for i in cohort_items(root, c)}


def sha(*parts) -> str:
    return hashlib.sha256(json.dumps(list(parts), ensure_ascii=False).encode()).hexdigest()


def file_hashes(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file()
    }


def selected_ids(root, assessment_id):
    return {
        (v["source_index"], v["item_id"]) for v in assessment.load_key(root, assessment_id).values()
    }


def test_selection_is_reproducible_and_category_balanced(root, accepted, tmp_path):
    first = create(root, accepted, "a-1", count=20, seed="seed-x")
    second = create(root, accepted, "a-2", count=20, seed="seed-x")
    other = create(root, accepted, "a-3", count=20, seed="seed-y")
    key = assessment.load_key(root, "a-1")
    assert selected_ids(root, "a-1") == selected_ids(root, "a-2")
    assert selected_ids(root, "a-1") != selected_ids(root, "a-3")
    assert first["display_order"] == second["display_order"]
    assert other["selection"]["seed"] == "seed-y"

    # count / 5 per category, and within each category the lowest sha256(seed, cohort, item).
    items = {i["item_id"]: i for i in cohort_items(root, BASELINE)}
    chosen = [items[v["item_id"]] for v in key.values()]
    assert {c: sum(i["category"] == c for i in chosen) for c in CATEGORIES} == dict.fromkeys(
        CATEGORIES, 4
    )
    for category in CATEGORIES:
        pool = sorted(
            (i for i in items.values() if i["category"] == category),
            key=lambda i: sha("seed-x", BASELINE, i["item_id"]),
        )
        assert {i["item_id"] for i in pool[:4]} == {
            i["item_id"] for i in chosen if i["category"] == category
        }
    manifest = first
    assert manifest["selection"] == {
        "algorithm": "sha256-stratified-v2",
        "seed": "seed-x",
        "count_per_source": 20,
        "excluded": [],
    }
    assert manifest["kind"] == "arm"
    assert manifest["sources"] == [
        {
            "cohort_id": BASELINE,
            "cohort_sha256": json.loads(
                (root / "cohorts" / BASELINE / "cohort.json").read_text(encoding="utf-8")
            )["sha256"],
            "collection_id": SOURCES["baseline"].collection_id,
            "arm": "baseline",
            "split": "assessed",
            "prompt_hash": manifest["sources"][0]["prompt_hash"],
            "model_sha256": SOURCES["baseline"].model_sha256,
        }
    ]
    assert manifest["sources"][0]["prompt_hash"] == chosen[0]["prompt_hash"]
    # The assessment writes no label file: the first saved label creates the ledger.
    assert {p.name for p in (root / "assessments/a-1").iterdir()} == FILES


def test_mixed_arms_are_interleaved_by_seed(root, accepted):
    manifest = create(root, accepted, "mix", cohorts=(CORRECTED, BASELINE), seed="mix-seed")
    loaded = load(root, "mix")
    traces = [b.trace_id for b in loaded.queue]
    assert len(traces) == 40
    assert traces == sorted(traces, key=lambda t: sha("mix-seed", "order", t))
    key = assessment.load_key(root, "mix")
    arms = [key[b.blind_id]["arm"] for b in loaded.queue]
    assert arms.count("baseline") == arms.count("corrected") == 20
    # Not grouped by source: the arm changes many times along the display order.
    assert sum(a != b for a, b in zip(arms, arms[1:], strict=False)) > 5
    assert [s["arm"] for s in manifest["sources"]] == ["corrected", "baseline"]
    assert {v["source_index"] for v in key.values()} == {0, 1}
    for blind_id, entry in key.items():
        source = manifest["sources"][entry["source_index"]]
        assert entry["arm"] == source["arm"]
        assert entry["run_id"].startswith(source["collection_id"])
    other = create(root, accepted, "mix-2", cohorts=(CORRECTED, BASELINE), seed="mix-seed-2")
    assert other["display_order"] == manifest["display_order"]  # ids are positions only
    assert [b.trace_id for b in load(root, "mix-2").queue] != traces


def test_blind_ids_follow_display_position(root, accepted):
    manifest = create(root, accepted, count=25)
    loaded = load(root)
    expected = [f"L-{n:03d}" for n in range(1, 26)]
    assert manifest["display_order"] == expected
    assert [b.blind_id for b in loaded.queue] == expected
    assert list(assessment.load_key(root, "a-1")) == expected


def test_queue_holds_only_blind_fields(root, accepted):
    create(root, accepted, cohorts=(BASELINE, CORRECTED))
    assert set(assessment.BlindItem.model_fields) == BLIND_FIELDS
    assert set(assessment.SetupRecord.model_fields) == {
        "blender",
        "bonsai",
        "ifc_schema",
        "discipline",
        "model_state",
    }
    directory = root / "assessments/a-1"
    queue = json.loads((directory / "queue.json").read_text(encoding="utf-8"))
    assert all(set(entry) == BLIND_FIELDS for entry in queue)
    text = (directory / "queue.json").read_text(encoding="utf-8")
    leaked = [s for s in provenance_sentinels(root) if s in text]
    assert leaked == []
    for name in ("baseline", "corrected", "prompt_variant", "run_id", "item_id", "model"):
        assert f'"{name}"' not in text

    # The display record: the profile's versions and setup, the cited sections (never the
    # uncited offered ones) and the model's quotes as stored in the envelope.
    records = by_trace(root, BASELINE, CORRECTED)
    setup = profiles()
    for blind in load(root).queue:
        record = records[blind.trace_id]
        profile = next(p for p in setup.profiles if p.id == record["setup_id"])
        line = next(v for v in setup.version_lines if v.id == profile.version_line)
        assert blind.setup.model_dump() == {
            "blender": line.blender,
            "bonsai": line.bonsai,
            "ifc_schema": profile.ifc_schema,
            "discipline": profile.discipline,
            "model_state": profile.model_state,
        }
        assert blind.item.model_dump() == record["item"]
        assert blind.category == record["category"]
        assert [q.model_dump() for q in blind.quotes] == record["quotes"]
        assert [c.model_dump() for c in blind.cited_sections] == record["cited_sections"]
        assert (
            blind.payload_sha256
            == hashlib.sha256(
                json.dumps(record["item"], sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
        )
        texts = section_texts(blind.cited_sections, FIXTURES)
        assert set(texts) == {c.id for c in blind.cited_sections}


def test_create_refuses_unaccepted_rubric(root, tmp_path):
    draft = write_rubric(tmp_path, status="assistant_drafted", name="draft.json")
    with pytest.raises(AssessmentError, match="chad_accepted"):
        create(root, draft)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(AssessmentError, match="rubric"):
        create(root, broken)
    with pytest.raises(AssessmentError, match="rubric"):
        create(root, tmp_path / "missing.json")
    assert not (root / "assessments").exists()


def test_rubric_copy_is_pinned(root, accepted, tmp_path):
    manifest = create(root, accepted)
    pinned = rubric.load_rubric(accepted)
    assert manifest["rubric_version"] == pinned.version
    assert manifest["rubric_sha256"] == rubric.rubric_sha256(pinned)
    assert manifest["rubric_status"] == "chad_accepted"
    copy = root / "assessments/a-1/rubric.json"
    assert copy.read_bytes() == accepted.read_bytes()
    loaded = load(root, rubric_path=accepted)
    assert loaded.rubric == pinned
    assert loaded.current_rubric_sha256 == manifest["rubric_sha256"]
    # A later change to the current rubric is reported, not hidden; the gate is labels'.
    changed = write_rubric(tmp_path, status="assistant_drafted", name="changed.json")
    assert load(root, rubric_path=changed).current_rubric_sha256 != manifest["rubric_sha256"]
    assert load(root, rubric_path=tmp_path / "gone.json").current_rubric_sha256 is None
    assert load(root).current_rubric_sha256 is None


def test_assessment_is_immutable(root, accepted):
    create(root, accepted)
    directory = root / "assessments/a-1"
    before = file_hashes(directory)
    with pytest.raises(AssessmentError, match="already exists"):
        create(root, accepted, seed="another-seed")
    assert file_hashes(directory) == before

    for name in ("manifest.json", "queue.json", "rubric.json"):
        original = (directory / name).read_bytes()
        data = json.loads(original)
        if isinstance(data, list):
            data[0]["item"]["question"] += " edited"
        else:
            data["schema_version"] = data["schema_version"] + "x"
        (directory / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
        with pytest.raises(AssessmentError, match="changed"):
            load(root)
        (directory / name).write_bytes(original)
    load(root)

    original = (directory / "key.json").read_bytes()
    key = json.loads(original)
    first, second = list(key)[:2]
    key[first], key[second] = key[second], key[first]
    (directory / "key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    with pytest.raises(AssessmentError, match="key"):
        assessment.load_key(root, "a-1")
    (directory / "key.json").write_bytes(original)
    assessment.load_key(root, "a-1")

    # A layout-only rewrite of the queue is a change too: it is pinned by its bytes.
    original = (directory / "queue.json").read_bytes()
    (directory / "queue.json").write_text(json.dumps(json.loads(original)), encoding="utf-8")
    with pytest.raises(AssessmentError, match="changed"):
        load(root)


def test_interrupted_create_is_reported_not_repaired(root, accepted, monkeypatch):
    real = assessment._write_once

    def fail_on_manifest(path, data):
        if path.name == "manifest.json":
            raise OSError("synthetic interruption")
        real(path, data)

    monkeypatch.setattr(assessment, "_write_once", fail_on_manifest)
    with pytest.raises(OSError, match="synthetic interruption"):
        create(root, accepted)
    monkeypatch.undo()
    directory = root / "assessments/a-1"
    before = file_hashes(directory)
    with pytest.raises(AssessmentError, match="inspect"):
        load(root)
    with pytest.raises(AssessmentError, match="inspect"):
        assessment.load_key(root, "a-1")
    with pytest.raises(AssessmentError, match="inspect"):
        assessment.assessment_summary(root, "a-1")
    with pytest.raises(AssessmentError, match="already exists"):
        create(root, accepted)
    assert file_hashes(directory) == before
    with pytest.raises(AssessmentError, match="no assessment"):
        load(root, "never-created")


def test_changed_cohort_or_collection_evidence_is_refused(root, accepted):
    create(root, accepted)
    path = root / "cohorts" / BASELINE / "cohort.json"
    original = path.read_bytes()
    data = json.loads(original)
    data["quality_status"] = "edited"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(AssessmentError, match="cohort"):
        load(root)
    with pytest.raises(AssessmentError, match="cohort"):
        create(root, accepted, "a-2")
    path.write_bytes(original)
    load(root)

    batch = root / f"{SOURCES['baseline'].collection_id}-b01" / "items.jsonl"
    original = batch.read_bytes()
    batch.write_bytes(original.replace(b"synthetic baseline wall", b"edited baseline wall", 1))
    with pytest.raises(AssessmentError):
        load(root)
    with pytest.raises(AssessmentError):
        create(root, accepted, "a-3")
    assert not (root / "assessments/a-2").exists()
    assert not (root / "assessments/a-3").exists()
    with pytest.raises(AssessmentError, match="no cohort"):
        create(root, accepted, "a-4", cohorts=("no-such-cohort",))


def test_smoke_or_mismatched_purpose_is_refused(root, accepted):
    with pytest.raises(AssessmentError, match="smoke"):
        create(root, accepted, cohorts=(SOURCES["smoke"].cohort_id,))
    with pytest.raises(AssessmentError, match="prompt_variant"):
        create(root, accepted, cohorts=(SOURCES["mismatch"].cohort_id,))
    assert not (root / "assessments").exists()


def test_split_decides_kind_and_mixing_is_refused(root, accepted):
    manifest = create(root, accepted, "dev-1", cohorts=(DEVELOPMENT,), count=5)
    assert manifest["kind"] == "development"
    assert manifest["sources"][0]["split"] == "development"
    assert assessment.assessment_summary(root, "dev-1")["kind"] == "development"
    with pytest.raises(UsageError, match="multiple of 5"):
        create(root, accepted, "dev-2", cohorts=(DEVELOPMENT,), count=0)
    with pytest.raises(AssessmentError, match="mix"):
        create(root, accepted, "mixed", cohorts=(BASELINE, DEVELOPMENT))
    assert not (root / "assessments/mixed").exists()
    # Development items keep development setup profiles; assessed items assessed ones.
    setup = {p.id: p.split for p in profiles().profiles}
    for item in cohort_items(root, DEVELOPMENT):
        assert setup[item["setup_id"]] == "development"


def test_one_cohort_per_arm(root, accepted):
    with pytest.raises(AssessmentError, match="one cohort per arm"):
        create(root, accepted, cohorts=(BASELINE, SOURCES["baseline2"].cohort_id))
    with pytest.raises(UsageError, match="more than once"):
        create(root, accepted, cohorts=(BASELINE, BASELINE))
    with pytest.raises(UsageError, match="at least one cohort"):
        create(root, accepted, cohorts=())
    assert not (root / "assessments").exists()


def test_exclusion_gives_disjoint_selection(root, accepted):
    first = create(root, accepted, "b6", count=30, seed="b6-seed")
    later = create(root, accepted, "b8", cohorts=(CORRECTED, BASELINE), count=20, exclude=["b6"])
    earlier = {v["item_id"] for v in assessment.load_key(root, "b6").values()}
    key = assessment.load_key(root, "b8")
    baseline_now = {v["item_id"] for v in key.values() if v["arm"] == "baseline"}
    assert len(baseline_now) == 20 and len(earlier) == 30
    assert earlier.isdisjoint(baseline_now)
    # Together the two take every baseline item of the cohort exactly once.
    assert earlier | baseline_now == {i["item_id"] for i in cohort_items(root, BASELINE)}
    assert later["selection"]["excluded"] == [{"assessment_id": "b6", "sha256": first["sha256"]}]
    load(root, "b8")

    # 6 of 10 per category are taken: a second draw of 25 (5 per category) cannot be met.
    with pytest.raises(AssessmentError, match="shortfall") as refused:
        create(root, accepted, "b8-more", count=25, exclude=["b6"])
    assert "padded" in str(refused.value)
    assert not (root / "assessments/b8-more").exists()
    with pytest.raises(AssessmentError, match="no assessment"):
        create(root, accepted, "b8-x", exclude=["missing"])
    with pytest.raises(UsageError, match="more than once"):
        create(root, accepted, "b8-y", exclude=["b6", "b6"])

    # A changed excluded assessment invalidates the selection that excluded it.
    path = root / "assessments/b6/manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["created_at"] = "2026-01-01T00:00:00+00:00"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(AssessmentError, match="changed"):
        load(root, "b8")


def test_count_rules(root, accepted):
    for count in (22, 0, -5, True, 20.0, "20"):
        with pytest.raises(UsageError):
            create(root, accepted, count=count)
    with pytest.raises(UsageError, match="at least 20"):
        create(root, accepted, count=15)
    with pytest.raises(AssessmentError, match="shortfall"):
        create(root, accepted, count=55)
    for seed in ("", "   ", 7):
        with pytest.raises(UsageError, match="seed"):
            create(root, accepted, seed=seed)
    assert not (root / "assessments").exists()
    assert create(root, accepted, count=50)["display_order"][-1] == "L-050"


def test_minimum_comes_from_the_rubric(root, tmp_path):
    accepted = write_rubric(tmp_path)
    assert assessment.minimum_per_arm(rubric.load_rubric(accepted)) == 20
    assert assessment.DEVELOPMENT_MINIMUM == 5


def test_tampered_fixture_refuses(root, accepted, tmp_path):
    create(root, accepted)
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    cited = load(root).queue[0].cited_sections[0]
    page = copy / cited.source / cited.id.split(":", 1)[1].split("#", 1)[0]
    page.write_bytes(page.read_bytes() + b"\nsynthetic tampering\n")
    with pytest.raises(AssessmentError, match="fixture"):
        load(root, fixtures_dir=copy)
    with pytest.raises(AssessmentError, match="fixture"):
        create(root, accepted, "a-2", fixtures_dir=copy)
    assert not (root / "assessments/a-2").exists()


def test_key_is_not_read_by_load_assessment(root, accepted, monkeypatch):
    create(root, accepted, cohorts=(BASELINE, CORRECTED))
    directory = root / "assessments/a-1"
    key = directory / "key.json"
    saved = key.read_bytes()
    key.unlink()

    def forbidden(*args, **kwargs):
        raise AssertionError("load_assessment read the key")

    monkeypatch.setattr(assessment, "load_key", forbidden)
    loaded = load(root)
    assert len(loaded.queue) == 40
    summary = assessment.assessment_summary(root, "a-1")
    monkeypatch.undo()
    with pytest.raises(AssessmentError, match="key"):
        assessment.load_key(root, "a-1")
    key.write_bytes(saved)
    assert len(assessment.load_key(root, "a-1")) == 40
    assert summary["selected"] == 40


def test_summary_is_blind(root, accepted):
    manifest = create(root, accepted, cohorts=(BASELINE, CORRECTED))
    summary = assessment.assessment_summary(root, "a-1")
    assert summary == {
        "assessment_id": "a-1",
        "kind": "arm",
        "sources": 2,
        "selected": 40,
        "rubric_version": manifest["rubric_version"],
        "rubric_sha256": manifest["rubric_sha256"],
        "created_at": manifest["created_at"],
    }
    text = json.dumps(summary)
    assert [s for s in provenance_sentinels(root) if s in text] == []


def test_key_is_verified_against_the_cohorts(root, accepted):
    create(root, accepted, cohorts=(BASELINE, CORRECTED))
    key = assessment.load_key(root, "a-1")
    records = by_trace(root, BASELINE, CORRECTED)
    queue = load(root).queue
    for blind in queue:
        entry = key[blind.blind_id]
        record = records[blind.trace_id]
        assert entry == {
            "source_index": entry["source_index"],
            "item_id": record["item_id"],
            "run_id": record["run_id"],
            "arm": record["prompt_variant"],
        }


def test_directories_stay_out_of_the_repository(tmp_path):
    with pytest.raises(ValueError, match="runs/"):
        assessment.assessment_directory(REPO / "config", "a-1")
    assert assessment.assessment_directory(REPO / "runs", "a-1") == (REPO / "runs/assessments/a-1")
    for bad in ("../escape", "a/b", "", "-lead"):
        with pytest.raises(ValueError):
            assessment.assessment_directory(tmp_path, bad)
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked/assessments").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="symlink"):
        assessment.assessment_directory(tmp_path / "linked", "a-1")


def test_cited_sections_are_section_references(root, accepted):
    create(root, accepted)
    for blind in load(root).queue:
        assert all(isinstance(c, CitedSection) for c in blind.cited_sections)
        assert blind.quotes
