"""Formula bar (+ the edit-mode state machine, landing in Part 5 #5).

This module is the *controller* side of the app. As of #4 it holds the
nav-mode half: ``FormulaBar``, a one-line readout that mirrors the
cursor's cell — ``cell.formula`` when set (the engine stores formulas
with their leading ``=``), else the rendered value. The edit-mode state
machine (#5) turns the bar into the single editing surface:

- Two modes. **nav**: cursor on the grid, bar mirrors. **edit**: focus
  in the bar's ``Input`` — replace-edit (typing starts empty) or
  revise-edit (F2, prefilled).
- Commit: leading ``=`` stores text as-is (engine formula sugar);
  otherwise through ``trellis.infer_value`` so typing ``42`` stores a
  number while ``01234`` stays a string. Empty commit: open question
  (lean: delete).
- Prefill fidelity (flagged in #3): prefill from ``cell.formula`` /
  ``repr(value)``, never from display text — ``display()`` is 15g-lossy
  for noisy floats.

Known nav-mode nit (accepted for #4): the bar refreshes on cursor moves,
not on engine writes under a stationary cursor; #5's commit flow
refreshes it explicitly.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from trellis import Sheet, to_a1

from .render import display

__all__ = ["FormulaBar"]


class FormulaBar(Static):
    """One-line cell readout: ``  B2 │ =A1*2``.

    ``shown`` keeps the last ``(address_a1, content)`` pair as plain
    strings — handy for tests and for #5's revise-edit to build on.
    """

    DEFAULT_CSS = """
    FormulaBar {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.shown: tuple[str, str] = ("", "")

    def show_cell(self, sheet: Sheet, address: tuple[int, int]) -> None:
        """Mirror one cell: formula if set (with its ``=``), else the
        rendered value."""
        a1 = to_a1(*address)
        cell = sheet[a1]
        content = cell.formula if cell.formula is not None else display(cell.value).text
        self.shown = (a1, content)
        line = Text()
        line.append(f"{a1:>5} ", style="bold")
        line.append("│ ", style="dim")
        line.append(content)
        self.update(line)


# TODO(Part 5 #5): edit-mode state machine (replace/revise edits, commit
# via infer_value, Esc cancel, Delete clear, dirty flag).
