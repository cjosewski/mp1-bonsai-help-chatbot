"""The first-pass gate stays frozen until the Phase B comparison (docs/DECISIONS.md,
November 24, 2026: "B5 report and gate freeze")."""

from __future__ import annotations

import hashlib
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "bonsai_help"

# SHA-256 of each gate file on November 24, 2026, at commit 3b3c51e.
FROZEN_GATE_FILES = {
    "checks.py": "4ba071af29d88255d9f727f956b4bb498edb8396d280a4e4257b7cf724bc62de",
    "gate.py": "3bdd471a030d640d75d46f9523f17f24a59cdda47a0fd587c7cdd995128416f7",
    "sampler.py": "93a1f9076b8cbe5c1b8f92908b2de78cc963dbccdcbef22164d31006cfae78d1",
}


def test_gate_files_unchanged_until_phase_b():
    """The deterministic checks, the gate and the sampler (with the quote and lexicon rules
    they apply) are byte-for-byte those of the baseline collection, so the baseline and
    corrected arms are gated alike.

    These hashes may change only after the Phase B comparison, and only with a dated
    docs/DECISIONS.md entry that records the change and its reason. Never update them to
    make this test pass."""
    actual = {
        name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in FROZEN_GATE_FILES
    }
    changed = sorted(name for name, sha in FROZEN_GATE_FILES.items() if actual[name] != sha)
    assert not changed, f"frozen gate file(s) changed before the Phase B comparison: {changed}"
