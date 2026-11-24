"""Deterministic pre-checks, one or more per rubric dimension.

These are heuristics. A failed check is evidence for the first-pass gate and the judge;
none of them replaces a human or judge decision. ``drop`` marks a failure the gate may
act on by itself; unknown Blender operators and menu paths are evidence only
(``EVIDENCE_ONLY``).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal

from bonsai_help.schemas import GeneratedItem

Dimension = Literal["D1", "D2", "D3", "D4", "D5", "D6"]

MIN_ANSWER_WORDS = 60
MIN_SAFETY_CHARS = 80
MIN_QUESTION_WORDS = 6
MIN_PROBLEM_WORDS = 3
MIN_TIP_CHARS = 30
TIP_STEP_JACCARD = 0.8
MIN_QUOTE_WORDS = 5
MAX_ECHO_CHARS = 80

GENERIC_PHRASES = frozenset(
    {
        "be careful",
        "use caution",
        "stay safe",
        "good luck",
        "practice makes perfect",
        "take your time",
        "follow the steps",
        "follow the instructions",
        "double check your work",
        "be safe",
        "stay careful",
        "use common sense",
    }
)
GENERIC_RESIDUAL_WORDS = 5
REFUSAL_PHRASES = ("as an ai", "i cannot help", "i'm unable to")
EVIDENCE_ONLY = frozenset({"blender_operators_known", "menu_paths_known"})
# Capitalized words, or two-word phrases, that may open a step just before a menu label
# ("Open Object > Apply", "Right click Object > Apply"). Any other capitalized word there
# is read as part of an invented label, unless it ends in "," or ":" (a clause break).
LEAD_IN_WORDS = frozenset(
    {
        "open",
        "go",
        "click",
        "right click",
        "double click",
        "select",
        "choose",
        "pick",
        "use",
        "press",
        "navigate",
        "find",
        "locate",
        "expand",
        "switch",
        "then",
        "next",
        "now",
        "finally",
        "first",
        "also",
        "using",
        "access",
        "enter",
        "in",
        "from",
        "under",
        "via",
    }
)
# Bonsai-source lexicon entries that are invocable ``bpy.ops.bim.*`` ids.
BIM_OPERATOR_KINDS = ("operator", "macro")

_BIM_ID = re.compile(r"\bbim\.[a-z0-9_]+")
_OPERATOR = re.compile(r"\b([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\b")
_MENU_SPLIT = re.compile(r"\s*(?:-->|->|=>|→|›|>)\s*")
_MENU_PATH = re.compile(r"[^\n.;:]*(?:-->|->|=>|→|›|>)[^\n.;:]*")
# A comma followed by a lowercase word ends one path and starts prose ("Edit > Preferences,
# then Add-ons > Install"); a comma between capitalized labels ("Move, Rotate") does not.
_PATH_BREAK = re.compile(r",\s+(?=[a-z])")
_TIP_NUMBER = re.compile(r"^\d+\s+")


@dataclass(frozen=True)
class CheckResult:
    dimension: Dimension
    name: str
    passed: bool
    drop: bool
    detail: str


@dataclass(frozen=True)
class Lexicons:
    """Per version line: Bonsai operator ids, Blender operator ids and menu labels.

    ``bim_ids`` holds only registered operators and macros. ``menu_segments`` holds the
    normalized labels of the Manual's menu paths, gui labels and operator labels, the
    Bonsai docs' menu and ui paths, and the Bonsai source's button texts and class labels.
    """

    bim_ids: dict[str, frozenset[str]]
    blender_operators: dict[str, frozenset[str]]
    menu_segments: dict[str, frozenset[str]]


def normalize(text: str) -> str:
    """NFKC and casefold, punctuation to spaces, whitespace collapsed."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = "".join(" " if unicodedata.category(c).startswith("P") else c for c in folded)
    return " ".join(folded.split())


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def _segment(text: str) -> str:
    return normalize(re.sub(r"[`*:]|\bmenu\b", " ", text, flags=re.IGNORECASE))


