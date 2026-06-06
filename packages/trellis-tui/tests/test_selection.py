"""Pilot tests for the selection model (Part 6 #4).

Selection is grid-owned view state — ``(anchor, cursor)`` — and these
tests cover the rectangle algebra (pure), the extension/collapse flows
(Shift+arrows, shift+click, Ctrl+A, Esc, plain-move collapse), painting
(the tint composes with error styling; big deltas rebuild), the bar
readout, Delete-clears-selection as ONE batch, and selection surviving
engine-triggered rebuilds.
"""

from __future__ import annotations

from textual.coordinate import Coordinate

from trellis import Workbook
from trellis_tui.app import TrellisApp
from trellis_tui.editor import FormulaBar
from trellis_tui.grid import SheetGrid, _intersect, _rect_area, _rect_minus

TINT = SheetGrid.SELECTION_STYLE


def _app(populate=None) -> TrellisApp:
    wb = Workbook()
    sh = wb.add_sheet("S")
    if populate:
        populate(sh)
    return TrellisApp(wb)


def _style(grid: SheetGrid, row: int, col: int) -> str:
    return str(grid.get_cell_at(Coordinate(row, col)).style)


# --------------------------------------------------------- rect algebra


def test_rect_algebra_pure():
    a, b = ((0, 0), (2, 2)), ((1, 1), (3, 3))
    assert _rect_area(a) == 9
    assert _rect_area(None) == 0
    assert _intersect(a, b) == ((1, 1), (2, 2))
    assert _intersect(a, ((5, 5), (6, 6))) is None
    assert _intersect(a, None) is None
    assert _rect_minus(None, None) == []
    assert _rect_minus(a, None) == [a]
    # rect − hole decomposes into DISJOINT strips covering exactly the
    # difference (the delta enumeration never touches the overlap).
    hole = _intersect(a, b)
    cells: set = set()
    for (r0, c0), (r1, c1) in _rect_minus(a, hole):
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                assert (r, c) not in cells, "strips overlap"
                cells.add((r, c))
    assert cells == {(0, 0), (0, 1), (0, 2), (1, 0), (2, 0)}


# ------------------------------------------------------- extend flows


async def test_no_selection_by_default():
    app = _app()
    async with app.run_test():
        grid = app.query_one(SheetGrid)
        assert grid.selection is None
        assert grid.selection_range is None
        assert TINT not in _style(grid, 0, 0)


async def test_shift_arrows_extend_with_anchor_pinned():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+down", "shift+down", "shift+right")
        assert grid.selection == ((0, 0), (2, 1))  # anchor pinned at A1
        assert grid.selection_range == ((0, 0), (2, 1))
        for row in range(3):
            for col in range(2):
                assert TINT in _style(grid, row, col)
        assert TINT not in _style(grid, 3, 0)
        assert TINT not in _style(grid, 0, 2)
        bar = app.query_one(FormulaBar)
        assert bar.shown == ("B3", "A1:B3 (3×2)")


async def test_extension_normalizes_up_left():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=2, column=2)
        await pilot.pause()
        await pilot.press("shift+up", "shift+left")
        assert grid.selection == ((2, 2), (1, 1))  # anchor C3, cursor B2
        assert grid.selection_range == ((1, 1), (2, 2))  # normalised
        assert app.query_one(FormulaBar).shown == ("B2", "B2:C3 (2×2)")


async def test_plain_move_collapses():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+down", "shift+right")
        assert grid.selection_range == ((0, 0), (1, 1))
        await pilot.press("down")
        assert grid.selection is None
        for row in range(3):
            for col in range(2):
                assert TINT not in _style(grid, row, col)
        # bar is back to mirroring the cursor cell
        assert app.query_one(FormulaBar).shown == ("B3", "")


async def test_escape_collapses_and_cursor_stays():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+down", "shift+down")
        await pilot.press("escape")
        assert grid.selection is None
        assert grid.cursor_coordinate == Coordinate(2, 0)  # stays put
        assert TINT not in _style(grid, 1, 0)
        assert app.query_one(FormulaBar).shown == ("A3", "")


async def test_ctrl_a_selects_used_range_and_is_idempotent():
    def populate(sh):
        sh["A1"] = 1
        sh["C3"] = 9

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("ctrl+a")
        assert grid.selection_range == ((0, 0), (2, 2))
        assert grid.cursor_coordinate == Coordinate(2, 2)
        assert app.query_one(FormulaBar).shown == ("C3", "A1:C3 (3×3)")
        await pilot.press("ctrl+a")  # cursor already on the far corner
        assert grid.selection_range == ((0, 0), (2, 2))
        await pilot.press("down")  # counter hygiene: plain move collapses
        assert grid.selection is None


async def test_ctrl_a_on_empty_sheet_is_noop():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+a")
        assert app.query_one(SheetGrid).selection is None


