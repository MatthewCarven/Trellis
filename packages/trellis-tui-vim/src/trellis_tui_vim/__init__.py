"""trellis-tui-vim — the vim keymap for the Trellis TUI (design.md Part 10).

The reference *keymap plugin*: a whole alternative key language behind
the TUI's keymap hook, registered under the ``trellis_tui.keymaps``
entry point and selected with ``trellis --vim`` (or ``--keymap vim``).
It proves the hook from outside the way mathpack proves the engine's
entry point — this package imports ONLY the contract
(``trellis_tui.keymap``), never textual, never the app.

The shape of the thing: the TUI was already half-modal (Insert = the
formula-bar editor, Visual = the selection model, Normal = grid focus),
so this keymap mostly *names* machinery that exists. The parse state a
static table can't hold — pending counts, the ``dd``/``gg`` doubles,
the ``:`` command buffer, visual-line's moving end — lives on the
keymap instance, which is exactly why the contract is a stateful
``handle()`` and not a dict.

Vim decisions made here (the design left them "vim-internal, settled at
build"):

- **Delete is yank**, like real vim: ``x``/``dd``/visual ``d`` return
  ``Chain((copy, clear))`` — so ``dd`` then ``p`` moves a row. (The
  design sketch said "d/x clear"; vim users' fingers say otherwise.)
- **Counts × motions** work (``3j``, ``5G``, ``2w``, ``3x``, ``3dd``);
  counts × *operators-pending-motions* (``d3j``) don't exist because
  operator+motion composition isn't in the v1 subset — operators take
  doubles (``dd``) or the Visual selection, per the design.
- **``c`` doesn't yank** (``cc``/visual ``c`` = clear + open the
  editor); change-then-paste-the-old is a refinement nobody asked for.
- **``p`` and ``P`` are the same paste** — the grid pastes *at* the
  cursor (Excel's model); before/after has no cell-grid meaning.
- **Visual-line tracks its own moving end** (``j``/``k`` recompute the
  whole-row rect from an internal cursor): the grid's selection always
  parks the cursor at the rect's bottom-right, so extending *upward*
  would otherwise stall against the anchor row.
- **Visual operators park the cursor at the region's start** (vim's
  yank/delete behavior) — a trailing ``MoveTo`` in the operator chain.
- **``Ctrl+C`` ≈ ``Esc``** (back to Normal), as in vim — and so it can
  never fall through to the app's quit binding mid-thought.
- **``Enter``** moves down (vim), **``Backspace``** moves left (vim) —
  Excel's revise-edit lives on ``i``/``a`` instead.

Deferred with the design: ``o``/``O`` (need ``Sheet.insert_row`` — a
core part), search, ``f``/``t``, marks, registers, macros, ``.``.
"""

from __future__ import annotations

from trellis_tui.keymap import (
    Action,
    BeginEdit,
    Chain,
    EnterMode,
    Hint,
    KeyContext,
    KeyPress,
    KeyRow,
    Move,
    MoveTo,
    Operate,
    Quit,
    Redo,
    Save,
    Select,
    Undo,
)

__version__ = "0.1.0"

__all__ = ["VimKeymap", "__version__"]


# ----------------------------------------------------------- sheet reading
#
# All read-only, all through the KeyContext — the keymap never writes.


def _occupied(ctx: KeyContext, row: int, col: int) -> bool:
    if row < 0 or col < 0:
        return False
    cell = ctx.cell(row, col)
    return cell is not None and (
        getattr(cell, "value", None) is not None
        or getattr(cell, "formula", None) is not None
    )


def _row_first(ctx: KeyContext, row: int) -> int:
    """``0``/``^``: first non-empty column in the row (else column 0)."""
    if ctx.used_range is None:
        return 0
    (_, c0), (_, c1) = ctx.used_range
    for col in range(c0, c1 + 1):
        if _occupied(ctx, row, col):
            return col
    return 0


def _row_last(ctx: KeyContext, row: int) -> int:
    """``$``: last non-empty column in the row (else stay put)."""
    if ctx.used_range is None:
        return ctx.cursor[1]
    (_, c0), (_, c1) = ctx.used_range
    for col in range(c1, c0 - 1, -1):
        if _occupied(ctx, row, col):
            return col
    return ctx.cursor[1]