def load_lexicons(reference_dir: Path) -> Lexicons:
    """Read the committed lexicons named by each version line of the setup profiles."""
    lex_dir = reference_dir / "lexicons"
    profiles = json.loads((reference_dir / "setup-profiles.json").read_bytes())
    bim: dict[str, frozenset[str]] = {}
    operators: dict[str, frozenset[str]] = {}
    segments: dict[str, frozenset[str]] = {}
    for line in profiles["version_lines"]:
        sources = line["sources"]
        source = json.loads((lex_dir / f"{sources['bonsai_source']}.json").read_bytes())
        bim[line["id"]] = frozenset(
            e["id"].casefold()
            for e in source["entries"]
            if isinstance(e.get("id"), str)
            and e.get("kind") in BIM_OPERATOR_KINDS
            and e.get("registered") is True
        )
        manual = json.loads((lex_dir / f"{sources['blender_manual']}.json").read_bytes())
        ops: set[str] = set()
        segs: set[str] = set()
        for entry in manual["entries"]:
            value = entry.get("value")
            if not isinstance(value, str):
                continue
            if entry["kind"] in ("blender_operator", "operator_ref"):
                ops.add(value.casefold())
                # The Manual documents each operator under its UI label ("Cube").
                if isinstance(entry.get("label"), str):
                    segs.add(_segment(entry["label"]))
            elif entry["kind"] == "menu_path":
                segs.update(_segment(part) for part in _MENU_SPLIT.split(value))
            elif entry["kind"] == "guilabel":
                segs.add(_segment(value))
        docs = json.loads((lex_dir / f"{sources['bonsai_docs']}.json").read_bytes())
        for entry in docs["entries"]:
            value = entry.get("value")
            if isinstance(value, str) and entry["kind"] in ("menu_path", "ui_path"):
                segs.update(_segment(part) for part in _MENU_SPLIT.split(value))
        for text in source.get("ui_texts", []):
            segs.add(_segment(text["text"]))
        for entry in source["entries"]:
            if isinstance(entry.get("label"), str):
                segs.add(_segment(entry["label"]))
        operators[line["id"]] = frozenset(ops)
        segments[line["id"]] = frozenset(s for s in segs if s)
    return Lexicons(bim, operators, segments)


def _initial_is_upper(word: str) -> bool:
    return next((c for c in word if c.isalpha()), "").isupper()


def _lead_in_ok(words: list[str], i: int) -> bool:
    """Whether ``words[:i]`` may stand before a label that starts at ``words[i]``.

    The word just before the label must be lowercase prose, or, when it opens the
    path, one of ``LEAD_IN_WORDS`` or a word ending in "," or ":" (a clause break,
    "Finally, File"). A two-word lead-in ("Right Click") may open the path the same way.
    Any other capitalized word is part of the label.
    """
    before = words[i - 1]
    if not _initial_is_upper(before):
        return True
    if i == 1:
        return before.endswith((",", ":")) or _segment(before) in LEAD_IN_WORDS
    return i == 2 and _segment(" ".join(words[:2])) in LEAD_IN_WORDS


def _menu_part_known(part: str, segments: frozenset[str], *, first: bool, last: bool) -> bool:
    """Whole-label match of one menu-path part; prose may only sit outside the path.

    A part is known when it equals a lexicon label after normalization. The first part
    may carry lead-in prose ("In Object Mode, open Object"): some trailing run of its
    words must be a label, preceded by a lowercase word or by a lead-in or clause break
    that opens the path ("Open Object", "Finally, File"; see ``_lead_in_ok``); leading
    words with no letters ("1)") are skipped. The last
    part may carry trailing prose ("Scale and confirm"): some leading run must be a
    label, followed by a word that is not capitalized. Labels never match inside a word
    or as a fragment of a longer label.
    """
    if _segment(part) in segments:
        return True
    words = part.split()
    if first:
        lead = words
        while lead and not any(c.isalpha() for c in lead[0]):
            lead = lead[1:]
        if lead and _segment(" ".join(lead)) in segments:
            return True
        for i in range(1, len(lead)):
            if _segment(" ".join(lead[i:])) in segments and _lead_in_ok(lead, i):
                return True
    if last:
        for j in range(len(words) - 1, 0, -1):
            if _segment(" ".join(words[:j])) in segments and not _initial_is_upper(words[j]):
                return True
    return False


