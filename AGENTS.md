# Bonsai help Q&A synthetic data (Mini Project 1)

This public repository is a course example, not a product. It generates synthetic help
question and answer data for building information modeling with Bonsai in Blender,
grounded in the Bonsai documentation and the Blender Manual, and evaluates it with the
course's six-step pipeline: generate, first-pass gate, human labels, LLM judge, analysis,
and two-phase iteration. The help chatbot itself moved to Mini Project 4 on November 23,
2026 (below); the repository name still says "chatbot" (open item O-8).

The owner is Chad Josewski. The plan is his document `docs/MP1-BONSAI-HELP-CHATBOT.md`
("proposed plan, not started"). Change the plan only on Chad's direction, and record
every change and every departure from it as a dated entry in `docs/DECISIONS.md`. Read `README.md`,
`docs/DECISIONS.md` and `docs/PORTING-MAP.md` before changing behavior.

## Current boundary

As of November 21, 2026, **B0 (repository readiness) is done**: licenses, README
skeleton, decision log, porting map, packaging and package-level behavioural tests.

As of November 22, 2026, **B1 (documentation snapshots) is done**:
`bonsai-help snapshot build` rebuilds the pinned Bonsai documentation (IfcOpenShell tag
`bonsai-0.9.0post1`, commit `2744f842`, 95 pages) and Blender Manual into git-ignored
`data/` and checks them against `config/doc-manifest.json`; `snapshot check` verifies the committed
files and the snapshots. The pins live in `config/doc-sources.json`, attribution in
`NOTICE.md`, and the fixture slice in `tests/fixtures/docs/`. Change a pin only with
`snapshot build --write-manifest`, never by editing the manifest; never edit fixture
files by hand (use `snapshot fixtures`). Section records (cutting pages at headings) are
B2's `docs_index`, not part of the snapshot. No pipeline code exists yet. B1 pinned the
Blender 5.3 Manual (`blender-v5.3-release`, commit `3481be3f`); B3 replaced it (below).

As of November 22, 2026, **B2 (lexicons and setup facts) is done** as assistant drafts:
- Three more sources are pinned through the B1 machinery: the Bonsai 0.8.5-post1 docs
  and the Bonsai add-on source at both tags, read only by AST.
- `docs index build` cuts docs pages into section records under `data/index/`; its digest
  is `reference/docs-index.json`.
- `lexicon build --write` writes `reference/lexicons/`.
- `reference/setup-profiles.json` and `reference/setup-facts.json` hold two version lines,
  18 profiles and the cited fact rows. Chad's SR-001 decisions (November 22, 2026) are
  applied: 38 records `chad_accepted`, SF-001 `chad_rejected`; a row drafted since is
  `assistant_drafted` until he decides it. Never mark one reviewed without Chad's
  own words in `review`: Chad reviews them through `setup review` packets (the gold packet
  format; the same rules below apply to `setup review import` and
  `data/setup-review/imports/`), and only `setup review apply --write` writes a record's
  `status` and `review`, from his imported decisions. Never set them by hand.
- Regenerate the tool-written files only with their commands, never by hand. Edit the
  setup files by hand, then run `setup format` and `setup check`.
- A fact row may cite only fixture-slice pages. Every quote must be verbatim, start and
  end on token boundaries and occur once in its section. A claim says no more than its
  quotes. A claim with no pinned
  support goes to `not_citable`, never into `rows`.

As of November 22, 2026, **B3 (gold set and Chad's review of the B2 drafts) has started**
with Chad's four decisions (pairings, IFC schemas, review packets, drafting; quoted in
`docs/DECISIONS.md`):
- Version lines: `VL-current` is Blender 5.2 with Bonsai 0.9.0-post1, `VL-older` Blender
  4.5 with Bonsai 0.8.5-post1. Each line's Blender steps come from its matching Manual:
  `blender-manual` (branch `blender-v5.2-release`, commit `4a3be8f9`, 2,358 pages) and
  `blender-manual-4-5` (branch `blender-v4.5-release`, commit `c2b17170`, 2,072 pages).
  The 5.3 Manual pin is removed from active use. Both pairings are `cited` (SF-012,
  SF-013), which `setup check` verifies against the line's own Bonsai docs pin.
- `ifc_schema` keeps IFC2X3, IFC4 and IFC4X3 for opened and federated models as a stated
  default; schema facts are scored only where a row cites them.
- Review is by Markdown packets of about 25 items outside Git under `data/`; decisions
  are imported append-only, and free-text reviewer notes never enter Git.
