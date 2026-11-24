# Mini Project 1 — Bonsai help Q&A synthetic data: adaptation plan

Owner: Chad Josewski. Drafted November 21, 2026, revised the same evening from Revit to Blender with Bonsai. Status: **proposed plan, not started; scope revised November 23, 2026** (Chad: "This plan is approved. Modify MP1 as needed."). Mini Project 1 now creates and evaluates synthetic data only; the help chatbot, the gold set and the security pass move to Mini Project 4 (§1, `docs/DECISIONS.md`). Execution is tracked in the owner's private program plan (P1-03). This document owns the adapted scope, how the course material maps onto it, and what it must meet. Hours are planning assumptions. Dates are left open on purpose; the program schedule is unchanged.

## 1. What changes

Mini Project 1 becomes a **synthetic Q&A data pipeline for one AEC topic: building information modeling with Bonsai in Blender.** A single structured generation prompt, parameterized by category and user setup, writes complete seven-field help items from pinned sections of the Bonsai documentation and the Blender Manual. The same documentation grounds the judge that evaluates the items. The deliverable is the data and its evaluation, as in the course brief.

**Revision of November 23, 2026.** The first version of this plan made the generator a help chatbot that answered generated questions, with read-only doc tools, a reviewed gold set, multi-part and injection requests and a security pass. Against the course briefs these go beyond Mini Project 1 and match Mini Project 4 (a RAG question-answering system with citations and its own judge). Chad approved a project map on November 23, 2026 that moves them there. In this plan the chatbot, the doc tools, the gold set (B3) and the security pass are withdrawn from MP1; the gold-set tooling and its 6 published items stay in this repository, frozen, as the seed for MP4's relevance labels. Everything else stands.

This follows the bank support-bot pattern that runs through Units 2, 4 and 5. There, the model reads the bank's fee policy and the customer's account type, answers the customer, and is graded against the policy. Here, the generator reads the Bonsai and Blender documentation and a user setup (Blender and Bonsai versions, IFC schema, discipline, model state), writes the question and its answer, and the item is graded against the documentation.

### Ground rules from Chad (November 21)

- No instructor approval is needed. Chad may change the project as long as the learning objectives are met and a functioning example runs and can be tested in the repository.
- It is a course example only: not a commercial or public product.
- The repository must be public, because the course evaluates the project from it.
- Keep the course's categories where they apply; otherwise derive new ones (§5).
- Dates are out of scope for now.

### Why not Revit

Revit was the first choice and was tested on November 21. The data itself was reachable: a plain script on Chad's workstation downloaded the full Revit 2027 table of contents (`data/toctree.json`, 7.8 MB) without a browser, and individual topic pages return readable text. The blocker is the license. Revit Help is under Creative Commons Attribution-NonCommercial-ShareAlike 3.0, a poor fit for a public repository. Revit is also proprietary software that a grader may not have. Blender and Bonsai are free, and their documentation is open-licensed and kept in public git repositories.

### What stays the same

The course's customization rule is to change the topic, not the technical stack, libraries or criteria. Kept as is:

- The six-step pipeline: generate, first-pass gate, human labels, LLM judge, analysis, two-phase iteration, each runnable on its own against saved artifacts.
- Python 3.10+, Pydantic and Instructor for structured output; Matplotlib or Seaborn for charts.
- The seven-field payload (`question`, `answer`, `equipment_problem`, `tools_required`, `steps`, `safety_info`, `tips`) and its validation rules.
- At least 50 items per run across five categories at 20% each; at least 20 human-labeled items; six binary quality dimensions; an independent judge at a lower temperature than the generator.
- The targets: ≥95% structural validity, ≥15% honest baseline failure, ≥80% human/judge agreement in every dimension, ≥80% corrected overall pass, and more than 80% relative failure reduction.
- The deliverables: baseline and corrected JSONL, gate report, labels, judge records, per-item traces, five charts, iteration log, README, demo and coaching approval.

