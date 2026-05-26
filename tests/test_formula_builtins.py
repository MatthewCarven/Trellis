"""Tests for the first batch of built-in functions (#22).

Covers SUM, AVERAGE, COUNT, MIN, MAX, ABS, ROUND, INT, IF (lazy), NOT.
These are exercised through the parser → evaluator stack so the tests
also lock in the dispatcher's eager/lazy contract for real built-ins,
not just the registry-level synthetic functions in
``test_formula_functions.py``.
"""

from __future__ import annotations

import math

import pytest

from trellis import Sheet
from trellis.formula import (
    DIV0,
    NA,
    VALUE,
    FormulaError,
    Context,
    evaluate,
    parse_formula,
)


def evalstr(src: str, sheet: Sheet | None = None) -> object:
    if sheet is None:
        sheet = Sheet("Test")
    return evaluate(parse_formula(src), Context(sheet=sheet))


def _fill(s: Sheet, **kwargs):
    for k, v in kwargs.items():
        s[k] = v
    return s


# --- Built-ins are registered at import --------------------------------


def test_all_builtins_registered_at_import():
    """Importing trellis.formula must register all #22 built-ins."""
    from trellis.formula import registered_function_names

    names = set(registered_function_names())
    expected = {"SUM", "AVERAGE", "COUNT", "MIN", "MAX",
                "ABS", "ROUND", "INT", "IF", "NOT"}
    missing = expected - names
    assert not missing, f"built-ins not registered: {missing}"


# =======================================================================
# SUM
# =======================================================================


def test_sum_no_args_is_zero():
    assert evalstr("SUM()") == 0


def test_sum_scalar_numbers():
    assert evalstr("SUM(1, 2, 3, 4)") == 10


def test_sum_negatives_and_floats():
    assert evalstr("SUM(1.5, -0.5, 2)") == 3.0


def test_sum_single_range():
    s = _fill(Sheet(), A1=10, A2=20, A3=30)
    assert evalstr("SUM(A1:A3)", s) == 60


def test_sum_mixed_scalar_and_range():
    s = _fill(Sheet(), A1=1, A2=2, A3=3)
    assert evalstr("SUM(100, A1:A3, 1000)", s) == 1106


def test_sum_skips_strings_in_range():
    s = Sheet()
    s["A1"] = 10
    s["A2"] = "ignored"
    s["A3"] = 20
    assert evalstr("SUM(A1:A3)", s) == 30


def test_sum_skips_bools_in_range():
    """Excel doesn't count TRUE/FALSE inside a range toward SUM."""
    s = Sheet()
    s["A1"] = 5
    s["A2"] = True
    s["A3"] = False
    assert evalstr("SUM(A1:A3)", s) == 5


def test_sum_skips_empty_cells_in_range():
    s = Sheet()
    s["A1"] = 1
    s["A3"] = 2  # A2 is empty (None)
    assert evalstr("SUM(A1:A3)", s) == 3


def test_sum_scalar_string_is_value_error():
    """A string passed directly as a scalar arg is an error (the engine
    doesn't auto-parse strings anywhere)."""
    assert evalstr('SUM(1, "hello", 3)') == VALUE


def test_sum_scalar_bool_treated_as_zero_or_one():
    """Bools as direct scalar args coerce per arithmetic rules."""
    assert evalstr("SUM(TRUE, TRUE, FALSE)") == 2


def test_sum_propagates_error_in_range():
    s = Sheet()
    s["A1"] = 1
    s["A2"] = 10 / 0 if False else None  # placeholder; set via formula below
    # Easier: put an error value directly.
    s["A2"] = DIV0
    s["A3"] = 3
    assert evalstr("SUM(A1:A3)", s) == DIV0


def test_sum_propagates_error_from_scalar_arg():
    """Eager dispatcher short-circuits on FormulaError args before
    SUM is ever invoked."""
    assert evalstr("SUM(1, 1/0, 3)") == DIV0


# =======================================================================
# AVERAGE
# =======================================================================


def test_average_basic():
    assert evalstr("AVERAGE(1, 2, 3, 4)") == 2.5


def test_average_of_range():
    s = _fill(Sheet(), A1=10, A2=20, A3=30)
    assert evalstr("AVERAGE(A1:A3)", s) == 20


