"""The judge's own configuration: local endpoints only, bounded, one credential source."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bonsai_help.config import REPOSITORY, HostedRefused
from bonsai_help.doc_sources import ConfigError
from bonsai_help.judge_config import JudgeConfig, load_judge_config, load_judge_prompt

EXAMPLE = REPOSITORY / "config" / "judge.example.json"
SENTINEL = "sk-judge-sentinel-0123456789"
EMBED_SENTINEL = "sk-judge-embedding-sentinel-0123456789"
SYNTHETIC_SHA = "ab" * 32


def make(**overrides):
    values = {
        "base_url": "http://127.0.0.1:8082/v1",
        "model": "synthetic-judge-model",
        "purpose": "smoke",
        "api_key_env": "BONSAI_HELP_JUDGE_API_KEY",
    }
    values.update(overrides)
    return JudgeConfig.model_validate(values)


def measured(**overrides):
    return make(
        purpose="measured",
        model_identity="synthetic-judge-identity",
        model_sha256=SYNTHETIC_SHA,
        **overrides,
    )


def write_config(tmp_path: Path, **changes) -> Path:
    values = json.loads(EXAMPLE.read_text(encoding="utf-8")) | changes
    path = tmp_path / "judge.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def test_example_config_loads_with_placeholders_and_the_documented_defaults():
    config = load_judge_config(EXAMPLE)
    assert config.base_url == "http://127.0.0.1:8082/v1"
    assert config.purpose == "smoke"
    assert (config.prompt_path, config.mode) == ("prompts/judge-v1.md", "json")
    assert (config.temperature, config.enable_thinking) == (0.0, None)
    assert (config.timeout_seconds, config.max_tokens, config.max_attempts) == (300, 1500, 2)
    assert (config.examples_k, config.artifact_root, config.hosted) == (4, "runs", False)
    # Placeholders only: the judge model's file name and hash never enter Git.
    raw = EXAMPLE.read_text(encoding="utf-8")
    assert config.model_sha256 is None and config.model_identity is None
    assert ".gguf" not in raw.casefold() and "llama" not in raw.casefold()
    text, digest, version = load_judge_prompt(config, with_examples=False)
    assert version == "judge-v1" and len(digest) == 64 and text


REFUSED_URLS = [
    "http://8.8.8.8/v1",
    "http://example.com/v1",
    "https://api.example.com/v1",
    "http://127.0.0.1:8082/api",
    "http://127.0.0.1:8082",
    "http://user:pass@127.0.0.1:8082/v1",
    "http://127.0.0.1:8082/v1?key=x",
    "http://169.254.169.254/v1",
    "ftp://127.0.0.1/v1",
]


@pytest.mark.parametrize("url", REFUSED_URLS)
@pytest.mark.parametrize("field", ["base_url", "embedding_base_url"])
def test_judge_config_local_endpoint_and_hosted_refused(url, field):
    extra = {"embedding_model": "synthetic-embed"} if field == "embedding_base_url" else {}
    with pytest.raises(ValidationError) as caught:
        make(**{field: url}, **extra)
    assert url not in str(caught.value)


@pytest.mark.parametrize("hosted_url", ["https://api.example.com/v1", "http://127.0.0.1:8082/v1"])
def test_hosted_true_is_refused_at_load(tmp_path, hosted_url):
    with pytest.raises(HostedRefused) as caught:
        make(base_url=hosted_url, hosted=True)
    assert isinstance(caught.value, ConfigError) and caught.value.exit_code == 2
    assert "not implemented" in str(caught.value) and "Chad" in str(caught.value)
    with pytest.raises(HostedRefused):
        load_judge_config(write_config(tmp_path, base_url=hosted_url, hosted=True))


def test_local_and_private_endpoints_accepted():
    for url in ("http://localhost:8082/v1/", "http://192.168.1.5:8082/v1", "http://[::1]:8/v1"):
        assert make(base_url=url).base_url == url.rstrip("/")


@pytest.mark.parametrize(
    "bad",
    [
        {"temperature": -0.1},
        {"temperature": 2.01},
        {"temperature": float("nan")},
        {"temperature": True},
        {"max_attempts": 0},
        {"max_attempts": 4},
        {"max_attempts": True},
        {"timeout_seconds": 0},
        {"timeout_seconds": 600.5},
        {"timeout_seconds": 601},
        {"max_tokens": 0},
        {"max_tokens": True},
        {"examples_k": 0},
        {"examples_k": 7},
        {"examples_k": True},
        {"examples_k": 4.0},
        {"max_attempts": "2"},
        {"mode": "markdown"},
        {"purpose": "baseline"},
    ],
)
def test_judge_config_bounds(bad):
    with pytest.raises(ValidationError):
        make(**bad)


def test_judge_config_bounds_accept_the_limits():
    config = make(temperature=2, max_attempts=3, timeout_seconds=600, examples_k=6)
    assert (config.max_attempts, config.timeout_seconds, config.examples_k) == (3, 600, 6)
    assert make(examples_k=1, max_attempts=1, temperature=0).examples_k == 1


def test_generation_fields_and_unknown_fields_are_refused():
    for extra in ({"seed": 1}, {"split": "development"}, {"prompt_variant": "baseline"}, {"x": 1}):
        with pytest.raises(ValidationError):
            make(**extra)


def test_exactly_one_credential_source():
    with pytest.raises(ValidationError, match="exactly one"):
        make(api_key_env=None)
    with pytest.raises(ValidationError, match="exactly one"):
        make(api_key_file="/synthetic/key")
    assert make(api_key_env=None, api_key_file="/synthetic/key").api_key_file == "/synthetic/key"
    with pytest.raises(ValidationError, match="at most one"):
        make(
            embedding_model="synthetic-embed",
            embedding_api_key_env="SYNTHETIC_EMBED_KEY",
            embedding_api_key_file="/synthetic/embed-key",
        )


def test_api_key_from_env_and_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BONSAI_HELP_JUDGE_API_KEY", SENTINEL)
    assert make().api_key() == SENTINEL
    monkeypatch.delenv("BONSAI_HELP_JUDGE_API_KEY")
    with pytest.raises(ValueError, match="missing or empty"):
        make().api_key()
    key = tmp_path / "judge-key"
    key.write_text(SENTINEL + "\n", encoding="utf-8")
    assert make(api_key_env=None, api_key_file=str(key)).api_key() == SENTINEL
    with pytest.raises(ValueError, match="cannot read"):
        make(api_key_env=None, api_key_file=str(tmp_path / "absent")).api_key()


def test_credential_never_in_public_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("BONSAI_HELP_JUDGE_API_KEY", SENTINEL)
    key_file = tmp_path / "embed-key-file-sentinel"
    key_file.write_text(EMBED_SENTINEL, encoding="utf-8")
    config = make(
        embedding_model="synthetic-embed",
        embedding_base_url="http://127.0.0.1:8081/v1",
        embedding_api_key_file=str(key_file),
    )
    assert (config.api_key(), config.embedding_api_key()) == (SENTINEL, EMBED_SENTINEL)
    settings = config.public_settings()
    text = json.dumps(settings)
    for secret in (SENTINEL, EMBED_SENTINEL, str(key_file), "BONSAI_HELP_JUDGE_API_KEY"):
        assert secret not in text
    assert "api_key" not in text
    assert settings["authentication"] == "environment"
    assert settings["embedding_authentication"] == "file"
    for bad in (
        {"base_url": SENTINEL},
        {"model": 5, "model_identity": SENTINEL},
        {"api_key_env": SENTINEL},
        {"embedding_model": "e", "embedding_api_key_env": SENTINEL},
        {"api_key_file": SENTINEL},
        {"model_sha256": SENTINEL},
    ):
        with pytest.raises(ValidationError) as caught:
            make(**bad)
        rendered = (str(caught.value), repr(caught.value))
        rendered += (json.dumps(caught.value.errors(include_input=False), default=str),)
        for message in rendered:
            assert SENTINEL not in message


def test_short_key_is_refused_without_echoing_it(monkeypatch):
    monkeypatch.setenv("BONSAI_HELP_JUDGE_API_KEY", "short-key")
    with pytest.raises(ValueError, match="chat API key") as caught:
        make().api_key()
    assert "short-key" not in str(caught.value)


def test_enable_thinking_is_strict_and_recorded(tmp_path):
    for value in ("false", "true", 0, 1):
        with pytest.raises(ValidationError, match="enable_thinking"):
            make(enable_thinking=value)
        with pytest.raises(ValidationError, match="enable_thinking"):
            load_judge_config(write_config(tmp_path, enable_thinking=value))
    recorded = [make(enable_thinking=v).public_settings()["enable_thinking"] for v in (None, True)]
    assert recorded == [None, True]
    assert make(enable_thinking=False).public_settings()["enable_thinking"] is False
    assert "enable_thinking" in make().public_settings()


def test_measured_judge_requires_model_identity_and_sha():
    with pytest.raises(ValidationError, match="model_identity and model_sha256"):
        make(purpose="measured")
    with pytest.raises(ValidationError, match="model_identity and model_sha256"):
        make(purpose="measured", model_identity="synthetic-judge-identity")
    with pytest.raises(ValidationError, match="model_identity and model_sha256"):
        make(purpose="measured", model_sha256=SYNTHETIC_SHA)
    for bad_sha in (SYNTHETIC_SHA.upper(), SYNTHETIC_SHA[:-1], SYNTHETIC_SHA + "0", "g" * 64):
        with pytest.raises(ValidationError, match="model_sha256"):
            make(
                purpose="measured", model_identity="synthetic-judge-identity", model_sha256=bad_sha
            )
        with pytest.raises(ValidationError, match="model_sha256"):
            make(model_sha256=bad_sha)
    config = measured()
    settings = config.public_settings()
    assert (settings["purpose"], settings["model_sha256"]) == ("measured", SYNTHETIC_SHA)
    assert settings["model_identity"] == "synthetic-judge-identity"
    # A smoke judge may leave both unset.
    assert make().public_settings()["model_sha256"] is None


def test_embedding_settings_need_an_embedding_model(monkeypatch):
    for orphan in (
        {"embedding_base_url": "http://127.0.0.1:8081/v1"},
        {"embedding_api_key_env": "SYNTHETIC_EMBED_KEY"},
        {"embedding_api_key_file": "/synthetic/embed-key"},
    ):
        with pytest.raises(ValidationError, match="embedding_model"):
            make(**orphan)
    plain = make()
    assert plain.embedding_endpoint() is None
    assert plain.public_settings()["embedding_base_url"] is None
    assert plain.public_settings()["embedding_authentication"] is None
    with pytest.raises(ValueError, match="no embedding model"):
        plain.embedding_api_key()
    monkeypatch.setenv("BONSAI_HELP_JUDGE_API_KEY", SENTINEL)
    shared = make(embedding_model="synthetic-embed")
    # Without its own endpoint or credential the chat ones serve embeddings, as in RunConfig.
    assert shared.embedding_endpoint() == "http://127.0.0.1:8082/v1"
    assert shared.embedding_api_key() == SENTINEL
    assert shared.public_settings()["embedding_authentication"] == "shared"
    assert shared.public_settings()["embedding_base_url"] == "http://127.0.0.1:8082/v1"


def test_artifact_root_and_paths_resolve_against_the_repository(tmp_path, monkeypatch):
    assert make(artifact_root="runs/judges").artifact_path() == REPOSITORY / "runs/judges"
    assert make(artifact_root=str(tmp_path)).artifact_path() == tmp_path.resolve()
    for bad in ("src", "data", str(REPOSITORY), "runs/../src", "submission"):
        with pytest.raises(ValidationError, match="artifact_root"):
            make(artifact_root=bad)
    monkeypatch.chdir(tmp_path)
    assert make().prompt_file() == REPOSITORY / "prompts/judge-v1.md"
    assert load_judge_prompt(make(), with_examples=False)[2] == "judge-v1"
