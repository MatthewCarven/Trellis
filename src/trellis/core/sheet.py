"""Sheet — a sparse 2D collection of Cells, addressed by (row, col) or A1.

The store is a plain dict keyed by ``(row, col)``. Absent addresses are *not*
stored as empty cells — reads return a fresh empty ``Cell`` without persisting
it, so iterating a sheet only walks cells that have actually been written.

Sheets are :class:`~trellis.core.events.Emitter` s. Every mutation that goes
through the public API emits ``"cell:change"``. The payload is locked (see
Part 3.1): ``sheet`` (this Sheet), ``address`` (a zero-indexed ``(row, col)``
tuple), ``old_value``/``new_value``, ``old_formula``/``new_formula``, and the
``old``/``new`` :class:`Cell` objects themselves. Convert the address to A1
with ``trellis.core.address.to_a1(*address)`` at the human-facing edge.
Delete of an existing cell also emits, with the ``new`` cell empty and
``new_value``/``new_formula`` set to ``None``. Delete of an absent address is
silent.

Range support: ``sheet['A1:B5']`` returns a :class:`~trellis.core.range.Range`
view. Assignment broadcasts (``sheet['A1:B5'] = 0`` fills, ``sheet['A1:A5'] =
[1,2,3,4,5]`` spreads). ``del sheet['A1:B5']`` clears every cell in the range.

There is also a private ``_set_value(addr, value)`` used by the recalc engine
to write computed results without firing another ``cell:change`` (which would
re-trigger recalc into an infinite loop). It mutates the existing cell's
``value`` in place, preserving ``formula`` and ``meta``, then emits
``"cell:recalc"`` — a separate event that recalc subscribers ignore and that
UI handlers wanting "any value change" can listen to alongside ``cell:change``.
Its payload mirrors ``cell:change`` and adds ``trigger``: the ``(row, col)`` of
the originating user change that kicked off the recalc cascade (``None`` for an
explicit/standalone recompute).

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
    sheet.on("cell:recalc", handler) -> Subscription   # post-recalc updates
    sheet.batch()           -> context manager (buffer writes, one event)
    sheet.used_range()      -> ((minr,minc),(maxr,maxc)) | None  (non-empty extent)
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
    >>> _ = s.on("cell:change", lambda **ev: changes.append(ev["address"]))
    >>> s["A1"] = 5
    >>> s["B2"] = "=A1*2"
    >>> changes
    [(0, 0), (1, 1)]
    >>> s["A3:C3"] = [10, 20, 30]    # range broadcast
    >>> [c.value for c in s["A3:C3"]]
    [10, 20, 30]
    """

    def __init__(self, name: str = "Sheet1"):
        self.name = name
        self._cells: dict[tuple[int, int], Cell] = {}
        self.meta: dict[str, Any] = {}  # plugin scratch space; core never writes here
        # Batch state (see Sheet.batch). _batch_depth > 0 means writes are
        # buffered into _batch_changes and the per-cell cell:change is
        # suppressed until the outermost batch exits.
        self._batch_depth = 0
        self._batch_changes: list[dict] = []

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
        self._emit_or_buffer_change(key, old, new)

    def delete(self, addr: Address) -> None:
        """Remove the cell at ``addr`` if present.

        Emits ``"cell:change"`` with ``new`` set to an empty cell — only if a
        cell was actually present. Deleting an absent address is silent.
        """
        key = _coerce(addr)
        old = self._cells.pop(key, None)
        if old is not None:
            self._emit_or_buffer_change(key, old, Cell())

    # --- change dispatch / batching --------------------------------------

    def _emit_or_buffer_change(self, key: tuple[int, int], old: Cell, new: Cell) -> None:
        """Emit ``cell:change`` for one write, or buffer it inside a batch.

        Builds the locked Part 3.1 payload (``sheet``, ``address``,
        ``old_value``/``new_value``, ``old_formula``/``new_formula``,
        ``old``/``new``). Outside a batch it emits immediately. Inside a
        batch (``_batch_depth > 0``) it appends to ``_batch_changes`` and
        stays silent; the consolidated ``sheet:batch`` fires when the
        outermost batch exits.
        """
        change = {
            "address": key,
            "old_value": old.value,
            "new_value": new.value,
            "old_formula": old.formula,
            "new_formula": new.formula,
            "old": old,
            "new": new,
        }
        if self._batch_depth > 0:
            self._batch_changes.append(change)
        else:
            self.emit("cell:change", sheet=self, **change)

    def batch(self) -> "_BatchContext":
        """Group many writes into one event and one deferred recalc.

        Use as a context manager::

            with sheet.batch():
                sheet["A1"] = 1
                sheet["A2"] = 2

        While the block is open, per-cell ``cell:change`` events are
        suppressed (the writes still land in the cell store immediately).
        When the *outermost* batch exits cleanly, the sheet emits one
        ``"sheet:batch"`` event carrying ``sheet`` and ``changes`` — a list
        of per-cell change dicts in write order, each shaped like a
        ``cell:change`` payload minus ``sheet``.

        The recalc engine listens for ``sheet:batch`` and replays each
        change through its normal per-cell path, so formulas recompute when
        the batch closes rather than on every intermediate write.

        Semantics:

        * **Nested batches flatten.** Only the outermost ``__exit__`` emits
          and triggers recalc; inner blocks just join the outer batch.
        * **Exceptions propagate, no rollback.** If the block raises, cells
          already written stay written, the buffered ``sheet:batch`` event
          is NOT emitted, and the exception propagates. Build transactional
          behaviour as a plugin if you need it.
        """
        return _BatchContext(self)

    # --- non-emitting write path (recalc engine use) ---------------------

    def _set_value(
        self, addr: Address, value: Any, *, trigger: tuple[int, int] | None = None
    ) -> None:
        """Update ``value`` in place at ``addr``, preserving formula and meta.

        Used by the recalc engine to write computed results. Emits
        ``"cell:recalc"`` (NOT ``"cell:change"``) so the engine doesn't
        re-trigger itself in an infinite loop. The cell's identity is
        preserved — handlers that hold a reference to the cell will see the
        new ``value`` directly.

        No-op if no cell exists at ``addr``. The engine only writes back to
        cells that were created via :meth:`set`, so this guard is defensive.

        Event payload mirrors ``cell:change``: ``addr``, ``old`` (a snapshot
        Cell carrying the pre-write value/formula/meta — separate instance,
        safe to read), ``new`` (the live mutated Cell). Subscribers can attach
        the same handler to both events if they want a unified "any change"
        view.
        """
        key = _coerce(addr)
        cell = self._cells.get(key)
        if cell is None:
            return
        # Snapshot the previous state so handlers can compare old vs new
        # values. The snapshot is a separate Cell instance — mutating ``cell``
        # below won't change ``old``.
        old = Cell(value=cell.value, formula=cell.formula)
        old.meta = dict(cell.meta)
        cell.value = value
        self.emit(
            "cell:recalc",
            sheet=self,
            address=key,
            old_value=old.value,
            new_value=cell.value,
            old_formula=old.formula,
            new_formula=cell.formula,
            old=old,
            new=cell,
            trigger=trigger,
        )

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

    # --- file I/O --------------------------------------------------------

    def to_csv(self, path, *, encoding: str = "utf-8", dialect: str = "excel") -> None:
        """Write this sheet to a CSV file.

        Convenience wrapper for :func:`trellis.io.csv.write_csv`. Each
        cell's ``value`` is written (formulas emit their computed value,
        matching Excel's CSV export). The sheet's bounding rectangle is
        determined by the maximum populated row and column.

        Lazy-imports :mod:`trellis.io.csv` so the core ``Sheet`` class
        does not depend on the io subpackage at import time.
        """
        from ..io.csv import write_csv
        write_csv(self, path, encoding=encoding, dialect=dialect)

    # --- introspection ---------------------------------------------------

    def used_range(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        """Bounding rectangle of non-empty cells, or ``None`` if there are none.

        Returns ``((min_row, min_col), (max_row, max_col))`` — both corners
        inclusive, zero-indexed — spanning every cell that is not empty (see
        :meth:`~trellis.core.cell.Cell.is_empty`). A cell counts if it has a
        value (including the empty string ``""``), a formula (even one whose
        current value is ``None``), or non-empty ``meta``. A cell explicitly
        set to ``None`` (which stores an empty cell) and absent/deleted cells
        do not count.

        Returns ``None`` when nothing qualifies — matching the "no content is
        a legit state" convention CSV export already uses. This is the method
        a renderer calls every frame to ask "what extent must I walk?".
        """
        keys = [k for k, cell in self._cells.items() if not cell.is_empty()]
        if not keys:
            return None
        rows = [r for (r, _c) in keys]
        cols = [c for (_r, c) in keys]
        return (min(rows), min(cols)), (max(rows), max(cols))

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


class _BatchContext:
    """Context manager returned by :meth:`Sheet.batch`. See that method."""

    __slots__ = ("_sheet",)

    def __init__(self, sheet: Sheet):
        self._sheet = sheet

    def __enter__(self) -> "_BatchContext":
        self._sheet._batch_depth += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        sheet = self._sheet
        sheet._batch_depth -= 1
        if sheet._batch_depth == 0:
            changes = sheet._batch_changes
            sheet._batch_changes = []
            if exc_type is None and changes:
                sheet.emit("sheet:batch", sheet=sheet, changes=changes)
        return False  # never suppress exceptions
