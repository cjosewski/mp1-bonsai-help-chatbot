"""Gold drafts, ingest, review packets, import and publish, on synthetic items in a temp data root.

Decisions in these tests are written by the test suite into temporary packets to exercise the
import; they are not Chad's decisions and never reach `reference/gold/`.
"""

from __future__ import annotations

import json
import re
import shutil
import sys

import pytest
from gold_support import (
    CONFIG,
    FACTS,
    GOLD,
    ROOT,
    WALLS,
    conflict,
    context,
    control,
    injection,
    multi,
    single,
    write_batch,
)

from bonsai_help import cli, gold, gold_review, setup
from bonsai_help.doc_snapshot import CheckFailed
from bonsai_help.doc_sources import ConfigError, Refused

YES = lambda summary: True  # noqa: E731  (a test's stand-in for Chad's typed confirmation)


def store(tmp_path) -> gold_review.Store:
    return gold_review.Store(tmp_path / "data" / "gold")


def ingest(tmp_path, *items, name="batch.json", supersede=False, ctx=None, **kwargs):
    path = write_batch(tmp_path / name, *items, **kwargs)
    return gold_review.ingest(store(tmp_path), ctx or context(), path, supersede_accepted=supersede)


def export(tmp_path, split="development", size=25, items=None, ctx=None):
    return gold_review.export_packets(
        store(tmp_path), ctx or context(), split, size=size, items=items, exported_on="2026-11-22"
    )


def packet_path(tmp_path, packet_id="GP-001"):
    return store(tmp_path).folder("packets") / f"{packet_id}.md"


def decide(tmp_path, item_id, word, packet_id="GP-001", note="", fence=None):
    """Fill one block's decision region, as Chad would in his editor."""
    path = packet_path(tmp_path, packet_id)
    text = path.read_text(encoding="utf-8")
    start = text.index(f"<!-- gold:decide {item_id} -->")
    end = text.index(f"<!-- gold:end {item_id} -->")
    region = text[start:end]
    region = region.replace("DECISION:\n", f"DECISION: {word}\n", 1).replace(
        "NOTE:\n", f"NOTE: {note}\n" if note else "NOTE:\n", 1
    )
    if fence is not None:
        opening = re.search(r"\n(`{3,})json\n", region)
        ticks = opening.group(1)
        body_start = opening.end()
        body_end = region.index(f"\n{ticks}\n", body_start)
        region = region[:body_start] + json.dumps(fence, indent=2) + region[body_end:]
    path.write_text(text[:start] + region + text[end:], encoding="utf-8")


def import_(tmp_path, packet_id="GP-001", skip_stale=False, ctx=None, confirm=YES):
    return gold_review.import_packet(
        store(tmp_path),
        ctx or context(),
        packet_id,
        decided_on="2026-11-23",
        skip_stale=skip_stale,
        confirm=confirm,
    )


def prefill(tmp_path, item_id):
    s = store(tmp_path)
    head = s.heads()[item_id]["sha256"]
    return gold_review.edit_prefill(s.load_draft(item_id, head))


def files(tmp_path):
    root = tmp_path / "data" / "gold"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# ------------------------------------------------------------------ ingest


def test_a_valid_batch_writes_drafts_and_a_receipt_with_derived_citations(tmp_path):
    report = ingest(tmp_path, single(), multi())
    assert report.lines[-1].startswith("ingested 2 item(s) as GI-")
    s = store(tmp_path)
    heads = s.heads()
    assert set(heads) == {"GS-SD-901", "GS-MD-901"}
    draft = s.load_draft("GS-SD-901", heads["GS-SD-901"]["sha256"])
    ctx = context()
    record = ctx.record(WALLS)
    made = setup.make_citation(record, single()["citations"][0]["quotes"][0]["text"])
    cited = draft.citations[0]
    assert (cited.path, cited.line_start, cited.section_sha256, cited.quotes[0].line) == (
        made["path"],
        made["line_start"],
        made["section_sha256"],
        made["quote_line"],
    )
    assert (
        heads["GS-SD-901"]["lane"] == "synthetic-test" and heads["GS-SD-901"]["supersedes"] is None
    )


def test_one_failing_item_refuses_the_whole_batch(tmp_path):
    bad = single(id="GS-SD-902", category="model_exploration", profile="SP-03")
    with pytest.raises(gold_review.ProblemsFound) as caught:
        ingest(tmp_path, single(), bad)
    assert any("GS-SD-902" in p and "profile is SP-03" in p for p in caught.value.problems)
    assert files(tmp_path) == []


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"lane": "Lane One"}, "lane"),
        ({"lane": "chad-edit"}, "reserved for Chad's edits"),
        ({"drafted_on": "2026-11-22T10:00:00"}, "drafted_on"),
    ],
)
def test_lane_label_and_date_rules(tmp_path, kwargs, message):
    with pytest.raises(CheckFailed, match=message):
        ingest(tmp_path, single(), **kwargs)


