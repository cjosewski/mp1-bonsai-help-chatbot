"""First-pass gate: per-item checks, duplicates, distribution and the one-time report."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from fakes import synthetic_item
from test_checks import GOOD_QUOTE, SECTION_IDS, fixture_section
from test_generation import FIXTURES, FakeClient, execute, offered_ids, run_dir

from bonsai_help import gate
from bonsai_help.checks import load_lexicons
from bonsai_help.config import RunConfig
from bonsai_help.doc_sources import CATEGORIES
from bonsai_help.gate import GateError, evaluate_gate, gate_run
from bonsai_help.model_client import AttemptResult, EmbeddingError
from bonsai_help.sampler import FixtureError
from bonsai_help.schemas import CitedSection, GeneratedItem, GenerationOutput

ROOT = Path(__file__).resolve().parents[1]
LEX = load_lexicons(ROOT / "reference")
EMBED_MODEL = "synthetic-embedding"
EMBED_URL = "http://127.0.0.1:8081/v1"
DIMENSIONS = {"D1", "D2", "D3", "D4", "D5", "D6"}


def section(n: int) -> CitedSection:
    """Real fixture-slice sections, so the quote check reads their offered text."""
    return fixture_section(SECTION_IDS[n - 1])


def good_item(index: int) -> dict:
    item = synthetic_item()
    item["question"] = f"How do I add wall number {index} to a new Bonsai project?"
    item["answer"] = " ".join(["Open the project and add the wall using the type library."] * 7)
    item["equipment_problem"] = f"Project {index} has no walls yet."
    item["safety_info"] = (
        "Save a copy of the project before editing so that an edit you cannot undo "
        "does not destroy the only version of the file."
    )
    item["tips"] = ["Name the wall type clearly so it is easy to find in the library later."]
    return item


def record(index: int, category: str | None = None, quotes=None, **changes) -> GeneratedItem:
    item = good_item(index)
    item.update(changes)
    if quotes is None:
        quotes = [{"section_id": SECTION_IDS[0], "text": GOOD_QUOTE}]
    return GeneratedItem(
        run_id="r",
        trace_id=f"t{index}",
        item_id=f"r-{index:03d}",
        attempt_id=f"a{index}",
        slot_id=f"{index:03d}",
        category=category or CATEGORIES[index % 5],
        setup_id="SP-1",
        version_line="VL-current",
        prompt_variant="baseline",
        prompt_hash="h",
        model="m",
        sampler_seed=1,
        generated_at="2026-11-24T00:00:00+00:00",
        offered_sections=[section(1), section(2)],
        cited_sections=[section(1)],
        quotes=quotes,
        item=item,
    )


class FakeEmbedder:
    """Distinct one-hot vectors, except texts mapped to the same group share a vector."""

    def __init__(self, groups=None, fail=False):
        self.groups = groups or {}
        self.fail = fail
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise EmbeddingError("synthetic embedding failure")
        vectors = []
        for index, text in enumerate(texts):
            slot = next((g for key, g in self.groups.items() if key in text), index)
            vector = [0.0] * (len(texts) + 8)
            vector[slot] = 1.0
            vectors.append(vector)
        return vectors


def evaluate(records, embedder=None, **kwargs):
    return evaluate_gate(
        records,
        lexicons=LEX,
        fixtures_dir=FIXTURES,
        embedder=embedder or FakeEmbedder(),
        embedding_model=EMBED_MODEL,
        embedding_base_url=EMBED_URL,
        **kwargs,
    )


def test_clean_balanced_batch_is_retained_and_recorded():
    records = [record(i) for i in range(10)]
    report = evaluate(records)
    assert report["retained_ids"] == sorted(r.item_id for r in records)
    assert report["gate_pass_rate"] == 1.0
    assert report["embedding_model"] == EMBED_MODEL
    assert report["embedding_base_url"] == EMBED_URL
    assert report["threshold"] == 0.92
    assert report["distribution"]["passed"] is True
    assert {c["retained"] for c in report["per_category"].values()} == {2}
    assert report["quality_status"] == "pending"
    assert all(v["retained"] and v["dropped_by"] == [] for v in report["per_item"].values())


def test_every_dimension_has_a_precheck():
    report = evaluate([record(0)])
    names = {c["dimension"] for c in report["per_item"]["r-000"]["checks"]}
    assert names == DIMENSIONS


def test_drops_counted_per_check():
    records = [
        record(0, safety_info="Be careful and stay safe and use caution."),
        record(1, tips=["Short tip."]),
        record(2, tips=["Tiny."]),
        record(3),
    ]
    report = evaluate(records)
    assert report["drops_per_check"]["safety_length"] == 1
    assert report["drops_per_check"]["tip_length"] == 2
    assert report["drops_per_check"]["exact_duplicate"] == 0
    assert report["retained_ids"] == ["r-003"]
    assert report["per_item"]["r-001"]["retained"] is False
    assert "D6:tip_length" in report["per_item"]["r-001"]["dropped_by"]
    assert report["gate_pass_rate"] == 0.25


def test_dropped_items_are_not_embedded():
    embedder = FakeEmbedder()
    evaluate([record(0), record(1, tips=["Short."]), record(2)], embedder)
    assert len(embedder.calls) == 1 and len(embedder.calls[0]) == 2


def test_exact_duplicate_dropped_and_counted():
    first = record(0)
    again = record(1, question="  HOW do I add wall number 0 to a NEW Bonsai project?!! ")
    report = evaluate([again, first, record(2)])
    assert report["exact_duplicates"] == [{"kept": "r-000", "dropped": "r-001"}]
    assert report["per_item"]["r-001"]["dropped_by"] == ["exact_duplicate"]
    assert report["drops_per_check"]["exact_duplicate"] == 1
    assert report["retained_ids"] == ["r-000", "r-002"]


def test_near_duplicate_dropped_with_fake_embedder():
    records = [record(0), record(1), record(2)]
    embedder = FakeEmbedder(groups={"number 0 ": 0, "number 2 ": 0})
    report = evaluate(records, embedder)
    assert [(p["kept"], p["dropped"]) for p in report["near_duplicates"]] == [("r-000", "r-002")]
    assert report["near_duplicates"][0]["score"] == pytest.approx(1.0)
    assert report["per_item"]["r-002"]["dropped_by"] == ["near_duplicate"]
    assert report["drops_per_check"]["near_duplicate"] == 1
    assert report["retained_ids"] == ["r-000", "r-001"]


def test_embedding_text_is_question_then_answer():
    embedder = FakeEmbedder()
    records = [record(0)]
    evaluate(records, embedder)
    item = records[0].item
    assert embedder.calls == [[item.question + "\n" + item.answer]]


def test_threshold_is_configurable():
    class Close(FakeEmbedder):
        def embed(self, texts):
            return [[1.0, 0.1 * i] for i in range(len(texts))]

    records = [record(0), record(1)]
    assert len(evaluate(records, Close(), threshold=0.999)["retained_ids"]) == 2
    assert len(evaluate(records, Close(), threshold=0.9)["retained_ids"]) == 1


def test_distribution_fails_under_18_percent():
    records = [record(i, category=CATEGORIES[0]) for i in range(9)] + [
        record(9, category=CATEGORIES[1])
    ]
    report = evaluate(records)
    assert report["distribution"]["min_share"] == 0.18
    assert report["distribution"]["passed"] is False
    assert report["per_category"][CATEGORIES[1]]["share"] == pytest.approx(0.1)


def test_distribution_fails_when_a_category_has_no_retained_items():
    records = [record(i, category=CATEGORIES[i % 4]) for i in range(8)]
    report = evaluate(records)
    assert report["per_category"][CATEGORIES[4]]["retained"] == 0
    assert report["distribution"]["passed"] is False


def test_distribution_is_over_the_final_retained_set():
    records = [record(i) for i in range(10)]
    dup = record(10, category=CATEGORIES[0], question=records[1].item.question)
    # Categories of records 0..9 are two each; dropping the duplicate must not matter.
    report = evaluate([*records, dup])
    assert report["distribution"]["passed"] is True
    assert report["per_category"][CATEGORIES[0]]["retained"] == 2
    assert report["per_category"][CATEGORIES[0]]["input"] == 3


def test_empty_batch_fails_distribution_without_dividing_by_zero():
    report = evaluate([])
    assert report["gate_pass_rate"] is None
    assert report["retained_ids"] == []
    assert report["distribution"]["passed"] is False


def test_unoffered_citation_drops_the_item():
    records = [record(0), record(1)]
    report = evaluate(records, unoffered_citations={"r-000": ["bonsai-docs:nowhere#L1-L2"]})
    assert "D3:cited_sections_offered" in report["per_item"]["r-000"]["dropped_by"]
    assert report["retained_ids"] == ["r-001"]


def test_embedding_failure_is_controlled():
    with pytest.raises(GateError, match="synthetic embedding failure"):
        evaluate([record(0)], FakeEmbedder(fail=True))


def test_wrong_number_of_vectors_is_controlled():
    class Short(FakeEmbedder):
        def embed(self, texts):
            return [[1.0]]

    with pytest.raises(GateError, match="vectors"):
        evaluate([record(0), record(1)], Short())


# --- gate_run on a real (synthetic) run directory -------------------------------------


class GoodClient(FakeClient):
    """Synthetic model returning a distinct, check-passing item per slot."""

    def generate(self, messages):
        self.calls += 1
        match = re.search(r"slot (?P<slot>\S+), attempt", messages[-1]["content"])
        body = {
            "item": good_item(self.calls)
            | {"question": f"How do I add the wall for slot {match['slot']} to a new project?"},
            "cited_section_ids": self.cite(offered_ids(messages)),
            "quotes": self.quote(offered_ids(messages)),
        }
        output = GenerationOutput.model_validate(body)
        return AttemptResult(output, {"synthetic": True}, None, None, self.model)


@pytest.fixture
def config(tmp_path):
    from fakes import FAKE_BASE_URL, FAKE_MODEL

    return RunConfig.model_validate(
        {
            "base_url": FAKE_BASE_URL,
            "model": FAKE_MODEL,
            "embedding_model": EMBED_MODEL,
            "seed": 7,
            "artifact_root": str(tmp_path / "runs"),
        }
    )


def run_gate(config, embedder=None, run_id="test-run"):
    return gate_run(
        config.artifact_path(),
        run_id,
        lexicons=LEX,
        embedder=embedder or FakeEmbedder(),
        embedding_model=EMBED_MODEL,
        embedding_base_url=EMBED_URL,
        fixtures_dir=FIXTURES,
    )


def test_gate_run_writes_the_report_once(config):
    execute(config, GoodClient())
    report = run_gate(config)
    path = run_dir(config) / "gate-report.json"
    written = json.loads(path.read_text())
    assert written == report
    assert written["run_id"] == "test-run"
    assert len(written["retained_ids"]) == 5
    assert written["distribution"]["passed"] is True
    before = path.read_bytes()
    with pytest.raises(GateError, match="already"):
        run_gate(config)
    assert path.read_bytes() == before
    assert not (run_dir(config) / ".gate.lock").exists()


def test_gate_run_reads_unoffered_citations_from_the_attempt(config):
    execute(config, GoodClient(cite=lambda ids: ["bonsai-docs:nowhere#L1-L2"]))
    report = run_gate(config)
    assert report["retained_ids"] == []
    assert report["drops_per_check"]["cited_sections_offered"] == 5


def test_bracketed_citation_of_an_offered_id_passes_the_gate(config):
    # The prompt shows each section as `[id]`; a model that copies the brackets still
    # cites that offered section, in generation and again when the gate recomputes it.
    execute(config, GoodClient(cite=lambda ids: [f"[{ids[0]}]"]))
    report = run_gate(config)
    assert len(report["retained_ids"]) == 5
    assert report["drops_per_check"]["cited_sections_offered"] == 0
    for entry in report["per_item"].values():
        assert "D3:cited_sections_offered" not in entry["dropped_by"]


def test_embedding_failure_writes_no_report(config):
    execute(config, GoodClient())
    with pytest.raises(GateError):
        run_gate(config, FakeEmbedder(fail=True))
    assert not (run_dir(config) / "gate-report.json").exists()
    assert not (run_dir(config) / ".gate.lock").exists()
    assert run_gate(config)["retained_ids"]  # a failed gate leaves the run gate-able


@pytest.mark.parametrize("change", ["delete", "alter"])
def test_tampered_run_is_refused(config, change):
    execute(config, GoodClient())
    target = run_dir(config) / "items.jsonl"
    if change == "delete":
        target.unlink()
    else:
        target.write_text(target.read_text().replace('"run_id"', '"x": 1, "run_id"', 1))
    with pytest.raises(ValueError, match="changed or missing"):
        run_gate(config)
    assert not (run_dir(config) / "gate-report.json").exists()


def test_item_not_backed_by_a_successful_attempt_is_refused(config):
    execute(config, GoodClient())
    directory = run_dir(config)
    lines = (directory / "items.jsonl").read_text().splitlines()
    forged = json.loads(lines[0])
    forged["item"]["answer"] = "forged " * 70
    lines[0] = json.dumps(forged)
    (directory / "items.jsonl").write_text("\n".join(lines) + "\n")
    manifest = json.loads((directory / "manifest.json").read_text())
    from bonsai_help.tracing import artifact_hashes

    manifest["artifacts_sha256"] = artifact_hashes(directory)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="successful attempt"):
        run_gate(config)


def test_missing_run_and_locked_run_are_refused(config):
    with pytest.raises(GateError, match="no run"):
        run_gate(config)
    execute(config, GoodClient())
    (run_dir(config) / ".generation.lock").write_text("x")
    with pytest.raises(GateError, match="lock"):
        run_gate(config)


def test_gate_module_has_no_domain_leftovers():
    source = Path(gate.__file__).read_text()
    for word in ("benchmark", "_repair_checks", "_HAZARD", "home-diy"):
        assert word not in source


def rehash(directory):
    from bonsai_help.tracing import artifact_hashes

    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["artifacts_sha256"] = artifact_hashes(directory)
    (directory / "manifest.json").write_text(json.dumps(manifest))


def test_interrupted_run_is_refused(config):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=3))
    with pytest.raises(GateError, match="interrupted"):
        run_gate(config)
    assert not (run_dir(config) / "gate-report.json").exists()


def test_deleted_item_row_is_refused_even_when_rehashed(config):
    execute(config, GoodClient())
    directory = run_dir(config)
    lines = (directory / "items.jsonl").read_text().splitlines()
    (directory / "items.jsonl").write_text("\n".join(lines[1:]) + "\n")
    rehash(directory)
    with pytest.raises(ValueError, match="disagree"):
        run_gate(config)


def test_retried_slot_is_gated_with_no_exhausted_slots(config):
    # The first attempt fails and its retry succeeds, so the run is complete.
    client = GoodClient()
    inner = client.generate

    def flaky(messages):
        if re.search(r"slot \S+, attempt", messages[-1]["content"]) and client.calls == 0:
            client.calls += 1
            return AttemptResult(None, "{broken", "invalid JSON", "ValidationError")
        return inner(messages)

    client.generate = flaky
    manifest = execute(config, client)
    report = run_gate(config)
    assert manifest["status"] == report["run_status"] == "complete"
    assert (report["slot_count"], report["input_count"], report["exhausted_slots"]) == (5, 5, [])
    assert report["gate_pass_rate_denominator"] == "schema-valid items entering the gate"
    assert len(report["retained_ids"]) == 5


def test_incomplete_run_is_gated_and_discloses_its_exhausted_slot(config):
    client = GoodClient()
    inner = client.generate
    failing = {}

    def one_slot_fails(messages):
        slot = re.search(r"slot (?P<slot>\S+), attempt", messages[-1]["content"])["slot"]
        failing.setdefault("slot", slot)
        if slot == failing["slot"]:
            return AttemptResult(None, "{broken", "invalid JSON", "ValidationError")
        return inner(messages)

    client.generate = one_slot_fails
    manifest = execute(config, client)
    report = run_gate(config)
    assert manifest["status"] == report["run_status"] == "incomplete"
    assert report["exhausted_slots"] == [failing["slot"]]
    assert (report["slot_count"], report["input_count"]) == (5, 4)
    assert len(report["retained_ids"]) == 4


def test_exhausted_slots_are_recorded(config):
    execute(config, FakeClient(fail=lambda slot, attempt: True))
    report = run_gate(config)
    assert report["run_status"] == "incomplete"
    assert len(report["exhausted_slots"]) == 5
    assert report["input_count"] == 0 and report["gate_pass_rate"] is None


def test_edited_unoffered_citations_are_refused(config):
    execute(config, GoodClient(cite=lambda ids: ["bonsai-docs:nowhere#L1-L2"]))
    directory = run_dir(config)
    lines = (directory / "attempts.jsonl").read_text().splitlines()
    edited = []
    for line in lines:
        row = json.loads(line)
        row["unoffered_citations"] = []
        edited.append(json.dumps(row))
    (directory / "attempts.jsonl").write_text("\n".join(edited) + "\n")
    rehash(directory)
    with pytest.raises(ValueError, match="unoffered_citations"):
        run_gate(config)


def test_mismatched_embedding_dimensions_are_controlled():
    class Ragged(FakeEmbedder):
        def embed(self, texts):
            return [[1.0] * (i + 1) for i in range(len(texts))]

    with pytest.raises(GateError, match="dimensions"):
        evaluate([record(0), record(1)], Ragged())


def test_per_check_failures_and_pass_rates_include_evidence_only_checks():
    invented = ["Run mesh.fake_operator_xyz.", "Open Zorbo Wizard > Bogus Exporter.", "Three."]
    records = [record(i, steps=invented) for i in range(3)]
    records += [record(3, tips=["Short tip."]), record(4)]
    report = evaluate(records)
    rates = report["pass_rates_per_check"]
    assert set(rates) == {c["name"] for c in report["per_item"]["r-000"]["checks"]}
    for name in ("blender_operators_known", "menu_paths_known"):
        assert rates[name] == {
            "dimension": "D3",
            "evidence_only": True,
            "evaluated": 5,
            "passed": 2,
            "failed": 3,
            "dropped": 0,
            "pass_rate": 0.4,
        }
        assert report["drops_per_check"][name] == 0
    assert rates["tip_length"] == {
        "dimension": "D6",
        "evidence_only": False,
        "evaluated": 5,
        "passed": 4,
        "failed": 1,
        "dropped": 1,
        "pass_rate": 0.8,
    }
    assert report["pass_rates_denominator"] == gate.DENOMINATOR
    # The three evidence-only failures stay retained; only the short tip is dropped.
    assert report["retained_ids"] == ["r-000", "r-001", "r-002", "r-004"]


def test_pass_rates_are_empty_for_an_empty_gate_input():
    report = evaluate([])
    assert report["pass_rates_per_check"] == {}
    assert report["gate_pass_rate"] is None


def test_two_successful_attempts_for_one_slot_are_refused(config):
    execute(config, GoodClient())
    directory = run_dir(config)
    path = directory / "attempts.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    copy = dict(next(r for r in rows if r["schema_valid"]), attempt_id="synthetic-copy")
    path.write_text("\n".join(json.dumps(r) for r in [*rows, copy]) + "\n")
    rehash(directory)
    with pytest.raises(ValueError, match="more than one successful attempt"):
        run_gate(config)
    assert not (directory / "gate-report.json").exists()


@pytest.mark.parametrize("bad", [[0.0, 0.0], [float("nan"), 1.0], [float("inf"), 1.0]])
@pytest.mark.parametrize("count", [1, 2])
def test_zero_or_non_finite_embedding_vector_is_controlled(bad, count):
    class Broken(FakeEmbedder):
        def embed(self, texts):
            return [[1.0, 0.0]] * (len(texts) - 1) + [bad]

    with pytest.raises(GateError, match="zero or non-finite"):
        evaluate([record(i) for i in range(count)], Broken())


# --- quotes_verbatim in the gate --------------------------------------------------------


def test_gate_drops_a_fabricated_quote_and_reports_the_check_rate():
    fabricated = [{"section_id": SECTION_IDS[0], "text": "a synthetic passage the docs never say"}]
    records = [record(0, quotes=fabricated), *(record(i) for i in range(1, 5))]
    report = evaluate(records)
    assert report["per_item"]["r-000"]["dropped_by"] == ["D3:quotes_verbatim"]
    assert report["retained_ids"] == ["r-001", "r-002", "r-003", "r-004"]
    assert report["drops_per_check"]["quotes_verbatim"] == 1
    rate = report["pass_rates_per_check"]["quotes_verbatim"]
    assert rate == {
        "dimension": "D3",
        "evidence_only": False,
        "evaluated": 5,
        "passed": 4,
        "failed": 1,
        "dropped": 1,
        "pass_rate": 0.8,
    }


def test_gate_run_drops_items_whose_quotes_are_not_in_their_cited_section(config):
    def invented(ids):
        return [{"section_id": ids[0], "text": "a synthetic passage the docs never say"}]

    execute(config, GoodClient(quote=invented))
    report = run_gate(config)
    assert report["retained_ids"] == []
    assert report["drops_per_check"]["quotes_verbatim"] == 5
    for entry in report["per_item"].values():
        assert entry["dropped_by"] == ["D3:quotes_verbatim"]
        (check,) = [c for c in entry["checks"] if c["name"] == "quotes_verbatim"]
        assert check["detail"] == "quote 0: not verbatim in its section"


def test_gate_run_reads_section_text_from_the_verified_fixture_slice(config, tmp_path):
    execute(config, GoodClient())
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    offered = json.loads((run_dir(config) / "items.jsonl").read_text().splitlines()[0])
    first = offered["offered_sections"][0]
    page = copy / first["source"] / first["id"].split(":", 1)[1].split("#")[0]
    page.write_bytes(page.read_bytes() + b"\nsynthetic tampering\n")
    with pytest.raises(FixtureError, match="differs from the offered page hash"):
        gate_run(
            config.artifact_path(),
            "test-run",
            lexicons=LEX,
            embedder=FakeEmbedder(),
            embedding_model=EMBED_MODEL,
            embedding_base_url=EMBED_URL,
            fixtures_dir=copy,
        )
    assert not (run_dir(config) / "gate-report.json").exists()
    assert run_gate(config)["retained_ids"]


def test_gate_refuses_an_item_whose_quotes_differ_from_its_attempt(config):
    execute(config, GoodClient())
    directory = run_dir(config)
    for name in ("items.jsonl", "attempts.jsonl"):
        path = directory / name
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for r in records:
            target = r if name == "items.jsonl" else r["record"]
            if target is not None:
                target["quotes"][0]["text"] = "an edited synthetic quote text"
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["artifacts_sha256"] = gate.artifact_hashes(directory)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="quotes that differ from its attempt"):
        run_gate(config)
    assert not (directory / "gate-report.json").exists()
