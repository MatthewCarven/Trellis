"""Evaluator for parsed formula ASTs.

Walks an AST and produces a result value (a number, string, bool, None, a
list of values from a range, or a :class:`FormulaError`). Function calls
dispatch through the registry in :mod:`trellis.formula.functions`; unknown
names return ``NAME``.

Errors are values, not exceptions: any FormulaError operand short-circuits
the surrounding operation and propagates outward. Empty-cell values (``None``)
coerce to ``0`` in arithmetic and ``""`` in concatenation, matching Excel.

Booleans coerce to 0/1 in arithmetic and in comparisons. Strings do NOT auto-
convert to numbers — ``"5" + 1`` is a VALUE error (Excel would parse it; we're
strict for v1).

Ranges (lists of values) are illegal as scalar operands. Use them only as
function arguments — anything else returns VALUE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .ast import (
    BinaryOp,
    Bool,
    CellRef,
    Error,
    FunctionCall,
    Number,
    RangeRef,
    String,
    UnaryOp,
)
from .errors import DIV0, NAME, VALUE, FormulaError, _BY_CODE
from .functions import get_function

if TYPE_CHECKING:
    from trellis.core.sheet import Sheet
    from trellis.core.workbook import Workbook


@dataclass
class Context:
    """Evaluation context — what cell references resolve against.

    Attributes:
        sheet: The Sheet a formula's *unqualified* CellRef / RangeRef nodes
            resolve against (the holding sheet).
        workbook: The Workbook used to resolve *sheet-qualified* refs
            (``Sheet2!A1``) by name; ``None`` for a bare-sheet evaluation,
            where a qualified ref then yields ``NAME``.
        current_cell: Optional ``(row, col)`` of the cell holding the formula.
            Used by the recalc engine for circular-reference detection. The
            evaluator itself does not read it.

    The :meth:`evaluate` method is a thin wrapper around the module-level
    :func:`evaluate` function — provided so lazy-arg functions can write
    ``ctx.evaluate(node)`` without importing from this module.
    """

    sheet: "Sheet"
    current_cell: tuple[int, int] | None = None
    workbook: "Workbook | None" = None

    def evaluate(self, node: Any) -> Any:
        """Evaluate ``node`` in this context. Convenience for lazy functions."""
        return evaluate(node, self)


def evaluate(node: Any, ctx: Context) -> Any:
    """Evaluate an AST node in ``ctx`` and return its value.

    Returns one of:
        - ``int`` / ``float`` / ``str`` / ``bool``: a scalar
        - ``None``: an empty cell (bubbles up from CellRef; arithmetic
          operands coerce None to 0 / "")
        - ``list``: values from a RangeRef (1D, row-major)
        - :class:`FormulaError`: a spreadsheet error value

    **Never raises** :class:`FormulaError` — errors are values.
    """
    if isinstance(node, Number):
        return node.value
    if isinstance(node, String):
        return node.value
    if isinstance(node, Bool):
        return node.value
    if isinstance(node, Error):
        # Resolve the literal back to its constant; mint if a plugin
        # taught the parser a code core doesn't know (open-world rule).
        return _BY_CODE.get(node.code, FormulaError(node.code))
    if isinstance(node, CellRef):
        return _eval_cellref(node, ctx)
    if isinstance(node, RangeRef):
        return _eval_rangeref(node, ctx)
    if isinstance(node, UnaryOp):
        return _eval_unary(node, ctx)
    if isinstance(node, BinaryOp):
        return _eval_binary(node, ctx)
    if isinstance(node, FunctionCall):
        return _eval_function(node, ctx)
    return FormulaError(VALUE.code, f"Unknown AST node type: {type(node).__name__}")


# --- Reference resolution ------------------------------------------------


def _resolve_sheet(sheet_name: Any, ctx: Context):
    # Resolve a ref's sheet to a Sheet object. None (unqualified) -> the
    # holding ctx.sheet. A qualified name is looked up in ctx.workbook by name;
    # an unknown name (or no workbook) yields NAME, which bubbles up like any
    # other error value.
    if sheet_name is None:
        return ctx.sheet
    wb = ctx.workbook
    if wb is None or sheet_name not in wb:
        return NAME
    return wb[sheet_name]


def _eval_cellref(node: CellRef, ctx: Context) -> Any:
    """Look up the value of a single cell. Empty cells return None."""
    sheet = _resolve_sheet(node.sheet, ctx)
    if isinstance(sheet, FormulaError):
        return sheet
    return sheet.get((node.row, node.col)).value


def _eval_rangeref(node: RangeRef, ctx: Context) -> Any:
    """Return a flat list of values for every position in the range, row-major.

    Empty cells contribute ``None`` to the list (not skipped — preserves shape).
    """
    sheet = _resolve_sheet(node.start.sheet, ctx)
    if isinstance(sheet, FormulaError):
        return sheet
    start = (node.start.row, node.start.col)
    end = (node.end.row, node.end.col)
    return list(sheet.range((start, end)).values())


# --- Operators ----------------------------------------------------------


def _eval_unary(node: UnaryOp, ctx: Context) -> Any:
    val = evaluate(node.operand, ctx)
    if isinstance(val, FormulaError):
        return val
    if isinstance(val, list):
        return VALUE

    n = _to_number(val)
    if isinstance(n, FormulaError):
        return n

    if node.op == "+":
        return n
    if node.op == "-":
        return -n
    if node.op == "%":
        return n / 100
    return FormulaError(VALUE.code, f"Unknown unary operator: {node.op}")


def _eval_binary(node: BinaryOp, ctx: Context) -> Any:
    left = evaluate(node.left, ctx)
    if isinstance(left, FormulaError):
        return left
    right = evaluate(node.right, ctx)
    if isinstance(right, FormulaError):
        return right

    if isinstance(left, list) or isinstance(right, list):
        return VALUE  # ranges don't fit scalar binary ops

    op = node.op

    if op == "&":
        return _to_string(left) + _to_string(right)

    if op in ("+", "-", "*", "/", "^"):
        l = _to_number(left)
        if isinstance(l, FormulaError):
            return l
        r = _to_number(right)
        if isinstance(r, FormulaError):
            return r
        if op == "+":
            return l + r
        if op == "-":
            return l - r
        if op == "*":
            return l * r
        if op == "/":
            if r == 0:
                return DIV0
            return l / r
        if op == "^":
            try:
                return l ** r
            except (OverflowError, ValueError, ZeroDivisionError):
                return FormulaError("#NUM!", "Number overflow or invalid math")

    if op in ("=", "<>", "<", ">", "<=", ">="):
        return _compare(left, right, op)

    return FormulaError(VALUE.code, f"Unknown binary operator: {op}")


# --- Function dispatch -------------------------------------------------


def _eval_function(node: FunctionCall, ctx: Context) -> Any:
    """Look up the function in the registry and call it.

    Returns ``NAME`` if no function is registered under this name. For
    eager functions, args are pre-evaluated and any FormulaError
    short-circuits (the function is never invoked). For lazy functions,
    args are passed as raw AST nodes — the function uses
    ``ctx.evaluate(node)`` to materialize them.
    """
    entry = get_function(node.name)
    if entry is None:
        return FormulaError(NAME.code, f"Unknown function {node.name!r}")
    fn, is_lazy = entry
    if is_lazy:
        return fn(ctx, *node.args)
    args: list = []
    for arg in node.args:
        val = evaluate(arg, ctx)
        if isinstance(val, FormulaError):
            return val
        args.append(val)
    return fn(ctx, *args)


# --- Coercion helpers --------------------------------------------------


def _to_number(v: Any) -> Any:
    """Coerce a value to a number for arithmetic.

    None -> 0 (empty cells act as zero in Excel arithmetic).
    bool -> 0/1.
    int / float -> as-is.
    str -> VALUE error (no auto-parsing in v1).
    Anything else -> VALUE error.
    """
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    return VALUE


def _to_string(v: Any) -> str:
    """Coerce a value to a string for ``&`` concatenation.

    None -> "". bool -> "TRUE"/"FALSE". Integer-valued floats -> "N" (no
    trailing ".0"). Everything else -> ``str(v)``.
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _compare(left: Any, right: Any, op: str) -> Any:
    """Excel-shaped comparison. Returns bool or VALUE error.

    None coerces to 0 (numeric context) or "" (string context based on the
    other operand). Booleans coerce to 0/1. Incompatible types yield VALUE.
    """
    if left is None and isinstance(right, str):
        left = ""
    elif left is None:
        left = 0
    if right is None and isinstance(left, str):
        right = ""
    elif right is None:
        right = 0

    if isinstance(left, bool):
        left = int(left)
    if isinstance(right, bool):
        right = int(right)

    try:
        if op == "=":
            return left == right
        if op == "<>":
            return left != right
        if op == "<":
            return left < right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        if op == ">=":
            return left >= right
    except TypeError:
        return VALUE
    return VALUE