def test_average_skips_non_numerics_in_range():
    s = Sheet()
    s["A1"] = 10
    s["A2"] = "skip"
    s["A3"] = 20
    # Average of [10, 20] = 15, not 10 (which it'd be if "skip" counted as 0)
    assert evalstr("AVERAGE(A1:A3)", s) == 15


def test_average_no_numerics_is_div0():
    assert evalstr("AVERAGE()") == DIV0


def test_average_empty_range_is_div0():
    s = Sheet()  # A1:A3 all empty
    assert evalstr("AVERAGE(A1:A3)", s) == DIV0


def test_average_scalar_string_is_value_error():
    assert evalstr('AVERAGE("hello")') == VALUE


# =======================================================================
# COUNT
# =======================================================================


def test_count_no_args_is_zero():
    assert evalstr("COUNT()") == 0


def test_count_scalars():
    assert evalstr("COUNT(1, 2, 3)") == 3


def test_count_skips_scalar_strings_silently():
    """COUNT never errors on text — text is just not counted."""
    assert evalstr('COUNT(1, "text", 2, "more text", 3)') == 3


def test_count_skips_bools_scalar():
    assert evalstr("COUNT(1, TRUE, 2, FALSE, 3)") == 3


def test_count_of_range_counts_numerics_only():
    s = Sheet()
    s["A1"] = 1
    s["A2"] = "text"
    s["A3"] = 2
    s["A4"] = True
    s["A5"] = 3
    assert evalstr("COUNT(A1:A5)", s) == 3


def test_count_of_empty_range_is_zero():
    s = Sheet()
    assert evalstr("COUNT(A1:A5)", s) == 0


def test_count_floats_counted():
    assert evalstr("COUNT(1, 2.5, 3.14)") == 3


# =======================================================================
# MIN / MAX
# =======================================================================


def test_min_basic():
    assert evalstr("MIN(3, 1, 4, 1, 5, 9, 2, 6)") == 1


def test_max_basic():
    assert evalstr("MAX(3, 1, 4, 1, 5, 9, 2, 6)") == 9


def test_min_of_range():
    s = _fill(Sheet(), A1=5, A2=-3, A3=10)
    assert evalstr("MIN(A1:A3)", s) == -3


def test_max_of_range():
    s = _fill(Sheet(), A1=5, A2=-3, A3=10)
    assert evalstr("MAX(A1:A3)", s) == 10


def test_min_no_numerics_returns_zero():
    """Excel convention: MIN()/MAX() of nothing returns 0, not an error."""
    assert evalstr("MIN()") == 0


def test_max_no_numerics_returns_zero():
    assert evalstr("MAX()") == 0


def test_min_skips_strings_in_range():
    s = Sheet()
    s["A1"] = 10
    s["A2"] = "huge string"  # would be lex-greatest if compared as string
    s["A3"] = 20
    assert evalstr("MIN(A1:A3)", s) == 10
    assert evalstr("MAX(A1:A3)", s) == 20


def test_min_scalar_string_is_value_error():
    assert evalstr('MIN("a", "b")') == VALUE


def test_min_propagates_error_in_range():
    s = Sheet()
    s["A1"] = 1
    s["A2"] = DIV0
    s["A3"] = 3
    assert evalstr("MIN(A1:A3)", s) == DIV0
    assert evalstr("MAX(A1:A3)", s) == DIV0


# =======================================================================
# ABS
# =======================================================================


def test_abs_positive():
    assert evalstr("ABS(5)") == 5


def test_abs_negative():
    assert evalstr("ABS(-7)") == 7


def test_abs_float():
    assert evalstr("ABS(-3.14)") == 3.14


def test_abs_zero():
    assert evalstr("ABS(0)") == 0


def test_abs_of_empty_cell_is_zero():
    s = Sheet()
    assert evalstr("ABS(A1)", s) == 0


def test_abs_of_string_is_value_error():
    assert evalstr('ABS("hello")') == VALUE


def test_abs_propagates_error():
    assert evalstr("ABS(1/0)") == DIV0


# =======================================================================
# ROUND
# =======================================================================


def test_round_half_away_from_zero_positive():
    """Excel rule: 2.5 → 3 (not 2 like banker's rounding)."""
    assert evalstr("ROUND(2.5, 0)") == 3


def test_round_half_away_from_zero_negative():
    """And -2.5 → -3, not -2."""
    assert evalstr("ROUND(-2.5, 0)") == -3


def test_round_to_decimals():
    assert evalstr("ROUND(1.2345, 2)") == 1.23


