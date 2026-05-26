"""Range — a rectangular view over multiple Cells in a Sheet.

A Range is a transient view, not a stored thing. It's constructed on demand
(usually via ``sheet['A1:B5']`` or ``sheet.range('A1:B5')``) and provides
iteration, bulk assignment, and shape introspection over a rectangular block.

Empty cells inside the bounding box are surfaced as empty ``Cell()`` instances
— they are not auto-stored on read. Iteration walks the *full* bounding box,
not just stored cells, because that matches the "I'm working with this
rectangle" mental model. Filter on ``cell.is_empty()`` if you want stored only.

Public surface:

    Range(sheet, 'A1:B5')      construct a range (also via Sheet.range)
    range.start, range.end     (row, col) tuples, normalised so start <= end
    range.rows, range.cols     dimensions
    range.shape                (rows, cols)
    len(range)                 total cell count
    range.addrs()              iterator of A1 strings, row-major
    range.positions()          iterator of (row, col) tuples, row-major
    range.cells()              iterator of (A1, Cell) pairs, row-major
    range.values()             iterator of values (None for empty cells)
    iter(range)                iterator of Cell objects
    addr in range              membership test
    range.assign(value)        broadcast assign (scalar, 1D, or 2D iterable)
    range.clear()              delete every stored cell in the range

Events: every write that ``assign`` or ``clear`` performs goes through the
Sheet's normal ``set``/``delete`` path, so subscribers to ``"cell:change"``
receive one event per affected cell.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any, Union

from .address import parse as parse_addr
from .address import to_a1
from .cell import Cell

if TYPE_CHECKING:
    from .sheet import Sheet


RangeAddress = Union[str, tuple]


def _coerce_single(addr: object) -> tuple[int, int]:
    """Normalise a single-cell address to (row, col)."""
    if isinstance(addr, str):
        return parse_addr(addr)
    if isinstance(addr, tuple) and len(addr) == 2:
        return int(addr[0]), int(addr[1])
    raise TypeError(
        f"Cell address must be an 'A1' string or (row, col) tuple, got {addr!r}"
    )


class Range:
    """A rectangular view over cells in a Sheet.

    >>> from trellis import Sheet
    >>> s = Sheet()
    >>> s['A1:B3'] = 0
    >>> [c.value for c in s['A1:B3']]
    [0, 0, 0, 0, 0, 0]
    >>> s['A1:A3'] = [10, 20, 30]
    >>> [c.value for c in s['A1:A3']]
    [10, 20, 30]
    """

    __slots__ = ("sheet", "start", "end")

    def __init__(self, sheet: "Sheet", addr: RangeAddress):
        self.sheet = sheet
        self.start, self.end = self._parse(addr)

    @staticmethod
    def _parse(addr: RangeAddress) -> tuple[tuple[int, int], tuple[int, int]]:
        if isinstance(addr, str):
            if ":" not in addr:
                raise ValueError(
                    f"Range address must contain ':' (e.g. 'A1:B5'), got {addr!r}"
                )
            left, _, right = addr.partition(":")
            a = parse_addr(left)
            b = parse_addr(right)
        elif isinstance(addr, tuple) and len(addr) == 2:
            a = _coerce_single(addr[0])
            b = _coerce_single(addr[1])
        else:
            raise TypeError(
                f"Range address must be an 'A1:B5' string or (start, end) tuple, "
                f"got {addr!r}"
            )
        start = (min(a[0], b[0]), min(a[1], b[1]))
        end = (max(a[0], b[0]), max(a[1], b[1]))
        return start, end

    # --- shape ----------------------------------------------------------

    @property
    def rows(self) -> int:
        return self.end[0] - self.start[0] + 1

    @property
    def cols(self) -> int:
        return self.end[1] - self.start[1] + 1

    @property
    def shape(self) -> tuple[int, int]:
        return (self.rows, self.cols)

    def __len__(self) -> int:
        return self.rows * self.cols

    # --- iteration ------------------------------------------------------

    def positions(self) -> Iterator[tuple[int, int]]:
        """Iterate every ``(row, col)`` in the bounding box, row-major."""
        for r in range(self.start[0], self.end[0] + 1):
            for c in range(self.start[1], self.end[1] + 1):
                yield (r, c)

    def addrs(self) -> Iterator[str]:
        """Iterate every A1 address in the bounding box, row-major."""
        for r, c in self.positions():
            yield to_a1(r, c)

    def cells(self) -> Iterator[tuple[str, Cell]]:
        """Iterate ``(A1, Cell)`` pairs for every position in the bounding box.

        Unstored cells are surfaced as ``Cell()`` placeholders, *not* persisted.
        """
        store = self.sheet._cells
        for r, c in self.positions():
            yield to_a1(r, c), store.get((r, c), Cell())

    def values(self) -> Iterator[Any]:
        """Iterate values for every position (``None`` for empty cells)."""
        store = self.sheet._cells
        for r, c in self.positions():
            cell = store.get((r, c))
            yield cell.value if cell is not None else None

    def __iter__(self) -> Iterator[Cell]:
        store = self.sheet._cells
        for r, c in self.positions():
            yield store.get((r, c), Cell())

    def __contains__(self, addr: object) -> bool:
        try:
            r, c = _coerce_single(addr)
        except (TypeError, ValueError):
            return False
        return self.start[0] <= r <= self.end[0] and self.start[1] <= c <= self.end[1]

    # --- assignment -----------------------------------------------------

    def assign(self, value: Any) -> None:
        """Broadcast-assign across the range.

        Accepts:
            - **A scalar** (number, str, bool, None, or Cell instance) — written
              to every cell. Strings starting with ``=`` are detected as formulas
              by ``Sheet.set``. NOTE: broadcasting a ``Cell`` instance stores the
              *same reference* at every position; mutating one mutates all. Pass
              a 2D iterable of distinct cells if you need independent identities.
            - **A 1D iterable** when the range is one row OR one column — values
              are spread across cells in order. Length must equal ``len(self)``.
            - **A 2D iterable** (iterable of iterables) whose shape matches
              ``self.shape`` — values are spread element-wise.

        Strings, bytes, and ``Cell`` instances are always treated as scalars,
        never as iterables.

        Raises:
            ValueError: shape mismatch, empty iterable, or 1D iterable assigned
                to a non-linear range.
        """
        # Scalar path: strings, bytes, Cells, and anything that isn't iterable.
        if isinstance(value, (str, bytes, Cell)) or not isinstance(value, Iterable):
            for addr in self.addrs():
                self.sheet.set(addr, value)
            return

        materialised = list(value)
        if not materialised:
            raise ValueError("Cannot assign an empty iterable to a range")

        first = materialised[0]
        is_2d = isinstance(first, Iterable) and not isinstance(first, (str, bytes, Cell))

        if is_2d:
            rows = [list(row) for row in materialised]
            if len(rows) != self.rows:
                raise ValueError(
                    f"2D iterable has {len(rows)} rows but range has {self.rows}"
                )
            for r_idx, row in enumerate(rows):
                if len(row) != self.cols:
                    raise ValueError(
                        f"2D iterable row {r_idx} has {len(row)} cols but range has {self.cols}"
                    )
                actual_r = self.start[0] + r_idx
                for c_idx, v in enumerate(row):
                    self.sheet.set((actual_r, self.start[1] + c_idx), v)
        else:
            if self.rows != 1 and self.cols != 1:
                raise ValueError(
                    "1D iterable can only assign to a single-row or single-column "
                    f"range; this range is {self.rows}x{self.cols}"
                )
            if len(materialised) != len(self):
                raise ValueError(
                    f"1D iterable has {len(materialised)} values but range has "
                    f"{len(self)} cells"
                )
            for addr, v in zip(self.addrs(), materialised):
                self.sheet.set(addr, v)

    def clear(self) -> None:
        """Delete every cell in the range.

        Fires ``"cell:change"`` per cell that was actually stored — absent
        positions in the bounding box are silent (per ``Sheet.delete``).
        """
        for addr in self.addrs():
            self.sheet.delete(addr)

    def __repr__(self) -> str:
        a = to_a1(*self.start)
        b = to_a1(*self.end)
        return f"Range({self.sheet.name!r}, {a}:{b}, {self.rows}x{self.cols})"
