"""Judge qualification receipts: a distinct model, complete smoke evidence, written once.

No model is called. The smoke judge runs are synthetic: `judge.judge_status` (Task 4) is
replaced by a scripted module that reports a status for each synthetic smoke run, in the
shape `qualification.SMOKE_STATUS_FIELDS` documents. The assessments come from the
synthetic cohorts of `evaluation_support`; no label is entered.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import types

import pytest
from evaluation_support import FIXTURES, SOURCES, doc_config, fresh_root, profiles, write_rubric

from bonsai_help import assessment, qualification
from bonsai_help.judge_config import JudgeConfig
from bonsai_help.qualification import QualificationError
from bonsai_help.tracing import digest

KEY_ENV = "SYNTHETIC_JUDGE_QUALIFY_KEY"
KEY_SENTINEL = "sk-synthetic-qualify-sentinel-0123456789"
JUDGE_MODEL = "synthetic-judge-model-zq9"
JUDGE_IDENTITY = "synthetic-judge-identity-zq9"
JUDGE_SHA = "9" * 64
DEVELOPMENT = SOURCES["development"]
BASELINE = SOURCES["baseline"]
SMOKE_ASSESSMENT = "dev-smoke"
SMOKE_RUN = "smoke-judge-1"


class FakeJudgeModule(types.ModuleType):
    """Stands in for `bonsai_help.judge`: a scripted `judge_status` per smoke run."""

    def __init__(self) -> None:
        super().__init__("bonsai_help.judge")
        self.statuses: dict[tuple[str, str], dict] = {}
        self.calls: list[tuple[str, str]] = []

    def judge_status(self, root, assessment_id, judge_run_id):
        self.calls.append((assessment_id, judge_run_id))
        try:
            return json.loads(json.dumps(self.statuses[(assessment_id, judge_run_id)]))
        except KeyError:
            raise ValueError(f"no judge run {judge_run_id!r}") from None


@pytest.fixture
def judge(monkeypatch):
    fake = FakeJudgeModule()
    monkeypatch.setitem(sys.modules, "bonsai_help.judge", fake)
    return fake


@pytest.fixture
def root(tmp_path, tmp_path_factory):
    return fresh_root(tmp_path, tmp_path_factory)


@pytest.fixture
def accepted(tmp_path):
    return write_rubric(tmp_path, name="accepted-rubric.json")


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(KEY_ENV, KEY_SENTINEL)


def create(root, accepted, assessment_id, cohort_id, count, seed="synthetic-seed-q"):
    return assessment.create_assessment(
        root,
        assessment_id,
        [cohort_id],
        count=count,
        seed=seed,
        rubric_path=accepted,
        profiles=profiles(),
        doc_config=doc_config(),
        fixtures_dir=FIXTURES,
    )


@pytest.fixture
def smoke(root, accepted):
    return create(root, accepted, SMOKE_ASSESSMENT, DEVELOPMENT.cohort_id, 5)


def make(root, **overrides) -> JudgeConfig:
    values = {
        "base_url": "http://127.0.0.1:8082/v1",
        "model": JUDGE_MODEL,
        "model_identity": JUDGE_IDENTITY,
        "model_sha256": JUDGE_SHA,
        "purpose": "measured",
        "api_key_env": KEY_ENV,
        "artifact_root": str(root),
    }
    values.update(overrides)
    return JudgeConfig.model_validate(values)


def status(config: JudgeConfig, **changes) -> dict:
    """A complete synthetic smoke run judged with `config`'s settings as a smoke judge."""
    settings = config.model_copy(update={"purpose": "smoke"}).public_settings()
    value = {
        "assessment_id": SMOKE_ASSESSMENT,
        "judge_run_id": SMOKE_RUN,
        "purpose": "smoke",
        "status": "complete",
        "settings": settings,
        "prompt_version": "judge-v1",
        "population": 5,
        "resolved": 5,
        "started_attempts": 6,
        "completed_attempts": 6,
        "unknown_outcomes": [],
        "unresolved": [],
        "reported_models": [config.model],
    }
    value.update(changes)
    return value


def qualify(config, root, qualification_id="q-1", run=SMOKE_RUN, assessment_id=SMOKE_ASSESSMENT):
    return qualification.qualify(
        config,
        root,
        smoke_assessment_id=assessment_id,
        smoke_judge_run_id=run,
        qualification_id=qualification_id,
    )


