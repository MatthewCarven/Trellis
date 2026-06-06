"""TrellisApp — the application shell (design.md Part 5; complete at #6).

The app is the coordinator: the grid translates raw input into semantic
requests (it never writes the engine), the bar hosts the editor, and the
app routes between them with exactly one write path —
``editor.commit_text``. Saves go through the public ``sheet.to_csv``;
repaints arrive only via the engine's event echo.

Chrome (#6): a one-line ``StatusBar`` (file · dirty marker · last
message — messages persist until replaced; no timers, deterministic),
``Ctrl+S`` save with a modal path prompt when pathless (DECIDED #6:
a modal, not a bar takeover — the cell editor's state machine stays
single-purpose), and a ``Ctrl+Q`` dirty warning (press again to quit).
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, Static

from trellis import Sheet, Workbook, read_csv, to_a1

from . import __version__
from .editor import CellEditor, FormulaBar, commit_text, prefill_text
from .grid import SheetGrid


def _empty_workbook() -> Workbook:
    wb = Workbook()
    wb.add_sheet("Sheet1")
    return wb


class StatusBar(Static):
    """One line of app state: file · dirty marker · last message.

    ``state`` mirrors what's rendered, as plain values ``(file_label,
    dirty, message)`` — for tests and curious code. Passing
    ``message=None`` to :meth:`show` keeps the previous message.
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.state: tuple[str, bool, str] = ("", False, "")

    def show(self, path: str | None, dirty: bool, message: str | None = None) -> None:
        label = path or "(no file)"
        kept = self.state[2] if message is None else message
        self.state = (label, dirty, kept)
        line = Text()
        line.append(label, style="bold")
        if dirty:
            line.append("  ● modified", style="yellow")
        if kept:
            line.append(f"  — {kept}", style="dim")
        self.update(line)


class SaveAsScreen(ModalScreen):
    """Modal path prompt for a pathless ``Ctrl+S``. Dismisses with the
    entered path, or ``None`` on Esc/empty."""

    DEFAULT_CSS = """
    SaveAsScreen {
        align: center middle;
    }
    SaveAsScreen > Vertical {
        width: 64;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Save as — CSV path (Enter saves · Esc cancels)")
            yield Input(placeholder="sheet.csv", id="save-path")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        workbook: Workbook | None = None,
        *,
        path: str | None = None,
    ) -> None:
        super().__init__()
        self.workbook = workbook if workbook is not None else _empty_workbook()
        #: CSV path for Ctrl+S; ``None`` = pathless (modal prompt on save).
        self.path = path
        #: v1 shows the workbook's first sheet (single-sheet decision).
        self.sheet: Sheet = next(iter(self.workbook.sheets()))
        #: True once any engine write lands; cleared by a successful save.
        self.dirty = False
        self._edit_addr: tuple[int, int] | None = None
        self._edit_prefill: str | None = None  # set only for revise-edits
        self._quit_armed = False  # first dirty Ctrl+Q warns; second quits
        self._subs: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield FormulaBar()
        yield SheetGrid(self.sheet)
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.path or "new workbook"
        self.query_one(FormulaBar).show_cell(self.sheet, (0, 0))
        # Dirty tracking + the recalc note ride the same engine events as
        # the repaint loop (recalc is derived state — it never dirties).
        self._subs = [
            self.sheet.on("cell:change", self._mark_dirty),
            self.sheet.on("sheet:batch", self._mark_dirty),
            self.sheet.on("cell:recalc", self._note_recalc),
        ]
        message = None
        if self.path and not Path(self.path).exists():
            message = "new file — Ctrl+S creates it"
        self._refresh_status(message)

    def on_unmount(self) -> None:
        for unsubscribe in self._subs:
            unsubscribe()
        self._subs = []

    # --------------------------------------------------------- app state

    def _refresh_status(self, message: str | None = None) -> None:
        bars = self.query(StatusBar)  # defensive: events can outlive widgets
        if bars:
            bars.first().show(self.path, self.dirty, message)

    def _mark_dirty(self, **ev: object) -> None:
        self.dirty = True
        self._quit_armed = False  # new changes re-arm the quit warning
        self._refresh_status()

    def _note_recalc(self, **ev) -> None:
        address, trigger = ev["address"], ev["trigger"]
        note = f"recalc {to_a1(*address)}"
        if trigger is not None and tuple(trigger) != tuple(address):
            note += f" ← {to_a1(*trigger)}"
        self._refresh_status(note)

    # ------------------------------------------------------------- save

    def action_save(self) -> None:
        if self.path:
            self._save_to(self.path)
        else:
            self.push_screen(SaveAsScreen(), callback=self._save_dialog_done)

    def _save_dialog_done(self, path: str | None) -> None:
        if not path:
            return  # cancelled
        self.path = path
        self.sub_title = path
        self._save_to(path)

    def _save_to(self, path: str) -> None:
        try:
            # The TUI treats its files as spreadsheets: formulas round-trip
            # (engine default stays values-only for plain CSV export — use
            # sheet.to_csv(path) from the REPL when you want that).
            self.sheet.to_csv(path, formulas=True)
        except OSError as error:
            self._refresh_status(f"save failed: {error}")
            return
        self.dirty = False
        self._quit_armed = False
        self._refresh_status(f"saved {path}")

    # ------------------------------------------------------------- quit

    async def action_quit(self) -> None:
        if self.dirty and not self._quit_armed:
            self._quit_armed = True
            self._refresh_status("unsaved changes — Ctrl+S to save, Ctrl+Q again to quit")
            return
        self.exit()

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


# ----------------------------------------------------------------- entry


def build_app(args: list[str]) -> TrellisApp | None:
    """Build the app from CLI args; ``None`` means already handled
    (``--version``). A path that doesn't exist yet opens an empty
    workbook with the path remembered — ``Ctrl+S`` creates the file."""
    if "--version" in args:
        print(f"trellis-tui {__version__}")
        return None
    path = args[0] if args else None
    workbook = None
    if path and Path(path).exists():
        # formulas=True mirrors save: =-cells load live, so a file the TUI
        # wrote reopens as the same spreadsheet (Matthew's first-run find).
        workbook = read_csv(path, formulas=True)
    return TrellisApp(workbook, path=path)


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point: ``trellis [file.csv]``."""
    app = build_app(sys.argv[1:] if argv is None else argv)
    if app is not None:
        app.run()
    return 0
