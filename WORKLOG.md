# Trellis worklog

A session-by-session record of what was built, decided, and discovered. Newest entries on top.

---
## 2026-06-06 — Session 33: first-run feedback — CSV `formulas=` round-trip

**Context:** chat archive wiped the session task list again — rebuilt (Part 6 design pass / implementation / Matthew-runs-v1). Matthew ran v1 for the first time: `setup-venv.ps1` clean on py3.14.5 + textual 8.2.7, core 749 green on Windows, app boots, editing/dirty/status all live. First-run find: demo.csv's formulas rendered as left-aligned *text*. Root cause: the engine's documented CSV policy (read: leading-`=` stays literal; write: computed values, "formulas do NOT round-trip. By design.") meeting a TUI whose ONLY format is CSV — so every Ctrl+S flattened formulas to values, and my demo.csv embedded formulas the stock loader deliberately doesn't honor. The demo was wrong; the gap it exposed was real.

**Decision (Matthew, this session): opt-in `formulas=` keyword** on `read_csv` / `write_csv` / `Sheet.to_csv`, default **False** = behavior unchanged. The default stays safe-by-default (an untrusted CSV never smuggles in live formulas — the injection vector; a plain export carries values other tools can use) and the TUI passes `formulas=True` on BOTH paths — its files are spreadsheets. Read side: `=`-cells route through the normal leading-`=` sugar inside the existing load batch (one evaluation pass on close; a broken formula loads exactly like it commits in the editor — error as value, source preserved). Write side: `cell.formula` (with its `=`) wins over the value — checked before the value-is-None branch, so a formula whose current value is None or an error still round-trips its source.

**Landed:**
- Engine: `io/csv.py` (module-docstring policy rewrite + both functions), `core/sheet.py` `to_csv` passthrough.
- TUI: `build_app` load + `_save_to` save both opt in; TUI README (features + key table), root README (io bullet).
- Tests: **+8 engine** (`TestFormulasFlag` — read live / default-still-literal / broken-formula-as-error-value; write source-text / default-still-values / broken-keeps-source; round-trip stays *live* (reloaded formula recalcs); comma-in-formula csv quoting) → **core 757**. **+2 TUI** (Ctrl+S writes source text; save→reopen keeps formulas live through `build_app`) → **TUI 86**.