def test_derived_fields_supplied_by_a_lane_are_refused(tmp_path):
    item = single()
    item["version_line"] = "VL-current"
    with pytest.raises(CheckFailed, match="Extra inputs are not permitted"):
        ingest(tmp_path, item)


def test_the_same_input_twice_a_leftover_lock_and_identical_content(tmp_path):
    ingest(tmp_path, single())
    with pytest.raises(Refused, match="already ingested"):
        ingest(tmp_path, single())
    report = ingest(tmp_path, single(), name="again.json", lane="synthetic-other")
    assert report.lines[0] == "GS-SD-901: unchanged"
    assert (
        len(store(tmp_path).ingests()) == 2
        and store(tmp_path).heads()["GS-SD-901"]["lane"] == "synthetic-test"
    )
    (tmp_path / "data/gold/.lock").write_text("")
    with pytest.raises(Refused, match="lock exists"):
        ingest(tmp_path, multi(), name="third.json")


def test_a_redraft_supersedes_the_head_and_an_accepted_head_needs_the_flag(tmp_path):
    ingest(tmp_path, single())
    first = store(tmp_path).heads()["GS-SD-901"]["sha256"]
    redraft = single()
    redraft["reference"]["steps"][1]["text"] = "Drag the length handle to the length you need."
    ingest(tmp_path, redraft, name="redraft.json")
    assert store(tmp_path).heads()["GS-SD-901"]["supersedes"] == first
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    import_(tmp_path)
    again = single()
    again["reference"]["steps"][1]["text"] = "Drag the handle."
    with pytest.raises(Refused, match="supersede-accepted"):
        ingest(tmp_path, again, name="third.json")
    ingest(tmp_path, again, name="third.json", supersede=True)
    s = store(tmp_path)
    head = s.heads()["GS-SD-901"]["sha256"]
    assert s.state_of(head, s.effective(head)) == "pending"


# ------------------------------------------------------------------ export


def test_export_orders_batches_and_never_mixes_splits(tmp_path):
    ingest(tmp_path, single(), multi(), injection())
    report = export(tmp_path, size=1)
    assert [line.split(":")[0] for line in report.lines] == ["GP-001", "GP-002"]
    first = packet_path(tmp_path).read_text(encoding="utf-8")
    assert "<!-- gold:item GS-MD-901 " in first and "GS-SD-901" not in first
    assert "GS-IH-901" not in packet_path(tmp_path, "GP-002").read_text(encoding="utf-8")
    assert export(tmp_path).lines == [
        "GS-MD-901: in GP-001, not yet imported",
        "GS-SD-901: in GP-002, not yet imported",
        "no development item is ready for review",
    ]
    held = export(tmp_path, split="held_out")
    assert held.lines == ["GP-003: 1 held_out item(s) in gold/packets/GP-003.md"]


