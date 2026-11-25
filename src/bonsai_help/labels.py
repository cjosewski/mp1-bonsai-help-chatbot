"""Append-only blind human labels with a rubric gate, entered only interactively by Chad.

Labels live beside their assessment (`assessment.assessment_directory`):

- `labels.jsonl`: hash-chained envelopes `{label, previous_sha256, sha256}`, where `sha256`
  is `tracing.digest` of the envelope without it and `previous_sha256` is the previous
  envelope's `sha256` (None for the first). Only appended, never rewritten.
- `labels-checkpoint.json`: `{assessment_sha256, ledger_sha256, count}`, written atomically
  after each append; `ledger_sha256` is the SHA-256 of the ledger's bytes.
- `.labels.lock`: the exclusive writer lock, held while a label is appended. A leftover
  lock is reported and never deleted by code.

`assessment.create_assessment` writes no label file, so the ledger's states are: neither
file (no labels yet), both consistent (`ok`), a ledger without a checkpoint (the first write
was interrupted), a checkpoint without a ledger (evidence missing), or a hash, count or chain
mismatch (interrupted or edited). Every state but the first two is refused with "preserve
and inspect"; nothing here repairs, truncates or re-signs a file.

A label pins the assessment hash, the blind id, the item's trace id and payload hash, and the
rubric version and hash. Its decisions are 0, 1 or None (unresolved) per dimension:
unresolved is recorded and reported, never a pass, and the item stays in its denominator. A
correction is a new label whose `supersedes_label_id` is the current label for that blind
id. Before the human reference is frozen (`REFERENCE` exists) a label is `blind`; after it,
`post_review`, which never changes the frozen reference.

Labeling never reads the assessment's key (`assessment.load_key`), so nothing here can show
or count an arm. The display holds the item's seven fields, its category, its setup record,
the model's quotes and the full text of its cited sections, and nothing else; control
characters other than newline and tab are shown escaped. An assistant never runs the
interactive session; the terminal check is the command's (`evaluation_cli`). Nothing here
calls a model endpoint.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import ValidationError

from bonsai_help.assessment import ACCEPTED, RUBRIC_COPY, Assessment, BlindItem
from bonsai_help.docs_index import is_adornment
from bonsai_help.evaluation_schemas import DIMENSIONS, Decisions, HumanLabel
from bonsai_help.rubric import Rubric, RubricError, load_rubric, rubric_sha256
from bonsai_help.sampler import SamplerError, section_texts
from bonsai_help.tracing import (
    append_record,
    digest,
    exclusive,
    now,
    read_json,
    read_records,
    write_checkpoint,
)

LEDGER = "labels.jsonl"
CHECKPOINT = "labels-checkpoint.json"
LOCK = ".labels.lock"
# Written once by `human_reference.freeze_reference`; its existence makes later labels
# post-review.
REFERENCE = "human-reference.json"
ENVELOPE_FIELDS = frozenset({"label", "previous_sha256", "sha256"})
CHECKPOINT_FIELDS = frozenset({"assessment_sha256", "ledger_sha256", "count"})
INSPECT = "preserve and inspect the label files; nothing was repaired"
CHANGED = "rubric changed since the assessment was created; create a new assessment"
ANSWERS = {"0": 0, "1": 1, "u": None}
SHOWN = {0: "0 (fail)", 1: "1 (pass)", None: "unresolved"}
LedgerStateName = Literal["none", "ok", "interrupted", "missing", "locked"]


class LabelError(ValueError):
    """Labeling is refused; nothing was written."""


class LedgerState(NamedTuple):
    state: LedgerStateName
    detail: str


class _Scan(NamedTuple):
    state: LedgerStateName
    detail: str
    envelopes: list[dict]
    checkpoint: dict | None


class _Quit(Exception):
    """The reviewer quit, or input ended, before an item was saved."""


def _file_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _chain_problem(envelopes: list[dict]) -> str | None:
    previous = None
    for number, envelope in enumerate(envelopes, 1):
        if set(envelope) != ENVELOPE_FIELDS:
            return f"{LEDGER} line {number} is not a label envelope"
        unsigned = {k: v for k, v in envelope.items() if k != "sha256"}
        if envelope["previous_sha256"] != previous or envelope["sha256"] != digest(unsigned):
            return f"{LEDGER} chain changed at line {number} (interrupted or edited)"
        previous = envelope["sha256"]
    return None


def _refused(detail: str, state: LedgerStateName = "interrupted") -> _Scan:
    return _Scan(state, detail, [], None)


def _scan(directory: Path) -> _Scan:
    """The ledger files' state; it never takes the lock and never writes."""
    ledger, checkpoint = directory / LEDGER, directory / CHECKPOINT
    has_ledger, has_checkpoint = _present(ledger), _present(checkpoint)
    if not has_ledger and not has_checkpoint:
        return _Scan("none", "no labels yet", [], None)
    if has_ledger and not has_checkpoint:
        return _refused(f"{LEDGER} exists without {CHECKPOINT}: the first write was interrupted")
    if has_checkpoint and not has_ledger:
        return _refused(f"{CHECKPOINT} exists without {LEDGER}: evidence is missing", "missing")
    for path in (ledger, checkpoint):
        if path.is_symlink() or not path.is_file():
            return _refused(f"{path.name} is not a regular file")
    try:
        data = ledger.read_bytes()
        pinned = read_json(checkpoint)
    except (OSError, ValueError):
        return _refused(f"{CHECKPOINT} is unreadable or not a JSON object")
    try:
        envelopes = read_records(ledger)
    except ValueError:
        return _refused(f"{LEDGER} has a broken line (interrupted or edited)")
    if (
        set(pinned) != CHECKPOINT_FIELDS
        or pinned["ledger_sha256"] != _file_sha(data)
        or type(pinned["count"]) is not int
        or pinned["count"] != len(envelopes)
        or pinned["count"] < 1
        or not data.endswith(b"\n")
    ):
        return _refused(
            f"{LEDGER} differs from {CHECKPOINT} (an append was interrupted or a file edited)"
        )
    problem = _chain_problem(envelopes)
    if problem:
        return _refused(problem)
    return _Scan("ok", f"{len(envelopes)} label record(s)", envelopes, pinned)


