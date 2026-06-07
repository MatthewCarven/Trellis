"""Pilot tests for keyboard fill — Ctrl+D / Ctrl+R (Part 8).

Fill writes the selection from its first row/column (or, single-lane,
from the neighbor above/left — Excel's no-selection gesture) through
the same per-cell transfer as paste: formulas shift per-lane (``$``
pins hold), values copy at full fidelity, empty sources clear. ONE
batch — one echo, one dirty mark, one undo step. No clipboard
involvement.
"""

from __future__ import annotations

from trellis import Workbook
from trellis_tui.app import TrellisApp
from trellis_tui.grid import SheetGrid


def _app(populate=None) -> TrellisApp:
    wb = Workbook()
    sh = wb.add_sheet("S")
    if populate:
        populate(sh)
    return TrellisApp(wb)


def _status(app: TrellisApp) -> str:
    from trellis_tui.app import StatusBar

    return app.query_one(StatusBar).state[2]


# ------------------------------------------------------------ fill down


async def test_fill_down_shifts_formulas_per_lane_one_batch():
    def populate(sh):
        sh["A1"] = 10
        sh["B1"] = "=A1*2"

    app = _app(populate)
    async with app.run_test() as pilot:
        batches: list = []
        app.sheet.on("sheet:batch", lambda **ev: batches.append(ev))
        # Select A1:B3, source row stays put, rows 2-3 get written.
        await pilot.press("shift+right", "shift+down", "shift+down", "ctrl+d")
        await pilot.pause()
        assert app.sheet["A2"].value == 10  # values copy verbatim per lane
        assert app.sheet["A3"].value == 10
        assert app.sheet["B2"].formula == "=A2*2"  # each lane's own source,
        assert app.sheet["B3"].formula == "=A3*2"  # shifted by ITS offset
        assert app.sheet["B3"].value == 20  # and re-evaluated
        assert len(batches) == 1, "fill must be ONE batch"
        assert _status(app) == "filled down A2:B3"
        assert app.sheet_clipboard is None  # no clipboard involvement


async def test_fill_down_respects_dollar_pins():
    def populate(sh):
        sh["A1"] = 100
        sh["A2"] = 7
        sh["B1"] = "=$A$1+A1"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=0, column=1)  # B1
        await pilot.pause()
        await pilot.press("shift+down", "ctrl+d")
        assert app.sheet["B2"].formula == "=$A$1+A2"  # pin holds, rel shifts
        assert app.sheet["B2"].value == 107  # pinned 100 + shifted A2


# ----------------------------------------------------------- fill right


async def test_fill_right_mirrors_with_columns():
    def populate(sh):
        sh["A1"] = 5
        sh["A2"] = "=A1*3"

    app = _app(populate)
    async with app.run_test() as pilot:
        await pilot.press(
            "shift+down", "shift+right", "shift+right", "ctrl+r"
        )  # A1:C2, source col A
        await pilot.pause()
        assert app.sheet["B1"].value == 5
        assert app.sheet["C1"].value == 5
        assert app.sheet["B2"].formula == "=B1*3"
        assert app.sheet["C2"].formula == "=C1*3"
        assert _status(app) == "filled right B1:C2"


# ------------------------------------- single lane: fill from the neighbor


async def test_fill_from_the_cell_above_no_selection():
    app = _app(lambda sh: sh.set("B1", "=A1*2"))
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=1, column=1)  # B2, no selection
        await pilot.pause()
        await pilot.press("ctrl+d")
        assert app.sheet["B2"].formula == "=A2*2"  # Excel's no-selection fill
        assert _status(app) == "filled down B2"


async def test_fill_single_row_selection_fills_from_above():
    def populate(sh):
        sh["A1"] = 1
        sh["B1"] = 2

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=1, column=0)  # A2
        await pilot.pause()
        await pilot.press("shift+right", "ctrl+d")  # A2:B2, one row tall
        assert app.sheet["A2"].value == 1
        assert app.sheet["B2"].value == 2


async def test_fill_at_the_sheet_edge_hints_and_writes_nothing():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+d")
        assert _status(app) == "nothing above to fill from"
        await pilot.press("ctrl+r")
        assert _status(app) == "nothing left to fill from"
        assert app.dirty is False


# ------------------------------------------------------------- semantics


async def test_fill_empty_source_clears_targets():
    def populate(sh):
        sh["A2"] = 5
        sh["A3"] = 6

    app = _app(populate)
    async with app.run_test() as pilot:
        await pilot.press("shift+down", "shift+down", "ctrl+d")  # A1:A3, A1 empty
        await pilot.pause()
        assert app.sheet["A2"].value is None  # Excel-faithful: empty fills
        assert app.sheet["A3"].value is None
        assert app.dirty is True


async def test_fill_nothing_over_nothing_stays_clean():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=4, column=0)  # A5: blank region, row above blank
        await pilot.pause()
        batches: list = []
        app.sheet.on("sheet:batch", lambda **ev: batches.append(ev))
        await pilot.press("shift+down", "ctrl+d")
        assert batches == []  # delete-of-absent is silent; empty batch skipped
        assert app.dirty is False


async def test_fill_is_one_undo_step():
    app = _app(lambda sh: sh.set("A1", "=1+1"))
    async with app.run_test() as pilot:
        await pilot.press("shift+down", "shift+down", "ctrl+d")  # A1:A3
        assert app.sheet["A3"].value == 2
        await pilot.press("ctrl+z")  # the whole fill, one step back
        assert app.sheet["A2"].value is None
        assert app.sheet["A3"].value is None
        assert app.sheet["A1"].value == 2  # source untouched by either


async def test_fill_disarms_a_pending_cut():
    def populate(sh):
        sh["A1"] = 1
        sh["C1"] = 9

    app = _app(populate)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+x")  # cut A1, pending
        assert app.sheet_clipboard.mode == "cut"
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=0, column=2)  # C1
        await pilot.pause()
        await pilot.press("shift+down", "ctrl+d")  # an engine change
        assert app.sheet_clipboard.mode == "copy"  # stale snapshot disarmed
        assert app.sheet["A1"].value == 1  # and the source is safe


# ------------------------------------------------------------- isolation


async def test_ctrl_d_while_editing_edits_text_not_the_sheet():
    from trellis_tui.editor import FormulaBar

    app = _app(lambda sh: sh.set("A1", 42))
    async with app.run_test() as pilot:
        await pilot.press("9")  # open a seeded edit on A1
        assert app.query_one(FormulaBar).editing
        await pilot.press("ctrl+d")  # Input's delete-right, not a fill
        assert app.query_one(FormulaBar).editing  # edit still open
        assert app.sheet["A1"].value == 42  # sheet untouched
        await pilot.press("escape")


async def test_selection_and_cursor_survive_fill():
    app = _app(lambda sh: sh.set("A1", 3))
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+right", "shift+down", "ctrl+d")  # A1:B2
        assert grid.selection_range == ((0, 0), (1, 1))  # Excel: sticks
        assert grid.cursor_coordinate.row == 1
        assert grid.cursor_coordinate.column == 1
