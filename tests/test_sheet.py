"""Tests for trellis.core.sheet.Sheet."""

import pytest

from trellis import Cell, Range, Sheet
from trellis.core.address import to_a1


def test_empty_sheet():
    s = Sheet()
    assert s.name == "Sheet1"
    assert len(s) == 0
    assert list(s.cells()) == []


def test_set_and_get_via_a1():
    s = Sheet()
    s["A1"] = 42
    assert s["A1"].value == 42
    assert s["A1"].formula is None


def test_set_and_get_via_tuple():
    s = Sheet()
    s[(2, 1)] = "hello"        # row=2, col=1 -> B3
    assert s["B3"].value == "hello"
    assert s[(2, 1)].value == "hello"


def test_formula_detection():
    s = Sheet()
    s["B2"] = "=A1*2"
    cell = s["B2"]
    assert cell.formula == "=A1*2"
    assert cell.value is None


def test_string_without_equals_is_a_value_not_a_formula():
    s = Sheet()
    s["A1"] = "hello"
    assert s["A1"].value == "hello"
    assert s["A1"].formula is None


def test_set_with_cell_instance_stores_it_directly():
    s = Sheet()
    custom = Cell(value=7)
    custom.meta["tag"] = "important"
    s["A1"] = custom
    assert s["A1"] is custom
    assert s["A1"].meta["tag"] == "important"


def test_subclass_cells_are_preserved():
    class TaggedCell(Cell):
        pass

    s = Sheet()
    s["A1"] = TaggedCell(value=1)
    assert isinstance(s["A1"], TaggedCell)


def test_absent_cell_returns_empty_but_does_not_persist():
    s = Sheet()
    cell = s["Z9"]
    assert cell.is_empty()
    assert len(s) == 0
    assert "Z9" not in s


def test_delete():
    s = Sheet()
    s["A1"] = 1
    s["A2"] = 2
    del s["A1"]
    assert "A1" not in s
    assert "A2" in s
    assert len(s) == 1


def test_delete_absent_is_silent():
    s = Sheet()
    s.delete("Z9")  # no error


def test_contains_via_a1_and_tuple():
    s = Sheet()
    s["A1"] = 1
    assert "A1" in s
    assert (0, 0) in s
    assert "A2" not in s


def test_contains_handles_garbage_inputs():
    s = Sheet()
    assert 5 not in s
    assert None not in s
    assert "garbage" not in s


def test_invalid_address_raises_on_set():
    s = Sheet()
    with pytest.raises(ValueError):
        s["not-an-address"] = 1


def test_iteration_yields_stored_cells_in_order():
    s = Sheet()
    s["B2"] = 1
    s["A1"] = 2
    s["C3"] = 3
    seen = [addr for addr, _ in s.cells()]
    assert seen == ["B2", "A1", "C3"]   # insertion order


def test_meta_is_publicly_writable():
    s = Sheet()
    s.meta["plugin:conditional_formatting"] = {"rules": []}
    assert s.meta["plugin:conditional_formatting"]["rules"] == []


def test_repr_includes_name_and_count():
    s = Sheet("MySheet")
    s["A1"] = 1
    assert repr(s) == "Sheet(name='MySheet', cells=1)"


# --- event emission ---------------------------------------------------------


def test_sheet_emits_cell_change_on_set():
    s = Sheet()
    events = []
    s.on("cell:change", lambda **ev: events.append((to_a1(*ev["address"]), ev["old_value"], ev["new_value"])))
    s["A1"] = 5
    s["A1"] = 10
    s["B2"] = "hello"
    assert events == [
        ("A1", None, 5),
        ("A1", 5, 10),
        ("B2", None, "hello"),
    ]


def test_sheet_emits_cell_change_on_delete_of_existing():
    s = Sheet()
    s["A1"] = 5
    events = []
    s.on("cell:change", lambda **ev: events.append((to_a1(*ev["address"]), ev["old_value"], ev["new"].is_empty())))
    del s["A1"]
    assert events == [("A1", 5, True)]


def test_sheet_does_not_emit_on_delete_of_absent():
    s = Sheet()
    events = []
    s.on("cell:change", lambda **kw: events.append(kw))
    del s["Z9"]
    s.delete("AA10")
    assert events == []