def test_a_packet_shows_the_cited_sections_in_a_long_enough_fence(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    text = packet_path(tmp_path).read_text(encoding="utf-8")
    assert "#### C1 (support) " + WALLS in text
    assert "\n```rst\n" in text and "``Edit Wall``" in text
    assert gold_review.fence("a ```` run", "rst").startswith("`````rst\n")
    assert "Dragging only modifies the in-progress" in text
    assert "| P1 | required | bonsai_operator | bim.enable_editing_wall | any |" in text
    assert "This answer assumes Blender 5.2, Bonsai 0.9.0-post1, the IFC4 schema." in text


def test_a_packet_shows_code_spans_alternatives_and_the_negation_rule(tmp_path):
    ingest(tmp_path, conflict())
    export(tmp_path)
    text = packet_path(tmp_path).read_text(encoding="utf-8")
    assert "#### K1 (support, pinned add-on source) bonsai-source:" in text
    assert '"type": "Q", "value": "PRESS", "shift": True' in text
    assert "| P1 | required | any_of | run the quantity take-off |" in text
    assert "| P1.1 |  | hotkey | Shift-Q |" in text and "grounded" in text
    assert "| P1.2 |  | bonsai_operator | bim.perform_quantity_take_off |" in text
    assert "counts only an affirmative occurrence" in text
    # The edit JSON carries the code citations in lane form, and an unchanged approve imports.
    fence = prefill(tmp_path, "GS-SD-901")
    assert fence["code_citations"][0]["quotes"][0]["id"] == "Q1"
    assert "span_sha256" not in json.dumps(fence)
    decide(tmp_path, "GS-SD-901", "approve")
    assert import_(tmp_path).lines[0].startswith("GP-001: 1 decision(s) recorded")


def test_an_item_failing_the_check_is_skipped(tmp_path):
    ingest(tmp_path, single(setup_facts=["SF-007"]))
    raw = FACTS.model_dump(by_alias=True)
    row = next(r for r in raw["rows"] if r["id"] == "SF-007")
    review = {"decided_on": "2026-11-23", "words": "reject", "decision_id": "SR-001.01"}
    row.update(status="chad_rejected", review={**review, "content_sha256": "0" * 64})
    ctx = context(facts=type(FACTS).model_validate(raw))
    report = export(tmp_path, ctx=ctx)
    assert report.lines[0].startswith("GS-SD-901: skipped, fails the check")
    assert not packet_path(tmp_path).exists()


# ------------------------------------------------------------------ import


def test_approve_reject_and_blank_round_trips(tmp_path):
    ingest(tmp_path, single(), multi())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve", note="Checked against the walls page.")
    assert import_(tmp_path).lines == [
        "GP-001: 1 decision(s) recorded, 1 left pending, 0 stale block(s) skipped"
    ]
    s = store(tmp_path)
    heads = s.heads()
    assert (
        s.state_of(heads["GS-SD-901"]["sha256"], s.effective(heads["GS-SD-901"]["sha256"]))
        == "chad_accepted"
    )
    assert (
        s.state_of(heads["GS-MD-901"]["sha256"], s.effective(heads["GS-MD-901"]["sha256"]))
        == "pending"
    )
    record = s.imports()[0]
    assert record["notes"] == {"GP-001.02": "Checked against the walls page."}
    assert export(tmp_path).lines[0] == "GP-002: 1 development item(s) in gold/packets/GP-002.md"
    decide(tmp_path, "GS-MD-901", "reject", packet_id="GP-002")
    import_(tmp_path, "GP-002")
    head = s.heads()["GS-MD-901"]["sha256"]
    assert s.state_of(head, s.effective(head)) == "rejected"
    with pytest.raises(Refused, match="already imported"):
        import_(tmp_path, "GP-002")


def test_an_edit_creates_chads_draft_and_amends_the_item(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    fence = prefill(tmp_path, "GS-SD-901")
    fence["reference"]["steps"][1]["text"] = "Drag the length handle; the IFC file is untouched."
    decide(tmp_path, "GS-SD-901", "edit", fence=fence)
    import_(tmp_path)
    s = store(tmp_path)
    head = s.heads()["GS-SD-901"]
    assert head["lane"] == "chad-edit" and head["origin"] == "GP-001.01"
    assert s.state_of(head["sha256"], s.effective(head["sha256"])) == "chad_amended"
    assert s.load_draft("GS-SD-901", head["sha256"]).reference.steps[1].text.endswith("untouched.")


def test_an_edit_settles_only_its_result_so_a_restored_draft_is_pending_again(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    fence = prefill(tmp_path, "GS-SD-901")
    fence["reference"]["steps"][1]["text"] = "Drag the length handle; the IFC file is untouched."
    decide(tmp_path, "GS-SD-901", "edit", fence=fence)
    import_(tmp_path)
    ingest(tmp_path, single(), name="restored.json", lane="synthetic-other", supersede=True)
    s = store(tmp_path)
    head = s.heads()["GS-SD-901"]["sha256"]
    assert s.state_of(head, s.effective(head)) == "pending"
    assert export(tmp_path).lines[0].startswith("GP-002: 1 development item(s)")
    decide(tmp_path, "GS-SD-901", "approve", packet_id="GP-002")
    assert import_(tmp_path, "GP-002").lines[0].startswith("GP-002: 1 decision(s) recorded")


@pytest.mark.parametrize(
    "word, fence_change, message",
    [
        ("maybe", None, "DECISION is 'maybe'"),
        ("edit", lambda f: f.update(category="model_exploration"), "cannot change category"),
        ("edit", lambda f: f.update(version_line="VL-older"), "cannot change version_line"),
        ("approve", lambda f: f.update(question="Changed?"), "write DECISION: edit"),
        ("", lambda f: f.update(question="Changed?"), "write DECISION: edit"),
        ("edit", lambda f: None, "nothing changed"),
        (
            "edit",
            lambda f: f["citations"][0]["quotes"][0].update(text="A pen icon appears somewhere"),
            "edit: C1.Q1: quote not found",
        ),
        (
            "edit",
            lambda f: f.update(
                question="Can I fix it without extra IFC entities? It only modifies "
                "the in-progress draft."
            ),
            "matches the question itself",
        ),
    ],
)
def test_bad_decisions_and_failing_edits_write_nothing(tmp_path, word, fence_change, message):
    ingest(tmp_path, single())
    export(tmp_path)
    fence = None
    if fence_change is not None:
        fence = prefill(tmp_path, "GS-SD-901")
        fence_change(fence)
    decide(tmp_path, "GS-SD-901", word, fence=fence)
    before = files(tmp_path)
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path)
    assert any(message in p for p in caught.value.problems), caught.value.problems
    assert files(tmp_path) == before


def test_a_note_on_a_blank_decision_is_refused(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "", note="decide this later")
    before = files(tmp_path)
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path)
    assert caught.value.problems == ["GS-SD-901: a NOTE needs a decision"]
    assert files(tmp_path) == before


def test_edits_in_one_packet_are_checked_together(tmp_path):
    second = single(
        id="GS-SD-902",
        category="model_exploration",
        profile="SP-02",
        question="How do I shorten a wall that I placed too long, inside the 3D view?",
    )
    ingest(tmp_path, single(), second)
    export(tmp_path)
    question = "How can I change the length of a wall after I have placed it in the model?"
    for item_id in ("GS-SD-901", "GS-SD-902"):
        fence = prefill(tmp_path, item_id)
        fence["question"] = question
        decide(tmp_path, item_id, "edit", fence=fence)
    before = files(tmp_path)
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path)
    assert caught.value.problems == [
        "edits fail the check together: gold: GS-SD-901 GS-SD-902: the same question twice"
    ]
    assert files(tmp_path) == before


