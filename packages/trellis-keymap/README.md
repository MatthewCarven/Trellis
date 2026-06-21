# trellis-keymap

The **textual-free keymap contract** for Trellis frontends. A *keymap* is a
whole key language for a spreadsheet grid: it receives every key the focused
grid sees and answers with an `Action` from a closed vocabulary, which the
frontend's executor performs. The keymap never writes the engine — it reads a
read-only `KeyContext` and returns an Action — the frontend echo of "the grid
never writes".

This package is the contract and the default `ExcelKeymap`. It depends on
nothing but the standard library (`dataclasses`, `typing`,
`importlib.metadata`), exactly like the core engine, so:

- a **frontend** (the `trellis-tui` terminal UI today; a future GUI) imports it
  to *host* key languages, and
- a **keymap package** (`trellis-vim`) imports only it to *be* one,

without either pulling in the other's UI framework. The same Excel/vim keymaps
drive any frontend.

## Surface

- `KeyPress` — one parsed key, textual-free (`KeyPress.parse("ctrl+shift+z")`).
- `KeyContext` — the read-only state a keymap sees (cursor, selection,
  `used_range`, a live `cell(r, c)` accessor, viewport size, mode).
- `Action` and its closed vocabulary: `Move`, `MoveTo`, `Select`, `BeginEdit`,
  `EnterMode`, `Operate`, `Fill`, `Undo`, `Redo`, `Save`, `Quit`, `Sheet`,
  `Chain`, `Hint`.
- `Keymap` — the protocol a key language implements (`handle(key, ctx) ->
  Action | None`, stateful: counts and operators are parse state).
- `ExcelKeymap` — the default bindings, the proof that the contract holds for
  more than one consumer.
- `available_keymaps()` / `load_keymap(name)` — discovery. Keymap packages
  register a `name = "module:factory"` under the
  **`trellis_keymap.keymaps`** entry-point group; the built-in `excel`
  cannot be shadowed.

## The contract, in three disciplines

1. **The keymap never writes** — it returns Actions; the frontend executes.
2. **Textual-free** — keymap packages import only this module.
3. **Rects resolve at execution time** — `Operate`/`Fill` carry `rect=None`
   ("the live selection, else the cursor"); the executor resolves it after
   any queued `Move` lands.

See `docs/keymap-plugin.md` in the monorepo for the full contract doc and a
toy keymap, and `trellis-vim` for the reference implementation.
