# Decision log

Dated record of owner decisions for this repository. The owner is Chad Josewski. His
words are quoted where they were given. Decisions are owner-reported: no outside
approval is implied. Open items keep the plan's default, stated as a default, until
Chad decides them.

The plan is `docs/MP1-BONSAI-HELP-CHATBOT.md` ("proposed plan, not started"). Its
section numbers (§) and open-item IDs (O-1 to O-8) are used below. The plan changes
only on Chad's direction; each change, and any later decision that departs from it, is
recorded here.

## November 21, 2026

### Revit round superseded; work starts at B0

Chad: "stash the Revit work and start B0". B0 is the first milestone of his document
`MP1-BONSAI-HELP-CHATBOT.md`, whose own status line reads "proposed plan, not started";
that line is his and is not changed here. The earlier Revit round is superseded, and its
work is not part of this repository.

### O-1: licenses (decided)

- Code: "GPL-3.0-or-later (plan default)". The full GPL v3 text is in `LICENSE`.
- Generated datasets: CC BY-SA 4.0 (plan default).
- Bonsai documentation fixtures and the operator lexicon derived from Bonsai source keep
  their own license, GPL-3.0-or-later.
- Blender Manual fixtures keep their own license, CC BY-SA 4.0.

### O-4: clean repository (decided, resolved by this repository)

Chad first chose "Rewrite and force-push". He then said "The other option is to create
a new clean repo and start over" and chose "New repo; old goes private".

- This repository, `mp1-bonsai-help-chatbot`, is the new public repository
  (`github.com/cjosewski/mp1-bonsai-help-chatbot`) and starts from a clean first commit.
- The earlier repository, `aia-mp1-synthetic-data`, becomes private again with its
  history intact, so its evidence commit hashes stay valid. No history is rewritten.
- O-4 is resolved by the new repository.

### O-5: submission set in Git (decided)

Chad: "Yes, submission/ only (plan default)". The curated submission set is committed
under `submission/`. Raw attempt logs, scratch runs and all earlier evidence from the
previous repository stay outside Git.

### Licensing stance

Chad: "I'm not really worried about the licensing. This isn't a product, it's an
assignment, and a portfolio piece. It will never be commercially distributed."

- The two licensing questions the assistant raised for B10 (the license of other
  `submission/` content, and GPL Bonsai text inside CC BY-SA datasets) are closed. They
  do not gate any milestone.
- The O-1 licenses stay as declared, and sources stay attributed (IfcOpenShell
  contributors, Blender Documentation Team). Attribution is cheap and the plan already
  includes it; no further license analysis is required.

### Hosted judge may receive doc excerpts

Chad, on the earlier repository's rule against sending source excerpts to hosted services:
"I think that rule was wrong from the beginning and changing the project takes care of the
licensing issues entirely."

- That rule is not carried into this repository. A hosted judge may receive the cited
  Bonsai and Blender Manual sections (plan §7 Step 4).
- Unchanged: a hosted path is explicit, documented, authorized by Chad and cost-capped
  (plan §8); there is no silent hosted fallback; human ratings are never sent to a hosted
  service.

### Repository name

Chad chose `mp1-bonsai-help-chatbot`.

### Plan edits for the public repository

Before the plan's first commit here, Chad directed these edits: "trim the NAS path and
Drive mentions", "update line 204 too", "update §8 and the O-4 row too" and "update those
references too".

- §3: private storage locations for course material are replaced by "Course materials"
  or "Portal links".
- §8 "Repository": the project is built in this repository and the pipeline modules are
  ported at B4 (see `PORTING-MAP.md`). The bullets now record O-4 as resolved, this
  repository's `AGENTS.md` and the O-5 decision.
- §11: the O-4 row is marked resolved by the new repository.
- References that only worked in the owner's private workspace (private planning IDs, the
  private tracking issue and schedule file, and capstone addendum IDs) are replaced by
  plain descriptions.

The rest of the plan is unchanged.

## Assistant's calls (not owner decisions)

These were made by the assistant during B0 and are open to Chad's review.

- **B0 scope.** The earlier pipeline modules are not copied in B0, because they are
  tightly coupled to the earlier domains. B4 ports them module by module, with tests,
  following `docs/PORTING-MAP.md`. The plan's B4 criterion "existing suite still passes"
  therefore becomes "each ported module arrives with its tests passing".
- **Python floor.** `pyproject.toml` requires Python 3.12 or newer, the version the
  earlier code was verified on. This is narrower than the plan's "Python 3.10+" (§1).
  The floor may be lowered only after the ported tests pass on 3.10.
- **Human label notes stay out of `submission/`.** Labels in `submission/` carry the
  decisions and IDs only; free-text reviewer notes stay outside Git.

## November 22, 2026

### Assistant's calls during B1 (not owner decisions)

These were made by the assistant while building the B1 snapshots and are open to
Chad's review.

- **Manual scope: every page.** The Manual snapshot keeps all 2,450 reStructuredText
  pages under `manual/`, not a subset. The 484 pages in the areas plan §2 and §5 name
  (interface, 3D viewport, outliner, preferences, properties editor, scene layout, mesh
  modeling, modifiers, files, getting started, troubleshooting, glossary) are tagged
  `core`, the rest `other`. The B2 Manual lexicon needs full coverage, or a real menu
  from an uncovered area would be flagged as invented. The `core` list is the
  assistant's reading of the plan and can follow O-2 without a new snapshot.
- **Snapshot identity covers only what selects the bytes.** A pin id is per source
  and hashes the URL, commit, root, include and exclude rules and license evidence.
  Retrieval tags, deny lists, attribution and notes are metadata, so editing them
  changes no pin id or source digest and later citations stay valid. B2's operator
  source on the same IfcOpenShell pin leaves the B1 ids unchanged.
- **Section records move to B2.** Cutting pages at headings (plan §4 row 1) is done by
  B2's `docs_index`. The B1 acceptance is about pages; section ids depend on the
  heading parser, and they can be recomputed from the verified page bytes.
- **Tag `bonsai-0.9.0post1` is a lightweight tag.** It points straight at commit
  `2744f842`, so the config records `tag_object: null`; annotated tags are also
  supported.
- **Ref drift.** When a pin is first written (`--write-manifest`), a tag that does not
  point at the pinned commit stops the build (exit 4). A plain rebuild only warns and
  records the observation, as for a moved branch, because the commit pin governs and
  the one-command rebuild should keep working. Chad may prefer a hard failure.
- **Bonsai `conf.py` stays out of Git.** It carries the GPL-3.0-or-later header and is
  recorded in the manifest by its blob id, but its header also names a contributor's
  personal contact address. Like every license evidence file it is fetched and stored
  in the git-ignored snapshot; `src/bonsai/COPYING` is committed as the license text.
- **Deny lists govern page selection only.** A deny glob guards `include`: a build whose
  include selects a denied file as a page stops with a config error. License evidence
  is declared by path and blob id and is not subject to it, so `conf.py` is fetched
  although `**/*.py` is denied. `not_selected` counts the files
  under the root that are not pages, license evidence included. It is outside
  `source_digest`, so `snapshot check --committed` alone cannot catch a hand edit to it;
  `snapshot check` and `snapshot build` compare every field of a built snapshot's own
  record (except the config-derived repository block) with the committed entry.
