"""Built-in functions for the formula engine.

This module is imported by :mod:`trellis.formula` so the
``@register_function`` decorators fire at package import time. Importing
``trellis.formula`` (or any of its public names) is sufficient to make all
built-ins available — no explicit setup call.

Each function follows the registry contract: ``fn(ctx, *args)`` where
``args`` are pre-evaluated values for eager functions (the default) or
raw AST nodes for lazy functions (IF, IFERROR, ISERROR). Errors are
values — return a :class:`FormulaError` rather than raising. Wrong arg
counts return ``#N/A``.

Excel-shaped rules worth knowing:

* Aggregates (SUM, AVERAGE, MIN, MAX) treat scalar string args as a
  ``#VALUE!`` error but silently *skip* strings, bools, and ``None``
  found inside a range argument. A FormulaError anywhere inside a
  range propagates.
* COUNT counts only numeric values; non-numerics (text, bools, empty,
  errors) are silently skipped whether scalar or in a range — COUNT
  intentionally never errors on text.
* AVERAGE of zero numerics is ``#DIV/0!``; MIN / MAX of zero numerics
  return 0 (matches Excel).
* ROUND uses round-half-away-from-zero, not banker's rounding —
  ``ROUND(2.5, 0)`` is 3, ``ROUND(-2.5, 0)`` is -3.
* INT rounds toward negative infinity — ``INT(-1.5)`` is -2, not -1.
* IF / IFERROR / ISERROR are lazy. IF: un-taken branch never evaluated,
  missing else returns ``FALSE``. IFERROR: fallback only evaluated on
  error. ISERROR: must be lazy because the eager dispatcher
  short-circuits FormulaError args — an eager ISERROR would never see
  the error to test.
* NOT (and IF's condition, AND, OR) coerce numbers to bool via
  ``!= 0``; strings are ``#VALUE!``; ``None`` is treated as ``FALSE``.
* AND / OR are eager. Excel doesn't short-circuit them either, and the
  eager dispatcher's error propagation matches that behaviour. Range
  args are walked Excel-style: strings/None inside the range are
  silently skipped; errors propagate.
* ISBLANK is strict — only an empty cell (``None`` value) counts. An
  empty string ``""`` is NOT blank. ISNUMBER excludes bools (bools are
  ``int`` subclass in Python but not "numbers" in spreadsheet sense).
* Text functions (CONCAT, LEN, LEFT, RIGHT, MID) coerce non-strings to
  text using the same rules as the ``&`` operator: ``None`` -> ``""``,
  ``True`` -> ``"TRUE"``, integer-valued float -> ``"N"``. MID is
  1-indexed per Excel; ``MID("hello", 2, 3)`` is ``"ell"``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from .errors import DIV0, NA, VALUE, FormulaError
from .evaluator import _to_string  # share the & operator's coercion rule
from .functions import register_function


# --- Coercion helpers ---------------------------------------------------


def _coerce_scalar_number(v: Any) -> Any:
    """Coerce a scalar arg to a number for math built-ins.

    Same rules as ``evaluator._to_number`` but with an explicit list-arg
    rejection (math built-ins are scalar-only). FormulaError pass-through
    is the dispatcher's job and shouldn't reach here in normal flow.
    """
    if isinstance(v, FormulaError):
        return v
    if isinstance(v, list):
        return VALUE
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    return VALUE


def _to_bool(v: Any) -> Any:
    """Coerce a value to bool for IF/NOT/AND/OR (scalar context).

    Strings are ``#VALUE!`` — we don't accept "TRUE"/"FALSE" strings
    (the engine doesn't auto-parse strings anywhere else either; staying
    consistent).
    """
    if isinstance(v, FormulaError):
        return v
    if isinstance(v, bool):
        return v
    if isinstance(v, list):
        return VALUE
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    return VALUE


def _collect_numerics(args: Iterable[Any]) -> Any:
    """Walk SUM/AVERAGE/MIN/MAX args and return a flat list of numbers.

    Scalar non-numerics (other than ``None`` which becomes 0) are an
    error — return ``#VALUE!``. Inside a range arg, non-numerics are
    silently skipped (Excel rule). A FormulaError anywhere inside a
    range propagates.
    """
    out: list[float] = []
    for a in args:
        if isinstance(a, list):
            for v in a:
                if isinstance(v, FormulaError):
                    return v
                if isinstance(v, bool):
                    continue  # bools in ranges are not numbers per Excel
                if isinstance(v, (int, float)):
                    out.append(v)
                # strings, None, others: silently skipped
        else:
            if isinstance(a, bool):
                out.append(int(a))
            elif isinstance(a, (int, float)):
                out.append(a)
            elif a is None:
                out.append(0)
            else:
                return VALUE  # scalar string / unknown type
    return out


def _collect_bools(args: Iterable[Any]) -> Any:
    """Walk AND/OR args and return a flat list of bools.

    Scalar context follows :func:`_to_bool` rules (strings VALUE, None
    FALSE, numbers truthy if non-zero). Range context follows the
    aggregate rule: skip strings/None silently, propagate errors,
    coerce numbers and bools.

    Returns ``#VALUE!`` if no args supplied, or if range args provided
    yielded zero usable values, matching Excel's behaviour.
    """
    out: list[bool] = []
    saw_scalar = False
    saw_range = False
    for a in args:
        if isinstance(a, list):
            saw_range = True
            for v in a:
                if isinstance(v, FormulaError):
                    return v
                if isinstance(v, bool):
                    out.append(v)
                elif isinstance(v, (int, float)):
                    out.append(v != 0)
                # strings, None, others: silently skipped
        else:
            saw_scalar = True
            b = _to_bool(a)
            if isinstance(b, FormulaError):
                return b
            out.append(b)
    if not saw_scalar and not saw_range:
        return VALUE  # AND() with no args at all
    if not out:
        return VALUE  # all range entries were skipped (text-only range)
    return out


def _arg_count_error(name: str, expected: str, got: int) -> FormulaError:
    """Standard #N/A for built-ins called with the wrong number of args."""
    return FormulaError(NA.code, f"{name} expected {expected} args, got {got}")


