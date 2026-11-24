# B4: Generation and First-Pass Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build MP1's Steps 1–2: a docs-grounded, category- and setup-parameterized generator with bounded, audited attempts, and the first-pass gate that decides which items go on to labels and judging. No model is called in tests.

**Architecture:** Port the earlier repository's generic pipeline modules (`tracing`, `schemas`, `config`, `model_client`, `generate`, `gate`, `collection`, `cohort`) into `bonsai_help`, following `docs/PORTING-MAP.md` §2–§3, with one change of design: generation is one stage (plan §7 Step 1, revised November 23, 2026). A new section sampler picks pinned doc sections per slot; a new deterministic-check module supplies the gate's per-dimension pre-checks from the committed lexicons and the docs index.

**Tech Stack:** Python ≥3.12, Pydantic 2, Instructor 1.17+, OpenAI SDK 2 (local OpenAI-compatible endpoint), httpx, pytest, ruff. No new dependency.

**Spec:** `docs/MP1-BONSAI-HELP-CHATBOT.md` (§5, §6, §7 Steps 1–2, §8, §9 B4), `AGENTS.md` (Implementation rules), `docs/PORTING-MAP.md` (§2, §3.1–§3.2, §5, §8 B4). The earlier repository is `aia-mp1-synthetic-data` (private; a local clone sits beside this one): port its modules and tests by reading them there, never by copying its fixtures, prompts, rubrics or config.

## Global Constraints

- Payload is exactly seven fields: `question`, `answer`, `equipment_problem`, `tools_required` (≥1), `steps` (≥3), `safety_info`, `tips` (≥1); all strings nonblank; output always `equipment_problem`; legacy `problem` normalized, conflicting values rejected. Metadata only in the envelope.
- Categories are exactly `doc_sources.CATEGORIES` (reuse that `Literal`; do not define a second one).
- Persist every attempt with its raw completion, including malformed output and transport failures; record a durable request start before each call; a started request with an unknown outcome uses up its attempt. Exhaustion is a controlled failure with a documented exit code.
- Never overwrite a run; resume keeps the original settings, prompt and code identity and verifies checkpoint hashes; exhausted slots get no extra attempts.
- Report initial-attempt schema validity (valid initial ÷ initial slots), retry recovery and gate retention separately.
- Local endpoint only by default (`base_url` ending `/v1`, localhost or a private/loopback IP); a hosted profile needs `hosted: true`, an authorization reference and a cost cap, and never happens by fallback.
- Credentials: exactly one source (env-var name or key-file path); never in config, prompts, logs or manifests. Env var default `BONSAI_HELP_API_KEY`.
- Raw runs live outside Git: default artifact root `runs/` (already git-ignored) or a path outside the repository.
- Deterministic checks are heuristics: they drop obviously bad items and feed the judge as evidence; they never stand in for a human or judge decision. Never weaken a check to get a pass.
- Tests exercise behaviour with clearly synthetic model outputs and fake transports; documentation text comes only from the committed fixture slice.
- Verification for every task: `uv lock --check`, `uv run --locked pytest -q`, `uv run --locked ruff check .`, `uv run --locked ruff format --check .`.

## Decisions this plan makes (assistant's calls, recorded in DECISIONS.md in Task 10)

