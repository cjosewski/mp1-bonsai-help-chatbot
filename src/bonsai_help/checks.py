"""Deterministic pre-checks, one or more per rubric dimension.

These are heuristics. A failed check is evidence for the first-pass gate and the judge;
none of them replaces a human or judge decision. ``drop`` marks a failure the gate may
act on by itself; unknown Blender operators and menu paths are evidence only.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
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

_BIM_ID = re.compile(r"\bbim\.[a-z0-9_]+")
_OPERATOR = re.compile(r"\b([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\b")
_MENU_SPLIT = re.compile(r"\s*(?:-->|->|=>|→|›|>)\s*")
_MENU_PATH = re.compile(r"[^\n.;:]*(?:-->|->|=>|→|›|>)[^\n.;:]*")
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
    """Per version line: Bonsai operator ids, Blender operator ids and menu labels."""

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
            e["id"].casefold() for e in source["entries"] if isinstance(e.get("id"), str)
        ) | frozenset(t["id"].casefold() for t in source.get("ui_texts", []) if "id" in t)
        manual = json.loads((lex_dir / f"{sources['blender_manual']}.json").read_bytes())
        ops: set[str] = set()
        segs: set[str] = set()
        for entry in manual["entries"]:
            value = entry.get("value")
            if not isinstance(value, str):
                continue
            if entry["kind"] in ("blender_operator", "operator_ref"):
                ops.add(value.casefold())
            elif entry["kind"] == "menu_path":
                segs.update(_segment(part) for part in _MENU_SPLIT.split(value))
            elif entry["kind"] == "guilabel":
                segs.add(_segment(value))
        for text in source.get("ui_texts", []):
            segs.add(_segment(text["text"]))
        for entry in source["entries"]:
            if isinstance(entry.get("label"), str):
                segs.add(_segment(entry["label"]))
        operators[line["id"]] = frozenset(ops)
        segments[line["id"]] = frozenset(s for s in segs if s)
    return Lexicons(bim, operators, segments)


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


def run_checks(
    record: GeneratedItem,
    lexicons: Lexicons,
    unoffered_citations: Iterable[str] = (),
) -> list[CheckResult]:
    """Evaluate every pre-check on one generated item."""
    item = record.item
    line = record.version_line
    if line not in lexicons.bim_ids:
        raise ValueError(f"unknown version line {line!r}; known: {sorted(lexicons.bim_ids)}")
    results: list[CheckResult] = []

    def add(dimension: Dimension, name: str, ok: bool, detail: str, *, drop: bool = True) -> None:
        results.append(CheckResult(dimension, name, ok, drop and not ok, detail))

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
    unknown_ops = [o for o in candidates if o not in blender_known]
    add(
        "D3",
        "blender_operators_known",
        not unknown_ops,
        f"not in the Manual lexicon: {unknown_ops}" if unknown_ops else "ok",
        drop=False,
    )
    segments = lexicons.menu_segments.get(line, frozenset())
    unknown_menu: list[str] = []
    for step in item.steps:
        for path in _MENU_PATH.findall(step):
            for part in _MENU_SPLIT.split(path.strip()):
                seg = _segment(part)
                if seg and not any(seg in s or s in seg for s in segments):
                    unknown_menu.append(part.strip())
    add(
        "D3",
        "menu_paths_known",
        not unknown_menu,
        f"not in the Manual lexicon: {sorted(set(unknown_menu))}" if unknown_menu else "ok",
        drop=False,
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
