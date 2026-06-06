"""Display policy: engine value -> grid/bar text. Lands in Part 5 #3.

Pure functions only — this module never imports textual, so the policy is
testable as plain Python. Planned rules (design.md Part 5, "Rendering
policy"): ``None`` -> ``""``; ``str`` as-is (no quoting); ``bool`` ->
``TRUE``/``FALSE`` (Excel-faithful); ``int`` -> ``str(x)``; ``float`` ->
repr-with-trimming (exact rule decided in #3 with table-driven tests);
``FormulaError`` -> its code (``#DIV/0!``), styled distinct. Numbers
right-aligned, text left. NO display-format system in v1.
"""

from __future__ import annotations

__all__ = ["display"]


def display(value) -> str:
    """Render an engine cell value for the grid and formula bar.

    Placeholder: implemented in Part 5 #3.
    """
    raise NotImplementedError("trellis-tui display policy lands in Part 5 #3")
