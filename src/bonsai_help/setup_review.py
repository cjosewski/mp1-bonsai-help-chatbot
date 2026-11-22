"""Chad's review of the B2 drafts: fact rows, profiles and version lines (B3).

The second record type of the review packets: the same Markdown format, block markers,
tamper and stale checks and append-only import as the gold items (`gold_review`), for the
records of `reference/setup-profiles.json` and `reference/setup-facts.json`. Everything here
lives outside Git under `data/setup-review/` (git-ignored):

    .lock, .tmp/                  as for the gold store
    packets/SR-NNN.md, .json      review packet and its manifest
    imports/SR-NNN.json           Chad's decisions, NOTE text and edit results (append-only)

A decision binds to the record's content (`setup.record_sha`: everything but its status and
review). `setup review apply --write` is the only writer of a record's status and review:
it sets them from the imported decisions, writes an edit's result, and returns a record
whose content changed since its decision to `assistant_drafted`. Without `--write` it
compares (exit 1 on a difference). Only Chad writes a packet's DECISION and NOTE lines and
its edit JSON, and only Chad runs the import (interactive terminal, typed confirmation).
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

from pydantic import BaseModel, ValidationError

from bonsai_help import gold, setup
from bonsai_help.doc_snapshot import CheckFailed, Problem, Report, dump_json, write_new
from bonsai_help.doc_sources import ConfigError, DocSources, Refused, canonical, sha256_hex
from bonsai_help.gold_review import (
    DECIDE_MARK,
    END_MARK,
    PACKET_MARK,
    ProblemsFound,
    Store,
    collapse_cell,
    fence,
    normalized,
    parse_packet,
)

PACKET_SCHEMA = "setup-packet-v1"
IMPORT_SCHEMA = "setup-import-v1"
DEFAULT_SIZE = 25
PACKET_NAME = re.compile(r"(?:.*/)?(SR-\d{3})(?:\.md)?")
KINDS = {"VL": "version_line", "SP": "profile", "SF": "fact"}
LABELS = {"version_line": "version line", "profile": "setup profile", "fact": "fact row"}
MODELS: dict[str, type[BaseModel]] = {
    "version_line": setup.VersionLine,
    "profile": setup.Profile,
    "fact": setup.FactRow,
}
# What an edit may change. Ids, a profile's line and split (the gold slot plan depends on
# them), a row's drafting date and the assistant's own note are fixed, so reviewer text
# reaches Git only as a reviewed field's new value.
EDIT_FIELDS = {
    "version_line": (
        "blender",
        "bonsai",
        "bonsai_tag",
        "sources",
        "pairing_status",
        "pairing_note",
        "claims",
    ),
    "profile": ("ifc_schema", "discipline", "model_state"),
    "fact": (
        "kind",
        "topic",
        "applies_to",
        "claim",
        "key_terms",
        "citations",
        "absent_in",
        "conflicts_with",
        "candidate_rule",
    ),
}
STATUS = {"approve": "chad_accepted", "edit": "chad_amended", "reject": "chad_rejected"}


def kind_of(record_id: str) -> str:
    return KINDS[record_id[:2]]


@dataclass
class SetupState:
    """The parsed setup files and what rendering and checking them reads: page bytes
    (snapshots; the fixture slice in tests) and, in full mode, the built index."""

    config: DocSources
    manifest: Mapping
    profiles: setup.SetupProfiles
    facts: setup.SetupFacts
    read: Callable[[str, str], bytes | None]
    index: Mapping[str, str] | None = None
    _pages: dict = dataclass_field(default_factory=dict)

    def page(self, source_id: str, path: str) -> tuple[bytes | None, list[dict] | str]:
        key = (source_id, path)
        if key not in self._pages:
            self._pages[key] = gold.load_page(self.config, self.manifest, self.read, *key)
        return self._pages[key]

    def record(self, record_id: str) -> dict | str:
        return gold.find_record(self.page, record_id)

    def records(self) -> dict[str, BaseModel]:
        """Version lines, profiles and fact rows, in review order."""
        ordered = (
            *self.profiles.version_lines,
            *sorted(self.profiles.profiles, key=lambda p: p.id),
            *sorted(self.facts.rows, key=lambda r: r.id),
        )
        return {record.id: record for record in ordered}

    def check(
        self,
        profiles: setup.SetupProfiles | None = None,
        facts: setup.SetupFacts | None = None,
    ) -> list[Problem]:
        return setup.check_documents(
            self.config,
            self.manifest,
            profiles or self.profiles,
            facts or self.facts,
            self.read,
            self.index,
        )


def settling(sha: str, decisions: Sequence[dict]) -> dict | None:
    """The latest decision on this content: an approve, edit or reject of it, or the edit
    that produced it. (Unlike a gold head, the file keeps the reviewed content until
    `apply` writes an edit's result, so an edit of it settles it too.)"""
    found = None
    for decision in decisions:
        if decision["draft_sha256"] == sha or decision["result_draft_sha256"] == sha:
            found = decision
    return found


def edit_prefill(record: BaseModel) -> dict:
    """A record's editable fields; a fact row's citations as a record id and a quote."""
    kind = kind_of(record.id)
    content = setup.record_content(record)
    data = {key: content[key] for key in EDIT_FIELDS[kind]}
    if kind == "fact":
        data["citations"] = [
            {"record_id": c["record_id"], "quote": c["quote"]} for c in content["citations"]
        ]
    return data


# ------------------------------------------------------------------ rendering


def _fact(row: setup.FactRow, state: SetupState) -> list[str]:
    rows = {r.id: r for r in state.facts.rows}
    out = [
        f"- kind: {row.kind} · topic: {collapse_cell(row.topic)}",
        f"- applies to: {', '.join(row.applies_to.version_lines)}; "
        f"{', '.join(row.applies_to.ifc_schemas)}",
        f"- claim: {collapse_cell(row.claim)}",
        "- key terms: " + ", ".join(f'"{collapse_cell(term)}"' for term in row.key_terms),
        f"- candidate rule: {row.candidate_rule} · drafted on {row.drafted_on}",
    ]
    if row.note:
        out.append(f"- assistant's note: {collapse_cell(row.note)}")
    for other in row.conflicts_with:
        claim = collapse_cell(rows[other].claim) if other in rows else "(unknown row)"
        out.append(f"- conflicts with {other}: {claim}")
    for absence in row.absent_in:
        out.append(f'- absent in {absence.source}:{absence.path}: "{collapse_cell(absence.text)}"')
    lines = [line.id for line in state.profiles.version_lines if row.id in line.claims]
    if lines:
        out.append(f"- a claim of version line(s): {', '.join(lines)}")
    out += ["", "### Cited sections", ""]
    grouped: dict[str, list[tuple[int, setup.Citation]]] = {}
    for number, citation in enumerate(row.citations, 1):
        grouped.setdefault(citation.record_id, []).append((number, citation))
    for record_id, citations in grouped.items():
        first = citations[0][1]
        record = state.record(record_id)
        heading = " > ".join(first.heading_path) or "(page head)"
        text = record["text"] if isinstance(record, dict) else f"(unavailable: {record})"
        out += [
            f"#### {record_id}",
            "",
            f"{heading} · lines {first.line_start}-{first.line_end}",
            "",
            fence(text, "rst"),
            "",
        ]
        for number, citation in citations:
            out.append(
                f'- citation {number} (line {citation.quote_line}): "{collapse_cell(citation.quote)}"'
            )
        out.append("")
    return out


def _profile(profile: setup.Profile, state: SetupState) -> list[str]:
    line = next((v for v in state.profiles.version_lines if v.id == profile.version_line), None)
    shown = f"{line.id} (Blender {line.blender}, Bonsai {line.bonsai})" if line else "(unknown)"
    out = [f"- version line: {shown}", f"- split: {profile.split}"]
    for attr in ("ifc_schema", "discipline", "model_state"):
        basis = state.profiles.enums[attr]
        detail = basis.basis
        if basis.facts:
            detail += f", fact rows {', '.join(basis.facts)}"
        if basis.cited_for:
            detail += f", cited for {', '.join(basis.cited_for)}"
        out.append(f"- {attr}: {getattr(profile, attr)} (enum basis: {detail})")
        if basis.note:
            out.append(f"  - enum note: {collapse_cell(basis.note)}")
    applying = [
        r.id
        for r in state.facts.rows
        if profile.version_line in r.applies_to.version_lines
        and profile.ifc_schema in r.applies_to.ifc_schemas
    ]
    out.append(f"- fact rows that apply to it: {', '.join(applying) or 'none'}")
    return out


def _line(line: setup.VersionLine, state: SetupState) -> list[str]:
    rows = {r.id: r for r in state.facts.rows}
    out = [
        f"- Blender {line.blender} · Bonsai {line.bonsai} · tag {line.bonsai_tag} · "
        f"origin {line.origin}",
        f"- pairing {line.pairing_status}: {collapse_cell(line.pairing_note)}",
        "- sources:",
    ]
    for role, source_id in line.sources.model_dump().items():
        entry = state.manifest["sources"].get(source_id)
        if entry is None:
            out.append(f"  - {role}: {source_id} (not in the manifest)")
            continue
        ref = entry["repository"]["ref"]
        out.append(
            f"  - {role}: {source_id} (pin {entry['pin_id']}, {ref['kind']} {ref['name']}, "
            f"commit {entry['repository']['commit'][:12]})"
        )
    profiles = [p.id for p in state.profiles.profiles if p.version_line == line.id]
    out += [f"- profiles: {', '.join(profiles) or 'none'}", "", "### Claims", ""]
    for claim in line.claims:
        row = rows.get(claim)
        text = f"({row.status}) {collapse_cell(row.claim)}" if row else "(unknown row)"
        out.append(f"- {claim} {text}")
    return out


RENDERERS = {"version_line": _line, "profile": _profile, "fact": _fact}


def render_record(record: BaseModel, state: SetupState, prior: dict | None) -> str:
    """The fixed region of one record's block (its editable region is the gold one)."""
    kind = kind_of(record.id)
    out = [
        f"<!-- gold:item {record.id} draft={setup.record_sha(record)} -->",
        f"## {record.id} · {LABELS[kind]} · {record.status}",
        "",
    ]
    if prior is not None:
        out += [
            f"Re-decision: the effective decision is {prior['id']} ({prior['word']}, "
            f"{prior['decided_on']})",
            "",
        ]
    out += RENDERERS[kind](record, state)
    out += [
        "",
        "To edit, change the JSON below in place and write DECISION: edit. A fact row's "
        "citations are a record id and a verbatim quote; the other citation fields are filled "
        "in again, and the whole setup check runs on the edited record.",
        DECIDE_MARK.format(record.id),
    ]
    fixed = "\n".join(out)
    if any(gold.packet_marker(chunk) for chunk in fixed.split("\n")[1:-1]):
        raise CheckFailed(
            f"{record.id}: rendered text holds a packet marker; it cannot be exported"
        )
    return normalized(fixed)


def editable_region(record: BaseModel) -> str:
    return (
        "\n".join(
            [
                "DECISION:",
                "NOTE:",
                fence(json.dumps(edit_prefill(record), indent=2, ensure_ascii=False), "json"),
                END_MARK.format(record.id),
            ]
        )
        + "\n"
    )


def header_text(packet_id: str, count: int, exported_on: str) -> str:
    return normalized(
        "\n".join(
            [
                f"# Setup review packet {packet_id} ({count} records)",
                "",
                f"Exported {exported_on}. The records are the B2 drafts: version lines, setup "
                "profiles and cited fact rows. For each record, write one word after DECISION: "
                "approve, edit or reject. Leave it blank to decide later; the record stays "
                "pending and a later export includes it again.",
                "",
                "The NOTE line is optional and one line. Notes stay in data/setup-review/imports/ "
                "and never enter Git.",
                "",
                "To edit, change the JSON block of the record in place and write DECISION: edit. "
                "Ids, a profile's version line and split, a row's drafting date and the "
                "assistant's note cannot be changed by an edit.",
                "",
                "Do not change anything from a record's `gold:item` line to its `gold:decide` "
                "line, or this header; the import refuses a changed packet and names the first "
                "changed line. Whitespace at line ends and line-ending style do not matter.",
                "",
                f"Import from an interactive terminal: bonsai-help setup review import {packet_id}",
                "Then write the decisions into the setup files: bonsai-help setup review apply "
                "--write",
            ]
        )
    )


# ------------------------------------------------------------------ export


def export_packets(
    store: Store,
    state: SetupState,
    *,
    size: int,
    records: Sequence[str] | None,
    exported_on: str,
) -> Report:
    """Packets of pending records (no decision settles their content), or of `records` for a
    re-decision. The setup files must pass the whole setup check first."""
    if size < 1:
        raise ConfigError("--size must be at least 1")
    report = Report()
    with store.locked():
        problems = state.check()
        if problems:
            raise ProblemsFound(
                f"{len(problems)} setup check problem(s); fix them before export; nothing written",
                problems,
            )
        current = state.records()
        decisions = store.decisions()
        outstanding = store.outstanding()
        if records:
            for record_id in records:
                if record_id not in current:
                    raise ConfigError(f"{record_id} is not a fact row, profile or version line")
                waiting = outstanding.get((record_id, setup.record_sha(current[record_id])))
                if waiting is not None:
                    raise ConfigError(
                        f"{record_id} is in {waiting}, not yet imported; import {waiting} first "
                        "(a blank DECISION leaves it pending)"
                    )
            chosen = [record_id for record_id in current if record_id in set(records)]
        else:
            chosen = []
            for record_id, record in current.items():
                sha = setup.record_sha(record)
                decision = settling(sha, decisions)
                if decision is not None:
                    if record.status == "assistant_drafted":
                        report.lines.append(
                            f"{record_id}: decided in {decision['id']}; run setup review apply"
                        )
                    continue
                if (record_id, sha) in outstanding:
                    report.lines.append(
                        f"{record_id}: in {outstanding[(record_id, sha)]}, not yet imported"
                    )
                    continue
                chosen.append(record_id)
        number = max((int(p["packet_id"][3:]) for p in store.packets()), default=0)
        for start in range(0, len(chosen), size):
            number += 1
            batch = chosen[start : start + size]
            report.lines.append(
                _write_packet(
                    store,
                    state,
                    f"SR-{number:03d}",
                    [current[r] for r in batch],
                    decisions,
                    bool(records),
                    exported_on,
                )
            )
    if not any(line.startswith("SR-") for line in report.lines):
        report.lines.append("no setup record is ready for review")
    return report


def _write_packet(store, state, packet_id, batch, decisions, redecision, exported_on) -> str:
    blocks, entries = [], []
    for record in batch:
        sha = setup.record_sha(record)
        prior = settling(sha, decisions) if redecision else None
        fixed = render_record(record, state, prior)
        blocks.append(fixed + editable_region(record))
        entries.append(
            {
                "item": record.id,
                "record_type": kind_of(record.id),
                "draft_sha256": sha,
                "redecision": redecision,
                "fixed_sha256": sha256_hex(fixed.encode()),
                "fixed_text": fixed,
            }
        )
    header = header_text(packet_id, len(batch), exported_on)
    body = {
        "schema": PACKET_SCHEMA,
        "packet_id": packet_id,
        "exported_on": exported_on,
        "header_text": header,
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
    return f"{packet_id}: {len(batch)} record(s) in setup-review/packets/{packet_id}.md"


# ------------------------------------------------------------------ import


def _derive_citations(value: object, state: SetupState) -> list[dict] | str:
    if not isinstance(value, list):
        return "citations is a list of {record_id, quote}"
    out = []
    for number, citation in enumerate(value, 1):
        if not isinstance(citation, dict) or set(citation) != {"record_id", "quote"}:
            return f"citation {number} is {{record_id, quote}}"
        record = state.record(str(citation["record_id"]))
        if isinstance(record, str):
            return f"citation {number}: {record}"
        try:
            out.append(setup.make_citation(record, str(citation["quote"])))
        except ValueError as error:
            return f"citation {number}: {error}"
    return out


def _apply(block: Mapping, record: BaseModel, state: SetupState) -> BaseModel | None | list[str]:
    """The edited record (status assistant_drafted until applied), None, or problems."""
    record_id, word, fence_value = block["item"], block["word"], block["fence"]
    kind = kind_of(record_id)
    prefill = edit_prefill(record)
    unchanged = fence_value in (None, {}) or fence_value == prefill
    if word in ("approve", "reject", ""):
        if not unchanged:
            return [f"{record_id}: the JSON changed; write DECISION: edit to keep the changes"]
        if not word and block["note"]:
            return [f"{record_id}: a NOTE needs a decision"]
        return None
    if not isinstance(fence_value, dict):
        return [f"{record_id}: an edit needs the JSON object of the record's editable fields"]
    refused = sorted(set(fence_value) - set(EDIT_FIELDS[kind]))
    if refused:
        return [f"{record_id}: an edit cannot change {', '.join(refused)}"]
    changed = {key: value for key, value in fence_value.items() if prefill.get(key) != value}
    if not changed:
        return [f"{record_id}: DECISION is edit but nothing changed"]
    if "citations" in changed:
        derived = _derive_citations(changed["citations"], state)
        if isinstance(derived, str):
            return [f"{record_id}: edit: {derived}"]
        changed["citations"] = derived
    merged = {
        **setup.record_content(record),
        **changed,
        "status": "assistant_drafted",
        "review": None,
    }
    try:
        return MODELS[kind].model_validate(merged)
    except ValidationError as error:
        return [f"{record_id}: edit invalid: {gold.validation_message(error)}"]


def with_records(
    state: SetupState, replacements: Mapping[str, BaseModel]
) -> tuple[setup.SetupProfiles, setup.SetupFacts]:
    """The two documents with some records replaced (by id)."""
    profiles = state.profiles.model_dump(mode="json", by_alias=True)
    facts = state.facts.model_dump(mode="json", by_alias=True)
    groups = {
        "version_line": profiles["version_lines"],
        "profile": profiles["profiles"],
        "fact": facts["rows"],
    }
    for record_id, model in replacements.items():
        group = groups[kind_of(record_id)]
        data = model.model_dump(mode="json", by_alias=True)
        group[:] = [data if item["id"] == record_id else item for item in group]
    return setup.SetupProfiles.model_validate(profiles), setup.SetupFacts.model_validate(facts)


def import_packet(
    store: Store,
    state: SetupState,
    packet: str,
    *,
    decided_on: str,
    skip_stale: bool,
    confirm: Callable[[str], bool],
) -> Report:
    """Validate a returned packet completely, ask for confirmation, then record it
    (append-only). The setup files are not touched: `apply` writes the decisions."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", decided_on):
        raise ConfigError("--decided-on is a date, YYYY-MM-DD")
    match = PACKET_NAME.fullmatch(packet)
    if match is None:
        raise ConfigError(f"{packet}: name a packet as SR-NNN or its .md file")
    packet_id = match.group(1)
    report = Report()
    with store.locked():
        if (store.folder("imports") / f"{packet_id}.json").exists():
            raise Refused(f"{packet_id} was already imported; export the pending records again")
        try:
            manifest = json.loads((store.folder("packets") / f"{packet_id}.json").read_bytes())
            text = (store.folder("packets") / f"{packet_id}.md").read_bytes().decode("utf-8")
        except (OSError, ValueError):
            raise CheckFailed(f"{packet_id}: packet or manifest missing or unreadable") from None
        body = {key: value for key, value in manifest.items() if key != "digest"}
        mark = PACKET_MARK.fullmatch(normalized(text).split("\n")[0])
        if (
            manifest.get("schema") != PACKET_SCHEMA
            or manifest.get("digest") != sha256_hex(canonical(body))
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
        current = state.records()
        decisions = store.decisions()
        stale, errors, accepted, decided = [], [], [], []
        edited: dict[str, BaseModel] = {}
        for block in blocks:
            record_id, entry = block["item"], block["entry"]
            record = current.get(record_id)
            sha = setup.record_sha(record) if record is not None else None
            prior = settling(sha, decisions) if sha is not None else None
            if (
                record is None
                or sha != entry["draft_sha256"]
                or render_record(record, state, prior if entry["redecision"] else None)
                != entry["fixed_text"]
            ):
                stale.append(record_id)
                continue
            if prior is not None and not entry["redecision"]:
                untouched = block["fence"] in (None, {}) or block["fence"] == edit_prefill(record)
                if block["word"] or block["note"] or not untouched:
                    errors.append(
                        f"{record_id}: already decided by {prior['id']}; leave its DECISION blank "
                        "to import this packet's other records, then export it with --records"
                    )
                else:
                    decided.append(record_id)
                continue
            outcome = _apply(block, record, state)
            if isinstance(outcome, list):
                errors += outcome
                continue
            if outcome is not None:
                edited[record_id] = outcome
            accepted.append(block)
        if edited and not errors:
            # Every edit is checked with the others applied: the whole setup check runs once.
            errors += [
                f"edits fail the setup check: {p}"
                for p in state.check(*with_records(state, edited))
            ]
        if errors:
            raise ProblemsFound(f"{len(errors)} problem(s); nothing written", errors)
        if stale and not skip_stale:
            raise ProblemsFound(
                f"{len(stale)} stale block(s); nothing written (--skip-stale imports the rest)",
                [
                    f"{record_id}: stale: the record or what its block shows changed since export"
                    for record_id in stale
                ],
            )
        words = Counter(block["word"] or "blank" for block in accepted)
        summary = ", ".join(f"{count} {word}" for word, count in sorted(words.items()))
        if not confirm(f"{packet_id}: {summary or 'nothing to record'}"):
            raise ConfigError("import not confirmed; nothing written")
        records, notes, pending = [], {}, []
        for block in accepted:
            record_id = block["item"]
            if not block["word"]:
                pending.append(record_id)
                continue
            decision_id = f"{packet_id}.{block['ordinal']:02d}"
            sha = block["entry"]["draft_sha256"]
            prior = settling(sha, decisions)
            result = edited.get(record_id)
            records.append(
                {
                    "id": decision_id,
                    "item": record_id,
                    "record_type": kind_of(record_id),
                    "word": block["word"],
                    "draft_sha256": sha,
                    "result_draft_sha256": setup.record_sha(result) if result else None,
                    "result": setup.record_content(result) if result else None,
                    "supersedes": prior["id"] if prior else None,
                    "redecision": block["entry"]["redecision"],
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
                "sequence": store.next_sequence(),
                "decided_on": decided_on,
                "decisions": records,
                "drafts": [],
                "notes": notes,
                "pending": pending,
                "skipped_stale": stale,
                "already_decided": decided,
            },
        )
    report.lines.append(
        f"{packet_id}: {len(records)} decision(s) recorded, {len(pending)} left pending, "
        f"{len(stale)} stale block(s) skipped"
        + (f", {len(decided)} blank block(s) of already decided records ignored" if decided else "")
        + "; run setup review apply --write to write them into the setup files"
    )
    return report


# ------------------------------------------------------------------ apply


def _review(decision: Mapping, sha: str) -> dict:
    return {
        "decided_on": decision["decided_on"],
        "words": decision["word"],
        "decision_id": decision["id"],
        "content_sha256": sha,
    }


def apply(
    store: Store, state: SetupState, profiles_path: Path, facts_path: Path, *, write: bool
) -> Report:
    """Set every record's status and review from Chad's imported decisions (an edit writes
    its result); compare with the setup files (exit 1 on a difference) or write them."""
    report = Report()
    with store.locked():
        decisions = store.decisions()
        try:
            raw = {
                "profiles": json.loads(profiles_path.read_bytes()),
                "facts": json.loads(facts_path.read_bytes()),
            }
        except (OSError, ValueError):
            raise CheckFailed("the setup files cannot be read as JSON") from None
        groups = {
            "version_line": raw["profiles"]["version_lines"],
            "profile": raw["profiles"]["profiles"],
            "fact": raw["facts"]["rows"],
        }
        changed = []
        for record_id, record in state.records().items():
            kind = kind_of(record_id)
            sha = setup.record_sha(record)
            decision = settling(sha, decisions)
            content: dict | None = None
            if decision is None:
                wanted = {"status": "assistant_drafted", "review": None}
            elif decision["word"] == "edit" and decision["draft_sha256"] == sha:
                content = decision["result"]
                result = MODELS[kind].model_validate(
                    {**content, "status": "assistant_drafted", "review": None}
                )
                if setup.record_sha(result) != decision["result_draft_sha256"]:
                    raise CheckFailed(
                        f"setup-review/imports: {decision['id']}'s edit result does not hash to "
                        "its record; inspect it"
                    )
                wanted = {
                    "status": STATUS["edit"],
                    "review": _review(decision, decision["result_draft_sha256"]),
                }
            else:
                wanted = {"status": STATUS[decision["word"]], "review": _review(decision, sha)}
            group = groups[kind]
            position = next(k for k, item in enumerate(group) if item.get("id") == record_id)
            before = group[position]
            after = {**(content if content is not None else before), **wanted}
            if after != before:
                group[position] = after
                changed.append(f"{record_id}: {before.get('status')} -> {wanted['status']}")
        documents = {}
        for name, schema, model in (
            ("profiles", setup.PROFILES_SCHEMA, setup.SetupProfiles),
            ("facts", setup.FACTS_SCHEMA, setup.SetupFacts),
        ):
            body = {key: value for key, value in raw[name].items() if key != "digest"}
            complete = {**body, "digest": sha256_hex(canonical(body))}
            try:
                documents[name] = (model.model_validate(complete), dump_json(complete))
            except ValidationError as error:
                raise CheckFailed(
                    f"setup-{name}.json would be invalid: {gold.validation_message(error)}"
                ) from None
        problems = state.check(documents["profiles"][0], documents["facts"][0])
        if problems:
            raise ProblemsFound(f"{len(problems)} problem(s); nothing written", problems)
        differing = []
        for name, path in (("profiles", profiles_path), ("facts", facts_path)):
            data = documents[name][1]
            if path.read_bytes() == data:
                continue
            if not write:
                differing.append(path.name)
                continue
            temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
            write_new(temporary, data)
            os.replace(temporary, path)
            report.lines.append(f"{path.name}: rewritten")
    if differing:
        raise ProblemsFound(
            f"{', '.join(differing)} differ from Chad's decisions; run setup review apply --write",
            changed,
        )
    report.lines = changed + report.lines
    states = Counter(
        record.status for record in setup_records(documents["profiles"][0], documents["facts"][0])
    )
    report.lines.append("states: " + ", ".join(f"{k} {v}" for k, v in sorted(states.items())))
    return report


def setup_records(profiles: setup.SetupProfiles, facts: setup.SetupFacts) -> list[BaseModel]:
    return [*profiles.version_lines, *profiles.profiles, *facts.rows]
