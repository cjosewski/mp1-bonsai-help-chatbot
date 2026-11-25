"""The assessment and labeling commands: exit codes, blind output, the terminal check.

Every assessment here is synthetic, built under `tmp_path` from the synthetic cohorts of
`evaluation_support`; every label is synthetic, by the reviewer "synthetic-reviewer". No
real label is entered or frozen, nothing is written under `runs/` or `data/`, and no model
is called. The tests that stand in a terminal replace `sys.stdin` and `sys.stdout` with
in-memory streams that report a terminal, on synthetic evidence only; no pseudo-terminal is
used. Every rubric marked `chad_accepted` is a synthetic copy whose review says it is not
Chad's.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
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
from test_human_reference import decisions

from bonsai_help import assessment, cli, evaluation_cli, labels
from bonsai_help.config import REPOSITORY
from bonsai_help.tracing import read_records

REVIEWER = "synthetic-reviewer"
BASELINE = SOURCES["baseline"].cohort_id
CORRECTED = SOURCES["corrected"].cohort_id
ASSESSMENT = "neutral-1"
INTERACTIVE = ("label", "freeze-human-reference")


class Terminal(io.StringIO):
    """An in-memory stream that reports a terminal (synthetic tests only)."""

    def isatty(self) -> bool:
        return True


class Pipe(io.StringIO):
    def isatty(self) -> bool:
        return False


@pytest.fixture
def root(tmp_path, tmp_path_factory):
    return fresh_root(tmp_path, tmp_path_factory)


@pytest.fixture
def accepted(tmp_path, monkeypatch):
    """A synthetic accepted rubric, also standing in for the repository's current rubric."""
    path = write_rubric(tmp_path, name="accepted-rubric.json")
    monkeypatch.setattr(evaluation_cli, "RUBRIC", path)
    return path


def create_args(root, *cohorts, count=20, seed="synthetic-seed", rubric=None, extra=()):
    args = ["assessment", "create", "--artifact-root", str(root), "--assessment-id", ASSESSMENT]
    for cohort_id in cohorts or (BASELINE,):
        args += ["--cohort", cohort_id]
    args += ["--count", str(count), "--seed", seed, *extra]
    if rubric is not None:
        args += ["--rubric", str(rubric)]
    return args


def invoke(argv, capsys):
    code = cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def common(root, assessment_id=ASSESSMENT):
    return ["--artifact-root", str(root), "--assessment-id", assessment_id]


def load(root, rubric, assessment_id=ASSESSMENT):
    return assessment.load_assessment(
        root, assessment_id, fixtures_dir=FIXTURES, doc_config=doc_config(), rubric_path=rubric
    )


def make(root, rubric, cohorts=(BASELINE,), assessment_id=ASSESSMENT):
    assessment.create_assessment(
        root,
        assessment_id,
        list(cohorts),
        count=20,
        seed="synthetic-seed",
        rubric_path=rubric,
        profiles=profiles(),
        doc_config=doc_config(),
        fixtures_dir=FIXTURES,
    )
    return load(root, rubric, assessment_id)


def label_some(made, rubric, count=None):
    """Synthetic labels through the library, for the first `count` queued items."""
    for entry in made.queue[:count]:
        labels.record_label(made, entry.blind_id, decisions(), REVIEWER, rubric_path=rubric)


def file_hashes(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file()
    }


def terminal(monkeypatch, text: str) -> Terminal:
    """Stand in a terminal: scripted input on stdin, output collected from stdout."""
    monkeypatch.setattr(sys, "stdin", Terminal(text))
    shown = Terminal()
    monkeypatch.setattr(sys, "stdout", shown)
    return shown


def summary_of(text: str) -> dict:
    """The JSON summary a command prints last (an input prompt may precede it on its line)."""
    return json.loads(text[text.rindex('{\n  "assessment_id"') :])


