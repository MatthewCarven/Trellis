"""Hermetic parser tests for the vim keymap — no textual, no app.

The keymap is a pure function of (its own parse state, KeyPress,
KeyContext) -> Action | None. These tests feed key sequences against a
fake context and assert the Actions, the way the contract intends a
keymap package to be testable.
"""

from __future__ import annotations

import pytest

from trellis_keymap import (
    BeginEdit,
    Chain,
    EnterMode,
    Hint,
    KeyContext,
    KeyPress,
    Move,
    MoveTo,
    Operate,
    Quit,
    Redo,
    Save,
    Select,
    Undo,
    available_keymaps,
)
from trellis_tui_vim import VimKeymap

kp = KeyPress.parse


class FakeCell:
    def __init__(self, value):
        self.value = value
        self.formula = None


def ctx(
    cells=None,
    cursor=(0, 0),
    mode="normal",
    selection=None,
    viewport=20,
) -> KeyContext:
    cells = cells or {}
    used = None
    if cells:
        rows = [a[0] for a in cells]
        cols = [a[1] for a in cells]
        used = ((min(rows), min(cols)), (max(rows), max(cols)))
    return KeyContext(
        mode=mode,
        cursor=cursor,
        selection=selection,
        used_range=used,
        cell=lambda r, c: FakeCell(cells.get((r, c))),
        viewport_rows=viewport,
        viewport_cols=8,
    )


@pytest.fixture
def vim() -> VimKeymap:
    return VimKeymap()


#: A1-row data: blocks at cols 2-3 and 5.   . . a b . c
ROW = {(0, 2): "a", (0, 3): "b", (0, 5): "c"}
#: A-column data: rows 1 and 4.
COL = {(1, 0): "x", (4, 0): "y"}


# -------------------------------------------------------------- motions


def test_hjkl_and_arrows(vim):
    assert vim.handle(kp("j", "j"), ctx()) == Move(1, 0)
    assert vim.handle(kp("k", "k"), ctx()) == Move(-1, 0)
    assert vim.handle(kp("h", "h"), ctx()) == Move(0, -1)
    assert vim.handle(kp("l", "l"), ctx()) == Move(0, 1)
    assert vim.handle(kp("down"), ctx()) == Move(1, 0)
    assert vim.handle(kp("enter"), ctx()) == Move(1, 0)  # vim: Enter = down
    assert vim.handle(kp("backspace"), ctx()) == Move(0, -1)  # vim: BS = left


def test_counts_multiply_motions(vim):
    assert vim.handle(kp("3", "3"), ctx()) is None  # pending, consumed
    assert vim.handle(kp("j", "j"), ctx()) == Move(3, 0)
    vim.handle(kp("1", "1"), ctx())
    vim.handle(kp("2", "2"), ctx())
    assert vim.handle(kp("k", "k"), ctx()) == Move(-12, 0)


def test_zero_is_motion_unless_counting(vim):
    assert vim.handle(kp("0", "0"), ctx(ROW)) == MoveTo(0, 2)  # first filled
    vim.handle(kp("1", "1"), ctx())
    assert vim.handle(kp("0", "0"), ctx()) is None  # "10" still counting
    assert vim.handle(kp("j", "j"), ctx()) == Move(10, 0)


def test_row_ends(vim):
    assert vim.handle(kp("circumflex_accent", "^"), ctx(ROW)) == MoveTo(0, 2)
    assert vim.handle(kp("dollar_sign", "$"), ctx(ROW)) == MoveTo(0, 5)
    # Empty row: 0 falls back to column 0, $ stays put.
    assert vim.handle(kp("0", "0"), ctx(ROW, cursor=(7, 4))) == MoveTo(7, 0)
    assert vim.handle(kp("dollar_sign", "$"), ctx(ROW, cursor=(7, 4))) == MoveTo(7, 4)


def test_w_b_data_jumps(vim):
    # From emptiness to the next block's near edge.
    assert vim.handle(kp("w", "w"), ctx(ROW, cursor=(0, 0))) == MoveTo(0, 2)
    # Inside a block with more block ahead: to the block's end.
    assert vim.handle(kp("w", "w"), ctx(ROW, cursor=(0, 2))) == MoveTo(0, 3)
    # At a block's end: across the gap to the next block.
    assert vim.handle(kp("w", "w"), ctx(ROW, cursor=(0, 3))) == MoveTo(0, 5)
    # Nothing ahead: stay.
    assert vim.handle(kp("w", "w"), ctx(ROW, cursor=(0, 5))) == MoveTo(0, 5)
    # And the mirror.
    assert vim.handle(kp("b", "b"), ctx(ROW, cursor=(0, 5))) == MoveTo(0, 3)
    assert vim.handle(kp("2", "2"), ctx()) is None
    assert vim.handle(kp("w", "w"), ctx(ROW, cursor=(0, 0))) == MoveTo(0, 3)