def test_an_edit_cannot_change_the_unusual_note(tmp_path):
    item = single()
    item["citations"].append(
        {
            "id": "C2",
            "role": "contrast",
            "record_id": "bonsai-docs-0-8-5-post1:src/bonsai/docs/guides/authoring/basic_modeling/"
            "creating_walls.rst#L35-L53",
            "quotes": [{"id": "Q1", "text": "Join wall segments end-to-end."}],
        }
    )
    item["patterns"].append(
        {
            "id": "P4",
            "polarity": "forbidden",
            "kind": "phrase",
            "value": "join wall segments end-to-end",
            "field": "steps",
            "part": None,
            "reason": "the older docs' route",
            "support": ["C2.Q1"],
        }
    )
    item["unusual"] = {"reason": "version_contrast", "note": "The older docs lack the editor."}
    ingest(tmp_path, item)
    export(tmp_path)
    fence = prefill(tmp_path, "GS-SD-901")
    fence["unusual"]["note"] = "My own reviewer note."
    decide(tmp_path, "GS-SD-901", "edit", fence=fence)
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path)
    assert any("cannot change unusual.note" in p for p in caught.value.problems)


def test_whitespace_and_line_endings_do_not_look_like_tampering(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    path = packet_path(tmp_path)
    text = path.read_text(encoding="utf-8")
    path.write_bytes(("\r\n".join(line + "  " for line in text.split("\n"))).encode())
    assert import_(tmp_path).lines[0].startswith("GP-001: 1 decision(s) recorded")


@pytest.mark.parametrize(
    "tamper, message",
    [
        (
            lambda t: t.replace(
                "Dragging only modifies the in-progress", "Dragging modifies the in-progress", 1
            ),
            "tampered: the fixed region changed at line",
        ),
        (
            lambda t: t.replace("Exported 2026-11-22", "Exported 2026-11-21"),
            "tampered: the header changed",
        ),
        (lambda t: t.split("<!-- gold:item GS-SD-901")[0], "blocks are missing"),
        (lambda t: t + "\nextra words\n", "text after its gold:end line"),
    ],
)
def test_a_tampered_packet_is_refused_and_names_the_place(tmp_path, tamper, message):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    path = packet_path(tmp_path)
    path.write_text(tamper(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path)
    assert any(message in p for p in caught.value.problems), caught.value.problems
    assert store(tmp_path).imports() == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("redecision", True),
        ("fixed_text", "<!-- gold:item GS-SD-901 -->\n"),
        ("draft_sha256", "0" * 64),
    ],
)
def test_an_edited_manifest_is_refused_and_nothing_is_written(tmp_path, field, value):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    path = store(tmp_path).folder("packets") / "GP-001.json"
    manifest = json.loads(path.read_bytes())
    manifest["items"][0][field] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = files(tmp_path)
    with pytest.raises(gold_review.ProblemsFound, match="packet tampered") as caught:
        import_(tmp_path)
    assert caught.value.problems == ["GP-001: tampered header or manifest"]
    assert files(tmp_path) == before


