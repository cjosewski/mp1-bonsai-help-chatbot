"""Setup profiles and the cited setup-fact table (`reference/setup-*.json`).

Every fact row is drafted by the assistant and carries `status: assistant_drafted` until
Chad reviews it at B3. A row cannot exist without citations, and every citation names a
pinned section (source, pin, path, heading path, line span, record id and section hash)
with a short verbatim quote that `verify_citation` proves present, exactly once, on token
boundaries and outside RST comments, in that section; every key term must occur in a quote
on token boundaries too. Claim wording and the choice of key terms are not machine-checked;
they are review items for Chad.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bonsai_help.doc_snapshot import Problem, dump_json, fixture_plan, load_canonical
from bonsai_help.doc_sources import DocSources, canonical, sha256_hex
from bonsai_help.docs_index import Diagnostics, docname, split_lines, split_page

PROFILES_SCHEMA = "setup-profiles-v1"
FACTS_SCHEMA = "setup-facts-v1"
MIN_QUOTE = 20
IfcSchema = Literal["IFC2X3", "IFC4", "IFC4X3"]
Discipline = Literal["architecture", "structure", "building_services"]
ModelState = Literal["new_project", "opened_ifc", "large_federated_model"]
Status = Literal["assistant_drafted", "chad_accepted", "chad_amended", "chad_rejected"]
FactKind = Literal[
    "schema_dependent", "version_dependent", "version_claim", "doc_conflict", "doc_absence"
]
SCHEMAS = ("IFC2X3", "IFC4", "IFC4X3")
DISCIPLINES = ("architecture", "structure", "building_services")
MODEL_STATES = ("new_project", "opened_ifc", "large_federated_model")
PIN_DIFF_PAIRS = (("bonsai-docs", "bonsai-docs-0-8-5-post1"),)
DIRECTIVE_START = re.compile(r"(?:[\w:+-]+::|_|\[|\|)")
CANDIDATE_RULES = {
    "schema-mention": re.compile(r"\bIFC(?:2X3|2x3|4X3|4x3|4)\b"),
    "version-mention": re.compile(r"Blender [2-5]\.\d+|Python 3\.\d+|\b0\.[89]\.\d+|\bLTS\b"),
    "change-words": re.compile(
        r"introduced in|deprecated|legacy|no longer|prior to|before Blender|since Blender|removed",
        re.IGNORECASE,
    ),
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Review(_Model):
    decided_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    words: str = Field(min_length=1)


def _reviewed(status: str, review: Review | None) -> None:
    if status == "assistant_drafted" and review is not None:
        raise ValueError("an assistant_drafted item has no review")
    if status != "assistant_drafted" and review is None:
        raise ValueError(f"status {status} needs a review with Chad's own words")


class EnumBasis(_Model):
    """Where an enum's values come from. `partly cited`: the fact rows support the values
    only for the model states in `cited_for`; the note says what the rest rests on."""

    values: list[str] = Field(min_length=1)
    basis: Literal["cited", "partly cited", "plan §4 wording", "assistant default"]
    facts: list[str] = []
    cited_for: list[ModelState] = []
    note: str | None = None

    @model_validator(mode="after")
    def _cited(self) -> EnumBasis:
        if (self.basis in ("cited", "partly cited")) != bool(self.facts):
            raise ValueError("a cited or partly cited enum names its fact rows; others name none")
        partly = self.basis == "partly cited"
        if partly != bool(self.cited_for):
            raise ValueError("cited_for is required for a partly cited enum and only for it")
        if partly and (not self.note or set(self.cited_for) >= set(MODEL_STATES)):
            raise ValueError("a partly cited enum needs a note and leaves some model state out")
        return self


class VersionSources(_Model):
    bonsai_docs: str
    bonsai_source: str
    blender_manual: str


class VersionLine(_Model):
    id: str = Field(pattern=r"^VL-[a-z]+$")
    blender: str = Field(min_length=1)
    bonsai: str = Field(min_length=1)
    bonsai_tag: str = Field(min_length=1)
    sources: VersionSources
    origin: Literal["plan §2", "O-3 default", "Chad, 2026-11-22"]
    pairing_status: Literal["cited", "partly cited", "uncited", "conflict"]
    pairing_note: str = Field(min_length=1)
    claims: list[str] = Field(min_length=1)
    status: Status
    review: Review | None = None

    @model_validator(mode="after")
    def _review(self) -> VersionLine:
        _reviewed(self.status, self.review)
        return self


class Profile(_Model):
    id: str = Field(pattern=r"^SP-\d{2}$")
    version_line: str
    ifc_schema: IfcSchema
    discipline: Discipline
    model_state: ModelState
    split: Literal["development", "assessed"]
    status: Status
    review: Review | None = None

    @model_validator(mode="after")
    def _review(self) -> Profile:
        _reviewed(self.status, self.review)
        return self


class SetupProfiles(_Model):
    schema_: Literal["setup-profiles-v1"] = Field(alias="schema")
    drafted_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    enums: dict[Literal["ifc_schema", "discipline", "model_state"], EnumBasis]
    version_lines: list[VersionLine] = Field(min_length=1)
    profiles: list[Profile] = Field(min_length=1)
    digest: str


class Citation(_Model):
    source: str
    pin_id: str
    commit: str
    path: str
    heading_path: list[str]
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    record_id: str
    section_sha256: str
    quote: str
    quote_line: int = Field(ge=1)


class Absence(_Model):
    source: str
    pin_id: str
    path: str
    text: str = Field(min_length=1)


class AppliesTo(_Model):
    version_lines: list[str] = Field(min_length=1)
    ifc_schemas: list[IfcSchema] = Field(min_length=1)


class FactRow(_Model):
    id: str = Field(pattern=r"^SF-\d{3}$")
    kind: FactKind
    topic: str = Field(min_length=1)
    applies_to: AppliesTo
    claim: str = Field(min_length=1)
    key_terms: list[str] = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)
    absent_in: list[Absence] = []
    conflicts_with: list[str] = []
    candidate_rule: Literal["schema-mention", "version-mention", "change-words", "pin-diff"]
    status: Status
    review: Review | None = None
    drafted_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> FactRow:
        _reviewed(self.status, self.review)
        if (self.kind == "doc_absence") != bool(self.absent_in):
            raise ValueError("absent_in is required for doc_absence rows and only for them")
        if (self.kind == "doc_conflict") != bool(self.conflicts_with):
            raise ValueError("conflicts_with is required for doc_conflict rows and only for them")
        return self


class NotCitable(_Model):
    claim: str = Field(min_length=1)
    wanted: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SetupFacts(_Model):
    schema_: Literal["setup-facts-v1"] = Field(alias="schema")
    rows: list[FactRow] = Field(min_length=1)
    not_citable: list[NotCitable] = []
    digest: str


# ------------------------------------------------------------------ quotes


def collapse(text: str) -> str:
    """Runs of ASCII space, tab and newline become one space; ends are stripped."""
    return re.sub(r"[ \t\n]+", " ", text).strip(" \t\n")


def comment_lines(lines: Sequence[str]) -> set[int]:
    """0-based lines inside RST comments (`..` not followed by a directive, target or label)."""
    found: set[int] = set()
    k = 0
    while k < len(lines):
        line = lines[k]
        stripped = line.lstrip(" \t")
        indent = len(line) - len(stripped)
        is_comment = stripped == ".." or (
            stripped.startswith(".. ") and not DIRECTIVE_START.match(stripped[3:].lstrip())
        )
        if not is_comment:
            k += 1
            continue
        found.add(k)
        j = k + 1
        while j < len(lines) and (
            not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip(" \t")) > indent
        ):
            if lines[j].strip():
                found.add(j)
            j += 1
        k = j
    return found


def _on_boundaries(collapsed: str, begin: int, end: int) -> bool:
    """No letter or digit shares a token with the match's first or last character."""
    head = collapsed.rfind(" ", 0, begin) + 1
    tail = collapsed.find(" ", end)
    tail = len(collapsed) if tail < 0 else tail
    return not any(ch.isalnum() for ch in collapsed[head:begin] + collapsed[end:tail])


