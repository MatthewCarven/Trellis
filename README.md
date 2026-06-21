# Trellis

A minimalist, modular spreadsheet framework, written in Python.

Trellis is two things, and you can use either without the other:

1. **A spreadsheet engine** you can use as a library, from the REPL, or inside a script. No UI required.
2. **A terminal-first spreadsheet application**, built on top of the engine using [Textual](https://textual.textualize.io/).

The project's design philosophy is *open extensibility*. The core is small. Almost every feature beyond the data model is intended to be a plugin — formulas, file formats, conditional formatting, UI panels. The framework's job is to expose clean hooks; the bells and whistles are yours.

## Status

Pre-alpha. Public API is unstable until 0.1. The monorepo ships the engine, the **frontend-neutral keymap contract** ([trellis-keymap](packages/trellis-keymap), zero-dependency, hosts swappable key languages for any frontend), three reference extensions — [trellis-mathpack](packages/trellis-mathpack) (global registration via entry point), [trellis-undo](packages/trellis-undo) (stateful attachment via events + meta), and [trellis-vim](packages/trellis-vim) (a whole key language built on `trellis-keymap`) — and the terminal app ([trellis-tui](packages/trellis-tui), v1 + selection/clipboard/undo/fill/tabs/keymaps). Each reference package exists to prove one extension style real.

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

Formulas can reach across sheets in the workbook — `=Costs!A1`, `=SUM(Data!A1:A3)`, or `='My Sheet'!B2` when the name needs quoting. Cross-sheet references recompute across sheets, are rewritten automatically when a referenced sheet is renamed, and degrade to `#NAME?` if the sheet is missing.

## Quick taste (terminal app)

```
# in a venv (scripts/setup-venv.ps1 or .sh builds one for you):
pip install -e . -e packages/trellis-tui
trellis data.csv
```

Arrow around, type to edit, `=SUM(A1:A3)` recalculates as you'd hope, `Ctrl+S` saves, `Ctrl+Q` quits. Select with `Shift`+arrows; copy-paste shifts relative references Excel-style (`$A$1` pins), cut moves, the OS clipboard works both ways, and `Ctrl+D`/`Ctrl+R` fill down/right. Open several CSVs at once — `trellis sales.csv costs.csv` — and each gets a tab (a sheet is a file; the clipboard crosses tabs). Full key table and notes in [packages/trellis-tui/README.md](packages/trellis-tui/README.md). On Windows, run it inside Windows Terminal.

## Install

Not yet on PyPI. Once published:

```
pip install trellis           # engine only
pip install trellis-tui       # the terminal app (depends on the engine)
pip install trellis[xlsx]     # plus .xlsx read/write (future)
```

## Extending

Three flavours of hook, depending on what you need.

### 1. Subclass a core object

`Cell`, `Sheet`, and `Workbook` are all designed for subclassing. A `Cell` subclass works wherever a `Cell` does (`sheet["A1"] = MyCell(...)` preserves the subclass), and the `Workbook.add()` method accepts your own `Sheet` subclass.

### 2. Subscribe to events

`Sheet` and `Workbook` are emitters. Handlers fire synchronously, in registration order, and exceptions propagate to the caller — no swallowing. The change payloads carry the displaced and stored `Cell` objects, which is enough to build undo/redo from the outside: [trellis-undo](packages/trellis-undo) is exactly that — an `UndoLog` subscribing to `cell:change`/`sheet:batch` and stashing itself at `sheet.meta["undo"]`, zero core changes.

```python
from trellis import Workbook

wb = Workbook()
# Wire a cell-change logger onto every sheet as it's added.
# Handlers take **ev (the payload is a keyword dict); read the
# fields you care about. `address` is a zero-indexed (row, col) tuple.
from trellis.core.address import to_a1

wb.on("sheet:add", lambda sheet:
    sheet.on("cell:change", lambda **ev:
        print(f"{ev['sheet'].name}!{to_a1(*ev['address'])}: "
              f"{ev['old_value']!r} -> {ev['new_value']!r}")))

sh = wb.add_sheet("Demo")
sh["A1"] = 42      # prints: Demo!A1: None -> 42
sh["A1"] = 100     # prints: Demo!A1: 42 -> 100
```

Events emitted today:

- `Sheet` — `"cell:change"` (user-initiated writes) and `"cell:recalc"` (recalc-engine writes to dependent formula cells). Both payloads carry `sheet`, `address` (a zero-indexed `(row, col)` tuple), `old_value`/`new_value`, `old_formula`/`new_formula`, and the live `old`/`new` `Cell` objects. `cell:recalc` additionally carries `trigger` — the `(row, col)` of the user change that started the recalc cascade (`None` for a standalone recompute).
- `Sheet` — `"sheet:batch"` (fired once when a `with sheet.batch():` block exits cleanly) carrying `sheet` and `changes` (a list of per-cell change dicts, each shaped like a `cell:change` payload minus `sheet`). Per-cell `cell:change` is suppressed inside a batch.
- `Workbook` — `"sheet:add"`, `"sheet:remove"`, `"sheet:rename"`.
- Subscribe with `"*"` to receive every event from a given emitter.
- `Sheet.used_range()` returns `((min_row, min_col), (max_row, max_col))` (zero-indexed, inclusive) over non-empty cells, or `None` for an empty sheet — what a renderer or exporter calls to find the extent it must walk.
- `trellis.infer_value(text)` — the conservative text→value rule CSV loading uses (int → float → string; leading zeros, `+` signs, scientific notation stay strings). Public so a frontend can make typed input behave exactly like loaded data.
- `read_csv(path, formulas=True)` / `sheet.to_csv(path, formulas=True)` — opt-in formula round-trip: `=`-cells load live and save as source text. The default stays values-only/literal-text — an untrusted CSV never smuggles in live formulas, and plain exports carry values other tools can use. The TUI opts in for its own files.
- Real-world CSV robustness, no flags needed: `read_csv` defaults to a BOM-tolerant decode (strips the byte-order mark Excel-on-Windows writes) and sniffs the field delimiter (comma, semicolon, tab, or pipe) from the file's first line — so a European Excel export (BOM-prefixed, semicolon-separated) loads as columns instead of one fat string. Force either with `encoding="utf-8"` / `delimiter=";"`. Writes are atomic (temp file + `os.replace`), so an interrupted save never truncates your original.
- `trellis.shift_formula(text, rows, cols)` — rewrite the cell references in a formula string by a paste offset, Excel-style: `$` pins hold their axis (`$A$1` never moves), references shifted off the sheet edge become `#REF!` (a range collapses whole), and everything that doesn't move survives byte-for-byte. Error codes are first-class formula source (`=#REF!*2` parses and evaluates). What the TUI's copy-paste rides on; public so any tool can move formulas around.

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

### 5. Supply a TUI keymap (frontend hook)

The terminal app has its own extension point: a **keymap** — a whole key language for the grid (the built-in Excel bindings are themselves one). A keymap package registers a factory under the `trellis_keymap.keymaps` entry point and users select it with `trellis --keymap NAME`. The contract (`trellis_keymap`: `Keymap.handl