"""AST nodes for parsed formulas.

All nodes are frozen dataclasses — immutable, hashable, value-equal. The
parser builds trees of these; the evaluator (task #4b) walks them via
``isinstance`` dispatch.

``Node`` is the union of every concrete node type. No abstract base class;
duck typing is enough.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class Number:
    """Numeric literal — int or float per the source."""

    value: float | int


@dataclass(frozen=True)
class String:
    """String literal (post-escape: ``""`` already collapsed to ``"``)."""

    value: str


@dataclass(frozen=True)
class Bool:
    """Boolean literal — TRUE or FALSE (case-insensitive in source)."""

    value: bool


@dataclass(frozen=True)
class CellRef:
    """Reference to a single cell. Coordinates are zero-indexed.

    ``col_abs`` / ``row_abs`` are the ``$`` pins (``$A$1``, ``$A1``, ``A$1``).
    They are deliberately invisible to evaluation and recalc — ``=$A$1``
    computes exactly like ``=A1``, and both are the same dependency (the
    graph keys on ``(row, col)``). The flags exist for rewriting tools
    (``shift_formula``, design.md Part 6), which shift only unpinned axes.

    No sheet attribute yet — cross-sheet references (``Sheet2!A1``) are out
    of scope for v1.
    """

    row: int
    col: int
    col_abs: bool = False
    row_abs: bool = False


@dataclass(frozen=True)
class RangeRef:
    """Reference to a rectangle of cells, e.g. ``A1:B5``.

    ``start`` is always the top-left, ``end`` always the bottom-right —
    the parser corner-normalises before constructing.
    """

    start: CellRef
    end: CellRef


@dataclass(frozen=True)
class UnaryOp:
    """Unary operator: prefix ``-`` / ``+`` or postfix ``%`` (divide-by-100)."""

    op: str
    operand: "Node"


@dataclass(frozen=True)
class BinaryOp:
    """Binary operator.

    Supported ``op`` values:
        ``+ - * /``    arithmetic
        ``^``           exponentiation (right-associative; parser handles)
        ``&``           string concatenation
        ``= <> < > <= >=``   comparisons
    """

    op: str
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class FunctionCall:
    """Function invocation, e.g. ``SUM(A1:A5)``.

    ``name`` is upper-case (the parser normalises). ``args`` is a tuple of
    Nodes (immutable, so the AST stays hashable).
    """

    name: str
    args: tuple


Node = Union[Number, String, Bool, CellRef, RangeRef, UnaryOp, BinaryOp, FunctionCall]
