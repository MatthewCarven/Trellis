"""Pilot tests for sheet tabs (Part 9) — the editor-buffers model.

Rows land in order: #2 per-sheet state (SheetView, dirty/undo/save/quit
routing) — UI still single-tab; #3 adds the tab bar; #4 rename + CLI;
#5 the cross-tab clipboard.
"""

from __future__ import annotations

from trellis import Workbook
from trellis_tui.app import SheetView, TrellisApp


def _two_sheet_app(paths=None) -> TrellisApp:
    wb = Workbook()
    wb.add_sheet("alpha")
    wb.add_sheet("beta")
    return TrellisApp(wb, paths=paths)


def _status(app: TrellisApp) -> str:
    from trellis_tui.app import StatusBar

    return app.query_one(StatusBar).state[2]


# ----------------------------------------------------------- #2: views


async def test_views_built_from_workbook_in_order_with_paths():
    app = _two_sheet_app(paths={"beta": "b.csv"})
    async with app.run_test():
        assert [v.sheet.name for v in app.views] == ["alpha", "beta"]
        assert app.views[0].path is None
        assert app.views[1].path == "b.csv"
        assert app.active_view is app.views[0]
        assert app.sheet is app.views[0].sheet  # the facade reads through


async def test_path_kwarg_still_names_the_first_sheet():
    app = _two_sheet_app()
    assert app.views[0].path is None
    app2 = TrellisApp(Workbook(), path="x.csv")  # empty wb grows Sheet1
    assert app2.views[0].sheet.name == "Sheet1"
    assert app2.views[0].path == "x.csv"


async def test_dirty_routes_to_the_changed_sheet():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        background = app.views[1].sheet
        background["A1"] = 5  # a REPL-style write to a non-active sheet
        await pilot.pause()
        assert app.views[1].dirty is True
        assert app.views[0].dirty is False
        assert app.dirty is False  # the facade reports the ACTIVE view


async def test_each_sheet_gets_its_own_undo_log():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        logs = [v.undo_log for v in app.views]
        assert all(log is not None for log in logs)
        assert logs[0] is not logs[1]
        assert app.undo_log is logs[0]  # facade: the active one
        app.views[1].sheet["A1"] = 7  # records on ITS log only
        await pilot.pause()
        assert logs[1].can_undo and not logs[0].can_undo


