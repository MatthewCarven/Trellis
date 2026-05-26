"""The Cell — the atom of a Trellis sheet.

A Cell carries a value, an optional source formula string, and an open
`meta` dict. The `meta` dict is intentionally public: plugins (formatting,
styling, validation, tagging) live there. Trellis core never writes to it.

Cells are deliberately *not* slotted. We trade a bit of per-cell memory for
the freedom to attach arbitrary attributes via subclassing or monkey-patching
without ceremony — that is the framework promise.
"""

from __future__ import annotations

from typing import Any


class Cell:
    """A single cell in a sheet.

    Attributes:
        value: The current value of the cell. Anything — number, str, bool,
            None, or a plugin-defined object. After a formula is evaluated,
            this is the result.
        formula: The source formula string (e.g. ``"=A1+B2"``), or None.
            Plain values have no formula. Trellis core does not yet evaluate
            formulas; the engine arrives in Phase 4.
        meta: A dict for plugins to attach arbitrary state. Core never writes
            here — it is yours.

    Constructing a cell with no arguments yields an empty cell:

    >>> Cell().is_empty()
    True
    >>> Cell(value=5).value
    5
    >>> Cell(formula="=A1+1").formula
    '=A1+1'
    """

    def __init__(self, value: Any = None, formula: str | None = None):
        self.value = value
        self.formula = formula
        self.meta: dict[str, Any] = {}

    def is_empty(self) -> bool:
        """True iff value, formula, and meta are all empty/None."""
        return self.value is None and self.formula is None and not self.meta

    def __repr__(self) -> str:
        if self.formula is not None:
            return f"Cell(value={self.value!r}, formula={self.formula!r})"
        return f"Cell({self.value!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Cell):
            return NotImplemented
        return (
            self.value == other.value
            and self.formula == other.formula
            and self.meta == other.meta
        )

    def __hash__(self):  # cells are mutable — explicitly unhashable
        raise TypeError("Cell is mutable and not hashable")
