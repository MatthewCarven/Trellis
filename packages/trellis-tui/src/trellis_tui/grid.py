"""SheetGrid — the DataTable-backed grid view (design.md Part 5 #4).

The view half of the one-repaint-path contract:

- **Window.** The grid materializes a rectangular window anchored at A1
  into Textual's ``DataTable``: rows × cols = ``used_range()`` ∪ the
  minimum size ∪ the cursor's high-water reach. Grid coordinates ARE
  engine addresses (zero-indexed ``(row, col)``) — no offset bookkeeping.
- **Grow on demand.** Arrowing toward an edge extends the window (rows
  in place, columns with an empty default) before the cursor hits the
  wall, so empty space is always reachable. The reach survives rebuilds.
- **Event echo only.** The grid subscribes to ``cell:change`` /
  ``cell:recalc`` (single-cell repaint via ``update_cell_at``, no-op
  writes skipped) and ``sheet:batch`` (walk the changes, or rebuild once
  when the batch is huge or reaches outside the window). It never calls
  ``sheet.set`` and never patches itself outside the echo — writes are
  the controller's job (``editor.py``, Part 5 #5).
- **Engine reads are safe.** ``sheet[a1]`` on an empty address returns a
  transient empty ``Cell`` without creating storage (verified — reading
  the window does not bloat ``_cells`` or disturb ``used_range()``).

Window defaults (DECIDED #4) live as class attributes so subclasses can
retune them — sharp tools: ``MIN_ROWS``/``MIN_COLS`` 100×26, grow by
32 rows / 8 cols when the cursor comes within ``GROW_EDGE`` (2) of an
edge, batch rebuild threshold 256 changes.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from trellis import Sheet, to_a1

from .render import display

__all__ = ["SheetGrid", "col_letters", "values_equal"]


def col_letters(col: int) -> str:
    """Zero-indexed column -> spreadsheet letters (0 -> A, 26 -> AA).

    Derived from the public ``to_a1`` rather than re-implementing
    base-26: the letters of row 0's address, with the trailing ``1``
    stripped.
    """
    return to_a1(0, col)[:-1]


def values_equal(a: Any, b: Any) -> bool:
    """No-op detection for repaint skipping.

    Stricter than ``==``: requires identical types, so ``0 == False``
    and ``1 == 1.0`` still repaint (their *display* differs: ``0`` vs
    ``FALSE``). Identity short-circuits cover error constants.
    """
    if a is b:
        return True
    if type(a) is not type(b):
        return False
    try:
        return bool(a == b)
    except Exception:
        return False


class SheetGrid(DataTable):
    """A read-only (toward the engine) spreadsheet grid over a live Sheet."""

    # Window tuning (DECIDED #4). Class attributes by design — retune by
    # subclassing, no config system.
    MIN_ROWS = 100
    MIN_COLS = 26
    GROW_ROWS = 32
    GROW_COLS = 8
    GROW_EDGE = 2
    REBUILD_THRESHOLD = 256
    COL_WIDTH = 10

    BINDINGS = [("ctrl+home", "cursor_a1", "A1")]

    def __init__(self, sheet: Sheet, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sheet = sheet
        self.cursor_type = "cell"
        self._subs: list = []
        self._win_rows = 0
        self._win_cols = 0
        # High-water mark from grow-on-demand; survives rebuilds so a
        # rebuild can't yank the window out from under the cursor.
        self._reach_rows = 0
        self._reach_cols = 0

    # ------------------------------------------------------------- lifecycle

    def on_mount(self) -> None:
        self._rebuild()
        self._subs = [
            self.sheet.on("cell:change", self._on_engine_change),
            self.sheet.on("cell:recalc", self._on_engine_change),
            self.sheet.on("sheet:batch", self._on_engine_batch),
        ]
        self.focus()

    def on_unmount(self) -> None:
        for unsubscribe in self._subs:
            unsubscribe()
        self._subs = []

    # ------------------------------------------------------------- rendering

    def _cell_text(self, row: int, col: int) -> Text:
        """Render one engine cell. The engine is always the authority —
        repaints re-read it rather than trusting event payloads."""
        d = display(self.sheet[to_a1(row, col)].value)
        return Text(d.text, justify=d.align, style="bold red" if d.error else "")

    # ---------------------------------------------------------------- window

    def _target_window(self) -> tuple[int, int]:
        rows = max(self.MIN_ROWS, self._reach_rows)
        cols = max(self.MIN_COLS, self._reach_cols)
        bounds = self.sheet.used_range()
        if bounds is not None:
            (_, _), (max_row, max_col) = bounds
            rows = max(rows, max_row + 1)
            cols = max(cols, max_col + 1)
        return rows, cols

    def _rebuild(self) -> None:
        """Clear and rematerialize the window (cursor preserved)."""
        cursor = self.cursor_coordinate
        rows, cols = self._target_window()
        self.clear(columns=True)
        for c in range(cols):
            self.add_column(
                Text(col_letters(c), justify="center"), width=self.COL_WIDTH
            )
        for r in range(rows):
            self.add_row(
                *(self._cell_text(r, c) for c in range(cols)),
                label=Text(str(r + 1), justify="right"),
            )
        self._win_rows, self._win_cols = rows, cols
        if cursor is not None and (cursor.row, cursor.column) != (0, 0):
            self.move_cursor(
                row=min(cursor.row, rows - 1), column=min(cursor.column, cols - 1)
            )

    def _grow_to(self, rows: int, cols: int) -> None:
        """Extend the window in place (no flicker, no cursor jump)."""
        if cols > self._win_cols:
            for c in range(self._win_cols, cols):
                # Beyond the window is beyond used_range(), hence empty.
                self.add_column(
                    Text(col_letters(c), justify="center"),
                    width=self.COL_WIDTH,
                    default=Text(""),
                )
            self._win_cols = cols
            self._reach_cols = max(self._reach_cols, cols)
        if rows > self._win_rows:
            for r in range(self._win_rows, rows):
                self.add_row(
                    *(self._cell_text(r, c) for c in range(self._win_cols)),
                    label=Text(str(r + 1), justify="right"),
                )
            self._win_rows = rows
            self._reach_rows = max(self._reach_rows, rows)

    def _in_window(self, address: tuple[int, int]) -> bool:
        return address[0] < self._win_rows and address[1] < self._win_cols

    # ------------------------------------------------------- engine -> view

    def _on_engine_change(self, **ev: Any) -> None:
        address = ev["address"]
        if not self._in_window(address):
            # A write landed outside the window (script/plugin): the data
            # exists, so the window must show it. used_range() already
            # covers it — a rebuild picks it up.
            self._rebuild()
            return
        if values_equal(ev["old_value"], ev["new_value"]):
            return  # no-op write: skip the repaint (3.1's old/new, cashed in)
        row, col = address
        self.update_cell_at(Coordinate(row, col), self._cell_text(row, col))

    def _on_engine_batch(self, **ev: Any) -> None:
        changes = ev["changes"]
        if len(changes) > self.REBUILD_THRESHOLD or any(
            not self._in_window(ch["address"]) for ch in changes
        ):
            self._rebuild()  # one pass beats N update calls (CSV load)
            return
        for ch in changes:
            if values_equal(ch["old_value"], ch["new_value"]):
                continue
            row, col = ch["address"]
            self.update_cell_at(Coordinate(row, col), self._cell_text(row, col))

    # ------------------------------------------------------- view-side input

    def on_data_table_cell_highlighted(
        self, event: DataTable.CellHighlighted
    ) -> None:
        # Grow BEFORE the cursor hits the wall so empty space is always
        # reachable. Don't stop the event — the app mirrors it to the bar.
        coordinate = event.coordinate
        rows, cols = self._win_rows, self._win_cols
        if coordinate.row >= rows - self.GROW_EDGE:
            rows = self._win_rows + self.GROW_ROWS
        if coordinate.column >= cols - self.GROW_EDGE:
            cols = self._win_cols + self.GROW_COLS
        if (rows, cols) != (self._win_rows, self._win_cols):
            self._grow_to(rows, cols)

    def action_cursor_a1(self) -> None:
        self.move_cursor(row=0, column=0)