def receipt_path(root, qualification_id="q-1"):
    return root / qualification.QUALIFICATIONS / f"{qualification_id}.json"


def generators(root, assessment_id):
    loaded = assessment.load_assessment(
        root, assessment_id, fixtures_dir=FIXTURES, doc_config=doc_config()
    )
    return qualification.source_generators(root, loaded.manifest["sources"])


def baseline_source() -> dict:
    return {
        "collection_id": BASELINE.collection_id,
        "model": BASELINE.model,
        "model_identity": BASELINE.model_identity,
        "model_sha256": BASELINE.model_sha256,
        "temperature": 0.6,
    }


def test_source_generators_come_from_the_recorded_collections(root, accepted, smoke):
    assert generators(root, SMOKE_ASSESSMENT) == [
        {
            "collection_id": DEVELOPMENT.collection_id,
            "model": DEVELOPMENT.model,
            "model_identity": DEVELOPMENT.model_identity,
            "model_sha256": DEVELOPMENT.model_sha256,
            "temperature": 0.6,
        }
    ]


def test_qualification_requires_distinct_model(root, smoke, judge):
    same = {
        "model": {"model": DEVELOPMENT.model},
        "model_identity": {"model_identity": DEVELOPMENT.model_identity},
        "model_sha256": {"model_sha256": DEVELOPMENT.model_sha256},
        # A judge name equal to a generator name in the other field, or in another case.
        "model as identity": {"model": DEVELOPMENT.model_identity},
        "identity in upper case": {"model_identity": DEVELOPMENT.model_identity.upper()},
    }
    for name, override in same.items():
        config = make(root, **override)
        judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = status(config)
        with pytest.raises(QualificationError, match="same model as a source generator"):
            qualify(config, root, f"q-{len(name)}")
    assert not (root / qualification.QUALIFICATIONS).exists()

    # Without an identity and a checksum the judge cannot be shown to be distinct.
    bare = make(root, purpose="smoke", model_identity=None, model_sha256=None)
    judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = status(bare)
    with pytest.raises(QualificationError, match="model_identity and model_sha256"):
        qualify(bare, root)

    config = make(root)
    judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = status(config)
    receipt = qualify(config, root)
    assert receipt["basis"] == {
        "kind": "distinct_model",
        "decision": "DECISIONS.md, November 24, 2026: judge model",
    }
    assert receipt["smoke_generators"] == generators(root, SMOKE_ASSESSMENT)
    sources = [baseline_source()]
    validated = qualification.validate_qualification(config, "q-1", sources, root)
    assert validated["receipt"] == receipt
    assert validated["sha256"] == hashlib.sha256(receipt_path(root).read_bytes()).hexdigest()

    # A judged assessment whose generator is the judge's model is refused at validation.
    for field, value in (
        ("model", JUDGE_MODEL),
        ("model_identity", JUDGE_IDENTITY),
        ("model_sha256", JUDGE_SHA),
        ("model", JUDGE_IDENTITY.upper()),
    ):
        clash = [baseline_source(), baseline_source() | {field: value}]
        with pytest.raises(QualificationError, match="same model as a source generator"):
            qualification.validate_qualification(config, "q-1", clash, root)
    for malformed in ([], [{"model": BASELINE.model}], [baseline_source() | {"model": " "}]):
        with pytest.raises(QualificationError, match="source generator"):
            qualification.validate_qualification(config, "q-1", malformed, root)


