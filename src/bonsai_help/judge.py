"""The blind, bounded and audited LLM judge (MP1 Step 4; B7 Decisions 4 to 9 and 13).

A judge run scores every item of one assessment on D1 to D6 with a local model and the
prompt `judge_config.load_judge_prompt` loads. It lives at
`<assessment dir>/judges/<judge_run_id>/` (`human_reference.JUDGES`, the directory whose
presence makes B6's freeze refuse) and holds:

- `manifest.json`: the identity, its fingerprint, the status and the ledger hashes,
  checkpointed atomically and written last at creation;
- `prompt.md`: a copy of the prompt;
- `starts.jsonl`: a durable start record written before each call, holding the exact
  messages and, for judge v2, the selected `example_ids`; `attempts.jsonl`: every
  completion, valid or not, with its raw response;
- for judge v2 only, `examples.json`: a copy of the example pool, every judged item's
  vector and the selection (`judge_examples.select_examples`), written at creation before
  any chat call and pinned by SHA-256 in the identity.

**Blind inputs.** The judge sees each item's category, setup record, seven fields, the
model's quotes, the full text of its cited sections (re-derived by `sampler.section_texts`
from the hash-verified fixture slice) and the deterministic check results the gate recorded
(`collection.batch_recorded_checks`, from the verified gate report). The key
(`assessment.load_key`) is read only to find each item's batch and gate record; nothing from
it, and no run, item or trace id, arm, prompt variant or hash, generator model, time,
collection or cohort id, human label or other judge output reaches a message. All item,
quote, section and check text is in fenced blocks (`render_inputs`).

**No judge evidence before frozen labels.** A `measured` run loads the frozen human
reference (`human_reference.load_reference`) and validates its qualification receipt
before any directory is created or any call is made. A `smoke` run (diagnostic only, never
calibration) is refused on an `arm` assessment and on any assessment with labels; once it
exists, B6's freeze refuses that assessment.

**Attempts.** Each item gets at most `max_attempts`. A start without a completion is an
unknown outcome: it uses up its attempt and is reported. A reply that reports a model other
than the configured judge model is an attempt failure (`ModelIdentityMismatch`). An item
whose attempts are used up without a valid judgment leaves the run `incomplete` (the CLI
maps that to exit 3). A resume needs the original identity (settings, prompt, code,
assessment, inputs, reference and qualification) and gives exhausted items nothing more; a
complete run is immutable. An assessment allows at most `MEASURED_RUNS_PER_ASSESSMENT`
measured runs.

**The frozen judge.** `frozen_identity` pins what can change the text the judge sees or how
its reply is parsed: the public settings, the prompt, the example pool (v2), the SHA-256 of
every module in `FROZEN_JUDGE_MODULES`, the installed and locked versions of
`MESSAGE_PATH_DISTRIBUTIONS`, the `Judgment` schema and the request Instructor prepares for
the configured mode. `render_path_closure` follows every package import from the judge's
modules; each module it reaches must be frozen or exempt with a reason
(`RENDER_PATH_EXEMPT`), or `frozen_identity` refuses.

Nothing here calls a model endpoint except through the client a caller passes in.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import importlib.resources
import json
import os
import re
import tomllib
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import ValidationError

from bonsai_help import (
    collection,
    generate,
    human_reference,
    judge_examples,
    qualification,
    sampler,
)
from bonsai_help.assessment import (
    Assessment,
    AssessmentError,
    BlindItem,
    SetupRecord,
    load_assessment,
    load_key,
)
from bonsai_help.config import REPOSITORY
from bonsai_help.display import escape_control, section_heading
from bonsai_help.doc_sources import load_config
from bonsai_help.evaluation_schemas import DIMENSIONS, Judgment
from bonsai_help.judge_config import JudgeConfig, load_judge_prompt
from bonsai_help.model_client import AttemptResult, InstructorClient
from bonsai_help.qualification import QualificationError
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

PACKAGE = "bonsai_help"
JUDGES = human_reference.JUDGES
STARTS, ATTEMPTS = "starts.jsonl", "attempts.jsonl"
LEDGERS = (STARTS, ATTEMPTS)
PROMPT_COPY = "prompt.md"
EXAMPLES = "examples.json"
MANIFEST = "manifest.json"
LOCK = ".judge.lock"
CREATE_LOCK = ".create.lock"
STATUSES = ("running", "complete", "incomplete", "interrupted")
MEASURED_RUNS_PER_ASSESSMENT = 3
FENCE_DOMAIN = "bonsai-judge-fence-v1"
FENCE_LENGTH = 16
BLOCK_NAMES = ("ITEM", "QUOTES", "SECTION", "CHECKS")
USER_MESSAGE = (
    "Judge the item above, attempt {number} of {max_attempts}. Reply with the JSON object only."
)
INSPECT = "preserve the judge run for inspection; nothing was repaired"
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "judge_run_id",
        "assessment_id",
        "purpose",
        "status",
        "created_at",
        "updated_at",
        "identity",
        "fingerprint",
        "artifacts_sha256",
    }
)
START_FIELDS = frozenset(
    {
        "event",
        "judge_run_id",
        "blind_id",
        "attempt_id",
        "attempt_number",
        "parent_attempt_id",
        "started_at",
        "example_ids",
        "input",
        "messages_sha256",
    }
)
EXAMPLES_FIELDS = frozenset(
    {"schema_version", "pool_id", "examples_k", "pool", "vectors", "selection"}
)
COMPLETION_FIELDS = frozenset(
    {
        "completed_at",
        "raw_response",
        "error",
        "error_type",
        "response_model",
        "valid",
        "judgment",
    }
)

# The modules that can change the text the judge sees or how its reply is parsed, directly
# or through what they import (B7 Decision 13).
FROZEN_JUDGE_MODULES: tuple[str, ...] = (
    "judge",
    "judge_config",
    "judge_examples",
    "display",
    "docs_index",
    "schemas",
    "doc_sources",
    "doc_snapshot",
    "git_fetch",
    "setup",
    "evaluation_schemas",
    "model_client",
    "assessment",
    "rubric",
    "collection",
    "gate",
    "generate",
    "sampler",
    "checks",
)
# Modules the closure reaches that render no judge text and parse no reply, with the reason.
RENDER_PATH_EXEMPT: dict[str, str] = {
    "config": (
        "endpoint, credential and run-config validation; it renders no text and parses no "
        "reply, and B8 may still need to change RunConfig (B7 Decision 1)"
    ),
    "tracing": (
        "record I/O, locks and hashing; the records it reads are pinned by SHA-256 in the run "
        "identity or verified through the collection, and the fence is computed in judge.py "
        "with hashlib and canonical JSON, not through tracing"
    ),
    "cohort": (
        "selects which items an assessment holds and renders nothing; each judge run pins "
        "the assessment SHA-256"
    ),
    "labels": (
        "Chad's labeling display and label records; after the move of its escaping and "
        "heading helpers to display.py it holds no code the judge renders with, and the "
        "reference it feeds is pinned by SHA-256"
    ),
    "human_reference": (
        "never rendered into a message; the frozen reference is pinned by SHA-256 in each "
        "measured run's identity"
    ),
    "qualification": (
        "never rendered into a message; the receipt is pinned by SHA-256 in each measured "
        "run's identity"
    ),
    "calibration": (
        "runs after judging, on recorded judgments; judge_examples uses only its agreement "
        "function to find the development disagreements, and the pool it builds is pinned "
        "by SHA-256 in every v2 run's identity"
    ),
    "acceptance": "runs after judging, on recorded judgments (the per-dimension minimum)",
    "stats": "runs after judging, on recorded judgments (the Clopper-Pearson intervals)",
    "__init__": "holds only the package docstring and __version__, which no message contains",
}
# Third-party distributions that build the judge's request or parse its reply.
MESSAGE_PATH_DISTRIBUTIONS: dict[str, str] = {
    "instructor": (
        "builds the request from Judgment (in json mode it writes the schema, in its own "
        "wording, into the system message; in tools mode it sends the schema as a tool "
        "definition) and parses the reply"
    ),
    "openai": "the SDK that builds and sends the chat request and decodes the response",
    "pydantic": "generates Judgment.model_json_schema() and validates the reply",
    "pydantic-core": "the validation and schema core under pydantic",
    "httpx": "the transport that carries the request body and reads the reply",
    "jiter": "the JSON parser that the OpenAI SDK and Instructor import for reply parsing",
    "docstring-parser": (
        "Instructor's tools mode builds the tool definition's descriptions with it"
    ),
}
# The fixed messages and credential of the in-process request probe (no endpoint is called).
_PROBE_MESSAGES = [
    {"role": "system", "content": "request schema probe"},
    {"role": "user", "content": "request schema probe"},
]
_PROBE_KEY = "request-schema-probe-credential-not-a-secret"
_PROBE_BASE_URL = "http://127.0.0.1:9/v1"


class JudgeError(ValueError):
    """A judge run, its evidence or the frozen judge is refused; nothing was repaired."""


class JudgeClient(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> AttemptResult: ...


# ---------------------------------------------------------------------------- rendering


def _canonical_sha(value: object) -> str:
    """SHA-256 of canonical JSON: sorted keys, compact separators, UTF-8, no NaN."""
    text = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fence_code(values: dict) -> str:
    """The block code: the first 16 hex characters of `_canonical_sha(values)`.

    `values` is `{"domain": FENCE_DOMAIN, "category", "setup", "item", "quotes",
    "sections", "checks"}` with the unfenced texts (`sections` a list of
    `[block name, body]` pairs in citation order). The code depends on the item's own
    text, so that text cannot hold the code of the message it appears in.
    """
    return _canonical_sha(values)[:FENCE_LENGTH]


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line else line for line in text.split("\n"))


def one_line(text: str) -> str:
    """Text on one line: each line break shown as `\\n`, control characters escaped."""
    return escape_control(text.replace("\n", "\\n"))


_one_line = one_line
# The seven fields in payload order, with the heading each starts on.
FIELD_HEADINGS = (
    ("question", "Question:"),
    ("answer", "Answer:"),
    ("equipment_problem", "Equipment problem:"),
    ("tools_required", "Tools required:"),
    ("steps", "Steps:"),
    ("safety_info", "Safety info:"),
    ("tips", "Tips:"),
)


def render_fields(item, fields) -> str:
    """The named fields of an item, in payload order: each heading starts a line and the
    field's text is indented by four spaces (`- ` before each tool and tip, `N. ` before
    each step), so a heading-like line inside a field cannot pass for a heading. Control
    characters are escaped."""
    wanted = set(fields)
    unknown = wanted - {name for name, _ in FIELD_HEADINGS}
    if unknown:
        raise JudgeError(f"unknown item fields: {', '.join(sorted(unknown))}")
    lines: list[str] = []
    for name, heading in FIELD_HEADINGS:
        if name not in wanted:
            continue
        value = getattr(item, name)
        lines.append(heading)
        if name in ("tools_required", "tips"):
            lines += [_indent(f"- {entry}") for entry in value]
        elif name == "steps":
            lines += [_indent(f"{n}. {step}") for n, step in enumerate(value, 1)]
        else:
            lines.append(_indent(value))
    return escape_control("\n".join(lines))


def _item_body(item) -> str:
    return render_fields(item, [name for name, _ in FIELD_HEADINGS])


def setup_lines(setup: SetupRecord) -> str:
    """The five setup lines, unindented, in B6's display order and labels."""
    return "\n".join(
        [
            f"Blender: {one_line(setup.blender)}",
            f"Bonsai: {one_line(setup.bonsai)}",
            f"IFC schema: {one_line(setup.ifc_schema)}",
            f"Discipline: {one_line(setup.discipline)}",
            f"Model state: {one_line(setup.model_state)}",
        ]
    )


