# B5: Rubric and Baseline Run Plan

**Goal:** Meet plan §9 B5: "Rubric (D1–D6 with Bonsai anchors and targets), versioned for the labels; ≥50 retained, ≥95% initial-attempt schema validity, gate report, honest failure rate". The rubric and the embedding endpoint are built and tested offline. The baseline run has not happened: it needs Chad's go-ahead and reachable local servers, and no test or assistant calls a real endpoint.

**Spec:** `docs/MP1-BONSAI-HELP-CHATBOT.md` (§6.2, §6.3, §7 Steps 1–3 and 6, §9 B5), `AGENTS.md` (Criteria, Models, Credentials, Human labels, Pipeline), `docs/PORTING-MAP.md` (§2 item 4, §4 items 8 and 18, the assessment, acceptance and calibration rows), `docs/DECISIONS.md` (November 24, 2026 entries).

## Global Constraints

- Six dimensions with the course names and order, and the course thresholds of `AGENTS.md`, unchanged. A threshold change is a dated amendment in `docs/DECISIONS.md` and a new rubric version.
- The rubric is `assistant_drafted` until Chad accepts it. Only a dated `DECISIONS.md` entry in his own words can make it `chad_accepted`; an assistant never sets that status.
- Local endpoints only; `hosted: true` is refused at load. Credentials come from one source per endpoint (an environment-variable name or a key-file path), never from config values, arguments or logs. No path or machine detail enters the repository.
- Report initial-attempt schema validity, retry recovery and gate retention separately, each with its counts and a 95% interval. Never compare retained items against filtered ones.
- Never fabricate a measurement, a label or an approval. A pending check is not a pass.

## Built (November 24, 2026)

### Task 1: Rubric (done)

**Files:** `config/rubric.json`, `src/bonsai_help/rubric.py`, `tests/test_rubric.py`, `tests/test_rubric_pipeline.py`; `src/bonsai_help/cli.py` registers the commands.

- [x] `config/rubric.json`, version `bonsai-rubric-v1`, status `assistant_drafted`: five labeling rules; D1–D6 with pass and fail anchors written from plan §6.2 (§6.3 for D2), labeling notes (check, common fail patterns, borderline) and each dimension's pass-rate minimum; the overall-pass rule (all six; a missing decision is unresolved); the course thresholds.
- [x] `rubric.load_rubric` validates the file strictly and refuses any threshold that differs from the course value. `rubric.rubric_sha256` pins the validated content (formatting and key order do not change it). `overall_pass` returns `False` when any present decision is 0, and `None` (unresolved) only when no decision is 0 and one is missing; `relative_reduction` is exact, so 0.80 does not pass and a zero baseline is undefined.
- [x] `bonsai-help rubric check | show [--rubric PATH]`: exit 0 valid (a warning while `assistant_drafted`), 1 the rubric fails its check, 2 unreadable file or usage error.
- [x] `tests/test_rubric_pipeline.py` fails if the rubric and the B4 pipeline drift apart: the checks' dimensions, the collection's default target of 50 and the cohort size.

### Task 2: Separate embedding endpoint (done)

**Files:** `src/bonsai_help/config.py`, `collection_cli.py`, `gate.py`, `collection.py`, `config/run.example.json`, with tests.

- [x] Chad chose "Separate embedding server (Recommended)". `RunConfig` gains `embedding_base_url` (default: `base_url`) and `embedding_api_key_env` / `embedding_api_key_file` (at most one; with neither, the chat credential source is used). The embedding URL passes the same local-endpoint rules as `base_url`.
- [x] The gate report and the cross-batch screens record `embedding_base_url`. A collection refuses a gate report or screen from another embedding endpoint, and resume refuses a changed endpoint or embedding credential-source kind.

## Still to build in B5

### Task 3: Baseline report with intervals

The B4 code gives counts and rates but no intervals, and `AGENTS.md` requires a 95% interval beside every rate. The `stats` extract (PORTING-MAP §3.4) is planned for B7.

- [ ] Port the Clopper–Pearson part of `compare_human` into `stats` now, with its reference-value and edge tests (0 of n, n of n, impossible counts refused). Fisher, Holm and McNemar stay in B7–B8.
- [ ] Add a read-only report over a collection (no new run, no model call): the three denominators with counts and intervals, exhausted slots, unknown outcomes, drops per check, per-category retained counts and the distribution result. It writes a new file once and never overwrites.
- [x] Record the porting-order change in `DECISIONS.md` ("Intervals need code", November 24, 2026) and PORTING-MAP §8 (B5–B6).

## Baseline run procedure

Two smoke runs have run (step 3, runs `smoke-2026-11-24-a` and `smoke-2026-11-24-b`, November 24, 2026; diagnostic only; `DECISIONS.md`, "first smoke run; thinking turned off"). The first baseline collection, `baseline-2026-11-24` (generator v1), was stopped during batch 2 by Chad's decision "Stop, fix, restart (Recommended)" and is kept unchanged as evidence; it never counts as the baseline (`DECISIONS.md`, "first baseline collection stopped; generator v1.1 and quote markup"). Each step needs Chad's go-ahead and servers that are already reachable; the client never starts or discovers a model.

