# trellis-undo

Undo/redo for [Trellis](../../README.md) sheets — and the **second reference plugin**, demonstrating the extension style the first one doesn't.

[trellis-mathpack](../trellis-mathpack) is *global registration*: an entry point runs at `import trellis` and registers formula functions. This package is *stateful attachment*: live `UndoLog` objects subscribe to a sheet's locked change events and stash themselves in `sheet.meta` — **no entry point, no core changes**. Between them: entry points register globals; events + meta attach state.

## Use

```python
from trellis import Workbook
from trellis_undo import attach

wb = Workbook()
sh = wb.add_sheet("S")
log = attach(sh)            # also lands at sh.meta["undo"]

sh["A1"] = 10
sh["A1"] = 20
log.undo()                  # A1 == 10
log.undo()                  # A1 is empty again (absence restores as absence)
log.redo()                  # A1 == 10
```

`attach(sheet)` is idempotent; `detach(sheet)` unsubscribes and clears; `attach_workbook(wb)` covers existing sheets and — via the workbook's `sheet:add` event — future ones (independent per-sheet histories). Or construct `UndoLog(sheet, capacity=...)` directly and manage it yourself.

## The contract

- **One recorded event = one step.** A `cell:change` is a 1-cell step; a `sheet:batch` (a paste, a multi-cell delete, a CSV load) is one step of N cells. `cell:recalc` is never recorded — derived values re-derive.
- **Restore by object.** Steps hold the payload's displaced/stored `Cell` objects; restoring `sheet.set(addr, cell)`s them back as-is. The recalc engine re-evaluates restored formulas *against the current sheet* (snapshot-stale values self-heal, dependents cascade), and plugin state in `meta` rides along. Cells that were empty restore as `sheet.delete`.
- **History is honest.** The log never records its own restores; any new recorded write clears the redo stack; history is capped (default 1000 steps, oldest drop silently) — `capacity=None` for unbounded, or retune `UndoLog.CAPACITY` by subclassing.
- Out-of-band `meta` mutations are not engine writes, so they are not history events.

## In the TUI

[trellis-tui](../trellis-tui) depends on this package: `Ctrl+Z` / `Ctrl+Y` out of the box, one step per gesture, with the live log at `app.undo_log`.

## Develop / test

Hermetic, engine-only (no textual):

```
cd packages/trellis-undo
PYTHONPATH=../../src:src python -m pytest
```

15 tests. Design and decisions: `design.md` Part 7.
