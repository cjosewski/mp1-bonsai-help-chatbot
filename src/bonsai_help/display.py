"""Text shown to a reviewer or a judge: control-character escaping and section headings.

Moved unchanged from B6's labeling display (`labels._escape` and `labels._heading`), so the
labeler's display and the judge's rendering share one escaping rule and one heading rule.
The module is on the judge's render path and is part of the frozen judge identity
(`judge.FROZEN_JUDGE_MODULES`); `labels` imports both helpers from here.
"""

from __future__ import annotations

import unicodedata

from bonsai_help.docs_index import is_adornment

# Control, format, line and paragraph separator and surrogate characters are escaped.
_ESCAPED_CATEGORIES = ("Cc", "Cf", "Zl", "Zp", "Cs")


def escape_control(text: str) -> str:
    """Control and format characters shown as escapes, so item text cannot drive a terminal.

    Newline and tab are kept. Every other character of the categories above is shown as
    `\\xNN` (up to U+00FF) or `\\uNNNN`, so a carriage return, a vertical tab, U+0085 or
    U+2028 cannot start a new line of its own.
    """
    out = []
    for char in text:
        if char in "\n\t" or unicodedata.category(char) not in _ESCAPED_CATEGORIES:
            out.append(char)
        elif ord(char) <= 0xFF:
            out.append(f"\\x{ord(char):02x}")
        else:
            out.append(f"\\u{ord(char):04x}")
    return "".join(out)


def section_heading(text: str) -> str:
    """A section's heading: its first nonblank line that is not an RST adornment."""
    for line in text.split("\n"):
        if line.strip() and not is_adornment(line):
            return line.strip()
    return "(none)"