_WILDCARD_WORDS = "[a-z0-9]+(?:_[a-z0-9]+)*"


def _wildcard_patterns(operators: Iterable[str]) -> list[re.Pattern[str]]:
    """The Manual's wildcard operator entries as whole-id patterns.

    Each ``*`` stands for one or more whole underscore-separated words, never for the
    empty string: ``*.select_box`` matches ``view3d.select_box``, ``object.*clear``
    matches ``object.location_clear`` but not ``object.clear`` or ``object.xclear``.
    """
    patterns = []
    for o in sorted(operators):
        if "*" not in o:
            continue
        pieces = o.split("*")
        parts = [re.escape(pieces[0])]
        for before, after in pairwise(pieces):
            lead = "_" if before[-1:].isalnum() else ""
            tail = "_" if after[:1].isalnum() else ""
            parts.append(f"{lead}{_WILDCARD_WORDS}{tail}{re.escape(after)}")
        patterns.append(re.compile("".join(parts)))
    return patterns


def _normalize_keep_dots(text: str) -> str:
    """NFKC and casefold only, so dotted operator ids survive."""
    return unicodedata.normalize("NFKC", text).casefold()


def _phrase_matches(phrase: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(normalize(phrase))}(?!\w)", text) is not None


def _is_generic(text: str) -> bool:
    """Generic only if under GENERIC_RESIDUAL_WORDS words remain once phrases are removed."""
    rest = normalize(text)
    for phrase in sorted(GENERIC_PHRASES, key=len, reverse=True):
        rest = re.sub(rf"(?<!\w){re.escape(normalize(phrase))}(?!\w)", " ", rest)
    return len(rest.split()) < GENERIC_RESIDUAL_WORDS and normalize(text) != " ".join(rest.split())


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _words(text: str) -> int:
    return len(text.split())


def _quote_form(text: str) -> str:
    """NFC with every whitespace run collapsed to one space; nothing else is changed."""
    return " ".join(unicodedata.normalize("NFC", text).split())


