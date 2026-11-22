# Bonsai help chatbot (Mini Project 1)

This public repository is a course example, not a product. It builds a help chatbot for
building information modeling with Bonsai in Blender, generates synthetic question and
answer data from the Bonsai documentation and the Blender Manual, and evaluates the
chatbot with the course's six-step pipeline: generate, first-pass gate, human labels,
LLM judge, analysis, and two-phase iteration.

The owner is Chad Josewski. The plan is his document `docs/MP1-BONSAI-HELP-CHATBOT.md`
("proposed plan, not started"). Change the plan only on Chad's direction, and record
every change and every departure from it as a dated entry in `docs/DECISIONS.md`. Read `README.md`,
`docs/DECISIONS.md` and `docs/PORTING-MAP.md` before changing behavior.

## Current boundary

As of November 21, 2026, **B0 (repository readiness) is done**: licenses, README
skeleton, decision log, porting map, packaging and package-level behavioural tests.

As of November 22, 2026, **B1 (documentation snapshots) is done**:
`bonsai-help snapshot build` rebuilds the pinned Bonsai documentation (IfcOpenShell tag
`bonsai-0.9.0post1`, commit `2744f842`, 95 pages) and Blender Manual (branch
`blender-v5.3-release`, commit `3481be3f`, 2,450 pages) into git-ignored `data/` and
checks them against `config/doc-manifest.json`; `snapshot check` verifies the committed
files and the snapshots. The pins live in `config/doc-sources.json`, attribution in
`NOTICE.md`, and the fixture slice in `tests/fixtures/docs/`. Change a pin only with
`snapshot build --write-manifest`, never by editing the manifest; never edit fixture
files by hand (use `snapshot fixtures`). Section records (cutting pages at headings) are
B2's `docs_index`, not part of the snapshot. No pipeline code exists yet.

Next is **B2** (lexicons and cited setup facts; the operator lexicon reuses the
`ifcopenshell` repository pin as a new source), then B3 (gold set), B4 (rubric, prompts,
checks and the first ported modules), and B5–B10 as the plan's §9 describes. B3, B6 and
B8 need Chad's review and labels.

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
- Not yet decided (plan defaults apply as defaults): O-2 categories, O-3 setup profiles,
  O-6 recheck of unpublished course units, O-7 distribution reference.

## Public repository rules

- Never commit private details: IP addresses, NAS or network paths, hostnames, SSH
  details, local usernames or home paths, email addresses other than the commit
  identity, credentials, private repository contents, course notebook or course data
  content, or human review notes.
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
  ending in `/v1`, served model id, mode, timeout, max attempts). The client never
  discovers or starts a model and never changes local service settings. Never fall back
  to a hosted provider silently. A hosted path must be explicit, documented, authorized
  by Chad and cost-capped. Never send human ratings to a hosted service. A hosted judge may
  receive the cited doc sections it needs (plan §7 Step 4; Chad, November 21, 2026, in
  `docs/DECISIONS.md`).
- **Credentials.** Exactly one source: an environment-variable name or a key-file path.
  No values in config, prompts, arguments or logs. Never log authorization headers or
  credential-file contents. `.env` is not auto-loaded. Local config files are git-ignored.
- **Pipeline.** Every stage runs on its own against saved artifacts. Every assessed
  answer is generated at runtime. Keep all five categories in every run (20% each; O-2
  and O-7 open), at least 50 retained items per run (generate about 70). A setup record
  travels with every item; uncited setup-fact rows are not scored; items are split by
  setup profile so no profile leaks between development and assessed sets. One embedding
  model for every vector. The chatbot has only read-only tools (`search_docs`,
  `get_doc_section`) and a step budget. The security pass is reported separately.
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

Tests exercise behaviour: invalid or malformed outputs, retry exhaustion, transport
failure and unknown outcomes, trace lineage, duplicate and category gates, denominator
accounting, CLI failures and exit codes, no-overwrite and resume hash checks, credential
redaction and each deterministic check. Do not write tests that merely repeat
implementation details. Model-output and test-remote fixtures are clearly synthetic
and never submitted as model evidence. Documentation fixtures in `tests/fixtures/docs/`
are unmodified, attributed copies of the pinned upstream files, not synthetic. Run a
real smoke test only against an endpoint that is already reachable.
