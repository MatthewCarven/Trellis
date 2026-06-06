---
name: trellis-tui-in-repo-frontend
description: "Decision: build the Trellis TUI as an in-repo companion FRONTEND package (packages/trellis-tui/), not a fork/separate repo. It drives the engine from outside; it is not a plugin."
metadata: 
  node_type: memory
  type: project
  originSessionId: 30141e71-1e33-4c90-b8c5-5c767acff512
---

**Decision (2026-06-05, with Matthew):** the TUI is built as an in-repo companion package at `packages/trellis-tui/`, mirroring `packages/trellis-mathpack/`. NOT a separate repo / fork — at least until core stabilizes (~1.0).

**Frontend, not a plugin — the distinction matters.** mathpack is a *plugin*: loaded INTO the engine via the `trellis.plugins` entry point, adds functions. The TUI is a *frontend*: it imports `trellis` and drives it from the OUTSIDE; core never knows it exists ("library first, app second"). Same home (`packages/`), same one-line `dependencies = ["trellis"]`, but it is an app on top of the library, not an extension loaded into it. Its `textual` dependency lives in the TUI package's pyproject — core stays dependency-free. (Core's existing `tui = ["textual>=0.50"]` extra is just a convenience hook; TUI code does NOT go in `src/trellis/`.)

**Why in-repo not forked:** Matthew said "I don't really know git" — the monorepo path needs zero new git knowledge (just another folder, committed as usual), whereas a separate repo demands publishing core, version pinning, and juggling two histories. Architecture agrees: the TUI is the prime consumer of the Part 3 public surface (like mathpack was for the plugin API) and benefits from atomic cross-boundary commits while the surface is young. Splitting to its own repo later is cheap + preserves history (git subtree/filter-repo); un-splitting is the painful direction. If Matthew later wants the split, Claude runs it for him — he doesn't need to learn git.

**Folder rename:** Matthew will rename the project folder from "Cross Tabulator Pro" to **Trellis** and delete the empty sibling `Trellis/` folder before the next cowork session. Cosmetic — git tracks contents not folder name; nothing in code hardcodes the path (src layout is relative; the tier2 script resolves repo root from its own location). Next session will be in the renamed folder.

**Next session pickup:** scope + start `packages/trellis-tui/` (textual frontend). Recorded in CLAUDE.md "Repository layout". Related: [[trellis-roadmap-position]], [[trellis-publication-gated-on-client]], [[design-philosophy-open-extensibility]].