def test_round_to_decimals_with_half_away():
    assert evalstr("ROUND(1.235, 2)") == pytest.approx(1.24)


def test_round_negative_digits_rounds_left_of_decimal():
    """Negative digits round to tens / hundreds / etc."""
    assert evalstr("ROUND(1234.5, -1)") == 1230
    assert evalstr("ROUND(1234.5, -2)") == 1200


def test_round_zero():
    assert evalstr("ROUND(0, 2)") == 0


def test_round_propagates_error():
    assert evalstr("ROUND(1/0, 2)") == DIV0
    assert evalstr("ROUND(5, 1/0)") == DIV0


def test_round_string_arg_is_value_error():
    assert evalstr('ROUND("x", 2)') == VALUE


# =======================================================================
# INT
# =======================================================================


def test_int_positive_truncates():
    assert evalstr("INT(3.7)") == 3


def test_int_exact_integer():
    assert evalstr("INT(5)") == 5


def test_int_negative_rounds_toward_negative_infinity():
    """Excel rule, NOT Python's int() (which truncates toward zero).
    INT(-1.5) is -2, not -1."""
    assert evalstr("INT(-1.5)") == -2
    assert evalstr("INT(-3.7)") == -4


def test_int_of_empty_cell_is_zero():
    s = Sheet()
    assert evalstr("INT(A1)", s) == 0


def test_int_propagates_error():
    assert evalstr("INT(1/0)") == DIV0


def test_int_string_is_value_error():
    assert evalstr('INT("hi")') == VALUE


# =======================================================================
# IF (lazy)
# =======================================================================


def test_if_true_returns_then_branch():
    assert evalstr("IF(TRUE, 1, 2)") == 1


def test_if_false_returns_else_branch():
    assert evalstr("IF(FALSE, 1, 2)") == 2


def test_if_truthy_number_takes_then():
    assert evalstr("IF(1, 10, 20)") == 10
    assert evalstr("IF(-5, 10, 20)") == 10  # any non-zero is truthy


def test_if_zero_takes_else():
    assert evalstr("IF(0, 10, 20)") == 20


def test_if_missing_else_returns_false_when_condition_false():
    """Excel-equivalent: omitted else means FALSE."""
    assert evalstr("IF(FALSE, 1)") is False


def test_if_missing_else_returns_then_when_condition_true():
    assert evalstr("IF(TRUE, 42)") == 42


def test_if_lazy_does_not_evaluate_else_when_true():
    """LOAD-BEARING: if IF eagerly evaluated both branches, 1/0 in the
    else branch would surface DIV0."""
    assert evalstr("IF(TRUE, 99, 1/0)") == 99


def test_if_lazy_does_not_evaluate_then_when_false():
    assert evalstr("IF(FALSE, 1/0, 99)") == 99


def test_if_propagates_error_from_condition():
    assert evalstr("IF(1/0, 1, 2)") == DIV0


def test_if_string_condition_is_value_error():
    """We don't auto-parse strings into bools."""
    assert evalstr('IF("yes", 1, 2)') == VALUE


def test_if_too_few_args_is_na():
    assert evalstr("IF(TRUE)") == NA


def test_if_too_many_args_is_na():
    assert evalstr("IF(TRUE, 1, 2, 3)") == NA


def test_if_with_comparison_condition():
    s = _fill(Sheet(), A1=10, A2=5)
    assert evalstr("IF(A1>A2, 100, 200)", s) == 100
    assert evalstr("IF(A1<A2, 100, 200)", s) == 200


def test_if_nested():
    assert evalstr("IF(TRUE, IF(TRUE, 1, 2), 3)") == 1
    assert evalstr("IF(TRUE, IF(FALSE, 1, 2), 3)") == 2
    assert evalstr("IF(FALSE, IF(TRUE, 1, 2), 3)") == 3


def test_if_empty_cell_condition_is_false():
    s = Sheet()  # A1 empty
    assert evalstr("IF(A1, 1, 2)", s) == 2


# =======================================================================
# NOT
# =======================================================================


def test_not_true_is_false():
    assert evalstr("NOT(TRUE)") is False


def test_not_false_is_true():
    assert evalstr("NOT(FALSE)") is True


def test_not_zero_is_true():
    assert evalstr("NOT(0)") is True


