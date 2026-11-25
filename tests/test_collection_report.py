"""The read-only collection report: denominators, intervals, write-once, synthetic models only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_collection import UniqueClient, make_config, run_collect

from bonsai_help import cli, cohort, generate
from bonsai_help.collection import CollectionError
from bonsai_help.collection_report import (
    FROZEN_FILES,
    build_report,
    render_summary,
    write_report,
)
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.model_client import AttemptResult
from bonsai_help.stats import clopper_pearson


class RetryAndDropClient(UniqueClient):
    """Call 1 is broken JSON (slot 1 recovers at attempt 2); call 3 has a too-short answer,
    which the gate's answer_length check drops."""

    def generate(self, messages):
        if self.calls == 0:
            self.calls += 1
            return AttemptResult(None, "{synthetic-broken-json", "invalid JSON", "ValidationError")
        result = super().generate(messages)
        if self.calls == 3:
            item = result.item.item.model_copy(update={"answer": "Too short."})
            output = result.item.model_copy(update={"item": item})
            result = AttemptResult(output, result.raw_response, None, None, "synthetic-model")
        return result


def tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def interval(k: int, n: int) -> dict:
    low, high = clopper_pearson(k, n)
    return {"method": "clopper_pearson", "confidence": 0.95, "low": low, "high": high}


@pytest.fixture
def ready(tmp_path):
    config = make_config(tmp_path)
    run_collect(config, RetryAndDropClient(), max_batches=3)
    return config.artifact_path()


def test_report_figures_and_intervals_on_a_synthetic_collection(ready):
    report = build_report(ready, "col-1")
    assert report["collection_id"] == "col-1"
    manifest = json.loads((ready / "collections/col-1/manifest.json").read_text())
    assert report["collection_sha256"] == manifest["sha256"]
    assert report["status"] == "ready" and report["reasons"] == []
    figures = report["figures"]
    # Two batches of 30: 59 of 60 first attempts valid, the one failed slot recovered at
    # attempt 2, and the gate dropped one of 60 schema-valid items.
    assert figures["initial_schema_validity"] | {"interval": None} == {
        "numerator": 59,
        "denominator": 60,
        "rate": 59 / 60,
        "interval": None,
        "defined": True,
        "definition": figures["initial_schema_validity"]["definition"],
        "target": 0.95,
        "meets_target": True,
    }
    assert figures["initial_schema_validity"]["interval"] == interval(59, 60)
    retry = figures["retry_recovery"]
    assert (retry["numerator"], retry["denominator"], retry["rate"]) == (1, 1, 1.0)
    assert retry["interval"] == interval(1, 1)
    retention = figures["gate_retention"]
    assert (retention["numerator"], retention["denominator"]) == (59, 60)
    assert retention["interval"] == interval(59, 60)
    assert report["exhausted_slots"] == {"count": 0, "slot_ids": []}
    assert report["unknown_outcomes"] == {"count": 0, "attempt_ids": []}
    assert report["gate_drops_per_check"]["answer_length"] == 1
    assert sum(report["gate_drops_per_check"].values()) == 1
    assert report["cross_batch_drops"] == {
        "cross_batch_duplicate": 0,
        "cross_batch_near_duplicate": 0,
    }
    counts = {c: v["retained"] for c, v in report["per_category"].items()}
    assert set(counts) == set(CATEGORIES) and sum(counts.values()) == report["retained"] == 59
    assert sorted(counts.values()) == [11, 12, 12, 12, 12]
    for value in report["per_category"].values():
        assert value["share"] == value["retained"] / 59
    distribution = report["distribution"]
    assert distribution["min_per_category"] == 10 and distribution["passed"] is True
    assert distribution["deficits"] == {}
    # Batch 1 keeps 5 of 29 in one category (17%), under the gate's 18% minimum share.
    assert [b["distribution_passed"] for b in distribution["batches"]] == [False, True]
    # The gate-freeze files' hashes as the batches recorded them (here: the current code).
    current = generate.implementation_identity()["source_files"]
    assert report["frozen_files"] == {f: current[f] for f in FROZEN_FILES} | {
        "prompt": report["frozen_files"]["prompt"]
    }
    assert len(report["frozen_files"]["prompt"]) == 64
    # Never a failure rate: that needs blind labels and the judge.
    assert report["quality_status"] == "pending"
    assert "failure_rate" not in json.dumps(report).replace("failure_rate_status", "")


