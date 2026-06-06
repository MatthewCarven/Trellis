---
name: trellis-publication-gated-on-client
description: "GATE CLEARED 2026-06-05 (Session 28): trellis-mathpack now exercises the public API end-to-end via a real editable install + auto-discovery. The first GitHub push is unblocked but NOT yet done — Matthew's call, no time pressure."
metadata: 
  node_type: memory
  type: project
  originSessionId: 6e3f251b-2621-4c11-99be-48f5180a7a37
---

Matthew decided NOT to push Trellis to GitHub until a real consumer has exercised the engine end-to-end. His words (2026-05-27): "it would be unwise to offer it publicly without first putting it through some usage first." No current time pressure across ANY of his projects (supersedes the older [[trellis-deadline-pressure]] framing).

**Why:** A passing test suite proves correctness, not API ergonomics. Public release locks the surface — better to find awkward bits via a real consumer first.

**Update 2026-06-05 (Session 28): GATE CLEARED.** `trellis-mathpack` (design.md Part 4, built Sessions 23–28) is complete: 20 functions exercising `register_function`, the `(ctx, *args)` convention, `FormulaError` construction (its own `#NUM!`), range/aggregate handling, and `entry_points` auto-discovery. The Tier-2 proof (`packages/trellis-mathpack/scripts/tier2_discovery_check.sh`, commit 8e8ac48) editable-installs core + mathpack into an off-mount venv and a fresh `import trellis` auto-discovers all 20 functions with no manual setup() — plus a negative control. Mathpack never reached for a core internal, so no public-surface gaps were found.

**How to apply now:**
- The push is **unblocked but not done**. Treat it as Matthew's decision — offer it, don't assume it. Nothing has been pushed; the `Homepage` URL in core `pyproject.toml` is still commented out (uncomment when publishing). No time pressure.
- The other live next-step is the **TUI** (`trellis-tui`). See [[trellis-roadmap-position]].