1. **Sampling source.** The sampler draws only from committed fixture-slice pages tagged with the slot's category (`fixture_pages[].categories` in `config/doc-sources.json`), from the sources of the slot's version line (Bonsai docs and Blender Manual of VL-current or VL-older). Generation, tests and the replay demo then run offline, and the judge and Chad can always see the cited text. The slice grows only through `snapshot fixtures`.
2. **Sections per slot.** Two Bonsai-docs sections and at most one Blender Manual section, at most 1,200 words in total, chosen by a seeded RNG keyed on `(run seed, slot id)`; developer and fragment tags excluded.
3. **Citations outside the payload.** The model returns `GenerationOutput(item: QAItem, cited_section_ids: list[str])`; the envelope stores the citations; the stored payload stays exactly seven fields. Citing a section that was not offered is a D3 pre-check failure, not a schema failure.
4. **Embedding duplicates.** Embeddings come from the same configured endpoint (`/v1/embeddings`) with one recorded `embedding_model` for every vector; cosine ≥ 0.92 drops the later item. Configurable, recorded in the gate report.
5. **Pre-check values.** D1 answer ≥ 60 words; D2 `safety_info` ≥ 80 characters and no generic phrase; D3 every `bim.*` id in `tools_required`/`steps` exists in the version line's Bonsai-source lexicon and every cited section was offered; D4 no refusal boilerplate (`as an ai`, `i cannot help`, `i'm unable to`); D5 question ≥ 6 words and `equipment_problem` ≥ 3 words; D6 every tip ≥ 30 characters, none generic, none a near-copy of a step (token Jaccard ≥ 0.8). Unknown Blender operators or menu paths are recorded as evidence, never a drop.
6. **Category balance.** The slot plan is exactly balanced; the gate passes the batch when every category is ≥ 18% of retained items (the brief's tolerance example).
7. **Slots and profiles.** A run of `count` items (multiple of 5) gives each category `count/5` slots; profiles are assigned round-robin from the run's `split` (`development` or `assessed`, from `reference/setup-profiles.json`), so no profile crosses splits.

## Review Focus

1. A model reply that is valid JSON but cites a section id it was not given → recorded, D3 pre-check fails, item dropped; never a crash. (Task 7 test `test_uncited_section_fails_d3`.)
2. A fixture page whose bytes no longer match the manifest when a run starts → the run refuses before any model call with a clear message. (Task 4 test `test_tampered_fixture_refuses`.)
3. A resume after a hard kill with a started-but-unfinished request → that attempt counts as used and unknown; the slot gets no extra attempt. (Task 6 test `test_unknown_outcome_consumes_attempt`.)
4. The embedding endpoint down while gating → the gate stops with a controlled failure and writes no partial report; it never silently skips near-duplicate removal. (Task 8 test `test_embedding_failure_is_controlled`.)
5. A config with an API key value pasted into `api_key_env` or a hosted URL without `hosted: true` → rejected at load, and no manifest or error message shows the value. (Task 3 tests `test_hosted_requires_flag_auth_and_cap`, `test_credential_never_in_public_settings`.)

---

### Task 1: Tracing and file helpers

**Files:**
- Create: `src/bonsai_help/tracing.py`
- Test: `tests/test_tracing.py`

**Interfaces:**
- Produces: `now() -> str`; `digest(value: str | dict) -> str`; `run_directory(root: Path, run_id: str) -> Path` (refuses ids that escape `root`); `append_record(path: Path, record: dict) -> None` (fsync); `read_records(path: Path) -> list[dict]` (raises `ValueError` on a truncated last line); `write_checkpoint(path: Path, record: dict) -> None` (atomic); `artifact_hashes(directory: Path) -> dict[str, str]`; `exclusive(path: Path)` (context manager; refuses an existing file); `read_json(path: Path) -> dict`.

- [ ] **Step 1:** Port the old `tracing.py` plus `exclusive`/`read_json` from the old `assessment.py` (PORTING-MAP §2 item 10). Write tests first: `test_run_directory_refuses_escape` (`"../x"`, absolute paths, empty), `test_truncated_jsonl_is_an_error`, `test_checkpoint_is_atomic` (no temp file left; old content intact if the write raises), `test_exclusive_refuses_existing`.
- [ ] **Step 2:** Run `uv run --locked pytest tests/test_tracing.py -q`; expect failures, implement, rerun to PASS.
- [ ] **Step 3:** Run the full verification; commit `Port tracing and file helpers`.

### Task 2: Payload, envelope and generation output schemas

**Files:**
- Create: `src/bonsai_help/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Consumes: `doc_sources.Category`, `doc_sources.CATEGORIES`.
- Produces: `QAItem` (old model, unchanged rules); `GenerationOutput(item: QAItem, cited_section_ids: list[NonBlank])` with `min_length=1`; `CitedSection(id: str, page_sha256: str, source: str, pin_id: str)`; `GeneratedItem` with fields `schema_version: Literal["1"]`, `run_id`, `trace_id`, `item_id`, `attempt_id`, `parent_attempt_id: str | None`, `slot_id`, `category: Category`, `setup_id`, `version_line`, `prompt_variant: Literal["baseline", "corrected"]`, `prompt_hash`, `model`, `sampler_seed: int`, `offered_sections: list[CitedSection]`, `cited_sections: list[CitedSection]`, `item: QAItem`.