def check_line(check: object) -> str:
    if (
        not isinstance(check, dict)
        or not isinstance(check.get("dimension"), str)
        or not isinstance(check.get("name"), str)
        or not isinstance(check.get("passed"), bool)
        or not isinstance(check.get("detail"), str)
    ):
        raise JudgeError("a recorded check is malformed; inspect the gate report")
    outcome = "passed" if check["passed"] else "failed"
    return _one_line(f"{check['dimension']} {check['name']}: {outcome} ({check['detail']})")


_check_line = check_line


def _block(fence: str, name: str, body: str) -> str:
    return f"<<<BEGIN {fence} {name}>>>\n{body}\n<<<END {fence} {name}>>>"


def render_inputs(
    blind_item: BlindItem, section_texts: dict[str, str], checks: list[dict]
) -> dict[str, str]:
    """The prompt's placeholder values for one item, in the fenced format of Decision 4.

    `{category}` is the category id; `{setup}` five unindented lines (`Blender:`,
    `Bonsai:`, `IFC schema:`, `Discipline:`, `Model state:`); `{item}`, `{quotes}`,
    `{sections}` (one block per cited section, in citation order, joined by a blank line)
    and `{checks}` are blocks opened by `<<<BEGIN {fence} NAME>>>` and closed by
    `<<<END {fence} NAME>>>`, each on its own line. Control characters are escaped
    (`display.escape_control`); a line break in a quote or a check detail is shown as
    `\\n`. If the code occurs in any of the texts, `JudgeError` is raised.
    """
    entry = blind_item
    category = escape_control(entry.category)
    setup_text = setup_lines(entry.setup)
    item_body = _item_body(entry.item)
    quotes_body = "\n".join(
        f"[{_one_line(quote.section_id)}] {_one_line(quote.text)}" for quote in entry.quotes
    )
    sections: list[list[str]] = []
    for section in entry.cited_sections:
        if section.id not in section_texts:
            raise JudgeError("no text for a cited section; the fixture slice is incomplete")
        text = section_texts[section.id]
        path = section.id.split(":", 1)[-1].split("#", 1)[0]
        body = "\n".join(
            [
                f"Source: {_one_line(section.source)}",
                f"Path: {_one_line(path)}",
                f"Heading: {_one_line(section_heading(text))}",
                text,
            ]
        )
        sections.append([f"SECTION {_one_line(section.id)}", escape_control(body)])
    if not isinstance(checks, list) or not checks:
        raise JudgeError("an item has no recorded checks; inspect its gate report")
    checks_body = "\n".join(_check_line(check) for check in checks)
    fence = fence_code(
        {
            "domain": FENCE_DOMAIN,
            "category": category,
            "setup": setup_text,
            "item": item_body,
            "quotes": quotes_body,
            "sections": sections,
            "checks": checks_body,
        }
    )
    texts = [category, setup_text, item_body, quotes_body, checks_body]
    texts += [part for pair in sections for part in pair]
    if not fence or any(fence in text for text in texts):
        raise JudgeError(
            "the block code occurs in the item's text, quotes, sections or checks; the item "
            "cannot be fenced and is not judged"
        )
    return {
        "category": category,
        "setup": setup_text,
        "item": _block(fence, "ITEM", item_body),
        "quotes": _block(fence, "QUOTES", quotes_body),
        "sections": "\n\n".join(_block(fence, name, body) for name, body in sections),
        "checks": _block(fence, "CHECKS", checks_body),
        "fence": fence,
    }


