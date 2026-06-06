"""Display policy: engine value -> grid/bar text (design.md Part 5 #3).

Pure functions only — this module imports the engine, never textual, so
the policy is testable as plain Python and reusable by any frontend.

The rules (Excel-faithful where that's cheap, honest everywhere):

- ``None`` -> ``""`` (an empty cell shows nothing).
- ``str`` -> as-is, left-aligned. No quoting, no escaping; a literal
  ``"#DIV/0!"`` *string* renders identically to the error but carries
  ``error=False`` — the styling distinguishes them.
- ``bool`` -> ``TRUE`` / ``FALSE``, centered (Excel renders logicals as
  uppercase keywords, centered). Checked BEFORE int: bool subclasses int.
- ``int`` -> ``str(x)``, right-aligned.
- ``float`` -> right-aligned, three-step rule (decided in #3):
  integral floats within ``±1e16`` render in integer form (``4.0`` -> ``4``,
  exact through 2**53); otherwise ``%.15g``, which keeps 15 significant
  digits — enough to be honest, few enough to trim one-ulp arithmetic
  noise (``=0.1+0.2`` shows ``0.3``, not ``0.30000000000000004``);
  non-finite values render as ``NaN`` / ``Infinity`` / ``-Infinity``
  (honest Python, not error cosplay — they are values, not FormulaErrors).
- ``FormulaError`` -> its ``code`` (``#DIV/0!``), centered, ``error=True``.
  Works for any constructed error, not a closed enum — a plugin's minted
  ``#NUM!`` renders like a built-in.
- anything else -> ``str(value)``, left. Plugins may store odd things in
  cells; the renderer's job is to show them, never to crash.

There is deliberately NO display-format system here (number formats,
date formats, decimal places) — that's a future plugin story, per
design.md Part 3's do-NOT-pre-build list.

Subtlety flagged for #5: ``display()`` is lossy for noisy floats (15g).
A revise-edit (F2) that prefills from display text could therefore alter
a stored value on commit; the editor should prefill from ``cell.formula``
or ``repr(value)`` instead. Recorded in design.md Part 5 open questions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from trellis import FormulaError

__all__ = ["DisplayText", "display"]

Align = Literal["left", "right", "center"]

#: Magnitude bound for rendering integral floats in integer form. Floats
#: are exact integers through 2**53 (~9.007e15); past 1e16 the int form
#: would print false precision, so %.15g (scientific) takes over.
_INT_FORM_LIMIT = 1e16


@dataclass(frozen=True)
class DisplayText:
    """What one cell renders as: the text plus the hints a view needs.

    ``align`` is a Rich ``justify`` value; ``error`` marks FormulaError
    values so views can style them distinctly (the grid uses red).
    """

    text: str
    align: Align = "left"
    error: bool = False


def _float_text(x: float) -> str:
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x.is_integer() and abs(x) < _INT_FORM_LIMIT:
        return str(int(x))  # Excel-faithful: =8/2 shows 4, not 4.0
    return f"{x:.15g}"  # trims one-ulp noise: 0.1+0.2 -> "0.3"


def display(value: Any) -> DisplayText:
    """Render an engine cell value for the grid and formula bar.

    Total function: never raises, whatever a cell holds. See the module
    docstring for the rule table; ``tests/test_render.py`` is the spec.
    """
    if value is None:
        return DisplayText("")
    if isinstance(value, FormulaError):
        return DisplayText(value.code, align="center", error=True)
    if isinstance(value, bool):  # before int: bool subclasses int
        return DisplayText("TRUE" if value else "FALSE", align="center")
    if isinstance(value, (int, float)):
        text = _float_text(value) if isinstance(value, float) else str(value)
        return DisplayText(text, align="right")
    if isinstance(value, str):
        return DisplayText(value)
    return DisplayText(str(value))  # plugin-stored oddities render honestly
