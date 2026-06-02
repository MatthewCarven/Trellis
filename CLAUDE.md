# Trellis — project notes for Claude

## What this is
A minimalist, modular spreadsheet framework in Python. The folder is named "Cross Tabulator Pro" as an in-joke; the actual package and product name is **Trellis**.

## Design philosophy (load-bearing)
- **Open extensibility / chaotic good.** Public-by-default APIs, hook-rich, trust other developers. Don't over-encapsulate "for safety" unless there's a concrete reason. Sharp tools over dull ones.
- **Minimalist core, plugin everything else.** Charts, pivots — explicitly out of scope as built-ins. Conditional formatting is on the fence as a built-in but *must* be expressible as a plugin either way.
- **The engine is a library first, an app second.** Anything you can do in the TUI you can do from a REPL with the same objects.

## Conventions
- Source under `src/trellis/`. Tests under `tests/`.
- Public surface re-exported from `trellis/__init__.py`. If it's not re-exported, it's internal.
- Cell, Sheet, Workbook all carry a `meta = {}` dict — plugins put their state there. Core never writes to `meta`. Plugins should namespace their keys under a single plugin-named key (e.g. `cell.meta["styles"][...]`), by convention not enforcement — see `docs/plugin-example.md`.
- Indexing uses A1 notation as the public-facing string form. Internally, everything is zero-indexed `(row, col)` tuples. Convert at the boundary using `trellis.core.address`.
- Python 3.11+ baseline.

## Working notes
- Use `WORKLOG.md` to record what each session did and any decisions made.
- The task list (tracked via TaskCreate/TaskUpdate) holds the roadmap. Keep it current.
- When adding a new extension hook, also note it in the README's "Extending" section so it's discoverable.

## What NOT to add without asking
- Required dependencies on the core package (`dependencies = []` in pyproject is intentional — keep it that way).
- GUI-only features in the core engine.
- Features that aren't expressible as a plugin (this is the design test).
