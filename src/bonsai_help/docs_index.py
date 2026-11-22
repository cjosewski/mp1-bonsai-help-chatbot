"""Section records cut at reStructuredText headings, and a deterministic BM25 core (B2).

A docs source's verified snapshot pages are split into one record per heading. The
records of a page partition its bytes exactly, so every record's line and byte span,
heading path and hash can be recomputed from the hash-pinned page alone. Directives are
kept verbatim and never expanded.

Layout under the data root (outside Git):

    index/<source-id>/<index-id>/sections.jsonl, index.json (written last)
    index/<source-id>/.staging-*      an interrupted build, left for inspection

The BM25 core (terms, Okapi BM25, windows, ranking, the JSONL separator guard) and the
leakage tokens (`g5_tokens`, `ngrams`, used by the gold set at B3) are copied
by hand from the earlier repository's `retrieval.py`; see `docs/PORTING-MAP.md`.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bonsai_help.doc_snapshot import (
    CheckFailed,
    Problem,
    Report,
    check_snapshot,
    dump_json,
    fsync_dir,
    load_canonical,
    snapshot_dir,
    write_new,
)
from bonsai_help.doc_sources import (
    DocSources,
    Refused,
    Source,
    canonical,
    sha256_hex,
    tag_for,
)
from bonsai_help.git_fetch import git_blob_id

PARSER = "rst-sections-v2"
INDEX_SCHEMA = "docs-index-v1"
DIGEST_SCHEMA = "docs-index-digest-v1"

# ------------------------------------------------------------------ BM25 core (ported)

CHUNK_MAX_LINES = 30
CHUNK_STRIDE_LINES = 15
CHUNK_MAX_TOKENS = 480
MIN_TERM_LENGTH = 2
BM25_K1 = 1.2
BM25_B = 0.75
SCORE_DECIMALS = 9
STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from has have how if in into is it "
    "its no not of on or so such than that the their then there these this those to too was "
    "were what when where which while who why will with within without you your".split()
)
JSONL_SEPARATORS = ("\x85", " ", " ")
LEAKAGE_N = 8


def separator_location(text: str) -> tuple[int, str] | None:
    """First line number and character that ``str.splitlines`` would split on besides LF."""
    line = 1
    for char in text:
        if char == "\n":
            line += 1
        elif char in JSONL_SEPARATORS:
            return line, f"U+{ord(char):04X}"
    return None


def split_lines(text: str) -> list[str]:
    """Split on LF; a final empty element after a trailing LF is dropped."""
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def g5_tokens(text: str) -> list[str]:
    """Lower-case ASCII letter and digit runs: the token stream of the leakage check."""
    return re.findall(r"[a-z0-9]+", text.lower())


def ngrams(tokens: Sequence[str], n: int = LEAKAGE_N) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def windows(
    live: Sequence[tuple[int, str]],
    no_boundary: Iterable[int],
    count_tokens: Callable[[str], int],
    *,
    max_lines: int = CHUNK_MAX_LINES,
    stride: int = CHUNK_STRIDE_LINES,
    max_tokens: int = CHUNK_MAX_TOKENS,
) -> tuple[list[tuple[int, int]], list[int]]:
    """Window walk over one segment's lines; returns spans and oversize lines."""
    nb = set(no_boundary)

    def eligible(k: int) -> bool:
        return live[k][1].strip() != "" and live[k][0] not in nb

    def text(a: int, b: int) -> str:
        return "\n".join(line for _, line in live[a:b])

    candidates = [k for k in range(len(live)) if eligible(k)]
    if not candidates:
        return [], []
    last = candidates[-1]
    spans: list[tuple[int, int]] = []
    oversize: list[int] = []
    i = 0
    while True:
        j = min(i + max_lines, len(live))
        a = i
        while a < j and not eligible(a):
            a += 1
        b = j
        while b > a and not eligible(b - 1):
            b -= 1
        while b > a and count_tokens(text(a, b)) > max_tokens:
            b -= 1
            while b > a and not eligible(b - 1):
                b -= 1
        if b > a:
            if (live[a][0], live[b - 1][0]) not in spans:
                spans.append((live[a][0], live[b - 1][0]))
        elif a < j and live[a][0] not in oversize:
            oversize.append(live[a][0])
        if a >= len(live) or (b > a and b - 1 >= last):
            break
        i = max(i + 1, min(i + stride, b))
    return spans, oversize


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*(?:(?:\.|::)[A-Za-z_][A-Za-z0-9_]*)*(?:@[A-Za-z0-9_]*)?"
_NUMBER = r"\d+(?:\.\d+)*(?:[eE][-+]?\d+)?"
CANDIDATE_RE = re.compile(f"{_IDENT}|{_NUMBER}", re.ASCII)
_SUBWORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", re.ASCII)
_SEPARATORS = re.compile(r"(\.|::|@)")


