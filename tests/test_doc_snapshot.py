"""Behaviour of the snapshot builder, checker and fixture export against synthetic remotes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from doc_remotes import FILES, make_remote, source_config, write_config

from bonsai_help import cli
from bonsai_help.doc_snapshot import (
    _with_digest,
    _write_new,
    build_manifest,
    dump_json,
    source_digest,
)
from bonsai_help.doc_sources import CATEGORIES, Source, glob_match, tag_for
from bonsai_help.git_fetch import Result, git_blob_id, subprocess_runner

ROOT = Path(__file__).resolve().parents[1]


class Workspace:
    def __init__(self, tmp_path: Path, capsys):
        self.tmp = tmp_path
        self.capsys = capsys
        self.config = tmp_path / "doc-sources.json"
        self.manifest = tmp_path / "doc-manifest.json"
        self.data = tmp_path / "data"
        self.fixtures = tmp_path / "fixtures"
        self.notice = tmp_path / "NOTICE.md"

    def run(self, *args: str, data: Path | None = None, manifest: Path | None = None, runner=None):
        argv = [
            "snapshot",
            *args,
            "--config",
            str(self.config),
            "--manifest",
            str(manifest or self.manifest),
        ]
        if args[0] != "check" or "--committed" not in args:
            argv += ["--data-root", str(data or self.data)]
        if args[0] in ("check", "fixtures"):
            argv += ["--fixtures", str(self.fixtures)]
        if args[0] == "check":
            argv += ["--notice", str(self.notice)]
        code = cli.main(argv, allow_file_urls=True, runner=runner)
        out, err = self.capsys.readouterr()
        assert "Traceback" not in err
        assert str((data or self.data).resolve()) not in out + err
        return code, out, err

    def snapshot(self, data: Path | None = None) -> Path:
        (snapshot,) = ((data or self.data) / "snapshots" / "fake-docs").glob("fake-docs-*")
        return snapshot

    def committed(self) -> None:
        """Pin, export fixtures and write a notice, as the real repository does."""
        assert self.run("build", "--write-manifest")[0] == 0
        assert self.run("fixtures")[0] == 0
        self.notice.write_text(f"# Notice\n\n{source_config()['attribution']}\n")


@pytest.fixture
def ws(tmp_path, capsys):
    return Workspace(tmp_path, capsys)


def edit_manifest(path: Path, change) -> None:
    manifest = json.loads(path.read_bytes())
    entry = manifest["sources"]["fake-docs"]
    change(entry)
    entry["totals"] = {
        "pages": len(entry["pages"]),
        "bytes": sum(p["bytes"] for p in entry["pages"]),
    }
    entry["source_digest"] = source_digest(entry)
    path.write_bytes(dump_json(build_manifest(manifest["sources"])))


def test_round_trip_is_reproducible_and_stores_raw_upstream_bytes(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    first = ws.manifest.read_bytes()
    second_root = ws.tmp / "second"
    code, out, _ = ws.run("build", data=second_root)
    assert code == 0 and "built" in out
    assert (ws.snapshot() / "manifest.json").read_bytes() == (
        ws.snapshot(second_root) / "manifest.json"
    ).read_bytes()
    assert (
        ws.run("build", "--write-manifest", data=ws.tmp / "third", manifest=ws.tmp / "new.json")[0]
        == 0
    )
    assert (ws.tmp / "new.json").read_bytes() == first
    assert b"built_at" not in first and b"tags" not in first
    files = ws.snapshot() / "files"
    stored = sorted(p.relative_to(files).as_posix() for p in files.rglob("*") if p.is_file())
    expected = [
        "COPYING",
        "docs/_fragment.rst",
        "docs/conf.py",
        "docs/guide/page.rst",
        "docs/index.rst",
        "docs/license.rst",
    ]
    assert stored == expected
    assert all((files / path).read_bytes() == FILES[path] for path in expected)
    entry = json.loads(first)["sources"]["fake-docs"]
    assert "docs/license.rst" in [p["path"] for p in entry["pages"]]
    assert "docs/license.rst" in [p["path"] for p in entry["license_evidence"]]
    assert entry["not_selected"] == {"png": 1, "py": 1, "svg": 1, "webp": 1}


def test_images_are_never_downloaded(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    cache = ws.data / "git" / "fake"
    for path in (
        "docs/img/picture.png",
        "docs/img/photo.webp",
        "docs/img/icon.svg",
        "other/outside.rst",
    ):
        assert not remote.has_object(cache, git_blob_id(FILES[path]))
    assert remote.has_object(cache, git_blob_id(FILES["docs/index.rst"]))


def test_lightweight_tag_must_match_when_pinning(ws):
    remote = make_remote(ws.tmp, tag="v1")
    advanced = remote.advance({"docs/index.rst": b"Changed\n"})
    write_config(
        ws.config, remote, ref={"kind": "tag", "name": "v1", "tag_object": None}, commit=advanced
    )
    code, _, err = ws.run("build", "--write-manifest")
    assert code == 4 and "tag v1" in err
    assert not (ws.data / "snapshots").exists()


def test_moved_tag_warns_on_rebuild_of_an_established_pin(ws):
    remote = make_remote(ws.tmp, tag="v1")
    write_config(ws.config, remote, ref={"kind": "tag", "name": "v1", "tag_object": None})
    assert ws.run("build", "--write-manifest")[0] == 0
    remote.advance({"docs/index.rst": b"Changed\n"})
    remote.move_tag("v1")
    code, _, err = ws.run("build", data=ws.tmp / "fresh")
    assert code == 0 and "warning: fake: tag v1" in err
    receipt = json.loads((ws.snapshot(ws.tmp / "fresh") / "receipt.json").read_bytes())
    assert receipt["ref_observed"]["matches_pin"] is False


@pytest.mark.parametrize(
    ("annotated", "declared", "code"),
    [(True, "actual", 0), (True, "0" * 40, 4), (True, None, 4), (False, "0" * 40, 4)],
)
def test_annotated_and_lightweight_tags_are_told_apart(ws, annotated, declared, code):
    remote = make_remote(ws.tmp, tag="v1", annotated=annotated)
    tag_object = remote.tag_object if declared == "actual" else declared
    write_config(ws.config, remote, ref={"kind": "tag", "name": "v1", "tag_object": tag_object})
    assert ws.run("build", "--write-manifest")[0] == code


def test_ref_lookup_is_exact_not_a_tail_match(ws):
    remote = make_remote(ws.tmp, branch="x/refs/tags/v1")
    write_config(ws.config, remote, ref={"kind": "tag", "name": "v1", "tag_object": None})
    code, _, err = ws.run("build", "--write-manifest")
    assert code == 4 and "not found" in err


def test_moved_branch_builds_the_pinned_commit(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    pinned = ws.manifest.read_bytes()
    remote.advance({"docs/index.rst": b"Changed upstream\n", "docs/new.rst": b"New\n"})
    code, _, err = ws.run("build", data=ws.tmp / "fresh")
    assert code == 0 and "has moved" in err
    assert ws.manifest.read_bytes() == pinned
    assert (ws.snapshot(ws.tmp / "fresh") / "files/docs/index.rst").read_bytes() == FILES[
        "docs/index.rst"
    ]


def test_network_failure_is_exit_3_and_writes_no_snapshot(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    shutil.rmtree(remote.bare)
    code, _, err = ws.run("build", "--write-manifest")
    assert code == 3 and "git" in err
    assert not (ws.data / "snapshots").exists()


def test_second_repository_failure_writes_nothing_for_the_first(ws):
    remote = make_remote(ws.tmp)
    other = make_remote(ws.tmp, name="other")
    repositories = {
        "fake": {
            "url": remote.url,
            "ref": {"kind": "branch", "name": "main"},
            "commit": remote.commit,
        },
        "other": {
            "url": other.url,
            "ref": {"kind": "branch", "name": "main"},
            "commit": other.commit,
        },
    }
    sources = [source_config(), source_config(id="other-docs", repository="other")]
    write_config(ws.config, remote, repositories=repositories, sources=sources)
    shutil.rmtree(other.bare)
    assert ws.run("build", "--write-manifest")[0] == 3
    assert not (ws.data / "snapshots").exists()
    assert not ws.manifest.exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"root": "gone", "include": ["gone/**/*.rst"], "fixture_pages": []},
        {"fixture_pages": [{"path": "docs/missing.rst", "categories": []}]},
        {"license_evidence": [{"path": "COPYING", "blob": "1" * 40, "commit_copy": True}]},
        {"license_evidence": [{"path": "NOPE", "blob": "1" * 40, "commit_copy": True}]},
    ],
    ids=["root", "fixture", "license-blob", "license-path"],
)
def test_missing_or_changed_pinned_paths_are_exit_4(ws, overrides):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote, sources=[source_config(**overrides)])
    assert ws.run("build", "--write-manifest")[0] == 4
    assert not (ws.data / "snapshots").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda e: e["pages"].pop(2),
        lambda e: e["pages"].append({**e["pages"][-1], "path": "docs/zz_ghost.rst"}),
        lambda e: e["pages"][1].update(blob="2" * 40),
    ],
    ids=["upstream-extra", "manifest-extra", "blob"],
)
def test_upstream_disagreeing_with_manifest_fails_before_blob_download(ws, change):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    edit_manifest(ws.manifest, change)
    fresh = ws.tmp / "fresh"
    code, _, err = ws.run("build", data=fresh)
    assert code == 4 and "fake-docs" in err
    assert not remote.has_object(fresh / "git" / "fake", git_blob_id(FILES["docs/guide/page.rst"]))
    assert not (fresh / "snapshots").exists()


def test_manifest_for_another_pin_is_a_usage_error(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    write_config(ws.config, remote, sources=[source_config(exclude=["docs/index.rst"])])
    code, _, err = ws.run("build", data=ws.tmp / "fresh")
    assert code == 2 and "--write-manifest" in err


def test_include_overlapping_deny_is_a_config_error_before_download(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote, sources=[source_config(include=["docs/**"])])
    assert ws.run("build", "--write-manifest")[0] == 2
    assert not remote.has_object(ws.data / "git" / "fake", git_blob_id(FILES["docs/index.rst"]))


def test_lfs_pointer_selected_is_exit_4(ws):
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 9\n"
    remote = make_remote(ws.tmp, {**FILES, "docs/stored.rst": pointer})
    write_config(ws.config, remote)
    code, _, err = ws.run("build", "--write-manifest")
    assert code == 4 and "LFS" in err


def hooked(after):
    """A real git runner whose result for selected calls is replaced by after(argv, result)."""

    def runner(argv, cwd, env, stdin, timeout):
        return after(argv, subprocess_runner(argv, cwd, env, stdin, timeout))

    return runner


def test_blob_bytes_that_do_not_hash_to_their_id_are_exit_4(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)

    def corrupt(argv, result):
        if argv[-2:] != ["cat-file", "--batch"]:
            return result
        out = bytearray(result.stdout)
        out[out.index(b"\n") + 1] ^= 1
        return Result(result.returncode, bytes(out), result.stderr)

    code, _, err = ws.run("build", "--write-manifest", runner=hooked(corrupt))
    assert code == 4 and "do not hash" in err
    assert not (ws.data / "snapshots").exists() and not ws.manifest.exists()


def test_fetch_that_gives_another_commit_is_exit_4(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)

    def other_commit(argv, result):
        if argv[-3:] == ["rev-parse", "--verify", "FETCH_HEAD^{commit}"]:
            return Result(0, b"1" * 40 + b"\n", b"")
        return result

    code, _, err = ws.run("build", "--write-manifest", runner=hooked(other_commit))
    assert code == 4 and "gave" in err
    assert not (ws.data / "snapshots").exists()


def test_hand_edit_outside_the_source_digest_fails_the_rebuild(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    edit_manifest(ws.manifest, lambda e: e["not_selected"].update(png=99))
    fresh = ws.tmp / "fresh"
    code, _, err = ws.run("build", data=fresh)
    assert code == 4 and "differs from the committed manifest" in err
    assert not (fresh / "snapshots").exists()


def test_hand_edit_outside_the_source_digest_fails_check_of_built_snapshots(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    edit_manifest(ws.manifest, lambda e: e["not_selected"].update(png=99))
    assert ws.run("check", "--committed")[0] == 0
    code, _, err = ws.run("check")
    assert code == 1 and "differs from the committed entry" in err
    code, _, err = ws.run("build")
    assert code == 5 and "refusing to overwrite" in err


def test_blobs_the_server_did_not_send_are_exit_3(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)

    def drop_blob_fetch(argv, cwd, env, stdin, timeout):
        if "fetch" in argv and "--stdin" in argv:
            return Result(0, b"", b"")
        return subprocess_runner(argv, cwd, env, stdin, timeout)

    code, _, err = ws.run("build", "--write-manifest", runner=drop_blob_fetch)
    assert code == 3 and "did not send" in err
    assert not (ws.data / "snapshots").exists() and not ws.manifest.exists()


def test_snapshot_that_appears_during_the_build_is_not_replaced(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    pin = json.loads(ws.manifest.read_bytes())["sources"]["fake-docs"]["pin_id"]
    fresh = ws.tmp / "fresh"
    rival = fresh / "snapshots" / "fake-docs" / pin

    def concurrent_build(argv, result):
        if argv[-2:] == ["cat-file", "--batch"]:
            rival.mkdir(parents=True)
        return result

    code, _, err = ws.run("build", data=fresh, runner=hooked(concurrent_build))
    assert code == 5 and "appeared during the build" in err
    assert rival.is_dir() and not any(rival.iterdir())
    (staging,) = rival.parent.glob(".staging-*")
    assert (staging / "receipt.json").is_file()


def test_snapshot_files_are_created_exclusively(tmp_path):
    target = tmp_path / "page.rst"
    target.write_bytes(b"first\n")
    with pytest.raises(FileExistsError):
        _write_new(target, b"second\n")
    assert target.read_bytes() == b"first\n"


def tamper_flip(files: Path) -> str:
    target = files / "docs/index.rst"
    data = bytearray(target.read_bytes())
    data[0] ^= 1
    target.write_bytes(bytes(data))
    return "docs/index.rst"


def tamper_delete(files: Path) -> str:
    (files / "docs/guide/page.rst").unlink()
    return "docs/guide/page.rst"


def tamper_add(files: Path) -> str:
    (files / "docs/extra.rst").write_bytes(b"extra\n")
    return "docs/extra.rst"


def tamper_symlink(files: Path) -> str:
    target = files / "docs/index.rst"
    target.unlink()
    target.symlink_to(files / "docs/license.rst")
    return "docs/index.rst"


@pytest.mark.parametrize("tamper", [tamper_flip, tamper_delete, tamper_add, tamper_symlink])
def test_tampered_snapshot_fails_check_and_is_never_overwritten(ws, tamper):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    assert ws.run("check")[0] == 0
    path = tamper(ws.snapshot() / "files")
    code, _, err = ws.run("check")
    assert code == 1 and path in err
    before = sorted((p, p.lstat().st_mtime_ns) for p in ws.snapshot().rglob("*"))
    code, _, err = ws.run("build")
    assert code == 5 and "refusing to overwrite" in err
    assert sorted((p, p.lstat().st_mtime_ns) for p in ws.snapshot().rglob("*")) == before


def test_snapshot_without_receipt_is_an_incomplete_build(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    (ws.snapshot() / "receipt.json").unlink()
    code, _, err = ws.run("check")
    assert code == 1 and "incomplete build" in err


def test_present_snapshot_is_verified_offline_and_left_alone(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    before = sorted((p, p.stat().st_mtime_ns) for p in ws.data.rglob("*"))
    shutil.rmtree(remote.bare)
    code, out, _ = ws.run("build")
    assert code == 0 and "present, verified, not rebuilt" in out
    assert sorted((p, p.stat().st_mtime_ns) for p in ws.data.rglob("*")) == before


def test_leftover_staging_directory_does_not_block_a_build_and_is_reported(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    leftover = ws.data / "snapshots" / "fake-docs" / ".staging-fake-docs-0000000000000000-dead"
    leftover.mkdir(parents=True)
    ws.committed()
    assert leftover.is_dir()
    code, _, err = ws.run("check")
    assert code == 0 and ".staging-fake-docs" in err


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda m: m["sources"]["fake-docs"]["pages"][0].update(sha256="0" * 64),
            "manifest_digest",
        ),
        ("recomputed", "source_digest"),
        ("layout", "canonical layout"),
    ],
)
def test_committed_manifest_tampering_fails_check(ws, mutate, message):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    assert ws.run("check", "--committed")[0] == 0
    manifest = json.loads(ws.manifest.read_bytes())
    if mutate == "recomputed":
        manifest["sources"]["fake-docs"]["pages"][0]["sha256"] = "0" * 64
        ws.manifest.write_bytes(dump_json(build_manifest(manifest["sources"])))
    elif mutate == "layout":
        ws.manifest.write_text(json.dumps(manifest, indent=4))
    else:
        mutate(manifest)
        ws.manifest.write_bytes(dump_json(manifest))
    code, _, err = ws.run("check", "--committed")
    assert code == 1 and message in err


def test_selection_change_changes_pin_but_tags_and_attribution_do_not(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    write_config(ws.config, remote, sources=[source_config(tags=[], default_tag="other", deny=[])])
    assert ws.run("check", "--committed")[0] == 0
    write_config(
        ws.config, remote, sources=[source_config(include=["docs/guide/*.rst", "docs/*.rst"])]
    )
    code, _, err = ws.run("check", "--committed")
    assert code == 1 and "pin_id" in err


def test_same_pin_with_different_bytes_refuses_to_write_manifest(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    assert ws.run("build", "--write-manifest")[0] == 0
    edit_manifest(ws.manifest, lambda e: e["pages"][0].update(sha256="0" * 64))
    tampered = ws.manifest.read_bytes()
    code, _, err = ws.run("build", "--write-manifest", data=ws.tmp / "fresh")
    assert code == 5 and "different bytes" in err
    assert ws.manifest.read_bytes() == tampered
    assert not (ws.tmp / "fresh" / "snapshots").exists()


def test_fixture_export_never_silently_replaces(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    code, out, _ = ws.run("fixtures")
    assert code == 0 and "0 written" in out
    page = ws.fixtures / "fake-docs/docs/guide/page.rst"
    page.write_bytes(b"edited\n")
    extra = ws.fixtures / "fake-docs/docs/extra.rst"
    extra.write_bytes(b"extra\n")
    assert ws.run("check", "--committed")[0] == 1
    code, _, err = ws.run("fixtures")
    assert code == 5 and "--replace" in err and page.read_bytes() == b"edited\n"
    assert ws.run("fixtures", "--replace")[0] == 0
    assert page.read_bytes() == FILES["docs/guide/page.rst"] and not extra.exists()
    assert ws.run("check", "--committed")[0] == 0


def test_fixture_list_edited_with_a_recomputed_digest_fails_check(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    path = ws.fixtures / "fixtures.json"
    document = json.loads(path.read_bytes())
    first = document["sources"]["fake-docs"]["files"][0]
    first["categories"] = sorted(set(first["categories"]) ^ {CATEGORIES[0]})
    path.write_bytes(dump_json(_with_digest(document, "digest")))
    code, _, err = ws.run("check", "--committed")
    assert code == 1 and "differs from the config's fixture list and the manifest" in err
    assert "digest does not match" not in err


@pytest.mark.parametrize("notice", ["missing", "changed"])
def test_notice_without_the_source_attribution_fails_check(ws, notice):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    assert ws.run("check", "--committed")[0] == 0
    if notice == "missing":
        ws.notice.unlink()
        message = "NOTICE.md: missing"
    else:
        attribution = source_config()["attribution"]
        ws.notice.write_text(f"# Notice\n\n{attribution.replace(' ', ' and others ', 1)}\n")
        message = "does not carry the source's attribution"
    code, _, err = ws.run("check", "--committed")
    assert code == 1 and message in err


def test_fixture_privacy_matches_need_a_reviewed_allowance(ws):
    remote = make_remote(
        ws.tmp, {**FILES, "docs/guide/page.rst": b"Config lives in /home/someone/.config\n"}
    )
    write_config(ws.config, remote)
    ws.committed()
    code, _, err = ws.run("check", "--committed")
    assert code == 1 and "home-path" in err


@pytest.mark.parametrize(
    "repository",
    [
        {"commit": "abc123"},
        {"url": "http://github.com/x/y.git"},
        {"url": "https://example.com/x/y.git"},
        {"url": "https://user@github.com/x/y.git"},
        {"ref": {"kind": "branch", "name": "main", "tag_object": "0" * 40}},
    ],
)
def test_invalid_repository_config_is_exit_2_with_no_git_call(ws, repository):
    remote = make_remote(ws.tmp)
    base = {"url": remote.url, "ref": {"kind": "branch", "name": "main"}, "commit": remote.commit}
    write_config(ws.config, remote, repositories={"fake": {**base, **repository}})
    calls = []
    assert ws.run("build", "--write-manifest", runner=lambda *a: calls.append(a))[0] == 2
    assert calls == []


@pytest.mark.parametrize(
    "sources",
    [
        [source_config(), source_config()],
        [source_config(include=["other/**/*.rst"])],
        [source_config(include=["docs/../other/*.rst"])],
        [source_config(repository="unknown")],
    ],
    ids=["duplicate-id", "outside-root", "dotdot", "unknown-repository"],
)
def test_invalid_source_config_is_exit_2_with_no_git_call(ws, sources):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote, sources=sources)
    calls = []
    assert ws.run("build", "--write-manifest", runner=lambda *a: calls.append(a))[0] == 2
    assert calls == []


def test_role_and_autosectionlabel_are_metadata_outside_the_pin(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    ws.committed()
    labelled = source_config(autosectionlabel={"prefix_document": True, "maxdepth": 2})
    write_config(ws.config, remote, sources=[labelled])
    assert ws.run("check", "--committed")[0] == 0
    no_fixtures = source_config(role="operator-source", fixture_pages=[])
    write_config(ws.config, remote, sources=[no_fixtures])
    code, _, err = ws.run("check", "--committed")
    assert code == 1 and "fixtures.json" in err and "pin_id" not in err  # slice, not pin


@pytest.mark.parametrize(
    "overrides",
    [{"role": "operator-source"}, {"role": "lexicon"}, {"autosectionlabel": {"maxdepth": 2}}],
    ids=["operator-source-with-fixtures", "unknown-role", "incomplete-autosectionlabel"],
)
def test_invalid_role_settings_are_exit_2(ws, overrides):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote, sources=[source_config(**overrides)])
    assert ws.run("build", "--write-manifest")[0] == 2


def test_https_url_cannot_be_used_by_tests_or_file_url_by_the_cli(ws, capsys):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)
    argv = [
        "snapshot",
        "build",
        "--config",
        str(ws.config),
        "--manifest",
        str(ws.manifest),
        "--data-root",
        str(ws.data),
    ]
    assert cli.main(argv) == 2
    assert "https" in capsys.readouterr().err


def test_git_without_no_lazy_fetch_is_exit_3(ws):
    remote = make_remote(ws.tmp)
    write_config(ws.config, remote)

    def old_git(argv, cwd, env, stdin, timeout):
        if argv[1:] == ["--no-lazy-fetch", "version"]:
            return Result(129, b"", b"unknown option: --no-lazy-fetch")
        return subprocess_runner(argv, cwd, env, stdin, timeout)

    code, _, err = ws.run("build", "--write-manifest", runner=old_git)
    assert code == 3 and "2.44" in err


def test_data_root_inside_the_repository_is_refused(ws, monkeypatch):
    monkeypatch.chdir(ROOT)
    target = ROOT / "src" / "not-a-data-root"
    code, _, err = ws.run("build", data=target)
    assert code == 2 and "--data-root" in err
    assert not target.exists()


def test_cli_help_and_unknown_subcommand(capsys):
    with pytest.raises(SystemExit) as done:
        cli.main(["snapshot", "--help"])
    assert done.value.code == 0
    help_text = capsys.readouterr().out
    assert all(name in help_text for name in ("build", "check", "fixtures"))
    with pytest.raises(SystemExit) as done:
        cli.main(["snapshot", "publish"])
    assert done.value.code == 2


def test_glob_semantics():
    assert glob_match("a/**/*.rst", "a/x.rst")
    assert glob_match("a/**/*.rst", "a/b/c/x.rst")
    assert not glob_match("a/*.rst", "a/b/x.rst")
    assert not glob_match("a/**/*.rst", "b/x.rst")
    assert glob_match("a/**", "a/b/c")
    source = source_config(
        tags=[{"glob": "docs/guide/**", "tag": "first"}, {"glob": "docs/**", "tag": "second"}]
    )
    parsed = Source.model_validate(source)
    assert tag_for(parsed, "docs/guide/page.rst") == "first"
    assert tag_for(parsed, "docs/index.rst") == "second"
    assert tag_for(parsed, "elsewhere.rst") == "user"
