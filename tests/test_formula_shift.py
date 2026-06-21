"""Tests for trellis.formula.shift (Part 6 #3) and the error literals it emits.

The table-driven cases ARE the spec, in the render-table tradition: each row
is (source, rows, cols, expected).
"""

import pytest

from trellis import Workbook, shift_formula
from trellis.formula import REF, parse_formula
from trellis.formula.ast import Error, Number, BinaryOp
from trellis.formula.errors import ParseError
from trellis.formula.lexer import TokenKind, tokenize


# --- the shift table ----------------------------------------------------

CASES = [
    # identity: zero shift is byte-for-byte, whatever the spelling
    ("=A1*2", 0, 0, "=A1*2"),
    ("=sum( a1 ,B2 )", 0, 0, "=sum( a1 ,B2 )"),
    ("= $A$1 ", 0, 0, "= $A$1 "),
    # plain shifts
    ("=A1*2", 1, 0, "=A2*2"),
    ("=A1*2", 0, 1, "=B1*2"),
    ("=A1+B2", 2, 3, "=D3+E4"),
    ("A1", 1, 1, "B2"),                          # leading = optional
    # $ pins hold their axis
    ("=$A$1*2", 5, 5, "=$A$1*2"),
    ("=$A1", 2, 3, "=$A3"),
    ("=A$1", 2, 3, "=D$1"),
    ("=$A$1+A1", 1, 1, "=$A$1+B2"),
    # unmoved spelling survives; moved refs re-emit uppercase
    ("=$a$1+a1", 1, 1, "=$a$1+B2"),
    # formatting survives around moved refs
    ("= A1 + B2 ", 1, 0, "= A2 + B3 "),
    # function names are not refs, even ref-shaped ones; bare ref-shaped
    # idents ARE refs (mirrors the parser's call-vs-ref rule)
    ("=LOG10(A1)", 0, 1, "=LOG10(B1)"),
    ("=LOG10+1", 1, 0, "=LOG11+1"),
    # ranges shift per-corner; pins per-corner
    ("=SUM(A1:B2)", 1, 1, "=SUM(B2:C3)"),
    ("=SUM($A$1:B2)", 1, 1, "=SUM($A$1:C3)"),
    # off the edge: single ref becomes #REF!, range collapses whole
    ("=A1*2", -1, 0, "=#REF!*2"),
    ("=A1*2", 0, -1, "=#REF!*2"),
    ("=SUM(A1:B2)", -1, 0, "=SUM(#REF!)"),
    ("=SUM(A2:B3)", -1, 0, "=SUM(A1:B2)"),       # just barely on the sheet
    # pinned axis can't fall off via the shift (the pin holds it)
    ("=A$1+B1", -1, 0, "=A$1+#REF!"),
    # strings and numbers are never touched
    ('=IF(A1>1,"A1 literal",2)', 1, 1, '=IF(B2>1,"A1 literal",2)'),
    # broken-but-tokenizable: refs shift anyway (moving a broken formula)
    ("=SUM(A1", 0, 1, "=SUM(B1"),
    # untokenizable: returned unchanged, never raises
    ('="abc', 3, 3, '="abc'),
    # error literals pass through untouched
    ("=#REF!*2", 5, 5, "=#REF!*2"),
    ("=A1+#DIV/0!", 1, 0, "=A2+#DIV/0!"),
    # cross-sheet refs (Part 12 follow-up): the sheet qualifier stays put,
    # only the CELL shifts. A bare name like Sheet2 also reads as the A1
    # cell SHEET2 and must NOT be shifted as one.
    ("=Sheet2!A1", 1, 0, "=Sheet2!A2"),
    ("=Sheet2!A1", 0, 1, "=Sheet2!B1"),
    ("=Sheet2!A1", 2, 3, "=Sheet2!D3"),
    ("=Sheet2!A1+A1", 1, 0, "=Sheet2!A2+A2"),     # bare-name regression
    ("=Sheet2!A1+B2", 1, 0, "=Sheet2!A2+B3"),     # qualified + local mix
    ("='My Data'!A1", 1, 0, "='My Data'!A2"),     # quoted qualifier
    ("='My Data'!A1:B2", 1, 1, "='My Data'!B2:C3"),
    ("=SUM(Sheet2!A1:B2)", 1, 0, "=SUM(Sheet2!A2:B3)"),
    ("=Sheet2!$A$1", 5, 5, "=Sheet2!$A$1"),       # pins hold under a qualifier
    ("=Sheet2!A$1", 1, 1, "=Sheet2!B$1"),
    ("=Sheet2!A1", 0, 0, "=Sheet2!A1"),           # identity
    # off the edge: the WHOLE qualified ref collapses (sheet dropped) so it
    # evaluates to #REF!, not the #NAME? a bare Sheet2!#REF! would give.
    ("=Sheet2!A1", -1, 0, "=#REF!"),
    ("=SUM(Sheet2!A1:B2)", -5, 0, "=SUM(#REF!)"),
    ("=Data!A1", 1, 0, "=Data!A2"),               # non-ref name already safe
]


@pytest.mark.parametrize("src,rows,cols,expected", CASES)
def test_shift_table(src, rows, cols, expected):
    assert shift_formula(src, rows, cols) == expected


def test_shift_is_importable_from_everywhere():
    import trellis
    import trellis.formula
    from trellis.formula.shift import shift_formula as deep
    assert trellis.shift_formula is deep
    assert trellis.formula.shift_formula is deep


