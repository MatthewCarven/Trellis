"""Pilot + unit tests for editing (Part 5 #5).

Engine writes are synchronous; mode transitions are message-driven, so
tests ``pause()`` around them.
"""

from __future__ import annotations

from textual.coordinate import Coordinate

from trellis import FormulaError, Workbook
from trellis_tui.app import TrellisApp
from trellis_tui.editor import CellEditor, FormulaBar, commit_text, prefill_text
from trellis_tui.grid import SheetGrid


def _app(populate=None) -> TrellisApp:
    wb = Workbook()
    sh = wb.add_sheet("S")
    if populate:
        populate(sh)
    return TrellisApp(wb)


def _text(grid: SheetGrid, row: int, col: int) -> str:
    return grid.get_cell_at(Coordinate(row, col)).plain


# --------------------------------------------------------- pure policy


def test_prefill_text_fidelity():
    wb = Workbook()
    sh = wb.add_sheet("S")
    sh["A1"] = "=A2*2"
    sh["A2"] = 0.1 + 0.2
    sh["A3"] = "01234"
    sh["A4"] = True
    sh["A5"] = 42
    sh.set((5, 0), FormulaError("#NUM!", "minted"))  # value-error, no formula
    assert prefill_text(sh["A1"]) == "=A2*2"  # formula wins, keeps its =
    assert prefill_text(sh["A2"]) == "0.30000000000000004"  # repr, NOT display
    assert prefill_text(sh["A3"]) == "01234"
    assert prefill_text(sh["A4"]) == "TRUE"
    assert prefill_text(sh["A5"]) == "42"
    assert prefill_text(sh["A6"]) == "#NUM!"
    assert prefill_text(sh["Z9"]) == ""  # empty cell


def test_commit_text_paths():
    wb = Workbook()
    sh = wb.add_sheet("S")
    commit_text(sh, (0, 0), "42")
    assert sh["A1"].value == 42 and isinstance(sh["A1"].value, int)
    commit_text(sh, (0, 0), "01234")
    assert sh["A1"].value == "01234"  # conservative inference, like CSV load
    commit_text(sh, (0, 0), " 42 ")
    assert sh["A1"].value == " 42 "  # whitespace keeps it a string
    commit_text(sh, (1, 0), "=A1")
    assert sh["A2"].formula == "=A1"
    commit_text(sh, (0, 0), "")  # empty commit deletes
    assert sh["A1"].is_empty()
    commit_text(sh, (5, 5), "")  # deleting an empty cell is fine
    assert sh["F6"].is_empty()


def test_commit_text_broken_formula_stores_error_not_raises():
    wb = Workbook()
    sh = wb.add_sheet("S")
    commit_text(sh, (0, 0), "=SUM(")
    assert isinstance(sh["A1"].value, FormulaError)
    assert sh["A1"].formula == "=SUM("  # preserved for F2


# --------------------------------------------------------- mode machine


async def test_typing_starts_replace_edit_with_seed():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("5")
        bar = app.query_one(FormulaBar)
        assert bar.editing
        assert app.query_one(CellEditor).value == "5"


async def test_enter_commits_int_and_moves_down():
    app = _app()
    async with app.run_test() as pilot:
        assert app.dirty is False
        await pilot.press("5", "enter")
        grid = app.query_one(SheetGrid)
        assert app.sheet["A1"].value == 5
        assert isinstance(app.sheet["A1"].value, int)  # inference, not "5"
        assert _text(grid, 0, 0) == "5"  # repainted via the event echo
        assert grid.cursor_coordinate == Coordinate(1, 0)
        assert app.query_one(FormulaBar).shown[0] == "A2"
        assert not app.query_one(FormulaBar).editing
        assert app.dirty is True


async def test_leading_zero_text_stays_string():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("0", "1", "2", "enter")
        assert app.sheet["A1"].value == "012"


