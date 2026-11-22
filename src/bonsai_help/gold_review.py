"""Gold drafts, ingest, review packets, import, effective state and publish.

Everything here lives outside Git under `data/gold/` (git-ignored):

    .lock                         exclusive create while a command writes; a leftover lock
                                  after a hard kill is refused, for inspection
    .tmp/                         staging for records; leftovers are listed by `gold status`
    drafts/<item>/<sha16>.json    content-addressed draft content (identical bytes: no-op)
    ingests/GI-<sha12>.json       lane receipt: lane, date, input hash, the drafts it made heads
    packets/GP-NNN.md, .json      review packet and its manifest (normalized fixed regions)
    imports/GP-NNN.json           Chad's decisions and NOTE text (append-only, one per packet)

Ingest receipts and imports share one sequence number; the latest event naming an item gives
its head draft. Decisions are ordered by that sequence and the block ordinal.

Only Chad writes the DECISION and NOTE lines and the edit JSON of a packet. Import runs only
from an interactive terminal with a typed confirmation (`cli`), and an assistant never fills,
edits or imports a packet (AGENTS.md).
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from bonsai_help import gold
from bonsai_help import gold_patterns as gp
from bonsai_help.doc_snapshot import CheckFailed, Problem, Report, dump_json, fsync_dir, write_new
from bonsai_help.doc_sources import ConfigError, Refused, canonical, privacy_matches, sha256_hex
from bonsai_help.gold import Context, GoldContent

INGEST_SCHEMA = "gold-ingest-v1"
PACKET_SCHEMA = "gold-packet-v1"
IMPORT_SCHEMA = "gold-import-v1"
EDIT_LANE = "chad-edit"
DEFAULT_SIZE = 25
WORDS = ("approve", "edit", "reject")
PACKET_MARK = re.compile(r"<!-- gold:packet (?P<id>GP-\d{3}) v1 sha256=(?P<sha>[0-9a-f]{64}) -->")
ITEM_MARK = re.compile(
    r"<!-- gold:item (?P<id>GS-[SMIC][DH]-\d{3}) draft=(?P<sha>[0-9a-f]{64}) -->"
)
DECIDE_MARK = "<!-- gold:decide {} -->"
END_MARK = "<!-- gold:end {} -->"
FENCE_OPEN = re.compile(r"(?P<ticks>`{3,})json")


class ProblemsFound(CheckFailed):
    """A check failed; `problems` are printed one per line before the summary."""

    def __init__(self, summary: str, problems: Sequence[Problem | str]):
        super().__init__(summary)
        self.problems = [str(p) for p in problems]


def normalized(text: str) -> str:
    """LF line ends, no trailing blanks on a line, one final newline: what packet hashes cover,
    so an editor that trims whitespace or writes CRLF does not make a packet look tampered."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip(" \t") for line in lines).strip("\n") + "\n"


# ------------------------------------------------------------------ store


