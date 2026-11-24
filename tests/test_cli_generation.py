"""The generation commands: exit codes, JSON summaries and credential hygiene.

Every model and embedding response comes from a synthetic fake transport; no network.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import httpx
import pytest
from fakes import FAKE_BASE_URL, FAKE_KEY, FAKE_MODEL, FakeTransport, completion
from fakes import embedding_response as embeddings
from test_gate import good_item
from test_generation import offered_ids

from bonsai_help import cli, generate
from bonsai_help.tracing import artifact_hashes

KEY_ENV = "BONSAI_HELP_SYNTHETIC_TEST_KEY"


def model_transport(*, broken=False) -> FakeTransport:
    """Chat completions get a distinct check-passing item; embeddings are one-hot."""
    counter = itertools.count(1)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            texts = body["input"]
            vectors = [
                [1.0 if i == n else 0.0 for i in range(len(texts))] for n in range(len(texts))
            ]
            return httpx.Response(200, json=embeddings(vectors))
        n = next(counter)
        if broken:
            return httpx.Response(200, json=completion("{synthetic-broken-json " + FAKE_KEY))
        output = {
            "item": good_item(n) | {"question": f"How do I add synthetic wall {n} in Bonsai?"},
            "cited_section_ids": offered_ids(body["messages"])[:1],
        }
        return httpx.Response(200, json=completion(json.dumps(output)))

    return FakeTransport(handler)


@pytest.fixture
def run_config(tmp_path, monkeypatch):
    monkeypatch.setenv(KEY_ENV, FAKE_KEY)
    path = tmp_path / "run-config.json"
    path.write_text(
        json.dumps(
            {
                "base_url": FAKE_BASE_URL,
                "model": FAKE_MODEL,
                "embedding_model": "synthetic-embedding",
                "seed": 7,
                "artifact_root": str(tmp_path / "runs"),
                "api_key_env": KEY_ENV,
            }
        )
    )
    return path


def invoke(capsys, argv, transport=None):
    code = cli.main(argv, transport=(transport or model_transport()).transport)
    out, err = capsys.readouterr()
    assert FAKE_KEY not in out and FAKE_KEY not in err
    assert "Traceback" not in err
    return code, out, err


def test_cli_exit_codes(tmp_path, run_config, capsys):
    config, root = str(run_config), str(tmp_path / "runs")
    code, out, _ = invoke(capsys, ["generate", "--config", config, "--run-id", "r1"])
    assert code == 0 and json.loads(out)["status"] == "complete"
    code, out, _ = invoke(capsys, ["gate", "--config", config, "--run-id", "r1"])
    assert code == 0 and json.loads(out)["distribution"]["passed"] is True
    # A second gate is refused: evidence is written once (check failed, 1).
    code, _, err = invoke(capsys, ["gate", "--config", config, "--run-id", "r1"])
    assert code == 1 and err.startswith("error:")
    # The same run ID again is a usage error (2), not an overwrite.
    code, _, err = invoke(capsys, ["generate", "--config", config, "--run-id", "r1"])
    assert code == 2 and "new" in err
    code, _, _ = invoke(capsys, ["generate", "--config", config, "--run-id", "r2", "--count", "7"])
    assert code == 2

    # Generation exhaustion is a controlled failure (3) with its evidence kept.
    code, out, _ = invoke(
        capsys, ["generate", "--config", config, "--run-id", "r3"], model_transport(broken=True)
    )
    assert code == 3 and json.loads(out)["status"] == "incomplete"
    assert (tmp_path / "runs/r3/attempts.jsonl").read_text().count("\n") == 15

    # Collection out of batches (3); status not ready (1).
    args = ["--collection-id", "c1", "--batch-count", "5", "--max-batches", "1"]
    code, out, _ = invoke(capsys, ["collect", "--config", config, *args])
    assert code == 3 and json.loads(out)["status"] == "incomplete"
    status = ["collection-status", "--collection-id", "c1", "--artifact-root", root]
    code, out, _ = invoke(capsys, status)
    assert code == 1 and json.loads(out)["status"] == "incomplete"
    freeze = ["cohort", "--collection-id", "c1", "--cohort-id", "k1", "--artifact-root", root]
    code, _, err = invoke(capsys, freeze)
    assert code == 1 and "not ready" in err

    # A ready collection freezes into a cohort (0) that verifies (0).
    args = ["--collection-id", "c2", "--batch-count", "50", "--max-batches", "1"]
    code, out, _ = invoke(capsys, ["collect", "--config", config, *args])
    assert code == 0 and json.loads(out)["status"] == "ready"
    freeze = ["cohort", "--collection-id", "c2", "--cohort-id", "k2", "--artifact-root", root]
    code, out, _ = invoke(capsys, freeze)
    assert code == 0 and len(json.loads(out)["item_ids"]) == 50
    code, out, _ = invoke(capsys, ["cohort-status", "--cohort-id", "k2", "--artifact-root", root])
    assert code == 0 and json.loads(out)["cohort_id"] == "k2"
    code, _, _ = invoke(capsys, ["cohort-status", "--cohort-id", "nope", "--artifact-root", root])
    assert code == 1

    # A leftover writer lock is evidence to inspect (1), and it is left in place.
    lock = tmp_path / "runs/r3/.generation.lock"
    lock.write_text("synthetic leftover")
    code, _, err = invoke(capsys, ["gate", "--config", config, "--run-id", "r3"])
    assert code == 1 and "lock" in err and lock.exists()


def test_cli_config_errors_exit_2(tmp_path, run_config, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"base_url": "https://example.com/v1", "model": "m"}))
    for path in (bad, tmp_path / "missing.json"):
        for command in (["generate", "--run-id", "r"], ["gate", "--run-id", "r"]):
            code, _, err = invoke(capsys, [command[0], "--config", str(path), *command[1:]])
            assert code == 2 and err.startswith("error:")
    code, _, _ = invoke(capsys, ["collect", "--config", str(bad), "--collection-id", "c"])
    assert code == 2
    inside = ["collection-status", "--collection-id", "c", "--artifact-root", "src"]
    code, _, _ = invoke(capsys, inside)
    assert code == 2
    with pytest.raises(SystemExit) as raised:
        cli.main(["generate", "--run-id", "r"])
    assert raised.value.code == 2
    capsys.readouterr()


def leaky(request: httpx.Request) -> httpx.Response:
    # A hostile endpoint echoes the credential in every failure it returns.
    return httpx.Response(401, json={"error": {"message": f"bad key {FAKE_KEY}"}})


def leaky_embeddings() -> FakeTransport:
    """Chat completions as in `model_transport`; every embedding request is a leaky 401."""
    good = model_transport()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return leaky(request)
        return good._handler(request)

    return FakeTransport(handler)


def embedding_requests(transport: FakeTransport) -> int:
    return sum(call.url.path.endswith("/embeddings") for call in transport.calls)


def test_cli_never_prints_credentials(tmp_path, run_config, monkeypatch, capsys, caplog):
    config = str(run_config)
    gate_leak = FakeTransport(leaky)
    collect_leak = leaky_embeddings()
    paths = [
        (["generate", "--config", config, "--run-id", "x1"], FakeTransport(leaky)),
        (["generate", "--config", config, "--run-id", "x2"], model_transport()),
        (["gate", "--config", config, "--run-id", "x2"], gate_leak),
        (["gate", "--config", config, "--run-id", "absent"], None),
        (
            [
                "collect",
                "--config",
                config,
                "--collection-id",
                "c",
                "--batch-count",
                "5",
                "--max-batches",
                "1",
            ],
            FakeTransport(leaky),
        ),
        (
            [
                "collect",
                "--config",
                config,
                "--collection-id",
                "c-embed",
                "--batch-count",
                "5",
                "--max-batches",
                "1",
            ],
            collect_leak,
        ),
        (
            [
                "generate",
                "--config",
                config,
                "--run-id",
                "x3",
                "--fixtures-dir",
                str(tmp_path / "no-fixtures"),
            ],
            None,
        ),
        (["generate", "--config", config, "--run-id", "../escape"], None),
    ]
    results = [invoke(capsys, argv, transport) for argv, transport in paths]
    # exhaustion 3, complete 0, embedding failed 1, no run 1, collection out of batches 3,
    # embedding failed inside collect 1, fixture slice does not verify 1, escaping ID 2.
    assert [code for code, _, _ in results] == [3, 0, 1, 1, 3, 1, 1, 2]
    for code, _, err in results:
        # Failures are one stderr line: no library log output beside the error.
        assert len(err.splitlines()) <= 1
        assert err == "" or err.startswith("error:")
    # Both embedding failures reached the key-echoing endpoint, and wrote no gate report.
    assert embedding_requests(gate_leak) >= 1 and embedding_requests(collect_leak) >= 1
    for (_, _, err), run in ((results[2], "x2"), (results[5], "c-embed-b01")):
        assert err.startswith("error: embedding failed") and "[REDACTED]" in err
        assert not (tmp_path / "runs" / run / "gate-report.json").exists()
    # The instructor library logs each failed call; the CLI keeps it quiet (the attempt
    # ledger is the record), so a terminal shows only the error line.
    assert not [r for r in caplog.records if r.name.startswith("instructor")]
    # A missing key and an unreadable key file are config errors (2).
    monkeypatch.delenv(KEY_ENV)
    code, _, err = invoke(capsys, ["generate", "--config", config, "--run-id", "x4"])
    assert code == 2 and "API key" in err
    by_file = json.loads(run_config.read_text())
    by_file["api_key_env"] = None  # exactly one credential source: the (missing) key file
    by_file["api_key_file"] = str(tmp_path / "no-such-key-file")
    keyfile_config = tmp_path / "keyfile-config.json"
    keyfile_config.write_text(json.dumps(by_file))
    code, _, err = invoke(capsys, ["generate", "--config", str(keyfile_config), "--run-id", "x5"])
    assert code == 2 and "API-key file" in err
    assert not (tmp_path / "runs/x4").exists() and not (tmp_path / "runs/x5").exists()
    attempts = Path(tmp_path / "runs/x1/attempts.jsonl").read_text()
    assert FAKE_KEY not in attempts


def test_cli_invalid_saved_record_is_evidence_not_config(tmp_path, run_config, capsys):
    config = str(run_config)
    code, _, _ = invoke(capsys, ["generate", "--config", config, "--run-id", "r1"])
    assert code == 0
    run = tmp_path / "runs/r1"
    lines = (run / "items.jsonl").read_text().splitlines()
    record = json.loads(lines[0])
    record["item"]["steps"] = ["one"]  # fails the payload schema (three steps or more)
    lines[0] = json.dumps(record)
    (run / "items.jsonl").write_text("\n".join(lines) + "\n")
    # Synthetic tampering that refreshes the ledger hashes, so only the schema catches it.
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["artifacts_sha256"] = artifact_hashes(run)
    (run / "manifest.json").write_text(json.dumps(manifest))
    code, _, err = invoke(capsys, ["gate", "--config", config, "--run-id", "r1"])
    assert code == 1 and err.startswith("error:")
    assert "run config" not in err and "item.steps" in err and "inspect" in err
    assert not (run / "gate-report.json").exists()


def test_cli_interrupt_exits_130_and_keeps_the_evidence(tmp_path, run_config, capsys):
    config = str(run_config)
    good = model_transport()
    chats = itertools.count(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if next(chats) == 3:
            raise KeyboardInterrupt  # synthetic Ctrl-C during the third request
        return good._handler(request)

    code, out, err = invoke(
        capsys, ["generate", "--config", config, "--run-id", "r1"], FakeTransport(handler)
    )
    assert code == 130 and out == ""
    assert err.startswith("error: interrupted") and "--resume" in err
    assert len(err.splitlines()) == 1
    run = tmp_path / "runs/r1"
    assert json.loads((run / "manifest.json").read_text())["status"] == "interrupted"
    starts = (run / "starts.jsonl").read_text().splitlines()
    assert len(starts) == 3 and (run / "attempts.jsonl").read_text().count("\n") == 2
    code, out, _ = invoke(capsys, ["generate", "--config", config, "--run-id", "r1", "--resume"])
    assert code == 0 and json.loads(out)["status"] == "complete"
    # The interrupted request stays disclosed as an unknown outcome.
    assert json.loads(out)["metrics"]["unknown_outcomes"] == 1


def test_cli_malformed_batch_slot_is_one_error_line(tmp_path, run_config, capsys):
    root = str(tmp_path / "runs")
    args = ["--collection-id", "c1", "--batch-count", "5", "--max-batches", "1"]
    code, _, _ = invoke(capsys, ["collect", "--config", str(run_config), *args])
    assert code == 3
    path = tmp_path / "runs/c1-b01/manifest.json"
    run = json.loads(path.read_text())
    run["slots"][0]["extra"] = "synthetic"  # a plain edit: the run manifest is not sealed
    path.write_text(json.dumps(run))
    status = ["collection-status", "--collection-id", "c1", "--artifact-root", root]
    code, out, err = invoke(capsys, status)
    assert code == 1 and out == ""
    assert err.startswith("error: c1-b01: batch slot plan is malformed")
    assert len(err.splitlines()) == 1


def test_cli_interrupt_with_a_failed_checkpoint_shows_the_note(
    tmp_path, run_config, capsys, monkeypatch
):
    real_checkpoint = generate.write_checkpoint

    def failing_checkpoint(path, record):
        if record.get("status") == "interrupted":
            # Synthetic failure whose text carries the key and a line break.
            raise OSError(f"synthetic disk full\nkey {FAKE_KEY}")
        real_checkpoint(path, record)

    monkeypatch.setattr(generate, "write_checkpoint", failing_checkpoint)
    good = model_transport()
    chats = itertools.count(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if next(chats) == 2:
            raise KeyboardInterrupt  # synthetic Ctrl-C during the second request
        return good._handler(request)

    code, out, err = invoke(
        capsys,
        ["generate", "--config", str(run_config), "--run-id", "r1"],
        FakeTransport(handler),
    )
    assert code == 130 and out == ""
    assert err.startswith("error: interrupted") and len(err.splitlines()) == 1
    assert "interrupted checkpoint also failed" in err and "synthetic disk full" in err
    assert "[REDACTED]" in err and "inspection" in err
    assert "--resume" not in err  # resume may refuse a run whose checkpoint failed
    manifest = json.loads((tmp_path / "runs/r1/manifest.json").read_text())
    assert manifest["status"] == "running"


def test_cli_error_line_carries_the_exception_notes(run_config, capsys, monkeypatch):
    def failing_run(*args, **kwargs):
        error = ValueError("synthetic refusal")
        error.add_note(f"synthetic note\nwith key {FAKE_KEY}")
        raise error

    monkeypatch.setattr(generate, "generate_run", failing_run)
    code, out, err = invoke(capsys, ["generate", "--config", str(run_config), "--run-id", "r1"])
    assert code == 2 and out == ""
    assert err == "error: synthetic refusal; synthetic note with key [REDACTED]\n"