def locate_quote(text: str, first_line: int, quote: str) -> tuple[int, list[int]] | str:
    """Where a collapsed quote occurs in a section: (first line, lines spanned) or a problem.

    A match must start and end on token boundaries: only punctuation may sit between it and
    the surrounding whitespace, so `supported` does not match inside `unsupported` and
    `Blender 4` does not match inside `Blender 4.2`.
    """
    wanted = collapse(quote)
    if len(wanted) < MIN_QUOTE:
        return "quote too short"
    words = [(m.group(), m.start()) for m in re.finditer(r"[^ \t\n]+", text)]
    collapsed, starts = "", []
    for word, position in words:
        if collapsed:
            collapsed += " "
        starts.append((len(collapsed), position, len(word)))
        collapsed += word
    anywhere = [m.start() for m in re.finditer(f"(?={re.escape(wanted)})", collapsed)]
    found = [at for at in anywhere if _on_boundaries(collapsed, at, at + len(wanted))]
    if anywhere and not found:
        return "quote occurs only inside a longer token"
    if not found:
        return "quote not found"
    if len(found) > 1:
        return f"quote occurs {len(found)} times in the section, must be once"
    begin, end = found[0], found[0] + len(wanted) - 1

    def original(offset: int) -> int:
        for start, position, length in reversed(starts):
            if start <= offset:
                return position + min(offset - start, length - 1)
        return 0

    def line_of(position: int) -> int:
        return first_line + text.count("\n", 0, position)

    first, last = line_of(original(begin)), line_of(original(end))
    return first, list(range(first, last + 1))