def ledger_state(directory: Path) -> LedgerState:
    """`none`, `ok`, `interrupted`, `missing` or `locked`, with a detail naming files only.

    A lock is reported first: while it exists a writer may be mid-append, or one stopped
    abruptly and left it. It is never removed here.
    """
    directory = Path(directory)
    if _present(directory / LOCK):
        return LedgerState(
            "locked",
            f"{LOCK} exists: another labeling session is saving, or one stopped abruptly; "
            "preserve and inspect it",
        )
    scan = _scan(directory)
    return LedgerState(scan.state, scan.detail)


def _verified(assessment: Assessment, scan: _Scan) -> dict[str, HumanLabel]:
    manifest = assessment.manifest
    if scan.state == "none":
        return {}
    if scan.state != "ok":
        raise LabelError(f"{scan.detail}; {INSPECT}")
    if scan.checkpoint["assessment_sha256"] != manifest["sha256"]:
        raise LabelError(f"{CHECKPOINT} belongs to another assessment; {INSPECT}")
    queue = {entry.blind_id: entry for entry in assessment.queue}
    reference = _present(assessment.directory / REFERENCE)
    effective: dict[str, HumanLabel] = {}
    seen: set[str] = set()
    post_review = False
    for number, envelope in enumerate(scan.envelopes, 1):
        where = f"{LEDGER} line {number}"
        try:
            label = HumanLabel.model_validate(envelope["label"])
        except ValidationError:
            raise LabelError(f"{where} is not a valid label; {INSPECT}") from None
        entry = queue.get(label.blind_id)
        if (
            entry is None
            or label.assessment_id != manifest["assessment_id"]
            or label.assessment_sha256 != manifest["sha256"]
        ):
            raise LabelError(f"{where} is a foreign label (not in this queue); {INSPECT}")
        if (
            label.trace_id != entry.trace_id
            or label.payload_sha256 != entry.payload_sha256
            or label.rubric_version != manifest["rubric_version"]
            or label.rubric_sha256 != manifest["rubric_sha256"]
        ):
            raise LabelError(f"{where} pins another item or rubric; {INSPECT}")
        if label.label_id in seen:
            raise LabelError(f"{where} repeats a label id; {INSPECT}")
        current = effective.get(label.blind_id)
        if label.supersedes_label_id != (current.label_id if current else None):
            raise LabelError(
                f"{where} does not supersede the current label of {label.blind_id}; {INSPECT}"
            )
        if label.review_stage == "post_review":
            post_review = True
            if not reference:
                raise LabelError(f"{where} is post-review but {REFERENCE} is missing; {INSPECT}")
        elif post_review:
            raise LabelError(f"{where} is blind after a post-review label; {INSPECT}")
        seen.add(label.label_id)
        effective[label.blind_id] = label
    return effective


