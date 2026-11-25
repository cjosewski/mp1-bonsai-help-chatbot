"""Append-only blind labels, the rubric gate and the blind display, on synthetic assessments.

Every label here is synthetic: it is written by a scripted `input_fn` for a synthetic
assessment under `tmp_path`, by the reviewer "synthetic-reviewer". No real label is
entered, no label file is written under `runs/` or `data/`, and no model is called. Every
rubric marked `chad_accepted` is a synthetic copy whose review says it is not Chad's.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from evaluation_support import (
    FIXTURES,
    SOURCES,
    doc_config,
    fresh_root,
    profiles,
    provenance_sentinels,
    write_rubric,
)

from bonsai_help import assessment, labels, rubric
from bonsai_help.evaluation_schemas import DIMENSIONS, Decisions, HumanLabel
from bonsai_help.labels import LabelError
from bonsai_help.sampler import section_texts
from bonsai_help.tracing import digest, read_records

REVIEWER = "synthetic-reviewer"
NOTE = "synthetic local note zq-note"
BASELINE = SOURCES["baseline"].cohort_id
CORRECTED = SOURCES["corrected"].cohort_id
ALL_PASS = ["1"] * 6


@pytest.fixture
def root(tmp_path, tmp_path_factory):
    return fresh_root(tmp_path, tmp_path_factory)


@pytest.fixture
def accepted(tmp_path):
    return write_rubric(tmp_path, name="accepted-rubric.json")


def create(root, accepted, assessment_id="a-1", cohorts=(BASELINE,), seed="synthetic-seed"):
    return assessment.create_assessment(
        root,
        assessment_id,
        list(cohorts),
        count=20,
        seed=seed,
        rubric_path=accepted,
        profiles=profiles(),
        doc_config=doc_config(),
        fixtures_dir=FIXTURES,
    )


def load(root, accepted, assessment_id="a-1"):
    return assessment.load_assessment(
        root, assessment_id, fixtures_dir=FIXTURES, doc_config=doc_config(), rubric_path=accepted
    )


@pytest.fixture
def made(root, accepted):
    create(root, accepted)
    return load(root, accepted)


def scripted(answers):
    """A scripted `input_fn`: each prompt is recorded; when answers run out, end of input."""
    answers = list(answers)
    prompts: list[str] = []

    def respond(prompt):
        prompts.append(prompt)
        if not answers:
            raise EOFError
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return respond, prompts


def item_answers(values=ALL_PASS, note=""):
    return [*values, note, "y"]


def run(made, accepted, answers, *, output=None, **kwargs):
    respond, prompts = scripted(answers)
    shown: list[str] = [] if output is None else output
    result = labels.interactive_label(
        made,
        kwargs.pop("reviewer", REVIEWER),
        rubric_path=accepted,
        fixtures_dir=FIXTURES,
        input_fn=respond,
        output=shown.append,
        **kwargs,
    )
    return result, shown, prompts


def label_items(made, accepted, count, values=ALL_PASS, note=""):
    answers = [f"label {made.manifest['assessment_id']}"]
    for _ in range(count):
        answers += item_answers(values, note)
    return run(made, accepted, answers)


def label_files(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir()} & {labels.LEDGER, labels.CHECKPOINT, labels.LOCK}


def file_hashes(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file()
    }


def resign(directory: Path, envelopes: list[dict]) -> None:
    """Rewrite a ledger as a valid chain with a matching checkpoint (a forger's edit)."""
    previous = None
    lines = []
    for envelope in envelopes:
        signed = {"label": envelope["label"], "previous_sha256": previous}
        signed["sha256"] = digest(signed)
        previous = signed["sha256"]
        lines.append(json.dumps(signed, ensure_ascii=False) + "\n")
    data = "".join(lines).encode()
    (directory / labels.LEDGER).write_bytes(data)
    checkpoint = json.loads((directory / labels.CHECKPOINT).read_text(encoding="utf-8"))
    checkpoint |= {"ledger_sha256": hashlib.sha256(data).hexdigest(), "count": len(lines)}
    (directory / labels.CHECKPOINT).write_text(json.dumps(checkpoint), encoding="utf-8")


def all_pass() -> Decisions:
    return Decisions.model_validate(dict.fromkeys(DIMENSIONS, 1))


def test_label_refuses_rubric_not_accepted_or_changed(root, accepted, made, tmp_path):
    directory = made.directory
    copy = directory / "rubric.json"
    original_copy = copy.read_bytes()
    draft = write_rubric(tmp_path, status="assistant_drafted", name="draft.json")
    edited = json.loads(accepted.read_text(encoding="utf-8"))
    edited["review"]["words"] += " edited"
    edited_path = tmp_path / "edited.json"
    edited_path.write_text(json.dumps(edited), encoding="utf-8")

    def refused(match, rubric_path, assessment=made):
        respond, prompts = scripted(["label a-1", *item_answers()])
        shown: list[str] = []
        with pytest.raises(LabelError, match=match):
            labels.interactive_label(
                assessment,
                REVIEWER,
                rubric_path=rubric_path,
                fixtures_dir=FIXTURES,
                input_fn=respond,
                output=shown.append,
            )
        assert shown == [] and prompts == []
        with pytest.raises(LabelError, match=match):
            labels.record_label(assessment, "L-001", all_pass(), REVIEWER, rubric_path=rubric_path)
        assert label_files(directory) == set()

    # The current rubric is a draft, edited after the assessment was made, or unreadable.
    refused("rubric changed since the assessment was created", draft)
    refused("rubric changed since the assessment was created", edited_path)
    refused("rubric changed since the assessment was created", tmp_path / "gone.json")
    # The stored copy was replaced after the assessment was loaded.
    copy.write_bytes(draft.read_bytes())
    refused("differs from its pin", accepted)
    # A copy and pin forged together to a draft rubric: the status gate still refuses.
    forged = dataclasses.replace(
        made,
        manifest=made.manifest | {"rubric_sha256": rubric.rubric_sha256(rubric.load_rubric(draft))},
    )
    refused("assistant_drafted, not chad_accepted", draft, forged)
    copy.write_bytes(original_copy)
    result, _, _ = label_items(made, accepted, 1)
    assert result["completed"] == 1


def test_interactive_label_records_pins_and_trace(made, accepted):
    result, shown, prompts = label_items(made, accepted, 1, note=f"  {NOTE}  ")
    assert prompts[0] == "Type 'label a-1' to begin: "
    assert any("recorded as the reviewer synthetic-reviewer's own" in line for line in shown)
    assert result["completed"] == 1 and result["status"] == "incomplete"
    [envelope] = read_records(made.directory / labels.LEDGER)
    label = HumanLabel.model_validate(envelope["label"])
    first = made.queue[0]
    manifest = made.manifest
    assert label.blind_id == first.blind_id == "L-001"
    assert label.trace_id == first.trace_id
    assert label.payload_sha256 == first.payload_sha256
    assert label.assessment_id == "a-1"
    assert label.assessment_sha256 == manifest["sha256"]
    assert label.rubric_version == manifest["rubric_version"] == "bonsai-rubric-v1"
    assert label.rubric_sha256 == manifest["rubric_sha256"]
    assert label.reviewer == REVIEWER and label.notes == NOTE
    assert label.timestamp.endswith("+00:00")
    assert label.decisions.values() == dict.fromkeys(DIMENSIONS, 1)
    assert label.supersedes_label_id is None
    assert label.review_stage == "blind" and label.entry == "interactive"
    assert envelope["previous_sha256"] is None
    assert envelope["sha256"] == digest({k: v for k, v in envelope.items() if k != "sha256"})
    checkpoint = json.loads((made.directory / labels.CHECKPOINT).read_text(encoding="utf-8"))
    ledger_bytes = (made.directory / labels.LEDGER).read_bytes()
    assert checkpoint == {
        "assessment_sha256": manifest["sha256"],
        "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "count": 1,
    }
    assert labels.load_labels(made) == {"L-001": label}
    assert f"Saved L-001 as label {label.label_id}." in shown
    # The next session resumes at the next pending item and links the chain.
    result, shown, _ = label_items(made, accepted, 1)
    second = read_records(made.directory / labels.LEDGER)[1]
    assert second["label"]["blind_id"] == "L-002"
    assert second["previous_sha256"] == envelope["sha256"]
    assert result["pending_blind_ids"] == [f"L-{n:03d}" for n in range(3, 21)]
    assert not any("===== L-001" in line for line in shown)


def test_unresolved_dimension_is_recorded_and_counted(made, accepted):
    result, shown, _ = label_items(made, accepted, 1, values=["1", "u", "1", "1", "1", "1"])
    [label] = labels.load_labels(made).values()
    assert label.decisions.D2 is None
    assert label.decisions.unresolved() == ("D2",)
    assert label.decisions.overall() is None
    assert any("Overall: unresolved (not a pass)" in line for line in shown)
    assert result["completed"] == 1 and result["unresolved_decisions"] == 1
    # One fail and one unresolved: a fail, never a pass; both counted.
    result, shown, _ = label_items(made, accepted, 1, values=["0", "u", "1", "u", "1", "1"])
    assert result["completed"] == 2 and result["unresolved_decisions"] == 3
    assert labels.load_labels(made)["L-002"].decisions.overall() is False
    # The items stay selected: unresolved never removes an item from the denominator.
    assert result["selected"] == 20 and len(result["pending_blind_ids"]) == 18


@pytest.mark.parametrize(
    "answers",
    [
        ["label a-1", "1", "1", "q"],
        ["label a-1", "1", "1", "1"],  # end of input mid-item
        ["label a-1", "1", KeyboardInterrupt()],
        ["label a-1", *ALL_PASS],  # end of input at the note
        ["label a-1", *ALL_PASS, NOTE, "q"],
        ["label a-1", *ALL_PASS, NOTE, KeyboardInterrupt()],
        [],  # end of input at the confirmation
        ["q"],
    ],
)
def test_quit_eof_and_partial_item_write_nothing(made, accepted, answers):
    if answers == ["q"]:
        with pytest.raises(LabelError, match="confirmation did not match"):
            run(made, accepted, answers)
    else:
        result, shown, _ = run(made, accepted, answers)
        assert result["completed"] == 0 and result["status"] == "incomplete"
        assert result["ledger"] == "none"
    assert label_files(made.directory) == set()


def test_skip_is_not_an_answer(made, accepted):
    result, shown, prompts = run(made, accepted, ["label a-1", "s", "", "2", "0", *ALL_PASS[1:]])
    assert prompts[1:5] == ["D1 [0/1/u/?/q]: "] * 4
    assert sum("Enter 0 (fail), 1 (pass), u (unresolved)" in line for line in shown) == 3
    # The item was answered in full but the save prompt got end of input: nothing saved.
    assert label_files(made.directory) == set()
    result, _, _ = run(made, accepted, ["label a-1", "s", "0", *ALL_PASS[1:], "", "y"])
    assert labels.load_labels(made)["L-001"].decisions.D1 == 0


def test_question_mark_shows_the_labeling_notes(made, accepted):
    _, shown, prompts = run(made, accepted, ["label a-1", "?", "1", "q"])
    d1 = made.rubric.dimensions[0]
    text = "\n".join(shown)
    assert "D1 Answer completeness: labeling notes" in text
    assert d1.labeling_notes.common_fail_patterns[0] in text
    assert prompts[1:3] == ["D1 [0/1/u/?/q]: "] * 2


def test_redo_before_save_changes_nothing_on_disk(made, accepted):
    seen = []
    respond, _ = scripted(
        ["label a-1", *ALL_PASS, "first note", "redo", *(["0"] * 6), "second note", "y"]
    )

    def watching(prompt):
        if prompt.startswith("save?"):
            seen.append(label_files(made.directory))
        return respond(prompt)

    labels.interactive_label(
        made,
        REVIEWER,
        rubric_path=accepted,
        fixtures_dir=FIXTURES,
        input_fn=watching,
        output=lambda _: None,
    )
    assert seen[0] == set()
    [envelope] = read_records(made.directory / labels.LEDGER)
    assert envelope["label"]["decisions"] == dict.fromkeys(DIMENSIONS, 0)
    assert envelope["label"]["notes"] == "second note"


def test_display_never_shows_provenance_sentinels(root, accepted):
    create(root, accepted, "mix", cohorts=(CORRECTED, BASELINE))
    made = load(root, accepted, "mix")
    result, shown, prompts = label_items(made, accepted, 40)
    assert result["status"] == "complete" and result["completed"] == 40
    text = "\n".join(shown + prompts) + json.dumps(result)
    sentinels = provenance_sentinels(root)
    assert sentinels and [s for s in sentinels if s in text] == []
    for entry in made.queue:
        assert entry.trace_id not in text and entry.payload_sha256 not in text
    for source in made.manifest["sources"]:
        assert source["prompt_hash"] not in text
    for word in ("arm", "run_id", "item_id", "prompt_variant", "judge", "gate"):
        assert word not in json.dumps(result)


def test_display_shows_setup_and_full_cited_sections(root, accepted, made):
    _, shown, _ = label_items(made, accepted, 20)
    records = {
        i["trace_id"]: i
        for i in json.loads(
            (root / "cohorts" / BASELINE / "cohort.json").read_text(encoding="utf-8")
        )["items"]
    }
    blocks = {line.split("\n", 1)[0]: line for line in shown if line.startswith("=====")}
    assert len(blocks) == 20
    for entry in made.queue:
        block = blocks[f"===== {entry.blind_id} (bonsai-rubric-v1) ====="]
        assert f"Category: {entry.category}" in block
        for value in entry.setup.model_dump().values():
            assert value in block
        assert entry.item.question in block and entry.item.answer in block
        assert all(step in block for step in entry.item.steps)
        texts = section_texts(entry.cited_sections, FIXTURES)
        for section in entry.cited_sections:
            assert texts[section.id] in block
            assert f"--- {section.id} ---" in block and f"Source: {section.source}" in block
        for quote in entry.quotes:
            assert f"[{quote.section_id}] {quote.text}" in block
        cited = {s.id for s in entry.cited_sections}
        uncited = [s["id"] for s in records[entry.trace_id]["offered_sections"]]
        uncited = [s for s in uncited if s not in cited]
        assert uncited and not any(s in block for s in uncited)


def test_control_characters_are_escaped_in_display(made):
    entry = made.queue[0]
    hostile = "Clear\x1b[2J the screen\r over‮ text  and\x07 bell\tok\nnext"
    forged = entry.model_copy(update={"item": entry.item.model_copy(update={"answer": hostile})})
    texts = section_texts(entry.cited_sections, FIXTURES)
    section = entry.cited_sections[0].id
    texts[section] = texts[section] + "\x9b31m"
    shown = labels.render_item(forged, texts, made.rubric)
    for raw in ("\x1b", "\r", "‮", " ", "\x07", "\x9b"):
        assert raw not in shown
    assert "Clear\\x1b[2J the screen\\x0d over\\u202e text\\u2028 and\\x07 bell\tok\n" in shown
    assert "\\x9b31m" in shown


def test_amendment_needs_the_current_label_id_and_keeps_history(made, accepted):
    label_items(made, accepted, 1, note=NOTE)
    first = labels.load_labels(made)["L-001"]
    for kwargs, match in (
        ({"amend": "L-001"}, "needs both"),
        ({"supersedes": first.label_id}, "needs both"),
        ({"amend": "L-001", "supersedes": "0" * 8}, "current label id of L-001"),
        ({"amend": "L-002", "supersedes": first.label_id}, "L-002 has no label"),
        ({"amend": "L-099", "supersedes": first.label_id}, "not in this assessment"),
    ):
        respond, prompts = scripted(["label a-1", *item_answers()])
        shown: list[str] = []
        with pytest.raises(LabelError, match=match):
            labels.interactive_label(
                made,
                REVIEWER,
                rubric_path=accepted,
                fixtures_dir=FIXTURES,
                input_fn=respond,
                output=shown.append,
                **kwargs,
            )
        assert shown == [] and prompts == []
    with pytest.raises(LabelError, match="must supersede it"):
        labels.record_label(made, "L-001", all_pass(), REVIEWER, rubric_path=accepted)
    with pytest.raises(LabelError, match="no label to supersede"):
        labels.record_label(
            made, "L-002", all_pass(), REVIEWER, rubric_path=accepted, supersedes=first.label_id
        )

    result, shown, _ = run(
        made,
        accepted,
        ["label a-1", "0", *ALL_PASS[1:], "amended", "y"],
        amend="L-001",
        supersedes=first.label_id,
    )
    text = "\n".join(shown)
    assert "===== L-001" in text and "===== L-002" not in text
    assert NOTE not in text and first.label_id not in text  # earlier decisions are not shown
    ledger = read_records(made.directory / labels.LEDGER)
    assert [e["label"]["label_id"] for e in ledger][0] == first.label_id
    second = labels.load_labels(made)["L-001"]
    assert second.supersedes_label_id == first.label_id
    assert second.review_stage == "blind" and second.decisions.D1 == 0
    assert result["completed"] == 1 and result["effective_label_ids"] == {"L-001": second.label_id}
    # The superseded id is no longer current.
    with pytest.raises(LabelError, match="current label id"):
        run(made, accepted, ["label a-1"], amend="L-001", supersedes=first.label_id)

    # After the reference is frozen an amendment is post-review (a synthetic placeholder
    # stands in for the frozen reference here; `human_reference` writes the real one).
    reference = made.directory / labels.REFERENCE
    reference.write_text("{}", encoding="utf-8")
    third = labels.record_label(
        made, "L-001", all_pass(), REVIEWER, rubric_path=accepted, supersedes=second.label_id
    )
    assert third.review_stage == "post_review"
    # A blind label recorded after a post-review one cannot appear; nor can a post-review
    # label without its reference.
    reference.unlink()
    with pytest.raises(LabelError, match="post-review"):
        labels.load_labels(made)


def test_interrupted_append_is_detected_not_repaired(made, accepted, monkeypatch):
    directory = made.directory
    label_items(made, accepted, 2)

    def crash(path, record):
        raise OSError("synthetic crash between append and checkpoint")

    monkeypatch.setattr(labels, "write_checkpoint", crash)
    with pytest.raises(OSError, match="synthetic crash"):
        label_items(made, accepted, 1)
    monkeypatch.undo()
    assert len(read_records(directory / labels.LEDGER)) == 3
    before = file_hashes(directory)
    assert labels.LOCK not in before

    assert labels.ledger_state(directory).state == "interrupted"
    status = labels.label_status(made)
    assert status["status"] == "not_intact" and status["ledger"] == "interrupted"
    assert status["completed"] is None
    with pytest.raises(LabelError, match="inspect"):
        labels.load_labels(made)
    with pytest.raises(LabelError, match="inspect"):
        labels.record_label(made, "L-003", all_pass(), REVIEWER, rubric_path=accepted)
    respond, prompts = scripted(["label a-1", *item_answers()])
    shown: list[str] = []
    with pytest.raises(LabelError, match="inspect"):
        labels.interactive_label(
            made,
            REVIEWER,
            rubric_path=accepted,
            fixtures_dir=FIXTURES,
            input_fn=respond,
            output=shown.append,
        )
    assert shown == [] and prompts == []
    assert file_hashes(directory) == before


def test_truncated_edited_or_reordered_ledger_is_refused(made, accepted):
    directory = made.directory
    label_items(made, accepted, 3, note=NOTE)
    ledger = directory / labels.LEDGER
    checkpoint = directory / labels.CHECKPOINT
    original, original_checkpoint = ledger.read_bytes(), checkpoint.read_bytes()
    lines = original.splitlines(keepends=True)
    envelopes = read_records(ledger)

    def resigned_checkpoint(data: bytes, count: int) -> None:
        value = json.loads(original_checkpoint)
        value |= {"ledger_sha256": hashlib.sha256(data).hexdigest(), "count": count}
        checkpoint.write_text(json.dumps(value), encoding="utf-8")

    def tamper_cases():
        yield "truncated", lambda: ledger.write_bytes(lines[0])
        yield "partial line", lambda: ledger.write_bytes(original + b'{"label":')
        yield "edited note", lambda: ledger.write_bytes(original.replace(b"zq-note", b"zq-edit", 1))

        def count():
            value = json.loads(original_checkpoint) | {"count": 2}
            checkpoint.write_text(json.dumps(value), encoding="utf-8")

        yield "count", count

        def edited_and_resigned():
            data = original.replace(b"zq-note", b"zq-edit", 1)
            ledger.write_bytes(data)
            resigned_checkpoint(data, 3)

        yield "edited, checkpoint re-signed", edited_and_resigned

        def reordered():
            data = lines[1] + lines[0] + lines[2]
            ledger.write_bytes(data)
            resigned_checkpoint(data, 3)

        yield "reordered", reordered

        def middle_deleted():
            data = lines[0] + lines[2]
            ledger.write_bytes(data)
            resigned_checkpoint(data, 2)

        yield "middle deleted", middle_deleted

    for name, tamper in tamper_cases():
        tamper()
        assert labels.ledger_state(directory).state == "interrupted", name
        with pytest.raises(LabelError, match="inspect"):
            labels.load_labels(made)
        assert labels.label_status(made)["status"] == "not_intact"
        ledger.write_bytes(original)
        checkpoint.write_bytes(original_checkpoint)
        assert len(labels.load_labels(made)) == 3

    # A whole chain re-signed with another item's pins: the files agree, the pins do not.
    for change, match in (
        ({"trace_id": made.queue[5].trace_id}, "pins another item"),
        ({"payload_sha256": "0" * 64}, "pins another item"),
        ({"rubric_sha256": "0" * 64}, "pins another item"),
        ({"supersedes_label_id": envelopes[0]["label"]["label_id"]}, "supersede"),
        ({"label_id": envelopes[0]["label"]["label_id"]}, "supersede|repeats"),
        ({"timestamp": "2026-11-24T10:00:00+02:00"}, "not a valid label"),
    ):
        forged = [dict(e) for e in envelopes]
        forged[1] = {**forged[1], "label": forged[1]["label"] | change}
        resign(directory, forged)
        assert labels.ledger_state(directory).state == "ok"
        with pytest.raises(LabelError, match=match):
            labels.load_labels(made)
        status = labels.label_status(made)
        assert status["status"] == "not_intact" and status["ledger"] == "ok"
        assert status["problem"]
        ledger.write_bytes(original)
        checkpoint.write_bytes(original_checkpoint)


def test_first_write_interrupted_and_missing_ledger_are_not_no_labels(made, accepted, monkeypatch):
    directory = made.directory

    def crash(path, record):
        raise OSError("synthetic crash before the first checkpoint")

    monkeypatch.setattr(labels, "write_checkpoint", crash)
    with pytest.raises(OSError):
        label_items(made, accepted, 1)
    monkeypatch.undo()
    assert label_files(directory) == {labels.LEDGER}
    state = labels.ledger_state(directory)
    assert state.state == "interrupted" and "first write" in state.detail
    with pytest.raises(LabelError, match="first write"):
        labels.load_labels(made)
    assert labels.label_status(made)["status"] == "not_intact"

    ledger = directory / labels.LEDGER
    saved = ledger.read_bytes()
    ledger.unlink()
    label_items(made, accepted, 1)
    ledger.unlink()  # a checkpoint whose ledger is gone
    state = labels.ledger_state(directory)
    assert state.state == "missing" and "missing" in state.detail
    with pytest.raises(LabelError, match="missing"):
        labels.load_labels(made)
    with pytest.raises(LabelError, match="missing"):
        labels.record_label(made, "L-001", all_pass(), REVIEWER, rubric_path=accepted)
    status = labels.label_status(made)
    assert status["status"] == "not_intact" and status["ledger"] == "missing"
    assert status["completed"] is None
    assert saved


def test_leftover_lock_is_reported_not_removed(made, accepted):
    lock = made.directory / labels.LOCK
    lock.write_text("synthetic leftover writer", encoding="utf-8")
    state = labels.ledger_state(made.directory)
    assert state.state == "locked" and labels.LOCK in state.detail
    status = labels.label_status(made)
    assert status["status"] == "not_intact" and status["ledger"] == "locked"
    with pytest.raises(LabelError, match="lock"):
        labels.record_label(made, "L-001", all_pass(), REVIEWER, rubric_path=accepted)
    respond, prompts = scripted(["label a-1", *item_answers()])
    shown: list[str] = []
    with pytest.raises(LabelError, match="lock"):
        labels.interactive_label(
            made,
            REVIEWER,
            rubric_path=accepted,
            fixtures_dir=FIXTURES,
            input_fn=respond,
            output=shown.append,
        )
    assert shown == [] and prompts == []
    assert lock.read_text(encoding="utf-8") == "synthetic leftover writer"
    assert label_files(made.directory) == {labels.LOCK}


def test_foreign_label_is_refused(root, accepted, made):
    create(root, accepted, "a-2", seed="another-seed")
    other = load(root, accepted, "a-2")
    label_items(other, accepted, 2)
    for name in (labels.LEDGER, labels.CHECKPOINT):
        shutil.copyfile(other.directory / name, made.directory / name)
    with pytest.raises(LabelError, match="another assessment"):
        labels.load_labels(made)
    assert labels.label_status(made)["status"] == "not_intact"
    for name in (labels.LEDGER, labels.CHECKPOINT):
        (made.directory / name).unlink()

    label_items(made, accepted, 2)
    envelopes = read_records(made.directory / labels.LEDGER)
    forged = [
        envelopes[0],
        {**envelopes[1], "label": envelopes[1]["label"] | {"blind_id": "L-099"}},
    ]
    resign(made.directory, forged)
    with pytest.raises(LabelError, match="foreign"):
        labels.load_labels(made)
    other_label = read_records(other.directory / labels.LEDGER)[0]["label"]
    resign(made.directory, [envelopes[0], {"label": other_label}])
    with pytest.raises(LabelError, match="foreign"):
        labels.load_labels(made)
    resign(made.directory, envelopes)
    with pytest.raises(LabelError, match="not in this assessment's queue"):
        labels.record_label(made, "L-099", all_pass(), REVIEWER, rubric_path=accepted)
    assert len(labels.load_labels(made)) == 2


def test_labels_never_read_the_key(root, accepted, monkeypatch):
    create(root, accepted, "mix", cohorts=(BASELINE, CORRECTED))
    key = root / "assessments/mix/key.json"
    key.unlink()

    def forbidden(*args, **kwargs):
        raise AssertionError("labeling read the key")

    monkeypatch.setattr(assessment, "load_key", forbidden)
    monkeypatch.setattr(assessment, "_read_key", forbidden)
    made = load(root, accepted, "mix")
    result, _, _ = label_items(made, accepted, 40)
    assert result["status"] == "complete" and result["completed"] == 40
    assert labels.label_status(made)["status"] == "complete"


def test_reviewer_and_text_are_checked_before_anything_is_written(made, accepted):
    with pytest.raises(LabelError, match="reviewer"):
        run(made, accepted, ["label a-1", *item_answers()], reviewer="  ")
    with pytest.raises(LabelError, match="UTF-8"):
        run(made, accepted, ["label a-1", *item_answers(note="bad \udcff byte")])
    with pytest.raises(LabelError, match="Decisions"):
        labels.record_label(
            made, "L-001", dict.fromkeys(DIMENSIONS, 1), REVIEWER, rubric_path=accepted
        )
    assert label_files(made.directory) == set()


def test_complete_session_reports_complete(made, accepted):
    result, shown, _ = label_items(made, accepted, 20)
    assert result["status"] == "complete" and result["pending_blind_ids"] == []
    assert list(result["effective_label_ids"]) == made.manifest["display_order"]
    result, shown, prompts = run(made, accepted, [])
    assert shown == ["All 20 items have labels; nothing to label."] and prompts == []
