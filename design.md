# Trellis design notes

This document holds the design rationale for non-obvious subsystems — the *why* behind the *what* — so a future session (or a new contributor) can pick up the codebase and understand why it's shaped the way it is.

Two parts so far:

- **Part 1: Event system** — shipped in subtasks #12–#15 of task #3.
- **Part 2: Formula engine** — designed, not yet implemented (task #4 + subtasks).

---

# Part 1: Event system (Task #3)

Status: **SHIPPED 2026-05-27** in subtasks #12 (Emitter mixin), #13 (Sheet emitter), #14 (Workbook emitter), #15 (re-exports + README). Original design drafted 2026-05-26 evening.

## Purpose

A small, synchronous publish/subscribe system that is the spinal cord of Trellis's extensibility. Once it exists, formula recalc, conditional formatting, UI redraws, and third-party plugins all attach through the same mechanism instead of patching core code.

## Design goals

1. **Cheap to embed.** Mixable into Cell-scale objects without paying memory for objects that never have a listener.
2. **Predictable.** Synchronous, in-process, registration-ordered. No async, no thread pools, no priorities.
3. **Honest about failure.** Exceptions in handlers propagate by default — buggy plugins are loud, not silent. Users can wrap their own handlers if they want isolation.
4. **No coupling between core and listeners.** Core objects do not know who is listening; listeners do not know how core objects work internally.

## Module: `trellis.core.events`

Two public types.

### `Emitter` (mixin)

Inheriting from `Emitter` adds:

    obj.on(event, handler)         -> Subscription
    obj.off(event, handler)        -> None
    obj.emit(event, **payload)     -> None
    obj.listener_count(event=None) -> int

Events are colon-namespaced strings: `"cell:change"`, `"sheet:add"`, `"sheet:rename"`, etc.

Handlers are called synchronously, in registration order. Wildcard subscription via `event="*"` receives the event name as the first positional argument followed by the keyword payload.

Storage is lazy: an `Emitter` with no listeners holds no listener dict. The mixin does not require `super().__init__()` to be called — subclasses can drop it in without touching their `__init__`.

### `Subscription` (handle)

Returned by `Emitter.on()`. Callable — calling it (or `.unsubscribe()`) removes the handler. Idempotent. Useful for "subscribe and forget" patterns where the lifetime of the subscription matches a context manager or scope.

## Why `Cell` is not an `Emitter` (by default)

I considered mixing `Emitter` into `Cell` so users could do `cell.on("change", ...)`. Decided against it because:

- The `Sheet` replaces `Cell` instances on `sheet["A1"] = value` (it doesn't mutate in place). Any per-cell subscription would be orphaned by the next write.
- The `Sheet` emits at the right level. A subscriber who cares about A1 specifically can subscribe to `sheet.on("cell:change", ...)` and filter on `addr == "A1"`. That's idiomatic and survives identity changes.
- The mixin is still available. Anyone who wants per-cell pub/sub can subclass `Cell` with `Emitter`. Open extensibility intact.

If a future change makes `Sheet` preserve cell identity on overwrites (in-place mutation), revisit this decision — it would make per-cell events safe.

## Events emitted by core types

### `Sheet`

- **`"cell:change"`** — fired on `set()` and on `delete()` of an existing cell. Payload: `addr` (A1 string), `old` (the previous `Cell`; empty `Cell` if it did not exist), `new` (the new `Cell`; empty `Cell` if deleted).

Notable: deleting an absent address is silent (no event). Setting a cell to its current value still fires (no value-comparison short-circuit in core — that's a job for plugins).

### `Workbook`

- **`"sheet:add"`** — payload: `sheet`. Fires from both `add_sheet(name)` and `add(sheet_instance)`.
- **`"sheet:remove"`** — payload: `name`, `sheet`.
- **`"sheet:rename"`** — payload: `old`, `new`, `sheet`.

The workbook's events describe its own collection only. To watch every cell in every sheet, subscribe to `"sheet:add"` and attach a `"cell:change"` listener to each new sheet.

## Rejected alternatives

- **Async handlers (`asyncio`-aware).** Adds ordering complexity, makes the engine harder to reason about, and is unnecessary for an in-process spreadsheet engine. Users who want async wrap their sync handler.
- **Exception isolation by default.** Swallowing exceptions in handlers hides bugs. We propagate; the caller of `emit()` sees the traceback.
- **Priority queues for handler ordering.** Premature. Registration order is predictable and 99% sufficient. Add priorities only if a real need shows up.
- **Global event bus replacing per-instance listener lists.** Globals are footguns; per-instance keeps lifetime clean and matches user mental model.
- **`Cell` as `Emitter` by default.** Footgun (see above). Mixin is opt-in.

## Resolved during implementation

1. **Re-entrant emit safety.** Allowed and tested. Infinite recursion blows the Python stack.
2. **`off` during emit.** Snapshot-before-iterate solves it; tested with `test_handler_unsubscribes_another_mid_emit_does_not_break`.
3. **Empty bucket cleanup.** Confirmed yes — `listener_count()` is honest about it.

---

# Part 2: Formula engine (Task #4)

Status: **designed, not yet implemented**. Drafted 2026-05-27 evening, post-Range.

## Purpose

Make `sheet["A1"] = "=B1*2"` actually compute. This is the milestone that turns Trellis from "typed dict with hooks" into something that *feels* like a spreadsheet. A user assigns a formula string to a cell; the engine parses it, evaluates it, stores the result, and recomputes everything that depends on it whenever inputs change.

## Design goals

1. **Zero new required dependencies.** Hand-rolled lexer + parser. Pure Python. Keep `dependencies = []` in `pyproject.toml`.
2. **The function registry is the plugin surface in microcosm.** Built-in functions (`SUM`, `IF`, etc.) register through the same dict that third-party plugins will use later (task #5). Eat the dogfood from day one.
3. **Recalc is event-driven.** The recalc engine subscribes to the existing `"cell:change"` event. No new coupling between Sheet and formula code beyond a registration call when the engine attaches to a workbook.
4. **Errors are values.** Spreadsheet errors (`#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`, `#CIRC!`) are first-class values that propagate through arithmetic and functions — they don't raise Python exceptions out of the engine. A formula that fails still has a *result*; that result is an Error.
5. **Eager evaluation.** When you set a formula, it parses and evaluates immediately. `cell.value` is always current. Lazy evaluation is more flexible but harder to reason about; deferring.

## Subpackage layout: `trellis.formula`

A new subpackage rather than dumping everything in `core/`, because the formula engine is materially larger than any single core module and has its own internal structure.

    src/trellis/formula/
        __init__.py        # re-exports the public surface
        errors.py          # FormulaError sentinel/class, error constants
        lexer.py           # source string -> token stream
        ast.py             # AST node dataclasses (frozen)
        parser.py          # token stream -> AST
        evaluator.py       # AST + context -> value (or Error)
        functions.py       # built-in function registry + the built-ins themselves
        recalc.py          # dependency graph + recalc engine + workbook attachment

Public re-exports from `trellis.formula` and ultimately `trellis`:

- `parse_formula(src) -> AST`
- `evaluate(ast, context) -> value`
- `FormulaError`, error constants (`DIV0`, `VALUE`, `REF`, `NAME`, `CIRC`, `NA`, `NULL`)
- `register_function(name)(callable)` — decorator
- `RecalcEngine` — for advanced users who want to attach manually
- `Formula` — convenience wrapper (parsed AST + source string + dependencies)

## Supported syntax (v1)

- **Literals:** integers (`42`), decimals (`3.14`, `.5`), scientific (`1e3`), strings (`"hello"`, with `""` as escape for embedded quotes), booleans (`TRUE`, `FALSE`).
- **References:** absolute cell refs (`A1`, `ZZ999`), absolute range refs (`A1:B5`).
- **Operators** (highest to lowest precedence):
  1. `:` (range) — only between two cell refs, produces a range
  2. unary `-` and `+`
  3. `%` (percent — postfix, divides by 100)
  4. `^` (exponentiation, right-associative)
  5. `*` `/`
  6. `+` `-`
  7. `&` (string concatenation — optional for v1; include if cheap)
  8. `=` `<>` `<` `>` `<=` `>=`
- **Parens** for grouping.
- **Function calls:** `IDENT(arg1, arg2, ...)` — case-insensitive name, comma-separated args.

**Out for v1:**

- Cross-sheet refs (`Sheet2!A1`)
- Named ranges
- Array formulas / spilled ranges
- Volatile functions (`NOW`, `RAND`, `TODAY`)
- Relative vs absolute distinction (`$A$1` parses but is treated identically to `A1` — relative addressing is meaningless without copy-paste semantics, which we don't have yet)
- `INDIRECT`, `OFFSET`, anything that computes references at evaluate time
- Iterative calculation (intentional cycles)

## Built-in functions (v1 starter set)

Math: `SUM`, `AVERAGE`, `COUNT`, `COUNTA`, `MIN`, `MAX`, `ABS`, `ROUND`, `INT`, `MOD`, `POWER`, `SQRT`.

Logical: `IF`, `AND`, `OR`, `NOT`, `TRUE`, `FALSE`, `IFERROR`.

Text: `CONCAT`, `LEN`, `UPPER`, `LOWER`, `TRIM` (optional for v1).

Lookup / info: `ISNUMBER`, `ISBLANK`, `ISERROR` (small but high-value).

That's ~20 functions — enough to demonstrate the registry mechanism and cover ~80% of basic spreadsheets. Everything else is a plugin.

## AST shape

Frozen dataclasses, all in `ast.py`:

    @dataclass(frozen=True)
    class Number:       value: float | int
    class String:       value: str
    class Bool:         value: bool
    class CellRef:      row: int; col: int           # 0-indexed; no sheet for v1
    class RangeRef:     start: CellRef; end: CellRef
    class UnaryOp:      op: str; operand: Node
    class BinaryOp:     op: str; left: Node; right: Node
    class FunctionCall: name: str; args: tuple[Node, ...]

`Node` is the union of all node types (PEP 695 type alias or simple Union).

## Error model

`FormulaError` is a class, not an Exception. Instances are spreadsheet error values:

    DIV0  = FormulaError("#DIV/0!", "Division by zero")
    VALUE = FormulaError("#VALUE!", "Wrong type for this operation")
    REF   = FormulaError("#REF!",   "Reference to a missing or deleted cell")
    NAME  = FormulaError("#NAME?",  "Unknown function or identifier")
    CIRC  = FormulaError("#CIRC!",  "Circular reference detected")
    NA    = FormulaError("#N/A",    "Value not available")
    NULL  = FormulaError("#NULL!",  "Empty intersection")

Errors propagate: any arithmetic or function call with an Error operand returns that Error (except `IFERROR`, which catches). The cell's `value` becomes the Error instance; UI/exporters check `isinstance(cell.value, FormulaError)` to render the `#DIV/0!` text.

Parse errors are stored as `NAME` (matches Excel for unknown idents) or `VALUE` (for malformed syntax) — the formula string is still in `cell.formula`, so the user can fix it.

## Recalc engine

A `RecalcEngine` instance owns:

- **A dependency graph:** `dependents: dict[(sheet_name, row, col), set[(sheet_name, row, col)]]` — keys are cells, values are the set of cells whose formulas reference them. Plus the reverse: `dependencies: dict[cell, set[cell]]`.
- **A registered workbook** (one engine per workbook).

When a workbook is attached:

1. Engine subscribes to each existing sheet's `"cell:change"`.
2. Engine subscribes to `workbook.on("sheet:add", ...)` to attach to new sheets, and `"sheet:remove"` to clean up.

On `"cell:change"` for some cell `C`:

1. If `C.new.formula` is set, parse it. If the parse succeeds, extract the dependencies (set of CellRef/RangeRef positions). Update the dep graph: remove `C`'s old dependencies, add new ones. Evaluate the AST, write the result to `C.value` via a *non-emitting* path (see below).
2. Look up `dependents[C]` — every formula cell that references `C` (directly). Topologically order them (forward BFS); recompute each; write each result via the non-emitting path.
3. Cycle detection: if topological order can't be built, mark all involved cells with `CIRC`.

**The non-emitting write problem.** If recalc writes back via the normal `sheet.set()`, it fires another `cell:change`, which re-triggers recalc, infinite loop. Solutions considered:

- **(A) Add `sheet.set(..., quiet=True)`** that skips the emit. Simple, but pollutes the Sheet API with an internal concern.
- **(B) Add a separate `"cell:recalc"` event** the engine emits when it writes results. Recalc ignores `cell:recalc`, but UI handlers can listen to both. Cleaner.
- **(C) Engine writes directly to `sheet._cells`** (private store), bypassing emit entirely, then fires `"cell:recalc"` itself. Most direct, but reaches into a private attribute.

**Tentative pick: (C) with a thin helper.** Add a private `_set_value(addr, value)` method on Sheet that only updates `cell.value` (preserving formula), and emits `"cell:recalc"` instead of `"cell:change"`. Recalc engine uses this; subscribers wanting "any change at all" listen to both events; subscribers wanting "user-initiated change" listen to just `cell:change`. Surface in the design doc as the integration choice.

## Function registry

A module-level dict in `functions.py`:

    _REGISTRY: dict[str, Callable] = {}

    def register_function(name: str):
        def decorator(fn):
            _REGISTRY[name.upper()] = fn
            return fn
        return decorator

    @register_function("SUM")
    def _sum(ctx, *args): ...

Functions take `(ctx, *args)` where `ctx` carries the workbook + evaluator (so functions can resolve ranges to value sequences). Args are pre-evaluated by the evaluator — no lazy/short-circuit by default. `IF` and `IFERROR` will need a lazy variant (lazy arg flag on register or separate decorator); spec it in `#4b`.

Third-party plugins register the same way: `from trellis.formula import register_function` and decorate. Task #5 wires `entry_points` discovery so `pip install trellis-mathpack` auto-imports the registration module.

## Rejected alternatives

- **Parser dependency** (lark, parsimonious, pyparsing). Adds a runtime dep; the formula grammar is small enough that a hand-rolled Pratt parser is ~200 lines.
- **Lazy evaluation** (compute on read instead of on write). More flexible but unpredictable performance, and complicates the "did this cell's value change?" question that UI listeners care about. Defer.
- **Storing the AST on the Cell.** Adds a field, couples Cell to formula internals. The dep graph holds the ASTs, keyed by cell address.
- **Per-Sheet recalc engines.** Doesn't survive cross-sheet refs in v2. Make it workbook-level from the start.
- **Raising Python exceptions from evaluation.** Breaks the "errors are values" model. Internal helpers may raise, but the public `evaluate()` always returns a value (possibly a `FormulaError`).
- **String concat with `+`.** Excel's `&` is the canonical operator and avoids ambiguity with addition coercing strings to numbers.

## Open questions

1. **`%` as postfix or modulo?** Excel uses `%` as postfix percent (`50%` = 0.5). Python uses it as modulo. Going with Excel — postfix percent — because formulas are an Excel-shaped DSL. Modulo is `MOD(a, b)`.
2. **Short-circuit for `IF` / `IFERROR`.** Must not eagerly evaluate the branch that won't be taken. Plan: mark these functions with `lazy=True` at registration; the evaluator passes them un-evaluated AST nodes for those args plus an `evaluate()` callback.
3. **What about a stored Cell whose value is set directly (e.g. `sheet["A1"] = 5`) that some formula depends on?** Recalc still needs to fire — the engine listens to `cell:change` for the underlying cell, sees A1 has changed, walks dependents. Same path. ✓ already works in the design.
4. **What if a formula references a Range that grows when new cells are written into it?** E.g. `=SUM(A:A)` references all of column A. For v1, range refs are *static rectangles* — `A1:A10` references exactly those 10 positions. Column refs (`A:A`) are out for v1.
5. **Should the engine deep-copy parse results?** AST nodes are frozen dataclasses; safe to share. No copies needed.

## Implementation breakdown (subtasks of #4)

Each subtask should land green tests and not break previous ones. Suggested order:

1. **#4a — Errors, Lexer, Parser, AST.** Pure parsing, no evaluation. Tests on tokenization and AST shapes for every supported syntactic construct. ~400 LOC + tests.
2. **#4b — Evaluator + built-in function registry + starter functions.** Walk an AST given a `Context` (workbook + current cell + evaluator-for-lazy-args). Built-ins for SUM/AVG/COUNT/MIN/MAX/IF/AND/OR/NOT/IFERROR/ABS/ROUND/CONCAT/LEN at minimum. Tests for arithmetic, comparisons, function dispatch, error propagation, lazy IF/IFERROR. ~500 LOC + tests.
3. **#4c — Recalc engine + Sheet integration.** Dependency graph; `RecalcEngine.attach(workbook)`; subscription wiring; topological recalc on `cell:change`; cycle detection → `CIRC`; the `_set_value`/`cell:recalc` non-emitting write path. Workbook acquires a `recalc` engine on construction. Tests for chain recalc (A1 → B1 → C1 → ...), broadcast updates, dependency edits, cycle detection, recalc engine teardown. ~400 LOC + tests.
4. **#4d — Top-level re-exports, README, smoke test.** `from trellis import parse_formula, FormulaError, register_function`. README "Quick taste" example uses a live formula. Worked formula plugin example in docs/. ~50 LOC of glue.

## Integration test (the milestone)

When #4 is done, this should work end-to-end:

```python
from trellis import Workbook

wb = Workbook()
sh = wb.add_sheet("Demo")
sh["A1"] = 10
sh["A2"] = 20
sh["A3"] = 30
sh["B1"] = "=SUM(A1:A3)"           # 60
sh["B2"] = "=IF(B1 > 50, \"big\", \"small\")"   # "big"

assert sh["B1"].value == 60
assert sh["B2"].value == "big"

sh["A1"] = 100                      # triggers recalc
assert sh["B1"].value == 150
assert sh["B2"].value == "big"

sh["A1"] = "=B1"                    # cycle: A1 -> B1 -> A1
assert isinstance(sh["A1"].value, FormulaError)
assert sh["A1"].value.code == "#CIRC!"
```

If this passes, the formula engine is done and Trellis feels like a spreadsheet.

## References

- Conversation transcript, 2026-05-27 evening session.
- `WORKLOG.md` — Session 7 entry (when written) records that this doc was the design pass for task #4.
- Auto-memory: `design-philosophy-open-extensibility.md` — informs the "function registry is the plugin surface" decision.
- Auto-memory: `trellis-deadline-pressure.md` — informs subtask sizing (each one independently shippable, so the next break-friendly stopping point is always near).


---



# Part 3: Pre-render engine prep (Task #1 and follow-up tasks)

Status: **planning, written 2026-05-27 Session 18**. Prerequisite for the `trellis-tui` sister package, but no TUI code in this part.

## Purpose

Harden the engine's public surface in the few places that will be hard to change once trellis is published to GitHub and external plugins (including the eventual `trellis-tui` sister package) start consuming it. The TUI itself is out of scope here — this is the API audit that lets the TUI ship cleanly without the engine fighting it.

## Design goals

1. **Lock in event payload shape now.** The moment a real plugin author writes `def on_change(event): event["old_value"]`, that field is in the contract. Better to nail the shape before plugins exist than to change it after.
2. **Give bulk operations a first-class home.** `read_csv` already wants to bypass per-cell events on load; paste, fill, and undo-of-a-paste will want the same thing. One `Sheet.batch()` context manager beats four ad-hoc bypasses.
3. **Promote the one introspection method a renderer needs every frame.** `used_range` — the bounding rectangle of populated cells — already exists privately inside the CSV writer. Lift it to public so the renderer doesn't reach into internals.
4. **Add a naming convention for plugin metadata.** Convention only, not enforcement. Prevents two plugins fighting over `cell.meta["color"]`.
5. **Do NOT pre-build:** display formatting, an undo log, viewport caches, style metadata in core, a Row/Column header type, a focus / cursor concept. Those are renderer or plugin concerns and would violate `simplicity-over-clever-solvers`.

## Rationale for doing this now

Two things are about to change at once that both raise the cost of API changes:

1. **trellis goes public on GitHub.** Plugin authors can start writing against the public surface. Breaking changes go from "fix one test" to "break N strangers' code."
2. **The TUI is the next major chunk.** It will be the most demanding consumer of the engine's public API — it renders, edits, undoes, pastes, watches for changes — and as a *separate package* (per the sister-package decision) it can only see the public surface.

Both forces converge on: spend an afternoon now sharpening four edges of the API, get a much better TUI build later and a much better story for external plugin authors.

## Subtask 3.1: Event payload audit and lock-in

**Goal.** Every event the core emits carries enough information for an undo plugin to reverse it and a viewport renderer to decide whether to repaint, without re-querying the sheet.

**Audit step (Task #2).** Read `src/trellis/core/events.py` and every `emit(...)` call in the codebase. Document the current payload shape per event type. Identify the gap between today's shape and the target shape below.

**Target shape (proposed, refine after audit):**

```python
# cell:change — emitted when sheet.set() writes a cell
{
    "sheet": Sheet,            # the sheet the change happened on
    "address": (row, col),     # zero-indexed tuple (A1-string available via address.to_a1)
    "old_value": Any,          # the value before the write (None if cell was blank)
    "new_value": Any,          # the value after the write
    "old_formula": str | None, # formula source before, if any
    "new_formula": str | None, # formula source after, if any
}

# cell:recalc — emitted when the recalc engine updates a computed cell
{
    "sheet": Sheet,
    "address": (row, col),
    "old_value": Any,
    "new_value": Any,
    "trigger": (row, col) | None,  # which cell's change triggered this recalc cascade; None for explicit recompute
}
```

**Why both old and new.** Undo plugins need `old_*` to restore. Renderers may also use `old_value` to detect "did this actually change?" before repainting (e.g., a formula recomputed to the same value).

**Tests.** Add explicit lock-in tests in `tests/test_events.py` (or wherever events live) named to make their contract role obvious: `test_cell_change_payload_carries_old_and_new_value`, `test_cell_change_payload_includes_formula_source_when_set`, `test_cell_recalc_payload_includes_trigger_cell`. These are the contract going forward.

## Subtask 3.2: `Sheet.batch()` context manager

**Goal.** Bulk operations buffer per-cell events and run recalc once on exit.

**Spec step (Task #4).** Pin down four decisions before any code:

1. **API shape: context manager only.** `with sheet.batch() as b: ...`. No callable wrapper (`sheet.batch(lambda: ...)`) — one obvious way is enough.
2. **What it emits on exit.** Lean: one consolidated `sheet:batch` event carrying `{sheet, changes: [{address, old_value, new_value, ...}, ...]}`. Per-cell `cell:change` events are *suppressed* during the batch. `cell:recalc` events still fire once during the deferred recalc at the end. Rationale: a plugin that cares about each cell can iterate `event["changes"]`; a plugin that cares about "something changed, repaint" gets one notification.
3. **Exception behaviour: propagate, no rollback.** If an exception is raised inside the with-block, the cells already set stay set, the buffered batch event is *not* emitted (because the batch didn't complete), and the exception propagates. No rollback — keeps the implementation simple, matches "sharp tools" philosophy. User can build transactional behaviour as a plugin if needed.
4. **Nested batches: flatten.** An inner `sheet.batch()` inside an outer one joins the outer batch. Only the outermost `__exit__` emits and recomputes. Rationale: a function that uses `batch()` internally can be safely called from inside another batch.

**DECIDED 2026-06-03 (recalc integration).** On exit the sheet emits one `sheet:batch`; the recalc engine subscribes to it and **replays each buffered change through its normal per-cell path** (Matthew's call, over a dedupe pass). Consequences: a dependent fed by several cells changed in the same batch may recompute more than once, and each `cell:recalc` keeps its own per-cell `trigger` (the replayed cell). Simpler engine, no new combined-propagation solver — consistent with `simplicity-over-clever-solvers`. The dedupe-once optimisation is available later if a real perf need appears. The `read_csv` bonus refactor landed: it now loads inside a `sheet.batch()` (writing `Cell` instances via `sheet.set` to keep the literal-`=` policy), so a load fires one `sheet:batch` and any formulas referencing the loaded region recompute once.

**Implementation sketch.**

```python
class Sheet:
    def __init__(self, ...):
        ...
        self._batch_depth = 0
        self._batch_changes: list[dict] = []

    def batch(self):
        return _BatchContext(self)

class _BatchContext:
    def __init__(self, sheet): self.sheet = sheet
    def __enter__(self):
        self.sheet._batch_depth += 1
        return self
    def __exit__(self, exc_type, exc, tb):
        self.sheet._batch_depth -= 1
        if self.sheet._batch_depth == 0:
            if exc_type is None:
                changes = self.sheet._batch_changes
                self.sheet._batch_changes = []
                self.sheet._emit("sheet:batch", {"sheet": self.sheet, "changes": changes})
                self.sheet._recalc_pending()  # or whatever the existing recalc trigger is
            else:
                self.sheet._batch_changes = []  # discard
        return False  # propagate exception
```

`Sheet.set` checks `self._batch_depth > 0` and, if so, appends to `_batch_changes` and *skips* the `cell:change` emit + the immediate recalc trigger.

**Bonus refactor.** Change `read_csv` (currently writes directly to `sheet._cells`) to use `sheet.batch()` instead. Validates the API on a real consumer and removes the special-case bypass — and it's the cleanest possible existence proof that batch is the right shape.

**Tests.** Per-cell events suppressed in batch; one `sheet:batch` event fires on exit; recalc runs once not N times; exception inside the block propagates and no batch event fires; nested batches flatten; bonus — full `tests/test_io_csv.py` still green after `read_csv` refactor.

## Subtask 3.3: Promote `used_range` to public Sheet API

**Goal.** A renderer asking "what's the extent of populated cells?" doesn't have to reach into internals.

**API.** `Sheet.used_range() -> tuple[tuple[int, int], tuple[int, int]] | None`. Returns `((min_row, min_col), (max_row, max_col))` of cells with non-empty values. Returns `None` for an empty sheet — matches the CSV writer's existing "no content is a legit state" decision. Tuple, not `Range` — `Range` may carry more semantics than this introspection needs, and a renderer wants the raw extent.

**Implementation.** Lift the bounding-rectangle helper currently inside `trellis/io/csv.py` to `Sheet.used_range`. Refactor `write_csv` to call it.

**Tests.** Empty sheet returns `None`; single cell returns `((r, c), (r, c))`; sparse layout returns the true min/max; cells with empty string `""` count as populated (matches what `write_csv` does today — confirm in audit); a cell that's been explicitly cleared (set to `None`) does NOT count.

## Subtask 3.4: Document the meta-namespacing convention

**Goal.** Prevent two plugins fighting over `cell.meta["color"]`.

**Convention.** Plugins writing to `cell.meta`, `sheet.meta`, or `workbook.meta` should namespace their keys under a dict keyed by their plugin name:

```python
# Good:
cell.meta["styles"] = {"bold": True, "color": "red"}
cell.meta["validation"] = {"rule": "int_range", "min": 0, "max": 100}

# Bad:
cell.meta["bold"] = True
cell.meta["color"] = "red"
cell.meta["validation_rule"] = "int_range"
```

**Where.** Add a short section to `docs/plugin-example.md` (with the good/bad pair above) and a one-line cross-ref in `CLAUDE.md` under Conventions. Pure docs, no code.

**Why convention, not enforcement.** Per `design-philosophy-open-extensibility`: hooks over locks. A plugin that violates the convention works fine until it collides with another plugin; the collision is the punishment, and that's enough. Forcing namespacing in code (e.g., a `MetaProxy` that requires `cell.meta.namespace("styles")["bold"]`) is the kind of "for safety" encapsulation CLAUDE.md warns against.

## Rejected alternatives

- **Display-formatter on Cell.** "How should `3.14159` look in a 12-char column?" is the renderer's job, not the engine's. The engine returns Python values; renderers format them. Lives in `trellis-tui` (or any other renderer).
- **Undo log in core.** Belongs in a plugin built on the event stream — which is exactly what 3.1 makes possible. Building it in core would couple the engine to a specific undo model (linear stack? tree? per-sheet? per-workbook?) and pre-build something with no proven shape requirement.
- **Viewport / window abstraction.** "Give me cells in rows 10–30, cols A–M" is a renderer concern. No proven need for engine support yet; iterating `_cells` and filtering is fine for any sheet a human could see at once. Revisit if/when a renderer demonstrates a real bottleneck.
- **Row-indexed cache.** Pre-building a `dict[row -> list[Cell]]` to make "give me row N" fast. Per `simplicity-over-clever-solvers` — no concrete need yet, and the right shape depends on access patterns we haven't seen.
- **Style metadata as a first-class field on Cell** (`cell.style`, `cell.format`, etc.). Lives in `cell.meta["styles"]` per 3.4. A styles plugin owns the namespace.
- **Forcing plugins to namespace by entry-point name** (mechanical enforcement of 3.4). Too rigid. Some plugins are local scripts with no entry point; the convention is enough.
- **`Sheet.batch()` with rollback semantics.** Implementing rollback means snapshotting old values, exception-safe restoration, and a clear story for what happens if recalc itself raises. None of that is free. Default to propagate-no-rollback; revisit if a real use case demands transactional behaviour.

## Open questions

- **Should `cell:change` include the `Cell` object itself, or just the address + values?** **DECIDED 2026-06-03 (against the original lean): include the live `Cell`** as `old`/`new` *alongside* the scalar `old_value`/`new_value`/`old_formula`/`new_formula` fields. Matthew's call — sharp-tools/give-everything over guard-rails; also keeps existing `old`/`new` subscribers (incl. the recalc engine) working. The mutation foot-gun is accepted as the plugin author's responsibility.
- **What's the canonical address representation in event payloads — tuple `(row, col)` or A1 string `"A1"`?** **DECIDED 2026-06-03: tuple `(row, col)`** under the key `address` (replaces the old `addr` A1-string key). `to_a1(*address)` at the human-facing edge. Matched the original lean.
- **Does `sheet.batch()` need a `discard()` method** to abort the batch from inside the block without raising? Lean no — if discard-from-inside becomes a real need, add it then.
- **Should `Sheet.used_range` count cells with explicit `None` values, or only "truly empty" ones?** **DECIDED 2026-06-03 (audit).** Definition is `not cell.is_empty()`: a cell counts if it has a value (incl. the empty string `""`), a formula (even one whose current value is `None`), or non-empty `meta`. A cell set to `None` via `sheet.set` stores an *empty* cell and does NOT count; absent/deleted cells don't count. This counts empty-string cells and formula-with-None-value cells (renderer correctness) while excluding truly-empty ones, satisfying every test in the 3.3 plan. `write_csv` was refactored onto it; the only behaviour change is that a trailing explicit-empty cell no longer pads the export (untested edge case, arguably a fix). The engine *does* distinguish "never set" (absent key) from "set to None" (present empty cell) — but `used_range` treats both as not-counted because `is_empty()` is value/formula/meta-based, not key-presence-based.
- **Recalc depth/iteration cap (`MAX_RECALC_DEPTH`).** **DEFERRED 2026-06-03 (Matthew).** Raised when adopting batch Replay (which recomputes a dependent up to N times). Not needed for correctness today: cycles are caught at registration by `_would_cycle` (→ `CIRC`), re-entry is guarded by `RecalcEngine._processing`, and `_propagate` has a topo-sort `None` fallback that marks runaway subgraphs `CIRC`. A `MAX_RECALC_DEPTH` constant (in `formula/errors.py` or a new `constants` module) plus a tripwire that bails a runaway cascade to `CIRC` is cheap belt-and-suspenders — wire it in when iterative/circular calculation or cross-sheet refs land and cycles get genuinely harder to reason about. Until then it would be redundant machinery.

## Implementation breakdown (subtasks of this part)

| Task ID | What | Plan/Implement |
|---------|------|----------------|
| #1 | Write this section (the planning task) | (this doc) |
| #2 | Audit current event payloads | DONE 2026-06-03 |
| #3 | Implement event payload changes + tests | DONE 2026-06-03 |
| #4 | Spec `Sheet.batch()` API surface | DONE 2026-06-03 |
| #5 | Implement `Sheet.batch()` + tests + read_csv refactor | DONE 2026-06-03 |
| #6 | Promote `used_range` to public + write_csv refactor | DONE 2026-06-03 |
| #7 | Document meta-namespacing convention | DONE 2026-06-03 |
| #8 | Verification + WORKLOG entry | Verify |

Per the established pattern: each implementation task lands as a self-contained chunk with tests bundled. The audit step (#2) and the spec step (#4) are explicit because they're the planning artifacts that have made every implementation task since #16 land first-run green.

## References

- Conversation transcript, 2026-05-27 Session 18.
- `WORKLOG.md` — Session 17 entry establishes the "engine is feature-complete as a library" milestone that motivates this prep.
- Auto-memory: `simplicity-over-clever-solvers` — informs the "what NOT to build" list (display formatter, undo log, viewport cache).
- Auto-memory: `design-philosophy-open-extensibility` — informs the convention-not-enforcement choice in 3.4.
- Auto-memory: `trellis-deadline-pressure` — informs sizing: each implementation subtask is independently shippable so the pre-break stopping point is always near.


# Part 4: `trellis-mathpack` — the reference plugin package (publication gate)

Status: **scope, written 2026-06-03 Session 23.** No package code yet — this is the plan. Decisions confirmed with Matthew: a *useful focused* function pack (~20 fns), living as a subdir of this repo, shipped as a *real companion package* (proper README + tests, installable).

## Purpose

Build a separate, installable Python distribution that adds ~20 math functions to Trellis purely through the public extension surface — `register_function`, the `(ctx, *args)` calling convention, `FormulaError` as a constructible value, and `entry_points` auto-discovery. Two jobs:

1. **Clear the publication gate.** Per auto-memory `trellis-publication-gated-on-client`: no GitHub push until a real consumer has exercised the API. `trellis-mathpack` is that consumer. When it installs and auto-loads cleanly and its formulas evaluate, the gate is cleared.
2. **Be the reference plugin.** A maintained example others copy when writing their own packages. `docs/plugin-example.md` already points at `trellis_mathpack` by name — this makes that real.

## Design goals

1. **Touch only the public surface.** Everything `mathpack` does must go through `from trellis import ...`. If it needs a core internal, that's a bug in the *core's* public surface to fix in core — exactly the kind of gap this exercise exists to find.
2. **Mirror the built-ins' conventions** so it reads as idiomatic Trellis: reject `bool` as a number, require `int`/`float` scalars (else `#VALUE!`), flatten list (range) args for aggregate functions, propagate any `FormulaError` found inside a range.
3. **Demonstrate minting custom error values.** Core has no `#NUM!`. `mathpack` defines its own `NUM = FormulaError("#NUM!", ...)` for domain errors (`SQRT(-1)`, `LN(0)`). This is the single best proof that "errors are values you construct," not a closed core enum.
4. **Real package hygiene.** Own `pyproject.toml`, `src/` layout, README, full unit tests, and a discovery integration test.

## Package layout

```
packages/trellis-mathpack/
  pyproject.toml
  README.md
  src/
    trellis_mathpack/
      __init__.py          # setup() + the NUM constant + shared helpers
      _functions.py        # the function implementations (optional split)
  tests/
    test_mathpack.py       # unit tests per function
    test_discovery.py      # entry_points / setup() integration
```

`pyproject.toml` essentials:

```toml
[project]
name = "trellis-mathpack"
version = "0.1.0"
dependencies = ["trellis"]            # depends on the core (core itself stays dep-free)

[project.entry-points."trellis.plugins"]
mathpack = "trellis_mathpack:setup"
```

The left key `mathpack` is the identifier surfaced by `load_plugins()` and in warnings; the right side is the `module:callable` setup reference. Matches the worked example already in `docs/plugin-example.md`.

## Function set (~20)

All names are NEW — none collide with the 24 built-ins (`SUM AVERAGE MIN MAX COUNT ROUND INT ABS IF IFERROR AND OR NOT CONCAT LEFT RIGHT MID LEN ISBLANK ISERROR ISNUMBER ISTEXT TRUE FALSE`).

| Group | Functions | Notes |
|-------|-----------|-------|
| Trig (6) | `SIN COS TAN ASIN ACOS ATAN` | radians; `ASIN`/`ACOS` domain `[-1,1]` → `#NUM!` outside |
| Hyperbolic (3) | `SINH COSH TANH` | the design's original worked example |
| Powers / logs (5) | `SQRT POWER EXP LN LOG` | `SQRT(<0)`→`#NUM!`; `LN(<=0)`/`LOG(<=0)`→`#NUM!`; `LOG(x, [base=10])` optional 2nd arg |
| Misc math (3) | `MOD SIGN PI` | `MOD(x,0)`→`#DIV/0!` (Excel-faithful); `PI()` zero-arg (confirmed supported) |
| Range stats (3) | `STDEV VAR MEDIAN` | sample stats (n−1); flatten range args; `STDEV`/`VAR` need ≥2 values else `#DIV/0!` |

**Possible later extensions (NOT v1):** `DEGREES RADIANS ATAN2 LOG10 CEILING FLOOR STDEVP VARP MODE PERCENTILE`. Listed so the package has an obvious growth path; out of scope for the gate.

## Design decisions

- **Scalar type guard (shared helper).** A `_num(x)` helper guards each scalar arg. **Implemented (Session 25):** it mirrors the built-ins' `_coerce_scalar_number` exactly — `None`→0 (empty-cell-as-zero), `int`/`float` pass through, list/str/other→`#VALUE!`, `FormulaError` passes through — with **one deliberate deviation: `bool`→`#VALUE!`** (core arithmetic coerces bool→int; mathpack treats bools as non-numbers, matching `ISNUMBER` and range-aggregation). The earlier wording here ("returns the value if a real int/float, else #VALUE!") would have rejected `None` too; mirroring core's `None`→0 keeps `COS(<empty cell>)`=1 Excel-faithful. If strict `None`→`#VALUE!` is preferred, it's a one-line change. The evaluator already short-circuits a top-level `FormulaError` arg before the function runs, so scalar functions don't re-check for errors — but aggregate functions must (see below).
- **Domain errors → mathpack-local `#NUM!`.** `NUM = FormulaError("#NUM!", "...")` defined once in `__init__.py`. Returned for `SQRT(<0)`, `ASIN/ACOS` out of `[-1,1]`, `LN/LOG(<=0)`, and any `math` domain error caught from `POWER`. `MOD(x, 0)` returns core `DIV0` (Excel uses `#DIV/0!` there, not `#NUM!`).
- **Aggregate (range) functions flatten lists.** `STDEV/VAR/MEDIAN` accept a mix of scalars and range args; a `_collect_numerics(args)` helper (mirroring the built-in of the same name) flattens lists, skips nothing silently — a `FormulaError` encountered inside a range is returned immediately (error propagation), `bool` is excluded, non-numerics → `#VALUE!`. Use Python's `statistics` module (`stdev`, `variance`, `median`) and convert its `StatisticsError` (too few points) to `#DIV/0!`.
- **`LOG(x, base=10)`.** One or two args. Two-arg form validates base > 0 and ≠ 1 → else `#NUM!`. Keeps Excel parity.
- **No built-in overrides.** `register_function` would silently replace; the pack deliberately never does. README says so.
- **`statistics` + `math` only.** Stdlib. The package's one real dependency is `trellis` itself.

## Testing strategy (two tiers)

- **Tier 1 — hermetic (runs in the normal test style).** Import `trellis_mathpack`, call `setup()` directly (or feed a `FakeEntryPoint` to `trellis.load_plugins([...])`, reusing the pattern from `tests/test_plugin_discovery.py`), then parse+evaluate formulas: `=COSH(0)` → 1.0, `=SQRT(-1)` → `#NUM!`, `=STDEV(A1:A4)` over a range, `=PI()` → 3.14159…, `=MOD(7,0)` → `#DIV/0!`. Per-function unit coverage plus the error paths. No install required; run with `PYTHONPATH=src:packages/trellis-mathpack/src`.
- **Tier 2 — real discovery (the actual gate proof).** `pip install -e packages/trellis-mathpack` (which pulls in the core), then a *fresh interpreter* does only `import trellis; ...` and confirms `=COSH(0)` already works — i.e. `load_plugins()` auto-found the entry point at `import trellis` time with zero manual `setup()`. This is the end-to-end proof the publication gate wants. Documented as a scripted check; runnable in CI.

## Rejected / deferred alternatives

- **Add `#NUM!` to core.** Tempting (it's a common error), but minting it in `mathpack` is the more valuable demonstration and keeps the core enum minimal. If multiple plugins end up wanting `#NUM!`, promote it to core later — cheap, backward-compatible.
- **Charts / pivots / a stats *engine*.** Out by core philosophy; `mathpack` is plain scalar+aggregate functions.
- **Bundling mathpack into the core package** (as another `builtins` module). Defeats the entire point — the gate needs a *separate distribution* exercising `entry_points`, not more in-tree built-ins.
- **Pinning a specific `trellis` version** in `dependencies`. During pre-publication dev the core isn't on PyPI; depend on `trellis` unpinned and install both editable locally. Revisit at first release.

## Open questions

- **Is the core `pip install`-able as-is for the Tier-2 test?** It has a `pyproject.toml` and `dependencies = []`. Confirm `pip install -e .` on the core succeeds in a clean venv before relying on it for the discovery test. (If the editable install of the core has the permission quirk noted in past WORKLOGs, the Tier-2 test may need a real venv rather than the mount.)
- **One module or split?** Start with everything in `__init__.py`; split into `_functions.py` only if it gets unwieldy. Decide during #3.
- **Sample vs population stats default.** Going with sample (`STDEV`/`VAR`, n−1) to match Excel's unsuffixed names; `STDEVP`/`VARP` are in the deferred list.

## Implementation breakdown (subtasks of this part)

| Task ID | What | Plan/Implement |
|---------|------|----------------|
| #1 | Write this scope (Part 4) | (this doc) |
| #2 | Scaffold the package (pyproject, src/ layout, README skeleton) | **DONE** (Session 24) |
| #3 | Scalar functions (trig, hyperbolic, powers/logs, misc) + `NUM` + `_num` helper | **DONE** (Session 25) |
| #4 | Range-aware stats (`STDEV`/`VAR`/`MEDIAN`) + `_collect_numerics` | **DONE** (Session 26) |
| #5 | `setup()` + entry-point wiring | **DONE** (Session 27) |
| #6 | Tier-1 hermetic tests (per-fn + error paths) | Verify |
| #7 | Tier-2 editable-install discovery proof + finish README | Verify |
| #8 | Confirm gate cleared; WORKLOG; note publication readiness | Verify |

Each implementation task lands as a self-contained chunk with its tests, per the established rhythm. #2–#5 are the build; #6–#7 are the two test tiers; #8 is the gate sign-off that unblocks the first GitHub push.

## References

- `docs/plugin-example.md` — "Shipping a plugin as an installable package" (the COSH/SINH worked example this