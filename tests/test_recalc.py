"""Tests for the recalc engine (#18) and Sheet._set_value.

This is the file that proves Trellis is a working spreadsheet: formula
cells evaluate at set-time, dependents recompute when their inputs change,
cycles are caught, and the dep graph stays consistent across formula edits.
"""

from __future__ import annotations

import pytest

from trellis import Sheet, Workbook
from trellis.core.address import to_a1
from trellis.formula import (
    CIRC,
    DIV0,
    NAME,
    VALUE,
    FormulaError,
    RecalcEngine,
    parse_formula,
)
from trellis.formula.recalc import extract_deps


# =======================================================================
# Sheet._set_value — the non-emitting write path
# =======================================================================


def test_set_value_preserves_formula():
    s = Sheet()
    s["A1"] = "=B1"  # creates Cell(value=None, formula="=B1")
    s._set_value("A1", 42)
    cell = s["A1"]
    assert cell.value == 42
    assert cell.formula == "=B1"


def test_set_value_preserves_meta():
    s = Sheet()
    s["A1"] = "=B1"
    s["A1"].meta["color"] = "red"
    s._set_value("A1", 99)
    assert s["A1"].meta == {"color": "red"}


def test_set_value_emits_cell_recalc_not_cell_change():
    s = Sheet()
    s["A1"] = "=B1"
    changes = []
    recalcs = []
    s.on("cell:change", lambda **ev: changes.append(to_a1(*ev["address"])))
    s.on("cell:recalc", lambda **ev: recalcs.append((to_a1(*ev["address"]), ev["new_value"])))
    s._set_value("A1", 99)
    assert changes == []
    assert recalcs == [("A1", 99)]


def test_set_value_event_payload_shape_matches_cell_change():
    s = Sheet()
    s["A1"] = "=B1"
    payloads = []
    s.on("cell:recalc",
         lambda **ev: payloads.append((ev["old_value"], ev["new_value"])))
    s._set_value("A1", 1)
    s._set_value("A1", 2)
    assert payloads == [(None, 1), (1, 2)]


def test_set_value_noop_on_missing_cell():
    s = Sheet()
    s._set_value("A1", 42)
    assert "A1" not in s


def test_set_value_accepts_tuple_address():
    s = Sheet()
    s["A1"] = "=B1"
    s._set_value((0, 0), 5)
    assert s["A1"].value == 5


# =======================================================================
# extract_deps
# =======================================================================


def test_extract_deps_cellref():
    deps = extract_deps(parse_formula("=A1"), "Sheet1")
    assert deps == {("Sheet1", 0, 0)}


def test_extract_deps_rangeref_expands_rectangle():
    deps = extract_deps(parse_formula("=SUM(A1:B2)"), "S")
    assert deps == {("S", 0, 0), ("S", 0, 1), ("S", 1, 0), ("S", 1, 1)}


def test_extract_deps_literals_only():
    assert extract_deps(parse_formula("=1+2*3"), "S") == set()


def test_extract_deps_nested_function_args():
    deps = extract_deps(parse_formula("=SUM(A1, B2) + IF(C3, D4, E5)"), "S")
    assert deps == {
        ("S", 0, 0), ("S", 1, 1),
        ("S", 2, 2), ("S", 3, 3), ("S", 4, 4),
    }


def test_extract_deps_in_unary():
    deps = extract_deps(parse_formula("=-A1"), "S")
    assert deps == {("S", 0, 0)}


def test_extract_deps_in_binary():
    deps = extract_deps(parse_formula("=A1 + B2 * C3"), "S")
    assert deps == {("S", 0, 0), ("S", 1, 1), ("S", 2, 2)}


def test_extract_deps_string_literal_has_no_deps():
    deps = extract_deps(parse_formula('="hello"'), "S")
    assert deps == set()


# =======================================================================
# RecalcEngine — formula evaluation at set-time
# =======================================================================


def make_wb():
    wb = Workbook()
    sh = wb.add_sheet("Main")
    return wb, sh


def test_formula_evaluated_at_set_time():
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1 + 5"
    assert sh["B1"].value == 15


def test_formula_with_empty_dep_is_zero():
    wb, sh = make_wb()
    sh["B1"] = "=A1 * 2"  # A1 is empty; None coerces to 0
    assert sh["B1"].value == 0


def test_formula_string_preserved_in_cell():
    wb, sh = make_wb()
    sh["A1"] = "=SUM(B1:B3)"
    assert sh["A1"].formula == "=SUM(B1:B3)"


# --- direct dependency ---


def test_direct_dep_recalcs_when_input_changes():
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1 + 5"
    assert sh["B1"].value == 15
    sh["A1"] = 20
    assert sh["B1"].value == 25


