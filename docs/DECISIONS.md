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

### November 23, 2026: B4 generation and gate (assistant's calls)

These are the assistant's engineering calls, not owner decisions. They are heuristics and
defaults; Chad can overrule any of them, and a change is a new dated entry.

Plan decisions:

1. **Sampling source.** The sampler draws only from committed fixture-slice pages tagged
   with the slot's category, from the sources of the slot's version line. Generation,
   tests and the replay demo then run offline, and the judge and Chad can always see the
   cited text. The slice grows only through `snapshot fixtures`.
2. **Sections per slot.** Two Bonsai docs sections and at most one Blender Manual section,
   at most 1,200 words in total, chosen by a seeded RNG keyed on the run seed and the slot
   id. Developer and fragment tags are excluded.
3. **Citations outside the payload.** The model returns the item and the cited section
   ids; the envelope stores the citations and the payload stays exactly seven fields.
   Citing a section that was not offered is a D3 pre-check failure, not a schema failure.
4. **Embedding duplicates.** Embeddings come from the same configured endpoint with one
   recorded embedding model for every vector. A cosine of 0.92 or more drops the later
   item. The threshold is configurable and recorded in the gate report.
   *Correction (November 24, 2026):* "configurable" overstated the code. The threshold
   is fixed at 0.92 (`gate.DEFAULT_THRESHOLD`): no run-config key or command flag sets
   it, and a collection accepts a batch gate report only at that value. It is recorded
   in each gate report and each cross-batch screen. Changing it is a code change and a
   new dated entry.
   *Changed (November 24, 2026):* Chad chose "Separate embedding server (Recommended)", so
   embeddings may come from their own local endpoint (`embedding_base_url`; see "B5
   embedding server and key file" below).
5. **Pre-check values.** D1: answer of at least 60 words. D2: `safety_info` of at least 80
   characters and no generic phrase. D3: every `bim.*` id exists in the version line's
   Bonsai-source lexicon and every cited section was offered. D4: no refusal boilerplate.
   D5: question of at least 6 words and `equipment_problem` of at least 3. D6: every tip at
   least 30 characters, none generic, none a near-copy of a step (token Jaccard 0.8 or
   more). Unknown Blender operators or menu paths are recorded as evidence, never a drop.
   *Correction (November 24, 2026):* the D3 operator check reads only `tools_required`
   and `steps`, as plan §6.4 and the B4 plan state; a `bim.*` id in `answer`, `tips`,
   `safety_info`, `question` or `equipment_problem` is not checked. "Every `bim.*` id"
   above means every id in those two fields. The lexicon it uses changed on November 24,
   2026 (registered operators and macros only; see that day's assistant's calls).
6. **Category balance.** The slot plan is exactly balanced. The gate passes a batch when
   every category is at least 18% of the retained items.
7. **Slots and profiles.** A run of `count` items (a multiple of 5) gives each category
   `count/5` slots. Profiles come from the run's split (`development` or `assessed`), so
   no profile crosses splits.

Rulings made while building:

- **Profile cycling.** Profiles cycle through all profiles of the split within each
  category, so no category is tied to a fixed subset.
- **Generic phrases.** Phrases match on word boundaries. A field counts as generic only
  when fewer than 5 words remain after the phrases are removed, so specific text that
  contains a stock phrase is not dropped. The cost if wrong is that a few generic items
  reach the judge.
- **Gate input.** The gate accepts only complete or incomplete runs, requires the items
  to match the successful attempts exactly, and recomputes unoffered citations from the
  attempts, refusing a disagreement.
- **Collection seeds.** Each collection batch gets its own derived sampler seed, so
  batches do not repeat requests, and retained items are screened for near-duplicates
  across batches. Both are recorded in the manifest.
- **VL-older slots.** The fixture slice has no Blender 4.5 Manual pages for
  `bonsai_project_setup`, `bonsai_modeling` and `ifc_data_and_materials`, so those slots
  offer Bonsai sections only. The slice grows only through `snapshot fixtures`.
- **Hard kill.** A hard kill between a ledger append and its checkpoint leaves a run that
  resume refuses. Inspect it; never repair it (the `AGENTS.md` rule on leftover locks and
  tails).
  *Detail (November 24, 2026):* the exact windows and the refusal each one gives are in
  "B4 cleanup (assistant's calls)" below.

No live model run has happened. B5 needs a reachable local endpoint and Chad's go-ahead.

### November 24, 2026: hosted path refused; rubric moved to B5

The final review of the B4 branch (workflow run `wf_7ed4c7f4-6a3`) found two gaps that
needed Chad. A run config with `hosted: true` was accepted, and its `cost_cap_usd` was
only checked to be above zero; nothing counted spend or stopped a run at the cap (finding
1). The README marked B4 done including "Rubric", but no rubric exists, although plan §9
lists it for B4 and the departure was not recorded (finding 2). Chad answered on
November 24, 2026: "Refuse hosted for now; record the rubric as moved to B5".

Owner decisions (Chad):

- **Hosted path refused for now.** A run config with `hosted: true` is refused when it
  is loaded (`config.HostedRefused`, exit 2, before any request or run directory),
  whatever its URL, `hosted_authorization` or `cost_cap_usd`. It stays refused until Chad
  authorizes a hosted path with an enforced cost cap. The fields `hosted`,
  `hosted_authorization` and `cost_cap_usd` stay in the run-config schema and have no
  effect. This defers plan §8's documented hosted path for graders; it does not remove
  it, and the `AGENTS.md` rule (explicit, documented, authorized by Chad and cost-capped,
  never a silent fallback) is unchanged. `docs/PORTING-MAP.md` §4 item 15 stays future
  work.
- **Rubric moved from B4 to B5.** B4 delivered no rubric. The rubric (D1 to D6 with
  Bonsai anchors and targets; `docs/PORTING-MAP.md` names it `config/rubric.json`, pinned
  by hash) is now a B5 deliverable, so it exists before B6's labels, which carry the
  pinned rubric version. Plan §9 is changed on this direction: the B4 row drops "rubric"
  and the B5 row gains it. The hours are unchanged (B4 6, B5 2, 30 remaining): the plan
  treats hours as assumptions and sets no rule that moves them with a deliverable.

### November 24, 2026: B4 final-review fixes (assistant's calls)

The final review of the B4 branch (workflow run `wf_7ed4c7f4-6a3`: 46 raw findings, 30
after deduplication, 29 confirmed by three verifiers each, 3 refuted) led to the fixes
below. Apart from the hosted refusal, which carries out Chad's decision above, these are
the assistant's calls, not owner decisions; Chad can overrule any of them, and a change
is a new dated entry. Each fix arrived with a regression test that failed before it.

Generation, envelope and ledgers:

- **Bracketed citations.** A listed citation equal to an offered id inside exactly one
  pair of square brackets (`[id]`) counts as that offered section (`generate._offered_id`,
  used by generation, resume and the gate). This is the only normalization: an id never
  offered is never accepted, two pairs or unbalanced or other brackets stay unoffered,
  unoffered ids are reported as listed, and `cited_section_ids` keeps the model's text.
  Reason: the prompt shows each section under `[id]`, so copying the brackets is a
  formatting artifact, not a grounding defect, and it should not drop an item under D3.
- **Unserializable responses.** A completion whose raw response is not strict JSON (NaN,
  Infinity or a non-JSON value) is a failed attempt with `error_type`
  `UnserializableResponse`, the raw response kept as JSON text, even when the item itself
  validated. Reason: before, it raised, left an unknown outcome and exited 2; the evidence
  cannot be stored verbatim, so the item is not kept, but the attempt must be recorded.
- **Envelope failures.** A completion that validates but cannot be built into the item
  envelope is a failed attempt with `error_type` `EnvelopeInvalid` (a field and message
  summary without input values). Reason: a recorded failure uses up its attempt; an
  exception lost it.
- **Reported model id.** Only an unreported model id falls back to the configured model
  (non-assessed runs). A blank id the server reports fails as `EnvelopeInvalid`. Reason:
  silently replacing a reported value misstates provenance. Assessed runs still require
  the configured id (`ModelIdentityMismatch`).
- **Item timestamp.** The envelope gains the required field `generated_at` (ISO 8601 with a
  UTC offset), the same text as its attempt's `completed_at`; resume refuses a record whose
  `generated_at` differs from its attempt. `schema_version` stays `"1"`, because no
  assessed or submitted run exists. Reason: `AGENTS.md` and plan §7 Step 1 require a
  timestamp in the metadata; a pre-change `items.jsonl` now fails loudly.
- **Legacy `problem`.** Values of `problem` and `equipment_problem` that differ only in
  leading or trailing whitespace are no longer a conflict; any other difference still is.
  Reason: both are stripped to the same stored text, so rejecting them rejected no real
  conflict.
- **JSONL records end at LF only.** `tracing.read_records` no longer splits on U+2028,
  U+2029, U+0085 or a stray CR inside a string. Reason: `append_record` writes those
  characters unescaped, so a valid ledger became unreadable. Truncation detection is
  unchanged.

Run config and model client:

- **Hosted refusal mechanics.** The refusal is a `ConfigError`, not a `ValueError`, so the
  command shows its reason rather than a validation summary that names only "(root)". The
  earlier load-time hosted checks (https, `hosted_authorization`, `cost_cap_usd > 0`) are
  removed, because no hosted config reaches them.
- **`api_key_env` names a variable.** It must match `[A-Z_][A-Z0-9_]{0,63}`; lower-case
  names, which POSIX allows, are refused on purpose. The error never shows the value.
  Reason: a pasted key value was accepted at load (review focus 5); a mixed-case value is
  far more likely a key than a variable name.
- **Local-endpoint allowlist.** `base_url` must be `localhost`, or an IP in 127.0.0.0/8,
  10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, `::1` or fc00::/7, or the IPv4-mapped form of
  one of those IPv4 ranges. Link-local (169.254.0.0/16, fe80::/10), 6to4, Teredo, NAT64,
  documentation and benchmarking ranges and CGNAT 100.64.0.0/10 are refused, so a model
  reached over a Tailscale 100.x address is not supported. Reason: `is_private` accepted
  publicly routed 6to4 and Teredo addresses; link-local holds cloud metadata services and
  is not a plausible model host.
- **Credential echo fails the attempt.** A response whose parsed item or raw body
  contains the configured key is a failed attempt with `error_type` `CredentialEcho`, its
  raw body stored redacted and its item not kept; it counts against the slot's attempts
  and the initial-attempt figure. Reason: before, the item was silently rewritten with
  `[REDACTED]` and kept as valid, which stored text the model did not write.
- **Minimum key length 16.** `RunConfig.api_key()` and both model clients refuse a key
  shorter than 16 characters before any request, without echoing it. Placeholders such as
  `EMPTY` or `none` are refused even for a local server that ignores the key; use a long
  random placeholder. Reason: keys are scrubbed by exact match, so a short key would match
  ordinary words in generated text; matching whole tokens would still flag words.

Deterministic checks and the gate:

- **Menu paths match whole labels.** `menu_paths_known` compares each part of a path,
  after normalization, with whole lexicon labels, not substrings. Only the first part may
  carry lead-in prose and only the last part trailing prose, each ending at a label
  boundary; middle parts must match exactly. Reason: substring matching accepted almost
  any invented label that contained a short lexicon string ("pan", "port", "tool"). The
  check stays evidence only.
- **Chained paths.** A comma followed by a lowercase word ends one path ("Edit >
  Preferences, then Add-ons > Install"), and each piece with a separator is checked on its
  own; commas between capitalized labels do not split. Reason: so the stricter rule does
  not flag a realistic chained phrasing.
- **Detail text.** A `menu_paths_known` failure now reads "not in the pinned UI lexicons",
  because the lexicon is more than the Manual.
- **Menu lexicon widened.** The menu-path lexicon is the version line's Manual (menu paths
  and `:guilabel:` texts), its pinned Bonsai docs lexicon (menu and UI paths) and the
  Bonsai source labels and button texts. This goes beyond plan §6.4's "lexicon extracted
  from the pinned Manual". Reason: paths copied from offered Bonsai docs sections were
  reported as unknown.
- **`bim.*` lexicon is registered operators.** `bim_operators_known` (a D3 drop check)
  accepts only Bonsai-source entries of kind `operator` or `macro` with `registered`
  true. The 4 operator classes the add-on never registers and the 30 workspace tool ids
  (`bim.*_tool`) now fail it, so an item naming one in `tools_required` or `steps` is
  dropped; the `ui_texts` id union is removed (all its ids are registered operators).
  Reason: plan §6.4 asks for the operator lexicon, and workspace tools are not `bpy.ops`
  operators.
- **Wildcard Manual operators.** `blender_operators_known` reads the Manual's wildcard
  entries (`*.select_box`, `object.*clear`, `curve.primitive*add` and the like) as
  whole-id patterns where `*` matches `[a-z0-9_]*`. A deliberate loosening for these
  documented forms only; every other id is checked by exact membership. Reason:
  `view3d.select_box` and similar real ids were reported as unknown.
  *Correction (November 24, 2026, B4 cleanup):* `*` now stands for one or more whole
  underscore-separated words, never the empty string; see "B4 cleanup (assistant's
  calls)" below.
