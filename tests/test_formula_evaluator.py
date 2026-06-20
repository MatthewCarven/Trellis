"""Tests for trellis.formula.evaluator."""

import pytest

from trellis import Sheet
from trellis.formula import (
    DIV0, NAME, VALUE, Context, FormulaError, evaluate, parse_formula,
)
from trellis.formula.ast import (
    Bool, CellRef, Number, RangeRef, String,
)


def ctx(sheet=None):
    if sheet is None:
        sheet = Sheet("Test")
    return Context(sheet=sheet)


def evalstr(src, sheet=None):
    """Parse + evaluate in one shot."""
    return evaluate(parse_formula(src), ctx(sheet))


# --- Literals -----------------------------------------------------


def test_number_literal_int():
    assert evaluate(Number(42), ctx()) == 42


def test_number_literal_float():
    assert evaluate(Number(3.14), ctx()) == 3.14


def test_string_literal():
    assert evaluate(String("hello"), ctx()) == "hello"


def test_bool_true():
    assert evaluate(Bool(True), ctx()) is True


def test_bool_false():
    assert evaluate(Bool(False), ctx()) is False


# --- Cell references ---------------------------------------------


def test_cellref_returns_cell_value():
    s = Sheet()
    s["A1"] = 42
    assert evaluate(CellRef(0, 0), ctx(s)) == 42


def test_cellref_to_empty_returns_none():
    s = Sheet()
    assert evaluate(CellRef(0, 0), ctx(s)) is None


def test_cellref_string_value():
    s = Sheet()
    s["A1"] = "hello"
    assert evaluate(CellRef(0, 0), ctx(s)) == "hello"


# --- Range references --------------------------------------------


def test_rangeref_returns_flat_list():
    s = Sheet()
    s["A1"] = 1
    s["A2"] = 2
    s["A3"] = 3
    result = evaluate(RangeRef(CellRef(0, 0), CellRef(2, 0)), ctx(s))
    assert result == [1, 2, 3]


def test_rangeref_includes_none_for_empty_cells():
    s = Sheet()
    s["A1"] = 1
    s["A3"] = 3  # A2 deliberately empty
    result = evaluate(RangeRef(CellRef(0, 0), CellRef(2, 0)), ctx(s))
    assert result == [1, None, 3]


def test_rangeref_row_major():
    s = Sheet()
    s["A1"] = 1
    s["B1"] = 2
    s["A2"] = 3
    s["B2"] = 4
    result = evaluate(RangeRef(CellRef(0, 0), CellRef(1, 1)), ctx(s))
    assert result == [1, 2, 3, 4]


# --- Unary -------------------------------------------------------


def test_unary_minus():
    assert evalstr("-5") == -5


def test_unary_plus():
    assert evalstr("+5") == 5


def test_double_negative():
    assert evalstr("--5") == 5


def test_postfix_percent():
    assert evalstr("50%") == 0.5


def test_unary_on_empty_cell_treats_as_zero():
    s = Sheet()
    assert evalstr("-A1", s) == 0


def test_percent_on_cell():
    s = Sheet()
    s["A1"] = 25
    assert evalstr("A1%", s) == 0.25


# --- Binary arithmetic ------------------------------------------


def test_addition():
    assert evalstr("1+2") == 3


def test_subtraction():
    assert evalstr("5-3") == 2


def test_multiplication():
    assert evalstr("4*5") == 20


def test_division():
    assert evalstr("10/4") == 2.5


def test_division_by_zero_returns_div0():
    assert evalstr("1/0") == DIV0


def test_exponentiation():
    assert evalstr("2^10") == 1024


def test_precedence_in_evaluation():
    """1+2*3 -> 1 + (2*3) = 7."""
    assert evalstr("1+2*3") == 7


def test_parens_in_evaluation():
    assert evalstr("(1+2)*3") == 9


def test_right_assoc_caret():
    """2^3^2 -> 2^(3^2) = 2^9 = 512."""
    assert evalstr("2^3^2") == 512