**Sandbox scars — the write-protocol memory earned its keep twice:**
- Edit-tool append to `tests/test_io_csv.py` silently didn't land at all; the Edit to `sheet.py` landed the edit but **truncated the file tail** (374 of 381 lines, ending mid-statement inside `_BatchContext`). Recovered from `git show HEAD:` + re-applying the change off-mount. Protocol hardened: stage-and-cp for EVERY mount write, verify with ast-parse + line count + sha256.
- A stale `__pycache__` masked the truncation (mount mtimes don't reliably invalidate pycs; in-tree pyc deletes are permission-blocked). All sandbox test runs now use `PYTHONPYCACHEPREFIX=/tmp/pyc`. Both memories updated.

**Verified:** core **757** (+doctests) and TUI **86** green on the 3.10 sandbox; demo.csv end-to-end through `build_app` — totals compute (D5 = 22.9) and a B2 edit cascades live. `demo.csv` left untracked (Matthew's call whether it joins the repo as an example).

**Next pick-up:** Matthew re-runs — `trellis demo.csv`, no reinstall needed (editable installs). Then the queue resumes: **Part 6 design pass — selection + clipboard** (chosen this session over undo plugin / sheet tabs / vim keymap). Push to origin still pending from Windows (now 8 commits ahead).

---
## 2026-06-06 — Session 32: Part 5 design pass — `trellis-tui` scope

**Context:** new session; the session-scoped task list was empty again (same casualty as the move) — rebuilt as 4 tasks (#1 Part 5 design pass, #2 scaffold trellis-tui, #3 implement umbrella, #4 `.memory-backup/` fate). Noticed commit `41089c0` (untrack `.memory-backup/`, keep local-only) already landed after Session 31's worklog entry, so #4 was born resolved — closed it. Local `main` is ahead of the recorded publish point (`37ec605`); Matthew pushes from Windows.

**What got done**
- **design.md — appended Part 5: `trellis-tui` — the terminal frontend** (~170 lines, planning only; design.md now 747 lines / 5 parts). Decisions confirmed with Matthew up front: **usable-editor v1** (grid + navigation + cell editing + formula bar + CSV open/save), **Excel-ish keybindings**, **hardcode-first** (no TUI plugin API in v1; a vim keymap is queued as the first future extensibility proof), **single visible sheet**.
- Scope highlights: MVC over a live engine (no shadow data model; DataTable-backed `SheetGrid` materializing `used_range()` ∪ a min window, grow-on-demand); **one repaint path** — the TUI repaints only via the engine's event echo (`cell:change`/`cell:recalc`/`sheet:batch`), including for its own writes — Part 3's payload lock-in cashed in (old/new for no-op skip, `trigger` for the status line, one `sheet:batch` per CSV load); formula-bar-only editing in v1; `render.py` as a pure, textual-free display-policy module; console script `trellis [file.csv]`; tests on Textual's headless Pilot; implementation table #1–#7 (#2 scaffold → #7 README/sign-off).

**Public-surface gap found by the pass (the reason design passes exist)**
- **Typed input needs core's value-inference rule, and it's private.** Typing `42` must store a number while `01234` stays a string — exactly `trellis.io.csv._infer_value`, underscore-private. Per the Part 4 rule ("a consumer needing an internal = core public-surface bug"), the fix is to **promote `_infer_value` to public** (`trellis.infer_value`), scheduled into Part 5 #2 rather than forking the rule into the TUI. Keeps "type 42" coherent with "load 42 from CSV".

**Also discovered**
- **design.md carried a committed EOF truncation scar**: the file ended mid-sentence inside Part 4's References ("…the COSH/SINH worked example this" — no trailing newline), present since at least `8e8ac48` and therefore public on GitHub. Almost certainly an old silent Write/Edit truncation (the exact failure mode the write-protocol memory exists for). Repaired with a minimal sentence close ("…this package realises)."); whatever further bullets existed are unrecoverable.
- **Textual is at 8.2.x (May 2026), supporting py3.9–3.14.** Core's convenience extras (`tui = ["textual>=0.50"]`, `all`) are badly stale — bump scheduled in Part 5 #2. TUI floor lean `>=8`; pin style left as an open question. Bonus: the 3.10 sandbox can run Pilot tests (package still declares 3.11+).

**Verified:** staged-in-/tmp + cp + sync + sha256 for both files (write protocol); `git diff` reviewed (append-only + the one-line EOF repair); 5 `# Part` headers present.

**Part 5 #2 SCAFFOLDED + core touches (same session, later).**
- **`packages/trellis-tui/` scaffolded** (10 files): pyproject with `dependencies = ["trellis", "textual>=8"]`, console script `trellis = trellis_tui.app:main`, `asyncio_mode = "auto"`, and deliberately NO `trellis.plugins` entry point (frontend, not plugin — comment says so). `src/trellis_tui/`: `__init__.py` (contract docstring: engine-is-the-model, one-repaint-path; `__version__` defined BEFORE the `.app` import, which app.py imports back), `__main__.py`, `app.py` (a real boots-and-quits `TrellisApp` — holds a live `Workbook`, optional CSV arg, `--version` flag, Ctrl+Q), `grid.py`/`editor.py` (contract-docstring stubs, TODO #4/#5), `render.py` (placeholder `display()` raising NotImplementedError, locked by a test). README skeleton with a lands-in table.
- **`_infer_value` → public `infer_value`** (the gap the design pass found): renamed in `io/csv.py` with a promoted-for-frontends docstring note, re-exported from `trellis.io` and top-level `trellis`, `__all__`s updated, root-README bullet added, 29 test references renamed, plus new contract test `test_infer_value_is_the_csv_loaders_rule` (top-level identity + leading-zero stays text).
- **Stale extras bumped:** core `tui`/`all` now `textual>=8` (was `>=0.50`). Pin-style open question DECIDED: uncapped — cap on a proven break, not preemptively.

**Verified (scaffold):** TUI suite **5 passed** (incl. two headless Pilot boots — empty workbook, and CSV-loaded with live in-app recalc `=SUM(A1:A2)`→30) on textual **8.2.7** / py3.10; core suite **749** (748 + the new contract test); end-to-end console-script proof in an off-mount venv — `pip install -e . -e packages/trellis-tui` (`--ignore-requires-python` on 3.10) → `trellis --version` prints, and a fresh interpreter drives the engine through `TrellisApp` (`=A1*2` → 42). design.md: #2 row DONE, textual-pin question DECIDED.

**Part 5 #3 DONE (same session, later) — `render.py` display policy.**
- `display(value) -> DisplayText(text, align, error)` (frozen dataclass), a total function — never raises, whatever a plugin stored in a cell. Rules: `None`→`""`; `str` as-is left (an error-LOOKING string carries `error=False` — styling distinguishes it from a real error); `bool`→`TRUE`/`FALSE` centered, checked before int (bool subclasses int — regression-tested); `int`→`str` right; `FormulaError`→`.code` centered `error=True` for ANY constructed error (a minted `#NUM!` renders like a built-in — no closed-enum assumption); fallback `str(value)` left.
- **Float rule (the open question, DECIDED):** integral floats within ±1e16 render in integer form (`4.0`→`4`, exact through 2**53 — the int-form branch earns its keep: bare `%.15g` would print `9.00719925474099e+15`); otherwise `%.15g`, trimming one-ulp noise (`=0.1+0.2` → `0.3`) while keeping 15 honest digits; `NaN`/`Infinity`/`-Infinity` render as themselves (values, not error cosplay). Alignment: logicals/errors centered (Excel-faithful).
- **New subtlety flagged for #5:** `display()` is deliberately lossy for noisy floats, so a revise-edit (F2) prefilled from display text could alter a stored value on commit. The editor must prefill from `cell.formula` / `repr(value)` instead. Recorded in render.py's docstring + design.md open questions.
- Tests: the placeholder `test_render.py` replaced with the real suite — a 30-case parametrized table (the table IS the spec) + 5 targeted tests (bool-before-int, all 7 core error constants, minted errors, never-raise fallback, frozen dataclass). **TUI suite 39 passed**; core suite **749** (untouched). design.md: #3 row DONE, float question DECIDED, prefill question added.

**Part 5 #4 DONE (same session, later) — read-only `SheetGrid`, the heart.**
- **`SheetGrid(DataTable)`** over a live `Sheet`: A1-anchored window (grid coordinate == engine address, no offset bookkeeping) materializing `used_range()` ∪ minimum ∪ the cursor's high-water reach. **Window defaults DECIDED:** 100×26 minimum, +32 rows/+8 cols when the cursor comes within 2 of an edge, batch-rebuild threshold 256, column width 10 — all class attributes (retune by subclassing, no config system).
- **The event echo, implemented:** `cell:change`/`cell:recalc` → single-cell `update_cell_at`, re-reading the ENGINE (the grid renders the authority, not the event payload), with no-op skip via `values_equal` — deliberately type-strict so `0`→`False` repaints (`==` says equal; display says `0` vs `FALSE`). `sheet:batch` → walk the changes, or one rebuild when >256 changes or any lands outside the window. Out-of-window single writes (scripts/plugins) → rebuild to cover. Mid-batch the grid shows stale text by design — suppression, then one echo.
- **Grow-on-demand** in `on_data_table_cell_highlighted`, growing BEFORE the cursor hits the wall (rows in place; columns via `add_column(default="")` — beyond-window is beyond `used_range`, hence empty). The reach survives rebuilds, so a CSV load can't yank the window out from under the cursor; rebuilds also preserve the cursor.
- **`FormulaBar`** (editor.py grows its nav half): one-line readout `B1 │ =A1*2` — the formula (with its `=`) when set, else the rendered value; `bar.shown` tuple kept for tests/#5. Accepted nit: refreshes on cursor moves, not on writes under a stationary cursor — #5's commit flow refreshes explicitly.
- **app.py real layout** (placeholder gone): Header / FormulaBar / SheetGrid / Footer; `app.sheet` = first sheet (single-sheet v1); sub_title = path. **Shutdown race found by the suite, fixed in the app:** a `CellHighlighted` posted just before exit can arrive after the bar unmounts — the handler queries defensively (`self.query(FormulaBar)`, skip if gone).
- `__init__` re-exports the whole surface (`TrellisApp, main, SheetGrid, FormulaBar, DisplayText, display`); `col_letters` derives A/AA from public `to_a1` (no base-26 duplication). Pre-flight verified: `sheet[a1]` reads are non-mutating (no storage created, `used_range` undisturbed) — window reads are safe.
- Tests: **`test_grid_sync.py`, 14 tests** — window defaults, data-beyond-minimum, display-policy rendering (red error styling, right-justify), single-write echo, recalc cascade, no-op skip + the 0/False repaint, batch suppress-then-echo, 300-row batch rebuild, out-of-window growth, edge growth + reach-survives-rebuild, bar mirrors formula-not-value, unsubscribe-on-unmount. **TUI suite 53 passed**; core **749** unchanged.

**Part 5 #5 DONE (same session, later) — editing. It's a spreadsheet now.**
- **Mode machine across three thin layers:** the grid translates raw input into intent messages (`EditRequest(mode, seed)` / `ClearRequest` — the grid still never writes the engine); the app coordinates; **`editor.commit_text` is the single write path**. `CellEditor(Input)` posts one `Done(text, move, commit)` for Enter/Shift+Enter/Tab/Shift+Tab/Esc.
- **Keys:** typing seeds a replace-edit (Excel overwrite); F2 and nav-Enter open revise-edit (**nav-Enter DECIDED: revise**, Sheets-style — Down already moves; grid's `enter` binding overrides DataTable's select, mouse-click CellSelected ignored); Delete clears; Backspace opens an empty replace-edit; commit keys move down/up/right/left; Esc cancels and restores.
- **Commit policy:** empty → `sheet.delete` (**empty-commit DECIDED: delete**; engine delete verified tolerant of absent cells); leading `=` → stored as-is; else the now-public `trellis.infer_value` (`42` → int, `01234` → string — typed input coherent with CSV load). **Commits never block:** pre-flight proved the engine stores a broken formula as `#NAME?` with the formula text preserved — `=SUM(` commits, shows the error, F2 retrieves it. Errors-are-values doing UX work.
- **Prefill + the unchanged-revise rule (#3's lossiness flag RESOLVED):** `prefill_text` = formula as stored, else full-fidelity text (`repr` for floats, `TRUE`/`FALSE` for bools, code for error values) — never 15g display text. An unmodified revise-edit commits NOTHING — what makes F2+Enter a true no-op on bools, whose text form can't round-trip (inference deliberately never produces bools, per the CSV policy).
- **Dirty flag** on the app via the same engine events (`cell:change` + `sheet:batch`; recalc excluded as derived state). Save clears it in #6.
- **Textual gotcha found by the suite:** `Input` selects-all on focus (8.x default), so the keystroke after a seeded edit replaced the seed wholesale (`=A1*2` arrived as `A1*2`; `012` ate its zero). Fix: `select_on_focus=False`, cursor at end. Bar's cursor-mirror now also skips while editing.
- Tests: **`test_editing.py`, 16** — pure policy (prefill fidelity incl. minted-error codes; commit paths incl. whitespace-strings, broken-formula-stores-not-raises, delete-on-empty) + Pilot flows (seeded replace-edit; int commit + cursor move + echo + dirty; leading-zero string; formula evaluate; F2 formula/`repr` prefill; unchanged-revise no-op on a bool with dirty staying False; Esc restore; Tab/Shift+Enter moves; Delete; Backspace→empty-commit deletes; nav-Enter revise; broken-formula F2 round-trip). **TUI suite 69**; core **749** unchanged.

**Part 5 #6 DONE (same session, later) — CSV save + chrome. v1 feature-complete.**
- **`StatusBar`:** one line — file label, yellow `● modified` marker, last message. Messages persist until replaced (no timers — deterministic, honest). `state` tuple exposed for tests.
- **`Ctrl+S`:** with a path → `sheet.to_csv`; pathless → **`SaveAsScreen` modal (DECIDED: modal over bar-takeover** — the cell editor's state machine stays single-purpose; also the growth point for a future Open dialog). `OSError` reports in the status line and keeps running; success clears dirty + disarms the quit warning. Saving mid-edit saves committed state and leaves the edit open.
- **`Ctrl+Q`:** dirty → warns once ("Ctrl+Q again to quit"); any new write re-arms the warning; clean → quits immediately. Overrides `App.action_quit`.
- **Recalc note:** the `cell:recalc` subscription renders `recalc B1 ← A1` in the status line — 3.1's `trigger` payload earning its keep as chrome.
- **`build_app(args)`** factored out of `main()` (testable without running the UI): `--version`; existing CSV → `read_csv`; **nonexistent path → empty workbook with the path remembered + "new file — Ctrl+S creates it"** (the natural create-a-new-spreadsheet flow).
- **`scripts/setup-venv.{sh,ps1}` updated** to also editable-install trellis-tui (+ pytest-asyncio) — they predated the TUI; the `trellis` command now lands in the venv they build.
- Tests: **`test_chrome.py`, 15** — build_app variants (incl. missing path), save + dirty-clear, pathless modal flow, Esc cancel, save-failure-keeps-running (directory as path), save-mid-edit, quit-warn → quit, re-arm on new write, clean quit, recalc trigger note, dirty marker. **TUI suite 84**; core **749**.

**Part 5 #7 DONE (same session, later) — README for real. PART 5 COMPLETE: trellis-tui v1 SHIPS.**
- TUI README full pass: v1 status (what's in, what's deliberately out), install via the venv scripts or by hand, usage incl. the new-file flow, the complete key table + commit rules (incl. the unchanged-revise no-op guarantee), **Windows Terminal note** (Textual renders poorly in legacy conhost), develop/test with the "the render table IS the spec" line.
- Root README: new "Quick taste (terminal app)" section; Install block updated (`trellis-tui` is its own package — the aspirational `trellis[tui]` line replaced); Status now names all three monorepo distributions. The day-one "terminal-first spreadsheet application" promise is true.
- design.md: #6/#7 rows DONE. **All Part 5 rows #1–#7 done, every open question resolved** (textual pin, window defaults, float display, prefill, nav-Enter, empty commit, pathless prompt).
- **Part 5 retrospective, one line each:** the design pass found a real public-surface gap before any TUI code existed (`infer_value`); the 3.1 payload lock-in carried the whole renderer (no-op skip, batch echo, the `trigger` status note); mathpack's errors-are-values lesson became UX (broken formulas commit and F2 retrieves); the Pilot suite caught two real Textual races (select-on-focus seed-eating, post-unmount messages). "Library first, app second" held — the TUI never needed a core internal beyond the one promotion it was designed to flush out.
- **Suites at sign-off: core 749, TUI 84.** Run it: `scripts\setup-venv.ps1` → `.venv\Scripts\Activate.ps1` → `trellis [file.csv]` (Windows Terminal).

**Next pick-up:** Matthew runs v1. Beyond that, candidates in rough order of pull: selection + clipboard (most-missed), the undo plugin (second reference plugin — payloads already carry old/new), sheet tabs, a vim keymap (first TUI-extensibility proof), xlsx extra. Matthew's call. Also still pending from S31: syncing licenses on his other repos.

---
## 2026-06-06 — Session 31: post-move pickup — roadmap rebuilt + venv setup scripts

**Context:** first session in the renamed/moved folder (`-=Programming=-\Trellis`). The move worked: memory-space link survived (all 10 memories recalled, no restore from `.memory-backup/` needed), git intact. Matthew cleaned up the stray `pytest-cache-files-*` dir. Casualty: the session-scoped task-list roadmap was empty.

**What got done**
- **Task-list roadmap regenerated** (5 tasks): #1 first GitHub publish (gate cleared, Matthew's call); #2 Part 5 design pass — trellis-tui scope in design.md; #3 scaffold `packages/trellis-tui/` (blocked by #2); #4 implement TUI (umbrella, subtasks TBD from design); #5 decide fate of `.memory-backup/`.
- **`scripts/setup-venv.ps1` + `scripts/setup-venv.sh`** — recreate the repo-root `.venv`: editable-install core + mathpack + pytest, then run the core suite (+doctests) as verification. The sh variant takes `VENV_DIR` (sandbox needs off-mount) and `PIP_FLAGS` (`--ignore-requires-python` on the 3.10 sandbox); both are no-ops on a real 3.11+ machine. Written via the /tmp staging protocol, sha256-verified.

**Discovered along the way**
- **Mathpack's Tier-1 tests cannot run inside an installed venv.** With mathpack pip-installed, `import trellis` auto-discovers it, so `test_import_alone_registers_nothing` (and the FUNCTIONS-delta test) fail at baseline; and the `TRELLIS_DISABLE_PLUGIN_DISCOVERY` kill switch is no help because it also disables *explicit* `load_plugins([...])` calls, which breaks the FakeEntryPoint tests instead. Both failure modes confirmed empirically. Conclusion (by design, now documented in the scripts): Tier-1 is hermetic-only (`PYTHONPATH`, uninstalled); the installed-context proof is `tier2_discovery_check.sh`. The setup scripts therefore verify with the core suite only.
- Stale `__pycache__` dirs survived the move with the old "Cross Tabulator Pro" session paths baked into tracebacks — cosmetic; cleaning them is pending Matthew's nod (mount deletes need the permission tool).

**Verified:** `scripts/setup-venv.sh` end-to-end in the sandbox (off-mount venv): editable installs clean, **748 passed** (741 + 7 doctests), exit 0.

**PUBLISHED (same session, later).** Trellis is now public: **https://github.com/MatthewCarven/Trellis** — all 21 commits on `main`, verified live, `origin/main` == local `37ec605`.
- License: Matthew confirmed **keep MIT** (over Unlicense/0BSD — MIT's universality beats the Unlicense's legally-murky "public domain" for real-world openness); repo already shipped MIT everywhere, so no change needed.
- Local prep: branch renamed `master`→`main`; `origin` + upstream tracking wired; `Homepage = "https://github.com/matthewcarven/Trellis"` uncommented in core pyproject (37ec605). Push done by Matthew from Windows (HTTPS + credential manager).
- **New mount quirk found (worse than the lock files):** any sandbox-git command that REWRITES `.git/config` (`git remote add`; `git branch -m`'s config pass) corrupts it into a ghost state — listed by `ls` but unreadable, "bad config line 1". Hit twice. Recovery: `rm .git/config` and hand-write the full config (incl. remote/branch sections) via the /tmp staging protocol. Sandbox sessions must never let git touch config. Recorded in the [[git-commit-on-mount]] memory.
- Noted: `.memory-backup/` is now public on GitHub — folds into the "decide its fate" task (contents are project notes, nothing sensitive, but it's odd furniture for a public repo).

**Next pick-up:** the **Part 5 trellis-tui design pass** (publish is done). Also pending: Matthew may sync licenses on his other repos to MIT; `.memory-backup/` fate.

---


## 2026-06-06 — Session 30: auto-memory backup + folder rename/move prep

**Context:** Matthew is about to rename/move the project folder from "Cross Tabulator Pro" to **Trellis** — most likely by moving contents into the already-mounted empty `-=Programming=-\Trellis` folder (also flattens the old double-nesting). Claude's auto-memory lives outside the folder (AppData, keyed by space ID); the files can't be lost by the move, but the folder↔memory-space *link* might not survive it.

**What got done**
- **`.memory-backup/`** created at repo root: verbatim copy of all 10 auto-memory files + `MEMORY.md` index + `RESTORE-README.md` (restore instructions for a future blank-slate session). Staged in /tmp, cp+sync, every file sha256-verified against staged copies — all OK. Committed as **49ec87b**.
- Catch-up: **Session 29 (2026-06-05)** decided the TUI ships as `packages/trellis-tui/` (in-repo companion *frontend*, not a fork, not a plugin) and recorded it in CLAUDE.md — commit **88dd64a**. No worklog entry was written that session; this line closes the gap.

**Move procedure agreed (Matthew executes in Explorer):**
1. Disconnect the folder in Cowork first.
2. Enable "Hidden items", move everything **including `.git`** but **excluding `.venv` and `.pytest_cache`** into `-=Programming=-\Trellis`.
3. Reconnect Trellis in Cowork; test recall ("what's the Trellis roadmap position?"). If blank → restore per `.memory-backup/RESTORE-README.md`.

**Next pick-up** (unchanged): Matthew's call — first GitHub publish and/or start `packages/trellis-tui/`. Next session expected in the renamed folder; rebuild `.venv` there if needed.

---


## 2026-06-05 — Session 28: Part 4 #6/#7/#8 — Tier-2 discovery proof — **PUBLICATION GATE CLEARED**

**What got built**
- **`packages/trellis-mathpack/scripts/tier2_discovery_check.sh`** — the runnable Tier-2 proof (89 lines). Resolves the repo root from its own location, builds a throwaway off-mount venv (`mktemp`), editable-installs the core then mathpack, and runs two embedded checks:
  1. **Auto-discovery proof** — a *fresh interpreter* does only `import trellis` (never imports `trellis_mathpack`, never calls `setup()`) and confirms `=COSH(0)`→1.0, `=SQRT(-1)`→`#NUM!`, `=STDEV(1..5)`→1.58…, and that all 20 functions are registered. This is the end-to-end gate: a real `pip install` user gets the functions for free at import time.
  2. **Negative control** — with `TRELLIS_DISABLE_PLUGIN_DISCOVERY=1`, the functions are absent and `=COSH(0)`→`#NAME?`. Proves it's genuinely the entry point doing the work, not an import side effect.
- README "Develop / test" section finished: documents both tiers and points at the script; notes the `--ignore-requires-python` reason.

**Verified (the gate itself)**
- Ran the script clean from scratch: editable-installed `trellis 0.0.1` + `trellis-mathpack 0.1.0`, entry point `mathpack = trellis_mathpack:setup` registered under `trellis.plugins`, **both checks passed, exit 0.**
- Tier-1: **32 mathpack tests pass**; core suite still **748**.
- No build pollution in the tree (hatchling editable writes nothing into the source dir; no stray `*.egg-info`/`build/`).

**Resolved: the design's open question.**
- *"Is the core `pip install -e .`-able as-is?"* — **Yes.** It installed editably with no mount permission quirk (the quirk is git-index / file-delete, not pip). The only wrinkle: the sandbox is Python 3.10 while the project declares `requires-python >= 3.11`, so the install needs `--ignore-requires-python` (the code runs fine on 3.10 — the suite does; the floor is just a declared baseline). The script passes that flag with a comment; on a real 3.11+ machine it's a no-op. On the mount, the venv MUST be off-mount (`/tmp`), which `mktemp` gives by default.

**Status — Part 4 COMPLETE. The publication gate ([[trellis-publication-gated-on-client]]) is CLEARED.**
- design.md Part 4 table: #1–#8 all done. A real, separately-distributed consumer (`trellis-mathpack`) now exercises the entire public plugin surface — `register_function`, the `(ctx, *args)` convention, `FormulaError` as a constructed value (`#NUM!`), range/aggregate handling, and `entry_points` auto-discovery — installed and auto-loaded end-to-end.
- **Publication is now unblocked.** Per the gate memory, this was the precondition for the first GitHub push. The actual push remains Matthew's call (the `Homepage` URL in core `pyproject.toml` is still commented out, and there's no time pressure on any project). Nothing has been pushed.

**Next pick-up**
- Matthew's decision: (a) do the first **GitHub publish** (uncomment Homepage, push core + mathpack), and/or (b) start the **TUI** (`trellis-tui` sister package) — the largest remaining "is this a usable spreadsheet?" chunk and the prime consumer of the Part 3 public surface. The GUI is the exciting next milestone.

---

## 2026-06-05 — Session 27: Part 4 #5 — finalise `setup()` + hermetic discovery test

**What got built** (`packages/trellis-mathpack/`)
- **Single source of truth for registration.** Added `_registrations()` (yields `(name, impl)` for all three groups) and made `setup()` a one-liner loop over it. The three group dicts (`_UNARY_MATH`/`_SPECIAL`/`_STATS`) are now enumerated in exactly one place.
- **Public `FUNCTIONS` tuple** — sorted names of all 20 functions, exported in `__all__`. Lets callers/tests introspect the pack without invoking it (e.g. assert no built-in clashes, or generate the README table).
- **`setup()` docstring tightened** to state the contract plainly: discovered via the `trellis.plugins` entry point, called once at `import trellis`, **import alone registers nothing** (registration happens only in `setup()`), idempotent.
- **Real hermetic discovery tests** (`tests/test_discovery.py`, replacing the placeholder): uses the same duck-typed `FakeEntryPoint` pattern as core's `tests/test_plugin_discovery.py` to drive `load_plugins([...])` — proving the wiring end-to-end without an install. Covers: `FUNCTIONS` matches exactly what `setup()` registers (and is length 20); **import-alone-registers-nothing**; `load_plugins([FakeEntryPoint("mathpack", setup)])` returns `["mathpack"]` and makes `=COSH(0)` evaluate to 1.0; and a **broken sibling plugin** warns-and-skips while mathpack still loads.

**Why this matters for the gate**
- #5 was meant to be a confirm-and-tidy, and it was — no behaviour change to the functions. But the hermetic discovery test now proves the *contract* the Tier-2 (#7) editable-install proof relies on: that `import` is inert and `setup()` is the sole registrar. If #7 ever fails, this test localises whether the bug is in the wiring (here) or the packaging/metadata (there).

**Verified**
- mathpack suite: **32 passed** (26 in `test_mathpack.py` + 6 in `test_discovery.py`).
- `FUNCTIONS` == the 20 registered names; **0** collisions with the 24 built-ins.
- Core suite still **748**.

**Status**
- Part 4 table: #1–#5 done. The package is feature-complete and its wiring is proven hermetically. Remaining are the verification milestones: **#6** Tier-1 sign-off (effectively already green — the per-function + discovery tests all pass), **#7** the Tier-2 editable-install discovery proof, **#8** gate sign-off.

**Next pick-up**
- **Part 4 #7 is the real remaining work** (#6 is essentially done): script the editable-install discovery proof. Per the design's open question and the mount quirks already logged, this needs an **off-mount venv** — `pip install -e .` (core) + `pip install -e packages/trellis-mathpack` into a venv under `/tmp`, then a fresh `python -c "import trellis; ...=COSH(0)..."` with NO manual setup() call, confirming auto-discovery. Then #8 signs off and clears the first GitHub push — after which the TUI (`trellis-tui`) becomes the next milestone.

---

## 2026-06-05 — Session 26: Part 4 #4 — mathpack range stats + `_collect_numerics`

**What got built** (`packages/trellis-mathpack/src/trellis_mathpack/__init__.py`)
- **3 range-aware statistics**, registered in `setup()` alongside the scalars (20 functions total now): `STDEV` (sample, n−1), `VAR` (sample, n−1), `MEDIAN`. Backed by Python's `statistics` module (`stdev`/`variance`/`median`); a `_make_stat(name, fn)` factory gives them the registry shape.
- **`_collect_numerics(args)`** — the range-flattening helper, mirroring core `builtins._collect_numerics` in structure: a `FormulaError` anywhere (scalar or inside a range) propagates immediately; **inside a range**, `int`/`float` are collected and `bool`/`str`/`None`/other are silently skipped (Excel rule — STDEV ignores text/logicals/blanks); **as a scalar**, `None`→0 and any `bool`/other non-number → `#VALUE!` (mathpack's bool-is-not-a-number stance, consistent with `_num`).
- **Too-few-points → `#DIV/0!`.** `statistics` raises `StatisticsError` when `STDEV`/`VAR` get <2 points (or `MEDIAN` gets 0); the factory catches it and returns core `DIV0`. So `STDEV(5)`, `VAR()`, `MEDIAN()` all → `#DIV/0!`.

**Design calls worth remembering**
- **Scalar/range asymmetry is intentional and idiomatic.** Inside a range, a non-number is skipped; as a bare scalar it's `#VALUE!`. Core's aggregates have the exact same asymmetry (scalar text → VALUE, range text → skip), so mathpack matches it — with the one mathpack twist that scalar `bool` is `#VALUE!` rather than counted as 1/0.
- **Sample stats (n−1), matching Excel's unsuffixed `STDEV`/`VAR`.** Population variants `STDEVP`/`VARP` remain deferred.
- **Kept everything in `__init__.py`** — 20 fns + 3 helpers is still comfortable; the design's "split only if unwieldy" bar isn't met.

**Tests** — `tests/test_mathpack.py` +9 (now 26 in that file, 27 incl. the discovery placeholder): stats over a range, mixed scalars+ranges, `<2`-points → `#DIV/0!`, `MEDIAN` 0/1-point, text/bool/blank skipped inside a range, scalar non-number → `#VALUE!`, error-in-range propagation (via a **`Workbook`** so the `=SQRT(-1)` cell actually recalculates to `#NUM!`), and a direct unit test of `_collect_numerics`. All pass.

**Verified**
- mathpack: **27 passed**.
- `setup()` adds exactly **20** names, **zero** collisions with the 24 built-ins.
- Core suite still **748** — mathpack doesn't touch core.
- Gotcha re-confirmed: a bare `Sheet` has no recalc engine, so a formula stored in a cell isn't evaluated (`.value` stays `None`); use a `Workbook` (auto-attaches recalc) when a test needs a stored formula to compute.

**Status**
- Part 4 table: #1–#4 done. **All 20 functions implemented.** Next: **#5** — review/finalise `setup()` (it already registers all three groups; mostly a confirm-and-tidy pass) → then #6 Tier-1 sign-off, #7 Tier-2 editable-install discovery proof + README finish, #8 gate sign-off.

**Next pick-up**
- Part 4 #5: confirm `setup()` is the single clean wiring point (it is — three loops over `_UNARY_MATH`/`_SPECIAL`/`_STATS`); decide if anything should move to a `_functions.py` (current call: no). Then the real work is #7, the editable-install discovery test — which needs an off-mount venv (mount editable-install + pytest-tempdir quirks).

---

## 2026-06-05 — Session 25: Part 4 #3 — mathpack scalar functions + `NUM` + `_num`

**What got built** (`packages/trellis-mathpack/src/trellis_mathpack/__init__.py`)
- **17 scalar functions**, all new names, registered in `setup()`: trig `SIN COS TAN ASIN ACOS ATAN` (radians), hyperbolic `SINH COSH TANH`, powers/logs `SQRT POWER EXP LN LOG`, misc `MOD SIGN PI`. Range stats (`STDEV/VAR/MEDIAN`) are still #4.
- **`NUM = FormulaError("#NUM!", ...)`** minted locally — the headline demo that errors are values you construct (core has no `#NUM!`). Returned for `SQRT(<0)`, `ASIN/ACOS` outside `[-1,1]`, `LN/LOG(<=0)`, invalid `LOG` base, and `POWER`/`EXP` overflow.
- **`_num(x)` guard** — `None`→0, `int`/`float` pass through, **`bool`→`#VALUE!`** (the one deliberate deviation from core's `_coerce_scalar_number`, consistent with `ISNUMBER`/range-aggregation treating bools as non-numbers), list/str/other→`#VALUE!`, `FormulaError` passes through.
- Implementation shape: a `_make_unary(name, fn)` factory for the 13 one-arg functions (arg-count check → `_num` → stdlib `math` call wrapped so `ValueError`/`OverflowError` → `NUM`); explicit bodies for `POWER` (2-arg), `LOG` (1-or-2-arg, base must be `>0` and `≠1`), `MOD` (2-arg; `MOD(x,0)`→core `DIV0`, *not* `NUM`; Python `%` already matches Excel's sign-of-divisor), and `PI` (0-arg).

**Design calls worth remembering**
- **`_num` reconciles a small spec/code mismatch.** design.md goal 2 says "reject bool … require int/float (else #VALUE!)" while also saying `_num` "mirrors `_coerce_scalar_number`" — but the core helper actually coerces bool→int and None→0. Resolved by treating **bool-rejection as the single intended deviation** and otherwise mirroring core (so `None`→0, empty-cell-as-zero, stays Excel-faithful: `COS(<empty>)`=1). Flagged for Matthew in case he wants strict None→`#VALUE!` instead — one-line change.
- **`POWER` domain errors → `NUM`** (e.g. `POWER(-2,0.5)`), per design, even though Excel returns `#DIV/0!` for `0^negative`. Uses `math.pow` so those raise `ValueError` and get caught.
- **Registration happens in `setup()`, not at import.** Functions are module-level (testable) but `register_function` is only called from `setup()`, preserving the entry-point contract (import alone must not register — the discovery test in #7 depends on this).
- **Kept everything in `__init__.py`** (the design's "start there, split only if unwieldy" open question). 17 fns + helpers is comfortable; revisit at #4 if stats push it over.

**Tests** — `tests/test_mathpack.py` rewritten from placeholder: **18 Tier-1 tests**, driven through the real `parse_formula`→`evaluate` stack (mirroring core's `test_formula_builtins.py`), with a fixture that snapshots `_REGISTRY`, calls `setup()`, restores after. Covers happy paths, every `#NUM!` domain path, `MOD→#DIV/0!`, bool→`#VALUE!` (fed via a cell, since `TRUE`/`FALSE` are literals not callables), string→`#VALUE!`, error-arg propagation, wrong-arg-count→`#N/A`, and empty-cell→0. All 18 pass.

**Verified**
- mathpack Tier-1: **18 passed**.
- Collision smoke: `setup()` adds exactly **17** names, **zero** collide with the 24 built-ins.
- Core suite still **748** (`PYTHONPATH=src pytest tests/ --doctest-modules src/trellis`) — mathpack doesn't touch core.
- pytest still needs `--basetemp=/tmp/... -p no:cacheprovider` to avoid the mount temp-cleanup `RecursionError` (see [[git-commit-on-mount]] / Session 24 note).

**Status**
- Part 4 table: #1, #2 done; **#3 done**. Next: **#4** — range-aware `STDEV`/`VAR`/`MEDIAN` + a `_collect_numerics`-style flattener (lists flatten, `FormulaError` inside a range propagates, bools excluded, `<2` values → `#DIV/0!` via `statistics.StatisticsError`).

**Next pick-up**
- Part 4 #4: implement the three range stats using Python's `statistics` module; add the flatten helper; land with unit tests. Then #5 setup finalise → #6/#7 test tiers → #8 gate sign-off.

---

## 2026-06-05 — Session 24: Part 4 #2 — scaffold `packages/trellis-mathpack/`

**What got built** (structure only — no function code yet, by design)
- New `packages/trellis-mathpack/` subdir of the repo with the layout from design.md Part 4:
  - `pyproject.toml` — `name = "trellis-mathpack"`, `version = "0.1.0"`, `dependencies = ["trellis"]` (unpinned, per the pre-publication decision), hatchling build over `src/trellis_mathpack`, and the load-bearing line: `[project.entry-points."trellis.plugins"]  mathpack = "trellis_mathpack:setup"`.
  - `src/trellis_mathpack/__init__.py` — module docstring (why this package exists, how discovery works, the public-surface-only and mint-your-own-`#NUM!` design notes) + `__version__` + a **placeholder `setup()` that is a deliberate no-op** with a TODO pointing at #3–#5.
  - `README.md` skeleton — purpose, local editable-install instructions (both core + pack), the function table, the error-behaviour summary (incl. the `MOD→#DIV/0!` exception to `#NUM!`), and the two-tier test commands.
  - `tests/test_mathpack.py` + `tests/test_discovery.py` — placeholder tests (import + `setup()` callable + version) standing in for the Tier-1 / Tier-2 suites that land in #6/#7.

**Verified**
- `PYTHONPATH=src:packages/trellis-mathpack/src python3 -c "import trellis_mathpack; trellis_mathpack.setup()"` — imports clean, `setup()` returns `None`.
- `import trellis` still resolves; core function count unchanged at **22 registered** (mathpack adds none yet, as intended — no collision).
- Both placeholder tests pass (`2 passed`).
- Core suite untouched (no edits under `src/trellis` or `tests/`; root `testpaths=["tests"]` doesn't pick up the new `packages/` dir) — remains at **748**.

**Quirk worth remembering (relevant to the #7 Tier-2 open question)**
- Running pytest with its default `basetemp`/cache *on the mount* throws `RecursionError` during temp-dir cleanup (the mount permission quirk flagged in past logs). Fix: run with `--basetemp=/tmp/... -p no:cacheprovider` (point temp off the mount). The Tier-2 editable-install discovery test should plan for a real off-mount venv/tmp for the same reason.

**Status**
- Part 4 table: #1 (scope) done, **#2 (scaffold) done**. Next: #3 scalar fns (trig/hyperbolic/powers-logs/misc) + the `NUM` constant + the `_num` helper.

**Next pick-up**
- Part 4 #3: implement the scalar functions in `__init__.py` (or split into `_functions.py` if it gets unwieldy), define `NUM = FormulaError("#NUM!", ...)`, add the `_num(x)` type guard mirroring the built-ins' `_coerce_scalar_number`, and wire them into `setup()`. Land with their unit tests.

---

## 2026-06-03 — Session 23: scoped Part 4 — trellis-mathpack (the publication gate)

**What got built** (planning only, no package code)
- `design.md` — appended **Part 4: `trellis-mathpack`**, a full scope for the reference plugin package. Confirmed with Matthew: useful focused pack (~20 fns), lives as `packages/trellis-mathpack/` subdir of this repo, shipped as a real installable companion package.
- Scope covers: purpose (clears the `trellis-publication-gated-on-client` gate + becomes the reference plugin), package layout + pyproject/entry-point, the ~20-function set (trig 6, hyperbolic 3, powers/logs 5, misc 3, range stats 3), design decisions, two-tier testing, rejected/deferred alternatives, open questions, and an #1–#8 implementation table.

**Design calls worth remembering**
- **mathpack mints its own `#NUM!`.** Core has DIV0/VALUE/REF/NAME/CIRC/NA/NULL but no NUM. Rather than add it to core, the package defines `NUM = FormulaError("#NUM!")` locally for domain errors (SQRT(<0), LN(<=0), ASIN/ACOS out of range). Best single proof that "errors are values you construct." `MOD(x,0)` still uses core DIV0 (Excel-faithful).
- **Audit confirmations baked into the scope:** range args arrive as **lists** (flatten via a `_collect_numerics`-style helper, propagate any FormulaError found inside); the evaluator short-circuits a top-level FormulaError arg before the fn runs (so scalar fns skip that check, aggregates don't); **zero-arg calls work** (`=PI()` parses+evaluates — verified live, and `test_zero_arg_function` already exists for `NOW()`).
- **Two test tiers.** Tier 1 hermetic (call `setup()` / FakeEntryPoint + per-fn units, no install) runs in the normal style; Tier 2 (editable install + fresh-interpreter `import trellis` auto-discovery of `=COSH(0)`) is the actual gate proof. Open question flagged: confirm the core `pip install -e .` works cleanly in a venv (past editable-install permission quirk on the mount).
- **Strictly public surface.** If mathpack needs a core internal, that's a core public-surface bug to fix — which is part of what this exercise is meant to surface.

**Status**
- Suite unchanged at 748. Part 4 is scoped (table #1 done); #2–#8 are the build/verify chunks.
- This is the last planned milestone before Trellis can go public: when mathpack installs, auto-loads, and evaluates green, the publication gate is cleared.

**Next pick-up**
- Part 4 #2: scaffold `packages/trellis-mathpack/` (pyproject with the `trellis.plugins` entry point, src/ layout, README skeleton). Then #3 scalar fns → #4 stats → #5 setup wiring → #6/#7 the two test tiers → #8 gate sign-off.

---

## 2026-06-03 — Session 22: Part 3.4 — meta-namespacing convention (task #7) — Part 3 COMPLETE

**What got built** (pure docs, no code)
- `docs/plugin-example.md` — new section "Namespacing your cell / sheet / workbook metadata" with the good/bad pair (own one top-level key per plugin, keep state in a dict under it vs flat keys that collide). Frames it as convention-not-enforcement and points at the open-extensibility philosophy; suggests the distribution name as the default key.
- `CLAUDE.md` — one-line cross-ref under Conventions: plugins namespace `meta` keys under a single plugin-named key, see `docs/plugin-example.md`.
- `design.md` — table row #7 DONE. **All of Part 3 (#1–#7) now complete** bar #8 (this verification/WORKLOG step).

**Status**
- No code change this session; suite remains at **748 passing**.
- **Part 3 "pre-render engine prep" is done.** Recap of what shipped across Sessions 19–22:
  - 3.1 — locked `cell:change`/`cell:recalc` payload (sheet, tuple address, old/new value+formula, live old/new Cell, recalc `trigger`).
  - 3.2 — `Sheet.batch()` (buffer writes, one `sheet:batch`, deferred recalc via Replay; `read_csv` refactored onto it).
  - 3.3 — public `Sheet.used_range()`; `write_csv` refactored onto it.
  - 3.4 — meta-namespacing convention documented.
- The public surface the TUI / external plugins depend on is now hardened ahead of going public. Deferred: `MAX_RECALC_DEPTH` guard (design.md Open Questions), the recalc dedupe-once optimisation (only if a perf need appears).

**Next pick-up**
- The big one: **plugin example package (`trellis-mathpack`)** — a separate installable that exercises the `entry_points` discovery end-to-end. This is the publication gate (per the `trellis-publication-gated-on-client` memory: no GitHub push until a real consumer has exercised the API). Once it's green, Trellis can go public.
- Alternatively, the TUI (`trellis-tui` sister package) — the largest remaining "is this a usable spreadsheet?" chunk, and the prime consumer of the Part 3 surface.
- Matthew's call on order.

---

## 2026-06-03 — Session 21: Part 3.3 — promote used_range() to public (task #6)

**What got built**
- `src/trellis/core/sheet.py` — new public `Sheet.used_range() -> ((min_row,min_col),(max_row,max_col)) | None`. Bounding rectangle (both corners inclusive, zero-indexed) over every cell where `not cell.is_empty()`; `None` when nothing qualifies. Listed in the public-surface docstring. Single-pass implementation over `_cells`.
- `src/trellis/io/csv.py` — `write_csv` refactored to call `sheet.used_range()` instead of computing `max_row`/`max_col` from raw `_cells` keys. CSV still anchors at A1, so only the max corner is used; the empty-file early-return now keys off `bounds is None`. Docstring updated to describe the non-empty semantics.
- Tests: `tests/test_sheet.py` +9 — empty→None, single, sparse true-min/max, empty-string counts, set-to-None excluded, deleted excluded, formula-with-None-value counts, meta-only counts, and a CSV guard that an all-empty sheet writes an empty file.
- `design.md` — table row #6 DONE; the `used_range` None-counting open question resolved. `README.md` — `used_range()` documented in the events/introspection section.

**Design calls worth remembering**
- **Definition is `not cell.is_empty()`, not key-presence.** Counts value cells (incl. `""`), formula cells (even with a `None` value — renderer correctness), and meta-only cells; excludes truly-empty cells (a `sheet.set(addr, None)` stores an *empty* cell) and absent/deleted cells. This is what the 3.3 plan's tests require ("empty string counts", "set to None does NOT count").
- **Audit finding: old `write_csv` bounded by key presence**, so it *did* count present-but-empty cells. The refactor changes that in exactly one untested edge case — a trailing explicit-empty cell no longer pads the export (e.g. `A1="a"; B1=None` now writes `a`, not `a,`). Arguably a fix; flagged for Matthew. No existing test put an empty cell at the extreme of the box, so the suite is unaffected.
- **CSV anchors at origin**, so `used_range`'s min corner is intentionally ignored by `write_csv` (it walks rows `0..max_row`, cols `0..max_col`). `used_range` still reports the true min for renderers that want it.

**Status**
- **748 passing** (739 prior + 9 new) incl. 7 doctest modules. Python 3.10 in-sandbox; baseline 3.11+ (annotation-safe).
- Part 3.3 complete (design.md table #6 DONE).

**Next pick-up**
- Part 3.4: **document the meta-namespacing convention** — pure docs. Add the good/bad `cell.meta["<plugin>"][...]` example to `docs/plugin-example.md` and a one-line cross-ref in `CLAUDE.md` under Conventions. No code. Closes Part 3.
- After 3.4: the plugin example package (`trellis-mathpack`) for the publication gate — the last thing before Trellis can go public.

**Tool notes**
- Source edits via python string-replacement on the mount + import smoke + `git diff` verification. WORKLOG spliced from `/tmp` with sha256 check.

---

## 2026-06-03 — Session 20: Part 3.2 — Sheet.batch() (tasks #4, #5)

**What got built**
- `src/trellis/core/sheet.py` — `Sheet.batch()` context manager + module-level `_BatchContext`. New per-instance state `_batch_depth` / `_batch_changes`. `set`/`delete` now funnel through `_emit_or_buffer_change(key, old, new)`, which builds the locked Part 3.1 change dict and either emits `cell:change` (normal) or appends to the buffer (inside a batch). On the **outermost** clean exit the sheet emits one `sheet:batch` carrying `sheet` + `changes` (list of per-cell dicts in write order, each = a `cell:change` payload minus `sheet`). Public-surface docstring lists `sheet.batch()`.
- `src/trellis/formula/recalc.py` — engine now subscribes to **both** `cell:change` and `sheet:batch` per sheet; `_sheet_subs[name]` holds a list of subscriptions (detach + `_on_sheet_remove` updated to unsubscribe all). New `_on_batch` replays each buffered change through `_on_cell_change` — normal per-cell path, so per-cell `trigger` is preserved.
- `src/trellis/io/csv.py` — **bonus refactor landed.** `read_csv` loads inside `with sheet.batch():`, writing `Cell` instances via `sheet.set` (Cell-instance path bypasses the leading-`=` formula sugar, preserving the literal-text policy). One `sheet:batch` per load instead of N silent direct-writes; formulas in a target workbook that reference the loaded region now recompute once on exit (previously they silently didn't). `_make_cell` docstring refreshed.
- `src/trellis/core/workbook.py` — docstring hint now points at `with sheet.batch(): ...` as the structured bulk-write path (detach still mentioned as the skip-recalc-entirely escape hatch).
- Tests: `tests/test_sheet.py` +7 (suppression+one event, record shape, immediate store visibility, exception propagate/no-rollback/depth-unwind, nested flatten, empty-batch-silent, buffered delete). `tests/test_recalc.py` +4 (defer-until-exit, formula-set-in-batch registers on exit, per-cell trigger on replay, detach unsubscribes batch too). `tests/test_io_csv.py` +2 (single sheet:batch per load, leading-`=` stays literal after refactor).
- `README.md` — `sheet:batch` added to the events list. `design.md` — table rows #4/#5 marked DONE; the recalc-integration decision (Replay, per-cell trigger, read_csv refactored) recorded under subtask 3.2.

**Design calls worth remembering**
- **Batch ↔ recalc = Replay, not dedupe** (Matthew's call). Engine replays each buffered change per-cell on `sheet:batch`; a dependent fed by several batched inputs may recompute >1×, and each `cell:recalc` keeps its own per-cell `trigger`. Simpler engine, no combined-propagation solver — per `simplicity-over-clever-solvers`. Dedupe-once stays available if a perf need ever shows up.
- **`read_csv` refactor is a net correctness win, not just an API proof.** CSV never loads formulas (literal-`=` policy), so the replay is a cheap no-op for fresh loads; but loading into a workbook whose formulas reference the region now recomputes them (previously a silent gap). Cost on the CSV hot path is a few dict lookups per cell — acceptable given `trellis-file-io-csv-only`.
- **No rollback on exception, by design.** Cells written before the raise stay written; the buffered `sheet:batch` is discarded; depth unwinds cleanly via the nested-decrement. Transactional behaviour is a plugin's job.
- **`MAX_RECALC_DEPTH` deferred (Matthew).** Replay raised the question; cycles are already handled (`_would_cycle` → CIRC, `_processing` re-entry guard, `_propagate` topo `None` fallback), so a depth cap is redundant belt-and-suspenders today. Documented in design.md Open Questions as a guard to wire in when iterative/cross-sheet calc lands.

**Status**
- **739 passing** (726 prior + 13 new) incl. 7 doctest modules, via `PYTHONPATH=src pytest tests/ --doctest-modules src/trellis`. Python 3.10 in-sandbox; baseline is 3.11+ (annotation-safe, re-confirm on 3.11 if convenient).
- Part 3.2 complete (design.md table #4, #5 DONE).

**Next pick-up**
- Part 3.3: **promote `used_range()` to public `Sheet` API** (lift the bounding-rect helper out of `io/csv.py`, refactor `write_csv` to call it). Small — design says skip the spec step. Watch the audit question: do explicit-`None` / empty-string cells count? (write_csv's current behaviour is the reference.)
- Then 3.3 → 3.4 (meta-namespacing docs, pure docs). After that the plugin example package (`trellis-mathpack`) for the publication gate.

**Tool notes**
- Source edits via python string-replacement on the mount + import smoke + `git diff` verification (Edit-truncation caution). WORKLOG spliced from `/tmp` with sha256 check.

---

## 2026-06-03 — Session 19: Part 3.1 — event payload lock-in (tasks #2, #3)

**What got built**
- `src/trellis/core/sheet.py` — `cell:change` and `cell:recalc` payloads reshaped to the locked Part 3.1 contract. Both now emit: `sheet` (the Sheet), `address` (zero-indexed `(row, col)` tuple, replacing the old `addr` A1-string key), `old_value`/`new_value`, `old_formula`/`new_formula`, and the live `old`/`new` `Cell` objects. `_set_value` gained a keyword-only `trigger: tuple[int,int] | None = None` param and `cell:recalc` carries it. `set`/`delete`/`_set_value` emit blocks rewritten; module docstring updated; the class doctest updated (address is now a tuple — `[(0, 0), (1, 1)]`).
- `src/trellis/formula/recalc.py` — internal consumer updated to the new shape. The `cell:change` subscriber lambda is now `lambda **ev: self._on_cell_change(ev["sheet"], ev["address"], ev["old"], ev["new"])`. `_on_cell_change` takes an `address` tuple. `trigger = (key[1], key[2])` (the originating user-changed cell) is derived in `_process_change` and threaded through `_propagate`, `_evaluate_and_write`, `_write`, and the NAME/CIRC `_set_value` calls, so every recalc in a cascade reports the cell that started it.
- `tests/test_sheet.py` — 6 new named contract lock-in tests (`...carries_old_and_new_value`, `...address_is_zero_indexed_tuple`, `...includes_sheet`, `...includes_formula_source_when_set`, `...includes_live_cell_objects`, `...on_delete_blanks_new_fields`). Existing event handlers migrated to `**ev` + `to_a1(*ev["address"])`.
- `tests/test_recalc.py` — 3 new contract tests (`...includes_trigger_cell`, `...trigger_is_none_for_standalone_set_value`, `...carries_value_and_formula_fields`). Existing handlers migrated.
- `tests/test_range.py` — 2 event handlers migrated.
- `README.md` — events example + "Events emitted today" list rewritten to the new payload (handlers take `**ev`; documents all fields incl. `trigger`).
- `design.md` — the two 3.1 open questions marked DECIDED; implementation table rows #2/#3 marked DONE.

**Design calls worth remembering**
- **Address is a tuple, not an A1 string.** Payload key renamed `addr` → `address`, value is `(row, col)`. `to_a1(*address)` at the human edge. (Matched the doc's lean.)
- **Live `Cell` is included AND the scalar fields.** Matthew chose this *against* the doc's original lean (which was values-only). Rationale: sharp-tools/give-everything, and it keeps every existing `old`/`new` subscriber — including the recalc engine, which reads `new.formula` — working unchanged. Mutation-during-emit is accepted as the handler author's responsibility.
- **`trigger` = the originating user-changed cell, shared across the whole cascade.** Setting a formula cell fires its own `cell:recalc` with `trigger` == its own address; dependents fire with `trigger` == the user-changed cell. Confirmed by smoke test: `B1='=A1*3'` then `A1=4` → B1 recalc with `trigger=(0,0)`.
- **Handlers now effectively must take `**kwargs`.** `Emitter.emit` does `handler(**payload)`, so with 8 keys a fixed-signature handler `lambda addr, old, new` raises. All internal handlers and the README example use `**ev`. Worth a note in the eventual plugin docs.

**Status**
- **726 passing** (719 tests + 7 doctest modules) via `PYTHONPATH=src pytest tests/ --doctest-modules src/trellis`. Was 710 pre-change; +9 new contract tests, ~17 existing handlers migrated, 0 regressions.
- Ran under Python 3.10 in this sandbox (no 3.11 available); project baseline is 3.11+. Code uses only `from __future__ import annotations`-safe typing, so this is a test-runner caveat, not a code change — re-confirm on 3.11 if convenient.
- Part 3.1 implementation (table #2, #3) complete. design.md decisions recorded.

**Next pick-up**
- Per the Part 3 table: **#4 spec `Sheet.batch()`** (the four decisions: context-manager-only, consolidated `sheet:batch` event, propagate-no-rollback, nested-flatten) → **#5 implement + refactor `read_csv` onto it**. The locked event payload from this session is the foundation `sheet:batch` builds on.
- Then #6 `used_range()` public, #7 meta-namespacing docs.
- Plugin example package (`trellis-mathpack`) still open as the publication-gate unblocker.

**Tool notes**
- Source edits applied via python string-replacement on the mount + `git diff` verification (per the Edit-truncation caution). WORKLOG spliced from `/tmp` with sha256 check.

---

## 2026-06-03 — Session 18: Part 3 design — pre-render engine prep (planning + commit)

**What got built**
- `design.md` — appended **Part 3: Pre-render engine prep** (+181 lines). A planning-only section (no code) that hardens the four corners of the public API that get expensive to change once Trellis is on GitHub and external plugins (incl. the eventual `trellis-tui` sister package) consume it. Authored in the 2026-05-27 working pass; committed today.
- Four subtasks specced:
  - **3.1 Event payload audit + lock-in** — target shape for `cell:change` (sheet, address, old/new value, old/new formula) and `cell:recalc` (+ `trigger` cell). Both old and new so undo plugins can reverse and renderers can skip no-op repaints. Lock-in tests named as contracts.
  - **3.2 `Sheet.batch()`** — context-manager-only; suppresses per-cell `cell:change`, emits one consolidated `sheet:batch` on exit, recalcs once. Propagate-no-rollback; nested batches flatten. Bonus: refactor `read_csv` off its `_cells` bypass onto `batch()` as a real-consumer proof.
  - **3.3 Promote `used_range()` to public Sheet API** — `((min_row,min_col),(max_row,max_col)) | None`; lift the bounding-rect helper out of `io/csv.py`, refactor `write_csv` to call it.
  - **3.4 Meta-namespacing convention** — docs only; plugins namespace under `cell.meta["<plugin>"]`. Convention not enforcement, per open-extensibility philosophy.

**Design calls worth remembering**
- **3.1 is the time-sensitive one.** Its cost jumps from "fix one test" to "break N strangers' code" the moment Trellis publishes. Recommended as the next thing to implement, ahead of the plugin example package.
- **Explicit "do NOT pre-build" list** in Part 3: display formatting, undo log, viewport/window abstraction, row-indexed cache, `Cell.style` field, mechanical namespace enforcement. All renderer/plugin concerns; building them in core violates `simplicity-over-clever-solvers`.
- **Open questions deferred to the audit (#2):** include the `Cell` object in payloads or just address+values (lean: address+values, avoids mutation foot-gun); tuple vs A1 address in payloads (lean: tuple); does `used_range` count explicit-`None` cells (confirm in audit).

**Status**
- Code unchanged — Session 16–17 work (plugin discovery + CSV I/O) was already committed in `039e4a8`. This session is the design-doc catch-up only.
- `design.md` Part 3 committed. Suggested message: `docs(design): add Part 3 — pre-render engine prep plan`.
- Implementation breakdown table (#1–#8) defines the next chunk of roadmap.

**Next pick-up**
- Per Part 3's sequence: **#2 audit current event payloads** (read `events.py` + every `emit(...)`), then **#3 implement the locked-in payload shape + contract tests**. That's the highest-value, most time-sensitive work before publish.
- Then: `Sheet.batch()` (#4 spec → #5 impl + read_csv refactor), `used_range()` (#6), meta-namespacing docs (#7).
- Plugin example package (`trellis-mathpack`) still open as the publication-gate unblocker — fits after the payload lock-in.

---

## 2026-05-27 — Session 17: CSV read + write (task #4)

**What got built**
- `src/trellis/io/__init__.py` (NEW) — new subpackage, re-exports `read_csv` and `write_csv` from `trellis.io.csv`. Module docstring lays out the "core is stdlib-only; xlsx/parquet/etc. live behind optional-dependency extras" rule.
- `src/trellis/io/csv.py` (NEW, ~220 LOC) — `read_csv(path, *, sheet_name="Sheet1", encoding="utf-8", dialect="excel", workbook=None) -> Workbook` and `write_csv(sheet, path, *, encoding="utf-8", dialect="excel") -> None`. Internal helpers `_infer_value` (string → int/float/string/None) and `_stringify` (Trellis value → CSV cell text). Inside the file, `import csv as _csv` is used defensively even though Python 3 absolute imports resolve to stdlib correctly — explicit-is-better.
- `src/trellis/core/sheet.py` — added `Sheet.to_csv(self, path, *, encoding, dialect)` as a thin method that lazy-imports `write_csv` from `trellis.io.csv`. 16-line insertion before the existing iteration section. Lazy import keeps the core ↔ io coupling one-way.
- `src/trellis/__init__.py` — re-exports `read_csv` at top level, adds it to `__all__`, mentions CSV round-trip in the docstring's "Extension surface" list.
- `tests/test_io_csv.py` (NEW, 48 tests across 4 classes) — `TestInferValue` (19 unit tests on the type-inference rule), `TestReadCSV` (12 load-path tests), `TestWriteCSV` (10 save-path tests), `TestRoundTrip` (5 end-to-end tests). All hermetic via pytest `tmp_path`.
- `tests/test_public_api.py` — added `"read_csv"` to the expected-exports set. Single-line addition.

**Design calls worth remembering**
- **`_infer_value` uses a round-trip shape check.** Parsed value is accepted only if `str(parsed) == s`. This means leading zeros (`"01234"` → string, not 1234), explicit `+` signs (`"+42"` → string), whitespace (`" 42 "` → string), scientific notation (`"1e5"` → string), and trailing zeros (`"3.140"` → string) all stay as strings. Preserves significant figures and ID-shaped data (ZIP codes, phone numbers) without an explicit "is this an ID column?" hint. The pandas comparison would be `dtype=object` for those columns; we get there by default. NaN and infinities are explicitly excluded — a CSV cell holding the literal text `"nan"` almost certainly didn't mean IEEE-754 NaN.
- **Booleans are NOT inferred.** Excel's `TRUE`/`FALSE`/`True`/`true`/etc. is a minefield across data sources. Cells stay as strings; users cast explicitly if they want booleans.
- **Leading `=` text loads as a string, NOT a formula.** Critical for "open a CSV someone else made and don't get surprised by accidental formula evaluation." Recovering a formula is one explicit line: `sh["B1"] = sh["B1"].value`. The `test_formula_text_stored_literally_not_evaluated` test locks this in.
- **`read_csv` writes directly to `sheet._cells`, bypassing the public `Sheet.set` path.** Two reasons: (1) `Sheet.set` has the leading-`=` → formula sugar, which would defeat the literal-text policy. (2) Bulk-load shouldn't emit `cell:change` per cell — if a plugin is subscribed to that event, they probably don't want to be notified once per CSV row. Documented in the `_make_cell` docstring. If a use case ever needs per-cell events on load, we can add a `sheet.set(addr, value, literal=True)` kwarg later — but don't pre-build.
- **`write_csv` writes the BOUNDING RECTANGLE.** Max row × max col of populated cells; trailing empty cells within the rectangle become empty fields. CSV is rectangular by definition. Trailing-empty rows past the last populated row are NOT emitted (no point). Empty sheet writes an empty file rather than raising — "no content" is a legit state, e.g., a newly-created sheet you want to clear an output file with.
- **Formulas don't round-trip.** Save writes the computed value (`cell.value`); load reads the value back as a number/string. By design — CSV has no formula syntax. Documented in the `test_formulas_become_values_after_round_trip` test as intentional lossiness.
- **`FormulaError` values render as their code in CSV** (`"#DIV/0!"`, `"#VALUE!"`, etc.). The user sees the error rather than a confusing `FormulaError(...)` repr in their exported CSV.
- **API shape: top-level `trellis.read_csv` + `Sheet.to_csv` method.** Matthew picked "sheet.to_csv only" for the save API in the design-question pass. Asymmetric (read is top-level fn, write is method) but matches pandas mental model (`pd.read_csv` / `df.to_csv`). Adding `to_csv` to Sheet is small enough — one delegating method, lazy-imports the io module — that the core stays clean.
- **Naming the file `csv.py` (not `csv_io.py`) is safe.** Inside `trellis/io/csv.py`, `import csv` does an absolute import to stdlib `csv`. Python 3 has no implicit relative imports. I used `import csv as _csv` defensively for readability; the `_` also signals "module-private import alias."
- **Workbook is `wb["SheetName"]`, NOT `wb.sheets["..."]`.** Caught me writing the tests — `wb.sheets` is an iterator method, dict-style access goes through `__getitem__`. Fixed via sed across the test file. Worth remembering for any future code that introspects the workbook.

**Status**
- **711 tests passing** (663 prior + 48 new). Doctest still passes. Green on the (third) pytest run — first run had 16 fails from the `wb.sheets["X"]` API confusion above; sed cleanup got it to green in two passes.
- Task #4 complete. CSV file I/O end-to-end: load, save, round-trip, with bounded-rectangle semantics, type inference, formula-as-literal-text policy, and FormulaError → error-code rendering.
- Working tree has Sessions 16–17 worth of changes uncommitted on top of `f30ab34`. Suggested split for commit:
  - Commit A (Session 16): "Plugin auto-discovery via entry_points (#5): load_plugins, env kill switch, docs."
  - Commit B (Session 17): "CSV file I/O: read_csv, Sheet.to_csv, type inference, round-trip tests."
  Or fold both into a single commit if you prefer one chunk.

**Tool notes**
- All file writes used stage-in-`/tmp` + cp + sync + sha256 protocol. Unique filenames (`tio_csv_s17.py`, `wl_s17_entry.md`, etc.) to dodge the `/tmp` cross-session collision pattern that bit Session 14 and got us briefly in Session 16. One small Edit via the file tool (`test_public_api.py`, adding `"read_csv"` to the expected set) — single-line addition, within the Edit carve-out, verified.
- 3.11 venv at `/tmp/trellis_venv` from Session 16 is still usable; ran tests via `PYTHONPATH=src` to avoid the mount's editable-install permission issue.

**Next pick-up**
- Roadmap is open. Candidates:
  - **Commit + pause.** Clean stopping point — formula engine + plugin discovery + CSV all shipped. Trellis is a working, extensible, importable spreadsheet at this point.
  - **TUI work.** The biggest remaining "is this actually a spreadsheet you can use?" chunk. Textual is the chosen lib (in optional-deps as `tui`).
  - **More built-ins.** Dates (DATE, TODAY, NOW, YEAR, MONTH, DAY), VLOOKUP/HLOOKUP/INDEX-MATCH, statistical (STDEV, VAR, MEDIAN). Each is its own chunk.
  - **A plugin example package.** Build `trellis-mathpack` (or similar) as a separate installable package that exercises the entry_points discovery end-to-end. Validates the plugin story for real, not just in tests.
- Matthew's call.

---



## 2026-05-27 — Session 16: entry_points plugin auto-discovery (task #5, closes README/docs follow-up)

**What got built**
- `src/trellis/_plugins.py` (NEW, ~90 LOC) — `load_plugins(entry_points=None)` plus module constants `ENV_DISABLE = "TRELLIS_DISABLE_PLUGIN_DISCOVERY"` and `ENTRY_POINT_GROUP = "trellis.plugins"`. Scans `importlib.metadata.entry_points(group=...)` by default; tests pass duck-typed `FakeEntryPoint` objects to keep things hermetic. Each entry point's `.load()()` is called inside a `try/except Exception` — failures emit `warnings.warn(..., RuntimeWarning, stacklevel=2)` with the plugin name and `type(e).__name__: {e}`, and discovery continues with the next plugin.
- `src/trellis/__init__.py` — added `from ._plugins import load_plugins`, added `"load_plugins"` to `__all__`, called `load_plugins()` at the very BOTTOM of the module (after every public name is bound, so plugin `setup()` calls can `from trellis import register_function` without hitting partial-import errors). Module docstring's "Extension surface" list updated to include the new entry_points story. Stale "Plugin registry … arrives in task #5" line removed.
- `tests/test_plugin_discovery.py` (NEW, 17 tests, 284 LOC) — `FakeEntryPoint` dataclass for hermetic stubs, `isolate_registry` autouse fixture (snapshot/restore `_REGISTRY`), `clear_disable_env` autouse fixture. Coverage: re-export check, group constant matches pyproject, happy path (multiple plugins, empty input, default scan doesn't crash), function registration end-to-end (plugin registers `PLUGIN_DOUBLE`, formula `=PLUGIN_DOUBLE(A1)` evaluates), broken plugin warnings (name in message, exception type+message in message, others still load, multiple bad plugins each get their own warning, `ep.load()` raising is also caught), env-var kill switch (`"1"` disables, any non-empty disables, empty does not disable, disables real scan too), and one `mock.patch("importlib.metadata.entry_points")` check that the default code path is hit with the right group arg.
- `tests/test_public_api.py` — added `"load_plugins"` to the expected-exports set (one-line addition; verified with `git diff` per the folder's Edit-banned rule).
- `docs/plugin-example.md` — rewrote the "no install step today" hedge on line 9 to point readers at the new "Shipping a plugin as an installable package" section appended at the bottom. New section covers: the `setup()` no-arg callable contract, `pyproject.toml` `[project.entry-points."trellis.plugins"]` stanza, the cosh/sinh worked example, failure handling (warn-and-skip + `python -W error::RuntimeWarning` for dev), kill switch (`TRELLIS_DISABLE_PLUGIN_DISCOVERY`), and `trellis.load_plugins()` for manual / mid-process loading.
- `README.md` — replaced the misleading "coming with file I/O in task #5" sentence (past-me crossed wires — #5 is plugin discovery, not file I/O) with a new "Extending §4: Ship a plugin as an installable package" subsection covering the same ground in 6 lines.

**Design calls worth remembering**
- **The entry_points group is `trellis.plugins`, NOT `trellis.formula_functions`.** Earlier session notes had me casually writing the narrower name, but the bootstrap `pyproject.toml` chose the broader one. The broader name is the right call given the "open extensibility / chaotic good" philosophy: a plugin's setup function is opaque code and can do anything (register functions, subscribe to events, attach custom Sheet subclasses, monkey-patch the world). Locking it to "formula functions only" would be a self-inflicted wound.
- **`load_plugins()` is called at the BOTTOM of `trellis/__init__.py`, not inside `trellis/formula/__init__.py`.** This matters: plugin `setup()` callables typically `from trellis import register_function`, which only works once `trellis/__init__.py` has bound that name into its namespace. Triggering discovery inside the formula subpackage's init would fire before `trellis.register_function` is exposed at the top level. Moved it up; documented why in the comment.
- **`load_plugins(entry_points=None)` takes an optional iterable for testing.** The default code path goes through `importlib.metadata.entry_points(group=...)`, but the function is also the public API for "I want to load this specific set of plugins manually" — tests use it with `FakeEntryPoint` instances, and advanced users can use it to load plugins from a non-default source (e.g., a config file, a directory scan, a remote registry). Same surface, two use cases.
- **Exception trap is `except Exception:`, not `except BaseException:`.** Deliberately lets `KeyboardInterrupt` and `SystemExit` propagate — if a plugin is doing something weird that warrants those, we want it to bubble up, not be swallowed by the plugin loader.
- **`stacklevel=2` on `warnings.warn`** so the warning's filename/line points at the caller of `load_plugins`, not at `_plugins.py:71`. Small thing, but the difference between "user sees their `import trellis` line as the source" and "user sees Trellis internals" is night and day for debugging.
- **No retry logic, no plugin ordering, no dependency declarations.** Per the "don't pre-build sophisticated solvers" memory: discovery is a flat list, loaded in iteration order, no DAG. If someone needs plugin A loaded before plugin B, they sort it out in their entry point's `setup()`. We can revisit if a real use case demands it.

**Tool notes**
- All file writes used the stage-in-`/tmp` + `cp` + `sync` + `sha256sum` protocol from `write-protocol-mount-folders`. One small one-line addition to `tests/test_public_api.py` went via Edit (single-line addition is within the "verify with git diff" carve-out from Session 14's rule); verified the file was 202 lines after the edit and the new line was at the right place.
- Sandbox-side `git status` is still throwing the `null sha1 / index.lock` permission warning that's been background noise — Matthew's local `git status` is the source of truth, as confirmed at the start of the session.
- Test execution required spinning up a 3.11 venv outside the mount (`/tmp/trellis_venv`) because pyproject's `requires-python >=3.11` rejected the system 3.10, and the mount blocked uv from writing editable install metadata. Ran with `PYTHONPATH=src` instead of editable install. **Also tripped over a stale `/tmp/ast.py`** from a prior session that shadowed the stdlib — same `/tmp` collision pattern that bit Session 14, just a different file. Worked around by `cd /tmp/run` (subdir not on path). Worth keeping in mind: `/tmp` is shared across sessions and accumulates cruft.

**Status**
- **663 tests passing** (645 prior + 17 new + 1 doctest re-run from the package docstring). Green on the first pytest run.
- Tasks #1 and #2 in this session's TaskList complete. The plugin discovery story is end-to-end: code, tests, README, docs.
- Working tree has Session 16 worth of changes uncommitted on top of `f30ab34`. Suggested commit: "Plugin auto-discovery via entry_points (#5): load_plugins, env kill switch, docs."

**Next pick-up**
- Task #3 — the file I/O scope conversation. Matthew flagged at the start of the session that he wants to talk through complexity (xlsx vs CSV, openpyxl as opt-in, what "round-trip" should mean for formulas) before any code is written. Hold for that discussion.

---



## 2026-05-27 — Session 15: Top-level re-exports + README + plugin docs (subtask #19, closes parent #4)

**What got built**
- `src/trellis/__init__.py` rewritten — re-exports the formula engine surface alongside the core types. Users can now write `from trellis import Workbook, register_function, FormulaError, parse_formula, RecalcEngine, ...` without touching `trellis.formula.*`. Module docstring updated with a working example (`SUM(A1:A2)` evaluating, then recomputing after an input change) that runs as a doctest via `pytest --doctest-modules`.
- `README.md` — "Quick taste" section rewritten to actually exercise the engine end-to-end: set inputs, set formulas including `=IF(B1 > 50, "big", "small")`, print computed values, mutate an input, show dependents recompute. The 22-built-in list is named inline so the README's first 30 lines tell the user what's possible. "Extending §2" event-list updated to mention `cell:recalc`. "Extending §3" is no longer "(coming)" — it's the canonical `@register_function("DOUBLE")` example with a worked snippet, and links to the new docs file.
- `docs/plugin-example.md` (NEW) — full plugin author's guide: contract (`fn(ctx, *args)`), errors-as-values, the error constants, range arg handling (flat list, row-major, None for blanks, FormulaError propagation), lazy mode (with `UNLESS` as a fresh example so it doesn't just rehash IF), and the override-built-ins-at-your-own-risk note. Points readers at `builtins.py` as the canonical reference set.
- `tests/test_public_api.py` (NEW, 13 tests) — smoke test that imports EVERYTHING from `trellis` only (no `trellis.formula.X` imports). Locks in the re-exports: if someone deletes a name from `__init__.py`, the test fails loud. Covers the README "Quick taste" pattern, the §3 decorator pattern (registers `DOUBLE`, calls it from a formula), error-constants-are-FormulaError invariants, and identity checks (RecalcEngine, Emitter, Subscription all wired correctly).

**Design calls worth remembering**
- **Re-exports keep the `trellis.formula` subpackage as an implementation detail for casual users.** Power users and plugin authors still import from `trellis.formula.ast`, `trellis.formula.builtins`, etc., but the README and the doctest only show `from trellis import ...`. The package-level `__all__` is now sorted into Core + Formula sections (with `# Core` / `# Formula engine` comments) to make accidental removal during refactors more visible in code review.
- **The docstring example doubles as the smoke test.** `pytest --doctest-modules src/trellis/__init__.py` runs the README's mental model end-to-end. If a refactor breaks `Workbook` + `SUM` + recalc, the doctest fails before any unit test runs.
- **Plugin doc deliberately uses a fresh function (UNLESS) for the lazy example** instead of re-explaining IF. Two reasons: (a) IF is already documented inline in `builtins.py`, (b) the reader sees that lazy isn't only for "the obvious" control-flow cases — anything that wants to *decide* whether to evaluate an argument benefits.

**Status**
- **645 tests passing** (632 carried + 13 new). The package-docstring doctest also passes via `pytest --doctest-modules`. Green on the first run.
- **Subtask #19 complete, which closes parent task #4 (the formula engine).** End-to-end: parser, AST, evaluator, function registry, 22 built-ins, recalc engine, Sheet/Workbook integration, top-level public surface, plugin author docs.
- Working tree includes Sessions 12–15 worth of source and worklog entries on top of the bootstrap commit. Time for a checkpoint commit (Matthew has the commit message draft from end-of-Session-14; this session's additions are README/docs/re-exports/smoke-test glue and can roll into the same commit, OR split into a doc-focused follow-up — Matthew's call).

**Next pick-up**
- Task #5 — `entry_points`-based auto-discovery for plugins. The decorator surface is locked in; what's missing is "I `pip install trellis-mathpack` and `=COSH(A1)` just works." Small wiring layer: scan `entry_points` group `"trellis.formula_functions"` on package import, call each registered hook. ~20–30 LOC plus a fixture/test plugin.
- Or shift gears entirely: file I/O (CSV in first, then `.xlsx` behind an optional dep). Both are smaller-than-#4 chunks; can pick either.

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
- Task #2 (core data model) paren