def test_not_nonzero_is_false():
    assert evalstr("NOT(5)") is False
    assert evalstr("NOT(-1)") is False


def test_not_empty_cell_is_true():
    s = Sheet()
    assert evalstr("NOT(A1)", s) is True


def test_not_string_is_value_error():
    assert evalstr('NOT("hello")') == VALUE


def test_not_propagates_error():
    assert evalstr("NOT(1/0)") == DIV0


def test_not_double_negation():
    assert evalstr("NOT(NOT(TRUE))") is True
    assert evalstr("NOT(NOT(FALSE))") is False


# =======================================================================
# Composition: built-ins playing nicely together
# =======================================================================


def test_sum_in_round():
    assert evalstr("ROUND(SUM(1.111, 2.222, 3.333), 1)") == pytest.approx(6.7)


def test_if_with_aggregates():
    s = _fill(Sheet(), A1=10, A2=20, A3=30)
    # SUM(A1:A3) = 60, > 50, so take the then-branch
    assert evalstr("IF(SUM(A1:A3) > 50, MAX(A1:A3), MIN(A1:A3))", s) == 30


def test_average_of_min_max():
    s = _fill(Sheet(), A1=1, A2=2, A3=3, A4=4, A5=5)
    # (MIN + MAX) / 2 = (1 + 5) / 2 = 3
    assert evalstr("AVERAGE(MIN(A1:A5), MAX(A1:A5))", s) == 3


def test_abs_of_sum_of_negatives():
    assert evalstr("ABS(SUM(-1, -2, -3))") == 6


def test_int_of_average():
    assert evalstr("INT(AVERAGE(1, 2, 4))") == 2  # avg = 2.333... → 2


def test_count_inside_if_condition():
    s = _fill(Sheet(), A1=1, A2=2, A3=3)
    assert evalstr('IF(COUNT(A1:A3) = 3, "all", "partial")', s) == "all"


# =======================================================================
# =======================================================================
# Second batch (#23): IFERROR, ISERROR, ISBLANK, ISNUMBER, ISTEXT,
# AND, OR, CONCAT, LEN, LEFT, RIGHT, MID. Plus arg-count regression
# tests for the #22 functions that were refactored to *args + len check.
# =======================================================================
# =======================================================================


# --- #23 functions registered at import --------------------------------


def test_batch_two_builtins_registered_at_import():
    from trellis.formula import registered_function_names

    names = set(registered_function_names())
    expected = {
        "IFERROR", "ISERROR",
        "ISBLANK", "ISNUMBER", "ISTEXT",
        "AND", "OR",
        "CONCAT", "LEN", "LEFT", "RIGHT", "MID",
    }
    missing = expected - names
    assert not missing, f"#23 built-ins not registered: {missing}"


# =======================================================================
# IFERROR
# =======================================================================


def test_iferror_passes_through_value_when_no_error():
    assert evalstr("IFERROR(42, 99)") == 42
    assert evalstr('IFERROR("hi", "fallback")') == "hi"


def test_iferror_returns_fallback_on_error():
    assert evalstr("IFERROR(1/0, 99)") == 99


def test_iferror_fallback_can_itself_be_an_error():
    """Excel returns the fallback as-is, even if it's an error."""
    assert evalstr("IFERROR(1/0, 1/0)") == DIV0


def test_iferror_does_not_evaluate_fallback_when_value_ok():
    """Lazy contract: 1/0 in the fallback must NOT evaluate if the
    primary value is fine."""
    assert evalstr("IFERROR(42, 1/0)") == 42  # would be DIV0 if eager


def test_iferror_works_with_value_zero():
    assert evalstr("IFERROR(0, 99)") == 0  # 0 is not an error


def test_iferror_works_with_empty_string():
    assert evalstr('IFERROR("", "fallback")') == ""


def test_iferror_arg_count_errors():
    assert evalstr("IFERROR(1)") == NA
    assert evalstr("IFERROR(1, 2, 3)") == NA
    assert evalstr("IFERROR()") == NA


# =======================================================================
# ISERROR
# =======================================================================


def test_iserror_true_for_div0():
    assert evalstr("ISERROR(1/0)") is True


def test_iserror_false_for_number():
    assert evalstr("ISERROR(42)") is False


def test_iserror_false_for_string():
    assert evalstr('ISERROR("hello")') is False


def test_iserror_false_for_bool():
    assert evalstr("ISERROR(TRUE)") is False
    assert evalstr("ISERROR(FALSE)") is False