# reStructuredText inline markup, approximating the docutils recognition rules but
# narrower: a start-string follows the text's start, whitespace, a hyphen or an opening
# bracket or quote mark (not a slash or colon, so a path's `/*.ifc` never opens emphasis)
# and is followed by a non-space; an end-string follows a non-space and precedes the
# text's end, whitespace or closing punctuation. Emphasis and strong text hold no
# asterisk or backtick, interpreted text and roles no backtick. Anything else (`5 * 3`,
# `*args`, `bim.add_*`, `C:/models/*.ifc`, `snake_case_`, an unpaired backtick) is an
# ordinary character.
_MARKUP_PRE = r"(?<![^\s\-'\"<(\[{\u2018\u201c\u00ab])"
_MARKUP_SUF = r"(?![^\s\-.,:;!?\\/'\")\]}>\u2019\u201d\u00bb])"
_BACKTICK_TEXT = r"[^`\s](?:[^`]*[^`\s])?"
_STAR_TEXT = r"[^*`\s](?:[^*`]*[^*`\s])?"
_INLINE_MARKUP = re.compile(
    _MARKUP_PRE
    + "(?:"
    # :role:`text`, also :domain:role:`text` (:kbd:, :menuselection:, :ref:, :py:func:)
    + r":(?P<role_name>[A-Za-z0-9][\w+.-]*(?::[A-Za-z0-9][\w+.-]*)*)"
    + rf":`(?P<role>{_BACKTICK_TEXT})`"
    + r"|``(?P<literal>\S(?:.*?\S)?)``"  # ``literal`` (its content is kept as it is)
    + rf"|\*\*(?P<strong>{_STAR_TEXT})\*\*"  # **strong**
    + rf"|\*(?P<emphasis>{_STAR_TEXT})\*"  # *emphasis*
    # `interpreted`, `link`_, `anonymous link`__
    + rf"|`(?P<interpreted>{_BACKTICK_TEXT})`(?P<link>__?)?"
    + ")"
    + _MARKUP_SUF
)
# The explicit target of `text <target>`_ or :ref:`text <target>`; only "text" is shown.
_EXPLICIT_TARGET = re.compile(r"^(?P<text>.*?\S)\s+<[^<>]+>$")
# Roles whose `text <target>` names a target that is not shown (Sphinx cross-references),
# and every domain role (:py:func:, :std:ref:). Any other role, :kbd: or :menuselection:
# among them, shows its text whole, angle brackets included, as does interpreted text
# with no trailing `_` or `__`.
_TARGET_ROLES = frozenset(
    {"ref", "doc", "term", "any", "numref", "download", "keyword", "option", "envvar", "token"}
)


def _unmark(match: re.Match[str], *, keep_targets: bool, roles: frozenset[str] | None) -> str:
    role = match.group("role_name")
    if role is not None:
        role = role.lower()
        if roles is not None and role not in roles:
            return match.group(0)
        text = match.group("role")
        has_target = ":" in role or role in _TARGET_ROLES
    elif match.group("interpreted") is not None:
        text = match.group("interpreted")
        has_target = match.group("link") is not None
    else:
        return next(match.group(k) for k in ("literal", "strong", "emphasis") if match.group(k))
    if has_target and not keep_targets:
        target = _EXPLICIT_TARGET.match(text)
        if target is not None:
            text = target.group("text")
    return text


def strip_inline_markup(
    text: str, *, keep_targets: bool = False, roles: frozenset[str] | None = None
) -> str:
    """``text`` with its RST inline-markup delimiters removed and their text kept.

    **strong**, *emphasis*, ``literal``, `interpreted`, :role:`text` and the trailing
    ``_`` or ``__`` of `link`_ and `anonymous link`__ lose their delimiters; the content
    of a literal is kept as it is. The ``<target>`` of an explicit target (a link, or a
    cross-reference role such as :ref: or :doc:) is removed too unless ``keep_targets``;
    in any other interpreted text or role it is shown text and stays. With ``roles``,
    only a role named in it is unmarked; any other role stays as written. Asterisks and
    backticks that are not paired markup stay. No other character is changed.
    """
    return _INLINE_MARKUP.sub(lambda m: _unmark(m, keep_targets=keep_targets, roles=roles), text)


def _paragraphs(text: str) -> list[str]:
    """``text`` split at blank lines, each part in `_quote_form`, empty parts dropped.

    Markup is recognised only inside one paragraph, as in RST, so a stray asterisk in one
    paragraph never pairs with one in the next.
    """
    parts = re.split(r"\n[^\S\n]*\n", unicodedata.normalize("NFC", text))
    return [form for form in (_quote_form(p) for p in parts) if form]


def _role_names(text: str) -> frozenset[str]:
    """The names of the roles ``text`` uses, lower-cased (`kbd`, `ref`, `py:func`)."""
    return frozenset(
        m.group("role_name").lower()
        for p in _paragraphs(text)
        for m in _INLINE_MARKUP.finditer(p)
        if m.group("role_name") is not None
    )


