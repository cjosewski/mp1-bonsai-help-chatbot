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

import errno
import hashlib
import importlib.metadata
import importlib.resources
import json
import platform
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

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
from bonsai_help.schemas import CitedSection, GeneratedItem, GenerationOutput, Quote
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
PROMPT_COPY = "prompt.md"
LEDGERS = (STARTS, ATTEMPTS, ITEMS)
# What the gate writes; its presence freezes the run (gate.REPORT).
GATE_FILES = ("gate-report.json",)
ASSESSED_PURPOSES = ("baseline", "corrected")
DEPENDENCIES = ("pydantic", "instructor", "openai", "httpx")
MIN_COUNT, MAX_COUNT, STEP = 5, 500, 5
DENOMINATOR = "all planned slots; a missing or unknown initial response is not a pass"


class ModelClient(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> AttemptResult: ...


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _package_dir() -> Path:
    return Path(str(importlib.resources.files(__package__)))


def implementation_identity(prompt_file: Path | None = None) -> dict:
    """SHA-256 of every package module, pyproject.toml, uv.lock and the prompt file.

    pyproject.toml and uv.lock must sit beside `src/` (a repository checkout); a missing
    one raises FileNotFoundError rather than leaving it out of the identity.
    """
    package = _package_dir()
    root = package.parents[1]
    project = [root / "pyproject.toml", root / "uv.lock"]
    for path in project:
        if not path.is_file():
            raise FileNotFoundError(
                errno.ENOENT,
                "missing; the implementation identity needs it beside src/ "
                "(run from the repository checkout)",
                str(path),
            )
    files = sorted(p for p in package.glob("*.py") if p.is_file()) + project
    hashes = {path.relative_to(root).as_posix(): _sha256(path.read_bytes()) for path in files}
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


def _offered_id(listed_id: str, offered_ids: set[str]) -> str:
    """The id a listed citation names: as listed, or without one pair of surrounding brackets.

    The prompt shows each offered section under its id in square brackets (`[id]`), so a
    model that copies the brackets still names that section. This is the only
    normalization: one leading `[` and one trailing `]` are removed, and only when the
    listed text is not itself an offered id and the result is one. Anything else (two pairs,
    unbalanced or other brackets, an id never offered) is returned unchanged and so stays
    unoffered.
    """
    if listed_id in offered_ids:
        return listed_id
    inner = listed_id[1:-1]
    if listed_id.startswith("[") and listed_id.endswith("]") and inner in offered_ids:
        return inner
    return listed_id


def _cited(offered: list[CitedSection], listed: list[str]) -> tuple[list[CitedSection], list]:
    """Offered sections the model listed, in offered order, and the listed ids not offered.

    Unoffered ids are reported exactly as the model listed them.
    """
    offered_ids = {s.id for s in offered}
    resolved = [_offered_id(i, offered_ids) for i in listed]
    wanted = set(resolved)
    unoffered = list(
        dict.fromkeys(raw for raw, i in zip(listed, resolved, strict=True) if i not in offered_ids)
    )
    return [s for s in offered if s.id in wanted], unoffered


split_citations = _cited  # public alias: (cited sections, unoffered ids)


def resolve_quotes(offered: list[CitedSection], listed: list[dict]) -> list[Quote]:
    """The envelope's quotes: each section id resolved as a citation, the text unchanged.

    `listed` is the attempt's `quotes`, as the model returned them. The section id goes
    through the same single bracket normalization as a cited id (`_offered_id`); an id
    that does not resolve is kept as listed, and the quote check then fails it.
    """
    offered_ids = {s.id for s in offered}
    return [
        Quote(section_id=_offered_id(q["section_id"], offered_ids), text=q["text"]) for q in listed
    ]


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
    *,
    prompt_sha256: str,
) -> None:
    """Require unchanged ledgers whose starts, attempts and items agree with the plan.

    `prompt_sha256` is the hash of the prompt the run is started or resumed with (bound
    by the fingerprint); the prompt copy and the manifest's unsealed `prompt_sha256`
    field must both match it, so editing the copy and that field together is refused.
    """
    recorded = manifest.get("artifacts_sha256", {})
    actual = artifact_hashes(directory)
    for name in LEDGERS:
        if name not in recorded or actual.get(name) != recorded[name]:
            raise ValueError(f"changed or missing {name}; preserve the run for inspection")
    if manifest.get("prompt_sha256") != prompt_sha256:
        raise ValueError(
            "manifest prompt_sha256 differs from the run's prompt; preserve the run for inspection"
        )
    prompt_copy = directory / PROMPT_COPY
    if not prompt_copy.is_file() or _sha256(prompt_copy.read_bytes()) != prompt_sha256:
        raise ValueError(f"changed or missing {PROMPT_COPY}; preserve the run for inspection")
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
            if any(record[key] != attempt[key] for key in _RECORD_KEYS) or (
                record["generated_at"] != attempt.get("completed_at")
            ):
                raise ValueError("successful record provenance differs from its attempt")
            offered = [CitedSection.model_validate(s) for s in record["offered_sections"]]
            cited, unoffered = _cited(offered, attempt.get("cited_section_ids") or [])
            if [s.model_dump(mode="json") for s in cited] != record["cited_sections"] or (
                unoffered != attempt.get("unoffered_citations")
            ):
                raise ValueError("recorded citations differ from the attempt's cited ids")
            if not quotes_match(offered, attempt.get("quotes"), record["quotes"]):
                raise ValueError("recorded quotes differ from the attempt's quotes")
            if per_slot[record["slot_id"]][-1]["attempt_id"] != record["attempt_id"]:
                raise ValueError(
                    f"a request start for {record['slot_id']} follows after its successful "
                    "completion"
                )
            successful[record["item_id"]] = record
        elif attempt.get("schema_valid") is not False or attempt.get("record") is not None:
            raise ValueError("failed attempt contains a successful record")
    seen: set[str] = set()
    for record in records:
        validated = GeneratedItem.model_validate(record).model_dump(mode="json")
        if validated["item_id"] in seen or successful.get(validated["item_id"]) != validated:
            raise ValueError("item differs from its successful attempt")
        seen.add(validated["item_id"])


