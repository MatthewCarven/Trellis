"""Tests for trellis.formula.parser."""

import pytest

from trellis.formula import parse_formula
from trellis.formula.ast import (
    BinaryOp, Bool, CellRef, FunctionCall, Number, RangeRef, String, UnaryOp,
)
from trellis.formula.errors import ParseError


# --- Literals --------------------------------------------------------


def test_integer_literal():
    assert parse_formula("42") == Number(42)


def test_float_literal():
    assert parse_formula("3.14") == Number(3.14)


def test_leading_dot_literal():
    assert parse_formula(".5") == Number(0.5)


def test_scientific_literal():
    assert parse_formula("1e3") == Number(1000.0)


def test_string_literal():
    assert parse_formula('"hello"') == String("hello")


def test_string_with_escape():
    assert parse_formula('"a""b"') == String('a"b')


def test_empty_string_literal():
    assert parse_formula('""') == String("")


def test_true_literal_upper():
    assert parse_formula("TRUE") == Bool(True)


def test_true_literal_lower():
    assert parse_formula("true") == Bool(True)


def test_true_literal_mixed_case():
    assert parse_formula("True") == Bool(True)


def test_false_literal():
    assert parse_formula("FALSE") == Bool(False)


# --- Cell references -------------------------------------------------


def test_cell_ref_simple():
    assert parse_formula("A1") == CellRef(0, 0)


def test_cell_ref_lowercase():
    assert parse_formula("a1") == CellRef(0, 0)


def test_cell_ref_two_letter():
    assert parse_formula("AA10") == CellRef(9, 26)


def test_cell_ref_far():
    assert parse_formula("ZZ999") == CellRef(998, 701)


# --- Range references ------------------------------------------------


def test_range_ref():
    assert parse_formula("A1:B5") == RangeRef(CellRef(0, 0), CellRef(4, 1))


def test_range_normalises_reversed_corners():
    """B5:A1 -> start is A1 (top-left), end is B5 (bottom-right)."""
    assert parse_formula("B5:A1") == RangeRef(CellRef(0, 0), CellRef(4, 1))


def test_range_normalises_mixed_corners():
    """A5:B1 (bottom-left to top-right) -> normal form."""
    assert parse_formula("A5:B1") == RangeRef(CellRef(0, 0), CellRef(4, 1))


def test_single_cell_range():
    assert parse_formula("A1:A1") == RangeRef(CellRef(0, 0), CellRef(0, 0))


def test_colon_without_second_ref_raises():
    with pytest.raises(ParseError, match="cell reference after"):
        parse_formula("A1:")


def test_range_with_bad_end_raises():
    with pytest.raises(ParseError):
        parse_formula("A1:notvalid")


# --- Unary operators ------------------------------------------------


def test_unary_minus():
    assert parse_formula("-5") == UnaryOp("-", Number(5))


def test_unary_plus():
    assert parse_formula("+5") == UnaryOp("+", Number(5))


def test_double_negative():
    assert parse_formula("--5") == UnaryOp("-", UnaryOp("-", Number(5)))


def test_unary_on_cell_ref():
    assert parse_formula("-A1") == UnaryOp("-", CellRef(0, 0))


def test_unary_on_parenthesized():
    assert parse_formula("-(1+2)") == UnaryOp(
        "-", BinaryOp("+", Number(1), Number(2))
    )


def test_unary_on_function_call():
    assert parse_formula("-SUM(A1)") == UnaryOp(
        "-", FunctionCall("SUM", (CellRef(0, 0),))
    )


# --- Postfix percent ----------------------------------------------


def test_postfix_percent():
    assert parse_formula("5%") == UnaryOp("%", Number(5))


def test_percent_on_cell_ref():
    assert parse_formula("A1%") == UnaryOp("%", CellRef(0, 0))


# --- Binary arithmetic --------------------------------------------


def test_addition():
    assert parse_formula("1+2") == BinaryOp("+", Number(1), Number(2))


def test_subtraction():
    assert parse_formula("3-1") == BinaryOp("-", Number(3), Number(1))


def test_multiplication():
    assert parse_formula("2*3") == BinaryOp("*", Number(2), Number(3))


def test_division():
    assert parse_formula("6/2") == BinaryOp("/", Number(6), Number(2))


def test_exponentiation():
    assert parse_formula("2^3") == BinaryOp("^", Number(2), Number(3))


def test_string_concat():
    assert parse_formula('"a"&"b"') == BinaryOp("&", String("a"), String("b"))


# --- Precedence --------------------------------------------------


def test_mul_before_add():
    # 1 + 2 * 3 -> 1 + (2 * 3)
    assert parse_formula("1+2*3") == BinaryOp(
        "+", Number(1), BinaryOp("*", Number(2), Number(3))
    )


def test_parens_override_precedence():
    assert parse_formula("(1+2)*3") == BinaryOp(
        "*", BinaryOp("+", Number(1), Number(2)), Number(3)
    )


def test_subtraction_is_left_associative():
    # 1 - 2 - 3 -> (1 - 2) - 3
    assert parse_formula("1-2-3") == BinaryOp(
        "-", BinaryOp("-", Number(1), Number(2)), Number(3)
    )


def test_division_is_left_associative():
    assert parse_formula("12/4/3") == BinaryOp(
        "/", BinaryOp("/", Number(12), Number(4)), Number(3)
    )