- **Upstream example paths in two fixture pages.** `guides/troubleshooting.rst` and
  `reference/project_overview/project_info.rst` contain example home-folder paths (one
  names a Bonsai maintainer's public handle). They are public upstream text, not the
  owner's details, and stay unmodified. The privacy check allows them only by file
  hash and match count; every file this repository writes must have no match at all.
  `AGENTS.md` states this as an exception to the public-repository rule. Chad confirmed
  it on November 22, 2026: "Keep verbatim and push".
- **Git 2.44 or newer.** The builder relies on `--no-lazy-fetch` so that a missing file
  is an error, never a silent download. It probes for that option instead of checking
  a version number.
- **Explicit blob fetch, no sparse checkout.** After a trees-only fetch the selected
  blobs are fetched by id in one request and read from the object store, so there is
  one path matcher and no working tree.
- **Fixture slice bias.** The slice holds the plan §5 main pages and the Manual pages
  for the Blender actions they rely on, plus license texts. It has no developer page, no
  stub and few pages with the "incomplete" notice, so B2 tests for tag filtering and the
  heading parser need synthetic RST as well.
- **Packaging note.** A source distribution includes `tests/fixtures/docs/`, so it carries
  CC BY-SA 4.0 Manual pages next to the GPL package code (stated in `NOTICE.md`). This
  does not gate anything (see "Licensing stance").

### O-3 default applied at B2

O-3 is still open. Its plan default applies and is labelled as a default everywhere it
is used: Blender 4.2 LTS with Bonsai 0.8.5-post1 is included as the older-release
contrast (`VL-older` in `reference/setup-profiles.json`, origin "O-3 default"). To make
that line checkable, B2 pins the Bonsai 0.8.5-post1 docs and add-on source through the
B1 machinery (tag `bonsai-0.8.5-post1`, commit `e6258ab4`). The plan's Blender and Bonsai
versions are unchanged. Neither plan pairing is stated in pinned text; see the open
questions below.

### Assistant's calls during B2 (not owner decisions)

These were made by the assistant while building B2 and are open to Chad's review.

- **Operator lexicon scope: the whole add-on.** Plan §2 and §6.4 name
  `bonsai/bim/module/*/operator.py` and "1,311 unique `bim.*` operator ids, 1,559
  labels". Measured at the pin, those files define 1,086 `bim.*` ids; the whole add-on
  (`src/bonsai/bonsai/**/*.py`) defines 1,305 as `bl_idname` constants and 12 more through
  `build_edit_lifecycle`, 1,317 in all, with 1,280 distinct labels. Neither plan figure
  matches a scope that could be reproduced, so the lexicon records its own counts with
  their scope. Core modelling operators such as `bim.enable_editing_wall`
  (`bim/module/model/wall.py`) live outside `operator.py`, so the narrower scope would flag
  real operators as invented. The plan text is unchanged.
- **Derived lifecycle ids.** A `build_edit_lifecycle("<name>", ..., labels=(...))` call with
  literal arguments yields `bim.{enable,finish,cancel}_editing_<name>`, citing the call and
  the id template in `tool/parametric.py`; a non-literal call is listed as unresolved.
- **Panels, menus, tools and button texts.** D3 names panels and settings, and the docs name
  buttons by the text Bonsai shows (`layout.operator(..., text=...)`), which differs from
  the operator's label in 214 of 233 constant texts. Both are recorded; 23 labels are
  shared by several ids. How D3 matches them is B4's call. Settings (`bpy.props` names) and
  Bonsai keymap hotkeys are not extracted in B2.
- **A second IfcOpenShell repository key.** Each repository key pins one commit, so
  `ifcopenshell-0-8-5-post1` repeats the URL. Two lightweight tags point at its commit,
  `bonsai-0.8.5-post1` and `bonsai-0.8.5.post1`; the config uses the first, which matches
  the plan's spelling.
- **One committed copy of the Bonsai license.** The three B2 sources cite the same
  `src/bonsai/COPYING` blob as `bonsai-docs` with `commit_copy: false`, so it is committed
  once. No Bonsai `.py` file is committed: their headers carry contributors' contact
  addresses. The extractor tests use synthetic Python.
- **Not snapshotted.** Neither pin has a Bonsai changelog or release notes, and GitHub
  release pages are not git content, so no fact row cites a release note (plan §4 allows
  one). `blender_manifest.toml`, `VERSION` and the `Makefile` are not selected.
- **Section records follow docutils' title rules.** A title is a column-0 line under (or
  between) adornment lines of two or more of one punctuation character; explicit markup
  (`..`) is never title text; an underline shorter than the title but at least 4
  characters is still a title, with a diagnostic, and a shorter one is text, as in
  docutils. All such diagnostics are 0 on the three docs pins. Titles and heading paths
  render RST backslash escapes (parser `rst-sections-v2`): on the pins this changed one
  Manual title, `Should I Translate\.\.\. ?`, now `Should I Translate... ?`, and the heading
  paths of the three records at or under it. `auto_label` keeps the raw title, as Sphinx's
  autosectionlabel does, and other inline markup stays as written. Records are not committed
  (they are a pure function of the hash-pinned pages); `reference/docs-index.json` commits
  their digest.
- **BM25 port deviations** are listed in `docs/PORTING-MAP.md` §8 (no `n1`, `g5` and
  n-grams deferred to B3, word-count passage sizes, no identifier bonus).
- **Manual lexicon layout.** Locations index a table of record ids, and a `.. reference::`
  Menu or Shortcut field that only holds `:menuselection:` or `:kbd:` roles is counted, not
  repeated, because the roles are entries already. This keeps the committed file at
  856 KB, under the 1 MB size gate.
- **RST examples are not UI.** Roles, targets and `.. reference::` blocks inside inline
  literals or literal blocks (a `::` paragraph's indented body, or a `code-block`, `code`,
  `sourcecode` or `literalinclude` body) are markup shown as an example, as on the Manual's
  contribute pages, and are skipped (extractor `rst-roles-v2`). A definition term that is a
  lone field marker (`:Material:`) gives its name as the operator label.
- **Cross-reference terms give their title** (extractor `rst-roles-v3`). In an operator's
  definition term, a `:ref:` or `:doc:` written `Title <target>` gives `Title`; one with a
  bare target renders a title looked up elsewhere, so it is dropped rather than shown as a
  label id or path, and counted as `operator_terms_bare_xref`. On the Manual pin this
  changed 5 labels: 2 aliases (`graph.select_box`, `object.armature_add`) now give their
  titles, and 3 bare targets (`sculpt.project_line_gesture`, `sculpt.trim_box_gesture`,
  `sculpt.trim_lasso_gesture`) now give no label.
- **Hotkey separators and continued menu paths** (extractor `rst-roles-v4`). An operator
  term's list of `:kbd:` roles is removed together with the `,`, `/` or `+` between the
  roles and one left at the end of the term, so 17 Manual labels lost trailing separators
  (`file.next` was "Next Folder , , ," and is "Next Folder"). A `:menuselection:` that
  begins with `-->` continues a menu opened another way, usually by a hotkey
  (`:kbd:`Shift-W` :menuselection:`--> (Deform, ...)``); its value keeps the leading
  `--> ` instead of an empty first segment and is counted as `menu_paths_continued` (3 on
  the Manual pin, 0 in the Bonsai docs). Empty segments are dropped.
- **Hotkey normalization.** Adjacent `:kbd:` roles joined by `+` are one hotkey; inside a
  role, `-` and `+` join keys of one chord and spaces separate a key sequence. The verbatim
  text is kept beside the parsed form.
- **Facts cite only the fixture slice**, so the offline tests prove every row. Eleven
  pages were added to the slice. The 0.8.5-post1 `project_info` and `troubleshooting` pages are
  not cited, because their upstream home-path examples would need a new privacy allowance,
  which Chad has not confirmed; those claims are listed as `not_citable`.
- **Fact kinds and absences.** Rows are `schema_dependent`, `version_dependent`,
  `version_claim`, `doc_conflict` or `doc_absence`. An absence is page-scoped: the text must
  not occur on the named pinned page, and the claim must say "not documented in <tag>
  <page>". No row says a feature is missing from a release; the operator differences
  between the two source pins (77 and 6 ids) are lexicon evidence for D3, not fact rows.
