"""A read-only report over a verified collection: the three denominators kept apart, each
with its counts and an exact 95% Clopper-Pearson interval (B5 Task 3).

The report reads only saved evidence through `collection.collection_status` and
`collection.verified_batches` (hash-verified ledgers and gate reports, metrics recomputed);
it never generates, gates or calls an endpoint, and it writes one new file,
`reports/<report-id>.json` under the artifact root, never an existing one.

Definitions (gated batches only; an ungated or unstarted batch is listed, never counted):

- initial-attempt schema validity: schema-valid first attempts / planned slots. The >=95%
  structural target is judged on this figure (point estimate; the interval is beside it).
- retry recovery: schema-valid results at attempt 2 or later / slots without a schema-valid
  first attempt (invalid, transport failure or unknown outcome). Never added to the first.
- gate retention: items the gate retained / schema-valid items entering the gate. The
  cross-batch screens after the gate are reported apart, as drop counts.

A rate whose denominator is 0 is undefined (`rate` and `interval` null), never 0 or 1. Gate
drops are heuristic screens, not rubric decisions: the report never states a failure rate,
which needs blind human labels and the judge.
"""

from __future__ import annotations

import json
import os
import tempfile
from fractions import Fraction
from pathlib import Path

from bonsai_help import cohort
from bonsai_help.collection import (
    FROZEN,
    CollectionError,
    collection_status,
    load_collection,
    verified_batches,
)
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.stats import clopper_pearson
from bonsai_help.tracing import now, read_json, run_directory

SCHEMA_VERSION = "1"
CONFIDENCE = 0.95
STRUCTURAL_TARGET = Fraction(19, 20)
REPORTS = "reports"
# Files whose behaviour must stay the same between the baseline and the corrected arm
# (the gate freeze, DECISIONS.md, November 24, 2026); their hashes are copied from the
# batches' recorded implementation identity so the corrected arm can be compared.
FROZEN_FILES = (
    "src/bonsai_help/checks.py",
    "src/bonsai_help/gate.py",
    "src/bonsai_help/sampler.py",
)
SETTINGS = (
    "model",
    "model_identity",
    "model_sha256",
    "purpose",
    "split",
    "prompt_path",
    "prompt_variant",
    "temperature",
    "enable_thinking",
    "max_attempts",
    "embedding_model",
    "seed",
)
DEFINITIONS = {
    "initial_schema_validity": "schema-valid first attempts / planned slots of the gated batches",
    "retry_recovery": (
        "schema-valid results at attempt 2 or later / slots of the gated batches without a "
        "schema-valid first attempt"
    ),
    "gate_retention": "items retained by the gate / schema-valid items entering the gate",
}


def figure(numerator: int, denominator: int, definition: str) -> dict:
    """Counts, rate and exact interval; undefined (null rate and interval) when n is 0."""
    if not 0 <= numerator <= max(denominator, 0):
        raise CollectionError(f"impossible count {numerator} of {denominator}; inspect the run")
    if denominator == 0:
        rate, interval = None, None
    else:
        low, high = clopper_pearson(numerator, denominator, CONFIDENCE)
        rate = numerator / denominator
        interval = {"method": "clopper_pearson", "confidence": CONFIDENCE, "low": low, "high": high}
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": rate,
        "interval": interval,
        "defined": denominator > 0,
        "definition": definition,
    }


