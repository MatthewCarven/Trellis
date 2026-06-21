"""Pilot + unit tests for CSV save and app chrome (Part 5 #6)."""

from __future__ import annotations

from trellis import Workbook
from trellis_tui.app import SaveAsScreen, StatusBar, TrellisApp, build_app
from trellis_tui.editor import FormulaBar
from textual.widgets import Input


def _app(populate=None, path=None) -> TrellisApp:
    wb = Workbook()
    sh = wb.add_sheet("S")
    if populate:
        populate(sh)
    return TrellisApp(wb, path=path)


def _status(app) -> tuple[str, bool, str]:
    return app.query_one(StatusBar).state


# ----------------------------------------------------------- build_app


def test_build_app_version_prints_and_returns_none(capsys):
    assert build_app(["--version"]) is None
    assert "trellis-tui" in capsys.readouterr().out


def test_build_app_no_args_is_pathless_empty():
    app = build_app([])
    assert app.path is None
    assert app.sheet.used_range() is None


def test_build_app_loads_existing_csv(tmp_path):
    p = tmp_path / "in.csv"
    p.write_text("7,8\n", encoding="utf-8")
    app = build_app([str(p)])
    assert app.path == str(p)
    assert app.sheet["B1"].value == 8


def test_build_app_missing_path_opens_empty_with_path_remembered(tmp_path):
    p = tmp_path / "not-yet.csv"
    app = build_app([str(p)])
    assert app.path == str(p)
    assert app.sheet.used_range() is None  # nothing loaded, nothing crashed


def test_build_app_unreadable_directory_aborts(tmp_path, capsys):
    """A path that exists but is a directory: clean message, no launch."""
    app = build_app([str(tmp_path)])  # tmp_path is a dir, so open() -> OSError
    assert app is None
    assert "cannot read" in capsys.readouterr().err


def test_build_app_undecodable_bytes_aborts(tmp_path, capsys):
    """Bytes that aren't valid UTF-8 abort with a message, not a traceback."""
    p = tmp_path / "bad.csv"
    p.write_bytes(b"\xff\xff\xff")
    app = build_app([str(p)])
    assert app is None
    err = capsys.readouterr().err
    assert "cannot read" in err and "bad.csv" in err


async def test_new_file_status_message(tmp_path):
    p = tmp_path / "fresh.csv"
    app = _app(path=str(p))
    async with app.run_test():
        assert "new file" in _status(app)[2]


# ----------------------------------------------------------------- save


async def test_ctrl_s_with_path_saves_and_clears_dirty(tmp_path):
    p = tmp_path / "out.csv"
    app = _app(path=str(p))
    async with app.run_test() as pilot:
        app.sheet["A1"] = 5
        assert app.dirty is True
        await pilot.press("ctrl+s")
        assert p.read_text(encoding="utf-8").strip() == "5"
        assert app.dirty is False
        label, dirty, message = _status(app)
        assert dirty is False and message == f"saved {p}"


async def test_ctrl_s_pathless_opens_modal_then_saves(tmp_path):
    target = tmp_path / "picked.csv"
    app = _app(lambda sh: sh.set((0, 0), 1))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SaveAsScreen)
        app.screen.query_one(Input).value = str(target)
        await pilot.press("enter")
        await pilot.pause()
        assert target.read_text(encoding="utf-8").strip() == "1"
        assert app.path == str(target)
        assert app.dirty is False


async def test_save_modal_escape_cancels(tmp_path):
    app = _app(lambda sh: sh.set((0, 0), 1))
    async with app.run_test() as pilot:
        app.dirty = True
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SaveAsScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SaveAsScreen)
        assert app.path is None and app.dirty is True
        assert not list(tmp_path.iterdir())  # nothing written


async def test_save_failure_reports_and_keeps_running(tmp_path):
    app = _app(lambda sh: sh.set((0, 0), 1), path=str(tmp_path))  # a DIRECTORY
    async with app.run_test() as pilot:
        app.dirty = True
        await pilot.press("ctrl+s")
        assert app.is_running
        assert app.dirty is True
        assert "save failed" in _status(app)[2]


async def test_save_while_editing_saves_committed_state(tmp_path):
    p = tmp_path / "mid.csv"
    app = _app(lambda sh: sh.set((0, 0), 1), path=str(p))
    async with app.run_test() as pilot:
        await pilot.press("9")  # editing A1, uncommitted
        await pilot.press("ctrl+s")
        assert p.read_text(encoding="utf-8").strip() == "1"  # committed state
        assert app.query_one(FormulaBar).editing  # edit survives the save


# ----------------------------------------------------------------- quit


async def test_quit_warns_when_dirty_then_quits():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("5", "enter")  # make it dirty
        await pilot.press("ctrl+q")
        assert app.is_running  # warned, not quit
        assert "again to quit" in _status(app)[2]
        await pilot.press("ctrl+q")  # armed: this one quits


async def test_new_edit_rearms_the_quit_warning():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("5", "enter")
        await pilot.press("ctrl+q")  # warn (arms)
        await pilot.press("7", "enter")  # new write disarms
        assert app._quit_armed is False
        await pilot.press("ctrl+q")
        assert app.is_running  # warns again rather than quitting
        assert "again to quit" in _status(app)[2]


async def test_clean_quit_exits_immediately():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+q")  # not dirty: straight out


# --------------------------------------------------------------- status


async def test_recalc_note_shows_trigger():
    def populate(sh):
        sh["A1"] = 2
        sh["B1"] = "=A1*3"

    app = _app(populate)
    async with app.run_test() as pilot:
        await pilot.press("9", "enter")  # replace A1 -> recalc cascade
        assert app.sheet["B1"].value == 27
        assert _status(app)[2] == "recalc B1 ← A1"


async def test_dirty_marker_in_status():
    app = _app()
    async with app.run_test() as pilot:
        assert _status(app)[1] is False
        await pilot.press("5", "enter")
        label, dirty, _ = _status(app)
        assert dirty is True
        assert label == "(no file)"


# ------------------------------------------------- formula round-trip (v1.1)
# Matthew's first real run found the gap: CSV is the TUI's only format, so
# the engine's values-only CSV policy silently flattened formulas on save.
# The TUI now opts in to the engine's formulas= flag on both paths.


async def test_save_writes_formula_source_text(tmp_path):
    p = tmp_path / "out.csv"
    app = _app(path=str(p))
    async with app.run_test() as pilot:
        app.sheet["A1"] = 10
        app.sheet["B1"] = "=A1*3"
        await pilot.press("ctrl+s")
        assert p.read_text(encoding="utf-8").strip() == "10,=A1*3"


async def test_round_trip_save_then_reopen_keeps_formulas_live(tmp_path):
    """The full loop the first run broke: save in the TUI, reopen in the
    TUI, and the formula is still a formula — recalculating, F2-editable."""
    p = tmp_path / "sheet.csv"
    app = _app(path=str(p))
    async with app.run_test() as pilot:
        app.sheet["A1"] = 10
        app.sheet["B1"] = "=A1*3"
        await pilot.press("ctrl+s")

    reopened = build_app([str(p)])
    assert reopened.sheet["B1"].formula == "=A1*3"
    assert reopened.sheet["B1"].value == 30
    reopened.sheet["A1"] = 100          # live engine, not a fossil
    assert reopened.sheet["B1"].value == 300