def _plain_form(
    text: str, *, keep_targets: bool = False, roles: frozenset[str] | None = None
) -> str:
    """`_quote_form` with RST inline markup removed (`strip_inline_markup`), by paragraph."""
    return " ".join(
        part
        for part in (
            strip_inline_markup(p, keep_targets=keep_targets, roles=roles)
            for p in _paragraphs(text)
        )
        if part
    )


def _echo(text: str) -> str:
    return text if len(text) <= MAX_ECHO_CHARS else text[: MAX_ECHO_CHARS - 1] + "…"


def _is_word(char: str) -> bool:
    return re.fullmatch(r"\w", char) is not None


# Characters that join the word characters on both sides into one token, so an operator id
# (`bim.add_wall`), a file name (`model.ifc`), a version (`4.5`), a contraction (`can't`,
# also with the curly apostrophe U+2019), a hyphenated word (`non-destructive`), a slash
# path (`File/Import`), a key combination (`Ctrl+S`) and a code (`EPSG:7856`) are each a
# single token. With a space or the text's edge on either side they are boundaries: a
# sentence period, a spaced dash or plus, a label colon, a possessive `walls'` and the
# quote marks around `'Walls'`.
_JOINERS = frozenset("._'\u2019-/+:")
# Joiners only between two digits: the thousands separator in `5,000` and the commas of
# `(0,0,0)`. A comma between letters (`walls,slabs`) stays a boundary.
_DIGIT_JOINERS = frozenset(",")


def _joins(text: str, j: int) -> bool:
    """True when ``text[j]`` is a joiner bound to the characters on both of its sides."""
    if not 0 < j < len(text) - 1:
        return False
    char, before, after = text[j], text[j - 1], text[j + 1]
    if char in _JOINERS:
        return _is_word(before) and _is_word(after)
    if char in _DIGIT_JOINERS:
        return before.isdigit() and after.isdigit()
    return False


def _joined(text: str, k: int) -> bool:
    """True when ``text[k - 1]`` and ``text[k]`` belong to the same token.

    Two word characters are one token, and so is a joiner bound on both sides (`_joins`)
    together with those neighbours. A sentence period (no word character after it), a
    comma after a word and the edges of the text are boundaries.
    """
    if not 0 < k < len(text):
        return False
    if _is_word(text[k - 1]) and _is_word(text[k]):
        return True
    return _joins(text, k - 1) or _joins(text, k)


def quote_word_count(text: str) -> int:
    """Whitespace tokens with at least one letter or digit; adornment and bullets do not count.

    This is the measure MIN_QUOTE_WORDS applies to; the sampler uses it too, so it never
    offers a section too short to quote.
    """
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


_NOT_VERBATIM = "not verbatim in its section"


def _passage_problem(needle: str, haystack: str) -> str | None:
    """Why ``needle`` is not a whole-token passage of ``haystack`` (both in one form)."""
    words = quote_word_count(needle)
    if words < MIN_QUOTE_WORDS:
        return f"{words} words, need {MIN_QUOTE_WORDS}"
    start = haystack.find(needle)
    if start < 0:
        return _NOT_VERBATIM
    while start >= 0:
        if not _joined(haystack, start) and not _joined(haystack, start + len(needle)):
            return None
        start = haystack.find(needle, start + 1)
    return "starts or ends inside a word of its section"


