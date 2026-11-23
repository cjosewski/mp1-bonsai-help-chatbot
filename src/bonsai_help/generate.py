"""One-stage, docs-grounded generation with bounded, audited and resumable attempts.

Each slot of the plan gets seeded sections from the committed fixture slice, the setup
record of its profile and its category, rendered into the generator prompt. Every request
is recorded in `starts.jsonl` before the call; every completion, valid or not, in
`attempts.jsonl` with its raw response; every schema-valid result in `items.jsonl` as a
`GeneratedItem`. A start without a completion is an unknown outcome: it uses up its
attempt and is reported. A run is never overwritten; a resume must match the original
settings, prompt, code, inputs and count, and verifies the ledgers against the manifest.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.resources
import platform
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from bonsai_help.config import RunConfig
from bonsai_help.doc_sources import DocSources
from bonsai_help.model_client import AttemptResult
from bonsai_help.sampler import (
    MANIFEST,
    Slot,
    plan_slots,
    render_sections,
    sample_sections,
    verify_fixtures,
)
from bonsai_help.schemas import CitedSection, GeneratedItem, GenerationOutput
from bonsai_help.setup import SetupProfiles
from bonsai_help.tracing import (
    append_record,
    artifact_hashes,
    digest,
    exclusive,
    now,
    read_json,
    read_records,
    run_directory,
    write_checkpoint,
)

STARTS, ATTEMPTS, ITEMS = "starts.jsonl", "attempts.jsonl", "items.jsonl"
LEDGERS = (STARTS, ATTEMPTS, ITEMS)
GATE_FILES = ("gate-report.json", "gate-items.jsonl")
ASSESSED_PURPOSES = ("baseline", "corrected")
DEPENDENCIES = ("pydantic", "instructor", "openai", "httpx")
MIN_COUNT, MAX_COUNT, STEP = 5, 500, 5
DENOMINATOR = "all planned slots; a missing or unknown initial response is not a pass"


class ModelClient(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> AttemptResult: ...


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def implementation_identity(prompt_file: Path | None = None) -> dict:
    """SHA-256 of every package module, pyproject.toml, uv.lock and the prompt file."""
    package = Path(str(importlib.resources.files(__package__)))
    root = package.parents[1]
    files = sorted(package.glob("*.py")) + [root / "pyproject.toml", root / "uv.lock"]
    hashes = {
        path.relative_to(root).as_posix(): _sha256(path.read_bytes())
        for path in files
        if path.is_file()
    }
    if prompt_file is not None:
        hashes["prompt"] = _sha256(prompt_file.read_bytes())
    return {"source_files": hashes, "source_tree_sha256": digest(hashes)}


def render_setup(profiles: SetupProfiles, setup_id: str) -> str:
    """The setup record as `key: value` lines: profile, version line and its versions."""
    profile = next((p for p in profiles.profiles if p.id == setup_id), None)
    if profile is None:
        raise ValueError(f"unknown setup profile {setup_id!r}")
    line = next((v for v in profiles.version_lines if v.id == profile.version_line), None)
    if line is None:
        raise ValueError(f"{setup_id}: unknown version line {profile.version_line!r}")
    fields = {
        "id": profile.id,
        "version_line": line.id,
        "blender": line.blender,
        "bonsai": line.bonsai,
        "ifc_schema": profile.ifc_schema,
        "discipline": profile.discipline,
        "model_state": profile.model_state,
    }
    return "\n".join(f"{key}: {value}" for key, value in fields.items())


def messages_for(
    prompt: str, slot: Slot, setup: str, sections: str, number: int, max_attempts: int
) -> list[dict[str, str]]:
    """The exact request for one attempt; the prompt's placeholders are filled once."""
    try:
        system = prompt.format(category=slot.category, setup=setup, sections=sections)
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(
            "generator prompt has an unknown or malformed placeholder; "
            "only {category}, {setup} and {sections} are filled (escape other braces)"
        ) from exc
    user = (
        f"Write the item for slot {slot.slot_id}, attempt {number} of {max_attempts}. "
        "Reply with the JSON object only."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generation_metrics(
    starts: list[dict], attempts: list[dict], records: list[dict], slots: list[Slot]
) -> dict:
    """Initial-attempt validity over all planned slots, kept apart from retry recovery."""
    completed = {a["attempt_id"] for a in attempts}
    unknown = [s["attempt_id"] for s in starts if s["attempt_id"] not in completed]
    initial_valid = sum(1 for a in attempts if a["attempt_number"] == 1 and a["schema_valid"])
    done = {r["slot_id"] for r in records}
    exhausted = [s.slot_id for s in slots if s.slot_id not in done]
    return {
        "initial_slots": len(slots),
        "initial_valid": initial_valid,
        "initial_validity": initial_valid / len(slots) if slots else None,
        "initial_denominator": DENOMINATOR,
        "retry_recovered": sum(
            1 for a in attempts if a["schema_valid"] and a["attempt_number"] > 1
        ),
        "exhausted": len(exhausted),
        "exhausted_slot_ids": exhausted,
        "unknown_outcomes": len(unknown),
        "unknown_attempt_ids": unknown,
        "started_attempts": len(starts),
        "completed_attempts": len(attempts),
        "items": len(records),
    }


def _plan(
    config: RunConfig,
    count: int,
    profiles: SetupProfiles,
    doc_config: DocSources,
    fixtures_dir: Path,
) -> list[dict]:
    """Every slot with its offered sections and rendered context; no model call, no write."""
    planned = []
    for slot in plan_slots(profiles, config.split, count):
        offered = sample_sections(
            slot, config.seed, config=doc_config, profiles=profiles, fixtures_dir=fixtures_dir
        )
        setup = render_setup(profiles, slot.setup_id)
        sections = render_sections(offered, fixtures_dir)
        planned.append({"slot": slot, "offered": offered, "setup": setup, "sections": sections})
    return planned


def _cited(offered: list[CitedSection], listed: list[str]) -> tuple[list[CitedSection], list]:
    """Offered sections the model listed, in offered order, and the listed ids not offered."""
    wanted = set(listed)
    offered_ids = {s.id for s in offered}
    unoffered = list(dict.fromkeys(i for i in listed if i not in offered_ids))
    return [s for s in offered if s.id in wanted], unoffered


split_citations = _cited  # public alias: (cited sections, unoffered ids)


def _expected_start(
    run_id: str, config: RunConfig, prompt: str, prompt_sha256: str, entry: dict, number: int
) -> dict:
    slot = entry["slot"]
    return {
        "run_id": run_id,
        "item_id": f"{run_id}-{slot.slot_id}",
        "attempt_number": number,
        "category": slot.category,
        "setup_id": slot.setup_id,
        "version_line": slot.version_line,
        "step": "generate",
        "model": config.model,
        "prompt_variant": config.prompt_variant,
        "prompt_hash": prompt_sha256,
        "sampler_seed": config.seed,
        "offered_sections": [s.model_dump(mode="json") for s in entry["offered"]],
        "input": messages_for(
            prompt, slot, entry["setup"], entry["sections"], number, config.max_attempts
        ),
    }


_RECORD_KEYS = (
    "run_id",
    "trace_id",
    "item_id",
    "attempt_id",
    "parent_attempt_id",
    "slot_id",
    "category",
    "setup_id",
    "version_line",
    "prompt_variant",
    "prompt_hash",
    "sampler_seed",
    "offered_sections",
)


def validate_evidence(
    manifest: dict,
    directory: Path,
    plan: dict[str, dict],
    expected: Callable[[dict, int], dict],
    starts: list[dict],
    attempts: list[dict],
    records: list[dict],
) -> None:
    """Require unchanged ledgers whose starts, attempts and items agree with the plan."""
    recorded = manifest.get("artifacts_sha256", {})
    actual = artifact_hashes(directory)
    for name in LEDGERS:
        if name not in recorded or actual.get(name) != recorded[name]:
            raise ValueError(f"changed or missing {name}; preserve the run for inspection")
    by_id: dict[str, dict] = {}
    per_slot: dict[str, list[dict]] = {}
    for start in starts:
        slot_id = start.get("slot_id")
        if slot_id not in plan or start.get("attempt_id") in by_id:
            raise ValueError("unknown slot or duplicate attempt identity in starts.jsonl")
        previous = per_slot.setdefault(slot_id, [])
        number = start.get("attempt_number")
        if type(number) is not int or not 1 <= number <= manifest["settings"]["max_attempts"]:
            raise ValueError("persisted retry budget is inconsistent")
        want = expected(plan[slot_id], number)
        if any(start.get(key) != value for key, value in want.items()):
            raise ValueError(f"persisted start for {slot_id} differs from its plan")
        if number != len(previous) + 1:
            raise ValueError("persisted retry budget is inconsistent")
        if start.get("parent_attempt_id") != (previous[-1]["attempt_id"] if previous else None):
            raise ValueError("persisted retry lineage is inconsistent")
        if previous and start.get("trace_id") != previous[0]["trace_id"]:
            raise ValueError("trace identity changed within a slot")
        by_id[start["attempt_id"]] = start
        previous.append(start)
    completed: set[str] = set()
    successful: dict[str, dict] = {}
    for attempt in attempts:
        start = by_id.get(attempt.get("attempt_id"))
        if start is None or attempt["attempt_id"] in completed:
            raise ValueError("completion is missing its unique request start")
        if any(attempt.get(k) != v for k, v in start.items() if k != "event"):
            raise ValueError("completion differs from its request start")
        completed.add(attempt["attempt_id"])
        if attempt.get("schema_valid") is True:
            record = GeneratedItem.model_validate(attempt["record"]).model_dump(mode="json")
            if record != attempt["record"]:
                raise ValueError("successful attempt holds a non-canonical record")
            if record["item_id"] in successful:
                raise ValueError("multiple successful completions for one slot")
            if any(record[key] != attempt[key] for key in _RECORD_KEYS):
                raise ValueError("successful record provenance differs from its attempt")
            offered = [CitedSection.model_validate(s) for s in record["offered_sections"]]
            cited, unoffered = _cited(offered, attempt.get("cited_section_ids") or [])
            if [s.model_dump(mode="json") for s in cited] != record["cited_sections"] or (
                unoffered != attempt.get("unoffered_citations")
            ):
                raise ValueError("recorded citations differ from the attempt's cited ids")
            successful[record["item_id"]] = record
        elif attempt.get("schema_valid") is not False or attempt.get("record") is not None:
            raise ValueError("failed attempt contains a successful record")
    seen: set[str] = set()
    for record in records:
        validated = GeneratedItem.model_validate(record).model_dump(mode="json")
        if validated["item_id"] in seen or successful.get(validated["item_id"]) != validated:
            raise ValueError("item differs from its successful attempt")
        seen.add(validated["item_id"])


def _check_count(count: object) -> None:
    if type(count) is not int or not MIN_COUNT <= count <= MAX_COUNT or count % STEP:
        raise ValueError(f"count must be a multiple of {STEP} between {MIN_COUNT} and {MAX_COUNT}")


def generate_run(
    config: RunConfig,
    prompt: str,
    prompt_sha256: str,
    *,
    count: int,
    run_id: str,
    client: ModelClient,
    profiles: SetupProfiles,
    doc_config: DocSources,
    fixtures_dir: Path,
    resume: bool = False,
) -> dict:
    """Generate `count` slots (or resume them); return the final manifest.

    Exhausted slots leave the run `incomplete` (the CLI maps that to exit 3). An
    interruption leaves it `interrupted` with every started request on record.
    """
    _check_count(count)
    if config.purpose in ASSESSED_PURPOSES and not (config.model_identity and config.model_sha256):
        raise ValueError("assessed generation requires model_identity and model_sha256")
    if _sha256(prompt.encode("utf-8")) != prompt_sha256:
        raise ValueError("prompt_sha256 does not match the prompt text")
    directory = run_directory(config.artifact_path(), run_id)
    # Fixtures are verified, and every slot sampled and rendered, before anything is written.
    verify_fixtures(doc_config, fixtures_dir)
    entries = _plan(config, count, profiles, doc_config, fixtures_dir)
    for entry in entries:  # a malformed prompt refuses here, not after the first start
        messages_for(prompt, entry["slot"], entry["setup"], entry["sections"], 1, 1)
    plan = {entry["slot"].slot_id: entry for entry in entries}
    slots = [entry["slot"] for entry in entries]
    if _sha256(config.prompt_file().read_bytes()) != prompt_sha256:
        raise ValueError("the prompt file changed after it was loaded")
    identity = implementation_identity(config.prompt_file())
    inputs = {
        "setup_profiles_sha256": digest(profiles.model_dump(mode="json", by_alias=True)),
        "doc_sources_sha256": digest(doc_config.model_dump(mode="json")),
        "doc_manifest_sha256": _sha256(MANIFEST.read_bytes()),
        "offered_sections_sha256": digest(
            {e["slot"].slot_id: [s.model_dump(mode="json") for s in e["offered"]] for e in entries}
        ),
    }
    fingerprint = digest(
        {
            "settings": config.public_settings(),
            "prompt_sha256": prompt_sha256,
            "count": count,
            "implementation": identity["source_tree_sha256"],
            "inputs": inputs,
        }
    )

    def expected(entry: dict, number: int) -> dict:
        return _expected_start(run_id, config, prompt, prompt_sha256, entry, number)

    if resume:
        try:
            manifest = read_json(directory / "manifest.json")
        except FileNotFoundError:
            raise ValueError(f"no run {run_id!r} to resume") from None
        if manifest.get("fingerprint") != fingerprint or manifest.get("run_id") != run_id:
            raise ValueError(
                "resume requires the original settings, prompt, code, inputs and count"
            )
        if manifest.get("status") == "complete":
            raise ValueError("complete runs are immutable; choose a new run ID")
    else:
        directory.mkdir(parents=True, exist_ok=False)
        for name in LEDGERS:
            (directory / name).touch(exist_ok=False)
        with (directory / "prompt.md").open("x", encoding="utf-8", newline="") as stream:
            stream.write(prompt)
        manifest = {
            "schema_version": "1",
            "run_id": run_id,
            "purpose": config.purpose,
            "status": "running",
            "created_at": now(),
            "count": count,
            "fingerprint": fingerprint,
            "settings": config.public_settings(),
            "prompt_sha256": prompt_sha256,
            "implementation": identity,
            "inputs": inputs,
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "category": s.category,
                    "setup_id": s.setup_id,
                    "version_line": s.version_line,
                }
                for s in slots
            ],
            "python_version": platform.python_version(),
            "dependencies": {name: importlib.metadata.version(name) for name in DEPENDENCIES},
            "course_acceptance": "not_evaluated",
            "artifacts_sha256": artifact_hashes(directory),
        }
        write_checkpoint(directory / "manifest.json", manifest)

    ledger = _Ledger(directory, manifest)
    with exclusive(directory / ".generation.lock"):
        validated = False
        try:
            if any((directory / name).exists() for name in GATE_FILES):
                raise ValueError("gated runs are frozen; choose a new run ID")
            ledger.starts = read_records(directory / STARTS)
            ledger.attempts = read_records(directory / ATTEMPTS)
            ledger.records = read_records(directory / ITEMS)
            validate_evidence(
                manifest, directory, plan, expected, ledger.starts, ledger.attempts, ledger.records
            )
            validated = True
            ledger.recover_items()
            manifest["status"] = "running"
            ledger.checkpoint()
            for entry in entries:
                ledger.run_slot(entry, config, run_id, client, expected)
            manifest["metrics"] = generation_metrics(
                ledger.starts, ledger.attempts, ledger.records, slots
            )
            manifest["status"] = "complete" if len(ledger.records) == len(slots) else "incomplete"
            ledger.checkpoint()
            return manifest
        except BaseException:
            if validated:
                manifest["status"] = "interrupted"
                ledger.checkpoint()
            raise


