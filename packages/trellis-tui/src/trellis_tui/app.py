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

Selection (Part 6 #4): the grid owns the rectangle and posts
``SelectionChanged``; the app renders the ``B2:D5 (3×4)`` readout into
the formula bar (the bar mirrors the cursor cell again on collapse) and
executes selection-wide ``ClearRequest``s as ONE ``sheet.batch()`` of
``commit_text`` deletes — still the single write path, one event echo,
one dirty mark.

Clipboard (Part 6 #5): app-owned ``Clipboard`` snapshot (formula text
or raw value per cell — objects, no text round-trip; plus the TSV
mirror for #6's OS bridge). Paste is Excel-faithful: relative refs
shift by the paste offset via the public ``trellis.shift_formula``
(``$`` pins opt out), a single-cell payload fills the whole selection,
empty source cells clear their targets, and the whole paste is ONE
``sheet.batch()``.

Cut + the OS bridge (Part 6 #6): cut is the pragmatic move — paste
relocates the cells *verbatim* (no shifting, matching Excel's cut) and
clears the not-overwritten source cells in the same batch, then the
clipboard demotes to copy mode (re-pasting re-stamps a copy). Any sheet
change while a cut is pending demotes it too — a stale snapshot must
never delete cells whose content has moved on. Copy/cut mirror the TSV
to the system clipboard (OSC 52); pastes FROM the OS arrive as the
terminal ``Paste`` event — our own TSV bouncing back routes to the
full-fidelity internal clipboard, anything else parses as external
TSV/text, every field through ``commit_text`` (the typing policy:
``=``-leading text commits as a formula verbatim, no shifting).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, Static

from trellis import Cell, Sheet, Workbook, read_csv, shift_formula, to_a1

from . import __version__
from .editor import CellEditor, FormulaBar, commit_text, prefill_text
from .grid import SheetGrid
from .render import display


def _empty_workbook() -> Workbook:
    wb = Workbook()
    wb.add_sheet("Sheet1")
    return wb


def _normalize_paste(text: str) -> str:
    """Line-ending-proof a pasted text for own-TSV comparison: CRLF/CR
    become LF and one trailing newline is forgiven. The mirror itself is
    always LF-joined with no trailing newline, so this only widens what
    we recognise as our own."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text[:-1] if text.endswith("\n") else text


def _tsv_field(text: str) -> str:
    """Flatten one display-text field for the TSV mirror (embedded tabs
    and newlines would break the grid shape — pragmatic lossy flatten,
    internal clipboard unaffected)."""
    return text.replace("\t", " ").replace("\n", " ").replace("\r", " ")


@dataclass(frozen=True)
class Clipboard:
    """A copied range — a snapshot, not live references (Part 6 #5).

    ``cells`` is rows×cols of per-cell payloads ``(formula, value)``:
    the formula text (with its ``=``) when the source cell had one —
    paste re-evaluates, so the snapshotted value is along only for the
    ride — else ``(None, raw value)`` at full fidelity (ints, floats,
    bools, error values carry as objects; no text round-trip).
    ``source_anchor`` is the copied rectangle's top-left; formula
    shifting keys off it. ``mode`` is ``"copy"`` (cut lands at #6).
    ``tsv`` is the OS mirror built at copy time (#6 pushes it out).
    """

    cells: tuple
    mode: str
    source_anchor: tuple[int, int]
    tsv: str


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
        #: The internal cells clipboard (None until the first copy).
        #: Named around textual's own App.clipboard property (the OS
        #: text mirror, which #6 feeds via copy_to_clipboard). Public —
        #: the same object a REPL poking at the app would want to see.
        self.sheet_clipboard: Clipboard | None = None

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
        clip = self.sheet_clipboard
        if clip is not None and clip.mode == "cut":
            # Any engine change while a cut is pending demotes it to a
            # copy: a stale snapshot must never delete source cells
            # whose content has changed since. (A cut-paste demotes
            # itself through here at its own batch exit — its writes
            # and source-deletes are already inside the batch, so the
            # move semantics are untouched.)
            self.sheet_clipboard = replace(clip, mode="copy")
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
        if not bars or bars.first().editing:
            return
        grids = self.query(SheetGrid)
        if grids and grids.first().selection_range is not None:
            return  # SelectionChanged drives the bar while a selection is live
        bars.first().show_cell(
            self.sheet, (event.coordinate.row, event.coordinate.column)
        )

    # --------------------------------------------------------- selection

    def on_sheet_grid_selection_changed(
        self, message: SheetGrid.SelectionChanged
    ) -> None:
        """Render the selection readout (``B2:D5 (3×4)``) into the bar,
        or hand the bar back to the cursor mirror on collapse."""
        bars = self.query(FormulaBar)
        if not bars or bars.first().editing:
            return
        grid = self.query_one(SheetGrid)
        cursor = grid.cursor_coordinate
        rect = message.rect
        if rect is None or rect[0] == rect[1]:
            # No selection (or a trivial 1×1): mirror the cell, Part 5 style.
            bars.first().show_cell(self.sheet, (cursor.row, cursor.column))
            return
        (r0, c0), (r1, c1) = rect
        readout = (
            f"{to_a1(r0, c0)}:{to_a1(r1, c1)}"
            f" ({r1 - r0 + 1}×{c1 - c0 + 1})"
        )
        bars.first().show_range(to_a1(cursor.row, cursor.column), readout)

    # ---------------------------------------------------------- clipboard

    def _snapshot(self, rect, mode: str) -> Clipboard:
        """Snapshot a rectangle: formula text or raw value per cell,
        plus the TSV mirror (display text) for the OS bridge."""
        (r0, c0), (r1, c1) = rect
        rows = []
        tsv_rows = []
        for row in range(r0, r1 + 1):
            payload_row = []
            tsv_row = []
            for col in range(c0, c1 + 1):
                cell = self.sheet[to_a1(row, col)]
                payload_row.append((cell.formula, cell.value))
                tsv_row.append(_tsv_field(display(cell.value).text))
            rows.append(tuple(payload_row))
            tsv_rows.append("\t".join(tsv_row))
        return Clipboard(
            cells=tuple(rows),
            mode=mode,
            source_anchor=(r0, c0),
            tsv="\n".join(tsv_rows),
        )

    @staticmethod
    def _rect_label(rect) -> str:
        (r0, c0), (r1, c1) = rect
        if (r0, c0) == (r1, c1):
            return to_a1(r0, c0)
        return f"{to_a1(r0, c0)}:{to_a1(r1, c1)}"

    def on_sheet_grid_copy_request(self, message: SheetGrid.CopyRequest) -> None:
        clip = self._snapshot(message.rect, "copy")
        self.sheet_clipboard = clip
        self.copy_to_clipboard(clip.tsv)  # OS mirror out (OSC 52)
        self._refresh_status(f"copied {self._rect_label(message.rect)}")

    def on_sheet_grid_cut_request(self, message: SheetGrid.CutRequest) -> None:
        clip = self._snapshot(message.rect, "cut")
        self.sheet_clipboard = clip
        self.copy_to_clipboard(clip.tsv)
        self._refresh_status(
            f"cut {self._rect_label(message.rect)} — paste moves it"
        )

    def on_sheet_grid_cancel_request(
        self, message: SheetGrid.CancelRequest
    ) -> None:
        """Esc cancels a pending cut (the content stays pasteable as a
        copy — friendlier than dropping it; deviation noted)."""
        clip = self.sheet_clipboard
        if clip is not None and clip.mode == "cut":
            self.sheet_clipboard = replace(clip, mode="copy")
            self._refresh_status("cut cancelled — clipboard keeps a copy")

    def on_sheet_grid_paste_request(self, message: SheetGrid.PasteRequest) -> None:
        self._paste_internal(message.rect)

    def _paste_internal(self, rect) -> None:
        """Paste the internal clipboard into the target rect, ONE batch.

        Copy mode: a 1×1 payload fills the whole target (Excel's
        fill-on-paste), each write shifted by that target's offset from
        the source cell; a block payload anchors at the target's
        top-left and shifts uniformly by the paste offset. Cut mode:
        verbatim block paste + the not-overwritten source cells cleared
        in the same batch, then the clipboard demotes to copy. Window
        growth for an out-of-window paste rides the batch echo's
        rebuild-to-cover.
        """
        clip = self.sheet_clipboard
        if clip is None:
            return
        (t0r, t0c), (t1r, t1c) = rect
        src = clip.cells
        sr, sc = clip.source_anchor
        moving = clip.mode == "cut"
        with self.sheet.batch():
            if not moving and len(src) == 1 and len(src[0]) == 1:
                formula, value = src[0][0]
                for row in range(t0r, t1r + 1):
                    for col in range(t0c, t1c + 1):
                        self._paste_cell(
                            (row, col), formula, value, row - sr, col - sc
                        )
                extent = ((t0r, t0c), (t1r, t1c))
            else:
                # Block paste. A move pastes verbatim (dr=dc=0 is
                # shift_formula's byte-for-byte identity); a copy
                # shifts by the paste offset.
                dr, dc = (0, 0) if moving else (t0r - sr, t0c - sc)
                written = set()
                for r_off, payload_row in enumerate(src):
                    for c_off, (formula, value) in enumerate(payload_row):
                        target = (t0r + r_off, t0c + c_off)
                        self._paste_cell(target, formula, value, dr, dc)
                        written.add(target)
                if moving:
                    for row in range(sr, sr + len(src)):
                        for col in range(sc, sc + len(src[0])):
                            if (row, col) not in written:
                                self.sheet.delete((row, col))
                extent = (
                    (t0r, t0c),
                    (t0r + len(src) - 1, t0c + len(src[0]) - 1),
                )
        if moving:
            # Re-pasting after a move re-stamps a copy (friendlier than
            # Excel's one-shot cut; deviation noted in design.md). The
            # batch exit already demoted via _mark_dirty; this also
            # covers a move of nothing-into-nothing (empty batch).
            clip = self.sheet_clipboard
            if clip is not None and clip.mode == "cut":
                self.sheet_clipboard = replace(clip, mode="copy")
            source_rect = ((sr, sc), (sr + len(src) - 1, sc + len(src[0]) - 1))
            self._refresh_status(
                f"moved {self._rect_label(source_rect)}"
                f" → {self._rect_label(extent)}"
            )
        else:
            self._refresh_status(f"pasted {self._rect_label(extent)}")

    def _paste_cell(
        self, address: tuple[int, int], formula, value, dr: int, dc: int
    ) -> None:
        """Write one pasted cell. Formulas shift (off-edge refs become
        ``#REF!`` literals — errors-are-values, the cell still commits);
        raw values write verbatim; empty source cells clear the target."""
        if formula is not None:
            self.sheet.set(address, shift_formula(formula, dr, dc))
        elif value is None:
            self.sheet.delete(address)
        elif isinstance(value, str) and value.startswith("="):
            # A literal "="-string VALUE (no formula). sheet.set's sugar
            # would promote it to a formula — a prebuilt Cell is the
            # engine's sanctioned verbatim path ("stored as-is").
            self.sheet.set(address, Cell(value=value))
        else:
            self.sheet.set(address, value)

    def on_paste(self, event: events.Paste) -> None:
        """The terminal Paste event — how Ctrl+V actually arrives in
        most terminals (it rarely reaches the app as a key), and how
        text pasted from other apps comes in.

        Our own TSV bouncing off the OS routes to the full-fidelity
        internal clipboard (formulas shift, objects survive); anything
        else parses as external TSV/text. While editing, the Input's
        own paste handling consumes the event before it bubbles here.
        """
        bars = self.query(FormulaBar)
        if bars and bars.first().editing:
            return  # belt-and-suspenders: Input.stop()s its paste anyway
        grids = self.query(SheetGrid)
        if not grids:
            return
        event.stop()
        grid = grids.first()
        rect = grid.selection_range or grid.cursor_rect()
        clip = self.sheet_clipboard
        if clip is not None and _normalize_paste(event.text) == clip.tsv:
            # Line endings get rewritten between us and the OS (Windows
            # clipboards speak CRLF; some paths append a trailing
            # newline) — normalize before comparing, or a multi-row
            # bounce of our own TSV silently loses its formulas to the
            # external path (field-tested, S35).
            self._paste_internal(rect)
        else:
            self._paste_external(event.text, rect)

    def _paste_external(self, text: str, rect) -> None:
        """Paste external TSV/text at the target's top-left, ONE batch.

        Every field goes through ``commit_text`` — the typing policy:
        ``=``-leading text commits as a formula verbatim (no shifting:
        external text has no source anchor), values infer like typed
        input, empty fields clear their targets.
        """
        lines = text.splitlines()
        if not lines:
            return
        (t0r, t0c), _ = rect
        max_cols = 1
        with self.sheet.batch():
            for r_off, line in enumerate(lines):
                fields = line.split("\t")
                max_cols = max(max_cols, len(fields))
                for c_off, field in enumerate(fields):
                    commit_text(self.sheet, (t0r + r_off, t0c + c_off), field)
        extent = ((t0r, t0c), (t0r + len(lines) - 1, t0c + max_cols - 1))
        self._refresh_status(f"pasted {self._rect_label(extent)}")

    # ------------------------------------------------------ edit lifecycle

    def on_sheet_grid_edit_request(self, message: SheetGrid.EditRequest) -> None:
        self._start_edit(message.mode, message.seed)

    def on_sheet_grid_clear_request(self, message: SheetGrid.ClearRequest) -> None:
        if message.rect is not None:
            # Delete with a live selection: every cell in the rectangle,
            # in ONE batch — one event echo, one recalc pass, one dirty
            # mark. (An all-empty rectangle emits nothing: the engine
            # skips empty batches, so deleting nothing dirties nothing.)
            (r0, c0), (r1, c1) = message.rect
            with self.sheet.batch():
                for row in range(r0, r1 + 1):
                    for col in range(c0, c1 + 1):
                        commit_text(self.sheet, (row, col), "")
            return
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
