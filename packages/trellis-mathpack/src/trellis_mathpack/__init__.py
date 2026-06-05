"""trellis-mathpack — a reference math-function plugin for Trellis.

This package adds ~20 math functions (trig, hyperbolic, powers/logs, a few
misc helpers, and range statistics) to the Trellis formula engine. It exists
for two reasons:

1. **It is the publication-gate consumer.** It exercises Trellis's public
   extension surface end-to-end — ``register_function``, the
   ``fn(ctx, *args)`` calling convention, ``FormulaError`` as a value you
   *construct*, and ``entry_points`` auto-discovery — proving the API works
   from outside the core distribution.
2. **It is the reference plugin.** A maintained example to copy when writing
   your own Trellis plugin package.

How discovery works
-------------------
``pyproject.toml`` declares an entry point::

    [project.entry-points."trellis.plugins"]
    mathpack = "trellis_mathpack:setup"

When ``import trellis`` runs, Trellis scans the ``trellis.plugins`` group and
calls :func:`setup` once, with no arguments. ``setup`` registers every
mathpack function. Nothing else is needed — no manual wiring at the call site.

Design notes
-----------
* **Public surface only.** Everything here goes through ``from trellis import
  ...``. If mathpack ever needs a core internal, that's a gap in the core's
  public surface to fix in core.
* **Minting a custom error.** Trellis core has no ``#NUM!``. mathpack defines
  its own :data:`NUM` for domain errors (``SQRT(-1)``, ``LN(0)``,
  ``ASIN(2)``). This is the package's headline demonstration that errors are
  ordinary values you construct, not a closed core enum.
* **Scalar type guard.** :func:`_num` mirrors the core built-ins'
  ``_coerce_scalar_number`` (``None`` -> 0, ``int``/``float`` pass through,
  list/str -> ``#VALUE!``) with one deliberate stricter twist: a ``bool`` is
  ``#VALUE!``, not 1/0. This matches the spirit of core ``ISNUMBER`` /
  range-aggregation, which already treat bools as "not numbers".
* **No built-in overrides.** Every function name here is new; mathpack never
  shadows a core built-in.

STATUS (Part 4 #5): all 20 functions implemented and wired. ``setup()`` is the
single registration point, driven off one source of truth (:data:`FUNCTIONS`).
The hermetic discovery path is proven (``load_plugins`` + a fake entry point);
the real editable-install discovery proof is #7, gate sign-off is #8.
"""

from __future__ import annotations

import math
import statistics

from trellis import DIV0, NA, VALUE, FormulaError, register_function

__version__ = "0.1.0"
__all__ = ["setup", "NUM", "FUNCTIONS"]


# --- mathpack's own error value ----------------------------------------
# Core has DIV0/VALUE/REF/NAME/CIRC/NA/NULL but no #NUM!. We mint our own
# here for out-of-domain math (SQRT of a negative, LN of <= 0, ASIN/ACOS
# outside [-1, 1], POWER/EXP overflow). Equality is by code, so this
# compares equal to any other FormulaError("#NUM!") a caller constructs.
NUM = FormulaError("#NUM!", "Number outside the function's valid domain")


# --- Coercion + arg-count helpers --------------------------------------

def _num(x):
    """Coerce a scalar arg to a number, mirroring core's scalar rule.

    ``None`` -> 0 (empty cells act as zero), ``int``/``float`` pass through.
    A ``bool`` is rejected as ``#VALUE!`` (mathpack treats bools as non-numbers,
    unlike core arithmetic which coerces them). Lists (range args) and any
    other type are ``#VALUE!``. A ``FormulaError`` passes straight through
    (defensive — the eager dispatcher already short-circuits error args before
    a scalar function runs, so this branch is belt-and-braces).
    """
    if isinstance(x, FormulaError):
        return x
    if isinstance(x, bool):
        return VALUE
    if x is None:
        return 0
    if isinstance(x, (int, float)):
        return x
    return VALUE


