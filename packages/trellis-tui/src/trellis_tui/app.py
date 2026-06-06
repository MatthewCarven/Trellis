"""TrellisApp — the application shell (bindings, file open/save, main()).

Stage #4: the real layout — ``SheetGrid`` (read-only toward the engine)
+ ``FormulaBar`` mirroring the cursor. Editing lands in #5, CSV save and
status chrome in #6.
"""

from __future__ import annotations

import sys

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from trellis import Sheet, Workbook, read_csv

from . import __version__
from .editor import FormulaBar
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield FormulaBar()
        yield SheetGrid(self.sheet)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.path or "new workbook"
        self.query_one(FormulaBar).show_cell(self.sheet, (0, 0))

    def on_data_table_cell_highlighted(
        self, event: DataTable.CellHighlighted
    ) -> None:
        """Mirror the cursor's cell into the formula bar.

        Messages can outlive widgets (a highlight posted just before
        shutdown arrives after the bar unmounts) — query defensively.
        """
        bars = self.query(FormulaBar)
        if bars:
            bars.first().show_cell(
                self.sheet, (event.coordinate.row, event.coordinate.column)
            )


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
