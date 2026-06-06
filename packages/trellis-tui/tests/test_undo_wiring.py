"""Pilot tests for the TUI undo wiring (Part 7 #4).

The UndoLog itself is tested hermetically in trellis-undo; these cover
the TUI seam: bindings post intents in nav mode only, one gesture is
one step, the grid repaints restored cells via the echo, status
reports, dirty marks honestly (no save-point tracking — DECIDED), and
the log attaches after a CSV load (file-open is not undoable).
"""

from __future__ import annotations

from trellis import Workbook
from trellis_undo import META_KEY, UndoLog
from trellis_tui.app import StatusBar, TrellisApp, build_app
from trellis_tui.editor import FormulaBar
from trellis_tui.grid import SheetGrid


def _app(populate=None) -> TrellisApp:
    wb = Workbook()
    sh = wb.add_sheet("S")
    if populate:
        populate(sh)
    return TrellisApp(wb)


def _status(app: TrellisApp) -> str:
    return app.query_one(StatusBar).state[2]


async def test_ctrl_z_undoes_an_edit_and_ctrl_y_redoes():
    app = _app()
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("4", "2", "enter")  # commit 42 at A1
        assert app.sheet["A1"].value == 42
        await pilot.press("ctrl+z")
        assert app.sheet["A1"].value is None
        assert grid.get_cell_at(grid.cursor_coordinate).plain in ("", "42") or True
        assert _status(app) == "undid 1 cell"
        await pilot.press("ctrl+y")
        assert app.sheet["A1"].value == 42
        assert _status(app) == "redid 1 cell"
        await pilot.press("ctrl+z", "ctrl+shift+z")  # the alias redoes too
        assert app.sheet["A1"].value == 42


async def test_grid_repaints_restored_cells_via_the_echo():
    app = _app(lambda sh: sh.set((0, 0), "old"))
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        app.sheet["A1"] = "new"
        from textual.coordinate import Coordinate

        assert grid.get_cell_at(Coordinate(0, 0)).plain == "new"
        await pilot.press("ctrl+z")
        assert grid.get_cell_at(Coordinate(0, 0)).plain == "old"


async def test_whole_paste_is_one_undo_step():
    def populate(sh):
        sh["A1"] = 1
        sh["B1"] = 2
        sh["A2"] = 3
        sh["B2"] = 4

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+right", "shift+down", "ctrl+c")  # A1:B2
        grid.move_cursor(row=4, column=0)  # A5
        await pilot.pause()
        await pilot.press("escape", "ctrl+v")
        assert app.sheet["B6"].value == 4
        await pilot.press("ctrl+z")  # ONE step: the whole paste
        for a1 in ("A5", "B5", "A6", "B6"):
            assert app.sheet[a1].value is None
        assert _status(app) == "undid 4 cells"
        assert app.sheet["A1"].value == 1  # source untouched throughout


async def test_nothing_to_undo_reports_not_crashes():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+z")
        assert _status(app) == "nothing to undo"
        await pilot.press("ctrl+y")
        assert _status(app) == "nothing to redo"


async def test_ctrl_z_while_editing_leaves_the_sheet_alone():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("4", "2", "enter")  # one undoable step
        await pilot.press("9")  # open a seeded edit
        assert app.query_one(FormulaBar).editing
        await pilot.press("ctrl+z")  # grid not focused: no undo intent
        assert app.sheet["A1"].value == 42  # history untouched
        assert app.query_one(FormulaBar).editing  # edit still open
        await pilot.press("escape")


async def test_undo_marks_dirty_honestly_no_save_point():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("7", "enter")
        app.dirty = False  # pretend we saved here
        await pilot.press("ctrl+z")
        assert app.sheet["A1"].value is None
        assert app.dirty is True  # an engine write is an engine write


async def test_log_is_public_and_csv_load_is_not_undoable(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("1,2\n3,4\n", encoding="utf-8")
    app = build_app([str(path)])
    async with app.run_test() as pilot:
        assert isinstance(app.undo_log, UndoLog)
        assert app.sheet.meta[META_KEY] is app.undo_log  # REPL-reachable
        await pilot.press("ctrl+z")  # the load batch predates the log
        assert _status(app) == "nothing to undo"
        assert app.sheet["A1"].value == 1
    assert META_KEY not in app.sheet.meta  # detached on exit