def test_sheet_emits_when_set_with_formula_string():
    s = Sheet()
    events = []
    s.on("cell:change", lambda **ev: events.append((to_a1(*ev["address"]), ev["new_formula"])))
    s["A1"] = "=B1*2"
    assert events == [("A1", "=B1*2")]


def test_sheet_emits_when_set_with_cell_instance():
    s = Sheet()
    custom = Cell(value=42)
    custom.meta["tag"] = "x"
    events = []
    s.on("cell:change", lambda **ev: events.append((to_a1(*ev["address"]), ev["new"] is custom)))
    s["A1"] = custom
    assert events == [("A1", True)]


def test_sheet_set_to_same_value_still_emits():
    """No short-circuit on no-op writes — value comparison is a plugin's job."""
    s = Sheet()
    s["A1"] = 5
    events = []
    s.on("cell:change", lambda **kw: events.append(to_a1(*kw["address"])))
    s["A1"] = 5
    assert events == ["A1"]


def test_sheet_listener_count():
    s = Sheet()
    assert s.listener_count() == 0
    sub = s.on("cell:change", lambda **kw: None)
    assert s.listener_count("cell:change") == 1
    sub()
    assert s.listener_count() == 0


# --- range integration via sheet sugar -------------------------------------


def test_sheet_getitem_range_string_returns_range():
    s = Sheet()
    r = s["A1:B3"]
    assert isinstance(r, Range)
    assert r.shape == (3, 2)


def test_sheet_getitem_range_tuple_returns_range():
    s = Sheet()
    r = s[((0, 0), (2, 1))]
    assert isinstance(r, Range)
    assert r.shape == (3, 2)


def test_sheet_setitem_range_broadcasts_scalar():
    s = Sheet()
    s["A1:B3"] = 7
    assert [c.value for c in s["A1:B3"]] == [7, 7, 7, 7, 7, 7]


def test_sheet_setitem_range_spreads_1d():
    s = Sheet()
    s["A1:A5"] = [1, 2, 3, 4, 5]
    assert [c.value for c in s["A1:A5"]] == [1, 2, 3, 4, 5]


def test_sheet_setitem_range_spreads_2d():
    s = Sheet()
    s["A1:B2"] = [[1, 2], [3, 4]]
    assert [c.value for c in s["A1:B2"]] == [1, 2, 3, 4]


def test_sheet_delitem_range_clears():
    s = Sheet()
    s["A1"] = 1
    s["B2"] = 2
    s["C3"] = 3
    del s["A1:C3"]
    assert len(s) == 0


def test_sheet_range_method_returns_range():
    s = Sheet()
    r = s.range("A1:B5")
    assert isinstance(r, Range)


def test_single_cell_access_still_returns_cell():
    s = Sheet()
    s["A1"] = 42
    assert isinstance(s["A1"], Cell)
    assert s["A1"].value == 42


def test_single_cell_tuple_access_still_returns_cell():
    s = Sheet()
    s[(0, 0)] = 99
    cell = s[(0, 0)]
    assert isinstance(cell, Cell)
    assert cell.value == 99


def test_range_assignment_fires_cell_change_per_cell():
    s = Sheet()
    events = []
    s.on("cell:change", lambda **ev: events.append(to_a1(*ev["address"])))
    s["A1:B2"] = 0
    assert events == ["A1", "B1", "A2", "B2"]


def test_invalid_range_part_raises():
    s = Sheet()
    with pytest.raises(ValueError):
        s["A1:not-an-address"] = 1


# --- Part 3.1: event payload contract lock-in ------------------------------
# These tests pin the public shape of cell:change. Once external plugins read
# these fields, the shape is a contract — change them only with a deprecation.


def test_cell_change_payload_carries_old_and_new_value():
    s = Sheet()
    s["A1"] = 5
    seen = []
    s.on("cell:change", lambda **ev: seen.append(ev))
    s["A1"] = 10
    (ev,) = seen
    assert ev["old_value"] == 5
    assert ev["new_value"] == 10


def test_cell_change_payload_address_is_zero_indexed_tuple():
    s = Sheet()
    seen = []
    s.on("cell:change", lambda **ev: seen.append(ev["address"]))
    s["A1"] = 1   # (0, 0)
    s["C2"] = 2   # (1, 2)
    assert seen == [(0, 0), (1, 2)]


def test_cell_change_payload_includes_sheet():
    s = Sheet("Demo")
    seen = []
    s.on("cell:change", lambda **ev: seen.append(ev["sheet"]))
    s["A1"] = 1
    assert seen == [s]


