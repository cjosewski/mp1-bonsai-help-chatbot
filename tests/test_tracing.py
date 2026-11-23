"""Behaviour tests for run evidence and file helpers."""

import json
import os
from pathlib import Path

import pytest

from bonsai_help import tracing


@pytest.mark.parametrize("bad", ["../x", "/abs/path", "", "a/b", "..", ".hidden"])
def test_run_directory_refuses_escape(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        tracing.run_directory(tmp_path, bad)


def test_run_directory_accepts_plain_id(tmp_path: Path) -> None:
    assert tracing.run_directory(tmp_path, "run-1_a") == tmp_path.resolve() / "run-1_a"


def test_run_directory_refuses_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        tracing.run_directory(root, "link")


def test_append_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    assert tracing.read_records(path) == []
    tracing.append_record(path, {"n": 1, "t": "é"})
    tracing.append_record(path, {"n": 2})
    assert tracing.read_records(path) == [{"n": 1, "t": "é"}, {"n": 2}]


def test_truncated_jsonl_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    tracing.append_record(path, {"n": 1})
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"n": 2, "x"')
    with pytest.raises(ValueError, match="a.jsonl:2"):
        tracing.read_records(path)


def test_non_object_record_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    path.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        tracing.read_records(path)


def test_checkpoint_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    tracing.write_checkpoint(path, {"v": 1})
    tracing.write_checkpoint(path, {"v": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["checkpoint.json"]


def test_checkpoint_failure_keeps_old_content_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "checkpoint.json"
    tracing.write_checkpoint(path, {"v": 1})

    def boom(*_args: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        tracing.write_checkpoint(path, {"v": 2})
    monkeypatch.undo()
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["checkpoint.json"]


def test_unserializable_checkpoint_leaves_old_content(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    tracing.write_checkpoint(path, {"v": 1})
    with pytest.raises(ValueError):
        tracing.write_checkpoint(path, {"v": float("nan")})
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["checkpoint.json"]


def test_digest_is_key_order_independent() -> None:
    assert tracing.digest({"a": 1, "b": 2}) == tracing.digest({"b": 2, "a": 1})
    assert tracing.digest("x") != tracing.digest("y")


def test_artifact_hashes_cover_only_jsonl(tmp_path: Path) -> None:
    (tmp_path / "b.jsonl").write_text("1\n", encoding="utf-8")
    (tmp_path / "a.jsonl").write_text("2\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    hashes = tracing.artifact_hashes(tmp_path)
    assert list(hashes) == ["a.jsonl", "b.jsonl"]
    assert hashes["a.jsonl"] != hashes["b.jsonl"]


def test_exclusive_refuses_existing(tmp_path: Path) -> None:
    lock = tmp_path / ".writer.lock"
    lock.write_text("held", encoding="utf-8")
    with pytest.raises(FileExistsError):
        with tracing.exclusive(lock):
            pytest.fail("must not enter")
    assert lock.read_text(encoding="utf-8") == "held"


def test_exclusive_creates_and_releases(tmp_path: Path) -> None:
    lock = tmp_path / ".writer.lock"
    with tracing.exclusive(lock):
        assert lock.exists()
        with pytest.raises(FileExistsError):
            with tracing.exclusive(lock):
                pass
    assert not lock.exists()


def test_read_json_requires_object(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert tracing.read_json(path) == {"a": 1}
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError):
        tracing.read_json(path)
