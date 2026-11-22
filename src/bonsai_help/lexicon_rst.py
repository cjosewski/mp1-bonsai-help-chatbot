"""Blender operators, menu paths, hotkeys and UI wording from the docs' reStructuredText roles.

Runs over `docs_index` section records, so every location is an existing record id, and
extraction is local to a record: the entries found in a fixture page's records equal the
committed entries restricted to those records. Values keep RST text as written, with
whitespace collapsed; nothing is rendered.

Kinds:

- `blender_operator`: a `.. _bpy.ops.<module>.<op>:` target at any indent. The label is
  the section title it is attached to, or the definition-list term that follows it at the
  target's own indent, with roles reduced to their text (a lone field marker such as
  `:Material:` gives its name; a `:ref:` or `:doc:` gives its title if written as
  `Title <target>` and nothing if its target is bare; a list of `:kbd:` roles goes with
  the `,`, `/` or `+` between them and one that ends the term), otherwise null.
- `operator_ref`: a `:ref:` to a `bpy.ops.*` target, with its alias label if written.
- `menu_path`: a `:menuselection:` role, segments split on `-->` and collapsed; empty
  segments are dropped. A role that begins with `-->` continues a menu opened another way
  (often by a hotkey); its value keeps that leading `--> ` and is counted as
  `menu_paths_continued`.
- `hotkey`: a `:kbd:` role, or adjacent roles joined by `+`, as one entry. `value` is the
  parsed form: chords separated by a space, keys of a chord by `-`; `label` keeps the
  verbatim text (collapsed).
- `guilabel`: a `:guilabel:` role.
- `ui_path`: interpreted text with the default role that contains ` > ` (Bonsai docs
  write some UI paths this way).
- `reference_field`: one field (Mode, Menu, Shortcut, Panel, Editor, Tool, Header,
  Context) of a `.. reference::` block, parsed at the field list's own indent.

Not extracted (counted in the summary or out of scope): `bpy.types` targets, which name
properties, not operators; settings (`bpy.props` names); inline `bpy.ops` prose outside
roles and targets; anything inside an inline literal or a literal block (a `::` paragraph's
indented body, or a `code-block`, `code`, `sourcecode` or `literalinclude` body), where
RST markup is shown as an example rather than rendered.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence

from bonsai_help.docs_index import split_lines

SCHEMA = "rst-lexicon-v1"
EXTRACTOR = "rst-roles-v4"
REFERENCE_FIELDS = ("Mode", "Menu", "Shortcut", "Panel", "Editor", "Tool", "Header", "Context")
TARGET = re.compile(r"(?P<indent>[ \t]*)\.\. _(?P<label>`[^`]+`|[^`:\s][^:]*):[ \t]*")
OPS_PREFIX = "bpy.ops."
TYPES_PREFIX = "bpy.types."
ROLE = re.compile(r":(?P<role>[\w-]+):`(?P<text>[^`]*)`")
LITERAL = re.compile(r"``.+?``", re.DOTALL)
KBD_RUN = re.compile(r":kbd:`[^`]+`(?:\s*\+\s*:kbd:`[^`]+`)*")
KBD = re.compile(r":kbd:`(?P<text>[^`]+)`")
KBD_LIST = re.compile(r":kbd:`[^`]+`(?:\s*[,/+]\s*:kbd:`[^`]+`)*(?:\s*[,/+]\s*$)?")
DEFAULT_ROLE = re.compile(r"(?<![\w\\])`(?P<text>[^`]+)`(?![`_\w])")
REFERENCE = re.compile(r"(?P<indent>[ \t]*)\.\. reference::[ \t]*")
FIELD = re.compile(r"(?P<indent>[ \t]*):(?P<name>[A-Za-z][A-Za-z ]*):(?:[ \t]+(?P<value>.*))?")
KEY_SPLIT = re.compile(r"(?<=.)[-+](?=.)")
LITERAL_DIRECTIVE = re.compile(r"[ \t]*\.\. (?:code-block|code|sourcecode|literalinclude)::")
LIST_MARKER = re.compile(r"(?:[-*+]|#\.|\d+\.|\(?[a-zA-Z0-9]+\))[ \t]+")
FIELD_MARKER = re.compile(r":(?P<name>[^:`]+):")
XREF_ALIAS = re.compile(r"(?P<label>.*?)\s*<(?P<target>[^<>]+)>", re.DOTALL)


def collapse(text: str) -> str:
    return " ".join(text.split())


def parse_keys(text: str) -> list[list[str]]:
    """`Ctrl-Shift-A` -> [[Ctrl, Shift, A]]; `R Y Y` -> [[R], [Y], [Y]]; `Ctrl+D` too."""
    return [KEY_SPLIT.split(item) for item in text.split()]


def hotkey_value(span: str) -> str:
    chords: list[list[str]] = []
    for index, match in enumerate(KBD.finditer(span)):
        parsed = parse_keys(match["text"])
        if index and chords and parsed:
            chords[-1] = chords[-1] + parsed[0]
            parsed = parsed[1:]
        chords += parsed
    return " ".join("-".join(chord) for chord in chords)


def reduce_roles(text: str, counts: Counter | None = None) -> str:
    """A term's text with `:bl-icon:` and `:kbd:` roles removed and other roles unwrapped.

    A list of `:kbd:` roles goes with the separators (`,`, `/`, `+`) between its roles and
    one left at the end of the term: `Next Folder` followed by `:kbd:` roles separated by
    commas gives `Next Folder`, not `Next Folder , ,`. A `:ref:` or `:doc:` written `Title <target>` gives its title. One with a bare target
    renders a title RST looks up elsewhere, so it is removed (and counted in `counts`)
    rather than shown as a target or path.
    """

    def replace(match: re.Match) -> str:
        role, body = match["role"], match["text"]
        if role in ("bl-icon", "kbd"):
            return ""
        if role in ("ref", "doc"):
            alias = XREF_ALIAS.fullmatch(body)
            if alias and collapse(alias["label"]):
                return alias["label"]
            if counts is not None:
                counts["operator_terms_bare_xref"] += 1
            return ""
        return body

    return collapse(ROLE.sub(replace, KBD_LIST.sub("", text)))


def _line_of(record: Mapping, position: int) -> int:
    return record["line_start"] + record["text"].count("\n", 0, position)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _blank(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group())


def literal_lines(lines: Sequence[str]) -> set[int]:
    """0-based lines of literal blocks: a `::` paragraph's indented body or a code directive's."""
    found: set[int] = set()
    k = 0
    while k < len(lines):
        line = lines[k]
        stripped = line.strip()
        directive = LITERAL_DIRECTIVE.match(line)
        if not directive and not (stripped.endswith("::") and not stripped.startswith("..")):
            k += 1
            continue
        base = _indent(line)
        marker = None if directive else LIST_MARKER.match(line, base)
        if marker:
            base = marker.end()
        j = k + 1
        while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > base):
            if lines[j].strip():
                found.add(j)
            j += 1
        k = j if j > k + 1 else k + 1
    return found


def _unliteral(text: str, literal: set[int]) -> str:
    """Text with literal-block lines and inline literals blanked (same length)."""
    lines = text.split("\n")
    kept = "\n".join(" " * len(line) if k in literal else line for k, line in enumerate(lines))
    return LITERAL.sub(_blank, kept)


def _masked(text: str) -> str:
    """Text with roles also blanked (same length), for default-role matching."""
    return ROLE.sub(_blank, text)


def _term_after(lines: Sequence[str], k: int, indent: int, counts: Counter) -> str | None:
    """The definition-list term after a target at line k, at the target's own indent."""
    j = k + 1
    while j < len(lines) and (not lines[j].strip() or TARGET.fullmatch(lines[j])):
        j += 1
    if j + 1 >= len(lines):
        return None
    term, body = lines[j], lines[j + 1]
    if _indent(term) != indent or term.lstrip().startswith(".."):
        return None
    if not body.strip() or _indent(body) <= indent:
        return None
    field = FIELD_MARKER.fullmatch(term.strip())
    return collapse(field["name"]) if field else reduce_roles(term, counts) or None