def test_cell_change_payload_includes_formula_source_when_set():
    s = Sheet()
    seen = []
    s.on("cell:change", lambda **ev: seen.append(ev))
    s["A1"] = "=B1*2"
    (ev,) = seen
    assert ev["new_formula"] == "=B1*2"
    assert ev["old_formula"] is None
    assert ev["new_value"] is None  # formula not yet evaluated on a bare sheet


def test_cell_change_payload_includes_live_cell_objects():
    """Per the Part 3.1 decision: the live Cell is carried alongside scalars."""
    s = Sheet()
    custom = Cell(value=42)
    seen = []
    s.on("cell:change", lambda **ev: seen.append(ev))
    s["A1"] = custom
    (ev,) = seen
    assert ev["new"] is custom
    assert isinstance(ev["old"], Cell)
    assert ev["old"].is_empty()


def test_cell_change_payload_on_delete_blanks_new_fields():
    s = Sheet()
    s["A1"] = "=B1"
    seen = []
    s.on("cell:change", lambda **ev: seen.append(ev))
    del s["A1"]
    (ev,) = seen
    assert ev["old_value"] is None
    assert ev["old_formula"] == "=B1"
    assert ev["new_value"] is None
    assert ev["new_formula"] is None
    assert ev["new"].is_empty()


# --- Part 3.2: Sheet.batch() -----------------------------------------------


def test_batch_suppresses_per_cell_change_and_emits_one_sheet_batch():
    s = Sheet()
    changes = []
    batches = []
    s.on("cell:change", lambda **ev: changes.append(ev["address"]))
    s.on("sheet:batch", lambda **ev: batches.append(ev))
    with s.batch():
        s["A1"] = 1
        s["A2"] = 2
        s["A3"] = 3
    assert changes == []            # no per-cell events during the batch
    assert len(batches) == 1        # exactly one consolidated event
    (ev,) = batches
    assert ev["sheet"] is s
    assert [c["address"] for c in ev["changes"]] == [(0, 0), (1, 0), (2, 0)]


def test_batch_change_records_match_cell_change_shape():
    s = Sheet()
    seen = []
    s.on("sheet:batch", lambda **ev: seen.append(ev["changes"]))
    with s.batch():
        s["A1"] = "=B1*2"
    (changes,) = seen
    (rec,) = changes
    assert rec["address"] == (0, 0)
    assert rec["new_formula"] == "=B1*2"
    assert rec["old_value"] is None
    assert rec["new"].formula == "=B1*2"
    assert "sheet" not in rec       # sheet lives on the top-level payload


def test_batch_writes_land_immediately_in_store():
    s = Sheet()
    with s.batch():
        s["A1"] = 7
        assert s["A1"].value == 7   # visible inside the block, pre-emit
    assert s["A1"].value == 7


def test_batch_exception_propagates_no_event_no_rollback():
    s = Sheet()
    batches = []
    s.on("sheet:batch", lambda **ev: batches.append(ev))
    with pytest.raises(ValueError):
        with s.batch():
            s["A1"] = 1
            raise ValueError("boom")
    assert batches == []            # buffered event discarded
    assert s["A1"].value == 1       # no rollback — the write stands
    assert s._batch_depth == 0      # depth cleanly unwound


def test_nested_batches_flatten_to_one_event():
    s = Sheet()
    batches = []
    s.on("sheet:batch", lambda **ev: batches.append(ev))
    with s.batch():
        s["A1"] = 1
        with s.batch():
            s["A2"] = 2
        s["A3"] = 3
    assert len(batches) == 1
    assert [c["address"] for c in batches[0]["changes"]] == [(0, 0), (1, 0), (2, 0)]


def test_empty_batch_emits_nothing():
    s = Sheet()
    batches = []
    s.on("sheet:batch", lambda **ev: batches.append(ev))
    with s.batch():
        pass
    assert batches == []


def test_batch_delete_is_buffered_too():
    s = Sheet()
    s["A1"] = 5
    batches = []
    s.on("sheet:batch", lambda **ev: batches.append(ev["changes"]))
    with s.batch():
        del s["A1"]
    (changes,) = batches
    (rec,) = changes
    assert rec["address"] == (0, 0)
    assert rec["old_value"] == 5
    assert rec["new_value"] is None
    assert rec["new"].is_empty()
