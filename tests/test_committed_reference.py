"""The committed docs-index digest and lexicons (real repository files, offline)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bonsai_help import cli, lexicons
from bonsai_help.doc_snapshot import dump_json
from bonsai_help.doc_sources import canonical, load_config, sha256_hex
from bonsai_help.docs_index import check_digest_committed

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "config/doc-sources.json")
MANIFEST = json.loads((ROOT / "config/doc-manifest.json").read_bytes())
LEXICONS = ROOT / "reference/lexicons"
FIXTURES = ROOT / "tests/fixtures/docs"


def lexicon(name: str) -> dict:
    return json.loads((LEXICONS / f"{name}.json").read_bytes())


@pytest.mark.parametrize(
    "argv",
    [
        ["docs", "index", "check", "--committed"],
        ["lexicon", "check", "--committed"],
        ["setup", "check", "--committed"],
    ],
)
def test_committed_checks_pass_through_the_cli_without_a_data_root(argv, capsys, monkeypatch):
    monkeypatch.chdir(ROOT / "tests")
    assert cli.main(argv) == 0
    assert "check passed" in capsys.readouterr().out


def test_operator_lexicons_record_the_measured_counts():
    current, older = lexicon("bonsai-source"), lexicon("bonsai-source-0-8-5-post1")
    assert current["summary"]["bim_operator_ids"] == 1317
    assert current["summary"]["bim_operator_ids_derived"] == 12
    assert older["summary"]["bim_operator_ids"] == 1246
    assert older["summary"]["bim_operator_ids_derived"] == 0
    for document in (current, older):
        assert document["summary"]["duplicate_ids"] == [
            "operator bim.copy_debug_information",
            "operator bim.open_uri",
        ]
        assert document["summary"]["unresolved_references"] == []
        (only,) = [u for u in document["unresolved"] if u["attr"] != "text"]
        assert (only["class"], only["attr"], only["file"]) == (
            "BIM_ADDON_preferences",
            "bl_idname",
            "bim/ui.py",
        )

    def ids(document):
        return {e["id"] for e in document["entries"] if e["kind"] in ("operator", "macro")}

    assert len(ids(current) - ids(older)) == 77 and len(ids(older) - ids(current)) == 6
    assert "bim.enable_editing_roof" in ids(current) and "bim.enable_editing_wall" in ids(current)


def test_manual_lexicon_resolves_every_operator_ref_and_fits_the_size_gate():
    manual = lexicon("blender-manual")
    assert manual["summary"]["operator_ids"] == 1443
    assert manual["summary"]["dangling_refs"] == []
    assert (LEXICONS / "blender-manual.json").stat().st_size <= 1_000_000
    bonsai = lexicon("bonsai-docs")
    assert bonsai["summary"]["counts"]["kbd_merged_runs"] > 0
    assert any(e["kind"] == "ui_path" for e in bonsai["entries"])


def relabel_fixture_entry(document: dict) -> None:
    """Give a menu path found on a fixture page a label the page does not have."""
    fixture = {f"bonsai-docs:{path}" for path in fixture_paths("bonsai-docs")}
    for entry in document["entries"]:
        where = {document["records"][i].split("#")[0] for i in entry["locations"]}
        if entry["kind"] == "menu_path" and where & fixture:
            entry["label"] = "invented"
            return
    raise AssertionError("no menu path on a fixture page")


def fixture_paths(source_id: str) -> list[str]:
    return [page.path for page in CONFIG.source(source_id).fixture_pages]


def redigest(document: dict) -> bytes:
    body = {key: value for key, value in document.items() if key != "digest"}
    return dump_json({**body, "digest": sha256_hex(canonical(body))})


@pytest.mark.parametrize(
    "name, change, message",
    [
        ("bonsai-docs", lambda d: relabel_fixture_entry(d), "differ from a re-extraction"),
        (
            "bonsai-source",
            lambda d: d["entries"][0].update(label="Ask maintainer@example.invalid"),
            "email match",
        ),
        ("blender-manual", lambda d: d.update(pin_id="blender-manual-0"), "pin_id differs"),
        ("bonsai-source", lambda d: d["entries"].reverse(), "not sorted and unique"),
        ("bonsai-docs", lambda d: d["records"].append("elsewhere:x#L1-L2"), "records are not"),
    ],
    ids=["fixture-entries", "privacy", "stale-pin", "order", "records"],
)
def test_changed_lexicons_fail_the_committed_check(tmp_path, name, change, message):
    copy = tmp_path / "lexicons"
    shutil.copytree(LEXICONS, copy)
    document = json.loads((copy / f"{name}.json").read_bytes())
    change(document)
    (copy / f"{name}.json").write_bytes(redigest(document))
    found = [str(p) for p in lexicons.check_committed(CONFIG, MANIFEST, copy, FIXTURES)]
    assert any(message in p for p in found), found


def test_missing_and_unexpected_lexicon_files_are_reported(tmp_path):
    copy = tmp_path / "lexicons"
    shutil.copytree(LEXICONS, copy)
    (copy / "bonsai-docs.json").unlink()
    (copy / "extra.json").write_text("{}")
    found = [str(p) for p in lexicons.check_committed(CONFIG, MANIFEST, copy, FIXTURES)]
    assert any("bonsai-docs.json: missing" in p for p in found)
    assert any("extra.json: unexpected file" in p for p in found)


def test_docs_index_digest_agrees_with_the_manifest(tmp_path):
    path = ROOT / "reference/docs-index.json"
    _, found = check_digest_committed(CONFIG, MANIFEST, path)
    assert found == []
    document = json.loads(path.read_bytes())
    assert set(document["sources"]) == {"bonsai-docs", "bonsai-docs-0-8-5-post1", "blender-manual"}
    assert document["sources"]["blender-manual"]["records"] == 9367
    document["sources"]["bonsai-docs"]["pin_id"] = "bonsai-docs-0"
    stale = tmp_path / "docs-index.json"
    stale.write_bytes(redigest(document))
    _, found = check_digest_committed(CONFIG, MANIFEST, stale)
    assert [str(p) for p in found] == ["bonsai-docs: docs-index.json: pin_id is stale"]
