"""SheetGrid — the DataTable-backed grid view. Lands in Part 5 #4.

Contract (design.md Part 5, "The shape"):

- Materializes a window = ``sheet.used_range()`` ∪ a minimum size into a
  textual ``DataTable`` (cell-cursor mode), with ``A B C…`` column headers
  and ``1 2 3…`` row labels; grows on demand as the cursor nears an edge.
- Subscribes to the engine: ``cell:change`` / ``cell:recalc`` repaint one
  cell via ``update_cell_at`` (skipping no-ops by comparing the payload's
  ``old_value``/``new_value``); ``sheet:batch`` walks its ``changes`` — or
  rebuilds the window once when the batch dwarfs it (CSV load).
- Read-only toward the engine: the grid never calls ``sheet.set`` and never
  patches its own cells outside the event echo. Writes are the controller's
  job (``editor.py``).
"""

from __future__ import annotations

# TODO(Part 5 #4): implement SheetGrid (window materialization, headers,
# cursor, event-driven repaint incl. sheet:batch) + Pilot tests.
