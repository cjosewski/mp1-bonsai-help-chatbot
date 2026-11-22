# Bonsai help chatbot (Mini Project 1)

A course example, not a product. This repository builds and evaluates a small help
chatbot for one AEC topic: building information modeling with
[Bonsai](https://bonsaibim.org/) in [Blender](https://www.blender.org/). The chatbot
answers a user's Bonsai question for that user's stated setup (Blender and Bonsai
versions, IFC schema, discipline, model state). It works from the Bonsai documentation
and the Blender Manual. The same documentation is used to derive synthetic questions
and reference answers, and to ground the judge that evaluates the answers.

The project follows the course's six-step pipeline: generate, first-pass gate, human
labels, LLM judge, analysis, and two-phase iteration. The owner's plan,
`docs/MP1-BONSAI-HELP-CHATBOT.md`, defines the milestones B0 to B10 below (its §9). The
edits Chad directed for this public copy are recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

**Milestones B0 (repository readiness) and B1 (documentation snapshots) are done.**
Install, the offline tests and the documentation corpus rebuild run today; every
pipeline step below is marked *not yet implemented* and will be filled in when its
milestone lands.

| Milestone | What it delivers | Status |
| --- | --- | --- |
| B0 | Repository, licenses, decision log, porting map, packaging | Done |
| B1 | Pinned, hashed documentation snapshots; fixture slice | Done |
| B2 | Operator lexicons; setup profiles and cited fact table | Not yet implemented |
| B3 | Gold set and multi-part and injection requests | Not yet implemented |
| B4 | Rubric, prompts, deterministic checks; generation, gate and collection modules ported | Not yet implemented |
| B5 | Baseline run | Not yet implemented |
| B6 | Baseline human labels | Not yet implemented |
| B7 | Judge and Phase A calibration | Not yet implemented |
| B8 | Phase B correction | Not yet implemented |
| B9 | Analysis, charts and security pass | Not yet implemented |
| B10 | Submission set, replay demo, iteration log, demo video, coaching approval | Not yet implemented |

No dataset, label, judge result or chart exists yet. No measurement is claimed.

Decisions and open items: [`docs/DECISIONS.md`](docs/DECISIONS.md). How earlier code
will be ported: [`docs/PORTING-MAP.md`](docs/PORTING-MAP.md).

## Install

Requirements: Python 3.12 to 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
```

The plan's stack statement is Python 3.10 or newer. This repository currently
requires 3.12 or newer, the version the earlier code was verified on. The floor will
be lowered only after the ported tests pass on 3.10.

The analysis extra (Matplotlib and Seaborn) is installed with
`uv sync --locked --extra analysis`. It is not used until B9.

## Run the offline tests

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

The tests need no model, no network and no credentials. They check the package
metadata and license, and the snapshot builder and checker: pin mismatches, moved
tags and branches, network failure, missing pinned paths, a manifest that disagrees
with upstream, images never downloaded, tampered snapshots and fixtures, no-overwrite
rules, config validation and exit codes. Builder tests use small synthetic git
repositories on local disk (`file://` URLs); an `https` URL fails in the tests instead
of reaching the network. One test file checks the committed pin config, manifest,
fixture slice and `NOTICE.md` (the same as `bonsai-help snapshot check --committed`).

## Rebuild the documentation corpus

Run from the repository root:

```bash
uv run --locked bonsai-help snapshot build
uv run --locked bonsai-help snapshot check
```

`snapshot build` is the one command. For each source in `config/doc-sources.json` it
fetches the pinned commit's trees (no file contents), selects the pages, compares the
selection with the page hashes in `config/doc-manifest.json` before downloading
anything else, then fetches exactly the selected files in one request and checks every
byte against the manifest. It writes `data/snapshots/<source>/<pin-id>/` (git-ignored)
and never overwrites a snapshot: one that is already present is verified offline and
left alone, and an invalid one is refused (exit 5) for inspection.

| Source | Pin | Pages | Bytes |
| --- | --- | ---: | ---: |
| Bonsai documentation, `src/bonsai/docs` in [IfcOpenShell](https://github.com/IfcOpenShell/IfcOpenShell) | tag `bonsai-0.9.0post1` (lightweight tag), commit `2744f8426bdef98a486406628a121298a5479690` | 95 | 363,783 |
| [Blender Manual](https://projects.blender.org/blender/blender-manual) source, `manual/` | commit `3481be3f6163a7c34e317b685f09fe67ca1057f0` on branch `blender-v5.3-release` | 2,450 | 5,961,691 |

Every reStructuredText page under each root is kept. Retrieval tags (Bonsai `user`,
`developer`, `fragment`; Manual `core` for the areas plan §2 and §5 name, `other` for
the rest) live in the config and are not part of a snapshot's identity. Images, the
Manual's source code and other files that are not pages are never fetched, with one
exception: the license evidence files (Bonsai's `src/bonsai/COPYING` and
`src/bonsai/docs/conf.py`, the Manual's `LICENSE` and `manual/copyright.rst`) are
fetched, checked by blob id and stored in the snapshot even when they are not pages.
The deny lists govern page selection only. Bonsai's `conf.py` stays out of Git. The
manifest's `not_selected` counts, by file type, the files under each root that are not
pages, so it still counts `conf.py` (`py`).

What a rebuild needs: Git 2.44 or newer (the build probes for `--no-lazy-fetch` and
stops with exit 3 without it), network access to github.com and projects.blender.org
over HTTPS, about 2.8 MiB of transfer, and about 10 MB of files under `data/`. Proxy and
CA settings (`HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `GIT_SSL_CAINFO` and similar)
are passed through to git; user and system git configuration is not used. Measured on
November 22, 2026: both sources rebuilt from an empty `data/` in about 4 seconds, and
the manifest written from that rebuild was byte-identical to the committed one. Do not
run two builds into the same data root at once; the second stops with exit 5.

| Command | Does | Network |
| --- | --- | --- |
| `snapshot build` | Verify present snapshots; fetch, check and write absent ones | Only for absent snapshots |
| `snapshot build --write-manifest` | As above, but write `config/doc-manifest.json` from the fetched bytes (once per pin change). A tag that no longer points at the pinned commit is exit 4 here and only a warning on a plain rebuild | Yes |
| `snapshot check` | Committed files plus both snapshots (fails if a snapshot is not built; use `--committed` offline) | Never |
| `snapshot check --committed` | Config, manifest, fixture slice, `NOTICE.md` and the privacy rules only | Never |
| `snapshot fixtures` | Copy the fixture slice from verified snapshots into `tests/fixtures/docs/`; differing files need `--replace` | Never |

Exit codes: 0 success; 1 check failed; 2 usage or invalid config; 3 git or network
failure; 4 upstream differs from the pins; 5 refused to write. Errors are one line
each on stderr, without tracebacks or absolute paths. A failed build leaves its
staging directory for inspection; `snapshot check` lists it as a warning.

The fixture slice in `tests/fixtures/docs/` (25 Bonsai pages, 21 Manual pages, the
license texts and `fixtures.json`) covers every plan §5 category, so offline tests and
the later replay demo need no network. Its pages link to pages outside the slice, so
nothing offline may require those links to resolve.

## Run each step

*Not yet implemented (B4 to B9).* Each step will run on its own against saved
artifacts:

1. Generate: derive questions, then answer them (B4, B5, B8).
2. First-pass gate: schema, deterministic checks, duplicates, category balance (B4, B5).
3. Human labels: blind, resumable labeling (B6).
4. Judge: independent prompt at a lower temperature than the generator (B7).
5. Analyze: pass rates, agreement, intervals and five charts (B9).
6. Iterate: Phase A judge calibration, Phase B generator correction (B7, B8).

A model is configured explicitly as a local OpenAI-compatible endpoint. A documented,
opt-in hosted path for graders without local models is planned; it is never used as a
silent fallback.

## Replay demo

*Not yet implemented (B10).* An offline replay of committed fixture traces that needs
no model and no credentials.

## Repository layout

```text
.
├── LICENSE              GNU GPL v3 (full text)
├── NOTICE.md            attribution and licenses of the documentation fixtures
├── README.md
├── AGENTS.md            instructions for coding agents
├── pyproject.toml       package bonsai_help, dependencies, ruff and pytest settings
├── uv.lock
├── config/
│   ├── doc-sources.json  pinned commits, page selection, licenses, attribution
│   └── doc-manifest.json page hashes of both snapshots (written by the tool)
├── docs/
│   ├── DECISIONS.md     dated owner decisions and open items
│   └── PORTING-MAP.md   what is ported from the earlier repository, and when
├── src/bonsai_help/     the package: snapshot builder, checker and CLI (`bonsai-help`)
├── tests/               offline behaviour tests
│   └── fixtures/docs/   unmodified, attributed documentation fixture slice
└── submission/          curated course submission set (filled at B10; datasets CC BY-SA 4.0)
```

Raw attempt logs, scratch runs, local configuration and the full documentation
snapshots (`data/`) are git-ignored and stay outside Git. Only the curated set under `submission/` is committed.

## Licensing

- **Code:** GNU General Public License, version 3 or (at your option) any later
  version (`GPL-3.0-or-later`). See [`LICENSE`](LICENSE).

  > This program is free software: you can redistribute it and/or modify it under the
  > terms of the GNU General Public License as published by the Free Software
  > Foundation, either version 3 of the License, or (at your option) any later version.
  > This program is distributed in the hope that it will be useful, but WITHOUT ANY
  > WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
  > PARTICULAR PURPOSE. See the GNU General Public License for more details.

- **Generated datasets** (under `submission/`): Creative Commons
  Attribution-ShareAlike 4.0 International (CC BY-SA 4.0). Quoted Bonsai or Blender
  Manual text keeps its source license wherever it appears in `submission/`, including
  inside the datasets. This is a course
  assignment and portfolio piece, not a product (see `docs/DECISIONS.md`).
- **Documentation fixtures** keep their own licenses: Bonsai documentation and the
  operator lexicon derived from Bonsai source are GPL-3.0-or-later; Blender Manual
  fixtures are CC BY-SA 4.0.

Source attributions to the IfcOpenShell contributors (Bonsai) and the Blender
Documentation Team (Blender Manual), the license texts and the list of fixture files
are in [`NOTICE.md`](NOTICE.md). The fixtures are unmodified copies of the pinned
upstream files.