async def test_formula_commit_evaluates_and_echoes():
    app = _app(lambda sh: sh.set((0, 0), 21))
    async with app.run_test() as pilot:
        await pilot.press("right")  # cursor to B1
        for ch in "=A1*2":
            await pilot.press(ch)
        await pilot.press("enter")
        grid = app.query_one(SheetGrid)
        assert app.sheet["B1"].value == 42
        assert _text(grid, 0, 1) == "42"


async def test_f2_revise_prefills_formula():
    def populate(sh):
        sh["A1"] = "=1+1"

    app = _app(populate)
    async with app.run_test() as pilot:
        await pilot.press("f2")
        assert app.query_one(CellEditor).value == "=1+1"


async def test_f2_prefill_uses_repr_not_lossy_display():
    app = _app(lambda sh: sh.set((0, 0), 0.1 + 0.2))
    async with app.run_test() as pilot:
        await pilot.press("f2")
        assert app.query_one(CellEditor).value == "0.30000000000000004"


async def test_unchanged_revise_commit_writes_nothing():
    app = _app(lambda sh: sh.set((0, 0), True))
    async with app.run_test() as pilot:
        await pilot.press("f2", "enter")  # open prefilled, commit untouched
        assert app.sheet["A1"].value is True  # still a bool, not "TRUE"
        assert app.dirty is False  # no write happened at all


async def test_escape_cancels_and_restores_nav():
    app = _app(lambda sh: sh.set((0, 0), 7))
    async with app.run_test() as pilot:
        await pilot.press("9", "escape")
        bar = app.query_one(FormulaBar)
        assert app.sheet["A1"].value == 7  # untouched
        assert not bar.editing
        assert bar.shown == ("A1", "7")
        assert app.query_one(SheetGrid).has_focus


async def test_tab_and_shift_enter_commit_and_move():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("1", "tab")  # A1, move right
        grid = app.query_one(SheetGrid)
        assert app.sheet["A1"].value == 1
        assert grid.cursor_coordinate == Coordinate(0, 1)
        await pilot.press("2", "enter")  # B1, move down
        assert app.sheet["B1"].value == 2
        assert grid.cursor_coordinate == Coordinate(1, 1)
        await pilot.press("3", "shift+enter")  # B2, move back up
        assert app.sheet["B2"].value == 3
        assert grid.cursor_coordinate == Coordinate(0, 1)


async def test_delete_clears_cell():
    app = _app(lambda sh: sh.set((0, 0), 5))
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        assert _text(grid, 0, 0) == "5"
        await pilot.press("delete")
        assert app.sheet["A1"].is_empty()
        assert _text(grid, 0, 0) == ""  # echoed
        assert app.dirty is True


async def test_backspace_opens_empty_edit_and_empty_commit_deletes():
    app = _app(lambda sh: sh.set((0, 0), 5))
    async with app.run_test() as pilot:
        await pilot.press("backspace")
        bar = app.query_one(FormulaBar)
        assert bar.editing
        assert app.query_one(CellEditor).value == ""
        await pilot.press("enter")
        assert app.sheet["A1"].is_empty()  # empty commit = delete (DECIDED)


async def test_nav_enter_opens_revise_edit():
    app = _app(lambda sh: sh.set((0, 0), 10))
    async with app.run_test() as pilot:
        await pilot.press("enter")
        bar = app.query_one(FormulaBar)
        assert bar.editing
        assert app.query_one(CellEditor).value == "10"


async def test_broken_formula_round_trip_via_f2():
    app = _app()
    async with app.run_test() as pilot:
        for ch in "=SUM(":
            await pilot.press(ch)
        await pilot.press("enter")
        grid = app.query_one(SheetGrid)
        assert _text(grid, 0, 0) == "#NAME?"  # committed as an error value
        await pilot.press("up", "f2")  # back to A1, revise
        assert app.query_one(CellEditor).value == "=SUM("  # formula preserved
