"""Synthetic review packets can be replaced after their checking context becomes stale."""

import copy

import pytest
from gold_support import context, single
from test_gold_review import decide, export, import_, ingest, packet_path, store

from bonsai_help import gold_review
from bonsai_help.doc_sources import ConfigError


def test_changed_checker_allows_new_packet_without_recording_a_review(tmp_path):
    old = context()
    ingest(tmp_path, single(), ctx=old)
    export(tmp_path, ctx=old)
    original = packet_path(tmp_path).read_bytes()
    new = context()
    new.digests = copy.deepcopy(old.digests)
    new.digests["checker"] = old.digests["checker"] + "-updated"
    report = export(tmp_path, ctx=new)
    assert report.lines == ["GP-002: 1 development item(s) in gold/packets/GP-002.md"]
    assert packet_path(tmp_path).read_bytes() == original
    assert store(tmp_path).imports() == []
    assert store(tmp_path).decisions() == []
    assert not any("GP-003:" in line for line in export(tmp_path, ctx=new).lines)
    # GP-002 re-exported GP-001's unchanged draft; GP-001 is still reported as a record.
    warnings = gold_review.status(store(tmp_path), new, tmp_path / "gold").warnings
    assert "GP-001 uses an obsolete checking context; retained as a record" in warnings
    assert "GP-002 exported, not yet imported" in warnings
    with pytest.raises(ConfigError, match="not yet imported"):
        export(tmp_path, ctx=new, items=["GS-SD-901"])
    decide(tmp_path, "GS-SD-901", "approve")
    with pytest.raises(gold_review.ProblemsFound, match="nothing written"):
        import_(tmp_path, ctx=new)
    assert store(tmp_path).imports() == []
    decide(tmp_path, "GS-SD-901", "approve", packet_id="GP-002")
    import_(tmp_path, packet_id="GP-002", ctx=new)
    assert len(store(tmp_path).decisions()) == 1
    assert store(tmp_path).decisions()[0]["packet_id"] == "GP-002"
