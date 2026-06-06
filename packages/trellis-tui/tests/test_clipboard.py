"""Pilot tests for the internal clipboard (Part 6 #5).

Copy snapshots (formula text | raw value per cell + the TSV mirror);
paste is Excel-faithful: relative refs shift by the paste offset
(``$`` pins hold), a 1×1 payload fills the whole selection, blocks
anchor at the target top-left, empty source cells clear targets, and
every paste is ONE ``sheet.batch()``.
"""

from __future__ import annotations

from textual.coordinate import Coordinate

from trellis import Cell, Workbook
from trellis_tui.app import TrellisApp, _tsv_field
from trellis_tui.grid import SheetGrid


def _app(populate=None) -> TrellisApp:
    wb = Workbook()
    sh = wb.add_sheet("S")
    if populate:
        populate(sh)
    return TrellisApp(wb)


def _status_message(app: TrellisApp) -> str:
    from trellis_tui.app import StatusBar

    return app.query_one(StatusBar).state[2]


# ----------------------------------------------------------------- copy


async def test_copy_snapshots_formulas_and_raw_values():
    def populate(sh):
        sh["A1"] = 10
        sh["B1"] = "=A1*2"
        sh["A2"] = True
        sh["B2"] = 1.5

    app = _app(populate)
    async with app.run_test() as pilot:
        await pilot.press("shift+right", "shift+down", "ctrl+c")  # A1:B2
        clip = app.sheet_clipboard
        assert clip is not None and clip.mode == "copy"
        assert clip.source_anchor == (0, 0)
        (a1, b1), (a2, b2) = clip.cells
        assert a1 == (None, 10)
        assert b1[0] == "=A1*2"  # formula text travels; value just rides
        assert a2 == (None, True) and isinstance(a2[1], bool)
        assert b2 == (None, 1.5) and isinstance(b2[1], float)
        assert clip.tsv == "10\t20\nTRUE\t1.5"  # display text, not repr
        assert _status_message(app) == "copied A1:B2"


async def test_copy_without_selection_copies_cursor_cell():
    app = _app(lambda sh: sh.set((0, 0), 42))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        assert app.sheet_clipboard.cells == (((None, 42),),)
        assert _status_message(app) == "copied A1"


async def test_copy_is_a_snapshot_not_live():
    app = _app(lambda sh: sh.set((0, 0), 10))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        app.sheet["A1"] = 99  # source changes after the copy
        await pilot.press("down", "ctrl+v")
        assert app.sheet["A2"].value == 10  # the snapshot, not the live cell


def test_tsv_field_flattens_grid_breakers():
    assert _tsv_field("a\tb") == "a b"
    assert _tsv_field("a\nb\rc") == "a b c"
    assert _tsv_field("plain") == "plain"


# ---------------------------------------------------------------- paste


async def test_paste_shifts_relative_refs_in_one_batch():
    def populate(sh):
        sh["A1"] = 10
        sh["A3"] = 7
        sh["B1"] = "=A1*2"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        batches: list = []
        app.sheet.on("sheet:batch", lambda **ev: batches.append(ev))
        grid.move_cursor(row=0, column=1)  # B1
        await pilot.pause()
        await pilot.press("ctrl+c")
        grid.move_cursor(row=2, column=1)  # B3
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert app.sheet["B3"].formula == "=A3*2"  # shifted by (+2, 0)
        assert app.sheet["B3"].value == 14  # and re-evaluated (A3=7)
        assert len(batches) == 1, "paste must be ONE batch"
        assert app.dirty is True
        assert _status_message(app) == "pasted B3"


async def test_paste_respects_dollar_pins():
    def populate(sh):
        sh["A1"] = 100
        sh["B1"] = "=$A$1+A1"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=0, column=1)
        await pilot.pause()
        await pilot.press("ctrl+c")
        grid.move_cursor(row=1, column=2)  # C2: offset (+1, +1)
        await pilot.pause()
        await pilot.press("ctrl+v")
        assert app.sheet["C2"].formula == "=$A$1+B2"  # pin holds, rel shifts