def candidates(text: str) -> list[str]:
    """CANDIDATE matches, left to right, with repeats."""
    return [m.group() for m in CANDIDATE_RE.finditer(text)]


def _is_number(candidate: str) -> bool:
    return candidate[:1].isdigit()


def candidate_terms(candidate: str) -> set[str]:
    """``terms(c)`` after lowercasing, the length floor and the stopwords."""
    if _is_number(candidate):
        found = {candidate}
    else:
        pieces = _SEPARATORS.split(candidate)
        parts = pieces[0::2]
        found = {candidate}
        found.update(p for p in parts if p)
        for k in range(2, len(parts) + 1):
            first = len(parts) - k
            if all(parts[first:]):
                found.add("".join(pieces[2 * first :]))
        for part in parts:
            subwords = [w for piece in part.split("_") for w in _SUBWORD.findall(piece)]
            if len(subwords) >= 2:
                found.update(subwords)
    lowered = {t.lower() for t in found}
    return {t for t in lowered if len(t) >= MIN_TERM_LENGTH and t not in STOPWORDS}


def terms(text: str) -> list[str]:
    """A text's BM25 term multiset: each candidate's distinct terms, once per occurrence."""
    out: list[str] = []
    for candidate in candidates(text):
        out.extend(sorted(candidate_terms(candidate)))
    return out


class BM25Index:
    """Okapi BM25 over term lists; per-document sums run in sorted query-term order."""

    def __init__(
        self, documents: Sequence[Sequence[str]], *, k1: float = BM25_K1, b: float = BM25_B
    ):
        self.k1, self.b = k1, b
        self.tf = [Counter(doc) for doc in documents]
        self.length = [len(doc) for doc in documents]
        self.n = len(documents)
        self.avgdl = sum(self.length) / self.n if self.n else 0.0
        self.df: Counter = Counter()
        self.postings: dict[str, list[int]] = {}
        for index, counts in enumerate(self.tf):
            for term in sorted(counts):
                self.df[term] += 1
                self.postings.setdefault(term, []).append(index)

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((self.n - df + 0.5) / (df + 0.5) + 1)

    def scores(self, query_terms: Iterable[str]) -> list[float]:
        out = [0.0] * self.n
        if not self.n or not self.avgdl:
            return out
        k1, b = self.k1, self.b
        for term in sorted(set(query_terms)):
            postings = self.postings.get(term)
            if not postings:
                continue
            weight = self.idf(term)
            for index in postings:
                tf = self.tf[index][term]
                norm = k1 * (1 - b + b * self.length[index] / self.avgdl)
                out[index] += weight * tf * (k1 + 1) / (tf + norm)
        return out


def bm25_scores(documents: Sequence[str], query: str) -> list[float]:
    """Raw BM25 of a query text against document texts, rounded to 9 decimals."""
    index = BM25Index([terms(d) for d in documents])
    return [round(s, SCORE_DECIMALS) for s in index.scores(terms(query))]


def word_count(text: str) -> int:
    """The passage size measure: whitespace-separated words (no tokenizer dependency)."""
    return len(text.split())


@dataclass(frozen=True)
class Passage:
    key: str
    record_id: str
    source_index: int
    path: str
    start: int
    end: int
    text: str


def passages(
    records: Sequence[Mapping],
    source_order: Mapping[str, int],
    count_tokens: Callable[[str], int] = word_count,
) -> tuple[list[dict], list[str]]:
    """Window every record's lines; a passage never crosses a record. Returns rows, oversize."""
    rows: list[dict] = []
    oversize: list[str] = []
    for record in records:
        lines = split_lines(record["text"])
        first = record["line_start"]
        live = [(first + k, line) for k, line in enumerate(lines)]
        spans, over = windows(live, (), count_tokens)
        oversize += [f"{record['id']}@L{n}" for n in over]
        for a, b in spans:
            rows.append(
                {
                    "key": f"{record['id']}@L{a}-L{b}",
                    "record_id": record["id"],
                    "source": record["source"],
                    "source_index": source_order[record["source"]],
                    "path": record["path"],
                    "start": a,
                    "end": b,
                    "text": "\n".join(lines[a - first : b - first + 1]),
                }
            )
    return rows, oversize