def _jump(ctx: KeyContext, row: int, col: int, step: int) -> int:
    """``w``/``b``: the Excel Ctrl+arrow data jump along the row.

    On a block with more block ahead: to the block's end. On a block
    edge (or emptiness): to the next block's near edge. Nothing there:
    stay. Bounded by column 0 and the used range's right edge.
    """
    if ctx.used_range is None:
        return col
    hi = ctx.used_range[1][1]

    def occ(c: int) -> bool:
        return 0 <= c <= hi and _occupied(ctx, row, c)

    if occ(col) and occ(col + step):
        c = col
        while occ(c + step):
            c += step
        return c
    c = col + step
    while 0 <= c <= hi and not occ(c):
        c += step
    return c if 0 <= c <= hi else col


def _col_top(ctx: KeyContext, col: int) -> int:
    """``gg``: first row with data in this column (else row 0)."""
    if ctx.used_range is None:
        return 0
    for row in range(0, ctx.used_range[1][0] + 1):
        if _occupied(ctx, row, col):
            return row
    return 0


def _col_bottom(ctx: KeyContext, col: int) -> int:
    """``G``: last row with data in this column (else the used bottom)."""
    if ctx.used_range is None:
        return 0
    bottom = ctx.used_range[1][0]
    for row in range(bottom, -1, -1):
        if _occupied(ctx, row, col):
            return row
    return bottom


def _row_rect(ctx: KeyContext, row: int, count: int = 1):
    """``dd``/``yy``/``cc``/``V``: whole-row rect, column 0 to the used
    right edge (vim takes the whole line, leading blanks included)."""
    right = ctx.used_range[1][1] if ctx.used_range is not None else 0
    return ((row, 0), (row + count - 1, right))


_KEY_TABLE: list[KeyRow] = [
    ("h j k l / arrows", "move (counts work: 3j)"),
    ("w / b", "next / previous data block in the row"),
    ("0 ^ / $", "first / last filled cell in the row"),
    ("gg / G", "top / bottom of the column's data ({n}G = row n)"),
    ("Ctrl+D / Ctrl+U", "half page down / up"),
    ("i a I A", "edit cell (caret at start / end)"),
    ("x", "delete cell(s) — yanks first, like vim"),
    ("dd / yy / cc", "delete / yank / change row"),
    ("p P", "paste at the cursor"),
    ("v / V", "visual / visual line"),
    ("u / Ctrl+R", "undo / redo"),
    (":w :q :wq :x :q! :{n}", "write, quit, both, force, go to row"),
    ("Esc / Ctrl+C", "back to normal; deselect"),
]


