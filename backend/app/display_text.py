"""Text from third parties, as the evidence shows it: on one line, nothing hidden.

Labels, explorer tags, list entries and exchange names come from other people
(TronScan, imported label lists, the label store). What reaches a signed
report, a PDF, a letter or a graph export must not be able to:

* start a line of its own: a newline in a tag would let it write a whole
  "FINDING" block that this server then signs, or a "CONTENT HASH (" line
  that makes the verifier cut a genuine report short;
* hide or reorder characters: bidi overrides and zero-width characters can
  make an address or a name read as something it is not;
* break a file format: XML 1.0 forbids most control characters, and a lone
  surrogate cannot be written as UTF-8 at all.

Line breaks, tabs and other control characters become a space. Characters
that print nothing (format, surrogate, private-use, unassigned) are shown as
<U+XXXX>, so a reader can see that something was there. Nothing is
normalised: a look-alike stays visibly what it is.
"""
from __future__ import annotations

import unicodedata
from typing import Any

# Category -> what replaces a character of it. Anything not printable and not
# listed here (Cf, Cs, Co, Cn) is escaped.
_AS_SPACE = {"Cc", "Zl", "Zp", "Zs"}


def _swap(ch: str) -> str:
    if ch.isprintable():
        return ch
    if unicodedata.category(ch) in _AS_SPACE:
        return " "
    return f"<U+{ord(ch):04X}>"


def one_line(value: Any) -> str:
    """`value` as text that is one line and shows everything it holds."""
    text = "" if value is None else str(value)
    if text.isprintable():  # the common case, checked in C
        return text
    return "".join(_swap(ch) for ch in text)


def short(value: Any, max_len: int) -> str:
    """one_line, cut to `max_len` characters with an ellipsis."""
    text = one_line(value)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"