def quotes_match(offered: list[CitedSection], listed: object, recorded: list[dict]) -> bool:
    """Whether an envelope's quotes are the ones resolved from the attempt's listed quotes."""
    if not isinstance(listed, list) or not all(
        isinstance(q, dict) and q.keys() == {"section_id", "text"} for q in listed
    ):
        return False
    try:
        resolved = resolve_quotes(offered, listed)
    except ValidationError:
        return False
    return [q.model_dump(mode="json") for q in resolved] == recorded


def check_count(count: object) -> None:
    """Refuse a slot count a run cannot plan: a multiple of STEP in [MIN_COUNT, MAX_COUNT]."""
    if type(count) is not int or not MIN_COUNT <= count <= MAX_COUNT or count % STEP:
        raise ValueError(f"count must be a multiple of {STEP} between {MIN_COUNT} and {MAX_COUNT}")


def check_assessed(config: RunConfig) -> None:
    """Refuse an assessed purpose that does not name the model it measures."""
    if config.purpose in ASSESSED_PURPOSES and not (config.model_identity and config.model_sha256):
        raise ValueError("assessed generation requires model_identity and model_sha256")


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
    check_count(count)
    check_assessed(config)
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
        with (directory / PROMPT_COPY).open("x", encoding="utf-8", newline="") as stream:
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
                manifest,
                directory,
                plan,
                expected,
                ledger.starts,
                ledger.attempts,
                ledger.records,
                prompt_sha256=prompt_sha256,
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
        except BaseException as error:
            if validated:
                manifest["status"] = "interrupted"
                try:
                    ledger.checkpoint()
                except Exception as failure:  # keep the original error; note this one
                    error.add_note(
                        f"the interrupted checkpoint also failed ({failure!r}); "
                        "preserve the run for inspection"
                    )
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


