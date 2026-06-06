"""Formula errors as values.

In a spreadsheet, errors are not exceptions — they are *values* that propagate
through formulas. ``=A1/B1`` where B1 is zero produces ``#DIV/0!``; if another
cell does ``=A2+5`` and A2 holds ``#DIV/0!``, the result is also ``#DIV/0!``.
This module defines :class:`FormulaError` (a value type) and the standard
spreadsheet error constants.

:class:`FormulaError` is intentionally NOT a subclass of ``Exception``. It is
a value you compare against, store in a cell, and return from a function. The
formula engine never raises a FormulaError out of evaluation — it produces one
and returns it.

The parser DOES raise :class:`ParseError` (a Python exception) when source
code can't be parsed. At the Sheet integration boundary (task #4c) that gets
caught and converted to a FormulaError (``NAME`` for unknown identifiers,
``VALUE`` for syntactic problems).
"""

from __future__ import annotations


class FormulaError:
    """A spreadsheet error value.

    Two FormulaError instances are equal if they have the same ``code``; the
    ``message`` is for human debugging and does not participate in equality
    or hashing.
    """

    __slots__ = ("code", "message")

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message

    def __repr__(self) -> str:
        if self.message:
            return f"FormulaError({self.code!r}, {self.message!r})"
        return f"FormulaError({self.code!r})"

    def __str__(self) -> str:
        return self.code

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FormulaError):
            return self.code == other.code
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.code)


# Standard Excel-shaped error values. Module-level singletons; callers may
# compare against them by identity or equality. Construct a fresh FormulaError
# with the same code (and a custom message) if you want extra context.
DIV0 = FormulaError("#DIV/0!", "Division by zero")
VALUE = FormulaError("#VALUE!", "Wrong type for this operation")
REF = FormulaError("#REF!", "Reference to a missing or deleted cell")
NAME = FormulaError("#NAME?", "Unknown function or identifier")
CIRC = FormulaError("#CIRC!", "Circular reference detected")
NA = FormulaError("#N/A", "Value not available")
NULL = FormulaError("#NULL!", "Empty intersection")

# Code -> singleton lookup. The lexer scans error literals against these
# exact code strings (``=#REF!*2`` is valid source — shift_formula emits it
# when a reference falls off the sheet edge); the evaluator resolves the
# code back to its constant.
_BY_CODE = {e.code: e for e in (DIV0, VALUE, REF, NAME, CIRC, NA, NULL)}


class ParseError(Exception):
    """Raised by the lexer/parser when source can't be parsed.

    Internal — at the Sheet integration boundary this is caught and converted
    to a :class:`FormulaError` value.
    """

    def __init__(self, message: str, pos: int = -1):
        super().__init__(message)
        self.pos = pos