def _quote_problem(quote: str, section: str) -> str | None:
    """Why ``quote`` is not a verbatim, whole-token passage of ``section`` (None if it is).

    The quote passes if it is found in one of three comparisons. As written: both texts
    in `_quote_form` (NFC, whitespace collapsed). Without markup: the section in
    `_plain_form` (its RST inline markup removed, explicit targets too), so a quote passes
    whether it keeps the section's **bold**, ``literal`` and :kbd:`...` markup or drops
    it, and the section in `_plain_form` with its explicit targets kept, so a quote may
    keep a target where the section has it. On the quote side only delimiters go: its
    ``<target>`` text always stays, and only a role the section uses is unmarked, so a
    quote can never pass with words hidden in markup the section does not have (a made-up
    target, a made-up role name). In each comparison a passage must have MIN_QUOTE_WORDS
    tokens with a letter or digit and start and end on a token boundary of the section
    (`_joined`), so "all walls" is not found in "install walls" and a quote may not end at
    "bim" in "bim.add_wall", "can" in "can't", "File" in "File/Import", "5" in "5,000",
    "EPSG" in "EPSG:7856" or "Ctrl" in "Ctrl+S", or start at "ifc" in "model.ifc" or
    "destructive" in "non-destructive". When every comparison fails, the reason is the
    written form's unless the quote is not verbatim as written; then it is the first
    markup-free comparison's reason that is not "not verbatim", else "not verbatim".
    """
    written = _passage_problem(_quote_form(quote), _quote_form(section))
    if written is None:
        return None
    needle = _plain_form(quote, keep_targets=True, roles=_role_names(section))
    plain = []
    for keep_targets in (False, True):
        problem = _passage_problem(needle, _plain_form(section, keep_targets=keep_targets))
        if problem is None:
            return None
        plain.append(problem)
    if written != _NOT_VERBATIM:
        return written
    return next((p for p in plain if p != _NOT_VERBATIM), _NOT_VERBATIM)


def quote_problems(record: GeneratedItem, section_texts: Mapping[str, str]) -> list[str]:
    """One line per failing quote, by index and reason; quote text is never repeated.

    ``section_texts`` maps each offered section id to its text as it was offered
    (`sampler.section_texts`). A quote must name a cited section, have at least
    MIN_QUOTE_WORDS words with a letter or digit and occur verbatim, on token boundaries,
    in that section, with or without its RST inline markup (`_quote_problem`).
    """
    cited = {s.id for s in record.cited_sections}
    offered = {s.id for s in record.offered_sections}
    missing = sorted(cited - set(section_texts))
    if missing:
        raise ValueError(f"no offered text for cited sections {missing}")
    problems = []
    for index, quote in enumerate(record.quotes):
        if quote.section_id not in offered:
            reason = f"section {_echo(quote.section_id)!r} was not offered"
        elif quote.section_id not in cited:
            reason = f"section {_echo(quote.section_id)!r} is offered but not cited"
        else:
            reason = _quote_problem(quote.text, section_texts[quote.section_id])
        if reason is not None:
            problems.append(f"quote {index}: {reason}")
    return problems