# ------------------------------------------------------------------ verification


def page_bytes_offline(fixtures_dir: Path) -> Callable[[str, str], bytes | None]:
    def read(source: str, path: str) -> bytes | None:
        target = fixtures_dir / source / path
        return target.read_bytes() if target.is_file() and not target.is_symlink() else None

    return read


def verify_citation(
    citation: Citation,
    config: DocSources,
    manifest: Mapping,
    read: Callable[[str, str], bytes | None],
    where: str,
    *,
    require_fixture: bool = True,
) -> list[Problem]:
    """Every field of a citation against the pinned page bytes; see the module docstring.

    `require_fixture=False` lets a gold draft cite a page outside the committed fixture slice;
    publishing it still needs the page in the slice."""
    shown = f"{where}: {citation.path}"
    ids = {source.id: source for source in config.sources}
    source = ids.get(citation.source)
    if source is None or source.role != "docs":
        return [Problem("setup", shown, f"unknown docs source {citation.source}")]
    entry = manifest["sources"].get(source.id, {})
    if (
        citation.pin_id != entry.get("pin_id")
        or citation.commit != config.repository_of(source).commit
    ):
        return [Problem("setup", shown, "stale pin: pin_id or commit differs from the manifest")]
    if require_fixture and citation.path not in fixture_plan(source):
        return [Problem("setup", shown, "cites a page outside the committed fixture slice")]
    page = next((item for item in entry["pages"] if item["path"] == citation.path), None)
    data = read(source.id, citation.path)
    if page is None or data is None or sha256_hex(data) != page["sha256"]:
        return [Problem("setup", shown, "page hash differs from the manifest or page missing")]
    pages = frozenset(item["path"] for item in entry["pages"])
    records = split_page(
        source, entry["pin_id"], citation.commit, citation.path, data, pages, Diagnostics()
    )
    record = next(
        (
            r
            for r in records
            if r["line_start"] == citation.line_start and r["line_end"] == citation.line_end
        ),
        None,
    )
    if record is None:
        return [
            Problem("setup", shown, f"no such section L{citation.line_start}-L{citation.line_end}")
        ]
    problems = []
    if record["heading_path"] != citation.heading_path:
        problems.append(Problem("setup", shown, "heading path mismatch"))
    if record["sha256"] != citation.section_sha256:
        problems.append(Problem("setup", shown, "section hash mismatch"))
    if record["id"] != citation.record_id:
        problems.append(Problem("setup", shown, "record id mismatch"))
    located = locate_quote(record["text"], record["line_start"], citation.quote)
    if isinstance(located, str):
        problems.append(Problem("setup", shown, located))
        return problems
    first, spanned = located
    comments = {record["line_start"] + k for k in comment_lines(split_lines(record["text"]))}
    if comments & set(spanned):
        problems.append(Problem("setup", shown, "quote falls inside an RST comment"))
    if first != citation.quote_line:
        problems.append(
            Problem("setup", shown, f"quote_line is {citation.quote_line}, match starts at {first}")
        )
    return problems


def absence_phrase(config: DocSources, absence: Absence) -> str:
    source = config.source(absence.source)
    tag = config.repository_of(source).ref.name
    return f"not documented in {tag} {docname(source, absence.path)}.rst"