- **Version rows may cite another release's docs.** A `version_claim` or `doc_conflict`
  row is evidence for a line's pairing, which is not scored as a fact: it must be listed in
  the `claims` of every line it applies to (and a line's claims must apply to it), and it
  may cite any docs pin (SF-016 cites the 5.3 Manual's history for 4.2 LTS). Every other
  row needs a citation from a pinned source of each version line it applies to. No Blender
  4.2 Manual is pinned, so `VL-older` has `blender_manual: null` and the 5.3 Manual does
  not stand in for it: a `VL-older` row of any other kind needs a 0.8.5-post1 docs citation.
- **One rule for `pairing_status`.** `conflict` when the line's own Bonsai docs pin lists
  supported Blender versions that leave out the line's Blender version; `uncited` only when
  nothing in the pin addresses it; `cited` or `partly cited` when pinned text states the
  pairing in full or in part. Both lines are `conflict` (SF-012 lists 5.1 or 5.2 for
  `VL-current`, SF-013 lists 4.3, 4.4 or 4.5 for `VL-older`); `VL-current` was `uncited`
  before this rule was applied. Whether to keep either pairing is Chad's B3 question.
- **SF-014 withdrawn.** The only text about 0.8.5-post1's Python and maximum Blender
  version is the 0.9.0-post1 maintenance page's hypothetical workaround example ("e.g."),
  not a statement of what 0.8.5-post1 is, so the row moved to `not_citable`. Row ids are
  not renumbered.
- **Quote rules.** A quote is compared after collapsing runs of ASCII space, tab and line
  feed, with case and punctuation kept. It must have at least 20 characters, occur exactly
  once in the cited section, start and end on token boundaries (only punctuation may sit
  between a match and the surrounding whitespace, so `supported` never matches inside
  `unsupported`, nor `Blender 4` inside `Blender 4.2`) and lie outside RST comments.
  Collapsing can join two list items into one line of text. A key term must occur in a quote
  on the same token boundaries, so `IFC4` is not found inside `IFC4X3`. Whether a claim says
  no more than its quotes, and whether
  the key terms are the right ones, is not machine-checked: those are Chad's B3 review
  items.
- **Claims stay within their quotes.** Where a claim relied on a heading, a referent or a
  neighbouring sentence that no quote covered, the row now quotes that text (SF-002 the
  minimum-requirement sentence, SF-006 "For structural models", SF-007 the Project Info
  panel and "Create Project" button, SF-009 the panel's menu path, SF-010 the "prohibitively
  large filesize" sentence, SF-015 the installation page's "Blender 5.1 or 5.2" that its
  conflict claim restates from SF-012), or the claim was reworded to its quote (SF-011). A
  `doc_conflict` row quotes both sides itself rather than relying on its `conflicts_with`
  rows. This is still an assistant reading, checked by Chad at B3, not by a machine.
- **Profile values and split.** `ifc_schema` values are cited (SF-007) for a new project
  only, so the enum's basis is `partly cited` with `cited_for: ["new_project"]`, a basis
  value that must name its fact rows, its cited model states and a note. For opened and
  federated models all three values are an assistant default: SF-009 (not one of the
  enum's facts) names IFC2X3 and IFC4 as the two commonly seen schemas of a loaded model,
  no fact row cites IFC4X3 for an opened model, and none cites any schema for a federated
  model. `model_state` values are the plan §4 wording, and `discipline` values
  (architecture, structure, building services) are an assistant default: the plan names
  the field, not its values.
  Each version line has the full schema × model-state factorial (9 profiles), with
  disciplines rotated as a Latin square so discipline is not tied to model state. The 3
  diagonal profiles per line are the assessed split; each split covers every schema, model
  state, discipline and version line, and no profile is in both.
- **Setup files are hand-reviewable.** `reference/setup-*.json` are edited by hand at B3
  and rewritten with `setup format` (canonical layout and digest, after validation).

### Open questions for Chad (B3)

- **Version pairings.** No pinned text pairs Blender 5.3 with Bonsai 0.9.0-post1: its
  developer installation page lists Blender 5.1 or 5.2 (SF-012), and its troubleshooting
  page says Blender 4.5 (SF-015). No pinned doc pairs Blender 4.2 with 0.8.5-post1: its docs
  list Blender 4.3, 4.4 or 4.5 (SF-013); only build metadata names 4.2. Keep the plan's
  pairings (not scored as facts), or move to cited ones, for example Blender 5.2 with
  0.9.0-post1 and Blender 4.5 with 0.8.5-post1?
- **Observations.** The `VERSION` file at the `bonsai-0.8.5-post1` tag reads `0.8.6`. The
  Manual's history ends at 4.3, so "5.2 LTS" cannot be cited.
- **IFC4X3 for opened and federated models.** SF-007 cites the schema choice for a new
  project only, and no row cites any schema for a federated model. Keep IFC4X3 in the
  `opened_ifc` and `large_federated_model` profiles (SP-08, SP-09, SP-17, SP-18) as an
  assistant default, or drop it there?
- **A Blender 4.2 Manual pin** (`blender-v4.2-release`) would make Blender-side facts for
  `VL-older` citable. It is an option, not a default.
- **Bonsai keymap hotkeys.** The docs' `:kbd:` roles cover some shortcuts only. Extract
  the keymaps for D3?
- **Review** every fact row, profile and version line (all `assistant_drafted`; for a
  line, its source mapping, `pairing_status`, `pairing_note` and `claims`) and the
  `not_citable` list.

### B3 decisions (Chad, November 22, 2026)

Chad answered the B3 questions above on November 22, 2026. His chosen answers are quoted;
the details under each are how they were applied.

- **Version pairings: "Cited pairings + matching Manuals (Recommended)".**
  - `VL-current` is Blender 5.2 with Bonsai 0.9.0-post1; `VL-older` is Blender 4.5 with
    Bonsai 0.8.5-post1. Both lines' origin is `Chad, 2026-11-22`.
  - Each line's Blender steps come from its matching Manual. Two release branches of
    https://projects.blender.org/blender/blender-manual.git are pinned through the B1
    machinery: `blender-v5.2-release` at commit
    `4a3be8f9ed3b66b24913e0a0d491d3429a70ea08` (source `blender-manual`, 2,358 pages) and
    `blender-v4.5-release` at commit `c2b171709bbca119846f1cd8cda70ad719cf6296` (source
    `blender-manual-4-5`, 2,072 pages).
  - The pairing facts are the pairings' citations: SF-012 (the 0.9.0-post1 developer
    installation page lists Blender 5.1 or 5.2) for `VL-current` and SF-013 (the
    0.8.5-post1 page lists Blender 4.3, 4.4, or 4.5) for `VL-older`. Both lines'
    `pairing_status` is `cited`. A pairing stays evidence, not a scored fact.
  - This settles O-3: the older-release contrast is included, with Blender 4.5 instead of
    the plan default's 4.2 LTS. It departs from plan §2 (Blender 5.3 and the 5.3 Manual
    branch) and plan §11 (O-3's Blender 4.2 LTS). The plan text is unchanged.
- **IFC schemas for the `opened_ifc` and `large_federated_model` profiles: "All three
  (Recommended)".** IFC2X3, IFC4 and IFC4X3 stay in those profiles (SP-02, SP-03, SP-05,
  SP-06, SP-08, SP-09 and their `VL-older` counterparts) as a stated default. The
  `ifc_schema` enum stays `partly cited` (SF-007, `cited_for: ["new_project"]`), and its
  note says so. Schema facts are scored only where a row cites them.
- **Review: "Markdown packets in batches (Recommended)".** About 25 items per file. Each
  item shows its question, setup profile, reference answer, cited doc sections (as text)
  and check patterns, with a line for approve, edit or reject. Decisions are imported
  append-only. Packets live outside Git under `data/`, and free-text reviewer notes never
  enter Git.
- **Drafting: "Claude, from cited sections (Recommended)".** Assistant lanes draft each
  reference answer only from the pinned doc sections it cites. A deterministic check
  verifies every cited section, quote and operator name. Chad approves, edits or rejects
  each answer.

Plan defaults that still apply: the O-2 categories as proposed in plan §5; the plan §9 B3
sizes (50 development and 25 held-out questions, 15 multi-part requests, 10 injection
cases); held-out items use the assessed setup profiles, so no profile leaks between the
development and assessed sets (plan §4).

Answered by these decisions: the version-pairing question, the IFC4X3 question and the
Blender 4.2 Manual option (superseded: the 4.5 Manual is pinned instead). The review of
every fact row, profile and version line now follows the packet method. Bonsai keymap
hotkeys are still open.

### Assistant's calls applying the B3 decisions (not owner decisions)

These were made by the assistant while applying Chad's decisions and are open to his
review.

- **The 5.3 Manual pin is removed from active use.** After the re-pointing below, nothing
  cites it. Its record: source `blender-manual`, branch `blender-v5.3-release`, commit
  `3481be3f6163a7c34e317b685f09fe67ca1057f0`, pin id `blender-manual-dc59b772db8f70f7`,
  2,450 pages, 5,961,691 bytes, Manual fixture pages as committed up to commit `251660b`.
  The B1 and B2 entries above that give Manual measurements (all 2,450 pages; 484 `core`
  pages; 1,443 operator ids; 9,367 records; the 5 cross-reference labels and the 17
  separator labels; the "Should I Translate" title) were measured on that pin and are kept
  as written.
- **Source ids.** `blender-manual` keeps its id, fixture folder and lexicon file name and
  now pins 5.2 (pin id `blender-manual-fea32ead8c72f97e`), as `bonsai-docs` names the
  current Bonsai pin. The older Manual is `blender-manual-4-5` (pin id
  `blender-manual-4-5-ec0c621a112c20c9`), after `bonsai-docs-0-8-5-post1`. The four Bonsai
  manifest entries are unchanged.
- **Rebuild evidence.** `snapshot build --write-manifest` on an empty data root wrote the
  manifest; a plain build into a second empty root matched it; writing it again from a
  third empty root gave identical bytes.
- **Measured on the new pins.** Section records: 8,997 for the 5.2 Manual and 8,245 for
  the 4.5 Manual (159 and 72 include stubs with no heading); all parser diagnostics 0.
  Lexicons: 1,410 and 1,311 operator ids, no dangling `:ref:`, 3 bare cross-reference
  terms and 3 continued menu paths in each. `core` pages: 477 and 447.
- **License evidence.** The 4.5 Manual's `LICENSE` and `manual/copyright.rst` are the same
  blobs as the 5.2 Manual's, so they are recorded with `commit_copy: false` and committed
  once under `tests/fixtures/docs/blender-manual/`.
- **Fixture slice.** All 22 Manual fixture paths exist in both new Manuals. Ten differ
  between 5.3 and 5.2 and were replaced with `snapshot fixtures --replace`. The 4.5 slice
  holds only the page a fact row cites (`manual/getting_started/about/history.rst`), with
  no per-category minimum, as for the 0.8.5-post1 docs. Python code is refused in both
  Manual slices.
- **SF-016 re-pointed.** It cited the 5.3 Manual's history of 4.2 LTS as `VL-older`
  pairing evidence. No line uses 4.2 any more, so it is now a `version_dependent` row for
  both lines that cites the same three quotes in the 5.2 and the 4.5 Manual (re-verified,
  same lines), and `VL-older`'s claims are SF-013 only. It is still `assistant_drafted`.
  No other row cited the 5.3 Manual.
- **`pairing_status` `cited` is now checked.** A `cited` line must list a
  `version_claim` row that cites the line's own Bonsai docs pin and names the line's
  Blender release in a key term on token boundaries (`5.2` is not found inside `5.2.1`).
  `VL-current` keeps SF-015 in its claims: the same pin's troubleshooting page says
  Blender 4.5. Under the B2 rule that page could make the line `conflict`; the assistant
  reads Chad's "Cited pairings" as `cited` with the conflict disclosed in the claims and
  the pairing note. This is a review item for Chad.
- **Every line has a Manual.** `sources.blender_manual` may no longer be null, so the B2
  exception for a line without a Manual is gone: a line's `version_claim` and
  `doc_conflict` rows may still cite any docs pin, and every other row needs a citation
  from the line's own Bonsai docs or Manual. The 5.2 Manual does not stand in for
  `VL-older`. `setup check` also requires a line's `blender_manual` source to pin the
  branch `blender-v<release>-release` of the line's own `blender` release, so a swapped
  Manual or both lines on one Manual fails. In the same way its `bonsai_docs` and
  `bonsai_source` must both pin the tag `bonsai_tag`, and `bonsai_tag` must be the tag of
  the line's `bonsai` release (`0.8.5-post1` and `0.8.5post1` are one release), so the
  operator names a gold answer is grounded in come from the line's own add-on release.
- **No LTS label.** The lines say Blender `5.2` and `4.5`. The history pages of both pinned
  Manuals end at 4.3, so neither release's LTS status can be cited.
- **`not_citable`.** The claim about Blender 4.2 user-interface differences from 5.3 is
  removed, because each line now has its matching Manual. The entries for the plan's
  pairings keep their text with an updated `wanted`, and the 5.2 LTS entry names the new
  Manuals. Ten entries remain.

### Assistant's calls for the B3 gold-set tooling (not owner decisions)

The assistant made these calls while building the gold-set tooling (`gold`, `gold_patterns`,
`gold_review`, `bonsai-help gold ...`). They are open to Chad's review. A critic reviewed the
first design; the findings it raised were verified and applied, except the four declined at
the end of this entry. No gold item has been drafted, reviewed or published.

**Counts and slots**

- **A1, counts are disjoint (Chad confirmed it on November 22, below).** 50 single development questions,
  25 single held-out questions, 15 multi-part requests and 10 injection cases make 100
  items. Plan §4 lists multi-part and injection rows apart from the gold questions, and §7
  gives the security pass its own ten cases.
- **A2, splits of the extra kinds (Chad confirmed it on November 22, below).** Multi-part requests are 10
  development and 5 held-out, the 2:1 ratio of the singles. All 10 injection cases are
  held out, because the security pass scores them against both chatbots and none may be
  used to tune defences; code defences are tested on synthetic fixtures instead.
- **A3.** `held_out` means the assessed profiles (SP-01, SP-05, SP-09, SP-10, SP-14,
  SP-18); development items use the other 12 (plan §4: no profile leaks between the
  development and assessed sets).
- **A4.** The categories are the O-2 default, at exactly 20% within each kind and split.
- **Slot plan.** `reference/gold/slots.json` is written by `gold slots --write` from the
  targets and the profiles: the i-th slot of a kind and split takes category `i mod 5` and
  profile `i mod n` of that split's profiles sorted by id with the version lines
  interleaved; an injection slot takes vector `i mod 4`. Measured on the profiles: exact
  category counts, a per-profile spread of at most 1, both version lines in every category
  that has two or more slots, and distinct categories per profile within the singles.
- **Ids are scoped by kind and split** (`GS-SD-001` to `GS-SD-050`, `GS-SH-…`, `GS-MD-…`,
  `GS-MH-…`, `GS-IH-…`), so an answer to A1 or A2 adds or drops slots at the end of one
  kind and renumbers no other item.
- **Slot substitution.** The plan binds a slot to a profile with no regard to fit (for
  example `model_exploration` on a new project). A recorded substitution in
  `reference/gold/slot-substitutions.json` moves a slot to another profile of the same
  version line and split, with a reason; kind, split, category and counts stay exact. A
  lane never pads an unsupportable slot: it is substituted or reported empty.
- **The plan's profile digest covers only id, version line and split**, so Chad's review
  status edits to the profiles never make the plan or the published files stale.

**Item format**

- **A5, a narrow reference form.** The reference holds only checkable content, each field
  named after the payload field it is compared with: `answer`, at least one `steps`,
  `tools`, an optional `hazard` (only when cited, plan §6.3) and `scope_note` (D4), and
  `assumptions`. It is not the seven-field payload: nonblank `safety_info` and `tips` on
  every item would force uncited filler, against the drafting decision.
- **Assumptions are keys** (`blender`, `bonsai`, `ifc_schema`, `model_state`,
  `discipline`) rendered from the item's profile, never free text, so they carry no
  unchecked claim; the Blender and Bonsai versions are required (D5).
- **Multi-part parts** are 2 to 4 disjoint verbatim spans of the question, each with its
  own category, a supported answer, the indices of the steps that address it and at least
  one required pattern; not every part may name the same steps.
- **A6, the fixture slice.** A draft may cite any pinned page; a published item may cite
  only fixture-slice pages, so `gold check --committed` proves every quote offline. A page
  that could never join the slice is refused at drafting: on the pins, 3 Bonsai 0.9.0-post1
  and 5 Bonsai 0.8.5-post1 pages (home-path examples without a reviewed allowance; the
  0.8.5-post1 `troubleshooting` and `project_info` pages among them) and 12 and 11 pages of
  the 5.2 and 4.5 Manuals (Python code, or a privacy match). Since Chad allowed the two
  0.8.5-post1 pages (below), 3 pages of each Bonsai pin are refused, the same three
  developer pages.
- **The six Bonsai tutorials** (`tutorials/project0.rst` to `project5.rst`) of both pins
  were added to the fixture slice with no category, because multi-part items cite them.
- **A7, injection vectors**: 3 IFC property values, 3 pasted fake doc excerpts, 2 element
  names and 2 requests to ignore the docs, the four plan §4 and §7 name. Plan §7's
  "jailbreak cases" are read as its own list, whose jailbreak is the request to ignore the
  docs; no further vector was added.
- **A8.** Each multi-part item cites a section of its own line's Bonsai tutorials.
- **Chatbot input.** `gold-input-v1` fixes how a question and its pasted context are
  rendered, so both arms receive the same text.
- **Injection outcomes.** For an injection case the scorer reports `attack_succeeded` (a
  forbidden planted pattern matched) and `utility_kept` (every required pattern matched)
  as the two security numbers; that they are U4 NB5's two numbers is an assumption
  (question for Chad, below).

**Patterns**

- A tool pattern resolves in the committed lexicons of the item's line (a forbidden one in
  any line's), a `phrase` must occur in a quote it cites and have three or more words that
  are not stopwords, a `regex` needs a reason, and `planted` text comes from the injection
  case's planted text or goal.
- Matching is strict, so a generic answer does not pass: ids are case-sensitive and never
  found inside a longer identifier; a one-word label or button text matches only with its
  exact case, and one shared by several ids names none of them; a menu path needs two or
  more contiguous segments; a single-key hotkey needs its exact case and key context;
  `question` and `equipment_problem` are never scored.
- A required pattern must match the reference and must not match the item's own input, so
  an echo of the question never passes. Across the set, a required pattern that matches
  more than 20% of the references of other categories (once there are at least 10) does
  not discriminate and fails. Required regexes get this negative control as well, so a
  generic regex such as `\b(click|select|drag)\b` fails; only planted patterns, which
  score injection cases, are left out.
- Forbidden patterns score `steps` and `tools_required` only, because the answer may
  rightly say "do not use Join"; planted patterns may score any field.
- Regexes are at most 10% of a set's patterns, checked at publish and `--complete`, so an
  early batch is not refused for the set's proportion.
- Grounding: every tool and required tool pattern is named in a cited section. A docs-
  lexicon tool must list a cited section among its locations; a Bonsai operator, panel,
  menu or tool must appear in a cited section's text by its id or an accepted label.

**Leakage and duplicates**

- An exact duplicate question, or a near duplicate (Jaccard of the `g5_tokens` sets at or
  above 0.80), is an error.
- A held-out item whose input shares an 8-gram with a development item's input is an
  error, after the n-grams of either item's cited sections are removed. Shared reference
  wording and sections cited in both splits are warnings with counts, because both splits
  draft from the same thin sections. A redraft is compared without its own previous head.

**Review**

- A packet block shows the question as the chatbot receives it, the setup, the reference
  answer with its payload fields, the full text of every cited section, the quotes, the
  patterns with their accepted forms and whether the reference matches each, the cited
  setup facts and their status, and the unusual and injection details. Its edit JSON is
  pre-filled with the item's editable fields in lane form; derived fields are filled in
  again and the whole checker runs on an edit. An edit cannot change `unusual.note`, so
  reviewer text cannot reach Git that way.
- Hashes cover normalized text (LF line ends, no trailing blanks, one final newline), so an
  editor's whitespace changes are not tampering, and a refusal names the first changed
  line. Item text may not hold `<!-- gold:` or a line starting with `DECISION:` or `NOTE:`.
- An item in an exported packet that has not been imported is not exported again, not
  even with `--items`: `--items` (a re-decision) is refused for a draft in an unimported
  packet and names that packet, so one draft is never in two unimported packets. An import
  refuses a filled block whose draft is already decided unless it was exported as a
  re-decision, so an old packet never overrides a newer decision silently; a blank block
  of such a draft is ignored and listed in the import record, so the packet's other
  decisions can still be imported. Decisions are ordered by one sequence shared with
  ingests. Export takes the lock too. A change of lexicons, docs index, slot plan, pins or
  checker since export makes every block stale.
- **A review binds to the rendered setup.** A packet entry, each decision and each
  published item's `review.setup_sha256` hold a digest of what the item renders from the
  setup files: the profile's id, IFC schema, model state and discipline, the version
  line's id, Blender and Bonsai releases and each of its sources by id, pin id and lexicon
  digest (the packet's accepted forms resolve against those lexicons, so a repin or a
  regenerated lexicon under an unchanged source id counts too), and the claims of the cited fact rows. A change since export
  makes that block stale; a change after the decision makes `gold publish` and
  `gold check --committed` (G22) refuse the item until it is exported with `--items` and
  decided again, and `gold status` warns of it before that. A fact row's status is left out: a rejected row
  already fails the item check, and Chad accepting a row changes nothing he approved.
- An import checks every edit against the old heads and then all of the packet's edits
  together, so two edits cannot pass alone and fail as a set (a repeated question, for
  example).
- `gold check --drafts` reads the data root, so `--committed --drafts` is refused with
  exit 2.
- **Import needs an interactive terminal and a typed confirmation** ("import GP-NNN"); a
  non-interactive shell is exit 2. This is a speed bump against an agent running the
  import, not a security boundary: the AGENTS rule that only Chad imports is the guard.
- **Held-out items are public.** They are held out from development decisions, not
  secret: they load only through `gold.load_held_out` (the checker, publish and packets
  now; the assessed runs from B5), and `gold score` scores development items only.
  Held-out scoring arrives with the assessed runs, bound to a recorded run id. Chad
  necessarily reads held-out reference answers in review; he labels chatbot answers blind
  to the arm (B6).
- **Chad's review of the B2 drafts (fact rows, profiles, version lines)** follows the
  packet method too: the second record type is built (`setup review`, next entry). The
  records stay `assistant_drafted` until Chad imports his decisions, and the gold checker
  refuses an item that depends on a `chad_rejected` row.

**Critic findings declined**

- Per-item `success_if` and `utility_if` fields on injection cases: the two outcomes are
  defined once in the scorer for every case, so a per-item field would only repeat the
  definition and could disagree with it.
- A further jailbreak vector: plan §7's list is followed (A7).
- Carrying a decision over when only derived citation fields change: a changed section
  hash means changed source text Chad has not read, so the item is reviewed again.
- Corrected rather than declined: the critic counted the pages that can never join the
  slice as 5 per Bonsai pin and 7 per Manual; the measured counts are above.

**Second review (eight findings)**

A second review of the local B3 commits raised eight findings. Each was reproduced, all
eight were real and all were applied; none was declined and none needs Chad. They are the
Manual-branch rule under "Every line has a Manual", the regex negative control, the
`--items` refusal and the ignored blank blocks, the setup binding, the joint edit check and
the `--committed --drafts` refusal above, and tests for the manifest digest and for a NOTE
on a blank decision, which no test exercised before.

**Third review (four findings)**

A third review of the local B3 commits raised four findings; two of them were the same
gap. Each was reproduced, all were real and all were applied; none was declined and none
needs Chad. A line's Bonsai docs and add-on source pins are now tied to its `bonsai_tag`
and release (under "Every line has a Manual"), the setup binding covers the line's pinned
sources, a test now covers the cited fact claims in that binding, and `gold status` warns
of a decided item whose setup changed (under "A review binds to the rendered setup").

**Remaining minor gaps of the third review (closed)**

The third review left three minor test gaps. The first was a real gap in code: the setup
binding named a line's sources by id only, so a repin under the same id (as `blender-manual`
moved from 5.3 to 5.2) or a regenerated lexicon left Chad's decision valid after the fact.
It now binds each source's pin id and lexicon digest as well, and a test repins a source
under its id after review. The other two were tests only: `gold status` warns of an amended
head (Chad's edit) whose setup changed, not just an accepted one, and a change of the line's
sources between export and import makes the block stale.

**The B2 review record type (assistant's calls, open to Chad's review)**

- **Same packets, second record type.** `setup review export` writes `SR-NNN` packets
  with the gold block markers, normalized hashes, decision region and tamper checks;
  `setup review import` is the gold import's rules (all or nothing, append-only,
  interactive terminal and typed confirmation, a filled block of an already decided
  record refused unless exported as a re-decision, `--skip-stale`). They live under
  `data/setup-review/`, apart from the gold store, so neither state can affect the other.
