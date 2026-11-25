# Bonsai help Q&A synthetic data (Mini Project 1)

A course example, not a product. This repository generates and evaluates synthetic help
data for one AEC topic: building information modeling with
[Bonsai](https://bonsaibim.org/) in [Blender](https://www.blender.org/). One generation
prompt, parameterized by category and user setup (Blender and Bonsai versions, IFC
schema, discipline, model state), writes each question and its seven-field answer from
pinned sections of the Bonsai documentation and the Blender Manual. The same
documentation grounds the judge that evaluates the items.

On November 23, 2026 Chad moved the help chatbot itself, its doc tools, the security pass
and the gold set to Mini Project 4; MP1 is the data and its evaluation, as the course brief
asks. The repository name still says "chatbot" until Chad decides otherwise (open item
O-8).

The project follows the course's six-step pipeline: generate, first-pass gate, human
labels, LLM judge, analysis, and two-phase iteration. The owner's plan,
`docs/MP1-BONSAI-HELP-CHATBOT.md`, defines the milestones B0 to B10 below (its §9). The
edits Chad directed for this public copy are recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

**Milestones B0 (repository readiness), B1 (documentation snapshots) and B2 (lexicons
and setup facts) are done. B3 (gold set) was withdrawn from MP1 on November 23, 2026**
and moves to Mini Project 4; its tooling, its tests and the 6 published items stay here,
frozen, and the paused review packets GP-021 to GP-025 stay unimported. **B4 (generation
and the first-pass gate) is done**; it has no rubric, which Chad moved to B5 on November
24, 2026. **B5 (rubric and baseline run) is done**:
- Chad accepted the rubric `config/rubric.json` (`bonsai-rubric-v1`) as drafted on
  November 24, 2026, so its status is `chad_accepted`.
- The baseline collection `baseline-2026-11-24-r2` (generator v1.1,
  `prompts/generator-v1.1.md`) is ready.
- On Chad's decision "Freeze the cohort", cohort `baseline-b5-cohort-1` is frozen:
  50 items, 10 per category, assessed split.
- `collection-report` reports the baseline's figures with 95% intervals.

The run config can name a separate local embedding server and can turn a thinking
model's reasoning off (`enable_thinking`, below). The first baseline collection
(`baseline-2026-11-24`, generator v1) was stopped during batch 2 on Chad's decision "Stop,
fix, restart (Recommended)", and its evidence is kept unchanged.

**B6 (baseline human labels): the tooling is built, and no label exists yet.** The
assessment and labeling commands are described under
[Human labels (B6)](#human-labels-b6). On Chad's go-ahead the assistant created the
assessment `b6-labels-1` (30 of the 50 cohort items; `docs/DECISIONS.md`). Only Chad labels
it, in his own terminal.

**B7 (judge and Phase A calibration): the tooling is built, and no judge run exists.** The
judge, qualification, calibration, example-pool and frozen-judge commands are described
under [Judge and calibration (B7)](#judge-and-calibration-b7). Chad chose the judge model
on November 24, 2026 ("use Llama 3.3 70B for the judge"). Every judge run waits for Chad's
frozen labels, his go-ahead and a reachable judge server, and B7's acceptance (at least
80% agreement in every dimension) is met only when the measured runs are done and the
calibration report says so.

What runs today: install, the offline tests, the documentation corpus rebuild, the section
index, the lexicons, the setup-fact checks, the rubric commands (`rubric check`,
`rubric show`) and the assessment and labeling commands. Steps 1 and 2 of the pipeline,
and the judge and calibration commands of steps 4 and 6, also run offline against fake
endpoints in the tests. Every other step below is marked *not yet
implemented* until its milestone lands.
Chad's decisions on the B2 setup records (packet SR-001) are applied: 38 accepted and fact
row SF-001 rejected. Setup review SR-003 (fact row SF-021) stays an MP1 item and is still
pending.

B3 history, kept as a record: Chad's November 22, 2026 decisions on the version pairings,
the IFC schemas, review packets and drafting were applied (see
[`docs/DECISIONS.md`](docs/DECISIONS.md)), and the gold-set tooling was built (slot plan,
lane batches, checker, review packets, import, publish, pattern score; see
[Gold set](#gold-set-b3)). Chad answered the gold-set count questions on November 22,
2026. All 110 items were drafted by assistant lanes; Chad imported his decisions on packets
GP-001 to GP-005 on November 22, 2026: 6 items accepted and 104 rejected, to be redrafted.
He delegated those reviews to an assistant reviewer and records the decisions as his own
([`docs/DECISIONS.md`](docs/DECISIONS.md)). The 6 accepted items are published in
`reference/gold/` (2 development, 4 held-out). Assistant lanes redrafted the 104 rejected
items under Chad's "Code wins, cited" rule. A further review revised 46 drafts and added
ordered, clause-scoped and affirmative matching; on November 23, 2026 Chad chose to fix two
scoring flaws before reviewing, so checker `gold-check-v4` tightens negation in affirmative
matching and lets answers explain a docs-versus-code difference, and 7 drafts were redrafted;
`gold-check-v5` then keeps the forbidden negation rule for the stale-docs guards and credits
a few correct phrasings again, with no draft changed. Chad then chose to stop patching
(November 23, 2026): `gold-check-v6` narrows the ", which" contrast, a scoring-only checker
change no longer makes packets stale, and pattern checks are reported as heuristics while
meaning is graded by Chad's blind labels and the LLM judge.
All 110 heads passed a complete-mode check with the fixture-slice rule. Before B3 was
withdrawn, the 104 redrafts were exported for Chad's decisions in replacement packets
GP-021 to GP-025; those packets are paused, unimported, and not reviewed for MP1. Older
packets remain as records. No new review decisions were imported.

| Milestone | What it delivers | Status |
| --- | --- | --- |
| B0 | Repository, licenses, decision log, porting map, packaging | Done |
| B1 | Pinned, hashed documentation snapshots; fixture slice | Done |
| B2 | Operator lexicons; setup profiles and cited fact table | Done (Chad's SR-001 decisions applied) |
| B3 | Gold set and multi-part and injection requests | Withdrawn from MP1 (moves to Mini Project 4); 6 of 110 items published and frozen; 104 drafts unreviewed |
| B4 | Section sampler, generation prompt v1, deterministic checks; generation, gate and collection modules ported | Done (no model run yet; the rubric moved to B5 on November 24, 2026) |
| B5 | Rubric (D1–D6) and baseline run | Done: rubric accepted by Chad ("Accept as drafted"); baseline `baseline-2026-11-24-r2` ready (70 of 70 valid initial attempts, 56 of 70 retained, at least 10 per category); cohort `baseline-b5-cohort-1` frozen; `collection-report` built (see `docs/DECISIONS.md`) |
| B6 | Baseline human labels | Tooling built (assessments, blind labeling, append-only ledger, frozen human reference). Assessment `b6-labels-1` created (30 items); no label entered yet |
| B7 | Judge and Phase A calibration | Tooling built: judge v1 prompt (SHA-256 pinned November 25, 2026) and config, bounded judge runs, qualification, calibration with TPR, TNR and intervals, v2 example pool, frozen judge, commands. Judge v2 not written; no judge run, agreement figure or calibration yet |
| B8 | Phase B correction | Not yet implemented |
| B9 | Analysis and charts | Not yet implemented |
| B10 | Submission set, pipeline replay demo, iteration log, demo video, coaching approval | Not yet implemented |

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
Bonsai source file is in the repository. The gold tests use clearly synthetic items in an
injected slot plan, built on real fixture-slice sections: every checker rule, the pattern
matcher, ingest, packet export and import (tampering, stale blocks, re-decisions, edits),
publish, the interactive-terminal gate on import and the held-out loading rule.
The B4 tests use clearly synthetic model outputs and fake transports: trace files and
no-overwrite rules, the seven-field schema, run config and credential rules (the hosted
refusal, the local-endpoint allowlist, key names and key length), the section sampler, the
model client (retries, timeouts, redaction, plain and JSON-escaped credential echo,
environment proxies ignored), generation (resume, exhaustion, unknown outcomes, transport
failures, unstorable responses, code and prompt identity), each deterministic check, the gate,
collections, cohorts and the generation commands with their exit codes. The B5 tests cover
the rubric (shape and course-criterion refusals, malformed files, the hash, the overall-pass
and relative-reduction rules, the command exit codes), its agreement with the B4 checks,
collection target and cohort size, the separate embedding endpoint and credential, the
exact Clopper-Pearson interval (reference values, the binomial-tail definition, edges and
impossible counts) and `collection-report` (figures and intervals on synthetic
collections, undefined rates, write-once, a locked or changed collection refused, exit
codes). The
B6 tests build synthetic collections and cohorts in a temporary directory. They label
only with scripted input, for a visibly synthetic reviewer and a synthetic test rubric, and
never under `runs/` or `data/`. They cover:
- decision values and unresolved decisions;
- reproducible, category-balanced and disjoint selections;
- the queue and key split, and display output that never contains the sentinel run,
  model, prompt, item or cohort ids;
- the rubric gate;
- the terminal check with no bypass;
- interrupted, truncated, edited and foreign ledgers, and leftover locks;
- corrections and the freeze preconditions.

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
any more, and its record is in `docs/DECISIONS.md`. The two add-on sources are read by the
operator lexicon and quoted by code citations. No whole Bonsai source file is committed,
because their headers carry contributors' contact addresses: only the cited line spans join
the fixture slice (below).

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

The fixture slice in `tests/fixtures/docs/` (34 Bonsai 0.9.0-post1 pages, 23 Bonsai
0.8.5-post1 pages, 29 Blender 5.2 Manual pages, 11 Blender 4.5 Manual pages, the license
texts and `fixtures.json`) covers every plan §5 category, every page a setup fact or gold draft cites and
the six Bonsai tutorials of each pin (`tutorials/project0.rst` to `project5.rst`, which gold
multi-part requests cite), so offline tests and the later replay demo need no network. Its pages link to pages outside the slice, so nothing
offline may require those links to resolve. The add-on sources contribute only the line
spans that gold items and fact rows cite (`fixture_code_spans` in the config; 138 at
0.9.0-post1 and 116 at 0.8.5-post1),
each written unmodified as `tests/fixtures/docs/<source>/<path>.L<first>-L<last>` with its
hashes in `fixtures.json`. `snapshot fixtures` refuses a span with any privacy match, and
`snapshot check` compares each span with the snapshot's lines.

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
| `docs search QUERY [--source ID] [--tag T] [--top N]` | BM25 over passages of the built index (a precursor of Mini Project 4's `search_docs`) | Never |
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
own Bonsai docs or Manual, so the 5.2 Manual does not stand in for `VL-older`, and a
line's `blender_manual` source must pin the `blender-v<release>-release` branch of the
line's own Blender release. Its `bonsai_docs` and `bonsai_source` must both pin the tag
`bonsai_tag`, and `bonsai_tag` must be the tag of the line's `bonsai` release, so swapped
Bonsai pins or both lines on one pin fail too. The
`ifc_schema` values are `partly cited`: SF-007 supports them for `new_project` only
(`cited_for`); for opened and federated models all three are a stated default that Chad
kept, and schema facts are scored only where a row cites them. The profiles are a
full IFC schema × model state factorial per line, with disciplines rotated as a Latin
square; the 6 diagonal profiles are the assessed split and the other 12 the development
split, and each split covers every schema, model state, discipline and version line.

`reference/setup-facts.json` holds 20 fact rows and 10 claims left out because no pinned
text supports them. Every row cites pinned sections with short verbatim quotes, and a row
may also cite pinned add-on code spans (`code_citations`, one quote each). A `doc_conflict`
row with code citations records a docs-versus-code conflict (the code wins, Chad, November
22, 2026): it cites, for every line it applies to, that line's own Bonsai docs and add-on
source, and it is never a line's pairing claim (SF-021);
`setup check` proves each quote occurs exactly once, on token boundaries and outside RST
comments, in the cited section, and that every key term is in a quote, on token boundaries
too. Whether a claim
says no more than its quotes is not machine-checked: every row, profile and version line
is `assistant_drafted` until Chad decides it in a review packet, and uncited rows cannot
exist.

### Chad's review of the setup drafts (begun at B3)

Chad reviews the version lines, profiles and fact rows through the same Markdown packets as
the gold items (about 25 records each), outside Git under `data/setup-review/`:

```bash
uv run --locked bonsai-help setup review export
uv run --locked bonsai-help setup review import SR-NNN   # Chad, interactive terminal only
uv run --locked bonsai-help setup review apply --write
```

| Command | Does | Writes |
| --- | --- | --- |
| `setup review export [--size 25] [--records ID ...]` | Packets `SR-NNN.md` of every record no decision settles, after the whole setup check passes. A block shows the record and what it rests on: a fact row's claim, key terms and the full text of every cited section with its quotes; a profile's values and the basis of each enum; a version line's releases, pins and the claims it lists. `--records` re-exports records for a re-decision, refused for one in a packet not yet imported | `data/setup-review/packets/` |
| `setup review import SR-NNN [--decided-on D] [--skip-stale]` | Record Chad's approve, edit or reject, all or nothing, append-only; interactive terminal and typed confirmation only. A changed fixed region is tampering; a record whose content, or anything its block shows, changed since export is stale; edits are checked together by the whole setup check. A fact row's edited citations are a record id and a verbatim quote, and the other fields are derived again | `data/setup-review/imports/` |
| `setup review apply [--write]` | Set every record's `status` and `review` (`decided_on`, Chad's word, decision id, content hash) from the imported decisions and write an edit's result; a record whose content changed since its decision returns to `assistant_drafted`. Compare (exit 1 on a difference) or write | `reference/setup-*.json` |

A review binds to the record's content (everything but its status and review), so
`setup check` reports a reviewed record whose content changed since the decision. NOTE text
stays in `data/setup-review/imports/`.

## Gold set (B3)

Withdrawn from MP1 on November 23, 2026; kept, frozen, as the seed for Mini Project 4's
relevance labels. The text below describes the tooling as built.

The gold set is 110 slots (Chad's decisions of November 22, 2026): 50 development and 25
held-out questions, 15 multi-part requests drawn from the Bonsai tutorials (10 development,
5 held-out), 10 injection cases and 10 benign controls beside them (both held out), five
categories at 20% within each kind and split, and held-out items only on the six assessed
profiles. A control is a harmless request that looks like an attack (an IFC property value
that mentions "ignore", a genuine pasted doc excerpt); the i-th control has the i-th
injection case's category, profile and vector. The chatbot must answer a control: the
security score reports attack success over the injection cases beside over-refusal over
the controls (a control answer that matches none of its required patterns counts as
over-refused). Each item has a question for one setup
profile, a reference answer drafted only from the pinned sections it cites, those sections
with verbatim quotes, optional code citations of the line's pinned add-on source, check
patterns (operator, panel, Blender operator, menu path, hotkey, UI label, phrase, `tokens`,
`any_of`, regex, planted text) and an optional unusual flag.

Patterns (`gold-check-v6`): `any_of` accepts any of 2 to 8 alternatives (a tool by id,
label, button text, menu route or hotkey; a phrase; tokens), and at least one alternative of
a required group must be tied to the sources (a phrase in its quote, tokens from its quotes,
or a tool named in a cited section); the rest may be paraphrases that Chad's review judges.
`tokens` (`green + new|added`, `remov* + default objects`) needs every entry, in any order,
within a `window` of one sentence. Word proximity alone does not prove a mapping.
Patterns and alternatives may opt into `ordered` (token entry order), `clause` (stay
inside one clause; a colon does not end one), and `affirmative` (reject a governing negation
of a positive claim: "does not A or B", "neither ... nor", "no longer", "does not mean you
will", a "? No," rebuttal, and descriptive negation such as "is not available", "does not
exist", "was removed" or a docs claim contrasted with "but" or with ", which" when the code,
docs or product is the negated subject (", which the pinned code no longer draws"); a
forbidden pattern keeps the forbidden negation rule, so an unrelated "Don't X and" does not
hide a stale instruction). The checker accepts `ordered` only on tokens and `clause` not
on tool kinds or on a phrase that crosses a clause. The packet displays these controls.
Negative claims keep their explicit negative wording and do not opt into affirmative
matching. These controls are heuristics, not a semantic proof. A forbidden rule can inspect any scored field, including `answer` or `any`, so
obsolete instructions cannot escape by moving out of `steps`; a forbidden tool or a pattern
supported by a `conflict` quote does so only when it is `affirmative` throughout, so an
answer that explains the stale docs does not count as following them. A forbidden
or planted pattern counts only an affirmative occurrence: "Do not remove the slab" is a
warning, not compliance (a deterministic clause-and-cue rule with documented limits; see
`gold_patterns`). Where the pinned docs and code disagree, the item follows the code, cites
the stale section with role `conflict` and the code span with a code citation, and carries
`unusual.reason: doc_conflict`; no required pattern may match or cite a conflict quote. A
hotkey that the add-on binds in code (not in the lexicons) resolves through a quoted
`bim.hotkey` keymap entry.

```bash
uv run --locked bonsai-help gold slots
uv run --locked bonsai-help gold check --committed
uv run --locked bonsai-help gold status
```

| Command | Does | Writes |
| --- | --- | --- |
| `gold slots [--write]` | Regenerate the slot plan from the targets, the profiles and `reference/gold/slot-substitutions.json`; compare (exit 1 on a difference) or write `reference/gold/slots.json` | `reference/gold/` |
| `gold ingest BATCH [--supersede-accepted]` | Validate a lane batch (`gold-draft-batch-v1`, lane form only), derive every citation field from the pinned pages, run the checks against the current drafts, then write the drafts and a receipt, or nothing | `data/gold/` |
| `gold check [--committed] [--complete] [--drafts]` | The slot plan and the published files: every check, with the fixture-slice rule; `--drafts` adds every draft head (it needs the data root, so not with `--committed`), `--complete` requires every slot published (the B3 acceptance check) | — |
| `gold status` | Per slot: head draft, check, decision state, published; counts against the targets, unusual reasons, leftover temp files, orphan drafts, a leftover lock, packets not yet imported and decided items whose setup changed since the decision (G22). Never shows NOTE text | — |
| `gold packet export --split S [--size 25] [--items ID ...]` | Write review packets of pending drafts that pass the check, about 25 per Markdown file, one split per packet; `--items` re-exports items for a re-decision, refused for a draft in a packet not yet imported | `data/gold/packets/` |
| `gold packet import GP-NNN [--decided-on D] [--skip-stale]` | Record Chad's decisions, all or nothing; runs only from an interactive terminal after a typed confirmation | `data/gold/` |
| `gold publish [--write]` | Build `reference/gold/development.json` and `held-out.json` from Chad's accepted and amended items; compare (exit 1) or write | `reference/gold/` |
| `gold score ANSWERS.jsonl` | Pattern scores of published development items, JSON lines; input lines are `{"item_id": ..., "fields": {...}}` with the scored payload fields | — |

How an item gets in:

1. A drafting lane writes a batch in the lane form (citations name a record id and
   quotes; no derived field) and runs `gold ingest`. A slot a lane cannot support from
   the pinned sections gets a recorded substitution or stays empty; it is never padded.
2. `gold packet export` writes `data/gold/packets/GP-NNN.md`. For each item Chad writes
   `approve`, `edit` or `reject` after `DECISION:` (blank stays pending), an optional
   one-line `NOTE:`, and for an edit changes the pre-filled JSON in place.
3. Chad runs `gold packet import GP-NNN`. A changed fixed region is refused and its first
   changed line named (line-end whitespace and CRLF do not count); a block whose draft,
   profile, version line or cited fact claims changed since export is stale
   (`--skip-stale` imports the rest); an edit runs the whole checker, and the packet's
   edits are checked together too. A packet is imported once; export its pending items
   again. A packet with obsolete review-checker (`gold.REVIEW_CHECKER`), source, index,
   slot or lexicon digests remains on disk but does not block a replacement export. A
   scoring-only checker change (`gold.CHECKER`) leaves packets current; the import still
   reruns the current check, and a draft that fails it is stale. Its stale decisions cannot settle a current review.
   A profile, version line or fact claim changed after a decision makes publish
   refuse the item until it is decided again with `--items`.
4. `gold publish --write` writes the reviewed items, which `gold check --committed`
   then proves offline against the fixture slice.

The checks (G01 to G26, in `src/bonsai_help/gold.py`) cover slot identity and splits;
every citation field and quote against the pinned bytes, code citations against the pinned
add-on source (G26); support references; the fixture
slice for published items; lexicon resolution and grounding of every named tool in a cited
section; backticked spans and `bim.*` ids (an id that exists only in the other version line
gets its own message); pattern shape and strictness (the reference must pass its patterns,
an echo of the question must not, and a pattern that matches most other categories'
references fails; the 10% regex share applies at `--complete` and to a set that fills every
slot, not to a partial publish); multi-part, injection and control rules (a genuine pasted excerpt must occur in a cited
section; another look-alike must carry a word an injection filter keys on); cited setup facts (a row Chad rejected
cannot back an item); duplicates and cross-split leakage; privacy; and packet markers. They
are heuristics that catch defects before Chad reads an item; the pattern score never
decides a rubric dimension. Meaning-level grading belongs to Chad's blind labels and the LLM
judge; pattern checks are reported as heuristics (Chad, November 23, 2026).

Held-out items are committed with the rest because the review record and the grader need
them, so anyone can read them. They are held out from development decisions, not secret:
they load only through `gold.load_held_out`, prompts and few-shot examples use development
items only, and `gold score` scores development items only. Chad reads held-out reference
answers when he reviews them; he labels chatbot answers blind to the arm (B6).

Layout outside Git, under `data/gold/`: `drafts/` (content-addressed), `ingests/`
(receipts), `packets/` (packets and manifests), `imports/` (decisions and NOTE text,
append-only), `.tmp/` and `.lock`. NOTE text never enters Git and publish never reads it.
The published files are CC BY-SA 4.0 data; quotes keep their source license (`NOTICE.md`).

## Generate and gate (B4)

Diagnostic smoke runs have been made. The first baseline collection was stopped, and the
restarted baseline `baseline-2026-11-24-r2` is ready (November 24, 2026;
`docs/DECISIONS.md`). No baseline failure rate exists yet: it needs B6's labels and B7's
judge. A model run needs a reachable local endpoint and Chad's go-ahead, and the offline
tests exercise the commands against fake endpoints only. Copy
`config/run.example.json` to `config/run.local.json` (git-ignored by the pattern
`config/*.local.json`; `config/run.json` would be tracked) or to a path outside the
repository, and fill in the endpoint (`base_url` ending in `/v1`, served model id,
timeout, attempts) and one credential source. The endpoint must be `localhost` or a
loopback, RFC 1918 or IPv6 unique local (fc00::/7) address; other addresses are refused.
`api_key_env` names an upper-case environment variable (default `BONSAI_HELP_API_KEY`),
or `api_key_file` names a key file. The key must be at least 16 characters; a local server
that ignores the key still needs a long random placeholder. Embeddings use `base_url`
unless `embedding_base_url` names a separate local embedding server (same rules: local
address, `/v1`, no credentials, query or fragment). The embedding server uses the chat
credential source unless `embedding_api_key_env` or `embedding_api_key_file` (at most one)
names its own. Run manifests record the embedding endpoint actually used and the kind of
its credential source (`shared`, `environment` or `file`), never a key, variable name or
path; resume refuses a change to either. `enable_thinking` (`true`, `false` or left out)
controls a thinking model's reasoning: left out (the default), nothing is added to a
request; `true` or `false` adds `"chat_template_kwargs": {"enable_thinking": ...}` to the
body of every chat request, never to an embedding request. The value must be a JSON
boolean (`"false"` or `0` is refused at load). It is part of the recorded settings, so
`generate --resume` and `collect --resume` refuse a changed value. The example config sets
it to `false` (Chad, November 24, 2026). The field is a server extension, not part of the
OpenAI API: the client sends it but does not check that the server honours it. Raw runs go under `runs/`
(git-ignored) or a path outside the repository. Run the commands from the repository
checkout: the code identity hashes every package module plus `pyproject.toml` and
`uv.lock` beside `src/`, and if either file is missing the command is refused before
anything is written ("cannot read uv.lock: missing; the implementation identity needs it
beside src/ (run from the repository checkout)", exit 2). The tool is not supported as an
installed wheel; the sampler likewise reads the committed `config/doc-manifest.json` of
the checkout.

```text
bonsai-help generate --config CONFIG --run-id RUN_ID [--count COUNT] [--resume]
                     [--fixtures-dir FIXTURES_DIR] [--reference-dir REFERENCE_DIR]
bonsai-help gate --config CONFIG --run-id RUN_ID
                 [--fixtures-dir FIXTURES_DIR] [--reference-dir REFERENCE_DIR]
bonsai-help collect --config CONFIG --collection-id COLLECTION_ID
                    [--target-retained TARGET_RETAINED] [--batch-count BATCH_COUNT]
                    [--max-batches MAX_BATCHES] [--resume]
                    [--fixtures-dir FIXTURES_DIR] [--reference-dir REFERENCE_DIR]
bonsai-help collection-status --collection-id COLLECTION_ID [--artifact-root ARTIFACT_ROOT]
bonsai-help collection-report --collection-id COLLECTION_ID [--report-id REPORT_ID]
                              [--artifact-root ARTIFACT_ROOT]
bonsai-help cohort --collection-id COLLECTION_ID --cohort-id COHORT_ID
                   [--artifact-root ARTIFACT_ROOT]
bonsai-help cohort-status --cohort-id COHORT_ID [--artifact-root ARTIFACT_ROOT]
```

Defaults: `--count` 5 (a multiple of 5), `--target-retained` 50, `--batch-count` 70,
`--max-batches` 3, fixtures `tests/fixtures/docs`, reference `reference`, artifact root
`runs`. `uv run --locked bonsai-help <command> --help` prints the full text.

`prompt_path` names the generator prompt. Any file that contains the `{category}`,
`{setup}` and `{sections}` placeholders is accepted, and each run records its SHA-256 and a
copy. Both measured arms use `prompts/generator-v1.1.md`: the baseline uses it as written,
and the corrected arm changes v1.1 by the one Phase B change pre-registered from the
heatmap. v1.1 differs from `prompts/generator-v1.md` only in asking for an answer of at
least 60 words, the gate's D1 minimum; v1's wording is otherwise kept. v1 is frozen, because recorded runs used it. The
field's default and `config/run.example.json` still name v1, so a baseline or corrected
config sets `prompt_path` itself.

| Command | What it does and writes |
| --- | --- |
| `generate` | Plans balanced slots, offers each slot pinned sections from the fixture slice, and calls the configured model once per slot (with bounded retries). Writes a new run: manifest, prompt copy, `starts.jsonl` (a durable start before each call), `attempts.jsonl` (every completion, valid or not, raw, with the model's `cited_section_ids` and `quotes` as returned), `items.jsonl` (schema-valid items in an envelope with the setup id, category, offered and cited sections, quotes, prompt version, model, `generated_at` timestamp and trace id). The model returns the seven-field item, `cited_section_ids` and 1 or more `quotes` (`section_id` and `text`, no other keys; a missing or empty list fails the schema); quotes are metadata and never enter the payload. The envelope keeps each quote's text as the model wrote it (the schema strips only surrounding whitespace) and resolves its `section_id` with the same single bracket normalization as a cited id. `generated_at` is the same text as the attempt's `completed_at`. A completion that cannot be kept as returned is a failed attempt that uses up that attempt (the slot retries within its budget), never an unknown outcome: `UnserializableResponse` (raw response not strict JSON; kept as text, as JSON with a safe `repr` for odd values, else its `repr`, else `<unrepresentable TYPE>`, so storing it never fails, even for a custom client's mapping that raises when read), `EnvelopeInvalid` (no valid envelope) or `CredentialEcho` (the response contains the configured key, plain or JSON-escaped; raw body kept redacted, a string that holds the key only in escaped form replaced whole by `[REDACTED: credential echo]`, item not kept). `--resume` keeps the original settings, prompt and code identity and verifies hashes, including the manifest's `prompt_sha256` and the run's `prompt.md` copy against the prompt the run is started or resumed with, each item's `generated_at` against its attempt, and each envelope's quotes against the attempt's quotes ("recorded quotes differ from the attempt's quotes", exit 1); it refuses a request start that follows a slot's successful completion. A gated run cannot be resumed. |
| `gate` | Runs the first-pass gate on a saved run: schema, deterministic checks, exact and near-duplicate removal, category balance. The quote check reads each item's offered sections again from the fixture slice (`--fixtures-dir`), verified against the offered page hash and the committed manifest; a changed page stops the gate with exit 1 and no report. Writes one file, `gate-report.json`, next to the run, once: each item's check results and drop reasons (`per_item`), `retained_ids`, `drops_per_check`, `pass_rates_per_check` (every check, the evidence-only ones too, over `pass_rates_denominator`, the schema-valid items entering the gate), exact and near duplicates, per-category counts and the distribution result, the embedding model, the embedding endpoint (`embedding_base_url`) and the threshold (0.92). Retained payloads are read from `items.jsonl` by `retained_ids`. Unknown Blender operators and menu paths are evidence only; the other checks drop, among them `quotes_verbatim` (D3, below). Checks are heuristics that drop obvious defects and feed the judge; they never replace a human or judge decision. A zero or non-finite embedding vector stops the gate with an error and no report; two schema-valid attempts for one slot or item ID are refused ("more than one successful attempt for slot ...; inspect the run"). |
| `collect` | Runs generate and gate in batches until enough items are retained (at least 10 per category) or the batch budget is spent. Each batch has its own derived seed, and retained items are screened for near-duplicates across batches; a question that exactly repeats an accepted member's is dropped. Batch run IDs `<collection-id>-b01` to `-bNN` belong to the collection: a fresh `collect` refuses (exit 2) if any of them within `--max-batches` already exists, and a batch run it does not own, or a gate report made with another embedding model, embedding endpoint, threshold, minimum share or lexicons, or whose per-item checks differ when rerun with the collection's lexicons and fixture slice (the quote check included), is refused (exit 1), never adopted. An assessed collection (`purpose` `baseline` or `corrected`) without `model_identity` and `model_sha256`, or a fixture slice that fails verification, is refused before anything is written. Batch denominators are recomputed from the hash-bound ledgers. A gate report made outside the collection is adopted only if its retention decisions re-derive from its per-item checks (retained flags, `dropped_by`, exact duplicates, `retained_ids`, per-category counts, the distribution result; near-duplicate drops stay trusted); otherwise "gate report decisions differ from its per-item checks; inspect it" (exit 1). A batch slot plan that is not a list of exact slot objects is "batch slot plan is malformed; inspect it" (exit 1). A cross-batch embedding that fails, or returns a zero or non-finite vector, stops the screen with exit 1 and leaves that batch unscreened for `--resume`. |
| `collection-status` | Reads a collection and reports its batches, retained counts per category and whether it is ready. |
| `collection-report` | Reads a collection with the same verification as `collection-status` (no generation, no gate, no endpoint) and writes one new file, `reports/<report-id>.json` under the artifact root (default ID `<collection-id>-report`; an existing file is refused with exit 2 and never replaced). It prints a short text summary: the three denominators below, each with its counts and an exact 95% Clopper-Pearson interval (`stats.clopper_pearson`), a rate with denominator 0 shown as undefined, never 0 or 1; exhausted slots and unknown outcomes (with their IDs in the file); gate drops per check (one item can fail several) and cross-batch drops; retained counts and shares per category; the collection's per-category minimum and each batch's gate share check; the frozen cohort, re-verified, if there is one; the collection ID and manifest SHA-256 it was made from; and the recorded hashes of the gate-freeze files (`checks.py`, `gate.py`, `sampler.py`) and the prompt. Only gated batches are counted. It never states a failure rate. Exit 0 for a ready collection, 1 for one that is not ready (the report is still written, with its status and reasons) or for evidence to inspect. |
| `cohort` | Freezes 10 retained items per category (seeded) from a ready collection into a new cohort. The collection's freeze receipt (`frozen.json`) is written before `cohort.json`, so a failed cohort write leaves a frozen collection with a missing cohort to inspect and never lets the collection freeze a second cohort. |
| `cohort-status` | Reads a frozen cohort and verifies its hashes. |

The deterministic checks, by dimension (all drop an item except the two marked evidence only):

| Dimension | Check | Fails when |
| --- | --- | --- |
| D1 | `answer_length` | the answer has fewer than 60 words |
| D2 | `safety_length`, `safety_not_generic` | `safety_info` is under 80 characters, or is little more than stock phrases |
| D3 | `bim_operators_known` | a `bim.*` id in `tools_required` or `steps` is not a registered operator or macro of the line's Bonsai source |
| D3 | `cited_sections_offered` | a cited id names a section that was not offered |
| D3 | `quotes_verbatim` | a quote names a section the item does not cite (offered or not), has fewer than 5 words, or does not occur in that section's offered text, compared after Unicode NFC with every whitespace run collapsed to one space, starting and ending on word boundaries; the detail names each failing quote by index and reason, never its text |
| D3 | `blender_operators_known` (evidence only) | an operator id is not in the line's Manual lexicon |
| D3 | `menu_paths_known` (evidence only) | a menu-path part is not a pinned UI label |
| D4 | `no_refusal` | the answer, safety text or tips carry refusal boilerplate |
| D5 | `question_length`, `problem_length` | the question has fewer than 6 words, or `equipment_problem` fewer than 3 |
| D6 | `tip_length`, `tip_not_generic`, `tip_not_step_copy` | a tip is under 30 characters, generic, or a near-copy of a step |

The two evidence-only checks read the version line's pinned lexicons.
`menu_paths_known` matches each part of a path against whole UI labels: the Manual's menu
paths, `:guilabel:` texts and per-operator labels (such as "Cube" for
`mesh.primitive_cube_add`), the Bonsai docs' UI paths and the Bonsai source labels and
button texts. Only the word just before the first label is checked: it must be lowercase
prose or, when it is the step's first word, one of a short list of lead-in words (Open, Go,
Click, Select, Use, Press, Navigate, Then, Now, Finally, Using, Access, In, From, Under and a
few more; `checks.LEAD_IN_WORDS`) or any word ending in a comma or colon ("Finally, File >
Export."). A two-word lead-in from that list (Right click, Double click) may open the step
the same way. So "Fabricated Settings > Export." and "Finally, Bogus File > Export." are
flagged while "Open Object > Apply > Scale." and "In Object Mode, open Object > Apply >
Scale." pass. `blender_operators_known` accepts an id the Manual
lists, or one that fits a Manual wildcard entry where each `*` stands for one or more whole
underscore-separated words, never the empty string (`object.*clear` accepts
`object.rotation_clear` but not `object.clear`).

Runs, gate reports, collections and cohorts are never overwritten; a new experiment gets
a new ID. Every ledger write is an fsynced append followed by an atomic manifest checkpoint
that records the ledger hashes. A hard kill (SIGKILL, power loss) between the two, or in
the middle of an append, leaves a run that resume refuses: first for the leftover
`.generation.lock` ("lock .generation.lock present: a writer is active; inspect", exit 1),
then for the ledger (exit 1). A kill between an append and its checkpoint, or one that cuts
off only an append's final newline, gives "changed or missing <ledger>; preserve the run
for inspection"; a cut inside the record gives "invalid JSONL record at <file>:<n>;
preserve and inspect it". A kill before a new run's first manifest leaves a directory that
resume does not find and a new run with that ID cannot reuse (exit 2). If the
"interrupted" checkpoint after Ctrl-C or an error itself fails, resume refuses the run
only when a ledger append came before it without its checkpoint; otherwise the manifest
still holds the right hashes and the run resumes. Inspect a refused run and choose a new
run ID; nothing repairs it (details in `docs/DECISIONS.md`, B4 cleanup).

Exit codes: 0 done; 1 a check failed or the evidence is not ready (including saved run
evidence that fails validation, and a missing or unreadable committed `doc-manifest.json`,
which is a fixture error); 2 usage or config error (including `hosted: true`); 3
controlled exhaustion (attempt or batch budget spent, or an unfinished run); 130
interrupted (Ctrl-C), with the evidence kept: continue with `--resume`. If the run's
"interrupted" checkpoint also failed, the error line shows that failure instead of the
resume advice: inspect the run, since resume may refuse it. Any error line ends with the
notes the exception carries.

Three denominators are reported separately and never mixed:

- **Initial-attempt schema validity**: valid initial responses over all initial slots. The
  95% structural target is judged on this figure.
- **Retry recovery**: schema-valid results that came from a retry (attempt 2 or later),
  counted apart from the initial figure and never added to it. `collection-report` gives
  it as a rate over the slots without a schema-valid first attempt.
- **Gate retention**: items retained by the gate over the schema-valid items that entered
  it. Retained items are never compared against filtered ones.

## Rubric (B5)

`config/rubric.json` (version `bonsai-rubric-v1`) holds the labeling rules, the six
dimensions in course order with their course names, a pass and a fail anchor for each
(from plan §6.2, with §6.3 for D2), labeling notes (what to check, common fail patterns,
borderline rulings), each dimension's pass-rate minimum (D1 0.85, D2 0.90, D3 0.95,
D4 0.95, D5 0.90, D6 0.85), the overall-pass rule (all six; one fail fails the item, and
otherwise a missing decision is unresolved, never a pass) and the course thresholds. Chad
accepted it as drafted on November 24, 2026 ("Accept as drafted"; `docs/DECISIONS.md`),
so its status is `chad_accepted`. Only a dated entry in `docs/DECISIONS.md` in his words
can set that status, and any later change is a new rubric version. A threshold that
differs from the course value, stricter or weaker, is refused: a change needs a dated
amendment, a new rubric version and a code change. Every B6 assessment and label pins the
rubric's version and hash.

```text
bonsai-help rubric check [--rubric RUBRIC]
bonsai-help rubric show [--rubric RUBRIC]
```

| Command | What it does |
| --- | --- |
| `rubric check` | Validates the rubric and prints its version, status and sha256 (of the validated content, so reformatting the file keeps it) |
| `rubric show` | Prints the labeling rules, each dimension's anchors, notes and minimum, and the thresholds |

`--rubric` defaults to `config/rubric.json`. Exit codes: 0 valid (with a warning on stderr
while the status is `assistant_drafted`); 1 the rubric fails its check (malformed JSON, a
shape error or a departure from the course criteria); 2 a missing or unreadable file, or a
usage error. Errors name only the file, never its absolute path.

The baseline run procedure and what B5 cannot measure yet are in
`docs/superpowers/plans/2026-11-24-b5-rubric-and-baseline.md`. The overall failure rate
needs Chad's labels (B6) and the judge (B7); it is never estimated from the gate.

## Human labels (B6)

The tooling is built. On Chad's go-ahead the assistant created assessment `b6-labels-1`
(30 of the 50 cohort items); no label has been entered. The
plan is `docs/superpowers/plans/2026-11-24-b6-labels.md`, and the assistant's calls are in
`docs/DECISIONS.md` (November 24, 2026: B6 labeling tooling).

```text
bonsai-help assessment create [--artifact-root ARTIFACT_ROOT]
                              --assessment-id ASSESSMENT_ID --cohort COHORT
                              --count COUNT --seed SEED
                              [--exclude-assessment EXCLUDE_ASSESSMENT]
                              [--rubric RUBRIC]
bonsai-help assessment status [--artifact-root ARTIFACT_ROOT]
                              --assessment-id ASSESSMENT_ID
bonsai-help label [--artifact-root ARTIFACT_ROOT] --assessment-id ASSESSMENT_ID
                  --reviewer REVIEWER [--amend L-NNN] [--supersedes LABEL_ID]
bonsai-help label-status [--artifact-root ARTIFACT_ROOT]
                         --assessment-id ASSESSMENT_ID
bonsai-help freeze-human-reference [--artifact-root ARTIFACT_ROOT]
                                   --assessment-id ASSESSMENT_ID
                                   --reviewer REVIEWER [--declare-blind]
```

`--cohort` and `--exclude-assessment` may be repeated: one cohort per arm, and any number
of earlier assessments whose items are left out. `--count` is items per cohort, a multiple
of 5. `--artifact-root` defaults to `runs`; it must be `runs/` or a path outside the
repository. `uv run --locked bonsai-help <command> --help` prints the full text.

| Command | What it does and writes |
| --- | --- |
| `assessment create` | Selects `--count` items from each frozen cohort and seals a new assessment under `<artifact root>/assessments/<id>/`. The selection is seeded, takes `count / 5` per category and refuses a shortfall. It writes `queue.json` (what the labeler sees), `key.json` (blind id to run, item and arm), a copy of the rubric and `manifest.json`, each once. It refuses unless the rubric is `chad_accepted`. It writes no label |
| `assessment status` | Re-verifies the assessment against its cohorts. Reports blind totals, the rubric pin, whether the current rubric still matches it, and the ledger's state |
| `label` | Chad's interactive labeling session (below) |
| `label-status` | Blind progress: selected, completed, pending blind ids, effective label ids, unresolved decisions, and the ledger state. It never writes |
| `freeze-human-reference` | Chad's interactive freeze. It writes `human-reference.json` once, the frozen input of B7's Phase A calibration |

The labeling rules:

- **Only Chad labels.** `label` and `freeze-human-reference` record the reviewer's own
  decisions. They refuse (exit 2) unless stdin and stdout are both terminals, before
  anything is shown, and no flag or environment variable bypasses that check. Each session
  starts with a typed confirmation, `label <assessment-id>` or `freeze <assessment-id>`.
  An assistant never runs either command, interactively or through a pseudo-terminal. An
  assistant never enters, edits or imports a label.
- **Rubric gate.** Labeling refuses before showing anything if the assessment's rubric
  copy differs from its pin or is not `chad_accepted`. It also refuses if the
  repository's `config/rubric.json` has changed since the assessment was created ("rubric
  changed since the assessment was created; create a new assessment").
- **Blind display.** Each item appears under an opaque blind id (`L-001`, ...), in one
  seeded, shuffled order. The display shows the item's seven fields, its category, its
  setup record (Blender and Bonsai versions, IFC schema, discipline, model state), the
  model's quotes and the full text of each cited section. It never shows the run id, item
  id, arm, prompt variant, model, generation time, collection or cohort id, gate results,
  judge output or other labels. The labeling code never reads `key.json`. Control
  characters in model or section text are shown escaped. Status commands print totals and
  blind ids, never a count per arm.
- **Decisions.** For each dimension D1 to D6, enter `0`, `1`, `u` (unresolved), `?` (the
  dimension's labeling notes) or `q` (quit). There is no skip. After six answers the
  summary is shown, then an optional note, then `save? [y/redo/q]`. Nothing is written
  until `y`, and quitting mid-item writes nothing.
- **Unresolved.** An unresolved decision is recorded and reported. It is never a pass,
  and the item stays in every denominator.
- **What a label carries.** The trace id, a UTC timestamp, the pinned rubric version and
  SHA-256, the assessment's hash and the decisions. Notes stay in the local ledger and
  never enter Git.
- **Append-only.** Labels go to a hash-chained `labels.jsonl` with a checkpoint written
  after each append, under an exclusive lock. To correct a label, run
  `label --amend L-NNN --supersedes LABEL_ID`: it adds a new label that names the label
  it supersedes, and the earlier label stays. An interrupted write, an edited, truncated
  or foreign ledger, or a leftover lock makes `label`, `label-status` and the freeze
  refuse with "preserve and inspect". Nothing is repaired or deleted.
- **Freeze.** `freeze-human-reference --declare-blind` needs a blind label by the
  declaring reviewer for every selected item. It also needs at least 20 labeled items
  per arm (the rubric's minimum), an unchanged rubric, and no judge evidence under the
  assessment. Unresolved decisions do not block it; they are counted in the reference.
  Corrections after the freeze are `post_review` and never change the frozen reference.

Procedure (Chad's answers of November 24, 2026 in `docs/DECISIONS.md`):

1. On Chad's go-ahead, the assistant runs `assessment create --cohort baseline-b5-cohort-1
   --count 30 --seed <seed>` under a neutral assessment id. It reports only the blind
   summary. That leaves 20 unselected cohort items for B8.
2. Chad runs `bonsai-help label --assessment-id <id> --reviewer <name>` in his own
   terminal. Quitting and resuming is safe, and `label-status` shows progress.
3. When `label-status` reports `complete`, Chad runs `freeze-human-reference
   --assessment-id <id> --reviewer <name> --declare-blind`.

B8 uses the same commands for one mixed assessment: the corrected cohort plus baseline
items that B6 did not select (`--exclude-assessment <B6 id>`). Give a mixed assessment a
neutral id (`b8-blind-1`, not `corrected-...`), because Chad types it. Chad chose B8's
mixed-queue baseline labels as the baseline figure for the improvement ratio; B6's labels
serve Phase A calibration.

Exit codes: 0 done, or labeling complete. 1 a refused state: a rubric not accepted or
changed, a ledger that is not intact or is locked, an incomplete selection, an unmet
freeze precondition or an unmatched confirmation, or changed evidence; an existing
assessment id is also 1. 2 a usage or configuration error, including a stdin or stdout
that is not a terminal. 130 interrupted: run `label-status` and inspect before
continuing. Errors are one line on stderr without absolute paths.

## Judge and calibration (B7)

The tooling is built and runs offline against fake endpoints. No judge run, agreement
figure or calibration exists: the measured runs need Chad's frozen labels, his go-ahead
and a judge server that is already reachable. The plan is
`docs/superpowers/plans/2026-11-24-b7-judge.md`, Chad's judge decision ("use Llama 3.3 70B
for the judge") and the assistant's calls are in `docs/DECISIONS.md` (November 24, 2026:
judge model; B7 judge), and the open questions for Chad are listed there. Chad answered
the judge temperature, the judge's inputs and the three adaptations on November 25, 2026,
and judge v1's SHA-256 is now pinned by `test_judge_v1_hash_is_pinned`.

The judge is MP1's Step 4: a separate prompt (`prompts/judge-v1.md`; `judge-v2.md` is
written later from development disagreements) at a lower temperature than every generator
collection it judges, with Instructor/Pydantic output of six binary decisions, each with a
reason. Its config is a `judge_config.JudgeConfig` file. `config/judge.example.json` shows
the shape with placeholder model ids; the real config, with `model_identity` and
`model_sha256`, is `config/judge.local.json` (git-ignored), and the judge model's file name
and hash never enter Git.

```text
bonsai-help judge [-h] --config CONFIG [--artifact-root ARTIFACT_ROOT]
                  --assessment-id ASSESSMENT_ID --judge-run-id JUDGE_RUN_ID
                  [--qualification ID] [--examples POOL_ID]
                  [--frozen-judge SELECTION_ID] [--resume]
bonsai-help judge-status [-h] [--artifact-root ARTIFACT_ROOT]
                         --assessment-id ASSESSMENT_ID --judge-run-id JUDGE_RUN_ID
bonsai-help judge-qualify [-h] --config CONFIG [--artifact-root ARTIFACT_ROOT]
                          --smoke-assessment-id SMOKE_ASSESSMENT_ID
                          --smoke-judge-run-id SMOKE_JUDGE_RUN_ID
                          --qualification-id QUALIFICATION_ID
bonsai-help judge-examples [-h] --config CONFIG [--artifact-root ARTIFACT_ROOT]
                           --assessment-id ASSESSMENT_ID --judge-run-id JUDGE_RUN_ID
                           --pool-id POOL_ID
bonsai-help calibrate [-h] [--artifact-root ARTIFACT_ROOT]
                      --assessment-id ASSESSMENT_ID --judge-run-id JUDGE_RUN_ID
                      --report-id REPORT_ID
bonsai-help judge-freeze [-h] [--artifact-root ARTIFACT_ROOT]
                         --assessment-id ASSESSMENT_ID --report-id REPORT_ID
                         --selection-id SELECTION_ID
```

The options of `judge`, as `--help` prints them:

```text
  --config CONFIG       judge config (JSON, git-ignored)
  --artifact-root ARTIFACT_ROOT
                        artifact root; must equal the config's artifact_root
                        (default: the config's artifact_root)
  --assessment-id ASSESSMENT_ID
  --judge-run-id JUDGE_RUN_ID
  --qualification ID    the judge's qualification receipt (measured)
  --examples POOL_ID    judge v2: the development example pool
  --frozen-judge SELECTION_ID
                        the judge-freeze selection this measured run must
                        match exactly
  --resume              continue an unfinished judge run
```

**`--artifact-root`.** `judge`, `judge-qualify` and `judge-examples` take a `--config`, and
for them `--artifact-root` defaults to the config's `artifact_root`. A different
`--artifact-root` is refused (exit 2), because the config's `artifact_root` is part of the
run identity. `judge-status`, `calibrate` and `judge-freeze` have no config and default to
`runs`, as the B6 commands do. Either way the root must be `runs/` or a path outside the
repository. `uv run --locked bonsai-help <command> --help` prints the full text.

| Command | What it does and writes |
| --- | --- |
| `judge` | Runs or resumes one judge run under `<assessment>/judges/<judge_run_id>/` (manifest, prompt copy, start and attempt ledgers, and for v2 `examples.json`). A `measured` run needs a frozen human reference and a valid qualification receipt, both checked before any directory is created or any call is made. A `smoke` run is refused on an `arm` assessment. `--examples` (v2) selects each item's examples by similarity before any chat call. `--frozen-judge` must match a `judge-freeze` selection exactly. Prints the run's blind status |
| `judge-status` | Verifies a judge run and prints its blind status: counts, unknown-outcome attempt ids, unresolved blind ids and reported model ids, never a decision, a reason or an item id |
| `judge-qualify` | Writes a qualification receipt once to `<artifact root>/judge-qualifications/<id>.json`, with a complete smoke run of the same model and settings as evidence. It makes no model call, and its printed summary leaves out `model_identity` and `model_sha256` |
| `judge-examples` | Builds judge v2's example pool once, `<artifact root>/judge-examples/<pool_id>/pool.json`, from a development assessment's disagreements with a complete measured v1 run. It calls only the embedding endpoint. An `arm` assessment is refused |
| `calibrate` | Writes a calibration report once as two files under `<assessment>/calibration/`: `<report_id>.json` (status, reasons, pins and the aggregate figures) and `<report_id>.disagreements.json` (the per-item disagreements). Prints only the aggregate figures, with the status on the first line |
| `judge-freeze` | Freezes the judge of a `ready` report into `<artifact root>/judge-selections/<id>.json`, for B8's `--frozen-judge`. It freezes only the report the pre-registered rule chooses (`calibration.preregistered_choice`: once `judge-v1` and `judge-v2` have each been measured once on the assessment and each has a calibration report, v2 if its report is `ready`, else v1 if its report is `ready`), and at most one selection per assessment. A measured run of any other prompt version on the assessment (a `judge-v3` or `judge-v1.1`) is refused: it needs Chad's dated decision and a new rule |

The judge rules:

- **Blind inputs.** The judge sees what Chad's display shows (the item's category, setup
  record, seven fields, the model's quotes and the full text of its cited sections) plus
  the deterministic check results the gate recorded for the item. It never sees a run,
  item or trace id, an arm, a prompt variant, a generator model, a collection or cohort id,
  a human label or note, or another judge's output. Item, quote, section and check text
  sits in blocks fenced by a code derived from the item's own text, so item text cannot
  forge a boundary.
- **No judge evidence before frozen labels.** A measured run refuses an assessment whose
  human reference is not frozen. A smoke run is allowed only on a development assessment
  that will never be labeled, and once it exists B6's freeze refuses that assessment.
- **Distinct judge.** A measured run refuses a judge whose `model`, `model_identity` or
  `model_sha256` equals a source generator's, and a judge temperature that is not below
  every source generator's recorded temperature. A reply that reports another model id is
  a failed attempt and blocks calibration.
- **Attempts.** A durable start record comes before each call, and every completion is kept
  raw, including malformed output, schema-invalid output and transport failures. A start
  with no completion is an unknown outcome: it uses up its attempt and is disclosed. Each
  item gets at most `max_attempts` (default 2, at most 3); a resume keeps the original
  settings, prompt, examples, code and reference and gives an exhausted item no more. An
  assessment allows at most 3 measured judge runs.
- **Agreement.** Per dimension, `matching / n` over every selected blind id. An unresolved
  human decision or a missing judge decision stays in `n` and never matches. A dimension
  meets the rubric's minimum (0.8) when `matching / n >= 0.8`, compared exactly (24 of 30
  meets it, 23 of 30 does not). Agreement, TPR and TNR each carry a 95% Clopper-Pearson
  interval, and a zero denominator is undefined, never 0 or 1.
- **Report status.** `ready` only on an `arm` assessment with a frozen, verified
  reference, a complete measured run, a valid qualification, every reply from the
  configured model, a judge temperature below every generator's, the reference's rubric pin
  and every dimension at or above the minimum. Otherwise `pending`, with every reason
  listed. A development assessment, a smoke run or a same-model judge gives `diagnostic`,
  whatever its agreement: diagnostic agreement never counts as calibration.
- **Development and assessed stay apart.** Judge v2's examples come only from
  development-split disagreements. Whoever writes a later judge prompt reads only the main
  report of an `arm` assessment, never its disagreements file.
- **Frozen judge.** `judge-freeze` pins the judge's settings, prompt, example pool, the
  modules on its render path, the libraries that build its request and parse its reply,
  and its response schema. A `--frozen-judge` run must match all of them. The code
  enforces the pre-registered selection rule: it refuses before v1 and v2 have each been
  measured once with a report, when a prompt version was measured twice, for any report
  other than the rule's choice, and for a second selection on the same assessment.

Exit codes: 0 done, a complete judge run, a `ready` report, or a `diagnostic` report
(`calibrate` then prints `status: diagnostic (never calibration)` first; on a development
assessment or a smoke run that is the planned outcome, not a refusal). 1 a refused or
pending state: an unfrozen reference, a spent judge-run budget, changed evidence, a
qualification mismatch, a `pending` report (still written), a freeze of a report that is
not `ready` or not the pre-registered rule's choice, a second selection for an assessment,
a lock, or an existing id. 2 a usage or configuration error, including a bad
judge prompt and an `--artifact-root` that differs from the config's. 3 controlled
exhaustion: the judge run is `incomplete` (`judge-status` exits 3 too). 130 interrupted:
run `judge-status`, then `judge --resume`. Errors are one line on stderr with absolute paths
redacted and every credential value read scrubbed.

Procedure (the plan's order of operations; Chad's steps are his alone, and every model run
needs his go-ahead and a reachable server):

1. Chad labels the B6 assessment `b6-labels-1` and freezes it
   (`freeze-human-reference --declare-blind`). Nothing judges it before then.
2. Chad serves the judge model locally and writes `config/judge.local.json` from
   `config/judge.example.json`.
3. On Chad's go-ahead, a development collection with the baseline's generator settings on
   the `development` split, then a 50-item development cohort.
4. On Chad's go-ahead, a 5-item development assessment and a `smoke` judge run on it
   (diagnostic only).
5. `judge-qualify` with the smoke run as evidence (no model call).
6. A 20-item development assessment, which Chad labels and freezes.
7. On Chad's go-ahead, judge v1 (`measured`) on the development assessment, then
   `calibrate`, which gives a `diagnostic` report.
8. `judge-examples` on that run (embedding server only).
9. Judge v2 is written from the development disagreements and pre-registered in
   `docs/DECISIONS.md` (prompt and pool SHA-256, `examples_k`, the selection rule) before
   any judge result on the baseline reference is read.
10. On Chad's go-ahead, judge v1 and then v2 once each on `b6-labels-1`, then `calibrate`
    for each.
11. `judge-freeze` on the report the pre-registered rule chooses (v2 if `ready`, else v1 if
    `ready`). If neither is `ready`, Phase A is not met, no judge is frozen, and Chad
    decides the next step.

## Run each step

Each step runs on its own against saved artifacts. Steps 1 and 2 exist (B4), step 3's
tooling exists (B6), and the tooling of step 4 and of step 6's Phase A exists (B7); the
rest are not yet implemented (B8, B9):

1. Generate: one prompt per category and setup profile writes each item from pinned doc sections (B4, B5, B8). Implemented.
2. First-pass gate: schema, deterministic checks, duplicates, category balance (B4, B5). Implemented.
3. Human labels: blind, resumable labeling against the pinned rubric (B6). Tooling implemented; no label entered yet.
4. Judge: independent prompt at a lower temperature than the generator (B7). Tooling implemented; no judge run yet.
5. Analyze: pass rates, agreement, intervals and five charts (B9).
6. Iterate: Phase A judge calibration, Phase B generator correction (B7, B8). Phase A tooling implemented; no calibration yet.

A model is configured explicitly as a local OpenAI-compatible endpoint. The hosted path
for graders without local models is refused for now (Chad, November 24, 2026): a run
config with `hosted: true` fails at load with exit 2, before any request, until Chad
authorizes a hosted path with an enforced cost cap. The fields `hosted`,
`hosted_authorization` and `cost_cap_usd` are kept only so the schema stays stable. A
hosted model is never used as a silent fallback.

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
│   ├── rubric.json       D1–D6 anchors, labeling notes and thresholds (accepted by Chad)
│   ├── run.example.json  example run config (local endpoints)
│   ├── judge.example.json  example judge config (local endpoint, placeholder model ids)
│   └── doc-manifest.json page hashes of every snapshot (written by the tool)
├── reference/
│   ├── docs-index.json   digest of the section index (written by the tool)
│   ├── lexicons/         operator, menu and hotkey lexicons (written by the tool)
│   ├── setup-profiles.json  version lines and setup profiles (assistant-drafted)
│   ├── setup-facts.json  cited setup-fact rows (assistant-drafted)
│   └── gold/             gold slot plan and, once reviewed, the published gold items (written by the tool)
├── docs/
│   ├── DECISIONS.md     dated owner decisions and open items
│   └── PORTING-MAP.md   what is ported from the earlier repository, and when
├── src/bonsai_help/     the package: snapshots, section index, lexicons, setup checks, gold set, generation, gate, rubric, assessments, labels, judge, calibration, CLI
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
