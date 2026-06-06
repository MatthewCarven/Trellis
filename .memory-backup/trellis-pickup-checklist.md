---
name: trellis-pickup-checklist
description: "When picking up the Trellis project (the spreadsheet framework in the \"Cross Tabulator Pro\" folder), read these docs in this order to be caught up"
metadata: 
  node_type: memory
  type: project
  originSessionId: f41ce9c6-54d4-4aa3-9871-15a925746349
---

If a session starts with "let's continue with Trellis" or similar, read these in order:

1. **`CLAUDE.md`** (project root) — conventions: package name is `trellis`, src-layout, Python 3.11+, `meta = {}` dict is the polite extension surface, MIT, etc. Short.
2. **`WORKLOG.md`** — newest entry on top is always the most recent state. Tells you: what just shipped, what tests are passing, what's blocked, what's the next pick-up. **This is the single most useful file.**
3. **TaskList** (via the `TaskList` tool) — gives you the task graph. The lowest-ID `in_progress` or unblocked `pending` task is usually the next chunk. Subtask descriptions are self-contained briefs.
4. **`design.md`** — only if you're working on something the doc covers. Part 1 is the event system (shipped); Part 2 is the formula engine (#4 + its subtasks). Each part has rationale, rejected alternatives, and a per-subtask breakdown.
5. **`README.md`** — high-level orientation, the "Quick taste" snippet, the "Extending" walkthrough. Skim if you've never seen the project.

Auto-memory that always loads (don't re-read, just be aware):
- `design-philosophy-open-extensibility` — chaotic-good extensibility, hooks over locks.
- `write-protocol-mount-folders` — the stage+cp+sync+verify protocol for non-trivial writes. Mandatory in this folder.
- `simplicity-over-clever-solvers` — default to naive algorithm + user escape hatch, especially in recalc / dispatch / scheduling.
- `trellis-publication-gated-on-client` — no time pressure; not publishing to GitHub until a real consumer (TUI or example program) has exercised the public API.

**Mental model:** Trellis is a pure-Python spreadsheet *framework* (not an app). Zero required deps. Core is `Cell` / `Sheet` / `Workbook` / `Range` / `Emitter`. The formula engine layers on top in `trellis.formula`. The TUI and plugins come later. Don't add features that can't be expressed as a plugin — that's the design test in CLAUDE.md.

**The pattern that's been working:** big subtasks get a `design.md` section first, then split into smaller subtasks (each independently shippable, with tests bundled). When Matthew greenlights, build the chunk in one bash batch + run pytest. Every subtask since #16 has landed first-run green — the design-doc → subtask-split → implement pipeline is the reason. Trust it.