def finalize_passages(rows: Sequence[Mapping]) -> tuple[list[Passage], dict]:
    """Drop duplicate spans, collapse identical text per source, drop term-less passages."""
    ordered = sorted(rows, key=lambda r: (r["source_index"], r["path"], r["start"], r["end"]))
    seen: set[tuple] = set()
    first_by_text: dict[tuple[str, str], str] = {}
    kept: list[Passage] = []
    record: dict[str, list] = {"duplicate_spans": [], "collapsed": [], "no_terms": []}
    for row in ordered:
        span = (row["source"], row["path"], row["start"], row["end"])
        if span in seen:
            record["duplicate_spans"].append(row["key"])
            continue
        seen.add(span)
        text_key = (row["source"], row["text"])
        if text_key in first_by_text:
            record["collapsed"].append({"key": row["key"], "kept": first_by_text[text_key]})
            continue
        first_by_text[text_key] = row["key"]
        if not terms(row["text"]):
            record["no_terms"].append(row["key"])
            continue
        kept.append(
            Passage(
                row["key"],
                row["record_id"],
                row["source_index"],
                row["path"],
                row["start"],
                row["end"],
                row["text"],
            )
        )
    return kept, record


@dataclass(frozen=True)
class Scored:
    passage: Passage
    score: float


def score_passage(passage: Passage, raw: float) -> Scored:
    return Scored(passage, round(raw, SCORE_DECIMALS))


def rank_key(scored: Scored) -> tuple:
    p = scored.passage
    return (-scored.score, p.source_index, p.path, p.start, p.end, p.key)


def rank(scored: Iterable[Scored]) -> list[Scored]:
    """A total order: score, then source order, path, span and key."""
    return sorted(scored, key=rank_key)


def search(found: Sequence[Passage], query: str, top: int) -> list[Scored]:
    index = BM25Index([terms(p.text) for p in found])
    raw = index.scores(terms(query))
    ranked = rank(score_passage(p, s) for p, s in zip(found, raw, strict=True) if s > 0)
    return ranked[:top]


# ------------------------------------------------------------------ RST section splitter

PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
LABEL = re.compile(r"\.\. _(?P<label>`[^`]+`|[^`:\s][^:]*):[ \t]*")
INCLUDE = re.compile(r"[ \t]*\.\. include::[ \t]*(?P<target>\S.*?)[ \t]*")
TOCTREE = re.compile(r"(?P<indent>[ \t]*)\.\. toctree::.*")
INDEX = re.compile(r"\.\. index::.*")
OPTION = re.compile(r"[ \t]+:[\w-]+:.*")
MARKUP = re.compile(r"`|\*|\||:[\w-]+:")
ESCAPE = re.compile(r"``.+?``|\\(?P<char>.)")


def unescape(text: str) -> str:
    """RST backslash escapes rendered as docutils does: `\\x` gives `x` and an escaped space
    gives nothing; inline literals are kept as written. Other markup is not rendered."""

    def replace(match: re.Match) -> str:
        char = match["char"]
        if char is None:
            return match.group()
        return "" if char.isspace() else char

    return ESCAPE.sub(replace, text)


class PageRefused(CheckFailed):
    """A page that is not strict UTF-8 without BOM or CR (spans must equal upstream)."""


def decode_page(data: bytes, shown: str) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PageRefused(f"{shown}: not strict UTF-8 ({error.reason})") from None
    if text.startswith("﻿"):
        raise PageRefused(f"{shown}: starts with a byte order mark")
    if "\r" in text:
        raise PageRefused(f"{shown}: contains a carriage return")
    return text


def is_adornment(line: str) -> bool:
    """Two or more of one punctuation character from column 0, trailing whitespace only."""
    body = line.rstrip(" \t")
    return (
        len(body) >= 2
        and body[0] in PUNCTUATION
        and body == body[0] * len(body)
        and not line[:1].isspace()
    )


def _blank(line: str) -> bool:
    return not line.strip()


def _explicit_markup(line: str) -> bool:
    return line.startswith("..") and (len(line) == 2 or line[2] in " \t")