- Assistant lanes draft each reference answer only from the pinned sections it cites; a
  deterministic check verifies every cited section, quote and operator name; Chad
  approves, edits or rejects.
- The gold-set tooling is built (`bonsai-help gold ...`, see README): the slot plan
  `reference/gold/slots.json`, lane batches and their ingest, the checker, review packets,
  import, publish and the pattern score.
  Chad answered the count questions on November 22, 2026 (quoted in `docs/DECISIONS.md`):
  the 15 multi-part requests (10 development, 5 held-out) and 10 injection cases (all
  held out) are in addition to the 75 questions, and 10 benign control cases sit beside
  the injection cases, held out, so the set is 110 items. All 110 were drafted; Chad
  imported GP-001 to GP-005 on November 22, 2026 (6 accepted, 104 rejected) and SR-001.
  He delegated those reviews to an assistant reviewer and records the decisions as his own
  ("I delegated; record them as mine"); future packets may be reviewed the same way, and
  only he runs `gold packet import` and `setup review import`. The 6 accepted items are
  published (`reference/gold/`). The 104 rejected items are redrafted as assistant drafts
  and exported for Chad's decisions. After corrections to 46 drafts (November 22) and two
  scoring fixes with 7 more redrafts (Chad, November 23, 2026: "Fix first, then re-export
  (Recommended)", then three affirmative-matching fixes), replacement packets are GP-021 to
  GP-025; fact row SF-021 is still in SR-003. Earlier packets remain as history. No new
  decisions were imported during these corrections.
- Docs versus code (Chad, November 22, 2026, "Code wins, cited"): where the pinned Bonsai
  docs and the pinned add-on source disagree, a reference answer follows the code, cites
  both (the doc section with role `conflict`, the code span as a code citation), and carries
  the unusual flag `doc_conflict`. Code spans join the fixture slice only as their own lines
  (`fixture_code_spans`, then `snapshot fixtures`); never commit a whole add-on file.
- Checker `gold-check-v6` (assistant's calls in `docs/DECISIONS.md`): `any_of` and `tokens`
  patterns with optional ordered, clause-bounded and affirmative matching (each only where it
  has an effect); negation-aware forbidden patterns, which may be checked across all scored
  fields, except that a forbidden tool or stale-docs pattern scores `steps` or
  `tools_required` unless it is affirmative throughout; code citations (G26); and the regex
  budget only for a set that fills every slot. Record every further change to a check as a dated
  assistant's call; never weaken a check silently. Review validity binds to draft content,
  setup, evidence digests and `gold.REVIEW_CHECKER`, not to `gold.CHECKER` (Chad, November
  23, 2026, "Narrow it, stop patching, review (Recommended)"): a scoring-only change keeps
  packets and decisions valid; bump `REVIEW_CHECKER` only when a check change can alter an
  item's content or derived fields. Pattern checks are heuristics; meaning is graded by
  Chad's blind labels and the LLM judge.
- Gold rules:
  - Only Chad writes a packet's `DECISION:` and `NOTE:` lines and its edit JSON, and only
    Chad runs `gold packet import` (interactive terminal, typed confirmation). An
    assistant never fills, edits or imports a packet, never runs the import through a
    pseudo-terminal, and never writes `data/gold/imports/`. The same holds for setup review
    packets (`setup review import`, `data/setup-review/`).
  - Lanes write batches in the lane form and ingest them; they never supply derived
    fields, never pad an unsupportable slot, and draft each reference answer only from
    the pinned sections it cites. A slot that cannot be supported gets a recorded
    substitution in `reference/gold/slot-substitutions.json` (then `gold slots --write`)
    or stays empty and is reported.
  - `reference/gold/slots.json`, `development.json` and `held-out.json` are tool-written:
    regenerate them only with `gold slots --write` and `gold publish --write`, never by
    hand. NOTE text and `data/gold/` never enter Git.
  - Held-out items are public but held out from development decisions: load them only
    through `gold.load_held_out` (checker, publish, packets; in MP4, the assessed runs).
    Prompts, few-shot examples and judge-v2 examples use development items only, and
    `gold score` scores development items only.

As of November 23, 2026, **MP1's scope is revised** (Chad: "This plan is approved. Modify
MP1 as needed."; details in `docs/DECISIONS.md`). MP1 creates and evaluates data: one
generation prompt, parameterized by category and setup profile, writes each seven-field
item from pinned doc sections, grounded from the baseline on; Phase B is one targeted,
pre-registered change to that prompt. The help chatbot, the doc tools `search_docs` and
`get_doc_section`, the security pass and the gold set move to Mini Project 4. **B3 is
withdrawn from MP1**: the gold tooling, its tests and the 6 published items stay, frozen,
and the gold rules above still bind anything touching `reference/gold/` or `data/gold/`.
The paused gold packets GP-021 to GP-025 stay unimported; do not ask Chad to review them for
MP1. Setup review SR-003 (fact row SF-021) stays an MP1 item, still pending.

As of November 23, 2026, **B4 (generation and the first-pass gate) is done**, with no model
run yet. `bonsai-help generate`, `gate`, `collect`, `collection-status`, `cohort` and
`cohort-status` exist, backed by the modules `tracing`, `schemas`, `config`, `sampler`,
`model_client`, `generate`, `checks`, `gate`, `collection` and `cohort`, the prompt
`prompts/generator-v1.md` and `config/run.example.json`. The assistant's calls are in
`docs/DECISIONS.md` (November 23, 2026: B4 generation and gate). B4 has no rubric: Chad
moved it to B5 on November 24, 2026 ("Refuse hosted for now; record the rubric as moved to
B5"). The final-review fixes and the cleanup of November 24, 2026 are recorded there as
assistant's calls.
As of November 24, 2026, **B5 (rubric and baseline run) is done**:
- **Rubric.** Chad accepted `config/rubric.json` (`bonsai-rubric-v1`, checked by
  `bonsai-help rubric check | show`) as drafted, so it is `chad_accepted`. Only a dated
  `docs/DECISIONS.md` entry in his words sets that status. Any change is a new rubric
  version, and a threshold change also needs a dated amendment and a code change.
- **Embedding server.** Chad chose a separate local embedding server
  (`embedding_base_url`) and the chat server's key file for the key ("Yes, use that
  file"). The path stays in the git-ignored local config.
- **Kept runs.** Diagnostic smoke runs (never baseline evidence) and the stopped first
  baseline `baseline-2026-11-24` (generator v1; Chad: "Stop, fix, restart (Recommended)")
  are kept unchanged under `runs/`. They are never resumed, repaired or counted.
- **Baseline.** Both measured arms use the assessed split (Chad: "Assessed split
  (Recommended)"). The baseline collection `baseline-2026-11-24-r2` (generator v1.1) is
  ready.
- **Cohort.** On Chad's "Freeze the cohort", cohort `baseline-b5-cohort-1` is frozen
  from it: 50 items, 10 per category. The cohort and its collection are read only.
- **Prompts.** `prompts/generator-v1.md` is frozen, and the Phase B correction changes
  v1.1.
- **Still open.** The `stats` code for the 95% intervals (B5 plan Task 3) is not built.

As of November 24, 2026, **B6 (baseline human labels) is next, and its tooling is built**:
`bonsai-help assessment create | status`, `label`, `label-status` and
`freeze-human-reference`, with the modules `evaluation_schemas`, `assessment`, `labels`,
`human_reference` and `evaluation_cli`. The plan is
`docs/superpowers/plans/2026-11-24-b6-labels.md`, and the calls and Chad's answers are in
`docs/DECISIONS.md`. No assessment has been created and no label has been entered.
- **Count.** B6 labels 30 of the 50 cohort items, and the other 20 stay unselected for
  B8's blind mixed queue.
- **Who runs what.** The assistant may run `assessment create` on Chad's go-ahead and
  reports only its blind summary.
- **Chad's commands.** Only Chad runs `label` and `freeze-human-reference`, in his own
  interactive terminal. An assistant never runs them, interactively or through a
  pseudo-terminal or any input script. It never writes, edits, moves or deletes a label
  file, checkpoint, lock or human reference under `runs/` or `data/`.
- **What an assistant may read.** It may read `label-status` and `assessment status`. It
  never tells Chad a blind id's run, item or arm (from `key.json`) before his labels for
  that assessment are frozen.
- **Labeling refuses** while the rubric is not `chad_accepted` or has changed since the
  assessment was created.
- **Blind display.** The display shows the item's seven fields, its category, its setup
  record, the model's quotes and the full text of its cited sections, never provenance.
- **Labels are append-only.** A correction is `label --amend --supersedes`. A refused
  ledger means preserve and inspect, never repair.
- **Unresolved** is reported and is never a pass.
- **B7** calls `human_reference.load_reference` first and writes judge evidence only
  under `<assessment>/judges/`.

Then B7–B10 as the plan's §9 describes. B8 needs Chad's labels too.

B0 scope is the assistant's call, not Chad's: earlier pipeline modules were not copied.
B4 ports them module by module, each with its tests, following `docs/PORTING-MAP.md`. The
plan's B4 criterion "existing suite still passes" becomes "each ported module arrives
with its tests passing".

## Owner decisions (November 21, 2026)

Recorded as owner-reported, in Chad's words where given. Details in `docs/DECISIONS.md`.

- The Revit round is superseded: "stash the Revit work and start B0".
- O-1: code is "GPL-3.0-or-later (plan default)"; generated datasets are CC BY-SA 4.0
  (plan default). Bonsai doc fixtures and the lexicon keep GPL-3.0-or-later; Blender
  Manual fixtures keep CC BY-SA 4.0.
- O-4: resolved by this new repository. Chad first chose "Rewrite and force-push", then
  said "The other option is to create a new clean repo and start over" and chose "New
  repo; old goes private". The earlier `aia-mp1-synthetic-data` repository goes private
  with its history intact; no history is rewritten.
- O-5: "Yes, submission/ only (plan default)". Only the curated set under `submission/`
  is committed; raw attempt logs, scratch runs and all earlier evidence stay outside Git.
- Repository name: `mp1-bonsai-help-chatbot`.
- Not yet decided (plan defaults apply as defaults): O-2 categories, O-6 recheck of
  unpublished course units, O-7 distribution reference. O-3 was settled on November 22,
  2026 by the pairing decision above.

## Public repository rules

- Never commit private details: IP addresses, NAS or network paths, hostnames, SSH
  details, local usernames or home paths, email addresses other than the commit
  identity, credentials, private repository contents, course notebook or course data
  content, or human review notes. One exception, confirmed by Chad on November 22,
  2026 (`docs/DECISIONS.md`): unmodified upstream fixture
  pages may contain public example home paths only through the hash-pinned
  `privacy_allowlist` in `config/doc-sources.json`.
- Only licensed open sources enter the repository. Public access is not permission to
  reuse. For every source record the URL or repository, pinned commit or tag, retrieval
  date, license, permitted use, page hashes and attribution: the IfcOpenShell
  contributors (Bonsai, GPL-3.0-or-later) and the Blender Documentation Team (Blender
  Manual, CC BY-SA 4.0 or later). Logos, trademarks, icons, source code and scripts in
  the Manual are excluded. No employer or client material.
- Raw runs (`data/`, `runs/`, `traces/`, `labels/`, `reports/`, `scratch/`, `snapshots/`)
  are git-ignored. `submission/` is tracked and must never be git-ignored.
- Commit as Chad Josewski <cjosewski@gmail.com>, set in the local git config.

## Implementation rules

- **Payload.** Exactly seven fields: `question`, `answer`, `equipment_problem`,
  `tools_required`, `steps`, `safety_info`, `tips`. All strings nonblank;
  `tools_required` has at least one item; `steps` has at least three ordered items with
  the panel or menu path; `tips` has at least one item. Output always uses
  `equipment_problem`; a legacy `problem` input is normalized and conflicting values are
  rejected. Metadata (setup id, category, cited doc sections, prompt version, model,
  timestamp, trace id) lives in a separate envelope, never in the payload.
- **Attempts.** Persist every generation and judge attempt with its raw completion,
  including malformed output and explicit transport failures. Record a durable request
  start before each call. A started request with an unknown outcome uses up its attempt
  and is disclosed. Bound transport timeouts and attempts per item; exhaustion is a
  controlled failure with a documented exit code, never a traceback or an infinite loop.
- **Immutability.** Never overwrite a run, assessment, judge run or report. Every
  experiment gets a new ID. Resume keeps the original settings, prompt, code and attempt
  budget, verifies checkpoint hashes and gives exhausted slots no extra attempts. After a
  hard kill, inspect leftover locks or tails rather than deleting them.
- **Denominators.** Report initial-attempt schema validity (valid initial responses ÷
  initial slots), retry recovery and gate retention separately. The ≥95% structural
  target is judged on the initial-attempt figure. Never compare retained answers against
  filtered ones.
- **Human labels.** Append-only; a correction is a new record with an explicit
  superseding ID; an interrupted write means inspect, not repair. Labels carry the trace
  id, timestamp and pinned rubric version. Labeling is blind: Chad does not see the arm,
  run or judge output, and sees the cited doc sections beside each item. Never enter
  assistant decisions as human labels.
- **No fabrication.** Never fabricate human labels, baseline failures, model
  measurements, instructor or owner approvals, or acceptance. A missing judgment is
  unresolved, not a pass; a pending check is not a pass. If baseline failure is below
  15%, report it honestly and never plant defects. If baseline failure is 0, the
  improvement ratio is undefined.
- **Judge.** A separate prompt at a lower temperature than the generator, with
  Instructor/Pydantic structured output (six binary decisions, each with a reason) and a
  recorded prompt version. Assessed use needs a distinct judge or a recorded basis for
  the choice; same-model smoke judging is diagnostic only, and diagnostic agreement never
  counts as calibration. The judge is frozen for the baseline/corrected comparison.
- **Deterministic checks are heuristics.** Operator and menu lexicons, citation
  existence, verbatim quote support, the generic-phrase list, deduplication and category
  counts flag defects and feed the judge as evidence. They never replace a human or judge
  decision. Never weaken the gate to obtain a pass.
- **Models.** Use an explicitly configured local OpenAI-compatible endpoint (`base_url`
  ending in `/v1`, served model id, mode, timeout, max attempts); an optional separate
  embedding endpoint (`embedding_base_url`) follows the same rules. The client never
  discovers or starts a model and never changes local service settings. Never fall back
  to a hosted provider silently. A hosted path must be explicit, documented, authorized
  by Chad and cost-capped; until Chad authorizes one with an enforced cost cap, a run
  config with `hosted: true` is refused at load (Chad, November 24, 2026). Never send
  human ratings to a hosted service. A hosted judge may
  receive the cited doc sections it needs (plan §7 Step 4; Chad, November 21, 2026, in
  `docs/DECISIONS.md`).
- **Credentials.** Exactly one source per credential: an environment-variable name or a
  key-file path (the embedding endpoint shares the chat source unless it names its own).
  No values in config, prompts, arguments or logs. Never log authorization headers or
  credential-file contents. `.env` is not auto-loaded. Local config files are git-ignored.
- **Pipeline.** Every stage runs on its own against saved artifacts. Every assessed
  answer is generated at runtime. Keep all five categories in every run (20% each; O-2
  and O-7 open), at least 50 retained items per run (generate about 70). A setup record
  travels with every item; uncited setup-fact rows are not scored; items are split by
  setup profile so no profile leaks between development and assessed sets. One embedding
  model for every vector. Generation cites the pinned sections each item was written
  from. The chatbot, its read-only tools and the security pass belong to Mini Project 4,
  not this pipeline.
- **Iteration.** Every prompt change gets an iteration-log entry: date, change,
  hypothesis, before and after, decision, next step. Phase B correction is pre-registered
  from the heatmap before any corrected run.
- **Criteria.** Six dimensions with the course names and order: D1 answer completeness
  (≥85%), D2 safety specificity (≥90%), D3 tool realism (≥95%), D4 scope appropriateness
  (≥95%), D5 context clarity (≥90%), D6 tip usefulness (≥85%); an item passes overall only
  if it passes all six. Course thresholds: ≥95% structural validity, ≥15% honest baseline
  failure, ≥80% human/judge agreement in every dimension (Phase A, before Phase B), ≥80%
  corrected overall pass, more than 80% relative failure reduction
  (`(baseline_failure − corrected_failure) / baseline_failure`, strict; disclose that
  exactly 0.80 does not pass), at least 20 blind labels each for baseline and corrected,
  and counts with 95% intervals beside every rate. Any threshold change is a dated
  amendment with its reason in `docs/DECISIONS.md`; original criteria are preserved.
- **Agents.** You may be working alongside other agents. Respect file ownership,
  preserve unrelated edits and coordinate interface changes.

## Verification

```bash
uv lock --check
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

After a pin change, run `snapshot build --write-manifest` on an empty data root, check
that a plain `snapshot build` into a second empty root reproduces the manifest, then run
`snapshot fixtures --replace`, `docs index build --write-digest`, `lexicon build --write`
and `setup check`. A cited
section whose bytes changed fails `setup check` until its row is redrafted.

Tests exercise behaviour: invalid or malformed outputs, retry exhaustion, transport
failure and unknown outcomes, trace lineage, duplicate and category gates, denominator
accounting, CLI failures and exit codes, no-overwrite and resume hash checks, credential
redaction and each deterministic check. Do not write tests that merely repeat
implementation details. Model-output and test-remote fixtures are clearly synthetic
and never submitted as model evidence. Documentation fixtures in `tests/fixtures/docs/`
are unmodified, attributed copies of the pinned upstream files, not synthetic. Run a
real smoke test only against an endpoint that is already reachable.
