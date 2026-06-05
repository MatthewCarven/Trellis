# Trellis — project notes for Claude

## What this is
A minimalist, modular spreadsheet framework in Python. The package and product name is **Trellis**. The folder was originally named "Cross Tabulator Pro" as an in-joke and is being renamed to **Trellis** (the rename is cosmetic — git tracks contents, not the folder name, and nothing in the code hardcodes the folder path).

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

## Repository layout (monorepo)
- This repo is a **monorepo**. The core engine lives at `src/trellis/`. Companion distributions live under `packages/<name>/`, each a real installable package with its own `pyproject.toml` and `dependencies = ["trellis"]`.
- **`packages/trellis-mathpack/`** — the reference *plugin*: registers extra formula functions via the `trellis.plugins` entry point, auto-loaded *into* the engine at `import trellis`. (Built Part 4; cleared the publication gate.)
- **`packages/trellis-tui/`** (planned, next milestone) — the *frontend*, not a plugin. A `textual`-based terminal UI that imports `trellis` and drives it from the outside; core never knows it exists ("library first, app second"). Its `textual` dependency lives in the TUI package's pyproject, NOT in core — core stays dependency-free. (The `tui = ["textual>=0.50"]` extra in core's pyproject is a convenience hook; the TUI code itself does not go inside `src/trellis/`.)
- **Decision (2026-06-05):** keep UIs as in-repo companion packages rather than forking a separate repo, at least until core stabilizes (~1.0). Splitting a `packages/` subdir into its own repo later is cheap and preserves history; doing it now adds cross-repo publish/dependency friction for no benefit. See WORKLOG / the `trellis-tui-in-repo-frontend` memory.

## Working notes
- Use `WORKLOG.md` to record what each session did and any decisions made.
- The task list (tracked via TaskCreate/TaskUpdate) holds the roadmap. Keep it current.
- When adding a new extension hook, also note it in the README's "Extending" section so it's discoverable.

## What NOT to add without asking
- Required dependencies on the core package (`dependencies = []` in pyproject is intentional — keep it that way).
- GUI-only features in the core engine.
- Features that aren't expressible as a plugin (this is the design test).
