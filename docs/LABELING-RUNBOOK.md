# Labeling runbook (B6 baseline labels, B8 and v2 blind mixed labels)

Chad's steps for labeling assessment `b6-labels-1`: 30 baseline items drawn from cohort
`baseline-b5-cohort-1`, pinned to rubric `bonsai-rubric-v1`. The details of the commands and
their rules are in the README section [Human labels (B6)](../README.md#human-labels-b6), and
the decisions behind them are in [`DECISIONS.md`](DECISIONS.md) (November 24, 2026: B6
labeling tooling, Chad's answers to the B6 questions, and the assessment entry).

Run every command from the repository root, in an interactive terminal on the machine that
holds the git-ignored `runs/` folder (directly or over SSH). An assistant never runs
`label` or `freeze-human-reference` and never enters a label.

## Before you start (optional)

```
uv run --locked bonsai-help rubric show | less
```

Shows the accepted rubric: the labeling rules, the D1 to D6 anchors, the labeling notes and
the borderline rulings.

## 1. Label

```
uv run --locked bonsai-help label --assessment-id b6-labels-1 --reviewer "Chad Josewski"
```

- Type `label b6-labels-1` when asked to confirm.
- Each item shows its blind id (`L-001` to `L-030`), the category, the setup record, the
  seven fields, the model's quotes and the full text of the cited sections. It never shows
  the run, arm, model, gate results or judge output.
- For each dimension D1 to D6, type:
  - `1` pass, `0` fail
  - `u` unresolved, only when it truly cannot be decided from the item, its setup record
    and its cited sections; an unresolved decision is never a pass and the item stays in
    the denominator
  - `?` that dimension's labeling notes
  - `q` quit
- After all six, the summary is shown, then an optional note, then `save? [y/redo/q]`.
  Nothing is written until `y`.
- Quit at any time. Running the same command again continues where you stopped.

## 2. Check progress

```
uv run --locked bonsai-help label-status --assessment-id b6-labels-1
```

Shows counts, blind ids and label ids only.

## 3. Correct a saved label (if needed)

```
uv run --locked bonsai-help label --assessment-id b6-labels-1 --reviewer "Chad Josewski" --amend L-007 --supersedes <label id>
```

Take the label id from `label-status`. A correction is a new label that names the one it
replaces; nothing is overwritten. After the freeze, a correction is recorded as
post-review and does not change the frozen reference.

## 4. Freeze the human reference

When `label-status` reports all 30 complete:

```
uv run --locked bonsai-help freeze-human-reference --assessment-id b6-labels-1 --reviewer "Chad Josewski" --declare-blind
```

Type `freeze b6-labels-1` to confirm. `--declare-blind` declares that no judge output,
model feedback or other label was consulted. The frozen reference is the input for the B7
judge calibration (Phase A), and it is written once.

## Good to know

- Budget about 3 hours for 30 items; sessions can be split.
- Labeling only reads local files, so it can run while a model collection uses the GPU.
- If a command reports "preserve and inspect", stop and ask. Do not delete or edit
  anything under `runs/`.
- The same steps apply to the later development assessment for judge v2 (`dev-labels-1`,
  20 items) and to B8's mixed assessment, with their own assessment ids.

## B8: the blind mixed assessment `b8-blind-1`

The B8 round uses the same steps with the assessment id `b8-blind-1`. It has 40 items,
`L-001` to `L-040`, shuffled into one queue: the 20 baseline items B6 did not select and
20 items from the corrected collection (generator v1.2). Nothing on screen names an
item's run or arm, and the assistant does not say until the labels are frozen. The
queue exists only after the corrected collection is done and the assistant has created
it; the ids, seed and counts are fixed in [`DECISIONS.md`](DECISIONS.md) (November 26,
2026: Phase B pre-registration).

From the repository root:

```
uv run --locked bonsai-help label --assessment-id b8-blind-1 --reviewer "Chad Josewski"
```

Type `label b8-blind-1` to confirm. Keys, notes and saving are as in step 1.

```
uv run --locked bonsai-help label-status --assessment-id b8-blind-1
```

```
uv run --locked bonsai-help label --assessment-id b8-blind-1 --reviewer "Chad Josewski" --amend L-007 --supersedes <label id>
```

When `label-status` reports all 40 complete:

```
uv run --locked bonsai-help freeze-human-reference --assessment-id b8-blind-1 --reviewer "Chad Josewski" --declare-blind
```

Type `freeze b8-blind-1` to confirm, then tell the assistant. The one judge run on these
40 items comes next, with the Llama judge server on port 8082.

- Budget about 3 to 4 hours; sessions can be split.
- An unresolved decision (`u`) counts as a failure in both arms, so use it only when an
  item truly cannot be decided.
- Some answers state the setup they apply to (versions, schema, model state). Grade each
  item against the rubric on its own; do not try to guess its arm. Chad accepted this
  risk as a disclosed limit of B8 ("Accept, disclose (Recommended)").

## v2: the blind mixed assessment `v2-blind-1`

The same steps as B8 with the assessment id `v2-blind-1`: 40 items, `L-001` to `L-040`,
shuffled into one queue. Twenty come from a fresh baseline collection (generator v1.1)
and twenty from generator v2. Nothing on screen names an item's run or arm. The ids,
seed and counts are fixed in [`DECISIONS.md`](DECISIONS.md) (November 26, 2026: v2 run
pre-registration).

```
uv run --locked bonsai-help label --assessment-id v2-blind-1 --reviewer "Chad Josewski"
```

Type `label v2-blind-1` to confirm. Check progress and correct a label as in steps 2 and
3, with `--assessment-id v2-blind-1`. When `label-status` reports all 40 complete:

```
uv run --locked bonsai-help freeze-human-reference --assessment-id v2-blind-1 --reviewer "Chad Josewski" --declare-blind
```

Type `freeze v2-blind-1` to confirm, then tell the assistant. The one judge run comes
next, with the Llama judge server on port 8082. Budget about 3 to 4 hours. The B8 notes
on unresolved decisions and stated setups apply here too.