- [ ] **Step 1:** Port `test_schemas.py` behaviours as new tests with synthetic Bonsai items: `test_seven_fields_exactly` (extra key rejected), `test_minimum_counts` (steps 2 → error; tools 0; tips 0), `test_blank_strings_rejected`, `test_legacy_problem_normalized_and_conflict_rejected`, `test_payload_never_serializes_problem`, `test_envelope_rejects_unknown_category`.
- [ ] **Step 2:** Implement; strict, `extra="forbid"`; no domain switch. Run tests to PASS, full verification, commit `Add payload, envelope and generation output schemas`.

### Task 3: Run configuration and generator prompt v1

**Files:**
- Create: `src/bonsai_help/config.py`, `prompts/generator-v1.md`, `config/run.example.json`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `RunConfig` (fields: `base_url`, `model`, `embedding_model`, `model_identity: str | None`, `model_sha256: str | None`, `purpose: Literal["smoke","baseline","corrected"]`, `split: Literal["development","assessed"]`, `prompt_path`, `prompt_variant: Literal["baseline","corrected"]`, `api_key_env: str | None = "BONSAI_HELP_API_KEY"`, `api_key_file: str | None`, `mode: Literal["json","tools"]`, `temperature` (default 0.6), `timeout_seconds` (default 120, ≤300), `max_tokens` (default 2000), `max_attempts` (default 3, ≤5), `artifact_root` (default `"runs"`), `seed: int`, `hosted: bool = False`, `hosted_authorization: str | None`, `cost_cap_usd: float | None`); methods `api_key() -> str`, `public_settings() -> dict`; `load_config(path: Path) -> RunConfig`; `load_prompt(config: RunConfig) -> tuple[str, str]` returning `(text, sha256)` and requiring the placeholders `{category}`, `{setup}`, `{sections}`.
- Policy: `artifact_root` may be `runs/` inside the repo (git-ignored) or outside it; any other in-repo path is refused. Endpoint check as the old `local_endpoint` unless `hosted` is true; hosted requires `https`, `hosted_authorization` and `cost_cap_usd > 0`.

- [ ] **Step 1:** Tests: `test_local_endpoint_rules` (public IP refused, path not `/v1` refused, credentials in URL refused), `test_hosted_requires_flag_auth_and_cap`, `test_exactly_one_credential_source`, `test_credential_never_in_public_settings` (set a sentinel key; assert absent from `public_settings()` JSON and from the `ValueError` text of a bad config), `test_artifact_root_rules`, `test_prompt_needs_placeholders`.
- [ ] **Step 2:** Write `prompts/generator-v1.md`: one prompt, the help-desk role, the seven fields with plan §6.1 meanings, "write from the sections below only; cite the ids of the sections you used", the setup record rendered as key: value lines, the sections fenced as untrusted reference text. No few-shot examples (none exist yet; gold items are frozen for MP4). Write `config/run.example.json` pointing at `http://127.0.0.1:8080/v1`.
- [ ] **Step 3:** Implement, PASS, full verification, commit `Add run configuration and generator prompt v1`.

### Task 4: Section sampler

**Files:**
- Create: `src/bonsai_help/sampler.py`
- Test: `tests/test_sampler.py`