def test_iserror_false_for_empty_cell():
    s = Sheet()
    assert evalstr("ISERROR(A1)", s) is False


def test_iserror_true_for_value_error():
    """A scalar string into a function that doesn't accept strings."""
    assert evalstr('ISERROR(ABS("hello"))') is True


def test_iserror_arg_count_error():
    assert evalstr("ISERROR()") == NA
    assert evalstr("ISERROR(1, 2)") == NA


# =======================================================================
# ISBLANK / ISNUMBER / ISTEXT
# =======================================================================


def test_isblank_true_for_empty_cell():
    s = Sheet()
    assert evalstr("ISBLANK(A1)", s) is True


def test_isblank_false_for_empty_string():
    """Excel-strict: "" is NOT blank, only an actually-empty cell is."""
    assert evalstr('ISBLANK("")') is False


def test_isblank_false_for_zero():
    assert evalstr("ISBLANK(0)") is False


def test_isblank_false_for_filled_cell():
    s = _fill(Sheet(), A1=42)
    assert evalstr("ISBLANK(A1)", s) is False


def test_isblank_range_arg_is_value_error():
    s = Sheet()
    assert evalstr("ISBLANK(A1:A3)", s) == VALUE


def test_isnumber_true_for_int():
    assert evalstr("ISNUMBER(42)") is True


def test_isnumber_true_for_float():
    assert evalstr("ISNUMBER(3.14)") is True


def test_isnumber_false_for_bool():
    """Bools shouldn't count as numbers in the spreadsheet sense,
    even though Python's ``bool`` is an ``int`` subclass."""
    assert evalstr("ISNUMBER(TRUE)") is False
    assert evalstr("ISNUMBER(FALSE)") is False


def test_isnumber_false_for_string():
    assert evalstr('ISNUMBER("42")') is False


def test_isnumber_false_for_empty_cell():
    s = Sheet()
    assert evalstr("ISNUMBER(A1)", s) is False


def test_isnumber_false_for_range():
    s = _fill(Sheet(), A1=1, A2=2)
    assert evalstr("ISNUMBER(A1:A2)", s) is False


def test_istext_true_for_string():
    assert evalstr('ISTEXT("hello")') is True


def test_istext_true_for_empty_string():
    assert evalstr('ISTEXT("")') is True


def test_istext_false_for_number():
    assert evalstr("ISTEXT(42)") is False


def test_istext_false_for_bool():
    assert evalstr("ISTEXT(TRUE)") is False


def test_istext_false_for_empty_cell():
    s = Sheet()
    assert evalstr("ISTEXT(A1)", s) is False


def test_type_predicates_arg_count_errors():
    assert evalstr("ISBLANK()") == NA
    assert evalstr("ISNUMBER(1, 2)") == NA
    assert evalstr("ISTEXT()") == NA


# =======================================================================
# AND
# =======================================================================


def test_and_all_true():
    assert evalstr("AND(TRUE, TRUE, TRUE)") is True


def test_and_one_false():
    assert evalstr("AND(TRUE, FALSE, TRUE)") is False


def test_and_numeric_truthiness():
    assert evalstr("AND(1, 2, 3)") is True
    assert evalstr("AND(1, 0, 3)") is False


def test_and_single_arg():
    assert evalstr("AND(TRUE)") is True
    assert evalstr("AND(FALSE)") is False


def test_and_no_args_is_value():
    assert evalstr("AND()") == VALUE


def test_and_range_arg():
    s = _fill(Sheet(), A1=True, A2=True, A3=True)
    assert evalstr("AND(A1:A3)", s) is True
    s["A2"] = False
    assert evalstr("AND(A1:A3)", s) is False


def test_and_skips_strings_in_range():
    s = Sheet()
    s["A1"] = True
    s["A2"] = "skip me"
    s["A3"] = True
    assert evalstr("AND(A1:A3)", s) is True


def test_and_all_text_range_is_value():
    s = Sheet()
    s["A1"] = "a"
    s["A2"] = "b"
    assert evalstr("AND(A1:A2)", s) == VALUE


def test_and_scalar_string_is_value():
    assert evalstr('AND(TRUE, "yes")') == VALUE


def test_and_propagates_error():
    assert evalstr("AND(TRUE, 1/0)") == DIV0