def verify_fact(
    row: FactRow,
    config: DocSources,
    manifest: Mapping,
    lines: Mapping[str, VersionLine],
    read: Callable[[str, str], bytes | None],
) -> list[Problem]:
    problems: list[Problem] = []
    for index, citation in enumerate(row.citations):
        problems += verify_citation(citation, config, manifest, read, f"{row.id} citation {index}")
    quotes = [collapse(c.quote) for c in row.citations]
    for term in row.key_terms:
        wanted = collapse(term)
        if not any(
            _on_boundaries(quote, m.start(), m.start() + len(wanted))
            for quote in quotes
            for m in re.finditer(f"(?={re.escape(wanted)})", quote)
        ):
            problems.append(
                Problem("setup", row.id, f"key term {term!r} is in no quote on token boundaries")
            )
    for name in row.applies_to.version_lines:
        line = lines.get(name)
        if line is None:
            problems.append(Problem("setup", row.id, f"unknown version line {name}"))
            continue
        if row.kind in ("version_claim", "doc_conflict"):
            # Evidence for the line's pairing, which may be stated in another release's docs;
            # the line lists it among its claims and its pairing is not scored as a fact.
            if row.id not in line.claims:
                problems.append(Problem("setup", row.id, f"version row not in {name}'s claims"))
            continue
        allowed = {line.sources.bonsai_docs, line.sources.blender_manual}
        if not any(c.source in allowed for c in row.citations):
            problems.append(Problem("setup", row.id, f"no citation from {name}'s sources"))
    ids = {source.id for source in config.sources}
    for absence in row.absent_in:
        shown = f"{row.id} absence {absence.path}"
        if absence.source not in ids:
            problems.append(Problem("setup", shown, f"unknown source {absence.source}"))
            continue
        source = config.source(absence.source)
        entry = manifest["sources"].get(source.id, {})
        page = next((p for p in entry.get("pages", []) if p["path"] == absence.path), None)
        data = read(source.id, absence.path)
        if absence.pin_id != entry.get("pin_id"):
            problems.append(Problem("setup", shown, "stale pin"))
        elif absence.path not in fixture_plan(source):
            problems.append(Problem("setup", shown, "page outside the committed fixture slice"))
        elif page is None or data is None or sha256_hex(data) != page["sha256"]:
            problems.append(Problem("setup", shown, "page hash differs or page missing"))
        elif collapse(absence.text) in collapse(data.decode("utf-8")):
            problems.append(Problem("setup", shown, "absence violated: the text is on that page"))
        if absence_phrase(config, absence) not in row.claim:
            problems.append(
                Problem("setup", row.id, f"claim must say {absence_phrase(config, absence)!r}")
            )
    return problems


# ------------------------------------------------------------------ committed files


def _validate(model: type[BaseModel], document: dict, label: str) -> tuple[object, list[Problem]]:
    try:
        return model.model_validate(document), []
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(p) for p in item['loc']) or '(root)'}: {item['msg']}"
            for item in error.errors()[:5]
        )
        return None, [Problem("setup", label, f"invalid: {details}")]


def _pairing_cited(line: VersionLine, rows: Mapping[str, FactRow]) -> bool:
    """A version_claim of the line's own Bonsai docs pin names the line's Blender release in a
    key term, on token boundaries (`5.2` is not found inside `5.2.1`)."""
    wanted = collapse(line.blender)
    for claim in line.claims:
        row = rows.get(claim)
        if row is None or row.kind != "version_claim":
            continue
        if not any(c.source == line.sources.bonsai_docs for c in row.citations):
            continue
        for term in map(collapse, row.key_terms):
            if any(
                _on_boundaries(term, m.start(), m.start() + len(wanted))
                for m in re.finditer(f"(?={re.escape(wanted)})", term)
            ):
                return True
    return False


def _release(version: str) -> str:
    """A Bonsai release as tags and docs spell it alike: `0.8.5-post1` and `0.8.5post1`."""
    return re.sub(r"[-_.]?post", "post", version)