- **Per-check pass rates.** `gate-report.json` gains `pass_rates_per_check` (per check:
  dimension, `evidence_only`, evaluated, passed, failed, dropped, `pass_rate`) and
  `pass_rates_denominator` (schema-valid items entering the gate). The evidence-only set is
  one constant, `checks.EVIDENCE_ONLY` (`blender_operators_known`, `menu_paths_known`).
  Reason: plan §7 Step 2 asks for pass rates per check, and evidence-only failures were
  invisible in the aggregate. Every other report key is unchanged.

Collections and the commands:

- **Batch run IDs belong to the collection.** A new `collect` refuses before any write if
  any batch run ID `<collection-id>-b01` to `-bNN` within `--max-batches` already exists
  (exit 2, "choose another collection ID"). A batch run directory that appears after the
  collection started, or an existing batch manifest that differs from the collection's
  identity, is refused (exit 1) and never generated into or gated. Reason: a collection
  could gate, and so freeze, an unrelated run.
- **Gate report acceptance.** A batch gate report counts only with the collection's
  embedding model, `gate.DEFAULT_THRESHOLD` and `gate.DEFAULT_MIN_SHARE`; before binding a
  report, `collect` also reruns the per-item checks with the collection's lexicons and
  refuses any difference. Reason: a batch gated out of band with another embedder or
  lexicons was accepted.
