"""Formula bar + edit-mode state machine. Lands in Part 5 #5.

Contract (design.md Part 5, "Interaction model"):

- Two modes. **nav**: cursor on the grid; the bar mirrors the current cell
  (``cell.formula`` if set, else rendered value). **edit**: focus in the
  bar's ``Input`` — replace-edit (typing starts empty) or revise-edit (F2,
  prefilled).
- Commit (Enter/Tab + shifted variants): leading ``=`` stores the text
  as-is (the engine's formula sugar takes over); otherwise the text runs
  through ``trellis.infer_value`` so typing ``42`` stores a number while
  ``01234`` stays a string — coherent with CSV load. Empty commit: store
  ``""`` vs delete is an open question (lean: delete).
- Esc cancels and restores the bar. ``Delete`` in nav mode clears the cell
  via ``sheet.delete``. Dirty flag rides the same engine events.
"""

from __future__ import annotations

# TODO(Part 5 #5): implement the bar widget + mode state machine + Pilot tests.