def messages_for(
    prompt: str,
    inputs: dict[str, str],
    number: int,
    max_attempts: int,
    examples: str | None = None,
) -> list[dict]:
    """The exact request for one attempt: the rendered prompt and the fixed user message.

    `examples` (judge v2) fills `{examples}`. The item's block code must not occur in the
    examples, nor an example block's code in the item's texts, or the item is refused."""
    values = dict(inputs)
    if examples is not None:
        codes = set(re.findall(r"^<<<(?:BEGIN|END) ([0-9a-f]{16}) EXAMPLE \d+>>>$", examples, re.M))
        fence = inputs.get("fence")
        if (isinstance(fence, str) and fence and fence in examples) or any(
            code in value for code in codes for value in inputs.values()
        ):
            raise JudgeError(
                "a block code of the item occurs in its examples, or one of the examples' "
                "in the item; the item is not judged"
            )
        values["examples"] = examples
    try:
        system = prompt.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        raise JudgeError(
            "judge prompt has an unknown or malformed placeholder for this run"
        ) from exc
    user = USER_MESSAGE.format(number=number, max_attempts=max_attempts)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def judge_client(
    config: JudgeConfig, *, _transport: httpx.BaseTransport | None = None
) -> InstructorClient:
    """The Instructor client for a judge config, with `Judgment` as its response model."""
    return InstructorClient(
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key(),
        mode=config.mode,
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        enable_thinking=config.enable_thinking,
        response_model=Judgment,
        _transport=_transport,
    )


# ----------------------------------------------------------------- the frozen judge


def _package_dir() -> Path:
    return Path(str(importlib.resources.files(PACKAGE)))


def _imports(path: Path, modules: set[str]) -> set[str]:
    """Every package module a file imports, at module level or inside a function.

    `from bonsai_help import x` names module `x` when `x.py` exists, else the package's
    `__init__`; every package import also runs `__init__`. Relative imports of level 1
    resolve the same way.
    """
    try:
        tree = ast.parse(path.read_bytes(), filename=path.name)
    except (OSError, SyntaxError, ValueError) as exc:
        raise JudgeError(f"cannot read the module {path.name} for the closure: {exc}") from None
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == PACKAGE:
                    found.add("__init__")
                    if len(parts) > 1:
                        found.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                parts = (node.module or "").split(".")
                if parts[0] != PACKAGE:
                    continue
                base = parts[1:]
            elif node.level == 1:
                base = node.module.split(".") if node.module else []
            else:
                continue
            found.add("__init__")
            if base:
                found.add(base[0])
            else:
                found.update(a.name if a.name in modules else "__init__" for a in node.names)
    return found


