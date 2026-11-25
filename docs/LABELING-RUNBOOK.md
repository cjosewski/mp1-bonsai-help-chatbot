# Labeling runbook (B6 baseline labels)

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
