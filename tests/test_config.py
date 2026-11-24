import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from bonsai_help import cli
from bonsai_help import config as config_module
from bonsai_help.config import HostedRefused, RunConfig, load_config, load_prompt
from bonsai_help.doc_sources import ConfigError

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
        # Addresses Python calls "private" that are not a local model host.
        "http://[2002:808:808::1]/v1",  # 6to4 relay to 8.8.8.8
        "http://[2001::1]/v1",  # Teredo
        "http://[64:ff9b::808:808]/v1",  # NAT64 to 8.8.8.8
        "http://[::ffff:8.8.8.8]/v1",  # IPv4-mapped public address
        "http://169.254.169.254/v1",  # link-local, cloud metadata
        "http://[fe80::1]/v1",  # IPv6 link-local
        "http://192.0.2.1/v1",  # documentation range
        "http://198.18.0.1/v1",  # benchmarking range
        "http://100.64.0.1/v1",  # shared address space (CGNAT)
        "http://172.32.0.1/v1",  # just outside 172.16.0.0/12
        "http://0.0.0.0/v1",
        "http://[::]/v1",
        "http://localhost.example.com/v1",
    ],
)
def test_local_endpoint_rules(url):
    with pytest.raises(ValidationError):
        make(base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:9/v1/",
        "http://127.0.0.2:8080/v1",
        "http://[::1]:8080/v1",
        "http://10.0.0.5/v1",
        "http://172.16.0.1/v1",
        "http://172.31.255.254/v1",
        "http://192.168.1.5:8080/v1",
        "http://[fd12:3456::1]/v1",  # IPv6 unique local
        "http://[::ffff:192.168.1.5]/v1",  # IPv4-mapped private address
        "http://[::ffff:127.0.0.1]/v1",  # IPv4-mapped loopback
    ],
)
def test_local_and_private_endpoints_accepted(url):
    assert make(base_url=url).base_url == url.rstrip("/")


def test_hosted_url_without_hosted_flag_is_refused():
    for url in ("https://api.example.com/v1", "http://api.example.com/v1"):
        with pytest.raises(ValidationError):
            make(base_url=url)


@pytest.mark.parametrize(
    "hosted",
    [
        # Even a fully specified hosted profile is refused: the cap is not enforced.
        {"hosted_authorization": "synthetic note", "cost_cap_usd": 5},
        {"hosted_authorization": "synthetic note", "cost_cap_usd": 1e-9},
        {},
        {"base_url": "http://api.example.com/v1"},
        {"base_url": "http://127.0.0.1:8080/v1"},
    ],
)
def test_hosted_true_is_refused_at_load(hosted):
    values = {"base_url": "https://api.example.com/v1", "hosted": True} | hosted
    with pytest.raises(HostedRefused) as caught:
        make(**values)
    message = str(caught.value)
    assert "not implemented" in message and "cost cap" in message and "Chad" in message
    assert isinstance(caught.value, ConfigError) and caught.value.exit_code == 2


def test_hosted_fields_stay_in_the_schema():
    assert {"hosted", "hosted_authorization", "cost_cap_usd"} <= set(RunConfig.model_fields)
    local = make(hosted=False, hosted_authorization="synthetic note", cost_cap_usd=5)
    assert local.hosted is False
    assert local.public_settings()["cost_cap_usd"] == 5


def test_hosted_config_file_is_refused_by_load_and_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BONSAI_HELP_API_KEY", SENTINEL)
    path = tmp_path / "hosted.json"
    path.write_text(
        json.dumps(
            {
                "base_url": "https://api.example.com/v1",
                "model": "synthetic-model",
                "embedding_model": "synthetic-embed",
                "seed": 1,
                "artifact_root": str(tmp_path / "runs"),
                "hosted": True,
                "hosted_authorization": "synthetic note",
                "cost_cap_usd": 5,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(HostedRefused):
        load_config(path)

    def no_request(request):
        pytest.fail("a refused hosted config must make no request")

    transport = httpx.MockTransport(no_request)
    code = cli.main(["generate", "--config", str(path), "--run-id", "h1"], transport=transport)
    out, err = capsys.readouterr()
    assert code == 2
    assert err.startswith("error:") and "hosted" in err and "not implemented" in err
    assert "Traceback" not in err and SENTINEL not in out + err
    assert not (tmp_path / "runs").exists()


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
        {"api_key_env": SENTINEL},
        {"api_key_env": SENTINEL, "api_key_file": SENTINEL},
    ):
        with pytest.raises(ValidationError) as caught:
            make(**bad)
        assert SENTINEL not in str(caught.value)


@pytest.mark.parametrize(
    "pasted",
    [
        SENTINEL,
        "sk-proj-AbCdEf0123456789XYZ",
        "synthetickeyvalue0123456789",  # lower case: a value, not a variable name
        "Bearer SYNTHETIC0123456789",
        "SYNTHETIC0123456789SYNTHETIC0123456789SYNTHETIC0123456789SYNTHETIC0",  # > 64
        "0SYNTHETIC",
    ],
)
def test_pasted_key_in_api_key_env_is_rejected_at_load(pasted, tmp_path, capsys):
    with pytest.raises(ValidationError) as caught:
        make(api_key_env=pasted)
    # Pydantic keeps the input in errors() unless include_input=False; every
    # rendered form (str, repr, the CLI message) must leave it out.
    errors = caught.value.errors(include_input=False)
    assert [e["loc"] for e in errors] == [("api_key_env",)]
    assert "environment variable" in errors[0]["msg"]
    for text in (str(caught.value), repr(caught.value), json.dumps(errors, default=str)):
        assert pasted not in text

    path = tmp_path / "pasted.json"
    path.write_text(
        json.dumps(
            {
                "base_url": "http://127.0.0.1:8080/v1",
                "model": "synthetic-model",
                "embedding_model": "synthetic-embed",
                "seed": 1,
                "artifact_root": str(tmp_path / "runs"),
                "api_key_env": pasted,
            }
        ),
        encoding="utf-8",
    )
    transport = httpx.MockTransport(lambda request: pytest.fail("no request expected"))
    code = cli.main(["generate", "--config", str(path), "--run-id", "p1"], transport=transport)
    out, err = capsys.readouterr()
    assert code == 2 and "api_key_env" in err
    assert pasted not in out + err


@pytest.mark.parametrize("name", ["BONSAI_HELP_API_KEY", "_X", "X1", "A" * 64])
def test_environment_variable_names_are_accepted(name):
    assert make(api_key_env=name).api_key_env == name


@pytest.mark.parametrize("short", ["tip", "none", "x", "local-key-0123"])
def test_short_api_key_is_refused_without_echoing_it(short, tmp_path, monkeypatch):
    monkeypatch.setenv("BONSAI_HELP_API_KEY", short)
    with pytest.raises(ValueError, match="at least 16 characters") as caught:
        make().api_key()
    assert short not in str(caught.value)
    key = tmp_path / "key"
    key.write_text(short + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="at least 16 characters") as caught:
        make(api_key_env=None, api_key_file=str(key)).api_key()
    assert short not in str(caught.value)


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
        "quotes",
        "section_id",
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
