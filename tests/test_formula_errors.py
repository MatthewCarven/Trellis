"""Tests for trellis.formula.errors."""

import pytest

from trellis.formula.errors import (
    CIRC, DIV0, NA, NAME, NULL, REF, VALUE, FormulaError, ParseError,
)


# --- Constants ---------------------------------------------------------


def test_constants_have_excel_codes():
    assert DIV0.code == "#DIV/0!"
    assert VALUE.code == "#VALUE!"
    assert REF.code == "#REF!"
    assert NAME.code == "#NAME?"
    assert CIRC.code == "#CIRC!"
    assert NA.code == "#N/A"
    assert NULL.code == "#NULL!"


def test_constants_have_human_messages():
    assert DIV0.message
    assert VALUE.message
    assert REF.message


# --- FormulaError value semantics --------------------------------------


def test_equality_is_by_code_only():
    assert FormulaError("#DIV/0!") == FormulaError("#DIV/0!", "different message")
    assert FormulaError("#DIV/0!", "x") == DIV0


def test_distinct_codes_are_unequal():
    assert DIV0 != VALUE
    assert FormulaError("#X") != FormulaError("#Y")


def test_equality_with_non_formulaerror_is_not_implemented():
    assert (DIV0 == "x") is False
    assert (DIV0 == 5) is False
    assert (DIV0 == None) is False


def test_str_returns_code():
    assert str(DIV0) == "#DIV/0!"
    assert str(FormulaError("#X")) == "#X"


def test_repr_with_message_includes_both():
    r = repr(DIV0)
    assert "FormulaError" in r
    assert "#DIV/0!" in r
    assert "Division" in r


def test_repr_without_message():
    assert repr(FormulaError("#X")) == "FormulaError('#X')"


def test_hash_matches_equality():
    a = FormulaError("#DIV/0!")
    b = FormulaError("#DIV/0!", "different message")
    assert hash(a) == hash(b)


def test_hash_allows_dict_key():
    d = {DIV0: "yes"}
    assert d[FormulaError("#DIV/0!")] == "yes"
    assert d[FormulaError("#DIV/0!", "any message")] == "yes"


def test_formulaerror_is_not_an_exception():
    """FormulaError must NOT subclass Exception — they're values, not raises."""
    assert not isinstance(DIV0, Exception)
    assert not issubclass(FormulaError, Exception)


def test_cannot_raise_a_formulaerror():
    """Raising a FormulaError fails at the Python level — it's not an Exception."""
    with pytest.raises(TypeError):
        raise DIV0  # type: ignore[misc]


def test_slots_prevents_arbitrary_attrs():
    err = FormulaError("#X")
    with pytest.raises(AttributeError):
        err.custom = "nope"  # type: ignore[attr-defined]


# --- ParseError --------------------------------------------------------


def test_parse_error_is_an_exception():
    assert issubclass(ParseError, Exception)
    with pytest.raises(ParseError):
        raise ParseError("bad")


def test_parse_error_carries_pos():
    try:
        raise ParseError("bad input", pos=42)
    except ParseError as e:
        assert e.pos == 42
        assert "bad input" in str(e)


def test_parse_error_default_pos_is_negative():
    e = ParseError("no position given")
    assert e.pos == -1