- **Denominators from the ledgers.** Collection summaries recompute each gated batch's
  metrics and status from its hash-bound ledgers and refuse a batch whose manifest metrics,
  status or gate-report `run_status` disagree. Reason: the denominators came from an
  unverified manifest.
- **Preflight before writes.** `collect` checks the assessed-purpose model identity and the
  fixture slice before it creates the collection, so a refused start leaves the collection
  ID usable. The model-identity condition duplicates `generate_run`'s.
  *Correction (November 24, 2026, B4 cleanup):* the duplicate is gone; `collect` and
  `generate_run` both call `generate.check_assessed`.
- **Cross-batch exact duplicates against members.** A question that exactly repeats an
  accepted member's is dropped, and `duplicate_of` always names a member; before, a
  question of an item later dropped as a near-duplicate also counted. A collection
  recorded under the old rule could now fail its screen check; none is committed.
- **Saved evidence is exit 1.** A validation error raised while reading saved run evidence
  is reported as "saved run evidence fails validation: <fields>; inspect the run" with
  exit 1, not as "invalid run config" with exit 2. Ctrl-C exit 130 (evidence kept, continue
  with `--resume`) is unchanged and now tested.

Prompt and records:

- **Generator v1 completed before first use.** `prompts/generator-v1.md` now asks for the
  question phrased the way users ask (their own words, sometimes a half-remembered tool or
  menu name or an older BlenderBIM-era term), as plan §7 Step 1 item 2 specifies, while the
  answer names tools as the sections do; it also says to cite each id without the square
  brackets it is shown in. It stays v1: no committed run, test or record pins the earlier
  text (SHA-256 `42c5382e…`; then `ced95092…`, since updated below), and no recorded run used it. This entry is
  the iteration-log record for the change (date November 24, 2026; change and before/after
  hashes above; hypothesis: questions in users' own words test grounding better than
  questions copied from the docs; decision: keep the name v1, since nothing was measured
  with the earlier text; next step: the B5 baseline run) and carries into the B10
  iteration log. Reason: otherwise B5 would measure a prompt other than the plan's v1, and
  adding the instruction later would be a second change confounding Phase B.
  *Update (November 24, 2026, quote field):* after Chad's "Add a quote field." (entry
  "Quote field" below), v1 also asks for 1 to 3 short `quotes`, each copied exactly from a
  section the item cites, with that section's id without the brackets, and the reply
  shape gains the `quotes` list. It still fills only `{category}`, `{setup}` and
  `{sections}`. It stays v1 for the same reason: no recorded run used `ced95092…` either.
  Iteration-log record: date November 24, 2026; change: the quote instruction and the
  `quotes` key; before SHA-256 `ced9509239de5e4eb3889f2d297c7f1f89ba32166e0823c14645f48e553a2dd7`,
  after `04c6d155b534226f51b1256d787e8d715b073e1017e9533d5cd5ee62ec548b36`; hypothesis:
  asking for verbatim quotes makes an ungrounded answer visible as a failed D3 check
  instead of passing on an offered citation alone; decision: keep the name v1, since
  nothing was measured with either earlier text; next step: the B5 baseline run.
- **Porting map.** `evaluation_schemas` was not ported in B4, which has no consumer for
  it; it moves to B5–B6 with `assessment` and `labels`. `sources` is not ported: its
  snapshot-manifest role is covered by B1's `doc_sources` and `doc_snapshot` with
  `sampler.verify_fixtures`, and its per-slot context by `sampler`.
- **Departure recorded, not decided.** Plan §6.4's check that "any quoted passage must
  appear verbatim in the cited section" is not implemented: the item has no quote field,
  and B4 checks only that every cited section was offered. Whether to add a quote check
  (and for which fields) is open for Chad; it is not decided here.
  *Resolved (November 24, 2026):* Chad decided "Add a quote field."; the check is
  `quotes_verbatim` (entry "Quote field" below). This bullet stays as the record of the
  departure.

### November 24, 2026: B4 cleanup (assistant's calls)

After the final-review fixes, a cleanup pass took the fix-review notes (R1 to R12), the
per-task deferred minors (D1 to D6) and two leftovers (L1, L2). These are the
assistant's calls, not owner decisions; Chad can overrule any of them, and a change is a
new dated entry. Each fix arrived with a regression test that failed before it, except
L1 (dead configuration, nothing to fail) and the added tests for behaviour that was
already correct. No model run happened; the checks stay heuristics.

Checks made stricter:

- **Lead-in words (R5, `menu_paths_known`, evidence only).** A capitalized word just
  before the first menu label of a step counts as lead-in prose only if it is in
  `checks.LEAD_IN_WORDS` (open, go, click, right click, double click, select, choose,
  pick, use, press, navigate, find, locate, expand, switch, then, next, in, from, under,
  via); any other capitalized word there is part of an invented label ("Fabricated
  Settings > Export." is flagged). Leading tokens with no letters ("1)") are skipped, a
  small loosening for numbered steps. Every committed Manual and Bonsai docs path on both
  lines still passes, plain and as "Open {p}." or "Go to {p}.". Only the word just before
  the label is checked: it is lead-in prose when lowercase, or when it is the step's first
  word and in the list. *Follow-up:* loosened by N6 below (clause breaks, seven more words,
  two-word lead-ins).
