# Trellis worklog

A session-by-session record of what was built, decided, and discovered. Newest entries on top.

---

## 2026-05-27 — Session 14: Recalc engine + Sheet/Workbook integration (subtask #18)

**The milestone session.** Trellis is now a working spreadsheet — set a formula, it computes; change an input, dependents recompute; create a cycle, get `#CIRC!`. The integration test from `design.md` passes verbatim.

**What got built**
- `src/trellis/core/sheet.py` — added private `_set_value(addr, value)`. Updates the existing cell's `value` in place (preserving `formula` and `meta`), emits `"cell:recalc"` (NOT `"cell:change"`) so the recalc engine doesn't re-trigger itself. Emits with the same `addr / old / new` payload shape as `cell:change` (old is a snapshot Cell; new is the live mutated Cell), so subscribers can attach a single handler to both events.
- `src/trellis/formula/recalc.py` (NEW, ~13 KB) — `RecalcEngine` plus the public `extract_deps(ast, sheet_name)` helper. Cell keys are `(sheet_name, row, col)` tuples (future-proof for cross-sheet refs even though they're out of v1). Engine state is three dicts: `_asts`, `_dependents`, `_dependencies`, plus a `_processing` re-entry guard.
- `src/trellis/core/workbook.py` — `__init__` now lazy-imports `RecalcEngine` and calls `self.recalc = RecalcEngine(); self.recalc.attach(self)`. Lazy import avoids the `trellis.core ↔ trellis.formula` cycle. Engine exposed publicly so users can `wb.recalc.detach()` for batch operations.
- `src/trellis/formula/__init__.py` — re-exports `RecalcEngine`.
- `tests/test_recalc.py` (NEW, 43 tests) — covers `_set_value` semantics, `extract_deps` shape, direct/chain/range/fan-out recalcs, dep-graph reroutes on formula change, parse errors → NAME, error propagation, all three cycle types (self / 2-cell / 3-cell), cycle recovery, sheet add/remove, detach/reattach, the design.md integration test verbatim, and "bare sheet" semantics (no workbook = no recalc, but no crash).

**Algorithm notes worth remembering**
- **Cycle detection runs *before* registration.** When `cell:change` arrives with a new formula, we parse + extract deps, then walk from each dep along `_dependencies` (BFS) — if we ever reach the target, the new edge `target -> dep` would close a loop. If yes: write `CIRC` and **do not register**. Registering a cyclic edge would let `_propagate` infinite-loop. Skipping registration means (a) the cycle is contained, (b) when the user fixes the formula the engine recovers cleanly, (c) other cells that already depended on the now-CIRC cell still see CIRC through normal error propagation.
- **Topological recalc via Kahn's algorithm restricted to the affected subset.** `_transitive_dependents(root)` collects every cell that depends on root via any chain; `_topo_sort(cells)` then orders them by counting in-degrees over edges *within* that set. Each cell gets re-evaluated exactly once per change, even when multiple paths converge (`test_chain_recalc_visits_each_dependent_once` locks this in).
- **The cell:recalc event mirrors cell:change's payload shape (`addr, old, new`).** Snapshot the cell's old `value`/`formula`/`meta` into a fresh Cell instance before mutating in place. Subscribers can attach the same handler to both events. The cell's *identity* is preserved across recalc (a handler holding a reference to the cell sees the new value via that reference).
- **Workbook auto-attaches.** Per design — `wb.recalc` exists on construction; no manual wiring. Lazy import handled the `core ↔ formula` cycle: `trellis.formula.recalc` doesn't import `trellis.core` at module level (only inside a `TYPE_CHECKING` block), and `Workbook.__init__` does the `from trellis.formula.recalc import RecalcEngine` lazily so package import order doesn't matter.
- **Bare sheets work fine — they just don't recalc.** A `Sheet("X")` not attached to a Workbook stores the formula but doesn't evaluate it (no engine subscribed). `cell.value` stays `None`. That's the *right* answer for the design: the formula engine is workbook-scoped because cross-sheet refs (v2) need a workbook to resolve against. Surfaced in `test_bare_sheet_does_not_evaluate_formulas`.

**Tool incident (third strike — Edit tool on this folder is now banned)**
- Two of my Edits in this session truncated files: `workbook.py` lost its `__contains__`/`__len__`/`__iter__`/`__repr__` methods at the bottom (Edit added 6 lines at top, dropped 10 lines at bottom), and `formula/__init__.py` ended up reverted to the pre-#18 state. Recovery: stage+cp on both. There was *also* a secondary `/tmp` permission issue — a stale `/tmp/formula_init.py` from a prior session was owned by `nobody:nogroup` and unwritable by the current user, so my heredoc silently failed and `cp` picked up the stale contents (Session 11's `__init__.py`). Fixed by using a unique filename `/tmp/formula_init_v2.py`.
- **New rule for this folder: Edit is BANNED for non-trivial changes. Stage+cp is the default for everything but pure single-line fixes, and even those should verify with `git diff`.** Sed-based edits via bash + cp are also OK since they go through bash directly. Auto-memory updated.

**Status**
- **632 tests passing** (589 carried + 43 new). One test failed on first run — my arithmetic (`1 + 20 + 100 = 122`); fixed to 121. Everything else green.
- Task #18 complete. The formula engine is now end-to-end functional. The design.md integration test (set values, set formulas, change inputs, watch dependents update, introduce a cycle, see CIRC) passes exactly as written.

**Next pick-up**
- #19 (top-level re-exports + README + smoke test docstring example) — the last subtask under #4. After that, the formula engine parent task #4 closes. Then #5 (entry_points plugin discovery) is the natural next chapter, or call #4 done and move to file I/O.

---


## 2026-05-27 — Session 13: Second batch of built-in functions (subtask #23)

**What got built**
- `src/trellis/formula/builtins.py` extended with 12 new functions: `IFERROR`, `ISERROR` (both lazy), `ISBLANK`, `ISNUMBER`, `ISTEXT`, `AND`, `OR`, `CONCAT`, `LEN`, `LEFT`, `RIGHT`, `MID`. Module docstring expanded to cover the new rules (CONCAT walks ranges, ISBLANK is strict, ISNUMBER excludes bools, text functions coerce via the `&` operator's `_to_string`, MID is 1-indexed, etc.).
- New shared helper `_collect_bools` mirrors `_collect_numerics`: walks AND/OR args, applies the scalar-strict / range-skip-text asymmetry, propagates errors out of ranges. Returns `#VALUE!` for both "no args at all" and "range provided but everything got skipped" — matches Excel.
- Same-package import: `from .evaluator import _to_string` so CONCAT/LEN/LEFT/RIGHT/MID share the exact stringification rule used by the `&` operator. Worth noting the underscore — it's "private to the formula package" rather than "private to the module"; if a plugin author asks for it to be public, easy to drop the prefix.
- `tests/test_formula_builtins.py` extended from 85 to 186 tests (+101). Per function: happy path, edge cases (n=0, n past end, empty string, single arg, no args), error propagation, range arg where applicable, arg-count errors. Composition section now spans both batches — e.g. `MID(A1, INT((LEN(A1)+1)/2), 1)` to pick the middle character, `CONCAT(LEFT(...), "_", RIGHT(...))`, `IFERROR(SUM(...), 0)`, `IF(ISNUMBER(A1), "num", "other")`.

**Refactor: #22 arg-count handling**
- Caught while planning #23: `ABS`, `ROUND`, `INT`, `NOT` used positional Python params (`def _abs(ctx, x): ...`), so calling `NOT(1, 2)` would raise an uncaught `TypeError` out of `evaluate()` — violating the "errors are values, never exceptions" contract. Refactored all four to use `*args + len check + _arg_count_error(name, expected, got)`, returning `#N/A` like IF/IFERROR do. Added 4 regression tests (`test_abs_wrong_arg_count`, etc.) to lock the new behaviour in.
- The new `_arg_count_error(name, expected, got)` helper standardises the message format. Worth using it for all future built-ins.

**Design calls worth remembering**
- ISERROR and IFERROR MUST be lazy. The eager dispatcher short-circuits FormulaError args before reaching the function, so an eager `ISERROR(1/0)` would never see the DIV0 to test — the dispatcher would just return DIV0. This is the same reason IF is lazy (un-taken branch protection), but the motivation is different: IF cares about *not* evaluating, ISERROR cares about *capturing* the error after evaluation.
- AND / OR are deliberately NOT short-circuited. Excel doesn't short-circuit them either: `OR(TRUE, 1/0)` is `#DIV/0!`, not `TRUE`. Eager dispatch gives that behaviour for free — no special lazy handling needed. If we ever want short-circuit semantics for performance, that's a separate function (something like `ANDX`), not a change to AND.
- ISNUMBER returns FALSE for bools. Python's `isinstance(True, int)` is True, so a naive ISNUMBER would return True for booleans — that's wrong in spreadsheet semantics. The check `if isinstance(v, bool): return False` runs *before* the int/float check.
- RIGHT with n=0 needs explicit handling: Python's `text[-0:]` returns the whole string (because -0 == 0), but Excel returns "". Easy to miss; the test `test_right_n_zero` locks it in.
- MID's start arg is 1-indexed per Excel. Internally we compute `text[start - 1 : start - 1 + n]`. `start < 1` is `#VALUE!` (not "treat as 1"). `start` past the end returns `""` (not an error — Excel does this too).

**Status**
- **589 tests passing** (488 carried + 101 new). Green on the first pytest run again — the #22 helpers and the registry-level contract made the second batch nearly mechanical.
- Task #23 complete. The formula engine now has 22 built-ins total: aggregates (SUM/AVERAGE/COUNT/MIN/MAX), scalar math (ABS/ROUND/INT), logical (IF/IFERROR/ISERROR/AND/OR/NOT), type checks (ISBLANK/ISNUMBER/ISTEXT), and text (CONCAT/LEN/LEFT/RIGHT/MID). The function-call surface is large enough now to build a vertical-slice demo on top of.
- Task #18 (recalc engine + Sheet/Workbook integration) is the obvious next step — it'd unlock end-to-end formula cells (set `A1=1`, `A2=2`, `A3="=SUM(A1:A2)"`, change `A1`, watch `A3` update). Touches the non-emitting-write path designed in Session 7. Worth a quick check with Matthew before starting since it spans the formula <-> sheet boundary.

**Tooling note**
- All file writes this session used the stage-in-`/tmp` + `cp` + `sync` + verify protocol per `write-protocol-mount-folders`. WORKLOG.md in particular — no more Edit on this file. The new entry above was built via `head -n 5` + heredoc + `cat` of the tail, then atomic cp+sync+verify.

**Next pick-up**
- #18 (recalc engine) — the vertical slice that turns this from "a parsed formula library" into "a working spreadsheet." Or #19 (re-exports + README + smoke test) if a smaller win is preferred. Matthew's call.

---



## 2026-05-27 — Session 12: First 10 built-in functions (subtask #22)

**What got built**
- `src/trellis/formula/builtins.py` (NEW) — ten built-ins registered via `@register_function` at import time: aggregates `SUM`, `AVERAGE`, `COUNT`, `MIN`, `MAX`; scalar math `ABS`, `ROUND`, `INT`; logical `IF` (lazy), `NOT`. Module docstring records the Excel-shaped rules (string-in-range silently skipped vs. string-as-scalar is `#VALUE!`, `AVERAGE` of nothing is `#DIV/0!`, `MIN/MAX` of nothing is 0, round-half-away-from-zero, `INT` rounds toward negative infinity, `IF` lazy + missing else returns `FALSE`).
- Three shared coercion helpers: `_coerce_scalar_number` (for ABS/ROUND/INT), `_to_bool` (for IF/NOT; strings are VALUE — no auto-parse, consistent with the rest of the engine), and `_collect_numerics` (for the aggregates; handles the scalar-vs-range error-vs-skip asymmetry and propagates FormulaError out of ranges).
- `src/trellis/formula/__init__.py` updated: imports `builtins` as `_builtins` purely for the registration side effect; nothing from it is re-exported because call sites use formula strings, not Python imports.
- `tests/test_formula_builtins.py` (NEW, 85 tests) — per function: happy path, range args, mixed scalar+range, empty-input cases, scalar-string-is-VALUE, error propagation. Plus a "all 10 registered at import" smoke test and a composition section (`AVERAGE(MIN(...), MAX(...))`, `IF(SUM(...)>50, MAX(...), MIN(...))`, `ROUND(SUM(...), 1)`, etc.) to catch wiring bugs the per-function tests would miss.

**Design calls worth remembering**
- Aggregates have an *asymmetry*: scalar string args raise VALUE, but strings inside a range are silently skipped. Reason: matches Excel and matches user expectation — a literal `SUM(1, "hi", 2)` is obviously wrong; `SUM(A1:A5)` where one cell happens to hold a label shouldn't blow up. COUNT is special — never errors on text, just doesn't count it.
- Bools in ranges are NOT counted as numerics for aggregates (Excel rule). Bools as direct scalar args ARE coerced to 0/1 for SUM/MIN/MAX/AVERAGE (consistent with the arithmetic operators' `_to_number`), but never for COUNT.
- `_to_bool` rejects strings rather than treating "TRUE"/"FALSE" as truthy text. Same reason the evaluator rejects `"5" + 1` — we don't auto-parse strings anywhere. If a user wants this, they can wrap with a future `VALUE()` built-in.
- ROUND uses `math.copysign(math.floor(abs(n) * factor + 0.5), n) / factor` — round-half-away-from-zero, NOT Python's banker's rounding. So `ROUND(2.5, 0)` is 3 and `ROUND(-2.5, 0)` is -3.
- INT uses `math.floor`, NOT Python's `int()`. So `INT(-1.5)` is -2, not -1. (`int()` truncates toward zero; Excel rounds toward negative infinity.)
- IF arg-count errors return `#N/A` (not VALUE). The error code "Value not available" most closely captures "you called this wrong, I can't give you a value". Worth revisiting if a built-in ever needs to distinguish.

**Sandbox setup wrinkle (not a code issue)**
- pyproject pins Python `>=3.11`; the bash sandbox only had 3.10. Installed CPython 3.11.15 via `uv python install 3.11` (one-time), then `pip install -e . pytest --break-system-packages`. Future sessions in this sandbox: the Python 3.11 binary is at a session-specific path under `~/.local/share/uv/python/...`, so it doesn't persist across sessions. Quickest re-bootstrap is `uv python install 3.11 && <that python> -m pip install -e . pytest --break-system-packages`.

**Tool incident & lesson (the actually-load-bearing entry)**
- The first attempt to write this Session 12 entry used the `Edit` tool. It appended the new section at the top correctly but silently truncated ~3 KB from the bottom of the file — the mount bug documented in Claude's `write-protocol-mount-folders` memory. Sessions 1 and 2 plus the tail of Session 3 were lost. The file was repaired via stage+cp protocol and a `[NOTE FROM SESSION 12]` marker added at the new end. **Lesson: the size threshold for stage+cp must include WORKLOG-class append-only files, not just newly-authored sources.** Memory updated to make this explicit.

**Status**
- **488 tests passing** (403 carried + 85 new). Green on the first pytest run — no debugging needed. The coercion helpers carried their weight; getting the asymmetric scalar-vs-range rule into one place paid off.
- Task #22 complete. Task #23 (second batch of built-ins) is now the next obvious move — likely candidates per design.md: `IFERROR` (lazy), `ISERROR`/`ISBLANK`/`ISNUMBER`/`ISTEXT`, `AND`/`OR` (probably lazy for short-circuit), `CONCAT`, `LEN`, `LEFT`/`RIGHT`/`MID`. Task #18 (recalc engine + Sheet/Workbook integration) is *also* unblocked now that there are real functions to recalc through; could pick that up instead of #23 if a vertical-slice demo feels more valuable than more built-ins.

**Next pick-up**
- Either #23 (more built-ins — mechanical, expands surface area) or #18 (recalc engine — vertical slice; first end-to-end formula-cell demo). Worth a quick check with Matthew before starting #18 since it touches Sheet/Workbook and the non-emitting-write path designed in Session 7.

---


## 2026-05-27 — Session 11: Function registry + lazy-arg support (subtask #21)

**What got built**
- `src/trellis/formula/functions.py` (NEW) — a private `_REGISTRY` dict mapping uppercase function names to `(callable, is_lazy)`. Public helpers: `register_function(name, lazy=False)` decorator, `get_function(name)`, `registered_function_names()`, `unregister_function(name)`. Re-registration silently replaces (plugins can override built-ins — chaotic-good).
- `src/trellis/formula/evaluator.py` updated: `Context` gained an `evaluate(node)` method (thin wrapper around the module-level function, so lazy callbacks can write `ctx.evaluate(node)` without importing from this module). `_eval_function` now dispatches through `get_function`: eager pre-evaluates args and short-circuits on FormulaError; lazy passes raw AST nodes. Unknown name → NAME error without evaluating args.
- `src/trellis/formula/__init__.py` updated: re-exports `register_function`, `get_function`, `registered_function_names`, `unregister_function`.
- `tests/test_formula_functions.py` (NEW) — 26 tests covering registration & lookup (case insensitivity, re-registration, unregister), eager calls (arg pre-evaluation, error short-circuit, range args, no-args, multi-args), lazy calls (receives AST nodes, uses ctx.evaluate, untaken branch never evaluated, can catch errors IFERROR-style), unknown function returns NAME without evaluating args, case-insensitive call sites. Uses an autouse fixture to snapshot/restore `_REGISTRY` around each test so registrations don't bleed.
- `tests/test_formula_evaluator.py` lightly updated: the "unknown function returns NAME" tests now use the non-builtin name `NOSUCH` so they stay correct after #22/#23 register SUM and friends. Also added a small `test_context_evaluate_method_works` covering the new Context method.

**Bug surfaced & fixed**
- The first pytest run failed one test: `test_eager_function_receives_context_as_first_arg` asserted `ctx.sheet is s`, but the helper `evalstr(src, sheet=None)` used `sheet or Sheet("Test")` to default. `Sheet` has `__len__` → empty sheets are Python-falsy → `sheet or default` silently substitutes when the caller passes an empty sheet. Fixed by switching to explicit `if sheet is None` checks in both `evalstr` helpers. Production code was correct; this was a test-helper bug. Worth remembering: **never use `or` to default a container — Sheet/Range/etc are falsy when empty.**

**Status**
- **403 tests passing** (376 carried + 27 new — 26 in test_formula_functions.py and 1 in test_formula_evaluator.py).
- Task #21 complete. Tasks #22 and #23 (built-in functions, first and second batch) are now unblocked.
- The formula engine can now register and dispatch functions. Eager + lazy semantics both verified end-to-end. No built-ins yet — that's #22/#23.

**Next pick-up**
- #22: first 10 built-ins — SUM, AVERAGE, COUNT, MIN, MAX, ABS, ROUND, INT, IF (lazy), NOT. Each with happy-path + edge-case + error-propagation tests. Should be mostly mechanical given the registry is in place.

---


## 2026-05-27 — Session 10: Evaluator core landed (subtask #17)

**What got built**
- `src/trellis/formula/evaluator.py` — the `evaluate(node, ctx)` function walks every AST node type. Number / String / Bool literals are trivial; CellRef resolves via `ctx.sheet.get((row, col))`; RangeRef returns a flat list of values (row-major, None for empty cells) via the existing `Sheet.range(...).values()` plumbing.
- `Context` dataclass holds the current `sheet` and an optional `current_cell` (used later by #18's recalc engine for circular-ref detection; ignored by the evaluator itself in v1).
- **Errors are values, not exceptions.** `evaluate()` never raises a FormulaError — the last test in the suite (`test_evaluate_never_raises_formulaerror`) enforces the contract across every error path.
- **Coercion rules wired:** `None` (empty cell) → 0 in arithmetic and "" in concatenation; bool → 0/1 in arithmetic; strings do NOT auto-parse to numbers (`"5" + 1` is a VALUE error — strict for v1, can soften later if it bites).
- **Error propagation:** any FormulaError operand short-circuits and bubbles up. Left operand wins when both would error (left is evaluated first; right is never reached). DIV0 returns from `1/0`. Number overflow on `^` returns a `#NUM!` error.
- **Ranges illegal as scalar operands.** `A1:A5 + 5` returns VALUE — ranges only make sense as function arguments. `A1:A2` evaluated alone returns the value list.
- **FunctionCall returns NAME** for any name — no functions are registered yet. Hook for #21 to replace.
- `src/trellis/formula/__init__.py` updated to re-export `Context` and `evaluate`.
- `tests/test_formula_evaluator.py` — 69 tests covering literals, cell/range refs (including None for empty cells and row-major order), all operators (unary, binary arithmetic, concat, comparison), precedence verified at the evaluation level, every coercion rule (None → 0 / "", bool → 0/1, string → VALUE), all error propagation paths, the left-error-short-circuit semantics, the "ranges in scalar ops return VALUE" rule, the "function calls return NAME" stub, the Context dataclass, and a full parser-then-evaluator integration suite.

**Status**
- **376 tests passing** (307 carried + 69 new). First run, no debugging.
- Task #17 complete. Task #21 (function registry + lazy support) is now unblocked.
- The formula engine can already evaluate everything *except* function calls: `(A1 + B1) * 2 - 1` works end-to-end against a live Sheet.

**Design notes worth remembering**
- Strict on string → number coercion. Excel would parse `"5" + 1` as `6`; we return VALUE. If users ask for it, add a `VALUE()` builtin (#22/#23) and revisit. Don't bury the coercion in the operator.
- Range values are a flat 1D list in row-major order. 2D ranges are still 1D lists at this layer; functions that care about row/column structure can request the shape from the AST or the underlying Sheet.
- `_compare()` is the most fiddly helper — None coerces to "" when the *other* operand is a string, otherwise to 0. Documented inline so the rule doesn't drift.

**Next pick-up**
- #21: function registry + lazy-arg support. Module-level decorator `register_function(name, lazy=False)`. Wire the evaluator's `_eval_function` to look up by uppercase name, returning NAME if absent. Lazy-arg variant for IF / IFERROR. Once this lands, #22 (first 10 built-ins) can begin.

---


## 2026-05-27 — Session 9: Formula parsing front-end verified (subtask #20)

**What got built**
- `tests/test_formula_errors.py` — 16 tests covering FormulaError value semantics (equality-by-code, hashing, dict-keyability, not-an-Exception, slots-prevent-attrs), Excel-shaped error constants, and ParseError as a proper Exception with position tracking.
- `tests/test_formula_lexer.py` — 51 tests (some parametrized) covering every token kind: numbers (int/float/scientific/leading-dot/trailing-dot, type preservation), strings (empty, escaped, punctuation-inside, unterminated), identifiers (upper/lower/underscore/digits), all single-char and multi-char operators, punctuation, position recording, and the explicit "lexer doesn't strip leading =" / "negative number is two tokens" behaviours.
- `tests/test_formula_parser.py` — 75 tests covering every AST node shape, every literal (incl. mixed-case TRUE/FALSE), cell refs, range refs with corner-normalisation (`B5:A1` -> `A1:B5`), all unary forms (incl. double-negative and unary-on-function-call), postfix percent, all binary operators, precedence (mul-before-add, left-assoc subtraction/division, right-assoc `^`, comparison lowest, concat middle, unary-binds-tighter-than-`^` per Excel), function calls (0/1/many args, name uppercasing, nested calls, whitespace inside), and a thorough error suite (empty input, just `=`, unbalanced parens, trailing tokens, missing operands, unknown identifiers, empty parens, non-string input, only-whitespace).

**Status**
- **307 tests passing** (165 carried + 142 new). First run, no debugging needed — sources from #16 were correct as written.
- Task #20 complete. Task #16 (the source-files-only sibling) already closed. Parsing front-end is fully verified.
- Task #17 (evaluator + function registry + built-ins) is now unblocked. It was the only subtask depending on the parser being green.

**Design notes worth remembering**
- Unary `-` binds tighter than `^` (Excel convention) — `-2^3` parses as `(-2)^3 = -8`, not `-(2^3) = -8`. Same numerical result here but they diverge on `-2^2` (Excel: 4, Python: -4). We follow Excel.
- The parser doesn't validate function names — `xyz()` parses to `FunctionCall("XYZ", ())` and only fails at evaluation. That's the evaluator's job (#17).
- Range corner-normalisation happens at parse time: by the time you have a `RangeRef`, `start` is always top-left and `end` is bottom-right. Saves the evaluator from re-normalising.

**Next pick-up**
- #17: evaluator. Walks the AST given a Context (workbook + current cell + lazy-arg evaluator). Function registry with ~20 built-in starters (SUM, IF, IFERROR, etc.). IF and IFERROR need lazy-arg support per design.md. Substantial chunk but well-spec'd; could be split into #17a (evaluator core) and #17b (built-in functions) if it feels too big when starting.

---


## 2026-05-27 — Session 8: Formula parsing front-end source files (subtask #16, partial)

**What landed**
- Five source files under `src/trellis/formula/`: `errors.py`, `ast.py`, `lexer.py`, `parser.py`, `__init__.py`. ~18 KB of code, no tests yet.
- `errors.py` — `FormulaError` value class (NOT an Exception); the seven Excel-shaped constants (`DIV0`, `VALUE`, `REF`, `NAME`, `CIRC`, `NA`, `NULL`); and `ParseError` (an Exception, internal to the parser).
- `ast.py` — frozen dataclasses for every AST node type, value-equal and hashable.
- `lexer.py` — small state-machine tokenizer. Handles numbers (int/float/scientific, leading-dot), strings (with `""` escape), idents, multi-char ops (`<=`, `>=`, `<>`), punctuation, positions for error messages.
- `parser.py` — Pratt parser per design.md Part 2 precedence ladder. Right-associative `^`, postfix `%`, unary `+`/`-`. Identifier handling distinguishes function call vs bool literal vs cell ref vs range ref (with corner-normalisation).
- `__init__.py` — re-exports the public surface of `trellis.formula`.

**Status**
- #16 closed as **sources shipped, untested** at Matthew's request. The test-and-verify pass is split into new subtask #20.
- 165 previously-passing tests still pass (no changes to existing files), but the new code is **untested** until #20 runs.
- #17 (evaluator) is now also blocked by #20 — don't start the evaluator until the parser's been verified green.

**Next pick-up**
- #20: write `test_formula_errors.py`, `test_formula_lexer.py`, `test_formula_parser.py` (tests outlined in the design); run pytest; debug any bugs the tests surface in the new source files; close #20.

---


## 2026-05-27 — Session 7: Formula engine designed (task #4)

**What happened**
- After closing task #11 (Range), shifted to scoping the formula engine. Drafted Part 2 of `design.md` covering subpackage layout (`trellis.formula/`), supported syntax (Excel-style operators, hand-rolled lexer + Pratt parser, zero new deps), built-in function set (~20 starters through a registry that doubles as the plugin surface), error-as-value model (`FormulaError` propagates through arithmetic and functions), recalc engine design (event-driven, attaches to workbook via `cell:change`), and the integration choice for the non-emitting write path.
- Surfaced the non-emitting-write problem as the design's load-bearing decision. Three options laid out; chose **option C**: private `Sheet._set_value()` that updates `value` (preserving formula) and emits a new `"cell:recalc"` event instead of `"cell:change"`. Subscribers wanting "user-initiated change" listen to `cell:change`; subscribers wanting "value changed at all" listen to both. Matthew approved.
- Matthew added a design constraint worth remembering: don't write a clever dependency-ordering algorithm for cheapest-path recalc. Naive forward BFS, with an escape hatch if it ever becomes a real problem. Saved to auto-memory as `simplicity-over-clever-solvers.md`.
- Created four subtasks under #4: #16 (errors + lexer + parser + AST), #17 (evaluator + function registry + built-ins), #18 (recalc engine + Sheet/Workbook integration), #19 (re-exports + README + end-to-end smoke test). Each independently shippable; sequenced via blockedBy so the task list naturally serves up "what's next."

**What got committed this session**
- `design.md` expanded to ~19 KB. Part 1 (event system) marked SHIPPED with resolutions to the original open questions. Part 2 (formula engine) is the new design.
- `.gitignore` expanded: added Windows OS metadata (Thumbs.db, desktop.ini), tooling caches (.mypy_cache, .ruff_cache, .pyright), write-protocol staging artifacts (*.tmp), and editor backups (*~, *.bak, *.orig).
- Auto-memory addition (lives in Claude's memory, not the repo): `simplicity-over-clever-solvers.md`.

**Status going into the break**
- 165 tests still passing (no code changes this session — design + bookkeeping only).
- Tasks #16–#19 created and sequenced. Parent #4 blocked on all four.
- Matthew committing the project locally at end of session. No work in flight, no half-shipped state.

**Next session pick-up**
- Start subtask #16 (errors + lexer + parser + AST). Pure parsing front-end, no evaluation. Design fully spec'd in design.md Part 2 — the lexer + Pratt parser pattern is well-trodden; the precedence ladder is enumerated.

---

## 2026-05-27 — Session 6: Range objects + multi-cell views (subtask #11)

**What got built**
- `src/trellis/core/range.py` (NEW) — `Range` class: a rectangular view over cells in a Sheet. Construction from `"A1:B5"` strings or `((row,col), (row,col))` tuples. Corner-normalisation (so `"B3:A1"` = `"A1:B3"`). Shape introspection (`rows`, `cols`, `shape`, `len`). Five iteration methods: `positions()`, `addrs()`, `cells()`, `values()`, and `__iter__` (cells). `__contains__` for membership. `assign()` for broadcast — scalar, 1D iterable to row/column, or 2D iterable matching shape. `clear()` to delete every stored cell. Strings, bytes, and `Cell` instances are always treated as scalars (never as iterables) to avoid character-by-character spread.
- `src/trellis/core/sheet.py` (updated) — added `Sheet.range(addr)` method. `__getitem__`, `__setitem__`, `__delitem__` now dispatch based on address shape: range-shaped addresses route to `Range`, single-cell addresses keep the existing Cell-level behaviour. Added `_is_range_addr` helper that recognises `"A1:B5"` strings and tuples-of-tuples without false-positives on single tuple `(0, 0)`.
- `src/trellis/__init__.py` (updated) — `Range` added to top-level imports and `__all__`. Module docstring updated with a range example.
- `tests/test_range.py` (NEW) — 36 tests covering construction (string, tuple, normalisation, validation), shape, all five iteration paths (with empty cells surfaced as `Cell()` placeholders), membership, broadcast assignment (scalar, formula string, 1D row/column, 2D shape-match), all the shape-mismatch / 1D-on-2D / empty-iterable error paths, the string-is-scalar-not-iterable rule, event emission per cell via `assign`, `clear`, and `__repr__`.
- `tests/test_sheet.py` (updated) — 11 new tests for Sheet's dunder dispatch: `sheet["A1:B5"]` returns a `Range`, tuple form `sheet[((0,0),(2,1))]` too, broadcast/spread/2D-spread assignment paths, range delete, single-cell paths still return `Cell`, range assignment fires per-cell `cell:change`, invalid range parts raise `ValueError`.

**Status**
- 165 tests passing (118 carried + 47 new). No regressions.
- Task #11 complete. Task #4 (formula engine) is now unblocked — it depended on Range.
- Task #2 (core data model) parent: I've left it `in_progress` since the original scope was "Cell/Sheet/Workbook"; arguably it could close now that Range has landed. Either way, the core is materially feature-complete for the formula engine to build on.

**Design notes worth remembering**
- `Range` is a *transient view*, not a stored thing. Construct on demand; nothing persists in the sheet just from constructing a Range. Iteration of `cells()` surfaces empty `Cell()` placeholders for unstored positions — matches the "I'm working with this rectangle" mental model. Filter on `cell.is_empty()` if you want stored-only.
- Broadcast of a `Cell` instance stores the *same reference* at every position. Documented as a footgun. Pass a 2D iterable of distinct cells if you need independent identities. Chaotic good — we didn't deep-copy implicitly.
- Strings and bytes are always scalars in `assign()`, never iterables. Prevents `s["A1:E1"] = "hello"` from spreading h-e-l-l-o across the row.
- Address-shape detection (`_is_range_addr`) lives in `sheet.py` because that's where the dispatch happens. Range itself accepts string OR tuple constructors without checking what called it.

**Operational note**
- Wrote all five files via the stage+cp+sync+verify protocol. Every file's staged sha256 matched the landed sha256 on the first attempt. No retries needed this session.

**Open**
- Task #4 (formula engine) is the obvious next chunk and would be a satisfying "feels like a real spreadsheet" milestone before the break.

---

## 2026-05-27 — Session 5: Event system fully shipped (subtask #15, parent #3 closed)

**What got built**
- `src/trellis/__init__.py` — added `Emitter` and `Subscription` to the top-level imports and `__all__`. Updated module docstring to describe the extension surface available today (subclassing, events, Emitter mixin).
- `README.md` — rewrote the "Extending" section. Three numbered subsections: subclass a core object, subscribe to events (live, with a runnable code example showing `wb.on("sheet:add", ...)` chained into `sheet.on("cell:change", ...)`), register into a plugin registry (still coming). Events emitted today are listed explicitly.

**Verification**
- Top-level smoke test: `from trellis import Cell, Sheet, Workbook, Emitter, Subscription` works, and a quick `wb -> sh -> on(cell:change) -> set` round-trip prints the expected events.
- 118 tests still passing, no regressions.

**Status**
- Subtask #15 complete. Parent task #3 (event system) closed — all four subtasks (#12–#15) done.
- Task #2 (core data model) still in progress; ranges/slicing are in follow-up #11.
- Next obvious milestone: #11 (Range objects + multi-cell views like `sheet["A1:B5"]`), which unblocks #4 (formula engine).

---

## 2026-05-27 — Session 4: Sheet & Workbook now emit events (subtasks #13, #14)

**What got built**
- `src/trellis/core/sheet.py` — `Sheet` now extends `Emitter`. `set()` and `delete()` emit `"cell:change"` with payload `addr` (A1 string), `old` (previous Cell, empty if none), `new` (new Cell, empty if delete). Delete of an absent address is silent. No value-equality short-circuit — setting to the same value still fires (plugins can optimize if they care).
- `src/trellis/core/workbook.py` — `Workbook` now extends `Emitter`. Emits `"sheet:add"` (from both `add_sheet()` and `add()`), `"sheet:remove"`, and `"sheet:rename"`, all per `design.md`.
- `tests/test_sheet.py` — appended 8 event tests covering set, delete (existing and absent), formula-string set, Cell-instance set, same-value re-write, and `listener_count`.
- `tests/test_workbook.py` — appended 7 event tests covering all three lifecycle events, the negative "do not emit on failed add/remove" cases, and a wildcard `"*"` subscription that captures every event type in order.

**Status**
- 118 tests passing (104 carried + 14 new). No regressions.
- Tasks #13 and #14 complete.
- Task #15 (re-exports + README) is now unblocked — it's the last subtask under #3.
- Once #15 lands, parent task #3 closes itself (it's blocked by #12–#15, all of which will be done).

**Notes**
- Both core types remain importable and usable without ever calling `on()` — lazy listener storage means no overhead for users who don't subscribe.
- `Sheet.set()` ordering is: capture old → build/store new → emit. So handlers see the new value already in place if they read `sheet[addr]` during the callback (use the `new` payload arg if you want to avoid the round-trip).

---

## 2026-05-27 — Session 3: Emitter mixin landed (subtask #12)

**What got built**
- `src/trellis/core/events.py` — `Emitter` mixin and `Subscription` handle, matching `design.md` exactly:
  - Lazy listener storage (instance `__dict__["_trellis_listeners"]`, only allocated on first `on()`).
  - Synchronous handler dispatch in registration order.
  - Wildcard `"*"` subscription — fires after specific handlers with the event name as the first positional argument.
  - Exceptions in handlers propagate (no swallowing); first thrower stops the chain.
  - Snapshot-before-iterate so handlers may `on`/`off` mid-emit without corrupting iteration.
  - `Subscription` is callable, idempotent, has `.active` and `__repr__`.
  - `listener_count(event=None)` for introspection.
- `tests/test_events.py` — 24 tests covering subscribe/emit basics, three unsubscribe paths, registration order, wildcard semantics, exception propagation (both specific and wildcard handlers), lazy allocation invariants, empty-bucket cleanup, re-entrant emit, on/off-during-emit safety, mixin without `super().__init__`, instance isolation.

- **104 tests passing (80 carried over + 24 new). No regressions.** *[Status line reconstructed by Claude in Session 12 — Edit-tool mount bug truncated the original mid-word here; see the "Bug surfaced & fixed" note in Session 12.]*

---

> **NOTE FROM SESSION 12 (2026-05-27).** Sessions 1 and 2 of this worklog, plus the trailing status line of Session 3, were lost when the Edit tool truncated the file's tail during the Session 12 append. The cause is the known mount-bug documented in Claude's memory (`write-protocol-mount-folders`) — a procedure Claude should have applied to a 26 KB file like this one but didn't. The Session 11 worklog (which mentioned the immediate "next pick-up") and everything from Session 3 onward up to the truncation point are intact. Sessions 1 and 2 covered the project bootstrap (scaffolding, pyproject, initial Cell/Sheet/Workbook stubs) — git HEAD's tree captures the files those sessions produced, even though the narrative entries are gone. If a richer reconstruction matters, ask Matthew before improvising.