def build_report(root: Path, collection_id: str) -> dict:
    """The report of one collection, from its verified saved evidence only; never writes."""
    summary = collection_status(root, collection_id)
    directory, manifest = load_collection(root, collection_id)
    batches = verified_batches(root, manifest)
    gated = [b for b in batches if b.get("gate") is not None]

    initial = figure(
        summary["initial_valid"], summary["initial_slots"], DEFINITIONS["initial_schema_validity"]
    )
    k, n = initial["numerator"], initial["denominator"]
    initial |= {  # compared exactly: 57 of 60 is exactly 95% and meets the target
        "target": float(STRUCTURAL_TARGET),
        "meets_target": None if n == 0 else Fraction(k, n) >= STRUCTURAL_TARGET,
    }
    retry = figure(
        summary["retry_recovered"],
        summary["initial_slots"] - summary["initial_valid"],
        DEFINITIONS["retry_recovery"],
    )
    retention = figure(
        summary["gate_retained"], summary["gate_input"], DEFINITIONS["gate_retention"]
    )

    drops: dict[str, int] = {}
    gate_categories = {c: {"gate_input": 0, "gate_retained": 0} for c in CATEGORIES}
    for batch in gated:
        for check, count in batch["gate"]["drops_per_check"].items():
            drops[check] = drops.get(check, 0) + count
        for category, value in batch["gate"]["per_category"].items():
            gate_categories[category]["gate_input"] += value["input"]
            gate_categories[category]["gate_retained"] += value["retained"]
    cross = {"cross_batch_duplicate": 0, "cross_batch_near_duplicate": 0}
    for decision in summary["decisions"]:
        for reason in decision["reasons"]:
            cross[reason] += 1

    shares = {b["run_id"]: b["gate"]["distribution"]["min_share"] for b in gated}
    retained = summary["retained"]
    minimum = summary["policy"]["min_per_category"]
    per_category = {
        c: {
            "retained": summary["counts"][c],
            "share": summary["counts"][c] / retained if retained else None,
        }
        | gate_categories[c]
        for c in CATEGORIES
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "collection_report",
        "created_at": now(),
        "collection_id": collection_id,
        "collection_sha256": manifest["sha256"],
        "status": summary["status"],
        "reasons": summary["reasons"],
        "policy": summary["policy"],
        "settings": {k: manifest["identity"]["settings"].get(k) for k in SETTINGS},
        "prompt_sha256": manifest["identity"]["prompt_sha256"],
        "inputs": manifest["identity"].get("inputs"),
        "frozen_files": _frozen_files(gated),
        "scope": "gated batches only; ungated or unstarted batches are listed, never counted",
        "figures": {
            "initial_schema_validity": initial,
            "retry_recovery": retry,
            "gate_retention": retention,
        },
        "exhausted_slots": {
            "count": summary["exhausted"],
            "slot_ids": [s for b in gated for s in b["metrics"]["exhausted_slot_ids"]],
        },
        "unknown_outcomes": {
            "count": summary["unknown_outcomes"],
            "attempt_ids": [a for b in gated for a in b["metrics"]["unknown_attempt_ids"]],
        },
        "gate_drops_per_check": drops,
        "gate_drops_note": "one item can fail several checks; drops per check do not add up "
        "to the items dropped",
        "cross_batch_drops": cross,
        "retained": retained,
        "per_category": per_category,
        "distribution": {
            "rule": "the collection's own: every category at min_per_category or more",
            "min_per_category": minimum,
            "passed": all(summary["counts"][c] >= minimum for c in CATEGORIES),
            "deficits": {c: n for c, n in summary["counts"].items() if n < minimum},
            "batches": [
                {
                    "run_id": b["run_id"],
                    "distribution_passed": b["distribution_passed"],
                    "min_share": shares.get(b["run_id"]),
                }
                for b in summary["batches"]
            ],
        },
        "batches": summary["batches"],
        "cohort": _cohort(root, directory),
        "quality_status": "pending",
        "failure_rate_status": "not measured: it needs blind human labels (B6) and the judge "
        "(B7); gate drops are heuristic screens, never rubric decisions",
    }
    # The evidence must not have moved while it was read.
    if load_collection(root, collection_id)[1]["sha256"] != manifest["sha256"]:
        raise CollectionError("collection manifest changed while the report was built; inspect it")
    return report


def _frozen_files(gated: list[dict]) -> dict | None:
    """The frozen files' hashes as every gated batch recorded them; differing batches are refused."""
    seen = []
    for batch in gated:
        files = (batch["manifest"].get("implementation") or {}).get("source_files") or {}
        seen.append({name: files.get(name) for name in (*FROZEN_FILES, "prompt")})
    if not seen:
        return None
    if any(entry != seen[0] for entry in seen):
        raise CollectionError("gated batches record different frozen-file hashes; inspect them")
    return seen[0]