def load_labels(assessment: Assessment) -> dict[str, HumanLabel]:
    """The effective (latest) label per blind id, after verifying the whole ledger.

    It checks the checkpoint, the hash chain, each label's schema (UTC timestamp included),
    its pins against the queue and the manifest, that each blind id is in the queue, unique
    label ids and the supersession order. No labels yet gives `{}`; any other state refuses.
    It does not look at the lock: writers call it while holding the lock.
    """
    return _verified(assessment, _scan(assessment.directory))


def check_rubric_gate(assessment: Assessment, rubric_path: Path) -> None:
    """Refuse unless the stored rubric copy matches the pin, is `chad_accepted`, and the
    current rubric at `rubric_path` still has the pinned hash."""
    manifest = assessment.manifest
    copy = assessment.directory / RUBRIC_COPY
    try:
        if copy.is_symlink():
            raise OSError
        pinned = load_rubric(copy)
    except (OSError, RubricError):
        raise LabelError(f"the assessment's {RUBRIC_COPY} is unreadable; {INSPECT}") from None
    if rubric_sha256(pinned) != manifest["rubric_sha256"]:
        raise LabelError(f"the assessment's {RUBRIC_COPY} differs from its pin; {INSPECT}")
    if pinned.status != ACCEPTED:
        raise LabelError(
            f"rubric {pinned.version} is {pinned.status}, not {ACCEPTED}: labeling waits for "
            "Chad's acceptance of the rubric"
        )
    try:
        current = load_rubric(Path(rubric_path))
    except (OSError, RubricError):
        raise LabelError(
            f"{CHANGED} (the current {Path(rubric_path).name} is unreadable)"
        ) from None
    if rubric_sha256(current) != manifest["rubric_sha256"]:
        raise LabelError(CHANGED)


def _escape(text: str) -> str:
    """Control and format characters shown as escapes, so item text cannot drive a terminal."""
    out = []
    for char in text:
        if char in "\n\t" or unicodedata.category(char) not in ("Cc", "Cf", "Zl", "Zp", "Cs"):
            out.append(char)
        elif ord(char) <= 0xFF:
            out.append(f"\\x{ord(char):02x}")
        else:
            out.append(f"\\u{ord(char):04x}")
    return "".join(out)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line else line for line in text.split("\n"))


def _heading(text: str) -> str:
    for line in text.split("\n"):
        if line.strip() and not is_adornment(line):
            return line.strip()
    return "(none)"