def test_reordered_blocks_are_refused(tmp_path):
    second = single(
        id="GS-SD-902",
        category="model_exploration",
        profile="SP-02",
        question="How do I shorten a wall that I placed too long, inside the 3D view?",
    )
    ingest(tmp_path, single(), second)
    export(tmp_path)
    path = packet_path(tmp_path)
    text = path.read_text(encoding="utf-8")
    head, first, rest = text.partition("<!-- gold:item GS-SD-901")
    block_one, _, block_two = (first + rest).partition("<!-- gold:item GS-SD-902")
    path.write_text(
        head + "<!-- gold:item GS-SD-902" + block_two + "\n" + block_one, encoding="utf-8"
    )
    with pytest.raises(gold_review.ProblemsFound, match="problem"):
        import_(tmp_path)


def test_a_stale_head_is_refused_and_skip_stale_imports_the_rest(tmp_path):
    ingest(tmp_path, single(), multi())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    decide(tmp_path, "GS-MD-901", "approve")
    redraft = multi()
    redraft["reference"]["steps"][2]["text"] = "Click the green tick icon to commit it."
    ingest(tmp_path, redraft, name="redraft.json")
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path)
    assert caught.value.problems == [
        "GS-MD-901: stale: the draft, its setup, its check or the lexicons, index or slots changed"
    ]
    report = import_(tmp_path, skip_stale=True)
    assert report.lines == [
        "GP-001: 1 decision(s) recorded, 0 left pending, 1 stale block(s) skipped"
    ]


def test_a_lexicon_or_slot_change_since_export_makes_every_block_stale(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    ctx = context()
    ctx.digests = {**ctx.digests, "slots": "another-slot-plan"}
    with pytest.raises(gold_review.ProblemsFound, match="1 stale block"):
        import_(tmp_path, ctx=ctx)


def changed_profile(**changes) -> gold.Context:
    """A context whose SP-04 (single()'s profile) renders differently."""
    ctx = context()
    profiles = ctx.profiles.model_dump(mode="json", by_alias=True)
    next(p for p in profiles["profiles"] if p["id"] == "SP-04").update(changes)
    ctx.profiles = setup.SetupProfiles.model_validate(profiles)
    return ctx


def test_a_profile_change_since_export_makes_its_blocks_stale(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    ctx = changed_profile(ifc_schema="IFC2X3", discipline="architecture")
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path, ctx=ctx)
    assert caught.value.problems == [
        "GS-SD-901: stale: the draft, its setup, its check or the lexicons, index or slots changed"
    ]
    assert import_(tmp_path, ctx=context()).lines[0].startswith("GP-001: 1 decision(s) recorded")


def test_a_profile_change_after_review_blocks_publish_and_stales_the_published_item(tmp_path):
    accept(tmp_path, single())
    publish_tmp(tmp_path)
    ctx = changed_profile(discipline="architecture")
    message = (
        "its profile, version line or cited fact claims changed since Chad's review; "
        "export it with --items for a re-decision (G22)"
    )
    problems, _ = gold.check_committed_set(tmp_path / "gold", ctx, complete=False)
    assert [str(p) for p in problems] == [f"gold: GS-SD-901: {message}"], problems
    with pytest.raises(gold_review.ProblemsFound) as caught:
        publish_tmp(tmp_path, ctx=ctx)
    assert caught.value.problems == [f"gold: GS-SD-901: {message}"]
    export(tmp_path, items=["GS-SD-901"], ctx=ctx)
    decide(tmp_path, "GS-SD-901", "approve", packet_id="GP-002")
    import_(tmp_path, "GP-002", ctx=ctx)
    assert publish_tmp(tmp_path, ctx=ctx).lines[0] == "development.json: written (1 items)"


def changed_claim(fact_id="SF-012") -> gold.Context:
    """A context whose fact row renders a different claim; its status is unchanged."""
    raw = FACTS.model_dump(by_alias=True)
    next(r for r in raw["rows"] if r["id"] == fact_id)["claim"] += " (edited)"
    return context(facts=type(FACTS).model_validate(raw))


def changed_sources(**changes) -> gold.Context:
    """A context whose VL-current (single()'s line) names other pinned sources."""
    ctx = context()
    profiles = ctx.profiles.model_dump(mode="json", by_alias=True)
    next(v for v in profiles["version_lines"] if v["id"] == "VL-current")["sources"].update(changes)
    ctx.profiles = setup.SetupProfiles.model_validate(profiles)
    return ctx


SETUP_CHANGED = (
    "its profile, version line or cited fact claims changed since Chad's review; "
    "export it with --items for a re-decision (G22)"
)


def test_a_cited_fact_claim_change_stales_the_block_and_then_the_review(tmp_path):
    ingest(tmp_path, single(setup_facts=["SF-012"]))
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path, ctx=changed_claim())
    assert caught.value.problems == [
        "GS-SD-901: stale: the draft, its setup, its check or the lexicons, index or slots changed"
    ]
    import_(tmp_path)
    publish_tmp(tmp_path)
    problems, _ = gold.check_committed_set(tmp_path / "gold", changed_claim(), complete=False)
    assert [str(p) for p in problems] == [f"gold: GS-SD-901: {SETUP_CHANGED}"], problems
    # A claim of a row the item does not cite is not part of its review.
    assert (
        gold.check_committed_set(tmp_path / "gold", changed_claim("SF-013"), complete=False)[0]
        == []
    )


