"""The vim keymap driving the real app (Pilot, headless textual).

The hermetic suite proves the parser; these prove the composition —
vim Actions through the TUI's executor against a live engine sheet.
"""

from __future__ import annotations

from trellis import Workbook
from trellis_tui import TrellisApp
from trellis_tui.app import StatusBar
from trellis_tui.editor import CellEditor
from trellis_vim import VimKeymap


def make_app(cells=None) -> TrellisApp:
    wb = Workbook()
    sheet = wb.add_sheet("Sheet1")
    for a1, value in (cells or {}).items():
        sheet[a1] = value
    return TrellisApp(wb, keymap=VimKeymap())


def status(app) -> str:
    return app.query_one(StatusBar).state[2]


async def test_motions_move_the_real_cursor():
    app = make_app({"A1": 1, "C1": 2, "C5": 3})
    async with app.run_test() as pilot:
        grid = app.active_view.grid
        await pilot.press("3", "j")
        assert grid.cursor_coordinate.row == 3
        await pilot.press("g", "g")  # top of column A's data
        assert (grid.cursor_coordinate.row, grid.cursor_coordinate.column) == (0, 0)
        await pilot.press("w")  # data jump: A1 -> C1
        assert grid.cursor_coordinate.column == 2
        await pilot.press("G")  # bottom of column C's data
        assert grid.cursor_coordinate.row == 4
        # j is a MOTION here — under Excel keys it would start an edit.
        assert not app.query_one("FormulaBar").has_class("editing")


async def test_insert_caret_and_commit_returns_to_normal():
    app = make_app({"A1": "hello"})
    async with app.run_test() as pilot:
        await pilot.press("i")
        editor = app.query_one(CellEditor)
        assert app.mode == "insert"
        assert editor.value == "hello" and editor.cursor_position == 0
        await pilot.press("escape")
        assert app.mode == "normal"
        await pilot.press("a")
        assert app.query_one(CellEditor).cursor_position == len("hello")
        await pilot.press("escape")


async def test_x_yanks_then_clears_so_p_moves():
    app = make_app({"A1": 42})
    async with app.run_test() as pilot:
        grid = app.active_view.grid
        await pilot.press("x")
        assert app.sheet["A1"].value is None
        await pilot.press("3", "j", "p")  # paste at A4
        assert app.sheet["A4"].value == 42
        assert grid.cursor_coordinate.row == 3


async def test_dd_p_moves_a_row():
    app = make_app({"A1": 1, "B1": "=A1*2", "A3": 9})
    async with app.run_test() as pilot:
        await pilot.press("d", "d")
        assert app.sheet["A1"].value is None
        assert app.sheet["B1"].value is None
        await pilot.press("j", "p")  # row lands at row 2
        assert app.sheet["A2"].value == 1
        assert app.sheet["B2"].value == 2  # formula shifted with the paste
        await pilot.press("u")  # one undo step un-pastes the row
        assert app.sheet["A2"].value is None


async def test_visual_y_p_copies_a_block():
    app = make_app({"A1": 1, "B1": 2})
    async with app.run_test() as pilot:
        await pilot.press("v", "l", "y")  # visual A1:B1, yank
        assert app.mode == "normal"
        assert app.active_view.grid.selection_range is None  # collapsed
        # Vim parks the cursor at the yanked region's start.
        assert app.active_view.grid.cursor_coordinate.column == 0
        await pilot.press("2", "j", "p")
        assert app.sheet["A3"].value == 1
        assert app.sheet["B3"].value == 2


async def test_visual_line_d_takes_whole_rows():
    app = make_app({"A1": 1, "C1": 2, "A2": 3, "C2": 4, "A4": 5})
    async with app.run_test() as pilot:
        await pilot.press("V", "j", "d")  # rows 1-2, delete
        for a1 in ("A1", "C1", "A2", "C2"):
            assert app.sheet[a1].value is None, a1
        assert app.sheet["A4"].value == 5
        assert app.mode == "normal"


async def test_command_goto_save_and_mode_chrome():
    app = make_app({"A1": 1})
    async with app.run_test() as pilot:
        bar = app.query_one(StatusBar)
        await pilot.press("colon")
        assert app.mode == "command" and bar.mode_shown == "command"
        await pilot.press("1", "5")
        assert status(app) == ":15"  # the buffer echoes in the status bar
        await pilot.press("enter")
        assert app.mode == "normal" and bar.mode_shown == ""
        assert app.active_view.grid.cursor_coordinate.row == 14
        # :w on a pathless sheet opens the same Save-As modal as Ctrl+S.
        await pilot.press("colon", "w", "enter")
        assert type(app.screen).__name__ == "SaveAsScreen"
        await pilot.press("escape")


async def test_q_bang_force_quits_and_q_warns():
    app = make_app({"A1": 1})
    async with app.run_test() as pilot:
        await pilot.press("i")  # dirty the sheet
        await pilot.press("9", "enter")
        assert app.dirty
        await pilot.press("colon", "q", "enter")  # :q warns, stays
        assert "unsaved" in status(app)
        await pilot.press("colon", "q", "exclamation_mark", "enter")
        assert app.return_value is None  # exited (run_test survives exit)


async def test_chrome_still_app_owned_under_vim():
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+t")  # the keymap declines it -> app chrome
        assert len(app.views) == 2
        assert app.sheet.name == "Sheet2"  # Ctrl+T activates the new tab
        await pilot.press("ctrl+pagedown")  # wraps back around
        assert app.sheet.name == "Sheet1"
