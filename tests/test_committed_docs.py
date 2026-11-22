"""The committed pin config, manifest, fixture slice and notice (real repository files, offline)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bonsai_help import cli
from bonsai_help.doc_snapshot import PYTHON_CODE, check_committed, fixture_refusal
from bonsai_help.doc_sources import CATEGORIES, load_config

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/doc-sources.json"
MANIFEST = ROOT / "config/doc-manifest.json"
FIXTURES = ROOT / "tests/fixtures/docs"
NOTICE = ROOT / "NOTICE.md"


def problems(fixtures: Path = FIXTURES, config_path: Path = CONFIG) -> list[str]:
    config = load_config(config_path)
    return [str(p) for p in check_committed(config, config_path, MANIFEST, fixtures, NOTICE)]


def test_committed_check_passes_through_the_cli(capsys, monkeypatch):
    monkeypatch.chdir(ROOT / "tests")
    assert cli.main(["snapshot", "check", "--committed"]) == 0
    assert "check passed" in capsys.readouterr().out


def test_manifest_pins_every_source():
    config = load_config(CONFIG)
    manifest = json.loads(MANIFEST.read_bytes())
    roles = {s.id: s.role for s in config.sources}
    assert roles == {
        "bonsai-docs": "docs",
        "blender-manual": "docs",
        "bonsai-docs-0-8-5-post1": "docs",
        "blender-manual-4-5": "docs",
        "bonsai-source": "operator-source",
        "bonsai-source-0-8-5-post1": "operator-source",
    }
    refs = {sid: manifest["sources"][sid]["repository"]["ref"] for sid in roles}
    for sid in ("bonsai-docs", "bonsai-source"):
        assert refs[sid] == {"kind": "tag", "name": "bonsai-0.9.0post1", "tag_object": None}
    for sid in ("bonsai-docs-0-8-5-post1", "bonsai-source-0-8-5-post1"):
        assert refs[sid] == {"kind": "tag", "name": "bonsai-0.8.5-post1", "tag_object": None}
    # Each version line's Blender steps come from its matching Manual release branch.
    assert refs["blender-manual"] == {"kind": "branch", "name": "blender-v5.2-release"}
    assert refs["blender-manual-4-5"] == {"kind": "branch", "name": "blender-v4.5-release"}
    # The B1 Bonsai pin is unchanged by the later sources; the 5.3 Manual pin was replaced.
    assert manifest["sources"]["bonsai-docs"]["pin_id"] == "bonsai-docs-00e02b1ec8e4c266"
    assert manifest["sources"]["blender-manual"]["pin_id"] == "blender-manual-fea32ead8c72f97e"
    assert manifest["totals"]["pages"] == sum(
        e["totals"]["pages"] for e in manifest["sources"].values()
    )


@pytest.mark.parametrize("change", ["byte", "extra", "missing"])
def test_changed_fixture_tree_fails(tmp_path, change):
    copy = tmp_path / "docs"
    shutil.copytree(FIXTURES, copy)
    page = copy / "bonsai-docs/src/bonsai/docs/guides/authoring/basic_modeling/door.rst"
    if change == "byte":
        page.write_bytes(page.read_bytes().replace(b"door", b"Door", 1))
    elif change == "extra":
        (copy / "blender-manual/manual/extra.rst").write_bytes(b"extra\n")
    else:
        page.unlink()
    found = problems(copy)
    assert found and any("door.rst" in p or "extra.rst" in p for p in found)


def test_stale_privacy_allowance_fails(tmp_path):
    data = json.loads(CONFIG.read_bytes())
    data["privacy_allowlist"][0]["count"] += 1
    config_path = tmp_path / "doc-sources.json"
    config_path.write_text(json.dumps(data))
    assert any("allowance" in p for p in problems(config_path=config_path))


def test_every_category_is_covered_and_manual_fixtures_carry_no_python():
    config = load_config(CONFIG)
    for source_id in ("bonsai-docs", "blender-manual"):
        assert config.source(source_id).fixture_min_per_category >= 1
    for source in config.sources:
        for category in CATEGORIES:
            count = sum(category in page.categories for page in source.fixture_pages)
            assert count >= source.fixture_min_per_category
        if source.role == "operator-source":
            assert not (FIXTURES / source.id).exists()
    for source_id in ("blender-manual", "blender-manual-4-5"):
        assert config.source(source_id).fixture_forbid_python
        for path in (FIXTURES / source_id).rglob("*"):
            if path.is_file():
                assert not PYTHON_CODE.search(path.read_bytes()), path


def test_python_code_rule_catches_its_forms():
    for form in (b"python", b"py", b"pycon", b"python3"):
        assert PYTHON_CODE.search(b"text\n\n.. code-block:: " + form + b"\n")
    assert PYTHON_CODE.search(b".. highlight:: python\n")
    assert PYTHON_CODE.search(b".. sourcecode:: py\n")
    assert PYTHON_CODE.search(b".. literalinclude:: x.txt\n")
    assert not PYTHON_CODE.search(b".. code-block:: bash\n")


def test_byte_exact_files_are_exempt_from_line_ending_conversion():
    paths = [
        "config/doc-manifest.json",
        "tests/fixtures/docs/fixtures.json",
        "tests/fixtures/docs/blender-manual/manual/copyright.rst",
        "reference/docs-index.json",
        "reference/lexicons/blender-manual.json",
        "reference/setup-facts.json",
    ]
    out = subprocess.run(
        ["git", "check-attr", "text", "--", *paths], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    assert out.count(": text: unset") == len(paths), out


def test_notice_carries_both_attributions():
    text = " ".join(NOTICE.read_text(encoding="utf-8").split())
    assert "IfcOpenShell contributors" in text and "Blender Documentation Team" in text
    assert "GNU General Public License v3.0 or later" in text and "CC BY-SA 4.0" in text


def test_fixture_refusal_applies_the_privacy_allowance_and_python_rules():
    """Pages that could never join the slice are found before anything cites them (gold ingest)."""
    config = load_config(CONFIG)
    bonsai, manual = config.source("bonsai-docs"), config.source("blender-manual")
    path = "src/bonsai/docs/guides/troubleshooting.rst"
    allowed = (ROOT / "tests/fixtures/docs/bonsai-docs" / path).read_bytes()
    assert fixture_refusal(config, bonsai, path, allowed) is None
    changed = allowed + b"\nSee /home/someone/notes.\n"
    assert "home-path match(es) without a reviewed allowance" in fixture_refusal(
        config, bonsai, path, changed
    )
    other = "src/bonsai/docs/guides/authoring/drawings.rst"
    assert "without a reviewed allowance" in fixture_refusal(config, bonsai, other, allowed)
    code = b"Title\n=====\n\n.. code-block:: python\n\n   import bpy\n"
    assert "Python code" in fixture_refusal(config, manual, "manual/x.rst", code)
    assert fixture_refusal(config, bonsai, "src/bonsai/docs/x.rst", code) is None