def _cohort(root: Path, directory: Path) -> dict | None:
    """The frozen cohort, re-verified against the collection, or None before a freeze."""
    if not (directory / FROZEN).exists():
        return None
    receipt = read_json(directory / FROZEN)
    cohort_id = receipt.get("cohort_id")
    if not isinstance(cohort_id, str):
        raise CollectionError("cohort freeze receipt is malformed; inspect it")
    frozen = cohort.load_cohort(root, cohort_id)
    return {"cohort_id": frozen["cohort_id"], "sha256": frozen["sha256"]}


def report_path(root: Path, report_id: str) -> Path:
    reports = root / REPORTS
    if reports.is_symlink():
        raise ValueError("a symlinked reports directory is not supported")
    target = run_directory(reports, report_id)
    return target.with_name(f"{report_id}.json")


def write_report(root: Path, collection_id: str, report_id: str | None = None) -> tuple[Path, dict]:
    """Build the report and write it once to `reports/<report_id>.json`; an existing file is
    never replaced (FileExistsError). The default ID is `<collection_id>-report`."""
    path = report_path(root, f"{collection_id}-report" if report_id is None else report_id)
    if path.exists() or path.is_symlink():
        raise FileExistsError(17, "report exists", str(path))
    report = {"report_id": path.stem} | build_report(root, collection_id)
    text = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".report-", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # fails, writing nothing, if the report appeared meanwhile
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return path, report


def _percent(value: float) -> str:
    return f"{value:.1%}"


def _line(name: str, value: dict) -> str:
    k, n = value["numerator"], value["denominator"]
    if not value["defined"]:
        return f"{name}: undefined ({k} of {n})"
    interval = value["interval"]
    return (
        f"{name}: {k}/{n} = {_percent(value['rate'])} "
        f"(95% CI {_percent(interval['low'])}-{_percent(interval['high'])})"
    )


def render_summary(report: dict, path: Path) -> str:
    """A short plain-text summary of a report."""
    figures = report["figures"]
    initial = figures["initial_schema_validity"]
    target = {True: "met", False: "not met", None: "undefined"}[initial["meets_target"]]
    drops = ", ".join(f"{k} {v}" for k, v in report["gate_drops_per_check"].items() if v) or "none"
    cross = report["cross_batch_drops"]
    categories = ", ".join(
        f"{c} {v['retained']}" + (f" ({_percent(v['share'])})" if v["share"] is not None else "")
        for c, v in report["per_category"].items()
    )
    distribution = report["distribution"]
    outcome = {True: "passed", False: "failed", None: "not gated"}
    batch_results = ", ".join(
        f"{b['run_id']} {outcome[b['distribution_passed']]}" for b in distribution["batches"]
    )
    frozen = report["cohort"]
    cohort_line = (
        f"cohort: {frozen['cohort_id']} (sha256 {frozen['sha256']}), verified"
        if frozen
        else "cohort: not frozen"
    )
    reasons = ", ".join(report["reasons"])
    lines = [
        f"collection {report['collection_id']} (sha256 {report['collection_sha256']})",
        f"status: {report['status']}" + (f" ({reasons})" if reasons else ""),
        f"report: {path}",
        _line("initial-attempt schema validity", initial)
        + f"; target >={_percent(initial['target'])}: {target} (point estimate)",
        _line("retry recovery", figures["retry_recovery"])
        + " [valid at attempt >=2 / slots without a valid first attempt]",
        _line("gate retention", figures["gate_retention"])
        + " [retained / schema-valid gate input]",
        f"exhausted slots: {report['exhausted_slots']['count']}; "
        f"unknown outcomes: {report['unknown_outcomes']['count']}",
        f"gate drops per check (an item can fail several): {drops}",
        f"cross-batch drops: exact {cross['cross_batch_duplicate']}, "
        f"near {cross['cross_batch_near_duplicate']}",
        f"retained: {report['retained']} of target {report['policy']['target_retained']}; "
        f"per category (min {distribution['min_per_category']}): {categories}",
        f"distribution: per-category minimum {'met' if distribution['passed'] else 'not met'}; "
        f"batch gate share check: {batch_results}",
        cohort_line,
        "quality: pending (no failure rate: it needs blind labels and the judge)",
    ]
    return "\n".join(lines)
