"""Recalc engine + Workbook integration.

The recalc engine maintains a dependency graph of formula cells across all
sheets in a workbook. When a cell changes, it propagates updates to all
transitive dependents in topological order. Errors propagate naturally
through evaluation; circular references are caught and stored as ``CIRC``.

Architecture
------------

One engine per workbook. Attaching subscribes to:

* ``cell:change`` on each sheet — react to user-initiated changes
* ``sheet:add`` on the workbook — attach to new sheets as they appear
* ``sheet:remove`` on the workbook — clean up graph entries for removed sheets

Results are written back via :meth:`Sheet._set_value`, which emits
``"cell:recalc"`` instead of ``"cell:change"`` — the latter would re-trigger
the engine in an infinite loop.

Dependency model
----------------

A "cell key" is a tuple ``(sheet_name, row, col)``. Even though cross-sheet
references are out for v1, keying by sheet name future-proofs the graph and
keeps the algorithms identical when we add cross-sheet support.

For each formula cell ``C``::

    _asts[C]          = the parsed AST
    _dependencies[C]  = set of keys C reads (i.e. cells whose values feed C)
    _dependents[D]    = set of keys whose formulas read D
                        (the inverse of _dependencies — value cells too)

When ``D`` changes, every key in ``_dependents[D]`` needs to recompute. The
``_propagate`` method walks transitive dependents and recomputes them in
topological order.

Cycle handling
--------------

Before registering a new formula's dependencies, :meth:`_would_cycle` walks
from each new dep along ``_dependencies`` and reports True if it ever reaches
the target. If it would, the cell is written as ``CIRC`` and NOT registered —
this is deliberate. A registered cycle would let the engine loop forever
during ``_propagate``. Skipping registration means: (a) the cycle is contained
to this cell, (b) if the user fixes the formula later, the engine recovers
cleanly, (c) other cells that already depended on this cell still see its
``CIRC`` value through normal error propagation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .ast import BinaryOp, CellRef, FunctionCall, RangeRef, UnaryOp
from .errors import CIRC, NAME, FormulaError, ParseError
from .evaluator import Context, evaluate
from .parser import parse_formula

if TYPE_CHECKING:
    from trellis.core.cell import Cell
    from trellis.core.sheet import Sheet
    from trellis.core.workbook import Workbook


CellKey = tuple[str, int, int]


# --- Dependency extraction ---------------------------------------------


def extract_deps(ast: Any, sheet_name: str) -> set[CellKey]:
    """Return the set of cell keys this AST references.

    ``RangeRef`` nodes expand to the full rectangle of positions. ``CellRef``
    contributes one position. Literals (Number, String, Bool) contribute
    nothing. UnaryOp/BinaryOp/FunctionCall recurse into operands/args.

    The sheet name is supplied by the caller; cross-sheet refs are out
    for v1 so a CellRef has no sheet of its own — it always belongs to the
    holding sheet.
    """
    deps: set[CellKey] = set()

    def walk(node: Any) -> None:
        if isinstance(node, CellRef):
            deps.add((sheet_name, node.row, node.col))
        elif isinstance(node, RangeRef):
            for r in range(node.start.row, node.end.row + 1):
                for c in range(node.start.col, node.end.col + 1):
                    deps.add((sheet_name, r, c))
        elif isinstance(node, UnaryOp):
            walk(node.operand)
        elif isinstance(node, BinaryOp):
            walk(node.left)
            walk(node.right)
        elif isinstance(node, FunctionCall):
            for arg in node.args:
                walk(arg)
        # Literals: no deps

    walk(ast)
    return deps


# --- The engine ---------------------------------------------------------


class RecalcEngine:
    """Workbook-scoped recalc engine.

    Usage::

        wb = Workbook()
        # wb.recalc is already attached — no manual wiring needed.

        sh = wb.add_sheet("Demo")
        sh["A1"] = 10
        sh["B1"] = "=A1 * 2"
        assert sh["B1"].value == 20

        sh["A1"] = 100
        assert sh["B1"].value == 200   # auto-recalc

    Advanced users can construct an engine manually and call
    :meth:`attach` on a Workbook themselves. Use :meth:`detach` to stop
    the engine (e.g. during a batch import to skip per-cell recalc, then
    re-attach and trigger a full recompute).
    """

    def __init__(self) -> None:
        self._workbook: Workbook | None = None
        self._asts: dict[CellKey, Any] = {}
        self._dependents: dict[CellKey, set[CellKey]] = defaultdict(set)
        self._dependencies: dict[CellKey, set[CellKey]] = defaultdict(set)
        self._sheet_subs: dict[str, Any] = {}
        self._workbook_subs: list[Any] = []
        # Re-entry guard. Recalc engine writes via _set_value (cell:recalc),
        # not set (cell:change), so it shouldn't re-trigger itself. But a
        # user handler on cell:change could call sheet.set() — this guards
        # against re-entry on the *same* cell key.
        self._processing: set[CellKey] = set()

    # --- attach / detach -----------------------------------------------

    def attach(self, workbook: Workbook) -> None:
        """Attach the engine to ``workbook``. Subscribes to existing sheets
        and to the workbook's sheet-lifecycle events."""
        if self._workbook is not None:
            raise RuntimeError("RecalcEngine is already attached to a workbook")
        self._workbook = workbook
        for sheet in workbook.sheets():
            self._subscribe_sheet(sheet)
        self._workbook_subs.append(
            workbook.on("sheet:add", self._on_sheet_add)
        )
        self._workbook_subs.append(
            workbook.on("sheet:remove", self._on_sheet_remove)
        )

    def detach(self) -> None:
        """Unsubscribe everything. The engine becomes inert until reattached."""
        for sub in self._sheet_subs.values():
            sub()
        for sub in self._workbook_subs:
            sub()
        self._sheet_subs.clear()
        self._workbook_subs.clear()
        self._workbook = None

    # --- Sheet/Workbook subscription handlers --------------------------

    def _subscribe_sheet(self, sheet: Sheet) -> None:
        # The cell:change payload carries its own ``sheet`` and ``address``
        # (Part 3.1), so the handler reads them straight off the event rather
        # than closing over the loop variable. ``**ev`` tolerates the full
        # locked payload (sheet, address, old/new value+formula, old/new Cell).
        sub = sheet.on(
            "cell:change",
            lambda **ev: self._on_cell_change(
                ev["sheet"], ev["address"], ev["old"], ev["new"]
            ),
        )
        self._sheet_subs[sheet.name] = sub

    def _on_sheet_add(self, sheet: Sheet) -> None:
        if sheet.name not in self._sheet_subs:
            self._subscribe_sheet(sheet)

    def _on_sheet_remove(self, name: str, sheet: Sheet) -> None:
        sub = self._sheet_subs.pop(name, None)
        if sub is not None:
            sub()
        # Drop graph entries owned by this sheet
        to_drop = [k for k in self._asts if k[0] == name]
        for k in to_drop:
            self._remove_deps(k)
            del self._asts[k]
        # Drop _dependents entries keyed in this sheet. Cells in OTHER
        # sheets that referenced removed cells will simply see None on
        # next eval — fine.
        for k in list(self._dependents):
            if k[0] == name:
                del self._dependents[k]

    # --- cell:change handler -------------------------------------------

    def _on_cell_change(
        self, sheet: Sheet, address: tuple[int, int], old: Cell, new: Cell
    ) -> None:
        key = self._key(sheet.name, address)
        if key in self._processing:
            return
        self._processing.add(key)
        try:
            self._process_change(sheet, key, old, new)
        finally:
            self._processing.discard(key)

    def _process_change(self, sheet: Sheet, key: CellKey, old: Cell, new: Cell) -> None:
        # The whole recalc cascade is attributed to the cell the user changed.
        trigger = (key[1], key[2])

        # Step 1: deregister any old formula bindings for this cell.
        if key in self._asts:
            self._remove_deps(key)
            del self._asts[key]

        # Step 2: register and evaluate the new formula (if any).
        if new.formula:
            try:
                ast = parse_formula(new.formula)
            except ParseError:
                sheet._set_value((key[1], key[2]), NAME, trigger=trigger)
                self._propagate(key, trigger)
                return

            deps = extract_deps(ast, sheet.name)

            if self._would_cycle(key, deps):
                sheet._set_value((key[1], key[2]), CIRC, trigger=trigger)
                self._propagate(key, trigger)
                return

            self._asts[key] = ast
            for d in deps:
                self._dependents[d].add(key)
                self._dependencies[key].add(d)

            self._evaluate_and_write(key, trigger)

        # Step 3: propagate to transitive dependents. Value-only cells can
        # have dependents too (a formula reading them).
        self._propagate(key, trigger)

    # --- graph maintenance ---------------------------------------------

    def _remove_deps(self, key: CellKey) -> None:
        """Drop ``key``'s dependencies from the graph (both directions)."""
        for dep in self._dependencies.pop(key, ()):
            self._dependents[dep].discard(key)
            if not self._dependents[dep]:
                del self._dependents[dep]

    def _would_cycle(self, target: CellKey, deps: set[CellKey]) -> bool:
        """Would registering ``target`` with ``deps`` create a cycle?

        Walks from each dep along ``_dependencies`` (what they read). If
        we ever reach ``target``, the new edge target -> dep would close
        a loop.
        """
        if target in deps:
            return True  # direct self-reference
        visited: set[CellKey] = set()
        queue = list(deps)
        while queue:
            cur = queue.pop()
            if cur == target:
                return True
            if cur in visited:
                continue
            visited.add(cur)
            for d in self._dependencies.get(cur, set()):
                if d not in visited:
                    queue.append(d)
        return False

    # --- propagate / evaluate -----------------------------------------

    def _propagate(self, key: CellKey, trigger: tuple[int, int] | None = None) -> None:
        """Recompute everything that transitively depends on ``key``."""
        affected = self._transitive_dependents(key)
        if not affected:
            return
        ordered = self._topo_sort(affected)
        if ordered is None:
            # Defensive: if registration logic is correct, the subgraph of
            # registered formula cells is acyclic and this never fires. If
            # it ever does, mark them all CIRC so we don't infinite-loop.
            for k in affected:
                self._write(k, CIRC, trigger)
            return
        for k in ordered:
            self._evaluate_and_write(k, trigger)

    def _transitive_dependents(self, root: CellKey) -> set[CellKey]:
        """All cells (excluding root) that depend on root via any chain."""
        result: set[CellKey] = set()
        queue = [root]
        while queue:
            cur = queue.pop()
            for d in self._dependents.get(cur, set()):
                if d not in result:
                    result.add(d)
                    queue.append(d)
        return result

    def _topo_sort(self, cells: set[CellKey]) -> list[CellKey] | None:
        """Kahn's algorithm restricted to ``cells``. Returns None on cycle."""
        in_degree = {c: 0 for c in cells}
        for c in cells:
            for d in self._dependencies.get(c, set()):
                if d in cells:
                    in_degree[c] += 1
        ready = [c for c, deg in in_degree.items() if deg == 0]
        ordered: list[CellKey] = []
        while ready:
            cur = ready.pop(0)
            ordered.append(cur)
            for dependent in self._dependents.get(cur, set()):
                if dependent in cells:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        ready.append(dependent)
        if len(ordered) != len(cells):
            return None
        return ordered

    def _evaluate_and_write(
        self, key: CellKey, trigger: tuple[int, int] | None = None
    ) -> None:
        ast = self._asts.get(key)
        if ast is None or self._workbook is None:
            return
        sheet = self._workbook[key[0]]
        ctx = Context(sheet=sheet, current_cell=(key[1], key[2]))
        result = evaluate(ast, ctx)
        sheet._set_value((key[1], key[2]), result, trigger=trigger)

    def _write(
        self, key: CellKey, value: Any, trigger: tuple[int, int] | None = None
    ) -> None:
        if self._workbook is None:
            return
        sheet = self._workbook[key[0]]
        sheet._set_value((key[1], key[2]), value, trigger=trigger)

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _key(sheet_name: str, addr: str | tuple[int, int]) -> CellKey:
        from trellis.core.address import parse as parse_addr
        if isinstance(addr, str):
            row, col = parse_addr(addr)
        else:
            row, col = addr
        return (sheet_name, row, col)
