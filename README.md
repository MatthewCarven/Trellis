# Trellis

A minimalist, modular spreadsheet framework, written in Python.

Trellis is two things, and you can use either without the other:

1. **A spreadsheet engine** you can use as a library, from the REPL, or inside a script. No UI required.
2. **A terminal-first spreadsheet application**, built on top of the engine using [Textual](https://textual.textualize.io/).

The project's design philosophy is *open extensibility*. The core is small. Almost every feature beyond the data model is intended to be a plugin — formulas, file formats, conditional formatting, UI panels. The framework's job is to expose clean hooks; the bells and whistles are yours.

## Status

Pre-alpha. Public API is unstable until 0.1.

## Quick taste (library)

```python
from trellis import Workbook

wb = Workbook()
sh = wb.add_sheet("Demo")

sh["A1"] = 10
sh["A2"] = 20
sh["A3"] = 30
sh["B1"] = "=SUM(A1:A3)"
sh["B2"] = '=IF(B1 > 50, "big", "small")'

print(sh["B1"].value)   # 60
print(sh["B2"].value)   # 'big'

sh["A1"] = 100          # dependents recompute automatically
print(sh["B1"].value)   # 150
print(sh["B2"].value)   # 'big'
```

22 built-in functions ship with the engine — aggregates (`SUM`, `AVERAGE`, `COUNT`, `MIN`, `MAX`), scalar math (`ABS`, `ROUND`, `INT`), logical (`IF`, `IFERROR`, `ISERROR`, `AND`, `OR`, `NOT`), type checks (`ISBLANK`, `ISNUMBER`, `ISTEXT`), and text (`CONCAT`, `LEN`, `LEFT`, `RIGHT`, `MID`). Anything else is a plugin — see [docs/plugin-example.md](docs/plugin-example.md).

## Install

Not yet on PyPI. Once published:

```
pip install trellis           # engine only
pip install trellis[tui]      # plus the terminal UI
pip install trellis[xlsx]     # plus .xlsx read/write
pip install trellis[all]      # the lot
```

## Extending

Three flavours of hook, depending on what you need.

### 1. Subclass a core object

`Cell`, `Sheet`, and `Workbook` are all designed for subclassing. A `Cell` subclass works wherever a `Cell` does (`sheet["A1"] = MyCell(...)` preserves the subclass), and the `Workbook.add()` method accepts your own `Sheet` subclass.

### 2. Subscribe to events

`Sheet` and `Workbook` are emitters. Handlers fire synchronously, in registration order, and exceptions propagate to the caller — no swallowing.

```python
from trellis import Workbook

wb = Workbook()
# Wire a cell-change logger onto every sheet as it's added:
wb.on("sheet:add", lambda sheet:
    sheet.on("cell:change", lambda addr, old, new:
        print(f"{sheet.name}!{addr}: {old.value!r} -> {new.value!r}")))

sh = wb.add_sheet("Demo")
sh["A1"] = 42      # prints: Demo!A1: None -> 42
sh["A1"] = 100     # prints: Demo!A1: 42 -> 100
```

Events emitted today:

- `Sheet` — `"cell:change"` (user-initiated writes) and `"cell:recalc"` (recalc-engine writes to dependent formula cells). Both carry `addr`, `old`, `new`.
- `Workbook` — `"sheet:add"`, `"sheet:remove"`, `"sheet:rename"`.
- Subscribe with `"*"` to receive every event from a given emitter.

The `Emitter` mixin (and `Subscription` handle) are re-exported from `trellis` if you want pub/sub on your own classes — it's a drop-in mixin and doesn't require `super().__init__()`.

### 3. Register a formula function

```python
from trellis import Workbook, register_function, FormulaError, VALUE

@register_function("DOUBLE")
def _double(ctx, *args):
    if len(args) != 1:
        return FormulaError("#N/A", "DOUBLE takes 1 arg")
    x = args[0]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return VALUE
    return x * 2

wb = Workbook()
sh = wb.add_sheet("D")
sh["A1"] = 21
sh["B1"] = "=DOUBLE(A1)"
print(sh["B1"].value)   # 42
```

Functions can be **eager** (default, args pre-evaluated) or **lazy** (`@register_function("MYFN", lazy=True)` — args arrive as un-evaluated AST nodes, useful for control-flow built-ins like IF and IFERROR). Errors are values: return a `FormulaError` rather than raising. See [docs/plugin-example.md](docs/plugin-example.md) for the full story.

### 4. Ship a plugin as an installable package

For a plugin that ships as a package others can install, declare an entry point in your `pyproject.toml`:

```toml
[project.entry-points."trellis.plugins"]
mathpack = "trellis_mathpack:setup"
```

`trellis_mathpack.setup` is a no-argument callable that does the `@register_function` decorations (and anything else you want — subscribe to events, register Cell subclasses, etc.). Trellis auto-discovers it on `import trellis`. A broken plugin warns and is skipped; others still load. Set `TRELLIS_DISABLE_PLUGIN_DISCOVERY=1` to opt out. Full story in [docs/plugin-example.md](docs/plugin-example.md).

## License

MIT.
