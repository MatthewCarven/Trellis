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
| #6 | Tier-1 hermetic tests (per-fn + error paths) | **DONE** (Session 27/28, 32 tests) |
| #7 | Tier-2 editable-install discovery proof + finish README | **DONE** (Session 28, `scripts/tier2_discovery_check.sh`) |
| #8 | Confirm gate cleared; WORKLOG; note publication readiness | **DONE** (Session 28 — GATE CLEARED) |

Each implementation task lands as a self-contained chunk with its tests, per the established rhythm. #2–#5 are the build; #6–#7 are the two test tiers; #8 is the gate sign-off that unblocks the first GitHub push.

## References

- `docs/plugin-example.md` — "Shipping a plugin as an installable package" (the COSH/SINH worked example this package realises).

---

# Part 5: `trellis-tui` — the terminal frontend (next milestone)

Status: **scope, written 2026-06-06 Session 32.** No package code yet — this is the plan. Decisions confirmed with Matthew this session: **v1 is a usable editor** (grid + navigation + cell editing + formula bar + CSV open/save), **Excel-ish keybindings**, **no TUI plugin API yet** (hardcode first, extract hooks when real patterns emerge), **single visible sheet**.

## Purpose

Build `packages/trellis-tui/` — the [Textual](https://textual.textualize.io/)-based terminal spreadsheet application the README has promised since day one. Three jobs:

1. **Clear the "is this a usable spreadsheet?" bar.** Everything so far is engine. This is the first thing a human can sit in front of and *use*.
2. **Be the first real renderer.** Part 3 ("pre-render engine prep") hardened the event payloads, `Sheet.batch()`, and `used_range()` *specifically for this consumer*. The TUI is where that investment pays out — or where its gaps surface.
3. **Prove "library first, app second" for real.** The TUI is a *frontend*, not a plugin (decision 2026-06-05, recorded in CLAUDE.md): it imports `trellis` and drives it from the outside; core never learns it exists. Where mathpack proved the *extension* surface (a plugin reaching in), the TUI proves the *embedding* surface (an application wrapping around). Same rule as Part 4: if the TUI needs a core internal, that's a core public-surface bug — fix it in core.

## Design goals

1. **One-way coupling, enforced by packaging.** `trellis-tui` depends on `trellis` + `textual`; nothing under `src/trellis/` imports, names, or special-cases the TUI. The `textual` dependency lives in the TUI package's pyproject only — core stays `dependencies = []`.
2. **The engine is the model — no shadow data.** The app holds a real `Workbook`/`Sheet`, the same objects a REPL would. The grid widget's displayed strings are a render cache, never an authority. All reads via public API (`cell.value`, `cell.formula`, `used_range()`); all writes via `sheet[a1] = ...` / `sheet.delete(...)` — the leading-`=` formula sugar comes free, and the TUI never parses formulas itself.
3. **One repaint path: the event echo.** The TUI repaints *only* in response to engine events (`cell:change`, `cell:recalc`, `sheet:batch`) — including for its own edits. A TUI-initiated write goes to the engine and the grid updates when the event comes back, identically to a recalc cascade or a plugin's write. No second "I just wrote this, patch the widget directly" path to drift out of sync.
4. **Excel-ish, immediately familiar.** Arrows move, typing replaces, F2 revises, Enter commits-and-moves-down, Esc cancels. The target user lives in CSV/Excel; the TUI should feel like that, not like a modal editor.
5. **Small v1, honest deferrals.** Single sheet, no selection ranges, no clipboard, no undo, no TUI plugin API. Each deferral is listed below with a reason and a revisit trigger.

## Package layout

```
packages/trellis-tui/
  pyproject.toml
  README.md
  src/
    trellis_tui/
      __init__.py          # __version__, re-export TrellisApp
      app.py               # TrellisApp (textual.App): bindings, CSV open/save, main()
      grid.py              # SheetGrid: DataTable-backed grid + engine-event subscriptions
      editor.py            # formula bar + edit-mode state machine (nav vs edit)
      render.py            # value -> display text policy (pure functions, no textual import)
  tests/
    test_render.py         # pure unit tests, no TUI needed
    test_grid_sync.py      # event -> repaint (Textual Pilot, headless)
    test_editing.py        # keybinding flows (Pilot)
```

Four modules, same "split only if unwieldy" rule as mathpack. `render.py` deliberately imports nothing from textual so the display policy is testable as plain functions.

`pyproject.toml` essentials:

```toml
[project]
name = "trellis-tui"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["trellis", "textual>=8"]   # 8.2.x current as of 2026-05; pin style = open question

[project.scripts]
trellis = "trellis_tui.app:main"
```

`trellis [file.csv]` is the whole CLI: open the file (via `read_csv`) or start with an empty one-sheet workbook.

## The shape: MVC over a live engine

- **Model** — a real `Workbook`; current sheet = first sheet (v1). Recalc, events, and plugins behave exactly as in a REPL — mathpack functions work in the TUI for free, a nice integration check.
- **View** — `SheetGrid` wraps Textual's `DataTable` (cell-cursor mode): column headers `A B C…`, row labels `1 2 3…`, one materialized **window** = `used_range()` ∪ a minimum size, growing on demand as the cursor nears an edge. Above it a formula bar (address label + cell content); below it a status line (file path, dirty flag, transient messages).
- **Controller** — bindings on the App. Two modes: **nav** (cursor on the grid; the bar mirrors the current cell — `formula` if set, else rendered value) and **edit** (focus in the bar's `Input`).

The repaint loop — Part 3, cashed in:

- `cell:change` / `cell:recalc` → if `address` is inside the window, render `new_value` and `update_cell_at` that one coordinate. Payloads carry `old_value`/`new_value`, so a no-op write can skip the repaint — the exact rationale 3.1 locked both in for. `cell:recalc`'s `trigger` feeds a status-line note ("recalc ← A1") nearly for free.
- `sheet:batch` → walk `changes`; if the batch dwarfs the window (CSV load), rebuild the window once instead. `read_csv` already loads inside `batch()` (3.2), so file-open is one event, not ten thousand.
- Handlers run synchronously inside the engine write, which happens inside a Textual key handler — same thread, no async gymnastics. A pathological recalc cascade means many `update_cell_at` calls in one handler; acceptable v1, coalescing is the documented escape hatch.
- Dirty tracking is the same subscription: any `cell:change`/`sheet:batch` sets the flag, save clears it, `Ctrl+Q` warns once if set. The TUI dogfoods the event system exactly like a plugin would.

## Interaction model (v1 keys)

| Key | Nav mode | Edit mode |
|-----|----------|-----------|
| Arrows / PgUp / PgDn / Home / End | move cursor (DataTable native) | — (arrows edit text) |
| `Ctrl+Home` | jump to A1 | — |
| printable char | **replace-edit**: open bar empty, insert char | type |
| `F2` | **revise-edit**: open bar with existing formula/value | — |
| `Enter` | start revise-edit (lean — see open questions) | commit + move down |
| `Tab` / `Shift+Tab` | — | commit + move right / left |
| `Shift+Enter` | — | commit + move up |
| `Esc` | — | cancel, restore bar |
| `Delete` | clear cell (`sheet.delete`) | — |
| `Ctrl+S` | save CSV (prompt for path if none) | — |
| `Ctrl+Q` | quit (warn once if dirty) | — |

Commit semantics: leading `=` → store the text as-is (the engine's formula sugar takes over); otherwise run the typed text through **value inference** (int → float → string; see the public-surface gap below) so typing `42` stores a number while `01234` stays a string — coherent with CSV load. Excel's commit-on-arrow-keys nuance in replace-edit is deferred polish. Commits never block: a broken formula stores as its error value with the formula text preserved for F2 (verified engine behaviour — errors are values, no ParseError at the set boundary).

## Rendering policy (`render.py`)

One pure function `display(value) -> DisplayText(text, align, error)` (frozen dataclass; `align` is a Rich justify value) shared by grid and bar:

- `None` → `""`; `str` → as-is (no quoting); `bool` → `TRUE`/`FALSE` (Excel-faithful); `int` → `str(x)`; `float` → integer form for integral floats within ±1e16 (`4.0`→`4`, exact through 2**53), else `%.15g` (trims one-ulp noise: `0.1+0.2`→`0.3`); `NaN`/`Infinity` render as themselves — values, not error cosplay (**DECIDED #3**). **No display-format system in v1** — number formats stay a future plugin story, per Part 3's do-NOT-pre-build list.
- `FormulaError` → its code (`#DIV/0!`), styled distinct (red) — matches the CSV export policy.
- Numbers right-aligned, text left-aligned, logicals and errors centered (Rich `Text(justify=…)` per cell — one line, big legibility win).

## Public-surface gap found by this pass

**Typed input needs core's value-inference rule, and that rule is private.** The TUI receives text from an `Input`; storing `"42"` as a string would make `=SUM(...)` over typed data useless. The needed rule — int, then float, then string, with the leading-zero / whitespace / no-bool conservatisms — is exactly `trellis.io.csv._infer_value`, which is underscore-private. Duplicating it in the TUI would drift. Per the Part 4 rule, that's a core public-surface bug: **promote `_infer_value` to a public name** (e.g. `trellis.io.csv.infer_value`, re-exported as `trellis.infer_value`) — a ~5-line core diff + tests + README line, scheduled in #2. First confirmed case of the TUI exercising a gap shut, which is much of why this part exists.

## Design decisions

- **`DataTable`, not a custom grid widget.** Textual's DataTable gives virtualized rendering, a cell cursor, `update_cell_at`, and mouse support — 90% of a grid for free. Cost: the window is materialized into it, so a million-row sheet would materialize a million rows — out of scope; CSV-scale data is the stated use. Replacing `SheetGrid`'s internals with a custom virtualized widget later is invisible to the rest of the app; that's the escape hatch, taken only on proven need (`simplicity-over-clever-solvers`).
- **Formula-bar-only editing in v1.** An in-cell floating `Input` overlay is the polished look but is absolute-positioning fiddliness over a DataTable; the bar is always visible, needs zero positioning code, and early-Excel users lived in it happily. In-cell overlay = deferred view-only upgrade.
- **Console script is `trellis`.** The TUI owns the human-facing command; core remains import-only (it has no CLI today). Reversible pre-publish if core ever wants the name.
- **Textual floor `>=8`** (8.2.x current, May 2026; supports py3.9–3.14, so the 3.10 sandbox can run the suite while the package declares 3.11+). Core's stale convenience extras (`tui = ["textual>=0.50"]`, `all = [...]`) get bumped in #2.
- **Tests ride Textual's `Pilot`** (`App.run_test()`): headless, async, CI-friendly — press keys, assert grid + engine state. `render.py` tests stay textual-free.
- **No `meta` writes in v1.** Column widths etc. are app state, not cell state. If the TUI ever persists per-cell UI state, it follows the plugin convention: one top-level `"trellis-tui"` key.

## Explicitly NOT in v1 (deferred, with reasons)

- **TUI plugin API** (panels, keymaps, commands) — confirmed hardcode-first (Matthew, 2026-06-06). Extract hooks once ≥2 concrete wants exist. First candidate already queued: a **vim keymap**.
- **Selection ranges + clipboard** — needs a selection model first, and terminal clipboard is its own yak. Revisit right after v1; likely the most-missed feature.
- **Undo/redo** — event payloads carry `old_*`/`new_*` precisely so an undo log can be an outside observer. Candidate *second reference plugin* rather than TUI code.
- **Sheet tabs / multi-sheet UI** — single sheet confirmed for v1; `sheet:add/remove/rename` events are ready when tabs come.
- **Column widths, frozen panes, in-cell edit overlay, themes** — view polish, post-v1.
- **Conditional-formatting display** — the on-the-fence core question; whatever lands must be plugin-expressible. The TUI will eventually *read* style hints from `cell.meta`; it won't invent them.

## Open questions

- ~~**Nav-mode `Enter`**~~ **DECIDED (#5, Session 32):** revise-edit (Sheets-style — Down already moves; a second move-down key is wasted). The grid's `enter` binding overrides DataTable's select; mouse-click selection is ignored (click ≠ edit).
- ~~**Empty commit**~~ **DECIDED (#5, Session 32):** delete (Excel-faithful, keeps `used_range()` tight; `sheet.delete` verified tolerant of already-empty cells).
- ~~**Textual pin style**~~ **DECIDED (#2, Session 32):** `>=8` uncapped — cap on a proven break, not preemptively; scaffold verified green on 8.2.7.
- ~~**Window defaults**~~ **DECIDED (#4, Session 32):** 100 rows × 26 cols minimum; grow +32 rows / +8 cols when the cursor comes within 2 of an edge; batch-rebuild threshold 256 changes; column width 10. All class attributes on `SheetGrid` — retune by subclassing, no config system. Out-of-window engine writes rebuild the window to cover them; the cursor's high-water reach survives rebuilds.
- ~~**Float display**~~ **DECIDED (#3, Session 32):** integer form for integral floats within ±1e16, else `%.15g`; `NaN`/`Infinity` as themselves. `tests/test_render.py`'s table is the spec.
- ~~**Revise-edit prefill (new, found in #3)**~~ **RESOLVED (#5, Session 32):** prefill from `cell.formula` when set, else full-fidelity text (`repr` for floats, `TRUE`/`FALSE` for bools, the code for error values) — never display text. Plus the **unchanged-revise rule**: an unmodified revise-edit commits nothing at all, making F2+Enter a true no-op even for values whose text form can't round-trip (bools: inference deliberately never produces them).
- ~~**Pathless `Ctrl+S` prompt**~~ **DECIDED (#6, Session 32):** a modal (`SaveAsScreen`), not a bar takeover — the cell editor's state machine stays single-purpose, and the modal is the natural growth point for a future Open dialog. Bonus #6 decision: `trellis missing.csv` opens an empty workbook with the path remembered (Ctrl+S creates the file) — the natural new-spreadsheet flow.

## Implementation breakdown (subtasks of this part)

| Task ID | What | Notes |
|---------|------|-------|
| #1 | Write this scope (Part 5) | (this doc) |
| #2 | Scaffold `packages/trellis-tui/` + core housekeeping | pyproject (`textual` dep, `trellis` script), src/tests skeleton, README skeleton; bump core's stale `tui`/`all` extras; **promote `_infer_value` → public** (+ tests, README line) — **DONE** (Session 32) |
| #3 | `render.py` display policy | pure functions, table-driven unit tests; settle the float rule — **DONE** (Session 32) |
| #4 | Read-only `SheetGrid` | window materialization (`used_range()` ∪ min, grow-on-demand), headers, cursor, formula-bar mirroring, event-driven repaint incl. `sheet:batch`; Pilot tests — **DONE** (Session 32) |
| #5 | Editing | replace/revise edits, commit/cancel keys, typed-input inference, `Delete`, dirty flag; Pilot tests — **DONE** (Session 32) |
| #6 | CSV open/save + app chrome | CLI-arg open, `Ctrl+S` (+ pathless prompt), status line, `Ctrl+Q` dirty warning; Pilot tests — **DONE** (Session 32) |
| #7 | README + sign-off | TUI README (usage, key table, "frontend not plugin" note), root README status update, WORKLOG — **DONE** (Session 32). **Part 5 #1–#7 COMPLETE; all open questions resolved.** |

Same rhythm as Part 4: each row lands as a self-contained chunk with its tests. #4 is the heart (the Part 3 surface, consumed); #5 makes it an editor; #6 makes it an app.

## References

- Part 3 of this doc — the event payloads, `batch()`, and `used_range()` this part consumes.
- README "Extending" + `docs/plugin-example.md` — the contrast: mathpack extends from inside, the TUI embeds from outside.
- Textual docs: [DataTable](https://textual.textualize.io/widgets/data_table/), [testing guide](https://textual.textualize.io/guide/testing/) (Pilot).
- CLAUDE.md "Repository layout" — the 2026-06-05 in-repo companion-package decision.


---

# Part 6: Selection + clipboard (the most-missed v1 gap)

## Purpose

Give the TUI the other half of spreadsheet muscle memory: select a rectangle, copy/cut it, paste it somewhere else — with formulas that *behave like Excel's* when they move. Part 5 deliberately shipped without this; it was the top of the v2 pull list and Matthew confirmed it as the next part after his first real run.

Like Part 5, this part is also a deliberate probe of the engine's public surface: moving formulas around exposes whether reference *rewriting* is expressible from outside the core. (Part 5's probe found `infer_value`; this part's finding is `shift_formula` + `$` pins — see below.)

## Design goals

- **Excel-faithful where it counts.** Shift+arrows extend, Ctrl+C/X/V, relative refs shift on copy-paste, `$` pins them, cut-paste moves verbatim. Deviations are explicit and documented, never accidental.
- **The grid still never writes the engine.** Selection is view state; clipboard actions route through the app to the same single write path family as editing. Every paste is ONE `sheet.batch()` — one event echo, one recalc pass, one dirty mark (Part 3's machinery keeps paying).
- **Engine growth stays minimal and library-first.** Core learns `$` references and one public helper; it never learns what a clipboard is. A REPL user gets `trellis.shift_formula` for free; the TUI is just its first consumer.

## Decisions confirmed up front (Matthew, 2026-06-06)

1. **Paste semantics: Excel-faithful + `$` pins.** Copy-paste shifts relative references by the paste offset (`=A1*2` from B1 pasted at B2 → `=A2*2`); the engine gains `$A$1` / `$A1` / `A$1` absolute syntax so references can opt out of shifting. Chosen over shift-without-`$` (no way to pin a rate cell) and verbatim-paste (defies the copy-across-a-row workflow).
2. **OS clipboard: both directions.** Copy mirrors the selection to the system clipboard as TSV (Textual `App.copy_to_clipboard`, OSC 52 — Windows Terminal supports it); paste FROM other apps arrives via the terminal `Paste` event. Paste a column out of Excel or a browser straight into Trellis.
3. **Cut: pragmatic move.** Cut-paste pastes the cells *verbatim* (no reference shifting — matching Excel's cut) and clears the source range at paste time, all in the same batch. What v1 does NOT do: rewrite *other* formulas that pointed at the moved range (Excel's inbound-reference following) — that's a whole-sheet scan-and-rewrite, deferred until someone misses it. Documented deviation.

## Engine additions

### 6.A — `$` absolute references

- **Lexer:** `$` joins the identifier scan (it currently lexes as an unknown character). `$A$1` arrives at the parser as one IDENT lexeme.
- **Parser:** the cell-ref predicate grows to `(\$?)([A-Za-z]+)(\$?)(\d+)`; corner normalisation for ranges preserves per-corner flags.
- **AST:** `CellRef` gains `col_abs: bool = False`, `row_abs: bool = False`. Frozen-dataclass-compatible (defaulted fields; existing constructions, equality, and hashing for plain refs are untouched).
- **Evaluator + recalc: indifferent by design.** `=$A$1` evaluates exactly like `=A1`; the dependency graph keys on `(row, col)`, so pinned and unpinned refs to the same cell are automatically the same dependency. The flags exist *only* for rewriting.
- **`trellis.core.address` stays `$`-free.** `to_a1` is unchanged; `$`-knowledge lives in the lexer/parser and the shift helper. Smallest possible surface.
- Storage already round-trips: `cell.formula` keeps the user's text verbatim, so `$` survives without any unparser.

### 6.B — `shift_formula` — the public rewrite helper

`trellis.shift_formula(text: str, rows: int, cols: int) -> str` — token-level splice, not AST re-emission:

- Tokenize; for each IDENT that satisfies the parser's cell-ref predicate, shift the non-`$` axes by the offset; splice the rewritten lexemes back at their `Token.pos` spans. Everything else — spacing, case, function names, the leading `=` — survives byte-for-byte.
- **A shift off the sheet edge** (row or col < 0) replaces that reference with the literal text `#REF!` (Excel-identical: the pasted formula *contains* `#REF!`). Whether the parser treats `#REF!` in source as a proper error literal or as a parse error is resolved at #3 — either way the cell stores an error value with the text preserved (the broken-formula commit contract from Part 5 already guarantees the fallback).
- Range refs shift per-corner. `rows=cols=0` returns the text unchanged (identity contract, tested).
- Public at all three levels (`trellis.formula`, re-export root) + root-README bullet, mirroring `infer_value`'s promotion pattern.

## TUI architecture

### Selection model (grid-owned view state)

- `selection = (anchor, cursor) | None` on `SheetGrid`; the normalised rectangle is a property. **Shift+arrows extend** (anchor pinned, cursor moves — grow-on-demand still applies at the edges); any plain cursor move or Esc collapses it. **Ctrl+A selects `used_range()`**.
- **Painting:** delta-repaint on selection change — restyle cells entering/leaving the rectangle with a background tint that *composes* with display styling (error-red text on selection tint must survive). Selections bigger than the existing batch-rebuild threshold just rebuild — reuse, don't invent.
- **Readout:** the formula bar / status line shows `B2:D5 (3×4)` while a selection is live; the formula bar otherwise keeps mirroring the cursor cell.

### Clipboard model (app-owned)

`Clipboard(cells, mode, source_anchor, tsv)` — a snapshot, not live references:

- Per-cell payload: **formula text if the cell has one, else the raw value** (full fidelity — ints, floats, bools, error values carry as objects, no text round-trip internally).
- `tsv` is the OS mirror built at copy time (display-text fields, embedded tabs/newlines flattened to spaces — pragmatic, resolved at #6); pushed via `copy_to_clipboard`.
- **Paste targeting:** range payload anchors at the cursor (or selection top-left); a single-cell payload **fills the whole selection** (Excel's fill-on-paste). Every written cell: formula → `shift_formula(text, dr, dc)` with that cell's offset from its source cell (copy mode) or verbatim (cut mode); value → written raw. All inside one `sheet.batch()`; window growth on out-of-window paste rides the existing rebuild-to-cover path for free.
- **Cut:** marks the clipboard `mode="cut"`, status line shows `cut B2:D4 — paste moves it`; paste writes targets *and* deletes the not-overwritten source cells in the same batch, then the clipboard demotes to copy mode (re-pasting after a move re-stamps a copy — friendlier than Excel's one-shot; deviation noted). Esc cancels a pending cut. **Added at #6:** *any* engine change while a cut is pending also demotes it — a stale snapshot must never delete source cells whose content changed since (Excel disarms cut on edit for the same reason).

### The Ctrl+V / terminal-paste unification

In most terminals (Windows Terminal included) **Ctrl+V never reaches the app** — it arrives as a Textual `Paste` event carrying text. So both entry points funnel to one `action_paste`:

- `on_paste(text)`: if `text` equals the TSV we last mirrored out → it's our own copy bouncing off the OS — use the **internal** clipboard (formulas shift, values keep fidelity). Otherwise it's **external** TSV/text: split on newlines/tabs, each field through `infer_value` (`=`-leading text commits as a formula verbatim — same policy as typing it; no shifting, external text has no source anchor), batch-written at the cursor.
- The `ctrl+v` BINDING also exists for terminals that pass the key through; it pastes the internal clipboard directly.

## Rejected / deferred alternatives

- **Inbound-reference rewrite on cut** (Excel's full move semantics) — whole-sheet scan + rewrite of every formula referencing the moved range. Deferred until missed; the pragmatic move covers the daily case.
- **Marching-ants source highlight** — status-line message instead; one repaint path, no animation timers (the StatusBar no-timers rule extends here).
- **Fill handle / Ctrl+D fill-down** — adjacent feature, separate part; `shift_formula` is the hard half of it anyway.
- **Mouse drag-select** — Textual's cell-click events need modifier inspection; checked at #4, included only if free. Keyboard-first is the v1 bar.
- **Clipboard history / multi-clipboard** — plugin territory the moment the TUI grows hooks; not core, not now.
- **Formula source in the outbound TSV mirror** — considered after the S35 field test (spreadsheets parse pasted text like typed input, so `=A1*2` would land live in OO/Excel); **declined by Matthew (S35): values-only stays** — Excel-faithful, least surprising for plain-text destinations. Revisit as an opt-in "copy formulas" gesture only if it's ever actually missed.

## Open questions

- ~~Does the parser want `#REF!` (and friends) as first-class error *literals* in source text?~~ **RESOLVED at #3 (S33): yes.** One ERROR token kind (longest-match against the seven codes), one frozen `Error` AST node, evaluator resolves the code to its constant (minting unknowns, open-world). `=#REF!*2` parses, evaluates to `#REF!`, and propagates — a shifted-off-edge paste computes exactly like Excel's.
- ~~Shift+click to extend selection: do DataTable click events expose modifiers in textual 8.x?~~ **RESOLVED at #4 (S34): yes — included.** `events.Click` carries `.shift` (and `.style.meta` carries the cell's row/column), so `SheetGrid._on_click` pins the anchor before `DataTable` moves the cursor and the move arrives flagged as an extension. Plain clicks collapse via the plain-move path. **Field addendum (S35):** the API exposing `.shift` isn't the same as the terminal *sending* it — emulators reserve Shift+mouse for native text selection and never forward it (Windows Terminal confirmed). Ctrl and Alt ride the SGR modifier bits through, so extend-click accepts shift|ctrl|meta; in practice Ctrl+click is the gesture.
- ~~Selection repaint threshold: reuse the grid's existing 256-cell rebuild threshold, or measure first?~~ **DECIDED at #4 (S34): reuse** `REBUILD_THRESHOLD`, retune by subclassing. The delta itself is enumerated in O(delta) (strip decomposition of the rect symmetric difference), so the threshold only gates the restyle-vs-rebuild choice.
- ~~TSV mirror fidelity: flattening embedded tabs/newlines is lossy for strings — acceptable for v1 OS interchange?~~ **DECIDED at #6 (S34): yes** — tabs/newlines/CRs flatten to spaces in the mirror only (`_tsv_field`); the internal clipboard carries the objects untouched, and the own-TSV bounce detection routes a same-app paste back to it, so the lossiness is only ever visible to *other* programs.

## Implementation breakdown

| # | What lands | Where |
|---|------------|-------|
| 1 | This design pass | design.md Part 6 |
| 2 | `$` references: lexer + parser predicate + `CellRef` flags; evaluator/recalc indifference proven — **DONE (S33)** | core + tests |
| 3 | Public `shift_formula` (token-splice; `#REF!` policy resolved; identity + pin + range + off-edge table) — **DONE (S33)** | core + re-exports + README bullet + tests |
| 4 | Selection model: Shift+arrows, shift+click, Ctrl+A, Esc, delta-paint, bar readout, Delete clears selection — **DONE (S34)** | grid.py + app/editor + tests |
| 5 | Internal clipboard: copy + paste (shift/fill/anchor), one-batch write path, dirty/echo riding it — **DONE (S34)** | app.py + grid intents + tests |
| 6 | Cut (pragmatic move) + OS bridge: TSV mirror out, `Paste`-event in with own-TSV detection, external inference — **DONE (S34)** (+ safety: any sheet change disarms a pending cut) | app.py + tests |
| 7 | READMEs (key table + features), design.md rows closed, worklog — **DONE (S34). PART 6 COMPLETE.** | docs |

Same rhythm as Parts 4–5: each row is a self-contained land with its tests; #4 and #5 are the heart; #6 makes it shine.

## References

- Part 3 — `sheet.batch()` and the locked event payloads every paste rides.
- Part 5 — the one-repaint-path rule, `commit_text` policy (broken formulas commit as error values), the class-attribute tuning pattern, `infer_value`'s promotion precedent.
- `src/trellis/formula/errors.py` — `REF` already exists; off-edge shifts have their error waiting.
- Textual docs: [Paste event](https://textual.textualize.io/api/events/#textual.events.Paste), `App.copy_to_clipboard` (OSC 52), DataTable styling.\n
# Part 7: trellis-undo — undo/redo as the second reference plugin

## Purpose

Undo/redo for any Trellis sheet, shipped as a companion package and wired into the TUI as Ctrl+Z / Ctrl+Y. Top of the v2 pull list after Part 6 field-verified (S35).

This is the **second reference plugin**, and it proves a different extension surface than the first. Mathpack shows *global registration* (entry point → `register_function` at import). Undo shows *stateful attachment*: a live object subscribing to a sheet's events and stashing itself in `meta` — zero core changes, no entry point at all. Together they bracket the two ways to extend Trellis. The Part 3 payload lock-in was designed with this consumer in mind ("the payloads already carry everything it needs" — now cashed in).

## Design goals

- **The engine hands us the diff; keep it.** One recorded event = one undo step. No command pattern, no shadow model — steps hold the displaced `Cell` *objects* from the locked payload.
- **Restore by object.** `sheet.set(addr, old_cell)` stores the instance as-is (engine-sanctioned); the recalc engine re-evaluates restored formulas and their dependents, so snapshot-stale values self-heal (verified S35: a restored `=A1*2` recomputed against moved deps, cascade included). Plugin state in `meta` survives the round-trip for free.
- **Library first.** `UndoLog(sheet)` works from a REPL with no TUI anywhere. The TUI is just its first consumer.

## Decisions confirmed up front (Matthew, 2026-06-07)

1. **TUI wiring: hard dependency.** `trellis-tui` depends on `trellis-undo`; Ctrl+Z works out of the box. (Soft-import rejected: weaker default for no real decoupling win in a monorepo.)
2. **Undo + redo.** Ctrl+Z / Ctrl+Y (+ Ctrl+Shift+Z alias). Redo clears on any new recorded write — standard editor contract.
3. **History capped, default 1000 steps.** Constructor arg + class attribute (`CAPACITY`), `None` = unbounded — the house escape-hatch pattern. Oldest steps drop silently (`deque(maxlen=...)`).

## Architecture

### The package

`packages/trellis-undo/` (module `trellis_undo`, `dependencies = ["trellis"]`) — **deliberately NO `trellis.plugins` entry point.** A no-arg import-time `setup()` has nothing sane to do here: there is no global registry of workbooks to attach to. The pyproject says so in a comment, mirroring the TUI's "frontend, not plugin" note. Reference value: entry points are for global registration; **events + meta are for stateful attachment.**

### `UndoLog(sheet, *, capacity=1000)`

- **Records** `cell:change` and `sheet:batch` — one step per event, so a TUI gesture (an edit; a paste, selection-delete, or CSV load batch) is exactly one step. `cell:recalc` is NOT recorded: derived state re-derives on restore.
- A step is a tuple of `(address, old, new)` triples (1 per change; N for a batch), holding the payload's `Cell` objects.
- **`undo()`**: pops a step, restores every `old` — inside ONE `sheet.batch()` when the step is multi-cell — pushes the step onto the redo stack, returns the cell count (`None` when empty). **`redo()`** mirrors (restores `new`). Empty `old` (no value, no formula) restores as `sheet.delete` — absence stays absence, storage stays tight (set-empty would be observably harmless — `used_range` filters empties, verified — but delete keeps `_cells` honest).
- **Self-suppression:** a `_restoring` flag makes the recorder ignore the log's own writes. Any *recorded* write clears the redo stack.
- Surface: `can_undo` / `can_redo`, `depths` (undo, redo) for save-point experiments, `clear()`, `detach()` (unsubscribe).

### Attachment helpers (the meta-convention demo)

- `attach(sheet, **kw) -> UndoLog` — construct, stash at `sheet.meta["undo"]` (single namespaced key, per convention), return. Idempotent: an already-attached sheet returns its existing log.
- `detach(sheet)` — unsubscribe + remove from meta.
- `attach_workbook(wb, **kw)` — attach to existing sheets and, via the `sheet:add` event the workbook docstring advertises for exactly this, every future one.

### TUI wiring

- `trellis-tui` pyproject gains the dependency; setup-venv scripts editable-install the new package.
- The app `attach`es on mount, `detach`es on unmount. Grid-level bindings (nav-only, the clipboard-keys rationale: while editing, Ctrl+Z must not touch the sheet) post `UndoRequest` / `RedoRequest`; the app calls the log and reports: `undid 3 cells` / `redid B3` / `nothing to undo`.
- **Dirty:** undo writes are engine writes → dirty marks honestly. Undoing back to the save point clearing dirty = open question (cheap depth-compare; decide at the TUI row).
- **Cut interplay for free:** undo writes demote a pending cut via the existing `_mark_dirty` hook — the stale-snapshot safety holds.

## Rejected / deferred

- **Entry-point auto-attach** — no global workbook registry exists, and inventing one for this would be the tail wagging the dog. Explicit attach is library-first.
- **Command-pattern undo** (recording intents, replaying inverses) — the engine already hands over exact state diffs; commands would re-derive what we're given.
- **Coalescing/grouping** (e.g. merging keystroke bursts) — TUI commits are already gesture-grained; nothing to merge.
- **Cross-sheet transactional undo** — logs are per-sheet; `attach_workbook` is N independent logs. The TUI is single-sheet anyway.

## Open questions

- ~~Save-point dirty integration: app remembers `depths` at save; undo/redo landing back on it clears dirty. Decide at #4.~~ **DECIDED at #4 (S35): not in v1.** Depth equality lies once steps drop off the cap (save at a full deque, write, redo back — same depths, different content), so the honest version needs drop-tracking. Undo writes mark dirty like any write; revisit only if the ● modified after undo-to-saved actually bothers anyone. **Ratified by Matthew (S35): it doesn't ("edge case dont care about really") — and his versioning instinct is git on the saved CSV anyway, which the `formulas=True` round-trip already serves. Closed for good.**
- ~~Does the TUI need a visible hint that history dropped past the cap?~~ **DECIDED (S35): no** — silent, like every editor.

## Implementation breakdown

| # | What lands | Where |
|---|------------|-------|
| 1 | This design pass | design.md Part 7 |
| 2 | Scaffold: pyproject (no entry point, with the why-comment), README skeleton, contract docstrings — **DONE (S35)** | packages/trellis-undo/ |
| 3 | `UndoLog` + `attach`/`detach`/`attach_workbook`: record/suppress/undo/redo/cap, hermetic engine-only tests (15) — **DONE (S35)** | trellis_undo + tests |
| 4 | TUI wiring: dependency, grid bindings + request messages, app handlers + status, venv scripts, Pilot tests (7) — **DONE (S35)** | trellis-tui |
| 5 | READMEs (undo + TUI key table + root), design rows closed, worklog — **DONE (S35). PART 7 COMPLETE.** | docs |

## References

- Part 3 — the 3.1 payload lock-in (old/new `Cell` objects in every change; `sheet:batch` change lists) — the contract this plugin consumes.
- Part 6 — `_mark_dirty`'s pending-cut demote (composes with undo writes unchanged).
- `core/workbook.py` — the `sheet:add` docstring that anticipated `attach_workbook`.
- mathpack — the *other* reference plugin: global registration via entry point, the style this one deliberately isn't.

---

# Part 8: Fill — Ctrl+D / Ctrl+R (keyboard fill)

## Purpose

The fill workflow: write `=B2*1.1` once, fill it down a hundred rows. Excel's drag handle is the famous gesture, but its keyboard half — **Ctrl+D fill down, Ctrl+R fill right** — is the one that fits a terminal, and it was named on the v2 pull list from the start ("`shift_formula` is the hard half of it anyway" — Part 6 called it, and that half is done and public).

Engine additions: **none.** Fill is a frontend gesture over surface the engine already exports — the design test passes by construction (the REPL idiom is a two-line loop over `shift_formula`; see Rejected for why that loop doesn't get promoted into core).

## Design goals

- **Excel-faithful keys, Excel-faithful semantics.** Ctrl+D/R fill within the selection from its first row/column; with no selection they fill from the neighbor above/left. No clipboard involvement — your copied cells survive a fill.
- **One gesture, one batch.** The whole fill is ONE `sheet.batch()` — one echo, one recalc, one dirty mark, one undo step (Part 7 composes for free).
- **The grid still never writes the engine.** Fill is a request message; the app executes it through the same per-cell transfer helper paste already uses.

## Decisions confirmed up front (Matthew, 2026-06-08)

1. **Keyboard only.** Ctrl+D / Ctrl+R; the mouse drag handle is deferred — a one-character target in a character grid plus drag-protocol fragility across terminals (the S35 shift+click lesson generalizes: anything mouse+modifier needs a field check, and drags are worse). Revisit only if keyboard fill leaves muscle memory unsatisfied.
2. **Single-row/no-selection = fill from the neighbor, Excel-exact.** Ctrl+D with no selection (or a selection only 1 row tall) copies the cell(s) *above* into the target row(s); Ctrl+R mirrors with the column to the left. At the sheet edge (cursor row 0 / col 0) there is nothing to fill from: status hint, no write.
3. **Series fill deferred.** Excel's Ctrl+D never extrapolates anyway (only the drag handle does). The spreadsheet-native idiom: `=A1+1` below, fill down — **the formula IS the series.** Documented in the README; a series gesture lands only if it's ever actually missed (simplicity over clever solvers).

## TUI architecture

### Grid: the intent

- Bindings `ctrl+d` / `ctrl+r` → `FillRequest(rect, axis)` with `axis` `"down"` | `"right"` and `rect` the live `selection_range` or the cursor 1×1 — the ClearRequest shape. Conflict check (textual 8.2.7): DataTable and App bind neither key; `Input` binds Ctrl+D (delete-right) for its *own* text editing, which is exactly the isolation the clipboard/undo keys already rely on — grid-bound means nav-only, and while editing the editor keeps its native behavior (regression-tested like undo's).

### App: the execution

`_fill(rect, axis)` — all writes inside ONE `sheet.batch()`:

- **Resolve source vs targets.** `axis="down"`: selection 2+ rows tall → source = its first row, targets = the rows below it (Excel: source stays put, only targets are written). Selection 1 row tall → source = the row *above* the rect (off-sheet → status `nothing above to fill from`, no batch). `axis="right"` mirrors with columns.
- **Per-cell transfer, per-lane source.** Each target column (down) / row (right) is an independent lane: target `(r, c)` receives the source cell of *its own* lane shifted by its own offset — `_paste_cell(target, formula, value, dr, dc)` verbatim, the same helper paste uses: formulas through `shift_formula` (`$` pins hold, off-edge refs land as `#REF!` literals), raw values copy at full fidelity, **empty source cells clear their targets** (Excel-faithful), `=`-string values take the prebuilt-`Cell` verbatim path.
- **Status:** `filled down B3:D7` / `filled right C2:F4` — the written extent, `_rect_label` style.
- **What composes for free** (the Part 3/6/7 machinery cashing in again): one batch = one undo step (Ctrl+Z un-fills whole); `_mark_dirty` disarms a pending cut; the selection survives (fill doesn't move the cursor — Excel-faithful); repaint rides the batch echo; out-of-window writes can't happen (targets ⊆ selection ⊆ window; the fill-from-neighbor row sits inside it by construction).

## Rejected / deferred

- **Mouse drag handle** — deferred per decision 1 (terminal drag fragility; the keyboard covers the workflow).
- **Series/auto-fill extrapolation** — deferred per decision 3; the formula idiom covers it honestly.
- **`trellis.fill()` engine helper** — fill would be the first core API that takes a rectangle and writes cells: that's a frontend's job description, not a library primitive's. The engine's contribution is `shift_formula` (already public); the REPL user's fill is `for r in range(2, 100): sheet.set((r, 1), shift_formula(src, r - 1, 0))`. Promote only if a second frontend duplicates the loop.
- **Ctrl+U / Ctrl+L fill up/left** — not Excel (those are font keys there); no muscle memory to honor. The rare upward fill is a copy-paste away.
- **Fill-into-empty-only / skip-blanks modes** — option-dialog territory; nothing in the daily workflow asks for it.

## Open questions

- ~~Do Ctrl+D / Ctrl+R survive Windows Terminal to the app?~~ **RESOLVED (S36, same day): yes — field-verified by Matthew, "seems to work nicely."** Both keys arrive clean in Windows Terminal. Workflow note from the field: the gesture pairs with extend-click — Ctrl+click the far cell to set where the fill stops, then Ctrl+D/R fills exactly that rect (the Part 6 selection model and the fill semantics composing as designed).

## Implementation breakdown

| # | What lands | Where |
|---|------------|-------|
| 1 | This design pass | design.md Part 8 |
| 2 | Grid: bindings + `FillRequest` message — **DONE (S36)** | grid.py |
| 3 | App: `_fill` (source/target resolution, lanes, one batch, status) — **DONE (S36)** | app.py |
| 4 | Tests: lanes/shift/pins, fill-from-neighbor, edge no-op, empty-clears, one-batch/one-undo-step, cut-disarm, editor isolation, selection survives (12) — **DONE (S36)** | tests/test_fill.py |
| 5 | Docs: TUI README (features + 2 key rows + the formula-is-the-series note), root README terminal-taste line, design rows closed, worklog — **DONE (S36). Field-verified same day — PART 8 COMPLETE.** | docs |

## References

- Part 6 — `shift_formula` + `$` pins (6.B), `_paste_cell`'s transfer semantics, the request-message pattern, `REBUILD_THRESHOLD` repaint authority.
- Part 7 — one-batch-one-step undo; fill inherits it untouched.
- Excel parity notes: Ctrl+D/R fill from the selection's first row/column; single-cell Ctrl+D copies the cell above; Ctrl+D never does series.

---

# Part 9: Sheet tabs — the editor-buffers model

## Purpose

Multiple sheets in the TUI. The engine's `Workbook` has done multi-sheet from day one (ordered, evented add/remove/rename — the `sheet:add` docstring was written for consumers like this); Part 5 deliberately showed only the first sheet. This part is the UI seam — and, deliberately, **nothing else**: zero engine changes again.

The shape is set by one decision: **a sheet is a file.** CSV is a single-sheet format and Matthew works in CSV ([CSV-only], by design), so tabs here are an *editor's open buffers*, not Excel's workbook-in-one-file: each tab is a CSV with its own path and its own dirty marker, `trellis sales.csv costs.csv` opens two tabs, and the engine `Workbook` is the session container (exactly what it is in a REPL).

## Design goals

- **Editor-buffers honesty.** Per-sheet path, per-sheet dirty, per-sheet undo. Ctrl+S saves *the active sheet*. Quit warns about *any* unsaved sheet. No invented workbook file format.
- **Per-sheet view state survives switching.** Cursor, selection, scroll/window reach, undo history — leave a tab, come back, everything's where you left it.
- **The clipboard crosses tabs.** Copy on one sheet, paste on another — the snapshot model already makes this safe; cut learns which sheet it came from.

## Decisions confirmed up front (Matthew, 2026-06-08)

1. **Sheet = file.** Each tab its own CSV + path + dirty flag; new sheets are pathless until the save prompt. Rejected: workbook-as-folder (saving writes files the user never named), manifest format (a new format other tools can't read).
2. **v1 ops: add / switch / rename / close.** The full editor set, with close warning once on unsaved changes. Per-sheet dirty tracking comes with it.
3. **Cross-sheet references deferred.** `=Sheet2!A1` is an engine part of its own (lexer `!`, parser, cross-sheet dependency graph) — and under sheet-=-file it's really a cross-*file* reference, which wants its own design pass. Tabs ship without it; formulas stay sheet-local.

## TUI architecture

### Per-sheet state: `SheetView`

A plain holder the app keeps one of per tab: `sheet`, `path | None`, `dirty`, its `SheetGrid` (created with the view), its `UndoLog`, its event unsubscribers. The app owns `views: list[SheetView]` + `active_view`; **`app.sheet` / `app.path` / `app.dirty` / `app.undo_log` become properties over the active view** — every existing handler (and most existing tests) reads through unchanged. Dirty-marking subscribes per sheet at view creation; the 3.1 payload's `sheet` field routes the event to its view (cut-disarm stays global — conservative is safe). The recalc status note shows only for the active sheet.

### Compose: `Tabs` over a `ContentSwitcher`

One `SheetGrid` per view inside a `ContentSwitcher` — grid-per-sheet keeps cursor/selection/reach per tab for free, and the per-grid engine subscriptions already detach on unmount. Background grids receiving events is a non-issue without cross-sheet refs (nothing writes a background sheet except undo/REPL — and a hidden `update_cell_at` is cheap anyway). Tab label = sheet name (dirty stays in the status bar; label-marker only if it turns out cheap). The formula bar re-mirrors the incoming grid's cursor on switch; title/status show the active view's path.

### Gestures (every one flagged for the field check — the S35 rule)

| Key | Action |
|-----|--------|
| `Ctrl+PgDn` / `Ctrl+PgUp` | next / previous sheet (Excel). CSI 5/6;5~ sequences — *should* arrive; **field check is the close gate** |
| click a tab | switch (textual `Tabs` native) |
| `Ctrl+T` | new pathless sheet, named `SheetN` (first free N) |
| `Ctrl+W` | close active tab — dirty warns once, press again; the *last* tab refuses with a hint (quit is `Ctrl+Q`) |
| double-click tab / `Ctrl+Shift+R` | rename the active sheet (modal, `SaveAsScreen` pattern; engine `rename_sheet` keeps order). Renames the *sheet*, never the file |

**Mid-edit switching is a no-op + hint** (`finish the edit first`) in v1 — Excel commits-on-switch, but that couples the editor's Done flow to tab logic; upgrade only if the field misses it. App-level bindings, non-priority, with the editing guard in the handlers.

### Open/save semantics

- CLI: `trellis a.csv b.csv …` — one tab per file via `read_csv(…, workbook=wb)` (the `workbook=` parameter, finally consumed); sheet name = file stem (collisions dedupe `stem-2`); nonexistent paths stay the new-file flow, per file. No args = one empty `Sheet1`.
- `Ctrl+S` saves the **active** sheet to its path (or prompts — `SaveAsScreen` unchanged); `saved sales.csv` names the file. Save-all deliberately absent until missed (close/quit warnings cover the leak).
- `Ctrl+Q` warns once naming the count: `2 sheets unsaved — Ctrl+Q again quits`.
- Constructor: `TrellisApp(workbook, path=…)` keeps meaning "the first sheet's path" (compat); `paths={name: path}` carries the multi-file case from `build_app`.

### Clipboard across tabs

`Clipboard` gains `sheet` (the source `Sheet`). Copy-paste cross-tab needs nothing else — offsets are sheet-agnostic and the payload is a snapshot. **Cut-paste onto another sheet**: targets write on the active sheet, source cells clear on `clip.sheet` — each in its *own* `sheet.batch()`, which is per-sheet undo-honest (Ctrl+Z on the target un-pastes; on the source, un-clears). Own-TSV bounce detection unchanged.

## Rejected / deferred

- **Cross-sheet references** — per decision 3; the engine part when it comes.
- **Workbook-as-folder / manifest persistence** — per decision 1.
- **Save-all gesture** — close/quit warnings already catch stray dirt; add only if the field asks.
- **Commit-on-switch while editing** — Excel's behavior, deferred for the editor-coupling cost; hint instead.
- **Tab reordering, colors, overflow scrolling** — textual `Tabs` scrolls on overflow already; the rest is decoration.
- **Per-tab `App.sub_title` flicker games** — status bar is the single source of file truth, as in Part 5.

## Open questions

- ~~Do `Ctrl+PgUp`/`Ctrl+PgDn` (CSI 5;5~/6;5~) and `Alt+R` arrive through Windows Terminal?~~ **RESOLVED (S36, field-verified by Matthew): switching, per-sheet undo, the lot — "all works well." One casualty: `Alt+R` never arrives — it's an AMD/NVIDIA overlay shortcut (resource usage) the GPU driver eats before the terminal sees it. Rebound to `Ctrl+Shift+R`** (keeps the R-for-rename mnemonic; double-click the tab is the mouse path, unaffected). *(Sandbox finding on the switch keys, #3: textual's ScrollView binds ctrl+pageup/pagedown for horizontal paging, so the focused grid ate them — the switch bindings are `priority=True` on the app. A field check would have caught it; Pilot did this time. The Alt+R collision is the mirror-image lesson: not every modifier key reaches the terminal at all — a driver/OS can swallow it upstream, which no test can catch.)*
- ~~Does a dirty marker in the tab *label* come cheap (textual `Tab.label` reactivity), or does it fight the widget?~~ **RESOLVED at #4 (S36): cheap** — `Tab.label` is a plain settable property; the marker updates only on the dirty *flip* (no per-keystroke churn). Tabs show `name ●` while unsaved.

## Implementation breakdown

| # | What lands | Where |
|---|------------|-------|
| 1 | This design pass | design.md Part 9 |
| 2 | `SheetView` + per-sheet dirty/undo/subs; active-view properties; save/quit semantics over views (UI still single-tab) — **DONE (S36, b934838)** | app.py + tests |
| 3 | `Tabs` + `ContentSwitcher` compose; switch gestures + click; `Ctrl+T` add; `Ctrl+W` close + warnings; bar/status/title wiring — **DONE (S36, cd881b0)** | app.py + tests |
| 4 | Rename (modal + double-click + `Ctrl+Shift+R`); stem naming + dedupe; CLI multi-file `build_app`; label-dirty question — **DONE (S36, e1362ed; rebound off Alt+R field-found, see below)** | app.py + tests |
| 5 | Clipboard `sheet` field; cross-tab paste + cut source-clear; disarm stays global — **DONE (S36, 7613d8b)** | app.py + tests |
| 6 | Docs: READMEs (key table + buffers-model note), design rows, worklog — **DONE (S36); field check pending** | docs |

Rows #2–#5 each land green before the next starts — same rhythm as Part 6.

## References

- `core/workbook.py` — ordered sheets, `sheet:add`/`remove`/`rename` events; the docstring that anticipated per-sheet attachment.
- `io/csv.py` `read_csv(workbook=…)` — the multi-file loading seam, built in Part 3, consumed now.
- Part 7 — per-sheet `UndoLog` attachment (`attach(sheet)` per view; `attach_workbook` is the REPL's spelling of the same).
- Part 6 — `Clipboard` snapshot model (why cross-tab paste is safe), `_mark_dirty` disarm.
- Textual: `Tabs`, `ContentSwitcher`, `Tab.label`.

---

# Part 10: Vim keymap — the TUI's first extension point (keymap plugins)

## Purpose

A vim keymap for the TUI — and, because of decision 3, the seam that makes it possible: **the
TUI's first extension point.** Until now the TUI hardcodes its keys (Part 5, deliberately). This
part introduces a *keymap* abstraction so a plugin can supply a whole alternative key language.

The shape is set by decision 6: **there is one key path, and every keymap goes through it —
including the default.** The current Excel bindings are ported to a built-in `ExcelKeymap`; vim
ships as the external `trellis-vim` package. So the contract is validated by **two consumers
from day one** — an extension point with a single consumer is just that consumer's internals
wearing a coat. Three reference plugins now bracket three extension styles: mathpack (entry-point
globals), trellis-undo (events + meta), and the keymaps (a frontend strategy hook).

Engine additions: **none** — all in the TUI layer. The core design test doesn't apply to a frontend.

## Decisions confirmed up front (Matthew, 2026-06-09/10)

1. **Opt-in via `--vim`.** Excel keys stay the boot default; `--vim` swaps the *active keymap* from
   `excel` to `vim` (see decision 6). A config knob can follow.
2. **Core subset for v1.** Modes (Normal/Insert/Visual/Command), `hjkl` + counts, `gg`/`G`, `w`/`b`
   as data-block jumps, `0`/`$`/`^`, operators `d`/`y`/`c`/`x`/`p`/`P` with `dd`/`yy`, insert-entry
   `i`/`a`/`I`/`A`, `u`/`Ctrl+r`, `:w`/`:q`/`:wq`/`:x`/`:q!`/`:{n}`.
3. **Keymap-plugin API now.** Vim is a keymap object behind a real extension point, not a hardcoded mode.
4. **In vim, `Ctrl+D` = half-page-down, `Ctrl+R` = redo.** The Part 8 fill keys are the *Excel
   keymap's* binding; the vim keymap rebinds them. Fill stays reachable in vim via Visual + `p`.
5. **Vim ships as a separate `packages/trellis-vim/` package**, registered via an entry point —
   proving the hook from *outside*, like mathpack.
6. **One path — Excel is a keymap too.** The default bindings port to a built-in `ExcelKeymap` (the
   default active keymap); every key in every config flows through the one `handle() → Action`
   delegate. **No hardcoded fall-through path.** This reverses an earlier additive-hook lean: a
   single consumer wouldn't prove the contract general, and the additive design's fall-through
   (vim's unhandled keys dropping into Excel bindings) was a precedence-bug waiting to happen. One
   path = the active keymap is the *sole* authority; switching fully commits. **`ExcelKeymap`
   *should* reproduce today's behavior** — deviation is allowed only where textual's own global key
   handling intercepts or blocks a key (accommodate the framework, don't fight it). The 175 tests
   are the regression net for the port.
7. **Chrome boundary: sheet/tab/quit stay app-keys.** Window-level keys — `Ctrl+PgUp/PgDn`,
   `Ctrl+T`/`Ctrl+W`, `Ctrl+Q` — remain app-level bindings, but emit the same `Sheet`/`Quit`
   Actions through the shared executor, so a keymap can also trigger them (vim `:w`/`:q`, a future
   `gt`). Keymaps own grid/cell/mode keys + the command-line verbs; the app owns the window chrome.
8. **Keymaps see our own textual-free `KeyPress`, not textual's `Key`.** A ~20-line adapter wraps
   textual's already-parsed `Key` at the boundary into `KeyPress(.key, .char, .ctrl/.alt/.shift)`;
   keymap packages import only our contract (the `render.py`/core decoupling, one layer out — the
   keymap drives the TUI from outside the way the TUI drives the engine from outside). Key-name
   strings mirror textual's for now; an own key-name vocabulary + translation table is deferred
   until a non-textual frontend ever exists (it may never — simplicity over clever solvers). textual
   does the OS/terminal parsing under the adapter either way, so this is decoupling at ~20 lines,
   not OS-key work.

## The insight that makes this cheap: the TUI is already half-modal

Vim's bargain is modes — commands in Normal, text in Insert. The TUI already runs this split,
unlabeled, so the work is mostly *naming and redirecting* existing machinery:

| Vim mode | Already is… | Reused as-is |
|----------|-------------|--------------|
| **Insert** | the `FormulaBar` `CellEditor`; `commit_text` is the one write path | editor entry (`EditRequest`), `Esc` cancel |
| **Visual** | the selection model — `(anchor, cursor)`, `selection_range`, `SelectionChanged` | extend/collapse, the one-batch `ClearRequest` |
| **Normal** | "grid focused, not editing" — `app._editing()` is the seam | the keymap delegate plugs in here |

Operators land on existing intents: `y`→`CopyRequest`, `d`/`x`→`Cut`/`ClearRequest`,
`p`→`PasteRequest`, `u`/`Ctrl+r`→the undo requests. The grid already posts every one.

## The extension contract (the load-bearing new public surface — treat like Part 3)

Three pieces. The discipline mirrors the engine's: **the keymap never writes** — it reads context
and returns an Action; the TUI executes it (the frontend echo of "the grid never writes the
engine"). The contract is **textual-free** (decision 8) — keymap packages don't import textual.

### 1. `Action` — the closed vocabulary the TUI executes
- `Move(dr, dc, extend=False)` / `MoveTo(row, col, extend=False)` — cursor moves + selection growth
  (`hjkl`, `gg`/`G`, `0`/`$`, data-block `w`/`b`, page motions; the keymap computes the target).
- `BeginEdit(caret="start"|"end", seed=None)` — enter Insert; maps to `EditRequest`("revise") + a
  caret-placement addition. `seed` carries Excel's type-to-edit (printable → replace).
- `EnterMode(name)` — Normal/Visual/Command (drives the mode indicator).
- `Operate(op, rect=None)`, `op ∈ {copy, cut, clear, paste, change}` — `rect` defaults to the
  selection; `change` = clear then `BeginEdit`. Maps to the Copy/Cut/Clear/Paste requests.
- **`Fill(axis, rect=None)`** — *added by modeling Excel* (Ctrl+D/R; vim doesn't need it, so a
  vim-only contract would have shipped this gap). The two-consumer payoff, concretely.
- `Undo()` / `Redo()`, `Save(prompt=False)` / `Quit(force=False)`, `Sheet("next"|"prev")` — map to
  the existing actions. `Hint(msg)` — a status note; returning `None` = consumed-pending or ignored.

### 2. `KeyContext` — the read-only state a keymap sees
`mode`, `cursor=(row,col)`, `selection: Rect|None`, `used_range: Rect|None`, `cell(row,col)->Cell`
(read-only, for data-block motions), `viewport_rows`/`viewport_cols` (paging), `editing: bool`.
Enough to resolve every core-subset motion and operator; **nothing writable.**

### 3. `Keymap` — what a plugin implements
```
class Keymap(Protocol):
    name: str
    def initial_mode(self) -> str: ...                       # "normal" for vim, "default" for excel
    def handle(self, key: KeyPress, ctx: KeyContext) -> Action | None: ...
    def key_table(self) -> list[KeyRow]: ...                 # optional, for help
```
One **stateful** instance per session (it holds the pending count/operator — vim parsing is more
than a static table, which is why it's `handle(...)`, not a dict). `KeyPress` is our thin
textual-free wrapper (decision 8): `.key` (str), `.char` (str|None), `.ctrl`/`.alt`/`.shift`.

### Discovery + selection
trellis-tui ships the built-in **`ExcelKeymap`** as the default active keymap. Entry-point group
**`trellis_tui.keymaps`** registers *additional* keymaps (`name = "module:factory"`,
`factory() -> Keymap`; mathpack's pattern). `--keymap NAME` selects among the built-in + registered;
default = `excel`; `--vim` = sugar for `--keymap vim`; unknown name errors with the list.

### The one path + the chrome boundary
Every key the grid sees goes to `active_keymap.handle(key, ctx)`; the returned Action runs through a
shared app-side **executor**. There is no second, non-delegate path. Two scopes share that executor:
the **keymap** owns grid/cell/mode keys + the command-line verbs (sole authority), and **app-chrome**
owns the window keys (decision 7) — both emit the same Actions. **Insert mode bypasses the keymap** —
the editor owns its keys as today; only `Esc` routes back to leave Insert. The textual key-routing
integration (priority vs `on_key`, the Part 9 ScrollView key-theft lesson) is the build-phase sharp edge.

## Why this is house-consistent
Two consumers validate the contract from day one (the default dogfoods the hook — "library first");
entry-point discovery of a named registerable (mathpack); read-only context + return-don't-write
(the grid-never-writes-engine discipline); textual-free contract (render.py); a locked public
vocabulary with contract tests (Part 3's payload lock); and the default ported behind a facade with
the suite green (Part 9's active-view move).

## Rejected / deferred
- **Additive hook (default stays hardcoded, vim the only keymap)** — rejected at decision 6: one
  consumer doesn't prove the contract, and the fall-through is a precedence-bug surface.
- **Default-on vim / hardcoded vim mode** — per decisions 1, 3.
- **`o`/`O`** — need `Sheet.insert_row`, which doesn't exist and would be a *core* part by the design
  test; deferred (ship `i`/`a`/`I`/`A`).
- **Search, `f`/`t`, marks, registers, macros, `.`-repeat** — per decision 2; later follow-ups.
- **Own key-name vocabulary + translation table** — per decision 8; pragmatic textual-name mirroring
  now, harden only if a non-textual frontend appears.

## Open questions (settled at build / field, not contract surface)
- **`change`/`c` over multi-cell**, and **counts × motions/operators** (`3dd`, `d3j`) —
  vim-keymap-internal parser rules; decided when we build the vim package (row 3), not contract-level.
- **Field check (S35 rule):** `Esc` timing, the `:` modal, printable-swallowing vs bracketed-paste —
  through Windows Terminal, at row 4.

## What the vim keymap maps (the reference plugin's key table)
- **Motions:** `h`/`j`/`k`/`l`; `w`/`b` = next/prev contiguous-data block (Excel `Ctrl+→`/`←`);
  `0`/`$` = first/last non-empty in the row, `^`=`0`; `gg`/`G` = top/bottom of the column's data;
  `Ctrl+D`/`Ctrl+U` = half-page; counts prefix any (`3j`).
- **Operators:** `d`/`x` clear, `y` copy, `p`/`P` paste, `c` change; doubled = row-wise (`dd`, `yy`).
- **Insert:** `i`/`I` (caret start), `a`/`A` (caret end). **Visual:** `v`/`V`/`Ctrl+v` + motion +
  operator. **Command:** `:w`/`:q`/`:wq`/`:x`/`:q!`/`:{n}`. **Undo:** `u`/`Ctrl+r`.

## Implementation breakdown (staged across sessions)
| # | What lands | Where |
|---|------------|-------|
| 1 | This design pass + the contract — **DONE (S37)** | design.md Part 10 (+ docs/keymap-plugin.md at row 4) |
| 2 | Keymap layer in trellis-tui: the delegate + Action executor (incl. `Fill`) + `KeyContext` + mode state/`-- MODE --` indicator + entry-point discovery + `--keymap`/`--vim`. **Port the current bindings into the built-in `ExcelKeymap` (default active); 175 tests are the net.** Possibly two sessions if the port is gnarly. — **DONE (S38**, one session: the port came in clean, 175 untouched + 20 contract tests**)** | trellis-tui |
| 3 | `packages/trellis-vim/`: the vim `Keymap` — modes, motions, operators, command-line — via the entry point. + hermetic tests — **DONE (S38**, same session as row 2: 26 hermetic + 9 Pilot tests; install-level discovery proved in an off-mount venv**)** | new package |
| 4 | Docs (both READMEs, the contract doc, design rows) + worklog; then **field-verify** (Windows Terminal) — **DONE (S39**, 2026-06-12: docs/keymap-plugin.md written; field check PASSED — see addendum**)** | docs + Matthew |

Rows land green before the next starts — the Part 6/9 rhythm.

## Build addendum (S38, row 2) — contract refinements found by building
- **`Select(rect)` joined the Action vocabulary.** Select-all is not expressible as a single
  anchored `Move`/`MoveTo` (the anchor must land on the rect's top-left regardless of the
  cursor), and vim's `V`/`Ctrl+v` Visual entries will want exactly this. Same discovery class
  as `Fill`: the vocabulary gap shows up only when a real consumer needs the verb.
- **`None` from `handle()` sharpened to "no action here — the key runs on"** (framework paging,
  focus, and the app's chrome bindings; DECIDED #7's boundary in practice). The design's
  "consumed-pending or ignored" reading survives unchanged for the keys a keymap actually
  parses (vim's pending counts are printables nothing else binds); a keymap that must *deaden*
  a framework-bound key returns `Hint("")` — the explicit consume. This is what makes chrome
  keys work under ANY keymap without a chrome-keys list leaking into the grid.
- **Rects resolve at execution time.** `Operate`/`Fill` default `rect=None` = "the live
  selection, else the cursor", resolved in the executor — queued Actions execute in order, so
  a burst of `Move(extend=True)` + `Operate("copy")` can never copy a stale rectangle. The
  handle-time `KeyContext` is for computing motions, not pre-resolving targets.
- **Mode indicator semantics:** the status bar renders `-- MODE --` for any mode except the
  keymap's `initial_mode()` (resting renders nothing). `BeginEdit` execution sets `insert`,
  editor close restores the resting mode — under Excel you now get an honest `-- INSERT --`
  while editing (Excel itself flags edit mode in its status bar; deviation embraced).
  `StatusBar.state` stays a 3-tuple (load-bearing for tests); the mode mirrors at
  `StatusBar.mode_shown`.
- **One casualty:** the Footer's `F2 Edit` / `Delete Clear` hints — they were Binding
  metadata, and the grid no longer has key Bindings. `Keymap.key_table()` is the help surface
  now (a help screen is a natural row-4+ follow-up).
- The textual integration came in at the predicted seam: `on_key` runs before binding
  processing, so an Action's `stop()`+`prevent_default()` suppresses DataTable's own cursor
  bindings — arrows route through `Move` like everything else. Pilot's per-key idle wait
  (verified in `_press_keys`) keeps the request-message hop invisible to tests.

## Build addendum (S38, row 3) — what the vim package decided and discovered
- **`Chain(actions)` joined the vocabulary** (the third build-found verb, after `Fill` and
  `Select`): vim's `:wq` is save-then-quit and vim's delete is yank-then-clear, and `handle()`
  returns ONE action. The executor recurses member-by-member, so execution-time rect
  resolution holds inside a chain.
- **The vim-internal decisions** (design said "settled at build"): delete IS yank (`x`/`dd`/
  visual `d` = `Chain((copy, clear))` — `dd` `p` moves a row; the design sketch's "d/x clear"
  lost to vim fingers); `c` doesn't yank; `p`=`P` (the grid pastes AT the cursor); operators
  take doubles or the Visual selection — `dw`/`d3j` composition stays out of v1; counts ×
  motions work everywhere (`3j`, `5G`, `2w`, `3x`, `3dd`); `Ctrl+C` ≈ Esc (it must never fall
  through to the app's quit binding mid-thought); Enter=down, Backspace=left (vim), the
  revise-edit lives on `i`/`a`.
- **Visual operators park the cursor at the region's start** (vim's post-yank/delete cursor)
  — a trailing `MoveTo` baked from the handle-time selection. Found by the integration suite:
  `vly` then `p` pasted at the selection's END cell offset; vim fingers expect anchor-relative.
- **Visual-line tracks its own moving end** (`_vline`/`_vcur`): the grid's `Select` always
  parks the real cursor at the rect's bottom-right, so extending UPWARD recomputed from the
  cursor would stall against the anchor row. The keymap is stateful for exactly this class of
  reason — the contract's `handle()`-not-a-dict call, vindicated.
- **The `:` command line lives entirely inside the contract**: `EnterMode("command")` + the
  buffer echoed as `Hint(":w…")` in the status bar; Enter parses to `Chain((EnterMode
  ("normal"), <verbs>))`; unsupported keys echo back (modal honesty — arrows don't move the
  grid mid-command). No new widget, no app changes — the v1 `:` modal costs zero chrome.
- The command-line UX (echo-in-status vs a real `:` input line) is a candidate refinement for
  the row-4 field check; the contract supports either without changing keymap code.

## References
- The "two consumers before you trust an abstraction" rule — why Excel-as-a-keymap, not additive.
- Part 3 — lock-the-contract + contract tests (the model for the Action/KeyContext/Keymap surface).
- Part 5 — hardcode-first; the formula-bar editing model (= Insert). Part 6 — the selection model
  (= Visual) and the request-message pattern (= the Action targets).
- Part 7 — one-batch-one-step undo (`u`/`Ctrl+r`). Part 8 — the `Ctrl+D`/`Ctrl+R` fill keys.
- mathpack — entry-point discovery; `render.py` — the textual-free precedent; Part 9 — facade-keeps-suite-green.
- `app._editing()`, `grid.py` BINDINGS — the Normal/Insert seam and the keys being ported.
## Field check (S39, 2026-06-12) — PART 10 CLOSES VERIFIED
Matthew, Windows Terminal, `trellis --vim demo.csv`. All three S35-rule items pass:
- **Esc timing:** `i` -> `-- INSERT --`, Esc back to normal instantly — no terminal Esc-delay.
  Ctrl+C while editing behaves as Esc (never falls through to quit).
- **The `:` echo UX:** keystroke echo + backspace feel like a command line; `:q` dirty-warns,
  `:q!` quits, unsupported commands echo (modal honesty held in the field).
- **Printable-swallowing:** normal-mode letters are commands, unbound letters inert — no
  type-to-edit leakage.
One install finding (not a code bug): a venv built before row 3 doesn't see the new package —
the helpful-failure path (`unknown keymap 'vim' (available: excel)`) fired exactly as designed,
fixed with `pip install -e packages/trellis-vim`. Noted in docs/keymap-plugin.md.
PART 10 COMPLETE.


## Part 11 — CSV-path I/O polish
Status: **opened 2026-06-17 Session 40.** Post-Part-10 milestone: harden the file path the
target user actually lives on (CSV, by design — [[trellis-file-io-csv-only]]). Candidates came
from auditing `io/csv.py` against real Excel-on-Windows behaviour; none were previously in scope.
Picked order (Matthew, S40): atomic save first, then read robustness, then graceful open errors.

| # | Item | Status |
|---|------|--------|
| 1 | `write_csv` atomic (temp + `os.replace`) | DONE 2026-06-17 (S40) |
| 2 | Read robustness — UTF-8 BOM + delimiter sniff | DONE 2026-06-21 (S42) |
| 3 | Graceful open errors in the TUI CLI path | DONE 2026-06-21 (S42) |

### Row 1 — atomic save (DONE 2026-06-17, S40)
**Problem.** `write_csv` opened the destination directly with `"w"`: a save interrupted partway
(disk full, crash, a flaky mount — the very failure the repo's own write-protocol guards against)
truncated the user's real file. A spreadsheet editor must never lose the old file to a bad new one.

**Shape.** Stream into a temp file in the *same directory* as the target (so the replace is a
same-filesystem rename, not a cross-device copy), then `os.replace(tmp, target)` — atomic on POSIX
and Windows. On any exception the temp is unlinked and the error re-raised; the original is never
touched. The empty-sheet branch shares the path (empty file, still atomic). Temp names are
`.<target>.*.tmp` — hidden, and matching the repo's existing `*.tmp` ignore.

**Permissions.** `mkstemp` makes its file 0600, which would leak through the replace.
`_apply_target_mode` restores what `open(path, "w")` would have produced: copy an existing file's
mode on overwrite, else `0o666 & ~umask` for a new file. Best-effort (OSError swallowed), POSIX-
shaped, a no-op on Windows — a permission quirk must never defeat an otherwise-good save.

**Tests (+5; core 816 -> 821).** No temp litter after success; a mid-serialize failure
(monkeypatched `_stringify`) leaves the original intact, leaves no litter, and propagates; empty-
sheet write stays atomic; a short overwrite truncates a longer file's stale tail; (POSIX) mode
0640 preserved across overwrite. No API or happy-path change — pure durability.

### Row 2 — read robustness (DONE 2026-06-21, S42)
**Problem.** Two ways a real Excel-on-Windows export mis-loaded *silently*. (1) Excel writes a
UTF-8 BOM; `read_csv` decoded as plain `utf-8` by default, so the first cell arrived as
`"\ufeffname"` — a header that never matches, a join key that never joins, no error. (2) Outside
the US, Excel exports semicolon-delimited; the `"excel"` dialect is comma-only, so the whole file
loaded as a single fat column. Both are the target user's everyday file ([[trellis-file-io-csv-only]]).

**Shape.** (1) Default `encoding` flips `utf-8` → `utf-8-sig`, which reads plain UTF-8 *and* strips a
leading BOM if present — strictly more lenient, no happy-path change. An explicit `encoding="utf-8"`
is the escape hatch back to strict, BOM-preserving decoding. (2) New `delimiter: str | None = None`
param: when `None`, sniff from a bounded sample (8 KB) of the file's first populated line; an explicit
character forces one and skips the sniff. The sniff stays on the engine's `dialect` for quoting and
just overrides the delimiter via `csv.reader(..., delimiter=…)`.

**The sniffer.** Deliberately *not* `csv.Sniffer` (opaque, raises on single-column) — a deterministic,
explainable rule per [[simplicity-over-clever-solvers]]: `_count_unquoted` counts each candidate
(`, ; \t |`) outside double-quoted spans; `_sniff_delimiter` walks to the first line with any candidate
and returns the most frequent, ties broken by candidate order (comma first). A file with no delimiter
anywhere — a genuine single-column CSV — falls back to comma, preserving old behaviour. Quote-aware
counting is what makes the European case work: `"1,5";"2,5"` (comma as decimal *inside* fields)
correctly sniffs `;`.

**Tests (+10; core 870 → 880).** BOM stripped by default / kept under explicit `utf-8`; plain no-BOM
still reads; semicolon/tab/pipe each sniffed; single-column → comma fallback; explicit `delimiter=`
overrides; commas inside quotes don't fool the sniff; BOM + semicolon together (the full European
export). Existing 63 CSV tests unchanged — the new default is a pure superset.

### Row 3 — graceful open errors in the TUI CLI (DONE 2026-06-21, S42)
**Problem.** `build_app`'s per-file load called `read_csv` unguarded after an `exists()` check. A path
that exists but can't be read — no permission, a *directory*, undecodable bytes, or one that vanished
between the check and the open (TOCTOU) — dumped a raw traceback and killed the launch. A CLI should
explain itself.

**Shape.** Wrap the `read_csv` call in `try/except (OSError, UnicodeDecodeError)`; on failure print one
clean line — `trellis: cannot read <path>: <reason>` — to stderr and `return None`, aborting the
launch. Same exit shape as the existing unknown-`--keymap` branch. Aborting (vs. skipping the bad
file) is the predictable choice: you asked for these files, one is unreadable, you're told exactly why
and nothing half-loads. The discarded workbook may hold a half-added empty sheet — harmless, it's
thrown away. `OSError` covers permission/`IsADirectoryError`/vanished; `UnicodeDecodeError` (not an
`OSError`) covers undecodable bytes that survive even `utf-8-sig`.

**Tests (+2; TUI test_chrome 17 → 19).** A directory path and an undecodable-bytes file each return
`None` and print `cannot read` (+ the filename) to stderr.

**Status — Part 11 COMPLETE (S42).** All three rows landed: atomic save (S40), read robustness
(BOM-tolerant default + deterministic delimiter sniff), and graceful CLI open errors. The CSV path the
target user lives on now survives an interrupted save, an Excel BOM, a European semicolon export, and
an unreadable file — none of which it handled when Part 11 opened. Core 821 → 880 across the part
(rows 2's +10 here; row 1's +5 in S40). One adjacent thing still *not* done by design: non-UTF-8
encodings (latin-1, cp1252) still need an explicit `encoding=` — auto-detecting charset is a bigger,
guessier problem deliberately left out of scope.


## trellis-keymap — the keymap contract becomes its own package (2026-06-17, S40)
Status: **DONE.** Extracted the textual-free keymap contract out of `trellis-tui` into a new
zero-dependency package, so a second frontend (a planned GUI — Matthew is eyeing DearPyGui) can
host the same Excel/vim key languages without dragging in Textual.

**Why now.** The contract was textual-free by design (Part 10 decision 8) but *housed* inside
`trellis-tui`. A new frontend would otherwise depend on the whole TUI (pulling Textual) or
duplicate the contract. Extracting it makes the keymap layer what it always wanted to be:
frontend-neutral — the same payoff shape as `render.py` being textual-free.

**What moved.** `trellis_tui/keymap.py` (422 lines, stdlib-only — `dataclasses`, `typing`,
`importlib.metadata`) → `packages/trellis-keymap/src/trellis_keymap/__init__.py`, unchanged
except the entry-point group, renamed `trellis_tui.keymaps` → **`trellis_keymap.keymaps`**
(DECIDED with Matthew, S40): the discovery group belongs to the package that owns the contract,
so any frontend reads a neutral group, not a `trellis_tui.*` one it doesn't own.

**Consumers repointed.**
- `trellis-vim` now imports `trellis_keymap` and depends on `trellis-keymap` ALONE (was
  `trellis-tui`). The vim language is now frontend-independent — it can drive a GUI unchanged.
  Its entry point moved to the new group.
- `trellis-tui` gained a `trellis-keymap` dependency; `trellis_tui/keymap.py` became a 19-line
  compat shim (`from trellis_keymap import *`) so `app.py`/`grid.py` (`from . import keymap as
  km`) stay byte-for-byte unchanged — minimal churn, write-protocol-safe. A later TUI pass can
  repoint those two imports and drop the shim.

**Verification.** trellis-keymap hermetic contract tests (19, lifted from the TUI suite) + vim
hermetic (26) + vim Pilot integration (9) + the full TUI suite (196, through the shim) + core
(821) all green. Discovery proved in an off-mount editable venv: `available_keymaps()` = `excel`
(built-in) + `vim` (entry point) under the new group; `build_app(['--vim'])` wires the discovered
`VimKeymap`.

**The monorepo now ships four companion packages**: trellis-keymap (the contract), trellis-mathpack
(engine plugin), trellis-undo (engine attachment), and trellis-tui (frontend) + trellis-vim
(a keymap on the contract). Three reference extension styles, plus the shared keymap contract the
second frontend will build on.

# Part 12: Cross-sheet references (workbook-local) — names out front, ids underneath

## Purpose

`=Sheet2!A1`. The feature Part 9 decision 3 deferred ("wants its own design pass") — this is that pass. Scope is **workbook-local**: a reference names another *sheet* (tab) in the current in-memory `Workbook`/session. Cross-*file* `[costs.csv]Sheet1!A1` stays out (decision 1) — under sheet-=-file it's a different, bigger feature with its own identity and resolution story.

This is the first deep reach into the engine's formula core since Part 6's `$`/`shift_formula` — most parts since have been TUI-side. It earns it: the recalc graph was made workbook-level from day one *for exactly this* (Part 2: "make it workbook-level from the start"), and the key was deliberately `(sheet_name, row, col)` to "keep the algorithms identical when we add cross-sheet support" (recalc.py architecture note). That note is half-right — the graph spans sheets already, but keying on the *mutable name* is a latent bug (below). This part finishes the job and fixes the key.

## The bug this also closes (found S41, 2026-06-20)

Renaming a sheet silently desyncs recalc *today*, with no cross-sheet refs in play. `RecalcEngine` subscribes to `sheet:add`/`sheet:remove` but **not `sheet:rename`** (recalc.py:157-162), and every graph key is built from the live `sheet.name` (recalc.py:223, :265). So `B1=A1` registered as `(old, B1) → {(old, A1)}` keeps those keys after a rename, but a post-rename edit to A1 fires keyed `(new, A1)` — whose `_dependents` set is empty → **B1 never recomputes** until it's re-typed. Stale `(old, …)` entries also leak across `_asts`/`_dependents`/`_dependencies`/`_sheet_subs`. The existing rename test only asserts the status line, so it never caught this. Keying on a stable id (decision 2) retires the whole bug class — no `sheet:rename` graph-rekey band-aid needed.

## Decisions confirmed up front (Matthew, 2026-06-20)

1. **Workbook-local only.** Ship `=Sheet2!A1`, resolving within the current session's sheets. `[Book]Sheet!A1` cross-file refs are out, and we do **not** pre-reserve `[` in the grammar — it's an illegal character today, so adding it later is non-breaking (YAGNI; minimalist core).
2. **Stable `sheet_id`, name display-only.** The dependency graph keys on a stable per-sheet id; the name is the public *string form* only. Same boundary discipline as A1↔`(row,col)`: the name lives in formula text and CSV, the id lives in the graph and resolution. Rename becomes a display/serialization concern, never a correctness one.
3. **Excel-faithful syntax `Sheet1!A1`.** The trailing `!` separates sheet from cell — `=Sheet1!A1`, `=SUM(Sheet1!A1:A10)`, `='Q1 Budget'!A1`. One symbol both announces and separates, the learning curve is zero, and a paste from Excel/Sheets/LibreOffice just works. A leading-`!` sigil was weighed and rejected (see below).

## The boundary model (the spine)

Mirror the address convention. A sheet has two faces:

- **Name** — the public string form. Appears in formula text (`=Sheet2!A1`) and saved CSVs. Mutable, workbook-unique (already enforced: `add_sheet`/`add`/`rename_sheet` all raise on collision).
- **`sheet_id`** — internal identity. A monotonic int assigned in `Sheet.__init__` from a module counter, so identity exists before a sheet joins a workbook (REPL-first). **Session-only — never serialized** (CSV is nameful text; on load, names re-resolve to fresh ids).

Conversion happens at one seam, exactly like `to_a1`/`parse`: the parser stays pure and name-based; the recalc engine resolves name→id once it has the workbook.

## Pipeline

- **Lexer** (`formula/lexer.py`) — add a `!` token (new `TokenKind.BANG`) and quoted sheet-names `'My Data'` (`''` escapes a literal quote, Excel-style). Bare names still arrive as `IDENT`.
- **Parser** (`formula/parser.py`) — in `_parse_ident`, an `IDENT` (or quoted-name) **followed by `!`** is a sheet qualifier: consume the `!`, parse the trailing cell/range, attach the sheet name. For a range the sheet binds the whole `Sheet2!A1:B5` (the end corner inherits it; a sheet on the right-hand corner is a parse error).
- **AST** (`formula/ast.py`) — `CellRef` gains `sheet: str | None = None` (name as written; `None` = the holding sheet). The trailing default keeps every existing positional `CellRef(row, col, …)` construction valid. `RangeRef` carries the sheet on its corners (`start.sheet == end.sheet` by construction).
- **Resolution + graph** (`formula/recalc.py`) — `extract_deps(ast, holding_sheet, workbook)` maps each ref's sheet name → `sheet_id` (`None` → the holding sheet's id), emitting `CellKey = (sheet_id, row, col)`. `CellKey`'s first element becomes the id throughout; `_on_cell_change`/`_on_sheet_remove`/`_subscribe_sheet` key on `sheet.id` (or the sheet object) instead of `sheet.name`. The engine already subscribes to every sheet's `cell:change`, so cross-sheet propagation works the moment the keys line up.
- **Evaluator** (`formula/evaluator.py`) — `Context` gains `workbook: Workbook | None`. `_eval_cellref`/`_eval_rangeref` resolve `node.sheet` (name) via the workbook when set, else use `ctx.sheet`. A missing sheet → `REF`.

## Error model (constants already exist)

- Unknown sheet name at resolve/eval → `NAME` (an unknown identifier).
- Reference into a sheet removed while referenced → `NAME` (**decision S41**: uniform with an unknown sheet — distinguishing removed-vs-never-existed would need per-ref provenance, not worth it; Excel uses `#REF!`). Non-destructive: the formula text keeps `Sheet2!A1` and recovers if a sheet of that name returns and the cell is re-entered.

## Rename & remove

- **Rename** — the graph is id-keyed, so dependencies need no rekey. The engine subscribes to `sheet:rename` and, for the bounded set of referrers (the reverse set in `_dependents`), rewrites both the formula *text* and the stored *AST* `OldName!…` → `NewName!…`. Both matter: the text so a saved CSV reloads, the AST because the evaluator resolves the sheet *by name* — a stale AST name would resolve to `NAME` on the next cross-sheet recompute, not only on reload. Done quietly (a rename moves no data, so values don't recompute). No graph rekey — the whole point of the id.
- **Remove** — `sheet:remove` re-registers the removed sheet's cross-sheet dependents: a re-parse drops the dead dep and the broken ref resolves to `NAME`, cascading to their dependents — instead of silently keeping a stale value.

## Rejected / deferred

- **Cross-file `[Book]Sheet!A1`** — per decision 1; wants its own identity + multi-file resolution + load-order story.
- **Leading-`!` sigil (`!Sheet1.A1` / `!Sheet1!A1`)** — weighed (Matthew, 2026-06-20): a leading sigil makes cross-sheet refs scannable like `$`/`#` and tells the parser "sheet ref incoming" up front. Rejected: it still needs a *second* separator before the cell — two symbols where Excel's trailing `!` does both jobs — a `.` separator collides visually with decimals, and nothing copied from Excel/Sheets would parse. Excel-faithful wins on familiarity + paste-compat (decision 3).
- **Reserving `[` in the grammar now** — per decision 1; non-breaking to add later.
- **uuid sheet ids** — heavier than needed; ids are session-scoped, a monotonic int suffices and reads better in debug output.
- **Storing the resolved id in the AST (render the name on demand)** — would make rename truly zero-work, but forces parse-time resolution (a workbook-aware parser) and can't represent a ref to an absent sheet. Keeping the *name* in the AST holds the pure-parser convention and the name=string-form analogy; the rename text-sweep is the modest, local cost. Revisit only if the sweep proves annoying.
- **Excel's destructive `#REF!` rewrite on sheet delete** — we keep refs non-destructive (the name survives, recovers if the sheet returns); simpler and less surprising for a file-backed editor.
- **Re-resolve-on-`sheet:add` for late-loaded names** — for workbook-local + CLI-load-all, siblings exist at registration; an unresolved name recovers on cell re-entry. Auto re-resolve when a matching sheet appears is a cheap later add if the field misses it.

## Open questions

- **`sheet_id` home** — module counter in `core/sheet.py` (leaning) vs. workbook-assigned on add. Counter wins for REPL identity-before-attachment; confirm at build.
- **Rename text-rewrite write path** — re-render through the normal formula-set (re-registers deps; may emit `cell:change`) vs. a quiet text-only update. Lean quiet — a rename isn't a value change.
- **`Context.workbook` vs. a resolver callback** — passing the whole `Workbook` is simplest and the evaluator only needs name→sheet lookup; a narrow `resolve_sheet(name)` callable is the tighter seam if we want to keep the evaluator workbook-agnostic.
- **Supersession of Part 2** — the recalc section's `(sheet_name, …)` key description is superseded here; Part 2 stays as written (historical), this part is the authority.

## Implementation breakdown (staged; each lands green before the next)

| # | What lands | Where |
|---|------------|-------|
| 1 | This design pass | design.md Part 12 |
| 2 | **DONE (S41, uncommitted)** — `Sheet.id` (module counter; stable + rename-invariant) + a standalone rename-desync test (verified red on the old name-keyed graph, green after) + the `sheet_id` graph migration. Engine gained a `{sheet_id: sheet}` map for write-back (`Workbook` is name-keyed). Core 821→825 | `core/sheet.py`, `formula/recalc.py` + tests |
| 3 | **DONE (S41, uncommitted)** — `TokenKind.BANG`+`QUOTED_NAME` (`!`; `'..'` with `''` escape) + parser sheet-qualifier (`_parse_ident` checks `!` first; factored `_parse_cell_or_range`/`_parse_quoted_sheet`) + `CellRef.sheet`. Parse-only — resolves to holding sheet until row 4. Core 825→843 | `formula/lexer.py`, `parser.py`, `ast.py` + tests |
| 4 | **DONE (S41, uncommitted)** — `extract_deps(ast, sheet_id, resolve)` (unknown sheet → no dep); engine `_resolve_sheet_id`; `Context.workbook` + evaluator `_resolve_sheet` cross-sheet read; unknown sheet → `NAME`. (Removed-sheet→`REF` re-eval moved to row 5.) Core 843→855 | `formula/recalc.py`, `evaluator.py` + tests |
| 5 | **DONE (S41, uncommitted)** — `sheet:rename` rewrites referrers' text **and** AST in place (`rename_sheet_in_formula` token-splice in `shift.py`; quiet/value-preserving) so cross-sheet refs survive a target rename; `sheet:remove` re-registers referrers → broken ref → `NAME` (cascades). Core 855→870 | `formula/recalc.py`, `shift.py` + tests |
| 6 | **DONE (S41, uncommitted)** — cross-sheet syntax note in README (library quick taste) + TUI README (sheet-tabs bullet updated, dropped from "not yet"); design rows + worklog. **Part 12 COMPLETE** | docs |

Row 2 is deliberately first and self-contained: it closes the live rename bug and proves the id model with a test *before* any new syntax exists.

**Status — Part 12 COMPLETE (S41).** All six rows landed; the core suite grew 821 → 870 across the part. `Sheet2!A1` / `'My Data'!A1` references resolve, recalc across sheets, survive a target rename (text + AST rewritten), and degrade to `#NAME?` on a missing/removed sheet — all on the stable `sheet_id` graph, which also retired the latent intra-sheet rename-desync bug found in row 2. One follow-up stayed flagged through S41 and is now **resolved (S42)** — see below.

### Cross-sheet follow-up — `shift_formula` made `!`-aware (DONE 2026-06-21, S42)
**Problem.** `shift_formula` (the copy/paste/fill rewriter, Part 6) scanned `IDENT`
tokens and shifted any that parsed as an A1 cell — but a bare sheet name like
`Sheet2` *also* parses as a cell (column `SHEET`, row 2). So `=Sheet2!A1` copied a
row down became `=SHEET3!A2` — the cell shifted (good) **and the sheet name shifted
too** (catastrophic: the formula silently re-points at a different, usually
non-existent sheet). Quoted qualifiers (`'My Data'!`) were already safe — they lex as
`QUOTED_NAME`, not `IDENT` — and bare names that don't read as a cell (`Data!`) were
safe by accident.

**Shape.** A token that is an `IDENT`/`QUOTED_NAME` immediately before a `!` is a
sheet qualifier, never a cell: the scan steps over it (and the `!`) and shifts only
the cell after it, so the sheet name survives byte-for-byte while `=Sheet2!A1` → 
`=Sheet2!A2`. The range guard also refuses an end corner that is itself a qualifier
(`A1:Sheet!B2` is illegal syntax — don't shift a second sheet name).

**Off-edge decision.** When the qualified cell shifts off the sheet the WHOLE
reference — sheet qualifier included — collapses to `#REF!`. The qualifier is dropped
deliberately: a bare `Sheet2!#REF!` mis-evaluates to `#NAME?` (the parser reads
`#REF!` as an unknown name after the `!`), whereas `=#REF!` is the first-class error
literal the engine reserves for a dead reference. So `=Sheet2!A1` shifted off the top
becomes `=#REF!`, evaluating to `#REF!` exactly like a local ref would.

**Tests (+16; core 880 → 896).** 14 table rows (qualified single/range shift, bare-
name regression, quoted qualifier, pins under a qualifier, identity, off-edge
collapse, mixed qualified+local) plus 2 named tests: the bare-`Sheet2`-not-corrupted
regression and an engine round-trip (live dependency on the shifted cell; off-edge
reads `#REF!`). `rename_sheet_in_formula` (the other `!`-aware splice, row 5) was
already correct and is untouched.

## References

- `core/workbook.py` — `rename_sheet`/`add_sheet` uniqueness; the `sheet:rename` payload (`old`, `new`, `sheet`).
- `formula/recalc.py` — `CellKey`, `extract_deps`, the `sheet:add`/`remove` subscriptions the rename handler joins.
- `formula/evaluator.py` `Context` — gains the workbook handle.
- design.md Part 2 (recalc, superseded key) · Part 9 decision 3 (the deferral this pass discharges).
