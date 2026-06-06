"""Pilot tests for SheetGrid: window, growth, and the event echo (#4).

Engine event handlers run synchronously inside the engine write, so grid
cell content is assertable immediately after a ``sheet[...] = ...``; only
*message*-driven effects (cursor moves -> formula bar) need a
``pilot.pause()``.
"""

from __future__ import annotations

from textual.coordinate import Coordinate

from trellis import Workbook
from trellis_tui.app import TrellisApp
from trellis_tui.editor import FormulaBar
from trellis_tui.grid import SheetGrid, col_letters, values_equal


def _app(populate=None) -> TrellisApp:
    wb = Workbook()
    sh = wb.add_sheet("S")
    if populate:
        populate(sh)
    return TrellisApp(wb)


def _text(grid: SheetGrid, row: int, col: int) -> str:
    return grid.get_cell_at(Coordinate(row, col)).plain


# ------------------------------------------------------------ pure helpers


def test_col_letters_via_public_to_a1():
    assert [col_letters(c) for c in (0, 1, 25, 26, 27)] == ["A", "B", "Z", "AA", "AB"]


def test_values_equal_is_type_strict():
    assert values_equal(3, 3)
    assert values_equal(None, None)
    assert not values_equal(0, False)  # display differs: "0" vs "FALSE"
    assert not values_equal(1, 1.0)
    assert not values_equal(0, None)


# ------------------------------------------------------------ window shape


async def test_empty_workbook_gets_minimum_window():
    app = _app()
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        assert grid.row_count == SheetGrid.MIN_ROWS
        assert len(grid.columns) == SheetGrid.MIN_COLS
        labels = [col.label.plain for col in grid.columns.values()]
        assert labels[0] == "A" and labels[-1] == "Z"
        assert _text(grid, 0, 0) == ""


async def test_window_covers_data_beyond_minimum():
    def populate(sh):
        sh["A150"] = 1
        sh["AB1"] = 2  # column index 27

    app = _app(populate)
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        assert grid.row_count >= 150
        assert len(grid.columns) >= 28
        assert _text(grid, 149, 0) == "1"
        assert _text(grid, 0, 27) == "2"


async def test_cells_render_through_the_display_policy():
    def populate(sh):
        sh["A1"] = 10
        sh["B1"] = "=A1*2"
        sh["C1"] = True
        sh["D1"] = "=1/0"

    app = _app(populate)
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        assert _text(grid, 0, 0) == "10"
        assert _text(grid, 0, 1) == "20"  # computed value, not the formula
        assert _text(grid, 0, 2) == "TRUE"
        error = grid.get_cell_at(Coordinate(0, 3))
        assert error.plain == "#DIV/0!"
        assert "red" in str(error.style)
        assert grid.get_cell_at(Coordinate(0, 0)).justify == "right"


# ------------------------------------------------------------ event echo


async def test_engine_write_repaints_one_cell():
    app = _app()
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        app.sheet["A1"] = 5
        assert _text(grid, 0, 0) == "5"


async def test_recalc_cascade_repaints_dependents():
    def populate(sh):
        sh["A1"] = 2
        sh["B1"] = "=A1*3"

    app = _app(populate)
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        app.sheet["A1"] = 10
        assert _text(grid, 0, 1) == "30"


async def test_noop_write_skips_repaint_but_type_change_does_not(monkeypatch):
    app = _app(lambda sh: sh.set((0, 0), 0))
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        calls: list = []
        original = grid.update_cell_at

        def spy(coordinate, value, *, update_width=False):
            calls.append(coordinate)
            original(coordinate, value, update_width=update_width)

        monkeypatch.setattr(grid, "update_cell_at", spy)
        app.sheet["A1"] = 0  # same value, same type: no repaint
        assert calls == []
        app.sheet["A1"] = False  # == but different display ("FALSE")
        assert calls == [Coordinate(0, 0)]
        assert _text(grid, 0, 0) == "FALSE"


async def test_batch_repaints_on_exit_not_during():
    app = _app()
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        with app.sheet.batch():
            app.sheet["A1"] = 1
            app.sheet["A2"] = 2
            assert _text(grid, 0, 0) == ""  # suppressed mid-batch
        assert _text(grid, 0, 0) == "1"
        assert _text(grid, 1, 0) == "2"


async def test_batch_reaching_outside_window_rebuilds_to_cover():
    app = _app()
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        with app.sheet.batch():
            for r in range(300):
                app.sheet.set((r, 0), r)
        assert grid.row_count >= 300
        assert _text(grid, 299, 0) == "299"


async def test_out_of_window_write_grows_the_window():
    app = _app()
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        app.sheet["A200"] = 7
        assert grid.row_count >= 200
        assert _text(grid, 199, 0) == "7"


# ------------------------------------------------------------ growth + bar


async def test_cursor_near_edge_grows_rows_and_cols():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=SheetGrid.MIN_ROWS - 1)
        await pilot.pause()
        assert grid.row_count == SheetGrid.MIN_ROWS + SheetGrid.GROW_ROWS
        grid.move_cursor(column=SheetGrid.MIN_COLS - 1)
        await pilot.pause()
        assert len(grid.columns) == SheetGrid.MIN_COLS + SheetGrid.GROW_COLS
        # the reach survives a rebuild (engine write far outside)
        app.sheet["A500"] = 1
        assert grid.row_count >= 500
        assert len(grid.columns) == SheetGrid.MIN_COLS + SheetGrid.GROW_COLS


async def test_formula_bar_mirrors_cursor_formula_not_value():
    def populate(sh):
        sh["A1"] = 10
        sh["B1"] = "=A1*2"

    app = _app(populate)
    async with app.run_test() as pilot:
        bar = app.query_one(FormulaBar)
        await pilot.pause()
        assert bar.shown == ("A1", "10")
        await pilot.press("right")
        assert bar.shown == ("B1", "=A1*2")  # the formula, with its =
        await pilot.press("down")
        assert bar.shown == ("B2", "")


async def test_unsubscribes_on_exit():
    app = _app()
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        assert len(grid._subs) == 3
    assert grid._subs == []
    app.sheet["A1"] = 99  # engine keeps working; no dead-widget explosions
    assert app.sheet["A1"].value == 99