- **Wildcards need a whole word (R7, `blender_operators_known`, evidence only).** A Manual
  wildcard `*` stands for one or more whole underscore-separated words, never the empty
  string. `object.clear`, `object.bogusclear` and `curve.primitiveadd` are now flagged.
  Accepted as the Manual's notation allows: `object.*clear` accepts any
  `object.<words>_clear`, an invented `object.bogus_clear` included, and
  `curve.primitive*add` and `surface.primitive*add` accept any `primitive_<words>_add`.
- **Unusable embedding vectors (D5, gate).** A zero or non-finite embedding vector is a
  `GateError` and no report is written, instead of a cosine of 0.0 that made such an item
  never a near duplicate.
- **Unusable cross-batch vectors (D5, collection).** The cross-batch screen refuses a zero
  or non-finite vector before scoring, matching the gate's own refusal:
  `CollectionError("cross-batch embedding returned a zero or non-finite vector")`, exit 1,
  with the batch's screen left unset for `--resume`. Before, such a vector scored a cosine
  of 0.0 against every member, so a broken embedding let an item through as never a near
  duplicate. This change came from the integration pass, not from a listed item.
- **Two successful attempts for one slot (D5, gate).** A second schema-valid attempt for
  the same slot or item ID is refused ("more than one successful attempt for slot ...;
  inspect the run") instead of being collapsed silently.
- **Gate report decisions re-derived (R11, collection).** Before a batch's gate report is
  bound to a collection, its retained flags, `dropped_by`, exact duplicates,
  `retained_ids`, `per_category`, `distribution.passed`, `input_count` and per-item
  category are re-derived from its already verified per-item checks. Near-duplicate drops
  stay trusted, but only for a check-passing item that is not an exact duplicate, with
  pairs that match. A mismatch is "gate report decisions differ from its per-item checks;
  inspect it" and the batch stays ungated.
- **Slot plan shape (R9, collection).** Each slot entry of a gated batch's run manifest
  must be an object with exactly the slot fields, all strings; otherwise "batch slot plan
  is malformed; inspect it", exit 1, instead of a traceback.
- **Implementation identity needs the project files (D3a, generation).**
  `implementation_identity` raises `FileNotFoundError` when `pyproject.toml` or `uv.lock`
  is missing beside `src/`, instead of leaving it out of the identity, so `generate` and
  `collect` refuse to start outside a repository checkout, before any write (exit 2,
  "cannot read uv.lock: missing; the implementation identity needs it beside src/ (run
  from the repository checkout)"). Reason: a missing lock silently weakened the code
  identity that resume and collection compare.
- **Prompt copy hash-checked (D3c, generation).** `validate_evidence`, on every start and
  resume, requires the run's `prompt.md` to exist and to hash to the manifest's
  `prompt_sha256` ("changed or missing prompt.md; preserve the run for inspection", exit 1).
  Reason: the copy is the evidence of the exact prompt sent. *Follow-up:* N5 below also
  binds the manifest's field to the fingerprinted prompt.
- **No start after a success (D3e, generation).** `validate_evidence` refuses a slot whose
  successful attempt is not its last request start ("a request start for <slot> follows
  after its successful completion"). `generate` never writes one, so only tampered or
  corrupt evidence is affected; before, it passed when the later attempt was missing or
  failed.
- **Escaped credential echo (R4, model client).** A key that appears JSON-escaped
  (`\uXXXX` or backslash escapes, up to 4 nested levels) anywhere in a response now counts
  as an echo: the attempt fails as `CredentialEcho`, and a stored string that holds the key
  only in escaped form is replaced whole with `[REDACTED: credential echo]`, because an
  escaped span cannot be cut out exactly. Plain-key redaction is unchanged, and clean
  content with ordinary escapes is kept verbatim. Before, the escaped key survived in
  `raw_response`, and "the raw response is kept redacted" was not true.
- **Committed manifest errors (D1, sampler).** A missing or unreadable
  `config/doc-manifest.json`, or a source absent from it, is a `FixtureError` (exit 1 under
  the generation commands, no paths in the text), instead of an `OSError` (exit 2) or an
  uncaught `KeyError` traceback.

Checks made looser:

- **Manual operator labels are UI labels (R6, `menu_paths_known`, evidence only).** The
  `label` of every Manual `blender_operator` and `operator_ref` entry (such as "Cube" for
  `mesh.primitive_cube_add`) joins the menu lexicon; null labels are skipped. Only labels
  the pinned Manual documents are added and whole-label matching is unchanged ("Bogus
  Cube" is still flagged). Some of these labels are section headings rather than exact UI
  strings ("Removing Drivers"), accepted because the check is evidence only.
- **`gate-items.jsonl` no longer freezes a run (L1, generation).** `generate.GATE_FILES` is
  now only `gate-report.json` (`gate.REPORT`). No code wrote or read `gate-items.jsonl`, so
  only a stray file by that name stops freezing a run; `gate-report.json` still does.

Other behaviour and interface changes:

- **Storing a raw value never raises (R2, generation).** A custom `ModelClient`'s raw value
  with a non-string key, a cycle, a `repr` that raises or very deep nesting is stored as
  text (JSON with a safe `repr` default, then `repr`, then `<unrepresentable TYPE>`) in a
  recorded `UnserializableResponse` attempt. Reason: an exception there left a start with
  no completion record. *Follow-up:* as first landed, only those cases were covered; N1
  below extends it to any exception (a mapping whose `items()` raises).
- **The interrupted checkpoint keeps the original error (D3d, generation).** If the
  "interrupted" checkpoint itself fails, the original exception propagates with the
  checkpoint failure added as a note, instead of being replaced by it; a second
  `KeyboardInterrupt` still propagates. Reason: the original error is the one to inspect.
  *Follow-up:* N2 below makes the CLI print that note.
- **Cut multi-byte characters (R3, tracing).** `read_records` decodes each line inside the
  same error mapping, so a record cut inside a UTF-8 character reads "invalid JSONL record
  at <file>:<n>; preserve and inspect it" instead of a bare `UnicodeDecodeError`. Same
  detection; records still end only at LF.
- **Freeze receipt first (D6, cohort).** `freeze_cohort` writes the collection's
  `frozen.json` before `cohort.json`. A failed cohort write now leaves a frozen collection
  with a missing cohort to inspect ("collection already frozen; inspect the existing
  cohort", "no cohort", and `collect --resume` refused), never a collection free to freeze
  a second cohort under another ID.
- **Shared checks (R10, D6).** `generate.check_count` and `generate.check_assessed` are
  public; `generate_run` and `collect` both call them, so the copied assessed-purpose
  refusal is gone. The private `_check_count` was removed, not kept as an alias: nothing
  calls it, because `collection` now calls `generate.check_count`.
- **Sampler interface (D1).** `sampler.MANIFEST` derives from `config.REPOSITORY`, so the
  checkout root is defined once, and the undocumented `manifest` keyword of
  `verify_fixtures` and `fixture_sections` is removed: the sampler always verifies against
  the committed manifest. The tool runs from its checkout and is not supported as an
  installed wheel.
- **Shared client plumbing (D2, model client).** The chat and embedding clients share one
  settings check, one SDK constructor (no SDK retries, no redirects, `trust_env=False`) and
  one credential redactor, so embedding error messages also get the escaped-echo
  redaction. Proxy tests cover `HTTP_PROXY`, `HTTPS_PROXY` (on an https endpoint, the only
  scheme httpx maps it to) and `ALL_PROXY` for both clients.
- **Tests added for behaviour already correct.** Transport failures through
  `InstructorClient` (one HTTP request per attempt, each a recorded failure, no unknown
  outcome; D3f); code identity on a copied tree, where an edited or added module makes a
  resume refuse (D3b); resume after a gate or cross-batch embedding failure regenerates and
  requests nothing (D6); an item failing only the evidence-only checks is not dropped (R8,
  replacing a test that restated `checks.EVIDENCE_ONLY`); renamed and added gate tests for
  complete and really incomplete runs (D5).

Hard-kill windows (D3, documented, behaviour unchanged). Every ledger write is
`append_record` (fsync) followed by an atomic manifest checkpoint (temp file, fsync,
`os.replace`) that records `artifacts_sha256`. A hard kill (SIGKILL, power loss) can land
(1) after a `starts.jsonl` append, before its checkpoint; (2) after an `attempts.jsonl`
append, before the `items.jsonl` append or the checkpoint; (3) after an `items.jsonl`
append, before its checkpoint (also inside `recover_items` on resume); (4) in the middle
of an append; (5) between creating a new run's directory, ledgers and `prompt.md` and its
first `manifest.json`. `.generation.lock` stays, so resume first fails with "lock
.generation.lock present: a writer is active; inspect" (exit 1). With the lock inspected
and removed, cases 1 to 3 fail with "changed or missing <ledger>; preserve the run for
inspection" (exit 1). Case 4 fails with "invalid JSONL record at <file>:<n>; preserve and
inspect it" (exit 1) when the cut falls inside the JSON object; when the cut loses only the
final newline, the line still reads as a record and the hash check fails instead, with
"changed or missing <ledger>" as in cases 1 to 3. Case 5 leaves a directory with no
manifest: resume says "no run ... to resume" and a new run with that ID is refused because
the directory exists (exit 2). `manifest.json` is never partial, but a temp file may be
left in the run directory. A failed "interrupted" checkpoint leaves a run that resume
refuses only when a ledger append came before it without its own checkpoint (the state of
cases 1 to 3), with the checkpoint failure noted on the original exception. When the
interrupt came after the last checkpoint, for example during the model call that follows
a checkpointed start, the manifest still holds the correct hashes with status `running`,
and that run resumes normally. Nothing repairs a refused run: inspect it and choose a new
run ID.

Kept as is (no behaviour change):

- **`schema_version` stays "1" (R1).** The envelope change is recorded above (Item
  timestamp); no code reads or dispatches on a manifest's `schema_version` and no run
  exists, so a bump to "2" across four writers would protect no reader.
- **Generic residual counts every word (D4).** Not counting filler words toward the
  5-word residual would make `tip_not_generic` and `safety_not_generic`, which drop items,
  stricter and would drop short specific text ("Be careful with Purge: it deletes unused
  types." and "Take your time to set the CRS before the false origin.", both pinned by a
  test). The cost: padded generic text passes too. "Be careful and take your time and
  always remember to be safe." and "Take your time and be careful, it is really very
  important." both pass `tip_not_generic` today, while "Good luck, take your time!" is
  still dropped. Such an item reaches the judge, where D2 and D6 are graded anyway.
- **Readiness ignores the 95% figure (D6).** Readiness means enough retained items and
  every category at its minimum; initial-attempt validity is reported separately, as
  `AGENTS.md` requires, and gating readiness on it would mix two denominators.
- **Exit 3 has two meanings (D6).** Controlled exhaustion for the generation commands,
  git or network failure for the snapshot commands; both docstrings say so and the
  generation codes are pinned by tests.
- **Evidence errors classified by function name (D6).** `collection_cli` tells saved-evidence
  errors (exit 1) from settings errors (exit 2) by the raising functions in
  `EVIDENCE_FUNCTIONS`. It works and is tested; a shared `EvidenceError` would have to wrap
  pydantic validation errors across `tracing`, `generate` and `gate`, a redesign no need
  calls for.
- **`cli` imports `collection_cli` eagerly (D6).** argparse needs the subcommands on every
  invocation, `--help` included; the cost is about 0.29 s of startup.
- **The cross-batch screen re-embeds all accepted members (D6).** It keeps every vector
  from the one configured embedder and stores none that could go stale; the cost is
  bounded by `--max-batches` times the batch size.
- **Resealed cross-batch decisions (D6).** The collection manifest's self-digest catches
  accidental edits, not a deliberate reseal. Recorded near-duplicate decisions are checked
  for structure and consistency but cannot be re-scored without an endpoint.

Documentation: the README status no longer says B3 is in progress (L2), and the
"Generator v1 completed before first use" entry above already serves as the
iteration-log record for that prompt change (R12).

Follow-up review (same day, notes N1 to N12). A review of the cleanup found five behaviour
faults and seven documentation faults. The behaviour fixes are assistant's calls like the
rest of this entry, each with a regression test written first; the documentation fixes
are folded into the text above (the shared checks, the unusable cross-batch vectors, the
hard-kill windows and the generic residual).

- **Storing a raw value never raises, for any exception (N1, generation).** The JSON
  check in `_storable` and the JSON step of `_spelled` now catch any `Exception`, not only
  `TypeError`, `ValueError` and `RecursionError`. A custom client's mapping whose
  `items()` raises is stored as its `repr` in an `UnserializableResponse` attempt, so the
  R2 bullet above now holds for every exception, not only for the cases it named; before,
  that error escaped and left a start with no completion record.
- **Error lines carry exception notes (N2, collection CLI).** Every `error:` line of the
  generation commands now ends with the exception's notes, scrubbed of the key and joined
  on one line. A Ctrl-C whose "interrupted" checkpoint also failed prints
  "error: interrupted; the interrupted checkpoint also failed (...); preserve the run for
  inspection" (exit 130) without the "continue with --resume" advice, because resume may
  refuse that run. Before, the CLI hid the checkpoint failure and advised a resume.
- **Prompt hash bound to the fingerprint (N5, generation, stricter).** `validate_evidence`
  also requires the manifest's `prompt_sha256` field to equal the hash of the prompt the
  run is started or resumed with, which the fingerprint binds ("manifest prompt_sha256
  differs from the run's prompt; preserve the run for inspection", exit 1). Before, editing
  `prompt.md` and that unsealed field together passed the D3c check. Only tampered evidence
  is affected.
- **Lead-in clause breaks and more lead-in words (N6, `menu_paths_known`, evidence only,
  looser).** The step's first word may also end in "," or ":" (a clause break) right
  before the first label, so "Finally, File > Export." and "Now, Object > Apply > Scale."
  pass; `LEAD_IN_WORDS` gains now, finally, first, also, using, access and enter ("Using
  Edit > Preferences > Add-ons, enable it.", "Access File > Export."); and a two-word
  lead-in from the list may open the step, so "Right Click Object > Apply > Scale." and
  "Double Click ..." pass. Reason: R5's closed list flagged ordinary step openings that
  passed before, telling the judge that documented menus were unknown. Cost: any
  capitalized first word followed by a comma now counts as prose, so "Bogus, File >
  Export." passes. An invented word next to the label is still flagged ("Finally, Bogus
  File > Export.", "Right Click Bogus Object > Apply."), and only the word just before the
  label is checked ("Then Open Object > Apply > Scale." is still flagged).
- **Malformed gate report shapes are a refusal (N9, collection, stricter).** Before a
  batch's gate report is adopted (and before its settings are compared), the parts the R11
  re-derivation reads must have the types the gate writes: `per_item` an object of
  objects, `distribution` an object, `near_duplicates` a list of objects whose `kept` and
  `dropped` are text. A missing or other-typed value gives "gate report decisions differ
  from its per-item checks; inspect it" (exit 1) instead of a `TypeError` traceback from
  `collect --resume`; a missing `near_duplicates` no longer reads as an empty list. Only a
  hand-edited report can trigger it.

### November 24, 2026: quote field

Plan §6.4 says "Cited doc sections must exist in the snapshot, and any quoted passage must
appear verbatim in the cited section". B4 recorded this as a departure open for Chad (B4
final-review fixes, "Departure recorded, not decided"). Chad decided on November 24, 2026:
"Add a quote field."

Owner decision (Chad):

- **Quote field.** Chad's words are "Add a quote field." His decision is to add the
  field. The check below carries out plan §6.4's existing rule that "any quoted passage
  must appear verbatim in the cited section"; it is the plan's requirement, applied
  through the assistant's calls that follow, not a further owner decision. Together they
  resolve the §6.4 departure.

Assistant's calls applying it (not owner decisions; Chad can overrule any of them, and a
change is a new dated entry):

- **Quote count.** The prompt asks for 1 to 3 quotes; the schema requires at least one
  and sets no upper bound, so a fourth quote is accepted and checked like the others.
  Reason: a cap would turn an over-eager but grounded reply into a schema failure.

- **Quotes are metadata.** The payload stays exactly seven fields. `GenerationOutput`
  gains a required `quotes` list (at least one) of `Quote` objects with exactly
  `section_id` and `text`, both nonblank strict strings; a missing or empty list, an extra
  key or a blank value fails the schema, like any other malformed output. The envelope
  (`GeneratedItem`) gains `quotes` (at least one): each quote's `section_id` resolved
  through the same single bracket normalization as a cited id (`generate._offered_id`,
  via `generate.resolve_quotes`), an id that does not resolve kept as listed, and its
  text as the model wrote it. The schema's `NonBlank` type strips surrounding whitespace,
  as it does for every payload string, so "as written" means the stripped text; nothing
  else (no NFC, no whitespace collapse) is applied before storage. The attempt record
  keeps the model's quotes as returned under `quotes`, beside `cited_section_ids`.
- **Check `quotes_verbatim`, D3, drop.** A fabricated quote is a grounding defect, like
  an unoffered citation, so it drops the item. An item passes only if every quote (a)
  names a section among the item's cited sections, (b) has at least 5 words
  (`checks.MIN_QUOTE_WORDS`), (c) occurs in that section's offered text, both compared
  after Unicode NFC with every whitespace run collapsed to one space (case and
  punctuation are compared as they are), and (d) starts and ends on word boundaries: a
  quote that begins or ends with a word character must not continue a word of the
  section, so a partial-word match fails. Any one occurrence that meets (d) passes. The
  detail lists each failing quote by index and reason ("quote 1: not verbatim in its
  section", "quote 0: 4 words, need 5", "section '...' is offered but not cited", "was
  not offered", "starts or ends inside a word of its section"); quote text is never
  repeated, and an echoed section id is cut at 80 characters. Reason for D3: plan §6.4
  lists the quote check with the citation and lexicon checks that feed tool realism, and
  the existing grounding check (`cited_sections_offered`) is D3. Cost if wrong: a
  correct item whose model reformatted a passage (changed case, dropped RST markup,
  joined two sentences) is dropped; the gate report counts these per check, so the cost
  is visible at B5.
- **What a word is, for quotes.** Only tokens with a letter or digit count toward the
  5-word minimum, so RST underlines and bullets do not. For boundaries, `.`, `_`, `'`,
  `’`, `-`, `/`, `+` and `:` join the characters on either side into one token when both
  are word characters (`bim.add_wall`, `model.ifc`, `4.5`, `Ctrl+S`, `EPSG:7856`), and
  `,` joins only between two digits (`5,000`); next to a space or the text's edge they
  are boundaries (a sentence-final period, `Ctrl + S`, `Note:`). A quote that starts or
  ends inside such a token fails. A scan of every 5- to 12-token window of all 584
  eligible fixture sections (562,866 quotes) found no verbatim quote failed. Known gap,
  kept: a quote may still drop a leading sign or a trailing unit (`Y axis` from `+Y
  axis`, `3.1` from `-3.1`, `100` from `100%`) or a Windows path prefix; the text stays
  verbatim, and a changed meaning is for Chad's labels and the judge, not this heuristic.
- **Section text is re-derived, never stored.** The check compares against the section
  text exactly as `sampler.render_sections` offered it, re-read at check time by
  `sampler.section_texts` from the fixture slice, with the page checked against the
  offered page hash and against the committed manifest's hash and pin for that page.
  The gate (`gate.item_checks`) and the collection's gate-report verification both go
  through that one function, so a gate report is adopted only if its checks, the quote
  check included, rerun identically on the collection's fixture slice. `bonsai-help
  gate` therefore gains `--fixtures-dir` (default `tests/fixtures/docs`, as for
  `generate` and `collect`); a changed fixture page stops the gate with a fixture error
  (exit 1) and no report.
- **Quotes are bound to their attempt.** Resume (`validate_evidence`) and the gate
  (`_load_run`) re-derive the envelope's quotes from the attempt's `quotes` and refuse a
  difference ("recorded quotes differ from the attempt's quotes"; "item ... has quotes
  that differ from its attempt"), as they already do for citations.
- **Prompt.** `prompts/generator-v1.md` asks for 1 to 3 short quotes; recorded as an
  update of "Generator v1 completed before first use" above, with both hashes, rather
  than a new prompt version.
- **Tests.** Synthetic model outputs in the tests quote words copied from the fixture
  sections they cite (`tests/fakes.py`, `fixture_quote`), so the existing gate and
  collection tests keep passing the new check for the reason they did before. Schema and
  model-client tests, which cite ids that are not fixture sections and never run the
  check, carry one clearly synthetic quote.

### November 24, 2026: B5 embedding server and key file

B5 starts the rubric and prepares the baseline run (plan §9 B5; plan file
`docs/superpowers/plans/2026-11-24-b5-rubric-and-baseline.md`). Chad answered two setup
questions on November 24, 2026.

Owner decisions (Chad):

- **Embeddings.** Chad chose "Separate embedding server (Recommended)". Embeddings may come
  from their own local OpenAI-compatible server instead of the chat endpoint. This changes
  B4 plan decision 4 ("Embeddings come from the same configured endpoint"). The same-model
  rule stays: one recorded embedding model for every vector.
- **Key.** On the API key, Chad answered "Yes, use that file". The run config reads the
  chat server's existing key file by path (`api_key_file`). That path, and any address or
  other machine detail, stays in the git-ignored local run config and never enters the
  repository. Local run configs for the smoke and baseline runs now exist outside Git
  (git-ignored `config/*.local.json`); their contents are not recorded here.

No model run has happened. The baseline run still needs Chad's go-ahead and servers that
are already reachable.

### November 24, 2026: B5 rubric and embedding endpoint (assistant's calls)

These are the assistant's calls, not owner decisions. Chad can overrule any of them, and a
change is a new dated entry.

Rubric (`config/rubric.json`, version `bonsai-rubric-v1`, sha256
`3d15baa13d7cda1ae80d7427ae525782b7c8da7bd0dcfa196aa68fa24a8f5cab`, after the
two wording changes below):

- **Status `assistant_drafted`, pending Chad's decision.** The rubric is a draft until Chad
  accepts, edits or rejects it. The allowed statuses are `assistant_drafted` and
  `chad_accepted`. `chad_accepted` needs a review record (`decided_on`, `words`,
  `decisions_entry`) that points to a dated entry here in his own words, and
  `assistant_drafted` may not carry one. An assistant never sets `chad_accepted`. While the
  rubric is a draft, `rubric check` and `rubric show` exit 0 and print a warning.
- **Wording drawn from plan §6.2.** Each dimension's pass anchor restates the plan §6.2
  "Passes when" text. The fail anchor is its converse, and D2 draws on plan §6.3. The
  §6.3 hazards are listed as examples of the kind, not as an answer key, with the §6.3
  condition in its own words: each "is used in scoring only after it is confirmed against
  the docs, with the page cited". The rubric holds no URL, no owner or instructor string
  and no text from the earlier repository.
- **D2 confirmation applies to the typical hazards only (wording change, pending Chad's
  review of the rubric).** The first draft widened the §6.3 condition to every risk: its
  fail pattern made any risk that no cited page confirms a D2 fail, "even when it is one
  of the typical hazards". Plan §6.3 attaches the condition to the typical candidates it
  lists and says "An answer passes D2 when it names the hazard that applies to its own
  steps." The D2 notes now say: only the §6.3 typical hazards need confirmation against
  the docs, with the page cited; another risk passes when the labeler can recognise it from
  the item's own steps and setup record. The fail pattern is an unconfirmed typical hazard,
  or another risk the labeler cannot recognise from the item's steps and setup record as a
  real risk of those steps.
- **Course names, matched exactly.** The names follow the plan §6.2 "Course name" column
  and `AGENTS.md` Criteria in sentence case ("Tool realism" for D3). `load_rubric` matches
  them exactly (case-sensitive) and refuses any other casing, spacing or wording, so a
  casing change cannot slip in and move the hash. The first draft matched them without
  regard to case; that was withdrawn. If the course brief writes them in title case, the
  names and `rubric.COURSE_NAMES` change together under a new rubric version. There is no
  `original_name` or adaptation field.
- **Labeling notes are the assistant's readings within the plan's wording.**
  - A name that the cited sections do not show passes D3 only if the labeler can confirm it
    exists in the stated version. An unconfirmed name is not a pass.
  - Versions stated only in the question do not satisfy D5.
  - A tip that the cited sections contradict does not count as the passing D6 tip.
  - A correct "cannot be done, do this instead" answer passes D1, and its scope is judged
    under D4.
  - A read-only task still needs a task-specific risk for D2.
  - **No skipping (wording change, pending Chad's review of the rubric).** The first draft
    told a labeler who could not decide a dimension to skip the item. A skipped item
    leaves its arm's denominator, and the items hardest to judge are likely to be the
    flawed ones, so skipping biases the failure rate down. Labeling rule 4 now says: decide
    every dimension of every item from the anchors and labeling notes; a dimension that
    truly cannot be decided from the item, its setup record and its cited sections is
    recorded as unresolved and reported, never counted as a pass, and the item stays in
    its arm's denominator ("A missing judgment is unresolved, not a pass", `AGENTS.md`).
- **Threshold encoding.** The per-dimension minimums are 0.85, 0.90, 0.95, 0.95, 0.90 and
  0.85, and the course thresholds of `AGENTS.md` are encoded in the file:
  - structural validity 0.95 on initial attempts;
  - baseline failure 0.15, reported honestly, with a zero baseline leaving the reduction
    undefined;
  - agreement 0.80 per dimension in Phase A, before Phase B;
  - corrected pass 0.80;
  - relative reduction strictly greater than 0.80, where exactly 0.80 does not pass;
  - 20 blind labels per arm and 50 retained items per run;
  - 95% intervals beside every rate.

  `load_rubric` refuses any threshold that differs from the course value, stricter or
  weaker. An amendment therefore needs a dated entry here, a new rubric version and a
  change to `rubric.COURSE_MINIMUMS` / `COURSE_THRESHOLDS`, so no threshold can change
  silently.
- **Overall pass.** `overall_pass` returns `False` when any present decision is 0: an item
  "passes overall only if it passes all six", so one fail settles it whatever the missing
  decisions turn out to be. It returns `None` (unresolved) only when no decision is 0 and
  at least one is missing, and `True` only with all six present and 1. `None` is never
  counted as a pass. (The first draft returned `None` whenever a decision was missing,
  even beside a 0; that hid certain failures as unresolved.)
- **Exact reduction.** `relative_reduction` takes exact failure rates only (a `Fraction`
  built from counts, or an `int`) and refuses a float with `TypeError`. A float is exact
  only for some decimals: 10/21 against 2/21 is exactly 0.80, but as floats it compares
  above 0.80 and would pass. With exact rates the strict 0.80 boundary holds for every
  count (10/21 against 2/21, or 35/63 against 7/63, does not pass). The `minimum` is the
  rubric's decimal threshold, so its float is read by its shortest decimal form (0.8 is
  4/5).
- **Label values.** `label_values` must be the integers `[0, 1]`; booleans or floats such
  as `[false, true]` are refused, so they cannot change the canonical dump or the hash.
- **Hash.** `rubric_sha256` hashes the validated rubric as sorted-key compact JSON, not the
  file bytes. Reformatting the file keeps the hash, and any change of content alters it.
  Labels (B6) will pin the version and this hash.
- **Exit codes.** Invalid content (JSON, shape or a course departure) is exit 1, because
  the rubric is what is being checked. A missing or unreadable file, or a usage error, is
  exit 2. Errors name only the file, never its absolute path.
- **Drift test.** `tests/test_rubric_pipeline.py` checks that the deterministic checks'
  dimensions are the rubric's D1–D6. It also checks that the collection's default retained
  target (in `collect` and on the command line) equals the rubric's 50 per run, and that a
  frozen cohort holds at least that many. Collection and cohort do not yet read their
  defaults from the rubric at run time; that is left to the B5–B7 stages that consume it.

Embedding endpoint (applying Chad's decision above):

- **Fields.** `RunConfig` gains `embedding_base_url` and the credential fields
  `embedding_api_key_env` and `embedding_api_key_file`.
  - With no `embedding_base_url`, embeddings use `base_url`.
  - At most one of the two credential fields may be set. With neither, the embedding
    client uses the chat credential source.
- **Same rules for the embedding endpoint.** The hosted refusal still comes first. The
  embedding URL then passes the same check as `base_url`: local hosts only, a `/v1`
  suffix, no credentials, query or fragment. The variable-name rule and the 16-character
  minimum apply to the embedding key as well. Messages name the field, never the value.
  A missing, unreadable or short key names which key it is ("the embedding API key must be
  at least 16 characters", or "chat"), never its value; with a shared credential the
  embedding client reads the chat key, so the message names the chat key.
- **Run identity.**
  - `public_settings()` leaves out all four credential fields: no value, variable name or
    path.
  - It records `embedding_base_url` as the endpoint actually used, so omitting the field
    and setting it equal to `base_url` give the same identity.
  - It records `embedding_authentication` as `shared`, `environment` or `file`.
  - Resume of a run or a collection, and adoption of a batch, refuse a changed embedding
    endpoint or a changed embedding credential-source kind.
- **Recorded where it is used.**
  - The gate report and each cross-batch screen store `embedding_base_url`.
    `evaluate_gate` and `gate_run` take it as a required keyword, so no report is written
    without it.
  - A collection refuses a gate report or screen made with another embedding endpoint. A
    report from before this change, which has no `embedding_base_url`, is refused instead
    of raising a `KeyError`.
- **Which key each command reads.**
  - `generate` reads only the chat key.
  - `gate` reads only the embedding key, which is the chat key when shared.
  - `collect` reads both before anything is written.
  - Both keys are scrubbed from error output.
- **Error text.** A run config refused as a whole now shows its fixed reason, which names
  fields and never values: "invalid run config: (root) (embedding_base_url: only loopback
  ...)".
- **Example config.** `config/run.example.json` shows `"embedding_base_url":
  "http://127.0.0.1:8081/v1"`.
- **Old runs.** Runs and collections started before this change cannot be resumed under
  the new settings identity. The code identity already refuses that after any code change,
  and no live model run exists yet.

B5 plan (`docs/superpowers/plans/2026-11-24-b5-rubric-and-baseline.md`):

- **Intervals need code.** `AGENTS.md` asks for a 95% interval beside every rate. The
  baseline report therefore needs the Clopper–Pearson part of the `stats` extract, which
  PORTING-MAP §8 schedules for B7. The plan moves that part forward to B5. It is not built
  yet.
- **Smoke first.** A smoke run (`purpose` `smoke`, development split, 5 items) checks both
  servers and the schema before the baseline collection. It is diagnostic only and never
  counts toward the baseline.
- **No failure rate from the gate.** "Honest failure rate" (plan §9 B5) is reported only
  once Chad's labels (B6) and the calibrated judge (B7) exist. It is never estimated from
  gate drops.

### Open questions for Chad (B5)

1. **Split of the measured runs.** The plan and `AGENTS.md` do not name the split the
   baseline run uses. They require that no profile leaks between the development and
   assessed sets, that judge v2 examples come from development disagreements, that Phase A
   calibrates on the baseline items, and that the two arms are compared.
   - The assistant recommends the assessed split (6 profiles) for both `baseline` and
     `corrected`, with smoke runs and any items labeled only to draw judge v2 examples on
     the development split (12 profiles). The two arms then share their profiles, and
     judge examples cannot leak into the measured agreement. The cost is more labeling for
     judge v2.
   - The alternative is both arms on the development split. That labels fewer items, but
     the assessed split goes unused in MP1, and the v2 examples would come from the items
     whose agreement they are meant to raise.

   **Decided by Chad on November 24, 2026:** "Assessed split (Recommended)". Both
   measured arms (`baseline`, `corrected`) run on the assessed split; smoke runs and any
   items labeled only to draw judge v2 examples run on the development split.
2. **Rubric.** Accept, edit or reject `config/rubric.json` (anchors, labeling notes and
   borderline rulings) before B6's labels, including the two wording changes above (D2
   confirmation for the typical hazards only; no skipping). Also confirm the casing of the
   dimension names: the rubric uses the plan's sentence case ("Answer completeness") and
   `load_rubric` accepts only that exact spelling; if the course brief writes them in title
   case ("Answer Completeness"), say which to use. A change needs a new rubric version and
   changes the rubric hash.
3. **Go-ahead.** Approve the smoke run and then the baseline collection, once both servers
   are reachable.
   Chad's instruction on November 24, 2026 was "Go on B5."; the smoke run and then the
   baseline collection proceed under it, each only against servers that are already
   reachable.

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
