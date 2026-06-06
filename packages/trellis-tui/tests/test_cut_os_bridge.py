"""Pilot tests for cut (the pragmatic move) + the OS clipboard bridge
(Part 6 #6).

Cut-paste relocates cells verbatim (no reference shifting) and clears
the not-overwritten source cells in the same batch, then demotes to
copy mode; Esc — or any sheet change — also demotes a pending cut.
Copy/cut mirror TSV out via copy_to_clipboard (OSC 52); the terminal
``Paste`` event funnels in: our own TSV routes to the internal
clipboard, external text parses through ``commit_text`` per field.
"""

from __future__ import annotations

from textual import events

from trellis import Workbook
from trellis_tui.app import StatusBar, TrellisApp
from trellis_tui.grid import SheetGrid


def _app(populate=None) -> TrellisApp:
    wb = Workbook()
    sh = wb.add_sheet("S")
    if populate:
        populate(sh)
    return TrellisApp(wb)


def _status(app: TrellisApp) -> str:
    return app.query_one(StatusBar).state[2]


# ------------------------------------------------------------------ cut


async def test_cut_paste_moves_verbatim_and_clears_source():
    def populate(sh):
        sh["A1"] = 10
        sh["B1"] = "=A1*2"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        batches: list = []
        app.sheet.on("sheet:batch", lambda **ev: batches.append(ev))
        grid.move_cursor(row=0, column=1)  # B1
        await pilot.pause()
        await pilot.press("ctrl+x")
        assert app.sheet_clipboard.mode == "cut"
        assert _status(app) == "cut B1 — paste moves it"
        assert app.sheet["B1"].value == 20  # cut is pending, not destructive
        grid.move_cursor(row=2, column=2)  # C3
        await pilot.pause()
        await pilot.press("ctrl+v")
        assert app.sheet["C3"].formula == "=A1*2"  # VERBATIM — no shift
        assert app.sheet["C3"].value == 20
        assert app.sheet["B1"].value is None  # source cleared...
        assert len(batches) == 1  # ...in the SAME batch
        assert _status(app) == "moved B1 → C3"


async def test_cut_paste_overlap_keeps_overwritten_source():
    def populate(sh):
        sh["A1"] = 1
        sh["A2"] = 2

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+down", "ctrl+x")  # cut A1:A2
        # Collapse the selection with PLAIN moves (Esc would cancel the
        # cut!) and land on A2 — the target overlaps the source.
        await pilot.press("down", "up")
        assert grid.selection is None
        assert app.sheet_clipboard.mode == "cut"  # plain moves keep it
        await pilot.press("ctrl+v")
        assert app.sheet["A1"].value is None  # cleared (not overwritten)
        assert app.sheet["A2"].value == 1  # overwritten by the move
        assert app.sheet["A3"].value == 2


async def test_cut_demotes_to_copy_after_paste():
    app = _app(lambda sh: sh.set((0, 0), 5))
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("ctrl+x", "down", "ctrl+v")  # move A1 -> A2
        assert app.sheet_clipboard.mode == "copy"  # re-paste re-stamps
        grid.move_cursor(row=4, column=0)
        await pilot.pause()
        await pilot.press("ctrl+v")
        assert app.sheet["A5"].value == 5  # pasted again, as a copy
        assert app.sheet["A2"].value == 5  # and nothing got cleared


async def test_escape_cancels_a_pending_cut():
    app = _app(lambda sh: sh.set((0, 0), 7))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+x", "escape")
        assert app.sheet_clipboard.mode == "copy"
        assert _status(app) == "cut cancelled — clipboard keeps a copy"
        await pilot.press("down", "ctrl+v")
        assert app.sheet["A2"].value == 7
        assert app.sheet["A1"].value == 7  # source survives — it's a copy


async def test_sheet_change_demotes_a_pending_cut():
    app = _app(lambda sh: sh.set((0, 0), 7))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+x")
        app.sheet["B5"] = "edited meanwhile"
        assert app.sheet_clipboard.mode == "copy"  # stale move disarmed
        await pilot.press("down", "ctrl+v")
        assert app.sheet["A1"].value == 7  # the source was NOT deleted