def check_profiles(profiles: SetupProfiles, facts: SetupFacts, config: DocSources) -> list[Problem]:
    problems: list[Problem] = []
    label = "setup-profiles.json"
    lines = {line.id: line for line in profiles.version_lines}
    rows = {row.id: row for row in facts.rows}
    if len(lines) != len(profiles.version_lines):
        problems.append(Problem("setup", label, "version line ids are not unique"))
    for line in profiles.version_lines:
        for role, sid in line.sources.model_dump().items():
            want = "operator-source" if role == "bonsai_source" else "docs"
            if sid not in {s.id for s in config.sources} or config.source(sid).role != want:
                problems.append(Problem("setup", label, f"{line.id}: {role} {sid} is not a {want}"))
            elif role == "blender_manual":
                # Each line's Blender steps come from its matching Manual (Chad, 2026-11-22).
                ref = config.repository_of(config.source(sid)).ref
                branch = f"blender-v{line.blender}-release"
                if (ref.kind, ref.name) != ("branch", branch):
                    problems.append(
                        Problem(
                            "setup",
                            label,
                            f"{line.id}: blender_manual {sid} pins {ref.kind} {ref.name}, "
                            f"not the Blender {line.blender} Manual branch {branch}",
                        )
                    )
            else:
                # The line's Bonsai docs and add-on source are both its own release's tag.
                ref = config.repository_of(config.source(sid)).ref
                if (ref.kind, ref.name) != ("tag", line.bonsai_tag):
                    problems.append(
                        Problem(
                            "setup",
                            label,
                            f"{line.id}: {role} {sid} pins {ref.kind} {ref.name}, "
                            f"not the line's Bonsai tag {line.bonsai_tag}",
                        )
                    )
        if _release(line.bonsai_tag.removeprefix("bonsai-")) != _release(line.bonsai):
            problems.append(
                Problem(
                    "setup",
                    label,
                    f"{line.id}: bonsai_tag {line.bonsai_tag} is not the tag of "
                    f"Bonsai {line.bonsai}",
                )
            )
        for claim in line.claims:
            if claim not in rows or rows[claim].kind not in ("version_claim", "doc_conflict"):
                problems.append(
                    Problem("setup", label, f"{line.id}: claim {claim} is not a version row")
                )
            elif line.id not in rows[claim].applies_to.version_lines:
                problems.append(
                    Problem("setup", label, f"{line.id}: claim {claim} does not apply to it")
                )
        if line.pairing_status == "cited" and not _pairing_cited(line, rows):
            problems.append(
                Problem(
                    "setup",
                    label,
                    f"{line.id}: a cited pairing needs a version_claim among its claims that cites "
                    f"{line.sources.bonsai_docs} and names Blender {line.blender} in a key term",
                )
            )
    ids = [p.id for p in profiles.profiles]
    if len(ids) != len(set(ids)):
        problems.append(Problem("setup", label, "profile ids are not unique"))
    for enum, values in (
        ("ifc_schema", SCHEMAS),
        ("discipline", DISCIPLINES),
        ("model_state", MODEL_STATES),
    ):
        basis = profiles.enums.get(enum)
        if basis is None or tuple(basis.values) != values:
            problems.append(Problem("setup", label, f"enum {enum} differs from the model"))
        elif any(fact not in rows for fact in basis.facts):
            problems.append(Problem("setup", label, f"enum {enum} names an unknown fact row"))
    for line_id in lines:
        mine = [p for p in profiles.profiles if p.version_line == line_id]
        cells = sorted((p.ifc_schema, p.model_state) for p in mine)
        if cells != sorted((s, m) for s in SCHEMAS for m in MODEL_STATES):
            problems.append(
                Problem("setup", label, f"{line_id}: not a full schema x state factorial")
            )
        for p in mine:
            want = DISCIPLINES[
                (SCHEMAS.index(p.ifc_schema) + MODEL_STATES.index(p.model_state)) % 3
            ]
            if p.discipline != want:
                problems.append(Problem("setup", label, f"{p.id}: discipline breaks the rotation"))
            assessed = SCHEMAS.index(p.ifc_schema) == MODEL_STATES.index(p.model_state)
            if (p.split == "assessed") != assessed:
                problems.append(Problem("setup", label, f"{p.id}: split breaks the diagonal rule"))
    unknown = {p.version_line for p in profiles.profiles} - set(lines)
    if unknown:
        problems.append(
            Problem("setup", label, f"profiles name unknown version lines {sorted(unknown)}")
        )
    for split in ("development", "assessed"):
        chosen = [p for p in profiles.profiles if p.split == split]
        for attr, values in (
            ("ifc_schema", SCHEMAS),
            ("model_state", MODEL_STATES),
            ("discipline", DISCIPLINES),
            ("version_line", tuple(lines)),
        ):
            if {getattr(p, attr) for p in chosen} != set(values):
                problems.append(Problem("setup", label, f"{split} split misses a {attr} value"))
    return problems


