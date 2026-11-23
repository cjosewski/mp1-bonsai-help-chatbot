"""Generation run: initial-attempt denominators, bounded retries, resume and the envelope.

Model output here is synthetic (tests/fakes.py); documentation text comes only from the
committed fixture slice.
"""

from __future__ import annotations

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

    def __init__(self, *, fail=None, interrupt_call=None, cite=None, model=None):
        self.calls = 0
        self.messages = []
        self.fail = fail or (lambda slot_id, attempt: False)
        self.interrupt_call = interrupt_call
        self.cite = cite or (lambda ids: ids[:1])
        self.model = model or "synthetic-model-revision"

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
        return AttemptResult(output, completion(json.dumps(body)), None, None, self.model)


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
