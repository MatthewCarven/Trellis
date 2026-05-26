"""A1 ↔ (row, col) address conversion.

Trellis uses zero-indexed `(row, col)` tuples as the internal representation
for every cell address. A1 notation ("B3", "AA10", "ZZ999"...) is the public
convention for human-facing APIs — convert at the boundary, never in the middle.

Public functions:
    parse(addr)       -> (row, col)
    to_a1(row, col)   -> "A1"-style string
"""

from __future__ import annotations

import re

# Strict pattern: one-or-more uppercase letters followed by one-or-more digits.
# Leading zeros on the row part are not accepted ("A01" is not a valid A1 ref).
_A1_RE = re.compile(r"^([A-Z]+)([1-9]\d*)$")


def parse(addr: str) -> tuple[int, int]:
    """Convert an 'A1'-style address to a zero-indexed (row, col).

    >>> parse("A1")
    (0, 0)
    >>> parse("B3")
    (2, 1)
    >>> parse("AA10")
    (9, 26)
    >>> parse("ZZ999")
    (998, 701)

    Raises:
        ValueError: if `addr` is not a well-formed A1 reference.
    """
    if not isinstance(addr, str):
        raise TypeError(f"Address must be a string, got {type(addr).__name__}")
    m = _A1_RE.match(addr.strip().upper())
    if not m:
        raise ValueError(f"Not a valid A1 address: {addr!r}")
    letters, digits = m.groups()
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return int(digits) - 1, col - 1


def to_a1(row: int, col: int) -> str:
    """Convert a zero-indexed `(row, col)` to an 'A1'-style string.

    >>> to_a1(0, 0)
    'A1'
    >>> to_a1(2, 1)
    'B3'
    >>> to_a1(9, 26)
    'AA10'
    >>> to_a1(998, 701)
    'ZZ999'

    Raises:
        ValueError: if `row` or `col` is negative.
    """
    if row < 0 or col < 0:
        raise ValueError(f"Address coordinates must be non-negative, got ({row}, {col})")
    letters = ""
    c = col + 1
    while c > 0:
        c, rem = divmod(c - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return f"{letters}{row + 1}"