def check_setup(
    config: DocSources,
    manifest: Mapping,
    profiles_path: Path,
    facts_path: Path,
    read: Callable[[str, str], bytes | None],
    index: Mapping[str, str] | None = None,
) -> list[Problem]:
    """Profiles and facts; `index` (record id -> sha256 of a built index) adds the full check."""
    problems: list[Problem] = []
    documents = {}
    for path, schema, model in (
        (profiles_path, PROFILES_SCHEMA, SetupProfiles),
        (facts_path, FACTS_SCHEMA, SetupFacts),
    ):
        document, found = load_canonical(path, schema, "digest", "setup")
        problems += found
        if document is None:
            if not found:
                problems.append(Problem("setup", path.name, "missing"))
            continue
        parsed, found = _validate(model, document, path.name)
        problems += found
        documents[schema] = parsed
    profiles, facts = documents.get(PROFILES_SCHEMA), documents.get(FACTS_SCHEMA)
    if profiles is None or facts is None:
        return problems
    row_ids = [row.id for row in facts.rows]
    if len(row_ids) != len(set(row_ids)):
        problems.append(Problem("setup", facts_path.name, "fact row ids are not unique"))
    lines = {line.id: line for line in profiles.version_lines}
    for row in facts.rows:
        problems += verify_fact(row, config, manifest, lines, read)
        for citation in row.citations if index is not None else ():
            if index.get(citation.record_id) != citation.section_sha256:
                problems.append(
                    Problem("setup", row.id, f"{citation.record_id} is not in the built index")
                )
        for other in row.conflicts_with:
            if other not in row_ids:
                problems.append(Problem("setup", row.id, f"conflicts_with names unknown {other}"))
    return problems + check_profiles(profiles, facts, config)


def format_document(path: Path, schema: str, model: type[BaseModel]) -> bytes:
    """A hand-edited reference file, validated and rewritten in canonical layout with its digest."""
    document = json.loads(path.read_bytes())
    if document.get("schema") != schema:
        raise ValueError(f"{path.name}: schema is not {schema}")
    body = {key: value for key, value in document.items() if key != "digest"}
    complete = {**body, "digest": sha256_hex(canonical(body))}
    model.model_validate(complete)
    return dump_json(complete)


# ------------------------------------------------------------------ candidates


def candidates(records: Iterable[Mapping], sources: Sequence[str] | None = None) -> list[dict]:
    """Deterministic candidate lines for fact rows; the assistant drafts rows from them."""
    records = [r for r in records if sources is None or r["source"] in sources]
    out = []
    for record in records:
        for k, line in enumerate(split_lines(record["text"])):
            for rule, pattern in CANDIDATE_RULES.items():
                if pattern.search(line):
                    out.append(
                        {
                            "record": record["id"],
                            "rule": rule,
                            "line": record["line_start"] + k,
                            "text": line.strip(),
                        }
                    )
    by_key: dict[tuple, Mapping] = {}
    seen: Counter[tuple] = Counter()
    for r in records:
        heading = (*r["heading_path"], f"#{seen[(r['source'], r['path'], *r['heading_path'])]}")
        seen[(r["source"], r["path"], *r["heading_path"])] += 1
        by_key[(r["source"], r["path"], heading)] = r
    for left, right in PIN_DIFF_PAIRS:
        keys = {(path, heading) for source, path, heading in by_key if source in (left, right)}
        for path, heading in sorted(keys):
            a, b = by_key.get((left, path, heading)), by_key.get((right, path, heading))
            if a is not None and b is not None and a["sha256"] == b["sha256"]:
                continue
            for record, other in ((a, right), (b, left)):
                if record is not None:
                    status = "differs" if (a and b) else f"absent at {other}"
                    out.append(
                        {
                            "record": record["id"],
                            "rule": "pin-diff",
                            "line": record["title_line"] or record["line_start"],
                            "text": f"{status}: {' > '.join(heading[:-1]) or '(page head)'}",
                        }
                    )
    return out


def make_citation(record: Mapping, quote: str) -> dict:
    """The citation fields for a quote in a record (used to draft rows; checks recompute them)."""
    located = locate_quote(record["text"], record["line_start"], quote)
    if isinstance(located, str):
        raise ValueError(f"{record['id']}: {located}: {quote!r}")
    return {
        "source": record["source"],
        "pin_id": record["pin_id"],
        "commit": record["commit"],
        "path": record["path"],
        "heading_path": record["heading_path"],
        "line_start": record["line_start"],
        "line_end": record["line_end"],
        "record_id": record["id"],
        "section_sha256": record["sha256"],
        "quote": quote,
        "quote_line": located[0],
    }
