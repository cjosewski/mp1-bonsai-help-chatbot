"""Synthetic ready collections, frozen cohorts and rubrics for the evaluation stages.

Everything here is clearly synthetic: a scripted fake model (no endpoint is called), items
built from the committed fixture slice, and sentinel run, model, prompt, collection and
cohort ids that a blind display must never show. It is never model evidence and never
submitted. No label is written here.

The collections are built once per test session into a template root and copied into each
test's `tmp_path`, so every test gets its own untouched evidence.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from fakes import grounded_quotes
from test_gate import FakeEmbedder, good_item
from test_generation import offered_ids

from bonsai_help import cohort, collection
from bonsai_help.config import RunConfig
from bonsai_help.doc_sources import load_config
from bonsai_help.model_client import AttemptResult
from bonsai_help.schemas import GenerationOutput
from bonsai_help.setup import SetupProfiles

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/docs"
REFERENCE = REPO / "reference"
RUBRIC = REPO / "config/rubric.json"
PROMPT = REPO / "prompts/generator-v1.1.md"
SYNTHETIC_ACCEPTANCE = "synthetic test acceptance, not Chad's"
# 50 slots in one batch give exactly 10 retained items per category: the whole cohort.
BATCH = 50


@dataclass(frozen=True)
class Source:
    """One synthetic collection and the cohort frozen from it."""

    key: str
    collection_id: str
    cohort_id: str
    purpose: str
    prompt_variant: str
    split: str
    model: str
    model_identity: str
    model_sha256: str


SOURCES = {
    s.key: s
    for s in (
        Source(
            "baseline",
            "sentinel-col-baseline-zq1",
            "sentinel-cohort-baseline-zq1",
            "baseline",
            "baseline",
            "assessed",
            "sentinel-model-baseline-zq1",
            "sentinel-identity-baseline-zq1",
            "1" * 64,
        ),
        Source(
            "corrected",
            "sentinel-col-corrected-zq2",
            "sentinel-cohort-corrected-zq2",
            "corrected",
            "corrected",
            "assessed",
            "sentinel-model-corrected-zq2",
            "sentinel-identity-corrected-zq2",
            "2" * 64,
        ),
        Source(
            "development",
            "sentinel-col-development-zq3",
            "sentinel-cohort-development-zq3",
            "baseline",
            "baseline",
            "development",
            "sentinel-model-development-zq3",
            "sentinel-identity-development-zq3",
            "3" * 64,
        ),
        Source(
            "baseline2",
            "sentinel-col-baseline2-zq4",
            "sentinel-cohort-baseline2-zq4",
            "baseline",
            "baseline",
            "assessed",
            "sentinel-model-baseline2-zq4",
            "sentinel-identity-baseline2-zq4",
            "4" * 64,
        ),
        Source(
            "smoke",
            "sentinel-col-smoke-zq5",
            "sentinel-cohort-smoke-zq5",
            "smoke",
            "baseline",
            "assessed",
            "sentinel-model-smoke-zq5",
            "sentinel-identity-smoke-zq5",
            "5" * 64,
        ),
        Source(
            "mismatch",
            "sentinel-col-mismatch-zq6",
            "sentinel-cohort-mismatch-zq6",
            "corrected",
            "baseline",
            "assessed",
            "sentinel-model-mismatch-zq6",
            "sentinel-identity-mismatch-zq6",
            "6" * 64,
        ),
    )
}


class SentinelClient:
    """Synthetic model: a distinct, check-passing item per call; reports a sentinel model."""

    def __init__(self, key: str, model: str) -> None:
        self.key = key
        self.model = model
        self.calls = 0

    def generate(self, messages):
        self.calls += 1
        slot = re.search(r"slot (\S+), attempt", messages[-1]["content"])[1]
        cited = offered_ids(messages)[:1]
        body = {
            "item": good_item(self.calls)
            | {"question": f"How do I add synthetic {self.key} wall {self.calls} for {slot}?"},
            "cited_section_ids": cited,
            "quotes": grounded_quotes(cited),
        }
        output = GenerationOutput.model_validate(body)
        # An assessed run refuses a reply whose reported model is not the configured one.
        return AttemptResult(output, {"synthetic": True}, None, None, self.model)


def _build(root: Path, prompts: Path, source: Source) -> None:
    prompt = prompts / f"prompt-{source.key}.md"
    prompt.write_text(
        PROMPT.read_text(encoding="utf-8") + f"\n<!-- synthetic sentinel prompt {source.key} -->\n",
        encoding="utf-8",
    )
    config = RunConfig.model_validate(
        {
            "base_url": "http://127.0.0.1:8080/v1",
            "model": source.model,
            "model_identity": source.model_identity,
            "model_sha256": source.model_sha256,
            "embedding_model": "synthetic-embedding",
            "purpose": source.purpose,
            "prompt_variant": source.prompt_variant,
            "split": source.split,
            "prompt_path": str(prompt),
            "seed": 11,
            "artifact_root": str(root),
        }
    )
    summary = collection.collect(
        config,
        source.collection_id,
        SentinelClient(source.key, source.model),
        FakeEmbedder(),
        target_retained=BATCH,
        batch_count=BATCH,
        max_batches=1,
        fixtures_dir=FIXTURES,
        reference_dir=REFERENCE,
    )
    if summary["status"] != "ready":
        raise RuntimeError(f"synthetic collection {source.key} is not ready: {summary['reasons']}")
    cohort.freeze_cohort(root, source.collection_id, source.cohort_id)


_TEMPLATE: dict[str, Path] = {}


def template_root(factory) -> Path:
    """The session's template artifact root, built on first use; never modify it."""
    if "root" not in _TEMPLATE:
        base = factory.mktemp("evaluation-template")
        root = base / "runs"
        prompts = base / "prompts"
        root.mkdir()
        prompts.mkdir()
        for source in SOURCES.values():
            _build(root, prompts, source)
        _TEMPLATE["root"] = root
    return _TEMPLATE["root"]