# --- String concat (&) -----------------------------------------


def test_concat_strings():
    assert evalstr('"hello"&" "&"world"') == "hello world"


def test_concat_number_to_string():
    assert evalstr('"x="&5') == "x=5"


def test_concat_integer_float_no_trailing_dot_zero():
    s = Sheet()
    s["A1"] = 5.0
    assert evalstr('"x="&A1', s) == "x=5"


def test_concat_bool():
    assert evalstr('"x="&TRUE') == "x=TRUE"
    assert evalstr('"x="&FALSE') == "x=FALSE"


def test_concat_with_empty_cell():
    s = Sheet()
    s["A1"] = "hello"
    assert evalstr('A1&"x"', s) == "hellox"
    s2 = Sheet()
    assert evalstr('A1&"x"', s2) == "x"  # None -> ""


# --- Comparison -------------------------------------------------


def test_equal_true():
    assert evalstr("1=1") is True


def test_equal_false():
    assert evalstr("1=2") is False


def test_not_equal():
    assert evalstr("1<>2") is True
    assert evalstr("1<>1") is False


def test_less_than():
    assert evalstr("1<2") is True
    assert evalstr("2<1") is False


def test_greater_than():
    assert evalstr("2>1") is True


def test_le_ge():
    assert evalstr("1<=1") is True
    assert evalstr("1>=1") is True
    assert evalstr("2<=1") is False


def test_compare_bool_to_number():
    assert evalstr("TRUE=1") is True
    assert evalstr("FALSE=0") is True


def test_compare_empty_cell_to_zero_is_true():
    s = Sheet()
    assert evalstr("A1=0", s) is True


def test_compare_empty_cell_to_empty_string_is_true():
    """Empty cell vs string operand: coerces to ""."""
    s = Sheet()
    assert evalstr('A1=""', s) is True


def test_compare_strings_alphabetically():
    assert evalstr('"a"<"b"') is True


def test_compare_incompatible_types_returns_value():
    """5 < "x" -> VALUE (Excel says TRUE; we're strict for v1)."""
    result = evalstr('5<"x"')
    assert result == VALUE


# --- Empty-cell coercion --------------------------------------


def test_empty_cell_plus_one():
    s = Sheet()
    assert evalstr("A1+1", s) == 1


def test_two_empty_cells_sum_to_zero():
    s = Sheet()
    assert evalstr("A1+B1", s) == 0


def test_empty_cell_in_complex_expression():
    s = Sheet()
    s["B1"] = 10
    assert evalstr("A1+B1*2", s) == 20


# --- Bool coercion in arithmetic ------------------------------


def test_true_plus_one():
    assert evalstr("TRUE+1") == 2


def test_false_times_anything():
    assert evalstr("FALSE*100") == 0


def test_bool_in_division():
    assert evalstr("10/TRUE") == 10


# --- String in arithmetic returns VALUE -----------------------


def test_string_plus_number_returns_value():
    assert evalstr('"hello"+1') == VALUE


def test_string_unary_minus_returns_value():
    assert evalstr('-"hello"') == VALUE


# --- Error propagation ---------------------------------------


def test_error_propagates_through_arithmetic():
    """1/0 + 5 -> #DIV/0!."""
    assert evalstr("1/0+5") == DIV0


def test_error_propagates_through_concat():
    assert evalstr('"x"&(1/0)') == DIV0


def test_error_propagates_through_comparison():
    assert evalstr("1/0=5") == DIV0


def test_error_propagates_through_unary():
    assert evalstr("-(1/0)") == DIV0


def test_error_propagates_through_percent():
    assert evalstr("(1/0)%") == DIV0


def test_left_error_short_circuits():
    """When left is an error, right is never evaluated."""
    result = evalstr("nope()+1/0")
    assert result == NAME


# --- Ranges in scalar context return VALUE -------------------