@dataclass
class Title:
    start: int  # 0-based first line (the overline when there is one)
    line: int  # 0-based title text line
    end: int  # 0-based adornment line that closes the title
    raw: str  # the title line as written; `text` renders its backslash escapes
    style: tuple[str, bool]

    @property
    def text(self) -> str:
        return unescape(self.raw)


@dataclass
class Diagnostics:
    short_underline: list[str] = field(default_factory=list)
    short_underline_text: list[str] = field(default_factory=list)
    overline_mismatch: list[str] = field(default_factory=list)
    level_jump: list[str] = field(default_factory=list)
    auto_label_markup: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {name: len(value) for name, value in sorted(vars(self).items())}


def find_titles(lines: Sequence[str], shown: str, diagnostics: Diagnostics) -> list[Title]:
    """Section titles by docutils' adornment rules; indented lines are never titles."""
    found: list[Title] = []
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        opens = i == 0 or _blank(lines[i - 1]) or LABEL.fullmatch(lines[i - 1]) is not None
        if not opens:
            i += 1
            continue
        if (
            is_adornment(line)
            and i + 2 < n
            and not _blank(lines[i + 1])
            and not is_adornment(lines[i + 1])
            and is_adornment(lines[i + 2])
        ):
            if lines[i + 2].rstrip() == line.rstrip():
                char = line[0]
                found.append(Title(i, i + 1, i + 2, lines[i + 1].strip(), (char, True)))
                i += 3
                continue
            diagnostics.overline_mismatch.append(f"{shown}:{i + 1}")
            i += 1
            continue
        if (
            not _blank(line)
            and not line[0].isspace()
            and not is_adornment(line)
            and not _explicit_markup(line)
            and i + 1 < n
            and is_adornment(lines[i + 1])
        ):
            under = len(lines[i + 1].rstrip())
            title = line.rstrip()
            if under < len(title):
                if under < 4:
                    # docutils: "Possible title underline, too short ... ordinary text".
                    diagnostics.short_underline_text.append(f"{shown}:{i + 1}")
                    i += 1
                    continue
                diagnostics.short_underline.append(f"{shown}:{i + 1}")
            found.append(Title(i, i, i + 1, title.strip(), (lines[i + 1][0], False)))
            i += 2
            continue
        i += 1
    return found


def _attached_start(lines: Sequence[str], start: int, floor: int) -> tuple[int, list[str]]:
    """First line of the labels and `.. index::` blocks directly before a title."""
    first, labels = start, []
    j = start - 1
    while j >= floor:
        while j >= floor and _blank(lines[j]):
            j -= 1
        if j < floor:
            break
        match = LABEL.fullmatch(lines[j])
        if match:
            labels.append(match["label"])
            first = j
            j -= 1
            continue
        k = j
        while k >= floor and (lines[k][:1].isspace() or _blank(lines[k])):
            k -= 1
        if k >= floor and INDEX.fullmatch(lines[k]):
            first = k
            j = k - 1
            continue
        break
    return first, list(reversed(labels))


def _resolve(target: str, page: str, root: str, pages: frozenset[str]) -> str | None:
    target = target.strip()
    if target.startswith("/"):
        candidate = f"{root}{target}"
    else:
        candidate = "/".join([*page.split("/")[:-1], target])
    parts: list[str] = []
    for part in candidate.split("/"):
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    resolved = "/".join(parts)
    for option in (resolved, f"{resolved}.rst"):
        if option in pages:
            return option
    return None


def _directives(
    lines: Sequence[str], first: int, last: int, page: str, root: str, pages: frozenset[str]
) -> tuple[list[dict], list[str], list[dict]]:
    """Includes, toctree targets and labels not attached to a title, inside lines first..last."""
    includes, toctree, targets = [], [], []
    k = first
    while k <= last:
        line = lines[k]
        match = INCLUDE.fullmatch(line)
        if match:
            options = []
            j = k + 1
            while j <= last and OPTION.fullmatch(lines[j]):
                options.append(lines[j].strip())
                j += 1
            target = match["target"]
            includes.append(
                {
                    "target": target,
                    "line": k + 1,
                    "options": options,
                    "resolved": _resolve(target, page, root, pages),
                }
            )
        tree = TOCTREE.fullmatch(line)
        if tree:
            indent = len(tree["indent"])
            j = k + 1
            while j <= last and (
                _blank(lines[j]) or len(lines[j]) - len(lines[j].lstrip()) > indent
            ):
                entry = lines[j].strip()
                if entry and not OPTION.fullmatch(lines[j]):
                    inner = re.fullmatch(r".*<(?P<target>[^<>]+)>", entry)
                    toctree.append(inner["target"] if inner else entry)
                j += 1
        stripped = line.lstrip(" \t")
        label = LABEL.fullmatch(stripped)
        if label:
            targets.append({"label": label["label"], "line": k + 1})
        k += 1
    return includes, toctree, targets


