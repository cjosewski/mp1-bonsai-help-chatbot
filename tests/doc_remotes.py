"""Synthetic local git remotes for the snapshot tests (no network; `file://` URLs only)."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bonsai_help.git_fetch import git_blob_id

FIXED_DATE = "2026-01-01T00:00:00+0000"
GIT_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Synthetic Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Synthetic Author",
    "GIT_COMMITTER_EMAIL": "author@example.invalid",
    "GIT_AUTHOR_DATE": FIXED_DATE,
    "GIT_COMMITTER_DATE": FIXED_DATE,
}

FILES: dict[str, bytes] = {
    "docs/index.rst": b"Index\n=====\n\nSynthetic index page.\n",
    "docs/guide/page.rst": b"Page\n====\n\nSynthetic guide page.\n",
    "docs/_fragment.rst": b".. note:: Synthetic fragment.\n",
    "docs/license.rst": b"License\n=======\n\nSynthetic license page.\n",
    "docs/img/picture.png": b"\x89PNG synthetic image bytes",
    "docs/img/photo.webp": b"RIFF synthetic webp bytes",
    "docs/img/icon.svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>\n",
    "docs/conf.py": b"# synthetic sphinx configuration\n",
    "COPYING": b"SYNTHETIC LICENSE TEXT\n",
    "other/outside.rst": b"Outside the root.\n",
}


def git(*args: str, cwd: Path | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True)
    return done.stdout.decode().strip()


@dataclass
class Remote:
    work: Path
    bare: Path
    url: str
    commit: str
    tag_object: str | None

    def advance(self, files: dict[str, bytes | None]) -> str:
        """Commit changes (None deletes a file) and push the branch; returns the new commit."""
        for path, data in files.items():
            target = self.work / path
            if data is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        git("add", "-A", cwd=self.work)
        git("commit", "-q", "-m", "advance", cwd=self.work)
        git("push", "-q", str(self.bare), "HEAD", cwd=self.work)
        return git("rev-parse", "HEAD", cwd=self.work)

    def move_tag(self, name: str) -> None:
        git("tag", "-f", name, cwd=self.work)
        git("push", "-q", "-f", str(self.bare), f"refs/tags/{name}", cwd=self.work)

    def has_object(self, cache: Path, oid: str) -> bool:
        argv = ["git", "--no-lazy-fetch", "cat-file", "-e", oid]
        return subprocess.run(argv, cwd=cache, env=GIT_ENV, capture_output=True).returncode == 0


def make_remote(
    tmp_path: Path,
    files: dict[str, bytes] = FILES,
    *,
    tag: str | None = None,
    annotated: bool = False,
    branch: str = "main",
    name: str = "remote",
) -> Remote:
    work, bare = tmp_path / f"{name}-work", tmp_path / f"{name}.git"
    git("init", "-q", "-b", branch, str(work))
    for path, data in files.items():
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "initial", cwd=work)
    if tag:
        git("tag", *(["-a", "-m", "release"] if annotated else []), tag, cwd=work)
    git("init", "-q", "--bare", str(bare))
    git("config", "uploadpack.allowFilter", "true", cwd=bare)
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=bare)
    git("push", "-q", str(bare), "--all", cwd=work)
    git("push", "-q", str(bare), "--tags", cwd=work)
    commit = git("rev-parse", "HEAD", cwd=work)
    tag_object = git("rev-parse", f"refs/tags/{tag}", cwd=work) if tag and annotated else None
    return Remote(work, bare, bare.as_uri(), commit, tag_object)


def source_config(**overrides) -> dict:
    source = {
        "id": "fake-docs",
        "repository": "fake",
        "root": "docs",
        "include": ["docs/**/*.rst"],
        "exclude": [],
        "deny": ["**/*.png", "**/*.webp", "**/*.svg", "**/*.py"],
        "tags": [{"glob": "docs/_*.rst", "tag": "fragment"}],
        "default_tag": "user",
        "license": "GPL-3.0-or-later",
        "license_evidence": [
            {"path": "COPYING", "blob": git_blob_id(FILES["COPYING"]), "commit_copy": True},
            {
                "path": "docs/license.rst",
                "blob": git_blob_id(FILES["docs/license.rst"]),
                "commit_copy": True,
            },
            {
                "path": "docs/conf.py",
                "blob": git_blob_id(FILES["docs/conf.py"]),
                "commit_copy": False,
            },
        ],
        "attribution": "Synthetic documentation by the test suite, copied unmodified.",
        "permitted_use": "Offline tests only.",
        "fixture_pages": [
            {"path": "docs/guide/page.rst", "categories": ["bonsai_modeling"]},
            {"path": "docs/_fragment.rst", "categories": []},
        ],
        "fixture_min_per_category": 0,
    }
    return {**source, **overrides}


def write_config(
    path: Path,
    remote: Remote,
    *,
    ref: dict | None = None,
    commit: str | None = None,
    sources=None,
    repositories=None,
) -> Path:
    config = {
        "schema": "doc-sources-v1",
        "pins_verified_on": "2026-01-01",
        "repositories": repositories
        or {
            "fake": {
                "url": remote.url,
                "ref": ref or {"kind": "branch", "name": "main"},
                "commit": commit or remote.commit,
            }
        },
        "sources": sources or [source_config()],
    }
    path.write_text(json.dumps(config, indent=2))
    return path