**Interfaces:**
- Consumes: `doc_sources.load_config`, `setup` profile models (`SetupProfiles`, `VersionLine`), the docs-index section records for the fixture slice (reuse `docs_index` splitting on fixture bytes; add a helper `fixture_sections(config, fixtures_dir) -> list[dict]` if none exists), `schemas.CitedSection`.
- Produces: `Slot(slot_id: str, category: Category, setup_id: str, version_line: str)`; `plan_slots(profiles: SetupProfiles, split: str, count: int) -> list[Slot]` (count multiple of 5; `slot_id` = `f"{category}-{n:03d}"`); `sample_sections(slot: Slot, seed: int, *, config: DocSources, profiles: SetupProfiles, fixtures_dir: Path) -> list[CitedSection]`; `render_sections(sections: list[CitedSection], fixtures_dir: Path) -> str`; `verify_fixtures(config: DocSources, fixtures_dir: Path) -> None` (raises on any page whose sha256 differs from the manifest).

- [ ] **Step 1:** Tests: `test_plan_is_balanced_and_split_pure` (count 70 → 14 per category; every setup id in the requested split), `test_same_seed_same_sections` and `test_different_slot_different_draw`, `test_sections_match_category_and_version_line` (VL-older slot never gets a `bonsai-docs` 0.9 or 5.2 Manual section), `test_word_budget` (≤1,200 words; ≤2 Bonsai + ≤1 Manual), `test_developer_and_fragment_excluded`, `test_tampered_fixture_refuses` (copy the slice to `tmp_path`, change one byte).
- [ ] **Step 2:** Implement with `random.Random(digest-derived int)` per slot; PASS; full verification; commit `Add the section sampler`.

### Task 5: Model client

**Files:**
- Create: `src/bonsai_help/model_client.py`
- Test: `tests/test_model_client.py`, `tests/fakes.py` (shared fake transport and synthetic records)

**Interfaces:**
- Produces: `AttemptResult(item, raw_response, error, error_type, response_model)`; `InstructorClient(*, base_url, model, api_key, response_model, mode, temperature, max_tokens, timeout_seconds)` with `generate(messages: list[dict[str, str]]) -> AttemptResult`, `close()`, context manager; `EmbeddingClient(*, base_url, model, api_key, timeout_seconds)` with `embed(texts: list[str]) -> list[list[float]]` (raises `EmbeddingError` on any transport or shape failure).

- [ ] **Step 1:** Port every behaviour of the old `test_model_client.py` onto `httpx.MockTransport`: malformed JSON kept raw, schema-invalid output kept raw, transport error typed, no hidden retries (exactly one HTTP request per `generate`), credential echoed by the server redacted in item, raw body and logs, proxies ignored. Add `test_embedding_shape_errors` (wrong vector count, ragged dims → `EmbeddingError`).
- [ ] **Step 2:** Port the client (drop `reasoning_effort` unless a test needs it), add `EmbeddingClient` on the same OpenAI SDK with `max_retries=0`. PASS; full verification; commit `Port the model client and add the embedding client`.

### Task 6: Generation run