Chad's freedom to adapt means a threshold can be changed if the data shows it cannot be met honestly. Any such change is written down as a dated amendment with its reason, never applied silently.

### What is new

| Change | Why |
| --- | --- |
| One topic, Bonsai BIM in Blender, with five categories derived from the documentation (§5) | Owner direction, November 21 |
| A user-setup record travels with every item, outside the seven-field payload | The bank example's account type: an answer can be right for one setup and wrong for another |
| The Bonsai docs and the Blender Manual are the knowledge source for generation and judging | The bank example's fee policy |
| A deterministic check layer runs beside the judge: operator names, cited doc pages, quoted passages | The bank example's regex answer checks |
| The generator is grounded in selected doc sections from the baseline on; Phase B is a targeted change to the generation prompt for the worst segment and dimension | Course brief, Step 6 (Phase B targets the generation prompt); the plan's grounding in pinned docs (§2) |
| The help chatbot, doc tools, gold set and security pass move to Mini Project 4 | Chad's project map, November 23 |

## 2. Knowledge sources, tested November 21

| Source | Pin | Size | License | Access test |
| --- | --- | --- | --- | --- |
| Bonsai documentation, `src/bonsai/docs` in the [IfcOpenShell repository](https://github.com/IfcOpenShell/IfcOpenShell) | Tag `bonsai-0.9.0post1`, the current stable Bonsai (0.9.0-post1, October 15, 2026, for Blender 5.1 and newer) | 95 reStructuredText pages, about 50,500 words; about 31,500 words outside the developer guides | Inside `src/bonsai`, which the repository licenses GPL-3.0-or-later (the docs' `conf.py` carries the GPL header) | Sparse git clone succeeded from this workspace; GitHub is reachable from the workstation too |
| Bonsai operator names, `src/bonsai/bonsai/bim/module/*/operator.py` | Same tag | 1,311 unique `bim.*` operator ids, 1,559 labels | GPL-3.0-or-later | Same clone |
| [Blender Manual](https://docs.blender.org/manual/en/latest/) source, `projects.blender.org/blender/blender-manual` | The 5.3 release branch, matching Blender 5.3 (released November 10, 2026); main is already 5.4 | 2,450 pages on main (modeling 794, interface 59, files 33, scene layout 65) | CC BY-SA 4.0 or later, except logos, trademarks, icons, source code and Python scripts | Git works from the workstation; this workspace cannot reach projects.blender.org; the HTML site returns 403 to a plain script |

Release facts: Blender 5.3 was released on November 10, 2026; 5.2 LTS is the long-term release. Bonsai 0.9.0 lists Blender 5.1 and newer; a separate 0.8.5-post1 build still serves Blender 4.2 LTS.

**What the test shows.** Both sources can be taken as git snapshots: pinned, hashed and reproducible, with no scraping. The Bonsai docs are thin in places. Six guide sections (drawings, costing and scheduling, services, structural analysis, facility management, coordination) are stubs of 5 to 282 words, and 44 pages carry the project's "incomplete" notice. The categories in §5 follow the parts that are written. The Blender Manual covers the Blender side every Bonsai task relies on: navigation, selection, snapping, transforms, modifiers, collections, saving and appending.

**What goes in the public repository.** Both licenses allow public redistribution with attribution, and both are share-alike. The plan:

- Commit the snapshot builder, the pinned commits and a manifest of page hashes. The full corpus is rebuilt with one command, so the grader gets the same text.
- Commit a small attributed fixture slice (a few dozen pages) so the offline tests and the demo run without network access.
- License the generated datasets CC BY-SA 4.0, because questions and answers derived from the Manual are adaptations of it, and say so in the README with attribution to the Blender Documentation Team and the IfcOpenShell contributors.
- The repository's own code license is open item O-1.

## 3. Course material behind this plan

| Source | What was used | Read |
| --- | --- | --- |
| [MP1 portal brief](https://community.newline.co/ai-accelerator-cohort-2026/community?space=7764533d-9888-422e-a11c-83e00817859b) | Customization rule, goal, six-step architecture, logging, benchmark use, six dimensions, thresholds, deliverables, charts, evaluation approach | November 21, signed-in portal |
| Unit 2 Notebooks 1–3 | First call, harness and trace with the pretend bank, four prompt layers | Course materials |
| Unit 3 | Product shapes, niche, project brief (16/16 complete on the portal) | Portal catalog |
| Unit 4 Notebooks 1–5 and bank data (`bank_fee_policy.md`, `fee_policy_questions.json`, `customer_complaints.json`, `fee_calculations.json`) | Prompt layers, structured output, long-document prompts, chaining and reflection, context failures, attacks and defences | Course materials |
| Unit 5 Module 1 Notebooks 1–3, `bank_bot_replies_judged.csv` | Accuracy and exact match, guessing baseline, declined answers, pass@k; recall, precision, judge TPR/TNR; standard errors, intervals, paired comparison, run-to-run variance | Portal links |
| Unit 5 Module 3, "LLM-as-Judge: Automated Evaluation for Customer Support Chatbots" | Dataset exploration, synthetic-data quality checks, v1 judge, full run, human comparison, error analysis, v2 judge | Portal links |
| Unit 6 Module 1 Notebooks 1–3 and "Tokens and embeddings" | Tokens and cost, embeddings, similarity matrix, semantic search, same-model rule, similarity-chosen few-shot examples | Portal links |
| Unit 7 | Lesson descriptions: an agent loop with three bank tools and a step budget; plan-then-execute and rails; guardrails (allow-list, approval gate, idempotency key, latency and cost) | Notebooks marked "coming soon" on November 21 |
| Unit 8 | Module 2 notebook (`LLMOPS.ipynb`) and the Module 1 descriptions: traces to a dataset with a per-customer split and content hash; simulation through a quality gate as an offline job | Module 1 notebooks marked "coming soon" on November 21 |

Unit 1 is environment and onboarding. The Unit 5 Module 2 exercises and the Unit 7 and Unit 8 Module 1 notebooks were not yet published; O-6 covers rechecking them.

## 4. Bank example to Bonsai, element by element

| In the bank example | In the Bonsai plan | Course source |
| --- | --- | --- |
| Fee policy in numbered sections; the current policy overrides old FAQ pages | Doc pages cut at their headings, one record each (page path, heading, source, pinned commit); the pinned release overrides older material | U4 NB4 Ex1, Ex5, Ex7 |
| Account type (Everyday vs Premier; Standard, Plus, Premium) | User setup: Blender and Bonsai versions, IFC schema (IFC2X3, IFC4, IFC4X3), discipline, model state (new project, opened IFC, large federated model) | U5 M1 `bank_bot_replies_judged.csv`; U4 fee plans |
| The model cannot see the balance; the harness calls a tool | The chatbot cannot see the user's model. It reads only the setup record and the docs, through two read-only tools: `search_docs` and `get_doc_section` | U2 NB2 Ex1–2 |
| 20 policy questions with gold answer, section and regex check, some flagged unusual | A gold set: question, setup, reference answer, doc sections, check patterns (operator id, panel path, hotkey), unusual flag | U4 NB1, NB4 |
| Multi-issue complaints in different tones | Multi-part requests drawn from the six Bonsai tutorials ("my door won't cut the wall and the window is on the wrong storey") | U4 NB3 Ex3 |
| Faults: wrong figure for the account, made-up fact, no next step | Faults: wrong for the setup, invented operator or panel, no next step, and a plain Blender action that breaks the IFC model (§6.3) | U5 M1 NB2 Ex3 |
| Old FAQ next to the current policy | Older BlenderBIM-era instructions next to Bonsai 0.9 docs | U4 NB4 Ex7 |
| Hidden instruction in a document the bot reads | Instruction planted in an IFC property value, an element name or a pasted doc excerpt | U4 NB5 Ex3 |
| Judge measured by TPR and TNR on human labels | Same, per dimension, on Chad's blind labels | U5 M1 NB2 Ex3; U5 M3 Ex5 |
| Agent with three bank tools and a step budget | Chatbot loop with two read-only doc tools, a step budget and errors returned as observations; no write tool exists | U7 M1 descriptions |
| Traces split by customer, content-hashed | Items split by setup profile so no profile leaks between development and assessed sets; every snapshot hashed | U8 M1 descriptions |

Since the November 23 revision, the rows for the doc tools, the gold set, multi-part requests, planted instructions and the agent loop belong to Mini Project 4. MP1 keeps the documentation as the rules, the user setup, the fault types, stale instructions, judge measurement and the profile split.

The account-type role is carried mostly by the Blender-versus-Bonsai boundary. Bonsai treats the IFC file as the model, so a plain Blender action can be right in Blender and wrong in Bonsai. The IFC schema and the Blender/Bonsai version pairing add the rest. Every setup-dependent fact is cited to a doc page or release note (§6.4); none is assumed.

## 5. Categories

The course has five categories at 20% each. Revit's were not kept, so these are derived from the parts of the Bonsai docs that are written, with Blender Manual pages for the Blender steps each task needs:

| ID | Category | Main doc pages (words) |
| --- | --- | --- |
| `bonsai_project_setup` | Starting a project, project info, units, spatial structure, georeferencing | starting_new_project (869), project_info (2,416), georeferencing (1,804), create_model (472) |
| `bonsai_modeling` | Walls, slabs and roofs, doors, windows, openings, parametric geometry | creating_walls (1,051), door (946), window (867), opening (389), toolbar/wall (635), parametric_geometry (256) |
| `ifc_data_and_materials` | IFC classes and types, representations, properties, material assignment | understanding_ifc pages (about 1,350), geometry_and_materials (1,497), material_assignment (526), properties (205) |
| `model_exploration` | Opening and exploring IFC models, the scene, large and federated models | explore_model (2,870), scene (1,533), dealing_with_large_models (1,160), toolbar/explore (281) |
| `files_versions_troubleshooting` | Saving and loading IFC, Git support, installation, add-on conflicts, troubleshooting | git_support (1,544), troubleshooting (1,247), other_addons (349), installation (176) |

Drawings and documentation, costing, services, structural analysis, facility management and coordination are left out because their pages are stubs. Every category mixes setup profiles, so setup-dependent faults can surface anywhere. Confirming these is open item O-2.

## 6. Payload and dimensions

### 6.1 The seven fields in Bonsai terms

| Field | Meaning |
| --- | --- |
| `question` | The user's question, as asked |
| `answer` | A direct answer for the stated setup |
| `equipment_problem` | The task or failure in Bonsai terms (the course's field name is kept) |
| `tools_required` | The Bonsai and Blender tools, operators, panels or hotkeys used, named as the docs name them |
| `steps` | At least three ordered steps, with the panel or menu path |
| `safety_info` | The specific risk to the IFC model or the user's work, and the precaution (§6.3) |
| `tips` | Useful advice beyond the steps |

The item envelope, outside the payload, holds the setup id, category, cited doc sections, prompt version, model, timestamp and trace id.

### 6.2 The six dimensions

Course names and order are kept; the anchors are rewritten for Bonsai.

| Dim | Course name | Passes when | Target |
| --- | --- | --- | --- |
| D1 | Answer completeness | The answer resolves the question for the stated setup, and every part of a question with several parts is addressed | ≥85% |
| D2 | Safety specificity | `safety_info` names a real risk to the IFC model or the user's work for this task, with the precaution that prevents it; generic warnings fail | ≥90% |
| D3 | Tool realism | Every named operator, panel, setting and hotkey exists in the stated Bonsai and Blender versions and matches the docs. Plain Blender steps are offered only where the docs say they are safe on IFC objects | ≥95% |
| D4 | Scope appropriateness | The answer stays within what Bonsai and Blender support. It says when the task needs another tool, a script, a bug report or a forum question, and when a design decision needs a qualified professional | ≥95% |
| D5 | Context clarity | The answer states which versions, schema and setup it applies to, and any assumption it made | ≥90% |
| D6 | Tip usefulness | At least one tip is specific to the task and not already in the steps | ≥85% |

### 6.3 What counts as a hazard

Typical candidates: changes made in Blender that never reach the saved IFC file; editing IFC objects with plain Blender operations (applying modifiers, joining, deleting outside Bonsai); undo limits; Git merges of IFC files; georeferencing changes that move the whole model; and loading a very large model. Each is used in scoring only after it is confirmed against the docs, with the page cited. An answer passes D2 when it names the hazard that applies to its own steps.

### 6.4 Deterministic checks (Step 2, and evidence for the judge)

- Every `bim.*` operator id or label in `tools_required` and `steps` is matched against the 1,311-operator lexicon from the pinned Bonsai source. An unknown id is a D3 pre-check failure.
- Blender operators and menu paths are matched against a lexicon extracted from the pinned Manual.
- Cited doc sections must exist in the snapshot, and any quoted passage must appear verbatim in the cited section (U4 NB1 Ex7, NB4 Ex8).
- A setup-fact table lists each version or schema difference the generated items may depend on, with its citation. Uncited rows are not scored.
- The gold questions' check patterns, which scored answers against reference answers, move with the gold set to Mini Project 4.

These run before labeling, as the brief requires. They are heuristics and never replace a human or judge decision.

## 7. Pipeline

### Step 1 — Generate

One structured generation prompt, parameterized by category and setup profile, writes each complete seven-field item through Instructor and Pydantic, as the brief's Step 1 requires.

1. **Select sections.** For each slot (category × setup profile), sample pinned doc sections from that category's pages, plus the Blender Manual pages its steps need. The sampler and its seed are recorded.
2. **Generate.** The prompt gives the category, the setup record and the selected sections, and asks for a realistic user question (phrased the way users ask: half-remembered names, BlenderBIM-era terms) and its answer in the seven fields, citing the sections it used.
   - **Baseline (generator v1):** the plain category-parameterized prompt with its sections.
   - **Corrected (Phase B):** one targeted change to that prompt for the worst segment × dimension found in the heatmap, pre-registered before the run (§7, Step 6). Not a rewrite.

Every attempt keeps its prompt version, category, setup, cited sections, model, timestamp and raw response. Generate about 70 items per run so that at least 50 pass the gate.

### Step 2 — First-pass gate

Schema validation; the checks in §6.4; a generic-phrase block list for D2 and D6; duplicate removal by normalized text and by embedding similarity, with one embedding model for every vector (U6 NB3, same-model rule); and category counts against 20%. The gate report gives pass rates per check, items dropped per check, duplicates removed and the distribution result.

### Step 3 — Human labels

The existing resumable CLI, with the rubric version pinned. Chad labels at least 20 baseline and 20 corrected items without knowing which run they came from, with the cited doc sections shown beside each item and no judge output.

### Step 4 — Judge

An independent prompt at a lower temperature than the generator, with Instructor/Pydantic output: six decisions and a short reason each. The judge receives the item, the setup record, the cited sections and the deterministic check results, which is what a human reviewer would consult. v1 has criteria and labeling rules only. v2 adds rules and few-shot examples drawn from development disagreements and chosen by similarity (U5 M3 Ex3 and Ex6; U6 NB3 Topic 6).

### Step 5 — Analyze

- Pass rate per dimension per segment (category, setup, prompt variant).
- Agreement per dimension, with TPR and TNR.
- 95% intervals on every rate (U5 M1 NB3), because 20 labels give wide ones.
- Gate statistics.
- The five required charts: pass rates before and after, segment heatmap, agreement by dimension, category distribution and paired before/after bars.

### Step 6 — Iterate

- **Phase A, judge calibration** on the baseline items, until every dimension reaches at least 80% agreement. Changes come from disagreement patterns, not single cases (U4 NB2 Ex7).
- **Phase B, generator correction.** Take the worst segment and dimension from the heatmap and pre-register one targeted change to the generation prompt for that segment (a category or a setup profile) before any corrected run. Freeze the judge, rerun Steps 1–5 and compute `(baseline_failure − corrected_failure) / baseline_failure`.

Every prompt change gets an iteration-log entry: date, change, hypothesis, before and after, decision.

### Security pass

Moved to Mini Project 4 with the chatbot (November 23 revision). MP1 has no user-facing model, so there is nothing for a planted instruction to reach.

## 8. Repository and models

**Repository.** Build in this repository, `mp1-bonsai-help-chatbot`, which is public and was started from a clean first commit on November 21. The generation, gate, label, judge, calibration and analysis modules carry over from `aia-mp1-synthetic-data` at B4, ported module by module with tests as listed in [PORTING-MAP.md](PORTING-MAP.md). New pieces: the snapshot builder and checker, the setup profiles and fact table, the two lexicon extractors and the section sampler for generation. The read-only retrieval tools move to Mini Project 4. `aia-mp1-synthetic-data` returns to private with its history intact; the earlier AEC evidence and its hashes stay frozen there and are not compared.

Before submission, the repository needs:

- The course notebooks and bank data were removed on November 21 (PR #1) and are kept outside the repository. Their earlier commits stay in the old repository, which is private again; this repository starts from a clean first commit, so no history rewrite is needed (O-4, resolved November 21).
- `AGENTS.md` is written for this repository and records that it is public.
- The course submission needs the final datasets, labels, judge records, traces and charts in the repository. The submission set is committed under `submission/`; raw attempt logs and scratch runs stay outside Git (O-5, decided November 21).
- A README a grader can follow: install, rebuild the corpus, run the offline tests and run each step.

**Models.** Generation runs on a local model through Herd, falling back to Ollama or LM Studio. The judge is a different model, or the same one with a different prompt at a lower temperature. A grader without local models needs one documented hosted path through an OpenAI-compatible API, as the course notebooks use OpenRouter; any hosted spend needs Chad's authorization. Offline tests and a replay demo run against the committed fixtures with no model at all, so the repository can be tested without credentials.

## 9. Milestones

Hours are assumptions, not measurements. The 26 h reference in the program schedule covers the original assignment. The November 23 revision withdrew B3 and narrowed B4, B9 and B10; B0–B2 are done and their hours are spent. On November 24, 2026 Chad moved the rubric from B4 to B5 ("Refuse hosted for now; record the rubric as moved to B5"; `docs/DECISIONS.md`, November 24, 2026); the hours are unchanged.

| ID | Milestone | Acceptance | Hours |
| --- | --- | --- | ---: |
| B0 | Repository readiness | AGENTS updated; O-1, O-4 and O-5 decided; README skeleton | 1.5 (done) |
| B1 | Doc snapshots | Bonsai and Manual snapshots pinned, hashed and rebuildable by one command; attribution and license notices; fixture slice committed | 4 (done) |
| B2 | Lexicons and setup facts | Operator lexicons extracted; setup profiles; every fact row cited | 3 (done) |
| B3 | ~~Gold set and requests~~ | Withdrawn November 23, 2026: moves to Mini Project 4. Tooling and 6 published items stay, frozen | — |
| B4 | `bonsai-help` domain | Categories, section sampler, generation prompt v1 and pre-checks; each ported module arrives with its tests passing (rubric moved to B5, November 24, 2026) | 6 |
| B5 | Rubric and baseline run | Rubric (D1–D6 with Bonsai anchors and targets), versioned for the labels; ≥50 retained, ≥95% initial-attempt schema validity, gate report, honest failure rate | 2 |
| B6 | Baseline labels | ≥20 blind human labels | 3 |
| B7 | Judge and Phase A | v1 and v2 judge; agreement per dimension with intervals; ≥80% in each | 6 |
| B8 | Phase B | Correction pre-registered from the heatmap; corrected run ≥50; ≥20 blind labels; improvement ratio | 7 |
| B9 | Analysis | Five charts, segment metrics | 2 |
| B10 | Submission | README, iteration log, traces, `submission/` set, replay demo of the pipeline, demo video, coaching approval | 4 |
| | **Remaining (B4–B10)** | | **30** |

Order: B4 → B5 → B6 → B7 → B8 → B9 → B10. B6 and B8 need Chad's labels.

## 10. How this feeds later projects and the capstone

- Mini Project 3 reuses the pinned corpus (built to PDF) for its retrieval grid; Mini Project 4 builds the Bonsai help chatbot on it, with the frozen gold set as its relevance labels; Mini Project 5 fine-tunes an embedding model on question and doc-section pairs from the same index. Chad's project map (November 23, 2026) records the plan; the dataset swaps are asked of the instructor, because a re-themed project is reviewed against the original criteria.
- The snapshot builder, setup profiles and grounded judge are a small first instance of the shared core's corpus, retrieval and evaluation pieces. Bonsai is IFC-native, so the fault types carry over to the capstone's IFC and native-design work.
- Business documents may describe this as a course project that generates and evaluates documentation Q&A data. They may not present it as a product or a client result.

## 11. Open items

| ID | Item | Default if unanswered |
| --- | --- | --- |
| O-1 | Code license for the public repository | GPL-3.0-or-later, matching Bonsai; generated data CC BY-SA 4.0 |
| O-2 | Confirm the five categories in §5 | Use them as proposed |
| O-3 | Setup profiles: include Blender 4.2 LTS with Bonsai 0.8.5-post1, or only Blender 5.x with Bonsai 0.9.0 | Include it, as the older-release contrast |
| O-4 | Remove the course notebooks from earlier commits | Resolved November 21: new clean repository; the old repository goes private with its history intact, so no rewrite |
| O-5 | Commit the submission set under `submission/`, changing the evidence-outside-Git rule for that folder only | Yes |
| O-6 | Recheck the Unit 5 Module 2 exercises and the Unit 7 and Unit 8 Module 1 notebooks when they are published | Recheck at B4 and before B10 |
| O-7 | Distribution reference: the course benchmark is DIY; use a uniform 20% target | Uniform 20%; asked of the instructor in the project map (November 23) |
| O-8 | Repository name: `mp1-bonsai-help-chatbot` still names the chatbot, which moved to Mini Project 4 | Keep the name until Chad decides; renaming changes the public URL |

## 12. Risks

| Risk | Effect | Response |
| --- | --- | --- |
| Bonsai docs are thin, so generated answers lack support | False D3 failures, ungrounded items | Use only the written categories; add Manual pages for Blender steps; check operators against the lexicons; drop items whose cited sections do not support them |
| A grounded generator fails less than 15% at baseline | Improvement ratio meaningless | Weight the slot plan toward Blender-versus-Bonsai and setup-dependent cases; never plant defects; report the rate honestly and amend the threshold openly if it still falls short |
| Docs change during the project | Scores drift | Pin commits and hash the snapshot before the baseline run (done at B1) |
| Twenty labels give wide intervals | An 80% agreement point estimate says little | Report counts and intervals beside every rate |
| The judge sees the sections each item cites | It may favor items that quote the docs | Give the judge the cited sections for both runs alike; check quote support separately |
