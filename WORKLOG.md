# Trellis worklog

A session-by-session record of what was built, decided, and discovered. Newest entries on top.

---

## 2026-06-20 — Session 41 (build, cont.): Part 12 row 3 — cross-sheet *syntax* (parse-only)

Built **Part 12 row 3**: `Sheet2!A1` now lexes and parses into the AST (no resolution yet — row 4).
`formula/ast.py`: `CellRef` gains `sheet: str | None = None` (the name as written, `None` = holding
sheet; participates in AST equality, invisible to the `(row,col)` coordinate identity). `formula/
lexer.py`: two new token kinds — `BANG` (`!`, via `_PUNCT`) and `QUOTED_NAME` (`'My Data'` with `''`
escaping, a branch mirroring the double-quote string lexer). `formula/parser.py`: `_parse_ident`
checks for a trailing `!` FIRST (a name before `!` is a sheet even if it spells a function `Sum!A1` or
bool `TRUE!A1`); the cell/range body is factored into `_parse_cell_or_range` (stamps `sheet` on every
CellRef; the sheet binds the whole range, and a sheet on the range END corner — `A1:Sheet!B2` — is a
parse error); `_parse_quoted_sheet` handles the `'..'!ref` path.

**Tests:** +6 lexer (BANG, QUOTED_NAME, `''` escape, unterminated, `#REF!` stays one ERROR token) and
+12 parser (qualified cell/range, quoted sheet, `$` pins, range-end-qualified error, bang-without-ref
error, sheet-name-beats-function/bool, plain ref stays `sheet=None`, equality). **Core 825 → 843,
green** (incl. doctests). Smoke-checked end to end: the engine ingests `=Sheet2!A1` without crashing
and preserves the formula text (resolves to the *holding* sheet for now — documented intermediate
state until row 4 wires `extract_deps` name→id + `Context.workbook` eval).

**Known follow-up (flagged):** `formula/shift.py` is token/text-based and unaware of `!` — copying a
formula with a cross-sheet ref (clipboard/fill shift) could mis-handle the `Sheet2` token. Out of
scope for rows 3-5 as written; revisit when cross-sheet meets clipboard. **Uncommitted** (no sandbox
git creds) — files: `formula/ast.py`, `lexer.py`, `parser.py`, `tests/test_formula_lexer.py`,
`tests/test_formula_parser.py`, `design.md`, `WORKLOG.md`. NEXT: row 4 — `extract_deps` name→id
resolution, `Context.workbook`, cross-sheet eval, unknown→`NAME`/`REF`.

---


## 2026-06-20 — Session 41 (build): Part 12 row 2 — Sheet.id + recalc keyed by id (rename-desync fixed)

Built **Part 12 row 2**: the recalc graph now keys on a stable **`Sheet.id`** instead of the mutable
sheet name, retiring the S41 rename-desync bug by construction. `core/sheet.py`: a module-level
`itertools.count(1)` assigns `self.id` at construction (stable across rename, unique per instance,
session-only — never serialized). `formula/recalc.py`: `CellKey` is now `(sheet_id, row, col)`;
`extract_deps`, `_key`, `_on_cell_change`, `_process_change`, `_on_sheet_remove`, `_subscribe_sheet`/
`_on_sheet_add` and the architecture docstring all switched `sheet.name` → `sheet.id`. **Non-obvious
bit:** `_evaluate_and_write`/`_write` resolved the target via `self._workbook[key[0]]`, but `Workbook`
is *name*-keyed — so the engine now keeps its own `{sheet_id: sheet}` map (filled in `_subscribe_sheet`,
dropped in `_on_sheet_remove`, cleared in `detach`) for write-back. No new syntax; no cross-sheet refs
yet (rows 3-5).

**Tests:** `test_recalc_survives_sheet_rename` (the regression) + `test_recalc_graph_keyed_by_sheet_id_
not_name` in test_recalc.py; `test_sheet_id_is_unique_per_instance` / `..._stable_across_rename` in
test_sheet.py; updated `test_engine_cleans_up_when_sheet_removed` to assert on `sh.id` not `"S"`.
**Verified the regression has teeth:** ran it against HEAD's old name-keyed recalc in an off-mount copy
→ fails `20 == 200` (B1 stuck at 20, the exact bug); green on the new code. **Full core suite 821 →
825, all green** (incl. doctests). Edited via the /tmp-script protocol; pytest needed `pip install
pytest --break-system-packages` in the fresh sandbox.