class VimKeymap:
    """The vim key language as a ``trellis_tui.keymap.Keymap``.

    One stateful instance per session. The *mode* lives in the app
    (``EnterMode`` actions move it; the context echoes it back) — the
    keymap holds only what no one else can: the pending count, the
    pending double (``d``/``y``/``c``/``g``), the ``:`` buffer, and
    visual-line's moving end.
    """

    name = "vim"

    def __init__(self) -> None:
        self._count = ""
        self._pending = ""  # awaiting a double: "d" | "y" | "c" | "g"
        self._cmdline: str | None = None
        self._vline: int | None = None  # visual-line anchor row
        self._vcur: int | None = None  # visual-line moving end row

    def initial_mode(self) -> str:
        return "normal"

    def key_table(self) -> list[KeyRow]:
        return list(_KEY_TABLE)

    # ------------------------------------------------------------ plumbing

    def _reset(self) -> None:
        self._count = ""
        self._pending = ""
        self._cmdline = None
        self._vline = None
        self._vcur = None

    def _take_count(self, default: int = 1) -> int:
        n = int(self._count) if self._count else default
        self._count = ""
        return n

    def _to_normal(self) -> Action:
        self._reset()
        return EnterMode("normal")

    # ------------------------------------------------------------ dispatch

    def handle(self, key: KeyPress, ctx: KeyContext) -> Action | None:
        if ctx.mode == "command" or self._cmdline is not None:
            return self._command(key, ctx)
        if ctx.mode in ("visual", "visual-line"):
            return self._visual(key, ctx)
        return self._normal(key, ctx)

    # ------------------------------------------------------------- normal

    def _normal(self, key: KeyPress, ctx: KeyContext) -> Action | None:
        ch = key.char
        row, col = ctx.cursor

        # A pending double resolves first (dd / yy / cc / gg).
        if self._pending:
            op, self._pending = self._pending, ""
            if op == "g" and ch == "g":
                if self._count:  # {n}gg = go to row n, like {n}G
                    return MoveTo(max(0, self._take_count() - 1), col)
                return MoveTo(_col_top(ctx, col), col)
            if op in "dyc" and ch == op:
                rect = _row_rect(ctx, row, self._take_count())
                if op == "d":  # delete is yank (vim): dd then p moves the row
                    return Chain((Operate("copy", rect), Operate("clear", rect)))
                if op == "y":
                    return Operate("copy", rect)
                return Operate("change", rect)  # cc: clear row, open editor
            self._count = ""
            return Hint(f"{op}{ch or key.key}? not a vim gesture here")

        # Count digits accumulate ("0" only continues a count — alone
        # it is the motion).
        if ch and ch.isdigit() and not key.ctrl and (self._count or ch != "0"):
            self._count += ch
            return None

        if key.ctrl:
            self._count = ""
            if key.key == "d":
                return Move(max(1, ctx.viewport_rows // 2), 0)
            if key.key == "u":
                return Move(-max(1, ctx.viewport_rows // 2), 0)
            if key.key == "r":
                return Redo()
            if key.key == "v":  # visual block = visual, in a grid
                return EnterMode("visual")
            if key.key == "c":  # vim: Ctrl+C ~ Esc (never the app's quit)
                return self._to_normal()
            return None  # chrome and the rest run on (Ctrl+S, tabs…)

        # Motions (counts consume).
        if ch == "h" or key.key in ("left", "backspace"):
            return Move(0, -self._take_count())
        if ch == "l" or key.key == "right":
            return Move(0, self._take_count())
        if ch == "j" or key.key in ("down", "enter"):
            return Move(self._take_count(), 0)
        if ch == "k" or key.key == "up":
            return Move(-self._take_count(), 0)
        if ch in ("0", "^"):
            self._count = ""
            return MoveTo(row, _row_first(ctx, row))
        if ch == "$":
            self._count = ""
            return MoveTo(row, _row_last(ctx, row))
        if ch == "w" or ch == "b":
            step = 1 if ch == "w" else -1
            c = col
            for _ in range(self._take_count()):
                c = _jump(ctx, row, c, step)
            return MoveTo(row, c)
        if ch == "G":
            if self._count:  # {n}G = go to row n
                return MoveTo(max(0, self._take_count() - 1), col)
            return MoveTo(_col_bottom(ctx, col), col)
        if ch == "g":
            self._pending = "g"
            return None
        if ch in ("d", "y", "c"):
            self._pending = ch
            return None

        # Operators on the cursor cell(s).
        if ch == "x" or key.key == "delete":
            n = self._take_count()
            rect = ((row, col), (row, col + n - 1))
            return Chain((Operate("copy", rect), Operate("clear", rect)))
        if ch in ("p", "P"):
            self._count = ""
            return Operate("paste")
        if ch == "u":
            self._count = ""
            return Undo()

        # Insert (the editor IS insert mode; caret per vim).
        if ch in ("i", "I"):
            self._count = ""
            return BeginEdit(caret="start")
        if ch in ("a", "A"):
            self._count = ""
            return BeginEdit(caret="end")

        # Visual / command-line.
        if ch == "v":
            self._count = ""
            return EnterMode("visual")
        if ch == "V":
            self._count = ""
            self._vline = self._vcur = row
            return Chain(
                (EnterMode("visual-line"), Select(_row_rect(ctx, row)))
            )
        if ch == ":":
            self._cmdline = ""
            return EnterMode("command")
        if key.key == "escape":
            return self._to_normal()

        return None  # unmapped: inert (o, O, e, … — nothing falls through)

    # ------------------------------------------------------------- visual

    def _visual(self, key: KeyPress, ctx: KeyContext) -> Action | None:
        ch = key.char
        row, col = ctx.cursor
        line = ctx.mode == "visual-line"

        if key.key == "escape" or ch == "v" or (key.ctrl and key.key == "c"):
            return self._to_normal()

        if ch and ch.isdigit() and not key.ctrl and (self._count or ch != "0"):
            self._count += ch
            return None

        # Operators over the live selection (rect=None: the executor
        # resolves it, then drops to normal). Vim parks the cursor at
        # the START of the operated region afterward — so `vy` then
        # `p` elsewhere pastes anchor-relative, the way fingers expect;
        # the MoveTo home is baked from the handle-time selection.
        home = MoveTo(*(ctx.selection or ((row, col),))[0])
        if ch in ("d", "x") or key.key == "delete":
            self._reset()
            return Chain(
                (Operate("copy"), Operate("clear"), EnterMode("normal"), home)
            )
        if ch == "y":
            self._reset()
            return Chain((Operate("copy"), EnterMode("normal"), home))
        if ch == "p" or ch == "P":
            self._reset()
            return Chain((Operate("paste"), EnterMode("normal"), home))
        if ch == "c":
            # Bake the rect: the change must survive the collapse that
            # precedes it (EnterMode first, or the editor would open
            # under a still-painted selection).
            rect = ctx.selection or ((row, col), (row, col))
            self._reset()
            return Chain((EnterMode("normal"), Operate("change", rect)))

        if line:
            return self._visual_line_motion(key, ctx)

        # Character-wise visual: motions extend (the grid pins the
        # anchor on the first extend).
        if ch == "h" or key.key in ("left", "backspace"):
            return Move(0, -self._take_count(), extend=True)
        if ch == "l" or key.key == "right":
            return Move(0, self._take_count(), extend=True)
        if ch == "j" or key.key in ("down", "enter"):
            return Move(self._take_count(), 0, extend=True)
        if ch == "k" or key.key == "up":
            return Move(-self._take_count(), 0, extend=True)
        if ch in ("0", "^"):
            self._count = ""
            return MoveTo(row, _row_first(ctx, row), extend=True)
        if ch == "$":
            self._count = ""
            return MoveTo(row, _row_last(ctx, row), extend=True)
        if ch == "w" or ch == "b":
            step = 1 if ch == "w" else -1
            c = col
            for _ in range(self._take_count()):
                c = _jump(ctx, row, c, step)
            return MoveTo(row, c, extend=True)
        if ch == "G":
            if self._count:
                return MoveTo(max(0, self._take_count() - 1), col, extend=True)
            return MoveTo(_col_bottom(ctx, col), col, extend=True)
        if ch == "g":
            # gg in visual: top of the column's data, extending. (No
            # pending-double machinery here — g is unambiguous in v1.)
            return MoveTo(_col_top(ctx, col), col, extend=True)

        return None

    def _visual_line_motion(self, key: KeyPress, ctx: KeyContext) -> Action | None:
        """Visual-line motions recompute the whole-row rect from the
        keymap's own moving end — the grid parks the cursor at the
        rect's bottom-right, so extending upward would otherwise stall
        against the anchor row."""
        ch = key.char
        anchor = self._vline if self._vline is not None else ctx.cursor[0]
        cur = self._vcur if self._vcur is not None else ctx.cursor[0]

        if ch == "j" or key.key in ("down", "enter"):
            cur += self._take_count()
        elif ch == "k" or key.key == "up":
            cur -= self._take_count()
        elif ch == "G":
            cur = (
                max(0, self._take_count() - 1)
                if self._count
                else _col_bottom(ctx, ctx.cursor[1])
            )
        elif ch == "g":
            cur = _col_top(ctx, ctx.cursor[1])
        else:
            return None
        cur = max(0, cur)
        self._vline, self._vcur = anchor, cur
        top, bottom = min(anchor, cur), max(anchor, cur)
        right = ctx.used_range[1][1] if ctx.used_range is not None else 0
        return Select(((top, 0), (bottom, right)))

    # ------------------------------------------------------- command line

    def _command(self, key: KeyPress, ctx: KeyContext) -> Action | None:
        if self._cmdline is None:
            self._cmdline = ""
        if key.key == "escape" or (key.ctrl and key.key == "c"):
            return self._to_normal()
        if key.key == "enter":
            text, self._cmdline = self._cmdline, None
            return self._run_command(text, ctx)
        if key.key == "backspace":
            if not self._cmdline:
                return self._to_normal()  # backspace past ':' leaves, like vim
            self._cmdline = self._cmdline[:-1]
            return Hint(":" + self._cmdline)
        if key.char and not key.ctrl and not key.alt:
            self._cmdline += key.char
            return Hint(":" + self._cmdline)
        return Hint(":" + self._cmdline)  # modal: arrows etc. stay consumed

    def _run_command(self, text: str, ctx: KeyContext) -> Action:
        cmd = text.strip()
        back = EnterMode("normal")
        if cmd == "":
            return back
        if cmd == "w":
            return Chain((back, Save()))
        if cmd == "q":
            return Chain((back, Quit()))
        if cmd == "q!":
            return Chain((back, Quit(force=True)))
        if cmd in ("wq", "x"):
            return Chain((back, Save(), Quit()))
        if cmd.isdigit():  # :{n} — go to row n, column kept
            return Chain((back, MoveTo(max(0, int(cmd) - 1), ctx.cursor[1])))
        return Chain((back, Hint(f"not an editor command: {cmd}")))
