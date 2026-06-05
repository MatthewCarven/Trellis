"""Tier 1 — hermetic unit tests for trellis-mathpack's scalar functions.

Run without installing:  PYTHONPATH=../../src:src python -m pytest tests/

mathpack is NOT installed here, so ``import trellis`` does not auto-load it
(its entry point isn't on the metadata path). We call ``setup()`` once to
register the functions, then drive formulas through the real parser ->
evaluator stack, exactly like core's ``tests/test_formula_builtins.py``.

Covers Part 4 #3 (the 17 scalar functions). Range stats land in #4.
"""

from __future__ import annotations

import math

import pytest

from trellis import Sheet, Workbook
from trellis.formula import Context, FormulaError, evaluate, parse_formula
from trellis.formula.functions import _REGISTRY

import trellis_mathpack


@pytest.fixture(autouse=True)
def registered():
    """Register mathpack into a snapshot of the registry; restore after."""
    saved = dict(_REGISTRY)
    trellis_mathpack.setup()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


def ev(src: str):
    return evaluate(parse_formula(src), Context(sheet=Sheet("T")))


def ev_on(sheet, src: str):
    return evaluate(parse_formula(src), Context(sheet=sheet))


def approx(x):
    return pytest.approx(x, rel=1e-12, abs=1e-12)


# --- Registration -------------------------------------------------------

def test_setup_registers_all_17_scalar_names():
    from trellis.formula import registered_function_names

    names = set(registered_function_names())
    expected = {
        "SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN",
        "SINH", "COSH", "TANH",
        "SQRT", "POWER", "EXP", "LN", "LOG",
        "MOD", "SIGN", "PI",
    }
    assert expected <= names


def test_mathpack_overrides_no_builtins():
    """Every mathpack name must be new — none may collide with a built-in."""
    builtins = {
        "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "ROUND", "INT", "ABS",
        "IF", "IFERROR", "AND", "OR", "NOT", "CONCAT", "LEFT", "RIGHT",
        "MID", "LEN", "ISBLANK", "ISERROR", "ISNUMBER", "ISTEXT",
        "TRUE", "FALSE",
    }
    mathpack = set(trellis_mathpack._UNARY_MATH) | set(trellis_mathpack._SPECIAL)
    assert builtins.isdisjoint(mathpack)


# --- Trig (radians) -----------------------------------------------------

def test_trig_happy():
    assert ev("SIN(0)") == approx(0.0)
    assert ev("COS(0)") == approx(1.0)
    assert ev("TAN(0)") == approx(0.0)
    assert ev("SIN(PI()/2)") == approx(1.0)
    assert ev("ASIN(1)") == approx(math.pi / 2)
    assert ev("ACOS(1)") == approx(0.0)
    assert ev("ATAN(1)") == approx(math.pi / 4)


def test_asin_acos_domain_is_num():
    assert ev("ASIN(2)") == FormulaError("#NUM!")
    assert ev("ASIN(-2)") == FormulaError("#NUM!")
    assert ev("ACOS(2)") == FormulaError("#NUM!")


# --- Hyperbolic ---------------------------------------------------------

def test_hyperbolic_happy():
    assert ev("SINH(0)") == approx(0.0)
    assert ev("COSH(0)") == approx(1.0)   # the worked-example formula
    assert ev("TANH(0)") == approx(0.0)


# --- Powers / logs ------------------------------------------------------

def test_sqrt():
    assert ev("SQRT(4)") == approx(2.0)
    assert ev("SQRT(0)") == approx(0.0)
    assert ev("SQRT(-1)") == FormulaError("#NUM!")


def test_power():
    assert ev("POWER(2,10)") == approx(1024.0)
    assert ev("POWER(9,0.5)") == approx(3.0)
    assert ev("POWER(2,-1)") == approx(0.5)
    assert ev("POWER(-2,0.5)") == FormulaError("#NUM!")


def test_exp_and_ln():
    assert ev("EXP(0)") == approx(1.0)
    assert ev("EXP(1)") == approx(math.e)
    assert ev("LN(1)") == approx(0.0)
    assert ev("LN(EXP(1))") == approx(1.0)
    assert ev("LN(0)") == FormulaError("#NUM!")
    assert ev("LN(-1)") == FormulaError("#NUM!")
    assert ev("EXP(1000)") == FormulaError("#NUM!")  # overflow


def test_log():
    assert ev("LOG(100)") == approx(2.0)        # default base 10
    assert ev("LOG(8,2)") == approx(3.0)
    assert ev("LOG(0)") == FormulaError("#NUM!")
    assert ev("LOG(8,1)") == FormulaError("#NUM!")   # base 1 invalid
    assert ev("LOG(8,-2)") == FormulaError("#NUM!")  # base <= 0 invalid


# --- Misc ---------------------------------------------------------------

def test_mod():
    assert ev("MOD(7,3)") == approx(1)
    assert ev("MOD(-7,3)") == approx(2)    # sign of divisor (Excel/Python agree)
    assert ev("MOD(7,-3)") == approx(-2)
    assert ev("MOD(7,0)") == FormulaError("#DIV/0!")  # core error, not #NUM!


def test_sign():
    assert ev("SIGN(-5)") == -1
    assert ev("SIGN(0)") == 0
    assert ev("SIGN(3.2)") == 1