def render_item(blind_item: BlindItem, section_texts: dict[str, str], rubric: Rubric) -> str:
    """The blind display of one item: only the fields a label is judged on.

    It shows the blind id, category, setup record, the seven fields, the model's quotes and
    each cited section's source, path, heading and full text. Never a run, item, trace or
    model id, an arm or prompt, gate or judge output, or another label.
    """
    entry = blind_item
    item, setup = entry.item, entry.setup
    lines = [
        f"===== {entry.blind_id} ({rubric.version}) =====",
        f"Category: {entry.category}",
        "Setup:",
        f"    Blender: {setup.blender}",
        f"    Bonsai: {setup.bonsai}",
        f"    IFC schema: {setup.ifc_schema}",
        f"    Discipline: {setup.discipline}",
        f"    Model state: {setup.model_state}",
        "",
        "Question:",
        _indent(item.question),
        "Answer:",
        _indent(item.answer),
        "Equipment problem:",
        _indent(item.equipment_problem),
        "Tools required:",
        *(_indent(f"- {tool}") for tool in item.tools_required),
        "Steps:",
        *(_indent(f"{n}. {step}") for n, step in enumerate(item.steps, 1)),
        "Safety info:",
        _indent(item.safety_info),
        "Tips:",
        *(_indent(f"- {tip}") for tip in item.tips),
        "",
        "Quotes (as the model wrote them, with the section each names):",
        *(_indent(f"[{quote.section_id}] {quote.text}") for quote in entry.quotes),
        "",
        "Cited sections (full text):",
    ]
    for section in entry.cited_sections:
        if section.id not in section_texts:
            raise LabelError(f"no text for cited section {section.id}")
        text = section_texts[section.id]
        path = section.id.split(":", 1)[-1].split("#", 1)[0]
        lines += [
            f"--- {section.id} ---",
            f"Source: {section.source}",
            f"Path: {path}",
            f"Heading: {_heading(text)}",
            text,
            f"--- end of {section.id} ---",
        ]
    return _escape("\n".join(lines))


def _writer(directory: Path) -> ExitStack:
    stack = ExitStack()
    try:
        stack.enter_context(exclusive(directory / LOCK))
    except FileExistsError:
        raise LabelError(
            f"{LOCK} exists: another labeling session is saving, or one stopped abruptly; "
            "preserve and inspect it (it is never removed by code)"
        ) from None
    return stack


def _storable(*texts: str) -> None:
    for text in texts:
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise LabelError(
                "text that UTF-8 cannot store was entered; nothing was saved"
            ) from None


def record_label(
    assessment: Assessment,
    blind_id: str,
    decisions: Decisions,
    reviewer: str,
    *,
    rubric_path: Path,
    notes: str = "",
    supersedes: str | None = None,
) -> HumanLabel:
    """Append one label under the writer lock, after the rubric gate and a full ledger check.

    `supersedes` must be the current label id for `blind_id` (None for its first label).
    Called by the interactive session only; an assistant never calls it on real evidence.
    """
    if not isinstance(decisions, Decisions):
        raise LabelError("decisions must be a Decisions record")
    _storable(reviewer, notes)
    directory = assessment.directory
    with _writer(directory):
        check_rubric_gate(assessment, rubric_path)
        scan = _scan(directory)
        effective = _verified(assessment, scan)
        entry = next((e for e in assessment.queue if e.blind_id == blind_id), None)
        if entry is None:
            raise LabelError(f"{blind_id} is not in this assessment's queue")
        current = effective.get(blind_id)
        expected = current.label_id if current else None
        if supersedes != expected:
            raise LabelError(
                f"{blind_id} has no label to supersede"
                if expected is None
                else f"{blind_id} already has label {expected}; an amendment must supersede it"
            )
        stage = "post_review" if _present(directory / REFERENCE) else "blind"
        manifest = assessment.manifest
        try:
            label = HumanLabel(
                schema_version="1",
                label_id=str(uuid.uuid4()),
                assessment_id=manifest["assessment_id"],
                assessment_sha256=manifest["sha256"],
                blind_id=blind_id,
                trace_id=entry.trace_id,
                payload_sha256=entry.payload_sha256,
                rubric_version=manifest["rubric_version"],
                rubric_sha256=manifest["rubric_sha256"],
                reviewer=reviewer,
                timestamp=now(),
                decisions=decisions,
                notes=notes,
                supersedes_label_id=supersedes,
                review_stage=stage,
                entry="interactive",
            )
        except ValidationError as exc:
            fields = ", ".join(sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]}))
            raise LabelError(f"the label is invalid ({fields}); nothing was saved") from None
        previous = scan.envelopes[-1]["sha256"] if scan.envelopes else None
        envelope = {"label": label.model_dump(mode="json"), "previous_sha256": previous}
        envelope["sha256"] = digest(envelope)
        path = directory / LEDGER
        append_record(path, envelope)
        write_checkpoint(
            directory / CHECKPOINT,
            {
                "assessment_sha256": manifest["sha256"],
                "ledger_sha256": _file_sha(path.read_bytes()),
                "count": len(scan.envelopes) + 1,
            },
        )
        return label


