# Writing a formula function plugin

Trellis's formula engine is built around a small public API:

```python
from trellis import register_function, FormulaError, VALUE
```

`register_function` is a decorator. Decorate a Python callable and it becomes callable from any formula in any workbook, immediately. For a one-off function in your own script, that's all you need. To ship a function as an installable package — so users `pip install your_plugin` and the function is available — see [Shipping a plugin as an installable package](#shipping-a-plugin-as-an-installable-package) at the bottom.

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

## Namespacing your cell / sheet / workbook metadata

`Cell`, `Sheet`, and `Workbook` each carry a public `meta = {}` dict. It is
yours — core never writes to it. But it's *shared*: every plugin sees the
same dict, so two plugins that both reach for `meta["color"]` will clobber
each other.

The convention: **namespace your keys under a single key named for your
plugin**, and keep your state in a dict under it.

```python
# Good — each plugin owns one top-level key:
cell.meta["styles"] = {"bold": True, "color": "red"}
cell.meta["validation"] = {"rule": "int_range", "min": 0, "max": 100}

# Bad — flat keys collide across plugins:
cell.meta["bold"] = True
cell.meta["color"] = "red"
cell.meta["validation_rule"] = "int_range"
```

This is a **convention, not an enforced rule**. Trellis deliberately doesn't
wrap `meta` in a guarded proxy — that's the kind of "for safety"
encapsulation the project avoids (see `design.md`, the open-extensibility
philosophy). A plugin that ignores the convention works fine right up until
it collides with another plugin; the collision is the consequence, and
that's enough. Pick a key unlikely to clash — your distribution name is a
good default (`cell.meta["trellis_mathpack"]`).

## Where to go next

- `src/trellis/formula/builtins.py` — every built-in is small, public-by-default, and self-contained. Best reference for "how do real ones look."
- `src/trellis/formula/functions.py` — the registry itself (`_REGISTRY`, the decorator, the lookup helpers).
- `design.md` Part 2 — the formula engine's design rationale, including the lazy-arg story and the "errors as values" model.

## Shipping a plugin as an installable package

The decorator works fine in a single script, but for a package others can install, you want Trellis to auto-discover your plugin on import. Trellis scans the `trellis.plugins` entry point group when `import trellis` runs and invokes each registered callable.

### 1. Write a setup function

In your package, expose a no-argument callable that registers everything you want to add:

```python
# trellis_mathpack/__init__.py
from trellis import register_function, VALUE
import math

def setup():
    @register_function("COSH")
    def _cosh(ctx, x):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return VALUE
        return math.cosh(x)

    @register_function("SINH")
    def _sinh(ctx, x):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return VALUE
        return math.sinh(x)
```

The setup function takes no arguments. It can do anything — register functions, subscribe to events, register custom Cell subclasses, monkey-patch internals. Trellis treats it as opaque code that runs once at startup.

### 2. Declare the entry point

In your package's `pyproject.toml`:

```toml
[project.entry-points."trellis.plugins"]
mathpack = "trellis_mathpack:setup"
```

The left-hand name (`mathpack`) is the plugin identifier shown in error messages and returned by `load_plugins()`. The right-hand side is a `module:attribute` reference to your setup callable.

### 3. That's it

After `pip install trellis_mathpack`, opening a Python REPL and importing Trellis loads your plugin:

```python
>>> from trellis import Workbook
>>> wb = Workbook(); sh = wb.add_sheet("S")
>>> sh["A1"] = 1.0
>>> sh["B1"] = "=COSH(A1)"
>>> sh["B1"].value
1.5430806348152437
```

### Failure handling

If your setup function raises, Trellis reports the failure via `warnings.warn` (category `RuntimeWarning`) and continues loading other plugins. Your plugin's functions won't be registered, but the rest of Trellis (and other plugins) still work. Test your setup with `python -W error::RuntimeWarning -c "import trellis"` to make warnings fatal during development.

### Disabling discovery

For reproducible scripts or "is this Trellis or a plugin?" debugging, set the environment variable:

```bash
TRELLIS_DISABLE_PLUGIN_DISCOVERY=1 python my_script.py
```

This skips the entry_points scan entirely. Built-in functions still work; only third-party plugins are suppressed.

### Manual discovery

`trellis.load_plugins()` is public. Useful if you disabled auto-discovery and want to opt back in, or if you installed a plugin into a running process and want to pick it up without restarting:

```python
import trellis
loaded = trellis.load_plugins()   # returns list of plugin names that loaded successfully
```

You can also pass a custom iterable of entry-point-like objects (anything with `.name` and `.load()`) — that's what the test suite does to keep tests hermetic.
