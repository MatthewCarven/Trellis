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

Undo (Part 7 #4): the app attaches a ``trellis_undo.UndoLog`` to the
sheet on mount (public as ``app.undo_log`` and at
``sheet.meta["undo"]`` — the same log a REPL would reach for) and
detaches on unmount. Ctrl+Z / Ctrl+Y arrive as grid intents; one TUI
gesture is one step (edits singly, pastes/selection-deletes/loads as
their batch). Undo writes are engine writes: the grid repaints via the
echo, dirty marks honestly (save-point tracking DECIDED against for
v1 — depth equality lies near the history cap), and a pending cut
disarms through the same ``_mark_dirty`` hook as always.

Sheet tabs (Part 9, building): **a sheet is a file** — each tab is a
``SheetView`` holding one engine sheet, its CSV path, its dirty flag,
its grid, and its undo history (editor-buffers model; CSV is a
single-sheet format, so the workbook is the *session*, exactly as in
a REPL). ``app.sheet`` / ``app.path`` / ``app.dirty`` /
``app.undo_log`` are properties over the active view, so every
handler reads the sheet under the cursor. Dirty-marking routes by
the event payload's ``sheet``; Ctrl+S saves the active sheet only;
Ctrl+Q warns once about ALL unsaved sheets.

Fill (Part 8): Ctrl+D / Ctrl+R fill the selection from its first
row/column — or, single-lane, from the neighbor above/left (Excel's
no-selection gesture). Per-lane transfer through the same
``_paste_cell`` helper as paste (formulas shift, ``$`` pins hold,
empty sources clear their targets), all ONE batch — one echo, one
dirty mark, one undo step. No clipboard involvement: a fill never
disturbs copied cells or a pending cut's snapshot (though the cut
disarms, as on any engine change).

