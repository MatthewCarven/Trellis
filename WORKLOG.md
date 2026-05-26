# Trellis worklog

A session-by-session record of what was built, decided, and discovered. Newest entries on top.

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

**Status**
- 104 tests passing (80 carried over + 24 new). No regressions in carried tests.
- Task #12 complete. Tasks #13 (Sheet emitter) and #14 (Workbook emitter) are now unblocked.
- Task #15 (re-exports + README) still blocked by #13 and #14.
- The Emitter mixin is reachable as `from trellis.core.events import Emitter, Subscription`. Top-level `from trellis import Emitter` comes in #15.

**Notes for #13 / #14**
- Sheet emits `cell:change` on both `set()` and `delete()` (of an existing cell); delete of an absent address is silent. Payload: `addr` (A1 string), `old` (previous Cell or empty), `new` (new Cell or empty).
- Workbook emits `sheet:add`, `sheet:remove`, `sheet:rename` per `design.md`.

---

## 2026-05-26 — Session 2: Event system designed, implementation deferred

**What happened**
- Started Task #3 (event system). Sketched the full design: `Emitter` mixin, `Subscription` handle, event naming convention, exception-propagation policy, lazy listener storage, and the decision to *not* make `Cell` an `Emitter` by default (footgun rationale documented).
- Matthew signed off for the night before any code landed and asked me to commit the design to a doc and break the implementation into subtasks.

**What got committed**
- `design.md` — full event system design, alternatives considered, open questions, and the implementation order.
- Subtasks #12–#15 in the task list, covering: `Emitter` mixin + tests; `Sheet` emitter; `Workbook` emitter; re-export + README update.
- Task #3 reverted to `pending` since no code landed.

**Status going into morning**
- All session-1 work still green (80 tests).
- No new code written this session.
- Next time, pick up at subtask #12 (`Emitter` mixin).

---

## 2026-05-26 — Session 1: Foundation + initial core

**Decisions made**
- Name: **Trellis** (folder remains "Cross Tabulator Pro" as a joke, package is `trellis`).
- Language/runtime: **Python 3.11+**.
- License: **MIT** — most permissive option, fits the open-extensibility philosophy. Easy to relax later if needed.
- Build backend: **hatchling**.
- TUI library (locked-in but not yet imported): **Textual**.
- xlsx via **openpyxl** when we get there. Both `textual` and `openpyxl` are *optional* extras — core has zero required deps.
- Source layout: `src/trellis/` (src-layout) with `core/` subpackage for the engine.
- Plugin discovery surface: `entry_points` group `trellis.plugins` (reserved now, used later).

**What got built**
- Project scaffolding: `pyproject.toml`, `README.md`, `LICENSE`, `.gitignore`, project-level `CLAUDE.md`, this `WORKLOG.md`.
- Initial core package:
  - `trellis.core.address` — A1 ↔ (row, col) conversion.
  - `trellis.core.cell.Cell` — minimal cell with `value`, `formula`, public `meta` dict.
  - `trellis.core.sheet.Sheet` — sparse 2D grid with dict-style access; absent cells return an empty `Cell` without persisting it.
  - `trellis.core.workbook.Workbook` — named collection of sheets.
- Re-exports in `trellis/__init__.py` so `from trellis import Sheet, Workbook, Cell` works.
- Tests: address round-trips and error cases, Cell defaults/equality/meta, Sheet get/set/delete/iteration.

**Conventions established**
- `meta = {}` dict on every core object is the polite extension surface. Subclassing and event subscription (coming Phase 3) are the other two.
- Address coercion: any public method accepting an address takes either an `'A1'` string or a `(row, col)` tuple.

**Operational note (added mid-session)**
- Matthew flagged this folder as mount-affected: the Write/Edit tool can silently truncate. Standing rule going forward: stage in `/tmp`, `cp + sync + mv -f + sync` to the target, then re-read size + sha256 to verify. Retry once on mismatch, surface to Matthew on the second failure. Protocol details live in the auto-memory (`write-protocol-mount-folders.md`).
- Retroactive audit of all 17 session-1 files: every Python file compiles via `py_compile`, pyproject parses via `tomli`, every text file's tail matches what was intended. No truncation this session.

**Open questions for next session**
- Confirm whether `Cell.value` should be normalised (e.g. coerce numeric strings to numbers on assignment) or stored as-given. Currently stored as-given.
- Decide where `Range` lives (Phase 2 expansion) — likely `trellis.core.range`.

**Status**
- Task #1 (Foundation) complete.
- Task #2 (Core data model) in progress — basic objects exist; ranges, slicing, and richer iteration to come.
- Task #10 (verify session-1 files on disk) complete — all clean.
