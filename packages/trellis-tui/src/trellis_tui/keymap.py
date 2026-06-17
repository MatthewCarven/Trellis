"""Compatibility shim — the keymap contract lives in ``trellis-keymap`` now.

The textual-free keymap contract (``KeyPress``/``KeyContext``/``Action``/
``Keymap``/``ExcelKeymap`` + discovery) was extracted to its own zero-
dependency package (``trellis-keymap``, S40) so any frontend — this TUI, a
future GUI — can host the same Excel/vim key languages without dragging in
Textual. This module re-exports that contract so existing imports
(``from trellis_tui import keymap as km``) keep working unchanged.

New code should import from ``trellis_keymap`` directly; a later pass can
repoint app.py/grid.py and drop this shim. See ``packages/trellis-keymap``
and ``docs/keymap-plugin.md``.
"""

from __future__ import annotations

# Re-export the public contract surface (trellis_keymap defines __all__).
from trellis_keymap import *  # noqa: F401,F403
from trellis_keymap import __all__ as __all__