def test_and_error_in_range_propagates():
    s = Sheet()
    s["A1"] = True
    s["A2"] = DIV0
    assert evalstr("AND(A1:A2)", s) == DIV0


# =======================================================================
# OR
# =======================================================================


def test_or_any_true():
    assert evalstr("OR(FALSE, FALSE, TRUE)") is True


def test_or_all_false():
    assert evalstr("OR(FALSE, FALSE, FALSE)") is False


def test_or_numeric_truthiness():
    assert evalstr("OR(0, 0, 1)") is True
    assert evalstr("OR(0, 0, 0)") is False


def test_or_no_args_is_value():
    assert evalstr("OR()") == VALUE


def test_or_range_arg():
    s = _fill(Sheet(), A1=False, A2=False, A3=True)
    assert evalstr("OR(A1:A3)", s) is True


def test_or_scalar_string_is_value():
    assert evalstr('OR(FALSE, "no")') == VALUE


def test_or_propagates_error():
    """Excel doesn't short-circuit OR either: OR(TRUE, 1/0) is DIV0."""
    assert evalstr("OR(TRUE, 1/0)") == DIV0


# =======================================================================
# CONCAT
# =======================================================================


def test_concat_basic():
    assert evalstr('CONCAT("a", "b", "c")') == "abc"


def test_concat_numbers_coerced():
    assert evalstr("CONCAT(1, 2, 3)") == "123"


def test_concat_mixed():
    assert evalstr('CONCAT("x=", 42)') == "x=42"


def test_concat_no_args_is_empty_string():
    assert evalstr("CONCAT()") == ""


def test_concat_range_arg():
    s = _fill(Sheet(), A1="hello", A2=" ", A3="world")
    assert evalstr("CONCAT(A1:A3)", s) == "hello world"


def test_concat_bool_coerced_to_text():
    assert evalstr('CONCAT("v=", TRUE)') == "v=TRUE"


def test_concat_none_becomes_empty_string():
    s = Sheet()  # A1 empty
    assert evalstr('CONCAT("a", A1, "b")', s) == "ab"


def test_concat_integer_float_loses_trailing_zero():
    """Matches the & operator: 1.0 concatenates as "1", not "1.0"."""
    assert evalstr('CONCAT("v=", 1.0)') == "v=1"


def test_concat_propagates_error_in_range():
    s = Sheet()
    s["A1"] = "x"
    s["A2"] = DIV0
    assert evalstr("CONCAT(A1:A2)", s) == DIV0


# =======================================================================
# LEN
# =======================================================================


def test_len_string():
    assert evalstr('LEN("hello")') == 5


def test_len_empty_string():
    assert evalstr('LEN("")') == 0


def test_len_number_coerced():
    assert evalstr("LEN(12345)") == 5


def test_len_float_coerced():
    assert evalstr("LEN(3.14)") == 4  # "3.14"


def test_len_bool():
    assert evalstr("LEN(TRUE)") == 4  # "TRUE"
    assert evalstr("LEN(FALSE)") == 5


def test_len_empty_cell():
    s = Sheet()
    assert evalstr("LEN(A1)", s) == 0


def test_len_range_is_value():
    s = _fill(Sheet(), A1=1, A2=2)
    assert evalstr("LEN(A1:A2)", s) == VALUE


def test_len_arg_count_error():
    assert evalstr("LEN()") == NA
    assert evalstr('LEN("a", "b")') == NA


# =======================================================================
# LEFT
# =======================================================================


def test_left_default_n_is_one():
    assert evalstr('LEFT("hello")') == "h"


def test_left_with_n():
    assert evalstr('LEFT("hello", 3)') == "hel"


def test_left_n_zero():
    assert evalstr('LEFT("hello", 0)') == ""


def test_left_n_larger_than_string():
    assert evalstr('LEFT("hi", 99)') == "hi"


def test_left_negative_n_is_value():
    assert evalstr('LEFT("hello", -1)') == VALUE


def test_left_coerces_number_to_string():
    assert evalstr("LEFT(12345, 2)") == "12"


def test_left_arg_count_errors():
    assert evalstr("LEFT()") == NA
    assert evalstr('LEFT("a", 1, 2)') == NA


# =======================================================================
# RIGHT
# =======================================================================


def test_right_default_n_is_one():
    assert evalstr('RIGHT("hello")') == "o"


def test_right_with_n():
    assert evalstr('RIGHT("hello", 3)') == "llo"


