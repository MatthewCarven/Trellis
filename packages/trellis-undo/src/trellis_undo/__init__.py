"""trellis-undo — undo/redo for any Trellis sheet (design.md Part 7).

The second reference plugin, and the *stateful attachment* one: where
mathpack registers global formula functions through an entry point at
``import trellis``, this package attaches live :class:`UndoLog` objects
to sheets you hand it — subscribing to the locked Part 3 events and
stashing itself under ``sheet.meta["undo"]`` (one namespaced key, per
the meta convention). No entry point, no core changes: events + meta
are the whole API surface it needs.

Contract:

- **One recorded event = one undo step.** ``cell:change`` is a 1-cell
  step; ``sheet:batch`` (a paste, a selection delete, a CSV load) is
  one step of N cells. ``cell:recalc`` is never recorded — derived
  values re-derive on restore.
- **Steps hold the payload's ``Cell`` objects** and restore by object:
  ``sheet.set(addr, cell)`` stores the instance as-is, the recalc
  engine re-evaluates restored formulas and their dependents (stale
  snapshot values self-heal), and plugin state in ``meta`` rides along.
  Cells that were empty restore as ``sheet.delete`` — absence stays
  absence. Out-of-band ``meta`` mutations are not engine writes and are
  therefore not history events.
- **The log never records itself.** Undo moves a step to the redo
  stack; redo moves it back; any *recorded* new write clears redo.
- **History is capped** (default :attr:`UndoLog.CAPACITY` = 1000
  steps; oldest drop silently). Pass ``capacity=None`` for unbounded —
  the house escape-hatch pattern.

REPL taste::

    from trellis import Workbook
    from trellis_undo import attach

    wb = Workbook(); sh = wb.add_sheet("S")
    log = attach(sh)            # also at sh.meta["undo"]
    sh["A1"] = 10
    sh["A1"] = 20
    log.undo()                  # A1 == 10 again
    log.redo()                  # A1 == 20 again
"""

from __future__ import annotations

from collections import deque
from typing import Any

from trellis import Sheet, Workbook

__version__ = "0.1.0"

__all__ = [
    "META_KEY",
    "UndoLog",
    "attach",
    "attach_workbook",
    "detach",
    "__version__",
]

#: Where :func:`attach` stashes the log on the sheet (the plugin's single
#: namespaced ``meta`` key, by convention).
META_KEY = "undo"

_DEFAULT = object()  # sentinel: "use the class default capacity"


class UndoLog:
    """Per-sheet undo/redo history over the engine's own change events.

    Construct directly for a bare log, or use :func:`attach` to also
    register it in ``sheet.meta``. The log subscribes on construction
    and records until :meth:`detach`.
    """

    #: Default history bound, in steps. Subclass-or-argument tunable;
    #: ``None`` means unbounded.
    CAPACITY: int | None = 1000

    def __init__(self, sheet: Sheet, *, capacity: Any = _DEFAULT) -> None:
        self.sheet = sheet
        if capacity is _DEFAULT:
            capacity = self.CAPACITY
        self.capacity = capacity
        self._undo: deque = deque(maxlen=capacity)
        self._redo: list = []
        self._restoring = False
        self._subs = [
            sheet.on("cell:change", self._on_change),
            sheet.on("sheet:batch", self._on_batch),
        ]

    # ------------------------------------------------------------ recording

    def _on_change(self, **ev: Any) -> None:
        if self._restoring:
            return  # our own restore write: history, not a new event
        self._record(((tuple(ev["address"]), ev["old"], ev["new"]),))

    def _on_batch(self, **ev: Any) -> None:
        if self._restoring:
            return
        step = tuple(
            (tuple(ch["address"]), ch["old"], ch["new"]) for ch in ev["changes"]
        )
        if step:
            self._record(step)

    def _record(self, step: tuple) -> None:
        self._undo.append(step)  # deque(maxlen) drops the oldest silently
        self._redo.clear()  # a new write forks history: redo dies

    # -------------------------------------------------------------- surface

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def depths(self) -> tuple[int, int]:
        """``(undo_steps, redo_steps)`` — for save-point bookkeeping."""
        return (len(self._undo), len(self._redo))

    def undo(self) -> int | None:
        """Restore the newest step's ``old`` cells. Returns the number of
        cells restored, or ``None`` when there is nothing to undo."""
        if not self._undo:
            return None
        step = self._undo.pop()
        self._restore(step, old_side=True)
        self._redo.append(step)
        return len(step)

    def redo(self) -> int | None:
        """Re-apply the newest undone step (its ``new`` cells)."""
        if not self._redo:
            return None
        step = self._redo.pop()
        self._restore(step, old_side=False)
        self._undo.append(step)
        return len(step)

    def clear(self) -> None:
        """Forget all history (both stacks). The log keeps recording."""
        self._undo.clear()
        self._redo.clear()

    def detach(self) -> None:
        """Unsubscribe from the sheet. The log stops recording; undoing
        a detached log would restore stale state, so the stacks clear."""
        for unsubscribe in self._subs:
            unsubscribe()
        self._subs = []
        self.clear()

    # -------------------------------------------------------------- restore

    def _restore(self, step: tuple, *, old_side: bool) -> None:
        self._restoring = True
        try:
            if len(step) == 1:
                address, old, new = step[0]
                self._write(address, old if old_side else new)
            else:
                with self.sheet.batch():  # one echo, one recalc pass
                    for address, old, new in step:
                        self._write(address, old if old_side else new)
        finally:
            self._restoring = False

    def _write(self, address: tuple[int, int], cell: Any) -> None:
        if cell.value is None and cell.formula is None:
            # "Was empty" restores as absence, not as a stored husk.
            self.sheet.delete(address)
        else:
            # Object restore: the engine stores Cell instances as-is;
            # recalc re-evaluates formulas (and dependents) against the
            # CURRENT sheet — undone values self-heal, Excel-style.
            self.sheet.set(address, cell)


# ------------------------------------------------------- attachment helpers


def attach(sheet: Sheet, **kwargs: Any) -> UndoLog:
    """Attach an :class:`UndoLog` to ``sheet`` and stash it at
    ``sheet.meta["undo"]``. Idempotent: an already-attached sheet
    returns its existing log (kwargs ignored in that case)."""
    log = sheet.meta.get(META_KEY)
    if isinstance(log, UndoLog):
        return log
    log = UndoLog(sheet, **kwargs)
    sheet.meta[META_KEY] = log
    return log


def detach(sheet: Sheet) -> UndoLog | None:
    """Detach and remove the sheet's log (no-op without one)."""
    log = sheet.meta.pop(META_KEY, None)
    if isinstance(log, UndoLog):
        log.detach()
        return log
    return None


def attach_workbook(workbook: Workbook, **kwargs: Any) -> dict:
    """Attach a log to every current sheet — and, via the workbook's
    ``sheet:add`` event, every future one. Returns ``{name: UndoLog}``
    for the sheets that exist now; later sheets' logs live where they
    always do, at ``sheet.meta["undo"]``. Logs are independent
    per-sheet histories (no cross-sheet transactions — design.md
    Part 7, Rejected)."""
    logs = {sheet.name: attach(sheet, **kwargs) for sheet in workbook.sheets()}
    workbook.on("sheet:add", lambda **ev: attach(ev["sheet"], **kwargs))
    return logs
