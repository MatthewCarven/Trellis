"""Function registry for the formula engine.

A global registry maps uppercase function names to callables. The same
registry is used by built-in functions (which register at import time in
:mod:`trellis.formula.functions` once #22 / #23 land) and by third-party
plugins (which register via ``entry_points`` discovery in task #5).

Functions come in two flavours:

**Eager** (default): args are pre-evaluated by the evaluator before the
function is called. The function receives a Context plus the resulting
values. If any arg evaluates to a FormulaError, the call short-circuits
and the error is returned to the caller — the function itself is never
invoked.

**Lazy** (``lazy=True``): args arrive as un-evaluated AST nodes. The
function uses ``ctx.evaluate(node)`` to materialize each as needed. This
is for IF, IFERROR, and similar conditional functions that must not
evaluate branches that won't be taken.

The calling convention is identical for both: ``fn(ctx, *args)``. The
only difference is what's IN ``args`` — values for eager, raw AST nodes
for lazy.

Usage::

    from trellis.formula import register_function

    @register_function("ABS")
    def _abs(ctx, x):
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return abs(x)
        return VALUE

    @register_function("IF", lazy=True)
    def _if(ctx, cond, then_branch, *rest):
        c = ctx.evaluate(cond)
        if isinstance(c, FormulaError):
            return c
        if c:
            return ctx.evaluate(then_branch)
        if rest:
            return ctx.evaluate(rest[0])
        return False
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Maps UPPERCASE function name -> (callable, is_lazy).
# Private — use the public helpers (register_function / get_function /
# registered_function_names / unregister_function).
_REGISTRY: dict[str, tuple[Callable[..., Any], bool]] = {}


def register_function(name: str, lazy: bool = False):
    """Decorator: register ``fn`` under ``name.upper()`` in the registry.

    See module docstring for the eager-vs-lazy contract.

    Re-registration silently replaces any previous entry — plugins can
    override built-ins if they really want to (chaotic-good extensibility).
    """
    upper = name.upper()

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _REGISTRY[upper] = (fn, lazy)
        return fn

    return decorator


def get_function(name: str) -> tuple[Callable[..., Any], bool] | None:
    """Look up a registered function by name (case-insensitive).

    Returns ``(fn, is_lazy)`` if registered, ``None`` if not.
    """
    return _REGISTRY.get(name.upper())


def registered_function_names() -> list[str]:
    """Return all registered function names, uppercased and sorted."""
    return sorted(_REGISTRY.keys())


def unregister_function(name: str) -> bool:
    """Remove a registered function. Returns ``True`` if it was present.

    Mainly for tests and plugin teardown. Built-ins re-register at import
    time, so unregistering them in a running process is rarely useful.
    """
    upper = name.upper()
    if upper in _REGISTRY:
        del _REGISTRY[upper]
        return True
    return False