def docname(source: Source, path: str) -> str:
    relative = path[len(source.root) + 1 :]
    return relative[: -len(".rst")] if relative.endswith(".rst") else relative


def split_page(
    source: Source,
    pin: str,
    commit: str,
    path: str,
    data: bytes,
    pages: frozenset[str],
    diagnostics: Diagnostics,
) -> list[dict]:
    """One record per heading; the records' byte spans concatenate to the page exactly."""
    shown = f"{source.id}:{path}"
    text = decode_page(data, shown)
    lines = split_lines(text)
    offsets = [0]
    for k, line in enumerate(lines):
        has_lf = k < len(lines) - 1 or text.endswith("\n")
        offsets.append(offsets[-1] + len(line.encode()) + (1 if has_lf else 0))
    assert offsets[-1] == len(data)
    titles = find_titles(lines, shown, diagnostics)
    styles: list[tuple[str, bool]] = []
    starts: list[tuple[int, list[str]]] = []
    floor = 0
    for title in titles:
        starts.append(_attached_start(lines, title.start, floor))
        floor = title.end + 1
    heads: list[dict] = []
    if not titles:
        heads.append({"first": 0, "title": None, "raw": None, "level": 0, "labels": [], "path": []})
    stack: list[tuple[int, str]] = []
    for index, title in enumerate(titles):
        if title.style not in styles:
            styles.append(title.style)
        level = styles.index(title.style) + 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        if level > (stack[-1][0] if stack else 0) + 1:
            diagnostics.level_jump.append(f"{shown}:{title.line + 1}")
        stack.append((level, title.text))
        first, labels = starts[index]
        heads.append(
            {
                "first": 0 if index == 0 else first,
                "title": title.text,
                "raw": title.raw,
                "title_line": title.line + 1,
                "level": level,
                "depth": len(stack),
                "labels": labels,
                "path": [name for _, name in stack],
            }
        )
    asl = source.autosectionlabel
    tag = tag_for(source, path)
    page_blob = git_blob_id(data)
    page_sha = sha256_hex(data)
    records = []
    for index, head in enumerate(heads):
        first = head["first"]
        last = (heads[index + 1]["first"] if index + 1 < len(heads) else len(lines)) - 1
        following = [
            later["first"] for later in heads[index + 1 :] if later["level"] <= head["level"]
        ]
        subtree_end = (following[0] if following else len(lines)) - 1
        body = data[offsets[first] : offsets[last + 1]]
        includes, toctree, targets = _directives(lines, first, last, path, source.root, pages)
        auto_label = None
        if asl is not None and head["title"] is not None and head["depth"] <= asl.maxdepth:
            # Sphinx's autosectionlabel names a section by its title's raw source.
            if MARKUP.search(head["raw"]):
                diagnostics.auto_label_markup.append(f"{shown}:{head['title_line']}")
            else:
                prefix = f"{docname(source, path)}:" if asl.prefix_document else ""
                auto_label = prefix + head["raw"]
        anchored = set(head["labels"])
        record = {
            "id": f"{source.id}:{path}#L{first + 1}-L{last + 1}",
            "source": source.id,
            "pin_id": pin,
            "commit": commit,
            "path": path,
            "page_blob": page_blob,
            "page_sha256": page_sha,
            "tag": tag,
            "ordinal": index,
            "level": head["level"],
            "heading_path": head["path"],
            "title": head["title"],
            "title_line": head.get("title_line"),
            "line_start": first + 1,
            "line_end": last + 1,
            "subtree_line_end": subtree_end + 1,
            "byte_start": offsets[first],
            "byte_end": offsets[last + 1],
            "anchors": head["labels"],
            "auto_label": auto_label,
            "inline_targets": [t for t in targets if t["label"] not in anchored],
            "includes": includes,
            "toctree": toctree,
            "text": body.decode("utf-8"),
            "sha256": sha256_hex(body),
        }
        records.append(record)
    return records


