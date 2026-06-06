"""Trellis formula engine.

Public surface (built incrementally across the #4 subtasks):

    from trellis.formula import parse_formula        # #16
    from trellis.formula import FormulaError, ParseError  # #16
    from trellis.formula import DIV0, VALUE, REF, NAME, CIRC, NA, NULL  # #16
    from trellis.formula import Context, evaluate    # #17
    from trellis.formula import register_function, get_function  # #21
    from trellis.formula import RecalcEngine         # #18 (THIS)
    # Built-in functions: registered as a side effect of importing.
    # Top-level trellis re-exports + README: #19

AST node types live in ``trellis.formula.ast``; rarely needed by end users
but exposed for plugins that want to construct or inspect ASTs directly.
"""

from .errors import CIRC, DIV0, NA, NAME, NULL, REF, VALUE, FormulaError, ParseError
from .evaluator import Context, evaluate
from .functions import (
    get_function,
    register_function,
    registered_function_names,
    unregister_function,
)
from .parser import parse_formula
from .recalc import RecalcEngine
from .shift import shift_formula

# Import for side effects: registers the built-in functions (SUM, IF, ...)
# in the function registry at package import time. Nothing from this
# module is re-exported — call sites use ``=SUM(...)`` inside a formula
# string, not a direct Python import.
from . import builtins as _builtins  # noqa: F401

__all__ = [
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
    "shift_formula",
    "unregister_function",
]
