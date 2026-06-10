"""Part 10 row 2: the keymap contract + the one key path.

Three layers, mirroring the Part 3 contract-test discipline:

- **Hermetic contract tests** — ``KeyPress.parse``, the ``ExcelKeymap``
  table, and the registry, no app at all.
- **The hook proved from OUTSIDE** — a toy keymap (vim-flavoured ``j``)
  drives the app through ``TrellisApp(keymap=...)``: keys mean what the
  keymap says (one path, no hardcoded fall-through), keys it declines
  fall to chrome (DECIDED #7), and ``Hint``/``BeginEdit(caret=...)``
  round-trip through the executor.
- **The chrome seams** — the ``--keymap``/``--vim`` CLI and the
  ``-- INSERT --`` mode indicator.
"""

from __future__ import annotations

import pytest
from textual.widgets import Tabs

from trellis import Workbook
from trellis_tui import TrellisApp
from trellis_tui import keymap as km
from trellis_tui.app import StatusBar, build_app
from trellis_tui.editor import CellEditor


def make_app(**kwargs) -> TrellisApp:
    wb = Workbook()
    wb.add_sheet("Sheet1")
    return TrellisApp(wb, **kwargs)


def ctx(used=None, selection=None, mode="default") -> km.KeyContext:
    return km.KeyContext(
        mode=mode,
        cursor=(0, 0),
        selection=selection,
        used_range=used,
        cell=lambda r, c: None,
        viewport_rows=20,
        viewport_cols=8,
    )


# ------------------------------------------------------------ KeyPress


def test_keypress_parse_splits_modifiers():
    kp = km.KeyPress.parse("ctrl+shift+z")
    assert (kp.key, kp.ctrl, kp.shift, kp.alt) == ("z", True, True, False)


def test_keypress_parse_plain_and_char():
    kp = km.KeyPress.parse("a", "a")
    assert (kp.key, kp.char, kp.ctrl) == ("a", "a", False)
    assert km.KeyPress.parse("escape").char is None
    assert km.KeyPress.parse("alt+r").alt is True


# ---------------------------------------------------------- ExcelKeymap


@pytest.fixture
def excel() -> km.ExcelKeymap:
    return km.ExcelKeymap()


def test_excel_arrows_move(excel):
    assert excel.handle(km.KeyPress.parse("down"), ctx()) == km.Move(1, 0)
    assert excel.handle(km.KeyPress.parse("left"), ctx()) == km.Move(0, -1)
    assert excel.handle(km.KeyPress.parse("shift+up"), ctx()) == km.Move(
        -1, 0, extend=True
    )
    assert excel.handle(km.KeyPress.parse("ctrl+home"), ctx()) == km.MoveTo(0, 0)


def test_excel_printables_begin_edit(excel):
    assert excel.handle(km.KeyPress.parse("a", "a"), ctx()) == km.BeginEdit(seed="a")
    assert excel.handle(km.KeyPress.parse("equals_sign", "="), ctx()) == km.BeginEdit(
        seed="="
    )


def test_excel_edit_keys(excel):
    revise = km.BeginEdit()
    assert revise.seed is None  # revise-edit: prefilled, full fidelity
    assert excel.handle(km.KeyPress.parse("f2"), ctx()) == revise
    assert excel.handle(km.KeyPress.parse("enter"), ctx()) == revise
    assert excel.handle(km.KeyPress.parse("backspace"), ctx()) == km.BeginEdit(seed="")
    assert excel.handle(km.KeyPress.parse("delete"), ctx()) == km.Operate("clear")


def test_excel_clipboard_undo_fill(excel):
    table = {
        "ctrl+c": km.Operate("copy"),
        "ctrl+x": km.Operate("cut"),
        "ctrl+v": km.Operate("paste"),
        "ctrl+z": km.Undo(),
        "ctrl+y": km.Redo(),
        "ctrl+shift+z": km.Redo(),
        "ctrl+d": km.Fill("down"),
        "ctrl+r": km.Fill("right"),
    }
    for key, expected in table.items():
        assert excel.handle(km.KeyPress.parse(key), ctx()) == expected, key


def test_excel_select_all_uses_used_range(excel):
    rect = ((0, 0), (3, 2))
    assert excel.handle(km.KeyPress.parse("ctrl+a"), ctx(used=rect)) == km.Select(rect)
    assert excel.handle(km.KeyPress.parse("ctrl+a"), ctx(used=None)) is None


def test_excel_escape_and_declined_keys(excel):
    assert excel.handle(km.KeyPress.parse("escape"), ctx()) == km.EnterMode("default")
    # Chrome + framework keys are NOT the keymap's (DECIDED #7): None
    # lets them run on to the app bindings / ScrollView paging.
    for key in ("ctrl+t", "ctrl+w", "ctrl+s", "ctrl+q", "pagedown", "tab"):
        assert excel.handle(km.KeyPress.parse(key), ctx()) is None, key
    assert excel.handle(km.KeyPress.parse("alt+r"), ctx()) is None  # Alt unbound


def test_excel_metadata(excel):
    assert excel.name == "excel"
    assert excel.initial_mode() == "default"
    assert excel.key_table()  # help rows exist


