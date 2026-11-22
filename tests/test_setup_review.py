"""Chad's review of the B2 drafts through packets, on copies of the setup files in a temp root.

Decisions in these tests are written by the test suite into temporary packets to exercise the
import and apply; they are not Chad's decisions and never reach `reference/`.
"""

from __future__ import annotations

import json
import re
import shutil
import sys

import pytest
from gold_support import FIXTURES, MANIFEST, ROOT

from bonsai_help import cli, gold_review, setup, setup_review
from bonsai_help.doc_snapshot import CheckFailed
from bonsai_help.doc_sources import ConfigError, Refused, load_config

CONFIG = load_config(ROOT / "config/doc-sources.json")
READ = setup.page_bytes_offline(FIXTURES)
YES = lambda summary: True  # noqa: E731  (a test's stand-in for Chad's typed confirmation)


@pytest.fixture
def root(tmp_path):
    for name in ("setup-profiles.json", "setup-facts.json"):
        shutil.copy(ROOT / "reference" / name, tmp_path / name)
    return tmp_path


def paths(root):
    return root / "setup-profiles.json", root / "setup-facts.json"


def state(root) -> setup_review.SetupState:
    profiles, facts = paths(root)
    return setup_review.SetupState(
        config=CONFIG,
        manifest=MANIFEST,
        profiles=setup.SetupProfiles.model_validate(json.loads(profiles.read_bytes())),
        facts=setup.SetupFacts.model_validate(json.loads(facts.read_bytes())),
        read=READ,
    )


def store(root) -> gold_review.Store:
    return gold_review.Store(root / "data" / "setup-review")


def export(root, size=25, records=None, st=None):
    return setup_review.export_packets(
        store(root), st or state(root), size=size, records=records, exported_on="2026-11-22"
    )


def import_(root, packet_id="SR-001", st=None, skip_stale=False, confirm=YES):
    return setup_review.import_packet(
        store(root),
        st or state(root),
        packet_id,
        decided_on="2026-11-23",
        skip_stale=skip_stale,
        confirm=confirm,
    )


def apply(root, write=True):
    profiles, facts = paths(root)
    return setup_review.apply(store(root), state(root), profiles, facts, write=write)


def packet(root, packet_id="SR-001"):
    return store(root).folder("packets") / f"{packet_id}.md"


def decide(root, record_id, word, packet_id="SR-001", note="", fence=None):
    """Fill one block's decision region, as Chad would in his editor."""
    path = packet(root, packet_id)
    text = path.read_text(encoding="utf-8")
    start = text.index(f"<!-- gold:decide {record_id} -->")
    end = text.index(f"<!-- gold:end {record_id} -->")
    region = text[start:end].replace("DECISION:\n", f"DECISION: {word}\n", 1)
    if note:
        region = region.replace("NOTE:\n", f"NOTE: {note}\n", 1)
    if fence is not None:
        opening = re.search(r"\n(`{3,})json\n", region)
        body_end = region.index(f"\n{opening.group(1)}\n", opening.end())
        region = region[: opening.end()] + json.dumps(fence, indent=2) + region[body_end:]
    path.write_text(text[:start] + region + text[end:], encoding="utf-8")


def prefill(root, record_id):
    return setup_review.edit_prefill(state(root).records()[record_id])


def record(root, record_id):
    return state(root).records()[record_id]


def edited_files(root, change):
    """Change the raw setup files in place (a hand edit) and rewrite their digests."""
    profiles, facts = paths(root)
    raw = {"profiles": json.loads(profiles.read_bytes()), "facts": json.loads(facts.read_bytes())}
    change(raw)
    for name, path, schema, model in (
        ("profiles", profiles, setup.PROFILES_SCHEMA, setup.SetupProfiles),
        ("facts", facts, setup.FACTS_SCHEMA, setup.SetupFacts),
    ):
        path.write_text(json.dumps(raw[name]), encoding="utf-8")
        path.write_bytes(setup.format_document(path, schema, model))


