"""Sheet — a sparse 2D collection of Cells, addressed by (row, col) or A1.

The store is a plain dict keyed by ``(row, col)``. Absent addresses are *not*
stored as empty cells — reads return a fresh empty ``Cell`` without persisting
it, so iterating a sheet only walks cells that have actually been written.

Sheets are :class:`~trellis.core.events.Emitter` s. Every mutation that goes
through the public API emits ``"cell:change"`` with ``addr``, ``old``, ``new``.
Delete of an existing cell also emits, with ``new`` set to an empty ``Cell``.
Delete of an absent address is silent.

Range support: ``sheet['A1:B5']`` returns a :class:`~trellis.core.range.Range`
view. Assignment broadcasts (``sheet['A1:B5'] = 0`` fills, ``sheet['A1:A5'] =
[1,2,3,4,5]`` spreads). ``del sheet['A1:B5']`` clears every cell in the range.

Public surface:
    sheet.get(addr)         -> Cell       (empty Cell if absent)
    sheet.set(addr, value)  -> None       (also accepts a Cell or a "=formula")
    sheet.delete(addr)      -> None
    sheet.range(addr)       -> Range      (e.g. sheet.range("A1:B5"))
    sheet[addr]             -> Cell or Range (depending on address shape)
    sheet[addr] = value     -> None       (single set or range broadcast)
    del sheet[addr]         -> None       (single delete or range clear)
    addr in sheet           -> bool       (single-cell membership only)
    sheet.cells()           -> iterator of (A1, Cell) for stored cells
    len(sheet)              -> number of stored cells
    sheet.on("cell:change", handler) -> Subscription
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Union

from .address import parse as parse_addr
from .address import to_a1
from .cell import Cell
from .events import Emitter
from .range import Range

Address = Union[str, tuple[int, int]]


def _coerce(addr: Address) -> tuple[int, int]:
    """Normalise a single-cell address to (row, col)."""
    if isinstance(addr, str):
        return parse_addr(addr)
    if isinstance(addr, tuple) and len(addr) == 2:
        return int(addr[0]), int(addr[1])
    raise TypeError(
        f"Address must be an 'A1' string or (row, col) tuple, got {addr!r}"
    )


def _is_range_addr(addr: Any) -> bool:
    """True if ``addr`` denotes a range rather than a single cell.

    Range shapes:
        - any string containing ``":"`` (e.g. ``"A1:B5"``)
        - a 2-tuple of 2-tuples (e.g. ``((0,0), (4,1))``)

    Single-cell shapes ((row, col) ints, "A1" strings) return False.
    """
    if isinstance(addr, str):
        return ":" in addr
    if isinstance(addr, tuple) and len(addr) == 2:
        a, b = addr
        if (isinstance(a, tuple) and len(a) == 2
                and isinstance(b, tuple) and len(b) == 2):
            return True
    return False


class Sheet(Emitter):
    """Sparse 2D grid of cells.

    >>> s = Sheet("Demo")
    >>> changes = []
    >>> _ = s.on("cell:change", lambda addr, old, new: changes.append(addr))
    >>> s["A1"] = 5
    >>> s["B2"] = "=A1*2"
    >>> changes
    ['A1', 'B2']
    >>> s["A3:C3"] = [10, 20, 30]    # range broadcast
    >>> [c.value for c in s["A3:C3"]]
    [10, 20, 30]
    """

    def __init__(self, name: str = "Sheet1"):
        self.name = name
        self._cells: dict[tuple[int, int], Cell] = {}
        self.meta: dict[str, Any] = {}  # plugin scratch space; core never writes here

    # --- single-cell access ----------------------------------------------

    def get(self, addr: Address) -> Cell:
        """Return the cell at ``addr``. Returns an empty (not-stored) Cell if absent."""
        return self._cells.get(_coerce(addr), Cell())

    def set(self, addr: Address, value: Any) -> None:
        """Write to ``addr`` (single cell).

        Accepts:
            - a :class:`Cell` instance (stored as-is — subclasses are honoured),
            - a string starting with ``=`` (treated as a formula),
            - anything else (stored as a plain value).

        Emits ``"cell:change"`` with payload ``addr``, ``old``, ``new``. No
        value-equality short-circuit — setting to the same value still fires.
        That's a plugin's job to optimize if it cares.
        """
        key = _coerce(addr)
        old = self._cells.get(key, Cell())
        if isinstance(value, Cell):
            new = value
        elif isinstance(value, str) and value.startswith("="):
            new = Cell(value=None, formula=value)
        else:
            new = Cell(value=value)
        self._cells[key] = new
        self.emit("cell:change", addr=to_a1(*key), old=old, new=new)

    def delete(self, addr: Address) -> None:
        """Remove the cell at ``addr`` if present.

        Emits ``"cell:change"`` with ``new`` set to an empty cell — only if a
        cell was actually present. Deleting an absent address is silent.
        """
        key = _coerce(addr)
        old = self._cells.pop(key, None)
        if old is not None:
            self.emit("cell:change", addr=to_a1(*key), old=old, new=Cell())

    # --- range access ----------------------------------------------------

    def range(self, addr: Any) -> Range:
        """Return a :class:`Range` view over a rectangle of cells."""
        return Range(self, addr)

    # --- dict-like sugar -------------------------------------------------

    def __getitem__(self, addr: Any) -> Any:
        """Return a Cell for single-cell addresses, a Range for range-shaped ones."""
        if _is_range_addr(addr):
            return self.range(addr)
        return self.get(addr)

    def __setitem__(self, addr: Any, value: Any) -> None:
        """Single-cell set, or range broadcast for range-shaped addresses."""
        if _is_range_addr(addr):
            self.range(addr).assign(value)
        else:
            self.set(addr, value)

    def __delitem__(self, addr: Any) -> None:
        """Single-cell delete, or range clear for range-shaped addresses."""
        if _is_range_addr(addr):
            self.range(addr).clear()
        else:
            self.delete(addr)

    def __contains__(self, addr: object) -> bool:
        try:
            return _coerce(addr) in self._cells  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    # --- iteration -------------------------------------------------------

    def cells(self) -> Iterator[tuple[str, Cell]]:
        """Iterate ``(A1, Cell)`` pairs for every stored cell.

        Insertion order is preserved (Python dict semantics).
        """
        for (row, col), cell in self._cells.items():
            yield to_a1(row, col), cell

    def __len__(self) -> int:
        return len(self._cells)

    def __repr__(self) -> str:
        return f"Sheet(name={self.name!r}, cells={len(self._cells)})"
