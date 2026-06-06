"""TrellisApp — the application shell (bindings, file open/save, main()).

Scaffold stage (Part 5 #2): the app boots, loads a CSV if given one, shows
a placeholder summary, and quits. The real layout — ``SheetGrid`` + formula
bar + status line — lands in #4 (grid), #5 (editing), #6 (CSV/chrome).
"""

from __future__ import annotations

import sys

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from trellis import Workbook, read_csv, to_a1

from . import __version__


def _empty_workbook() -> Workbook:
    wb = Workbook()
    wb.add_sheet("Sheet1")
    return wb


class TrellisApp(App):
    """The Trellis terminal spreadsheet.

    Holds a live engine ``Workbook`` (the model — same object a REPL would
    drive) and, for now, a placeholder body proving the wiring end to end:
    engine -> textual -> console script.
    """

    TITLE = "Trellis"
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

    def compose(self) -> ComposeResult:  # TODO(Part 5 #4): SheetGrid + bar + status
        yield Header()
        yield Static(self._summary(), id="placeholder")
        yield Footer()

    def _summary(self) -> str:
        sheet = next(iter(self.workbook.sheets()))
        bounds = sheet.used_range()
        extent = "empty" if bounds is None else f"{to_a1(*bounds[0])}:{to_a1(*bounds[1])}"
        return (
            f"trellis-tui {__version__} — scaffold\n\n"
            f"loaded: {self.path or '(new workbook)'}\n"
            f"sheet: {sheet.name!r}   used range: {extent}\n\n"
            "The grid lands next (design.md Part 5 #4).  Ctrl+Q quits."
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