def fact(raw, identifier):
    return next(r for r in raw["facts"]["rows"] if r["id"] == identifier)


# ------------------------------------------------------------------ export


def test_export_batches_every_pending_record_in_review_order(root):
    report = export(root)
    assert report.lines == [
        "SR-001: 25 record(s) in setup-review/packets/SR-001.md",
        "SR-002: 14 record(s) in setup-review/packets/SR-002.md",
    ]
    ids = [
        e["item"]
        for p in ("SR-001", "SR-002")
        for e in json.loads((store(root).folder("packets") / f"{p}.json").read_bytes())["items"]
    ]
    assert ids[:3] == ["VL-current", "VL-older", "SP-01"] and ids[-1] == "SF-020"
    assert len(ids) == len(set(ids)) == 39
    text = packet(root, "SR-002").read_text(encoding="utf-8")
    # A fact row shows its claim, the full text of every cited section and each quote.
    assert "## SF-012 · fact row · assistant_drafted" in text
    assert "- Blender 5.1 or 5.2 with Python 3.13\n" in text
    assert '- citation 1 (line 27): "Blender 5.1 or 5.2 with Python 3.13"' in text
    # Nothing is exported twice while a packet waits for its import.
    assert export(root).lines[-1] == "no setup record is ready for review"


def test_export_refuses_while_the_setup_check_fails(root):
    edited_files(root, lambda raw: fact(raw, "SF-012").update(key_terms=["Blender 9.9"]))
    with pytest.raises(setup_review.ProblemsFound, match="setup check problem"):
        export(root)
    assert not store(root).folder("packets").exists()


# ------------------------------------------------------------------ import and apply


def test_approve_reject_and_blank_are_recorded_then_applied(root):
    export(root, size=3)
    decide(root, "VL-current", "approve", note="note text 42")
    decide(root, "VL-older", "reject")
    report = import_(root)
    assert report.lines[0].startswith("SR-001: 2 decision(s) recorded, 1 left pending")
    # The import writes data/ only; the setup files change when apply writes them.
    assert record(root, "VL-current").status == "assistant_drafted"
    with pytest.raises(setup_review.ProblemsFound, match="differ from Chad's decisions") as caught:
        apply(root, write=False)
    assert caught.value.problems == [
        "VL-current: assistant_drafted -> chad_accepted",
        "VL-older: assistant_drafted -> chad_rejected",
    ]
    report = apply(root)
    assert report.lines[-1] == "states: assistant_drafted 37, chad_accepted 1, chad_rejected 1"
    line = record(root, "VL-current")
    assert line.review.model_dump() == {
        "decided_on": "2026-11-23",
        "words": "approve",
        "decision_id": "SR-001.01",
        "content_sha256": setup.record_sha(line),
    }
    assert record(root, "SP-01").status == "assistant_drafted"
    profiles, facts = paths(root)
    assert setup.check_setup(CONFIG, MANIFEST, profiles, facts, READ) == []
    assert b"note text 42" not in profiles.read_bytes() + facts.read_bytes()
    assert apply(root, write=False).lines == [
        "states: assistant_drafted 37, chad_accepted 1, chad_rejected 1"
    ]
    # Decided records are not exported again; the blank one is (the other 36 records wait in
    # the 12 other packets of the first export).
    report = export(root)
    assert report.lines[-1] == "SR-014: 1 record(s) in setup-review/packets/SR-014.md"
    assert report.lines[0] == "SP-02: in SR-002, not yet imported" and len(report.lines) == 37
    assert "<!-- gold:item SP-01 " in packet(root, "SR-014").read_text(encoding="utf-8")


def test_a_decision_not_yet_applied_is_reported_not_exported(root):
    export(root, size=1)
    decide(root, "VL-current", "approve")
    import_(root)
    report = export(root, size=50)
    assert report.lines[0] == "VL-current: decided in SR-001.01; run setup review apply"
    assert "VL-current" not in packet(root, "SR-002").read_text(encoding="utf-8")


