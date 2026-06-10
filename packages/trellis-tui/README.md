# trellis-tui

The terminal frontend for [Trellis](../../README.md) — a [Textual](https://textual.textualize.io/) application that drives the spreadsheet engine from the outside.

**A frontend, not a plugin.** There is no `trellis.plugins` entry point here and the core never imports this package. The app holds a real `Workbook` — the same object a REPL would drive — and repaints only in response to the engine's events (`cell:change` / `cell:recalc` / `sheet:batch`), including for its own writes. Anything the TUI can do, your script can do with the same objects. Architecture and decisions: `design.md` Part 5.

## Status

**v1 complete** (design.md Part 5 #1–#7) plus **selection + clipboard** (Part 6), **keyboard fill** (Part 8), **sheet tabs** (Part 9), and **keymaps** (Part 10 — the layer *and* the reference [vim keymap](../trellis-tui-vim); field check pending): an editable, CSV-backed, multi-sheet terminal spreadsheet whose key language is swappable.

- A live grid over the engine: A1-anchored window that grows as you arrow into empty space; Excel-faithful rendering (`4.0` → `4`, `TRUE`/`FALSE` centered, errors as red `#DIV/0!` codes, float noise trimmed so `=0.1+0.2` shows `0.3`).
- Excel-ish editing: type to replace, `F2`/`Enter` to revise, commits move the cursor, and typed input gets the engine's conservative inference (`42` is a number, `01234` stays text — the same public `trellis.infer_value` rule CSV loading uses).
- Formulas commit even when broken: the error value shows in the grid and `F2` hands your text back. Errors are values here.
- CSV open/save **with formulas intact** — the TUI passes `formulas=True` to the engine's CSV I/O both ways, so `=SUM(A1:A2)` survives save and reopen as a live formula. (Want a values-only export for other tools? That's the engine default: `sheet.to_csv(path)` from a REPL.) Plus dirty tracking, a quit guard, and a status line that shows what recalculated and why (`recalc B1 ← A1`).
- **Undo/redo** (Part 7): `Ctrl+Z` / `Ctrl+Y`, one step per gesture — an edit singly, a paste / selection-delete / file-load batch as one step. Backed by [trellis-undo](../trellis-undo), which the TUI depends on; the live log is `app.undo_log` (also `sheet.meta["undo"]`), the same object you'd drive from a REPL.
- **Keyboard fill** (Part 8): `Ctrl+D` fills down, `Ctrl+R` fills right — within the selection from its first row/column, or with no selection from the cell above/left, Excel-exact. Formulas shift per lane (`$` pins hold), values copy, empty sources clear; the whole fill is one batch and one undo step, and your clipboard is never touched. Field tip: `Ctrl`+click the cell you want the fill to *end* at (extending the selection there), then `Ctrl+D` — the selection is the fill's extent. No series extrapolation, on purpose: put `=A1+1` below a value and fill down — **the formula IS the series** (and recalc keeps it honest where a pasted 1,2,3 would go stale).
- **Sheet tabs — a sheet is a file** (Part 9): CSV is a single-sheet format, so tabs are an editor's open buffers, not Excel's workbook-in-one-file. `trellis sales.csv costs.csv` opens two tabs (named for the file stems); each tab has its own path, its own dirty marker (a ● on the tab), and its own undo history. `Ctrl+S` saves the **active** sheet; `Ctrl+Q` warns once about every unsaved one. `Ctrl+PgUp`/`Ctrl+PgDn` (or click) switch, `Ctrl+T` adds a pathless sheet, `Ctrl+W` closes (warns once if unsaved), `Ctrl+Shift+R` or double-clicking the tab renames the *sheet* — never the file. The clipboard crosses tabs: copy here, paste there, formulas shifting as usual; a cut-paste across tabs clears the source cells on the sheet they came from, one undo step per side. Cross-sheet *references* (`=Sheet2!A1`) don't exist yet — formulas are sheet-local (deferred, with reasons, in design.md).
- **Keymaps — the TUI's first extension point** (Part 10): every key the grid sees flows through ONE path — `app.active_keymap.handle(key, ctx) -> Action` — and the default Excel bindings are themselves a keymap (`ExcelKeymap`), so the contract is proved by a real consumer from day one. A keymap package implements the textual-free contract in `trellis_tui.keymap` (`KeyPress` in, `Action` out, a read-only `KeyContext` to compute motions with — the keymap never writes, the app's executor does), registers a factory under the `trellis_tui.keymaps` entry point, and users opt in with `--keymap NAME` (`--vim` is sugar; the reference is [trellis-tui-vim](../trellis-tui-vim) — modes, counts, operators, and the `:` command line, importing only the contract). Window chrome (save/quit/tab keys) stays the app's, but emits the same `Action`s through the same executor — a keymap's `:w` reaches the identical save. The status bar shows the keymap's mode (`-- INSERT --` while editing); the resting mode shows nothing.
- **Selection + clipboard, Excel-faithful where it counts** (Part 6): `Shift`+arrows extend (so does modifier+click — `Ctrl` or `Alt`, since terminals reserve `Shift`+mouse for native text selection), `Ctrl+A` selects the used range, the bar reads out `B2:D5 (3×4)`. Copy-paste **shifts relative references** by the paste offset (`=A1*2` copied down becomes `=A2*2`) and `$` pins opt out (`$A$1` stays put — the engine grew real absolute references for this); a reference pushed off the sheet edge lands as a literal `#REF!`, which the engine evaluates as the error it names. A single copied cell **fills** a selected range on paste. Cut is the pragmatic move: paste relocates verbatim and clears the source in the same batch (formulas *pointing at* the moved cells are not rewritten — documented deviation), and a pending cut disarms on Esc or any sheet change. The OS clipboard works **both ways**: copies mirror out as TSV (OSC 52), and pasting — from Excel, a browser, anywhere — arrives as text, every field committed exactly as if typed (so `=`-leading fields come in as live formulas). Your own copy bouncing back through the OS is recognized (line-ending mangling included) and keeps full fidelity. One ecosystem truth: the *plain-text* clipboard carries computed values, not formulas — that's what every spreadsheet (Excel and OpenOffice included) puts there, and the rich formats they use between themselves aren't speakable from a terminal. Formulas survive any Trellis→Trellis copy; cross-app transfers carry values.