1. **Config.** Chad's local config is a copy of `config/run.example.json` at `config/run.local.json` (git-ignored) or outside the repository. Its `api_key_file` names the chat server's key file (Chad: "Yes, use that file"); the embedding server shares that key unless its config names its own source. `embedding_base_url` names the separate embedding server. No path, address or key goes into Git.
2. **Pre-checks.** `snapshot check`, `setup check` and `rubric check` pass on the checkout.
3. **Smoke run.** `purpose: "smoke"`, `split: "development"`, `enable_thinking: false` (Chad, November 24, 2026: "Turn thinking off (Recommended)"): `generate --count 5`, then `gate`. It shows that both servers answer and the output fits the schema. A smoke run is diagnostic only: it never counts toward the baseline, is never submitted and never calibrates anything. Every smoke run gets a new run ID; the first one (`smoke-2026-11-24-a`, thinking left on, 0 of 5 initial-attempt valid) is kept unchanged and not resumed.
4. **Baseline collection.** A new config with `purpose: "baseline"`, `prompt_path: "prompts/generator-v1.1.md"` (the baseline prompt; v1 is frozen and the field's default still names it, so the config must name v1.1), `prompt_variant: "baseline"`, `enable_thinking: false` (the corrected run uses the same value), the assessed split (Chad: "Assessed split (Recommended)", below), `model_identity` and `model_sha256` set (refused without them), and the same embedding model and server that the corrected run will use. Run `collect` under a new collection ID (never `baseline-2026-11-24`, which is stopped and kept) with the defaults: batches of 70 generated items, at most 3 batches, until at least 50 are retained with at least 10 per category. If the budget runs out first, the collection stops with exit 3 and that is reported. The budget is not raised quietly.
5. **Freeze.** `collection-status`, then `cohort` (10 retained items per category, seeded). The cohort is the population B6 labels are drawn from.
6. **Report (Task 3).** The three figures, each with its counts and 95% interval: initial-attempt schema validity (valid initial responses ÷ initial slots; the ≥95% target is judged on this figure), retry recovery (valid results from attempt 2 or later, never added to the initial figure) and gate retention (retained ÷ schema-valid items entering the gate). Add the gate report's drops per check and category counts. A figure below target is reported as measured. Any prompt or code change afterwards is a new dated entry and a new run ID. The restarted baseline's `answer_length` drops are the "after" of the v1 → v1.1 iteration-log record.

### Prompt for the two arms

Both measured arms start from `prompts/generator-v1.1.md` (SHA-256 `ee1dc9a1…`). v1.1 is generator v1 with one fix found by the stopped collection: it states the gate's 60-word D1 minimum. That is a pre-baseline fix of a prompt/gate mismatch, not the Phase B correction. The corrected arm changes v1.1 by the one change pre-registered from the heatmap, as a new prompt file with its own iteration-log entry. `prompts/generator-v1.md` is never edited.

### Which split the baseline uses

The plan and `AGENTS.md` do not name it. They require that items are split by setup profile so no profile leaks between the development and assessed sets, that the judge's v2 examples come from development disagreements (plan §7 Step 4), that the judge is calibrated on the baseline items (§7 Step 6, Phase A), and that the baseline and corrected arms are compared by `(baseline_failure − corrected_failure) / baseline_failure`.

Recommended: run both measured arms (`baseline` and `corrected`) on the **assessed** split (the 6 diagonal profiles). Smoke runs, and any items labeled only to draw judge v2 examples, go on the **development** split (12 profiles). The reasons:

- `baseline` and `corrected` are the code's assessed purposes.
- The improvement ratio compares like with like only if both arms use the same profiles.
- The B3 record already planned "the assessed runs from B5" on the assessed profiles (for the gold set, which has since moved to Mini Project 4).
- Judge examples taken from development items cannot leak into the agreement measured on assessed items.

The cost is that judge v2 needs some labeled development-split items, which means more labeling for Chad in B6–B7. The alternative is both arms on the development split. That labels fewer items, but the assessed split goes unused in MP1, and the v2 examples would come from the same items whose agreement they are meant to raise.

Chad decided on November 24, 2026: "Assessed split (Recommended)" (`DECISIONS.md`, "Open questions for Chad (B5)").

## What B5 cannot measure yet

- **The honest failure rate.** The baseline's overall failure rate, and whether it reaches the ≥15% target, need Chad's blind labels (B6) and the calibrated judge (B7). It is reported once those exist. It is never estimated from the gate: gate drops are heuristic screens, not rubric decisions, and retained items are never compared against filtered ones.
- **Per-dimension pass rates, human/judge agreement, the corrected pass rate and the improvement ratio** (B6–B8).
- **The rubric's status.** It stays `assistant_drafted` until Chad accepts, edits or rejects it. The baseline run does not read the rubric, but B6's labels pin its version and hash, so Chad must decide on it before labeling starts.

## Open questions for Chad

1. ~~Which split do the baseline and corrected runs use?~~ Decided: the assessed split (above).
2. Accept, edit or reject `config/rubric.json` (anchors, labeling notes and borderline rulings) before B6.
3. Go-ahead for the smoke run and then the baseline collection, once both servers are reachable.