# --- Aggregates ---------------------------------------------------------


@register_function("SUM")
def _sum(ctx, *args):
    nums = _collect_numerics(args)
    if isinstance(nums, FormulaError):
        return nums
    return sum(nums)


@register_function("AVERAGE")
def _average(ctx, *args):
    nums = _collect_numerics(args)
    if isinstance(nums, FormulaError):
        return nums
    if not nums:
        return DIV0
    return sum(nums) / len(nums)


@register_function("MIN")
def _min(ctx, *args):
    nums = _collect_numerics(args)
    if isinstance(nums, FormulaError):
        return nums
    if not nums:
        return 0
    return min(nums)


@register_function("MAX")
def _max(ctx, *args):
    nums = _collect_numerics(args)
    if isinstance(nums, FormulaError):
        return nums
    if not nums:
        return 0
    return max(nums)


@register_function("COUNT")
def _count(ctx, *args):
    """COUNT counts only numbers. Non-numerics (text, bools, empty,
    errors) are silently skipped — COUNT never errors on text, even
    when text is passed as a direct scalar arg.
    """
    total = 0
    for a in args:
        if isinstance(a, list):
            for v in a:
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)):
                    total += 1
        else:
            if isinstance(a, bool):
                continue  # logical args not counted (matches range rule)
            if isinstance(a, (int, float)):
                total += 1
    return total


# --- Scalar math --------------------------------------------------------


@register_function("ABS")
def _abs(ctx, *args):
    if len(args) != 1:
        return _arg_count_error("ABS", "1", len(args))
    n = _coerce_scalar_number(args[0])
    if isinstance(n, FormulaError):
        return n
    return abs(n)


