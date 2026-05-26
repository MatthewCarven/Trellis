"""Trellis — a minimalist, modular spreadsheet framework.

The core engine is a plain Python library. Import what you need and use it from
your own code or a REPL:

    >>> from trellis import Workbook
    >>> wb = Workbook()
    >>> sheet = wb.add_sheet("Demo")
    >>> sheet["A1"] = 42
    >>> sheet["A1:C1"] = [1, 2, 3]
    >>> [c.value for c in sheet["A1:C1"]]
    [1, 2, 3]

The TUI, formula engine, file I/O, and other features layer on top of this core
without coupling back to it. Design philosophy: open extensibility — public-by-
default APIs and hooks everywhere, on the assumption that other developers will
want to bend the framework rather than be protected from it.

Extension surface available today:
    - Subclass any core object (Cell, Sheet, Workbook).
    - Subscribe to events emitted by Sheet ("cell:change") and Workbook
      ("sheet:add", "sheet:remove", "sheet:rename"). Use "*" to receive every
      event from a given emitter.
    - Use the Emitter mixin on your own classes to give them the same pub/sub.
    - Work with rectangles of cells via Range (sheet["A1:B5"], broadcast assign,
      bulk clear).

Plugin registry surface arrives with the formula engine and file I/O.
"""

from .core.address import parse as parse_address
from .core.address import to_a1
from .core.cell import Cell
from .core.events import Emitter, Subscription
from .core.range import Range
from .core.sheet import Sheet
from .core.workbook import Workbook

__all__ = [
    "Cell",
    "Emitter",
    "Range",
    "Sheet",
    "Subscription",
    "Workbook",
    "parse_address",
    "to_a1",
]
__version__ = "0.0.1"
