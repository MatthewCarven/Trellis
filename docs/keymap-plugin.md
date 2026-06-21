# Writing a TUI keymap plugin

The terminal app's first extension point is the **keymap**: a whole key
language for the grid. The built-in Excel bindings are themselves one
(`ExcelKeymap`), and the reference plugin
([trellis-vim](../packages/trellis-vim)) is a full vim language —
modes, counts, operators, the `:` command line — in ~470 lines that
import only the contract. This doc is the contract, for the next author.

This is a **frontend hook, not an engine one**. A keymap package depends
on `trellis-tui`, imports one module (`trellis_tui.keymap`), and the
core engine never learns it exists. (For engine plugins — formula
functions, events + meta — see [plugin-example.md](plugin-example.md).)

## The shape of it

```python
from trellis_tui.keymap import Action, KeyContext, KeyPress, KeyRow, Move

class MyKeymap:
    name = "mine"

    def initial_mode(self) -> str:
        return "default"          # the resting mode; the indicator hides it

    def handle(self, key: KeyPress, ctx: KeyContext) -> Action | None:
        if key.key == "j" and not key.ctrl:
            return Move(1, 0)     # j moves down
        return None               # not ours: the key runs on

    def key_table(self) -> list[KeyRow]:
        return [("j", "move down")]
```

Every key the focused grid sees goes to `handle()` — one path, no
fall-through, the active keymap is the sole authority for the keys it
answers. Return an `Action` and the app executes it (and stops the key);
return `None` and the key continues to the framework and the app's
chrome bindings (sheet switching, tab management, save/quit prompts —
those stay app-owned).

## The three disciplines

1. **The keymap never writes.** `handle()` reads a `KeyContext` and
   names what the key *means*; the TUI executes it. The frontend echo of
   "the grid never writes the engine".
2. **Stay textual-free.** Import only `trellis_tui.keymap`. `KeyPress`
   is already parsed for you; if your package imports `textual`, it's
   wrong.
3. **Don't pre-resolve targets.** `Operate`/`Fill` default
   `rect=None` = "the live selection, else the cursor", resolved at
   execution time. Queued actions execute in order, so a
   `Move(extend=True)` burst followed by `Operate("copy")` can never
   copy a stale rectangle. Use the context to *compute motions* (data
   jumps, paging), not to bake coordinates.

## What `handle()` receives

`KeyPress` — one parsed key, modifiers split out: `key` (base name,
textual's naming: `"a"`, `"up"`, `"escape"`, `"f2"`), `char` (the
printable, or `None`), `ctrl`/`alt`/`shift` flags.
`KeyPress.parse("ctrl+shift+z")` builds one from a string — handy in
tests.

`KeyContext` — read-only state: `mode`, `cursor` (row, col),
`selection` / `used_range` (rects or `None`), `cell(row, col)` for live
engine cells (data-block motions), `viewport_rows`/`viewport_cols` for
page motions, `editing`. Coordinates are zero-indexed engine tuples; a
`Rect` is `((top, left), (bottom, right))`, inclusive.

While the cell editor has focus the keymap is bypassed entirely —
Insert mode belongs to the editor. Your keymap handles the grid.

## The Action vocabulary (closed)

| Action | Meaning |
|---|---|
| `Move(dr, dc, extend=False)` | relative cursor move; `extend` grows the selection |
| `MoveTo(row, col, extend=False)` | absolute move (`gg`, `Ctrl+Home`) |
| `Select(rect)` | set the selection outright (`Ctrl+A`, Visual entry) |
| `BeginEdit(caret="end", seed=None)` | enter the editor; `seed=None` = revise (F2), `seed="x"` = replace-and-type, `seed=""` = clear-and-type; `caret` = `"start"`\|`"end"` (vim `i` vs `a`) |
| `EnterMode(name)` | switch the mode indicator; entering `initial_mode()` also deselects and cancels a pending cut (the Esc contract) |
| `Operate(op, rect=None)` | `copy`/`cut`/`clear`/`paste`/`change` over rect-or-live-selection |
| `Fill(axis, rect=None)` | fill `"down"`/`"right"` (Excel Ctrl+D/R) |
| `Undo()` / `Redo()` | history |
| `Save(prompt=False)` / `Quit(force=False)` | the `:w` / `:q!` verbs |
| `Sheet(direction)` | cycle tabs, `"next"`/`"prev"` |
| `Chain(actions)` | several in order — one gesture, several verbs (`:wq`; vim's delete = yank-then-clear). Members resolve rects at their own execution time |
| `Hint(msg)` | show `msg` in the status bar; `Hint("")` is the explicit "consumed, do nothing" — the deaden, when you must eat a framework-bound key |

The vocabulary is closed by convention (the Part 3 discipline): the
executor matches on these classes, so an invented `Action` subclass gets
silence, not magic. If a real keymap needs a verb that isn't here,
that's a contract conversation — `Fill`, `Select`, and `Chain` each
joined exactly that way.

## State and modes

`Keymap` is a *stateful* strategy — one instance per session. Multi-key
gestures (counts, operator-pending, a `:` buffer) live in your instance;
answer `None` (or `Hint("…")` to echo progress) until the gesture
completes. The **app** is the mode authority: emit `EnterMode(name)`,
read it back as `ctx.mode`. Keep in the instance only what nobody else
can hold — the vim keymap keeps its pending count, pending operator,
`:` buffer, and visual-line's moving end, and nothing else.

The status bar renders `-- MODE --` (upper-cased) for any mode except
your `initial_mode()`. `BeginEdit` sets `insert` for you; closing the
editor restores the resting mode.

## Shipping it

Mathpack's discovery pattern, one layer out — register a factory under
the `trellis_tui.keymaps` entry point:

```toml
[project]
name = "trellis-tui-mine"
dependencies = ["trellis-tui"]

[project.entry-points."trellis_tui.keymaps"]
mine = "trellis_tui_mine:MyKeymap"
```

`pip install` it and `trellis --keymap mine file.csv` selects it
(`--vim` is sugar for the reference). The factory is any
`() -> Keymap` — the class itself usually. A plugin cannot shadow the
built-in `excel` name. Unknown names fail with the available list —
which is also your install smoke test:

```python
from trellis_tui.keymap import available_keymaps
assert "mine" in available_keymaps()
```

(Field note, 2026-06-12: an already-built venv does NOT see a package
added to the monorepo afterward — re-run `scripts/setup-venv.{ps1,sh}`
or `pip install -e packages/<name>` into the live venv.)

## Testing without a terminal

The contract is the testability story: `handle()` is a pure-ish function
of `(KeyPress, KeyContext)` and your own parse state, so the bulk of a
keymap's tests run hermetically — build a fake `KeyContext` (a frozen
dataclass; `cell` can be a dict lookup), feed `KeyPress.parse(...)`
sequences, assert on the returned Actions. The vim package's 26 hermetic
tests run in 0.2s this way; only 9 integration tests touch textual's
Pilot. Copy that ratio.

## What the reference proves

`trellis-vim` exercises every corner: modes via `EnterMode`, counts
and doubled operators as parse state, motions computed from
`ctx.cell`/`used_range`, Visual ops over execution-time rects, `Chain`
for `:wq`, the `:` line built entirely from `EnterMode("command")` +
`Hint(":…")` echoes — zero app changes, zero new widgets. When in
doubt, read its `__init__.py` next to this doc.
