---
name: trellis-file-io-csv-only
description: "Matthew's real-world Trellis usage is CSV-only; xlsx is not a near-term priority"
metadata: 
  node_type: memory
  type: user
  originSessionId: 7cf7f7e2-9c90-411a-906d-c4ac24bcdbe9
---

Matthew said "I only really work with csvs anyways" when scoping file I/O for the pre-break milestone (Session 16, 2026-05-27). For Trellis file I/O work, prefer CSV-first; treat xlsx as nice-to-have but not load-bearing.

**Why:** Self-reported actual usage. He'd been worried about openpyxl complexity ("how difficult xlsx is to open?") and the comparison made the CSV-only path obvious.

**How to apply:** When designing or scoping file I/O features for Trellis, optimise for the CSV path. xlsx (if revisited) should probably stay read-only-values, not full round-trip — that lines up with the "don't pre-build sophisticated solvers" rule. See [[trellis-deadline-pressure]] and [[simplicity-over-clever-solvers]].