def test_setting_dep_to_same_value_still_recalcs():
    """No value-equality short-circuit in core (per design)."""
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1 + 5"
    calls = []
    sh.on("cell:recalc", lambda **ev: calls.append(to_a1(*ev["address"])))
    sh["A1"] = 10  # same value
    assert "B1" in calls


# --- chains ---


def test_chain_recalcs_in_order():
    wb, sh = make_wb()
    sh["A1"] = 1
    sh["B1"] = "=A1 * 2"
    sh["C1"] = "=B1 + 10"
    sh["D1"] = "=C1 * 3"
    assert sh["D1"].value == 36  # ((1*2)+10)*3
    sh["A1"] = 5
    assert sh["B1"].value == 10
    assert sh["C1"].value == 20
    assert sh["D1"].value == 60


def test_chain_recalc_visits_each_dependent_once():
    """No double-recalcs even if there are multiple paths."""
    wb, sh = make_wb()
    sh["A1"] = 1
    sh["B1"] = "=A1 + 1"
    sh["C1"] = "=A1 + B1"  # depends on both A1 directly and via B1
    visits = []
    sh.on("cell:recalc", lambda **ev: visits.append(to_a1(*ev["address"])))
    sh["A1"] = 10
    assert visits.count("C1") == 1
    assert sh["C1"].value == 21  # 10 + 11


# --- range dependency ---


def test_range_dep_recomputes_when_any_cell_in_range_changes():
    wb, sh = make_wb()
    sh["A1"] = 1
    sh["A2"] = 2
    sh["A3"] = 3
    sh["B1"] = "=SUM(A1:A3)"
    assert sh["B1"].value == 6
    sh["A2"] = 20
    assert sh["B1"].value == 24
    sh["A3"] = 100
    assert sh["B1"].value == 121  # 1 + 20 + 100


# --- fan-out ---


def test_multiple_dependents_all_recalc():
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1"
    sh["C1"] = "=A1 * 2"
    sh["D1"] = "=A1 + 100"
    sh["A1"] = 5
    assert sh["B1"].value == 5
    assert sh["C1"].value == 10
    assert sh["D1"].value == 105


# --- dep graph updates on formula change ---


def test_changing_formula_reroutes_dependencies():
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["A2"] = 20
    sh["B1"] = "=A1"
    assert sh["B1"].value == 10
    # B1 now depends on A2 instead of A1
    sh["B1"] = "=A2"
    assert sh["B1"].value == 20
    # Changes to A1 should NOT trigger B1
    visits = []
    sh.on("cell:recalc", lambda **ev: visits.append(to_a1(*ev["address"])))
    sh["A1"] = 999
    assert "B1" not in visits
    # But A2 changes still do
    sh["A2"] = 50
    assert sh["B1"].value == 50


def test_replacing_formula_with_value_drops_deps():
    """Setting B1 to a plain value should drop B1's dep on A1."""
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1"
    sh["B1"] = 99   # overwrite formula with plain value
    visits = []
    sh.on("cell:recalc", lambda **ev: visits.append(to_a1(*ev["address"])))
    sh["A1"] = 1
    assert "B1" not in visits
    assert sh["B1"].value == 99


def test_deleting_formula_cell_drops_deps():
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1 + 5"
    del sh["B1"]
    visits = []
    sh.on("cell:recalc", lambda **ev: visits.append(to_a1(*ev["address"])))
    sh["A1"] = 99
    assert visits == []


# --- cycle detection ---


def test_self_reference_is_circ():
    wb, sh = make_wb()
    sh["A1"] = "=A1"
    assert sh["A1"].value == CIRC


def test_two_cell_cycle_marks_offending_cell_circ():
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1"  # not a cycle yet
    assert sh["B1"].value == 10
    sh["A1"] = "=B1"  # now closes the loop
    assert sh["A1"].value == CIRC


def test_indirect_cycle_three_cells():
    wb, sh = make_wb()
    sh["A1"] = "=B1"  # B1 doesn't exist; A1 evaluates against None
    sh["B1"] = "=C1"
    sh["C1"] = "=A1"  # closes the loop
    assert sh["C1"].value == CIRC


def test_cycle_recovers_when_broken():
    """Setting a cycle-creating cell back to a value should recover."""
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1"
    sh["A1"] = "=B1"  # cycle — A1 becomes CIRC
    assert sh["A1"].value == CIRC
    # Heal: set A1 to a plain value
    sh["A1"] = 7
    assert sh["A1"].value == 7
    assert sh["B1"].value == 7  # B1 recomputes against the fresh A1


# --- parse errors ---


def test_parse_error_stored_as_name():
    wb, sh = make_wb()
    sh["A1"] = "=SUM(unclosed"
    assert sh["A1"].value == NAME