def test_a_change_of_the_lines_pinned_sources_after_review_stales_the_published_item(tmp_path):
    accept(tmp_path, single())
    publish_tmp(tmp_path)
    item = gold.load_items(tmp_path / "gold")[0]
    ctx = changed_sources(bonsai_source="bonsai-source-0-8-5-post1")
    assert gold.setup_sha(item, ctx) != gold.setup_sha(item, context())
    assert gold.check_published_item(item, ctx) == [SETUP_CHANGED]


def repinned(source="bonsai-source", *, lexicon=False) -> gold.Context:
    """A context where a source keeps its id but names another pin (or another lexicon)."""
    ctx = context()
    key, name = ("lexicons", f"{source}.json") if lexicon else ("pins", source)
    ctx.digests = {**ctx.digests, key: {**ctx.digests[key], name: "repinned-under-the-same-id"}}
    return ctx


@pytest.mark.parametrize("lexicon", [False, True], ids=["pin", "lexicon"])
def test_a_repin_under_the_same_source_id_after_review_stales_the_published_item(tmp_path, lexicon):
    accept(tmp_path, single())
    publish_tmp(tmp_path)
    item = gold.load_items(tmp_path / "gold")[0]
    assert gold.check_published_item(item, context()) == []
    ctx = repinned(lexicon=lexicon)
    assert item.version_line == "VL-current"
    assert gold.check_published_item(item, ctx) == [SETUP_CHANGED]
    # A source of another line is not part of this item's review.
    assert gold.check_published_item(item, repinned("bonsai-source-0-8-5-post1")) == []


def test_a_change_of_the_lines_pinned_sources_between_export_and_import_stales_the_block(
    tmp_path,
):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path, ctx=changed_sources(bonsai_source="bonsai-source-0-8-5-post1"))
    assert caught.value.problems == [
        "GS-SD-901: stale: the draft, its setup, its check or the lexicons, index or slots changed"
    ]
    assert store(tmp_path).imports() == []
    assert import_(tmp_path).lines[0].startswith("GP-001: 1 decision(s) recorded")


def test_status_warns_of_an_amended_head_whose_setup_changed(tmp_path):
    ingest(tmp_path, single(setup_facts=["SF-012"]))
    export(tmp_path)
    fence = prefill(tmp_path, "GS-SD-901")
    fence["question"] = fence["question"].replace("I placed a wall", "I drew a wall")
    decide(tmp_path, "GS-SD-901", "edit", fence=fence)
    import_(tmp_path)
    assert gold_review.status(store(tmp_path), context(), tmp_path / "gold").warnings == []
    for ctx in (
        changed_profile(discipline="architecture"),
        changed_claim(),
        changed_sources(bonsai_source="bonsai-source-0-8-5-post1"),
        repinned(),
    ):
        report = gold_review.status(store(tmp_path), ctx, tmp_path / "gold")
        assert report.warnings == [
            "GS-SD-901: its profile, version line or cited fact claims changed since Chad's "
            "decision; export it with --items for a re-decision (G22)"
        ]
        assert any("state=chad_amended" in line for line in report.lines)


def test_status_warns_of_a_decided_head_whose_setup_changed(tmp_path):
    ingest(tmp_path, single(setup_facts=["SF-012"]))
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    import_(tmp_path)
    assert gold_review.status(store(tmp_path), context(), tmp_path / "gold").warnings == []
    for ctx in (changed_profile(discipline="architecture"), changed_claim()):
        report = gold_review.status(store(tmp_path), ctx, tmp_path / "gold")
        assert report.warnings == [
            "GS-SD-901: its profile, version line or cited fact claims changed since Chad's "
            "decision; export it with --items for a re-decision (G22)"
        ]
        assert any("state=chad_accepted" in line for line in report.lines)