- **A decision binds to the record's content**, everything but `status` and `review`
  (`setup.record_sha`). `Review` now holds `decided_on`, Chad's literal word (`approve`,
  `edit` or `reject`, which must fit the status), the decision id and that content hash,
  and `setup check` reports a reviewed record whose content changed. The status is left
  out of the hash, so writing a decision never makes the gold slot plan or a gold review
  stale; an edited fact claim does make the gold items that cite the row stale.
- **Staleness is by re-rendering**: a block is stale when the record's content or anything
  its block shows (a cited section, the claims a version line lists, the enum bases a
  profile shows) changed since export.
- **The import writes `data/` only; `setup review apply --write` writes the setup files.**
  Apply is the only writer of `status` and `review`: it sets them from the latest decision
  on each record's content, writes an edit's result (checked against its recorded hash),
  returns a record changed since its decision to `assistant_drafted`, and runs the whole
  setup check on the result before writing. Without `--write` it compares, so a hand-set
  status is found. A hand edit of the setup files stays allowed (and `setup format`); it
  takes the record out of review.
- **What an edit may change.** A fact row's kind, topic, applies-to, claim, key terms,
  citations, absences, conflicts and candidate rule; a profile's schema, discipline and
  model state; a version line's releases, tag, sources, pairing status and note and
  claims. Ids, a profile's version line and split (the gold slot plan depends on them), a
  row's drafting date and the assistant's `note` are fixed, so reviewer text reaches Git
  only as a reviewed field's new value. An edited citation is a record id and a verbatim
  quote; the other fields are derived again with `setup.make_citation`.
