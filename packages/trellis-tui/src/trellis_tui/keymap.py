"""The keymap contract — the TUI's first extension point (design.md Part 10).

A *keymap* is a whole key language for the grid: it receives every key
the focused grid sees and answers with an :class:`Action` from a closed
vocabulary, which the app's shared executor then performs. There is one
key path and every keymap goes through it — the default Excel bindings
live in the built-in :class:`ExcelKeymap`, and an alternative language
(vim, in ``trellis-tui-vim``) is just another :class:`Keymap` registered
under the ``trellis_tui.keymaps`` entry point and selected with
``--keymap NAME`` (``--vim`` is sugar). No fall-through between keymaps:
the active keymap is the sole authority for the keys it sees (DECIDED
Part 10 #6).

The discipline mirrors the engine's:

- **The keymap never writes.** It reads a :class:`KeyContext` and
  returns an Action; the TUI executes it — the frontend echo of "the
  grid never writes the engine".
- **The contract is textual-free** (DECIDED #8). Keymap packages import
  only this module; :class:`KeyPress` is the ~20-line adapter's output,
  parsed here from plain strings (key names mirror textual's for now —
  an own vocabulary waits for a non-textual frontend to exist).
- **Rects resolve at execution time.** An Action that targets cells
  (:class:`Operate`, :class:`Fill`) should usually carry ``rect=None``
  ("the live selection, else the cursor") rather than baking
  coordinates from the context: actions execute in order, so a queued
  ``Move(extend=True)`` lands before the ``Operate`` that follows it,
  while the handle-time context may not have caught up under fast
  input. The context is for *computing motions* (data jumps, paging),
  not for pre-resolving targets the executor resolves better.

Returning ``None`` from :meth:`Keymap.handle` means "no action here":
the key continues to the framework and the app's chrome bindings —
window-level keys (sheet switching, new/close/rename tab, save, quit)
stay app-owned (DECIDED #7), and a multi-key parse in progress (vim's
pending count) simply answers ``None`` until the gesture completes. A
keymap that must *deaden* a framework-bound key returns ``Hint("")``.

What the boundary looks like from the grid's side: an Action stops the
key event (``stop`` + ``prevent_default``); ``None`` lets it run.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Callable, Protocol, runtime_checkable

__all__ = [
    "Action",
    "BeginEdit",
    "ENTRY_POINT_GROUP",
    "EnterMode",
    "ExcelKeymap",
    "Fill",
    "Hint",
    "KeyContext",
    "KeyPress",
    "KeyRow",
    "Keymap",
    "Move",
    "MoveTo",
    "Operate",
    "Quit",
    "Rect",
    "Redo",
    "Save",
    "Select",
    "Sheet",
    "Undo",
    "available_keymaps",
    "load_keymap",
]

#: A normalised rectangle: ``((top, left), (bottom, right))``, inclusive,
#: zero-indexed engine coordinates (the grid's ``Rect``, re-stated here so
#: keymap packages need no other import).
Rect = tuple[tuple[int, int], tuple[int, int]]

#: One row of a keymap's help table: ``(keys, description)``.
KeyRow = tuple[str, str]

#: The entry-point group a keymap package registers under. Each entry is
#: ``name = "module:factory"`` with ``factory() -> Keymap`` — mathpack's
#: discovery pattern, one layer out.
ENTRY_POINT_GROUP = "trellis_tui.keymaps"


# ------------------------------------------------------------- key press


@dataclass(frozen=True)
class KeyPress:
    """One parsed key, textual-free (DECIDED #8).

    ``key`` is the base key name (textual's naming, modifiers split
    off): ``"a"``, ``"up"``, ``"escape"``, ``"f2"``. ``char`` is the
    printable character, or ``None`` for non-printables (so ``enter``
    does not read as a printable ``"\\r"``). Modifier flags are split
    out of the combination string: ``"ctrl+shift+z"`` parses to
    ``KeyPress("z", ctrl=True, shift=True)``.
    """

    key: str
    char: str | None = None
    ctrl: bool = False
    alt: bool = False
    shift: bool = False

    @classmethod
    def parse(cls, name: str, char: str | None = None) -> "KeyPress":
        """Parse a textual-style key string (``"ctrl+shift+z"``)."""
        parts = name.split("+")
        mods = set(parts[:-1])
        return cls(
            key=parts[-1],
            char=char,
            ctrl="ctrl" in mods,
            alt="alt" in mods or "meta" in mods,
            shift="shift" in mods,
        )


# ------------------------------------------------------------- key context


@dataclass(frozen=True)
class KeyContext:
    """The read-only state a keymap sees. Nothing here is writable —
    ``cell(row, col)`` returns live engine cells for data-block motions
    (vim's ``w``/``b``, Excel's ``Ctrl+arrow``), and the viewport pair
    sizes page motions. ``editing`` is along for completeness: while the
    cell editor has focus the keymap is bypassed entirely (Insert mode
    is the editor's, DECIDED Part 10), so handle() normally sees False.
    """

    mode: str
    cursor: tuple[int, int]
    selection: Rect | None
    used_range: Rect | None
    cell: Callable[[int, int], Any]
    viewport_rows: int
    viewport_cols: int
    editing: bool = False


# ---------------------------------------------------------------- actions


class Action:
    """Base of the closed vocabulary the TUI executes (design Part 10).

    Closed by convention, like the Part 3 payloads: executors match on
    these classes, so a keymap inventing new Action subclasses gets
    silence, not magic.
    """

    __slots__ = ()


@dataclass(frozen=True)
class Move(Action):
    """Relative cursor move; ``extend=True`` grows the selection
    (anchor pinned). The executor clamps to the grid window."""

    dr: int
    dc: int
    extend: bool = False


@dataclass(frozen=True)
class MoveTo(Action):
    """Absolute cursor move (``Ctrl+Home``, vim ``gg``/``G``/``:{n}``)."""

    row: int
    col: int
    extend: bool = False


@dataclass(frozen=True)
class Select(Action):
    """Set the selection to ``rect`` outright: anchor at the top-left,
    cursor to the bottom-right (``Ctrl+A``; vim's Visual entries).
    Added at build time alongside the design's vocabulary — select-all
    is not expressible as a single anchored Move."""

    rect: Rect


@dataclass(frozen=True)
class BeginEdit(Action):
    """Enter the cell editor. ``seed=None`` is a revise-edit (F2:
    prefilled, full fidelity); a string seed is a replace-edit carrying
    Excel's type-to-edit (``""`` = clear-and-type). ``caret`` places
    the insertion point (vim ``i`` vs ``a``)."""

    caret: str = "end"  # "start" | "end"
    seed: str | None = None


@dataclass(frozen=True)
class EnterMode(Action):
    """Switch the mode indicator (Normal/Visual/Command…). Entering the
    keymap's ``initial_mode()`` also collapses the selection and cancels
    a pending cut — the Esc contract."""

    name: str


@dataclass(frozen=True)
class Operate(Action):
    """A cell operation over ``rect`` — or, when ``rect`` is ``None``,
    the live selection (else the cursor cell), resolved at execution
    time. ``op`` is one of ``copy``/``cut``/``clear``/``paste``/
    ``change`` (``change`` = clear, then a replace-edit)."""

    op: str
    rect: Rect | None = None


@dataclass(frozen=True)
class Fill(Action):
    """Part 8's fill over ``rect`` (``None`` = selection else cursor):
    ``axis`` ``"down"`` or ``"right"``. In the vocabulary because
    modeling Excel-as-a-keymap demanded it — vim alone never would
    have (the two-consumer payoff, design Part 10)."""

    axis: str
    rect: Rect | None = None


@dataclass(frozen=True)
class Undo(Action):
    """One history step back (Part 7)."""


@dataclass(frozen=True)
class Redo(Action):
    """Re-apply the newest undone step."""


@dataclass(frozen=True)
class Save(Action):
    """Save the active sheet; ``prompt=True`` always asks for a path."""

    prompt: bool = False


@dataclass(frozen=True)
class Quit(Action):
    """Quit (dirty sheets warn once); ``force=True`` skips the warning
    (vim ``:q!``)."""

    force: bool = False


@dataclass(frozen=True)
class Sheet(Action):
    """Cycle the active sheet tab: ``direction`` ``"next"`` | ``"prev"``."""

    direction: str


@dataclass(frozen=True)
class Hint(Action):
    """Show ``msg`` in the status bar — also the explicit "consumed,
    do nothing" (``Hint("")``) when a keymap must deaden a key."""

    msg: str


# ---------------------------------------------------------------- protocol


@runtime_checkable
class Keymap(Protocol):
    """What a keymap package implements. One *stateful* instance per
    session — vim's pending counts and operators are parse state, which
    is why this is ``handle(...)`` and not a static dict."""

    name: str

    def initial_mode(self) -> str:
        """The resting mode name (``"default"`` for Excel, ``"normal"``
        for vim). The mode indicator hides this one."""
        ...

    def handle(self, key: KeyPress, ctx: KeyContext) -> Action | None:
        """Answer one key with an Action, or ``None`` (no action here:
        the key continues to the framework and app chrome)."""
        ...

    def key_table(self) -> list[KeyRow]:
        """Rows for a help display. Optional in spirit — return []."""
        ...


# ------------------------------------------------------------ ExcelKeymap

# The default bindings, ported from SheetGrid.BINDINGS + on_key (Parts
# 5-8) — table rows are (base key, ctrl, shift) -> Action factory. Alt
# combinations are deliberately absent: nothing default binds Alt.

def _select_all(ctx: KeyContext) -> Action | None:
    if ctx.used_range is None:
        return None  # empty sheet: nothing to select (no-op, as before)
    return Select(ctx.used_range)


_EXCEL_TABLE: dict[tuple[str, bool, bool], Callable[[KeyContext], Action | None]] = {
    # Navigation. DataTable's own cursor bindings are suppressed by the
    # one-path dispatch; these reproduce them through the executor.
    ("up", False, False): lambda ctx: Move(-1, 0),
    ("down", False, False): lambda ctx: Move(1, 0),
    ("left", False, False): lambda ctx: Move(0, -1),
    ("right", False, False): lambda ctx: Move(0, 1),
    ("home", True, False): lambda ctx: MoveTo(0, 0),
    # Selection (Part 6 #4).
    ("up", False, True): lambda ctx: Move(-1, 0, extend=True),
    ("down", False, True): lambda ctx: Move(1, 0, extend=True),
    ("left", False, True): lambda ctx: Move(0, -1, extend=True),
    ("right", False, True): lambda ctx: Move(0, 1, extend=True),
    ("a", True, False): _select_all,
    ("escape", False, False): lambda ctx: EnterMode("default"),
    # Editing (Part 5 #5).
    ("f2", False, False): lambda ctx: BeginEdit(),
    ("enter", False, False): lambda ctx: BeginEdit(),
    ("backspace", False, False): lambda ctx: BeginEdit(seed=""),
    ("delete", False, False): lambda ctx: Operate("clear"),
    # Clipboard (Part 6 #5).
    ("c", True, False): lambda ctx: Operate("copy"),
    ("x", True, False): lambda ctx: Operate("cut"),
    ("v", True, False): lambda ctx: Operate("paste"),
    # Undo (Part 7 #4).
    ("z", True, False): lambda ctx: Undo(),
    ("y", True, False): lambda ctx: Redo(),
    ("z", True, True): lambda ctx: Redo(),
    # Fill (Part 8).
    ("d", True, False): lambda ctx: Fill("down"),
    ("r", True, False): lambda ctx: Fill("right"),
}

_EXCEL_ROWS: list[KeyRow] = [
    ("arrows / Shift+arrows", "move / extend selection"),
    ("Ctrl+Home", "jump to A1"),
    ("Ctrl+A", "select used range"),
    ("F2 / Enter", "edit cell"),
    ("typing", "replace cell"),
    ("Backspace", "clear and edit"),
    ("Delete", "clear cell/selection"),
    ("Ctrl+C / Ctrl+X / Ctrl+V", "copy / cut / paste"),
    ("Ctrl+Z / Ctrl+Y", "undo / redo"),
    ("Ctrl+D / Ctrl+R", "fill down / right"),
    ("Esc", "deselect, cancel cut"),
]


class ExcelKeymap:
    """The default key language — today's bindings behind the one path
    (DECIDED Part 10 #6: Excel is a keymap too; the contract is proved
    by two consumers or it isn't proved). Stateless and modeless:
    ``initial_mode()`` is ``"default"`` and nothing ever leaves it —
    the editor (Insert) is entered via :class:`BeginEdit` like any
    keymap, and the indicator hides the initial mode."""

    name = "excel"

    def initial_mode(self) -> str:
        return "default"

    def handle(self, key: KeyPress, ctx: KeyContext) -> Action | None:
        if key.alt:
            return None  # nothing default binds Alt (chrome may)
        if key.char is not None and not key.ctrl:
            # Excel's type-to-edit: any printable replaces the cell.
            return BeginEdit(seed=key.char)
        entry = _EXCEL_TABLE.get((key.key, key.ctrl, key.shift))
        if entry is None:
            return None  # not ours: framework keys (paging) + app chrome
        return entry(ctx)

    def key_table(self) -> list[KeyRow]:
        return list(_EXCEL_ROWS)


# ---------------------------------------------------------------- registry


def available_keymaps() -> dict[str, Callable[[], "Keymap"]]:
    """Name -> factory for every known keymap: the built-in ``excel``
    plus everything registered under :data:`ENTRY_POINT_GROUP`. A
    plugin cannot shadow the built-in name."""
    maps: dict[str, Callable[[], Keymap]] = {"excel": ExcelKeymap}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        maps.setdefault(ep.name, ep.load())
    return maps


def load_keymap(name: str) -> "Keymap":
    """Instantiate the keymap registered as ``name``.

    Raises ``KeyError`` (listing what IS available) for unknown names —
    ``build_app`` turns that into the CLI error message.
    """
    maps = available_keymaps()
    if name not in maps:
        known = ", ".join(sorted(maps))
        raise KeyError(f"unknown keymap {name!r} (available: {known})")
    return maps[name]()