def test_an_edit_derives_its_citations_and_is_applied_as_amended(root):
    export(root, records=["SF-012"])
    fence = prefill(root, "SF-012")
    fence["topic"] = "Blender versions the developer page supports"
    decide(root, "SF-012", "edit", fence=fence)
    import_(root)
    apply(root)
    row = record(root, "SF-012")
    assert row.status == "chad_amended" and row.topic == fence["topic"]
    assert row.review.words == "edit" and row.review.content_sha256 == setup.record_sha(row)
    assert row.citations[0].quote_line == 27
    profiles, facts = paths(root)
    assert setup.check_setup(CONFIG, MANIFEST, profiles, facts, READ) == []


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda f: f.update(id="SF-099"), "an edit cannot change id"),
        (lambda f: f.update(note="reviewer text"), "an edit cannot change note"),
        (
            lambda f: f["citations"][0].update(quote="Blender 9.9 with Python 3.13"),
            "citation 1: bonsai-docs:src/bonsai/docs/guides/development/installation.rst",
        ),
        (lambda f: f["citations"][0].update(line=3), "citation 1 is {record_id, quote}"),
        (lambda f: f.update(key_terms=["Blender 9.9"]), "edits fail the setup check"),
        (lambda f: f.update(kind="no_such_kind"), "edit invalid"),
        (lambda f: None, "DECISION is edit but nothing changed"),
    ],
)
def test_bad_edits_write_nothing(root, change, message):
    export(root, records=["SF-012"])
    fence = prefill(root, "SF-012")
    change(fence)
    decide(root, "SF-012", "edit", fence=fence)
    with pytest.raises(setup_review.ProblemsFound) as caught:
        import_(root)
    assert any(message in p for p in caught.value.problems), caught.value.problems
    assert store(root).imports() == []


def test_a_profile_edit_cannot_move_it_to_another_split(root):
    export(root, records=["SP-01"])
    decide(root, "SP-01", "edit", fence={**prefill(root, "SP-01"), "split": "development"})
    with pytest.raises(setup_review.ProblemsFound) as caught:
        import_(root)
    assert caught.value.problems == ["SP-01: an edit cannot change split"]


def test_approve_with_a_changed_json_and_a_note_on_a_blank_are_refused(root):
    export(root, records=["SF-012", "SF-013"])
    decide(root, "SF-012", "approve", fence={**prefill(root, "SF-012"), "topic": "x"})
    decide(root, "SF-013", "", note="a note without a decision")
    with pytest.raises(setup_review.ProblemsFound) as caught:
        import_(root)
    assert caught.value.problems == [
        "SF-012: the JSON changed; write DECISION: edit to keep the changes",
        "SF-013: a NOTE needs a decision",
    ]


def test_a_tampered_block_is_refused_and_names_the_line(root):
    export(root, records=["SF-012"])
    path = packet(root)
    path.write_text(
        path.read_text(encoding="utf-8").replace("- claim: The 0.9.0-post1", "- claim: A"),
        encoding="utf-8",
    )
    with pytest.raises(setup_review.ProblemsFound) as caught:
        import_(root)
    assert caught.value.problems[0].startswith("SF-012: tampered: the fixed region changed at line")


def test_a_record_or_what_its_block_shows_changing_since_export_is_stale(root):
    export(root, records=["VL-current", "SF-013"])
    decide(root, "VL-current", "approve")
    decide(root, "SF-013", "approve")
    # SF-015's claim is shown in VL-current's block, so VL-current is stale although its own
    # content is unchanged; SF-013 is unaffected.
    st = state(root)
    raw = st.facts.model_dump(mode="json", by_alias=True)
    next(r for r in raw["rows"] if r["id"] == "SF-015")["claim"] += " (edited)"
    st.facts = setup.SetupFacts.model_validate(raw)
    with pytest.raises(setup_review.ProblemsFound) as caught:
        import_(root, st=st)
    assert caught.value.problems == [
        "VL-current: stale: the record or what its block shows changed since export"
    ]
    report = import_(root, st=st, skip_stale=True)
    assert report.lines[0].startswith("SR-001: 1 decision(s) recorded, 0 left pending, 1 stale")