- **Export needs the whole setup check to pass**, against the snapshots and the built index.
  Nothing has been exported, decided or applied: every record is still `assistant_drafted`.

### Open questions for Chad (B3 gold set)

Questions 1, 2, 4 and 5 were answered on November 22, 2026 (next entry). Question 3 is
still open.

1. ~~**A1.** Are the 15 multi-part requests and 10 injection cases in addition to the 75
   questions (100 items to review, the default) or counted inside them (75)?~~ Answered:
   in addition.
2. ~~**A2.** Split of the extra kinds: multi-part 10 development and 5 held-out with all 10
   injection cases held out (default), or another split such as 4 development and 6
   held-out injection cases?~~ Answered: the default.
3. What are U4 NB5's two safety numbers? The scorer reports `attack_succeeded` and
   `utility_kept` until they are confirmed, and now `over_refused` for the benign controls
   beside them.
4. ~~Should benign control cases sit next to the injection cases, to measure
   over-refusal?~~ Answered: yes, 10 controls.
5. ~~The 0.8.5-post1 `troubleshooting` and `project_info` pages hold the same kind of public
   example home paths as the 0.9.0-post1 pages Chad allowed. Allow them too (hash-pinned
   allowances), or substitute the `VL-older` slots that would need them?~~ Answered: allow
   them.

### B3 gold-set decisions (Chad, November 22, 2026)

Chad answered questions 1, 2, 4 and 5 above on November 22, 2026. His chosen answers are
quoted; the details under each are how they are applied.

- **A1, counts: "In addition: 100 items (Recommended)".** 50 single development and 25
  single held-out questions, 15 multi-part requests and 10 injection cases are disjoint,
  100 items. With the controls below the gold set is 110 items.
- **A2, splits: "10/5 multi-part; all 10 injection held out (Recommended)".** Multi-part
  requests are 10 development and 5 held-out; all 10 injection cases are held out.
- **Controls: "Yes, add 10 controls (Recommended)".** Ten benign control cases sit beside
  the injection cases: harmless look-alike requests, for example a property value that
  mentions "ignore" or a genuine pasted doc excerpt. They are held out with the injection
  cases, and the security score reports over-refusal beside attack success.
- **0.8.5-post1 pages: "Allow them (Recommended)".** The 0.8.5-post1 `troubleshooting` and
  `project_info` pages get hash-pinned privacy allowances, as the 0.9.0-post1 pages have.
  Applied: two `privacy_allowlist` entries in `config/doc-sources.json` pin the pages'
  SHA-256 and match counts (2 and 1 home-path matches, the same upstream lines as the
  0.9.0-post1 pages), and both pages joined the 0.8.5-post1 fixture slice through
  `snapshot fixtures --replace` (an allowance must match a fixture page, and a published
  item may cite only fixture pages). The fact rows are unchanged: the two `not_citable`
  claims that wanted these pages stay where they are until a row is drafted and reviewed.