def _argc(name: str, expected: str, got: int) -> FormulaError:
    """Standard ``#N/A`` for a wrong argument count (mirrors core built-ins)."""
    return FormulaError(NA.code, f"{name} expected {expected} args, got {got}")


def _collect_numerics(args):
    """Flatten the args of a range-aware stat function to a list of numbers.

    Mirrors core's ``builtins._collect_numerics`` in structure, with mathpack's
    bool-is-not-a-number stance applied to scalars:

    * A ``FormulaError`` anywhere — a scalar arg or inside a range — is returned
      immediately (error propagation).
    * **Inside a range** (a list arg): ``int``/``float`` are collected; ``bool``,
      ``str``, ``None`` and anything else are silently skipped. This is the Excel
      rule (``STDEV`` over a range ignores text, logicals, and blanks) and matches
      core's aggregates.
    * **As a scalar** arg: ``int``/``float`` are collected; ``None`` counts as 0
      (empty-cell-as-zero, mirrors core); a ``bool`` or any other type is a
      ``#VALUE!`` error. (Core counts a scalar bool as 1/0; mathpack rejects it,
      consistent with :func:`_num` and ``ISNUMBER``.)

    Returns a ``list`` of numbers, or a ``FormulaError``.
    """
    out = []
    for a in args:
        if isinstance(a, FormulaError):
            return a
        if isinstance(a, list):
            for v in a:
                if isinstance(v, FormulaError):
                    return v
                if isinstance(v, bool):
                    continue  # logicals in a range are skipped (Excel rule)
                if isinstance(v, (int, float)):
                    out.append(v)
                # str / None / other inside a range: silently skipped
        else:
            if isinstance(a, bool):
                return VALUE  # scalar bool is not a number in mathpack
            if isinstance(a, (int, float)):
                out.append(a)
            elif a is None:
                out.append(0)  # scalar empty acts as zero
            else:
                return VALUE  # scalar string / unknown type
    return out


# --- Scalar function bodies --------------------------------------------
# The simple one-argument functions share a factory: arg-count check, _num
# coercion, then the stdlib math call wrapped so any domain error (ValueError)
# or overflow (OverflowError) becomes our #NUM!. Angles are in radians.

_UNARY_MATH = {
    # Trig (6)
    "SIN": math.sin,
    "COS": math.cos,
    "TAN": math.tan,
    "ASIN": math.asin,   # domain [-1, 1]  -> ValueError -> #NUM!
    "ACOS": math.acos,   # domain [-1, 1]  -> ValueError -> #NUM!
    "ATAN": math.atan,
    # Hyperbolic (3)
    "SINH": math.sinh,
    "COSH": math.cosh,
    "TANH": math.tanh,
    # Powers / logs — the single-arg members (3 of 5)
    "SQRT": math.sqrt,   # x < 0          -> ValueError -> #NUM!
    "EXP": math.exp,     # large x        -> OverflowError -> #NUM!
    "LN": math.log,      # x <= 0         -> ValueError -> #NUM!
    # Misc — SIGN (1 of 3); returns -1 / 0 / 1, never raises
    "SIGN": lambda x: (x > 0) - (x < 0),
}


def _make_unary(name: str, fn):
    """Build a registered-shape ``fn(ctx, *args)`` for a one-arg math call."""
    def impl(ctx, *args):
        if len(args) != 1:
            return _argc(name, "1", len(args))
        x = _num(args[0])
        if isinstance(x, FormulaError):
            return x
        try:
            return fn(x)
        except (ValueError, OverflowError):
            return NUM
    impl.__name__ = f"_{name.lower()}"
    impl.__qualname__ = impl.__name__
    return impl


def _power(ctx, *args):
    """POWER(base, exponent). Domain errors / overflow -> #NUM!."""
    if len(args) != 2:
        return _argc("POWER", "2", len(args))
    base = _num(args[0])
    if isinstance(base, FormulaError):
        return base
    exponent = _num(args[1])
    if isinstance(exponent, FormulaError):
        return exponent
    try:
        return math.pow(base, exponent)
    except (ValueError, OverflowError):
        return NUM


