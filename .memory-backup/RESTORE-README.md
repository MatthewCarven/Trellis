# Memory backup — Trellis (Claude auto-memory)

Created 2026-06-06 before renaming/moving the project folder from
"Cross Tabulator Pro" to "Trellis".

## What this is
A verbatim copy of Claude's auto-memory for this project's memory "space".
These files normally live OUTSIDE the project folder, in the Claude app's
AppData area, keyed by an internal space ID. They are copied here as a
safety net so they survive — and can be restored — no matter what happens
to the folder↔space link during the rename/move.

10 memory files + MEMORY.md (the index). MEMORY.md is the one loaded into
context each session; each .md is one fact with frontmatter.

## How to restore (only if a future session comes up blank on Trellis)
If, after the rename/move, Claude no longer recalls the Trellis context,
the new session created a fresh empty memory space. Ask Claude to:
1. Find the new space's memory directory (under the Claude AppData
   local-agent-mode-sessions .../spaces/<new-id>/memory/).
2. Copy every .md from this folder into that directory.
3. Confirm MEMORY.md lists all 10 entries.

That's it — the link is restored.