def _reference_fields(lines: Sequence[str], k: int) -> list[tuple[str, str, int]]:
    directive = REFERENCE.fullmatch(lines[k])
    base = len(directive["indent"]) if directive else 0
    fields: list[tuple[str, list[str], int]] = []
    column = None
    j = k + 1
    while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > base):
        line = lines[j]
        match = FIELD.fullmatch(line)
        if match and column is None:
            column = len(match["indent"])
        if match and len(match["indent"]) == column:
            fields.append((match["name"], [match["value"] or ""], j))
        elif fields and line.strip():
            fields[-1][1].append(line)
        j += 1
    return [(name, collapse(" ".join(parts)), j) for name, parts, j in fields]


def extract_record(record: Mapping) -> tuple[list[tuple[str, str, str | None, int]], Counter]:
    """(kind, value, label, line) occurrences in one record, and summary counts."""
    found: list[tuple[str, str, str | None, int]] = []
    counts: Counter[str] = Counter()
    text = record["text"]
    lines = split_lines(text)
    literal = literal_lines(lines)
    text = _unliteral(text, literal)
    anchored = set(record["anchors"])
    for k, line in enumerate(lines):
        if k in literal:
            continue
        number = record["line_start"] + k
        target = TARGET.fullmatch(line)
        if target:
            label = target["label"]
            if label.startswith(TYPES_PREFIX):
                counts["bpy_types_targets"] += 1
            if label.startswith(OPS_PREFIX):
                name = label[len(OPS_PREFIX) :]
                title_line = record["title_line"]
                if label in anchored and title_line is not None and number < title_line:
                    counts["operator_targets_on_title"] += 1
                    found.append(("blender_operator", name, record["title"], number))
                else:
                    term = _term_after(lines, k, len(target["indent"]), counts)
                    counts["operator_targets_on_term" if term else "operator_targets_other"] += 1
                    counts["operator_targets_indented"] += bool(target["indent"])
                    found.append(("blender_operator", name, term, number))
        if REFERENCE.fullmatch(line):
            counts["reference_blocks"] += 1
            for name, value, j in _reference_fields(lines, k):
                counts[f"reference_field:{name}"] += 1
                if name in ("Menu", "Shortcut") and re.search(r":(?:menuselection|kbd):`", value):
                    counts["reference_fields_covered_by_roles"] += 1
                elif name in REFERENCE_FIELDS:
                    found.append(
                        ("reference_field", f"{name}: {value}", None, record["line_start"] + j)
                    )
    for match in ROLE.finditer(text):
        role, body, line = match["role"], match["text"], _line_of(record, match.start())
        if role == "menuselection":
            segments = [collapse(part) for part in body.split("-->")]
            continued = not segments[0]
            counts["menu_paths_continued"] += continued
            value = " --> ".join(segment for segment in segments if segment)
            found.append(("menu_path", f"--> {value}" if continued else value, None, line))
        elif role == "guilabel":
            found.append(("guilabel", collapse(body), None, line))
        elif role == "ref":
            alias = XREF_ALIAS.fullmatch(body)
            target, label = (
                (alias["target"], collapse(alias["label"]) or None) if alias else (body, None)
            )
            target = collapse(target)
            if target.startswith(OPS_PREFIX):
                found.append(("operator_ref", target[len(OPS_PREFIX) :], label, line))
    for match in KBD_RUN.finditer(text):
        span = match.group()
        counts["kbd_roles"] += len(KBD.findall(span))
        counts["kbd_merged_runs"] += span.count(":kbd:") > 1
        found.append(
            ("hotkey", hotkey_value(span), collapse(span), _line_of(record, match.start()))
        )
    for match in DEFAULT_ROLE.finditer(_masked(text)):
        body = match["text"]
        if " > " in collapse(body) and "<" not in body:
            parts = [collapse(part) for part in body.split(">")]
            found.append(("ui_path", " > ".join(parts), None, _line_of(record, match.start())))
    return found, counts