**Uncommitted** (sandbox has no git creds). Files for Matthew's commit+push: `src/trellis/core/
sheet.py`, `src/trellis/formula/recalc.py`, `tests/test_recalc.py`, `tests/test_sheet.py`, `design.md`,
`WORKLOG.md` (+ the earlier S41 design edits). NEXT: Part 12 row 3 — lexer `!` + quoted names, parser
sheet-qualifier, `CellRef.sheet`.

---

## 2026-06-20 — Session 41 (design): cross-sheet refs design pass + a latent rename bug

Matthew opened the "how do sheet references name things?" question and we settled it in design only
(no code touched). Two decisions locked, now Part 12's "Decisions confirmed up front":
**(1) workbook-local only** — ship `=Sheet2!A1` resolving within the in-memory session; cross-*file*
`[Book]Sheet!A1` stays out and we don't even reserve `[` (illegal today → non-breaking to add later).
**(2) Stable `sheet_id`, name display-only** — the recalc graph + AST resolution key on a per-sheet
id; the name is the public string form (formula text + CSV), mirroring the A1↔(row,col) boundary.
Rename becomes a display/serialization concern, never a correctness one.

Reading the engine to ground the decision surfaced a **latent bug**: `RecalcEngine` never subscribes
to `sheet:rename` (recalc.py:157-162) yet keys the whole graph off the live `sheet.name`
(recalc.py:223, :265). So renaming a sheet silently desyncs recalc *even with no cross-sheet refs*:
a formula registered before the rename stops recomputing when its precedent is edited after, until
it's re-typed — and stale `(old, …)` keys leak across `_asts`/`_dependents`/`_dependencies`/
`_sheet_subs`. The existing rename test only asserts the status line, so it never caught this. The
`sheet_id` migration (decision 2) retires the whole bug class by construction — no band-aid rekey.

Wrote **design.md Part 12** (~80 lines, 1387→1467): boundary model; full pipeline (lexer `!` +
quoted `'My Data'` names → parser sheet-qualifier in `_parse_ident` → `CellRef.sheet: str|None` →
`extract_deps` name→id → `Context.workbook` eval); error model (`NAME` unknown sheet / `REF` removed
sheet — both constants already exist); rename text-rewrite sweep + remove→`REF` re-eval; rejected/
deferred (cross-file, `[` reservation, uuid ids, id-in-AST, Excel's destructive `#REF!`); open
questions; and a 6-row staged breakdown where **row 2 lands first** — `Sheet.id` + a standalone
*failing* rename-desync test, then the id migration that makes it pass, before any new syntax exists.
Syntax confirmed **Excel-faithful trailing `Sheet1!A1`** (a leading-`!` sigil weighed and rejected — two symbols vs one, `.`-vs-decimal collision, no Excel paste-compat). NEXT (Matthew's call): start building row 2, or land the rename-bug fix standalone first.

---


## 2026-06-17 — Session 40 (DPG spike, cont.): hybrid candidate + column-width fix

Matthew ran variants A (formula bar) and B (in-place) and picked the combination: **edit in place,
keep the formula bar up top as a status/formula line.** He also flagged the columns as too narrow.
Built **variant C `dpg_grid_hybrid.py` — the candidate**: in-place editing + a top bar showing the
cursor address, the cell's formula/value source, and `[READY]`/`[EDIT]` (live-mirrored from the cell
while editing) + **fixed-width columns**. The narrow-column root cause was `mvTable_SizingFixedFit`
with `width=-1` inputs (columns get no intrinsic width and collapse); fix = explicit
`init_width_or_weight=92` per data column + `scrollX/scrollY` — verified 92px headlessly. Also fixed
the window-title mojibake (a `·` rendered as `Â·` on Windows -> plain ASCII " - ") in all three.

Reuses `grid_model.py` + the key adapter unchanged (third view over the same model). **Spike suite:
37 headless tests green** (15 model + 9 dpg + 7 in-place + 6 hybrid). Still additive under
`spikes/dpg-grid/`. NEXT: a real-GUI prototype around variant C (selection highlight, undo via
trellis-undo, mouse drag-select, persistent column resize) when Matthew's ready to start the new
project proper.

---

## 2026-06-17 — Session 40 (DPG spike, cont.): in-place editing variant + a real bug

Matthew ran the formula-bar spike and hit `ModuleNotFoundError: trellis_keymap` (his venv predates
the extraction). Fix: the spike now self-bootstraps `sys.path` (in-repo `src` + `packages/
trellis-keymap/src`), so it runs from a checkout with only `pip install dearpygui` — plus a
`conftest.py` for pytest. That run also exposed a genuine bug `load_model` had: `Workbook.sheets`
is a METHOD, not a property — now `wb[next(iter(wb))]` (covered by two new tests).

Then built **variant B, in-place editing** (`dpg_grid_inplace.py`) alongside variant A (formula
bar): the cursor cell IS the editor, modal like Excel — READY (arrows nav via ExcelKeymap) vs EDIT
(F2/type begins; the cell's input owns the keyboard; Enter commits+down, Tab commits+right, Esc
cancels; global handler gated on an `editing` flag). Reuses `grid_model.py` and the key adapter
unchanged — same engine, same keymap, two feels. README now compares them and lists the frictions
variant B surfaces (modal arrows, type-to-replace timing, click-gives-a-caret) for Matthew to judge
live. **Spike suite: 31 headless tests green** (15 model + 9 dpg + 7 in-place). Still additive,
its own dir; nothing to commit beyond `spikes/dpg-grid/`.

---

## 2026-06-17 — Session 40 (later still): DearPyGui spike — proving the new-GUI seam

**Context:** Matthew is scoping a new project with a new GUI (likes DearPyGui, happy owning the
input/render layer). Built a spike to pressure-test DPG ergonomics AND to validate that the S40
packaging + trellis-keymap extraction actually pay off for a second frontend.

**What landed** (`spikes/dpg-grid/`, a throwaway/seed — NOT a package): `grid_model.py`, an
engine-neutral view-model (windowing = used_range ∪ a 12×6 minimum with tracked UL/LR bounds for
O(1) visibility — his plan; commit policy identical to the TUI's; `apply_action` executes keymap
Actions) with ZERO DearPyGui. `dpg_grid.py`, a ~250-line DPG shell: a windowed grid of read-only
value cells (his "text-boxes for the active view"), a formula bar editing the cursor cell, and a
`keypress_from_code` adapter — the only DPG-specific code in the key path — so the SAME
`ExcelKeymap` the TUI uses drives the GUI. demo.csv (live formulas) + README.

**Verification: 22 headless tests green** (15 model + 7 DPG). DPG segfaults trying to open a
viewport in this sandbox, but imports + builds its item tree + get/set work headlessly, so the
construction code and callbacks ARE exercised: recalc propagation shows up in the grid, keymap
arrows move the cursor + follow the formula bar, type-to-edit seeds the bar, the window grows to
cover far cells. What's left for Matthew's machine: live key dispatch, rendering, the cursor-
highlight theme, modifier polling (ctrl-combos tested via the model, not through DPG).

**Payoff proven:** a frontend = `import trellis` + `import trellis_keymap` + draw-the-window/adapt-
the-keys, no Textual. NEXT experiment if he likes it: in-place cell editing (the cursor cell as an
editable input_text) — where DPG's real editing ergonomics live. The spike depends only on the
published trellis + trellis-keymap, so it `git mv`s out to the new project's repo cleanly. Pending:
Matthew commits the S40 work (this spike is additive, its own dir).

---

## 2026-06-17 — Session 40 (later): trellis-keymap — the keymap contract gets its own package

**Context:** same session, after the atomic-save work and packaging the engine. Matthew is
planning a new GUI for the next project (likes DearPyGui, happy owning the input layer) and asked
to extract `trellis-keymap` so a second frontend can share the Excel/vim key languages. He picked
the entry-point group rename (`trellis_tui.keymaps` -> `trellis_keymap.keymaps`).

**What landed.** New `packages/trellis-keymap/` — the 422-line, stdlib-only keymap contract
(`KeyPress`/`KeyContext`/`Action`/`Keymap`/`ExcelKeymap` + discovery) lifted out of `trellis-tui`
verbatim, zero dependencies like the core, group renamed to `trellis_keymap.keymaps`, with a
README and 19 hermetic contract tests. `trellis-tui-vim` repointed to import `trellis_keymap` and
now depends on `trellis-keymap` ALONE (dropped `trellis-tui`) — the vim language is frontend-
independent now; its entry point moved to the new group. `trellis-tui` gained the `trellis-keymap`
dep and `trellis_tui/keymap.py` became a 19-line compat shim (`from trellis_keymap import *`), so
`app.py`/`grid.py` are byte-for-byte unchanged (only one stale group-name docstring in app.py was
refreshed). One TUI test repointed its monkeypatch to `trellis_keymap.entry_points` (discovery
moved there).

**Verification — all green.** trellis-keymap hermetic 19 / vim hermetic 26 / vim Pilot 9 / full
TUI suite 196 (through the shim, run in halves) / core 821. Off-mount editable venv proved
discovery under the new group: `available_keymaps()` = excel + vim; `build_app(['--vim'])` wires
the discovered VimKeymap. The shim re-exports the full surface and `Keymap` is the same object
(isinstance holds).

**Forward note.** This sets up the new GUI cleanly: it imports `trellis` (engine) + `trellis-keymap`
(input contract) and owns its own rendering — no Textual, no TUI. The TUI session can later repoint
app.py/grid.py off the shim and delete it. Pending Matthew's side: commit + push the S40 work
(CSV atomic + packaging sdist target + the trellis-keymap extraction).

---

## 2026-06-17 — Session 40: Part 11 row 1 — write_csv is atomic now

**Context:** pickup after Part 10 closed (S39, field-verified). Confirmed with Matthew the repo is
fully pushed (his `git status` = up to date with origin/main; my sandbox's view of origin was
stale — corrected, no push was pending). Cleaned a field-check leftover: `.gitignore` now ignores
`demo[0-9]*.csv` (catches demo2.csv etc.; the already-tracked demo.csv stays tracked). Next
milestone chosen: **CSV-path I/O polish**; Matthew picked **atomic save** to lead.

**What landed.** `write_csv` no longer opens the destination directly. It streams into a temp file
beside the target and `os.replace`s it into place — atomic on POSIX and Windows, so an interrupted
save can't truncate the user's original (the write-protocol failure mode, now closed for the
engine's own file path too). On any failure the temp is unlinked and the error re-raised. The
empty-sheet branch shares the path. `_apply_target_mode` restores the mode `open(path, "w")` would
have produced (copy existing on overwrite, else `0o666 & ~umask`) so mkstemp's 0600 doesn't leak
through; best-effort, POSIX-shaped. Docstrings (module + `path` param) note the guarantee.

**Tests: +5, core 816 -> 821, all green** (full `--doctest-modules src tests` in ~1s). No temp
litter after success; a monkeypatched mid-serialize failure leaves the original intact + no litter
+ propagates; empty-sheet stays atomic; a short overwrite truncates a longer file's stale tail;
(POSIX-only) 0640 preserved across overwrite. Pure durability — no API or happy-path change.

**Protocol notes.** Edited off-mount (python string-patch -> /tmp -> cp -> sha256-verified, per
[[write-protocol-mount-folders]]); PYTHONPYCACHEPREFIX=/tmp/pyc throughout; pytest needed
`pip install --break-system-packages` in this fresh sandbox.

**NEXT (Part 11):** row 2 = read robustness (UTF-8 BOM + semicolon-delimiter sniff so real Excel
exports open clean — benefits the TUI for free); row 3 = graceful open errors in the CLI path
(`app.py:1302` read_csv is unguarded — a bad-encoding file currently bubbles a traceback). Pending
Matthew's side: commit + push this session (csv.py, test_io_csv.py, .gitignore, design.md, WORKLOG).

---
## 2026-06-12 — Session 39: PART 10 ROW 4 — contract doc + FIELD CHECK PASSED; PART 10 COMPLETE

**Context:** pickup session. Matthew ran the field check live mid-session.

**Field check first (it gated everything):** initial `trellis --vim` failed with the designed
helpful error (`unknown keymap 'vim' (available: excel)`) — root cause NOT a discovery bug but a
venv built before row 3; `pip install -e packages\trellis-tui-vim` into the live venv fixed it.
Then all three S35-rule items passed on Windows Terminal: **Esc timing instant** (insert -> normal,
no terminal delay; Ctrl+C-as-Esc held), **`:` echo UX good** (echo/backspace/dirty-warn/`:q!`/
unsupported-command echo), **printables sane** (normal-mode letters are commands, unbound letters
inert). Matthew's verdict: "works well... I'm happy". **Part 10 closes field-verified** — the
S35 rule satisfied for the third time (Alt+R, the ScrollView theft, now this venv-staleness find).

**docs/keymap-plugin.md (157 lines)** — the contract doc, plugin-example.md's sibling for the
frontend hook: the minimal toy keymap, the three disciplines (keymap-never-writes / textual-free /
execution-time rects), KeyPress/KeyContext, the full Action table (incl. Chain and the Hint("")
deaden), state-and-modes (app is the mode authority; instance holds only what nobody else can),
entry-point shipping + the available_keymaps() smoke test + the stale-venv field note, and the
hermetic-testing story (26-in-0.2s vs 9 Pilot — copy that ratio).

**Close-out:** design.md row 4 marked DONE + S39 field-check addendum (PART 10 COMPLETE);
root README Extending #5 links the doc. Written off-mount per the write protocol, sha256-verified.

**PART 10 COMPLETE.** The monorepo now ships three proven extension styles with docs for each.
NEXT per pull list: xlsx (deprioritized), or whatever the field suggests. Also pending on
Matthew's side: push (origin is 2 behind after this session's commit).

---
## 2026-06-11 — Session 38 (later): PART 10 ROW 3 — trellis-tui-vim, the reference keymap plugin

**Context:** row 2 pushed (origin = 1b49f9f) and Matthew said continue — row 3 in the same session, the Part 6/9 same-day rhythm. The third reference package ships: the monorepo now brackets all three extension styles (mathpack = entry-point globals, trellis-undo = events+meta, trellis-tui-vim = a frontend strategy hook).

**Contract prep — `Chain(actions)` joined the vocabulary** (the third build-found verb, after Fill and Select, same discovery class): vim's `:wq` is save-then-quit and vim's delete is yank-then-clear, and `handle()` returns ONE action. Executor recurses member-by-member — execution-time rect resolution holds inside a chain. +1 TUI test (Hint then Sheet, order proved): **TUI 196**.

**The package** (`packages/trellis-tui-vim/`, ~470-line `__init__.py`, imports ONLY `trellis_tui.keymap` — never textual, never the app): `VimKeymap` registered as `vim = "trellis_tui_vim:VimKeymap"` under `trellis_tui.keymaps`; `trellis --vim` selects it. The app's mode is the mode authority (EnterMode out, ctx.mode back); the instance holds only what nobody else can — pending count, pending double (d/y/c/g), the `:` buffer, visual-line's moving end. Core subset all in: hjkl/arrows + counts, w/b Excel data-jumps, 0/^/$ row ends, gg/G column-data (+{n}G/{n}gg/:{n}), Ctrl+D/U half-page, i/I/a/A (caret start/end — the row-2 `caret=` lands its consumer), x/dd/yy/cc, p/P, v/V/Ctrl+v, visual operators, u/Ctrl+r, `:w :q :wq :x :q! :{n}`.

**Vim-internal decisions (design deferred them to build; recorded in design.md S38 row-3 addendum):** delete IS yank (`dd` `p` moves a row — the design sketch's "d/x clear" lost to vim fingers); `c` doesn't yank; `p`=`P` (grid pastes AT the cursor); operators take doubles or Visual — no `dw`/`d3j` composition in v1; counts × motions everywhere; **Ctrl+C ≈ Esc** (it must never fall through to the app's quit mid-thought); Enter=down, Backspace=left. The `:` line lives entirely inside the contract: EnterMode("command") + the buffer echoed as `Hint(":w…")`, Enter parses to a Chain ending back in normal, unsupported keys echo (modal honesty). Zero app changes, zero new widgets.

**Two findings the tests forced:** (1) **visual operators park the cursor at the region's start** (trailing baked MoveTo) — the integration suite caught `vly`+`p` pasting at the selection's END offset; vim fingers expect anchor-relative. (2) **visual-line tracks its own moving end** (`_vline`/`_vcur`) — the grid parks the real cursor at the rect's bottom-right, so upward extension recomputed from the cursor stalls against the anchor. The stateful-`handle()` contract call, vindicated twice in one file.

**Tests: 26 hermetic + 9 Pilot = 35** (hermetic suite runs in 0.2s with a fake KeyContext — the contract's testability promise, kept). Integration proves composition end-to-end: dd+p moves a row with its formula shifting, u un-pastes; `:q` warns dirty / `:q!` exits; `:w` pathless opens the same SaveAs modal as Ctrl+S; Ctrl+T/PgDn chrome alive under vim. **Install-level discovery proved in an off-mount venv** (mathpack's Tier-2 pattern, inline): `available_keymaps()` = excel+vim, `build_app(["--vim"])` boots with it. setup-venv.{ps1,sh} install the new package.

**Suites: core 816 / undo 15 / TUI 196 / vim 35 — all green.** Docs: vim README (key table + the vim-decisions list), root README (three reference extensions; Extending §5 names the reference), TUI README (status/usage/196+35), design.md row 3 closed + S38 row-3 addendum.

**NEXT: row 4 — docs polish (docs/keymap-plugin.md contract doc) + the field check** (Windows Terminal: Esc timing, the `:`-echo UX, printable-swallowing vs bracketed paste — the S35 rule; Part 10 closes field-verified or not at all). Matthew: `scripts\setup-venv.ps1` (installs the new package) then `trellis --vim demo.csv` and live a little.

---
## 2026-06-11 — Session 38: Part 10 row 2 — the keymap layer lands, Excel becomes a keymap

**Context:** row 2 of the Part 10 rollout, fresh session off the S37 design. Tree clean at 3ff8450 (one design commit ahead of origin — Matthew's push pending). Predicted "possibly two sessions if the port is gnarly" — it wasn't: **one session, 175 untouched-green on the first full run after the port**, the Part 9 facade rhythm again.

**What landed (one commit's worth, ~420 lines of src + 230 of tests):**
- **`trellis_tui/keymap.py` — the contract, textual-free (decision 8):** `KeyPress` (with a string-only `parse`, so the "~20-line adapter" is itself hermetic), read-only `KeyContext` (cursor/selection/used_range/`cell()`/viewport/mode), the `Action` vocabulary as frozen dataclasses (Move/MoveTo/**Select**/BeginEdit/EnterMode/Operate/Fill/Undo/Redo/Save/Quit/Sheet/Hint), the `Keymap` protocol, **`ExcelKeymap`** (the ported default — a (key,ctrl,shift)→factory table + the printable→type-to-edit rule), and entry-point discovery (`trellis_tui.keymaps` group; `available_keymaps`/`load_keymap`; a plugin can't shadow the built-in name).
- **grid.py:** ALL grid-key `BINDINGS` deleted — `on_key` is the one path: build `KeyPress`, call `active_keymap.handle(key, key_context())`, Action → `stop`+`prevent_default` (suppresses DataTable's own cursor bindings too — arrows are `Move`s now) + post `ActionRequest`; `None` → the key runs on to framework + chrome. `select_rect(rect)` generalizes Ctrl+A's machinery for the `Select` action.
- **app.py:** the shared async `_execute` — keymap Actions and app chrome land in the same executor (decision 7: `action_save`/`action_quit`/sheet-cycling now *emit* `km.Save()`/`km.Quit()`/`km.Sheet(...)` through it); handler bodies extracted to `_copy`/`_cut`/`_clear`/`_undo`/`_redo` so executor and legacy request-messages share one implementation; `_start_edit` grew `caret=` (vim's `i`/`a`) and sets mode `insert`; editor Done restores the resting mode; `StatusBar` renders `-- MODE --` (resting mode renders nothing; `state` stays a 3-tuple — load-bearing for tests — mode mirrors at `mode_shown`); `TrellisApp(keymap=...)` + `build_app` `--keymap NAME`/`--keymap=NAME`/`--vim` (unknown name prints what IS available).
- **Contract refinements found by building** (folded into design.md Part 10 as the S38 build addendum): `Select` joined the vocabulary (select-all isn't a single anchored Move; vim's Visual entries want it — the Fill discovery class repeating); `None` sharpened to "no action here, the key runs on" with `Hint("")` as the explicit deaden; **rects resolve at execution time** (`Operate`/`Fill` carry `rect=None` = live-selection-else-cursor — queued Actions execute in order, so a `Move(extend)`+`Operate` burst can't copy a stale rect); one casualty: the Footer's F2/Delete hints (were Binding metadata; `key_table()` is the help surface now).
- **Tests: `test_keymap.py`, 20** — hermetic contract layer (parse, the full Excel table, registry, entry-point no-shadow via monkeypatch); **the hook proved from OUTSIDE** with a toy keymap (`j` moves — a printable that would start an edit under Excel: one-path proof; declined printables are inert — no fall-through; Ctrl+T still makes a sheet under a keymap that's never heard of it — the chrome boundary); CLI flags incl. `--vim` failing helpfully with vim-not-installed; caret="start"; `_execute(km.Sheet("next"))` from outside = the executor is the REPL surface too; mode indicator lifecycle around an edit.

**Sandbox scars (the mount Write/Edit landmine, 3 hits this session):** Edit tool truncated grid.py's tail mid-edit AND __init__.py — recovered both via git-show + scripted re-patch off-mount (/tmp + cp + sync + sha256). app.py and all docs were patched scripted-off-mount from the start (the file's been truncated twice in past sessions). **The rule hardens: on this mount, Edit/Write only for trivial single-spot edits, and verify with `ast.parse` + `wc -l` immediately; anything multi-edit goes through the /tmp script protocol from the first keystroke.**

**Suites: core 816 (with doctests) / undo 15 / TUI 195** (was 175; run in halves, the 45s window), all green. Docs: TUI README (status, keymap bullet, `--keymap` usage, deliberately-not updated, 195), root README (Status + **Extending §5: the TUI keymap hook** — frontend hook, core knows nothing of it), design.md row 2 closed + build addendum.

**NEXT: row 3 — `packages/trellis-tui-vim/`**, the reference keymap plugin (modes, counts, motions, operators, the `:` command line) + hermetic tests; then row 4 docs + the Windows Terminal field check (Esc timing, `:` modal, printable-swallowing — the S35 rule). The vim-internal parse questions (counts × operators, `c` over multi-cell) get decided there.

---
## 2026-06-10 — Session 37: Part 10 DESIGNED — vim keymap as the TUI's first extension point

**Context:** vim keymap picked off the v2 pull list. Design-only session, no code — the part introduces a *public extension surface*, so decisions were confirmed up front before any build (the Part 3 / reference-plugin discipline). Folded into design.md Part 10 (line 1086+); the `design-part10-vim-keymap-DRAFT.md` scratch was removed once folded.

**The framing:** vim is NOT a hardcoded mode — it's a *keymap* behind the TUI's first real hook, with vim as the reference keymap plugin. That makes keymaps the third sibling of mathpack (entry-point globals) and trellis-undo (events + meta): a frontend strategy hook. The leverage is that the TUI is already half-modal — Insert = the FormulaBar editor, Visual = the selection model, Normal = "grid focused, not editing" (`app._editing()` is the seam) — so the keymap mostly *names and redirects* machinery that exists (`y`→CopyRequest, `d`→Cut/Clear, `p`→Paste, `u`→undo).

**The pivot worth the entry — decision 6 flipped mid-design (Matthew's call):** from an *additive hook* (default stays hardcoded, vim the only keymap) to **one path — Excel is a keymap too**. The default bindings port to a built-in `ExcelKeymap`; every key in every config flows through one `handle()->Action` delegate, no fall-through. Why it's better: a single consumer doesn't prove the contract general (it's just vim's internals in a coat), and the additive fall-through (vim's unhandled keys dropping into Excel bindings) was a precedence-bug surface — the class that keeps biting this project. The two-consumer payoff was immediate and concrete: **modeling Excel-as-keymap surfaced a vocabulary gap a vim-only contract would have shipped without — `Fill` had to become an Action** (Excel's Ctrl+D/R; vim doesn't need it).

**The contract (load-bearing, treat like Part 3):** `Action` — the closed vocab the TUI executes (Move/MoveTo, BeginEdit, EnterMode, Operate{copy,cut,clear,paste,change}, **Fill**, Undo/Redo, Save/Quit, Sheet, Hint); `KeyContext` — read-only state a keymap sees (cursor, selection, used_range, cell(), viewport, editing); `Keymap` — a *stateful* `handle(key, ctx)->Action` strategy (vim's counts/operators need parse state, not a static dict). Discipline mirrors the engine: **keymap never writes** (returns Actions, the TUI executes — the frontend echo of grid-never-writes-engine); **textual-free** like render.py.

**8 decisions locked (Matthew, 2026-06-09/10):** (1) opt-in `--vim`; (2) core subset [hjkl+counts, gg/G, w/b data-jumps, 0/$/^, d/y/c/x/p/dd/yy, i/a/I/A, u/Ctrl+r, :w/:q]; (3) keymap-plugin API now; (4) vim Ctrl+D=half-page / Ctrl+R=redo (fill is Excel's binding); (5) vim ships separate as `packages/trellis-tui-vim/` (entry point — proves the hook from outside, like mathpack); (6) one path, Excel-as-keymap, ExcelKeymap *should* reproduce (deviation OK only where textual's global key handling forces it); (7) chrome boundary — sheet/tab/quit stay app-keys, shared Actions (keymaps own grid/cell/mode + the `:` verbs); (8) keymaps see our own textual-free `KeyPress` (~20-line adapter over textual's parsed `Key`; key-names mirrored; own-vocabulary + translation table deferred until a non-textual frontend exists). The KeyPress discussion settled the "more work / less work" worry: textual does the OS/terminal parsing under the adapter either way, so "our handler" is decoupling at ~20 lines, NOT OS-key work; upstream capture (Alt+R-style) is orthogonal and unsolvable by either — field-check only.

**Deferred:** `o`/`O` (need `Sheet.insert_row` — confirmed absent this session; it'd be a *core* part by the design test); search, f/t, marks, registers, macros, `.`-repeat. Vim-internal, settled at build: `c`/change over multi-cell, counts × motions parsing.

**Rollout (staged, multi-session):** row 2 = keymap layer in trellis-tui + port the bindings into the built-in ExcelKeymap (175 tests the regression net — possibly 2 sessions if gnarly); row 3 = the trellis-tui-vim package; row 4 = docs + field-verify. **Sandbox scar (again):** the Write tool truncated the design draft at 143/163 lines mid-edit — recovered via the /tmp-stage + cp+sync+sha256 protocol; design.md itself was folded via `cat >>` on the mount (bash file ops on the mount are reliable; it's the Edit/Write harness tools that truncate — see write-protocol-mount-folders). NEXT: row 2 as its own session.

---
## 2026-06-08 — Session 36 (later): PART 9 — sheet tabs, the editor-buffers model

**Context:** Part 8 closed field-verified earlier in the session; Matthew picked **sheet tabs** off the pull list. Design pass first (design.md Part 9, ~90 lines, 23d7888), decisions confirmed up front — all three recommended picks: **(1) sheet = file** (CSV is single-sheet and Matthew is CSV-native, so tabs are an *editor's open buffers*: per-tab path + dirty + undo; rejected workbook-as-folder and manifest formats), **(2) full op set** add/switch/rename/close, **(3) cross-sheet references deferred** (a real engine part — lexer `!`, cross-sheet dep graph; under sheet=file they'd be cross-FILE refs. Formulas stay sheet-local, documented). Zero engine changes again — `Workbook` had everything (ordered sheets, add/remove/rename events) and `read_csv(workbook=)` finally found its consumer.

**#2 — `SheetView` + the active-view facade (b934838).** Per-tab state object (sheet, path, dirty, grid, undo log, event subs; `uid` for stable DOM ids). **`app.sheet`/`app.path`/`app.dirty`/`app.undo_log` became properties over the active view** — every existing handler and most existing tests read through unchanged (the whole 147-test suite passed untouched on the first run after the refactor). Dirty routes by the event payload's `sheet` (the 3.1 lock-in carrying the day again); recalc notes gate on the active sheet; Ctrl+S saves the active sheet only; Ctrl+Q counts every unsaved sheet. Empty `Workbook()` now grows a Sheet1 instead of crashing the constructor.

**#3 — the tab bar (cd881b0).** One `SheetGrid` per view in a `ContentSwitcher` (grid-per-sheet keeps cursor/selection/window reach per tab for free); `Tabs` strip at the BOTTOM, Excel-style. One switch path: clicks, Ctrl+PgUp/PgDn, Ctrl+T and Ctrl+W all funnel through `Tabs` activation → handler sets the active uid, flips the switcher, re-syncs chrome (`_sync_chrome`: title, status, formula bar — cell mirror or range readout), focuses the incoming grid. **The bug worth the entry: the switch keys did nothing** — textual's ScrollView (DataTable's base) binds ctrl+pageup/pagedown for *horizontal paging*, so the focused grid ate them. Fix: `priority=True` app bindings (+ explicit editing guard with a status hint — switching mid-edit is a no-op by design, Excel's commit-on-switch deferred). Every `query_one(SheetGrid)` in the app had to become active-view-aware — with multiple grids mounted, query_one raises and `.first()` lies; the cursor-mirror also gained a source guard (`event.data_table is not the active grid` → a background rebuild, not the user). Close = switch-away-first, then detach/remove/`workbook.remove_sheet` — the activation race never starts. Right neighbor wins (Excel), left when closing the last-most.

**#4 — rename + multi-file CLI (e1362ed).** `RenameScreen` modal (SaveAsScreen pattern, prefilled); **Alt+R** or **double-click the tab** (textual `Click.chain == 2`; the first click of the pair already activated the tab, so rename always targets the active sheet). Renames the *sheet*, never the file — `app.path` is untouched, regression-tested. Collisions hint (`name taken: beta`), Esc cancels. **Open question resolved: the tab dirty marker comes cheap** — `Tab.label` is a settable property; labels show `name ●`, updated only on the dirty *flip* (no per-keystroke churn), cleared on save. `build_app` grew the multi-file CLI: `trellis a.csv b.csv` = one tab per file via `read_csv(…, sheet_name=stem, workbook=wb, formulas=True)`, stems dedupe (`data`, `data-2`), nonexistent paths keep the new-file flow per file.

**#5 — the clipboard crosses tabs (7613d8b).** `Clipboard` gained `sheet` (the source). Copy-paste cross-tab needed nothing else — offsets are sheet-agnostic, the snapshot model pays again. **Cut-paste across tabs clears the source cells on the sheet they came from**: targets in the active sheet's batch, source-clears in the source sheet's own batch — one undo step *per side*, per-sheet undo-honest (tested: Ctrl+Z on the target un-pastes, Ctrl+Z on the source un-clears, formula round-trips). Same-sheet moves keep the single-batch written-set exclusion untouched. Cut-disarm stays global (conservative).

**Tests: `test_tabs.py`, 28** — views/paths/facade, dirty routing (background writes dirty THEIR view, not the bar), per-sheet undo logs, save-active-only, quit counts, recalc-note gating, tab strip compose + focus, PgUp/PgDn cycling with wraparound, per-tab cursor+selection survival, formula-bar follow, Ctrl+T (first-free SheetN, typing lands on the new sheet), Ctrl+W warn-then-close / clean-closes / last-refuses, mid-edit switch hint, background-rebuild bar guard, rename (modal/collision/Esc/double-click/path-kept/label), CLI multi-file + stem dedupe, cross-tab copy/cut/per-side undo. One test-side find: my own setup writes dirtied the source view — reset before asserting paste-side dirt. Suite timing: full TUI now ~65s — **run in halves remains the rule** (and one bundled run tripped the 45s window; split further when stacking suites).

**Suites: core 816 / undo 15 / TUI 175** (was 147), all green. Docs: TUI README (status, buffers-model feature bullet, 5 key rows, deliberately-not additions incl. sheet-local formulas + save-all, 175), root README (Status + taste lines), design.md rows #1–#6 closed + both open questions resolved (labels cheap; the ScrollView key-theft finding noted against the field-check question).

**PART 9 FIELD-VERIFIED (same session, Matthew): "all works well"** — sheet switching, per-sheet undo, close all confirmed on Windows. One casualty: **Alt+R never arrives — the GPU driver (AMD/NVIDIA overlay, resource-usage shortcut) eats it upstream of the terminal.** Rebound rename to **Ctrl+Shift+R** (kept the R mnemonic; double-click the tab was always the mouse path and is unaffected). The mirror-image of the #3 ScrollView lesson: #3 was the app's own widget stealing a key (Pilot caught it); Alt+R is the OS/driver swallowing a key before any app sees it (only a field check catches it). PART 9 COMPLETE. NEXT per pull: vim keymap / xlsx (deprioritized) — or whatever the field suggests.

---
## 2026-06-08 — Session 36: Part 8 — keyboard fill (Ctrl+D / Ctrl+R)

**Context:** fresh session; task list rebuilt (design pass / implement / tests / docs / Matthew verifies). Tree clean at e439a77 (one docs commit ahead of Matthew's last push). Matthew picked **fill handle** off the pull list — the part Part 6 predicted ("`shift_formula` is the hard half of it anyway").

**Design pass (design.md Part 8, ~65 lines).** Decisions confirmed up front, all three recommended picks (same pattern as Parts 6/7): **(1) keyboard only** — Ctrl+D fill down / Ctrl+R fill right; the mouse drag handle is *deferred* (a one-character target in a character grid, plus the S35 lesson generalized: drags are even less terminal-portable than modifier+clicks). **(2) Single-lane = fill from the neighbor, Excel-exact** — no selection (or a 1-row/1-col one): Ctrl+D copies the cell(s) above into the target, Ctrl+R from the left; at the sheet edge, status hint, no write. **(3) Series fill deferred** — Excel's Ctrl+D never extrapolates anyway (only the drag handle does); the spreadsheet-native idiom is documented in the README: `=A1+1` below and fill down — **the formula IS the series.** Engine additions: **none** — fill is a frontend gesture over `shift_formula`, the design test passes by construction (rejected: a `trellis.fill()` core helper — the first engine API that takes a rect and writes cells would be a frontend's job description; the REPL idiom is a two-line loop).

**Implementation — small, by design (the Part 6 machinery did the work):**
- **Grid:** `ctrl+d`/`ctrl+r` bindings (grid-bound = nav-only, the clipboard-keys isolation: while editing, Input's own ctrl+d keeps deleting text — conflict check came up clean, DataTable and App bind neither key) posting `FillRequest(rect, axis)`, rect = selection or cursor 1×1, ClearRequest-shaped. Source-vs-target resolution is deliberately the app's — the grid stays semantics-free.
- **App:** `_fill(rect, axis)` — resolve source lane (first row/col of a 2+-lane rect; the neighbor above/left for single-lane; edge → `nothing above/left to fill from`), then per-lane transfer through **the same `_paste_cell` as paste** (docstring now says "paste and fill both route here"): formulas `shift_formula`-shifted by each target's offset from ITS lane's source ($ pins hold, off-edge → `#REF!`), values verbatim, empty sources clear targets. ONE `sheet.batch()`. Status: `filled down A2:B3`.
- **Composition, all free:** one batch = one undo step (Ctrl+Z un-fills whole); `_mark_dirty` disarms a pending cut; selection and cursor stay put (Excel-faithful); repaint rides the batch echo; an all-empty fill emits nothing (verified in the engine first: delete-of-absent is silent → empty batch skipped → no dirty). No clipboard involvement — a fill never clobbers copied cells.

**Tests: `test_fill.py`, 12** — per-lane shift + one-batch + no-clipboard, $ pins (caught my own test's bad arithmetic, not a code bug: filled `=$A$1+A2` against an empty A2 — populated A2 and asserted both halves), fill-right mirror, fill-from-above ×2 (no selection / 1-row selection), edge hints + no dirty, empty-source-clears, nothing-over-nothing stays clean (no batch event, not dirty), one-undo-step, cut-disarm, editing isolation (ctrl+d deletes text, sheet untouched), selection+cursor survive. **Suites: core 816 / undo 15 / TUI 147** (was 135), all green on the 3.10 sandbox (run in halves — the 45s window).

**Docs:** TUI README (status line, fill feature bullet with the formula-is-the-series note, 2 key rows, deliberately-not list updated — "fill handle" out, "mouse drag-fill and series fill" in with the why, test count 147); root README (Status + terminal-taste lines); design.md Part 8 rows #1–#5 closed.

**Open question pending the field check (the S35 lesson made it a rule):** do Ctrl+D / Ctrl+R survive Windows Terminal to the app? They're plain C0 controls (0x04/0x12), no emulator-reserved meaning in raw mode — expected clean, but **Part 8 closes field-verified or not at all.** Matthew: pull, `Ctrl+D` on a selection with a formula in the top row, `Ctrl+R`, a lone `Ctrl+D` under a cell, and `Ctrl+Z` to un-fill — then the part closes. NEXT per pull list after that: sheet tabs / vim keymap / xlsx.

**Field-verified (same day, Matthew):** Ctrl+D and Ctrl+R both arrive through Windows Terminal and fill as designed — "seems to work nicely." His workflow note: set the fill's extent first — Ctrl+click the end cell to extend the selection there, then fill; the Part 6 extend-click and the fill semantics compose exactly as intended (tip added to the TUI README). **PART 8 CLOSES FIELD-VERIFIED.** He pushed through 3f23399 before testing — origin is current.

---
## 2026-06-07 — Session 35: field feedback on Part 6 — two terminal-reality fixes

**Context:** Matthew field-ran selection+clipboard against OpenOffice Calc. Paste OO→Trellis and Trellis→OO both worked — values only, which prompted the question: where are the formulas? Answer recorded here for posterity: the OS *text* clipboard carries computed display values by ecosystem convention (Excel and OO both mirror values into text/plain; formula interchange between GUI spreadsheets rides rich formats — ODF/BIFF/XML — that no terminal app can speak). Trellis matches Excel exactly: values out, typed-input semantics in, full fidelity Trellis→Trellis via the internal clipboard. NOT a bug — but his report flushed out two things that WERE:

**Fix 1 — own-TSV detection was line-ending brittle (real formula-loss risk).** Windows clipboards speak CRLF and some paths append a trailing newline; our mirror is LF-joined. A multi-row Trellis→Trellis paste bouncing through the OS could fail the `text == clip.tsv` comparison and silently downgrade to the external path — values instead of shifted formulas, the exact thing the bounce detection exists to prevent. Textual passes bracketed-paste text raw (only strips NULs — verified in `_xterm_parser.py`), so nothing upstream normalizes. Fix: `_normalize_paste` (CRLF/CR→LF, one trailing newline forgiven) applied to the *comparison only* — the external path keeps raw text (`splitlines` already handles any endings). The mirror is never CR-bearing by construction, so this only widens what we recognise as ourselves.

**Fix 2 — extend-click: terminals EAT shift+click ("no amount of clicking" — Matthew).** The S34 resolution checked the wrong layer: `events.Click` exposes `.shift`, but emulators reserve Shift+mouse for native text selection and never forward it to apps in mouse mode (xterm convention; Windows Terminal confirmed in the field). The SGR protocol forwards Ctrl (bit 16) and Alt/meta (bit 8) — verified in textual's `parse_mouse_code`. Fix: extend-click accepts `shift | ctrl | meta`; **Ctrl+click is the practical gesture**, Alt+click the fallback, shift kept for terminals that do forward it. Pilot tests couldn't have caught this — they synthesize post-parser events, bypassing the terminal layer entirely. Lesson noted: anything mouse+modifier needs a field check, not just a Pilot check.

**Landed:** grid.py (`_on_click` modifier set + docstrings), app.py (`_normalize_paste` + detection comment), test_selection.py (+1: ctrl- and alt-click extend), test_cut_os_bridge.py (+1: CRLF+trailing-newline bounce keeps formulas, multi-row), TUI README (key-table row reworded, ecosystem-truth note in the bridge bullet), design.md (field addendum on the click question). Suites: **TUI 128, core 816 untouched**, green. Also same session: outbound-TSV design knob surfaced by the field test — **values-only confirmed by Matthew** (87340c0 records it in design.md's rejected alternatives).

**Field-verified (same day, Matthew):** Ctrl+click extend works as expected; internal copy preserved formulas with computed values showing in the grid — "working flawlessly again." **Part 6 closes field-verified.** Next pull: the undo plugin (second reference plugin; the 3.1 payloads carry everything it needs), then fill handle / sheet tabs / vim keymap / xlsx per pull.

**PART 7 — trellis-undo, same session (design 197b716, package cbdc860, TUI wiring 21e7cd7).** Matthew called the undo plugin next ("undo me! ... don't do that (to me!)"). Design pass first, house-style, decisions confirmed up front (all three recommended picks): hard TUI dependency / undo+redo / capped 1000.
- **Pre-design recon paid off:** `Workbook` already emits `sheet:add` (docstring literally anticipates per-sheet attachment); `delete` emits `cell:change` carrying the displaced `Cell`; batch changes carry the full 3.1 payload. Verified empirically before writing the design: **object-restore recalcs** (a restored `=A1*2` self-healed its snapshot-stale value against moved deps, dependents cascaded), empty-`Cell` stores don't bloat `used_range`, meta rides the restored object.
- **The package** (`packages/trellis-undo/`, 15 hermetic engine-only tests): `UndoLog(sheet, capacity=...)` records `cell:change` + `sheet:batch` (one event = one step; `cell:recalc` never — derived state re-derives), steps hold the payload's `Cell` objects, restore = `sheet.set(addr, old_cell)` / `delete` for was-empty, multi-cell steps inside one `sheet.batch()`. Self-suppressing recorder (`_restoring` flag); redo clears on forks; `deque(maxlen)` cap, `None` unbounded. `attach`/`detach` own `sheet.meta["undo"]` (idempotent); `attach_workbook` rides `sheet:add`. **Deliberately NO entry point** — the pyproject comment explains: entry points register globals; events + meta attach state. The two reference plugins now bracket both extension styles.
- **TUI wiring** (7 Pilot tests): hard dependency; attach on mount AFTER any CSV load (file-open is not an undoable gesture), detach on unmount; Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z as grid-bound intents (nav-only — while editing they leave the sheet alone, tested); status `undid 4 cells` / `nothing to undo`. Undo writes ride the normal echo: grid repaints, dirty marks, pending cuts disarm via the existing `_mark_dirty` hook — composition for free. **Save-point question DECIDED: not in v1** — depth equality lies once steps drop off the cap; honest tracking needs drop-detection. Documented in README ("undoing back to the saved state still shows ● modified").
- Sandbox note: the TUI suite (135) now exceeds the 45s bash window — run halves, or `test_undo_wiring.py` alone for the new seam. PYTHONPATH gains `../trellis-undo/src`.
- **Suites: core 816 / undo 15 / TUI 135** (was 128), all green. READMEs: trellis-undo full pass; TUI (undo bullet, 2 key rows, deliberately-not list updated); root (Status names both reference plugins + the events section points at trellis-undo as the build-undo-from-outside proof). **PART 7 COMPLETE — second reference plugin shipped.**
- **Field-verified (same day, Matthew):** setup-venv.ps1 rebuilt clean on py3.14.5 (all four packages editable, core 816 green on Windows); Ctrl+Z/Ctrl+Y "living the dream!" — **Part 7 closes field-verified.** Save-point question ratified closed for good in the same exchange (fe9fa56); his versioning instinct (git on the saved CSV) already works because formulas round-trip — the file IS the document.

---
## 2026-06-07 — Session 34: Part 6 #4 — the TUI selection model

**Context:** fresh session; task list rebuilt per the S33 handoff (① #4 selection ② #5 clipboard ③ #6 cut+OS bridge ④ #7 docs ⑤ Matthew pushes). Matthew committed `demo.csv` (c7e100a) — the S33 commit-or-delete question answered itself. Tree was clean at fdbb842/1e88762 + that.

**Part 6 #4 DONE — selection is grid-owned view state.** `selection = (anchor, cursor)`: the anchor pins where extension started, the cursor IS the DataTable cursor; `selection_range` is the normalised rectangle property. **Shift+arrows extend** (clamped to the window; the move rides the normal cursor machinery so grow-on-demand still applies at the edges), **shift+click extends** (open question RESOLVED: textual 8.x `Click` exposes `.shift`, and `.style.meta` the clicked cell — `_on_click` pins the anchor *before* DataTable moves the cursor), **Ctrl+A selects `used_range()`** (no-op on an empty sheet; idempotent when the cursor already sits on the far corner), **Esc or any plain cursor move collapses**. The grid still never writes the engine: **Delete posts the rectangle with `ClearRequest`** and the app clears it as ONE `sheet.batch()` of `commit_text` deletes — one echo, one recalc, one dirty mark; an all-empty rectangle emits nothing (the engine skips empty batches) so deleting nothing dirties nothing. The selection survives Delete, Excel-style.

**Painting: delta-restyle keyed on `_painted`.** Cells entering/leaving the rectangle restyle via `update_cell_at`; the symmetric difference is enumerated in O(delta) by strip decomposition (`_rect_minus`/`_intersect` — no materializing a 256-wide × thousands-tall overlap). Deltas over `REBUILD_THRESHOLD` rebuild instead (threshold question DECIDED: reuse, retune by subclassing; `SELECTION_STYLE = "on grey37"` same pattern). `_cell_text` reads `_painted` (not the live rect), so partial repaints can never disagree with what the table shows — and the tint *composes* with content styling (error red on selection tint, regression-tested). The bar readout is `B2:D5 (3×4)` via new `FormulaBar.show_range` (status line left to its file/save duties), driven by a `SelectionChanged` message; the app's cursor-mirror skips while a selection is live.

**The bug worth the entry — DataTable's first-row highlight.** Textual's `add_row` posts a `CellHighlighted((0,0))` of its own whenever the first row lands in an empty table ("cell_now_available"), so every `_rebuild` queues TWO non-user cursor events: that one, plus the cursor restore. The selection's plain-move-collapses rule ran on them and wiped the selection after any engine-triggered rebuild (caught by the suite; clear()'s own cursor reset posts nothing — the table is empty at that instant, verified in the textual source). Fix: `_rebuild` flags both as `_restore_moves` before they can read as user moves. Found the matching test-side trap: textual dispatches message handlers from the CLASS, so instance-attr monkeypatching a handler silently does nothing — class-level tracing got the diagnosis.

**Tests:** `test_selection.py`, 16 — rect algebra (disjoint-strips property), extend/normalise/anchor-pinning, plain-move + Esc collapse, Ctrl+A (+idempotence, +empty no-op), shift+click extend + plain-click collapse, tint-composes-with-error, big-selection rebuild path (spied), selection survives engine rebuild, extension grows the window, Delete = one batch / empty-Delete = no dirty / no-selection Delete regression. **TUI suite 102** (was 86); **core 816 untouched**, both green on the 3.10 sandbox.

**NEXT: Part 6 #5 — internal clipboard** (app-owned `Clipboard(cells, mode, source_anchor, tsv)`; copy + paste with `shift_formula` per-cell offsets, fill-on-paste, one-batch writes). Then #6 cut + OS bridge, #7 docs. Selection surface #5 needs is ready: `selection_range`, `SelectionChanged`, and the one-batch ClearRequest pattern to mirror.

**Part 6 #5 DONE (same session, later) — internal clipboard. Copy/paste works.**
- **`Clipboard` snapshot, app-owned** (frozen dataclass, tuple-of-tuples cells): per-cell payload = formula text when set (paste re-evaluates; the snapshotted value just rides along), else the raw value object — bools/floats/error values at full fidelity, no text round-trip. `source_anchor` keys the shifting; `mode="copy"` (cut is #6's); `tsv` mirror (display text, tabs/newlines flattened to spaces) is built at copy time so #6 only has to push it.
- **Intents stay grid-side, writes app-side:** Ctrl+C/Ctrl+V are GRID bindings posting `CopyRequest`/`PasteRequest` with a concrete rect (selection or cursor 1×1) — same shape as ClearRequest; the grid still never touches the engine or the clipboard. Bound on the grid deliberately: while editing, textual `Input`'s own ctrl+c/v handle text (app's default ctrl+c is non-priority, so the focused grid wins in nav mode).
- **Paste semantics (Excel-faithful, spec'd at #1):** 1×1 payload **fills the whole selection**, each target shifted by ITS offset from the source cell; block payload anchors at the target top-left, uniform shift = paste offset. `shift_formula` does the rewriting (`$` pins hold; off-edge refs land as `=#REF!` whose value IS the REF error — the #3 error-literal work cashing in). Empty source cells **clear** their targets. Everything in ONE `sheet.batch()` — one echo, one recalc, one dirty; out-of-window pastes ride the batch echo's rebuild-to-cover for free. Status line: `copied A1:B2` / `pasted D5:E6`.
- **Two collisions found by the suite:** textual's `App` already owns a read-only `clipboard` property (its OS-text mirror — the very thing #6 feeds via `copy_to_clipboard`), so the internal one is `app.sheet_clipboard` (70 tests failed on the name before the rename). And a literal `"="`-prefixed *string value* would get promoted to a formula by `sheet.set`'s sugar on paste — the engine's own "Cell instance stored as-is" path is the sanctioned verbatim write (regression-tested).
- Tests: **`test_clipboard.py`, 13** — snapshot fidelity (+is-a-snapshot-not-live), TSV flatten, shift/pin/off-edge-REF, fill-on-paste, block anchor+shape-wins, empty-clears, =-string verbatim, empty-clipboard no-op, out-of-window growth; one-batch asserted twice. **TUI 115, core 816**, green.

**NEXT: Part 6 #6 — cut + OS bridge** (cut = verbatim move, source cleared in the paste batch, clipboard demotes to copy after; TSV out via `copy_to_clipboard`, terminal `Paste` event in, own-TSV detection, external text through `infer_value`; TSV-fidelity open question gets its formal answer). Then #7 docs.

**Part 6 #6 DONE (same session, later) — cut + the OS bridge. PART 6 #7 docs same pass — PART 6 COMPLETE.**
- **Cut = the pragmatic move, as designed:** Ctrl+X snapshots with `mode="cut"` (status: `cut B1 — paste moves it`); paste relocates the block *verbatim* (`shift_formula(text, 0, 0)` is the engine's byte-for-byte identity — one code path with copy) and deletes the not-overwritten source cells **in the same batch**; then the clipboard demotes to copy (re-paste re-stamps). Esc cancels via a new grid `CancelRequest` (posted by the Esc action whether or not a selection collapses — the app demotes; "cut cancelled — clipboard keeps a copy"). **Safety addition beyond the spec:** `_mark_dirty` demotes a pending cut on ANY engine change — a stale snapshot must never delete cells whose content moved on (Excel disarms cut on edit for the same reason; the cut-paste's own batch demotes harmlessly at exit, its writes+deletes are already inside). Self-overlap moves keep the overwritten source cells (written-set exclusion, tested).
- **OS bridge both ways:** copy AND cut push the TSV mirror via `App.copy_to_clipboard` (OSC 52; sets textual's own `App.clipboard` — which is why the internal clipboard had to be `sheet_clipboard`). Inbound, `TrellisApp.on_paste` catches the terminal `Paste` event (how Ctrl+V actually arrives in most terminals — the #1 insight, now implemented): **own-TSV detection** (`text == sheet_clipboard.tsv`) routes the bounce to the full-fidelity internal paste (formulas shift, objects survive); anything else is external — split lines/tabs, every field through **`commit_text`** (the typing policy verbatim: `=`-leading fields commit as live formulas unshifted, `01234` stays text, empty fields clear), one batch, anchored at the selection top-left (no fill for external text). While editing, textual `Input`'s own paste consumes the event before it bubbles (verified in source + belt-and-suspenders guard).
- **Open question RESOLVED (the last one): TSV flatten fidelity** — tabs/newlines/CRs → spaces in the *mirror only*; internal clipboard unaffected and the bounce detection means the loss is only ever visible to other programs. All Part 6 rows #1–#7 done, all five open questions resolved.
- **#7 docs:** TUI README — Part 6 status paragraph (shift-on-copy + `$` pins + `#REF!`, fill-on-paste, pragmatic cut + disarm rules, OS both-ways) and six new key-table rows; root README terminal-taste line; design.md rows + cut-demote note. Worklog: this.
- Tests: **`test_cut_os_bridge.py`, 11** — verbatim move + same-batch source clear, overlap keeps overwritten cells, demote-after-paste / Esc-cancel / change-disarms, TSV out (app.clipboard == mirror), own-TSV bounce routes internal (formula shifts — external would store text), external inference (int/string/formula/leading-zero) one-batch, selection-top-left anchor, empty-fields-clear, editing-paste isolation. One test-side find: a live selection makes paste anchor at ITS top-left — the overlap test needed plain-move collapse first (Esc would have disarmed the very cut under test; the interplay is the feature). **TUI 126 / core 816, green.**

**SESSION 34 CLOSE.** Part 6 shipped whole: selection (#4, 4e3c881), internal clipboard (#5, 39c1122), cut + OS bridge + docs (#6+#7, this commit). Suites core **816** / TUI **126**. Matthew runs it next — selection + clipboard are the most-missed v1 gaps, field feedback will say if the muscle memory lands. v2 pull list after this: undo plugin (payloads ready), fill handle (shift_formula is the hard half, done), sheet tabs, vim keymap, xlsx extra.

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

**Matthew re-ran: "works flawlessly :-{D"** — formulas compute, cascade, and round-trip on his machine. v1 + the formulas= fix are field-verified.

**Part 6 design pass DONE (same session, later) — selection + clipboard scoped in design.md** (~150 lines, Part 6; design.md now 851 lines / 6 parts). Decisions confirmed with Matthew up front (all three "recommended" picks): **(1) Excel-faithful paste + `$` pins** — relative refs shift by the paste offset, engine gains `$A$1`/`$A1`/`A$1` (lexer joins `$` to ident scan, parser predicate grows, `CellRef` gains defaulted `col_abs`/`row_abs` flags, evaluator/recalc stay indifferent — pinned and plain refs are the same dependency); **(2) OS clipboard both ways** — TSV mirror out via OSC 52, terminal `Paste` event in, with own-TSV detection so a bounce off the OS still uses the rich internal clipboard (key insight: Ctrl+V usually never reaches the app — it arrives AS the Paste event); **(3) cut = pragmatic move** — verbatim paste + source cleared in the same batch; inbound-reference rewriting explicitly deferred. The Part-5-style surface probe found this part's promotion: **public `trellis.shift_formula(text, rows, cols)`** — token-splice rewrite preserving formatting byte-for-byte, off-edge refs become literal `#REF!` (the error constant already exists in core). Selection = grid view state (anchor+cursor, Shift+arrows, Ctrl+A, delta-paint composing with error styling); every paste is ONE `sheet.batch()`. Implementation table #1–#7 (#1 = the pass, done); open questions: `#REF!` as parseable error literal (resolve at #3), click-modifier availability (#4), TSV flatten fidelity (#6).

**Part 6 #2 DONE (same session, later) — engine `$` references.** Lexer: `$` joins the ident scan (start + continue), so `$A$1` arrives as ONE lexeme; pin *placement* is the parser's job. Parser: new module-level `_ref_parts(text) -> (row, col, col_abs, row_abs)` — strips pins, delegates the clean body to `core.address.parse` (which stays `$`-free per the design), rejects `$$A1`/`A1$`/`$1A`/bare-`$`. `CellRef` gains defaulted frozen fields `col_abs`/`row_abs` (back-compat: `CellRef(r,c)` value-equal to explicitly-unpinned; pinned vs plain are DIFFERENT values — rewriters must tell them apart). Range corner-normalisation now swaps pins WITH their coordinates (`B$2:$A1` → `$A1:B$2`). Evaluator/recalc: untouched and verified indifferent — `=$A$1*2` evaluates like `=A1*2` and recalcs when A1 changes (the dep graph keys on `(row,col)`). Side-effect documented: `SU$M(1)` now parses as a call and dies at eval as `#NAME?` instead of dying at lex — still errors-are-values. Tests: +3 lexer, +14 parser, +1 recalc → **core 775**; TUI suite untouched at 86.

**Part 6 #3 DONE (same session, later) — public `shift_formula` + error literals.** New `formula/shift.py`: token-level splice — only reference lexemes are rewritten, at their exact `Token.pos` spans, so spacing/case/commas survive byte-for-byte; **references that don't move keep their original spelling** (pinned axes, zero offsets — so `shift(text,0,0)` is the true identity and `$a$1` stays lowercase), moved refs re-emit canonical uppercase. Function names are exempt via LPAREN lookahead (`LOG10(A1)` shifts only `A1`; bare `LOG10` IS a ref and shifts to `LOG11` — mirrors the parser's call-vs-ref rule, regression-tested). Ranges shift per-corner; **either corner off the edge collapses the whole `ref:ref` span to `#REF!`** (`=SUM(A1:B2)` up one → `=SUM(#REF!)`, Excel-shaped). Untokenizable text returns unchanged (a rewriter never raises on text the engine stores); broken-but-tokenizable (`=SUM(A1`) shifts its refs — moving a broken formula works. **Open question RESOLVED: error literals are first-class source.** ERROR token kind (longest-match over the seven codes — `#N/A` vs `#NAME?` tested), frozen `Error` AST node, evaluator resolves code→constant (mints unknown codes, open-world); `=#REF!*2` evaluates to `#REF!` and propagates, formula preserved for F2. `_BY_CODE` lookup added to errors.py. Public at all three levels + root-README bullet (the `infer_value` promotion pattern). Caught-by-staging note: the evaluator patch initially forgot its two imports — the staged-file verify habit caught it before it ever hit the mount. Tests: `test_formula_shift.py` — a 28-row shift table (the table IS the spec) + surface/round-trip/error-literal tests, 41 in all → **core 816**; TUI untouched at **86**.

**SESSION 33 CLOSE — state at handoff (Matthew breaking here, fresh session next).**
- **Done this session:** `formulas=` CSV round-trip (b2f486f, field-verified "works flawlessly"); Part 6 designed (3dffddc); Part 6 engine half — #2 `$` refs (fdbb842), #3 `shift_formula` + first-class error literals (1e88762). Suites at close: **core 816, TUI 86**, both green, tree clean.
- **Push state:** Matthew pushed mid-session through 3dffddc (an earlier "main 11 ahead" projection in this entry is stale — ignore it); at close only fdbb842 + 1e88762 are ahead. He'll push from Windows.
- **demo.csv** (grocery sheet, formulas) sits untracked at repo root — works in the TUI now; commit-or-delete is Matthew's call.
- **NEXT: Part 6 row #4 — TUI selection model.** Before coding, read design.md Part 6 §"TUI architecture" (selection = grid-owned `(anchor, cursor)`, Shift+arrows extend, Ctrl+A = used_range, Esc collapses, delta-paint composing with error styling, `B2:D5 (3×4)` readout, Delete clears selection) + grid.py and app.py. Then #5 internal clipboard (one-batch paste, shift per-cell offsets, fill-on-paste), #6 cut + OS bridge (TSV out via copy_to_clipboard, Paste event in, own-TSV detection — Ctrl+V usually ARRIVES as the Paste event), #7 READMEs/docs.
- **Task list will be empty again** (chat archive wipes it) — rebuild as: ① Part 6 row #4 selection model ② row #5 clipboard ③ row #6 cut+OS bridge ④ row #7 docs ⑤ Matthew: push. Open questions for #4 live in design.md Part 6 (click-modifier availability, repaint threshold).

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