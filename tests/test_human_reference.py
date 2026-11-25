"""The frozen human reference, on synthetic assessments with synthetic labels.

Every label here is synthetic: it is written through the library for a synthetic assessment
under `tmp_path`, by the reviewer "synthetic-reviewer". No real label is entered or frozen,
nothing is written under `runs/` or `data/`, and no model is called. Every rubric marked
`chad_accepted` is a synthetic copy whose review says it is not Chad's.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from evaluation_support import FIXTURES, SOURCES, doc_config, fresh_root, profiles, write_rubric
from test_labels import resign, scripted

from bonsai_help import assessment, human_reference, labels
from bonsai_help.evaluation_schemas import DIMENSIONS, Decisions
from bonsai_help.human_reference import HumanReferenceError
from bonsai_help.tracing import digest, read_records

REVIEWER = "synthetic-reviewer"
OTHER = "synthetic-reviewer-other"
BASELINE = SOURCES["baseline"].cohort_id
CORRECTED = SOURCES["corrected"].cohort_id
DEVELOPMENT = SOURCES["development"].cohort_id


@pytest.fixture
def root(tmp_path, tmp_path_factory):
    return fresh_root(tmp_path, tmp_path_factory)


@pytest.fixture
def accepted(tmp_path):
    return write_rubric(tmp_path, name="accepted-rubric.json")


def make(root, accepted, assessment_id="a-1", cohorts=(BASELINE,), count=20):
    assessment.create_assessment(
        root,
        assessment_id,
        list(cohorts),
        count=count,
        seed="synthetic-seed",
        rubric_path=accepted,
        profiles=profiles(),
        doc_config=doc_config(),
        fixtures_dir=FIXTURES,
    )
    return assessment.load_assessment(
        root, assessment_id, fixtures_dir=FIXTURES, doc_config=doc_config(), rubric_path=accepted
    )


@pytest.fixture
def made(root, accepted):
    return make(root, accepted)


def decisions(**values) -> Decisions:
    return Decisions.model_validate(dict.fromkeys(DIMENSIONS, 1) | values)


def label_all(made, accepted, *, reviewer=REVIEWER, leave=(), values=None):
    """Label every queued item except `leave`; `values` maps a blind id to its decisions."""
    for entry in made.queue:
        if entry.blind_id in leave:
            continue
        chosen = (values or {}).get(entry.blind_id, decisions())
        labels.record_label(made, entry.blind_id, chosen, reviewer, rubric_path=accepted)


def freeze(made, accepted, reviewer=REVIEWER, declare_blind=True):
    return human_reference.freeze_reference(
        made, reviewer, declare_blind=declare_blind, rubric_path=accepted
    )


def file_hashes(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file()
    }


def reference_path(made) -> Path:
    return made.directory / labels.REFERENCE


def refused(made, accepted, match, *, rubric=None, **kwargs):
    """The freeze is refused and leaves every file byte-identical, with no reference."""
    before = file_hashes(made.directory)
    with pytest.raises(HumanReferenceError, match=match):
        freeze(made, rubric or accepted, **kwargs)
    assert file_hashes(made.directory) == before
    assert not reference_path(made).exists()


def reseal(path: Path, change) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    value["sha256"] = digest({k: v for k, v in value.items() if k != "sha256"})
    path.write_text(json.dumps(value), encoding="utf-8")


def test_freeze_requires_complete_blind_labels_and_declaration(made, accepted, tmp_path):
    with pytest.raises(HumanReferenceError, match="no frozen human reference"):
        human_reference.load_reference(made)
    refused(made, accepted, "0 of 20 selected items have labels")
    label_all(made, accepted, leave={"L-007"})
    refused(made, accepted, r"19 of 20 selected items have labels.*next pending: L-007")
    label_all(made, accepted, leave={e.blind_id for e in made.queue} - {"L-007"})
    refused(made, accepted, "declare", declare_blind=False)
    refused(made, accepted, "declare", declare_blind="yes")
    refused(made, accepted, "nonblank", reviewer="  ")
    draft = write_rubric(tmp_path, status="assistant_drafted", name="draft.json")
    refused(made, accepted, "rubric changed since the assessment was created", rubric=draft)

    reference = freeze(made, accepted, reviewer=f"  {REVIEWER} ")
    effective = labels.load_labels(made)
    manifest = made.manifest
    assert set(reference) == human_reference.REFERENCE_FIELDS
    assert reference["reviewer"] == REVIEWER and reference["declared_blind"] is True
    assert reference["kind"] == "arm" and reference["minimum_per_group"] == 20
    assert reference["assessment_sha256"] == manifest["sha256"]
    assert reference["rubric_version"] == manifest["rubric_version"]
    assert reference["rubric_sha256"] == manifest["rubric_sha256"]
    assert reference["display_order"] == manifest["display_order"]
    assert reference["labels"] == {b: effective[b].model_dump(mode="json") for b in effective}
    assert list(reference["labels"]) == manifest["display_order"]
    assert all(label["review_stage"] == "blind" for label in reference["labels"].values())
    ledger = (made.directory / labels.LEDGER).read_bytes()
    assert reference["ledger_prefix_lines"] == 20
    assert reference["ledger_prefix_sha256"] == hashlib.sha256(ledger).hexdigest()
    assert reference["counts"]["groups"] == {
        "baseline": {
            "items": 20,
            "unresolved_items": 0,
            "unresolved_by_dimension": dict.fromkeys(DIMENSIONS, 0),
        }
    }
    assert reference["sha256"] == digest({k: v for k, v in reference.items() if k != "sha256"})
    assert json.loads(reference_path(made).read_text(encoding="utf-8")) == reference
    assert human_reference.load_reference(made) == reference
    # Written in one step: no lock, no temporary file left behind.
    assert sorted(p.name for p in made.directory.iterdir()) == sorted(
        [
            "manifest.json",
            "queue.json",
            "key.json",
            "rubric.json",
            labels.LEDGER,
            labels.CHECKPOINT,
            labels.REFERENCE,
        ]
    )


def test_freeze_requires_rubric_minimum_per_arm(root, accepted, monkeypatch):
    made = make(root, accepted, "mix", cohorts=(CORRECTED, BASELINE))
    label_all(made, accepted)
    real = assessment.load_key

    def short_baseline(*args, **kwargs):
        # A forged key (create_assessment cannot make one) that puts 5 baseline items in
        # the corrected arm: 25 corrected and 15 baseline.
        key = {b: dict(entry) for b, entry in real(*args, **kwargs).items()}
        moved = [b for b, entry in key.items() if entry["arm"] == "baseline"][:5]
        for blind_id in moved:
            key[blind_id]["arm"] = "corrected"
        return key

    monkeypatch.setattr(assessment, "load_key", short_baseline)
    refused(made, accepted, "baseline has 15; the rubric needs at least 20 per arm")

    def foreign_arm(*args, **kwargs):
        key = {b: dict(entry) for b, entry in real(*args, **kwargs).items()}
        for entry in key.values():
            if entry["arm"] == "baseline":
                entry["arm"] = "smoke"
        return key

    monkeypatch.setattr(assessment, "load_key", foreign_arm)
    refused(made, accepted, "arms differ")
    monkeypatch.undo()

    reference = freeze(made, accepted)
    groups = reference["counts"]["groups"]
    assert {name: g["items"] for name, g in groups.items()} == {"baseline": 20, "corrected": 20}
    assert reference["counts"]["total"]["items"] == 40
    assert human_reference.load_reference(made) == reference


def test_freeze_once_and_verified_against_ledger_prefix(made, accepted):
    label_all(made, accepted)
    reference = freeze(made, accepted)
    path = reference_path(made)
    original = path.read_bytes()
    with pytest.raises(HumanReferenceError, match="never replaced"):
        freeze(made, accepted)
    assert path.read_bytes() == original

    def check(match):
        with pytest.raises(HumanReferenceError, match=match):
            human_reference.load_reference(made)
        path.write_bytes(original)
        assert human_reference.load_reference(made) == reference

    # Edits to the reference itself, unsealed and re-sealed.
    edited = json.loads(original)
    edited["labels"]["L-001"]["decisions"]["D1"] = 0
    path.write_text(json.dumps(edited), encoding="utf-8")
    check("changed after it was frozen")
    reseal(path, lambda v: v["labels"]["L-001"]["decisions"].update(D1=0))
    check("labels differ from its frozen ledger prefix")
    reseal(path, lambda v: v.update(ledger_prefix_lines=19))
    check("prefix changed")
    reseal(path, lambda v: v.update(ledger_prefix_lines=21))
    check("prefix is not in")
    reseal(path, lambda v: v["counts"]["total"].update(unresolved_items=1))
    check("counts differ from the key")
    reseal(path, lambda v: v.update(reviewer=OTHER))
    check("declaring reviewer's own")
    reseal(path, lambda v: v.update(declared_blind=False))
    check("does not match its assessment")
    reseal(path, lambda v: v.pop("counts"))
    check("changed after it was frozen")
    path.write_text("[]", encoding="utf-8")
    check("not a JSON object")

    # Edits to the ledger, re-signed with a matching checkpoint so that the ledger alone
    # verifies: the frozen prefix still refuses them.
    ledger = made.directory / labels.LEDGER
    checkpoint = made.directory / labels.CHECKPOINT
    saved_ledger, saved_checkpoint = ledger.read_bytes(), checkpoint.read_bytes()
    envelopes = read_records(ledger)

    def check_ledger(match):
        labels.load_labels(made)  # the ledger on its own is intact
        with pytest.raises(HumanReferenceError, match=match):
            human_reference.load_reference(made)
        ledger.write_bytes(saved_ledger)
        checkpoint.write_bytes(saved_checkpoint)
        assert human_reference.load_reference(made) == reference

    forged = [dict(e) for e in envelopes]
    forged[0] = {**forged[0], "label": forged[0]["label"] | {"notes": "synthetic edit"}}
    resign(made.directory, forged)
    check_ledger("prefix changed")
    # A blind label appended after the freeze (a post-freeze label is always post-review).
    late = envelopes[-1]["label"] | {
        "label_id": str(uuid.uuid4()),
        "supersedes_label_id": envelopes[-1]["label"]["label_id"],
        "decisions": dict.fromkeys(DIMENSIONS, 0),
    }
    resign(made.directory, [*envelopes, {"label": late}])
    check_ledger("not post-review")


def test_amendment_after_freeze_is_post_review_and_reference_unchanged(made, accepted):
    label_all(made, accepted)
    reference = freeze(made, accepted)
    original = reference_path(made).read_bytes()
    first = labels.load_labels(made)["L-003"]
    respond, _ = scripted(["label a-1", "0", "1", "1", "1", "1", "1", "post-review note", "y"])
    labels.interactive_label(
        made,
        REVIEWER,
        rubric_path=accepted,
        fixtures_dir=FIXTURES,
        input_fn=respond,
        output=lambda _: None,
        amend="L-003",
        supersedes=first.label_id,
    )
    amended = labels.load_labels(made)["L-003"]
    assert amended.review_stage == "post_review"
    assert amended.supersedes_label_id == first.label_id and amended.decisions.D1 == 0
    # Another reviewer's post-review amendment does not touch the reference either.
    current = labels.load_labels(made)["L-004"]
    labels.record_label(
        made, "L-004", decisions(D6=0), OTHER, rubric_path=accepted, supersedes=current.label_id
    )
    assert reference_path(made).read_bytes() == original
    loaded = human_reference.load_reference(made)
    assert loaded == reference
    assert loaded["labels"]["L-003"]["label_id"] == first.label_id
    assert loaded["labels"]["L-003"]["decisions"]["D1"] == 1
    assert loaded["labels"]["L-004"]["decisions"]["D6"] == 1
    assert labels.label_status(made)["status"] == "complete"
    with pytest.raises(HumanReferenceError, match="never replaced"):
        freeze(made, accepted)


def test_freeze_refused_when_judge_evidence_exists(made, accepted):
    label_all(made, accepted)
    judges = made.directory / human_reference.JUDGES
    judges.mkdir()
    (judges / "synthetic-judge-run.json").write_text("{}", encoding="utf-8")
    refused(made, accepted, "judge evidence exists")
    (judges / "synthetic-judge-run.json").unlink()
    refused(made, accepted, "judge evidence exists")  # even an empty judges/ directory
    judges.rmdir()
    judges.write_text("synthetic", encoding="utf-8")
    refused(made, accepted, "judge evidence exists")
    judges.unlink()
    assert freeze(made, accepted)["counts"]["total"]["items"] == 20


def test_freeze_refused_on_reviewer_mismatch(made, accepted):
    label_all(made, accepted)
    refused(made, accepted, "declaring reviewer's own", reviewer=OTHER)
    current = labels.load_labels(made)["L-010"]
    labels.record_label(
        made, "L-010", decisions(), OTHER, rubric_path=accepted, supersedes=current.label_id
    )
    # The effective labels now come from two reviewers: neither may freeze them.
    refused(made, accepted, "declaring reviewer's own")
    refused(made, accepted, "declaring reviewer's own", reviewer=OTHER)


def test_reference_reports_unresolved_and_keeps_denominator(root, accepted):
    made = make(root, accepted, "mix", cohorts=(CORRECTED, BASELINE))
    key = assessment.load_key(root, "mix")  # the test's own bookkeeping, never labeling code
    baseline = [b for b, entry in key.items() if entry["arm"] == "baseline"]
    corrected = [b for b, entry in key.items() if entry["arm"] == "corrected"]
    values = {
        baseline[0]: decisions(D2=None),
        baseline[1]: decisions(D2=None),
        baseline[2]: decisions(D2=None, D4=None),
        baseline[3]: decisions(D1=0, D3=None),
        corrected[0]: decisions(D2=None, D5=None),
    }
    label_all(made, accepted, values=values)
    reference = freeze(made, accepted)
    zeros = dict.fromkeys(DIMENSIONS, 0)
    assert reference["counts"] == {
        "total": {
            "items": 40,
            "unresolved_items": 5,
            "unresolved_by_dimension": zeros | {"D2": 4, "D3": 1, "D4": 1, "D5": 1},
        },
        "groups": {
            "baseline": {
                "items": 20,
                "unresolved_items": 4,
                "unresolved_by_dimension": zeros | {"D2": 3, "D3": 1, "D4": 1},
            },
            "corrected": {
                "items": 20,
                "unresolved_items": 1,
                "unresolved_by_dimension": zeros | {"D2": 1, "D5": 1},
            },
        },
    }
    # Every selected item stays in the reference, and an unresolved one is never a pass.
    assert list(reference["labels"]) == made.manifest["display_order"]
    for blind_id, label in reference["labels"].items():
        recorded = Decisions.model_validate(label["decisions"])
        assert recorded == values.get(blind_id, decisions())
        if recorded.unresolved():
            assert recorded.overall() is not True
    assert (
        Decisions.model_validate(reference["labels"][baseline[3]]["decisions"]).overall() is False
    )
    assert labels.label_status(made)["unresolved_decisions"] == 7
    assert human_reference.load_reference(made) == reference


def test_development_reference_is_marked_development(root, accepted):
    made = make(root, accepted, "dev-1", cohorts=(DEVELOPMENT,), count=5)
    label_all(made, accepted, leave={"L-005"})
    refused(made, accepted, "4 of 5 selected items have labels")
    label_all(made, accepted, leave={"L-001", "L-002", "L-003", "L-004"})
    reference = freeze(made, accepted)
    assert reference["kind"] == "development"
    assert reference["minimum_per_group"] == assessment.DEVELOPMENT_MINIMUM
    assert list(reference["counts"]["groups"]) == ["development"]
    assert reference["counts"]["groups"]["development"]["items"] == 5
    assert "baseline" not in json.dumps(reference["counts"])
    assert human_reference.load_reference(made) == reference


def test_interrupted_ledger_blocks_freeze(made, accepted, monkeypatch):
    label_all(made, accepted, leave={"L-020"})

    def crash(path, record):
        raise OSError("synthetic crash between append and checkpoint")

    monkeypatch.setattr(labels, "write_checkpoint", crash)
    with pytest.raises(OSError, match="synthetic crash"):
        labels.record_label(made, "L-020", decisions(), REVIEWER, rubric_path=accepted)
    monkeypatch.undo()
    assert labels.ledger_state(made.directory).state == "interrupted"
    refused(made, accepted, "inspect")
    with pytest.raises(HumanReferenceError, match="no frozen human reference"):
        human_reference.load_reference(made)


def test_leftover_lock_blocks_freeze_and_is_kept(made, accepted):
    label_all(made, accepted)
    lock = made.directory / labels.LOCK
    lock.write_text("synthetic leftover writer", encoding="utf-8")
    refused(made, accepted, "never removed by code")
    assert lock.read_text(encoding="utf-8") == "synthetic leftover writer"
    lock.unlink()
    assert freeze(made, accepted)["ledger_prefix_lines"] == 20
