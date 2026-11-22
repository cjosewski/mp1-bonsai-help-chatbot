# Decision log

Dated record of owner decisions for this repository. The owner is Chad Josewski. His
words are quoted where they were given. Decisions are owner-reported: no outside
approval is implied. Open items keep the plan's default, stated as a default, until
Chad decides them.

The plan is `docs/MP1-BONSAI-HELP-CHATBOT.md` ("proposed plan, not started"). Its
section numbers (§) and open-item IDs (O-1 to O-7) are used below. The plan changes
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
  nothing in the pin addresses it; `cited` or `partly_cited` when pinned text states the
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
  large filesize" sentence), or the claim was reworded to its quote (SF-011). This is still
  an assistant reading, checked by Chad at B3, not by a machine.
- **Profile values and split.** `ifc_schema` values are cited (SF-007) for a new project
  only, so the enum's basis is `partly cited` with `cited_for: ["new_project"]`, a basis
  value that must name its fact rows, its cited model states and a note; for opened and
  federated models IFC4X3 is an assistant default (the quickstart
  names IFC2X3 and IFC4 as the commonly seen schemas, SF-009). `model_state` values are
  the plan §4 wording, and `discipline` values (architecture, structure,
  building services) are an assistant default: the plan names the field, not its values.
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
  project only. Keep IFC4X3 in the `opened_ifc` and `large_federated_model` profiles
  (SP-08, SP-09, SP-17, SP-18) as an assistant default, or drop it there?
- **A Blender 4.2 Manual pin** (`blender-v4.2-release`) would make Blender-side facts for
  `VL-older` citable. It is an option, not a default.
- **Bonsai keymap hotkeys.** The docs' `:kbd:` roles cover some shortcuts only. Extract
  the keymaps for D3?
- **Review** every fact row, profile and version line (all `assistant_drafted`; for a
  line, its source mapping, `pairing_status`, `pairing_note` and `claims`) and the
  `not_citable` list.

## Open items (not yet decided)

| ID | Item | Plan default (applies until Chad decides) |
| --- | --- | --- |
| O-2 | Confirm the five categories in plan §5 | Use them as proposed: `bonsai_project_setup`, `bonsai_modeling`, `ifc_data_and_materials`, `model_exploration`, `files_versions_troubleshooting` |
| O-3 | Setup profiles: include Blender 4.2 LTS with Bonsai 0.8.5-post1, or only Blender 5.x with Bonsai 0.9.0 | Include it, as the older-release contrast (applied as the default at B2, see above) |
| O-6 | Recheck the Unit 5 Module 2 exercises and the Unit 7 and Unit 8 Module 1 notebooks when they are published | Recheck at B4 and before B10 |
| O-7 | Distribution reference for category balance | Uniform 20% target |

## Amendment rule

Any change to a course threshold or criterion is a new dated entry here, with its
reason. Original criteria are preserved; nothing is weakened silently.