def run_checks(
    record: GeneratedItem,
    lexicons: Lexicons,
    unoffered_citations: Iterable[str] = (),
    *,
    section_texts: Mapping[str, str],
) -> list[CheckResult]:
    """Evaluate every pre-check on one generated item.

    ``section_texts`` is the offered text of each offered section, re-derived from the
    hash-verified fixture slice (`sampler.section_texts`); `quotes_verbatim` compares
    against it.
    """
    item = record.item
    line = record.version_line
    if line not in lexicons.bim_ids:
        raise ValueError(f"unknown version line {line!r}; known: {sorted(lexicons.bim_ids)}")
    results: list[CheckResult] = []

    def add(dimension: Dimension, name: str, ok: bool, detail: str) -> None:
        results.append(
            CheckResult(dimension, name, ok, name not in EVIDENCE_ONLY and not ok, detail)
        )

    words = _words(item.answer)
    add("D1", "answer_length", words >= MIN_ANSWER_WORDS, f"{words} words, need {MIN_ANSWER_WORDS}")

    safety = normalize(item.safety_info)
    chars = len(item.safety_info.strip())
    add(
        "D2",
        "safety_length",
        chars >= MIN_SAFETY_CHARS,
        f"{chars} characters, need {MIN_SAFETY_CHARS}",
    )
    hits = sorted(p for p in GENERIC_PHRASES if _phrase_matches(p, safety))
    hits = hits if _is_generic(item.safety_info) else []
    add("D2", "safety_not_generic", not hits, f"generic phrases: {hits}" if hits else "none")

    texts = [*item.tools_required, *item.steps]
    used = sorted({m for t in texts for m in _BIM_ID.findall(_normalize_keep_dots(t))})
    known = lexicons.bim_ids.get(line, frozenset())
    unknown = [i for i in used if i not in known]
    add(
        "D3",
        "bim_operators_known",
        not unknown,
        f"unknown for {line}: {unknown}" if unknown else f"{len(used)} ids checked",
    )
    unoffered = sorted(unoffered_citations)
    add(
        "D3",
        "cited_sections_offered",
        not unoffered,
        f"not offered: {unoffered}" if unoffered else "all offered",
    )
    bad_quotes = quote_problems(record, section_texts)
    add(
        "D3",
        "quotes_verbatim",
        not bad_quotes,
        "; ".join(bad_quotes) if bad_quotes else f"{len(record.quotes)} quotes verbatim",
    )
    blender_known = lexicons.blender_operators.get(line, frozenset())
    prefixes = {o.split(".")[0] for o in blender_known if "." in o} - {"*", "bim"}
    candidates = sorted(
        {
            f"{a}.{b}"
            for t in texts
            for a, b in _OPERATOR.findall(_normalize_keep_dots(t))
            if a in prefixes
        }
    )
    wildcards = _wildcard_patterns(blender_known)
    unknown_ops = [
        o
        for o in candidates
        if o not in blender_known and not any(w.fullmatch(o) for w in wildcards)
    ]
    add(
        "D3",
        "blender_operators_known",
        not unknown_ops,
        f"not in the Manual lexicon: {unknown_ops}" if unknown_ops else "ok",
    )
    segments = lexicons.menu_segments.get(line, frozenset())
    unknown_menu: list[str] = []
    for step in item.steps:
        pieces = [p for m in _MENU_PATH.findall(step) for p in _PATH_BREAK.split(m)]
        for path in (p for p in pieces if _MENU_SPLIT.search(p)):
            parts = _MENU_SPLIT.split(path.strip())
            for index, part in enumerate(parts):
                first, last = index == 0, index == len(parts) - 1
                if _segment(part) and not _menu_part_known(part, segments, first=first, last=last):
                    unknown_menu.append(part.strip())
    add(
        "D3",
        "menu_paths_known",
        not unknown_menu,
        f"not in the pinned UI lexicons: {sorted(set(unknown_menu))}" if unknown_menu else "ok",
    )

    fields = normalize(f"{item.answer} {item.safety_info} {' '.join(item.tips)}")
    refusals = [p for p in REFUSAL_PHRASES if _phrase_matches(p, fields)]
    add("D4", "no_refusal", not refusals, f"refusal phrases: {refusals}" if refusals else "none")

    qwords = _words(item.question)
    add(
        "D5",
        "question_length",
        qwords >= MIN_QUESTION_WORDS,
        f"{qwords} words, need {MIN_QUESTION_WORDS}",
    )
    pwords = _words(item.equipment_problem)
    add(
        "D5",
        "problem_length",
        pwords >= MIN_PROBLEM_WORDS,
        f"{pwords} words, need {MIN_PROBLEM_WORDS}",
    )

    short = [t for t in item.tips if len(t.strip()) < MIN_TIP_CHARS]
    add("D6", "tip_length", not short, f"{len(short)} tips under {MIN_TIP_CHARS} characters")
    generic = [t for t in item.tips if _is_generic(t)]
    add("D6", "tip_not_generic", not generic, f"{len(generic)} generic tips")
    step_tokens = [_tokens(_TIP_NUMBER.sub("", s)) for s in item.steps]
    copies = [
        t
        for t in item.tips
        if any(_jaccard(_tokens(t), s) >= TIP_STEP_JACCARD for s in step_tokens)
    ]
    add("D6", "tip_not_step_copy", not copies, f"{len(copies)} tips copy a step")
    return results