def test_qualification_requires_complete_smoke_evidence(root, accepted, smoke, judge):
    config = make(root)
    refusals = {
        "incomplete": (status(config, status="incomplete"), "not complete"),
        "unresolved": (status(config, unresolved=["L-003"], resolved=4), "not complete"),
        "short": (status(config, resolved=4), "not complete"),
        "empty": (status(config, population=0, resolved=0), "not complete"),
        "measured": (status(config, purpose="measured"), "not a smoke run"),
        "temperature": (
            status(config, settings=status(config)["settings"] | {"temperature": 0.1}),
            "other settings: temperature",
        ),
        "checksum": (
            status(config, settings=status(config)["settings"] | {"model_sha256": "8" * 64}),
            "other settings: model_sha256",
        ),
        "mode": (
            status(config, settings=status(config)["settings"] | {"mode": "tools"}),
            "other settings: mode",
        ),
        "thinking": (
            status(config, settings=status(config)["settings"] | {"enable_thinking": False}),
            "other settings: enable_thinking",
        ),
        "other model": (
            status(config, reported_models=[JUDGE_MODEL, "synthetic-other-model"]),
            "reported a model other than",
        ),
        "generator reply": (
            status(config, reported_models=[DEVELOPMENT.model]),
            "reported a model other than",
        ),
        "no reply": (status(config, reported_models=[]), "no reply reported"),
        "unknown shape": (
            {k: v for k, v in status(config).items() if k != "reported_models"},
            "reported_models",
        ),
    }
    for name, (value, match) in refusals.items():
        judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = value
        with pytest.raises(QualificationError, match=match):
            qualify(config, root, "q-refused")
        assert not receipt_path(root, "q-refused").exists(), name

    with pytest.raises(QualificationError, match="smoke judge run"):
        qualify(config, root, "q-refused", run="no-such-run")
    with pytest.raises(QualificationError, match="no assessment"):
        qualify(config, root, "q-refused", assessment_id="no-such-assessment")

    # A smoke run is evidence only on a development assessment that is never labeled.
    create(root, accepted, "arm-1", BASELINE.cohort_id, 20)
    judge.statuses[("arm-1", SMOKE_RUN)] = status(config, assessment_id="arm-1")
    with pytest.raises(QualificationError, match="development assessment"):
        qualify(config, root, "q-refused", assessment_id="arm-1")
    assert not receipt_path(root, "q-refused").exists()

    # Any prompt, either purpose in the qualified config, and disclosed unknown outcomes
    # are accepted: the evidence is about the model and its settings.
    other_prompt = status(
        config,
        settings=status(config)["settings"] | {"prompt_path": "prompts/judge-v2.md"},
        prompt_version="judge-v2",
        unknown_outcomes=[f"{SMOKE_RUN}:L-002:1"],
    )
    judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = other_prompt
    receipt = qualify(config.model_copy(update={"purpose": "smoke"}), root, "q-ok")
    assert receipt["evidence"]["unknown_outcomes"] == [f"{SMOKE_RUN}:L-002:1"]
    assert receipt["evidence"]["reported_models"] == [JUDGE_MODEL]
    assert receipt["evidence"]["status_sha256"] == digest(
        {k: other_prompt[k] for k in qualification.SMOKE_STATUS_FIELDS}
    )


def test_qualification_refuses_changed_settings(root, smoke, judge):
    config = make(root)
    judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = status(config)
    qualify(config, root)
    changes = {
        "temperature": 0.1,
        "max_tokens": 1200,
        "timeout_seconds": 450,
        "max_attempts": 3,
        "mode": "tools",
        "enable_thinking": False,
        "base_url": "http://127.0.0.1:8090/v1",
        "model": "synthetic-judge-model-other",
        "model_identity": "synthetic-judge-identity-other",
        "model_sha256": "7" * 64,
    }
    for field, value in changes.items():
        changed = make(root, **{field: value})
        with pytest.raises(QualificationError, match=f"does not match the judge config: {field}"):
            qualification.validate_qualification(changed, "q-1", [baseline_source()], root)
    with pytest.raises(QualificationError, match="does not match the judge config: authentication"):
        key_file = root.parent / "synthetic-key.txt"
        key_file.write_text(KEY_SENTINEL, encoding="utf-8")
        changed = make(root, api_key_env=None, api_key_file=str(key_file))
        qualification.validate_qualification(changed, "q-1", [baseline_source()], root)
    # A smoke config is never a measured run's judge.
    smoke_config = config.model_copy(update={"purpose": "smoke"})
    with pytest.raises(QualificationError, match="measured"):
        qualification.validate_qualification(smoke_config, "q-1", [baseline_source()], root)
    # The prompt, the example pool settings and the artifact root are not qualified.
    unqualified = make(
        root,
        prompt_path="prompts/judge-v2.md",
        examples_k=6,
        embedding_model="synthetic-embedding",
    )
    assert qualification.validate_qualification(unqualified, "q-1", [baseline_source()], root)


