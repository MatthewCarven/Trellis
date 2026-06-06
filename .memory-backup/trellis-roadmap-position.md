---
name: trellis-roadmap-position
description: "Trellis status snapshot as of 2026-06-05: Part 3 AND Part 4 COMPLETE (trellis-mathpack done end-to-end, publication gate cleared, commit 8e8ac48). Next is Matthew's call: first GitHub publish and/or the TUI (trellis-tui)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 119f8586-f304-4502-a589-72e52c8a98b2
---

Snapshot as of **2026-06-03** (Sessions 19–23). Verify against WORKLOG.md top entries + design.md Part 3/4 tables on pickup — this is a pointer, not live state. Resume via [[trellis-pickup-checklist]].

**Part 3 "pre-render engine prep" — COMPLETE** (Sessions 19–22). Hardened the public surface ahead of going public; treat these as a locked contract (the contract tests enforce it):
- 3.1 — locked `cell:change` / `cell:recalc` event payload: `sheet`, `address` (zero-indexed `(row, col)` tuple), `old_value`/`new_value`, `old_formula`/`new_formula`, the live `old`/`new` `Cell` objects, and (recalc only) `trigger`. Note: handlers must take `**kwargs`.
- 3.2 — `Sheet.batch()` context manager: buffers writes, suppresses per-cell `cell:change`, emits one `sheet:batch` on outermost clean exit, deferred recalc via Replay (per-cell trigger; may recompute a dependent >1×). `read_csv` refactored onto it.
- 3.3 — public `Sheet.used_range()` (bounding rect of non-empty cells, `None` if empty); `write_csv` refactored onto it.
- 3.4 — meta-namespacing convention documented (docs only).
- Deferred (documented in design.md Open Questions): `MAX_RECALC_DEPTH` recalc tripwire, and the recalc dedupe-once optimisation — only build if a real need appears (per [[simplicity-over-clever-solvers]]).

**Part 4 `trellis-mathpack` — COMPLETE (#1–#8), publication gate CLEARED** (Sessions 23–28, design.md Part 4). The reference plugin that clears the publication gate ([[trellis-publication-gated-on-client]]). 20 fns (trig/hyperbolic/powers-logs/misc/range-stats), lives at `packages/trellis-mathpack/` subdir, real installable companion package, mints its own `FormulaError("#NUM!")` for domain errors (core has no NUM).
- #2 scaffold (commit ddea1e8): `pyproject.toml` (entry point `mathpack = "trellis_mathpack:setup"`, `dependencies = ["trellis"]`), `src/trellis_mathpack/__init__.py`, README, placeholder tests.
- #3 scalar fns (commit c91bae8): **17 functions** in `setup()` — `SIN COS TAN ASIN ACOS ATAN SINH COSH TANH SQRT POWER EXP LN LOG MOD SIGN PI`. `NUM` minted locally. `_num(x)` = core's `_coerce_scalar_number` (None→0, int/float pass, list/str→VALUE) **but bool→#VALUE!** (the one deviation; flagged in design.md in case Matthew wants strict None→VALUE too). `MOD(x,0)`→core DIV0, not NUM.
- #4 range stats (commit e253772): **3 functions** — `STDEV`/`VAR` (sample, n−1) + `MEDIAN`, via Python `statistics`. `_collect_numerics(args)` flattens range args (FormulaError anywhere propagates; inside a range bool/str/None skipped per Excel; scalar None→0, scalar bool/other→VALUE). `statistics.StatisticsError` (too few points) → core `DIV0`, so `STDEV(5)`/`VAR()`/`MEDIAN()` → `#DIV/0!`. 27 Tier-1 tests, all green.
- #5 finalise (commit 7f72b9d): `setup()` now one loop over `_registrations()` (single source of truth); public `FUNCTIONS` tuple (20 names) in `__all__`; hermetic discovery tests via core's `FakeEntryPoint` + `load_plugins`.
- #6/#7/#8 (commit 8e8ac48): **GATE CLEARED.** `packages/trellis-mathpack/scripts/tier2_discovery_check.sh` builds an off-mount venv, editable-installs core + mathpack, and a fresh `import trellis` auto-discovers all 20 functions with NO manual `setup()` (+ negative control). Resolved the open question: core IS `pip install -e`-able as-is; only needs `--ignore-requires-python` on the 3.10 sandbox vs the declared `>=3.11` floor (no-op on 3.11+); venv must be off-mount.
- **Next is Matthew's call** (no fixed next step): (a) first **GitHub publish** — uncomment `Homepage` in core `pyproject.toml`, push core + mathpack (nothing pushed yet); and/or (b) start the **TUI** (`trellis-tui` sister package), the prime consumer of the Part 3 public surface and the milestone Matthew is excited about.
- Registration design note (still load-bearing for the TUI / any plugin): mathpack fns are module-level but only registered when `setup()` runs (NOT at import).

**Health:** core suite 748 (mathpack's 32 tests are separate, run with `PYTHONPATH=src:packages/trellis-mathpack/src`). Work through Session 27 committed (7f72b9d). pytest on the mount needs `--basetemp=/tmp/... -p no:cacheprovider`; bare `Sheet` has no recalc engine (use `Workbook` when a test needs a stored formula to compute); see [[git-commit-on-mount]] for commit quirks incl. the Edit-tool-invisible-to-git gotcha. "Keep everything in the old folder (Cross Tabulator Pro) for now"; the sibling mounted `Trellis/` folder is currently empty.