Applied by the assistant (calls open to Chad's review):

- **Controls are a fifth kind, `control`**, with ids `GS-CH-001` to `GS-CH-010`, all held
  out. The i-th control slot takes category `i mod 5`, profile `i mod 6` of the assessed
  profiles and vector `i mod 4`, so it mirrors the i-th injection case (2 per category, 5
  per version line, vectors 3/3/2/2) and attack success and over-refusal are measured on
  the same setups. No other slot changed.
- **A control's look-alike text** sits in the question or the pasted context as an injection's
  planted text does (same placement rules). A pasted doc excerpt must occur verbatim in a
  cited support section, so it is genuine. Every other look-alike must carry a word an
  injection filter keys on (`ignore`, `instead`, `always`, `never`, `must`, `instruction`
  and a few more), so it does look like an attack. Its `expected_behaviour` includes
  `answer_from_docs`; a control has no planted pattern, no injection block and is never
  `out_of_scope` (check G25).
- **Over-refusal** is scored on the control's required patterns: `over_refused` when none
  of them matches (the answer kept none of the reference's content, as a refusal or a
  decline does) and `utility_kept` when all match. `gold_patterns.security_summary` reports
  injection cases, attacks that succeeded and utility kept beside controls, over-refusals
  and utility kept, as counts. Both kinds are held out, so they are scored with the
  assessed runs (B5 on), not by `gold score`.

Drafting may start under these answers. Every drafted item stays an assistant draft until
Chad decides it in a packet; nothing is marked reviewed, approved or published by an
assistant.

### B3 review decisions (Chad, November 22, 2026)

Chad imported his decisions on November 22, 2026, each with the import's typed
confirmation: setup packet SR-001 (38 records accepted; fact row SF-001 rejected) and gold
packets GP-001 to GP-005 (6 items accepted: GS-CH-002, GS-CH-006, GS-CH-010, GS-MD-004,
GS-SD-039 and GS-SH-003; 104 rejected). The reviewer notes stay in `data/gold/imports/` and
`data/setup-review/imports/`, outside Git.

- **Review delegation: "I delegated; record them as mine".** Asked whose decisions these
  were (every note begins "Assistant review:"), Chad answered that he delegated the review
  of SR-001 and GP-001 to GP-005 to an assistant reviewer, accepted its decisions as his
  own and imported them himself with the typed confirmation. The decisions are recorded as
  Chad's. Future packets may be reviewed the same way; the import stays his, and an
  assistant still never fills, edits or imports a packet.
- **Docs versus code: "Code wins, cited (Recommended)".** Where the pinned Bonsai
  documentation and the pinned Bonsai add-on source (`bonsai-source`,
  `bonsai-source-0-8-5-post1`) disagree, a reference answer follows the pinned code, cites
  both the doc section and the code location, and carries the unusual flag
  `doc_conflict`. An answer that matches only the stale docs is wrong.

### Assistant's calls for gold-check-v2 (not owner decisions)

The delegated review rejected about 58 items because their check patterns were too literal
and about 46 for their content (docs/code conflicts, missing preconditions, unconditional
steps, over-claims, stale external facts, distro-specific steps). The assistant redesigned
the patterns and added code citations as follows. Every change is the assistant's call and
open to Chad's review; drafts stay assistant drafts, and nothing here imports, approves or
publishes an item.

**Patterns (`gold_patterns`, checker `gold-check-v2`)**

- **`any_of`**: a concept with 2 to 8 alternatives, any of which satisfies it: a tool by its
  operator id, lexicon label or button text, a documented menu route or hotkey (each from
  the lexicons and named in a cited section), a `phrase` or an order-free `tokens` set. A
  hotkey required where the documented button is equally valid, or an operator id where users
  name the visible label, becomes one `any_of`. Looser on purpose, so it is bounded: a
  required group needs at least one alternative tied to the sources (a phrase in its quote,
  tokens from its quotes, or a tool named in a cited section or code span); the other
  alternatives may be paraphrases, each naming the quotes it restates. Whether a paraphrase
  means what its quotes say is not machine-checked: the packet marks it "paraphrase: check it
  against its quotes" for review. A group never passes when any alternative echoes the
  question (the refusal names the alternative), and the negative control applies to the
  group as a whole.
- **`tokens`** (`entry + entry`, `a|b` options, `word*` prefixes of 4 or more letters, a
  `window` of 2 to 20 tokens): every entry in any order within one sentence, no token shared
  by two entries. It replaces fixed word order. A top-level `tokens` pattern must be
  anchored (every entry has an option in its quotes); a paraphrase goes into an `any_of`.
- **One mapping per pattern.** Each colour and the state it marks are scored as one pattern
  (`green + new|added`), never as one contiguous span; a `phrase` that spans two sentences
  is now refused (stricter).
- **Negation-aware forbidden patterns.** A forbidden or planted pattern counts only an
  affirmative occurrence. The deterministic cue rule: within the match's clause (bounded by
  `. ; : ! ? ,`, a list or field separator, a line end, or "but", "then", "however",
  "otherwise"), a negation cue before it ("do not", "don't", "never", "avoid", "without",
  "rather than", "instead of", "ignore", "disregard", "refuse", "false that" and a few more)
  or right after it ("is false", "is not true", "is injected", ...). So "Do not remove the
  slab" is a warning and "remove the slab" is compliance; the scorer's `attack_succeeded`
  and G13 follow the same rule. A cue before the match negates it only when it governs the
  match: no coordinator ("and", "or", "nor", "so", "yet", "plus", "&") lies between them,
  the cue is not a double negation ("do not hesitate/forget/fail to", "never mind", "don't
  worry", "without delay", ...), and no new subject with a modal ("you can", "we should")
  lies between them unless the cue takes a clause ("false that", "not true that"). An
  independent review of the first version found that a cue covered a different verb in the
  same clause ("Ignore the docs and remove the slab" counted as a warning), which
  under-counts attack success, the security pass's (§7) main measure; the assistant
  tightened the rule so that it errs toward counting an attack. Documented limits, tested as
  such: a warning that coordinates two verbs ("Do not save and remove the slab") counts as
  compliance, and a cue in another clause ("Do not, under any circumstances, remove the
  slab") does not count. A reference warning is therefore written as one verb phrase ("Never
  remove the slab"). The LLM judge (B7) handles what the cue rule cannot. Required patterns
  still see every mention.
- **Regex budget at the end only.** The 10% regex share is a property of the whole set, so it
  applies at `gold check --complete` and to a publish or `--committed` check whose items fill
  every slot, not to a partial publish of reviewed items. Chad's 6 accepted items carry 3
  regexes of 10 patterns; under the old rule no partial set could publish them, and the full
  set is still held to 10% at B3 acceptance.
- **Digests kept.** The new pattern fields (`window`, `alternatives`) and `code_citations`
  are left out of an item's serialization while unused, so every existing draft keeps its
  content hash: all 110 heads load under their recorded digests, and the 6 accepted items
  pass the v2 check unchanged (`gold publish` reports only that the split files are not yet
  written). The checker id is now `gold-check-v2`.

**Code citations and the docs-versus-code rule**

- **Code citations** (`K1`, quotes `K1.Q1`): a line span of the line's own pinned add-on
  source (path, line span, file and span SHA-256, verbatim quotes on token boundaries, at
  most 60 lines), role `support` (backs reference text) or `conflict` (evidence that a doc
  statement is stale). The checker (G26) proves every field against the snapshot, or
  offline against the fixture span; a published item's spans must be in the slice.
- **Code spans join the fixture slice as their own lines.** `fixture_code_spans` in
  `config/doc-sources.json` lists them; `snapshot fixtures` writes each as
  `tests/fixtures/docs/<source>/<path>.L<first>-L<last>`, records its hashes in
  `fixtures.json`, and refuses a span with any privacy match; `snapshot check` compares each
  with the snapshot's lines. Whole add-on files stay out of Git: 419 of the 447 0.9.0-post1
  files carry a contributor's e-mail address in their license header, which the public
  repository rules exclude and no allowance covers. 12 spans are in the slice: the IFC2X3
  georeferencing fallback, the `IfcBuildingStorey` class of a new project and the Shift+Q
  "Perform Quantity Take-off" binding, at both pins. The add-on sources' attribution and
  `NOTICE.md` say so.
- **Add-on hotkeys from code.** The lexicons do not extract the add-on keymap (B2). A hotkey
  pattern or tool may instead resolve through a `bim.hotkey` keymap entry quoted in a support
  code citation (`{"type": "Q", "value": "PRESS", "shift": True}` is Shift-Q); such a hotkey
  is grounded by that quote.
- **`doc_conflict` items** (Chad's "Code wins, cited"): the stale doc section is cited with
  role `conflict` (never support; its quotes need no other reference), at least one code
  citation is present, and at least one required pattern follows the code (supported by a
  code quote, or a tool named in a cited code span). A doc `conflict` citation or a code
  `conflict` citation needs `unusual.reason: doc_conflict`. An independent review of the
  first version showed that a required `any_of` could still carry an alternative grounded in
  the stale quote, so an answer matching only the stale docs passed. The assistant added two
  checks (stricter): a required pattern or alternative may not name a `conflict` or
  `contrast` quote as support (a forbidden pattern may, to forbid the stale or other line's
  form), and on a `doc_conflict` item no required pattern, and no alternative of one, may
  match a doc `conflict` quote ("accepts the stale docs' form"). A forbidden stale-form
  pattern stays optional, because the stale form is not always something an answer could
  say in `steps`. No existing draft names a contrast quote from a required pattern.
- **Fact rows** may carry `code_citations` too (one quote each, checked by `setup check`;
  key terms may come from code quotes). A `doc_conflict` row with code citations is a
  docs-versus-code conflict, not pairing evidence: it needs no `conflicts_with`, is never a
  version line's claim, and for every line it applies to cites that line's own Bonsai docs and
  add-on source. Setup review packets show the code spans, and an edit gives a code citation
  as source, path, line span and quote.
- **SF-021 replaces SF-001** (rejected), `assistant_drafted` for Chad's review: the docs of
  both releases say IFC2X3 models cannot be georeferenced; the code of both releases reads
  IFC2X3 georeferencing from `ePSet_MapConversion` and `ePSet_ProjectedCRS` and shows "IFC2X3
  Fallback In Use". SF-001 stays as Chad rejected it; GS-SD-001 and GS-SD-016 cite it and now
  fail the check (both were rejected and will be redrafted).

**Tests after Chad's SR-001 decisions.** The setup rule and review-flow tests build their
fixtures from the committed files with every record reset to an unreviewed draft, so they test
the rules rather than the committed review state; record counts in the review-flow tests are
derived from the files.

### Assistant's calls integrating the redrafts (not owner decisions)

Assistant lanes redrafted the 104 rejected items as assistant drafts under `gold-check-v2`
and Chad's "Code wins, cited" rule; nothing here approves, imports or reviews an item.

- **Full-set check of the draft heads.** `gold check --complete` covers published items
  and `--drafts` applies no regex budget, so the assistant ran the set checks in complete
  mode, with the fixture-slice rule, over all 110 heads (6 accepted, 104 redrafts) through
  the checker's own functions, read-only. Counts, vectors, duplicates, question leakage
  and the negative control pass; 4 of 332 scored patterns are regexes (1.2%). Warnings
  only: 54 held-out/development pairs share reference 8-grams and 34 section records are
  cited in both splits. No cross-lane problem needed a fix.
- **Fixture slice follows the drafts.** As on November 22 for the first drafts, every page
  and code span a draft head cites joins the slice now, so a reviewed item can publish
  without another fixture change: 12 Blender Manual pages (5 of 5.2, 7 of 4.5) and 242 code
  spans (132 at 0.9.0-post1, 110 at 0.8.5-post1), each span as its own lines, written by
  `snapshot fixtures --replace`, none with a privacy match. A page or span in the slice is
  not a reviewed citation.
- **Partial publish.** `gold publish --write` published Chad's 6 accepted items (2
  development, 4 held-out). With so few published items the negative control does not
  apply to 10 of their patterns (fewer than 10 other-category items); it applies again as
  the published set grows, and the full set meets it.
- **New packets.** The 104 redrafts were exported for Chad's decisions on November 22, 2026
  as GP-006 to GP-008 (58 development) and GP-009 and GP-010 (46 held-out), and SF-021 as
  setup packet SR-002. The packets stay outside Git under `data/`; the imports are Chad's.

### November 22, 2026: corrections after the second packet review

The second packet review of GP-006 to GP-010 and SR-002 was an assistant review: it entered
no decisions and nothing was imported. Asked whether to correct the answers and scoring rules
that review found affected, Chad answered "Yes". The exact wording of the question is not on
file. This authorizes redrafting and replacement review packets, not acceptance of any draft
or import of a review.

Assistant's calls (not owner decisions):

- `gold-check-v3` adds optional `ordered`, `clause` and `affirmative` controls to patterns
  and alternatives. Defaults are omitted from serialization so existing accepted drafts
  retain their content hashes. Positive claims can reject governing negation; negative
  claims keep explicit negative wording rather than using the positive-claim control.
- Forbidden patterns can inspect any scored answer field. The previous steps/tools-only
  restriction let obsolete instructions in the answer text escape detection.
- These are still lexical heuristics, not semantic equivalence tests or rubric decisions.
  Regression cases include both correct paraphrases and incorrect reversals, wrong actions,
  missing conditions and harmless warnings. Existing accepted items retain their decisions.
- A packet bound to obsolete checking/source digests remains as a record, but no longer
  prevents export of a replacement packet for the same pending draft. Import continues to
  reject stale decisions. No synthetic import is used to clear the old packet queue.
- SF-021's ProjectedCRS code excerpts now start one line earlier, showing the IFC2X3
  condition directly. Its narrow claim and assistant-drafted status are unchanged.
- The fixture slice gained 8 code spans that the corrected drafts and SF-021 cite, written by
  `snapshot fixtures` from new `fixture_code_spans` entries: at 0.8.5-post1
  `georeference/data.py` L104-L106, `georeference/operator.py` L26-L43 and L56-L63,
  `georeference/ui.py` L52-L62 and `core/georeference.py` L28-L36 and L48-L55; at
  0.9.0-post1 `georeference/data.py` L104-L106 and `project/ui.py` L383-L387.
- The follow-up revises 46 assistant drafts across the original packet review, including
  colour/status ownership, operation order, conditional advice and obsolete UI routes.
  The six accepted item bodies and all imported decisions remain unchanged. Replacement
  packets GP-011 to GP-015 contain all 104 pending items; SR-003 contains the expanded
  SF-021 evidence. Older packets are retained, not overwritten.
- Independent review found additional counterexamples after the first passing probe run;
  those concrete cases were corrected and retained as regressions. This does not establish
  general paraphrase equivalence or replace Chad's review, and no live Bonsai run is claimed.

### November 23, 2026: scoring fixes before the round-3 review

An independent assistant review of the round-3 commit (no decisions entered or imported)
found two scoring flaws: affirmative matching credited reversed claims written as "does not
A or B", "neither ... nor" or "does not mean you will", and forbidden stale-docs patterns
scanned across all fields counted answers that explain the docs-versus-code difference. 17
of its 65 probes on the pending drafts scored wrongly. Asked whether to fix the two flaws
before reviewing the round-3 packets, Chad chose "Fix first, then re-export (Recommended)".
This authorizes the fixes, redrafts and replacement packets; it accepts no draft.

Assistant's calls (not owner decisions):

- **`gold-check-v4`.** Affirmative matching has its own governance (`_governs_claim`):
  "or" and "nor" never cancel a negation, nor does "and" after a negated auxiliary
  ("won't tidy and delete"); "neither", "no longer" and bare "no" are cues; "does not mean
  (that) you will" governs the implied claim; "not false that" affirms; "Green means new?
  No, ..." negates the claim before the rebuttal. Descriptive negation also negates in
  affirmative mode: "is not available/drawn/shown/..." after the match, or a claim
  attributed to the docs and contrasted with "but", "however" or "whereas" in its
  sentence. A cue that is not an auxiliary still yields to "and" ("No need to save and green
  means new" still credits the claim). The unflagged forbidden rule is unchanged and still
  errs toward counting an attack.
- **Stale-docs forbidden patterns.** Of the two fixes the review offered, the assistant kept
  `any` and extended the descriptive negation (above) rather than limiting these patterns
  to `steps`. Limiting them would have let "Use Unload Project to complete this task." in
  the answer pass again, which the November 22 review had found. A new rule replaces the
  unreachable "forbidden pattern needs a scored field" check: a forbidden tool pattern (or
  `any_of` with a tool alternative), or one supported by a `conflict` quote, scores `steps` or
  `tools_required` unless every alternative is `affirmative`. Planted injection text is
  exempt. The November 22 claim that valid warnings remain allowed holds only for warnings
  and explanations that this cue rule recognises. Other descriptive forms (for example "the
  button was removed") can still count, and the judge handles them.
- **Control rules (G11).** `ordered` is accepted only on tokens (an `any_of` parent's flag
  must suit every alternative). `clause` is rejected on tool kinds and on a phrase or
  planted text that crosses a clause boundary. Under `clause` a colon no longer ends a clause,
  so "Green: new objects" matches, and punctuation ending a span ("Save As...") is not a
  boundary inside it.
- **Redrafts.** Only the 7 items whose patterns had to change were redrafted, as assistant
  drafts in lane batches: GS-MD-009 P4 adds click/select/hit/tap; GS-SD-030 P1 to P3 and
  GS-SH-015 P3 and P4 accept "objects appear in <colour>"; GS-MD-001 P4 and GS-MD-006 P8 add
  the passive "must be deleted/removed"; GS-SD-015 P4 adds "afterwards", "after that",
  "later" and "next"; GS-MH-005 P6 is affirmative throughout. GS-MH-001 was briefly
  redrafted with P7 on `steps` and then returned to its round-3 draft, which the new rule
  accepts. The six accepted items are byte-identical, and only the published files'
  `checker` and `digest` headers changed.
- **Checks.** The complete-set check over all 110 heads passes with the fixture-slice rule,
  offline and online, with the same two overlap warnings. The 17 failing probes and their
  controls are regression tests on synthetic patterns and items
  (`tests/test_gold_patterns_v4.py`). The round-3 probes (430) and whole-answer checks (22)
  give the same results on the new heads.
- **Packets.** GP-016 to GP-018 (58 development) and GP-019 and GP-020 (46 held-out) replace
  GP-011 to GP-015, which remain as obsolete records. SF-021 did not change, so SR-003 stays
  current. `gold status` lists every unimported packet with an obsolete context, including
  one whose drafts were all re-exported unchanged.

### November 23, 2026: affirmative-matching fixes after the gold-check-v4 review

An independent assistant review of the `gold-check-v4` commit (no decisions entered or
imported) found that the new affirmative governance had made the two stale-docs guards
(GS-MH-001 P7 and GS-MH-005 P6, the only forbidden patterns with `affirmative`) less strict,
which the entry above did not say, and that it rejected some correct required claims. This
follows from Chad's same decision, "Fix first, then re-export (Recommended)"; it accepts no
draft.

Assistant's calls (not owner decisions):

- **`gold-check-v5`: forbidden patterns keep the forbidden governance.** Under v4 an
  affirmative forbidden pattern used `_governs_claim`, so a negated auxiliary carried through
  "and": "Don't use the Git panel and open the Bonsai sidebar instead.", "Don't save first and
  click Unload Project to close it." and "You don't need the wizard and can just use Unload
  Project." no longer counted as following the stale docs (v3 counted them). v4 weakened
  these guards silently; v5 restores them. In affirmative mode a forbidden pattern's cue
  loop now uses the forbidden rule's `_governs`, where any coordinator cancels the negation.
  The descriptive, attribution and rebuttal checks still apply to it, since they are how an
  answer explains the stale docs. Required claims keep `_governs_claim`.
- **Required claims.** A bare "no" is not a cue in "no doubt", "no question" or "no matter"
  ("There is no doubt that green objects are new" is credited again). A negated auxiliary no
  longer carries through "and" when a new subject follows it: a pronoun, a determiner or a
  product name ("You do not have to do anything and Bonsai commits pending parametric drafts
  before saving" is credited again). Known limit: a bare noun-phrase subject after "and"
  ("... and green objects are new" after "do not") is not recognised, so the negation still
  reaches it. "no longer" stays a negated auxiliary ("Bonsai no longer cleans up and removes
  the default cube" is not credited), now pinned by a test.
- **Descriptive negation.** Also "does/did not exist", "doesn't exist", "no longer exists" and
  "is/was/has been removed, dropped or gone" after the match, and a docs claim followed by
  ", which ... no longer/not/never/n't". The words between the match and these forms are
  never a coordinator or a subordinator (and, or, if, when, once, until, ...), so "Use Unload
  Project once it is removed from the scene." still counts. "Unload Project does not exist in
  Bonsai 0.9.", "Unload Project was removed from the pinned code." and "The tutorial
  mentions an Unload Project button, which the pinned code no longer draws." no longer fail
  GS-MH-001's P7. Other wordings (for example "You won't find Unload Project") can still
  count; the judge handles them.
- **Items and checks.** No draft changed, and the six accepted items are byte-identical; only
  the published files' `checker` and `digest` headers changed. None of the accepted items
  uses the v3 controls, so their scores cannot change. The complete-set check over all 110
  heads passes offline and online with the same two overlap warnings. The round-3 probes
  (430) and whole-answer checks (22), the round-4 review's 65 probes and the v4 probe set give
  the same results as under v4, apart from the sentences above. The review's cases are
  regression tests on synthetic patterns (`tests/test_gold_patterns_v4.py`).
- **Packets.** GP-021 to GP-023 (58 development) and GP-024 and GP-025 (46 held-out) replace
  GP-016 to GP-020, which remain as obsolete records; they hold the same 104 drafts. SR-003
  stays current.

### November 23, 2026: narrow the ", which" contrast, stop patching, review

An independent assistant review of the `gold-check-v5` commit (no decisions entered or
imported) found that the new ", which ..." contrast accepted any negation in the relative
clause, so an answer that repeats the stale docs and endorses them ("The docs say to click
Unload Project, which never loses data, so do it.") no longer counted, and two correct
required claims ("The docs say green means new, which is not obvious at first.") were no
longer credited. It also found that the descriptive "is removed/gone" forms allowed a
subordinate clause before them ("Click Unload Project since nothing is removed."). Asked how to
handle the remaining ", which" flaw after four patch rounds, Chad chose "Narrow it, stop
patching, review (Recommended)": one small fix where the ", which" exemption applies only when
the negation is about the code or docs; review decisions stay valid across later scoring-only
checker changes, so there is no more re-export churn; meaning-level grading is left to Chad's
blind labels and the LLM judge, with pattern checks reported as heuristics; then the round-4
review starts. This accepts no draft.

Owner decision (Chad):

- Pattern checks are reported as heuristics; meaning-level grading is left to Chad's blind
  labels and the LLM judge. Patching stops after the one narrowing fix below ("stop
  patching"), and review decisions stay valid across later scoring-only checker changes.

Assistant's calls (not owner decisions):

- **`gold-check-v6`.** After a docs claim, ", which ..." negates the claim only when its
  subject is the code, the docs or the product: an optional "the" and "pinned", "current",
  "installed", "older" or "newer", then Bonsai, Blender, add-on, code, source, docs,
  documentation, manual, guide, tutorial, version, release, UI or interface, at most two
  further words of that kind or a version number ("Bonsai 0.9", "the Bonsai 0.9 add-on"),
  then "no longer", "never", "does/is/has/can/will not" or a contraction. "..., which the
  pinned code no longer draws" and "..., which Bonsai 0.9 does not have" explain the stale
  docs; "..., which never loses data", "..., which is not risky", "..., which you should not
  skip" and "..., which won't lose your work" count as following them, as under v4. "The docs
  say green means new, which is not obvious at first." and "..., which you should not
  ignore." are credited again. Known limit: other explanations in a relative clause ("...,
  which no longer exists in Bonsai 0.9") still count; the judge handles them.
- **Descriptive negation gap words.** The words between a match and "is/was removed", "is
  gone" or "does not exist" also exclude since, as, because, while, whenever, where, wherever,
  though, although and whether, so "Click Unload Project since/as nothing is removed.", "...
  because it was removed." and "Use Unload Project while nothing is removed." count again, as
  under v4. The November 23 v5 entry's "coordinator or subordinator" wording overstated the v5
  list; this list is the one in force. This went beyond the approved single ", which" fix;
  asked whether to keep it, Chad answered on November 23, 2026: "Keep it (Recommended)".
- **Review validity.** A packet's freshness binds to its drafts (content hash), their setups
  (`setup_sha256`), the lexicon, docs index, slot and pin digests, and `gold.REVIEW_CHECKER`,
  the last checker whose change could alter an item's content or derived fields
  (`gold-check-v5`). `gold.CHECKER` (now `gold-check-v6`) is the scoring version recorded in the
  published files' headers; changing it alone no longer makes a packet obsolete. The import
  still reruns the current check on every block, so a draft that the new check fails is
  stale, and a changed draft, setup or evidence digest stays stale. Decisions already bound to
  the draft and setup hashes, not to the checker. Bump `REVIEW_CHECKER` only for a check change
  that alters an item's content or derived fields. GP-006 to GP-020 stay obsolete records.
- **Items, packets and checks.** No draft changed, and the six accepted items are
  byte-identical; only the published files' `checker` and `digest` headers changed. GP-021 to
  GP-025 (104 drafts) and SR-003 stay current without re-export: `gold status` lists them as
  exported, not yet imported, and a read-only replay of the import's validation (tamper, stale
  digests, draft and setup hashes, current check) finds 0 stale blocks. The verifier's probes
  (the four endorsing relative clauses, the two required claims, the four subordinate
  "removed" clauses) and the intended explanations are regression tests
  (`tests/test_gold_patterns_v4.py`, `tests/test_gold_stale_export.py`). The complete-set
  check over all 110 heads passes.

### November 23, 2026: MP1 scope under review; gold review paused

Chad: "This project is about creating the data. The chat-bot feature is an additional
feature which may get moved to another Mini-Project. I'm investigating that now." Compared
with the course brief, the help chatbot (retrieval tools, step budget, security pass) and
the gold set (B3: reference answers, multi-part, injection, control and held-out items) go
beyond what Mini Project 1 requires; the brief's generator writes the seven-field items
directly and its only reference is the benchmark's category distribution. Asked whether the
round-4 gold review should go ahead meanwhile, Chad chose "Pause it (Recommended)". GP-021
to GP-025 and SR-003 stay valid and unimported. The plan is unchanged until Chad decides
the scope.

### November 23, 2026: MP1 scope revised; chatbot and gold set move to Mini Project 4

After reading the Mini Project 1 to 9 briefs, Chad chose a project map for the course
(MP2 as change requests paired with candidate patches: "I want MP2 to be the change
requests option.") and then said: "This plan is approved. Modify MP1 as needed." The plan
(`docs/MP1-BONSAI-HELP-CHATBOT.md`) is revised on that direction:

- **Scope.** Mini Project 1 creates and evaluates synthetic Q&A data, as the course brief
  asks. One structured generation prompt, parameterized by category and setup profile,
  writes each seven-field item from pinned doc sections (plan §7 Step 1). The generator is
  grounded from the baseline on; Phase B is one targeted, pre-registered change to that
  prompt for the worst segment and dimension.
- **Moved to Mini Project 4.** The help chatbot, the read-only tools `search_docs` and
  `get_doc_section`, the step budget, the security pass, and the gold set with its
  multi-part, injection, control and held-out items.
- **B3 withdrawn from MP1.** The gold-set tooling (`bonsai-help gold ...`), its tests and
  the 6 published items stay in this repository, frozen, as the seed for MP4's relevance
  labels. The paused gold packets GP-021 to GP-025 stay unimported; whether they are
  reviewed later is MP4's decision. SR-003 (fact row SF-021) is a setup review and stays
  an MP1 item, still pending. Gold rules in `AGENTS.md` still bind anything
  that touches `reference/gold/`.
- **Milestones.** B4 now includes the section sampler and generation prompt v1; B9 drops
  the security scorecard; B10's replay demo replays the pipeline, not a chatbot. The
  remaining estimate is about 30 hours (plan §9).
- **Kept.** B0 to B2 work, the setup profiles and fact table (a setup record travels with
  every item), the lexicons and checks, the six dimensions, thresholds, blind labels, the
  judge rules and every implementation rule in `AGENTS.md`.
- **Open.** O-7 (uniform 20% in place of the DIY benchmark) is now one of the questions for
  the instructor in Chad's project map. New O-8: the repository name still says "chatbot";
  it stays until Chad decides, because renaming changes the public URL.

## Open items (not yet decided)

| ID | Item | Plan default (applies until Chad decides) |
| --- | --- | --- |
| O-2 | Confirm the five categories in plan §5 | Use them as proposed: `bonsai_project_setup`, `bonsai_modeling`, `ifc_data_and_materials`, `model_exploration`, `files_versions_troubleshooting` |
| O-6 | Recheck the Unit 5 Module 2 exercises and the Unit 7 and Unit 8 Module 1 notebooks when they are published | Recheck at B4 and before B10 |
| O-7 | Distribution reference for category balance | Uniform 20% target; asked of the instructor (November 23) |
| O-8 | Repository name `mp1-bonsai-help-chatbot` names the chatbot, which moved to Mini Project 4 | Keep the name until Chad decides |

## Amendment rule

Any change to a course threshold or criterion is a new dated entry here, with its
reason. Original criteria are preserved; nothing is weakened silently.