def test_gg_G_column_data(vim):
    assert vim.handle(kp("G", "G"), ctx(COL, cursor=(0, 0))) == MoveTo(4, 0)
    assert vim.handle(kp("g", "g"), ctx(COL, cursor=(3, 0))) is None  # pending
    assert vim.handle(kp("g", "g"), ctx(COL, cursor=(3, 0))) == MoveTo(1, 0)
    # {n}G and {n}gg go to row n.
    vim.handle(kp("5", "5"), ctx())
    assert vim.handle(kp("G", "G"), ctx()) == MoveTo(4, 0)
    vim.handle(kp("7", "7"), ctx())
    vim.handle(kp("g", "g"), ctx())
    assert vim.handle(kp("g", "g"), ctx()) == MoveTo(6, 0)


def test_half_page(vim):
    assert vim.handle(kp("ctrl+d"), ctx(viewport=20)) == Move(10, 0)
    assert vim.handle(kp("ctrl+u"), ctx(viewport=20)) == Move(-10, 0)


# ------------------------------------------------------------ operators


def test_x_is_yank_then_clear(vim):
    a = vim.handle(kp("x", "x"), ctx(cursor=(2, 1)))
    assert a == Chain(
        (Operate("copy", ((2, 1), (2, 1))), Operate("clear", ((2, 1), (2, 1))))
    )
    vim.handle(kp("3", "3"), ctx())
    a = vim.handle(kp("x", "x"), ctx(cursor=(2, 1)))
    assert a == Chain(
        (Operate("copy", ((2, 1), (2, 3))), Operate("clear", ((2, 1), (2, 3))))
    )


def test_dd_yy_cc_row_wise(vim):
    assert vim.handle(kp("d", "d"), ctx(ROW)) is None  # pending double
    a = vim.handle(kp("d", "d"), ctx(ROW, cursor=(0, 4)))
    rect = ((0, 0), (0, 5))
    assert a == Chain((Operate("copy", rect), Operate("clear", rect)))
    vim.handle(kp("y", "y"), ctx(ROW))
    assert vim.handle(kp("y", "y"), ctx(ROW)) == Operate("copy", rect)
    vim.handle(kp("c", "c"), ctx(ROW))
    assert vim.handle(kp("c", "c"), ctx(ROW)) == Operate("change", rect)
    # 3dd takes three rows.
    vim.handle(kp("3", "3"), ctx(ROW))
    vim.handle(kp("d", "d"), ctx(ROW))
    a = vim.handle(kp("d", "d"), ctx(ROW, cursor=(1, 0)))
    assert a == Chain(
        (Operate("copy", ((1, 0), (3, 5))), Operate("clear", ((1, 0), (3, 5))))
    )


def test_broken_double_hints_and_resets(vim):
    vim.handle(kp("d", "d"), ctx())
    a = vim.handle(kp("z", "z"), ctx())
    assert isinstance(a, Hint)
    assert vim.handle(kp("j", "j"), ctx()) == Move(1, 0)  # state clean


def test_paste_undo_redo(vim):
    assert vim.handle(kp("p", "p"), ctx()) == Operate("paste")
    assert vim.handle(kp("P", "P"), ctx()) == Operate("paste")  # p = P here
    assert vim.handle(kp("u", "u"), ctx()) == Undo()
    assert vim.handle(kp("ctrl+r"), ctx()) == Redo()


# -------------------------------------------------------------- inserts


def test_insert_entries(vim):
    assert vim.handle(kp("i", "i"), ctx()) == BeginEdit(caret="start")
    assert vim.handle(kp("I", "I"), ctx()) == BeginEdit(caret="start")
    assert vim.handle(kp("a", "a"), ctx()) == BeginEdit(caret="end")
    assert vim.handle(kp("A", "A"), ctx()) == BeginEdit(caret="end")


# --------------------------------------------------------------- visual


def test_visual_extend_and_operators(vim):
    assert vim.handle(kp("v", "v"), ctx()) == EnterMode("visual")
    assert vim.handle(kp("j", "j"), ctx(mode="visual")) == Move(1, 0, extend=True)
    assert vim.handle(kp("w", "w"), ctx(ROW, cursor=(0, 0), mode="visual")) == MoveTo(
        0, 2, extend=True
    )
    sel = ((0, 0), (1, 1))
    home = MoveTo(0, 0)  # vim: the cursor lands at the region's start
    a = vim.handle(kp("y", "y"), ctx(mode="visual", selection=sel))
    assert a == Chain((Operate("copy"), EnterMode("normal"), home))
    a = vim.handle(kp("d", "d"), ctx(mode="visual", selection=sel))
    assert a == Chain(
        (Operate("copy"), Operate("clear"), EnterMode("normal"), home)
    )
    a = vim.handle(kp("p", "p"), ctx(mode="visual", selection=sel))
    assert a == Chain((Operate("paste"), EnterMode("normal"), home))


def test_visual_change_bakes_its_rect(vim):
    sel = ((1, 1), (2, 3))
    a = vim.handle(kp("c", "c"), ctx(mode="visual", selection=sel))
    assert a == Chain((EnterMode("normal"), Operate("change", sel)))