def _log(ctx, *args):
    """LOG(x, [base=10]). x <= 0 or invalid base -> #NUM!.

    Base must be > 0 and != 1 (a base of 1 has no logarithm). Excel parity.
    """
    if len(args) not in (1, 2):
        return _argc("LOG", "1 or 2", len(args))
    x = _num(args[0])
    if isinstance(x, FormulaError):
        return x
    if len(args) == 2:
        base = _num(args[1])
        if isinstance(base, FormulaError):
            return base
    else:
        base = 10
    if base <= 0 or base == 1:
        return NUM
    try:
        return math.log(x, base)
    except (ValueError, OverflowError):
        return NUM


def _mod(ctx, *args):
    """MOD(number, divisor). Result takes the sign of the divisor (Excel /
    Python agree). MOD(x, 0) is #DIV/0! — the *core* error, not #NUM!.
    """
    if len(args) != 2:
        return _argc("MOD", "2", len(args))
    number = _num(args[0])
    if isinstance(number, FormulaError):
        return number
    divisor = _num(args[1])
    if isinstance(divisor, FormulaError):
        return divisor
    if divisor == 0:
        return DIV0
    return number % divisor


def _pi(ctx, *args):
    """PI() -> 3.14159...  Takes no arguments (zero-arg calls are supported)."""
    if len(args) != 0:
        return _argc("PI", "0", len(args))
    return math.pi


# Functions that aren't the plain one-arg shape.
_SPECIAL = {
    "POWER": _power,
    "LOG": _log,
    "MOD": _mod,
    "PI": _pi,
}


# --- Range-aware statistics --------------------------------------------
# STDEV / VAR are sample statistics (n-1) to match Excel's unsuffixed names;
# they need >= 2 data points (population variants STDEVP/VARP are deferred).
# MEDIAN needs >= 1. Python's statistics module enforces those minimums by
# raising StatisticsError, which we surface as the core #DIV/0! value.

_STATS = {
    "STDEV": statistics.stdev,      # sample standard deviation (n-1)
    "VAR": statistics.variance,     # sample variance (n-1)
    "MEDIAN": statistics.median,
}


def _make_stat(name: str, fn):
    """Build a registered-shape ``fn(ctx, *args)`` for a range-aware stat."""
    def impl(ctx, *args):
        nums = _collect_numerics(args)
        if isinstance(nums, FormulaError):
            return nums
        try:
            return fn(nums)
        except statistics.StatisticsError:
            return DIV0  # too few data points
    impl.__name__ = f"_{name.lower()}"
    impl.__qualname__ = impl.__name__
    return impl


# --- Plugin entry point ------------------------------------------------

def _registrations():
    """Yield ``(name, impl)`` for every function this plugin provides.

    Single source of truth for :func:`setup` and for the :data:`FUNCTIONS`
    listing — the three groups (unary scalars, special-arity scalars, range
    stats) are enumerated here and nowhere else.
    """
    for name, mfn in _UNARY_MATH.items():
        yield name, _make_unary(name, mfn)
    for name, impl in _SPECIAL.items():
        yield name, impl
    for name, sfn in _STATS.items():
        yield name, _make_stat(name, sfn)


#: Every function name mathpack registers, sorted. Public so callers/tests can
#: introspect the pack without invoking it (e.g. to assert no built-in clashes).
FUNCTIONS = tuple(sorted(set(_UNARY_MATH) | set(_SPECIAL) | set(_STATS)))


def setup() -> None:
    """Register all mathpack functions with the Trellis formula engine.

    This is the plugin's entry point: ``import trellis`` discovers it via the
    ``trellis.plugins`` group (``mathpack = "trellis_mathpack:setup"`` in
    ``pyproject.toml``) and calls it once, with no arguments. Importing this
    module alone registers nothing — registration happens here and only here,
    which is what the editable-install discovery test (#7) verifies.

    Idempotent: calling it again simply re-registers the same names (handy for
    the hermetic test tier, which drives it directly).
    """
    for name, impl in _registrations():
        register_function(name)(impl)
    return None