async def test_paste_off_edge_becomes_ref_error_value():
    def populate(sh):
        sh["B2"] = "=B1"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        grid.move_cursor(row=1, column=1)  # B2
        await pilot.pause()
        await pilot.press("ctrl+c", "ctrl+home", "ctrl+v")  # paste at A1
        cell = app.sheet["A1"]
        assert cell.formula == "=#REF!"  # ref shifted off the sheet edge
        assert getattr(cell.value, "code", None) == "#REF!"  # error value


async def test_single_cell_payload_fills_the_selection():
    def populate(sh):
        sh["B1"] = 5
        sh["A1"] = "=B1"

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("ctrl+c")  # copy A1 (cursor cell)
        grid.move_cursor(row=0, column=2)  # C1
        await pilot.pause()
        await pilot.press("shift+right", "shift+down")  # C1:D2
        batches: list = []
        app.sheet.on("sheet:batch", lambda **ev: batches.append(ev))
        await pilot.press("ctrl+v")
        # each target gets the formula shifted by ITS offset from A1
        assert app.sheet["C1"].formula == "=D1"
        assert app.sheet["D1"].formula == "=E1"
        assert app.sheet["C2"].formula == "=D2"
        assert app.sheet["D2"].formula == "=E2"
        assert len(batches) == 1
        assert _status_message(app) == "pasted C1:D2"


async def test_block_paste_anchors_at_selection_top_left():
    def populate(sh):
        sh["A1"] = 1
        sh["B1"] = 2
        sh["A2"] = 3
        sh["B2"] = 4

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+right", "shift+down", "ctrl+c")  # A1:B2
        grid.move_cursor(row=4, column=3)  # D5
        await pilot.pause()
        # an oversized selection: the block's SHAPE wins, anchored top-left
        await pilot.press("shift+down", "shift+down", "shift+down", "ctrl+v")
        for a1, expected in (("D5", 1), ("E5", 2), ("D6", 3), ("E6", 4)):
            assert app.sheet[a1].value == expected
        assert app.sheet["D8"].value is None  # selection shape ignored
        assert _status_message(app) == "pasted D5:E6"


async def test_paste_empty_source_cells_clear_targets():
    def populate(sh):
        sh["B1"] = 7  # A1 stays empty
        sh["C1"] = 88
        sh["D1"] = 99

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("shift+right", "ctrl+c")  # A1:B1 (A1 empty)
        grid.move_cursor(row=0, column=2)  # C1
        await pilot.pause()
        await pilot.press("ctrl+v")
        assert app.sheet["C1"].value is None  # cleared by the empty A1
        assert app.sheet["D1"].value == 7
        assert app.sheet.used_range() is not None


async def test_pasted_equals_string_stays_a_string():
    app = _app(lambda sh: sh.set((0, 0), Cell(value="=not a formula")))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c", "down", "ctrl+v")
        cell = app.sheet["A2"]
        assert cell.value == "=not a formula"
        assert cell.formula is None  # the sugar did NOT promote it


async def test_paste_with_empty_clipboard_is_a_noop():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+v")
        assert app.dirty is False
        assert app.sheet.used_range() is None


async def test_out_of_window_block_paste_grows_to_cover():
    def populate(sh):
        for r in range(10):
            sh.set((r, 0), r + 1)

    app = _app(populate)
    async with app.run_test() as pilot:
        grid = app.query_one(SheetGrid)
        await pilot.press("ctrl+a", "ctrl+c")  # copy A1:A10
        await pilot.press("escape")
        grid.move_cursor(row=95, column=0)
        await pilot.pause()
        await pilot.press("ctrl+v")  # targets A96:A105 — beyond the window
        await pilot.pause()
        assert app.sheet["A105"].value == 10
        assert grid.row_count >= 105  # rebuild-to-cover caught the batch
        assert grid.get_cell_at(Coordinate(104, 0)).plain == "10"