def reseal(path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    data["sha256"] = digest({k: v for k, v in data.items() if k != "sha256"})
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_qualification_receipt_is_written_once_and_tamper_evident(root, accepted, smoke, judge):
    config = make(root)
    judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = status(config)
    receipt = qualify(config, root)
    path = receipt_path(root)
    original = path.read_bytes()
    assert set(receipt) == qualification.RECEIPT_FIELDS
    assert receipt["sha256"] == digest({k: v for k, v in receipt.items() if k != "sha256"})
    assert json.loads(original) == receipt
    with pytest.raises(QualificationError, match="already exists"):
        qualify(config, root)
    assert path.read_bytes() == original
    assert [p.name for p in path.parent.iterdir()] == ["q-1.json"]  # no temporary left

    def refused(match):
        with pytest.raises(QualificationError, match=match):
            qualification.validate_qualification(config, "q-1", [baseline_source()], root)

    def restore():
        path.write_bytes(original)
        qualification.validate_qualification(config, "q-1", [baseline_source()], root)

    # An edit without a new seal.
    data = json.loads(original)
    data["judge"]["temperature"] = 0.1
    path.write_text(json.dumps(data), encoding="utf-8")
    refused("receipt changed")
    restore()
    # Resealed edits: a changed basis, a changed evidence hash, an added field.
    reseal(path, lambda d: d["basis"].update(kind="same_model"))
    refused("receipt changed")
    restore()
    reseal(path, lambda d: d["evidence"].update(status_sha256="0" * 64))
    refused("smoke evidence changed")
    restore()
    reseal(path, lambda d: d.update(note="synthetic"))
    refused("receipt changed")
    restore()
    reseal(path, lambda d: d.update(qualification_id="q-2"))
    refused("receipt changed")
    restore()
    # The smoke evidence itself changes after the receipt was written.
    judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = status(config, started_attempts=7) | {
        "unknown_outcomes": [f"{SMOKE_RUN}:L-001:2"]
    }
    refused("smoke evidence changed")
    del judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)]
    refused("smoke judge run")
    judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = status(config)
    restore()
    # The smoke assessment is replaced by another under the same id.
    moved = root.parent / "moved-smoke"
    smoke_dir = assessment.assessment_directory(root, SMOKE_ASSESSMENT)
    smoke_dir.rename(moved)
    refused("no assessment")
    create(root, accepted, SMOKE_ASSESSMENT, DEVELOPMENT.cohort_id, 5, seed="synthetic-seed-r")
    refused("smoke evidence changed")
    shutil.rmtree(smoke_dir)
    moved.rename(smoke_dir)
    restore()
    # Unreadable, malformed, symlinked or missing receipts.
    path.write_text("{not json", encoding="utf-8")
    refused("not a JSON object")
    path.write_text("[]", encoding="utf-8")
    refused("not a JSON object")
    restore()
    elsewhere = root.parent / "elsewhere.json"
    elsewhere.write_bytes(original)
    path.unlink()
    path.symlink_to(elsewhere)
    refused("symlink")
    path.unlink()
    refused("no judge qualification")
    with pytest.raises(QualificationError, match="qualification id"):
        qualification.validate_qualification(config, "../q-1", [baseline_source()], root)


def test_receipt_and_messages_hold_no_credential(root, smoke, judge, tmp_path):
    key_file = tmp_path / "synthetic-qualify-key.txt"
    key_file.write_text(KEY_SENTINEL, encoding="utf-8")
    errors: list[str] = []
    for index, credential in enumerate(
        ({"api_key_env": KEY_ENV}, {"api_key_env": None, "api_key_file": str(key_file)})
    ):
        config = make(root, **credential)
        judge.statuses[(SMOKE_ASSESSMENT, SMOKE_RUN)] = status(config)
        qualify(config, root, f"q-{index}")
        text = receipt_path(root, f"q-{index}").read_text(encoding="utf-8")
        for secret in (KEY_SENTINEL, KEY_ENV, str(key_file), key_file.name):
            assert secret not in text
        # Every refusal's message, too.
        for attempt in (
            lambda: qualify(config, root, f"q-{index}"),
            lambda: qualify(make(root, model=DEVELOPMENT.model, **credential), root, "q-x"),
            lambda: qualification.validate_qualification(
                make(root, temperature=0.2, **credential), f"q-{index}", [baseline_source()], root
            ),
            lambda: qualification.validate_qualification(config, "q-missing", [], root),
        ):
            with pytest.raises(QualificationError) as raised:
                attempt()
            errors.append(str(raised.value))
    assert len(errors) == 8
    for message in errors:
        for secret in (KEY_SENTINEL, KEY_ENV, str(key_file), key_file.name, str(root)):
            assert secret not in message
