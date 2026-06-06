"""SheetGrid — the DataTable-backed grid view (design.md Part 5 #4, Part 6 #4).

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
- **Selection is view state** (Part 6 #4): ``(anchor, cursor)`` — the
  anchor pins where extension started; the cursor IS the DataTable
  cursor. Shift+arrows and shift+click extend, Ctrl+A selects
  ``used_range()``, Esc or any plain cursor move collapses. Painting is
  a delta-restyle of the cells entering/leaving the rectangle — the
  tint *composes* with display styling (error red survives selection) —
  and deltas bigger than ``REBUILD_THRESHOLD`` rebuild instead (reuse,
  don't invent). The grid still never writes the engine: Delete posts
  the selection rectangle with the ``ClearRequest`` and the app does
  the (one-batch) clearing.
- **Engine reads are safe.** ``sheet[a1]`` on an empty address returns a
  transient empty ``Cell`` without creating storage (verified — reading
  the window does not bloat ``_cells`` or disturb ``used_range()``).

Window defaults (DECIDED #4) live as class attributes so subclasses can
retune them — sharp tools: ``MIN_ROWS``/``MIN_COLS`` 100×26, grow by
32 rows / 8 cols when the cursor comes within ``GROW_EDGE`` (2) of an
edge, batch rebuild threshold 256 changes. ``SELECTION_STYLE`` (the
selection tint) follows the same pattern: retune by subclassing.
"""

from __future__ import annotations

from typing import Any, Iterable

from rich.text import Text
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from trellis import Sheet, to_a1

from .render import display

__all__ = ["Rect", "SheetGrid", "col_letters", "values_equal"]

#: A normalised selection rectangle: ``((top, left), (bottom, right))``,
#: both corners inclusive, in engine coordinates.
Rect = tuple[tuple[int, int], tuple[int, int]]


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


# ------------------------------------------------------- rectangle algebra
#
# Selection repaints restyle only the cells entering/leaving the rectangle.
# These helpers keep that delta enumeration O(delta): the symmetric
# difference of two rects is decomposed into strips rather than
# materialized cell-by-cell over the (possibly huge) overlap.


def _rect_area(rect) -> int:
    if rect is None:
        return 0
    (r0, c0), (r1, c1) = rect
    return (r1 - r0 + 1) * (c1 - c0 + 1)


def _intersect(a, b):
    """Intersection of two rects, or ``None`` when disjoint (or either is)."""
    if a is None or b is None:
        return None
    (ar0, ac0), (ar1, ac1) = a
    (br0, bc0), (br1, bc1) = b
    r0, c0 = max(ar0, br0), max(ac0, bc0)
    r1, c1 = min(ar1, br1), min(ac1, bc1)
    if r0 > r1 or c0 > c1:
        return None
    return ((r0, c0), (r1, c1))


def _rect_minus(rect, hole) -> list:
    """Decompose ``rect − hole`` into disjoint rects.

    ``hole`` must be ``rect``'s intersection with something (i.e. fully
    inside ``rect``) or ``None``. At most four strips come back.
    """
    if rect is None:
        return []
    if hole is None:
        return [rect]
    (r0, c0), (r1, c1) = rect
    (hr0, hc0), (hr1, hc1) = hole
    parts = []
    if hr0 > r0:
        parts.append(((r0, c0), (hr0 - 1, c1)))  # strip above
    if hr1 < r1:
        parts.append(((hr1 + 1, c0), (r1, c1)))  # strip below
    if hc0 > c0:
        parts.append(((hr0, c0), (hr1, hc0 - 1)))  # strip left
    if hc1 < c1:
        parts.append(((hr0, hc1 + 1), (hr1, c1)))  # strip right
    return parts


