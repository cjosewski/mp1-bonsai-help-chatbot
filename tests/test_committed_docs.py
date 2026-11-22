"""The committed pin config, manifest, fixture slice and notice (real repository files, offline)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bonsai_help import cli
from bonsai_help.doc_snapshot import PYTHON_CODE, check_committed
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


def test_manifest_pins_both_sources():
    config = load_config(CONFIG)
    manifest = json.loads(MANIFEST.read_bytes())
    assert {s.id for s in config.sources} == {"bonsai-docs", "blender-manual"}
    assert manifest["sources"]["bonsai-docs"]["repository"]["ref"]["name"] == "bonsai-0.9.0post1"
    assert manifest["sources"]["blender-manual"]["repository"]["ref"]["kind"] == "branch"
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
    for source in config.sources:
        for category in CATEGORIES:
            count = sum(category in page.categories for page in source.fixture_pages)
            assert count >= max(source.fixture_min_per_category, 1)
    for path in (FIXTURES / "blender-manual").rglob("*"):
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
    ]
    out = subprocess.run(
        ["git", "check-attr", "text", "--", *paths], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    assert out.count(": text: unset") == len(paths), out


def test_notice_carries_both_attributions():
    text = " ".join(NOTICE.read_text(encoding="utf-8").split())
    assert "IfcOpenShell contributors" in text and "Blender Documentation Team" in text
    assert "GNU General Public License v3.0 or later" in text and "CC BY-SA 4.0" in text
