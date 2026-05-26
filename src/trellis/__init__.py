"""Trellis — a minimalist, modular spreadsheet framework.

The core engine is a plain Python library. Import what you need and use it from
your own code or a REPL:

    >>> from trellis import Workbook
    >>> wb = Workbook()
    >>> sh = wb.add_sheet("Demo")
    >>> sh["A1"] = 10
    >>> sh["A2"] = 20
    >>> sh["B1"] = "=SUM(A1:A2)"
    >>> sh["B1"].value
    30
    >>> sh["A1"] = 100             # B1 recomputes automatically
    >>> sh["B1"].value
    120

The TUI, file I/O, and other features layer on top of this core without
coupling back to it. Design philosophy: open extensibility — public-by-default
APIs and hooks everywhere, on the assumption that other developers will want
to bend the framework rather than be protected from it.

Extension surface available today:
    - Subclass any core object (Cell, Sheet, Workbook).
    - Subscribe to events emitted by Sheet ("cell:change", "cell:recalc")
      and Workbook ("sheet:add", "sheet:remove", "sheet:rename"). Use "*"
      to receive every event from a given emitter.
    - Use the Emitter mixin on your own classes to give them the same pub/sub.
    - Work with rectangles of cells via Range (sheet["A1:B5"], broadcast assign,
      bulk clear).
    - Register a formula function with ``@register_function("MYFN")``. It
      becomes callable as ``=MYFN(...)`` in any formula immediately. See
      ``docs/plugin-example.md``.
    - Attach a RecalcEngine manually if you want fine-grained control (one is
      auto-attached to every Workbook on construction).

Plugin registry (entry_points-based auto-discovery) arrives in task #5.
"""

# Core data model
from .core.address import parse as parse_address
from .core.address import to_a1
from .core.cell import Cell
from .core.events import Emitter, Subscription
from .core.range import Range
from .core.sheet import Sheet
from .core.workbook import Workbook

# Formula engine — re-exported here so users don't need to know
# ``trellis.formula`` exists for everyday work.
from .formula import (
    CIRC,
    Context,
    DIV0,
    FormulaError,
    NA,
    NAME,
    NULL,
    ParseError,
    REF,
    RecalcEngine,
    VALUE,
    evaluate,
    get_function,
    parse_formula,
    register_function,
    registered_function_names,
    unregister_function,
)

__all__ = [
    # Core
    "Cell",
    "Emitter",
    "Range",
    "Sheet",
    "Subscription",
    "Workbook",
    "parse_address",
    "to_a1",
    # Formula engine
    "CIRC",
    "Context",
    "DIV0",
    "FormulaError",
    "NA",
    "NAME",
    "NULL",
    "ParseError",
    "REF",
    "RecalcEngine",
    "VALUE",
    "evaluate",
    "get_function",
    "parse_formula",
    "register_function",
    "registered_function_names",
    "unregister_function",
]
__version__ = "0.0.1"