@register_function("ROUND")
def _round(ctx, *args):
    if len(args) != 2:
        return _arg_count_error("ROUND", "2", len(args))
    nn = _coerce_scalar_number(args[0])
    if isinstance(nn, FormulaError):
        return nn
    dd = _coerce_scalar_number(args[1])
    if isinstance(dd, FormulaError):
        return dd
    dd = int(dd)  # Excel truncates fractional digit counts
    # round-half-away-from-zero (Excel rule, not Python's banker's rounding)
    factor = 10 ** dd
    rounded = math.copysign(math.floor(abs(nn) * factor + 0.5), nn) / factor
    # Keep ints as ints when digits >= 0 and result is integer-valued.
    if dd >= 0 and isinstance(nn, int) and float(rounded).is_integer():
        return int(rounded)
    return rounded


@register_function("INT")
def _int(ctx, *args):
    if len(args) != 1:
        return _arg_count_error("INT", "1", len(args))
    n = _coerce_scalar_number(args[0])
    if isinstance(n, FormulaError):
        return n
    return math.floor(n)


# --- Logical ------------------------------------------------------------


@register_function("IF", lazy=True)
def _if(ctx, *args):
    """IF(condition, value_if_true, [value_if_false]).

    Lazy — the un-taken branch is never evaluated. Missing else-branch
    returns ``FALSE``. Wrong arg count is ``#N/A``.
    """
    if len(args) < 2 or len(args) > 3:
        return _arg_count_error("IF", "2 or 3", len(args))
    cond_val = ctx.evaluate(args[0])
    b = _to_bool(cond_val)
    if isinstance(b, FormulaError):
        return b
    if b:
        return ctx.evaluate(args[1])
    if len(args) == 3:
        return ctx.evaluate(args[2])
    return False


@register_function("NOT")
def _not(ctx, *args):
    if len(args) != 1:
        return _arg_count_error("NOT", "1", len(args))
    b = _to_bool(args[0])
    if isinstance(b, FormulaError):
        return b
    return not b


@register_function("IFERROR", lazy=True)
def _iferror(ctx, *args):
    """IFERROR(value, value_if_error).

    Lazy — fallback is only evaluated if value yields an error. The
    fallback is returned as-is even if it is itself an error.
    """
    if len(args) != 2:
        return _arg_count_error("IFERROR", "2", len(args))
    val = ctx.evaluate(args[0])
    if isinstance(val, FormulaError):
        return ctx.evaluate(args[1])
    return val


@register_function("ISERROR", lazy=True)
def _iserror(ctx, *args):
    """ISERROR(value). True iff value evaluates to a FormulaError.

    Must be lazy: the eager dispatcher short-circuits FormulaError args
    before reaching the function, so an eager ISERROR would never see
    the error it's meant to test.
    """
    if len(args) != 1:
        return _arg_count_error("ISERROR", "1", len(args))
    return isinstance(ctx.evaluate(args[0]), FormulaError)


@register_function("AND")
def _and(ctx, *args):
    bools = _collect_bools(args)
    if isinstance(bools, FormulaError):
        return bools
    return all(bools)


@register_function("OR")
def _or(ctx, *args):
    bools = _collect_bools(args)
    if isinstance(bools, FormulaError):
        return bools
    return any(bools)


# --- Type-check predicates (eager) -------------------------------------


@register_function("ISBLANK")
def _isblank(ctx, *args):
    """ISBLANK(value). Excel-strict: only an empty cell counts. Empty
    string is NOT blank. Range arg is ``#VALUE!``."""
    if len(args) != 1:
        return _arg_count_error("ISBLANK", "1", len(args))
    v = args[0]
    if isinstance(v, list):
        return VALUE
    return v is None


