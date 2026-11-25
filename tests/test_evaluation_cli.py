"""The assessment, labeling, judge and calibration commands: exit codes, blind output, the
terminal check.

Every assessment here is synthetic, built under `tmp_path` from the synthetic cohorts of
`evaluation_support`; every label is synthetic, by the reviewer "synthetic-reviewer". No
real label is entered or frozen, nothing is written under `runs/` or `data/`, and no model
is called. The tests that stand in a terminal replace `sys.stdin` and `sys.stdout` with
in-memory streams that report a terminal, on synthetic evidence only; no pseudo-terminal is
used. Every rubric marked `chad_accepted` is a synthetic copy whose review says it is not
Chad's.

The judge and calibration commands run on the same synthetic evidence. Every judge reply
is synthetic: the real Instructor client answers from an `httpx.MockTransport` passed to
`cli.main`, or a scripted fake judge prepares evidence through the library. No figure,
receipt, pool or selection here is a measurement.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import test_calibration
import test_judge
from evaluation_support import (
    FIXTURES,
    SOURCES,
    doc_config,
    fresh_root,
    profiles,
    provenance_sentinels,
    write_rubric,
)
from fakes import completion, embedding_response
from test_human_reference import decisions

from bonsai_help import (
    assessment,
    calibration,
    cli,
    evaluation_cli,
    judge,
    judge_examples,
    labels,
    qualification,
)
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


# --------------------------------------------------------- judge and calibration

JUDGE_COMMANDS = (
    "judge",
    "judge-status",
    "judge-qualify",
    "judge-examples",
    "calibrate",
    "judge-freeze",
)
KEY_ENV = test_judge.KEY_ENV
KEY_SENTINEL = test_judge.KEY_SENTINEL
JUDGE_MODEL = test_judge.JUDGE_MODEL
SMOKE = test_judge.SMOKE
ARM = test_judge.ARM
DEV = "dev-labels-cli"
EMBEDDING = "synthetic-embedding"  # the synthetic gate's embedding model


@pytest.fixture
def judge_key(monkeypatch):
    monkeypatch.setenv(KEY_ENV, KEY_SENTINEL)


def judge_config_file(directory: Path, root: Path, name="judge.json", **overrides) -> Path:
    """A synthetic judge config file (the values of `test_judge.config`)."""
    values = {
        "base_url": "http://127.0.0.1:8082/v1",
        "model": JUDGE_MODEL,
        "model_identity": test_judge.JUDGE_IDENTITY,
        "model_sha256": test_judge.JUDGE_SHA,
        "purpose": "smoke",
        "api_key_env": KEY_ENV,
        "artifact_root": str(root),
    }
    values.update(overrides)
    values = {k: v for k, v in values.items() if v is not None}
    path = directory / name
    path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    return path


def judgment_body(**decisions_by_dimension) -> dict:
    return {
        d: {
            "decision": decisions_by_dimension.get(d, 1),
            "reason": f"synthetic cli judge reason {d}",
        }
        for d in ("D1", "D2", "D3", "D4", "D5", "D6")
    }


class Server:
    """A synthetic local server on `httpx.MockTransport`: chat replies and embeddings."""

    def __init__(self, reply=None, model=JUDGE_MODEL):
        self.reply = reply or (lambda body: json.dumps(judgment_body()))
        self.model = model
        self.chat: list[dict] = []
        self.embeddings: list[dict] = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            self.embeddings.append(body)
            vectors = [[1.0, float(i % 3), 0.5] for i in range(len(body["input"]))]
            return httpx.Response(200, json=embedding_response(vectors, model=EMBEDDING))
        self.chat.append(body)
        return httpx.Response(200, json=completion(self.reply(body), model=self.model))

    @property
    def calls(self) -> int:
        return len(self.chat) + len(self.embeddings)


def run_cli(argv, capsys, server=None):
    code = cli.main(argv, transport=None if server is None else server.transport)
    out, err = capsys.readouterr()
    return code, out, err


def judge_args(config_path, assessment_id, judge_run_id, *extra):
    return [
        "judge",
        "--config",
        str(config_path),
        "--assessment-id",
        assessment_id,
        "--judge-run-id",
        judge_run_id,
        *extra,
    ]


def root_args(root, assessment_id, *extra):
    return ["--artifact-root", str(root), "--assessment-id", assessment_id, *extra]


def judges_dir(root, assessment_id) -> Path:
    return root / "assessments" / assessment_id / judge.JUDGES


@pytest.mark.parametrize("command", JUDGE_COMMANDS)
def test_cli_help_lists_judge_commands(command, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    top = capsys.readouterr().out
    assert command in top and command in evaluation_cli.COMMANDS
    with pytest.raises(SystemExit) as exc:
        cli.main([command, "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--artifact-root" in out
    expected = {
        "judge": ["--config", "--qualification", "--examples", "--frozen-judge", "--resume"],
        "judge-status": ["--assessment-id", "--judge-run-id"],
        "judge-qualify": ["--smoke-assessment-id", "--smoke-judge-run-id", "--qualification-id"],
        "judge-examples": ["--config", "--pool-id"],
        "calibrate": ["--judge-run-id", "--report-id"],
        "judge-freeze": ["--report-id", "--selection-id"],
    }[command]
    for flag in expected:
        assert flag in out, (command, flag)


def test_judge_cli_exit_codes(root, accepted, tmp_path, capsys, judge_key):
    test_judge.smoke_assessment(root, accepted)
    server = Server()
    smoke = judge_config_file(tmp_path, root)

    # A bad config gives 2 before any directory or call.
    bad_configs = {
        "hosted": {"hosted": True},
        "public-ip": {"base_url": "http://8.8.8.8:8082/v1"},
        "no-v1": {"base_url": "http://127.0.0.1:8082/api"},
        "url-credentials": {"base_url": "http://user:synthetic-pass@127.0.0.1:8082/v1"},
        "two-credentials": {"api_key_file": str(tmp_path / "synthetic-key")},
        "attempts": {"max_attempts": 4},
        "measured-no-identity": {"purpose": "measured", "model_sha256": None},
        "bad-prompt": {"prompt_path": str(tmp_path / "judge-v1.md")},
    }
    (tmp_path / "judge-v1.md").write_text("synthetic prompt with no placeholder\n")
    for name, change in bad_configs.items():
        path = judge_config_file(tmp_path, root, name=f"bad-{name}.json", **change)
        code, out, err = run_cli(judge_args(path, SMOKE, "smoke-bad"), capsys, server)
        assert (code, out) == (2, ""), (name, err)
        assert err.startswith("error: ") and "synthetic-pass" not in err, name
    not_json = tmp_path / "not-json.json"
    not_json.write_text("{ synthetic", encoding="utf-8")
    for path in (not_json, tmp_path / "synthetic-missing.json"):
        code, _, err = run_cli(judge_args(path, SMOKE, "smoke-bad"), capsys, server)
        assert code == 2, err
    other_root = tmp_path / "synthetic-other-root"
    code, _, err = run_cli(
        [*judge_args(smoke, SMOKE, "smoke-bad"), "--artifact-root", str(other_root)],
        capsys,
        server,
    )
    assert code == 2 and "artifact_root" in err
    assert server.calls == 0 and not judges_dir(root, SMOKE).exists()

    # An unfrozen reference refuses a measured run (1) before any directory or call.
    test_judge.create(root, accepted, ARM, [test_judge.BASELINE.cohort_id], 20)
    measured = judge_config_file(tmp_path, root, name="measured.json", purpose="measured")
    code, out, err = run_cli(
        judge_args(measured, ARM, "v1", "--qualification", "q-1"), capsys, server
    )
    assert (code, out) == (1, "")
    assert "frozen human reference" in err
    assert server.calls == 0 and not judges_dir(root, ARM).exists()
    # A smoke run is refused on an arm assessment.
    code, _, err = run_cli(judge_args(smoke, ARM, "smoke-arm"), capsys, server)
    assert code == 1 and "arm assessment" in err
    assert server.calls == 0 and not judges_dir(root, ARM).exists()

    # Exhaustion: every reply malformed; the run is incomplete, exit 3.
    broken = Server(reply=lambda body: "synthetic malformed reply {")
    one = judge_config_file(tmp_path, root, name="one.json", max_attempts=1)
    code, out, err = run_cli(judge_args(one, SMOKE, "smoke-exhausted"), capsys, broken)
    assert code == 3, err
    status = json.loads(out)
    assert status["status"] == "incomplete" and status["resolved"] == 0
    assert len(status["unresolved"]) == 5 and len(broken.chat) == 5
    code, out, _ = run_cli(
        ["judge-status", *root_args(root, SMOKE, "--judge-run-id", "smoke-exhausted")], capsys
    )
    assert code == 3 and json.loads(out)["status"] == "incomplete"
    # A resume gives exhausted items no extra attempt and stays at exit 3.
    code, _, _ = run_cli(judge_args(one, SMOKE, "smoke-exhausted", "--resume"), capsys, broken)
    assert code == 3 and len(broken.chat) == 5

    # A complete run: 0.
    code, out, err = run_cli(judge_args(smoke, SMOKE, "smoke-1"), capsys, server)
    assert code == 0, err
    status = json.loads(out)
    assert status["status"] == "complete" and status["resolved"] == 5
    assert status["reported_models"] == [JUDGE_MODEL]
    code, out, _ = run_cli(
        ["judge-status", *root_args(root, SMOKE, "--judge-run-id", "smoke-1")], capsys
    )
    assert code == 0 and json.loads(out) == status

    # A second create of the same id is refused (1); so is resuming a complete run.
    calls = server.calls
    before = test_judge.file_hashes(judges_dir(root, SMOKE) / "smoke-1")
    code, out, err = run_cli(judge_args(smoke, SMOKE, "smoke-1"), capsys, server)
    assert (code, out) == (1, "") and "already exists" in err
    code, _, err = run_cli(judge_args(smoke, SMOKE, "smoke-1", "--resume"), capsys, server)
    assert code == 1 and "immutable" in err
    assert server.calls == calls
    assert test_judge.file_hashes(judges_dir(root, SMOKE) / "smoke-1") == before
    code, _, err = run_cli(
        ["judge-status", *root_args(root, SMOKE, "--judge-run-id", "synthetic-none")], capsys
    )
    assert code == 1 and "no judge run" in err

    # A measured run on a frozen reference with a qualification: 0.
    other = test_judge.frozen(root, accepted, assessment_id="arm-frozen")
    code, out, err = run_cli(
        ["judge-qualify", "--config", str(measured), "--smoke-assessment-id", SMOKE]
        + ["--smoke-judge-run-id", "smoke-1", "--qualification-id", "q-1"],
        capsys,
    )
    assert code == 0, err
    receipt = json.loads(out)
    assert receipt["qualification_id"] == "q-1" and receipt["basis"]["kind"] == "distinct_model"
    code, _, err = run_cli(
        ["judge-qualify", "--config", str(measured), "--smoke-assessment-id", SMOKE]
        + ["--smoke-judge-run-id", "smoke-1", "--qualification-id", "q-1"],
        capsys,
    )
    assert code == 1 and "already exists" in err
    code, out, err = run_cli(
        judge_args(measured, "arm-frozen", "v1", "--qualification", "q-1"), capsys, server
    )
    assert code == 0, err
    assert json.loads(out)["resolved"] == len(other.queue)
    # Without a qualification a measured run is refused.
    code, _, err = run_cli(judge_args(measured, "arm-frozen", "v1-b"), capsys, server)
    assert code == 1 and "qualification" in err


def test_judge_cli_never_prints_credentials(root, accepted, tmp_path, capsys, monkeypatch):
    test_judge.smoke_assessment(root, accepted)
    key_file = tmp_path / "synthetic-judge-key-file"
    key_file.write_text(KEY_SENTINEL + "\n", encoding="utf-8")
    by_file = judge_config_file(
        tmp_path, root, name="by-file.json", api_key_env=None, api_key_file=str(key_file)
    )
    monkeypatch.setenv(KEY_ENV, KEY_SENTINEL)
    by_env = judge_config_file(tmp_path, root, name="by-env.json", max_attempts=1)
    echo = Server(
        reply=lambda body: json.dumps(
            judgment_body() | {"D2": {"decision": 1, "reason": f"synthetic echo {KEY_SENTINEL}"}}
        )
    )
    outputs = []
    code, out, err = run_cli(judge_args(by_env, SMOKE, "smoke-echo"), capsys, echo)
    assert code == 3  # every reply echoed the key: each attempt failed, redacted
    outputs.append(out + err)
    attempts = test_judge.read_records(judges_dir(root, SMOKE) / "smoke-echo" / judge.ATTEMPTS)
    assert {a["error_type"] for a in attempts} == {"CredentialEcho"}
    code, out, err = run_cli(judge_args(by_file, SMOKE, "smoke-file"), capsys, Server())
    assert code == 0, err
    outputs.append(out + err)
    for run_id in ("smoke-echo", "smoke-file"):
        code, out, err = run_cli(
            ["judge-status", *root_args(root, SMOKE, "--judge-run-id", run_id)], capsys
        )
        outputs.append(out + err)

    # A refusal whose message carried the key is scrubbed before it is shown.
    def leaky(*args, **kwargs):
        raise judge.JudgeError(f"synthetic refusal holding {KEY_SENTINEL}")

    monkeypatch.setattr(judge, "judge_run", leaky)
    code, out, err = run_cli(judge_args(by_file, SMOKE, "smoke-leak"), capsys, Server())
    assert code == 1 and "[REDACTED]" in err
    outputs.append(out + err)
    # A missing credential names the source kind, never a value or the variable's content.
    monkeypatch.delenv(KEY_ENV)
    code, out, err = run_cli(judge_args(by_env, SMOKE, "smoke-nokey"), capsys, Server())
    assert code == 2 and "API key is missing" in err
    outputs.append(out + err)
    text = "\n".join(outputs)
    for secret in (KEY_SENTINEL, str(key_file), key_file.name, KEY_ENV):
        assert secret not in text, secret
    for path in judges_dir(root, SMOKE).rglob("*"):
        if path.is_file():
            assert KEY_SENTINEL not in path.read_text(encoding="utf-8")


def calibrate_args(root, assessment_id, judge_run_id, report_id):
    return [
        "calibrate",
        *root_args(root, assessment_id, "--judge-run-id", judge_run_id),
        "--report-id",
        report_id,
    ]


def freeze_args(root, assessment_id, report_id, selection_id):
    return [
        "judge-freeze",
        *root_args(root, assessment_id, "--report-id", report_id),
        "--selection-id",
        selection_id,
    ]


def test_calibrate_exit_codes(root, accepted, tmp_path, capsys, judge_key):
    made = test_calibration.frozen_with(root, accepted)
    judge_config = test_judge.measured(root)
    test_judge.qualify(root, accepted, judge_config)
    run = test_calibration.run
    assert (
        run(root, made, "v1", judge_config, test_calibration.agreeing(made))["status"] == "complete"
    )
    last = made.manifest["display_order"][-1]
    gap = test_calibration.by_item(
        made,
        lambda b, attempt: test_calibration.broken(b) if b == last else test_calibration.reply(b),
    )
    assert run(root, made, "v1-gap", judge_config, gap)["status"] == "incomplete"

    # ready: 0, the status on the first line, no judge reason or paired decision printed.
    code, out, err = run_cli(calibrate_args(root, ARM, "v1", "r-ready"), capsys)
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0] == "status: ready"
    assert test_calibration.REASON not in out and JUDGE_MODEL not in out
    main, side = test_calibration.report_paths(root, ARM, "r-ready")
    assert main.exists() and side.exists()
    assert json.loads(main.read_text(encoding="utf-8"))["status"] == "ready"

    # diagnostic: 0, never calibration, written.
    code, out, err = run_cli(calibrate_args(root, SMOKE, "smoke-1", "r-smoke"), capsys)
    assert code == 0, err
    assert out.splitlines()[0] == "status: diagnostic (never calibration)"
    assert test_calibration.report_paths(root, SMOKE, "r-smoke")[0].exists()

    # pending: 1, still written.
    code, out, err = run_cli(calibrate_args(root, ARM, "v1-gap", "r-pending"), capsys)
    assert code == 1
    assert out.splitlines()[0] == "status: pending"
    assert any("incomplete" in line for line in out.splitlines())
    main, side = test_calibration.report_paths(root, ARM, "r-pending")
    assert main.exists() and side.exists()

    # A report id is written once.
    before = test_calibration.sha(test_calibration.report_paths(root, ARM, "r-ready")[0])
    code, out, err = run_cli(calibrate_args(root, ARM, "v1", "r-ready"), capsys)
    assert (code, out) == (1, "") and "already exists" in err
    assert test_calibration.sha(test_calibration.report_paths(root, ARM, "r-ready")[0]) == before

    # judge-freeze refuses a diagnostic or pending report (1), accepts the ready one (0).
    for assessment_id, report_id in ((SMOKE, "r-smoke"), (ARM, "r-pending")):
        code, out, err = run_cli(freeze_args(root, assessment_id, report_id, "sel-x"), capsys)
        assert (code, out) == (1, ""), report_id
        assert "ready" in err
    assert not (root / calibration.SELECTIONS / "sel-x.json").exists()
    code, out, err = run_cli(freeze_args(root, ARM, "r-ready", "sel-1"), capsys)
    assert code == 0, err
    shown = json.loads(out)
    selection = calibration.load_selection(root, "sel-1")
    assert shown["sha256"] == selection["sha256"]
    assert (shown["report_id"], shown["prompt_version"]) == ("r-ready", "judge-v1")
    assert "frozen_identity" not in shown
    code, _, err = run_cli(freeze_args(root, ARM, "r-ready", "sel-1"), capsys)
    assert code == 1 and "already exists" in err

    # A later measured run must match the frozen judge exactly.
    other = test_calibration.frozen_with(
        root, accepted, assessment_id="arm-2", cohorts=(SOURCES["baseline2"].cohort_id,)
    )
    measured = judge_config_file(tmp_path, root, name="measured.json", purpose="measured")
    server = Server()
    code, out, err = run_cli(
        judge_args(measured, "arm-2", "b8-v1", "--qualification", "q-1")
        + ["--frozen-judge", "sel-1"],
        capsys,
        server,
    )
    assert code == 0, err
    assert json.loads(out)["resolved"] == len(other.queue)
    changed = judge_config_file(
        tmp_path, root, name="changed.json", purpose="measured", max_tokens=1400
    )
    calls = server.calls
    code, _, err = run_cli(
        judge_args(changed, "arm-2", "b8-v1b", "--qualification", "q-1")
        + ["--frozen-judge", "sel-1"],
        capsys,
        server,
    )
    assert code == 1 and server.calls == calls
    code, _, err = run_cli(
        judge_args(measured, "arm-2", "b8-v1c", "--qualification", "q-1")
        + ["--frozen-judge", "synthetic-missing"],
        capsys,
        server,
    )
    assert code == 1 and "no judge selection" in err


def test_judge_examples_cli(root, accepted, tmp_path, capsys, judge_key):
    """A development pool through the CLI: its summary holds no item text or reason."""
    judge_config = test_judge.measured(root)
    test_judge.qualify(root, accepted, judge_config)
    made = test_calibration.frozen_with(
        root,
        accepted,
        assessment_id=DEV,
        cohorts=(SOURCES["development"].cohort_id,),
        count=10,
    )
    measured = judge_config_file(
        tmp_path, root, name="measured.json", purpose="measured", embedding_model=EMBEDDING
    )
    without = judge_config_file(tmp_path, root, name="no-embedding.json", purpose="measured")
    disagreeing = Server(reply=lambda body: json.dumps(judgment_body(D5=0)))
    code, _, err = run_cli(
        judge_args(without, DEV, "dev-v1", "--qualification", "q-1"), capsys, disagreeing
    )
    assert code == 0, err

    pool_args = ["judge-examples", "--assessment-id", DEV, "--judge-run-id", "dev-v1"]
    code, out, err = run_cli(
        [*pool_args, "--config", str(without), "--pool-id", "pool-1"], capsys, Server()
    )
    assert (code, out) == (2, "") and "embedding_model" in err
    server = Server()
    code, out, err = run_cli(
        [*pool_args, "--config", str(measured), "--pool-id", "pool-1"], capsys, server
    )
    assert code == 0, err
    assert server.chat == [] and len(server.embeddings) == 1
    summary = json.loads(out)
    pool = judge_examples.load_pool(root, "pool-1")
    assert summary["sha256"] == pool["sha256"]
    assert summary["entries"] == len(made.queue) == summary["entries_by_dimension"]["D5"]
    assert summary["source"]["assessment_id"] == DEV
    for entry in made.queue:
        assert entry.item.question not in out and entry.trace_id not in out
    assert "synthetic cli judge reason" not in out and test_calibration.NOTE not in out
    code, _, err = run_cli(
        [*pool_args, "--config", str(measured), "--pool-id", "pool-1"], capsys, server
    )
    assert code == 1 and "already exists" in err
    # An arm assessment never gives a pool.
    test_judge.frozen(root, accepted)
    code, _, err = run_cli(
        judge_args(without, ARM, "v1", "--qualification", "q-1"), capsys, Server()
    )
    assert code == 0, err
    code, _, err = run_cli(
        ["judge-examples", "--config", str(measured), "--assessment-id", ARM]
        + ["--judge-run-id", "v1", "--pool-id", "pool-arm"],
        capsys,
        Server(),
    )
    assert code == 1
    assert not (root / judge_examples.POOLS / "pool-arm").exists()
    assert qualification.receipt_path(root, "q-1").exists()


def test_cli_errors_show_no_absolute_paths(root, accepted, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(KEY_ENV, KEY_SENTINEL)
    home = os.path.expanduser("~")
    inside = REPOSITORY / "src"
    config_path = judge_config_file(tmp_path, root)
    cases = [
        judge_args(tmp_path / "synthetic-missing.json", SMOKE, "s"),
        judge_args(tmp_path, SMOKE, "s"),
        judge_args(config_path, "synthetic-missing", "s"),
        judge_args(config_path, SMOKE, "../escape"),
        ["judge-status", *root_args(inside, SMOKE, "--judge-run-id", "s")],
        ["judge-status", *root_args(root, "synthetic-missing", "--judge-run-id", "s")],
        calibrate_args(inside, ARM, "v1", "r"),
        calibrate_args(root, "synthetic-missing", "v1", "r"),
        freeze_args(root, ARM, "synthetic-missing", "sel"),
        ["judge-qualify", "--config", str(config_path), "--smoke-assessment-id", SMOKE]
        + ["--smoke-judge-run-id", "s", "--qualification-id", "q"],
    ]
    for argv in cases:
        code, out, err = run_cli(argv, capsys, Server())
        assert code in (1, 2) and err.startswith("error: "), (argv, err)
        for absolute in (str(tmp_path), str(REPOSITORY), home):
            assert absolute not in err, (argv, err)

    def leaky(*args, **kwargs):
        raise calibration.CalibrationError(
            f"synthetic failure at {root}/assessments/x and {REPOSITORY}/config and {home}/x"
        )

    monkeypatch.setattr(calibration, "calibration_report", leaky)
    code, _, err = run_cli(calibrate_args(root, ARM, "v1", "r"), capsys)
    assert code == 1
    assert "<artifact-root>/assessments/x" in err and "./config" in err and "~/x" in err
    for absolute in (str(tmp_path), str(REPOSITORY), home):
        assert absolute not in err


def test_judge_cli_interrupt_keeps_the_run_for_resume(root, accepted, tmp_path, capsys, judge_key):
    test_judge.smoke_assessment(root, accepted)
    smoke = judge_config_file(tmp_path, root)
    state = {"calls": 0}

    def reply(body):
        state["calls"] += 1
        if state["calls"] == 3:
            raise KeyboardInterrupt  # a synthetic Ctrl-C during the third call
        return json.dumps(judgment_body())

    code, out, err = run_cli(judge_args(smoke, SMOKE, "smoke-1"), capsys, Server(reply=reply))
    assert (code, out) == (130, "")
    assert "judge-status" in err and "--resume" in err
    code, out, _ = run_cli(
        ["judge-status", *root_args(root, SMOKE, "--judge-run-id", "smoke-1")], capsys
    )
    status = json.loads(out)
    assert code == 1 and status["status"] == "interrupted"
    assert len(status["unknown_outcomes"]) == 1
    code, out, err = run_cli(
        judge_args(smoke, SMOKE, "smoke-1", "--resume"), capsys, Server(reply=reply)
    )
    assert code == 0, err
    status = json.loads(out)
    assert status["status"] == "complete" and len(status["unknown_outcomes"]) == 1
    assert status["started_attempts"] == 6  # the unknown attempt was used up, not repeated