def test_a_redecision_supersedes_and_an_old_packet_cannot_override_silently(tmp_path, monkeypatch):
    ingest(tmp_path, single(), multi())
    export(tmp_path)
    with pytest.raises(
        ConfigError, match="GS-SD-901 is in GP-001, not yet imported; import GP-001"
    ):
        export(tmp_path, items=["GS-SD-901"])
    # A draft in two unimported packets (possible before that refusal): the older packet's
    # other decisions can still be imported, and it never overrides the newer decision.
    with monkeypatch.context() as patched:
        patched.setattr(gold_review.Store, "outstanding", lambda self: {})
        export(tmp_path, items=["GS-SD-901"])
    decide(tmp_path, "GS-SD-901", "approve", packet_id="GP-002")
    import_(tmp_path, "GP-002")
    untouched = packet_path(tmp_path, "GP-001").read_text(encoding="utf-8")
    decide(tmp_path, "GS-SD-901", "reject", packet_id="GP-001")
    decide(tmp_path, "GS-MD-901", "approve", packet_id="GP-001")
    with pytest.raises(gold_review.ProblemsFound) as caught:
        import_(tmp_path, "GP-001")
    assert caught.value.problems == [
        "GS-SD-901: already decided by GP-002.01; leave its DECISION blank to import this "
        "packet's other items, then export it with --items"
    ]
    packet_path(tmp_path, "GP-001").write_text(untouched, encoding="utf-8")
    decide(tmp_path, "GS-MD-901", "approve", packet_id="GP-001")
    assert import_(tmp_path, "GP-001").lines == [
        "GP-001: 1 decision(s) recorded, 0 left pending, 0 stale block(s) skipped, "
        "1 blank block(s) of already decided drafts ignored"
    ]
    s = store(tmp_path)
    assert [d["item"] for d in s.decisions()] == ["GS-SD-901", "GS-MD-901"]
    assert s.decisions()[0]["word"] == "approve"
    export(tmp_path, items=["GS-SD-901"])
    text = packet_path(tmp_path, "GP-003").read_text(encoding="utf-8")
    assert "Re-decision: the effective decision is GP-002.01 (approve, 2026-11-23)" in text
    decide(tmp_path, "GS-SD-901", "reject", packet_id="GP-003")
    import_(tmp_path, "GP-003")
    s = store(tmp_path)
    latest = s.decisions()[-1]
    assert latest["supersedes"] == "GP-002.01" and latest["word"] == "reject"
    head = s.heads()["GS-SD-901"]["sha256"]
    assert s.state_of(head, s.effective(head)) == "rejected"