class Store:
    def __init__(self, root: Path):
        self.root = root

    def folder(self, name: str) -> Path:
        return self.root / name

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / ".lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise Refused(
                "gold/.lock exists: another gold command is running or one was interrupted; "
                "inspect it before removing it"
            ) from None
        os.close(descriptor)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _records(self, name: str) -> list[dict]:
        folder = self.folder(name)
        if not folder.is_dir():
            return []
        out = []
        for path in sorted(folder.glob("*.json")):
            try:
                out.append(json.loads(path.read_bytes()))
            except ValueError:
                raise CheckFailed(
                    f"gold/{name}/{path.name} is not valid JSON; inspect it"
                ) from None
        return out

    def ingests(self) -> list[dict]:
        return self._records("ingests")

    def imports(self) -> list[dict]:
        return sorted(self._records("imports"), key=lambda r: r["sequence"])

    def packets(self) -> list[dict]:
        return self._records("packets")

    def events(self) -> list[dict]:
        return sorted([*self.ingests(), *self.imports()], key=lambda r: r["sequence"])

    def next_sequence(self) -> int:
        return max((r["sequence"] for r in self.events()), default=0) + 1

    def draft_path(self, item_id: str, sha: str) -> Path:
        return self.folder("drafts") / item_id / f"{sha[:16]}.json"

    def write_draft(self, content: GoldContent) -> str:
        sha = gold.content_sha(content)
        data = dump_json(gold.content_dict(content))
        path = self.draft_path(content.id, sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise Refused(
                    f"gold/drafts/{content.id}/{path.name} differs from its content; inspect it"
                )
            return sha
        temporary = self.temp_path(path.name)
        write_new(temporary, data)
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise Refused(
                f"gold/drafts/{content.id}/{path.name} appeared meanwhile; inspect it"
            ) from None
        finally:
            temporary.unlink(missing_ok=True)
        return sha

    def load_draft(self, item_id: str, sha: str) -> GoldContent:
        path = self.draft_path(item_id, sha)
        try:
            content = GoldContent.model_validate(json.loads(path.read_bytes()))
        except (OSError, ValueError, ValidationError):
            raise CheckFailed(
                f"gold/drafts/{item_id}/{path.name} is missing or invalid; inspect it"
            ) from None
        if gold.content_sha(content) != sha:
            raise CheckFailed(
                f"gold/drafts/{item_id}/{path.name} does not hash to its name; inspect it"
            )
        return content

    def temp_path(self, name: str) -> Path:
        folder = self.folder(".tmp")
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{name}.{secrets.token_hex(4)}"

    def write_record(self, name: str, file_name: str, document: Mapping) -> None:
        """Commit point: a temp file linked into place, failing if the record exists."""
        folder = self.folder(name)
        folder.mkdir(parents=True, exist_ok=True)
        temporary = self.temp_path(file_name)
        write_new(temporary, dump_json(document))
        os.sync()
        try:
            os.link(temporary, folder / file_name)
        except FileExistsError:
            raise Refused(f"gold/{name}/{file_name} exists; nothing was written") from None
        finally:
            temporary.unlink(missing_ok=True)
        fsync_dir(folder)

    # ------------------------------------------------------------- state

    def heads(self) -> dict[str, dict]:
        heads: dict[str, dict] = {}
        for event in self.events():
            if event["schema"] == INGEST_SCHEMA:
                for entry in event["items"]:
                    if not entry["unchanged"]:
                        heads[entry["item"]] = {
                            "sha256": entry["sha256"],
                            "lane": event["lane"],
                            "drafted_on": event["drafted_on"],
                            "origin": event["ingest_id"],
                            "supersedes": entry["supersedes"],
                        }
            else:
                for entry in event["drafts"]:
                    heads[entry["item"]] = {
                        "sha256": entry["sha256"],
                        "lane": EDIT_LANE,
                        "drafted_on": event["decided_on"],
                        "origin": entry["decision"],
                        "supersedes": entry["supersedes"],
                    }
        return heads

    def decisions(self) -> list[dict]:
        return [
            {**decision, "decided_on": record["decided_on"], "packet_id": record["packet_id"]}
            for record in self.imports()
            for decision in record["decisions"]
        ]

    def effective(self, sha: str, decisions: Sequence[dict] | None = None) -> dict | None:
        """The latest decision that settles this draft: an approve or reject of it, or the edit
        that produced it. An edit never settles the draft it replaced."""
        found = None
        for decision in self.decisions() if decisions is None else decisions:
            if (decision["word"] != "edit" and decision["draft_sha256"] == sha) or (
                decision["word"] == "edit" and decision["result_draft_sha256"] == sha
            ):
                found = decision
        return found

    @staticmethod
    def state_of(sha: str, decision: dict | None) -> str:
        if decision is None:
            return "pending"
        if decision["word"] == "approve" and decision["draft_sha256"] == sha:
            return "chad_accepted"
        if decision["word"] == "edit" and decision["result_draft_sha256"] == sha:
            return "chad_amended"
        if decision["word"] == "reject":
            return "rejected"
        return "pending"

    def outstanding(self) -> dict[tuple[str, str], str]:
        """(item, draft) pairs in an exported packet that has not been imported."""
        imported = {record["packet_id"] for record in self.imports()}
        return {
            (entry["item"], entry["draft_sha256"]): packet["packet_id"]
            for packet in self.packets()
            if packet["packet_id"] not in imported
            for entry in packet["items"]
        }

    def head_items(self, heads: Mapping[str, dict]) -> dict[str, GoldContent]:
        return {item: self.load_draft(item, head["sha256"]) for item, head in heads.items()}


# ------------------------------------------------------------------ ingest


def check_heads(
    candidates: Mapping[str, GoldContent], current: Mapping[str, GoldContent], ctx: Context
) -> list[Problem]:
    """Item checks of the candidates (drafts: no fixture-slice rule) and set checks against the
    current heads, each candidate replacing its own previous head."""
    problems = []
    for item in candidates.values():
        problems += gold.check_item(item, ctx, require_fixture=False)
    merged = {**current, **candidates}
    found, _ = gold.check_set(merged, ctx, focus=candidates)
    return problems + found


def by_item(problems: Sequence[Problem], ids: Sequence[str]) -> dict[str, list[Problem]]:
    """Problems per item: an item's own, a pair's for both items, a set-level one for all."""
    out: dict[str, list[Problem]] = {item: [] for item in ids}
    for problem in problems:
        named = set(problem.path.split()) & set(out)
        for item in named or (out if problem.path == "set" else ()):
            out[item].append(problem)
    return out


def ingest(store: Store, ctx: Context, batch_path: Path, *, supersede_accepted: bool) -> Report:
    try:
        raw = batch_path.read_bytes()
    except OSError:
        raise ConfigError(f"{batch_path.name}: cannot be read") from None
    try:
        batch = gold.DraftBatch.model_validate(json.loads(raw))
    except ValueError as error:
        detail = (
            gold.validation_message(error) if isinstance(error, ValidationError) else str(error)
        )
        raise CheckFailed(f"{batch_path.name}: invalid batch: {detail}") from None
    if privacy_matches(batch.lane):
        raise CheckFailed(f"{batch_path.name}: the lane label has a privacy match")
    if batch.lane == EDIT_LANE:
        raise CheckFailed(f"{batch_path.name}: lane {EDIT_LANE} is reserved for Chad's edits")
    ids = [item.id for item in batch.items]
    if len(ids) != len(set(ids)):
        raise CheckFailed(f"{batch_path.name}: an item id appears twice")
    input_sha = sha256_hex(raw)
    ingest_id = f"GI-{input_sha[:12]}"
    report = Report()
    with store.locked():
        if (store.folder("ingests") / f"{ingest_id}.json").exists():
            raise Refused(f"{batch_path.name} was already ingested as {ingest_id}")
        problems: list[str] = []
        derived: dict[str, GoldContent] = {}
        for item in batch.items:
            content, found = gold.derive(item, ctx)
            problems += [f"gold: {item.id}: {message}" for message in found]
            if content is not None:
                derived[item.id] = content
        if problems:
            raise ProblemsFound(f"{len(problems)} problem(s); nothing written", problems)
        heads = store.heads()
        decisions = store.decisions()
        for item_id, content in derived.items():
            head = heads.get(item_id)
            if head is None or head["sha256"] == gold.content_sha(content):
                continue
            state = store.state_of(head["sha256"], store.effective(head["sha256"], decisions))
            if state in ("chad_accepted", "chad_amended") and not supersede_accepted:
                raise Refused(
                    f"{item_id}: the head is {state}; pass --supersede-accepted to replace it "
                    "(the item returns to pending)"
                )
        current = store.head_items(heads)
        problems = check_heads(derived, current, ctx)
        if problems:
            raise ProblemsFound(f"{len(problems)} problem(s); nothing written", problems)
        entries = []
        for item_id in sorted(derived):
            sha = store.write_draft(derived[item_id])
            head = heads.get(item_id)
            unchanged = head is not None and head["sha256"] == sha
            entries.append(
                {
                    "item": item_id,
                    "sha256": sha,
                    "supersedes": head["sha256"] if head and not unchanged else None,
                    "unchanged": unchanged,
                }
            )
            report.lines.append(f"{item_id}: {'unchanged' if unchanged else 'draft ' + sha[:16]}")
        store.write_record(
            "ingests",
            f"{ingest_id}.json",
            {
                "schema": INGEST_SCHEMA,
                "ingest_id": ingest_id,
                "sequence": store.next_sequence(),
                "lane": batch.lane,
                "drafted_on": batch.drafted_on,
                "input_sha256": input_sha,
                "items": entries,
            },
        )
    report.lines.append(f"ingested {len(entries)} item(s) as {ingest_id}")
    return report


# ------------------------------------------------------------------ packets


def fence(text: str, language: str = "") -> str:
    """A code fence longer than any backtick run in the text."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{language}\n{text.rstrip(chr(10))}\n{ticks}"


def _cell(text: str) -> str:
    return collapse_cell(text).replace("|", "\\|")


def collapse_cell(text: str) -> str:
    return " ".join(str(text).split())


def edit_prefill(item: GoldContent) -> dict:
    data = gold.lane_form(item)
    return {key: data[key] for key in gold.EDIT_FIELDS}


def render_item(item: GoldContent, ctx: Context, prior: dict | None) -> tuple[str, str]:
    """(fixed region, editable region) of one item block."""
    profile, line = ctx.profile(item.profile), ctx.line(item.version_line)
    out = [
        f"<!-- gold:item {item.id} draft={gold.content_sha(item)} -->",
        f"## {item.id} · {item.kind} · {item.split} · {item.category} · {item.profile}",
        "",
        f"Setup: {line.id} (Blender {line.blender}, Bonsai {line.bonsai}) · {profile.ifc_schema} · "
        f"{profile.model_state} · {profile.discipline}",
    ]
    slot = ctx.slots[item.id]
    if slot.get("substitution"):
        out.append(
            f"Slot substitution: planned {slot['substitution']['planned_profile']}, "
            f"reason: {slot['substitution']['reason']}"
        )
    if prior is not None:
        out.append(
            f"Re-decision: the effective decision is {prior['id']} ({prior['word']}, "
            f"{prior['decided_on']})"
        )
    out += [
        "",
        "### Question (input " + gold.INPUT_RENDERING + ")",
        "",
        fence(gold.render_input(item)),
    ]
    if item.parts:
        out += ["", "### Parts", ""]
        for part in item.parts:
            steps = ", ".join(str(s + 1) for s in part.steps)
            out.append(
                f'- {part.id} ({part.category}), span "{collapse_cell(part.span)}", steps {steps}: '
                f"{collapse_cell(part.answer.text)} [{', '.join(part.answer.support)}]"
            )
    ref = item.reference
    out += ["", "### Reference answer", ""]
    out.append(
        f"- answer (payload answer): {collapse_cell(ref.answer.text)} [{', '.join(ref.answer.support)}]"
    )
    out.append("- steps (payload steps):")
    for k, step in enumerate(ref.steps, 1):
        out.append(f"  {k}. {collapse_cell(step.text)} [{', '.join(step.support)}]")
    tools = "; ".join(f"{t.display} ({t.kind} {t.value})" for t in ref.tools)
    out.append(f"- tools (payload tools_required): {tools}")
    for name, label in (("hazard", "safety_info"), ("scope_note", "answer")):
        value = getattr(ref, name)
        if value is not None:
            out.append(
                f"- {name} (payload {label}): {collapse_cell(value.text)} [{', '.join(value.support)}]"
            )
    out.append(f"- assumptions (payload answer): {gold.assumptions_sentence(item, profile, line)}")
    out += ["", "### Cited sections", ""]
    for citation in item.citations:
        record = ctx.record(citation.record_id)
        heading = " > ".join(citation.heading_path) or "(page head)"
        out += [
            f"#### {citation.id} ({citation.role}) {citation.record_id}",
            "",
            f"{heading} · lines {citation.line_start}-{citation.line_end}",
            "",
            fence(
                record["text"] if isinstance(record, dict) else f"(unavailable: {record})", "rst"
            ),
            "",
        ]
        for quote in citation.quotes:
            out.append(
                f'- {citation.id}.{quote.id} (line {quote.line}): "{collapse_cell(quote.text)}"'
            )
        out.append("")
    out += ["### Check patterns", ""]
    out.append(
        "| id | polarity | kind | value | field | part | accepted forms | matches reference |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    tools_by_id = gold.pattern_tools(item, ctx, line)
    fields = gold.pseudo_payload(item, ctx)
    for pattern in item.patterns:
        tool = tools_by_id.get(pattern.id)
        forms = ", ".join([tool.value, *tool.forms]) if tool else "(text)"
        hit = gp.matches(pattern.model_dump(), gp.field_text(fields, pattern.field), tool)
        out.append(
            "| "
            + " | ".join(
                _cell(v)
                for v in (
                    pattern.id,
                    pattern.polarity,
                    pattern.kind,
                    pattern.value,
                    pattern.field,
                    pattern.part or "",
                    forms,
                    "yes" if hit else "no",
                )
            )
            + " |"
        )
    rows = {row.id: row for row in ctx.facts.rows}
    if item.setup_facts:
        out += ["", "### Setup facts", ""]
        for fact in item.setup_facts:
            row = rows[fact]
            out.append(f"- {fact} ({row.status}): {collapse_cell(row.claim)}")
    if item.unusual is not None:
        out += [
            "",
            "### Unusual",
            "",
            f"- {item.unusual.reason}: {collapse_cell(item.unusual.note)}",
        ]
    if item.injection is not None:
        planted = item.injection
        out += [
            "",
            "### Injection",
            "",
            f"- vector {planted.vector}, planted in the {planted.location}",
            f"- goal: {collapse_cell(planted.goal)}",
            f"- expected behaviour: {', '.join(planted.expected_behaviour)}",
            "",
            fence(planted.planted_text),
        ]
    if item.control is not None:
        control = item.control
        out += [
            "",
            "### Control (benign look-alike; must be answered, not refused)",
            "",
            f"- vector {control.vector}, look-alike text in the {control.location}",
            f"- expected behaviour: {', '.join(control.expected_behaviour)}",
            "",
            fence(control.lookalike_text),
        ]
    out += [
        "",
        f"Checker: passed ({gold.CHECKER}). To edit, change the JSON below in place (lane form: "
        "derived fields are filled in again) and write DECISION: edit.",
        DECIDE_MARK.format(item.id),
    ]
    editable = [
        "DECISION:",
        "NOTE:",
        fence(json.dumps(edit_prefill(item), indent=2, ensure_ascii=False), "json"),
        END_MARK.format(item.id),
    ]
    fixed = "\n".join(out)
    if any(gold.packet_marker(chunk) for chunk in fixed.split("\n")[1:-1]):
        raise CheckFailed(f"{item.id}: rendered text holds a packet marker; it cannot be exported")
    return normalized(fixed), "\n".join(editable) + "\n"


def header_text(packet_id: str, split: str, count: int, exported_on: str) -> str:
    return normalized(
        "\n".join(
            [
                f"# Gold review packet {packet_id} ({split}, {count} items)",
                "",
                f"Exported {exported_on} with {gold.CHECKER}. For each item, write one word after "
                "DECISION: approve, edit or reject. Leave it blank to decide later; the item stays "
                "pending and a later export includes it again.",
                "",
                "The NOTE line is optional and one line. Notes stay in data/gold/imports/ and never "
                "enter Git.",
                "",
                "To edit, change the JSON block of the item in place and write DECISION: edit. The "
                "JSON is the lane form: citations name a record id and quotes; every derived field "
                "is filled in again and the whole checker runs on the edited item. unusual.note "
                "cannot be changed by an edit.",
                "",
                "Do not change anything from an item's `gold:item` line to its `gold:decide` line, "
                "or this header; the import refuses a changed packet and names the first changed "
                "line. Whitespace at line ends and line-ending style do not matter.",
                "",
                f"Import from an interactive terminal: bonsai-help gold packet import {packet_id}",
            ]
        )
    )


def export_packets(
    store: Store,
    ctx: Context,
    split: str,
    *,
    size: int,
    items: Sequence[str] | None,
    exported_on: str,
) -> Report:
    if size < 1:
        raise ConfigError("--size must be at least 1")
    report = Report()
    with store.locked():
        heads = store.heads()
        decisions = store.decisions()
        outstanding = store.outstanding()
        chosen = []
        if items:
            for item_id in items:
                if item_id not in heads:
                    raise ConfigError(f"{item_id} has no draft")
                if ctx.slots.get(item_id, {}).get("split") != split:
                    raise ConfigError(f"{item_id} is not a {split} item")
                waiting = outstanding.get((item_id, heads[item_id]["sha256"]))
                if waiting is not None:
                    # Two unimported packets with one draft would strand the older one.
                    raise ConfigError(
                        f"{item_id} is in {waiting}, not yet imported; import {waiting} first "
                        "(a blank DECISION leaves it pending)"
                    )
            chosen = sorted(set(items))
        else:
            for item_id in sorted(heads):
                sha = heads[item_id]["sha256"]
                if ctx.slots.get(item_id, {}).get("split") != split:
                    continue
                if store.state_of(sha, store.effective(sha, decisions)) != "pending":
                    continue
                if (item_id, sha) in outstanding:
                    report.lines.append(
                        f"{item_id}: in {outstanding[(item_id, sha)]}, not yet imported"
                    )
                    continue
                chosen.append(item_id)
        current = store.head_items(heads)
        grouped = by_item(check_heads({i: current[i] for i in chosen}, current, ctx), chosen)
        ready = []
        for item_id in chosen:
            if grouped[item_id]:
                report.lines.append(
                    f"{item_id}: skipped, fails the check ({len(grouped[item_id])} problem(s))"
                )
                report.warnings += [str(p) for p in grouped[item_id]]
            else:
                ready.append(item_id)
        numbers = [int(p["packet_id"][3:]) for p in store.packets()]
        number = max(numbers, default=0)
        for start in range(0, len(ready), size):
            number += 1
            batch = ready[start : start + size]
            packet_id = f"GP-{number:03d}"
            report.lines.append(
                _write_packet(
                    store,
                    ctx,
                    packet_id,
                    split,
                    batch,
                    current,
                    heads,
                    decisions,
                    bool(items),
                    exported_on,
                )
            )
    if not any(line.startswith("GP-") for line in report.lines):
        report.lines.append(f"no {split} item is ready for review")
    return report


def _write_packet(
    store, ctx, packet_id, split, batch, current, heads, decisions, redecision, exported_on
) -> str:
    blocks, entries = [], []
    for item_id in batch:
        item = current[item_id]
        sha = heads[item_id]["sha256"]
        prior = store.effective(sha, decisions) if redecision else None
        fixed, editable = render_item(item, ctx, prior)
        blocks.append(fixed + editable)
        entries.append(
            {
                "item": item_id,
                "draft_sha256": sha,
                "redecision": redecision,
                "setup_sha256": gold.setup_sha(item, ctx),
                "fixed_sha256": sha256_hex(fixed.encode()),
                "fixed_text": fixed,
            }
        )
    header = header_text(packet_id, split, len(batch), exported_on)
    body = {
        "schema": PACKET_SCHEMA,
        "packet_id": packet_id,
        "split": split,
        "exported_on": exported_on,
        "header_text": header,
        "digests": _staleness_digests(ctx),
        "items": entries,
    }
    manifest = {**body, "digest": sha256_hex(canonical(body))}
    markdown = (
        f"<!-- gold:packet {packet_id} v1 sha256={manifest['digest']} -->\n"
        + header
        + "\n"
        + "\n".join(blocks)
    )
    folder = store.folder("packets")
    folder.mkdir(parents=True, exist_ok=True)
    write_new(folder / f"{packet_id}.md", markdown.encode())
    write_new(folder / f"{packet_id}.json", dump_json(manifest))
    return f"{packet_id}: {len(batch)} {split} item(s) in gold/packets/{packet_id}.md"


def _staleness_digests(ctx: Context) -> dict:
    return {key: ctx.digests[key] for key in ("checker", "lexicons", "docs_index", "slots", "pins")}


# ------------------------------------------------------------------ import


def _first_difference(expected: str, found: str, offset: int) -> str:
    want, got = expected.split("\n"), found.split("\n")
    for k, (a, b) in enumerate(zip(want, got, strict=False)):
        if a != b:
            return f"line {offset + k + 1}"
    return f"line {offset + min(len(want), len(got)) + 1}"


def parse_packet(text: str, manifest: Mapping) -> tuple[list[dict], list[str]]:
    """Blocks of a returned packet, checked against its manifest; problems mean tampering or a
    malformed decision region."""
    lines = normalized(text).split("\n")
    problems: list[str] = []
    marks = [(k, ITEM_MARK.fullmatch(line)) for k, line in enumerate(lines)]
    marks = [(k, m) for k, m in marks if m]
    first = marks[0][0] if marks else len(lines)
    header = normalized("\n".join(lines[1:first]))
    if header != manifest["header_text"]:
        problems.append(
            f"tampered: the header changed at {_first_difference(manifest['header_text'], header, 1)}"
        )
    expected = [(e["item"], e["draft_sha256"]) for e in manifest["items"]]
    found_ids = [(m["id"], m["sha"]) for _, m in marks]
    if found_ids != expected:
        problems.append("tampered: blocks are missing, extra, reordered or name another draft")
        return [], problems
    blocks = []
    for ordinal, ((start, mark), entry) in enumerate(zip(marks, manifest["items"], strict=True), 1):
        stop = marks[ordinal][0] if ordinal < len(marks) else len(lines)
        item_id = mark["id"]
        decide = next(
            (k for k in range(start, stop) if lines[k] == DECIDE_MARK.format(item_id)), None
        )
        end = next((k for k in range(start, stop) if lines[k] == END_MARK.format(item_id)), None)
        if decide is None or end is None or end < decide:
            problems.append(f"{item_id}: tampered: its gold:decide or gold:end line is missing")
            continue
        fixed = normalized("\n".join(lines[start : decide + 1]))
        if sha256_hex(fixed.encode()) != entry["fixed_sha256"]:
            where = _first_difference(entry["fixed_text"], fixed, start)
            problems.append(f"{item_id}: tampered: the fixed region changed at {where}")
            continue
        if any(line.strip() for line in lines[end + 1 : stop]):
            problems.append(f"{item_id}: text after its gold:end line")
            continue
        parsed, found = _decision_region(lines[decide + 1 : end], item_id)
        problems += found
        if parsed is not None:
            blocks.append({**parsed, "item": item_id, "ordinal": ordinal, "entry": entry})
    return blocks, problems


def _decision_region(region: Sequence[str], item_id: str) -> tuple[dict | None, list[str]]:
    decision = note = None
    body: list[str] | None = None
    k = 0
    problems = []
    while k < len(region):
        line = region[k]
        stripped = line.strip()
        opening = FENCE_OPEN.fullmatch(stripped)
        if not stripped:
            k += 1
        elif line.startswith("DECISION:"):
            if decision is not None:
                problems.append(f"{item_id}: more than one DECISION line")
            decision = line[len("DECISION:") :].strip()
            k += 1
        elif line.startswith("NOTE:"):
            if note is not None:
                problems.append(f"{item_id}: more than one NOTE line")
            note = line[len("NOTE:") :].strip()
            k += 1
        elif opening and body is None:
            close = next(
                (j for j in range(k + 1, len(region)) if region[j].strip() == opening["ticks"]),
                None,
            )
            if close is None:
                problems.append(f"{item_id}: the JSON fence is not closed")
                break
            body = list(region[k + 1 : close])
            k = close + 1
        else:
            problems.append(f"{item_id}: unexpected text in the decision region: {stripped[:40]!r}")
            k += 1
    if decision is None:
        problems.append(f"{item_id}: the DECISION line is missing")
    elif decision not in ("", *WORDS):
        problems.append(f"{item_id}: DECISION is {decision!r}; write approve, edit or reject")
    fence_value = None
    if body is not None and "\n".join(body).strip():
        try:
            fence_value = json.loads("\n".join(body))
        except ValueError as error:
            problems.append(f"{item_id}: the JSON block is not valid JSON ({error})")
    if problems:
        return None, problems
    return {"word": decision, "note": note or "", "fence": fence_value}, []


def import_packet(
    store: Store,
    ctx: Context,
    packet: str,
    *,
    decided_on: str,
    skip_stale: bool,
    confirm: Callable[[str], bool],
) -> Report:
    """Validate a returned packet completely, ask for confirmation, then record it (append-only)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", decided_on):
        raise ConfigError("--decided-on is a date, YYYY-MM-DD")
    match = re.fullmatch(r"(?:.*/)?(GP-\d{3})(?:\.md)?", packet)
    if match is None:
        raise ConfigError(f"{packet}: name a packet as GP-NNN or its .md file")
    packet_id = match.group(1)
    report = Report()
    with store.locked():
        if (store.folder("imports") / f"{packet_id}.json").exists():
            raise Refused(f"{packet_id} was already imported; export the pending items again")
        try:
            manifest = json.loads((store.folder("packets") / f"{packet_id}.json").read_bytes())
            text = (store.folder("packets") / f"{packet_id}.md").read_bytes().decode("utf-8")
        except (OSError, ValueError):
            raise CheckFailed(f"{packet_id}: packet or manifest missing or unreadable") from None
        body = {key: value for key, value in manifest.items() if key != "digest"}
        mark = PACKET_MARK.fullmatch(normalized(text).split("\n")[0])
        if (
            manifest.get("digest") != sha256_hex(canonical(body))
            or mark is None
            or mark["id"] != packet_id
            or mark["sha"] != manifest["digest"]
        ):
            raise ProblemsFound(
                "packet tampered; nothing written", [f"{packet_id}: tampered header or manifest"]
            )
        blocks, problems = parse_packet(text, manifest)
        if problems:
            raise ProblemsFound(f"{len(problems)} problem(s); nothing written", problems)
        heads = store.heads()
        decisions = store.decisions()
        current = store.head_items(heads)
        stale_digests = manifest["digests"] != _staleness_digests(ctx)
        reviewed = [b["item"] for b in blocks if b["item"] in current]
        grouped = by_item(check_heads({i: current[i] for i in reviewed}, current, ctx), reviewed)
        stale, errors, accepted, decided = [], [], [], []
        edited: dict[str, GoldContent] = {}
        for block in blocks:
            item_id, entry = block["item"], block["entry"]
            head = heads.get(item_id)
            if (
                stale_digests
                or head is None
                or head["sha256"] != entry["draft_sha256"]
                or gold.setup_sha(current[item_id], ctx) != entry["setup_sha256"]
            ):
                stale.append(item_id)
                continue
            draft = current[item_id]
            prior = store.effective(head["sha256"], decisions)
            if prior is not None and not entry["redecision"]:
                untouched = block["fence"] in (None, {}) or block["fence"] == edit_prefill(draft)
                if block["word"] or block["note"] or not untouched:
                    errors.append(
                        f"{item_id}: already decided by {prior['id']}; leave its DECISION blank "
                        "to import this packet's other items, then export it with --items"
                    )
                else:
                    decided.append(item_id)
                continue
            if grouped[item_id]:
                stale.append(item_id)
                continue
            outcome = _apply(block, draft, ctx, current)
            if isinstance(outcome, list):
                errors += outcome
                continue
            if outcome is not None:
                edited[item_id] = outcome
            accepted.append(block)
        if len(edited) > 1 and not errors:
            # Each edit was checked against the old heads; together they must pass as well.
            errors += [
                f"edits fail the check together: {p}" for p in check_heads(edited, current, ctx)
            ]
        if errors:
            raise ProblemsFound(f"{len(errors)} problem(s); nothing written", errors)
        if stale and not skip_stale:
            raise ProblemsFound(
                f"{len(stale)} stale block(s); nothing written (--skip-stale imports the rest)",
                [
                    f"{item}: stale: the draft, its setup, its check or the lexicons, index or "
                    "slots changed"
                    for item in stale
                ],
            )
        words = Counter(block["word"] or "blank" for block in accepted)
        summary = ", ".join(f"{count} {word}" for word, count in sorted(words.items()))
        if not confirm(f"{packet_id}: {summary or 'nothing to record'}"):
            raise ConfigError("import not confirmed; nothing written")
        sequence = store.next_sequence()
        records, drafts, notes, pending = [], [], {}, []
        for block in accepted:
            item_id = block["item"]
            if not block["word"]:
                pending.append(item_id)
                continue
            decision_id = f"{packet_id}.{block['ordinal']:02d}"
            head = heads[item_id]["sha256"]
            prior = store.effective(head, decisions)
            result = None
            setup_of = current[item_id]
            if block["word"] == "edit":
                result = store.write_draft(edited[item_id])
                setup_of = edited[item_id]
                drafts.append(
                    {"item": item_id, "sha256": result, "supersedes": head, "decision": decision_id}
                )
            records.append(
                {
                    "id": decision_id,
                    "item": item_id,
                    "word": block["word"],
                    "draft_sha256": head,
                    "result_draft_sha256": result,
                    "supersedes": prior["id"] if prior else None,
                    "redecision": block["entry"]["redecision"],
                    "setup_sha256": gold.setup_sha(setup_of, ctx),
                }
            )
            if block["note"]:
                notes[decision_id] = block["note"]
        store.write_record(
            "imports",
            f"{packet_id}.json",
            {
                "schema": IMPORT_SCHEMA,
                "packet_id": packet_id,
                "sequence": sequence,
                "decided_on": decided_on,
                "decisions": records,
                "drafts": drafts,
                "notes": notes,
                "pending": pending,
                "skipped_stale": stale,
                "already_decided": decided,
            },
        )
    report.lines.append(
        f"{packet_id}: {len(records)} decision(s) recorded, {len(pending)} left pending, "
        f"{len(stale)} stale block(s) skipped"
        + (f", {len(decided)} blank block(s) of already decided drafts ignored" if decided else "")
    )
    return report


def _apply(
    block: Mapping, draft: GoldContent, ctx: Context, current
) -> GoldContent | None | list[str]:
    item_id, word, fence_value = block["item"], block["word"], block["fence"]
    prefill = edit_prefill(draft)
    unchanged = fence_value in (None, {}) or fence_value == prefill
    if word in ("approve", "reject", ""):
        if not unchanged:
            return [f"{item_id}: the JSON changed; write DECISION: edit to keep the changes"]
        if not word and block["note"]:
            return [f"{item_id}: a NOTE needs a decision"]
        return None
    if not isinstance(fence_value, dict):
        return [f"{item_id}: an edit needs the JSON object of the item's editable fields"]
    refused = sorted(set(fence_value) - set(gold.EDIT_FIELDS))
    if refused:
        return [f"{item_id}: an edit cannot change {', '.join(refused)}"]
    changed = {key: value for key, value in fence_value.items() if prefill.get(key) != value}
    if not changed:
        return [f"{item_id}: DECISION is edit but nothing changed"]
    old_note = draft.unusual.note if draft.unusual else None
    new_unusual = changed.get("unusual", prefill["unusual"])
    if isinstance(new_unusual, dict) and new_unusual.get("note") != old_note:
        return [f"{item_id}: an edit cannot change unusual.note (reviewer text stays out of Git)"]
    lane = {**gold.lane_form(draft), **changed}
    try:
        lane_item = gold.LaneItem.model_validate(lane)
    except ValidationError as error:
        return [f"{item_id}: edit invalid: {gold.validation_message(error)}"]
    content, found = gold.derive(lane_item, ctx)
    if content is None:
        return [f"{item_id}: edit: {message}" for message in found]
    problems = check_heads({item_id: content}, current, ctx)
    if problems:
        return [f"{item_id}: edit fails the check: {p.message}" for p in problems]
    return content


# ------------------------------------------------------------------ publish and status


def accepted_items(store: Store) -> list[gold.PublishedItem]:
    heads = store.heads()
    decisions = store.decisions()
    out = []
    for item_id, head in sorted(heads.items()):
        decision = store.effective(head["sha256"], decisions)
        state = store.state_of(head["sha256"], decision)
        if state not in ("chad_accepted", "chad_amended"):
            continue
        content = store.load_draft(item_id, head["sha256"])
        out.append(
            gold.PublishedItem.model_validate(
                {
                    **gold.content_dict(content),
                    "draft": head,
                    "review": {
                        "status": state,
                        "words": decision["word"],
                        "decided_on": decision["decided_on"],
                        "packet_id": decision["packet_id"],
                        "decision_id": decision["id"],
                        "reviewed_draft_sha256": decision["draft_sha256"],
                        "setup_sha256": decision["setup_sha256"],
                    },
                }
            )
        )
    return out


def publish(store: Store, ctx: Context, gold_dir: Path, *, write: bool) -> Report:
    """Build both split files from Chad's accepted and amended heads; NOTE text is never read."""
    with store.locked():
        items = accepted_items(store)
    problems: list[Problem] = []
    for item in items:
        problems += gold.check_item(item, ctx, require_fixture=True)
        problems += [Problem("gold", item.id, m) for m in gold.check_published_item(item, ctx)]
    found, _ = gold.check_set({i.id: i for i in items}, ctx, final=True)
    problems += found
    if problems:
        raise ProblemsFound(f"{len(problems)} problem(s); nothing published", problems)
    documents = {
        split: gold.published_document(split, [i for i in items if i.split == split], ctx.digests)
        for split in gold.SPLIT_FILES
    }
    return gold.write_published(gold_dir, documents, write=write)


def published_ids(gold_dir: Path) -> set[str]:
    ids = set()
    for split in gold.SPLIT_FILES:
        if split == "held_out":
            _, items, _ = gold.load_held_out(gold_dir)
        else:
            _, items, _ = gold._load_split(gold_dir, split)
        ids |= {item.id for item in items}
    return ids


def status(store: Store, ctx: Context, gold_dir: Path) -> Report:
    """Per slot: head, check, decision state, published; a decided head whose setup changed
    since the decision is a warning. Never shows NOTE text."""
    report = Report()
    if (store.root / ".lock").exists():
        report.warnings.append("gold/.lock exists: a gold command is running or was interrupted")
    temporary = (
        sorted(p.name for p in store.folder(".tmp").glob("*"))
        if store.folder(".tmp").is_dir()
        else []
    )
    for name in temporary:
        report.warnings.append(f"leftover gold/.tmp/{name} from an interrupted write; inspect it")
    heads = store.heads()
    decisions = store.decisions()
    known = {(e["item"], e["sha256"][:16]) for ev in store.ingests() for e in ev["items"]}
    known |= {(d["item"], d["sha256"][:16]) for ev in store.imports() for d in ev["drafts"]}
    drafts = store.folder("drafts")
    for path in sorted(drafts.glob("*/*.json")) if drafts.is_dir() else []:
        if (path.parent.name, path.stem) not in known:
            report.warnings.append(
                f"orphan draft gold/drafts/{path.parent.name}/{path.name}; inspect it"
            )
    outstanding = store.outstanding()
    for packet in sorted(set(outstanding.values())):
        report.warnings.append(f"{packet} exported, not yet imported")
    published = published_ids(gold_dir)
    current = store.head_items(heads)
    grouped = by_item(check_heads(current, current, ctx), list(current))
    states: Counter[str] = Counter()
    unusual: Counter[str] = Counter()
    for slot_id, slot in sorted(ctx.slots.items()):
        head = heads.get(slot_id)
        if head is None:
            state, check, shown = "empty", "-", "-"
        else:
            decision = store.effective(head["sha256"], decisions)
            state = store.state_of(head["sha256"], decision)
            check = "fail" if grouped[slot_id] else "pass"
            shown = head["sha256"][:16]
            item = current[slot_id]
            if state in ("chad_accepted", "chad_amended") and decision[
                "setup_sha256"
            ] != gold.setup_sha(item, ctx):
                report.warnings.append(
                    f"{slot_id}: its profile, version line or cited fact claims changed since "
                    f"Chad's decision; export it with --items for a re-decision (G22)"
                )
            if item.unusual is not None:
                unusual[item.unusual.reason] += 1
        states[state] += 1
        report.lines.append(
            f"{slot_id}\t{slot['category']}\t{slot['profile']}\thead={shown}\tcheck={check}\t"
            f"state={state}\tpublished={'yes' if slot_id in published else 'no'}"
        )
    for (kind, split), target in gold.TARGETS.items():
        filled = sum(
            1
            for s in heads
            if ctx.slots.get(s, {}).get("kind") == kind and ctx.slots[s]["split"] == split
        )
        report.lines.append(f"{kind} {split}: {filled} of {target} slots drafted")
    report.lines.append("states: " + ", ".join(f"{k} {v}" for k, v in sorted(states.items())))
    report.lines.append(
        "unusual: " + (", ".join(f"{k} {v}" for k, v in sorted(unusual.items())) or "none")
    )
    return report