@dataclass
class _Ledger:
    """The run's append-only ledgers in memory, mirrored to disk record by record."""

    directory: Path
    manifest: dict
    starts: list[dict] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)

    def checkpoint(self) -> None:
        self.manifest["artifacts_sha256"] = artifact_hashes(self.directory)
        self.manifest["updated_at"] = now()
        write_checkpoint(self.directory / "manifest.json", self.manifest)

    def _append(self, name: str, records: list[dict], record: dict) -> None:
        append_record(self.directory / name, record)
        records.append(record)

    def done(self) -> set[str]:
        return {record["item_id"] for record in self.records}

    def recover_items(self) -> None:
        """A completion can survive an interruption that came before its item was appended."""
        for attempt in self.attempts:
            if attempt["schema_valid"] and attempt["record"]["item_id"] not in self.done():
                self._append(ITEMS, self.records, attempt["record"])

    def run_slot(
        self,
        entry: dict,
        config: RunConfig,
        run_id: str,
        client: ModelClient,
        expected: Callable[[dict, int], dict],
    ) -> None:
        slot: Slot = entry["slot"]
        if f"{run_id}-{slot.slot_id}" in self.done():
            return
        previous = [s for s in self.starts if s["slot_id"] == slot.slot_id]
        trace_id = previous[0]["trace_id"] if previous else str(uuid.uuid4())
        parent_attempt_id = previous[-1]["attempt_id"] if previous else None
        # A start without a completion (unknown outcome) has used up its attempt.
        for number in range(len(previous) + 1, config.max_attempts + 1):
            attempt_id = str(uuid.uuid4())
            start = {
                "event": "attempt_started",
                "timestamp": now(),
                "slot_id": slot.slot_id,
                "trace_id": trace_id,
                "attempt_id": attempt_id,
                "parent_attempt_id": parent_attempt_id,
            } | expected(entry, number)
            self._append(STARTS, self.starts, start)
            self.checkpoint()
            result = client.generate(start["input"])
            attempt = start | _complete(result, config, start, entry["offered"])
            self._append(ATTEMPTS, self.attempts, attempt)
            parent_attempt_id = attempt_id
            if attempt["record"] is not None:
                self._append(ITEMS, self.records, attempt["record"])
                self.checkpoint()
                return
            self.checkpoint()


