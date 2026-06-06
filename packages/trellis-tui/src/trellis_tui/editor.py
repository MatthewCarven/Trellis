"""Formula bar + the edit-mode state machine (design.md Part 5 #5).

The controller side of the app. Two modes:

- **nav** — cursor on the grid; the bar mirrors the cursor's cell
  (``cell.formula`` when set, else the rendered value).
- **edit** — focus in the bar's ``CellEditor`` (an ``Input``): either a
  *replace-edit* (typing in nav mode starts empty/seeded) or a
  *revise-edit* (F2 / Enter, prefilled with high-fidelity text).

The pure helpers carry the policy; the widgets stay thin:

- ``prefill_text(cell)`` — what a revise-edit starts from: the formula
  (with its ``=``) when set; else ``repr`` for floats (NOT the 15g-lossy
  display text — the #3 flag), the string itself for strings,
  ``TRUE``/``FALSE`` for bools, the code for error values, ``""`` for
  empty.
- ``commit_text(sheet, address, text)`` — the ONLY write path the TUI
  has: empty text deletes the cell (DECIDED: Excel-faithful, keeps
  ``used_range()`` tight; delete is tolerant of already-empty cells);
  leading ``=`` stores the text as-is (engine formula sugar — a broken
  formula does NOT block commit, it stores as its error value with the
  formula preserved for F2); anything else goes through the public
  ``trellis.infer_value`` so typing ``42`` stores a number while
  ``01234`` stays a string, coherent with CSV load.

**Unchanged-revise rule:** committing a revise-edit whose text was not
modified writes nothing at all. This is what makes F2 + Enter a true
no-op on values whose text form can't round-trip (``True`` would
re-infer as the *string* ``"TRUE"`` — bools are deliberately not
inferred, per the CSV policy).
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Input, Label, Static

from trellis import FormulaError, Sheet, infer_value, to_a1

from .render import display

__all__ = ["CellEditor", "FormulaBar", "commit_text", "prefill_text"]


# --------------------------------------------------------------- policy


def prefill_text(cell: Any) -> str:
    """The text a revise-edit starts from (full fidelity, never display)."""
    if cell.formula is not None:
        return cell.formula  # stored with its leading "="
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, FormulaError):
        return value.code
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return repr(value)  # exact round-trip through infer_value
    if isinstance(value, str):
        return value
    return str(value)  # int + plugin-stored oddities


def commit_text(sheet: Sheet, address: tuple[int, int], text: str) -> None:
    """The TUI's single engine-write path. See the module docstring."""
    a1 = to_a1(*address)
    if text == "":
        sheet.delete(a1)  # empty commit clears (tolerant of already-empty)
        return
    if text.startswith("="):
        sheet[a1] = text  # engine sugar; broken formulas store as errors
        return
    sheet[a1] = infer_value(text)


# --------------------------------------------------------------- widgets


class CellEditor(Input):
    """The bar's input. Translates commit/cancel keys into one message."""

    _MOVES = {
        "enter": (1, 0),
        "shift+enter": (-1, 0),
        "tab": (0, 1),
        "shift+tab": (0, -1),
    }

    class Done(Message):
        """An edit ended. ``commit`` False = cancelled (Esc)."""

        def __init__(self, text: str, move: tuple[int, int], commit: bool) -> None:
            self.text = text
            self.move = move
            self.commit = commit
            super().__init__()

    def on_key(self, event) -> None:
        if event.key in self._MOVES:
            event.stop()
            event.prevent_default()
            self.post_message(self.Done(self.value, self._MOVES[event.key], True))
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.Done(self.value, (0, 0), False))


class FormulaBar(Horizontal):
    """One-line bar: address label + (mirror readout | cell editor).

    ``shown`` keeps the last mirrored ``(address_a1, content)`` pair as
    plain strings — for tests and chrome. ``editing`` reflects the mode.
    """

    DEFAULT_CSS = """
    FormulaBar {
        height: 1;
    }
    FormulaBar > Label {
        width: 7;
        padding: 0 1;
        text-style: bold;
    }
    FormulaBar > Static#fb-view {
        width: 1fr;
    }
    FormulaBar > CellEditor,
    FormulaBar > CellEditor:focus {
        display: none;
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }
    FormulaBar.editing > Static#fb-view {
        display: none;
    }
    FormulaBar.editing > CellEditor,
    FormulaBar.editing > CellEditor:focus {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.shown: tuple[str, str] = ("", "")

    def compose(self):
        yield Label("A1", id="fb-address")
        yield Static(id="fb-view")
        # select_on_focus=False: focusing must NOT select the seeded
        # prefill, or the next keystroke would replace it wholesale
        # (found by the Pilot suite: "=A1*2" arrived as "A1*2").
        yield CellEditor(id="fb-input", select_on_focus=False)

    @property
    def editing(self) -> bool:
        return self.has_class("editing")

    # nav mode -----------------------------------------------------------

    def show_cell(self, sheet: Sheet, address: tuple[int, int]) -> None:
        """Mirror one cell: formula if set (with its ``=``), else value."""
        a1 = to_a1(*address)
        cell = sheet[a1]
        content = cell.formula if cell.formula is not None else display(cell.value).text
        self.shown = (a1, content)
        self.query_one("#fb-address", Label).update(a1)
        line = Text()
        line.append("│ ", style="dim")
        line.append(content)
        self.query_one("#fb-view", Static).update(line)

    def show_range(self, cursor_a1: str, readout: str) -> None:
        """Mirror a live selection (Part 6 #4): the ``B2:D5 (3\u00d74)``
        readout replaces the cell mirror; the label keeps the cursor's
        address. Plain ``show_cell`` resumes when the selection collapses.
        """
        self.shown = (cursor_a1, readout)
        self.query_one("#fb-address", Label).update(cursor_a1)
        line = Text()
        line.append("\u2502 ", style="dim")
        line.append(readout, style="bold")
        self.query_one("#fb-view", Static).update(line)

    # edit mode ----------------------------------------------------------

    def start_edit(self, a1: str, prefill: str) -> None:
        self.add_class("editing")
        self.query_one("#fb-address", Label).update(a1)
        editor = self.query_one(CellEditor)
        editor.value = prefill
        editor.cursor_position = len(prefill)
        editor.focus()

    def end_edit(self) -> None:
        self.remove_class("editing")
