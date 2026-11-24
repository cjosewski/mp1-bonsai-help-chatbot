"""Generation run: initial-attempt denominators, bounded retries, resume and the envelope.

Model output here is synthetic (tests/fakes.py); documentation text comes only from the
committed fixture slice.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import httpx
import pytest
from fakes import (
    FAKE_BASE_URL,
    FAKE_KEY,
    FAKE_MODEL,
    FakeTransport,
    completion,
    synthetic_generation,
)

from bonsai_help import generate, sampler
from bonsai_help.config import RunConfig, load_prompt
from bonsai_help.doc_sources import CATEGORIES, load_config
from bonsai_help.model_client import AttemptResult, InstructorClient
from bonsai_help.schemas import CitedSection, GeneratedItem, GenerationOutput
from bonsai_help.setup import SetupProfiles
from bonsai_help.tracing import artifact_hashes, read_records

ROOT = Path(__file__).resolve().parents[1]
DOC_CONFIG = load_config(ROOT / "config/doc-sources.json")
PROFILES = SetupProfiles.model_validate(
    json.loads((ROOT / "reference/setup-profiles.json").read_bytes())
)
FIXTURES = ROOT / "tests/fixtures/docs"
SECTION_ID = re.compile(r"^\[([a-z0-9-]+:[^\]\s]+#L\d+-L\d+)\]$", re.MULTILINE)
REQUEST = re.compile(r"slot (?P<slot>\S+), attempt (?P<attempt>\d+)")


def offered_ids(messages) -> list[str]:
    return SECTION_ID.findall("\n".join(m["content"] for m in messages))


class FakeClient:
    """Synthetic model: valid output citing the first offered section, unless told to fail."""

    def __init__(self, *, fail=None, interrupt_call=None, cite=None, model=None, raw=None):
        self.calls = 0
        self.messages = []
        self.fail = fail or (lambda slot_id, attempt: False)
        self.interrupt_call = interrupt_call
        self.cite = cite or (lambda ids: ids[:1])
        self.model = "synthetic-model-revision" if model is None else model
        self.raw = raw or (lambda envelope: envelope)

    def generate(self, messages):
        self.calls += 1
        self.messages.append(messages)
        if self.calls == self.interrupt_call:
            raise KeyboardInterrupt
        match = REQUEST.search(messages[-1]["content"])
        if self.fail(match["slot"], int(match["attempt"])):
            return AttemptResult(None, "{synthetic-broken-json", "invalid JSON", "ValidationError")
        body = synthetic_generation(cited=self.cite(offered_ids(messages)))
        output = GenerationOutput.model_validate(body)
        raw = self.raw(completion(json.dumps(body)))
        return AttemptResult(output, raw, None, None, self.model)


@pytest.fixture
def config(tmp_path):
    return RunConfig.model_validate(
        {
            "base_url": FAKE_BASE_URL,
            "model": FAKE_MODEL,
            "embedding_model": "synthetic-embedding",
            "seed": 7,
            "artifact_root": str(tmp_path / "runs"),
        }
    )


def execute(config, client=None, *, resume=False, count=5, run_id="test-run", fixtures=FIXTURES):
    prompt, prompt_sha256 = load_prompt(config)
    return generate.generate_run(
        config,
        prompt,
        prompt_sha256,
        count=count,
        run_id=run_id,
        client=client or FakeClient(),
        profiles=PROFILES,
        doc_config=DOC_CONFIG,
        fixtures_dir=fixtures,
        resume=resume,
    )


def run_dir(config, run_id="test-run") -> Path:
    return config.artifact_path() / run_id


def ledger(config, name):
    return read_records(run_dir(config) / name)


def first_slots(n):
    """The ids of the first n planned development slots (plan order)."""
    return {s.slot_id for s in sampler.plan_slots(PROFILES, "development", 5)[:n]}


def test_initial_attempt_denominator(config):
    failing = first_slots(2)
    manifest = execute(config, FakeClient(fail=lambda s, a: s in failing and a == 1))
    metrics = manifest["metrics"]
    assert metrics["initial_slots"] == 5
    assert metrics["initial_valid"] == 3
    assert metrics["initial_validity"] == pytest.approx(0.6)
    assert metrics["retry_recovered"] == 2
    assert metrics["exhausted"] == 0
    assert manifest["status"] == "complete"


def test_retry_recovery_counted_separately(config):
    client = FakeClient(fail=lambda s, a: a == 1)
    manifest = execute(config, client)
    assert client.calls == 10
    assert manifest["status"] == "complete"
    metrics = manifest["metrics"]
    assert (metrics["initial_valid"], metrics["initial_validity"]) == (0, 0)
    assert metrics["retry_recovered"] == 5
    attempts = ledger(config, "attempts.jsonl")
    assert attempts[0]["raw_response"] == "{synthetic-broken-json"
    assert attempts[0]["schema_valid"] is False and attempts[0]["record"] is None
    assert attempts[1]["parent_attempt_id"] == attempts[0]["attempt_id"]
    assert attempts[1]["trace_id"] == attempts[0]["trace_id"]
    items = ledger(config, "items.jsonl")
    assert len(items) == 5
    assert all(GeneratedItem.model_validate(record) for record in items)
    assert {r["attempt_id"] for r in items} == {
        a["attempt_id"] for a in attempts if a["attempt_number"] == 2
    }


def test_exhaustion_is_controlled(config):
    client = FakeClient(fail=lambda s, a: True)
    manifest = execute(config, client)
    assert client.calls == 5 * config.max_attempts
    assert manifest["status"] == "incomplete"
    assert manifest["metrics"]["exhausted"] == 5
    assert manifest["metrics"]["initial_validity"] == 0
    assert ledger(config, "items.jsonl") == []
    assert len(ledger(config, "attempts.jsonl")) == 15
    # Exhausted slots get no extra attempts on resume.
    again = FakeClient()
    assert execute(config, again, resume=True)["status"] == "incomplete"
    assert again.calls == 0


def test_unknown_outcome_consumes_attempt(config):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=2))
    directory = run_dir(config)
    assert not (directory / ".generation.lock").exists()
    assert json.loads((directory / "manifest.json").read_text())["status"] == "interrupted"
    starts, attempts = ledger(config, "starts.jsonl"), ledger(config, "attempts.jsonl")
    assert (len(starts), len(attempts)) == (2, 1)
    first_items = (directory / "items.jsonl").read_bytes()

    client = FakeClient()
    manifest = execute(config, client, resume=True)
    assert client.calls == 4
    assert (directory / "items.jsonl").read_bytes().startswith(first_items)
    metrics = manifest["metrics"]
    assert metrics["unknown_outcomes"] == 1
    assert metrics["unknown_attempt_ids"] == [starts[1]["attempt_id"]]
    assert metrics["initial_valid"] == 4 and metrics["initial_slots"] == 5
    slot_two = [s for s in ledger(config, "starts.jsonl") if s["slot_id"] == starts[1]["slot_id"]]
    assert [s["attempt_number"] for s in slot_two] == [1, 2]
    assert slot_two[1]["parent_attempt_id"] == slot_two[0]["attempt_id"]
    assert slot_two[1]["trace_id"] == slot_two[0]["trace_id"]


def test_unknown_outcome_can_exhaust_a_slot(config):
    config = config.model_copy(update={"max_attempts": 1})
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=2))
    client = FakeClient()
    manifest = execute(config, client, resume=True)
    assert client.calls == 3
    assert manifest["status"] == "incomplete"
    assert manifest["metrics"]["exhausted"] == 1
    assert manifest["metrics"]["unknown_outcomes"] == 1


@pytest.mark.parametrize("change", ["settings", "prompt", "code", "count"])
def test_resume_refuses_changed_settings_prompt_or_code(config, tmp_path, monkeypatch, change):
    prompt_file = tmp_path / "prompt.md"
    shutil.copyfile(config.prompt_file(), prompt_file)
    config = config.model_copy(update={"prompt_path": str(prompt_file)})
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=2))
    manifest_bytes = (run_dir(config) / "manifest.json").read_bytes()
    count = 5
    if change == "settings":
        config = config.model_copy(update={"temperature": 0.2})
    elif change == "prompt":
        prompt_file.write_text(prompt_file.read_text() + "\nBe brief.\n")
    elif change == "code":
        monkeypatch.setattr(
            generate,
            "implementation_identity",
            lambda *args, **kwargs: {"source_files": {}, "source_tree_sha256": "0" * 64},
        )
    else:
        count = 10
    client = FakeClient()
    with pytest.raises(ValueError, match="original"):
        execute(config, client, resume=True, count=count)
    assert client.calls == 0
    assert (run_dir(config) / "manifest.json").read_bytes() == manifest_bytes


def test_no_overwrite_of_existing_run(config):
    execute(config)
    path = run_dir(config) / "items.jsonl"
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        execute(config)
    with pytest.raises(ValueError, match="complete"):
        execute(config, resume=True)
    assert path.read_bytes() == original


def test_messages_carry_category_setup_and_sections(config):
    def handler(request: httpx.Request) -> httpx.Response:
        messages = json.loads(request.content)["messages"]
        body = synthetic_generation(cited=offered_ids(messages)[:1])
        return httpx.Response(200, json=completion(json.dumps(body)))

    transport = FakeTransport(handler)
    with InstructorClient(
        base_url=FAKE_BASE_URL,
        model=FAKE_MODEL,
        api_key=FAKE_KEY,
        response_model=GenerationOutput,
        _transport=transport.transport,
    ) as client:
        manifest = execute(config, client)
    assert manifest["status"] == "complete"
    starts = ledger(config, "starts.jsonl")
    bodies = transport.bodies()
    assert len(bodies) == len(starts) == 5
    assert {s["category"] for s in starts} == set(CATEGORIES)
    profiles = {p.id: p for p in PROFILES.profiles}
    lines = {v.id: v for v in PROFILES.version_lines}
    for start, body in zip(starts, bodies):
        text = "\n".join(m["content"] for m in body["messages"])
        profile = profiles[start["setup_id"]]
        line = lines[profile.version_line]
        assert profile.split == "development"
        assert f"Category: {start['category']}" in text
        for expected in (
            f"id: {profile.id}",
            f"version_line: {line.id}",
            f"blender: {line.blender}",
            f"bonsai: {line.bonsai}",
            f"ifc_schema: {profile.ifc_schema}",
            f"discipline: {profile.discipline}",
            f"model_state: {profile.model_state}",
        ):
            assert expected in text
        offered = [CitedSection.model_validate(s) for s in start["offered_sections"]]
        assert offered
        assert sampler.render_sections(offered, FIXTURES) in text
        assert offered_ids(body["messages"]) == [s.id for s in offered]
        assert "{sections}" not in text and "{setup}" not in text
        assert FAKE_KEY not in json.dumps(start)


def test_cited_sections_recorded_in_envelope(config):
    def cite(ids):
        # Listed out of order, with one id that was never offered.
        return [ids[-1], "bonsai-docs:invented/page.rst#L1-L2", ids[0]]

    execute(config, FakeClient(cite=cite))
    attempts = ledger(config, "attempts.jsonl")
    items = ledger(config, "items.jsonl")
    assert len(items) == 5
    for record, attempt in zip(items, attempts):
        offered = record["offered_sections"]
        assert record["cited_sections"] == [
            s for s in offered if s["id"] in {offered[0]["id"], offered[-1]["id"]}
        ]
        assert attempt["unoffered_citations"] == ["bonsai-docs:invented/page.rst#L1-L2"]
        assert attempt["schema_valid"] is True
        assert record["sampler_seed"] == config.seed
        assert set(record["item"]) == {
            "question",
            "answer",
            "equipment_problem",
            "tools_required",
            "steps",
            "safety_info",
            "tips",
        }


def test_only_unoffered_citations_leave_cited_sections_empty(config):
    execute(config, FakeClient(cite=lambda ids: ["blender-manual:nowhere.rst#L1-L1"]))
    items = ledger(config, "items.jsonl")
    assert len(items) == 5
    assert all(record["cited_sections"] == [] for record in items)
    assert all(
        a["unoffered_citations"] == ["blender-manual:nowhere.rst#L1-L1"]
        for a in ledger(config, "attempts.jsonl")
    )


@pytest.mark.parametrize("count", [0, 4, 6, 505, 510, True, 5.0])
def test_invalid_count_makes_no_requests(config, count):
    client = FakeClient()
    with pytest.raises(ValueError, match="multiple of 5"):
        execute(config, client, count=count)
    assert client.calls == 0
    assert not run_dir(config).exists()


def test_fixture_mismatch_refuses_before_any_start(config, tmp_path):
    fixtures = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, fixtures)
    page = DOC_CONFIG.sources[0].fixture_pages[0].path
    target = fixtures / DOC_CONFIG.sources[0].id / page
    target.write_bytes(target.read_bytes() + b"\nInjected synthetic line.\n")
    client = FakeClient()
    with pytest.raises(sampler.FixtureError):
        execute(config, client, fixtures=fixtures)
    assert client.calls == 0
    assert not run_dir(config).exists()


def test_fixture_mismatch_refuses_resume_before_any_start(config, tmp_path):
    fixtures = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, fixtures)
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=2), fixtures=fixtures)
    starts = (run_dir(config) / "starts.jsonl").read_bytes()
    page = DOC_CONFIG.sources[0].fixture_pages[0].path
    target = fixtures / DOC_CONFIG.sources[0].id / page
    target.write_bytes(target.read_bytes() + b"\nInjected synthetic line.\n")
    client = FakeClient()
    with pytest.raises(sampler.FixtureError):
        execute(config, client, resume=True, fixtures=fixtures)
    assert client.calls == 0
    assert (run_dir(config) / "starts.jsonl").read_bytes() == starts


def test_assessed_purpose_requires_model_identity(config):
    client = FakeClient()
    assessed = config.model_copy(update={"purpose": "baseline", "split": "assessed"})
    with pytest.raises(ValueError, match="model_identity"):
        execute(assessed, client)
    assert client.calls == 0
    assert not run_dir(config).exists()


def test_assessed_run_refuses_a_different_reported_model(config):
    assessed = config.model_copy(
        update={
            "purpose": "baseline",
            "split": "assessed",
            "model_identity": "synthetic-weights-v1",
            "model_sha256": "a" * 64,
        }
    )
    manifest = execute(assessed, FakeClient(model="some-other-model"))
    assert manifest["status"] == "incomplete"
    attempts = ledger(config, "attempts.jsonl")
    assert {a["error_type"] for a in attempts} == {"ModelIdentityMismatch"}
    assert all(a["raw_response"] is not None for a in attempts)
    starts = ledger(config, "starts.jsonl")
    assessed_ids = {p.id for p in PROFILES.profiles if p.split == "assessed"}
    assert {s["setup_id"] for s in starts} <= assessed_ids


def test_prompt_hash_must_match_prompt_text(config):
    prompt, _ = load_prompt(config)
    client = FakeClient()
    with pytest.raises(ValueError, match="prompt_sha256"):
        generate.generate_run(
            config,
            prompt,
            "0" * 64,
            count=5,
            run_id="test-run",
            client=client,
            profiles=PROFILES,
            doc_config=DOC_CONFIG,
            fixtures_dir=FIXTURES,
        )
    assert client.calls == 0


@pytest.mark.parametrize("name", ["starts.jsonl", "attempts.jsonl", "items.jsonl"])
@pytest.mark.parametrize("change", ["delete", "alter"])
def test_resume_refuses_tampered_or_deleted_evidence(config, name, change):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=3))
    directory = run_dir(config)
    manifest_bytes = (directory / "manifest.json").read_bytes()
    target = directory / name
    if change == "delete":
        target.unlink()
    else:
        text = target.read_text()
        target.write_text(text.replace('"run_id": "test-run"', '"run_id": "test-run", "x": 1', 1))
    client = FakeClient()
    with pytest.raises(ValueError, match="changed or missing"):
        execute(config, client, resume=True)
    assert client.calls == 0
    assert (directory / "manifest.json").read_bytes() == manifest_bytes


def test_resume_checks_item_against_its_attempt(config):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=3))
    directory = run_dir(config)
    target = directory / "items.jsonl"
    target.write_text(target.read_text().replace("Bonsai add-on", "Invented add-on"))
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["artifacts_sha256"] = artifact_hashes(directory)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="differs from its successful attempt"):
        execute(config, resume=True)


def test_resume_checks_start_against_the_slot_plan(config):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=3))
    directory = run_dir(config)
    target = directory / "starts.jsonl"
    records = read_records(target)
    records[0]["offered_sections"] = records[0]["offered_sections"][:1]
    target.write_text("".join(json.dumps(r) + "\n" for r in records))
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["artifacts_sha256"] = artifact_hashes(directory)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    client = FakeClient()
    with pytest.raises(ValueError, match="differs from its plan"):
        execute(config, client, resume=True)
    assert client.calls == 0


def test_resume_recovers_an_item_written_only_to_its_attempt(config, monkeypatch):
    real_append = generate.append_record
    state = {"failed": False}

    def append_once_failing(path, record):
        if path.name == "items.jsonl" and not state["failed"]:
            state["failed"] = True
            raise KeyboardInterrupt
        real_append(path, record)

    monkeypatch.setattr(generate, "append_record", append_once_failing)
    with pytest.raises(KeyboardInterrupt):
        execute(config)
    monkeypatch.undo()
    assert ledger(config, "items.jsonl") == []
    client = FakeClient()
    manifest = execute(config, client, resume=True)
    assert client.calls == 4
    assert manifest["status"] == "complete"
    assert manifest["metrics"]["initial_valid"] == 5
    first = ledger(config, "attempts.jsonl")[0]
    assert ledger(config, "items.jsonl")[0] == first["record"]


def test_resume_refuses_lock_gate_and_missing_run(config):
    with pytest.raises(ValueError, match="no run"):
        execute(config, resume=True)
    execute(config, FakeClient(fail=lambda s, a: True))
    lock = run_dir(config) / ".generation.lock"
    lock.write_text("another process")
    with pytest.raises(FileExistsError):
        execute(config, resume=True)
    assert lock.read_text() == "another process"
    lock.unlink()
    (run_dir(config) / "gate-report.json").write_text("{}")
    with pytest.raises(ValueError, match="gated runs are frozen"):
        execute(config, resume=True)


def test_manifest_records_identity_inputs_and_slots(config):
    manifest = execute(config)
    assert manifest["prompt_sha256"] == load_prompt(config)[1]
    files = manifest["implementation"]["source_files"]
    assert "src/bonsai_help/generate.py" in files
    assert {"pyproject.toml", "uv.lock", "prompt"} <= set(files)
    assert [s["slot_id"] for s in manifest["slots"]] == [
        s.slot_id for s in sampler.plan_slots(PROFILES, "development", 5)
    ]
    assert manifest["artifacts_sha256"] == artifact_hashes(run_dir(config))
    text = json.dumps(manifest)
    assert "api_key_env" not in text and FAKE_KEY not in text
    assert (run_dir(config) / "prompt.md").read_text() == load_prompt(config)[0]


def test_implementation_identity_is_derived_from_the_package():
    identity = generate.implementation_identity()
    package = sorted(p.name for p in (ROOT / "src/bonsai_help").glob("*.py"))
    assert (
        sorted(Path(k).name for k in identity["source_files"] if k.startswith("src/bonsai_help/"))
        == package
    )
    assert len(identity["source_tree_sha256"]) == 64


@pytest.mark.parametrize("extra", ["{other}", "{0}", "{category!z}"])
def test_prompt_with_an_unknown_placeholder_is_refused_before_any_write(config, tmp_path, extra):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text(config.prompt_file().read_text() + f"\nSee {extra}.\n")
    config = config.model_copy(update={"prompt_path": str(prompt_file)})
    client = FakeClient()
    with pytest.raises(ValueError, match="placeholder"):
        execute(config, client)
    assert client.calls == 0
    assert not run_dir(config).exists()


def test_item_timestamp_is_the_attempt_completion_time(config):
    execute(config)
    attempts = {a["attempt_id"]: a for a in ledger(config, "attempts.jsonl")}
    items = ledger(config, "items.jsonl")
    assert len(items) == 5
    for record in items:
        attempt = attempts[record["attempt_id"]]
        assert record["generated_at"] == attempt["completed_at"]
        assert attempt["record"]["generated_at"] == attempt["completed_at"]
        assert "generated_at" not in record["item"]


def test_resume_refuses_an_item_timestamp_that_differs_from_its_attempt(config):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=3))
    directory = run_dir(config)
    attempts = read_records(directory / "attempts.jsonl")
    items = read_records(directory / "items.jsonl")
    shifted = "2000-01-01T00:00:00+00:00"
    attempts[0]["record"]["generated_at"] = shifted
    items[0]["generated_at"] = shifted
    for name, records in (("attempts.jsonl", attempts), ("items.jsonl", items)):
        (directory / name).write_text("".join(json.dumps(r) + "\n" for r in records))
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["artifacts_sha256"] = artifact_hashes(directory)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    client = FakeClient()
    with pytest.raises(ValueError, match="provenance differs from its attempt"):
        execute(config, client, resume=True)
    assert client.calls == 0


@pytest.mark.parametrize(
    "extra,marker",
    [(float("nan"), "NaN"), (float("inf"), "Infinity"), ({"synthetic-set"}, "synthetic-set")],
)
def test_unserializable_raw_response_is_a_recorded_failed_attempt(config, extra, marker):
    client = FakeClient(raw=lambda envelope: {**envelope, "timing": extra})
    manifest = execute(config, client)
    assert manifest["status"] == "incomplete"
    starts, attempts = ledger(config, "starts.jsonl"), ledger(config, "attempts.jsonl")
    assert len(starts) == len(attempts) == client.calls == 5 * config.max_attempts
    assert manifest["metrics"]["unknown_outcomes"] == 0
    assert manifest["metrics"]["exhausted"] == 5
    assert ledger(config, "items.jsonl") == []
    for attempt in attempts:
        assert attempt["schema_valid"] is False and attempt["record"] is None
        assert attempt["error_type"] == "UnserializableResponse"
        assert attempt["verdict"] == "generation_failed"
        # The raw completion is kept, as text, with the synthetic item inside it.
        assert isinstance(attempt["raw_response"], str)
        assert marker in attempt["raw_response"]
        assert "synthetic Bonsai test project" in attempt["raw_response"]
    # Exhausted slots get no further attempts: a resume makes no requests.
    again = FakeClient()
    assert execute(config, again, resume=True)["status"] == "incomplete"
    assert again.calls == 0


def test_nan_in_a_real_response_body_is_recorded_not_raised(config):
    def handler(request: httpx.Request) -> httpx.Response:
        messages = json.loads(request.content)["messages"]
        body = json.dumps(completion(json.dumps(synthetic_generation(offered_ids(messages)[:1]))))
        body = body[:-1] + ', "timing": NaN}'
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "application/json"}
        )

    transport = FakeTransport(handler)
    with InstructorClient(
        base_url=FAKE_BASE_URL,
        model=FAKE_MODEL,
        api_key=FAKE_KEY,
        response_model=GenerationOutput,
        _transport=transport.transport,
    ) as client:
        manifest = execute(config, client)
    assert manifest["status"] == "incomplete"
    attempts = ledger(config, "attempts.jsonl")
    assert len(attempts) == len(ledger(config, "starts.jsonl")) == len(transport.calls)
    assert {a["error_type"] for a in attempts} == {"UnserializableResponse"}
    assert all('"timing": NaN' in a["raw_response"] for a in attempts)
    assert all(FAKE_KEY not in a["raw_response"] for a in attempts)


@pytest.mark.parametrize("reported", [" ", ""])
def test_blank_reported_model_is_a_recorded_failed_attempt(config, reported):
    client = FakeClient(model=reported)
    manifest = execute(config, client)
    assert manifest["status"] == "incomplete"
    attempts = ledger(config, "attempts.jsonl")
    assert len(attempts) == len(ledger(config, "starts.jsonl")) == client.calls
    assert manifest["metrics"]["unknown_outcomes"] == 0
    for attempt in attempts:
        assert attempt["error_type"] == "EnvelopeInvalid"
        assert "model" in attempt["error"]
        assert attempt["schema_valid"] is False and attempt["record"] is None
        assert attempt["raw_response"]["choices"]
        assert attempt["response_model"] == reported
    again = FakeClient()
    assert execute(config, again, resume=True)["status"] == "incomplete"
    assert again.calls == 0


def test_unreported_model_still_falls_back_to_the_configured_model(config):
    # Not reported (None) is unchanged: the configured id is recorded for non-assessed runs.
    client = FakeClient()
    client.model = None
    assert execute(config, client)["status"] == "complete"
    assert {r["model"] for r in ledger(config, "items.jsonl")} == {config.model}


def test_bracketed_citation_of_an_offered_id_counts_as_that_section(config):
    execute(config, FakeClient(cite=lambda ids: [f"[{ids[0]}]"]))
    attempts = ledger(config, "attempts.jsonl")
    items = ledger(config, "items.jsonl")
    assert len(items) == 5
    for record, attempt in zip(items, attempts):
        first = record["offered_sections"][0]
        assert record["cited_sections"] == [first]
        assert attempt["unoffered_citations"] == []
        # The model's own text is kept as listed.
        assert attempt["cited_section_ids"] == [f"[{first['id']}]"]


def test_resume_accepts_bracketed_citations(config):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(cite=lambda ids: [f"[{ids[0]}]"], interrupt_call=3))
    manifest = execute(config, FakeClient(cite=lambda ids: [f"[{ids[0]}]"]), resume=True)
    assert manifest["status"] == "complete"


def test_bracket_normalization_never_accepts_an_id_that_was_not_offered():
    offered = [
        CitedSection(id="bonsai-docs:a.rst#L1-L5", page_sha256="a" * 64, source="s", pin_id="p"),
        CitedSection(id="bonsai-docs:b.rst#L1-L5", page_sha256="b" * 64, source="s", pin_id="p"),
    ]
    listed = [
        "[bonsai-docs:b.rst#L1-L5]",  # one pair of brackets: offered id b
        "bonsai-docs:a.rst#L1-L5",  # exact: offered id a
        "[[bonsai-docs:a.rst#L1-L5]]",  # two pairs: only one is removed
        "[bonsai-docs:a.rst#L1-L5",  # unbalanced
        "bonsai-docs:a.rst#L1-L5]",  # unbalanced
        "[bonsai-docs:invented.rst#L1-L2]",  # bracketed but never offered
        "(bonsai-docs:a.rst#L1-L5)",  # other brackets are not stripped
    ]
    cited, unoffered = generate.split_citations(offered, listed)
    assert [s.id for s in cited] == ["bonsai-docs:a.rst#L1-L5", "bonsai-docs:b.rst#L1-L5"]
    assert unoffered == listed[2:]


# A lone UTF-16 surrogate escape (here from a synthetic broken emoji) is valid JSON that
# response.json() accepts but UTF-8 cannot encode. It must never stop the run between a
# start and its attempt record.
LONE_SURROGATE = "\ud83d"


def surrogate_body(messages, *, where: str) -> bytes:
    body = synthetic_generation(offered_ids(messages)[:1])
    body["item"]["tips"] = ["Use the synthetic marker SURROGATE-HERE."]
    text = json.dumps(completion(json.dumps(body)))
    if where == "content":
        # The HTTP body's content string itself holds the lone surrogate.
        text = text.replace("SURROGATE-HERE", "\\ud83d")
    elif where == "inner":
        # Escaped once more: the body is clean text and only the parsed item holds it.
        text = text.replace("SURROGATE-HERE", "\\\\ud83d")
    else:
        text = text[:-1] + ', "system_fingerprint": "synthetic-\\ud800"}'
    return text.encode()


@pytest.mark.parametrize("where", ["content", "inner", "envelope"])
def test_lone_surrogate_in_a_real_response_body_is_recorded_not_raised(config, where):
    def handler(request: httpx.Request) -> httpx.Response:
        messages = json.loads(request.content)["messages"]
        return httpx.Response(
            200,
            content=surrogate_body(messages, where=where),
            headers={"content-type": "application/json"},
        )

    transport = FakeTransport(handler)
    with InstructorClient(
        base_url=FAKE_BASE_URL,
        model=FAKE_MODEL,
        api_key=FAKE_KEY,
        response_model=GenerationOutput,
        _transport=transport.transport,
    ) as client:
        manifest = execute(config, client)
    assert manifest["status"] == "incomplete"
    assert manifest["metrics"]["unknown_outcomes"] == 0
    assert manifest["metrics"]["exhausted"] == 5
    starts, attempts = ledger(config, "starts.jsonl"), ledger(config, "attempts.jsonl")
    assert len(starts) == len(attempts) == len(transport.calls) == 5 * config.max_attempts
    assert ledger(config, "items.jsonl") == []
    for attempt in attempts:
        assert attempt["schema_valid"] is False and attempt["record"] is None
        assert attempt["raw_response"] is not None
        assert FAKE_KEY not in json.dumps(attempt)
        if where == "inner":
            # Strict JSON body, kept unchanged; the client rejected the item.
            assert attempt["raw_response"]["choices"]
            assert attempt["error_type"] not in (None, "UnserializableResponse")
            continue
        if where == "content":
            # The item cannot parse as a unicode string: the client's error type is kept.
            assert attempt["error_type"] not in (None, "UnserializableResponse")
            marker = "\\ud83d"
        else:
            # The item itself is valid; only the envelope cannot be stored as returned.
            assert attempt["error_type"] == "UnserializableResponse"
            assert "not strict JSON" in attempt["error"]
            marker = "\\ud800"
        # The raw completion is kept as text, the surrogate spelled as its escape.
        assert isinstance(attempt["raw_response"], str)
        assert "synthetic Bonsai test project" in attempt["raw_response"]
        assert marker in attempt["raw_response"]
    again = FakeClient()
    assert execute(config, again, resume=True)["status"] == "incomplete"
    assert again.calls == 0


def test_lone_surrogate_in_a_raw_envelope_field_fails_a_valid_item(config):
    client = FakeClient(raw=lambda envelope: {**envelope, "system_fingerprint": LONE_SURROGATE})
    manifest = execute(config, client)
    assert manifest["metrics"]["unknown_outcomes"] == 0
    attempts = ledger(config, "attempts.jsonl")
    assert len(attempts) == len(ledger(config, "starts.jsonl")) == client.calls
    assert {a["error_type"] for a in attempts} == {"UnserializableResponse"}
    assert all("\\ud83d" in a["raw_response"] for a in attempts)
    assert ledger(config, "items.jsonl") == []


def test_lone_surrogate_in_a_raw_text_response_is_kept_escaped(config):
    class TextClient(FakeClient):
        def generate(self, messages):
            super().generate(messages)
            text = "{synthetic-broken" + LONE_SURROGATE
            return AttemptResult(None, text, "synthetic parse failure", "ValidationError")

    client = TextClient()
    manifest = execute(config, client)
    assert manifest["metrics"]["unknown_outcomes"] == 0
    attempts = ledger(config, "attempts.jsonl")
    assert len(attempts) == len(ledger(config, "starts.jsonl")) == client.calls
    for attempt in attempts:
        assert attempt["raw_response"] == "{synthetic-broken\\ud83d"
        assert attempt["error_type"] == "ValidationError"


def test_lone_surrogate_in_a_reported_model_or_error_is_recorded_escaped(config):
    client = FakeClient(model="synthetic-model-" + LONE_SURROGATE)
    manifest = execute(config, client)
    assert manifest["metrics"]["unknown_outcomes"] == 0
    attempts = ledger(config, "attempts.jsonl")
    assert len(attempts) == len(ledger(config, "starts.jsonl")) == client.calls
    for attempt in attempts:
        assert attempt["error_type"] == "EnvelopeInvalid"
        assert attempt["response_model"] == "synthetic-model-\\ud83d"
        assert attempt["record"] is None

    class ErrorClient(FakeClient):
        def generate(self, messages):
            super().generate(messages)
            return AttemptResult(None, None, "synthetic failure " + LONE_SURROGATE, "APIError")

    errors = ErrorClient()
    execute(config, errors, run_id="error-run")
    attempts = read_records(run_dir(config, "error-run") / "attempts.jsonl")
    assert len(attempts) == errors.calls
    assert {a["error"] for a in attempts} == {"synthetic failure \\ud83d"}


class _Unrepresentable:
    """A synthetic raw value whose repr itself fails."""

    def __repr__(self) -> str:
        raise RuntimeError("synthetic repr failure")


def _cyclic() -> dict:
    loop: dict = {"note": "synthetic cycle"}
    loop["self"] = loop
    return loop


def _deep() -> list:
    nested: list = []
    for _ in range(100_000):
        nested = [nested]
    return nested


class _RaisingMapping(dict):
    """A synthetic mapping whose items() fails with an error JSON encoding does not expect."""

    def items(self):
        raise RuntimeError("synthetic items failure")


# Values no JSON or repr fallback can always spell: a custom ModelClient's raw response
# must still never raise between a start and its attempt record.
@pytest.mark.parametrize(
    "extra,keeps_item",
    [
        ({("synthetic", "tuple-key"): 1}, True),
        (_cyclic(), True),
        (_Unrepresentable(), True),
        (_deep(), False),
        (_RaisingMapping(note="synthetic"), True),
    ],
    ids=["tuple-key", "cycle", "unrepresentable", "deep", "raising-mapping"],
)
def test_raw_response_that_cannot_be_spelled_is_still_a_recorded_failed_attempt(
    config, extra, keeps_item
):
    client = FakeClient(raw=lambda envelope: {**envelope, "timing": extra})
    manifest = execute(config, client)
    assert manifest["status"] == "incomplete"
    starts, attempts = ledger(config, "starts.jsonl"), ledger(config, "attempts.jsonl")
    assert len(starts) == len(attempts) == client.calls == 5 * config.max_attempts
    assert manifest["metrics"]["unknown_outcomes"] == 0
    assert ledger(config, "items.jsonl") == []
    for attempt in attempts:
        assert attempt["schema_valid"] is False and attempt["record"] is None
        assert attempt["error_type"] == "UnserializableResponse"
        assert isinstance(attempt["raw_response"], str) and attempt["raw_response"]
        if keeps_item:
            assert "synthetic Bonsai test project" in attempt["raw_response"]


@pytest.mark.parametrize("failure", ["connect", "timeout", "server-error"])
def test_transport_failure_is_a_recorded_failed_attempt(config, failure):
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "connect":
            raise httpx.ConnectError("synthetic connection refused", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic read timeout", request=request)
        return httpx.Response(503, json={"error": {"message": "synthetic overload"}})

    transport = FakeTransport(handler)
    with InstructorClient(
        base_url=FAKE_BASE_URL,
        model=FAKE_MODEL,
        api_key=FAKE_KEY,
        response_model=GenerationOutput,
        _transport=transport.transport,
    ) as client:
        manifest = execute(config, client)
    assert manifest["status"] == "incomplete"
    metrics = manifest["metrics"]
    assert metrics["unknown_outcomes"] == 0
    assert metrics["exhausted"] == 5 and metrics["initial_valid"] == 0
    starts, attempts = ledger(config, "starts.jsonl"), ledger(config, "attempts.jsonl")
    # One request per attempt: no hidden SDK retries, every attempt bounded and recorded.
    assert len(transport.calls) == len(starts) == len(attempts) == 5 * config.max_attempts
    for attempt in attempts:
        assert attempt["schema_valid"] is False and attempt["record"] is None
        assert attempt["verdict"] == "generation_failed"
        assert attempt["error"] and attempt["error_type"]
        assert FAKE_KEY not in json.dumps(attempt)
    again = FakeClient()
    assert execute(config, again, resume=True)["status"] == "incomplete"
    assert again.calls == 0


def _package_copy(tmp_path: Path) -> Path:
    """A copy of the package tree, pyproject.toml and uv.lock; returns the package dir."""
    root = tmp_path / "tree"
    package = root / "src/bonsai_help"
    package.mkdir(parents=True)
    for module in (ROOT / "src/bonsai_help").glob("*.py"):
        shutil.copyfile(module, package / module.name)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(ROOT / name, root / name)
    return package


def test_resume_refuses_a_changed_or_added_module(config, tmp_path, monkeypatch):
    package = _package_copy(tmp_path)
    real = generate.implementation_identity()
    monkeypatch.setattr(generate, "_package_dir", lambda: package)
    assert generate.implementation_identity() == real
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=2))
    manifest_bytes = (run_dir(config) / "manifest.json").read_bytes()
    module = package / "sampler.py"
    original = module.read_bytes()
    for change in ("edit", "add"):
        if change == "edit":
            module.write_bytes(original + b"\n# synthetic edit\n")
        else:
            module.write_bytes(original)
            (package / "synthetic_extra.py").write_text("VALUE = 1\n")
        client = FakeClient()
        with pytest.raises(ValueError, match="original"):
            execute(config, client, resume=True)
        assert client.calls == 0
        assert (run_dir(config) / "manifest.json").read_bytes() == manifest_bytes


@pytest.mark.parametrize("name", ["pyproject.toml", "uv.lock"])
def test_missing_project_file_refuses_before_any_write(config, tmp_path, monkeypatch, name):
    package = _package_copy(tmp_path)
    (package.parents[1] / name).unlink()
    monkeypatch.setattr(generate, "_package_dir", lambda: package)
    client = FakeClient()
    with pytest.raises(FileNotFoundError, match="implementation identity") as raised:
        execute(config, client)
    assert Path(raised.value.filename).name == name
    assert client.calls == 0
    assert not run_dir(config).exists()


@pytest.mark.parametrize("change", ["alter", "delete"])
def test_resume_refuses_a_changed_or_missing_prompt_copy(config, change):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=3))
    directory = run_dir(config)
    manifest_bytes = (directory / "manifest.json").read_bytes()
    copy = directory / "prompt.md"
    if change == "delete":
        copy.unlink()
    else:
        copy.write_text(copy.read_text() + "\nSynthetic extra instruction.\n")
    client = FakeClient()
    with pytest.raises(ValueError, match="prompt.md"):
        execute(config, client, resume=True)
    assert client.calls == 0
    assert (directory / "manifest.json").read_bytes() == manifest_bytes


def test_resume_refuses_a_prompt_copy_edited_with_its_manifest_hash(config):
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=3))
    directory = run_dir(config)
    copy = directory / "prompt.md"
    edited = copy.read_text() + "\nSynthetic extra instruction.\n"
    copy.write_text(edited)
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["prompt_sha256"] = hashlib.sha256(edited.encode("utf-8")).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest))
    manifest_bytes = (directory / "manifest.json").read_bytes()
    client = FakeClient()
    with pytest.raises(ValueError, match="manifest prompt_sha256 differs from the run's prompt"):
        execute(config, client, resume=True)
    assert client.calls == 0
    assert (directory / "manifest.json").read_bytes() == manifest_bytes
    assert copy.read_text() == edited


class _BrokenClient(FakeClient):
    def generate(self, messages):
        if self.calls == 1:
            self.calls += 1
            raise RuntimeError("synthetic client bug")
        return super().generate(messages)


@pytest.mark.parametrize("client", [FakeClient(interrupt_call=2), _BrokenClient()])
def test_failed_interrupted_checkpoint_keeps_the_original_error(config, monkeypatch, client):
    real_checkpoint = generate.write_checkpoint

    def failing_checkpoint(path, record):
        if record.get("status") == "interrupted":
            raise OSError("synthetic disk full")
        real_checkpoint(path, record)

    monkeypatch.setattr(generate, "write_checkpoint", failing_checkpoint)
    with pytest.raises((KeyboardInterrupt, RuntimeError)) as raised:
        execute(config, client)
    assert not isinstance(raised.value, OSError)
    assert any("synthetic disk full" in note for note in raised.value.__notes__)
    assert not (run_dir(config) / ".generation.lock").exists()


def test_resume_refuses_a_start_after_a_successful_completion(config):
    first = sorted(first_slots(1)).pop()
    # A second run supplies the exact request the plan would make for attempt 2.
    execute(config, FakeClient(fail=lambda s, a: s == first and a == 1), run_id="other-run")
    other = read_records(run_dir(config, "other-run") / "starts.jsonl")
    second = next(s for s in other if s["slot_id"] == first and s["attempt_number"] == 2)
    with pytest.raises(KeyboardInterrupt):
        execute(config, FakeClient(interrupt_call=2))
    directory = run_dir(config)
    starts = read_records(directory / "starts.jsonl")
    success = next(s for s in starts if s["slot_id"] == first)
    forged = second | {
        "run_id": "test-run",
        "item_id": success["item_id"],
        "trace_id": success["trace_id"],
        "parent_attempt_id": success["attempt_id"],
    }
    with (directory / "starts.jsonl").open("a") as stream:
        stream.write(json.dumps(forged) + "\n")
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["artifacts_sha256"] = artifact_hashes(directory)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    client = FakeClient()
    with pytest.raises(ValueError, match="after its successful completion"):
        execute(config, client, resume=True)
    assert client.calls == 0


def test_assessed_check_is_shared_and_exact(config):
    assessed = config.model_copy(update={"purpose": "baseline", "split": "assessed"})
    with pytest.raises(ValueError) as raised:
        generate.check_assessed(assessed)
    with pytest.raises(ValueError) as from_run:
        execute(assessed, FakeClient())
    assert type(raised.value) is type(from_run.value)
    assert str(raised.value) == str(from_run.value)
    assert generate.check_assessed(config) is None
    complete = assessed.model_copy(
        update={"model_identity": "synthetic-weights-v1", "model_sha256": "a" * 64}
    )
    assert generate.check_assessed(complete) is None


@pytest.mark.parametrize("count", [0, 4, 6, 505, True, 5.0, "5"])
def test_public_count_check_refuses_what_a_run_refuses(count):
    with pytest.raises(ValueError, match="multiple of 5"):
        generate.check_count(count)


@pytest.mark.parametrize("count", [5, 50, 500])
def test_public_count_check_accepts_valid_counts(count):
    assert generate.check_count(count) is None
