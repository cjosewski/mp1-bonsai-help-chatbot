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

**Milestones B0 (repository readiness), B1 (documentation snapshots) and B2 (lexicons
and setup facts) are done.** Install, the offline tests, the documentation corpus
rebuild, the section index, the lexicons and the setup-fact checks run today; every
pipeline step below is marked *not yet implemented* and will be filled in when its
milestone lands. The B2 setup profiles and fact rows are drafts by the assistant,
pending Chad's review at B3. B3 has started: Chad's November 22, 2026 decisions on the
version pairings, the IFC schemas, review packets and drafting are applied
(see [`docs/DECISIONS.md`](docs/DECISIONS.md)); the gold set itself does not exist yet.

| Milestone | What it delivers | Status |
| --- | --- | --- |
| B0 | Repository, licenses, decision log, porting map, packaging | Done |
| B1 | Pinned, hashed documentation snapshots; fixture slice | Done |
| B2 | Operator lexicons; setup profiles and cited fact table | Done (rows await Chad's review at B3) |
| B3 | Gold set and multi-part and injection requests | Started: Chad's decisions applied; gold set not yet built |
| B4 | Rubric, prompts, deterministic checks; generation, gate and collection modules ported | Not yet implemented |
| B5 | Baseline run | Not yet implemented |
| B6 | Baseline human labels | Not yet implemented |
| B7 | Judge and Phase A calibration | Not yet implemented |
| B8 | Phase B correction | Not yet implemented |
| B9 | Analysis, charts and security pass | Not yet implemented |
| B10 | Submission set, replay demo, iteration log, demo video, coaching approval | Not yet implemented |

No dataset, label, judge result or chart exists yet. No model measurement is claimed;
the counts below are counts of pinned files.

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
metadata and license; the section splitter, the ported BM25 core, both lexicon
extractors and the setup-fact citation checks (each failure mode on a changed copy of
a real row); and the snapshot builder and checker: pin mismatches, moved
tags and branches, network failure, missing pinned paths, a manifest that disagrees
with upstream, images never downloaded, tampered snapshots and fixtures, no-overwrite
rules, config validation and exit codes. Builder tests use small synthetic git
repositories on local disk (`file://` URLs); an `https` URL fails in the tests instead
of reaching the network. Two test files check the committed pin config, manifest,
fixture slice, `NOTICE.md` and the files under `reference/` (the same as the
`--committed` checks below). The extractor tests use synthetic Python and RST; no
Bonsai source file is in the repository.

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
| [Blender Manual](https://projects.blender.org/blender/blender-manual) 5.2 source, `manual/` | commit `4a3be8f9ed3b66b24913e0a0d491d3429a70ea08` on branch `blender-v5.2-release` | 2,358 | 5,745,382 |
| Bonsai documentation, older release (`bonsai-docs-0-8-5-post1`) | tag `bonsai-0.8.5-post1` (lightweight tag), commit `e6258ab4a8e8c76d18b743ea80a6f7699809319b` | 95 | 361,583 |
| Blender Manual 4.5 source (`blender-manual-4-5`), `manual/` | commit `c2b171709bbca119846f1cd8cda70ad719cf6296` on branch `blender-v4.5-release` | 2,072 | 5,182,293 |
| Bonsai add-on source (`bonsai-source`), every `.py` file under `src/bonsai/bonsai` | tag `bonsai-0.9.0post1`, commit `2744f842…` (as above) | 447 | 7,738,049 |
| Bonsai add-on source, older release (`bonsai-source-0-8-5-post1`) | tag `bonsai-0.8.5-post1`, commit `e6258ab4…` (as above) | 425 | 6,593,423 |

Each version line has its own Bonsai docs, add-on source and matching Manual (Chad's
decision of November 22, 2026): Blender 5.2 with Bonsai 0.9.0-post1, and Blender 4.5 with
Bonsai 0.8.5-post1 as the older-release contrast. The Blender 5.3 Manual pin
(`blender-v5.3-release`, commit `3481be3f`) was replaced by the 5.2 pin; nothing cites it
any more, and its record is in `docs/DECISIONS.md`. The two add-on sources are read only by the operator lexicon; no
Bonsai source file is committed, because their headers carry contributors' contact
addresses.

Every reStructuredText page under each root is kept. Retrieval tags (Bonsai `user`,
`developer`, `fragment`; Manual `core` for the areas plan §2 and §5 name, `other` for
the rest) live in the config and are not part of a snapshot's identity. Images, the
Manual's source code and other files that are not pages are never fetched, with one
exception: the license evidence files (Bonsai's `src/bonsai/COPYING` and
`src/bonsai/docs/conf.py`, the Manual's `LICENSE` and `manual/copyright.rst`; the B2 sources cite the same
`src/bonsai/COPYING` blob, and the 4.5 Manual the same two Manual blobs, each committed once) are
fetched, checked by blob id and stored in the snapshot even when they are not pages.
The deny lists govern page selection only. Bonsai's `conf.py` stays out of Git. The
manifest's `not_selected` counts, by file type, the files under each root that are not
pages, so it still counts `conf.py` (`py`). `not_selected` is outside `source_digest`, so
`snapshot check --committed` cannot detect a hand edit to it once the digests are
recomputed; `snapshot check` and `snapshot build` compare it with a built snapshot's own
record, and a build into an empty data root compares it with upstream.

What a rebuild needs: Git 2.44 or newer (the build probes for `--no-lazy-fetch` and
stops with exit 3 without it), network access to github.com and projects.blender.org
over HTTPS, and about 49 MB under `data/` (40 MB of snapshots and a 9 MB git cache),
plus 28 MB for the section index (`docs index build`). Proxy and CA settings
(`HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `GIT_SSL_CAINFO` and similar) are passed
through to git; user and system git configuration is not used. Measured on November
22, 2026, after the Manual pin change: all six sources rebuilt from an empty data root in
about 11 seconds; a plain build into a second empty data root matched the manifest
written from that rebuild, writing it again from a third empty root gave identical bytes,
and the four Bonsai entries were unchanged by the Manual pins. Do not
run two builds into the same data root at once. They share the git cache under
`data/git/`, so the second usually stops with exit 3 (a git lock or setup conflict in
that cache), or with exit 5 if it reaches the point of moving its snapshot into place;
the first build's snapshot is unaffected.

| Command | Does | Network |
| --- | --- | --- |
| `snapshot build` | Verify present snapshots; fetch, check and write absent ones | Only for absent snapshots |
| `snapshot build --write-manifest` | As above, but write `config/doc-manifest.json` (once per pin change). Absent snapshots are fetched and recorded from their bytes; snapshots already present are verified and their own records re-emitted, so run it on an empty data root after a pin change. A tag that no longer points at the pinned commit is exit 4 here and only a warning on a plain rebuild | Only for absent snapshots |
| `snapshot check` | Committed files plus every snapshot (fails if a snapshot is not built; use `--committed` offline) | Never |
| `snapshot check --committed` | Config, manifest, fixture slice, `NOTICE.md` and the privacy rules only | Never |
| `snapshot fixtures` | Copy the fixture slice from verified snapshots into `tests/fixtures/docs/`; differing files need `--replace` | Never |

Exit codes: 0 success; 1 check failed; 2 usage or invalid config; 3 git or network
failure; 4 upstream differs from the pins; 5 refused to write. Errors are one line
each on stderr, without tracebacks or absolute paths. A failed build leaves its
staging directory for inspection; `snapshot check` lists it as a warning.

The fixture slice in `tests/fixtures/docs/` (33 Bonsai 0.9.0-post1 pages, 14 Bonsai
0.8.5-post1 pages, 22 Blender 5.2 Manual pages, 1 Blender 4.5 Manual page, the license
texts and `fixtures.json`) covers every plan §5 category, every page a setup fact cites and
the six Bonsai tutorials of each pin (`tutorials/project0.rst` to `project5.rst`, which gold
multi-part requests cite), so offline tests and the later replay demo need no network. Its pages link to pages outside the slice, so nothing
offline may require those links to resolve.

## Section index, lexicons and setup facts (B2)

Run after `snapshot build`, from the repository root:

```bash
uv run --locked bonsai-help docs index build
uv run --locked bonsai-help lexicon check
uv run --locked bonsai-help setup check
```

| Command | Does | Network |
| --- | --- | --- |
| `docs index build` | Cut every docs page at its headings into section records under `data/index/` (git-ignored, never overwritten; a present index is verified) and compare with `reference/docs-index.json`. `--write-digest` writes that file (once per pin change) | Never |
| `docs index check [--committed]` | The committed digest agrees with the config and manifest; without `--committed`, a rebuild and the built index agree with it | Never |
| `docs search QUERY [--source ID] [--tag T] [--top N]` | BM25 over passages of the built index (a precursor of B5's `search_docs`) | Never |
| `docs section RECORD_ID` | Print one section record; an unknown id is exit 1 | Never |
| `lexicon build [--write]` | Extract every lexicon from the verified snapshots and compare with `reference/lexicons/` (exit 1 on a difference); `--write` writes them | Never |
| `lexicon check [--committed]` | Layout, digest, pins, ordering, counts, no privacy match, and the RST entries of fixture pages equal a re-extraction from the fixture slice; without `--committed`, also a full rebuild | Never |
| `setup candidates [--source ID]` | Print candidate lines for fact rows (schema and version mentions, change words, differences between the two Bonsai docs pins) as JSON lines | Never |
| `setup check [--committed]` | Profiles and every fact citation, against the fixture slice (`--committed`) or the snapshots and the built index | Never |
| `setup format` | Validate the two hand-edited setup files and rewrite them in canonical layout with their digests | Never |

A section record is one heading's span of a page: source, pin, path, heading path (titles
with RST backslash escapes rendered), line and byte span and the SHA-256 of its bytes. The records of a page concatenate to the page
exactly; directives (`include`, `toctree`) are recorded, not expanded. Measured on the
pins: 463 records for the Bonsai 0.9.0-post1 docs, 464 for 0.8.5-post1, 8,997 for the 5.2
Manual and 8,245 for the 4.5 Manual (159 and 72 Manual pages are include stubs with no
heading). Building the index takes about a second per Manual.

The lexicons in `reference/lexicons/` (measured on the pins; the scope is stated
because the plan's 1,311 ids and 1,559 labels match no scope that could be reproduced):

| Lexicon | Contents |
| --- | --- |
| `bonsai-source.json` | Operators, macros, workspace tools, panels and menus of the whole add-on, read by AST (never imported): 1,317 unique `bim.*` operator ids (1,305 `bl_idname` constants plus 12 built by `build_edit_lifecycle`; 1,086 of them in `bim/module/*/operator.py`), 1,280 distinct labels, 208 panels, 13 menus, 30 tools, 233 button texts that `layout.operator(..., text=...)` shows, 23 labels shared by several ids, and the values that could not be resolved (listed, never guessed) |
| `bonsai-source-0-8-5-post1.json` | The same for 0.8.5-post1: 1,246 `bim.*` operator ids. 77 ids exist only at 0.9.0-post1 and 6 only at 0.8.5-post1 |
| `blender-manual.json`, `blender-manual-4-5.json` | 5.2 Manual: 1,410 Blender operator ids from `.. _bpy.ops.*:` targets at any indent (every `:ref:` to one resolves), 1,500 menu paths, 397 hotkeys, 206 `:guilabel:` texts and the fields of 1,517 `.. reference::` blocks; 4.5 Manual: 1,311 operator ids, 1,417 menu paths, 391 hotkeys, 117 `:guilabel:` texts and 1,417 `.. reference::` blocks. Every entry lists the section records that hold it; markup inside inline literals and literal or code blocks is an example, not UI, and is skipped. An operator label never shows a cross-reference target: a `:ref:`/`:doc:` term gives its title, and the 3 with a bare target (in each Manual) give no label. A term's `:kbd:` roles are removed with the separators between them, and the 3 menu paths (in each Manual) that begin with `-->` continue a menu opened another way (counted as `menu_paths_continued`) |
| `bonsai-docs.json`, `bonsai-docs-0-8-5-post1.json` | Menu paths, hotkeys (63 written as `:kbd:` roles joined by `+`) and UI paths written as `` `A > B` `` in the Bonsai docs |

Not extracted in B2: Bonsai keymap hotkeys (only the docs' `:kbd:` roles), settings
(`bpy.props` names) and `bpy.types` targets. The lexicons are deterministic heuristics
for the B4 checks; they never decide a dimension.

`reference/setup-profiles.json` holds two version lines and 18 setup profiles, with the
pairings Chad chose on November 22, 2026 (origin `Chad, 2026-11-22`). `VL-current` is
Blender 5.2 with Bonsai 0.9.0-post1 and the 5.2 Manual; `VL-older` is Blender 4.5 with
Bonsai 0.8.5-post1 and the 4.5 Manual. Both carry `pairing_status` `cited`: each line's own
Bonsai docs list its Blender release (SF-012 lists 5.1 or 5.2, SF-013 lists 4.3, 4.4 or
4.5), and `setup check` requires a `cited` line to list such a `version_claim` row among its
claims, citing the line's own Bonsai docs pin, with a key term that names the release on
token boundaries. `VL-current` also lists SF-015, the same pin's troubleshooting page that
says Blender 4.5. The pairing itself is evidence, not a scored fact. A line's
`version_claim` and `doc_conflict` rows may cite any docs pin; every other row
(`schema_dependent`, `version_dependent`, `doc_absence`) needs a citation from the line's
own Bonsai docs or Manual, so the 5.2 Manual does not stand in for `VL-older`. The
`ifc_schema` values are `partly cited`: SF-007 supports them for `new_project` only
(`cited_for`); for opened and federated models all three are a stated default that Chad
kept, and schema facts are scored only where a row cites them. The profiles are a
full IFC schema × model state factorial per line, with disciplines rotated as a Latin
square; the 6 diagonal profiles are the assessed split and the other 12 the development
split, and each split covers every schema, model state, discipline and version line.

`reference/setup-facts.json` holds 19 fact rows and 10 claims left out because no pinned
text supports them. Every row cites pinned sections with short verbatim quotes;
`setup check` proves each quote occurs exactly once, on token boundaries and outside RST
comments, in the cited section, and that every key term is in a quote, on token boundaries
too. Whether a claim
says no more than its quotes is not machine-checked: every row, profile and version line
is `assistant_drafted` until Chad reviews it at B3, and uncited rows cannot exist.

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
│   └── doc-manifest.json page hashes of every snapshot (written by the tool)
├── reference/
│   ├── docs-index.json   digest of the section index (written by the tool)
│   ├── lexicons/         operator, menu and hotkey lexicons (written by the tool)
│   ├── setup-profiles.json  version lines and setup profiles (assistant-drafted)
│   └── setup-facts.json  cited setup-fact rows (assistant-drafted)
├── docs/
│   ├── DECISIONS.md     dated owner decisions and open items
│   └── PORTING-MAP.md   what is ported from the earlier repository, and when
├── src/bonsai_help/     the package: snapshots, section index, lexicons, setup checks, CLI
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
  lexicons derived from Bonsai source and docs are GPL-3.0-or-later; Blender Manual
  fixtures and the Manual lexicon are CC BY-SA 4.0.

Source attributions to the IfcOpenShell contributors (Bonsai) and the Blender
Documentation Team (Blender Manual), the license texts and the list of fixture files
are in [`NOTICE.md`](NOTICE.md). The fixtures are unmodified copies of the pinned
upstream files.