def test_right_n_zero():
    """Special case: text[-0:] is the whole string in Python, but Excel
    returns "" for RIGHT(text, 0). Verify we get the Excel answer."""
    assert evalstr('RIGHT("hello", 0)') == ""


def test_right_n_larger_than_string():
    assert evalstr('RIGHT("hi", 99)') == "hi"


def test_right_negative_n_is_value():
    assert evalstr('RIGHT("hello", -1)') == VALUE


def test_right_arg_count_errors():
    assert evalstr("RIGHT()") == NA
    assert evalstr('RIGHT("a", 1, 2)') == NA


# =======================================================================
# MID
# =======================================================================


def test_mid_basic():
    assert evalstr('MID("hello", 2, 3)') == "ell"


def test_mid_one_indexed():
    """start=1 returns from the beginning."""
    assert evalstr('MID("hello", 1, 2)') == "he"


def test_mid_n_larger_than_remaining():
    """n past the end returns what's available."""
    assert evalstr('MID("hello", 4, 99)') == "lo"


def test_mid_start_past_end():
    assert evalstr('MID("hello", 10, 3)') == ""


def test_mid_n_zero():
    assert evalstr('MID("hello", 2, 0)') == ""


def test_mid_start_zero_is_value():
    """start must be 1-indexed and >= 1."""
    assert evalstr('MID("hello", 0, 3)') == VALUE


def test_mid_negative_n_is_value():
    assert evalstr('MID("hello", 2, -1)') == VALUE


def test_mid_coerces_number_to_string():
    assert evalstr("MID(123456, 2, 3)") == "234"


def test_mid_arg_count_errors():
    assert evalstr('MID("a", 1)') == NA
    assert evalstr('MID("a", 1, 2, 3)') == NA
    assert evalstr('MID("a")') == NA


# =======================================================================
# Composition across batches
# =======================================================================


def test_iferror_with_sum():
    s = _fill(Sheet(), A1=10, A2=20)
    assert evalstr("IFERROR(SUM(A1:A2), 0)", s) == 30
    assert evalstr("IFERROR(1/0, SUM(A1:A2))", s) == 30


def test_iserror_inside_if():
    """ISERROR pairs naturally with IF — fallback pattern without IFERROR."""
    assert evalstr("IF(ISERROR(1/0), 99, 42)") == 99
    assert evalstr("IF(ISERROR(5), 99, 42)") == 42


def test_and_with_comparisons():
    s = _fill(Sheet(), A1=10, A2=20)
    assert evalstr("AND(A1 > 0, A2 > 0)", s) is True
    assert evalstr("AND(A1 > 0, A2 < 0)", s) is False


def test_concat_with_left_and_right():
    assert evalstr('CONCAT(LEFT("hello", 2), "_", RIGHT("world", 3))') == "he_rld"


def test_isnumber_in_if():
    s = _fill(Sheet(), A1=42, A2="text")
    assert evalstr('IF(ISNUMBER(A1), "num", "other")', s) == "num"
    assert evalstr('IF(ISNUMBER(A2), "num", "other")', s) == "other"


def test_len_of_concat():
    assert evalstr('LEN(CONCAT("foo", "bar"))') == 6


def test_mid_with_len():
    """Pick the middle character of a string."""
    s = _fill(Sheet(), A1="hello")
    # MID(A1, INT((LEN(A1)+1)/2), 1) — middle char of odd-length string
    assert evalstr("MID(A1, INT((LEN(A1)+1)/2), 1)", s) == "l"


def test_or_inside_iferror():
    assert evalstr("IFERROR(OR(1/0), FALSE)") is False


# =======================================================================
# Arg-count regression tests for #22 functions
# (was: positional params raised TypeError on misuse; now: returns #N/A)
# =======================================================================


def test_abs_wrong_arg_count():
    assert evalstr("ABS()") == NA
    assert evalstr("ABS(1, 2)") == NA


def test_round_wrong_arg_count():
    assert evalstr("ROUND()") == NA
    assert evalstr("ROUND(1)") == NA
    assert evalstr("ROUND(1, 2, 3)") == NA


def test_int_wrong_arg_count():
    assert evalstr("INT()") == NA
    assert evalstr("INT(1, 2)") == NA


def test_not_wrong_arg_count():
    assert evalstr("NOT()") == NA
    assert evalstr("NOT(TRUE, FALSE)") == NA
