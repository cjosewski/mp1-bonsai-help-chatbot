# Third-party documentation notice

This repository's own code is GPL-3.0-or-later (see [`LICENSE`](LICENSE)). It also carries
a small slice of third-party documentation, copied unmodified from the pinned upstream
commits, under `tests/fixtures/docs/`. Those files keep their own licenses. The full
corpora are not in Git: `uv run --locked bonsai-help snapshot build` rebuilds them from
the pins in `config/doc-sources.json` and checks them against the page hashes in
`config/doc-manifest.json`.

## Bonsai documentation

Bonsai documentation by the IfcOpenShell contributors (https://github.com/IfcOpenShell/IfcOpenShell, src/bonsai/docs at tag bonsai-0.9.0post1, commit 2744f8426bdef98a486406628a121298a5479690), licensed under the GNU General Public License v3.0 or later. Copied unmodified.

- Files: `tests/fixtures/docs/bonsai-docs/src/bonsai/docs/` (25 pages).
- License text: [`tests/fixtures/docs/bonsai-docs/src/bonsai/COPYING`](tests/fixtures/docs/bonsai-docs/src/bonsai/COPYING)
  (GNU GPL v3; the upstream `src/bonsai/docs/conf.py` header states "version 3 of the
  License, or (at your option) any later version"). That `conf.py` is recorded in the
  manifest by its blob id and kept out of Git, because its header also names a
  contributor's personal contact address.

## Blender Manual

The Blender 5.3 Manual (https://docs.blender.org/manual/) by the Blender Documentation Team (https://projects.blender.org/blender/documentation), licensed under CC BY-SA 4.0 or any later version (https://creativecommons.org/licenses/by-sa/4.0/). Source: https://projects.blender.org/blender/blender-manual, branch blender-v5.3-release, commit 3481be3f6163a7c34e317b685f09fe67ca1057f0. Copied unmodified; logos, trademarks, icons, source code and Python scripts are not covered by that license and are not included.

- Files: `tests/fixtures/docs/blender-manual/manual/` (21 pages plus the Manual's own
  license page).
- License text: [`tests/fixtures/docs/blender-manual/LICENSE`](tests/fixtures/docs/blender-manual/LICENSE)
  (CC BY-SA 4.0 legal code) and the Manual's license page
  [`tests/fixtures/docs/blender-manual/manual/copyright.rst`](tests/fixtures/docs/blender-manual/manual/copyright.rst).
- No image, icon, logo or Python code from the Manual is included; the fixture check
  rejects Python code blocks in Manual fixtures.

## Packaging

A source distribution built from this repository includes `tests/fixtures/docs/`, so it
carries the CC BY-SA 4.0 Manual pages and the GPL Bonsai pages under the licenses above,
next to the GPL-3.0-or-later package code.