def _utf8_text(text: str) -> str:
    """The text as UTF-8 can store it: a lone surrogate is spelled as its escape."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _storable(raw: object) -> tuple[object, str | None]:
    """The raw response as it can be recorded, and why it had to be changed, if it did.

    A strict-JSON value that UTF-8 can encode is kept unchanged. Otherwise (NaN or
    Infinity, which an HTTP body can carry and `allow_nan=False` refuses; a lone UTF-16
    surrogate escape, which `response.json()` accepts and UTF-8 cannot encode; or a
    non-JSON value) it is kept as its JSON text, with non-finite numbers spelled out,
    lone surrogates as their escapes and other values as their repr. Raw text is kept
    as text. The client has already redacted it. Any Exception from the check (a custom
    client's mapping whose `items()` raises, say) takes the text path, so this never
    raises between a request start and its attempt record.
    """
    try:
        json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except Exception as exc:  # TypeError, ValueError (UnicodeEncodeError), RecursionError, ...
        if isinstance(raw, str):
            return _utf8_text(raw), str(exc)
        return _utf8_text(_spelled(raw)), str(exc)
    return raw, None


def _safe_repr(value: object) -> str:
    try:
        return repr(value)
    except Exception:
        return f"<unrepresentable {type(value).__name__}>"


def _spelled(raw: object) -> str:
    """The raw value as text; never raises, whatever a custom client returned.

    JSON text first (non-string keys, cycles, deep nesting or a mapping whose `items()`
    raises make it fail), then repr, then only the type's name.
    """
    try:
        return json.dumps(raw, ensure_ascii=False, allow_nan=True, default=_safe_repr)
    except Exception:  # whatever a custom value raises; RecursionError included
        pass
    try:
        return repr(raw)
    except Exception:  # RecursionError included
        return f"<unrepresentable {type(raw).__name__}>"


def _optional_text(value: str | None) -> str | None:
    return None if value is None else _utf8_text(value)


def _validation_summary(exc: ValidationError) -> str:
    """Field locations and messages only; input values are not repeated."""
    return "; ".join(
        f"{'.'.join(str(part) for part in e['loc']) or 'record'}: {e['msg']}"
        for e in exc.errors(include_url=False, include_input=False)
    )


def _complete(
    result: AttemptResult, config: RunConfig, start: dict, offered: list[CitedSection]
) -> dict:
    """The completion fields of an attempt record, including its envelope when valid.

    A completion that cannot be recorded as returned (raw response not strict JSON) or
    turned into an envelope is a failed attempt with its raw response kept, never an
    exception: the attempt is used up and the retry loop goes on.
    """
    completed_at = now()
    raw_response, unserializable = _storable(result.raw_response)
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
    if output is not None and unserializable is not None:
        output = None
        error = f"raw response is not strict JSON ({unserializable}); recorded as text"
        error_type = "UnserializableResponse"
    record = None
    listed = list(output.cited_section_ids) if output is not None else None
    quotes = [q.model_dump(mode="json") for q in output.quotes] if output is not None else None
    unoffered: list[str] = []
    if output is not None:
        cited, unoffered = _cited(offered, listed)
        # Not reported (None) falls back to the configured id; a reported id must be valid.
        model = result.response_model if result.response_model is not None else config.model
        try:
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
                model=model,
                sampler_seed=start["sampler_seed"],
                generated_at=completed_at,
                offered_sections=offered,
                cited_sections=cited,
                quotes=resolve_quotes(offered, quotes),
                item=output.item,
            ).model_dump(mode="json")
        except ValidationError as exc:
            error = f"envelope invalid: {_validation_summary(exc)}"
            error_type = "EnvelopeInvalid"
    return {
        "event": "attempt_completed",
        "completed_at": completed_at,
        "raw_response": raw_response,
        # Server-derived text; the item and cited ids passed strict unicode validation.
        "error": _optional_text(error),
        "error_type": _optional_text(error_type),
        "response_model": _optional_text(result.response_model),
        "schema_valid": record is not None,
        "cited_section_ids": listed,
        # The model's quotes as returned; the envelope holds them resolved.
        "quotes": quotes,
        "unoffered_citations": unoffered,
        "record": record,
        "verdict": "schema_valid" if record is not None else "generation_failed",
    }