def item_texts(made) -> list[str]:
    return [entry.item.question for entry in made.queue]


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["assessment", "--help"],
        ["assessment", "create", "--help"],
        ["assessment", "status", "--help"],
        ["label", "--help"],
        ["label-status", "--help"],
        ["freeze-human-reference", "--help"],
    ],
)
def test_cli_help_lists_commands(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 0
    out = capsys.readouterr().out
    if argv == ["--help"]:
        for command in evaluation_cli.COMMANDS:
            assert command in out
    else:
        assert "--artifact-root" in out or argv == ["assessment", "--help"]


def test_label_refuses_non_interactive_stdin(root, accepted, capsys, monkeypatch):
    made = make(root, accepted)
    before = file_hashes(made.directory)
    # Answers that would label every item if the terminal check were missing.
    script = f"label {ASSESSMENT}\n" + "1\n1\n1\n1\n1\n1\n\ny\n" * len(made.queue)
    for stdin, stdout in (
        (Pipe(script), Pipe()),
        (Pipe(script), Terminal()),
        (Terminal(script), Pipe()),
    ):
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", stdout)
        code, out, err = invoke(["label", *common(root), "--reviewer", REVIEWER], capsys)
        shown = out + stdout.getvalue()
        assert code == 2
        assert "interactive terminal" in err
        assert shown == ""
        assert not any(text in shown for text in item_texts(made))
        assert stdin.tell() == 0  # nothing was read
    assert file_hashes(made.directory) == before
    assert not (made.directory / labels.LEDGER).exists()
    assert not (made.directory / labels.CHECKPOINT).exists()


def test_freeze_refuses_non_interactive_stdin(root, accepted, capsys, monkeypatch):
    made = make(root, accepted)
    label_some(made, accepted)
    before = file_hashes(made.directory)
    monkeypatch.setattr(sys, "stdin", Pipe(f"freeze {ASSESSMENT}\n"))
    argv = ["freeze-human-reference", *common(root), "--reviewer", REVIEWER, "--declare-blind"]
    code, out, err = invoke(argv, capsys)
    assert code == 2
    assert out == ""
    assert "interactive terminal" in err
    assert file_hashes(made.directory) == before
    assert not (made.directory / labels.REFERENCE).exists()


def test_no_flag_or_env_bypasses_the_terminal_check(root, accepted, capsys, monkeypatch):
    made = make(root, accepted)
    first = made.queue[0].blind_id
    for flag in (
        ["--decisions", "1", "1", "1", "1", "1", "1"],
        ["--item-id", first],
        ["--yes"],
        ["--non-interactive"],
        ["--review-stage", "blind"],
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main(["label", *common(root), "--reviewer", REVIEWER, *flag])
        assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        cli.main(["freeze-human-reference", *common(root), "--reviewer", REVIEWER, "--yes"])
    assert exc.value.code == 2
    capsys.readouterr()
    for name in (
        "BONSAI_HELP_INTERACTIVE",
        "BONSAI_HELP_ALLOW_NON_INTERACTIVE",
        "BONSAI_HELP_ASSUME_TTY",
        "BONSAI_HELP_YES",
    ):
        monkeypatch.setenv(name, "1")
    monkeypatch.setattr(sys, "stdin", Pipe(f"label {ASSESSMENT}\n"))
    for argv in (
        ["label", *common(root), "--reviewer", REVIEWER],
        ["freeze-human-reference", *common(root), "--reviewer", REVIEWER, "--declare-blind"],
    ):
        code, out, err = invoke(argv, capsys)
        assert (code, out) == (2, "")
        assert "interactive terminal" in err
    assert not (made.directory / labels.LEDGER).exists()


def test_assessment_create_and_status_exit_codes(root, accepted, tmp_path, capsys):
    draft = write_rubric(tmp_path, status="assistant_drafted", name="draft-rubric.json")
    code, out, err = invoke(create_args(root, rubric=draft), capsys)
    assert (code, out) == (1, "")
    assert "assistant_drafted" in err
    code, _, err = invoke(create_args(root, "synthetic-unknown-cohort"), capsys)
    assert code == 1 and "no cohort" in err
    for count in (7, 15, 0):
        code, _, err = invoke(create_args(root, count=count), capsys)
        assert code == 2, count
    code, _, _ = invoke(create_args(root, BASELINE, BASELINE), capsys)
    assert code == 2
    code, _, _ = invoke(create_args(root, SOURCES["smoke"].cohort_id), capsys)
    assert code == 1
    with pytest.raises(SystemExit) as exc:
        cli.main(create_args(root, count="many"))
    assert exc.value.code == 2
    capsys.readouterr()
    assert not (root / "assessments" / ASSESSMENT).exists()

    code, out, err = invoke(create_args(root), capsys)
    assert code == 0, err
    summary = json.loads(out)
    assert summary["assessment_id"] == ASSESSMENT
    assert summary["selected"] == 20
    assert summary["rubric_sha256"] == load(root, accepted).manifest["rubric_sha256"]
    assert not any(
        (root / "assessments" / ASSESSMENT / name).exists()
        for name in (labels.LEDGER, labels.CHECKPOINT, labels.LOCK)
    )
    before = file_hashes(root / "assessments" / ASSESSMENT)
    code, out, err = invoke(create_args(root, seed="another-seed"), capsys)
    assert (code, out) == (1, "")
    assert "already exists" in err
    assert file_hashes(root / "assessments" / ASSESSMENT) == before

    code, out, _ = invoke(["assessment", "status", *common(root)], capsys)
    assert code == 0
    status = json.loads(out)
    assert status["selected"] == 20 and status["ledger"] == "none"
    assert status["rubric_matches_current"] is True
    code, _, err = invoke(["assessment", "status", *common(root, "synthetic-missing")], capsys)
    assert code == 1 and "no assessment" in err
    code, _, _ = invoke(["assessment", "status", *common(root, "../escape")], capsys)
    assert code == 2


def test_status_reports_a_changed_rubric_and_label_refuses_it(root, accepted, capsys, monkeypatch):
    """The repository rubric (still a draft) differs from the assessment's pin."""
    made = make(root, accepted)
    monkeypatch.setattr(evaluation_cli, "RUBRIC", REPOSITORY / "config/rubric.json")
    code, out, _ = invoke(["assessment", "status", *common(root)], capsys)
    assert code == 0 and json.loads(out)["rubric_matches_current"] is False
    shown = terminal(monkeypatch, f"label {ASSESSMENT}\n" + "1\n" * 6 + "\ny\n")
    code, out, err = invoke(["label", *common(root), "--reviewer", REVIEWER], capsys)
    assert code == 1
    assert "rubric changed since the assessment was created" in err
    assert not any(text in shown.getvalue() + out for text in item_texts(made))
    assert sys.stdin.tell() == 0
    assert not (made.directory / labels.LEDGER).exists()


def test_status_commands_never_reveal_arm_or_item_ids(root, accepted, capsys):
    code, created, err = invoke(create_args(root, BASELINE, CORRECTED), capsys)
    assert code == 0, err
    made = load(root, accepted)
    label_some(made, accepted, 7)
    outputs = [created]
    for argv in (["assessment", "status", *common(root)], ["label-status", *common(root)]):
        code, out, err = invoke(argv, capsys)
        assert code in (0, 1), err
        outputs.append(out + err)
    status = json.loads(outputs[-1])
    assert status["selected"] == 40 and status["completed"] == 7
    assert status["pending_blind_ids"] == [e.blind_id for e in made.queue[7:]]
    text = "\n".join(outputs)
    for sentinel in provenance_sentinels(root):
        assert sentinel not in text
    for word in ("baseline", "corrected", "run_id", "item_id", "trace"):
        assert word not in text
    for entry in made.queue:
        assert entry.trace_id not in text


def test_label_status_reports_interrupted_ledger_with_exit_1(root, accepted, capsys):
    made = make(root, accepted)
    code, out, _ = invoke(["label-status", *common(root)], capsys)
    assert code == 1 and json.loads(out)["status"] == "incomplete"
    label_some(made, accepted, 2)
    directory = made.directory
    with (directory / labels.LEDGER).open("ab") as stream:  # an append the checkpoint missed
        stream.write(b'{"synthetic": "torn')
    before = file_hashes(directory)
    code, out, _ = invoke(["label-status", *common(root)], capsys)
    status = json.loads(out)
    assert code == 1
    assert status["status"] == "not_intact" and status["ledger"] == "interrupted"
    assert "preserve and inspect" in status["problem"] or "interrupted" in status["problem"]
    assert file_hashes(directory) == before


def test_label_status_reports_leftover_lock_and_keeps_it(root, accepted, capsys):
    made = make(root, accepted)
    label_some(made, accepted, 1)
    lock = made.directory / labels.LOCK
    lock.write_text("synthetic leftover lock\n", encoding="utf-8")
    code, out, _ = invoke(["label-status", *common(root)], capsys)
    assert code == 1
    assert json.loads(out)["ledger"] == "locked"
    assert lock.read_text(encoding="utf-8") == "synthetic leftover lock\n"


def test_label_status_complete_exits_0(root, accepted, capsys):
    made = make(root, accepted)
    label_some(made, accepted)
    code, out, _ = invoke(["label-status", *common(root)], capsys)
    assert code == 0
    status = json.loads(out)
    assert status["status"] == "complete" and status["completed"] == 20


def test_errors_show_no_absolute_paths(root, accepted, tmp_path, capsys, monkeypatch):
    home = os.path.expanduser("~")
    missing = tmp_path / "synthetic-missing-rubric.json"
    inside = REPOSITORY / "src"
    cases = [
        create_args(root, rubric=missing),
        create_args(root, rubric=tmp_path),
        create_args(inside),
        ["label-status", *common(inside)],
        ["label-status", *common(root, "synthetic-missing")],
    ]

    def leaky(*args, **kwargs):
        raise assessment.AssessmentError(
            f"synthetic failure at {root}/assessments/x and {REPOSITORY}/config and {home}/x"
        )

    for argv in cases:
        code, out, err = invoke(argv, capsys)
        assert code in (1, 2) and err.startswith("error: "), argv
        for absolute in (str(tmp_path), str(REPOSITORY), home):
            assert absolute not in err
    monkeypatch.setattr(assessment, "create_assessment", leaky)
    code, _, err = invoke(create_args(root), capsys)
    assert code == 1
    assert "<artifact-root>/assessments/x" in err and "./config" in err and "~/x" in err
    for absolute in (str(tmp_path), str(REPOSITORY), home):
        assert absolute not in err


def test_label_through_a_terminal_saves_only_confirmed_items(root, accepted, capsys, monkeypatch):
    made = make(root, accepted)
    shown = terminal(monkeypatch, "label synthetic-wrong\n")
    code, out, err = invoke(["label", *common(root), "--reviewer", REVIEWER], capsys)
    assert code == 1 and "confirmation did not match" in err
    assert not any(text in shown.getvalue() for text in item_texts(made))
    assert not (made.directory / labels.LEDGER).exists()

    # One item saved, the next quit before its save: exit 1 (incomplete), one label.
    script = f"label {ASSESSMENT}\n" + "1\n0\nu\n1\n1\n1\n\ny\n" + "1\n1\nq\n"
    shown = terminal(monkeypatch, script)
    code, out, err = invoke(["label", *common(root), "--reviewer", REVIEWER], capsys)
    assert code == 1, err
    display = shown.getvalue()
    assert made.queue[0].item.question in display
    for sentinel in provenance_sentinels(root):
        assert sentinel not in display
    status = summary_of(display)
    assert status["completed"] == 1 and status["unresolved_decisions"] == 1
    records = read_records(made.directory / labels.LEDGER)
    assert len(records) == 1
    first = records[0]["label"]
    assert first["reviewer"] == REVIEWER and first["decisions"]["D3"] is None

    # An amendment needs both its blind id and the label it supersedes.
    for partial in (["--amend", first["blind_id"]], ["--supersedes", first["label_id"]]):
        code, _, err = invoke(["label", *common(root), "--reviewer", REVIEWER, *partial], capsys)
        assert code == 2 and "--amend" in err
    script = f"label {ASSESSMENT}\n" + "1\n" * 6 + "\ny\n"
    terminal(monkeypatch, script)
    amend = ["--amend", first["blind_id"], "--supersedes", first["label_id"]]
    code, _, err = invoke(["label", *common(root), "--reviewer", REVIEWER, *amend], capsys)
    assert code == 1, err
    records = read_records(made.directory / labels.LEDGER)
    assert len(records) == 2
    assert records[1]["label"]["supersedes_label_id"] == first["label_id"]
    assert records[1]["label"]["blind_id"] == first["blind_id"]


def test_freeze_through_a_terminal_needs_declaration_and_confirmation(
    root, accepted, capsys, monkeypatch
):
    made = make(root, accepted)
    reference = made.directory / labels.REFERENCE
    argv = ["freeze-human-reference", *common(root), "--reviewer", REVIEWER]
    terminal(monkeypatch, f"freeze {ASSESSMENT}\n")
    code, _, err = invoke([*argv, "--declare-blind"], capsys)
    assert code == 1 and "label every selected item" in err
    assert sys.stdin.tell() == 0  # refused before the confirmation was asked
    label_some(made, accepted)
    terminal(monkeypatch, f"freeze {ASSESSMENT}\n")
    code, _, err = invoke(argv, capsys)
    assert code == 1 and "--declare-blind" in err
    assert not reference.exists()
    terminal(monkeypatch, "freeze synthetic-wrong\n")
    code, _, err = invoke([*argv, "--declare-blind"], capsys)
    assert code == 1 and "nothing was frozen" in err
    assert not reference.exists()
    terminal(monkeypatch, "")
    code, _, err = invoke([*argv, "--declare-blind"], capsys)
    assert code == 1 and not reference.exists()

    shown = terminal(monkeypatch, f"freeze {ASSESSMENT}\n")
    code, _, err = invoke([*argv, "--declare-blind"], capsys)
    assert code == 0, err
    text = shown.getvalue()
    assert "recorded as the reviewer" in text
    summary = summary_of(text)
    frozen = json.loads(reference.read_text(encoding="utf-8"))
    assert summary["sha256"] == frozen["sha256"] and summary["labels"] == 20
    assert "groups" not in json.dumps(summary)
    for word in ("baseline", "corrected"):
        assert word not in text
    before = file_hashes(made.directory)
    terminal(monkeypatch, f"freeze {ASSESSMENT}\n")
    code, _, err = invoke([*argv, "--declare-blind"], capsys)
    assert code == 1 and "already exists" in err
    assert file_hashes(made.directory) == before
