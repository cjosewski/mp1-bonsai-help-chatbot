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
- **Hosted judge and doc excerpts (open question raised by the assistant).** The plan's
  judge receives the cited doc sections (§7 Step 4), and §8 "Models" allows a documented
  hosted path with Chad's authorization of any spend. Whether a hosted judge may receive
  those open-licensed Bonsai and Blender Manual excerpts is not decided. It needs a dated
  decision from Chad before any hosted run. Human ratings are never sent to a hosted
  service.
- **Human label notes stay out of `submission/`.** Labels in `submission/` carry the
  decisions and IDs only; free-text reviewer notes stay outside Git.

## Open items (not yet decided)

| ID | Item | Plan default (applies until Chad decides) |
| --- | --- | --- |
| O-2 | Confirm the five categories in plan §5 | Use them as proposed: `bonsai_project_setup`, `bonsai_modeling`, `ifc_data_and_materials`, `model_exploration`, `files_versions_troubleshooting` |
| O-3 | Setup profiles: include Blender 4.2 LTS with Bonsai 0.8.5-post1, or only Blender 5.x with Bonsai 0.9.0 | Include it, as the older-release contrast |
| O-6 | Recheck the Unit 5 Module 2 exercises and the Unit 7 and Unit 8 Module 1 notebooks when they are published | Recheck at B4 and before B10 |
| O-7 | Distribution reference for category balance | Uniform 20% target |

## Amendment rule

Any change to a course threshold or criterion is a new dated entry here, with its
reason. Original criteria are preserved; nothing is weakened silently.