async def test_save_writes_the_active_sheet_only(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    app = _two_sheet_app(paths={"alpha": str(a), "beta": str(b)})
    async with app.run_test() as pilot:
        app.views[0].sheet["A1"] = 1
        app.views[1].sheet["A1"] = 2
        await pilot.pause()
        await pilot.press("ctrl+s")
        assert a.exists() and not b.exists()
        assert app.views[0].dirty is False
        assert app.views[1].dirty is True  # un-saved, un-touched


async def test_quit_warning_counts_every_unsaved_sheet():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        app.views[0].sheet["A1"] = 1
        app.views[1].sheet["A1"] = 2
        await pilot.pause()
        await pilot.press("ctrl+q")
        assert "2 sheets unsaved" in _status(app)
        assert app._quit_armed is True  # next Ctrl+Q quits


async def test_recalc_note_stays_quiet_for_background_sheets():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        background = app.views[1].sheet
        background["A1"] = 3
        background["B1"] = "=A1*2"
        await pilot.pause()
        before = _status(app)
        background["A1"] = 4  # cascades a recalc on the background sheet
        await pilot.pause()
        assert _status(app) == before  # no "recalc B1" note for tab 2
        assert background["B1"].value == 8  # the recalc itself happened


# -------------------------------------------------------- #3: the tab bar


async def test_tab_strip_composes_and_first_grid_focused():
    from textual.widgets import Tabs

    app = _two_sheet_app()
    async with app.run_test() as pilot:
        tabs = app.query_one(Tabs)
        assert tabs.tab_count == 2
        assert app.focused is app.views[0].grid
        from textual.widgets import ContentSwitcher

        assert (
            app.query_one(ContentSwitcher).current == f"grid-{app.views[0].uid}"
        )


async def test_ctrl_pagedown_cycles_sheets_with_wraparound():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+pagedown")
        await pilot.pause()  # Tabs activation arrives as a queued message
        assert app.active_view is app.views[1]
        assert app.sheet.name == "beta"  # the facade follows
        assert app.focused is app.views[1].grid
        await pilot.press("ctrl+pagedown")  # wraps
        await pilot.pause()
        assert app.active_view is app.views[0]
        await pilot.press("ctrl+pageup")  # wraps backward
        await pilot.pause()
        assert app.active_view is app.views[1]


async def test_per_tab_cursor_and_selection_survive_switching():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("down", "right")  # alpha cursor to B2
        await pilot.press("shift+right")  # selection B2:C2
        alpha_grid = app.views[0].grid
        assert alpha_grid.selection_range == ((1, 1), (1, 2))
        await pilot.press("ctrl+pagedown")
        beta_grid = app.views[1].grid
        assert (beta_grid.cursor_coordinate.row, beta_grid.cursor_coordinate.column) == (0, 0)
        await pilot.press("ctrl+pageup")
        assert (alpha_grid.cursor_coordinate.row, alpha_grid.cursor_coordinate.column) == (1, 2)
        assert alpha_grid.selection_range == ((1, 1), (1, 2))  # intact


async def test_formula_bar_follows_the_active_sheet():
    from trellis_tui.editor import FormulaBar

    app = _two_sheet_app()
    async with app.run_test() as pilot:
        app.views[1].sheet["A1"] = 99
        await pilot.pause()
        bar = app.query_one(FormulaBar)
        assert bar.shown[0] == "A1"
        before = bar.shown[1]
        await pilot.press("ctrl+pagedown")
        await pilot.pause()
        assert bar.shown[0] == "A1"
        assert bar.shown[1] != before  # now mirrors beta's A1 (99)


async def test_ctrl_t_adds_a_pathless_sheet_and_activates_it():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+t")
        assert len(app.views) == 3
        view = app.active_view
        assert view is app.views[2]
        assert view.sheet.name == "Sheet1"  # first free N
        assert view.path is None and view.dirty is False
        assert "Sheet1" in app.workbook
        assert "names its file" in _status(app)
        await pilot.press("4", "2", "enter")  # typing lands on the new sheet
        assert view.sheet["A1"].value == 42
        assert app.views[0].sheet["A1"].value is None


async def test_ctrl_w_warns_once_on_dirty_then_closes():
    from textual.widgets import Tabs

    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("7", "enter")  # dirty alpha
        await pilot.press("ctrl+w")
        assert "alpha unsaved" in _status(app)
        assert len(app.views) == 2  # warned, not closed
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert len(app.views) == 1
        assert app.active_view.sheet.name == "beta"  # right neighbor
        assert "alpha" not in app.workbook
        assert app.query_one(Tabs).tab_count == 1


async def test_close_clean_sheet_closes_immediately():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+pagedown")  # to beta (clean)
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert len(app.views) == 1
        assert app.active_view.sheet.name == "alpha"  # left neighbor (no right)


async def test_ctrl_w_on_the_last_tab_refuses():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("ctrl+w")  # now a single tab
        await pilot.pause()
        assert len(app.views) == 1
        assert "last sheet" in _status(app)


async def test_switching_while_editing_is_a_noop_with_hint():
    from trellis_tui.editor import FormulaBar

    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("9")  # open a seeded edit
        assert app.query_one(FormulaBar).editing
        await pilot.press("ctrl+pagedown")
        assert app.active_view is app.views[0]  # did not switch
        assert _status(app) == "finish the edit first"
        assert app.query_one(FormulaBar).editing  # edit still open
        await pilot.press("escape")


async def test_background_rebuild_does_not_steal_the_formula_bar():
    from trellis_tui.editor import FormulaBar

    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("down")  # active cursor to A2 (bar shows A2)
        bar = app.query_one(FormulaBar)
        assert bar.shown[0] == "A2"
        # A write far outside beta's window forces ITS grid to rebuild,
        # which posts a CellHighlighted from the background DataTable.
        app.views[1].sheet[(200, 1)] = 1
        await pilot.pause()
        assert bar.shown[0] == "A2"  # the bar still mirrors the active tab


# ------------------------------------------------- #4: rename + CLI files


async def test_alt_r_renames_the_active_sheet():
    from textual.widgets import Tab

    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("alt+r")
        await pilot.pause()
        # The modal Input arrives prefilled with the current name.
        await pilot.press("ctrl+u")  # clear it (Input's delete-left-all)
        await pilot.press("g", "a", "m", "m", "a", "enter")
        await pilot.pause()
        assert app.sheet.name == "gamma"
        assert "gamma" in app.workbook and "alpha" not in app.workbook
        assert "renamed alpha → gamma" in _status(app)
        tab = app._tab_for(app.active_view)
        assert str(tab.label) == "gamma"
        assert [v.sheet.name for v in app.views] == ["gamma", "beta"]


async def test_rename_collision_hints_and_keeps_the_name():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("alt+r")
        await pilot.pause()
        await pilot.press("ctrl+u")
        await pilot.press("b", "e", "t", "a", "enter")
        await pilot.pause()
        assert app.sheet.name == "alpha"  # unchanged
        assert "name taken: beta" in _status(app)


async def test_rename_esc_cancels():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        await pilot.press("alt+r")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.sheet.name == "alpha"


async def test_double_click_on_tab_opens_rename():
    from trellis_tui.app import RenameScreen

    app = _two_sheet_app()
    async with app.run_test() as pilot:
        tab = app._tab_for(app.views[0])
        await pilot.click(tab, times=2)
        await pilot.pause()
        assert isinstance(app.screen, RenameScreen)
        await pilot.press("escape")


async def test_tab_label_carries_the_dirty_marker(tmp_path):
    path = tmp_path / "alpha.csv"
    app = _two_sheet_app(paths={"alpha": str(path)})
    async with app.run_test() as pilot:
        assert str(app._tab_for(app.views[0]).label) == "alpha"
        await pilot.press("7", "enter")  # dirty alpha
        assert str(app._tab_for(app.views[0]).label) == "alpha ●"
        assert str(app._tab_for(app.views[1]).label) == "beta"  # untouched
        await pilot.press("ctrl+s")
        assert str(app._tab_for(app.views[0]).label) == "alpha"  # saved


async def test_rename_keeps_the_save_path(tmp_path):
    path = tmp_path / "data.csv"
    app = _two_sheet_app(paths={"alpha": str(path)})
    async with app.run_test() as pilot:
        await pilot.press("alt+r")
        await pilot.pause()
        await pilot.press("ctrl+u")
        await pilot.press("x", "enter")
        await pilot.pause()
        assert app.sheet.name == "x"
        assert app.path == str(path)  # the file identity is untouched
        await pilot.press("4", "enter", "ctrl+s")
        assert path.exists()


def test_build_app_opens_one_tab_per_file(tmp_path):
    from trellis_tui.app import build_app

    a = tmp_path / "sales.csv"
    b = tmp_path / "costs.csv"
    a.write_text("1,=A1*2\n", encoding="utf-8")
    b.write_text("3\n", encoding="utf-8")
    app = build_app([str(a), str(b)])
    assert [v.sheet.name for v in app.views] == ["sales", "costs"]
    assert app.views[0].path == str(a)
    assert app.views[1].path == str(b)
    assert app.views[0].sheet["B1"].value == 2  # formulas load live
    assert app.views[1].sheet["A1"].value == 3


def test_build_app_dedupes_stems_and_remembers_new_paths(tmp_path):
    from trellis_tui.app import build_app

    d1 = tmp_path / "one"
    d2 = tmp_path / "two"
    d1.mkdir()
    d2.mkdir()
    p1 = d1 / "data.csv"
    p1.write_text("1\n", encoding="utf-8")
    p2 = d2 / "data.csv"  # same stem, different dir; does not exist yet
    app = build_app([str(p1), str(p2)])
    assert [v.sheet.name for v in app.views] == ["data", "data-2"]
    assert app.views[1].path == str(p2)  # new-file flow, path remembered
    assert app.views[1].sheet.used_range() is None  # empty tab


# -------------------------------------------- #5: the cross-tab clipboard


async def test_copy_pastes_across_tabs_with_shifted_formulas():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        alpha = app.views[0].sheet
        alpha["A1"] = 10
        alpha["B1"] = "=A1*2"
        await pilot.pause()
        app.views[0].dirty = False  # the setup writes dirtied alpha
        app.views[0].grid.move_cursor(row=0, column=1)  # B1
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.press("ctrl+pagedown")
        await pilot.pause()
        beta_grid = app.views[1].grid
        beta_grid.move_cursor(row=1, column=1)  # B2: offset (+1, 0)
        await pilot.pause()
        await pilot.press("ctrl+v")
        beta = app.views[1].sheet
        assert beta["B2"].formula == "=A2*2"  # shifted, on the OTHER sheet
        assert alpha["B1"].formula == "=A1*2"  # source untouched
        assert app.views[1].dirty and not app.views[0].dirty


async def test_cut_paste_across_tabs_clears_the_source_sheet():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        alpha = app.views[0].sheet
        alpha["A1"] = 7
        await pilot.pause()
        await pilot.press("ctrl+x")
        await pilot.press("ctrl+pagedown")
        await pilot.pause()
        await pilot.press("ctrl+v")
        beta = app.views[1].sheet
        assert beta["A1"].value == 7  # moved here
        assert alpha["A1"].value is None  # cleared THERE, not on beta
        assert app.views[0].dirty and app.views[1].dirty  # both honest
        # Per-sheet undo: beta's Ctrl+Z un-pastes, alpha's log un-clears.
        assert app.views[1].undo_log.can_undo
        assert app.views[0].undo_log.can_undo


async def test_cross_sheet_cut_undo_restores_each_side():
    app = _two_sheet_app()
    async with app.run_test() as pilot:
        alpha = app.views[0].sheet
        alpha["A1"] = "=1+1"
        await pilot.pause()
        await pilot.press("ctrl+x", "ctrl+pagedown")
        await pilot.pause()
        await pilot.press("ctrl+v")
        beta = app.views[1].sheet
        assert beta["A1"].value == 2 and alpha["A1"].value is None
        await pilot.press("ctrl+z")  # active = beta: un-paste
        assert beta["A1"].value is None
        await pilot.press("ctrl+pageup")
        await pilot.pause()
        await pilot.press("ctrl+z")  # alpha's own log: un-clear
        assert alpha["A1"].value == 2 and alpha["A1"].formula == "=1+1"
