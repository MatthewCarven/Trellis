"""Tests for trellis.io.csv — CSV read and write (task #4)."""

from __future__ import annotations

import math

import pytest

from trellis import (
    FormulaError,
    Sheet,
    VALUE,
    Workbook,
    read_csv,
)
from trellis.io.csv import _infer_value, write_csv


# ---------------------------------------------------------------------
# _infer_value: the type-inference rule
# ---------------------------------------------------------------------


class TestInferValue:
    def test_empty_is_none(self):
        assert _infer_value("") is None

    def test_int(self):
        assert _infer_value("42") == 42
        assert isinstance(_infer_value("42"), int)

    def test_negative_int(self):
        assert _infer_value("-7") == -7

    def test_zero(self):
        assert _infer_value("0") == 0

    def test_float(self):
        assert _infer_value("3.14") == 3.14
        assert isinstance(_infer_value("3.14"), float)

    def test_negative_float(self):
        assert _infer_value("-0.5") == -0.5

    def test_float_with_explicit_zero_decimal(self):
        # str(1.0) == "1.0", round-trip succeeds, parsed as float.
        assert _infer_value("1.0") == 1.0
        assert isinstance(_infer_value("1.0"), float)

    def test_plain_string(self):
        assert _infer_value("hello") == "hello"

    def test_leading_zero_preserved_as_string(self):
        # str(int("01234")) == "1234" != "01234" — round-trip fails, stays string.
        # This protects ZIP codes, phone numbers, ID codes.
        assert _infer_value("01234") == "01234"

    def test_plus_sign_preserved_as_string(self):
        # str(int("+42")) == "42" != "+42" — round-trip fails.
        assert _infer_value("+42") == "+42"

    def test_whitespace_preserved_as_string(self):
        # int(" 42 ") parses to 42, but the original has whitespace.
        # Round-trip rule keeps it as a string.
        assert _infer_value(" 42 ") == " 42 "

    def test_scientific_notation_preserved_as_string(self):
        # float("1e5") == 100000.0; str(100000.0) == "100000.0" != "1e5".
        assert _infer_value("1e5") == "1e5"

    def test_trailing_zero_in_float_preserved(self):
        # float("3.140") == 3.14; str(3.14) == "3.14" != "3.140".
        # Round-trip fails, preserve as string. (Significant figures matter.)
        assert _infer_value("3.140") == "3.140"

    def test_nan_string_stays_string(self):
        # float("nan") parses, but we explicitly reject NaN.
        result = _infer_value("nan")
        assert isinstance(result, str)
        assert result == "nan"

    def test_inf_string_stays_string(self):
        assert _infer_value("inf") == "inf"
        assert _infer_value("-inf") == "-inf"

    def test_booleans_not_inferred(self):
        # Avoiding the TRUE/true/True ambiguity.
        assert _infer_value("TRUE") == "TRUE"
        assert _infer_value("true") == "true"
        assert _infer_value("True") == "True"
        assert _infer_value("FALSE") == "FALSE"

    def test_formula_text_preserved_as_string(self):
        # Critical: a leading "=" must NOT make this a formula on load.
        assert _infer_value("=SUM(A1:A2)") == "=SUM(A1:A2)"
        assert _infer_value("=A1+1") == "=A1+1"

    def test_currency_string_stays_string(self):
        assert _infer_value("$1,234") == "$1,234"

    def test_date_string_stays_string(self):
        # No date parsing — Trellis doesn't have a date type yet.
        assert _infer_value("2026-05-27") == "2026-05-27"


# ---------------------------------------------------------------------
# read_csv: load path
# ---------------------------------------------------------------------


