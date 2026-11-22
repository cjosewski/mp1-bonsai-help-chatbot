# Third-party documentation notice

This repository's own code is GPL-3.0-or-later (see [`LICENSE`](LICENSE)). It also carries
a small slice of third-party documentation, copied unmodified from the pinned upstream
commits, under `tests/fixtures/docs/`. Those files keep their own licenses. The full
corpora are not in Git: `uv run --locked bonsai-help snapshot build` rebuilds them from
the pins in `config/doc-sources.json` and checks them against the page hashes in
`config/doc-manifest.json`.

## Bonsai documentation

Bonsai documentation by the IfcOpenShell contributors (https://github.com/IfcOpenShell/IfcOpenShell, src/bonsai/docs at tag bonsai-0.9.0post1, commit 2744f8426bdef98a486406628a121298a5479690), licensed under the GNU General Public License v3.0 or later. Copied unmodified.

- Files: `tests/fixtures/docs/bonsai-docs/src/bonsai/docs/` (33 pages).
- License text: [`tests/fixtures/docs/bonsai-docs/src/bonsai/COPYING`](tests/fixtures/docs/bonsai-docs/src/bonsai/COPYING)
  (GNU GPL v3; the upstream `src/bonsai/docs/conf.py` header states "version 3 of the
  License, or (at your option) any later version"). That `conf.py` is recorded in the
  manifest by its blob id and kept out of Git, because its header also names a
  contributor's personal contact address.

## Bonsai documentation, older release (0.8.5-post1)

Bonsai documentation by the IfcOpenShell contributors (https://github.com/IfcOpenShell/IfcOpenShell, src/bonsai/docs at tag bonsai-0.8.5-post1, commit e6258ab4a8e8c76d18b743ea80a6f7699809319b), licensed under the GNU General Public License v3.0 or later. Copied unmodified.

- Pinned for the older version line (Blender 4.5 with Bonsai 0.8.5-post1, Chad's decision of
  November 22, 2026, which settles open item O-3).
- Files: `tests/fixtures/docs/bonsai-docs-0-8-5-post1/src/bonsai/docs/` (14 pages: the ones
  setup-fact rows cite and the six tutorials that gold multi-part requests cite).
- License text: the same `src/bonsai/COPYING` blob as above, committed once under
  `tests/fixtures/docs/bonsai-docs/`. This release's `src/bonsai/docs/conf.py` is recorded by
  its blob id and kept out of Git for the same reason as above.

## Bonsai add-on source (operator lexicon)

Bonsai add-on source code by the IfcOpenShell contributors (https://github.com/IfcOpenShell/IfcOpenShell, src/bonsai/bonsai at tag bonsai-0.9.0post1, commit 2744f8426bdef98a486406628a121298a5479690), licensed under the GNU General Public License v3.0 or later. Read only to extract the operator, panel and menu lexicon; no source file is committed.

Bonsai add-on source code by the IfcOpenShell contributors (https://github.com/IfcOpenShell/IfcOpenShell, src/bonsai/bonsai at tag bonsai-0.8.5-post1, commit e6258ab4a8e8c76d18b743ea80a6f7699809319b), licensed under the GNU General Public License v3.0 or later. Read only to extract the operator, panel and menu lexicon; no source file is committed.

- No Bonsai source file is committed (their headers name contributors' contact
  addresses). The committed lexicons under `reference/lexicons/bonsai-source*.json` hold
  only identifiers, labels, button texts, panel fields, file paths and line numbers, and
  keep GPL-3.0-or-later.
- License text: the same `src/bonsai/COPYING` blob as above.

## Blender Manual

The Blender 5.2 Manual (https://docs.blender.org/manual/) by the Blender Documentation Team (https://projects.blender.org/blender/documentation), licensed under CC BY-SA 4.0 or any later version (https://creativecommons.org/licenses/by-sa/4.0/). Source: https://projects.blender.org/blender/blender-manual, branch blender-v5.2-release, commit 4a3be8f9ed3b66b24913e0a0d491d3429a70ea08. Copied unmodified; logos, trademarks, icons, source code and Python scripts are not covered by that license and are not included.

- Files: `tests/fixtures/docs/blender-manual/manual/` (22 pages plus the Manual's own
  license page).
- License text: [`tests/fixtures/docs/blender-manual/LICENSE`](tests/fixtures/docs/blender-manual/LICENSE)
  (CC BY-SA 4.0 legal code) and the Manual's license page
  [`tests/fixtures/docs/blender-manual/manual/copyright.rst`](tests/fixtures/docs/blender-manual/manual/copyright.rst).
- No image, icon, logo or Python code from the Manual is included; the fixture check
  rejects Python code blocks in Manual fixtures.
- Pinned for the current version line (Blender 5.2 with Bonsai 0.9.0-post1, Chad's decision
  of November 22, 2026). It replaces the Blender 5.3 Manual pin (branch
  `blender-v5.3-release`, commit `3481be3f`), whose history is in `docs/DECISIONS.md`.

## Blender Manual, older release (4.5)

The Blender 4.5 Manual (https://docs.blender.org/manual/) by the Blender Documentation Team (https://projects.blender.org/blender/documentation), licensed under CC BY-SA 4.0 or any later version (https://creativecommons.org/licenses/by-sa/4.0/). Source: https://projects.blender.org/blender/blender-manual, branch blender-v4.5-release, commit c2b171709bbca119846f1cd8cda70ad719cf6296. Copied unmodified; logos, trademarks, icons, source code and Python scripts are not covered by that license and are not included.

- Pinned for the older version line (Blender 4.5 with Bonsai 0.8.5-post1, Chad's decision of
  November 22, 2026).
- Files: `tests/fixtures/docs/blender-manual-4-5/manual/` (1 page, the one a setup-fact row
  cites).
- License text: the same `LICENSE` and `manual/copyright.rst` blobs as above, committed once
  under `tests/fixtures/docs/blender-manual/`. The fixture check rejects Python code blocks in
  these fixtures too.

## Gold set (`reference/gold/`)

The published gold files (`reference/gold/development.json` and `held-out.json`, written by
`bonsai-help gold publish --write`) are generated datasets under CC BY-SA 4.0. They hold
short verbatim quotes, record ids and heading paths of the pinned pages above; quoted Bonsai
text keeps GPL-3.0-or-later and quoted Blender Manual text keeps CC BY-SA 4.0, with the
attributions above. Section text is not committed there: the fixture slice reproduces it.

## Packaging

A source distribution built from this repository includes `tests/fixtures/docs/`, so it
carries the CC BY-SA 4.0 Manual pages and the GPL Bonsai pages under the licenses above,
next to the GPL-3.0-or-later package code.