def test_an_unconfirmed_import_writes_nothing(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve")
    with pytest.raises(ConfigError, match="not confirmed"):
        import_(tmp_path, confirm=lambda summary: False)
    assert store(tmp_path).imports() == []


def test_status_reports_leftovers_without_note_text(tmp_path):
    ingest(tmp_path, single())
    export(tmp_path)
    decide(tmp_path, "GS-SD-901", "approve", note="private reviewer remark")
    import_(tmp_path)
    leftover = store(tmp_path).folder(".tmp") / "GP-002.json.abcd1234"
    leftover.write_text("{}")
    report = gold_review.status(store(tmp_path), context(), tmp_path / "gold")
    shown = "\n".join(report.lines + report.warnings)
    assert "leftover gold/.tmp/GP-002.json.abcd1234" in shown
    assert "GS-SD-901\tbonsai_modeling\tSP-04\thead=" in shown and "state=chad_accepted" in shown
    assert "private reviewer remark" not in shown


# ------------------------------------------------------------------ publish


def publish_tmp(tmp_path, write=True, ctx=None):
    return gold_review.publish(store(tmp_path), ctx or context(), tmp_path / "gold", write=write)


def accept(tmp_path, *items):
    ingest(tmp_path, *items)
    for split in ("development", "held_out"):
        report = export(tmp_path, split=split)
        for line in report.lines:
            if line.startswith("GP-"):
                packet_id = line.split(":")[0]
                text = packet_path(tmp_path, packet_id).read_text(encoding="utf-8")
                for item_id in re.findall(r"<!-- gold:item (\S+) ", text):
                    decide(tmp_path, item_id, "approve", packet_id=packet_id, note="note text 42")
                import_(tmp_path, packet_id)


def test_publish_takes_only_accepted_heads_and_is_byte_identical(tmp_path):
    accept(tmp_path, single(), injection())
    ingest(tmp_path, multi(), name="pending.json")
    report = publish_tmp(tmp_path)
    assert report.lines == [
        "development.json: written (1 items)",
        "held-out.json: written (1 items)",
    ]
    first = {p.name: p.read_bytes() for p in (tmp_path / "gold").iterdir()}
    assert publish_tmp(tmp_path).lines[0] == "development.json: unchanged (1 items)"
    assert {p.name: p.read_bytes() for p in (tmp_path / "gold").iterdir()} == first
    published = gold.load_items(tmp_path / "gold")
    assert [i.id for i in published] == ["GS-SD-901"]
    assert published[0].review.words == "approve" and published[0].review.packet_id == "GP-001"
    for data in first.values():
        assert b"note text 42" not in data
    _, held, _ = gold.load_held_out(tmp_path / "gold")
    assert [i.id for i in held] == ["GS-IH-901"]
    problems, _ = gold.check_committed_set(tmp_path / "gold", context(), complete=False)
    assert problems == [], problems


def test_a_control_case_is_reviewed_and_published_with_the_held_out_items(tmp_path):
    ingest(tmp_path, control(), injection())
    export(tmp_path, split="held_out")
    text = packet_path(tmp_path).read_text(encoding="utf-8")
    assert "### Control (benign look-alike; must be answered, not refused)" in text
    assert "- vector pasted_doc_excerpt, look-alike text in the user_context" in text
    assert prefill(tmp_path, "GS-CH-901")["control"] == control()["control"]
    for item_id in ("GS-CH-901", "GS-IH-901"):
        decide(tmp_path, item_id, "approve")
    import_(tmp_path)
    publish_tmp(tmp_path)
    _, held, _ = gold.load_held_out(tmp_path / "gold")
    assert [(i.id, i.kind) for i in held] == [("GS-CH-901", "control"), ("GS-IH-901", "injection")]
    assert gold.check_committed_set(tmp_path / "gold", context(), complete=False)[0] == []


def test_publish_compare_mode_and_stale_headers(tmp_path):
    accept(tmp_path, single())
    with pytest.raises(CheckFailed, match="run gold publish --write"):
        publish_tmp(tmp_path, write=False)
    publish_tmp(tmp_path)
    assert publish_tmp(tmp_path, write=False).lines[0].endswith("unchanged (1 items)")
    ctx = context()
    ctx.digests = {
        **ctx.digests,
        "lexicons": {**ctx.digests["lexicons"], "bonsai-source.json": "0" * 64},
    }
    problems, _ = gold.check_committed_set(tmp_path / "gold", ctx, complete=False)
    # The file header is stale, and so is Chad's review: the packet's accepted forms came from
    # the old lexicon of the item's line.
    assert [p.message for p in problems] == [
        "lexicons is stale; recheck and republish (G22)",
        SETUP_CHANGED,
    ]


def test_publish_refuses_pages_outside_the_fixture_slice_and_lists_them(tmp_path):
    accept(tmp_path, single())
    plain = CONFIG.model_dump(by_alias=True)
    for source in plain["sources"]:
        if source["id"] == "bonsai-docs":
            source["fixture_pages"] = [
                p for p in source["fixture_pages"] if not p["path"].endswith("creating_walls.rst")
            ]
    ctx = context()
    ctx.config = type(CONFIG).model_validate(plain)
    with pytest.raises(gold_review.ProblemsFound) as caught:
        publish_tmp(tmp_path, ctx=ctx)
    assert any("creating_walls.rst" in p and "fixture_pages" in p for p in caught.value.problems)
    assert not (tmp_path / "gold").exists()


# ------------------------------------------------------------------ CLI


def test_packet_import_needs_an_interactive_terminal(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(ROOT / "tests")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code = cli.main(["gold", "packet", "import", "GP-001", "--data-root", str(tmp_path / "data")])
    assert code == 2
    assert "needs an interactive terminal" in capsys.readouterr().err


def test_gold_check_drafts_needs_the_data_root(monkeypatch, capsys):
    monkeypatch.chdir(ROOT / "tests")
    assert cli.main(["gold", "check", "--committed", "--drafts"]) == 2
    assert "error: --drafts reads the draft heads in the data root; drop --committed" in (
        capsys.readouterr().err
    )


def test_gold_score_scores_development_items_only(tmp_path, monkeypatch, capsys):
    accept(tmp_path, single(), injection())
    publish_tmp(tmp_path)
    gold_dir = tmp_path / "gold"
    shutil.copy(GOLD / "slots.json", gold_dir / "slots.json")
    answers = tmp_path / "answers.jsonl"
    answers.write_text(
        json.dumps(
            {
                "item_id": "GS-SD-901",
                "fields": {
                    "answer": "Use the Edit Wall pen; it only modifies the in-progress draft.",
                    "steps": ["Select the wall.", "Drag the handle.", "Commit."],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(ROOT / "tests")
    assert cli.main(["gold", "score", str(answers), "--gold", str(gold_dir)]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["item_id"] == "GS-SD-901" and row["all_pass"] is True and row["score"] == 1.0
    answers.write_text(json.dumps({"item_id": "GS-IH-901", "fields": {"answer": "x"}}) + "\n")
    assert cli.main(["gold", "score", str(answers), "--gold", str(gold_dir)]) == 2
    assert "not a published development item" in capsys.readouterr().err
    answers.write_text(json.dumps({"item_id": "GS-SD-901", "fields": {"question": "x"}}) + "\n")
    assert cli.main(["gold", "score", str(answers), "--gold", str(gold_dir)]) == 2