def test_parse_error_preserves_formula_string():
    wb, sh = make_wb()
    sh["A1"] = "=SUM(unclosed"
    assert sh["A1"].formula == "=SUM(unclosed"


# --- deletes propagate ---


def test_deleting_dep_propagates_to_formula_cells():
    wb, sh = make_wb()
    sh["A1"] = 10
    sh["B1"] = "=A1 + 5"
    assert sh["B1"].value == 15
    del sh["A1"]
    # A1 is gone -> sheet.get returns empty Cell -> None -> 0 -> B1 = 5
    assert sh["B1"].value == 5


# --- error propagation ---


def test_division_by_zero_propagates_through_dependent():
    wb, sh = make_wb()
    sh["A1"] = "=1/0"
    sh["B1"] = "=A1 + 5"
    assert sh["A1"].value == DIV0
    assert sh["B1"].value == DIV0


def test_iferror_catches_propagated_error():
    wb, sh = make_wb()
    sh["A1"] = "=1/0"
    sh["B1"] = "=IFERROR(A1, 999)"
    assert sh["B1"].value == 999


# --- the integration test from design.md ---


def test_design_md_integration_test():
    wb = Workbook()
    sh = wb.add_sheet("Demo")
    sh["A1"] = 10
    sh["A2"] = 20
    sh["A3"] = 30
    sh["B1"] = "=SUM(A1:A3)"
    sh["B2"] = '=IF(B1 > 50, "big", "small")'

    assert sh["B1"].value == 60
    assert sh["B2"].value == "big"

    sh["A1"] = 100
    assert sh["B1"].value == 150
    assert sh["B2"].value == "big"

    sh["A1"] = "=B1"
    assert isinstance(sh["A1"].value, FormulaError)
    assert sh["A1"].value.code == "#CIRC!"


# =======================================================================
# Workbook integration
# =======================================================================


def test_workbook_auto_attaches_engine():
    wb = Workbook()
    assert wb.recalc is not None
    assert isinstance(wb.recalc, RecalcEngine)


def test_engine_attaches_to_sheets_added_after_construction():
    wb = Workbook()
    sh = wb.add_sheet("Later")
    sh["A1"] = 10
    sh["B1"] = "=A1 * 2"
    assert sh["B1"].value == 20
    sh["A1"] = 5
    assert sh["B1"].value == 10


def test_engine_cleans_up_when_sheet_removed():
    wb = Workbook()
    sh = wb.add_sheet("S")
    sh["A1"] = 10
    sh["B1"] = "=A1"
    keys_before = list(wb.recalc._asts.keys())
    assert any(k[0] == "S" for k in keys_before)
    wb.remove_sheet("S")
    keys_after = list(wb.recalc._asts.keys())
    assert not any(k[0] == "S" for k in keys_after)


def test_detach_stops_recalc():
    wb = Workbook()
    sh = wb.add_sheet("S")
    sh["A1"] = 10
    sh["B1"] = "=A1"
    assert sh["B1"].value == 10
    wb.recalc.detach()
    sh["A1"] = 99
    # B1 should NOT recalc after detach.
    assert sh["B1"].value == 10


def test_attach_twice_raises():
    wb = Workbook()
    # wb.recalc is already attached during construction; re-attaching should
    # fail loudly rather than silently double-subscribe.
    with pytest.raises(RuntimeError):
        wb.recalc.attach(wb)


def test_detach_and_reattach():
    wb = Workbook()
    sh = wb.add_sheet("S")
    sh["A1"] = 10
    sh["B1"] = "=A1"
    wb.recalc.detach()
    sh["A1"] = 99
    assert sh["B1"].value == 10  # no recalc
    # Re-attach. (Subsequent changes recalc; old formula's dep graph is
    # lost, but a re-set rebuilds it.)
    wb.recalc.attach(wb)
    sh["B1"] = "=A1"  # re-register
    assert sh["B1"].value == 99
    sh["A1"] = 5
    assert sh["B1"].value == 5


def test_processing_guard_prevents_reentry_for_same_cell():
    """If a cell:change handler synchronously sets the same cell, the engine
    shouldn't re-process it (would infinite-loop)."""
    wb = Workbook()
    sh = wb.add_sheet("S")
    counter = {"n": 0}
    def handler(**ev):
        counter["n"] += 1
        if counter["n"] < 5 and ev["address"] == (0, 0):
            sh["A1"] = 42  # would re-enter the engine for the same cell
    sh.on("cell:change", handler)
    sh["A1"] = 1
    # The handler may fire multiple times for legitimate cell:change events,
    # but the engine itself shouldn't infinite-loop. Sanity check we exited.
    assert counter["n"] < 100


# =======================================================================
# Bare sheets (no workbook) — no recalc, but no crash
# =======================================================================