def test_visual_escape_and_toggle(vim):
    assert vim.handle(kp("escape"), ctx(mode="visual")) == EnterMode("normal")
    assert vim.handle(kp("v", "v"), ctx(mode="visual")) == EnterMode("normal")
    assert vim.handle(kp("ctrl+c"), ctx(mode="visual")) == EnterMode("normal")


def test_visual_line_tracks_its_own_end(vim):
    a = vim.handle(kp("V", "V"), ctx(ROW, cursor=(0, 3)))
    assert a == Chain((EnterMode("visual-line"), Select(((0, 0), (0, 5)))))
    # Extend down: whole rows, the keymap's own moving end.
    a = vim.handle(kp("j", "j"), ctx(ROW, cursor=(0, 3), mode="visual-line"))
    assert a == Select(((0, 0), (1, 5)))
    # Extend back up — the grid parks the cursor at bottom-right, so a
    # cursor-based recompute would stall; the internal end doesn't.
    a = vim.handle(kp("k", "k"), ctx(ROW, cursor=(1, 5), mode="visual-line"))
    assert a == Select(((0, 0), (0, 5)))
    a = vim.handle(kp("k", "k"), ctx(ROW, cursor=(0, 5), mode="visual-line"))
    assert a == Select(((0, 0), (0, 5)))  # clamped at the top


# ----------------------------------------------------------- command line


def test_command_line_echo_and_w(vim):
    assert vim.handle(kp("colon", ":"), ctx()) == EnterMode("command")
    assert vim.handle(kp("w", "w"), ctx(mode="command")) == Hint(":w")
    a = vim.handle(kp("enter"), ctx(mode="command"))
    assert a == Chain((EnterMode("normal"), Save()))


@pytest.mark.parametrize(
    "text, tail",
    [
        ("q", (Quit(),)),
        ("q!", (Quit(force=True),)),
        ("wq", (Save(), Quit())),
        ("x", (Save(), Quit())),
    ],
)
def test_command_verbs(vim, text, tail):
    vim.handle(kp("colon", ":"), ctx())
    for ch in text:
        vim.handle(kp(ch, ch), ctx(mode="command"))
    a = vim.handle(kp("enter"), ctx(mode="command"))
    assert a == Chain((EnterMode("normal"),) + tail)


def test_command_goto_row_keeps_column(vim):
    vim.handle(kp("colon", ":"), ctx())
    for ch in "15":
        vim.handle(kp(ch, ch), ctx(mode="command"))
    a = vim.handle(kp("enter"), ctx(mode="command", cursor=(0, 2)))
    assert a == Chain((EnterMode("normal"), MoveTo(14, 2)))


def test_command_unknown_backspace_escape(vim):
    vim.handle(kp("colon", ":"), ctx())
    vim.handle(kp("z", "z"), ctx(mode="command"))
    a = vim.handle(kp("enter"), ctx(mode="command"))
    assert a == Chain((EnterMode("normal"), Hint("not an editor command: z")))
    # Backspace past ':' leaves command mode, like vim.
    vim.handle(kp("colon", ":"), ctx())
    vim.handle(kp("w", "w"), ctx(mode="command"))
    assert vim.handle(kp("backspace"), ctx(mode="command")) == Hint(":")
    assert vim.handle(kp("backspace"), ctx(mode="command")) == EnterMode("normal")
    vim.handle(kp("colon", ":"), ctx())
    assert vim.handle(kp("escape"), ctx(mode="command")) == EnterMode("normal")


def test_command_mode_is_modal(vim):
    vim.handle(kp("colon", ":"), ctx())
    vim.handle(kp("w", "w"), ctx(mode="command"))
    # Arrows etc. stay consumed (echo back) — no grid moves mid-command.
    assert vim.handle(kp("down"), ctx(mode="command")) == Hint(":w")


# ------------------------------------------------------------- boundary


def test_unmapped_keys_are_inert_or_chrome(vim):
    # Unmapped printables: None — and under one-path, None means inert
    # for grid semantics (nothing falls through to an Excel edit).
    assert vim.handle(kp("e", "e"), ctx()) is None
    assert vim.handle(kp("o", "o"), ctx()) is None  # deferred with reasons
    # Chrome runs on: the keymap declines the window keys.
    for key in ("ctrl+s", "ctrl+q", "ctrl+t", "ctrl+w", "ctrl+pagedown"):
        assert vim.handle(kp(key), ctx()) is None, key
    # Ctrl+C never reaches the app's quit: it's Esc here.
    assert vim.handle(kp("ctrl+c"), ctx()) == EnterMode("normal")


def test_metadata_and_registry():
    vim = VimKeymap()
    assert vim.name == "vim"
    assert vim.initial_mode() == "normal"
    assert vim.key_table()
    # Hermetic registry check: the factory contract (the entry point
    # itself is proved installed by scripts/tier2_discovery_check.sh).
    assert callable(VimKeymap)
    assert "excel" in available_keymaps()
