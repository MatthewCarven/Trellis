"""trellis-tui — the Textual terminal frontend for Trellis.

A FRONTEND, not a plugin: this package imports ``trellis`` and drives the
engine from the outside, strictly through the public API. There is no
``trellis.plugins`` entry point here and core never imports this package —
"the engine is a library first, an app second."

The contract that keeps the app honest (design.md Part 5):

- **The engine is the model.** The app holds a real ``Workbook`` — the same
  object a REPL would hold. No shadow copies of cell data; the grid's text
  is a render cache, never an authority.
- **One repaint path.** The grid repaints only in response to engine events
  (``cell:change`` / ``cell:recalc`` / ``sheet:batch``) — including for the
  TUI's own writes, which round-trip through ``sheet.set`` like anyone
  else's.
- **One key path** (Part 10). Every key the focused grid sees goes to the
  active :class:`Keymap`, which answers with an :class:`Action` the app
  executes — the default Excel bindings are themselves a keymap
  (:class:`ExcelKeymap`), and alternative key languages register under the
  ``trellis_tui.keymaps`` entry point (``--keymap NAME`` / ``--vim``).

Run it as ``trellis [file.csv]`` (console script) or
``python -m trellis_tui``.
"""

__version__ = "0.1.0"

# __version__ first: app.py imports it back from the package.
from .app import TrellisApp, main  # noqa: E402
from .editor import FormulaBar  # noqa: E402
from .grid import SheetGrid  # noqa: E402
from .keymap import (  # noqa: E402
    Action,
    BeginEdit,
    EnterMode,
    ExcelKeymap,
    Fill,
    Hint,
    KeyContext,
    Keymap,
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
    load_keymap,
)
from .keymap import Sheet as SheetAction  # noqa: E402  (trellis.Sheet is the engine's)
from .render import DisplayText, display  # noqa: E402

__all__ = [
    "Action",
    "BeginEdit",
    "DisplayText",
    "EnterMode",
    "ExcelKeymap",
    "Fill",
    "FormulaBar",
    "Hint",
    "KeyContext",
    "Keymap",
    "KeyPress",
    "Move",
    "MoveTo",
    "Operate",
    "Quit",
    "Redo",
    "Save",
    "Select",
    "SheetAction",
    "SheetGrid",
    "TrellisApp",
    "Undo",
    "available_keymaps",
    "display",
    "load_keymap",
    "main",
    "__version__",
]