def extract(records: Iterable[Mapping]) -> dict:
    """Aggregated entries: one per (kind, value, label).

    `locations` index the sorted `records` table of record ids that hold the entry; a record
    id is `<source>:<path>#L<start>-L<end>` (see `docs_index`).
    """
    locations: dict[tuple[str, str, str | None], set[str]] = defaultdict(set)
    occurrences: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for record in records:
        found, record_counts = extract_record(record)
        counts.update(record_counts)
        for kind, value, label, _ in found:
            occurrences[kind] += 1
            locations[(kind, value, label)].add(record["id"])
    table = sorted({record for where in locations.values() for record in where})
    position = {record: index for index, record in enumerate(table)}
    entries = []
    for (kind, value, label), where in sorted(
        locations.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")
    ):
        entry = {
            "kind": kind,
            "value": value,
            "label": label,
            "locations": sorted(position[record] for record in where),
        }
        entries.append(entry)
    operators = {e["value"] for e in entries if e["kind"] == "blender_operator"}
    refs = {e["value"] for e in entries if e["kind"] == "operator_ref"}
    by_kind: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        by_kind[entry["kind"]].add(entry["value"])
    summary = {
        "occurrences": dict(sorted(occurrences.items())),
        "unique_values": {kind: len(values) for kind, values in sorted(by_kind.items())},
        "entries": len(entries),
        "counts": dict(sorted(counts.items())),
        "operator_ids": len(operators),
        "operator_ids_wildcard": sum("*" in value for value in operators),
        "dangling_refs": sorted(refs - operators),
    }
    return {"records": table, "entries": entries, "summary": summary}


def resolved(lexicon: Mapping) -> list[tuple[str, str, str | None, tuple[str, ...]]]:
    """Entries with their locations as record ids."""
    table = lexicon["records"]
    return [
        (e["kind"], e["value"], e["label"], tuple(table[i] for i in e["locations"]))
        for e in lexicon["entries"]
    ]


def restrict(lexicon: Mapping, record_ids: set[str]) -> list[tuple]:
    """Entries as they would be extracted from only these records."""
    out = []
    for kind, value, label, where in resolved(lexicon):
        kept = tuple(record for record in where if record in record_ids)
        if kept:
            out.append((kind, value, label, kept))
    return out