def _iter_cells(rects: Iterable) -> Iterable[tuple[int, int]]:
    for (r0, c0), (r1, c1) in rects:
        for row in range(r0, r1 + 1):
            for col in range(c0, c1 + 1):
                yield (row, col)


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
    #: Rich style layered onto cells inside the selection rectangle. It
    #: must compose with content styling (error red stays readable).
    SELECTION_STYLE = "on grey37"

    BINDINGS = [
        Binding("ctrl+home", "cursor_a1", "A1", show=False),
        Binding("f2", "request_revise", "Edit"),
        Binding("enter", "request_revise", "Edit", show=False),  # nav-Enter = revise (DECIDED #5); overrides DataTable's select binding
        Binding("delete", "request_clear", "Clear"),
        Binding("backspace", "request_replace_empty", "Clear+edit", show=False),
        # Selection (Part 6 #4). DataTable binds none of these.
        Binding("shift+up", "extend(-1, 0)", "Extend", show=False),
        Binding("shift+down", "extend(1, 0)", "Extend", show=False),
        Binding("shift+left", "extend(0, -1)", "Extend", show=False),
        Binding("shift+right", "extend(0, 1)", "Extend", show=False),
        Binding("ctrl+a", "select_all", "Select all", show=False),
        Binding("escape", "collapse_selection", "Deselect", show=False),
        # Clipboard (Part 6 #5). Bound on the grid, not the app: while
        # the CellEditor has focus, Input's own ctrl+c/v handle text
        # editing; the app's default ctrl+c (help_quit) is non-priority
        # so the focused grid wins.
        Binding("ctrl+c", "request_copy", "Copy", show=False),
        Binding("ctrl+v", "request_paste", "Paste", show=False),
    ]

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
        # Selection state (Part 6 #4). The cursor half lives in
        # DataTable's cursor_coordinate; only the anchor is ours. The
        # counters classify queued CellHighlighted messages: cursor
        # moves we caused (extension / rebuild-restore) must not
        # collapse the selection the way a plain user move does.
        self._sel_anchor: tuple[int, int] | None = None
        self._extend_moves = 0
        self._restore_moves = 0
        self._painted = None  # the rect currently tinted in the table

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

    # ------------------------------------------------------------- selection

    class SelectionChanged(Message):
        """The selection rectangle changed. ``rect`` is normalised
        ``((top, left), (bottom, right))`` or ``None`` (collapsed)."""

        def __init__(self, rect) -> None:
            self.rect = rect
            super().__init__()

    @property
    def selection(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        """``(anchor, cursor)`` as engine coordinates, or ``None``."""
        if self._sel_anchor is None:
            return None
        cursor = self.cursor_coordinate
        return (self._sel_anchor, (cursor.row, cursor.column))

    @property
    def selection_range(self) -> Rect | None:
        """The normalised selection rectangle, or ``None``."""
        sel = self.selection
        if sel is None:
            return None
        (ar, ac), (cr, cc) = sel
        return ((min(ar, cr), min(ac, cc)), (max(ar, cr), max(ac, cc)))

    def action_extend(self, rows: int, cols: int) -> None:
        """Shift+arrow: move the cursor with the anchor pinned.

        The move rides the normal cursor machinery, so grow-on-demand
        still applies at the window edges.
        """
        cursor = self.cursor_coordinate
        row = min(max(cursor.row + rows, 0), self.row_count - 1)
        col = min(max(cursor.column + cols, 0), len(self.columns) - 1)
        self._extend_cursor_to(row, col)

    def _extend_cursor_to(self, row: int, col: int) -> None:
        cursor = self.cursor_coordinate
        if (row, col) == (cursor.row, cursor.column):
            return  # at the wall: no move, no event, no counter leak
        if self._sel_anchor is None:
            self._sel_anchor = (cursor.row, cursor.column)
        self._extend_moves += 1
        self.move_cursor(row=row, column=col)

    def action_select_all(self) -> None:
        """Ctrl+A: select ``used_range()`` (no-op on an empty sheet)."""
        bounds = self.sheet.used_range()
        if bounds is None:
            return
        (r0, c0), (r1, c1) = bounds
        self._sel_anchor = (r0, c0)
        cursor = self.cursor_coordinate
        if (cursor.row, cursor.column) == (r1, c1):
            # Cursor already on the far corner (Ctrl+A twice): no cursor
            # move will fire, so repaint and announce here.
            self._repaint_selection()
            self.post_message(self.SelectionChanged(self.selection_range))
        else:
            self._extend_moves += 1
            self.move_cursor(row=r1, column=c1)

    def action_collapse_selection(self) -> None:
        """Esc: collapse the selection (the cursor stays put)."""
        if self._sel_anchor is None:
            return
        self._sel_anchor = None
        self._repaint_selection()
        self.post_message(self.SelectionChanged(None))

    async def _on_click(self, event) -> None:
        # Shift+click extends the selection to the clicked cell (resolved
        # open question: Click DOES expose modifiers in textual 8.x).
        # Pin the anchor BEFORE DataTable moves the cursor, so the move
        # arrives flagged as an extension. Plain clicks fall through and
        # collapse via the plain-move path, like any other cursor move.
        if event.shift:
            meta = event.style.meta
            row, col = meta.get("row"), meta.get("column")
            if (
                row is not None
                and col is not None
                and row >= 0  # -1 = header click
                and col >= 0  # -1 = row-label click
                and not meta.get("out_of_bounds", False)
            ):
                cursor = self.cursor_coordinate
                if (row, col) != (cursor.row, cursor.column):
                    if self._sel_anchor is None:
                        self._sel_anchor = (cursor.row, cursor.column)
                    self._extend_moves += 1
        await super()._on_click(event)

    def _repaint_selection(self) -> None:
        """Restyle exactly the cells entering/leaving the rectangle.

        ``_painted`` is what the table currently shows; the live
        ``selection_range`` is the target. Deltas bigger than
        ``REBUILD_THRESHOLD`` take the rebuild path instead — the same
        threshold (and repaint authority) as engine batches.
        """
        old, new = self._painted, self.selection_range
        if old == new:
            return
        overlap = _intersect(old, new)
        delta = _rect_area(old) + _rect_area(new) - 2 * _rect_area(overlap)
        if delta > self.REBUILD_THRESHOLD:
            self._rebuild()  # renders through _cell_text: tint included
            return
        self._painted = new
        for row, col in _iter_cells(
            _rect_minus(old, overlap) + _rect_minus(new, overlap)
        ):
            if self._in_window((row, col)):
                self.update_cell_at(
                    Coordinate(row, col), self._cell_text(row, col)
                )

    # ------------------------------------------------------------- rendering

    def _cell_text(self, row: int, col: int) -> Text:
        """Render one engine cell. The engine is always the authority —
        repaints re-read it rather than trusting event payloads. The
        selection tint keys on ``_painted`` (the paint state) so partial
        repaints can never disagree with what the table shows."""
        d = display(self.sheet[to_a1(row, col)].value)
        style = "bold red" if d.error else ""
        rect = self._painted
        if rect is not None:
            (r0, c0), (r1, c1) = rect
            if r0 <= row <= r1 and c0 <= col <= c1:
                style = f"{style} {self.SELECTION_STYLE}".strip()
        return Text(d.text, justify=d.align, style=style)

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
        """Clear and rematerialize the window (cursor + selection preserved)."""
        cursor = self.cursor_coordinate
        # Snapshot the rect now: clear() resets the DataTable cursor to
        # (0, 0), which would skew a live selection_range mid-rebuild.
        self._painted = self.selection_range
        rows, cols = self._target_window()
        self.clear(columns=True)
        for c in range(cols):
            self.add_column(
                Text(col_letters(c), justify="center"), width=self.COL_WIDTH
            )
        # The FIRST add_row after a clear posts a CellHighlighted((0, 0))
        # of its own (DataTable's "cell_now_available" hook — found
        # empirically; clear()'s cursor reset posts none, the table is
        # empty at that point). Flag it as ours before it can read as a
        # user move.
        self._restore_moves += 1
        for r in range(rows):
            self.add_row(
                *(self._cell_text(r, c) for c in range(cols)),
                label=Text(str(r + 1), justify="right"),
            )
        self._win_rows, self._win_cols = rows, cols
        if cursor is not None and (cursor.row, cursor.column) != (0, 0):
            # Restoring the cursor fires exactly one more CellHighlighted.
            # Flag it too, so a rebuild can never collapse the selection.
            self._restore_moves += 1
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
        if self._restore_moves:
            # A _rebuild restoring the cursor, not a user move: the
            # rebuild already repainted everything (selection included),
            # and the window already covers the reach — nothing to
            # collapse, nothing to grow.
            self._restore_moves -= 1
            return
        if self._extend_moves:
            # A move we caused (Shift+arrow / shift+click / Ctrl+A):
            # the selection changed shape.
            self._extend_moves -= 1
            self._repaint_selection()
            self.post_message(self.SelectionChanged(self.selection_range))
        elif self._sel_anchor is not None:
            # Any plain cursor move collapses the selection.
            self._sel_anchor = None
            self._repaint_selection()
            self.post_message(self.SelectionChanged(None))
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

    # ----------------------------------------------------- input -> intent
    #
    # The grid never writes the engine (read-only contract). It translates
    # raw input into semantic request messages; the App executes them via
    # editor.commit_text — the single write path.

    class EditRequest(Message):
        """Start an edit at the cursor. ``mode`` is "replace" or "revise"."""

        def __init__(self, mode: str, seed: str = "") -> None:
            self.mode = mode
            self.seed = seed
            super().__init__()

    class ClearRequest(Message):
        """Clear cells (Delete): the whole selection when one is live
        (``rect`` is the normalised rectangle), else the cursor's cell
        (``rect`` is ``None``)."""

        def __init__(self, rect=None) -> None:
            self.rect = rect
            super().__init__()

    def on_key(self, event) -> None:
        # Any printable character starts a replace-edit seeded with it
        # (Excel: typing overwrites). Navigation keys fall through to the
        # DataTable bindings untouched.
        if event.is_printable and event.character:
            event.stop()
            event.prevent_default()
            self.post_message(self.EditRequest("replace", event.character))

    def action_request_revise(self) -> None:
        self.post_message(self.EditRequest("revise"))

    def action_request_replace_empty(self) -> None:
        self.post_message(self.EditRequest("replace", ""))

    def action_request_clear(self) -> None:
        self.post_message(self.ClearRequest(self.selection_range))

    # Clipboard intents (Part 6 #5): the rect is always concrete — the
    # selection when one is live, else the cursor's 1×1. The app owns
    # the clipboard and the writes; the grid stays read-only.

    class CopyRequest(Message):
        """Snapshot ``rect`` to the app clipboard (Ctrl+C)."""

        def __init__(self, rect) -> None:
            self.rect = rect
            super().__init__()

    class PasteRequest(Message):
        """Paste the app clipboard into ``rect`` (Ctrl+V binding path —
        most terminals deliver Ctrl+V as a Paste *event* instead; that
        arrives at #6)."""

        def __init__(self, rect) -> None:
            self.rect = rect
            super().__init__()

    def _cursor_rect(self):
        cursor = self.cursor_coordinate
        cell = (cursor.row, cursor.column)
        return (cell, cell)

    def action_request_copy(self) -> None:
        self.post_message(
            self.CopyRequest(self.selection_range or self._cursor_rect())
        )

    def action_request_paste(self) -> None:
        self.post_message(
            self.PasteRequest(self.selection_range or self._cursor_rect())
        )