def test_bare_sheet_does_not_evaluate_formulas():
    """A Sheet not attached to a Workbook has no recalc engine, so formulas
    are stored but not evaluated."""
    s = Sheet("Standalone")
    s["A1"] = 10
    s["B1"] = "=A1 + 5"
    # B1's value remains None — no engine to compute it.
    assert s["B1"].value is None
    assert s["B1"].formula == "=A1 + 5"


# --- Part 3.1: cell:recalc trigger contract --------------------------------


def test_cell_recalc_payload_includes_trigger_cell():
    """A recalc cascade is attributed to the (row, col) the user changed."""
    wb, sh = make_wb()
    sh["A1"] = 1
    sh["B1"] = "=A1 * 2"
    sh["C1"] = "=B1 + 1"
    triggers = {}
    sh.on(
        "cell:recalc",
        lambda **ev: triggers.__setitem__(to_a1(*ev["address"]), ev["trigger"]),
    )
    sh["A1"] = 10  # user change at A1 == (0, 0)
    # Every cell recomputed in this cascade points back at A1.
    assert triggers["B1"] == (0, 0)
    assert triggers["C1"] == (0, 0)


def test_cell_recalc_trigger_is_none_for_standalone_set_value():
    """A direct _set_value with no originating user change has trigger None."""
    s = Sheet()
    s["A1"] = "=B1"
    seen = []
    s.on("cell:recalc", lambda **ev: seen.append(ev["trigger"]))
    s._set_value("A1", 99)
    assert seen == [None]


def test_cell_recalc_payload_carries_value_and_formula_fields():
    wb, sh = make_wb()
    sh["A1"] = 1
    sh["B1"] = "=A1 * 2"   # evaluates to 2
    seen = []
    sh.on("cell:recalc", lambda **ev: seen.append(ev))
    sh["A1"] = 5           # B1 recomputes 2 -> 10
    (ev,) = [e for e in seen if to_a1(*e["address"]) == "B1"]
    assert ev["old_value"] == 2
    assert ev["new_value"] == 10
    assert ev["new_formula"] == "=A1 * 2"
    assert ev["sheet"] is sh


# --- Part 3.2: batch replay semantics --------------------------------------


def test_batch_defers_recalc_until_exit():
    wb, sh = make_wb()
    sh["A1"] = 1
    sh["B1"] = "=A1 * 10"
    assert sh["B1"].value == 10
    recalcs = []
    sh.on("cell:recalc", lambda **ev: recalcs.append(to_a1(*ev["address"])))
    with sh.batch():
        sh["A1"] = 5
        assert sh["B1"].value == 10   # NOT recomputed yet, inside the block
    assert sh["B1"].value == 50       # recomputed once the batch closed
    assert "B1" in recalcs


def test_setting_formula_inside_batch_registers_and_evaluates_on_exit():
    wb, sh = make_wb()
    sh["A1"] = 4
    with sh.batch():
        sh["B1"] = "=A1 * 3"
    assert sh["B1"].value == 12       # formula registered + evaluated on exit
    # And the new dependency is live afterward.
    sh["A1"] = 10
    assert sh["B1"].value == 30


def test_batch_replay_carries_per_cell_trigger():
    wb, sh = make_wb()
    sh["A1"] = 1
    sh["A2"] = 1
    sh["B1"] = "=A1 + 100"
    sh["B2"] = "=A2 + 200"
    triggers = {}
    sh.on(
        "cell:recalc",
        lambda **ev: triggers.__setitem__(to_a1(*ev["address"]), ev["trigger"]),
    )
    with sh.batch():
        sh["A1"] = 2   # triggers B1 recalc, trigger == A1 == (0, 0)
        sh["A2"] = 2   # triggers B2 recalc, trigger == A2 == (1, 0)
    assert triggers["B1"] == (0, 0)
    assert triggers["B2"] == (1, 0)
    assert sh["B1"].value == 102
    assert sh["B2"].value == 202


def test_detach_unsubscribes_both_change_and_batch():
    wb, sh = make_wb()
    sh["A1"] = 1
    sh["B1"] = "=A1 * 2"
    wb.recalc.detach()
    with sh.batch():
        sh["A1"] = 9
    assert sh["B1"].value == 2        # engine detached: no recompute via batch


# --- $ pins are evaluation- and recalc-invisible (design.md Part 6) ----


def test_pinned_refs_evaluate_and_recalc_like_plain_ones():
    wb = Workbook()
    sh = wb.add_sheet("S")
    sh["A1"] = 21
    sh["B1"] = "=$A$1*2"
    sh["C1"] = "=SUM($A$1:A1)"
    assert sh["B1"].value == 42
    assert sh["C1"].value == 21
    sh["A1"] = 50                  # pinned refs are the same dependency
    assert sh["B1"].value == 100
    assert sh["C1"].value == 50