class TestReadCSV:
    def test_basic_read(self, tmp_path):
        p = tmp_path / "basic.csv"
        p.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")
        wb = read_csv(p)
        sh = wb["Sheet1"]
        assert sh["A1"].value == "name"
        assert sh["B1"].value == "age"
        assert sh["A2"].value == "Alice"
        assert sh["B2"].value == 30
        assert sh["A3"].value == "Bob"
        assert sh["B3"].value == 25

    def test_returns_workbook(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text("a\n", encoding="utf-8")
        wb = read_csv(p)
        assert isinstance(wb, Workbook)

    def test_default_sheet_name(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text("a\n", encoding="utf-8")
        wb = read_csv(p)
        assert "Sheet1" in wb

    def test_custom_sheet_name(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text("a\n", encoding="utf-8")
        wb = read_csv(p, sheet_name="MyData")
        assert "MyData" in wb
        assert "Sheet1" not in wb

    def test_into_existing_workbook(self, tmp_path):
        wb = Workbook()
        wb.add_sheet("Existing")
        p = tmp_path / "x.csv"
        p.write_text("a\n", encoding="utf-8")
        out = read_csv(p, sheet_name="Loaded", workbook=wb)
        assert out is wb
        assert "Existing" in wb
        assert "Loaded" in wb

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_csv(tmp_path / "nope.csv")

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        wb = read_csv(p)
        sh = wb["Sheet1"]
        assert len(sh) == 0

    def test_empty_cells_become_absent(self, tmp_path):
        p = tmp_path / "blanks.csv"
        p.write_text("a,,c\n", encoding="utf-8")
        wb = read_csv(p)
        sh = wb["Sheet1"]
        assert sh["A1"].value == "a"
        # B1 is empty — should NOT be in the sparse cell dict.
        assert (0, 1) not in sh._cells
        assert sh["C1"].value == "c"

    def test_ragged_rows(self, tmp_path):
        p = tmp_path / "ragged.csv"
        p.write_text("a,b,c\nd,e\nf\n", encoding="utf-8")
        wb = read_csv(p)
        sh = wb["Sheet1"]
        assert sh["A1"].value == "a"
        assert sh["C1"].value == "c"
        assert sh["A2"].value == "d"
        assert sh["B2"].value == "e"
        assert (1, 2) not in sh._cells  # row 2 has no C value
        assert sh["A3"].value == "f"

    def test_quoted_string_with_comma(self, tmp_path):
        p = tmp_path / "q.csv"
        p.write_text('"Smith, John",42\n', encoding="utf-8")
        wb = read_csv(p)
        sh = wb["Sheet1"]
        assert sh["A1"].value == "Smith, John"
        assert sh["B1"].value == 42

    def test_utf8_bom_with_utf8_sig(self, tmp_path):
        p = tmp_path / "bom.csv"
        # Excel often writes UTF-8 BOM.
        p.write_bytes("﻿name,age\nAlice,30\n".encode("utf-8"))
        wb = read_csv(p, encoding="utf-8-sig")
        sh = wb["Sheet1"]
        assert sh["A1"].value == "name"  # BOM stripped

    def test_formula_text_stored_literally_not_evaluated(self, tmp_path):
        """CRITICAL: leading-= text loads as string, NOT as a formula."""
        p = tmp_path / "eq.csv"
        p.write_text("=SUM(1+1),plain\n", encoding="utf-8")
        wb = read_csv(p)
        sh = wb["Sheet1"]
        cell = sh["A1"]
        assert cell.value == "=SUM(1+1)"
        # If it had been treated as a formula, value would be 2 and
        # cell.formula would be the string. Confirm formula is None.
        assert cell.formula is None

    def test_mixed_types_in_column(self, tmp_path):
        p = tmp_path / "mixed.csv"
        p.write_text("42\nhello\n3.14\n\n", encoding="utf-8")
        wb = read_csv(p)
        sh = wb["Sheet1"]
        assert sh["A1"].value == 42
        assert sh["A2"].value == "hello"
        assert sh["A3"].value == 3.14
        # Row 4 is blank — no cell stored.
        assert (3, 0) not in sh._cells


# ---------------------------------------------------------------------
# write_csv / Sheet.to_csv: save path
# ---------------------------------------------------------------------


class TestWriteCSV:
    def test_basic_write(self, tmp_path):
        wb = Workbook()
        sh = wb.add_sheet("Out")
        sh["A1"] = "name"
        sh["B1"] = "age"
        sh["A2"] = "Alice"
        sh["B2"] = 30
        out = tmp_path / "out.csv"
        sh.to_csv(out)
        text = out.read_text(encoding="utf-8")
        # csv module uses \r\n by default; normalize for comparison.
        lines = text.splitlines()
        assert lines == ["name,age", "Alice,30"]

    def test_method_form_matches_function_form(self, tmp_path):
        wb = Workbook()
        sh = wb.add_sheet("S")
        sh["A1"] = 1
        sh["B1"] = 2
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        sh.to_csv(a)
        write_csv(sh, b)
        assert a.read_bytes() == b.read_bytes()

    def test_empty_sheet_writes_empty_file(self, tmp_path):
        sh = Sheet("E")
        out = tmp_path / "e.csv"
        sh.to_csv(out)
        assert out.read_text(encoding="utf-8") == ""

    def test_bounding_rectangle_fills_internal_blanks(self, tmp_path):
        # A1 and C1 populated, B1 empty — output row is "a,,c".
        sh = Sheet("S")
        sh["A1"] = "a"
        sh["C1"] = "c"
        out = tmp_path / "s.csv"
        sh.to_csv(out)
        assert out.read_text(encoding="utf-8").splitlines() == ["a,,c"]

    def test_bounding_rectangle_pads_short_rows(self, tmp_path):
        # A1=a, B1=b, A2=d. C1 is empty. Row 2 should be padded to "d,".
        sh = Sheet("S")
        sh["A1"] = "a"
        sh["B1"] = "b"
        sh["A2"] = "d"
        out = tmp_path / "s.csv"
        sh.to_csv(out)
        assert out.read_text(encoding="utf-8").splitlines() == ["a,b", "d,"]

    def test_none_cell_writes_empty(self, tmp_path):
        sh = Sheet("S")
        sh["A1"] = "a"
        sh["B1"] = None
        sh["C1"] = "c"
        out = tmp_path / "n.csv"
        sh.to_csv(out)
        assert out.read_text(encoding="utf-8").splitlines() == ["a,,c"]

    def test_formula_writes_computed_value(self, tmp_path):
        wb = Workbook()
        sh = wb.add_sheet("F")
        sh["A1"] = 10
        sh["A2"] = 20
        sh["B1"] = "=SUM(A1:A2)"
        # Recalc made B1.value == 30.
        out = tmp_path / "f.csv"
        sh.to_csv(out)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines == ["10,30", "20,"]

    def test_formula_error_writes_error_code(self, tmp_path):
        wb = Workbook()
        sh = wb.add_sheet("E")
        sh["A1"] = "=1/0"
        out = tmp_path / "e.csv"
        sh.to_csv(out)
        text = out.read_text(encoding="utf-8")
        assert "#DIV/0!" in text

    def test_quoting_for_commas_in_values(self, tmp_path):
        sh = Sheet("S")
        sh["A1"] = "Smith, John"
        sh["B1"] = 42
        out = tmp_path / "q.csv"
        sh.to_csv(out)
        text = out.read_text(encoding="utf-8")
        # csv module should quote the comma-containing string.
        assert '"Smith, John"' in text

    def test_quoting_for_newlines_in_values(self, tmp_path):
        sh = Sheet("S")
        sh["A1"] = "line1\nline2"
        out = tmp_path / "n.csv"
        sh.to_csv(out)
        # Should be quoted and the embedded newline preserved.
        text = out.read_text(encoding="utf-8")
        assert '"line1\nline2"' in text

    def test_overwrites_existing_file(self, tmp_path):
        sh = Sheet("S")
        sh["A1"] = "new"
        out = tmp_path / "ow.csv"
        out.write_text("old content here", encoding="utf-8")
        sh.to_csv(out)
        assert out.read_text(encoding="utf-8").strip() == "new"


# ---------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------


class TestRoundTrip:
    def test_strings_round_trip(self, tmp_path):
        wb = Workbook()
        sh = wb.add_sheet("RT")
        sh["A1"] = "alpha"
        sh["B1"] = "beta"
        sh["A2"] = "gamma"
        out = tmp_path / "rt.csv"
        sh.to_csv(out)
        wb2 = read_csv(out)
        sh2 = wb2["Sheet1"]
        assert sh2["A1"].value == "alpha"
        assert sh2["B1"].value == "beta"
        assert sh2["A2"].value == "gamma"

    def test_ints_round_trip(self, tmp_path):
        wb = Workbook()
        sh = wb.add_sheet("RT")
        sh["A1"] = 1
        sh["A2"] = 100
        sh["A3"] = -42
        out = tmp_path / "rt.csv"
        sh.to_csv(out)
        sh2 = read_csv(out)["Sheet1"]
        assert sh2["A1"].value == 1
        assert sh2["A2"].value == 100
        assert sh2["A3"].value == -42
        assert all(isinstance(sh2[a].value, int) for a in ("A1", "A2", "A3"))

    def test_floats_round_trip(self, tmp_path):
        wb = Workbook()
        sh = wb.add_sheet("RT")
        sh["A1"] = 3.14
        sh["A2"] = -0.5
        sh["A3"] = 1.0
        out = tmp_path / "rt.csv"
        sh.to_csv(out)
        sh2 = read_csv(out)["Sheet1"]
        assert sh2["A1"].value == 3.14
        assert sh2["A2"].value == -0.5
        assert sh2["A3"].value == 1.0
        assert isinstance(sh2["A3"].value, float)

    def test_empty_cells_round_trip(self, tmp_path):
        wb = Workbook()
        sh = wb.add_sheet("RT")
        sh["A1"] = "x"
        sh["C1"] = "z"
        out = tmp_path / "rt.csv"
        sh.to_csv(out)
        sh2 = read_csv(out)["Sheet1"]
        assert sh2["A1"].value == "x"
        assert (0, 1) not in sh2._cells  # B1 stays sparse
        assert sh2["C1"].value == "z"

    def test_formulas_become_values_after_round_trip(self, tmp_path):
        """Documents the intentional lossiness — formulas don't survive."""
        wb = Workbook()
        sh = wb.add_sheet("F")
        sh["A1"] = 10
        sh["A2"] = 20
        sh["B1"] = "=SUM(A1:A2)"  # computes to 30
        out = tmp_path / "f.csv"
        sh.to_csv(out)
        sh2 = read_csv(out)["Sheet1"]
        # B1 is now an int, not a formula.
        assert sh2["B1"].value == 30
        assert sh2["B1"].formula is None


def test_read_csv_emits_single_sheet_batch(tmp_path):
    """The read_csv -> Sheet.batch refactor: one sheet:batch for the whole load."""
    from trellis import Workbook, read_csv

    p = tmp_path / "data.csv"
    p.write_text("1,2,3\n4,5,6\n", encoding="utf-8")

    wb = Workbook()
    seen = []
    # Subscribe before the sheet exists by watching sheet:add, then attach.
    wb.on("sheet:add", lambda sheet: sheet.on("sheet:batch", lambda **ev: seen.append(ev)))
    read_csv(p, workbook=wb)

    assert len(seen) == 1
    assert len(seen[0]["changes"]) == 6   # six populated cells


def test_read_csv_leading_equals_stays_literal_after_refactor(tmp_path):
    """The batch refactor must preserve the literal-text policy for '='."""
    from trellis import read_csv

    p = tmp_path / "f.csv"
    p.write_text("=A1+1,hi\n", encoding="utf-8")
    wb = read_csv(p)
    sh = wb["Sheet1"]
    assert sh["A1"].value == "=A1+1"   # stored as text
    assert sh["A1"].formula is None    # NOT a formula
