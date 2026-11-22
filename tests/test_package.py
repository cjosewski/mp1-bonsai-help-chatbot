import tomllib
from importlib.metadata import version
from pathlib import Path

import bonsai_help

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_installed_version_matches_package_and_pyproject():
    declared = _pyproject()["project"]["version"]
    assert bonsai_help.__version__ == declared
    assert version("mp1-bonsai-help-chatbot") == declared


def test_code_is_licensed_gpl_3_or_later_with_full_text():
    project = _pyproject()["project"]
    assert project["license"] == "GPL-3.0-or-later"
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    assert "Version 3, 29 June 2007" in text.splitlines()[1]
    assert "END OF TERMS AND CONDITIONS" in text
