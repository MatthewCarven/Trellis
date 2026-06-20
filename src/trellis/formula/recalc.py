"""Recalc engine + Workbook integration.

The recalc engine maintains a dependency graph of formula cells across all
sheets in a workbook. When a cell changes, it propagates updates to all
transitive dependents in topological order. Errors propagate naturally
through evaluation; circular references are caught and stored as ``CIRC``.

Architecture
------------

One engine per workbook. Attaching subscribes to:

* ``cell:change`` on each sheet — react to user-initiated changes
* ``sheet:batch`` on each sheet — replay a bulk write (Sheet.batch) once
* ``sheet:add`` on the workbook — attach to new sheets as they appear
* ``sheet:remove`` on the workbook — clean up graph entries for removed sheets

Results are written back via :meth:`Sheet._set_value`, which emits
``"cell:recalc"`` instead of ``"cell:change"`` — the latter would re-trigger
the engine in an infinite loop.

Dependency model
----------------

A "cell key" is a tuple ``(sheet_id, row, col)`` — the sheet's stable identity,
not its (mutable) name. Keying on the id means a rename can never desync the
graph (the S41 bug; design.md Part 12). Name resolution happens at the formula-
text boundary once cross-sheet refs land; the holding sheet supplies its own id.

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
from .shift import rename_sheet_in_formula

if TYPE_CHECKING:
    from trellis.core.cell import Cell
    from trellis.core.sheet import Sheet
    from trellis.core.workbook import Workbook


CellKey = tuple[int, int, int]


# --- Dependency extraction ---------------------------------------------


def extract_deps(ast: Any, sheet_id: int, resolve: Any = None) -> set[CellKey]:
    """Return the set of cell keys this AST references.

    ``RangeRef`` nodes expand to the full rectangle of positions. ``CellRef``
    contributes one position. Literals (Number, String, Bool) contribute
    nothing. UnaryOp/BinaryOp/FunctionCall recurse into operands/args.

    ``sheet_id`` is the holding sheet's id (for refs with no sheet qualifier).
    ``resolve`` maps a sheet *name* to a sheet_id, or ``None`` if no such sheet
    exists — this is how cross-sheet refs (``Sheet2!A1``) find their owner. A
    qualified ref to an unknown sheet contributes no dependency (the formula
    evaluates to ``NAME`` and recovers if re-entered). With ``resolve=None``,
    qualified refs fall back to the holding sheet.
    """
    deps: set[CellKey] = set()

    def _owner(sheet_name: Any) -> int | None:
        # Unqualified ref (None) or no resolver -> the holding sheet. A
        # qualified name resolves via the caller's map; an unknown sheet
        # returns None and the ref is dropped (formula -> NAME, recovers on
        # re-entry; design.md Part 12).
        if sheet_name is None or resolve is None:
            return sheet_id
        return resolve(sheet_name)

    def walk(node: Any) -> None:
        if isinstance(node, CellRef):
            oid = _owner(node.sheet)
            if oid is not None:
                deps.add((oid, node.row, node.col))
        elif isinstance(node, RangeRef):
            oid = _owner(node.start.sheet)
            if oid is not None:
                for r in range(node.start.row, node.end.row + 1):
                    for c in range(node.start.col, node.end.col + 1):
                        deps.add((oid, r, c))
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
        self._sheet_subs: dict[int, Any] = {}
        self._sheets_by_id: dict[int, Sheet] = {}
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
        self._workbook_subs.append(
            workbook.on("sheet:rename", self._on_sheet_rename)
        )

    def detach(self) -> None:
        """Unsubscribe everything. The engine becomes inert until reattached."""
        for subs in self._sheet_subs.values():
            for sub in subs:
                sub()
        for sub in self._workbook_subs:
            sub()
        self._sheet_subs.clear()
        self._sheets_by_id.clear()
        self._workbook_subs.clear()
        self._workbook = None

    # --- Sheet/Workbook subscription handlers --------------------------

    def _subscribe_sheet(self, sheet: Sheet) -> None:
        # The cell:change payload carries its own ``sheet`` and ``address``
        # (Part 3.1), so the handler reads them straight off the event rather
        # than closing over the loop variable. ``**ev`` tolerates the full
        # locked payload (sheet, address, old/new value+formula, old/new Cell).
        change_sub = sheet.on(
            "cell:change",
            lambda **ev: self._on_cell_change(
                ev["sheet"], ev["address"], ev["old"], ev["new"]
            ),
        )
        # A bulk write (Sheet.batch) suppresses per-cell cell:change and
        # instead emits one sheet:batch on exit. Replay each buffered change
        # through the normal path so formulas recompute once the batch closes.
        batch_sub = sheet.on(
            "sheet:batch",
            lambda **ev: self._on_batch(ev["sheet"], ev["changes"]),
        )
        self._sheet_subs[sheet.id] = [change_sub, batch_sub]
        self._sheets_by_id[sheet.id] = sheet

    def _on_sheet_add(self, sheet: Sheet) -> None:
        if sheet.id not in self._sheet_subs:
            self._subscribe_sheet(sheet)

    def _on_sheet_remove(self, name: str, sheet: Sheet) -> None:
        removed = sheet.id
        # Capture cross-sheet dependents (in OTHER sheets) BEFORE we tear the
        # graph down, so we can re-register them: their refs to the gone sheet
        # now resolve to NAME instead of silently keeping a stale value.
        affected = {
            dep
            for k in self._dependents
            if k[0] == removed
            for dep in self._dependents[k]
            if dep[0] != removed
        }
        subs = self._sheet_subs.pop(removed, None)
        self._sheets_by_id.pop(removed, None)
        if subs is not None:
            for sub in subs:
                sub()
        # Drop graph entries owned by this sheet.
        to_drop = [k for k in self._asts if k[0] == removed]
        for k in to_drop:
            self._remove_deps(k)
            del self._asts[k]
        for k in list(self._dependents):
            if k[0] == removed:
                del self._dependents[k]
        # Re-register surviving cross-sheet dependents: re-parsing drops the
        # now-dead dep and re-evaluation surfaces the broken ref as NAME, which
        # then cascades to anything depending on them.
        for key in affected:
            s = self._sheets_by_id.get(key[0])
            if s is None:
                continue
            cell = s.get((key[1], key[2]))
            if cell.formula:
                self._process_change(s, key, cell, cell)

    def _on_sheet_rename(self, old: str, new: str, sheet: Sheet) -> None:
        # The id-keyed graph is rename-invariant, so dependencies need no
        # rekey. But a cross-sheet ref stores the sheet NAME in both its
        # formula text and its AST; left stale, referrers would resolve to NAME
        # after the rename (the evaluator resolves the sheet by name) and a save
        # would persist the old name. Rewrite the text of every referrer
        # old->new and re-parse its AST in place. A rename moves no data, so the
        # value is unchanged — update quietly, no recompute or events.
        referrers = set()
        for k in self._dependents:
            if k[0] == sheet.id:
                referrers |= self._dependents[k]
        for key in referrers:
            s = self._sheets_by_id.get(key[0])
            if s is None:
                continue
            cell = s.get((key[1], key[2]))
            if not cell.formula:
                continue
            new_text = rename_sheet_in_formula(cell.formula, old, new)
            if new_text == cell.formula:
                continue
            cell.formula = new_text
            try:
                self._asts[key] = parse_formula(new_text)
            except ParseError:
                pass

    # --- cell:change handler -------------------------------------------

    def _on_cell_change(
        self, sheet: Sheet, address: tuple[int, int], old: Cell, new: Cell
    ) -> None:
        key = self._key(sheet.id, address)
        if key in self._processing:
            return
        self._processing.add(key)
        try:
            self._process_change(sheet, key, old, new)
        finally:
            self._processing.discard(key)

    def _on_batch(self, sheet: Sheet, changes: list) -> None:
        """Replay a batch's buffered changes through the per-cell path.

        Each change recomputes independently and carries its own
        ``trigger`` (the replayed cell), so a dependent fed by several
        batched inputs may recompute more than once — the simple, correct
        behaviour chosen for batches. Cycle protection is unchanged: every
        replayed change goes through the same registration guard as a
        single write.
        """
        for change in changes:
            self._on_cell_change(
                sheet, change["address"], change["old"], change["new"]
            )

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

            deps = extract_deps(ast, sheet.id, self._resolve_sheet_id)

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
        sheet = self._sheets_by_id.get(key[0])
        if sheet is None:
            return
        ctx = Context(sheet=sheet, current_cell=(key[1], key[2]), workbook=self._workbook)
        result = evaluate(ast, ctx)
        sheet._set_value((key[1], key[2]), result, trigger=trigger)

    def _write(
        self, key: CellKey, value: Any, trigger: tuple[int, int] | None = None
    ) -> None:
        if self._workbook is None:
            return
        sheet = self._sheets_by_id.get(key[0])
        if sheet is None:
            return
        sheet._set_value((key[1], key[2]), value, trigger=trigger)

    # --- helpers --------------------------------------------------------

    def _resolve_sheet_id(self, name: str) -> int | None:
        # Map a sheet NAME to its id (or None if no such sheet) — the
        # cross-sheet resolver handed to extract_deps. Workbook is name-keyed.
        wb = self._workbook
        if wb is None or name not in wb:
            return None
        return wb[name].id

    @staticmethod
    def _key(sheet_id: int, addr: str | tuple[int, int]) -> CellKey:
        from trellis.core.address import parse as parse_addr
        if isinstance(addr, str):
            row, col = parse_addr(addr)
        else:
            row, col = addr
        return (sheet_id, row, col)