def test_a_re_decision_supersedes_and_a_hand_edit_returns_the_record_to_drafted(root):
    export(root, records=["SF-013"])
    decide(root, "SF-013", "approve")
    import_(root)
    apply(root)
    # An unimported second packet of the same record is refused.
    export(root, records=["SF-013"])
    with pytest.raises(ConfigError, match="SF-013 is in SR-002, not yet imported"):
        export(root, records=["SF-013"])
    text = packet(root, "SR-002").read_text(encoding="utf-8")
    assert "Re-decision: the effective decision is SR-001.01 (approve, 2026-11-23)" in text
    decide(root, "SF-013", "reject", packet_id="SR-002")
    import_(root, "SR-002")
    apply(root)
    row = record(root, "SF-013")
    assert row.status == "chad_rejected" and row.review.decision_id == "SR-002.01"
    assert store(root).decisions()[-1]["supersedes"] == "SR-001.01"
    # A hand edit after the decision: setup check names it, and apply returns it to drafted.
    edited_files(root, lambda raw: fact(raw, "SF-013").update(topic="supported versions (edited)"))
    profiles, facts = paths(root)
    found = [str(p) for p in setup.check_setup(CONFIG, MANIFEST, profiles, facts, READ)]
    assert found == [
        "setup: SF-013: changed since Chad's decision SR-002.01; run setup review apply (it "
        "returns to assistant_drafted) and export it again"
    ]
    apply(root)
    assert record(root, "SF-013").status == "assistant_drafted"


def test_an_old_packet_cannot_override_a_newer_decision(root):
    export(root, records=["SF-013"])
    import_(root)  # blank: imported, nothing decided
    export(root, records=["SF-013"])
    decide(root, "SF-013", "approve", packet_id="SR-002")
    import_(root, "SR-002")
    export(root, size=50)  # the pending rest, as an ordinary (not a re-decision) packet
    items = json.loads((store(root).folder("packets") / "SR-003.json").read_bytes())["items"]
    assert len(items) == 38 and "SF-013" not in {e["item"] for e in items}


def test_a_second_import_an_unconfirmed_import_and_a_lock_write_nothing(root):
    export(root, records=["SF-013"])
    decide(root, "SF-013", "approve")
    with pytest.raises(ConfigError, match="not confirmed"):
        import_(root, confirm=lambda summary: False)
    assert store(root).imports() == []
    import_(root)
    with pytest.raises(Refused, match="already imported"):
        import_(root)
    (store(root).root / ".lock").write_text("")
    with pytest.raises(Refused, match="lock exists"):
        apply(root)


def test_an_edit_result_that_does_not_hash_to_its_record_is_refused_by_apply(root):
    export(root, records=["SF-012"])
    decide(root, "SF-012", "edit", fence={**prefill(root, "SF-012"), "topic": "versions"})
    import_(root)
    path = store(root).folder("imports") / "SR-001.json"
    record_file = json.loads(path.read_bytes())
    record_file["decisions"][0]["result"]["topic"] = "tampered"
    path.write_text(json.dumps(record_file), encoding="utf-8")
    with pytest.raises(CheckFailed, match="does not hash to its record"):
        apply(root)


def test_setup_review_import_needs_an_interactive_terminal(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(ROOT / "tests")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code = cli.main(["setup", "review", "import", "SR-001", "--data-root", str(tmp_path / "data")])
    assert code == 2
    assert "needs an interactive terminal" in capsys.readouterr().err