@register_function("ISNUMBER")
def _isnumber(ctx, *args):
    """ISNUMBER(value). True iff numeric. Bools are NOT numbers in the
    spreadsheet sense, even though Python treats ``bool`` as ``int``.
    Range arg is ``False`` (the array isn't itself a number)."""
    if len(args) != 1:
        return _arg_count_error("ISNUMBER", "1", len(args))
    v = args[0]
    if isinstance(v, bool):
        return False
    if isinstance(v, list):
        return False
    return isinstance(v, (int, float))


@register_function("ISTEXT")
def _istext(ctx, *args):
    """ISTEXT(value). True iff value is a string."""
    if len(args) != 1:
        return _arg_count_error("ISTEXT", "1", len(args))
    return isinstance(args[0], str)


# --- Text functions ----------------------------------------------------


@register_function("CONCAT")
def _concat(ctx, *args):
    """CONCAT(arg, ...). Joins all args as strings. Walks ranges (unlike
    older CONCATENATE). Each value coerced via ``_to_string``: ``None``
    becomes ``""``, bools become ``"TRUE"``/``"FALSE"``, integer-valued
    floats lose the trailing ``.0``. Errors anywhere propagate.
    """
    parts: list[str] = []
    for a in args:
        if isinstance(a, list):
            for v in a:
                if isinstance(v, FormulaError):
                    return v
                parts.append(_to_string(v))
        else:
            parts.append(_to_string(a))
    return "".join(parts)


@register_function("LEN")
def _len(ctx, *args):
    """LEN(text). Length of the value after string coercion. ``LEN(123)``
    is ``3`` (the string ``"123"``). Range arg is ``#VALUE!``."""
    if len(args) != 1:
        return _arg_count_error("LEN", "1", len(args))
    v = args[0]
    if isinstance(v, list):
        return VALUE
    return len(_to_string(v))


@register_function("LEFT")
def _left(ctx, *args):
    """LEFT(text, [n]). First n characters; n defaults to 1. Negative
    n is ``#VALUE!``; n larger than the string returns the whole string.
    """
    if len(args) < 1 or len(args) > 2:
        return _arg_count_error("LEFT", "1 or 2", len(args))
    v = args[0]
    if isinstance(v, list):
        return VALUE
    text = _to_string(v)
    if len(args) == 2:
        n = _coerce_scalar_number(args[1])
        if isinstance(n, FormulaError):
            return n
        n = int(n)
    else:
        n = 1
    if n < 0:
        return VALUE
    return text[:n]


@register_function("RIGHT")
def _right(ctx, *args):
    """RIGHT(text, [n]). Last n characters; n defaults to 1. Negative
    n is ``#VALUE!``; n=0 is ``""``; n larger than the string returns
    the whole string.
    """
    if len(args) < 1 or len(args) > 2:
        return _arg_count_error("RIGHT", "1 or 2", len(args))
    v = args[0]
    if isinstance(v, list):
        return VALUE
    text = _to_string(v)
    if len(args) == 2:
        n = _coerce_scalar_number(args[1])
        if isinstance(n, FormulaError):
            return n
        n = int(n)
    else:
        n = 1
    if n < 0:
        return VALUE
    if n == 0:
        return ""
    return text[-n:]


@register_function("MID")
def _mid(ctx, *args):
    """MID(text, start, n). 1-indexed substring per Excel.
    ``MID("hello", 2, 3)`` is ``"ell"``. ``start < 1`` or ``n < 0`` is
    ``#VALUE!``; ``start`` past the end returns ``""``.
    """
    if len(args) != 3:
        return _arg_count_error("MID", "3", len(args))
    v, start_v, n_v = args
    if isinstance(v, list):
        return VALUE
    text = _to_string(v)
    start = _coerce_scalar_number(start_v)
    if isinstance(start, FormulaError):
        return start
    start = int(start)
    n = _coerce_scalar_number(n_v)
    if isinstance(n, FormulaError):
        return n
    n = int(n)
    if start < 1 or n < 0:
        return VALUE
    # 1-indexed: MID(text, 2, 3) -> text[1:4]
    return text[start - 1:start - 1 + n]
