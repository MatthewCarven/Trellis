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
sheet = wb.add_sheet("Demo")
sheet["A1"] = 42
sheet["B1"] = "=A1*2"   # formula stored; engine evaluates it
print(sheet["A1"].value, sheet["B1"].value)
```

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

### 2. Subscribe to events (live now)

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

- `Sheet` — `"cell:change"` with `addr`, `old`, `new`.
- `Workbook` — `"sheet:add"`, `"sheet:remove"`, `"sheet:rename"`.
- Subscribe with `"*"` to receive every event from a given emitter.

The `Emitter` mixin (and `Subscription` handle) are re-exported from `trellis` if you want pub/sub on your own classes — it's a drop-in mixin and doesn't require `super().__init__()`.

### 3. Register into a plugin registry (coming)

For formula functions, file format handlers, renderers, and UI panels. A `pip install trellis-yourthing` package will register itself automatically via `entry_points`. Lands with the formula engine and file I/O.

A worked plugin example will live under `docs/` once the registry surface is locked in.

## License

MIT.