def test_exponentiation_is_right_associative():
    # 2 ^ 3 ^ 4 -> 2 ^ (3 ^ 4)
    assert parse_formula("2^3^4") == BinaryOp(
        "^", Number(2), BinaryOp("^", Number(3), Number(4))
    )


def test_comparison_has_lowest_precedence():
    # 1+2=3 -> (1+2) = 3
    assert parse_formula("1+2=3") == BinaryOp(
        "=", BinaryOp("+", Number(1), Number(2)), Number(3)
    )


def test_concat_above_comparison_below_arithmetic():
    # "a"&"b"="ab" -> ("a"&"b") = "ab"
    assert parse_formula('"a"&"b"="ab"') == BinaryOp(
        "=", BinaryOp("&", String("a"), String("b")), String("ab")
    )


def test_unary_binds_tighter_than_caret():
    """Excel convention: -2^3 -> (-2)^3, not -(2^3). Per design.md."""
    assert parse_formula("-2^3") == BinaryOp(
        "^", UnaryOp("-", Number(2)), Number(3)
    )


# --- Comparison operators ---------------------------------------


@pytest.mark.parametrize("op", ["=", "<>", "<", ">", "<=", ">="])
def test_all_comparison_operators(op):
    assert parse_formula(f"A1{op}B1") == BinaryOp(op, CellRef(0, 0), CellRef(0, 1))


# --- Function calls --------------------------------------------


def test_zero_arg_function():
    assert parse_formula("NOW()") == FunctionCall("NOW", ())


def test_one_arg_function():
    assert parse_formula("ABS(-5)") == FunctionCall(
        "ABS", (UnaryOp("-", Number(5)),)
    )


def test_multi_arg_function():
    assert parse_formula("IF(A1>0,1,2)") == FunctionCall(
        "IF",
        (
            BinaryOp(">", CellRef(0, 0), Number(0)),
            Number(1),
            Number(2),
        ),
    )


def test_function_name_is_uppercased():
    assert parse_formula("sum(A1:A5)") == FunctionCall(
        "SUM", (RangeRef(CellRef(0, 0), CellRef(4, 0)),)
    )


def test_nested_function_calls():
    assert parse_formula("SUM(ABS(A1),ABS(B1))") == FunctionCall(
        "SUM",
        (
            FunctionCall("ABS", (CellRef(0, 0),)),
            FunctionCall("ABS", (CellRef(0, 1),)),
        ),
    )


def test_function_with_range_arg():
    assert parse_formula("SUM(A1:A10)") == FunctionCall(
        "SUM", (RangeRef(CellRef(0, 0), CellRef(9, 0)),)
    )


def test_unknown_function_parses_to_function_call():
    """Parser doesn't validate function names — eval does (task #4b)."""
    assert parse_formula("xyz()") == FunctionCall("XYZ", ())


def test_whitespace_inside_function_call():
    assert parse_formula("SUM ( A1 : A5 )") == FunctionCall(
        "SUM", (RangeRef(CellRef(0, 0), CellRef(4, 0)),)
    )


def test_trailing_comma_in_args_raises():
    with pytest.raises(ParseError):
        parse_formula("SUM(A1,)")


def test_missing_comma_in_args_raises():
    with pytest.raises(ParseError):
        parse_formula("SUM(A1 A2)")


# --- Leading equals & whitespace --------------------------------


def test_leading_equals_is_stripped():
    assert parse_formula("=1+2") == BinaryOp("+", Number(1), Number(2))


def test_leading_equals_with_whitespace():
    assert parse_formula("  =  1+2  ") == BinaryOp("+", Number(1), Number(2))


def test_no_leading_equals_also_works():
    assert parse_formula("1+2") == BinaryOp("+", Number(1), Number(2))


# --- Error cases ----------------------------------------------


def test_empty_string_raises():
    with pytest.raises(ParseError):
        parse_formula("")


def test_just_equals_raises():
    with pytest.raises(ParseError):
        parse_formula("=")


def test_unbalanced_paren_raises():
    with pytest.raises(ParseError):
        parse_formula("(1+2")


def test_extra_closing_paren_raises():
    with pytest.raises(ParseError):
        parse_formula("1+2)")


def test_trailing_token_raises():
    with pytest.raises(ParseError, match="trailing"):
        parse_formula("1+2 3")


def test_missing_operand_raises():
    with pytest.raises(ParseError):
        parse_formula("1+")


def test_unknown_identifier_raises():
    with pytest.raises(ParseError, match="Unknown identifier"):
        parse_formula("hello")


def test_empty_parens_raises():
    with pytest.raises(ParseError):
        parse_formula("()")


def test_non_string_input_raises():
    with pytest.raises(ParseError, match="must be a string"):
        parse_formula(123)  # type: ignore[arg-type]


def test_only_whitespace_raises():
    with pytest.raises(ParseError):
        parse_formula("   ")


# --- AST nodes are equal & hashable ---------------------------


def test_ast_nodes_are_value_equal():
    a = parse_formula("A1+1")
    b = parse_formula("A1+1")
    assert a == b


def test_ast_nodes_are_hashable():
    expr = parse_formula("SUM(A1:A5)")
    {expr: "ok"}  # must not raise


def test_distinct_formulas_compare_unequal():
    assert parse_formula("A1+1") != parse_formula("A1+2")
