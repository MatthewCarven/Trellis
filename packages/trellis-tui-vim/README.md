# trellis-tui-vim

A vim keymap for the [Trellis](../../README.md) terminal spreadsheet — and the **reference keymap plugin**: it proves the [trellis-tui](../trellis-tui) keymap hook from outside, the way [trellis-mathpack](../trellis-mathpack) proves the engine's entry point. The three reference packages bracket the three extension styles: entry-point globals (mathpack), events + meta (trellis-undo), and a frontend strategy hook (this).

```
pip install -e packages/trellis-tui-vim
trellis --vim data.csv        # or --keymap vim
```

This package imports only the contract (`trellis_tui.keymap`) — never textual, never the app. It receives every key the grid sees and answers with `Action`s; the app executes them. The keymap never writes.

## The language (v1 core subset)

| Keys | Does |
|------|------|
| `h j k l` / arrows | move — counts work (`3j`) |
| `w` / `b` | next / previous data block in the row (Excel `Ctrl+→`/`←`) |
| `0` `^` / `$` | first / last filled cell in the row |
| `gg` / `G` | top / bottom of the column's data; `{n}G` (or `:{n}`) = row *n* |
| `Ctrl+D` / `Ctrl+U` | half page down / up (`Ctrl+R` is redo, as in vim — fill is the Excel keymap's binding) |
| `i` `I` / `a` `A` | edit the cell, caret at start / end |
| `x` | delete cell(s) — **yanks first**, so `x` then `p` moves a cell |
| `dd` / `yy` / `cc` | delete / yank / change the row (counts: `3dd`) |
| `p` `P` | paste at the cursor |
| `v` / `V` / `Ctrl+V` | visual / visual-line / visual-block (block = visual: it's already a grid) |
| visual + `d`/`x`/`y`/`c`/`p` | operate on the selection, drop to normal |
| `u` / `Ctrl+R` | undo / redo |
| `:w` `:q` `:wq` `:x` `:q!` `:{n}` | write, quit, both, force-quit, go to row |
| `Esc` / `Ctrl+C` | back to normal; deselect (`Ctrl+C` never quits mid-thought) |

The mode rides the TUI status bar (`-- VISUAL --`, `-- INSERT --`, `-- COMMAND --` with the `:` buffer echoed); normal shows nothing. Window chrome stays the app's under any keymap: `Ctrl+S`/`Ctrl+Q`, tab keys, `Ctrl+T`/`Ctrl+W` all still work.

## Vim decisions made here (vim-internal, per design.md Part 10)

- **Delete is yank** (`x`/`dd`/visual `d` copy before clearing) — `dd` `p` moves a row, as your fingers expect. The design sketch said "d/x clear"; vim says otherwise.
- **`c` doesn't yank** — `cc`/visual `c` clear and open the editor.
- **`p` = `P`** — the grid pastes *at* the cursor (Excel's model); before/after has no cell meaning.
- **Operators take doubles or the Visual selection** — `d3j`/`dw` composition is not in v1 (counts × *motions* work everywhere: `3j`, `5G`, `2w`, `3x`, `3dd`).
- **Deferred with reasons:** `o`/`O` (need `Sheet.insert_row` — an engine part), search, `f`/`t`, marks, registers, macros, `.`-repeat.

## Develop / test

Hermetic parser tests need no textual; the integration tests drive the real app headless (Pilot):

```
cd packages/trellis-tui-vim
PYTHONPATH=src:../trellis-tui/src:../../src:../trellis-undo/src python -m pytest
```