def test_report_is_written_once_and_reads_only(ready):
    before = tree(ready)
    path, report = write_report(ready, "col-1", "rep-1")
    assert path == ready / "reports/rep-1.json"
    assert json.loads(path.read_text()) == report
    assert report["report_id"] == "rep-1"
    after = tree(ready)
    assert {k: v for k, v in after.items() if not k.startswith("reports/")} == before
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_report(ready, "col-1", "rep-1")
    assert path.read_bytes() == original
    assert sorted(p.name for p in (ready / "reports").iterdir()) == ["rep-1.json"]


def test_default_report_id_and_bad_ids(ready):
    path, _ = write_report(ready, "col-1")
    assert path.name == "col-1-report.json"
    for bad in ("../escape", "", "a/b", "x" * 65):
        with pytest.raises(ValueError):
            write_report(ready, "col-1", bad)


def test_incomplete_collection_is_reported_honestly_with_undefined_rates(tmp_path):
    # One batch whose every attempt fails: nothing enters the gate.
    config = make_config(tmp_path)
    run_collect(config, UniqueClient(fail_first=90), max_batches=1)
    report = build_report(config.artifact_path(), "col-1")
    assert report["status"] == "incomplete"
    assert {"below_target", "category_deficits"} <= set(report["reasons"])
    figures = report["figures"]
    initial = figures["initial_schema_validity"]
    assert (initial["numerator"], initial["denominator"], initial["rate"]) == (0, 30, 0.0)
    assert initial["interval"] == interval(0, 30) and initial["meets_target"] is False
    retry = figures["retry_recovery"]
    assert (retry["numerator"], retry["denominator"], retry["rate"]) == (0, 30, 0.0)
    retention = figures["gate_retention"]
    assert retention == retention | {
        "numerator": 0,
        "denominator": 0,
        "rate": None,
        "interval": None,
        "defined": False,
    }
    assert report["exhausted_slots"]["count"] == 30
    assert len(report["exhausted_slots"]["slot_ids"]) == 30
    assert report["distribution"]["passed"] is False
    assert report["distribution"]["deficits"] == dict.fromkeys(CATEGORIES, 0)
    text = render_summary(report, Path("r.json"))
    assert "gate retention: undefined (0 of 0)" in text
    assert "0.0%" not in text.split("gate retention")[1].splitlines()[0]


def test_retry_recovery_is_undefined_when_every_first_attempt_is_valid(tmp_path):
    config = make_config(tmp_path)
    run_collect(config, UniqueClient(), max_batches=3)
    retry = build_report(config.artifact_path(), "col-1")["figures"]["retry_recovery"]
    assert (retry["numerator"], retry["denominator"]) == (0, 0)
    assert retry["rate"] is None and retry["interval"] is None and retry["defined"] is False