# ------------------------------------------------------------ OS bridge


async def test_copy_and_cut_mirror_tsv_to_the_os_clipboard():
    def populate(sh):
        sh["A1"] = 10
        sh["B1"] = "=A1*2"

    app = _app(populate)
    async with app.run_test() as pilot:
        await pilot.press("shift+right", "ctrl+c")
        assert app.clipboard == "10\t20"  # textual's OS mirror got the TSV
        await pilot.press("ctrl+x")
        assert app.clipboard == app.sheet_clipboard.tsv


async def test_own_tsv_paste_event_routes_to_internal_clipboard():
    def populate(sh):
        sh["A1"] = 10
        sh["B1"] = "=A1*2"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=0, column=1)  # B1
        await pilot.pause()
        await pilot.press("ctrl+c")
        grid.move_cursor(row=2, column=1)  # B3
        await pilot.pause()
        app.post_message(events.Paste(app.sheet_clipboard.tsv))  # the bounce
        await pilot.pause()
        # internal path: the formula SHIFTED — an external paste of "20"
        # would have stored the number 20 with no formula.
        assert app.sheet["B3"].formula == "=A3*2"


async def test_own_tsv_bounce_survives_crlf_and_trailing_newline():
    # Windows clipboards speak CRLF and some paths append a newline —
    # the own-TSV detection must still recognise itself (S35), or a
    # multi-row bounce quietly downgrades to values-only.
    def populate(sh):
        sh["A1"] = 10
        sh["B1"] = "=A1*2"
        sh["A2"] = 3
        sh["B2"] = "=A2*2"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+right", "shift+down", "ctrl+c")  # A1:B2
        assert "\n" in app.sheet_clipboard.tsv  # multi-row: the risky case
        mangled = app.sheet_clipboard.tsv.replace("\n", "\r\n") + "\r\n"
        grid.move_cursor(row=4, column=0)  # A5
        await pilot.pause()
        await pilot.press("escape")  # collapse; paste targets the cursor
        app.post_message(events.Paste(mangled))
        await pilot.pause()
        assert app.sheet["B5"].formula == "=A5*2"  # internal path: shifted
        assert app.sheet["B6"].formula == "=A6*2"


async def test_external_tsv_paste_infers_fields_in_one_batch():
    app = _app()
    async with app.run_test() as pilot:
        batches: list = []
        app.sheet.on("sheet:batch", lambda **ev: batches.append(ev))
        app.post_message(events.Paste("1\thello\n=A1*10\t01234\n"))
        await pilot.pause()
        assert app.sheet["A1"].value == 1  # int, like typing it
        assert app.sheet["B1"].value == "hello"
        assert app.sheet["A2"].formula == "=A1*10"  # verbatim, NO shifting
        assert app.sheet["A2"].value == 10
        assert app.sheet["B2"].value == "01234"  # leading zero stays text
        assert len(batches) == 1
        assert app.dirty is True
        assert _status(app) == "pasted A1:B2"


async def test_external_paste_lands_at_selection_top_left():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=2, column=2)  # C3
        await pilot.pause()
        await pilot.press("shift+down", "shift+right")  # C3:D4
        app.post_message(events.Paste("x"))
        await pilot.pause()
        assert app.sheet["C3"].value == "x"  # anchored, not filled


async def test_external_paste_empty_fields_clear_targets():
    def populate(sh):
        sh["A1"] = 5
        sh["B1"] = 6

    app = _app(populate)
    async with app.run_test() as pilot:
        app.post_message(events.Paste("x\t"))
        await pilot.pause()
        assert app.sheet["A1"].value == "x"
        assert app.sheet["B1"].value is None  # empty field = clear


async def test_paste_event_while_editing_leaves_the_sheet_alone():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("a")  # seeded replace-edit opens in the bar
        app.post_message(events.Paste("99\t99"))
        await pilot.pause()
        assert app.sheet.used_range() is None  # nothing hit the engine
        assert app.dirty is False
