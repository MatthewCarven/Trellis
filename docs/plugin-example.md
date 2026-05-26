# Writing a formula function plugin

Trellis's formula engine is built around a small public API:

```python
from trellis import register_function, FormulaError, VALUE
```

`register_function` is a decorator. Decorate a Python callable and it becomes callable from any formula in any workbook, immediately. There is no separate "install" step today — that's coming with task #5 (`entry_points`-based auto-discovery, so `pip install trellis-mathpack` registers itself).

## A first function

```python
from trellis import Workbook, register_function, FormulaError, VALUE

@register_function("DOUBLE")
def _double(ctx, *args):
    # Argument count is your responsibility — return #N/A if wrong.
    if len(args) != 1:
        return FormulaError("#N/A", "DOUBLE takes 1 arg")

    # Type-check yourself. Bools are ``int`` in Python; spreadsheets
    # treat them separately, so check ``bool`` first.
    x = args[0]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return VALUE

    return x * 2

wb = Workbook()
sh = wb.add_sheet("D")
sh["A1"] = 21
sh["B1"] = "=DOUBLE(A1)"
assert sh["B1"].value == 42
```

That's the entire surface for the common case.

## The contract

Every registered function is called as `fn(ctx, *args)`:

- `ctx` is a `Context` carrying the `Sheet` the formula lives on (and the formula's own address as `current_cell`, useful for circular-reference checks).
- `args` are the *evaluated values* of the function's arguments by default (see lazy mode below).

What you can return:

- Any Python value — numbers, strings, bools, `None`, a list (for range-producing functions).
- A `FormulaError`. **Errors are values, not exceptions.** Returning `FormulaError(...)` is how you signal `#DIV/0!`, `#VALUE!`, `#N/A`, etc. Raising a Python exception breaks the engine's "evaluation always returns a value" contract.

Standard error constants you can `return` directly:

```python
from trellis import DIV0, VALUE, REF, NAME, CIRC, NA, NULL
```

Or build a custom one with a contextual message:

```python
return FormulaError("#VALUE!", "MYFUNC: expected number, got str")
```

## Range arguments

A range like `A1:B3` arrives in your function as a **flat list** of values in row-major order (None for empty cells, FormulaError for cells whose own values are errors):

```python
@register_function("AVGNONZERO")
def _avgnz(ctx, *args):
    nums = []
    for a in args:
        if isinstance(a, list):
            for v in a:
                if isinstance(v, FormulaError):
                    return v   # propagate errors out of ranges
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
                    nums.append(v)
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            if a != 0:
                nums.append(a)
        elif a is None:
            continue
        else:
            return VALUE   # scalar string / other — reject
    if not nums:
            return FormulaError("#DIV/0!", "AVGNONZERO of no values")
    return sum(nums) / len(nums)
```

The built-ins follow the same pattern. Look at `src/trellis/formula/builtins.py` for worked references — `SUM` / `AVERAGE` / `MIN` / `MAX` show the aggregate pattern, `CONCAT` shows text functions, `LEFT` / `RIGHT` / `MID` show variable arg-count handling.

## Lazy mode (for control-flow functions)

By default the evaluator pre-evaluates your arguments. That means `=YOURFN(1/0)` short-circuits to `#DIV/0!` **before your function is called** — which is the right behaviour for almost every function, but not for control flow.

`IF`, `IFERROR`, and `ISERROR` need lazy mode: they decide *whether* to evaluate each argument. Mark a function `lazy=True` and your `args` arrive as raw AST nodes; call `ctx.evaluate(node)` to materialize them.

```python
@register_function("UNLESS", lazy=True)
def _unless(ctx, *args):
    """UNLESS(cond, value): value if cond is falsy, otherwise FALSE.

    The inverted-condition twin of a one-armed IF — value is
    evaluated only when the condition is falsy.
    """
    if len(args) != 2:
        return FormulaError("#N/A", "UNLESS takes 2 args")
    cond = ctx.evaluate(args[0])
    if isinstance(cond, FormulaError):
        return cond
    if cond:
        return False
    return ctx.evaluate(args[1])
```

`ISERROR` is the canonical example of *why* lazy matters in the other direction: an eager `ISERROR(1/0)` would never run, because the dispatcher would short-circuit `1/0` to `#DIV/0!` before reaching the function. Lazy lets `ISERROR` *see* the error and report it as a boolean.

## Overriding built-ins

`register_function` silently replaces any existing registration under the same name. This is intentional — plugins can override built-ins. Use sparingly; users will be surprised if `=SUM(...)` suddenly means something different.

```python
@register_function("SUM")   # replaces the built-in for THIS process
def _strict_sum(ctx, *args):
    ...
```

For sanity, prefer a distinct namespace prefix (`MYLIB_SUM`) unless you really do want to override.

## Where to go next

- `src/trellis/formula/builtins.py` — every built-in is small, public-by-default, and self-contained. Best reference for "how do real ones look."
- `src/trellis/formula/functions.py` — the registry itself (`_REGISTRY`, the decorator, the lookup helpers).
- `design.md` Part 2 — the formula engine's design rationale, including the lazy-arg story and the "errors as values" model.
