"""Hermetic contract tests for trellis-keymap.

No textual, no app, no engine — a fake ``KeyContext`` drives ``ExcelKeymap``
and the registry. This is the contract's testability promise: the whole key
language is exercised in-process in milliseconds. (Lifted and trimmed from
trellis-tui's test_keymap.py when the contract was extracted, S40.)
"""

from __future__ import annotations

import pytest

from trellis_keymap import (
    ENTRY_POINT_GROUP,
    BeginEdit,
    ExcelKeymap,
    Fill,
    KeyContext,
    KeyPress,
    Move,
    MoveTo,
    Operate,
    Select,
    Undo,
    available_keymaps,
    load_keymap,
)


def ctx(**over) -> KeyContext:
    base = dict(
        mode="default",
        cursor=(0, 0),
        selection=None,
        used_range=((0, 0), (2, 2)),
        cell=lambda r, c: None,
        viewport_rows=10,
        viewport_cols=5,
    )
    base.update(over)
    return KeyContext(**base)


class TestKeyPressParse:
    def test_plain_key_with_char(self):
        k = KeyPress.parse("a", char="a")
        assert (k.key, k.char, k.ctrl, k.alt, k.shift) == ("a", "a", False, False, False)

    def test_ctrl_shift(self):
        k = KeyPress.parse("ctrl+shift+z")
        assert k.key == "z" and k.ctrl and k.shift and not k.alt

    def test_meta_reads_as_alt(self):
        assert KeyPress.parse("meta+x").alt is True

    def test_non_printable_has_no_char(self):
        assert KeyPress.parse("enter").char is None


class TestExcelKeymap:
    def setup_method(self):
        self.km = ExcelKeymap()

    def test_identity(self):
        assert self.km.name == "excel"
        assert self.km.initial_mode() == "default"
        assert self.km.key_table()  # non-empty help rows

    def test_arrows_move(self):
        assert self.km.handle(KeyPress.parse("up"), ctx()) == Move(-1, 0)
        assert self.km.handle(KeyPress.parse("right"), ctx()) == Move(0, 1)

    def test_shift_arrow_extends(self):
        assert self.km.handle(KeyPress.parse("shift+down"), ctx()) == Move(1, 0, extend=True)

    def test_ctrl_home_jumps_to_a1(self):
        assert self.km.handle(KeyPress.parse("ctrl+home"), ctx()) == MoveTo(0, 0)

    def test_ctrl_a_selects_used_range(self):
        assert self.km.handle(KeyPress.parse("ctrl+a"), ctx()) == Select(((0, 0), (2, 2)))

    def test_ctrl_a_on_empty_sheet_is_none(self):
        assert self.km.handle(KeyPress.parse("ctrl+a"), ctx(used_range=None)) is None

    def test_printable_replaces_cell(self):
        assert self.km.handle(KeyPress.parse("k", char="k"), ctx()) == BeginEdit(seed="k")

    def test_clipboard_and_fill(self):
        assert self.km.handle(KeyPress.parse("ctrl+c"), ctx()) == Operate("copy")
        assert self.km.handle(KeyPress.parse("ctrl+d"), ctx()) == Fill("down")

    def test_undo(self):
        assert self.km.handle(KeyPress.parse("ctrl+z"), ctx()) == Undo()

    def test_alt_is_never_ours(self):
        assert self.km.handle(KeyPress.parse("alt+r"), ctx()) is None

    def test_unbound_key_runs_on(self):
        # ctrl+t is a chrome key — the keymap declines it (None = runs on).
        assert self.km.handle(KeyPress.parse("ctrl+t"), ctx()) is None


class TestRegistry:
    def test_excel_is_builtin(self):
        assert "excel" in available_keymaps()

    def test_load_excel(self):
        assert isinstance(load_keymap("excel"), ExcelKeymap)

    def test_unknown_raises_listing_available(self):
        with pytest.raises(KeyError, match="excel"):
            load_keymap("nope")

    def test_group_renamed_to_this_package(self):
        assert ENTRY_POINT_GROUP == "trellis_keymap.keymaps"