def test_shifted_formula_round_trips_through_the_engine():
    """The point of it all: shift, store, and the engine agrees."""
    wb = Workbook()
    sh = wb.add_sheet("S")
    sh["A1"] = 10
    sh["A2"] = 20
    sh["B1"] = "=A1*2"
    moved = shift_formula(sh["B1"].formula, 1, 0)
    sh["B2"] = moved
    assert sh["B2"].formula == "=A2*2"
    assert sh["B2"].value == 40
    sh["A2"] = 50
    assert sh["B2"].value == 100              # live dependency on the NEW ref


def test_cross_sheet_shift_does_not_corrupt_a_ref_shaped_sheet_name():
    """Regression (the flagged Part 12 gap): `Sheet2` parses as the A1 cell
    SHEET2, so a naive shift re-pointed `=Sheet2!A1` at SHEET3. The sheet
    qualifier must never be the thing that moves."""
    assert shift_formula("=Sheet2!A1", 1, 0) == "=Sheet2!A2"
    assert shift_formula("=Sheet2!A1", 0, 1) == "=Sheet2!B1"
    assert "SHEET3" not in shift_formula("=Sheet2!A1", 1, 0).upper()


def test_cross_sheet_shift_round_trips_through_the_engine():
    """Shift a cross-sheet formula, store it, and the engine agrees: a live
    dependency on the NEW cell, and an off-edge qualified ref reads #REF!."""
    wb = Workbook()
    s1 = wb.add_sheet("Sheet1")
    s2 = wb.add_sheet("Sheet2")
    s2["A1"] = 5
    s2["A2"] = 99
    s1["B1"] = shift_formula("=Sheet2!A1", 1, 0)   # -> =Sheet2!A2
    assert s1["B1"].formula == "=Sheet2!A2"
    assert s1["B1"].value == 99
    s2["A2"] = 7
    assert s1["B1"].value == 7                      # live on the shifted ref
    # off-edge collapses to a clean #REF! (sheet dropped), not #NAME?
    s1["C1"] = shift_formula("=Sheet2!A1", -1, 0)
    assert s1["C1"].formula == "=#REF!"
    assert s1["C1"].value == REF


# --- error literals (the #REF! that shift emits is first-class source) ---


def test_error_literal_lexes_as_one_token():
    toks = [(t.kind, t.value) for t in tokenize("#REF!")]
    assert toks == [(TokenKind.ERROR, "#REF!"), (TokenKind.EOF, "")]


@pytest.mark.parametrize(
    "code", ["#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#CIRC!", "#N/A", "#NULL!"]
)
def test_all_seven_codes_parse_as_error_nodes(code):
    assert parse_formula("=" + code) == Error(code)


def test_na_vs_name_longest_match():
    # "#N/A" and "#NAME?" share a prefix; each must lex as itself.
    assert parse_formula("#N/A") == Error("#N/A")
    assert parse_formula("#NAME?") == Error("#NAME?")


def test_unknown_error_literal_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_formula("=#BOGUS!")


def test_error_literal_evaluates_to_the_constant_and_propagates():
    wb = Workbook()
    sh = wb.add_sheet("S")
    sh["A1"] = "=#REF!*2"                     # what a shifted-off-edge paste stores
    assert sh["A1"].value == REF
    sh["B1"] = "=A1+1"
    assert sh["B1"].value == REF              # propagates like any error value
    assert sh["A1"].formula == "=#REF!*2"     # source preserved for F2


def test_error_literal_inside_larger_expression_parses():
    node = parse_formula("=1+#REF!")
    assert node == BinaryOp("+", Number(1), Error("#REF!"))


# --- rename_sheet_in_formula (Part 12 row 5) -------------------------------

from trellis.formula.shift import rename_sheet_in_formula


def test_rename_bare_sheet_qualifier():
    assert rename_sheet_in_formula("=Sheet2!A1", "Sheet2", "Renamed") == "=Renamed!A1"


def test_rename_preserves_rest_byte_for_byte():
    assert rename_sheet_in_formula("=Sheet2!A1 + B2*3", "Sheet2", "S3") == "=S3!A1 + B2*3"


def test_rename_in_range_and_function():
    assert rename_sheet_in_formula("=SUM(Data!A1:A3)", "Data", "Info") == "=SUM(Info!A1:A3)"


def test_rename_to_name_with_space_gets_quoted():
    assert rename_sheet_in_formula("=Data!A1", "Data", "My Data") == "='My Data'!A1"


def test_rename_from_quoted_name_to_bare():
    assert rename_sheet_in_formula("='My Data'!A1", "My Data", "Data") == "=Data!A1"


def test_rename_quoted_to_quoted_with_apostrophe():
    assert rename_sheet_in_formula("='My Data'!A1", "My Data", "O'Brien") == "='O''Brien'!A1"


def test_rename_only_the_matching_name():
    assert rename_sheet_in_formula("=Sheet2!A1 + Sheet3!B1", "Sheet2", "X") == "=X!A1 + Sheet3!B1"


def test_rename_ignores_string_literals_and_plain_cells():
    # "Data" is a string; Data! is a qualifier; A1 (no bang) is a plain cell.
    assert rename_sheet_in_formula('="Data" & Data!A1', "Data", "Info") == '="Data" & Info!A1'


def test_rename_no_match_is_identity():
    assert rename_sheet_in_formula("=A1 + B2", "Sheet2", "X") == "=A1 + B2"


def test_rename_untokenizable_returns_unchanged():
    assert rename_sheet_in_formula("=SUM(@", "Sheet2", "X") == "=SUM(@"
