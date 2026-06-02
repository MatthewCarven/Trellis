"""Tests for trellis.core.range.Range."""

import pytest

from trellis import Cell, Range, Sheet
from trellis.core.address import to_a1


# --- Construction --------------------------------------------------------


def test_construct_from_string_addr():
    r = Range(Sheet(), "A1:B3")
    assert r.start == (0, 0)
    assert r.end == (2, 1)


def test_construct_from_tuple_addr():
    r = Range(Sheet(), ((0, 0), (2, 1)))
    assert r.start == (0, 0)
    assert r.end == (2, 1)


def test_construct_normalizes_reversed_corners():
    r = Range(Sheet(), "B3:A1")
    assert r.start == (0, 0)
    assert r.end == (2, 1)


def test_construct_normalizes_mixed_corners():
    r = Range(Sheet(), "A3:B1")
    assert r.start == (0, 0)
    assert r.end == (2, 1)


def test_construct_single_cell_range():
    r = Range(Sheet(), "A1:A1")
    assert r.start == (0, 0)
    assert r.end == (0, 0)
    assert len(r) == 1


def test_string_without_colon_raises():
    with pytest.raises(ValueError, match="must contain ':'"):
        Range(Sheet(), "A1")


def test_invalid_address_part_raises():
    with pytest.raises(ValueError):
        Range(Sheet(), "A1:not-an-address")


def test_unsupported_addr_type_raises():
    with pytest.raises(TypeError):
        Range(Sheet(), 5)
    with pytest.raises(TypeError):
        Range(Sheet(), ["A1", "B5"])  # list, not tuple


# --- Shape ---------------------------------------------------------------


def test_shape_properties():
    r = Range(Sheet(), "A1:C5")
    assert r.rows == 5
    assert r.cols == 3
    assert r.shape == (5, 3)
    assert len(r) == 15


def test_single_row():
    r = Range(Sheet(), "A1:E1")
    assert r.shape == (1, 5)


def test_single_column():
    r = Range(Sheet(), "A1:A5")
    assert r.shape == (5, 1)


# --- Iteration -----------------------------------------------------------


def test_positions_row_major():
    r = Range(Sheet(), "A1:B2")
    assert list(r.positions()) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_addrs_row_major():
    r = Range(Sheet(), "A1:B2")
    assert list(r.addrs()) == ["A1", "B1", "A2", "B2"]


def test_cells_yields_empty_for_unstored():
    s = Sheet()
    s["A1"] = 5
    r = Range(s, "A1:B1")
    pairs = list(r.cells())
    assert pairs[0][0] == "A1"
    assert pairs[0][1].value == 5
    assert pairs[1][0] == "B1"
    assert pairs[1][1].is_empty()


def test_values_includes_none_for_empty():
    s = Sheet()
    s["A1"] = 5
    s["B1"] = 10
    r = Range(s, "A1:C1")
    assert list(r.values()) == [5, 10, None]


def test_iter_yields_cell_objects():
    s = Sheet()
    s["A1"] = 5
    r = Range(s, "A1:B1")
    cells = list(r)
    assert len(cells) == 2
    assert cells[0].value == 5
    assert cells[1].is_empty()


# --- Membership ----------------------------------------------------------


def test_contains_inside_addr():
    r = Range(Sheet(), "B2:D4")
    assert "B2" in r
    assert "C3" in r
    assert "D4" in r


def test_contains_outside_addr():
    r = Range(Sheet(), "B2:D4")
    assert "A1" not in r
    assert "E5" not in r
    assert "A2" not in r


def test_contains_tuple_addr():
    r = Range(Sheet(), "A1:B2")
    assert (0, 0) in r
    assert (5, 5) not in r


def test_contains_garbage_returns_false():
    r = Range(Sheet(), "A1:B2")
    assert "garbage" not in r
    assert 5 not in r


# --- Broadcast assignment ------------------------------------------------


def test_assign_scalar_broadcasts():
    s = Sheet()
    s.range("A1:B3").assign(0)
    assert [c.value for c in s.range("A1:B3")] == [0, 0, 0, 0, 0, 0]


def test_assign_formula_string_broadcasts():
    s = Sheet()
    s.range("A1:A3").assign("=B1*2")
    assert all(c.formula == "=B1*2" for c in s.range("A1:A3"))


def test_assign_1d_to_row():
    s = Sheet()
    s.range("A1:C1").assign([10, 20, 30])
    assert [c.value for c in s.range("A1:C1")] == [10, 20, 30]


def test_assign_1d_to_column():
    s = Sheet()
    s.range("A1:A3").assign([10, 20, 30])
    assert [c.value for c in s.range("A1:A3")] == [10, 20, 30]


def test_assign_1d_length_mismatch_raises():
    s = Sheet()
    with pytest.raises(ValueError, match="has 2 values but range has 3"):
        s.range("A1:A3").assign([1, 2])


def test_assign_1d_to_2d_range_raises():
    s = Sheet()
    with pytest.raises(ValueError, match="1D iterable can only assign"):
        s.range("A1:B3").assign([1, 2, 3, 4, 5, 6])


def test_assign_2d_matching_shape():
    s = Sheet()
    s.range("A1:B2").assign([[1, 2], [3, 4]])
    assert [c.value for c in s.range("A1:B2")] == [1, 2, 3, 4]


def test_assign_2d_row_count_mismatch_raises():
    s = Sheet()
    with pytest.raises(ValueError, match="has 1 rows but range has 2"):
        s.range("A1:B2").assign([[1, 2]])


def test_assign_2d_col_count_mismatch_raises():
    s = Sheet()
    with pytest.raises(ValueError, match="has 1 cols but range has 2"):
        s.range("A1:B2").assign([[1], [3]])


def test_assign_empty_iterable_raises():
    s = Sheet()
    with pytest.raises(ValueError, match="empty iterable"):
        s.range("A1:A3").assign([])


def test_assign_string_is_scalar_not_iterable():
    s = Sheet()
    s.range("A1:B1").assign("hello")
    assert [c.value for c in s.range("A1:B1")] == ["hello", "hello"]


def test_assign_none_broadcasts():
    s = Sheet()
    s.range("A1:B1").assign(None)
    # None is a scalar; still gets stored as a Cell with value=None
    assert all(c.value is None for c in s.range("A1:B1"))


# --- Event emission via Range -------------------------------------------


def test_assign_fires_cell_change_per_cell():
    s = Sheet()
    events = []
    s.on("cell:change", lambda **ev: events.append((to_a1(*ev["address"]), ev["new"].value)))
    s.range("A1:B2").assign([[1, 2], [3, 4]])
    assert events == [("A1", 1), ("B1", 2), ("A2", 3), ("B2", 4)]


# --- Clear --------------------------------------------------------------


def test_clear_deletes_all_cells():
    s = Sheet()
    s["A1"] = 1
    s["B2"] = 2
    s["C3"] = 3
    s.range("A1:C3").clear()
    assert len(s) == 0


def test_clear_emits_for_existing_cells_only():
    s = Sheet()
    s["A1"] = 1
    s["B2"] = 2
    events = []
    s.on("cell:change", lambda **ev: events.append(to_a1(*ev["address"])))
    s.range("A1:B2").clear()
    assert sorted(events) == ["A1", "B2"]


# --- Repr ---------------------------------------------------------------


def test_repr_includes_addresses_and_shape():
    s = Sheet("MySheet")
    r = s.range("A1:C5")
    assert repr(r) == "Range('MySheet', A1:C5, 5x3)"