# ------------------------------------------------------------------ build and check


@dataclass
class SourceIndex:
    source: Source
    records: list[dict]
    summary: dict

    def jsonl(self) -> bytes:
        return b"".join(
            json.dumps(record, sort_keys=True, ensure_ascii=False).encode() + b"\n"
            for record in self.records
        )


def docs_sources(config: DocSources) -> list[Source]:
    return [source for source in config.sources if source.role == "docs"]


def index_id(source: Source, entry: dict) -> str:
    settings = source.autosectionlabel.model_dump() if source.autosectionlabel else None
    spec = {
        "parser": PARSER,
        "pin_id": entry["pin_id"],
        "source_digest": entry["source_digest"],
        "settings": settings,
    }
    return f"{source.id}-{sha256_hex(canonical(spec))[:16]}"


def index_pages(source: Source, entry: dict, read: Callable[[str], bytes]) -> SourceIndex:
    """Split every page of a manifest entry; `read(path)` gives hash-verified page bytes."""
    diagnostics = Diagnostics()
    pages = frozenset(page["path"] for page in entry["pages"])
    records: list[dict] = []
    headless = 0
    commit = entry["repository"]["commit"]
    for page in entry["pages"]:
        found = split_page(
            source, entry["pin_id"], commit, page["path"], read(page["path"]), pages, diagnostics
        )
        headless += found[0]["title"] is None
        records += found
    for record in records:
        where = separator_location(record["text"])
        if where is not None:
            raise Refused(
                f"{record['id']}: line {where[0]} holds {where[1]}; a JSONL reader would split it"
            )
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise CheckFailed(f"{source.id}: duplicate record ids")
    result = SourceIndex(source, records, {})
    result.summary = {
        "pin_id": entry["pin_id"],
        "source_digest": entry["source_digest"],
        "index_id": index_id(source, entry),
        "parser": PARSER,
        "pages": len(entry["pages"]),
        "records": len(records),
        "headless_pages": headless,
        "records_sha256": sha256_hex(result.jsonl()),
        "diagnostics": diagnostics.counts(),
    }
    return result


def index_from_snapshot(config: DocSources, manifest: dict, data_root: Path) -> list[SourceIndex]:
    """Verify each docs snapshot against the committed manifest, then split its pages."""
    out = []
    for source in docs_sources(config):
        entry = manifest["sources"][source.id]
        snapshot = snapshot_dir(data_root, source, config.repository_of(source))
        shown = f"snapshots/{source.id}/{snapshot.name}"
        if not snapshot.is_dir():
            raise CheckFailed(f"{source.id}: {shown} not built (run snapshot build)")
        problems = check_snapshot(source, entry, snapshot, shown)
        if problems:
            raise CheckFailed("; ".join(map(str, problems[:3])))
        files = snapshot / "files"
        out.append(
            index_pages(source, entry, lambda path, files=files: (files / path).read_bytes())
        )
    return out


def index_dir(data_root: Path, built: SourceIndex) -> Path:
    return data_root / "index" / built.source.id / built.summary["index_id"]


def _receipt(built: SourceIndex) -> dict:
    return {"schema": INDEX_SCHEMA, "source": built.source.id, **built.summary}


def write_index(data_root: Path, built: SourceIndex) -> str:
    """Write a new index through a staging directory, or verify a present one byte for byte."""
    final = index_dir(data_root, built)
    shown = f"index/{built.source.id}/{final.name}"
    records, receipt = built.jsonl(), dump_json(_receipt(built))
    if final.exists():
        try:
            same = (final / "sections.jsonl").read_bytes() == records and (
                final / "index.json"
            ).read_bytes() == receipt
        except OSError:
            same = False
        if not same:
            raise Refused(f"{built.source.id}: existing {shown} differs from a rebuild; inspect it")
        return f"{built.source.id}: {shown} present, verified, not rewritten"
    parent = final.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".staging-{final.name}-{secrets.token_hex(4)}"
    os.mkdir(staging)
    try:
        write_new(staging / "sections.jsonl", records)
        os.sync()
        write_new(staging / "index.json", receipt)
        fsync_dir(staging)
        os.rename(staging, final)
    except OSError as error:
        raise Refused(
            f"{built.source.id}: writing {shown} failed ({error.strerror}); inspect {staging.name}"
        ) from None
    fsync_dir(parent)
    return (
        f"{built.source.id}: built {shown}: {built.summary['pages']} pages, "
        f"{built.summary['records']} records"
    )


