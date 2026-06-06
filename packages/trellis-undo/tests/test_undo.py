"""Hermetic engine-only tests for trellis-undo (design.md Part 7 #3).

No textual, no TUI — a Workbook, a sheet, and the log. The contract
under test: one event = one step; restore-by-object with recalc
self-heal; absence restores as absence; the log never records itself;
redo dies on a fork; capacity caps; attach/detach own the meta key.
"""

from __future__ import annotations

import pytest

from trellis import Cell, Workbook
from trellis_undo import META_KEY, UndoLog, attach, attach_workbook, detach


@pytest.fixture
def sheet():
    return Workbook().add_sheet("S")


# ------------------------------------------------------------- basic cycle


def test_undo_redo_single_value(sheet):
    log = UndoLog(sheet)
    sheet["A1"] = 10
    sheet["A1"] = 20
    assert log.undo() == 1
    assert sheet["A1"].value == 10
    assert log.undo() == 1
    assert sheet["A1"].value is None  # before the first write: absent
    assert log.undo() is None  # stack exhausted
    assert log.redo() == 1
    assert sheet["A1"].value == 10
    assert log.redo() == 1
    assert sheet["A1"].value == 20
    assert log.redo() is None


def test_undo_restores_absence_not_a_stored_husk(sheet):
    log = UndoLog(sheet)
    sheet["C3"] = 7
    assert sheet.used_range() == ((2, 2), (2, 2))
    log.undo()
    assert sheet["C3"].value is None
    assert sheet.used_range() is None  # deleted, not stored-empty


def test_undo_of_delete_restores_the_cell(sheet):
    log = UndoLog(sheet)
    sheet["A1"] = "hello"
    sheet.delete("A1")
    assert sheet["A1"].value is None
    log.undo()
    assert sheet["A1"].value == "hello"


# ------------------------------------------------- formulas + recalc heal


def test_restored_formula_recalcs_against_current_sheet(sheet):
    log = UndoLog(sheet)
    sheet["A1"] = 10
    sheet["B1"] = "=A1*2"  # 20
    sheet["B1"] = 5  # displace the formula
    sheet["A1"] = 100  # deps move on AFTER the displacement
    log.undo()  # undo A1: 100 -> 10
    log.undo()  # undo B1: 5 -> the formula cell
    assert sheet["B1"].formula == "=A1*2"
    assert sheet["B1"].value == 20  # recalced against A1=10, not stale
    log.redo()  # B1 -> 5 again
    assert sheet["B1"].value == 5


def test_dependents_cascade_on_undo(sheet):
    log = UndoLog(sheet)
    sheet["A1"] = 1
    sheet["B1"] = "=A1+1"
    sheet["A1"] = 41
    assert sheet["B1"].value == 42
    log.undo()  # A1 back to 1
    assert sheet["B1"].value == 2  # recalc cascade, not a recorded step
    assert log.depths == (2, 1)  # B1's recalc never entered history


def test_meta_rides_the_restored_object(sheet):
    log = UndoLog(sheet)
    sheet["A1"] = 10
    sheet["A1"].meta["styles"] = {"bold": True}
    sheet["A1"] = 20  # displaces the styled cell
    log.undo()
    assert sheet["A1"].value == 10
    assert sheet["A1"].meta == {"styles": {"bold": True}}


# ------------------------------------------------------------ batch steps


def test_batch_is_one_step_restored_in_one_batch(sheet):
    log = UndoLog(sheet)
    sheet["D1"] = "stays"
    with sheet.batch():
        sheet["A1"] = 1
        sheet["A2"] = 2
        sheet["A3"] = 3
    batches = []
    sheet.on("sheet:batch", lambda **ev: batches.append(ev))
    assert log.undo() == 3  # the whole batch, one step
    assert all(sheet[a].value is None for a in ("A1", "A2", "A3"))
    assert sheet["D1"].value == "stays"
    assert len(batches) == 1  # restored inside ONE engine batch
    assert log.redo() == 3
    assert sheet["A2"].value == 2


# --------------------------------------------------------- history shape


def test_redo_dies_when_history_forks(sheet):
    log = UndoLog(sheet)
    sheet["A1"] = 1
    sheet["A1"] = 2
    log.undo()
    assert log.can_redo
    sheet["A1"] = 99  # fork: a new recorded write
    assert not log.can_redo
    log.undo()
    assert sheet["A1"].value == 1


def test_log_never_records_its_own_restores(sheet):
    log = UndoLog(sheet)
    sheet["A1"] = 1
    sheet["A1"] = 2
    assert log.depths == (2, 0)
    log.undo()
    assert log.depths == (1, 1)  # moved, not re-recorded
    log.redo()
    assert log.depths == (2, 0)


def test_capacity_drops_oldest(sheet):
    log = UndoLog(sheet, capacity=2)
    sheet["A1"] = 1
    sheet["A1"] = 2
    sheet["A1"] = 3
    assert log.depths == (2, 0)
    assert log.undo() == 1  # 3 -> 2
    assert log.undo() == 1  # 2 -> 1
    assert log.undo() is None  # the 1-write fell off the cap
    assert sheet["A1"].value == 1


def test_capacity_none_is_unbounded(sheet):
    log = UndoLog(sheet, capacity=None)
    for n in range(1500):
        sheet["A1"] = n
    assert log.depths[0] == 1500


def test_clear_forgets_but_keeps_recording(sheet):
    log = UndoLog(sheet)
    sheet["A1"] = 1
    log.clear()
    assert not log.can_undo
    sheet["A1"] = 2
    assert log.undo() == 1
    assert sheet["A1"].value == 1


# ------------------------------------------------------- attach lifecycle


def test_attach_stashes_in_meta_and_is_idempotent(sheet):
    log = attach(sheet, capacity=5)
    assert sheet.meta[META_KEY] is log
    assert attach(sheet) is log  # second attach: same log
    assert log.capacity == 5


def test_detach_unsubscribes_and_clears(sheet):
    log = attach(sheet)
    sheet["A1"] = 1
    assert detach(sheet) is log
    assert META_KEY not in sheet.meta
    sheet["A1"] = 2  # not recorded anymore
    assert not log.can_undo  # and old history is gone (stale restores)
    assert detach(sheet) is None  # no-op without a log


def test_attach_workbook_covers_existing_and_future_sheets():
    wb = Workbook()
    first = wb.add_sheet("First")
    logs = attach_workbook(wb, capacity=9)
    assert logs["First"] is first.meta[META_KEY]
    later = wb.add_sheet("Later")  # sheet:add hook attaches it
    log = later.meta[META_KEY]
    assert isinstance(log, UndoLog) and log.capacity == 9
    later["A1"] = 1
    assert log.undo() == 1
    assert later["A1"].value is None