def test_range_in_arithmetic_returns_value():
    s = Sheet()
    s["A1"] = 1
    s["A2"] = 2
    assert evalstr("A1:A2+5", s) == VALUE


def test_range_in_concat_returns_value():
    s = Sheet()
    s["A1"] = 1
    s["A2"] = 2
    assert evalstr('A1:A2&"x"', s) == VALUE


def test_range_alone_returns_list():
    s = Sheet()
    s["A1"] = 1
    s["A2"] = 2
    assert evalstr("A1:A2", s) == [1, 2]


# --- Function call returns NAME for unknown name --------------


def test_unknown_function_returns_name():
    """Function names not in the registry return NAME (using a never-
    going-to-be-a-builtin name so this stays correct after #22/#23)."""
    assert evalstr("NOSUCH()") == NAME


def test_unknown_function_returns_name_mentions_function():
    """Returned FormulaError should name which function (helps debugging)."""
    result = evalstr("NOSUCH()")
    assert isinstance(result, FormulaError)
    assert result == NAME
    assert "NOSUCH" in result.message


# --- Context dataclass ---------------------------------------


def test_context_default_current_cell_is_none():
    s = Sheet()
    c = Context(sheet=s)
    assert c.current_cell is None
    assert c.sheet is s


def test_context_with_current_cell():
    s = Sheet()
    c = Context(sheet=s, current_cell=(0, 0))
    assert c.current_cell == (0, 0)


def test_context_evaluate_method_works():
    """ctx.evaluate(node) is a thin wrapper around module-level evaluate."""
    s = Sheet()
    s["A1"] = 5
    c = Context(sheet=s)
    assert c.evaluate(CellRef(0, 0)) == 5


# --- Integration: parse + evaluate ---------------------------


def test_full_pipeline_simple_arithmetic():
    assert evalstr("1+2*3") == 7


def test_full_pipeline_with_cells():
    s = Sheet()
    s["A1"] = 10
    s["A2"] = 20
    s["A3"] = 30
    assert evalstr("A1+A2+A3", s) == 60


def test_full_pipeline_with_parens():
    s = Sheet()
    s["A1"] = 5
    s["B1"] = 3
    assert evalstr("(A1+B1)*2-1", s) == 15


def test_full_pipeline_leading_equals():
    s = Sheet()
    s["A1"] = 5
    assert evalstr("=A1*2", s) == 10


def test_full_pipeline_comparison():
    s = Sheet()
    s["A1"] = 100
    s["B1"] = 50
    assert evalstr("A1>B1", s) is True


def test_evaluate_never_raises_formulaerror():
    """The contract: evaluate always returns; never raises FormulaError."""
    for expr in ("1/0", '"x"+1', "nope()", "A1:A2+5"):
        sheet = Sheet()
        sheet["A1"] = 1
        sheet["A2"] = 2
        result = evaluate(parse_formula(expr), ctx(sheet))
        assert isinstance(result, FormulaError)


# --- Cross-sheet resolution (Part 12 row 4) --------------------------------


def test_cross_sheet_ref_resolves_via_workbook():
    from trellis import Workbook
    wb = Workbook()
    s1 = wb.add_sheet("Sheet1")
    s2 = wb.add_sheet("Sheet2")
    s2["A1"] = 99
    c = Context(sheet=s1, workbook=wb)
    assert evaluate(parse_formula("=Sheet2!A1"), c) == 99


def test_qualified_ref_unknown_sheet_is_name():
    from trellis import Workbook
    wb = Workbook()
    s1 = wb.add_sheet("Sheet1")
    c = Context(sheet=s1, workbook=wb)
    assert evaluate(parse_formula("=Ghost!A1"), c) == NAME


def test_qualified_ref_without_workbook_is_name():
    s = Sheet("Solo")
    c = Context(sheet=s)  # no workbook -> qualified ref cannot resolve
    assert evaluate(parse_formula("=Other!A1"), c) == NAME