def load_index(config: DocSources, manifest: dict, data_root: Path) -> list[dict]:
    """Records of every built docs index, re-hashed against their receipts."""
    records: list[dict] = []
    for source in docs_sources(config):
        entry = manifest["sources"][source.id]
        directory = data_root / "index" / source.id / index_id(source, entry)
        shown = f"index/{source.id}/{directory.name}"
        try:
            receipt = json.loads((directory / "index.json").read_bytes())
            data = (directory / "sections.jsonl").read_bytes()
        except (OSError, ValueError):
            raise CheckFailed(f"{source.id}: {shown} not built (run docs index build)") from None
        if sha256_hex(data) != receipt.get("records_sha256"):
            raise CheckFailed(f"{source.id}: {shown}/sections.jsonl does not match its receipt")
        records += [json.loads(line) for line in data.decode("utf-8").split("\n") if line]
    return records


def digest_document(built: Sequence[SourceIndex]) -> dict:
    document = {
        "schema": DIGEST_SCHEMA,
        "parser": PARSER,
        "sources": {item.source.id: item.summary for item in built},
    }
    return {**document, "digest": sha256_hex(canonical(document))}


def check_digest_committed(
    config: DocSources, manifest: dict, digest_path: Path
) -> tuple[dict | None, list[Problem]]:
    """The committed digest file is canonical and agrees with the config and manifest."""
    label = "docs-index"
    document, problems = load_canonical(digest_path, DIGEST_SCHEMA, "digest", label)
    if document is None:
        return None, problems or [Problem(label, digest_path.name, "missing")]
    sources = document.get("sources", {})
    expected = {source.id for source in docs_sources(config)}
    if set(sources) != expected:
        problems.append(Problem(label, digest_path.name, "sources differ from the config"))
    for source in docs_sources(config):
        summary, entry = sources.get(source.id), manifest["sources"].get(source.id)
        if not isinstance(summary, dict) or not isinstance(entry, dict):
            continue
        for key, want in (
            ("pin_id", entry["pin_id"]),
            ("source_digest", entry["source_digest"]),
            ("pages", entry["totals"]["pages"]),
            ("index_id", index_id(source, entry)),
            ("parser", PARSER),
        ):
            if summary.get(key) != want:
                problems.append(Problem(source.id, digest_path.name, f"{key} is stale"))
    return document, problems


def build_index(
    config: DocSources, manifest: dict, data_root: Path, digest_path: Path, *, write_digest: bool
) -> Report:
    built = index_from_snapshot(config, manifest, data_root)
    report = Report()
    wanted = dump_json(digest_document(built))
    if not write_digest:
        _, problems = check_digest_committed(config, manifest, digest_path)
        if problems:
            raise CheckFailed("; ".join(map(str, problems[:3])))
        if digest_path.read_bytes() != wanted:
            raise CheckFailed(
                f"{digest_path.name}: a rebuild differs from the committed digest; inspect it"
            )
    for item in built:
        report.lines.append(write_index(data_root, item))
    if write_digest:
        if digest_path.is_file() and digest_path.read_bytes() == wanted:
            report.lines.append(f"{digest_path.name} unchanged")
        else:
            digest_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = digest_path.with_name(f".{digest_path.name}.{secrets.token_hex(4)}")
            write_new(temporary, wanted)
            os.replace(temporary, digest_path)
            report.lines.append(f"{digest_path.name} written")
    return report


def check_index(
    config: DocSources, manifest: dict, data_root: Path | None, digest_path: Path
) -> list[Problem]:
    document, problems = check_digest_committed(config, manifest, digest_path)
    if problems or document is None or data_root is None:
        return problems
    built = index_from_snapshot(config, manifest, data_root)
    if dump_json(digest_document(built)) != digest_path.read_bytes():
        problems.append(Problem("docs-index", digest_path.name, "differs from a rebuild"))
    for item in built:
        directory = index_dir(data_root, item)
        shown = f"index/{item.source.id}/{directory.name}"
        try:
            same = (directory / "sections.jsonl").read_bytes() == item.jsonl()
        except OSError:
            problems.append(Problem(item.source.id, shown, "not built (run docs index build)"))
            continue
        if not same:
            problems.append(Problem(item.source.id, shown, "sections.jsonl differs from a rebuild"))
    return problems