Deliberately **not** here yet (each with a reason in design.md): inbound-reference rewriting on cut, save-point dirty tracking (undoing back to the saved state still shows ● modified), mouse drag-fill and series fill (the keyboard fill + formulas cover both), cross-sheet references (sheet-local formulas only — the engine part when it comes), save-all (close/quit warnings cover the leak), themes, a general TUI plugin API (keymaps are the first, deliberately narrow hook — Part 10's reasons).

## Install (development)

Not on PyPI yet. From the repo root:

```
# Windows:  scripts\setup-venv.ps1     then  .venv\Scripts\Activate.ps1
# POSIX:    scripts/setup-venv.sh      then  source .venv/bin/activate

# or by hand, into any venv:
pip install -e . -e packages/trellis-tui
```

**Windows note:** run it inside [Windows Terminal](https://aka.ms/terminal) (or any modern terminal emulator). Textual apps render poorly in the legacy console host.

## Usage

```
trellis                # empty workbook
trellis data.csv       # open a CSV
trellis new.csv        # nonexistent path: empty workbook, Ctrl+S creates the file
trellis --version
python -m trellis_tui  # same thing

trellis --keymap NAME data.csv   # pick a key language (default: excel)
trellis --vim data.csv           # sugar for --keymap vim (pip install -e packages/trellis-tui-vim)
```

## Keys

| Key | In the grid (nav) | While editing |
|-----|-------------------|---------------|
| Arrows / PgUp / PgDn / Home / End | move the cursor | move the text cursor |
| any printable character | start a **replace** edit, seeded with it | type |
| `F2` / `Enter` | start a **revise** edit (formula, or full-fidelity value text) | — / commit + move down |
| `Tab` / `Shift+Tab` | — | commit + move right / left |
| `Shift+Enter` | — | commit + move up |
| `Esc` | — | cancel the edit |
| `Delete` | clear the cell | delete right |
| `Backspace` | clear + start an empty edit | delete left |
| `Shift`+arrows / `Ctrl`+click (or `Alt`+click) | extend the selection — most terminals keep `Shift`+click for themselves | — |
| `Ctrl+A` | select the used range | select all text |
| `Esc` (with a selection / pending cut) | collapse the selection; disarm a cut | cancel the edit |
| `Ctrl+C` / `Ctrl+X` | copy / cut the selection (or cursor cell) | copy / cut text |
| `Ctrl+V` (or any OS paste) | paste — fills from a single cell; external text commits as typed | paste text |
| `Delete` (with a selection) | clear every selected cell (one undo-friendly batch) | — |
| `Ctrl+D` | fill down — from the selection's first row, or the cell above | delete right |
| `Ctrl+R` | fill right — from the selection's first column, or the cell to the left | — |
| `Ctrl+PgDn` / `Ctrl+PgUp` | next / previous sheet (wraps) | same — switching is blocked with a hint |
| `Ctrl+T` | new pathless sheet (`SheetN`) | — |
| `Ctrl+W` | close the tab — unsaved warns once; the last tab refuses | delete word left |
| `Ctrl+Shift+R` / double-click tab | rename the sheet (modal) | — |
| `Ctrl+Z` | undo (one gesture per step) | — |
| `Ctrl+Y` / `Ctrl+Shift+Z` | redo (dies on any new edit) | — |
| `Ctrl+Home` | jump to A1 | — |
| `Ctrl+S` | save CSV, formulas included (modal path prompt if pathless) | saves committed state |
| `Ctrl+Q` | quit — warns once if unsaved | quit |

Commit rules: empty text clears the cell; a leading `=` is a formula (a broken formula commits as its error value — fix it later with `F2`); everything else gets `int → float → string` inference with the CSV loader's conservatisms (leading zeros, `+` signs, surrounding whitespace, and scientific notation all stay strings). An unmodified revise-edit commits nothing, so `F2` + `Enter` is always a safe no-op.

## Develop / test

Hermetic, no install needed (`textual` and `pytest-asyncio` must be importable):

```
cd packages/trellis-tui
PYTHONPATH=../../src:src:../trellis-undo/src python -m pytest
```

The suite is Pilot-based (headless Textual) plus pure unit tests for the display, commit, and keymap contracts — 196 tests as of Part 10 row 3 (the vim package carries its own 35). The display table in `tests/test_render.py` is the rendering spec; change it deliberately or not at all. `tests/test_keymap.py` is the keymap contract's spec, toy-keymap proof included.