def _complete(
    result: AttemptResult, config: RunConfig, start: dict, offered: list[CitedSection]
) -> dict:
    """The completion fields of an attempt record, including its envelope when valid."""
    error, error_type = result.error, result.error_type
    output = result.item
    if output is not None and not isinstance(output, GenerationOutput):
        output, error, error_type = None, "unexpected response model", "UnexpectedResponseModel"
    if (
        output is not None
        and config.purpose in ASSESSED_PURPOSES
        and result.response_model != config.model
    ):
        output = None
        error = "reported generator model differs from the configured model"
        error_type = "ModelIdentityMismatch"
    record = None
    listed = list(output.cited_section_ids) if output is not None else None
    unoffered: list[str] = []
    if output is not None:
        cited, unoffered = _cited(offered, listed)
        record = GeneratedItem(
            run_id=start["run_id"],
            trace_id=start["trace_id"],
            item_id=start["item_id"],
            attempt_id=start["attempt_id"],
            parent_attempt_id=start["parent_attempt_id"],
            slot_id=start["slot_id"],
            category=start["category"],
            setup_id=start["setup_id"],
            version_line=start["version_line"],
            prompt_variant=start["prompt_variant"],
            prompt_hash=start["prompt_hash"],
            model=result.response_model or config.model,
            sampler_seed=start["sampler_seed"],
            offered_sections=offered,
            cited_sections=cited,
            item=output.item,
        ).model_dump(mode="json")
    return {
        "event": "attempt_completed",
        "completed_at": now(),
        "raw_response": result.raw_response,
        "error": error,
        "error_type": error_type,
        "response_model": result.response_model,
        "schema_valid": record is not None,
        "cited_section_ids": listed,
        "unoffered_citations": unoffered,
        "record": record,
        "verdict": "schema_valid" if record is not None else "generation_failed",
    }