async def test_ctrl_and_alt_click_also_extend():
    # Most terminals never forward shift+click (they keep it for native
    # text selection) — ctrl/alt survive, so they extend too (S35).
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        region = grid._get_cell_region(Coordinate(1, 1))
        await pilot.click(SheetGrid, offset=(region.x + 1, region.y), control=True)
        assert grid.selection == ((0, 0), (1, 1))
        region = grid._get_cell_region(Coordinate(3, 2))
        await pilot.click(SheetGrid, offset=(region.x + 1, region.y), meta=True)
        assert grid.selection == ((0, 0), (3, 2))  # anchor survives


async def test_shift_click_extends_and_plain_click_collapses():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        region = grid._get_cell_region(Coordinate(2, 2))
        await pilot.click(SheetGrid, offset=(region.x + 1, region.y), shift=True)
        assert grid.selection == ((0, 0), (2, 2))
        assert TINT in _style(grid, 1, 1)
        region = grid._get_cell_region(Coordinate(0, 0))
        await pilot.click(SheetGrid, offset=(region.x + 1, region.y))
        assert grid.selection is None
        assert TINT not in _style(grid, 1, 1)


# ------------------------------------------------------------- painting


async def test_selection_tint_composes_with_error_styling():
    def populate(sh):
        sh["B1"] = "=1/0"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+right")  # A1:B1
        error_style = _style(grid, 0, 1)
        assert "red" in error_style and TINT in error_style  # composed
        plain_style = _style(grid, 0, 0)
        assert TINT in plain_style and "red" not in plain_style


async def test_big_selection_takes_the_rebuild_path(monkeypatch):
    def populate(sh):
        for r in range(20):
            for c in range(20):
                sh.set((r, c), 1)  # 400 cells > REBUILD_THRESHOLD (256)

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        rebuilds: list = []
        original = grid._rebuild
        monkeypatch.setattr(
            grid, "_rebuild", lambda: (rebuilds.append(1), original())[1]
        )
        await pilot.press("ctrl+a")
        assert rebuilds, "big delta should rebuild, not restyle cell-by-cell"
        assert grid.selection_range == ((0, 0), (19, 19))
        assert TINT in _style(grid, 0, 0)
        assert TINT in _style(grid, 19, 19)
        assert app.query_one(FormulaBar).shown == ("T20", "A1:T20 (20×20)")


async def test_selection_survives_engine_rebuild():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+down", "shift+right")  # A1:B2, cursor B2
        app.sheet["A300"] = 7  # out-of-window write -> full rebuild
        await pilot.pause()
        assert grid.selection_range == ((0, 0), (1, 1))  # not collapsed
        assert TINT in _style(grid, 0, 0)  # rebuild re-painted the tint
        assert TINT in _style(grid, 1, 1)
        await pilot.press("down")  # and a real user move still collapses
        assert grid.selection is None


async def test_extension_grows_window_at_the_edge():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=SheetGrid.MIN_ROWS - 3)
        await pilot.pause()
        assert grid.row_count == SheetGrid.MIN_ROWS  # not yet in the zone
        await pilot.press("shift+down")  # into GROW_EDGE -> window grows
        assert grid.row_count == SheetGrid.MIN_ROWS + SheetGrid.GROW_ROWS
        assert grid.selection_range == (
            (SheetGrid.MIN_ROWS - 3, 0),
            (SheetGrid.MIN_ROWS - 2, 0),
        )


# ------------------------------------------------------ delete-selection


async def test_delete_clears_selection_in_one_batch():
    def populate(sh):
        sh["A1"] = 1
        sh["A2"] = 2
        sh["B1"] = "=A1*10"
        sh["C5"] = "survivor"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        batches: list = []
        app.sheet.on("sheet:batch", lambda **ev: batches.append(ev))
        await pilot.press("shift+down", "shift+right")  # A1:B2
        await pilot.press("delete")
        await pilot.pause()
        assert len(batches) == 1, "selection clear must be ONE batch"
        assert {tuple(ch["address"]) for ch in batches[0]["changes"]} == {
            (0, 0),
            (1, 0),
            (0, 1),
        }
        for a1 in ("A1", "A2", "B1"):
            assert app.sheet[a1].value is None
        assert app.sheet["C5"].value == "survivor"  # outside the rect
        assert app.dirty is True
        # Excel-faithful: the selection stays live after Delete (and the
        # now-empty cells keep their tint via the batch echo).
        assert grid.selection_range == ((0, 0), (1, 1))
        assert TINT in _style(grid, 0, 0)


async def test_delete_of_all_empty_selection_changes_nothing():
    app = _app()
    async with app.run_test() as pilot:
        batches: list = []
        app.sheet.on("sheet:batch", lambda **ev: batches.append(ev))
        await pilot.press("shift+down", "delete")
        await pilot.pause()
        assert batches == []  # engine skips empty batches...
        assert app.dirty is False  # ...so deleting nothing dirties nothing


async def test_delete_without_selection_still_clears_cursor_cell():
    app = _app(lambda sh: sh.set((0, 0), 42))
    async with app.run_test() as pilot:
        await pilot.press("delete")
        await pilot.pause()
        assert app.sheet["A1"].value is None
        assert app.dirty is True
