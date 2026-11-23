import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bonsai_help import config as config_module
from bonsai_help.config import RunConfig, load_config, load_prompt

REPO = Path(config_module.__file__).resolve().parents[2]
SENTINEL = "sk-sentinel-0123456789"


def make(**overrides):
    values = {
        "base_url": "http://127.0.0.1:8080/v1",
        "model": "local-model",
        "embedding_model": "local-embed",
        "seed": 7,
        "api_key_env": "BONSAI_HELP_API_KEY",
        "artifact_root": "runs",
    }
    values.update(overrides)
    return RunConfig.model_validate(values)


def test_defaults_and_example_config_load():
    config = load_config(REPO / "config" / "run.example.json")
    assert config.base_url == "http://127.0.0.1:8080/v1"
    assert (config.temperature, config.timeout_seconds) == (0.6, 120)
    assert (config.max_tokens, config.max_attempts, config.artifact_root) == (2000, 3, "runs")


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/v1",
        "http://example.com/v1",
        "http://127.0.0.1:8080/api",
        "http://127.0.0.1:8080",
        "http://user:pass@127.0.0.1/v1",
        "http://127.0.0.1/v1?x=1",
        "ftp://127.0.0.1/v1",
    ],
)
def test_local_endpoint_rules(url):
    with pytest.raises(ValidationError):
        make(base_url=url)


@pytest.mark.parametrize("url", ["http://localhost:9/v1/", "http://192.168.1.5:8080/v1"])
def test_local_and_private_endpoints_accepted(url):
    assert make(base_url=url).base_url == url.rstrip("/")


def test_hosted_requires_flag_auth_and_cap():
    hosted = {"base_url": "https://api.example.com/v1"}
    with pytest.raises(ValidationError):
        make(**hosted)
    with pytest.raises(ValidationError):
        make(**hosted, hosted=True)
    with pytest.raises(ValidationError):
        make(**hosted, hosted=True, hosted_authorization="note", cost_cap_usd=0)
    with pytest.raises(ValidationError):
        make(
            base_url="http://api.example.com/v1",
            hosted=True,
            hosted_authorization="n",
            cost_cap_usd=5,
        )
    ok = make(**hosted, hosted=True, hosted_authorization="note", cost_cap_usd=5)
    assert ok.hosted


def test_exactly_one_credential_source():
    with pytest.raises(ValidationError):
        make(api_key_env=None, api_key_file=None)
    with pytest.raises(ValidationError):
        make(api_key_env="X", api_key_file="/some/key")
    assert make(api_key_env=None, api_key_file="/some/key").api_key_file == "/some/key"


def test_api_key_from_env_and_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BONSAI_HELP_API_KEY", SENTINEL)
    assert make().api_key() == SENTINEL
    monkeypatch.delenv("BONSAI_HELP_API_KEY")
    with pytest.raises(ValueError):
        make().api_key()
    key = tmp_path / "key"
    key.write_text(SENTINEL + "\n", encoding="utf-8")
    assert make(api_key_env=None, api_key_file=str(key)).api_key() == SENTINEL
    with pytest.raises(ValueError):
        make(api_key_env=None, api_key_file=str(tmp_path / "missing")).api_key()


def test_credential_never_in_public_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("BONSAI_HELP_API_KEY", SENTINEL)
    config = make()
    config.api_key()
    text = json.dumps(config.public_settings())
    assert SENTINEL not in text
    assert "api_key" not in text
    assert config.public_settings()["authentication"] == "environment"
    for bad in (
        {"seed": SENTINEL},
        {"base_url": SENTINEL},
        {"api_key_env": SENTINEL, "api_key_file": SENTINEL},
    ):
        with pytest.raises(ValidationError) as caught:
            make(**bad)
        assert SENTINEL not in str(caught.value)


def test_artifact_root_rules(tmp_path):
    assert make(artifact_root="runs").artifact_root == "runs"
    assert make(artifact_root="runs/sub/run-1")
    assert make(artifact_root=str(REPO / "runs" / "x"))
    assert make(artifact_root=str(tmp_path))
    for bad in ["src", "data", str(REPO), "docs/out", "runs/../src", "submission"]:
        with pytest.raises(ValidationError):
            make(artifact_root=bad)


def test_range_limits_and_unknown_fields():
    with pytest.raises(ValidationError):
        make(timeout_seconds=301)
    with pytest.raises(ValidationError):
        make(max_attempts=6)
    with pytest.raises(ValidationError):
        make(model_sha256="ABC")
    with pytest.raises(ValidationError):
        make(fixtures_dir="x")


def test_prompt_needs_placeholders(tmp_path):
    good = tmp_path / "good.md"
    good.write_text("{category} {setup} {sections} {{literal}}", encoding="utf-8")
    text, digest = load_prompt(make(prompt_path=str(good)))
    assert text.startswith("{category}")
    import hashlib

    assert digest == hashlib.sha256(good.read_bytes()).hexdigest()
    for missing in ("{category}", "{setup}", "{sections}"):
        bad = tmp_path / "bad.md"
        bad.write_text("{category} {setup} {sections}".replace(missing, ""), encoding="utf-8")
        with pytest.raises(ValueError, match="placeholder"):
            load_prompt(make(prompt_path=str(bad)))
    with pytest.raises(ValueError):
        load_prompt(make(prompt_path=str(tmp_path / "absent.md")))


def test_committed_prompt_formats_and_names_fields():
    text, digest = load_prompt(make())
    assert len(digest) == 64
    rendered = text.format(category="c", setup="k: v", sections="S")
    for field in (
        "question",
        "answer",
        "equipment_problem",
        "tools_required",
        "steps",
        "safety_info",
        "tips",
        "cited_section_ids",
    ):
        assert field in rendered


def test_escaped_placeholder_is_rejected(tmp_path):
    bad = tmp_path / "escaped.md"
    bad.write_text("{{category}} {setup} {sections}", encoding="utf-8")
    with pytest.raises(ValueError, match="placeholder"):
        load_prompt(make(prompt_path=str(bad)))


def test_paths_resolve_against_repository_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = make()
    assert config.artifact_path() == REPO / "runs"
    assert config.prompt_file() == REPO / "prompts" / "generator-v1.md"
    assert load_prompt(config)[0]