def label_status(assessment: Assessment) -> dict:
    """Blind progress: totals, blind ids and label ids only; nothing per arm, no item ids.

    `status` is `complete`, `incomplete` or `not_intact` (a ledger that is locked,
    interrupted, missing or fails verification; `problem` then says why). It never takes
    the lock and never writes.
    """
    state = ledger_state(assessment.directory)
    status = {
        "assessment_id": assessment.manifest["assessment_id"],
        "selected": len(assessment.queue),
        "completed": None,
        "pending_blind_ids": None,
        "effective_label_ids": None,
        "unresolved_decisions": None,
        "ledger": state.state,
        "status": "not_intact",
        "problem": None,
    }
    if state.state not in ("none", "ok"):
        return status | {"problem": state.detail}
    try:
        effective = load_labels(assessment)
    except LabelError as exc:
        return status | {"problem": str(exc)}
    order = [entry.blind_id for entry in assessment.queue]
    pending = [blind_id for blind_id in order if blind_id not in effective]
    return status | {
        "completed": len(effective),
        "pending_blind_ids": pending,
        "effective_label_ids": {b: effective[b].label_id for b in order if b in effective},
        "unresolved_decisions": sum(len(v.decisions.unresolved()) for v in effective.values()),
        "status": "incomplete" if pending else "complete",
    }


def _notes_text(dimension) -> str:
    notes = dimension.labeling_notes
    parts = [f"{dimension.id} {dimension.name}: labeling notes"]
    for title, values in (
        ("Check", notes.check),
        ("Common fail patterns", notes.common_fail_patterns),
        ("Borderline", notes.borderline),
    ):
        parts.append(f"  {title}:")
        parts += [f"    - {value}" for value in values]
    return "\n".join(parts)


def _ask(input_fn: Callable[[str], str], prompt: str) -> str:
    try:
        return input_fn(prompt)
    except (EOFError, KeyboardInterrupt):
        raise _Quit from None


def _ask_item(rubric: Rubric, input_fn, output) -> tuple[Decisions, str]:
    """Six answers, the summary, an optional note, then `save? [y/redo/q]`."""
    while True:
        values: dict[str, int | None] = {}
        for dimension in rubric.dimensions:
            output(
                _escape(
                    f"{dimension.id} {dimension.name}\n  Pass: {dimension.pass_anchor}\n"
                    f"  Fail: {dimension.fail_anchor}"
                )
            )
            while True:
                answer = _ask(input_fn, f"{dimension.id} [0/1/u/?/q]: ").strip().lower()
                if answer == "q":
                    raise _Quit
                if answer == "?":
                    output(_escape(_notes_text(dimension)))
                    continue
                if answer in ANSWERS:
                    values[dimension.id] = ANSWERS[answer]
                    break
                output("Enter 0 (fail), 1 (pass), u (unresolved), ? (labeling notes) or q (quit).")
        decisions = Decisions.model_validate(values)
        overall = decisions.overall()
        summary = [f"  {d}: {SHOWN[values[d]]}" for d in DIMENSIONS]
        summary.append(
            "  Overall: " + {True: "pass", False: "fail", None: "unresolved (not a pass)"}[overall]
        )
        output("Summary:\n" + "\n".join(summary))
        notes = _ask(input_fn, "Note (optional; stays in the local ledger, never in Git): ")
        while True:
            answer = _ask(input_fn, "save? [y/redo/q]: ").strip().lower()
            if answer == "y":
                return decisions, notes.strip()
            if answer == "q":
                raise _Quit
            if answer == "redo":
                break
            output("Enter y (save), redo or q (quit).")


