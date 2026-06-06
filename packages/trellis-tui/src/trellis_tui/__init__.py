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

Run it as ``trellis [file.csv]`` (console script) or
``python -m trellis_tui``.
"""

__version__ = "0.1.0"

from .app import TrellisApp, main  # noqa: E402  (__version__ first: app.py imports it)

__all__ = ["TrellisApp", "main", "__version__"]
