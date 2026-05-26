"""Tests for trellis.core.cell.Cell."""

import pytest

from trellis import Cell


def test_default_cell_is_empty():
    c = Cell()
    assert c.value is None
    assert c.formula is None
    assert c.meta == {}
    assert c.is_empty()


def test_value_cell_is_not_empty():
    assert not Cell(value=0).is_empty()
    assert not Cell(value="").is_empty()
    assert not Cell(value=False).is_empty()


def test_formula_cell_is_not_empty():
    c = Cell(formula="=A1+1")
    assert c.value is None
    assert c.formula == "=A1+1"
    assert not c.is_empty()


def test_cell_with_meta_is_not_empty():
    c = Cell()
    c.meta["color"] = "red"
    assert not c.is_empty()


def test_equality():
    assert Cell(5) == Cell(5)
    assert Cell(5) != Cell(6)
    assert Cell(formula="=A1") == Cell(formula="=A1")
    assert Cell(5) != Cell(5, formula="=A1+1")


def test_equality_includes_meta():
    a = Cell(5)
    b = Cell(5)
    a.meta["x"] = 1
    assert a != b
    b.meta["x"] = 1
    assert a == b


def test_cell_not_equal_to_other_types():
    assert Cell(5) != 5
    assert Cell("hi") != "hi"
    assert (Cell() == object()) is False


def test_repr_plain():
    assert repr(Cell(5)) == "Cell(5)"
    assert repr(Cell("hi")) == "Cell('hi')"


def test_repr_with_formula():
    assert repr(Cell(value=10, formula="=A1*2")) == "Cell(value=10, formula='=A1*2')"


def test_meta_is_publicly_writable():
    """The meta dict is the polite extension surface — verify it's free game."""
    c = Cell()
    c.meta["plugin:formatting"] = {"bold": True, "color": "#ff0000"}
    c.meta["plugin:validation"] = lambda v: isinstance(v, int)
    assert c.meta["plugin:formatting"]["bold"] is True


def test_cells_are_unhashable():
    with pytest.raises(TypeError):
        hash(Cell(5))


def test_cell_accepts_arbitrary_attribute():
    """Open-extensibility check: monkey-patching is allowed, no __slots__."""
    c = Cell()
    c.custom_attribute = "hello"  # type: ignore[attr-defined]
    assert c.custom_attribute == "hello"  # type: ignore[attr-defined]