def interactive_label(
    assessment: Assessment,
    reviewer: str,
    *,
    rubric_path: Path,
    fixtures_dir: Path,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], object] = print,
    amend: str | None = None,
    supersedes: str | None = None,
) -> dict:
    """The reviewer's labeling session; returns `label_status` when it ends.

    Every refusal (rubric gate, ledger state, amendment target) comes before anything is
    shown. A typed confirmation `label <assessment_id>` starts the session. Each pending item
    is shown in display order; per dimension the answer is 0, 1, u (unresolved), ? (notes) or
    q (quit), and there is no skip. Nothing is written until `y`; quitting, end of input or
    Ctrl-C before that writes nothing for the item. With `amend` and `supersedes`, only that
    item is shown again, without its earlier decisions, and the new label supersedes it.
    """
    check_rubric_gate(assessment, rubric_path)
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise LabelError("the reviewer name must be nonblank")
    state = ledger_state(assessment.directory)
    if state.state not in ("none", "ok"):
        raise LabelError(f"{state.detail}; {INSPECT}")
    effective = load_labels(assessment)
    if (amend is None) != (supersedes is None):
        raise LabelError("an amendment needs both the blind id and the label id it supersedes")
    if amend is not None:
        entry = next((e for e in assessment.queue if e.blind_id == amend), None)
        if entry is None:
            raise LabelError(f"{amend} is not in this assessment's queue")
        current = effective.get(amend)
        if current is None:
            raise LabelError(f"{amend} has no label to amend")
        if supersedes != current.label_id:
            raise LabelError(f"--supersedes must be the current label id of {amend}")
        items = [entry]
    else:
        items = [e for e in assessment.queue if e.blind_id not in effective]
    assessment_id = assessment.manifest["assessment_id"]
    if not items:
        output(f"All {len(assessment.queue)} items have labels; nothing to label.")
        return label_status(assessment)
    try:
        texts = {e.blind_id: section_texts(e.cited_sections, fixtures_dir) for e in items}
    except SamplerError as exc:
        raise LabelError(f"fixture slice: {exc}") from None
    output(
        _escape(
            f"Blind labeling of {assessment_id} under rubric {assessment.rubric.version}. "
            f"Each decision you save is recorded as the reviewer {reviewer.strip()}'s own."
        )
    )
    try:
        confirmation = _ask(input_fn, f"Type 'label {assessment_id}' to begin: ")
    except _Quit:
        return label_status(assessment)
    if confirmation.strip() != f"label {assessment_id}":
        raise LabelError("the confirmation did not match; nothing was recorded")
    output(
        f"{len(items)} item(s) to label. Per dimension: 0 = fail, 1 = pass, u = unresolved "
        "(never a pass), ? = labeling notes, q = quit. Nothing is saved until you answer y."
    )
    for entry in items:
        output(render_item(entry, texts[entry.blind_id], assessment.rubric))
        try:
            decisions, notes = _ask_item(assessment.rubric, input_fn, output)
        except _Quit:
            output(f"Stopped. Nothing was saved for {entry.blind_id}.")
            return label_status(assessment)
        label = record_label(
            assessment,
            entry.blind_id,
            decisions,
            reviewer.strip(),
            rubric_path=rubric_path,
            notes=notes,
            supersedes=supersedes if amend is not None else None,
        )
        output(f"Saved {entry.blind_id} as label {label.label_id}.")
    return label_status(assessment)