def test_pi():
    assert ev("PI()") == approx(math.pi)


# --- Cross-cutting: type guard + arg counts -----------------------------

def test_bool_arg_is_value_error():
    # mathpack treats bools as non-numbers (stricter than core arithmetic).
    # Feed a real Python bool in via a cell (TRUE/FALSE are literals, not fns).
    s = Sheet("T")
    s["A1"] = True
    s["A2"] = False
    assert evaluate(parse_formula("SIN(A1)"), Context(sheet=s)) == FormulaError("#VALUE!")
    assert evaluate(parse_formula("SQRT(A2)"), Context(sheet=s)) == FormulaError("#VALUE!")


def test_string_arg_is_value_error():
    assert ev('SQRT("x")') == FormulaError("#VALUE!")


def test_error_arg_propagates():
    # SQRT(-1) -> #NUM!, fed into SIN -> the dispatcher short-circuits it.
    assert ev("SIN(SQRT(-1))") == FormulaError("#NUM!")


def test_wrong_arg_count_is_na():
    assert ev("SIN()") == FormulaError("#N/A")
    assert ev("SIN(1,2)") == FormulaError("#N/A")
    assert ev("POWER(2)") == FormulaError("#N/A")
    assert ev("PI(1)") == FormulaError("#N/A")
    assert ev("LOG(1,2,3)") == FormulaError("#N/A")


def test_empty_cell_arg_is_zero():
    # An empty referenced cell -> None -> 0 (Excel empty-cell semantics).
    s = Sheet("T")
    out = evaluate(parse_formula("COS(A1)"), Context(sheet=s))
    assert out == approx(1.0)   # COS(0) == 1


# =======================================================================
# Range-aware statistics (Part 4 #4): STDEV / VAR / MEDIAN
# =======================================================================

def test_stats_registered():
    from trellis.formula import registered_function_names

    assert {"STDEV", "VAR", "MEDIAN"} <= set(registered_function_names())


def test_stats_happy_over_a_range():
    s = Sheet("T")
    for i, v in enumerate([2, 4, 4, 4, 5, 5, 7, 9], 1):
        s[f"A{i}"] = v
    assert ev_on(s, "STDEV(A1:A8)") == approx(2.138089935299395)
    assert ev_on(s, "VAR(A1:A8)") == approx(4.571428571428571)
    assert ev_on(s, "MEDIAN(A1:A8)") == approx(4.5)


def test_stats_mixed_scalars_and_ranges():
    s = Sheet("T")
    s["A1"] = 1
    s["A2"] = 2
    # range A1:A2 == [1, 2], plus scalars 3, 4
    assert ev_on(s, "MEDIAN(A1:A2,3,4)") == approx(2.5)
    assert ev_on(s, "VAR(A1:A2,3,4)") == approx(pytest.approx(1.6666666666666667))


def test_stdev_var_need_two_points():
    assert ev("STDEV(5)") == FormulaError("#DIV/0!")
    assert ev("VAR(5)") == FormulaError("#DIV/0!")
    assert ev("STDEV()") == FormulaError("#DIV/0!")
    assert ev("VAR()") == FormulaError("#DIV/0!")


def test_median_needs_one_point():
    assert ev("MEDIAN(5)") == approx(5)
    assert ev("MEDIAN(1,2)") == approx(1.5)
    assert ev("MEDIAN()") == FormulaError("#DIV/0!")


def test_range_skips_text_bool_and_blanks():
    # Excel rule: STDEV/MEDIAN ignore text, logicals, and blanks inside a range.
    s = Sheet("T")
    s["A1"] = 2
    s["A2"] = "x"     # text -> skipped
    s["A3"] = 4
    s["A4"] = True    # logical -> skipped
    # A5 left blank -> skipped
    assert ev_on(s, "MEDIAN(A1:A5)") == approx(3.0)
    assert ev_on(s, "VAR(A1:A5)") == approx(2.0)  # variance of [2, 4]


def test_scalar_non_number_in_stats_is_value_error():
    assert ev('MEDIAN(1, "x", 3)') == FormulaError("#VALUE!")


def test_error_in_range_propagates_through_stats():
    # Needs a Workbook so the formula cell actually evaluates to #NUM!.
    wb = Workbook()
    s = wb.add_sheet("V")
    s["A1"] = 1
    s["A2"] = "=SQRT(-1)"   # -> #NUM!
    assert s["A2"].value == FormulaError("#NUM!")
    assert ev_on(s, "STDEV(A1:A2)") == FormulaError("#NUM!")


def test_collect_numerics_helper_directly():
    from trellis_mathpack import _collect_numerics

    # error anywhere propagates
    assert _collect_numerics([[1, FormulaError("#NUM!")]]) == FormulaError("#NUM!")
    assert _collect_numerics([FormulaError("#REF!"), 1]) == FormulaError("#REF!")
    # inside a range: bool / None / text skipped; numbers kept
    assert _collect_numerics([[1, True, None, "x", 2]]) == [1, 2]
    # scalar rules: None -> 0, bool -> VALUE, text -> VALUE
    assert _collect_numerics([1, None, 2]) == [1, 0, 2]
    assert _collect_numerics([1, True]) == FormulaError("#VALUE!")
    assert _collect_numerics([1, "x"]) == FormulaError("#VALUE!")
