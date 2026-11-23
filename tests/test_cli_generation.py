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

from bonsai_help import cli

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


def test_cli_never_prints_credentials(tmp_path, run_config, monkeypatch, capsys, caplog):
    config = str(run_config)

    def leaky(request: httpx.Request) -> httpx.Response:
        # A hostile endpoint echoes the credential in every failure it returns.
        return httpx.Response(401, json={"error": {"message": f"bad key {FAKE_KEY}"}})

    paths = [
        (["generate", "--config", config, "--run-id", "x1"], FakeTransport(leaky)),
        (["generate", "--config", config, "--run-id", "x2"], model_transport(broken=True)),
        (["gate", "--config", config, "--run-id", "x2"], FakeTransport(leaky)),
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
    # exhaustion 3, exhaustion 3, distribution failed 1, no run 1, collection out of
    # batches 3, fixture slice does not verify 1, escaping run ID 2.
    assert [code for code, _, _ in results] == [3, 3, 1, 1, 3, 1, 2]
    for code, _, err in results:
        # Failures are one stderr line: no library log output beside the error.
        assert len(err.splitlines()) <= 1
        assert err == "" or err.startswith("error:")
    # The instructor library logs each failed call; the CLI keeps it quiet (the attempt
    # ledger is the record), so a terminal shows only the error line.
    assert not [r for r in caplog.records if r.name.startswith("instructor")]
    # The key file path: a missing key and an unreadable key file are config errors.
    monkeypatch.delenv(KEY_ENV)
    code, _, err = invoke(capsys, ["generate", "--config", config, "--run-id", "x4"])
    assert code == 2 and "API key" in err
    attempts = Path(tmp_path / "runs/x1/attempts.jsonl").read_text()
    assert FAKE_KEY not in attempts