def test_unknown_outcomes_are_listed(tmp_path):
    config = make_config(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        run_collect(config, UniqueClient(interrupt_call=5), max_batches=3)
    run_collect(config, UniqueClient(), max_batches=3, resume=True)
    report = build_report(config.artifact_path(), "col-1")
    unknown = report["unknown_outcomes"]
    assert unknown["count"] == 1 and len(unknown["attempt_ids"]) == 1
    # The interrupted slot's first attempt has no outcome; its retry counts as recovery.
    figures = report["figures"]
    assert figures["initial_schema_validity"]["numerator"] == 59
    assert (figures["retry_recovery"]["numerator"], figures["retry_recovery"]["denominator"]) == (
        1,
        1,
    )


def test_frozen_cohort_is_verified_and_named(ready):
    assert build_report(ready, "col-1")["cohort"] is None
    frozen = cohort.freeze_cohort(ready, "col-1", "coh-1")
    report = build_report(ready, "col-1")
    assert report["cohort"] == {"cohort_id": "coh-1", "sha256": frozen["sha256"]}
    # A changed cohort file is evidence to inspect, not a report.
    path = ready / "cohorts/coh-1/cohort.json"
    data = json.loads(path.read_text())
    data["item_ids"] = data["item_ids"][1:]
    path.write_text(json.dumps(data))
    with pytest.raises(CollectionError, match="cohort"):
        build_report(ready, "col-1")


def test_locked_or_tampered_collection_is_refused(ready):
    lock = ready / "collections/col-1/.collection.lock"
    lock.write_text("synthetic leftover")
    with pytest.raises(CollectionError, match="lock"):
        write_report(ready, "col-1", "rep-1")
    lock.unlink()
    gate_report = ready / "col-1-b01/gate-report.json"
    data = json.loads(gate_report.read_text())
    data["drops_per_check"]["answer_length"] = 0
    gate_report.write_text(json.dumps(data))
    with pytest.raises(CollectionError, match="gate report"):
        write_report(ready, "col-1", "rep-1")
    assert not (ready / "reports").exists()


def invoke(capsys, argv):
    code = cli.main(argv)
    out, err = capsys.readouterr()
    assert "Traceback" not in err
    return code, out, err


def test_cli_collection_report(ready, capsys):
    root = str(ready)
    args = ["collection-report", "--collection-id", "col-1", "--artifact-root", root]
    code, out, err = invoke(capsys, [*args, "--report-id", "rep-1"])
    assert code == 0 and err == ""
    assert "collection col-1" in out and "status: ready" in out
    assert "initial-attempt schema validity: 59/60 = 98.3%" in out
    assert "retry recovery: 1/1 = 100.0%" in out
    assert "gate retention: 59/60 = 98.3%" in out
    assert "answer_length 1" in out
    assert str(ready / "reports/rep-1.json") in out
    low, high = clopper_pearson(59, 60)
    assert f"95% CI {low:.1%}-{high:.1%}" in out
    # The same report ID again is a usage error (2), never an overwrite.
    before = (ready / "reports/rep-1.json").read_bytes()
    code, out, err = invoke(capsys, [*args, "--report-id", "rep-1"])
    assert code == 2 and out == "" and "already exists" in err
    assert (ready / "reports/rep-1.json").read_bytes() == before
    # A missing collection is a check failure (1); a bad report ID a usage error (2).
    code, _, err = invoke(
        capsys, ["collection-report", "--collection-id", "nope", "--artifact-root", root]
    )
    assert code == 1 and err.startswith("error:")
    code, _, err = invoke(capsys, [*args, "--report-id", "../x"])
    assert code == 2 and err.startswith("error:")


def test_cli_report_of_an_incomplete_collection_exits_1(tmp_path, capsys):
    config = make_config(tmp_path)
    run_collect(config, UniqueClient(fail_first=90), max_batches=1)
    root = str(config.artifact_path())
    args = ["collection-report", "--collection-id", "col-1", "--artifact-root", root]
    code, out, _ = invoke(capsys, args)
    assert code == 1 and "status: incomplete" in out
    assert (config.artifact_path() / "reports/col-1-report.json").exists()


class OddCallsFailClient(UniqueClient):
    """Calls 1, 3 and 5 are broken JSON: three slots fail their first attempt and recover."""

    def generate(self, messages):
        if self.calls in (0, 2, 4):
            self.calls += 1
            return AttemptResult(None, "{synthetic-broken-json", "invalid JSON", "ValidationError")
        return super().generate(messages)


def test_structural_target_is_met_exactly_at_95_percent(tmp_path):
    # 57 of 60 is exactly 95%: met at the boundary, never missed by float rounding.
    config = make_config(tmp_path)
    run_collect(config, OddCallsFailClient(), max_batches=3)
    figures = build_report(config.artifact_path(), "col-1")["figures"]
    initial = figures["initial_schema_validity"]
    assert (initial["numerator"], initial["denominator"]) == (57, 60)
    assert initial["meets_target"] is True and initial["target"] == 0.95
    retry = figures["retry_recovery"]
    assert (retry["numerator"], retry["denominator"]) == (3, 3)