Keymaps (Part 10, building): grid keys live behind the TUI's first
extension point. ``app.active_keymap`` answers every key the focused
grid sees with an ``Action`` (``keymap.py`` — the textual-free
contract), and the app's shared ``_execute`` performs it. The default
is the built-in ``ExcelKeymap`` — one path, Excel is a keymap too
(DECIDED #6) — and ``--keymap NAME`` selects an entry-point-registered
alternative (``--vim`` is sugar for ``--keymap vim``). Chrome keys
(save/quit/sheet tabs) stay app bindings (DECIDED #7) but emit the
same Actions through the same executor, so a keymap's ``:w``/``:q``
verbs reach identical code. The keymap's mode rides the status bar
(``-- INSERT --``); the resting mode renders as nothing.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    ContentSwitcher,
    Footer,
    Header,
    Input,
    Label,
    Static,
    Tab,
    Tabs,
)

from trellis import Cell, Sheet, Workbook, read_csv, shift_formula, to_a1
from trellis_undo import attach as attach_undo, detach as detach_undo

from . import __version__
from . import keymap as km
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
    ``sheet`` is the source sheet (Part 9 #5): pastes are sheet-agnostic
    — offsets carry across tabs — but a cut must clear its source cells
    on the sheet they actually live on.
    """

    cells: tuple
    mode: str
    source_anchor: tuple[int, int]
    tsv: str
    sheet: Sheet | None = None


class SheetView:
    """Per-tab state (Part 9): one sheet, its file, its history.

    Plain and mutable on purpose — this is bookkeeping, not a value.
    ``grid`` is created at compose/add time; ``undo_log`` and the
    engine-event ``subs`` attach on app mount and detach on unmount.
    """

    def __init__(self, sheet: Sheet, path: str | None = None, uid: int = 0) -> None:
        self.sheet = sheet
        self.path = path
        #: Stable identity for DOM ids (``grid-{uid}`` / ``tab-{uid}``)
        #: — list positions shift when tabs close; uids never do.
        self.uid = uid
        self.dirty = False
        self.grid: SheetGrid | None = None
        self.undo_log = None
        self.subs: list = []


class StatusBar(Static):
    """One line of app state: file · dirty marker · last message.

    ``state`` mirrors what's rendered, as plain values ``(file_label,
    dirty, message)`` — for tests and curious code. Passing
    ``message=None`` to :meth:`show` keeps the previous message.
    ``mode`` (Part 10) renders as a leading ``-- MODE --`` segment and
    is mirrored at ``mode_shown``; the empty string renders nothing
    (the keymap's resting mode). Deliberately NOT in ``state`` — the
    3-tuple is load-bearing for existing tests and curious code.
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
        self.mode_shown: str = ""

    def show(
        self,
        path: str | None,
        dirty: bool,
        message: str | None = None,
        mode: str = "",
    ) -> None:
        label = path or "(no file)"
        kept = self.state[2] if message is None else message
        self.state = (label, dirty, kept)
        self.mode_shown = mode
        line = Text()
        if mode:
            line.append(f"-- {mode.upper()} --  ", style="bold yellow")
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


class RenameScreen(ModalScreen):
    """Modal sheet-rename prompt (Part 9 #4), prefilled with the current
    name. Dismisses with the new name, or ``None`` on Esc/empty."""

    DEFAULT_CSS = """
    RenameScreen {
        align: center middle;
    }
    RenameScreen > Vertical {
        width: 48;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Rename sheet (Enter renames · Esc cancels)")
            yield Input(value=self._current, id="rename-sheet")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TrellisApp(App):
    """The Trellis terminal spreadsheet.

    Holds a live engine ``Workbook`` — the same object a REPL would
    drive. One ``SheetView`` per sheet (sheet = file, Part 9); the model
    is the engine, the grids are render caches of it.
    """

    TITLE = "Trellis"
    CSS = """
    ContentSwitcher { height: 1fr; }
    SheetGrid { height: 100%; }
    """
    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("ctrl+q", "quit", "Quit"),
        # Sheet tabs (Part 9). The switch keys need priority=True:
        # DataTable is a ScrollView, which binds ctrl+pageup/pagedown
        # for horizontal paging — the focused grid would eat them first.
        # Priority also fires while editing, so the actions guard that
        # case with a status hint. Ctrl+T/Ctrl+W stay non-priority:
        # nothing shadows them in nav mode, and while editing the
        # Input's own ctrl+w (delete-word) correctly wins.
        Binding("ctrl+pagedown", "next_sheet", "Next sheet", priority=True),
        Binding("ctrl+pageup", "prev_sheet", "Prev sheet", priority=True),
        ("ctrl+t", "new_sheet", "New sheet"),
        ("ctrl+w", "close_sheet", "Close sheet"),
        # Rename: Ctrl+Shift+R, NOT Alt+R — Alt+R is an AMD/NVIDIA
        # overlay shortcut (resource usage) that the GPU driver eats
        # before it reaches the terminal (field-found, S36). Double-
        # click the tab is the mouse path.
        ("ctrl+shift+r", "rename_sheet", "Rename sheet"),
    ]

    def __init__(
        self,
        workbook: Workbook | None = None,
        *,
        path: str | None = None,
        paths: dict[str, str] | None = None,
        keymap: km.Keymap | None = None,
    ) -> None:
        super().__init__()
        self.workbook = workbook if workbook is not None else _empty_workbook()
        sheets = list(self.workbook.sheets())
        if not sheets:  # an empty Workbook still gets a sheet to stand on
            sheets = [self.workbook.add_sheet("Sheet1")]
        #: Per-sheet path map (Part 9, sheet = file). ``path`` stays the
        #: single-file sugar: it names the FIRST sheet's file.
        mapping = dict(paths or {})
        if path is not None:
            mapping.setdefault(sheets[0].name, path)
        #: One SheetView per sheet, in workbook order. The first is active.
        self._next_uid = 0
        self.views: list[SheetView] = [
            SheetView(sh, mapping.get(sh.name), uid=self._take_uid())
            for sh in sheets
        ]
        self._active_uid = self.views[0].uid
        self._close_armed = False  # first Ctrl+W on a dirty sheet warns
        self._edit_addr: tuple[int, int] | None = None
        self._edit_prefill: str | None = None  # set only for revise-edits
        self._quit_armed = False  # first dirty Ctrl+Q warns; second quits
        #: The internal cells clipboard (None until the first copy).
        #: Named around textual's own App.clipboard property (the OS
        #: text mirror, which #6 feeds via copy_to_clipboard). Public —
        #: the same object a REPL poking at the app would want to see.
        self.sheet_clipboard: Clipboard | None = None
        #: The active keymap (Part 10): the sole authority for every key
        #: the focused grid sees. Public — a REPL can swap it live.
        self.active_keymap: km.Keymap = (
            keymap if keymap is not None else km.ExcelKeymap()
        )
        #: The keymap's current mode name. ``EnterMode`` actions and the
        #: editor lifecycle move it; the status bar renders it (the
        #: keymap's ``initial_mode()`` renders as nothing).
        self.mode: str = self.active_keymap.initial_mode()

    # ------------------------------------------------- active-view facade
    #
    # Part 9: the app is multi-sheet, but every gesture acts on the sheet
    # under the cursor. These properties keep all handlers (and the REPL
    # surface) reading/writing the ACTIVE view — app.sheet is "the sheet"
    # exactly as before, it just follows the active tab now.

    def _take_uid(self) -> int:
        self._next_uid += 1
        return self._next_uid

    @property
    def active_view(self) -> SheetView:
        for view in self.views:
            if view.uid == self._active_uid:
                return view
        return self.views[0]  # unreachable unless mid-mutation

    @property
    def sheet(self) -> Sheet:
        return self.active_view.sheet

    @property
    def path(self) -> str | None:
        return self.active_view.path

    @path.setter
    def path(self, value: str | None) -> None:
        self.active_view.path = value

    @property
    def dirty(self) -> bool:
        return self.active_view.dirty

    @dirty.setter
    def dirty(self, value: bool) -> None:
        self.active_view.dirty = value

    @property
    def undo_log(self):
        return self.active_view.undo_log

    def _view_for(self, sheet) -> SheetView | None:
        for view in self.views:
            if view.sheet is sheet:
                return view
        return None

    def compose(self) -> ComposeResult:
        yield Header()
        yield FormulaBar()
        # One grid per view inside a ContentSwitcher (Part 9 #3): grid-
        # per-sheet keeps cursor/selection/window state per tab for free,
        # and every grid's engine subscriptions stay live so background
        # render caches keep themselves warm.
        with ContentSwitcher(initial=f"grid-{self.active_view.uid}"):
            for view in self.views:
                view.grid = SheetGrid(view.sheet, id=f"grid-{view.uid}")
                yield view.grid
        # The tab strip sits at the bottom, Excel-style.
        yield Tabs(
            *(Tab(v.sheet.name, id=f"tab-{v.uid}") for v in self.views)
        )
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.path or "new workbook"
        # Per-view attachment (Part 9): every sheet gets its own undo
        # history (also at ``sheet.meta["undo"]``) and its own dirty
        # tracking — attached here, after any CSV load, because opening
        # a file is not an undoable gesture (matching every editor).
        # The recalc note rides the same events (derived state — never
        # dirties); handlers route by the payload's ``sheet``.
        for view in self.views:
            self._attach_view(view)
        self._sync_chrome()
        message = None
        if self.path and not Path(self.path).exists():
            message = "new file — Ctrl+S creates it"
        self._refresh_status(message)

    def on_unmount(self) -> None:
        for view in self.views:
            self._detach_view(view)

    def _attach_view(self, view: SheetView) -> None:
        view.undo_log = attach_undo(view.sheet)
        view.subs = [
            view.sheet.on("cell:change", self._mark_dirty),
            view.sheet.on("sheet:batch", self._mark_dirty),
            view.sheet.on("cell:recalc", self._note_recalc),
        ]

    def _detach_view(self, view: SheetView) -> None:
        detach_undo(view.sheet)
        for unsubscribe in view.subs:
            unsubscribe()
        view.subs = []

    # --------------------------------------------------------- app state

    def _refresh_status(self, message: str | None = None) -> None:
        bars = self.query(StatusBar)  # defensive: events can outlive widgets
        if bars:
            bars.first().show(
                self.path, self.dirty, message, mode=self._mode_label()
            )

    def _mode_label(self) -> str:
        return "" if self.mode == self.active_keymap.initial_mode() else self.mode

    def _set_mode(self, name: str) -> None:
        """Track the keymap mode (Part 10); the status bar re-renders."""
        if name != self.mode:
            self.mode = name
            self._refresh_status(None)

    def _tab_for(self, view: SheetView) -> Tab | None:
        tabs = self.query(Tabs)
        if not tabs:
            return None
        try:
            return tabs.first().query_one(f"#tab-{view.uid}", Tab)
        except Exception:
            return None

    def _refresh_tab_label(self, view: SheetView) -> None:
        """Tab label = sheet name, with a ● while unsaved (the open
        question resolved: ``Tab.label`` is a plain settable property)."""
        tab = self._tab_for(view)
        if tab is not None:
            tab.label = (
                f"{view.sheet.name} ●" if view.dirty else view.sheet.name
            )

    def _mark_dirty(self, **ev: object) -> None:
        view = self._view_for(ev.get("sheet"))
        if view is not None and not view.dirty:
            view.dirty = True  # the changed sheet's view, not necessarily active
            self._refresh_tab_label(view)  # only on the flip — no churn
        self._quit_armed = False  # new changes re-arm the quit warning
        self._close_armed = False  # and the close warning
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
        if ev.get("sheet") is not self.sheet:
            return  # a background tab recalculating is not status news
        address, trigger = ev["address"], ev["trigger"]
        note = f"recalc {to_a1(*address)}"
        if trigger is not None and tuple(trigger) != tuple(address):
            note += f" ← {to_a1(*trigger)}"
        self._refresh_status(note)

    # ------------------------------------------------------------- save

    async def action_save(self) -> None:
        await self._execute(km.Save())

    def _save_gesture(self, prompt: bool = False) -> None:
        if self.path and not prompt:
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
        self._refresh_tab_label(self.active_view)
        self._refresh_status(f"saved {path}")

    # ------------------------------------------------------------- quit

    async def action_quit(self) -> None:
        await self._execute(km.Quit())

    async def _quit_gesture(self, force: bool = False) -> None:
        if force:
            self.exit()
            return
        unsaved = sum(1 for view in self.views if view.dirty)
        if unsaved and not self._quit_armed:
            self._quit_armed = True
            if unsaved == 1 and self.dirty:
                message = "unsaved changes — Ctrl+S to save, Ctrl+Q again to quit"
            else:
                noun = "sheet" if unsaved == 1 else "sheets"
                message = (
                    f"{unsaved} {noun} unsaved — Ctrl+S saves the active one,"
                    " Ctrl+Q again quits"
                )
            self._refresh_status(message)
            return
        self.exit()

    # ------------------------------------------------------------- tabs

    def _view_by_uid(self, uid: int) -> SheetView | None:
        for view in self.views:
            if view.uid == uid:
                return view
        return None

    def _editing(self) -> bool:
        bars = self.query(FormulaBar)
        return bool(bars) and bars.first().editing

    def _sync_chrome(self) -> None:
        """Point the chrome at the active view: title, status, and the
        formula bar (cell mirror, or the range readout if the incoming
        grid still has a live selection)."""
        view = self.active_view
        self.sub_title = view.path or view.sheet.name
        bars = self.query(FormulaBar)
        if bars and not bars.first().editing and view.grid is not None:
            cursor = view.grid.cursor_coordinate
            rect = view.grid.selection_range
            if rect is not None and rect[0] != rect[1]:
                (r0, c0), (r1, c1) = rect
                bars.first().show_range(
                    to_a1(cursor.row, cursor.column),
                    f"{to_a1(r0, c0)}:{to_a1(r1, c1)}"
                    f" ({r1 - r0 + 1}×{c1 - c0 + 1})",
                )
            else:
                bars.first().show_cell(view.sheet, (cursor.row, cursor.column))
        self._refresh_status(None)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """The single switch path — clicks, Ctrl+PgUp/PgDn, Ctrl+T and
        Ctrl+W all funnel through Tabs activation."""
        if event.tab.id is None:
            return
        view = self._view_by_uid(int(event.tab.id.removeprefix("tab-")))
        if view is None or view.grid is None:
            return
        self._active_uid = view.uid
        self._close_armed = False  # switching disarms a pending close
        switchers = self.query(ContentSwitcher)
        if switchers:
            switchers.first().current = f"grid-{view.uid}"
        self._sync_chrome()
        view.grid.focus()

    def _cycle_sheet(self, step: int) -> None:
        if self._editing():
            self._refresh_status("finish the edit first")
            return
        if len(self.views) < 2:
            return
        index = next(
            i for i, v in enumerate(self.views) if v.uid == self._active_uid
        )
        target = self.views[(index + step) % len(self.views)]
        self.query_one(Tabs).active = f"tab-{target.uid}"

    async def action_next_sheet(self) -> None:
        await self._execute(km.Sheet("next"))

    async def action_prev_sheet(self) -> None:
        await self._execute(km.Sheet("prev"))

    def action_new_sheet(self) -> None:
        """Ctrl+T: a new pathless sheet, named SheetN (first free N) —
        name a file at the first Ctrl+S."""
        if self._editing():
            self._refresh_status("finish the edit first")
            return
        n = 1
        while f"Sheet{n}" in self.workbook:
            n += 1
        sheet = self.workbook.add_sheet(f"Sheet{n}")
        view = SheetView(sheet, None, uid=self._take_uid())
        self.views.append(view)
        self._attach_view(view)
        view.grid = SheetGrid(sheet, id=f"grid-{view.uid}")
        self.query_one(ContentSwitcher).mount(view.grid)
        tabs = self.query_one(Tabs)
        tabs.add_tab(Tab(sheet.name, id=f"tab-{view.uid}"))
        tabs.active = f"tab-{view.uid}"
        self._refresh_status(f"new sheet {sheet.name} — Ctrl+S names its file")

    async def action_close_sheet(self) -> None:
        """Ctrl+W: close the active tab. Unsaved warns once; the last
        tab refuses (quit is Ctrl+Q). Closing removes the sheet from
        the session workbook — sheet = file, buffers-model honest."""
        if self._editing():
            self._refresh_status("finish the edit first")
            return
        if len(self.views) == 1:
            self._refresh_status("last sheet — Ctrl+Q quits")
            return
        view = self.active_view
        if view.dirty and not self._close_armed:
            self._close_armed = True
            self._refresh_status(
                f"{view.sheet.name} unsaved — Ctrl+S saves, Ctrl+W again closes"
            )
            return
        self._close_armed = False
        index = next(
            i for i, v in enumerate(self.views) if v.uid == view.uid
        )
        neighbor = (
            self.views[index + 1]
            if index + 1 < len(self.views)
            else self.views[index - 1]
        )
        tabs = self.query_one(Tabs)
        tabs.active = f"tab-{neighbor.uid}"  # switch away first
        self.views.remove(view)
        self._detach_view(view)
        if view.grid is not None:
            await view.grid.remove()
        await tabs.remove_tab(f"tab-{view.uid}")
        self.workbook.remove_sheet(view.sheet.name)
        self._refresh_status(f"closed {view.sheet.name}")

    def action_rename_sheet(self) -> None:
        """Ctrl+Shift+R (or double-click the tab): rename the active
        sheet. Renames the *sheet* — the file path is untouched."""
        if self._editing():
            self._refresh_status("finish the edit first")
            return
        self.push_screen(
            RenameScreen(self.sheet.name), callback=self._rename_done
        )

    def on_click(self, event: events.Click) -> None:
        """Double-click on a tab = rename (Excel's gesture). The first
        click of the pair already activated the tab, so the rename
        always targets the active sheet."""
        if event.chain != 2:
            return
        widget = getattr(event, "widget", None)
        on_tab = isinstance(widget, Tab) or any(
            isinstance(a, Tab) for a in getattr(widget, "ancestors", [])
        )
        if on_tab:
            self.action_rename_sheet()

    def _rename_done(self, name: str | None) -> None:
        if not name:
            return  # cancelled
        view = self.active_view
        old = view.sheet.name
        if name == old:
            return
        if name in self.workbook:
            self._refresh_status(f"name taken: {name}")
            return
        self.workbook.rename_sheet(old, name)
        self._refresh_tab_label(view)
        self._sync_chrome()
        self._refresh_status(f"renamed {old} → {name}")

    # ------------------------------------------- the action executor (Part 10)

    async def _execute(self, action: km.Action) -> None:
        """The shared Action executor — every gesture lands here, whether
        the active keymap answered a grid key with it or an app-chrome
        binding emitted it (DECIDED #7: same Actions, same code). The
        keymap never writes; this is where Actions become cursor moves,
        engine writes, and chrome. Targets (``rect=None``) resolve HERE,
        at execution time: queued actions run in order, so the selection
        a prior ``Move(extend=True)`` grew is the one an ``Operate``
        sees, however fast the keys came in."""
        grid = self.active_view.grid
        if isinstance(action, (km.Move, km.MoveTo)):
            if grid is None:
                return
            if isinstance(action, km.Move):
                cursor = grid.cursor_coordinate
                row, col = cursor.row + action.dr, cursor.column + action.dc
            else:
                row, col = action.row, action.col
            row = min(max(row, 0), grid.row_count - 1)
            col = min(max(col, 0), len(grid.columns) - 1)
            if action.extend:
                grid._extend_cursor_to(row, col)
            else:
                grid.move_cursor(row=row, column=col)
        elif isinstance(action, km.Select):
            if grid is not None:
                grid.select_rect(action.rect)
        elif isinstance(action, km.BeginEdit):
            mode = "revise" if action.seed is None else "replace"
            self._start_edit(mode, action.seed or "", caret=action.caret)
        elif isinstance(action, km.EnterMode):
            self._set_mode(action.name)
            if grid is not None and action.name == self.active_keymap.initial_mode():
                # The Esc contract: entering the resting mode collapses
                # the selection and cancels a pending cut.
                grid.action_collapse_selection()
        elif isinstance(action, km.Operate):
            if grid is None:
                return
            if action.op == "clear":
                # Selection-or-cursor, preserving the single-cell
                # no-batch path exactly as the ClearRequest always has.
                self._clear(action.rect or grid.selection_range)
                return
            rect = action.rect or grid.selection_range or grid.cursor_rect()
            if action.op == "copy":
                self._copy(rect)
            elif action.op == "cut":
                self._cut(rect)
            elif action.op == "paste":
                self._paste_internal(rect)
            elif action.op == "change":
                self._clear(rect)  # vim's c: clear, then a replace-edit
                self._start_edit("replace", "")
        elif isinstance(action, km.Fill):
            if grid is None:
                return
            rect = action.rect or grid.selection_range or grid.cursor_rect()
            self._fill(rect, action.axis)
        elif isinstance(action, km.Undo):
            self._undo()
        elif isinstance(action, km.Redo):
            self._redo()
        elif isinstance(action, km.Save):
            self._save_gesture(action.prompt)
        elif isinstance(action, km.Quit):
            await self._quit_gesture(action.force)
        elif isinstance(action, km.Sheet):
            self._cycle_sheet(1 if action.direction == "next" else -1)
        elif isinstance(action, km.Hint):
            if action.msg:
                self._refresh_status(action.msg)
        # Unknown Action subclasses get silence, not magic — the
        # vocabulary is closed by convention (keymap.py).

    async def on_sheet_grid_action_request(
        self, message: SheetGrid.ActionRequest
    ) -> None:
        await self._execute(message.action)

    # ------------------------------------------------------ cursor mirror

    def on_data_table_cell_highlighted(self, event) -> None:
        """Mirror the cursor's cell into the formula bar.

        Messages can outlive widgets (a highlight posted just before
        shutdown arrives after the bar unmounts) — query defensively.
        """
        grid = self.active_view.grid
        if getattr(event, "data_table", None) is not grid:
            return  # a background tab's grid rebuilding, not the user
        bars = self.query(FormulaBar)
        if not bars or bars.first().editing:
            return
        if grid is not None and grid.selection_range is not None:
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
        grid = self.active_view.grid
        if grid is None:
            return
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
            sheet=self.sheet,
        )

    @staticmethod
    def _rect_label(rect) -> str:
        (r0, c0), (r1, c1) = rect
        if (r0, c0) == (r1, c1):
            return to_a1(r0, c0)
        return f"{to_a1(r0, c0)}:{to_a1(r1, c1)}"

    def _copy(self, rect) -> None:
        clip = self._snapshot(rect, "copy")
        self.sheet_clipboard = clip
        self.copy_to_clipboard(clip.tsv)  # OS mirror out (OSC 52)
        self._refresh_status(f"copied {self._rect_label(rect)}")

    def _cut(self, rect) -> None:
        clip = self._snapshot(rect, "cut")
        self.sheet_clipboard = clip
        self.copy_to_clipboard(clip.tsv)
        self._refresh_status(f"cut {self._rect_label(rect)} — paste moves it")

    def on_sheet_grid_copy_request(self, message: SheetGrid.CopyRequest) -> None:
        self._copy(message.rect)

    def on_sheet_grid_cut_request(self, message: SheetGrid.CutRequest) -> None:
        self._cut(message.rect)

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

    # --------------------------------------------------------------- undo

    def _undo(self) -> None:
        """One step back. The restore is an engine write like any other:
        the grid repaints via the echo, dirty marks honestly."""
        count = self.undo_log.undo()
        if count is None:
            self._refresh_status("nothing to undo")
        else:
            self._refresh_status(f"undid {count} cell{'' if count == 1 else 's'}")

    def _redo(self) -> None:
        count = self.undo_log.redo()
        if count is None:
            self._refresh_status("nothing to redo")
        else:
            self._refresh_status(f"redid {count} cell{'' if count == 1 else 's'}")

    def on_sheet_grid_undo_request(self, message: SheetGrid.UndoRequest) -> None:
        self._undo()

    def on_sheet_grid_redo_request(self, message: SheetGrid.RedoRequest) -> None:
        self._redo()

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
        # Cross-tab paste (Part 9 #5): targets land on the ACTIVE sheet;
        # a cut clears its source cells on the sheet they came from. A
        # same-sheet move is one batch as always; a cross-sheet move is
        # one batch per sheet — per-sheet undo-honest (Ctrl+Z on the
        # target un-pastes, on the source un-clears).
        source_sheet = clip.sheet if clip.sheet is not None else self.sheet
        cross = moving and source_sheet is not self.sheet
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
                if moving and not cross:
                    for row in range(sr, sr + len(src)):
                        for col in range(sc, sc + len(src[0])):
                            if (row, col) not in written:
                                self.sheet.delete((row, col))
                extent = (
                    (t0r, t0c),
                    (t0r + len(src) - 1, t0c + len(src[0]) - 1),
                )
        if cross:
            # The source sheet's own batch: every source cell goes (the
            # written-set exclusion is a same-sheet overlap concern).
            with source_sheet.batch():
                for row in range(sr, sr + len(src)):
                    for col in range(sc, sc + len(src[0])):
                        source_sheet.delete((row, col))
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
        """Write one transferred cell (paste and fill both route here).
        Formulas shift (off-edge refs become
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

    # --------------------------------------------------------------- fill

    def on_sheet_grid_fill_request(self, message: SheetGrid.FillRequest) -> None:
        self._fill(message.rect, message.axis)

    def _fill(self, rect, axis: str) -> None:
        """Ctrl+D / Ctrl+R (Part 8): fill ``rect`` along ``axis``, ONE batch.

        A 2+-lane rect fills from its own first row/column (Excel: the
        source lane stays put, only the rest is written); a single-lane
        rect fills from the neighbor above/left — Excel's no-selection
        gesture — and at the sheet edge there is nothing to fill from.
        Lanes transfer independently through ``_paste_cell``: formulas
        shift by each target's offset from ITS lane's source (``$``
        pins hold, off-edge refs land as ``#REF!``), values copy at
        full fidelity, empty sources clear their targets. One batch =
        one echo, one dirty mark, one undo step; an all-empty fill
        emits nothing (delete-of-absent is silent, the engine skips
        empty batches) so it cannot dirty the sheet.
        """
        (r0, c0), (r1, c1) = rect
        down = axis == "down"
        lo, hi = (r0, r1) if down else (c0, c1)
        if hi > lo:
            src, first = lo, lo + 1  # source lane sits inside the rect
        elif lo == 0:
            self._refresh_status(
                f"nothing {'above' if down else 'left'} to fill from"
            )
            return
        else:
            src, first = lo - 1, lo  # the neighbor above/left
        lanes = range(c0, c1 + 1) if down else range(r0, r1 + 1)
        with self.sheet.batch():
            for lane in lanes:
                addr = (src, lane) if down else (lane, src)
                cell = self.sheet[to_a1(*addr)]
                for t in range(first, hi + 1):
                    target = (t, lane) if down else (lane, t)
                    dr, dc = (t - src, 0) if down else (0, t - src)
                    self._paste_cell(target, cell.formula, cell.value, dr, dc)
        extent = ((first, c0), (r1, c1)) if down else ((r0, first), (r1, c1))
        self._refresh_status(f"filled {axis} {self._rect_label(extent)}")

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
        grid = self.active_view.grid
        if grid is None:
            return
        event.stop()
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
        self._clear(message.rect)

    def _clear(self, rect) -> None:
        if rect is not None:
            # Delete with a live selection: every cell in the rectangle,
            # in ONE batch — one event echo, one recalc pass, one dirty
            # mark. (An all-empty rectangle emits nothing: the engine
            # skips empty batches, so deleting nothing dirties nothing.)
            (r0, c0), (r1, c1) = rect
            with self.sheet.batch():
                for row in range(r0, r1 + 1):
                    for col in range(c0, c1 + 1):
                        commit_text(self.sheet, (row, col), "")
            return
        grid = self.active_view.grid
        cursor = grid.cursor_coordinate
        commit_text(self.sheet, (cursor.row, cursor.column), "")  # delete

    def _start_edit(self, mode: str, seed: str = "", caret: str = "end") -> None:
        if self._edit_addr is not None:
            return
        grid = self.active_view.grid
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
        if caret == "start":
            # BeginEdit(caret="start") — vim's ``i``/``I``; the bar
            # parks the caret at the end by default (Excel's F2).
            self.query_one(CellEditor).cursor_position = 0
        self._set_mode("insert")  # the editor IS Insert (Part 10)

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
        self._set_mode(self.active_keymap.initial_mode())
        if message.commit and not unchanged_revise:
            # The single write path. Never blocks: a broken formula
            # commits as its error value (formula preserved for F2).
            commit_text(self.sheet, address, message.text)

        grid = self.active_view.grid
        grid.focus()
        row = max(0, address[0] + message.move[0])
        column = max(0, address[1] + message.move[1])
        grid.move_cursor(row=row, column=column)
        # Explicit refresh: covers Esc (no cursor move) and commits that
        # change the cell under a stationary cursor.
        bar.show_cell(self.sheet, (row, column))


# ----------------------------------------------------------------- entry


def _unique_sheet_name(taken, stem: str) -> str:
    """First free name for a CLI-opened file: the stem, then stem-2…"""
    name = stem or "Sheet"
    n = 2
    while name in taken:
        name = f"{stem or 'Sheet'}-{n}"
        n += 1
    return name


def build_app(args: list[str]) -> TrellisApp | None:
    """Build the app from CLI args; ``None`` means already handled
    (``--version``).

    ``trellis a.csv b.csv …`` opens one tab per file (Part 9 #4): each
    sheet is named for its file's stem (collisions dedupe ``stem-2``),
    loaded via ``read_csv(…, workbook=…)`` — the multi-file seam the
    engine grew in Part 3, consumed at last. A path that doesn't exist
    yet opens an empty tab with the path remembered — ``Ctrl+S``
    creates the file.

    ``--keymap NAME`` selects the key language (Part 10): the built-in
    ``excel`` (default) or any keymap registered under the
    ``trellis_tui.keymaps`` entry point. ``--vim`` is sugar for
    ``--keymap vim``. An unknown name prints what IS available."""
    if "--version" in args:
        print(f"trellis-tui {__version__}")
        return None
    keymap_name = "excel"
    files: list[str] = []
    rest = iter(args)
    for arg in rest:
        if arg == "--vim":
            keymap_name = "vim"
        elif arg == "--keymap":
            keymap_name = next(rest, None) or ""
        elif arg.startswith("--keymap="):
            keymap_name = arg.split("=", 1)[1]
        else:
            files.append(arg)
    try:
        keymap = km.load_keymap(keymap_name)
    except KeyError as error:
        print(error.args[0])
        return None
    if not files:
        return TrellisApp(None, keymap=keymap)
    workbook = Workbook()
    paths: dict[str, str] = {}
    for arg in files:
        name = _unique_sheet_name(paths, Path(arg).stem)
        if Path(arg).exists():
            # formulas=True mirrors save: =-cells load live, so a file
            # the TUI wrote reopens as the same spreadsheet.
            read_csv(arg, sheet_name=name, workbook=workbook, formulas=True)
        else:
            workbook.add_sheet(name)
        paths[name] = arg
    return TrellisApp(workbook, paths=paths, keymap=keymap)


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point: ``trellis [file.csv]``."""
    app = build_app(sys.argv[1:] if argv is None else argv)
    if app is not None:
        app.run()
    return 0
