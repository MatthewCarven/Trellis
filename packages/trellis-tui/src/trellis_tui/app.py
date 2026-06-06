"""TrellisApp — the application shell (design.md Part 5; editing as of #5).

The app is the coordinator: the grid translates raw input into semantic
requests (it never writes the engine), the bar hosts the editor, and the
app routes between them with exactly one write path —
``editor.commit_text``. Repaints still arrive only via the engine's
event echo. CSV save + status chrome land in #6.
"""

from __future__ import annotations

import sys

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from trellis import Sheet, Workbook, read_csv, to_a1

from . import __version__
from .editor import CellEditor, FormulaBar, commit_text, prefill_text
from .grid import SheetGrid


def _empty_workbook() -> Workbook:
    wb = Workbook()
    wb.add_sheet("Sheet1")
    return wb


class TrellisApp(App):
    """The Trellis terminal spreadsheet.

    Holds a live engine ``Workbook`` — the same object a REPL would
    drive. Single visible sheet in v1 (the workbook's first); the model
    is the engine, the grid is a render cache of it.
    """

    TITLE = "Trellis"
    CSS = """
    SheetGrid { height: 1fr; }
    """
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(
        self,
        workbook: Workbook | None = None,
        *,
        path: str | None = None,
    ) -> None:
        super().__init__()
        self.workbook = workbook if workbook is not None else _empty_workbook()
        #: CSV path for Ctrl+S (#6); ``None`` = pathless (prompt on save).
        self.path = path
        #: v1 shows the workbook's first sheet (single-sheet decision).
        self.sheet: Sheet = next(iter(self.workbook.sheets()))
        #: True once any engine write lands (cleared by save, #6).
        self.dirty = False
        self._edit_addr: tuple[int, int] | None = None
        self._edit_prefill: str | None = None  # set only for revise-edits
        self._dirty_subs: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield FormulaBar()
        yield SheetGrid(self.sheet)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.path or "new workbook"
        self.query_one(FormulaBar).show_cell(self.sheet, (0, 0))
        # Dirty tracking rides the same engine events as the repaint loop
        # (cell:recalc excluded: derived state always follows a change).
        self._dirty_subs = [
            self.sheet.on("cell:change", self._mark_dirty),
            self.sheet.on("sheet:batch", self._mark_dirty),
        ]

    def on_unmount(self) -> None:
        for unsubscribe in self._dirty_subs:
            unsubscribe()
        self._dirty_subs = []

    def _mark_dirty(self, **ev: object) -> None:
        self.dirty = True

    # ------------------------------------------------------ cursor mirror

    def on_data_table_cell_highlighted(self, event) -> None:
        """Mirror the cursor's cell into the formula bar.

        Messages can outlive widgets (a highlight posted just before
        shutdown arrives after the bar unmounts) — query defensively.
        """
        bars = self.query(FormulaBar)
        if bars and not bars.first().editing:
            bars.first().show_cell(
                self.sheet, (event.coordinate.row, event.coordinate.column)
            )

    # ------------------------------------------------------ edit lifecycle

    def on_sheet_grid_edit_request(self, message: SheetGrid.EditRequest) -> None:
        self._start_edit(message.mode, message.seed)

    def on_sheet_grid_clear_request(self, message: SheetGrid.ClearRequest) -> None:
        grid = self.query_one(SheetGrid)
        cursor = grid.cursor_coordinate
        commit_text(self.sheet, (cursor.row, cursor.column), "")  # delete

    def _start_edit(self, mode: str, seed: str = "") -> None:
        if self._edit_addr is not None:
            return
        grid = self.query_one(SheetGrid)
        cursor = grid.cursor_coordinate
        address = (cursor.row, cursor.column)
        if mode == "revise":
            prefill = prefill_text(self.sheet[to_a1(*address)])
            self._edit_prefill = prefill
        else:
            prefill = seed
            self._edit_prefill = None
        self._edit_addr = address
        self.query_one(FormulaBar).start_edit(to_a1(*address), prefill)

    def on_cell_editor_done(self, message: CellEditor.Done) -> None:
        address = self._edit_addr
        if address is None:
            return
        self._edit_addr = None
        unchanged_revise = (
            self._edit_prefill is not None and message.text == self._edit_prefill
        )
        self._edit_prefill = None

        bar = self.query_one(FormulaBar)
        bar.end_edit()
        if message.commit and not unchanged_revise:
            # The single write path. Never blocks: a broken formula
            # commits as its error value (formula preserved for F2).
            commit_text(self.sheet, address, message.text)

        grid = self.query_one(SheetGrid)
        grid.focus()
        row = max(0, address[0] + message.move[0])
        column = max(0, address[1] + message.move[1])
        grid.move_cursor(row=row, column=column)
        # Explicit refresh: covers Esc (no cursor move) and commits that
        # change the cell under a stationary cursor.
        bar.show_cell(self.sheet, (row, column))


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point: ``trellis [file.csv]``."""
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(f"trellis-tui {__version__}")
        return 0
    path = args[0] if args else None
    workbook = read_csv(path) if path else None
    TrellisApp(workbook, path=path).run()
    return 0