def fresh_root(tmp_path: Path, factory) -> Path:
    """A private copy of the template root under `tmp_path`."""
    target = tmp_path / "runs"
    shutil.copytree(template_root(factory), target, symlinks=True)
    return target


def write_rubric(directory: Path, *, status: str = "chad_accepted", name: str = "rubric.json"):
    """A rubric file derived from the committed one, with a synthetic status and review.

    `chad_accepted` here carries the synthetic acceptance words, never Chad's own.
    """
    data = json.loads(RUBRIC.read_text(encoding="utf-8"))
    data["status"] = status
    if status == "chad_accepted":
        data["review"] = {
            "decided_on": "2026-11-24",
            "words": SYNTHETIC_ACCEPTANCE,
            "decisions_entry": "synthetic test entry",
        }
    else:
        data.pop("review", None)
    path = directory / name
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def profiles() -> SetupProfiles:
    return SetupProfiles.model_validate(
        json.loads((REFERENCE / "setup-profiles.json").read_bytes())
    )


def doc_config():
    return load_config(REPO / "config/doc-sources.json")


def provenance_sentinels(root: Path) -> set[str]:
    """Every provenance string a blind display or blind status must never contain."""
    found: set[str] = set()
    for source in SOURCES.values():
        found |= {
            source.collection_id,
            source.cohort_id,
            source.model,
            source.model_identity,
            source.model_sha256,
        }
        path = root / "cohorts" / source.cohort_id / "cohort.json"
        if not path.exists():
            continue
        frozen = json.loads(path.read_text(encoding="utf-8"))
        for item in frozen["items"]:
            found |= {
                item["item_id"],
                item["run_id"],
                item["attempt_id"],
                item["prompt_hash"],
                item["model"],
                item["generated_at"],
            }
    return found
