"""Scaffold tests: package wiring + the app boots headless (Pilot).

The real suites (grid sync #4, editing #5, CSV/chrome #6) replace and
extend these as the corresponding parts land. ``asyncio_mode = "auto"``
(pyproject) lets the async tests run bare.
"""

from __future__ import annotations

import trellis_tui
from trellis_tui.app import TrellisApp, main


def test_version():
    assert isinstance(trellis_tui.__version__, str) and trellis_tui.__version__


def test_main_version_flag(capsys):
    assert main(["--version"]) == 0
    assert trellis_tui.__version__ in capsys.readouterr().out


async def test_app_boots_empty_and_quits():
    app = TrellisApp()
    async with app.run_test() as pilot:
        sheet = next(iter(app.workbook.sheets()))
        assert sheet.used_range() is None  # fresh workbook is empty
        assert app.path is None
        await pilot.press("ctrl+q")


async def test_app_holds_a_live_engine_workbook(tmp_path):
    """The engine is the model: a CSV-loaded workbook computes like a REPL's."""
    p = tmp_path / "t.csv"
    p.write_text("10,1\n20,2\n", encoding="utf-8")
    from trellis import read_csv

    app = TrellisApp(read_csv(p), path=str(p))
    async with app.run_test():
        sheet = next(iter(app.workbook.sheets()))
        assert sheet["A2"].value == 20
        sheet["C1"] = "=SUM(A1:A2)"   # live engine: recalc works in-app
        assert sheet["C1"].value == 30
        assert sheet.used_range() is not None
