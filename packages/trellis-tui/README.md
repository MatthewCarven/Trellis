# trellis-tui

The terminal frontend for [Trellis](../../README.md) — a [Textual](https://textual.textualize.io/) application that drives the spreadsheet engine from the outside.

**A frontend, not a plugin.** There is no `trellis.plugins` entry point here and the core never imports this package. The app holds a real `Workbook` — the same object a REPL would drive — and repaints only in response to the engine's events (`cell:change` / `cell:recalc` / `sheet:batch`), including for its own writes. Anything the TUI can do, your script can do with the same objects. Architecture and decisions: `design.md` Part 5.

## Status

**v1 complete** (design.md Part 5 #1–#7) plus **selection + clipboard** (Part 6): an editable, CSV-backed terminal spreadsheet.

- A live grid over the engine: A1-anchored window that grows as you arrow into empty space; Excel-faithful rendering (`4.0` → `4`, `TRUE`/`FALSE` centered, errors as red `#DIV/0!` codes, float noise trimmed so `=0.1+0.2` shows `0.3`).
- Excel-ish editing: type to replace, `F2`/`Enter` to revise, commits move the cursor, and typed input gets the engine's conservative inference (`42` is a number, `01234` stays text — the same public `trellis.infer_value` rule CSV loading uses).
- Formulas commit even when broken: the error value shows in the grid and `F2` hands your text back. Errors are values here.
- CSV open/save **with formulas intact** — the TUI passes `formulas=True` to the engine's CSV I/O both ways, so `=SUM(A1:A2)` survives save and reopen as a live formula. (Want a values-only export for other tools? That's the engine default: `sheet.to_csv(path)` from a REPL.) Plus dirty tracking, a quit guard, and a status line that shows what recalculated and why (`recalc B1 ← A1`).
- **Selection + clipboard, Excel-faithful where it counts** (Part 6): `Shift`+arrows / `Shift`+click extend, `Ctrl+A` selects the used range, the bar reads out `B2:D5 (3×4)`. Copy-paste **shifts relative references** by the paste offset (`=A1*2` copied down becomes `=A2*2`) and `$` pins opt out (`$A$1` stays put — the engine grew real absolute references for this); a reference pushed off the sheet edge lands as a literal `#REF!`, which the engine evaluates as the error it names. A single copied cell **fills** a selected range on paste. Cut is the pragmatic move: paste relocates verbatim and clears the source in the same batch (formulas *pointing at* the moved cells are not rewritten — documented deviation), and a pending cut disarms on Esc or any sheet change. The OS clipboard works **both ways**: copies mirror out as TSV (OSC 52), and pasting — from Excel, a browser, anywhere — arrives as text, every field committed exactly as if typed (so `=`-leading fields come in as live formulas). Your own copy bouncing back through the OS is recognized and keeps full fidelity.

Deliberately **not** here yet (each with a reason in design.md): undo (a future plugin — the event payloads already carry everything it needs), inbound-reference rewriting on cut, fill handle, sheet tabs, themes, a TUI plugin API.

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
| `Shift`+arrows / `Shift`+click | extend the selection | — |
| `Ctrl+A` | select the used range | select all text |
| `Esc` (with a selection / pending cut) | collapse the selection; disarm a cut | cancel the edit |
| `Ctrl+C` / `Ctrl+X` | copy / cut the selection (or cursor cell) | copy / cut text |
| `Ctrl+V` (or any OS paste) | paste — fills from a single cell; external text commits as typed | paste text |
| `Delete` (with a selection) | clear every selected cell (one undo-friendly batch) | — |
| `Ctrl+Home` | jump to A1 | — |
| `Ctrl+S` | save CSV, formulas included (modal path prompt if pathless) | saves committed state |
| `Ctrl+Q` | quit — warns once if unsaved | quit |

Commit rules: empty text clears the cell; a leading `=` is a formula (a broken formula commits as its error value — fix it later with `F2`); everything else gets `int → float → string` inference with the CSV loader's conservatisms (leading zeros, `+` signs, surrounding whitespace, and scientific notation all stay strings). An unmodified revise-edit commits nothing, so `F2` + `Enter` is always a safe no-op.

## Develop / test

Hermetic, no install needed (`textual` and `pytest-asyncio` must be importable):

```
cd packages/trellis-tui
PYTHONPATH=../../src:src python -m pytest
```

The suite is Pilot-based (headless Textual) plus pure unit tests for the display and commit policies — 126 tests as of Part 6. The display table in `tests/test_render.py` is the rendering spec; change it deliberately or not at all.