def render_path_closure(package_dir: Path | None = None) -> set[str]:
    """Every package module reached from the judge's modules by imports, transitively.

    It starts from `judge`, `judge_config`, `judge_examples` and every module of
    `FROZEN_JUDGE_MODULES`, and follows the imports of every module it reaches,
    exempt ones included, so nothing is reached through an exemption without being listed.
    A reached name without a file is kept, so `frozen_identity` reports it.
    """
    package = Path(package_dir) if package_dir is not None else _package_dir()
    modules = {path.stem for path in package.glob("*.py")}
    start = {"judge", "judge_config", "judge_examples", *FROZEN_JUDGE_MODULES}
    reached: set[str] = set()
    pending = sorted(start)
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        path = package / f"{name}.py"
        if path.is_file():
            pending.extend(sorted(_imports(path, modules) - reached))
    return reached


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_version(distribution: str) -> str | None:
    """The installed version of a distribution, or None when it is not installed."""
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _locked_versions(lock_path: Path) -> dict[str, set[str]]:
    try:
        data = tomllib.loads(Path(lock_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JudgeError(f"cannot read uv.lock for the frozen judge: {exc}") from None
    versions: dict[str, set[str]] = {}
    for package in data.get("package", []):
        if isinstance(package, dict) and isinstance(package.get("name"), str):
            version = package.get("version")
            if isinstance(version, str):
                versions.setdefault(_normalized(package["name"]), set()).add(version)
    return versions


def _dependencies(lock_path: Path) -> dict[str, str]:
    """Each message-path distribution's installed version, which must be the locked one."""
    locked = _locked_versions(lock_path)
    found: dict[str, str] = {}
    for name in MESSAGE_PATH_DISTRIBUTIONS:
        version = installed_version(name)
        if version is None:
            raise JudgeError(f"the message-path distribution {name} is not installed")
        pinned = locked.get(_normalized(name))
        if not pinned:
            raise JudgeError(f"the message-path distribution {name} is not in uv.lock")
        if version not in pinned:
            raise JudgeError(
                f"the message-path distribution {name} is installed at {version}, not at the "
                f"locked {', '.join(sorted(pinned))}; sync the environment with uv.lock"
            )
        found[name] = version
    return found


def _probe_reply(mode: str) -> dict:
    """A synthetic, schema-valid reply for the in-process request probe."""
    arguments = json.dumps(
        {d: {"decision": 1, "reason": "request schema probe"} for d in DIMENSIONS}
    )
    if mode == "tools":
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "probe-call",
                    "type": "function",
                    "function": {"name": Judgment.__name__, "arguments": arguments},
                }
            ],
        }
    else:
        message = {"role": "assistant", "content": arguments}
    return {
        "id": "probe",
        "object": "chat.completion",
        "created": 0,
        "model": "probe",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


def request_schema_sha256(config: JudgeConfig) -> str:
    """SHA-256 of the chat request Instructor and the SDK prepare for this config.

    The request is built by the real client path for the configured mode, model,
    temperature, token limit and thinking setting, with fixed probe messages, and caught by
    an in-process transport: no endpoint is called and no credential of the config is read.
    In json mode it holds the schema text Instructor writes into the system message; in
    tools mode the tool definition.
    """
    bodies: list[object] = []

    def capture(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_probe_reply(config.mode))

    client = InstructorClient(
        base_url=_PROBE_BASE_URL,
        model=config.model,
        api_key=_PROBE_KEY,
        mode=config.mode,
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        enable_thinking=config.enable_thinking,
        response_model=Judgment,
        _transport=httpx.MockTransport(capture),
    )
    with client:
        client.generate(_PROBE_MESSAGES)
    if len(bodies) != 1:
        raise JudgeError("the request probe did not capture exactly one request")
    return _canonical_sha(bodies[0])


def frozen_identity(
    config: JudgeConfig,
    prompt: tuple[str, str, str],
    *,
    pool: dict | None = None,
    package_dir: Path | None = None,
    lock_path: Path | None = None,
) -> dict:
    """What a `--frozen-judge` match compares (B7 Decision 13).

    `prompt` is `load_judge_prompt`'s `(text, sha256, version)`. Refuses a module the
    render-path closure reaches that is neither frozen nor exempt, a frozen module without
    a file, and a message-path distribution that is missing, absent from `uv.lock` or
    installed at another version than the locked one.
    """
    package = Path(package_dir) if package_dir is not None else _package_dir()
    lock = Path(lock_path) if lock_path is not None else REPOSITORY / "uv.lock"
    both = set(FROZEN_JUDGE_MODULES) & set(RENDER_PATH_EXEMPT)
    if both:
        raise JudgeError(f"modules both frozen and exempt: {', '.join(sorted(both))}")
    unlisted = sorted(
        render_path_closure(package) - set(FROZEN_JUDGE_MODULES) - set(RENDER_PATH_EXEMPT)
    )
    if unlisted:
        raise JudgeError(
            "the judge's render path reaches modules that are neither frozen nor exempt: "
            + ", ".join(unlisted)
            + "; list each in judge.FROZEN_JUDGE_MODULES or judge.RENDER_PATH_EXEMPT"
        )
    modules: dict[str, str] = {}
    for name in FROZEN_JUDGE_MODULES:
        path = package / f"{name}.py"
        if not path.is_file():
            raise JudgeError(f"the frozen judge module {name} has no file")
        modules[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    _, prompt_sha256, version = prompt
    return {
        "schema_version": "1",
        "settings": config.public_settings(),
        "prompt_version": version,
        "prompt_sha256": prompt_sha256,
        "examples": None
        if pool is None
        else {"pool_sha256": pool["sha256"], "examples_k": config.examples_k},
        "modules": modules,
        "dependencies": _dependencies(lock),
        "judgment_schema_sha256": _canonical_sha(Judgment.model_json_schema()),
        "request_schema_sha256": request_schema_sha256(config),
    }


def check_frozen_match(frozen: object, current: dict) -> None:
    """Refuse a judge whose frozen identity differs in any part from the frozen one."""
    if not isinstance(frozen, dict):
        raise JudgeError("the frozen judge identity is unreadable")
    differing = sorted(k for k in set(frozen) | set(current) if frozen.get(k) != current.get(k))
    if not differing:
        return
    details = []
    for key in differing:
        old, new = frozen.get(key), current.get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            parts = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
            details.append(f"{key} ({', '.join(parts)})")
        else:
            details.append(key)
    raise JudgeError(
        "this judge is not the frozen judge; these parts differ: " + "; ".join(details)
    )


# ------------------------------------------------------------------- run evidence


def judge_directory(assessment_dir: Path, judge_run_id: str) -> Path:
    """`<assessment dir>/judges/<judge_run_id>`; a symlinked `judges/` is refused."""
    root = Path(assessment_dir) / JUDGES
    if root.is_symlink():
        raise JudgeError(f"a symlinked {JUDGES} directory is not supported")
    try:
        return run_directory(root, judge_run_id)
    except ValueError:
        raise JudgeError(
            f"judge run id must be 1-64 letters, digits, underscores or hyphens, inside {JUDGES}/"
        ) from None


def _assessment(root: Path, assessment_id: str) -> Assessment:
    try:
        return load_assessment(
            root,
            assessment_id,
            fixtures_dir=collection.FIXTURES,
            doc_config=load_config(collection.DOC_SOURCES),
        )
    except (AssessmentError, ValueError) as exc:
        raise JudgeError(f"assessment: {exc}") from None


def _root(assessment: Assessment) -> Path:
    # `assessment.assessment_directory` puts an assessment at `<root>/assessments/<id>`.
    return assessment.directory.parent.parent


def item_checks(assessment: Assessment) -> dict[str, list[dict]]:
    """Each blind id's recorded checks, from its batch's verified gate report.

    The key (`assessment.load_key`) is read only to find each item's batch and gate
    record; nothing from it is returned. No write, no call."""
    root = _root(assessment)
    manifest = assessment.manifest
    try:
        key = load_key(root, manifest["assessment_id"])
    except (AssessmentError, ValueError) as exc:
        raise JudgeError(f"assessment key: {exc}") from None
    sources = manifest["sources"]
    batches: dict[tuple[str, str], dict[str, list[dict]]] = {}
    found: dict[str, list[dict]] = {}
    for entry in assessment.queue:
        record = key[entry.blind_id]
        pair = (sources[record["source_index"]]["collection_id"], record["run_id"])
        if pair not in batches:
            try:
                batches[pair] = collection.batch_recorded_checks(root, *pair)
            except (collection.CollectionError, ValueError, OSError) as exc:
                raise JudgeError(
                    f"a source collection's recorded checks cannot be verified: {exc}"
                ) from None
        checks = batches[pair].get(record["item_id"])
        if checks is None:
            raise JudgeError("a selected item has no gate record; inspect its collection")
        found[entry.blind_id] = checks
    return found


def _rendered(assessment: Assessment) -> dict[str, dict[str, str]]:
    """Each blind id's placeholder values, from verified evidence; no write, no call."""
    checks = item_checks(assessment)
    rendered: dict[str, dict[str, str]] = {}
    for entry in assessment.queue:
        try:
            texts = sampler.section_texts(entry.cited_sections, collection.FIXTURES)
        except sampler.SamplerError as exc:
            raise JudgeError(f"fixture slice: {exc}") from None
        rendered[entry.blind_id] = render_inputs(entry, texts, checks[entry.blind_id])
    return rendered


# ------------------------------------------------------------------ examples (v2)


def _pool_error(exc: ValueError) -> JudgeError:
    return JudgeError(f"example pool: {exc}")


def _load_pool(root: Path, pool_id: str, config: JudgeConfig, assessment: Assessment) -> dict:
    """The verified pool for a v2 run on this assessment; every refusal before any write.

    The config must name an embedding model, the pool's, which must also be the gate's
    for the judged assessment's sources; the pool must come from a development assessment
    and share no item (trace id or payload hash) with the judged one."""
    if config.embedding_model is None:
        raise JudgeError(
            "a judge run with an example pool needs embedding_model (the gate's embedding "
            "model) in its config"
        )
    try:
        pool = judge_examples.load_pool(root, pool_id)
        if pool["embedding"]["model"] != config.embedding_model:
            raise judge_examples.PoolError(
                "the judge config's embedding model differs from the pool's"
            )
        judge_examples.check_gate_model(root, assessment, config.embedding_model)
        judge_examples.check_independent(pool, assessment.queue)
    except judge_examples.PoolError as exc:
        raise _pool_error(exc) from None
    return pool


def _examples_record(data: bytes, pool: dict | None, assessment: Assessment) -> dict:
    """A run's examples file, verified against its pool copy and the assessment: the pool
    seal, the judged vectors and the selection they give. Never repaired."""
    try:
        record = json.loads(data)
    except ValueError:
        raise JudgeError(f"{EXAMPLES} is not JSON; {INSPECT}") from None
    order = list(assessment.manifest["display_order"])
    if not isinstance(record, dict) or set(record) != EXAMPLES_FIELDS:
        raise JudgeError(f"{EXAMPLES} changed or is malformed; {INSPECT}")
    try:
        judge_examples.verify_pool(record["pool"])
        if pool is not None and record["pool"] != pool:
            raise judge_examples.PoolError("the run's pool copy differs from the pool")
        vectors = record["vectors"]
        if not isinstance(vectors, dict) or list(vectors) != order:
            raise judge_examples.PoolError("the judged vectors do not cover the assessment")
        selection = judge_examples.select_examples(record["pool"], vectors, record["examples_k"])
    except judge_examples.PoolError as exc:
        raise JudgeError(f"{EXAMPLES} changed or is malformed ({exc}); {INSPECT}") from None
    if (
        record["schema_version"] != "1"
        or record["pool_id"] != record["pool"]["pool_id"]
        or record["selection"] != selection
    ):
        raise JudgeError(f"{EXAMPLES} changed or is malformed; {INSPECT}")
    return record


def _examples_texts(record: dict, assessment: Assessment) -> dict[str, str]:
    try:
        return {
            blind_id: judge_examples.render_examples(record["pool"], ids, assessment.rubric)
            for blind_id, ids in record["selection"].items()
        }
    except judge_examples.PoolError as exc:
        raise _pool_error(exc) from None


def _generators(root: Path, assessment: Assessment) -> list[dict]:
    try:
        return qualification.source_generators(root, assessment.manifest["sources"])
    except QualificationError as exc:
        raise JudgeError(str(exc)) from None


def _names(model: object, identity: object) -> set[str]:
    return {v.strip().casefold() for v in (model, identity) if isinstance(v, str)}


def _check_generators(config: JudgeConfig, generators: list[dict]) -> None:
    """Below every generator's temperature; a measured judge is another model than each."""
    for generator in generators:
        temperature = generator.get("temperature")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise JudgeError("a source collection's generator temperature is unreadable")
        if not config.temperature < temperature:
            raise JudgeError(
                f"the judge temperature {config.temperature} must be below every source "
                f"generator's temperature (one ran at {temperature})"
            )
    if config.purpose != "measured":
        return
    names = _names(config.model, config.model_identity)
    for generator in generators:
        if names & _names(
            generator.get("model"), generator.get("model_identity")
        ) or config.model_sha256 == generator.get("model_sha256"):
            raise JudgeError(
                "a measured judge must be another model than every source generator (model, "
                "model_identity or model_sha256 matches one); same-model judging is smoke only"
            )


def _check_smoke(config: JudgeConfig, assessment: Assessment, qualification_id, frozen) -> None:
    if config.purpose != "smoke":
        return
    if assessment.manifest["kind"] != "development":
        raise JudgeError(
            "a smoke judge run is refused on an arm assessment: smoke runs are diagnostic only "
            "and allowed only on a development assessment that is never labeled"
        )
    directory = assessment.directory
    if any(
        (directory / name).exists() or (directory / name).is_symlink()
        for name in (human_reference.LEDGER, human_reference.REFERENCE, human_reference.LOCK)
    ):
        raise JudgeError(
            "a smoke judge run is allowed only on a development assessment that is never "
            "labeled; this one has labels"
        )
    if qualification_id is not None or frozen is not None:
        raise JudgeError("a smoke judge run takes no qualification and no frozen judge")


def _reference_sha(assessment: Assessment) -> str:
    try:
        return human_reference.load_reference(assessment)["sha256"]
    except human_reference.HumanReferenceError as exc:
        raise JudgeError(
            f"a measured judge run needs the frozen human reference first: {exc}"
        ) from None


def _qualification(
    config: JudgeConfig, qualification_id: object, generators: list[dict], root: Path
) -> dict:
    if not isinstance(qualification_id, str):
        raise JudgeError("a measured judge run needs a qualification receipt (judge-qualify)")
    try:
        checked = qualification.validate_qualification(config, qualification_id, generators, root)
    except QualificationError as exc:
        raise JudgeError(f"qualification: {exc}") from None
    return {"qualification_id": qualification_id, "sha256": checked["sha256"]}


def _receipt_sha(root: Path, qualification_id: str) -> str | None:
    try:
        path = qualification.receipt_path(root, qualification_id)
        if path.is_symlink():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (QualificationError, OSError):
        return None


def _read_manifest(directory: Path) -> dict:
    path = directory / MANIFEST
    if path.is_symlink():
        raise JudgeError(f"{MANIFEST} is a symlink; {INSPECT}")
    if not path.exists():
        raise JudgeError(
            f"judge run {directory.name!r} has no {MANIFEST}: its creation was interrupted; "
            f"{INSPECT}"
        )
    try:
        manifest = read_json(path)
    except (OSError, ValueError):
        raise JudgeError(f"{MANIFEST} is unreadable or not a JSON object; {INSPECT}") from None
    identity = manifest.get("identity")
    if (
        set(manifest) != MANIFEST_FIELDS
        or manifest["schema_version"] != "1"
        or manifest["judge_run_id"] != directory.name
        or not isinstance(identity, dict)
        or manifest["fingerprint"] != digest(identity)
        or manifest["status"] not in STATUSES
        or manifest["purpose"] != identity.get("purpose")
        or manifest["assessment_id"] != identity.get("assessment_id")
    ):
        raise JudgeError(f"judge run manifest changed; {INSPECT}")
    return manifest


def _check_ledgers(directory: Path, manifest: dict) -> str:
    """The ledgers and prompt copy as the manifest pins them; returns the prompt text."""
    recorded = manifest["artifacts_sha256"]
    for name in LEDGERS:
        if (directory / name).is_symlink():
            raise JudgeError(f"{name} is a symlink; {INSPECT}")
    actual = artifact_hashes(directory)
    if not isinstance(recorded, dict) or any(
        name not in recorded or actual.get(name) != recorded[name] for name in LEDGERS
    ):
        raise JudgeError(f"a judge ledger changed or is missing; {INSPECT}")
    copy = directory / PROMPT_COPY
    if copy.is_symlink() or not copy.is_file():
        raise JudgeError(f"{PROMPT_COPY} is missing; {INSPECT}")
    data = copy.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["identity"].get("prompt_sha256"):
        raise JudgeError(f"{PROMPT_COPY} changed; {INSPECT}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise JudgeError(f"{PROMPT_COPY} changed; {INSPECT}") from None


def _read_examples(directory: Path) -> bytes:
    path = directory / EXAMPLES
    if path.is_symlink() or not path.is_file():
        raise JudgeError(f"{EXAMPLES} is missing or a symlink; {INSPECT}")
    return path.read_bytes()


def _pinned_examples(
    directory: Path, identity: dict, assessment: Assessment
) -> tuple[dict | None, dict[str, str]]:
    """A v2 run's examples file as its identity pins it, and each item's examples text;
    a run without examples must have no examples file."""
    pinned = identity.get("examples")
    path = directory / EXAMPLES
    if pinned is None:
        if path.exists() or path.is_symlink():
            raise JudgeError(f"{EXAMPLES} exists in a run without examples; {INSPECT}")
        return None, {}
    data = _read_examples(directory)
    if not isinstance(pinned, dict) or hashlib.sha256(data).hexdigest() != pinned.get(
        "file_sha256"
    ):
        raise JudgeError(f"{EXAMPLES} changed; {INSPECT}")
    record = _examples_record(data, None, assessment)
    if (
        record["pool"]["sha256"] != pinned.get("pool_sha256")
        or record["pool_id"] != pinned.get("pool_id")
        or record["examples_k"] != pinned.get("examples_k")
        or record["pool"]["embedding"]["model"] != pinned.get("embedding_model")
    ):
        raise JudgeError(f"{EXAMPLES} differs from the run's identity; {INSPECT}")
    return record, _examples_texts(record, assessment)


def _validate(
    directory: Path, assessment: Assessment, rendered: dict[str, dict[str, str]]
) -> tuple[dict, list[dict], list[dict], dict[str, dict]]:
    manifest = _read_manifest(directory)
    identity = manifest["identity"]
    if (
        identity.get("assessment_id") != assessment.manifest["assessment_id"]
        or identity.get("assessment_sha256") != assessment.manifest["sha256"]
    ):
        raise JudgeError("the judge run belongs to another assessment or an earlier version")
    prompt = _check_ledgers(directory, manifest)
    record, texts = _pinned_examples(directory, identity, assessment)
    if identity.get("inputs_sha256") != digest(rendered):
        raise JudgeError(
            "the judged inputs changed since the run started (assessment, fixture slice or "
            f"gate records); {INSPECT}"
        )
    if manifest["purpose"] == "measured":
        if identity.get("reference_sha256") != _reference_sha(assessment):
            raise JudgeError(f"the frozen human reference differs from the run's; {INSPECT}")
        pinned = identity.get("qualification") or {}
        found = _receipt_sha(_root(assessment), pinned.get("qualification_id", ""))
        if found is None or found != pinned.get("sha256"):
            raise JudgeError(f"the run's qualification receipt changed or is missing; {INSPECT}")
    settings = identity.get("settings") or {}
    max_attempts = settings.get("max_attempts")
    if type(max_attempts) is not int or max_attempts < 1:
        raise JudgeError(f"judge run settings are malformed; {INSPECT}")
    run_id = directory.name
    try:
        starts = read_records(directory / STARTS)
        attempts = read_records(directory / ATTEMPTS)
    except ValueError as exc:
        raise JudgeError(f"{exc}; {INSPECT}") from None
    by_id: dict[str, dict] = {}
    per_item: dict[str, list[dict]] = {}
    for start in starts:
        blind_id = start.get("blind_id")
        if set(start) != START_FIELDS or not isinstance(blind_id, str) or blind_id not in rendered:
            raise JudgeError(f"a start record is malformed or names no selected item; {INSPECT}")
        previous = per_item.setdefault(blind_id, [])
        number = len(previous) + 1
        messages = messages_for(
            prompt, rendered[blind_id], number, max_attempts, texts.get(blind_id)
        )
        example_ids = None if record is None else record["selection"][blind_id]
        if (
            start["event"] != "attempt_started"
            or start["judge_run_id"] != run_id
            or start["attempt_number"] != number
            or number > max_attempts
            or start["attempt_id"] != f"{run_id}:{blind_id}:{number}"
            or start["parent_attempt_id"] != (previous[-1]["attempt_id"] if previous else None)
            or not isinstance(start["started_at"], str)
            or start["example_ids"] != example_ids
            or start["input"] != messages
            or start["messages_sha256"] != digest({"messages": messages})
        ):
            raise JudgeError(f"a start record's lineage, budget or input differs; {INSPECT}")
        by_id[start["attempt_id"]] = start
        previous.append(start)
    completed: set[str] = set()
    successful: dict[str, dict] = {}
    for attempt in attempts:
        attempt_id = attempt.get("attempt_id")
        start = by_id.get(attempt_id) if isinstance(attempt_id, str) else None
        if start is None or attempt_id in completed:
            raise JudgeError(f"a completion has no unique start; {INSPECT}")
        if set(attempt) != START_FIELDS | COMPLETION_FIELDS or attempt["event"] != (
            "attempt_completed"
        ):
            raise JudgeError(f"a completion record is malformed; {INSPECT}")
        if any(attempt[k] != v for k, v in start.items() if k != "event"):
            raise JudgeError(f"a completion differs from its start; {INSPECT}")
        completed.add(attempt["attempt_id"])
        blind_id = attempt["blind_id"]
        if attempt["valid"] is True:
            try:
                canonical = Judgment.model_validate(attempt["judgment"]).model_dump(mode="json")
            except ValidationError:
                canonical = None
            if (
                canonical != attempt["judgment"]
                or attempt["error"] is not None
                or attempt["error_type"] is not None
                or attempt["response_model"] != settings.get("model")
                or blind_id in successful
                or per_item[blind_id][-1]["attempt_id"] != attempt["attempt_id"]
            ):
                raise JudgeError(f"a successful completion is inconsistent; {INSPECT}")
            successful[blind_id] = attempt
        elif (
            attempt["valid"] is not False
            or attempt["judgment"] is not None
            or not isinstance(attempt["error_type"], str)
            or not attempt["error_type"]
        ):
            raise JudgeError(f"a failed completion is inconsistent; {INSPECT}")
    unresolved = [b for b in assessment.manifest["display_order"] if b not in successful]
    status = manifest["status"]
    if (status == "complete" and unresolved) or (
        status == "incomplete"
        and (not unresolved or any(len(per_item.get(b, [])) != max_attempts for b in unresolved))
    ):
        raise JudgeError(f"the run's status differs from its ledgers; {INSPECT}")
    return manifest, starts, attempts, successful


def validate_judge(
    directory: Path, assessment: Assessment
) -> tuple[dict, list[dict], list[dict], dict[str, dict]]:
    """Verify a judge run against its assessment and return its manifest, starts, attempts
    and successful completions (by blind id).

    The manifest's fingerprint, the ledger and prompt hashes, every start's lineage and
    exact messages (re-rendered from the verified evidence), every completion against its
    start, the reference and qualification pins of a measured run, and the status are
    checked; any difference is refused, never repaired."""
    return _validate(Path(directory), assessment, _rendered(assessment))


def _reported_models(attempts: list[dict]) -> list[str]:
    """Every model id a reply reported, sorted. A reply that reported none is never a valid
    judgment (it fails `ModelIdentityMismatch`), so it appears among the failed attempts."""
    return sorted({a["response_model"] for a in attempts if a["response_model"] is not None})


def _summary(
    manifest: dict,
    assessment: Assessment,
    starts: list[dict],
    attempts: list[dict],
    successful: dict[str, dict],
) -> dict:
    completed = {a["attempt_id"] for a in attempts}
    identity = manifest["identity"]
    return {
        "assessment_id": assessment.manifest["assessment_id"],
        "judge_run_id": manifest["judge_run_id"],
        "purpose": manifest["purpose"],
        "status": manifest["status"],
        "settings": identity["settings"],
        "prompt_version": identity["prompt_version"],
        "population": len(assessment.queue),
        "resolved": len(successful),
        "started_attempts": len(starts),
        "completed_attempts": len(attempts),
        "unknown_outcomes": [s["attempt_id"] for s in starts if s["attempt_id"] not in completed],
        "unresolved": [b for b in assessment.manifest["display_order"] if b not in successful],
        "reported_models": _reported_models(attempts),
    }


def _locked(path: Path, holder: str) -> ExitStack:
    """Hold a lock file; an existing one is reported and never removed by code."""
    stack = ExitStack()
    try:
        stack.enter_context(exclusive(path))
    except FileExistsError:
        raise JudgeError(
            f"{path.name} exists: {holder} stopped abruptly; inspect it (it is never removed "
            "by code)"
        ) from None
    return stack


def _lock_present(directory: Path) -> None:
    if (directory / LOCK).exists() or (directory / LOCK).is_symlink():
        raise JudgeError(
            f"{LOCK} exists: a judge run is active, or one stopped abruptly; inspect it (it is "
            "never removed by code)"
        )


def _existing(root: Path, assessment_id: str, judge_run_id: str) -> tuple[Assessment, Path]:
    assessment = _assessment(Path(root), assessment_id)
    directory = judge_directory(assessment.directory, judge_run_id)
    if not directory.is_dir():
        raise JudgeError(f"no judge run {judge_run_id!r} for assessment {assessment_id!r}")
    _lock_present(directory)
    return assessment, directory


def judge_status(root: Path, assessment_id: str, judge_run_id: str) -> dict:
    """A verified judge run's status: counts, unknown outcomes and unresolved blind ids.

    Holds the status, purpose, judge settings and prompt version, the population, resolved
    items, started and completed attempts, unknown-outcome attempt ids, unresolved blind ids
    and the model ids replies reported. No decision, reason, item, run or trace id."""
    assessment, directory = _existing(root, assessment_id, judge_run_id)
    manifest, starts, attempts, successful = validate_judge(directory, assessment)
    return _summary(manifest, assessment, starts, attempts, successful)


def load_judgments(root: Path, assessment_id: str, judge_run_id: str) -> dict[str, Judgment]:
    """The valid judgments of a verified judge run, keyed by blind id."""
    assessment, directory = _existing(root, assessment_id, judge_run_id)
    _, _, _, successful = validate_judge(directory, assessment)
    return {
        blind_id: Judgment.model_validate(attempt["judgment"])
        for blind_id, attempt in successful.items()
    }


# ---------------------------------------------------------------------- the run


def _validation_summary(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in e['loc']) or 'judgment'}: {e['msg']}"
        for e in exc.errors(include_url=False, include_input=False)
    )


def _complete(result: AttemptResult, config: JudgeConfig) -> dict:
    """The completion fields of an attempt; a reply that is not a valid judgment from the
    configured judge model is a failed attempt with its raw response kept, never an error."""
    raw_response, unserializable = generate._storable(result.raw_response)
    error, error_type = result.error, result.error_type
    judgment = None
    if result.item is not None:
        if not isinstance(result.item, Judgment):
            error, error_type = "unexpected response model", "UnexpectedResponseModel"
        else:
            try:
                judgment = Judgment.model_validate(result.item.model_dump(mode="json")).model_dump(
                    mode="json"
                )
            except ValidationError as exc:
                error, error_type = (
                    f"judgment invalid: {_validation_summary(exc)}",
                    "JudgmentInvalid",
                )
    if judgment is not None and result.response_model != config.model:
        judgment = None
        error = "the reply reported a model other than the configured judge model"
        error_type = "ModelIdentityMismatch"
    if judgment is not None and unserializable is not None:
        judgment = None
        error = f"raw response is not strict JSON ({unserializable}); recorded as text"
        error_type = "UnserializableResponse"
    if judgment is None and not error_type:
        error = error or "the client returned no judgment"
        error_type = "NoJudgment"
    return {
        "event": "attempt_completed",
        "completed_at": now(),
        "raw_response": raw_response,
        "error": generate._optional_text(error),
        "error_type": generate._optional_text(error_type),
        "response_model": generate._optional_text(result.response_model),
        "valid": judgment is not None,
        "judgment": judgment,
    }


def _measured_runs(judges: Path, judge_run_id: str) -> int:
    """Measured runs already under `judges/`; an unreadable one counts as measured."""
    if not judges.is_dir():
        return 0
    count = 0
    for path in judges.iterdir():
        if path.name.startswith(".") or path.name == judge_run_id:
            continue
        try:
            purpose = read_json(path / MANIFEST).get("purpose")
        except (OSError, ValueError):
            purpose = None
        if purpose != "smoke":
            count += 1
    return count


def _check_budget(config: JudgeConfig, judges: Path, judge_run_id: str) -> None:
    if config.purpose != "measured":
        return
    if _measured_runs(judges, judge_run_id) >= MEASURED_RUNS_PER_ASSESSMENT:
        raise JudgeError(
            f"this assessment already has {MEASURED_RUNS_PER_ASSESSMENT} measured judge runs, "
            "the most it allows; a further run needs a new dated decision"
        )


def _create(
    directory: Path,
    config: JudgeConfig,
    prompt: str,
    identity: dict,
    judge_run_id: str,
    examples: bytes | None = None,
) -> dict:
    judges = directory.parent
    judges.mkdir(exist_ok=True)
    with _locked(judges / CREATE_LOCK, "a judge run is being created, or a creation"):
        if directory.exists() or directory.is_symlink():
            raise JudgeError(f"judge run {judge_run_id!r} already exists; choose a new id")
        _check_budget(config, judges, judge_run_id)
        directory.mkdir()
        for name in LEDGERS:
            (directory / name).touch(exist_ok=False)
        with (directory / PROMPT_COPY).open("x", encoding="utf-8", newline="") as stream:
            stream.write(prompt)
        if examples is not None:
            with (directory / EXAMPLES).open("xb") as stream:
                stream.write(examples)
                stream.flush()
                os.fsync(stream.fileno())
        created = now()
        manifest = {
            "schema_version": "1",
            "judge_run_id": judge_run_id,
            "assessment_id": identity["assessment_id"],
            "purpose": config.purpose,
            "status": "running",
            "created_at": created,
            "updated_at": created,
            "identity": identity,
            "fingerprint": digest(identity),
            "artifacts_sha256": artifact_hashes(directory),
        }
        write_checkpoint(directory / MANIFEST, manifest)
        return manifest


def judge_run(
    root: Path,
    assessment_id: str,
    judge_run_id: str,
    config: JudgeConfig,
    client: JudgeClient,
    *,
    qualification_id: str | None = None,
    frozen_judge: dict | None = None,
    pool_id: str | None = None,
    embedder: judge_examples.Embedder | None = None,
    resume: bool = False,
    before_attempt: Callable[[str, int], None] | None = None,
) -> dict:
    """Judge every item of an assessment (or resume a run); return its status summary.

    Every refusal comes before any directory is created or any call is made: the purpose
    and kind, the generator temperatures and models, the frozen human reference and the
    qualification (measured), the example pool (`pool_id`, judge v2), the prompt, the
    frozen judge (`frozen_judge`, the identity a selection recorded, matched exactly), the
    rendering of every item, and the measured-run budget. `before_attempt(blind_id,
    number)` runs before each start is written.

    With `pool_id` (judge v2, B7 Decision 11), every judged item's vector is computed with
    `embedder` when the run is created, before any chat call, and the selection is written
    into the run's `examples.json` with the judged vectors and a copy of the pool; an
    embedding failure creates no run and no start record. A resume reuses the recorded
    selection (no embedder is needed) and never recomputes it. Each start record lists
    its `example_ids`.
    """
    root = Path(root)
    assessment = _assessment(root, assessment_id)
    directory = judge_directory(assessment.directory, judge_run_id)
    _check_smoke(config, assessment, qualification_id, frozen_judge)
    generators = _generators(root, assessment)
    _check_generators(config, generators)
    reference_sha256 = None
    pinned_qualification = None
    if config.purpose == "measured":
        reference_sha256 = _reference_sha(assessment)
        pinned_qualification = _qualification(config, qualification_id, generators, root)
    pool = None
    if pool_id is not None:
        pool = _load_pool(root, pool_id, config, assessment)
        if not resume and embedder is None:
            raise JudgeError(
                "a judge run with an example pool needs an embedder for the gate's embedding "
                "model, to select each item's examples before any chat call"
            )
    try:
        prompt, prompt_sha256, version = load_judge_prompt(config, with_examples=pool is not None)
    except ValueError as exc:
        raise JudgeError(str(exc)) from None
    current = frozen_identity(config, (prompt, prompt_sha256, version), pool=pool)
    if frozen_judge is not None:
        if config.purpose != "measured":
            raise JudgeError("only a measured judge run can be matched to the frozen judge")
        check_frozen_match(frozen_judge, current)
    rendered = _rendered(assessment)
    record = examples_data = None
    texts: dict[str, str] = {}
    if pool is not None:
        if resume:
            if not directory.is_dir():
                raise JudgeError(f"no judge run {judge_run_id!r} to resume")
            examples_data = _read_examples(directory)
            record = _examples_record(examples_data, pool, assessment)
        else:
            # Refuse an existing id or a spent budget before the embedding call.
            if directory.exists() or directory.is_symlink():
                raise JudgeError(f"judge run {judge_run_id!r} already exists; choose a new id")
            _check_budget(config, directory.parent, judge_run_id)
            try:
                vectors, selection = judge_examples.select_for(
                    pool, assessment.queue, embedder, config.examples_k
                )
            except judge_examples.PoolError as exc:
                raise _pool_error(exc) from None
            record = {
                "schema_version": "1",
                "pool_id": pool_id,
                "examples_k": config.examples_k,
                "pool": pool,
                "vectors": vectors,
                "selection": selection,
            }
            examples_data = (
                json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
            ).encode("utf-8")
        texts = _examples_texts(record, assessment)
    for blind_id, inputs in rendered.items():  # a placeholder the run cannot fill refuses here
        messages_for(prompt, inputs, 1, config.max_attempts, texts.get(blind_id))
    if hashlib.sha256(config.prompt_file().read_bytes()).hexdigest() != prompt_sha256:
        raise JudgeError("the judge prompt file changed after it was loaded")
    identity = {
        "assessment_id": assessment_id,
        "assessment_sha256": assessment.manifest["sha256"],
        "kind": assessment.manifest["kind"],
        "purpose": config.purpose,
        "settings": config.public_settings(),
        "prompt_version": version,
        "prompt_sha256": prompt_sha256,
        "reference_sha256": reference_sha256,
        "qualification": pinned_qualification,
        "examples": None
        if pool is None
        else {
            "pool_id": pool_id,
            "pool_sha256": pool["sha256"],
            "examples_k": config.examples_k,
            "embedding_model": config.embedding_model,
            "file_sha256": hashlib.sha256(examples_data).hexdigest(),
        },
        "frozen_judge_sha256": None if frozen_judge is None else digest(frozen_judge),
        "generators": [
            {
                "collection_id": g["collection_id"],
                "temperature": g["temperature"],
                "model_sha256": g["model_sha256"],
            }
            for g in generators
        ],
        "inputs_sha256": digest(rendered),
        "frozen_identity": current,
        "implementation": generate.implementation_identity(config.prompt_file()),
    }
    if resume:
        if not directory.is_dir():
            raise JudgeError(f"no judge run {judge_run_id!r} to resume")
    else:
        if directory.exists() or directory.is_symlink():
            raise JudgeError(f"judge run {judge_run_id!r} already exists; choose a new id")
        _check_budget(config, directory.parent, judge_run_id)
        _create(directory, config, prompt, identity, judge_run_id, examples_data)
    with _locked(directory / LOCK, "a judge run is active, or one"):
        manifest, starts, attempts, successful = _validate(directory, assessment, rendered)
        if manifest["fingerprint"] != digest(identity):
            raise JudgeError(
                "resume requires the original settings, prompt, code, assessment, inputs, "
                "reference and qualification"
            )
        if manifest["status"] == "complete":
            raise JudgeError("complete judge runs are immutable; choose a new judge run id")
        ledger = _Ledger(directory, manifest, starts, attempts, successful)
        try:
            manifest["status"] = "running"
            ledger.checkpoint()
            for entry in assessment.queue:
                ledger.judge_item(
                    entry.blind_id,
                    prompt,
                    rendered[entry.blind_id],
                    config,
                    client,
                    before_attempt,
                    examples=texts.get(entry.blind_id),
                    example_ids=None if record is None else record["selection"][entry.blind_id],
                )
            unresolved = [b for b in assessment.manifest["display_order"] if b not in successful]
            manifest["status"] = "incomplete" if unresolved else "complete"
            ledger.checkpoint()
        except BaseException as error:
            manifest["status"] = "interrupted"
            try:
                ledger.checkpoint()
            except Exception as failure:  # keep the original error; note this one
                error.add_note(f"the interrupted checkpoint also failed ({failure!r}); {INSPECT}")
            raise
        return _summary(manifest, assessment, starts, attempts, successful)


class _Ledger:
    """The run's append-only ledgers in memory, mirrored to disk record by record."""

    def __init__(
        self,
        directory: Path,
        manifest: dict,
        starts: list[dict],
        attempts: list[dict],
        successful: dict[str, dict],
    ) -> None:
        self.directory = directory
        self.manifest = manifest
        self.starts = starts
        self.attempts = attempts
        self.successful = successful

    def checkpoint(self) -> None:
        self.manifest["artifacts_sha256"] = artifact_hashes(self.directory)
        self.manifest["updated_at"] = now()
        write_checkpoint(self.directory / MANIFEST, self.manifest)

    def _append(self, name: str, records: list[dict], record: dict) -> None:
        append_record(self.directory / name, record)
        records.append(record)

    def judge_item(
        self,
        blind_id: str,
        prompt: str,
        inputs: dict[str, str],
        config: JudgeConfig,
        client: JudgeClient,
        before_attempt: Callable[[str, int], None] | None,
        *,
        examples: str | None = None,
        example_ids: list[str] | None = None,
    ) -> None:
        if blind_id in self.successful:
            return
        run_id = self.manifest["judge_run_id"]
        previous = [s for s in self.starts if s["blind_id"] == blind_id]
        # A start without a completion (unknown outcome) has used up its attempt.
        for number in range(len(previous) + 1, config.max_attempts + 1):
            if before_attempt is not None:
                before_attempt(blind_id, number)
            messages = messages_for(prompt, inputs, number, config.max_attempts, examples)
            start = {
                "event": "attempt_started",
                "judge_run_id": run_id,
                "blind_id": blind_id,
                "attempt_id": f"{run_id}:{blind_id}:{number}",
                "attempt_number": number,
                "parent_attempt_id": previous[-1]["attempt_id"] if previous else None,
                "started_at": now(),
                "example_ids": example_ids,
                "input": messages,
                "messages_sha256": digest({"messages": messages}),
            }
            self._append(STARTS, self.starts, start)
            self.checkpoint()
            previous.append(start)
            result = client.generate(messages)
            attempt = start | _complete(result, config)
            self._append(ATTEMPTS, self.attempts, attempt)
            self.checkpoint()
            if attempt["valid"]:
                self.successful[blind_id] = attempt
                return
