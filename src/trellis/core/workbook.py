"""Workbook — a named, ordered collection of Sheets.

Workbooks are :class:`~trellis.core.events.Emitter` s and fire sheet-lifecycle
events:

    "sheet:add"     payload: sheet
    "sheet:remove"  payload: name, sheet
    "sheet:rename"  payload: old, new, sheet

These events describe the workbook's own collection only. To watch every cell
in every sheet, subscribe to ``"sheet:add"`` here and attach a
``"cell:change"`` handler to each new sheet.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .events import Emitter
from .sheet import Sheet


class Workbook(Emitter):
    """Container for one or more sheets.

    >>> wb = Workbook()
    >>> events = []
    >>> _ = wb.on("sheet:add", lambda sheet: events.append(sheet.name))
    >>> sh = wb.add_sheet("Data")
    >>> sh["A1"] = 42
    >>> events
    ['Data']
    >>> wb["Data"]["A1"].value
    42
    """

    def __init__(self):
        self._sheets: dict[str, Sheet] = {}
        self.meta: dict[str, Any] = {}  # plugin scratch space; core never writes here

    def add_sheet(self, name: str = "Sheet1") -> Sheet:
        """Create and return a new sheet. Raises if ``name`` already exists.

        Emits ``"sheet:add"`` with payload ``sheet``.
        """
        if name in self._sheets:
            raise ValueError(f"Sheet {name!r} already exists in this workbook")
        sheet = Sheet(name=name)
        self._sheets[name] = sheet
        self.emit("sheet:add", sheet=sheet)
        return sheet

    def add(self, sheet: Sheet) -> Sheet:
        """Attach an existing Sheet (e.g. a subclass) to the workbook.

        The sheet's ``name`` must not collide with one already in the workbook.
        Emits ``"sheet:add"`` with payload ``sheet``. Returns the sheet for
        convenience.
        """
        if sheet.name in self._sheets:
            raise ValueError(f"Sheet {sheet.name!r} already exists in this workbook")
        self._sheets[sheet.name] = sheet
        self.emit("sheet:add", sheet=sheet)
        return sheet

    def remove_sheet(self, name: str) -> None:
        """Remove the sheet with this name. Raises KeyError if absent.

        Emits ``"sheet:remove"`` with payload ``name``, ``sheet``.
        """
        if name not in self._sheets:
            raise KeyError(name)
        sheet = self._sheets.pop(name)
        self.emit("sheet:remove", name=name, sheet=sheet)

    def rename_sheet(self, old: str, new: str) -> None:
        """Rename a sheet, preserving insertion order. Raises if ``new`` is taken.

        Emits ``"sheet:rename"`` with payload ``old``, ``new``, ``sheet``.
        """
        if old not in self._sheets:
            raise KeyError(old)
        if new in self._sheets:
            raise ValueError(f"Sheet {new!r} already exists in this workbook")
        # Rebuild the dict to preserve order at the same position.
        rebuilt: dict[str, Sheet] = {}
        renamed: Sheet | None = None
        for name, sheet in self._sheets.items():
            if name == old:
                sheet.name = new
                rebuilt[new] = sheet
                renamed = sheet
            else:
                rebuilt[name] = sheet
        self._sheets = rebuilt
        self.emit("sheet:rename", old=old, new=new, sheet=renamed)

    def sheets(self) -> Iterator[Sheet]:
        """Iterate sheets in insertion order."""
        return iter(self._sheets.values())

    # --- dict-like sugar --------------------------------------------------

    def __getitem__(self, name: str) -> Sheet:
        return self._sheets[name]

    def __contains__(self, name: object) -> bool:
        return name in self._sheets

    def __len__(self) -> int:
        return len(self._sheets)

    def __iter__(self) -> Iterator[str]:
        return iter(self._sheets)  # iterate names, dict-style

    def __repr__(self) -> str:
        return f"Workbook(sheets={list(self._sheets)!r})"
