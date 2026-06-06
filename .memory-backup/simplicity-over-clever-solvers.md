---
name: simplicity-over-clever-solvers
description: "For Trellis (and Matthew's projects in general) prefer the naive algorithm with a user-escape-hatch over building a clever solver; only earn the cleverness when there's a concrete failure"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f41ce9c6-54d4-4aa3-9871-15a925746349
---

When facing a "should I write a clever algorithm here?" moment in core code, default to the naive approach plus a way for the user to override if it matters. Don't pre-build sophisticated solvers (topological reordering for cheapest-path recalc, query planners, schedulers, etc.) without a concrete proven need.

**Why:** Matthew said on 2026-05-27 about the formula recalc engine: "we are not here to write a dependency sorter to serialise the order of applied formulas cheapest path, if it becomes an issue we will push it back onto the user via having them specify the order of ops so to speak somehow etc." Cleverness is debt — it's code to maintain, edge cases to fight, and complexity that mostly nobody needs. Naive + escape hatch ships sooner and is easier to evolve.

**How to apply:**
- For recalc, dependency resolution, scheduling, etc.: start with forward BFS / naive topological sort / linear scan. Document the limitation.
- If a user hits a real performance or correctness wall, add an *opt-in* override (a flag, a config knob, a callback) — not a smarter default.
- This is the same shape as the [[design-philosophy-open-extensibility]] hand: give users sharp tools and trust them to wield them, rather than pre-solving every problem they might not even have.
- Don't apply this rule to *correctness* — cycle detection in the recalc engine still needs to be right. The shortcut is on *optimization*, not on *what the engine guarantees*.
