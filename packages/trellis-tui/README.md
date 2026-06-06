# trellis-tui

The terminal frontend for [Trellis](../../README.md) — a [Textual](https://textual.textualize.io/) application that drives the spreadsheet engine from the outside.

**A frontend, not a plugin.** There is no `trellis.plugins` entry point here and the core never imports this package. The app holds a real `Workbook` — the same object a REPL would drive — and repaints only in response to the engine's events. Anything the TUI can do, your script can do with the same objects. Scope and architecture: `design.md` Part 5.

## Status

Read-only spreadsheet (Part 5 #4). The app boots into a live grid — an A1-anchored window over the engine sheet, growing on demand as you arrow into empty space, repainting via the engine's events (writes made by a script or plugin against the same `Workbook` appear as they happen), with a formula bar mirroring the cursor. No editing yet.

| Lands in | What |
|----------|------|
| #3 | `render.py` display policy (value → text) — **done** |
| #4 | `SheetGrid`: the DataTable-backed grid, event-driven repaint — **done** |
| #5 | Editing: formula bar, Excel-ish keys, typed-input inference |
| #6 | CSV save (`Ctrl+S`), status line, dirty warning |
| #7 | This README for real |

## Install (development)

Not on PyPI yet. From the repo root, into a venv:

```
pip install -e . -e packages/trellis-tui
```

## Usage

```
trellis                # empty workbook
trellis data.csv       # open a CSV (engine's read_csv: conservative type inference)
trellis --version
python -m trellis_tui  # same thing
```

## Keys (v1 plan — see design.md Part 5 for the full table)

Arrows move · type to replace · `F2` revise · `Enter` commit + down · `Tab` commit + right · `Esc` cancel · `Delete` clear · `Ctrl+S` save · `Ctrl+Q` quit.

## Develop / test

Hermetic, no install needed (textual + pytest-asyncio required):

```
cd packages/trellis-tui
PYTHONPATH=../../src:src python -m pytest
```
