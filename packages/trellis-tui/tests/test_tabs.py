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