# ------------------------------------------------------------- registry


def test_available_keymaps_has_builtin():
    maps = km.available_keymaps()
    assert "excel" in maps
    assert isinstance(maps["excel"](), km.ExcelKeymap)


def test_load_keymap_unknown_lists_available():
    with pytest.raises(KeyError, match="unknown keymap 'nope'.*excel"):
        km.load_keymap("nope")


def test_entry_point_cannot_shadow_builtin(monkeypatch):
    class FakeEP:
        name = "excel"

        @staticmethod
        def load():  # pragma: no cover - must never be called the winner
            return lambda: "shadowed"

    monkeypatch.setattr(km, "entry_points", lambda group: [FakeEP()])
    assert isinstance(km.available_keymaps()["excel"](), km.ExcelKeymap)


# ------------------------------------------------------------------ CLI


def test_build_app_keymap_flags(capsys):
    app = build_app(["--keymap", "excel"])
    assert isinstance(app.active_keymap, km.ExcelKeymap)
    app = build_app(["--keymap=excel"])
    assert isinstance(app.active_keymap, km.ExcelKeymap)


def test_build_app_unknown_keymap_errors(capsys):
    assert build_app(["--vim"]) is None  # trellis-tui-vim not installed here
    out = capsys.readouterr().out
    assert "unknown keymap 'vim'" in out and "excel" in out
    assert build_app(["--keymap"]) is None  # missing value
    assert "unknown keymap ''" in capsys.readouterr().out


# ------------------------------------------- the hook, proved from outside


class ToyKeymap:
    """A vim-flavoured toy: proves the active keymap is the sole
    authority for grid keys. ``j`` moves (a printable that would start
    an edit under Excel!), ``q`` hints, ``i`` opens a caret-start edit,
    and everything else — including other printables — is declined."""

    name = "toy"

    def initial_mode(self) -> str:
        return "normal"

    def handle(self, key: km.KeyPress, ctx: km.KeyContext):
        if key.char == "j":
            return km.Move(1, 0)
        if key.char == "q":
            return km.Hint("toy says hi")
        if key.char == "i":
            return km.BeginEdit(caret="start")
        return None

    def key_table(self):
        return [("j", "down"), ("q", "hint"), ("i", "insert")]


async def test_toy_keymap_owns_the_keys():
    app = make_app(keymap=ToyKeymap())
    async with app.run_test() as pilot:
        grid = app.active_view.grid
        await pilot.press("j")  # moves — does NOT start an edit
        assert grid.cursor_coordinate.row == 1
        assert not app.query_one("FormulaBar").has_class("editing")
        await pilot.press("q")
        assert app.query_one(StatusBar).state[2] == "toy says hi"


async def test_toy_keymap_declined_printable_is_inert():
    # No hardcoded fall-through: a printable the keymap declines does
    # NOT start an Excel-style replace-edit. One path (DECIDED #6).
    app = make_app(keymap=ToyKeymap())
    async with app.run_test() as pilot:
        await pilot.press("5")
        assert not app.query_one("FormulaBar").has_class("editing")
        assert app.sheet["A1"].value is None


async def test_toy_keymap_chrome_still_flows():
    # Keys the keymap declines run on to the app's chrome bindings:
    # Ctrl+T still makes a sheet under a keymap that knows nothing of it.
    app = make_app(keymap=ToyKeymap())
    async with app.run_test() as pilot:
        await pilot.press("ctrl+t")
        assert len(app.views) == 2


async def test_begin_edit_caret_start():
    app = make_app(keymap=ToyKeymap())
    async with app.run_test() as pilot:
        app.sheet["A1"] = "hello"
        await pilot.pause()
        await pilot.press("i")
        editor = app.query_one(CellEditor)
        assert editor.value == "hello"  # revise-edit prefill
        assert editor.cursor_position == 0  # caret="start" (vim's i)


async def test_executor_is_shared_with_chrome():
    # The same executor chrome bindings use is callable with the same
    # Actions a keymap returns — Sheet("next") flips the active tab.
    wb = Workbook()
    wb.add_sheet("alpha")
    wb.add_sheet("beta")
    app = TrellisApp(wb)
    async with app.run_test() as pilot:
        assert app.sheet.name == "alpha"
        await app._execute(km.Sheet("next"))
        await pilot.pause()
        assert app.sheet.name == "beta"
        app.query_one(Tabs)  # the switch went through the single path


# ----------------------------------------------------- the mode indicator


async def test_mode_indicator_hides_resting_shows_insert():
    app = make_app()  # default ExcelKeymap
    async with app.run_test() as pilot:
        bar = app.query_one(StatusBar)
        assert app.mode == "default"
        assert bar.mode_shown == ""  # resting mode renders as nothing
        await pilot.press("5")  # type-to-edit: the editor IS Insert
        assert app.mode == "insert"
        assert bar.mode_shown == "insert"
        await pilot.press("enter")
        assert app.mode == "default"
        assert bar.mode_shown == ""
        assert app.sheet["A1"].value == 5  # and the edit still committed