**Files:**
- Create: `src/bonsai_help/generate.py`
- Test: `tests/test_generation.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `implementation_identity() -> dict` (hashes every `src/bonsai_help/*.py`, `pyproject.toml`, `uv.lock`, the prompt file; path from `__package__`); `generation_metrics(starts, attempts, records, slots) -> dict` with keys `initial_slots`, `initial_valid`, `initial_validity`, `retry_recovered`, `exhausted`, `unknown_outcomes`; `generate_run(config: RunConfig, prompt: str, prompt_sha256: str, *, count: int, run_id: str, client: ModelClient, profiles, doc_config, fixtures_dir: Path, resume: bool = False) -> dict` writing `manifest.json`, `starts.jsonl`, `attempts.jsonl`, `items.jsonl` (`GeneratedItem` records) under `run_directory(artifact_root, run_id)`.
- Exit behaviour: exhaustion of a slot is recorded and the run completes with `status: "incomplete"`; the CLI maps it to exit 3 (Task 9).

- [ ] **Step 1:** Port the old `test_generation.py` behaviours with a fake client: `test_initial_attempt_denominator`, `test_retry_recovery_counted_separately`, `test_exhaustion_is_controlled`, `test_unknown_outcome_consumes_attempt` (a start with no attempt record on resume), `test_resume_refuses_changed_settings_prompt_or_code`, `test_no_overwrite_of_existing_run`, `test_messages_carry_category_setup_and_sections`, `test_cited_sections_recorded_in_envelope`.
- [ ] **Step 2:** Implement one stage: per slot, sample sections (Task 4), render the prompt, call `client.generate`, persist start → attempt → item. Assessed purposes (`baseline`, `corrected`) require `model_identity` and `model_sha256`. PASS; full verification; commit `Add one-stage, docs-grounded generation`.

### Task 7: Deterministic pre-checks

**Files:**
- Create: `src/bonsai_help/checks.py`
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: committed lexicons (`reference/lexicons/bonsai-source*.json`, `blender-manual*.json`), `GeneratedItem`.
- Produces: `CheckResult(dimension: Literal["D1",...,"D6"], name: str, passed: bool, drop: bool, detail: str)`; `load_lexicons(reference_dir: Path) -> Lexicons`; `run_checks(record: GeneratedItem, lexicons: Lexicons) -> list[CheckResult]`; constants `GENERIC_PHRASES`, `REFUSAL_PHRASES` and the thresholds of Decision 5.

- [ ] **Step 1:** Tests, one per rule and dimension, with synthetic items on real lexicon ids: `test_d1_short_answer`, `test_d2_short_or_generic_safety`, `test_d3_unknown_bim_operator`, `test_d3_known_operator_passes` (an id read from the committed lexicon), `test_uncited_section_fails_d3`, `test_d4_refusal_boilerplate`, `test_d5_thin_question`, `test_d6_generic_short_or_step_copy_tip`, `test_unknown_blender_menu_is_evidence_not_drop`, `test_normalization_catches_fullwidth_generic_phrase`.
- [ ] **Step 2:** Implement (regex for `bim\.[a-z0-9_]+`; NFKC casefold normalization from the old gate). PASS; full verification; commit `Add deterministic pre-checks`.

### Task 8: First-pass gate

**Files:**
- Create: `src/bonsai_help/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: Task 7, `EmbeddingClient`.
- Produces: `evaluate_gate(records: list[GeneratedItem], *, lexicons, embedder, embedding_model: str, threshold: float = 0.92, min_share: float = 0.18) -> dict` with keys `per_item` (item id → check results, `retained: bool`, `dropped_by`), `drops_per_check`, `exact_duplicates`, `near_duplicates`, `per_category`, `distribution: {"min_share", "passed"}`, `retained_ids`, `gate_pass_rate`, `embedding_model`, `threshold`; `gate_run(root: Path, run_id: str, *, lexicons, embedder, embedding_model) -> dict` writing `gate-report.json` once (no overwrite).

- [ ] **Step 1:** Port the old `test_gate.py` behaviours onto Bonsai items: `test_exact_duplicate_dropped_and_counted`, `test_near_duplicate_dropped_with_fake_embedder`, `test_drops_counted_per_check`, `test_distribution_fails_under_18_percent`, `test_every_dimension_has_a_precheck`, `test_embedding_failure_is_controlled` (embedder raises → `GateError`, no report file), `test_report_never_overwritten`. Remove the DIY benchmark block and hazard regexes entirely.
- [ ] **Step 2:** Implement (`gate_run` lives here, breaking the old `collection` → `cli` cycle). PASS; full verification; commit `Add the first-pass gate`.

### Task 9: Collection, cohort and CLI commands

**Files:**
- Create: `src/bonsai_help/collection.py`, `src/bonsai_help/cohort.py`, `src/bonsai_help/collection_cli.py`
- Modify: `src/bonsai_help/cli.py` (register `generate`, `gate`, `collect`, `collection-status`, `cohort`, `cohort-status`)
- Test: `tests/test_collection.py`, `tests/test_cli_generation.py`

**Interfaces:**
- Produces: `collect(config: RunConfig, collection_id: str, client, embedder, *, target_retained: int = 50, batch_count: int = 70, max_batches: int = 3, resume: bool = False) -> dict`; `collection_status(root, collection_id) -> dict`; `freeze_cohort(root, collection_id, cohort_id) -> dict` (50 items, 10 per category, seeded); `load_cohort(root, cohort_id) -> dict`. Exit codes: 0 done, 1 check failed or not ready, 2 usage/config error, 3 controlled exhaustion.

- [ ] **Step 1:** Tests: `test_collect_stops_at_target`, `test_failed_batch_is_immutable_and_counted`, `test_cohort_requires_ready_collection_and_balance`, `test_cli_exit_codes` (bad config 2, exhaustion 3), `test_cli_never_prints_credentials` (sentinel key absent from stdout/stderr on every failure path).
- [ ] **Step 2:** Port; `POLICY` becomes the parameters above; no import of `assessment` (helpers come from Task 1). PASS; full verification; commit `Add collection, cohort and generation commands`.

### Task 10: Documentation and decision record

**Files:**
- Modify: `README.md` (pipeline section: Steps 1–2 commands and outputs; status table B4), `docs/PORTING-MAP.md` (§8 B4 marked done with deviations), `docs/DECISIONS.md` (dated "Assistant's calls" entry listing Decisions 1–7 above, and any deviation made during the tasks), `AGENTS.md` (Current boundary: B4 done)

- [ ] **Step 1:** Run `uv run --locked bonsai-help generate --help`, `gate --help`, `collect --help` and paste the real usage into the README; describe outputs and the three denominators.
- [ ] **Step 2:** Full verification; grep the diff for home paths, IPs other than `127.0.0.1`, hostnames and emails; commit `Record B4 and document generation and the gate`.

---

**Not in B4:** labels, assessment, judge, calibration, analysis and charts (B6–B9); the corrected prompt (B8, pre-registered from the heatmap); any live model run (B5 needs Chad's go-ahead and a reachable endpoint).

---

## Amendments after the final review (November 24, 2026)

The tasks above are kept as written. After the final whole-branch review (workflow run
`wf_7ed4c7f4-6a3`), these statements no longer describe the code; `docs/DECISIONS.md`
(November 24, 2026) records each change.

- **Hosted profile (Global Constraints, Task 3, Review Focus 5).** Chad decided on November
  24, 2026: "Refuse hosted for now; record the rubric as moved to B5". Any `hosted: true`
  is refused at load (`config.HostedRefused`, exit 2); `hosted_authorization` and
  `cost_cap_usd` stay in `RunConfig` without effect. `test_hosted_requires_flag_auth_and_cap`
  is replaced by the hosted-refusal tests in `tests/test_config.py`. The endpoint guard is an
  explicit allowlist (loopback, RFC 1918, IPv6 unique local), and `api_key_env` must be an
  upper-case variable name.
- **Rubric.** Plan §9 listed a rubric for B4; this plan built none. It moves to B5 on
  Chad's decision.
- **Task 2 interface.** `GeneratedItem` also has `generated_at` (ISO 8601 with a UTC offset,
  equal to the attempt's `completed_at`), after `sampler_seed`.
- **Task 5.** A credential echoed by the server makes the attempt fail (`CredentialEcho`,
  raw body redacted) instead of being redacted in the item; keys under 16 characters are
  refused.
- **Decision 4.** The 0.92 threshold is fixed (`gate.DEFAULT_THRESHOLD`), not configurable;
  collections require it.
- **Task 7 interface.** `load_lexicons` also reads each version line's
  `bonsai-docs*.json` lexicon; `run_checks` takes `unoffered_citations`; the `bim.*` lexicon
  holds registered operators and macros only; menu paths match whole labels.
- **Task 8 interface.** The gate report also has `pass_rates_per_check` and
  `pass_rates_denominator`; `gate_run` writes only `gate-report.json`.
- **Task 3 Step 2.** Generator v1 also asks for user-style question phrasing (plan §7
  Step 1 item 2) and for ids cited without their square brackets.
