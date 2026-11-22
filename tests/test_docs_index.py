"""Section records cut at RST headings, the index build and check, and the ported BM25 core."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from doc_remotes import FILES, make_remote, source_config, write_config

from bonsai_help import cli
from bonsai_help import docs_index as di
from bonsai_help.doc_snapshot import CheckFailed, fixture_plan
from bonsai_help.doc_sources import Refused, Source, load_config

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/docs"


def words(text):
    return len(text.split())


def source(**overrides) -> Source:
    return Source.model_validate(source_config(**overrides))


def split(text: str, path: str = "docs/page.rst", pages=(), **overrides):
    diagnostics = di.Diagnostics()
    records = di.split_page(
        source(**overrides),
        "fake-docs-pin",
        "0" * 40,
        path,
        text.encode(),
        frozenset(pages) | {path},
        diagnostics,
    )
    return records, diagnostics


def titles(text: str, **overrides):
    records, _ = split(text, **overrides)
    return [(r["title"], r["level"], r["heading_path"]) for r in records]


def assert_partition(records, data: bytes):
    assert b"".join(r["text"].encode() for r in records) == data
    for before, after in zip(records, records[1:], strict=False):
        assert before["line_end"] + 1 == after["line_start"]
        assert before["byte_end"] == after["byte_start"]
    for record in records:
        body = data[record["byte_start"] : record["byte_end"]]
        assert body.decode() == record["text"] and di.sha256_hex(body) == record["sha256"]


# ---------------------------------------------------------------- ported BM25 core


def test_golden_terms():
    assert di.terms('bpy.ops.bim.add_wall(ifc_class="IfcWall")') == [
        "add",
        "add_wall",
        "bim",
        "bim.add_wall",
        "bpy",
        "bpy.ops.bim.add_wall",
        "ops",
        "ops.bim.add_wall",
        "wall",
        "class",
        "ifc",
        "ifc_class",
        "ifc",
        "ifcwall",
        "wall",
    ]
    assert di.terms("Blender 4.2 LTS 3.5.1.3 1e-6") == ["blender", "4.2", "lts", "3.5.1.3", "1e-6"]


def test_stopwords_short_terms_and_no_stemming():
    assert di.terms("the and of x9") == ["x9"]
    assert di.terms("a b c d1") == ["d1"]
    assert di.terms("walls wall walling") == ["walls", "wall", "walling"]
    assert di.terms("Part::Cone") == ["cone", "part", "part::cone"]
    assert di.terms("HOST_AREA_COMPUTED") == ["area", "computed", "host", "host_area_computed"]


def test_golden_bm25():
    corpus = ["alpha beta", "alpha gamma gamma", "delta"]
    assert di.bm25_scores(corpus, "gamma") == [0.0, 1.18236951, 0.0]
    assert di.bm25_scores(corpus, "alpha gamma") == [0.470003629, 1.572561203, 0.0]


HASH_SEED_SCRIPT = textwrap.dedent(
    """
    import json
    from bonsai_help import docs_index as di
    texts = [
        "Wall\\n====\\n\\nbim.add_wall draws an IfcWall with the Wall tool.\\n",
        "Slab\\n====\\n\\nAn IfcSlab is drawn with bim.add_slab and the Slab tool.\\n",
        "Join\\n====\\n\\nJoin merges objects; on IFC objects use bim.join_wall instead.\\n",
    ] * 3
    records = [
        {"id": f"s:p{i}.rst#L1-L4", "source": "s", "path": f"p{i}.rst", "line_start": 1,
         "text": t}
        for i, t in enumerate(texts)
    ]
    rows, _ = di.passages(records, {"s": 0})
    kept, record = di.finalize_passages(rows)
    hits = di.search(kept, "add an IfcWall with bim.add_wall", 10)
    print(json.dumps({"hits": [[h.passage.key, h.score] for h in hits], "record": record}))
    """
)


def run_with_seed(script, seed):
    env = {**os.environ, "PYTHONHASHSEED": str(seed)}
    done = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True
    )
    return done.stdout


def test_ranking_is_identical_under_hash_seeds_0_and_1():
    first = run_with_seed(HASH_SEED_SCRIPT, 0)
    assert first == run_with_seed(HASH_SEED_SCRIPT, 1)
    result = json.loads(first)
    assert result["hits"][0][0] == "s:p0.rst#L1-L4@L1-L4"
    assert len(result["record"]["collapsed"]) == 6


def passage(key, *, source_index=0, path="p", start=1, end=1, text="x"):
    return di.Passage(key, key, source_index, path, start, end, text)


def test_every_tie_break_level():
    expected = [
        di.Scored(passage("score"), 3.0),
        di.Scored(passage("source", source_index=0, path="z"), 2.0),
        di.Scored(passage("path", source_index=1, path="a"), 2.0),
        di.Scored(passage("start", source_index=1, path="b", start=1, end=9), 2.0),
        di.Scored(passage("end", source_index=1, path="b", start=2, end=3), 2.0),
        di.Scored(passage("key-a", source_index=1, path="b", start=2, end=4), 2.0),
        di.Scored(passage("key-b", source_index=1, path="b", start=2, end=4), 2.0),
    ]
    assert di.rank(reversed(expected)) == expected


def test_scores_1e12_apart_tie_after_rounding():
    low = di.score_passage(passage("low", path="b"), 1.0 + 1e-12)
    high = di.score_passage(passage("high", path="a"), 1.0)
    assert low.score == high.score
    assert [x.passage.key for x in di.rank([low, high])] == ["high", "low"]


def test_window_worked_example():
    live = [(n, f"w{n}") for n in range(1, 51)]
    spans, oversize = di.windows(live, set(), words)
    assert spans == [(1, 30), (16, 45), (31, 50)]
    assert oversize == []


def test_windows_limits_edges_coverage_and_oversize():
    lines = []
    for n in range(1, 81):
        if n % 9 == 0:
            lines.append("")
        elif n == 40:
            lines.append(" ".join(["big"] * 500))
        else:
            lines.append(" ".join([f"t{n}"] * 40))
    no_boundary = {12, 13}
    live = list(enumerate(lines, 1))
    spans, oversize = di.windows(live, no_boundary, words)
    assert oversize == [40]
    text_of = dict(live)
    covered = set()
    for a, b in spans:
        body = [text_of[n] for n in range(a, b + 1)]
        assert len(body) <= 30
        assert words("\n".join(body)) <= 480
        assert text_of[a].strip() and text_of[b].strip()
        assert a not in no_boundary and b not in no_boundary
        covered.update(range(a, b + 1))
    eligible = {n for n, t in live if t.strip() and n not in no_boundary}
    assert eligible - covered == {40}


def test_passages_never_cross_records_and_reslice_verbatim():
    text = "".join(f"Title {n}\n=======\n\n" + "body line\n" * 40 for n in range(1, 3))
    records, _ = split(text)
    rows, oversize = di.passages(records, {"fake-docs": 0})
    assert oversize == []
    lines = di.split_lines(text)
    for row in rows:
        record = next(r for r in records if r["id"] == row["record_id"])
        assert record["line_start"] <= row["start"] <= row["end"] <= record["line_end"]
        assert row["text"] == "\n".join(lines[row["start"] - 1 : row["end"]])
    assert {row["record_id"] for row in rows} == {r["id"] for r in records}


def test_finalize_drops_duplicates_collapses_text_per_source_and_drops_termless():
    def row(src, index, path, start, end, text):
        return {
            "key": f"{src}:{path}@L{start}-L{end}",
            "record_id": f"{src}:{path}",
            "source": src,
            "source_index": index,
            "path": path,
            "start": start,
            "end": end,
            "text": text,
        }

    rows = [
        row("a", 0, "y.rst", 1, 2, "same text here"),
        row("a", 0, "x.rst", 1, 2, "same text here"),
        row("a", 0, "x.rst", 1, 2, "same text here"),
        row("b", 1, "z.rst", 1, 2, "same text here"),
        row("a", 0, "x.rst", 5, 6, "== ++ --"),
    ]
    kept, record = di.finalize_passages(rows)
    assert [x.key for x in kept] == ["a:x.rst@L1-L2", "b:z.rst@L1-L2"]
    assert record == {
        "duplicate_spans": ["a:x.rst@L1-L2"],
        "collapsed": [{"key": "a:y.rst@L1-L2", "kept": "a:x.rst@L1-L2"}],
        "no_terms": ["a:x.rst@L5-L6"],
    }


def test_separator_location_finds_the_first_non_lf_line_break():
    assert di.separator_location("a\nb") is None
    assert di.separator_location("a\nb c") == (2, "U+2028")


# ---------------------------------------------------------------- RST splitter


def test_underline_styles_take_levels_by_first_appearance():
    text = "Top\n===\n\nAa\n--\n\nDeep\n^^^^\n\nBb\n--\n\nNext top\n========\n"
    assert titles(text) == [
        ("Top", 1, ["Top"]),
        ("Aa", 2, ["Top", "Aa"]),
        ("Deep", 3, ["Top", "Aa", "Deep"]),
        ("Bb", 2, ["Top", "Bb"]),
        ("Next top", 1, ["Next top"]),
    ]


def test_overline_title_may_be_inset_and_differs_from_underline_style():
    text = "######\n Part \n######\n\nPart body\n\nChapter\n#######\n\nbody\n"
    assert titles(text) == [("Part", 1, ["Part"]), ("Chapter", 2, ["Part", "Chapter"])]


def test_mismatched_overline_is_not_a_title():
    records, diagnostics = split("Intro\n\n=====\nTitle\n-----\n\nbody\n")
    assert [r["title"] for r in records] == [None]
    assert diagnostics.overline_mismatch == ["fake-docs:docs/page.rst:3"]


def test_short_underlines_follow_docutils():
    records, diagnostics = split("Long title here\n=====\n\nOk\n==\n\nTitle\n--\n\nbody\n")
    assert [r["title"] for r in records] == ["Long title here", "Ok"]
    assert diagnostics.short_underline == ["fake-docs:docs/page.rst:1"]
    assert diagnostics.short_underline_text == ["fake-docs:docs/page.rst:7"]


@pytest.mark.parametrize(
    "body",
    [
        "Text\n\n----------\n\nMore text\n",
        "=====  =====\nA      B\n=====  =====\n",
        "+-----+-----+\n| a   | b   |\n+-----+-----+\n",
        ".. code-block:: rst\n\n   Not a title\n   ===========\n",
        "Literal::\n\n   Not a title\n   -----------\n",
        ".. note::\n\n   Not a title\n   ~~~~~~~~~~~\n",
        ".. .. figure:: image.png\n..\n\n   caption\n",
        "para line one\npara line two\n-------------\n",
    ],
    ids=[
        "transition",
        "simple-table",
        "grid-table",
        "code-block",
        "literal",
        "note",
        "comment-markup",
        "paragraph-continuation",
    ],
)
def test_lines_that_are_never_titles(body):
    records, diagnostics = split("Page\n====\n\n" + body)
    assert [r["title"] for r in records] == ["Page"]
    assert diagnostics.short_underline_text == []


def test_labels_and_index_entries_open_the_section_they_precede():
    text = (
        "Page\n====\n\nIntro.\n\n.. _first:\n.. _second:\n\n.. index::\n   single: Thing\n\n"
        "Thing\n-----\n\nBody.\n"
    )
    records, _ = split(text)
    assert [r["line_start"] for r in records] == [1, 6]
    assert records[1]["anchors"] == ["first", "second"]
    assert records[1]["title_line"] == 12
    assert records[1]["text"].startswith(".. _first:\n")


def test_level_jump_nests_under_the_open_ancestor_and_is_recorded():
    text = "Aa\n==\n\nBb\n--\n\nCc\n^^\n\nDd\n==\n\nEe\n^^\n"
    records, diagnostics = split(text)
    assert records[-1]["heading_path"] == ["Dd", "Ee"] and records[-1]["level"] == 3
    assert diagnostics.level_jump == ["fake-docs:docs/page.rst:13"]


def test_subtree_extent_covers_descendants():
    records, _ = split("Aa\n==\n\nBb\n--\n\nb\n\nCc\n==\n\nc\n")
    assert [(r["title"], r["line_end"], r["subtree_line_end"]) for r in records] == [
        ("Aa", 3, 8),
        ("Bb", 8, 8),
        ("Cc", 12, 12),
    ]


@pytest.mark.parametrize("text", ["No heading here.\n", "no final line feed", ""])
def test_headless_pages_and_pages_without_final_lf(text):
    records, _ = split(text)
    assert len(records) == 1 and records[0]["title"] is None and records[0]["heading_path"] == []
    assert_partition(records, text.encode())
    records, _ = split("Title\n=====\n\nlast line without LF")
    assert_partition(records, b"Title\n=====\n\nlast line without LF")


def test_includes_and_toctree_are_recorded_not_expanded():
    text = (
        "Page\n====\n\n.. include:: /shared/part.rst\n   :start-line: 2\n\n"
        ".. include:: missing.rst\n\n.. toctree::\n   :maxdepth: 1\n\n   other\n   Named <sub/x>\n"
    )
    pages = {"docs/shared/part.rst", "docs/other.rst", "docs/sub/x.rst"}
    records, _ = split(text, pages=pages)
    (record,) = records
    assert record["includes"] == [
        {
            "target": "/shared/part.rst",
            "line": 4,
            "options": [":start-line: 2"],
            "resolved": "docs/shared/part.rst",
        },
        {"target": "missing.rst", "line": 7, "options": [], "resolved": None},
    ]
    assert record["toctree"] == ["other", "sub/x"]
    assert ".. include:: /shared/part.rst" in record["text"]


def test_autosectionlabel_follows_the_source_settings():
    text = "Top\n===\n\nSub\n---\n\nDeep\n^^^^\n\n``Code`` title\n--------------\n"
    asl = {"prefix_document": True, "maxdepth": 2}
    records, diagnostics = split(text, path="docs/guide/page.rst", autosectionlabel=asl)
    assert [r["auto_label"] for r in records] == ["guide/page:Top", "guide/page:Sub", None, None]
    assert diagnostics.auto_label_markup == ["fake-docs:docs/guide/page.rst:10"]
    records, _ = split(text)
    assert all(r["auto_label"] is None for r in records)


def test_labels_not_attached_to_a_title_are_inline_targets():
    records, _ = split("Page\n====\n\n.. _bpy.ops.mesh.merge:\n\nMerge\n   Merges.\n")
    assert records[0]["anchors"] == []
    assert records[0]["inline_targets"] == [{"label": "bpy.ops.mesh.merge", "line": 4}]


@pytest.mark.parametrize(
    "data, message",
    [
        (b"T\n=\r\n", "carriage return"),
        (b"\xef\xbb\xbfT\n=\n", "byte order mark"),
        (b"\xff", "UTF-8"),
    ],
)
def test_pages_that_cannot_keep_upstream_spans_are_refused(data, message):
    with pytest.raises(CheckFailed, match=message) as raised:
        di.split_page(source(), "p", "0" * 40, "docs/x.rst", data, frozenset(), di.Diagnostics())
    assert raised.value.exit_code == 1


def test_a_record_holding_a_jsonl_separator_is_refused():
    entry = {
        "pin_id": "p",
        "source_digest": "d",
        "repository": {"commit": "0" * 40},
        "pages": [{"path": "docs/x.rst"}],
    }
    with pytest.raises(Refused, match="U\\+2029"):
        di.index_pages(source(), entry, lambda path: "T\n=\n\na b\n".encode())


def test_every_fixture_page_partitions_exactly():
    config = load_config(ROOT / "config/doc-sources.json")
    manifest = json.loads((ROOT / "config/doc-manifest.json").read_bytes())
    checked = 0
    for src in di.docs_sources(config):
        pages = {p["path"] for p in manifest["sources"][src.id]["pages"]}
        for path in fixture_plan(src):
            if path not in pages:
                continue
            data = (FIXTURES / src.id / path).read_bytes()
            records = di.split_page(
                src, "pin", "0" * 40, path, data, frozenset(pages), di.Diagnostics()
            )
            assert_partition(records, data)
            checked += 1
    assert checked >= 40


# ---------------------------------------------------------------- index build and check


class Docs:
    def __init__(self, tmp_path: Path, capsys):
        self.tmp, self.capsys = tmp_path, capsys
        self.config = tmp_path / "doc-sources.json"
        self.manifest = tmp_path / "doc-manifest.json"
        self.data = tmp_path / "data"
        self.digest = tmp_path / "docs-index.json"
        write_config(self.config, make_remote(tmp_path))
        assert self.run("snapshot", "build", "--write-manifest")[0] == 0

    def run(self, *args: str, data: Path | None = None):
        argv = [*args, "--config", str(self.config), "--manifest", str(self.manifest)]
        if "--committed" not in args and args[:2] != ("setup", "format"):
            argv += ["--data-root", str(data or self.data)]
        if args[:2] == ("docs", "index"):
            argv += ["--digest", str(self.digest)]
        if args[0] == "lexicon":
            argv += ["--lexicons", str(self.tmp / "lexicons")]
        if args[0] == "setup":
            argv += ["--profiles", str(self.tmp / "p.json"), "--facts", str(self.tmp / "f.json")]
        code = cli.main(argv, allow_file_urls=True)
        out, err = self.capsys.readouterr()
        assert "Traceback" not in err and str(self.tmp) not in out + err
        return code, out, err

    def index_dir(self, data: Path | None = None) -> Path:
        (found,) = ((data or self.data) / "index" / "fake-docs").glob("fake-docs-*")
        return found


@pytest.fixture
def docs(tmp_path, capsys):
    return Docs(tmp_path, capsys)


def test_index_build_writes_once_then_verifies(docs):
    code, out, _ = docs.run("docs", "index", "build", "--write-digest")
    assert code == 0 and "built index/fake-docs/" in out and "docs-index.json written" in out
    first = (docs.index_dir() / "sections.jsonl").read_bytes()
    code, out, _ = docs.run("docs", "index", "build")
    assert code == 0 and "present, verified, not rewritten" in out
    assert docs.run("docs", "index", "check")[0] == 0
    assert docs.run("docs", "index", "check", "--committed")[0] == 0
    second = docs.tmp / "second"
    assert docs.run("snapshot", "build", data=second)[0] == 0
    assert docs.run("docs", "index", "build", data=second)[0] == 0
    assert (docs.index_dir(second) / "sections.jsonl").read_bytes() == first
    records = [json.loads(line) for line in first.decode().splitlines()]
    assert {r["path"] for r in records} == {
        p for p in FILES if p.endswith(".rst") and p.startswith("docs/")
    }


def test_tampered_index_is_refused_and_never_rewritten(docs):
    assert docs.run("docs", "index", "build", "--write-digest")[0] == 0
    sections = docs.index_dir() / "sections.jsonl"
    sections.write_bytes(sections.read_bytes().replace(b"Synthetic", b"Changed", 1))
    code, _, err = docs.run("docs", "index", "build")
    assert code == 5 and "inspect it" in err
    assert b"Changed" in sections.read_bytes()
    code, _, err = docs.run("docs", "index", "check")
    assert code == 1 and "differs from a rebuild" in err
    code, _, err = docs.run("docs", "section", "fake-docs:docs/index.rst#L1-L4")
    assert code == 1 and "does not match its receipt" in err


def test_committed_digest_must_match_and_be_canonical(docs):
    assert docs.run("docs", "index", "build", "--write-digest")[0] == 0
    document = json.loads(docs.digest.read_bytes())
    docs.digest.write_text(json.dumps(document))
    code, _, err = docs.run("docs", "index", "check", "--committed")
    assert code == 1 and "canonical layout" in err
    document["sources"]["fake-docs"]["records"] += 1
    docs.digest.write_text(json.dumps(document, indent=2))
    assert docs.run("docs", "index", "build")[0] == 1


def test_index_needs_a_verified_snapshot(docs):
    code, _, err = docs.run("docs", "index", "build", "--write-digest", data=docs.tmp / "empty")
    assert code == 1 and "not built (run snapshot build)" in err


def test_section_and_search_on_the_built_index(docs):
    assert docs.run("docs", "index", "build", "--write-digest")[0] == 0
    code, out, _ = docs.run("docs", "section", "fake-docs:docs/guide/page.rst#L1-L4")
    assert code == 0
    assert out.splitlines() == [
        "fake-docs:docs/guide/page.rst#L1-L4 (Page)",
        "Page",
        "====",
        "",
        "Synthetic guide page.",
    ]
    code, _, err = docs.run("docs", "section", "fake-docs:docs/none.rst#L1-L2")
    assert code == 1 and "no such section" in err
    code, out, _ = docs.run("docs", "search", "guide page")
    assert code == 0 and out.splitlines()[0].split("\t")[2] == "fake-docs:docs/guide/page.rst#L1-L4"
    assert docs.run("docs", "search", "x", "--top", "0")[0] == 2
    assert docs.run("docs", "search", "x", "--source", "elsewhere")[0] == 2
    code, out, _ = docs.run("docs", "search", "zzzz")
    assert code == 0 and "no passage matches" in out


def test_search_before_an_index_is_built_is_exit_1(docs):
    code, _, err = docs.run("docs", "search", "page")
    assert code == 1 and "run docs index build" in err


def test_lexicon_build_compares_unless_written(docs):
    code, _, err = docs.run("lexicon", "build")
    assert code == 1 and "fake-docs.json differ from a rebuild" in err
    code, out, _ = docs.run("lexicon", "build", "--write")
    assert code == 0 and "fake-docs.json: written" in out
    code, out, _ = docs.run("lexicon", "build")
    assert code == 0 and "fake-docs.json: unchanged" in out
    document = json.loads((docs.tmp / "lexicons/fake-docs.json").read_bytes())
    assert document["schema"] == "rst-lexicon-v1" and document["source"] == "fake-docs"
    code, _, err = docs.run("lexicon", "build", data=docs.tmp / "empty")
    assert code == 1 and "not built (run snapshot build)" in err


def test_setup_candidates_need_the_built_index_and_print_json_lines(docs):
    assert docs.run("setup", "candidates")[0] == 1
    assert docs.run("docs", "index", "build", "--write-digest")[0] == 0
    code, out, _ = docs.run("setup", "candidates")
    assert code == 0 and out == ""  # the synthetic pages mention no schema or version


def test_setup_format_on_missing_files_is_exit_1(docs):
    code, _, err = docs.run("setup", "format")
    assert code == 1 and "p.json" in err
