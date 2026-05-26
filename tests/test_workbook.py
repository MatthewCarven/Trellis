"""Tests for trellis.core.workbook.Workbook."""

import pytest

from trellis import Sheet, Workbook


def test_empty_workbook():
    wb = Workbook()
    assert len(wb) == 0
    assert list(wb) == []
    assert list(wb.sheets()) == []


def test_add_sheet_returns_the_new_sheet():
    wb = Workbook()
    s = wb.add_sheet("Data")
    assert isinstance(s, Sheet)
    assert s.name == "Data"
    assert wb["Data"] is s


def test_duplicate_name_raises():
    wb = Workbook()
    wb.add_sheet("A")
    with pytest.raises(ValueError):
        wb.add_sheet("A")


def test_add_existing_sheet_object():
    wb = Workbook()
    custom = Sheet("Custom")
    wb.add(custom)
    assert wb["Custom"] is custom


def test_add_existing_sheet_with_taken_name_raises():
    wb = Workbook()
    wb.add_sheet("A")
    with pytest.raises(ValueError):
        wb.add(Sheet("A"))


def test_remove_sheet():
    wb = Workbook()
    wb.add_sheet("A")
    wb.add_sheet("B")
    wb.remove_sheet("A")
    assert "A" not in wb
    assert "B" in wb
    assert len(wb) == 1


def test_remove_missing_sheet_raises():
    wb = Workbook()
    with pytest.raises(KeyError):
        wb.remove_sheet("Nope")


def test_rename_sheet_preserves_position():
    wb = Workbook()
    wb.add_sheet("A")
    wb.add_sheet("B")
    wb.add_sheet("C")
    wb.rename_sheet("B", "Z")
    assert list(wb) == ["A", "Z", "C"]
    assert wb["Z"].name == "Z"


def test_rename_into_existing_name_raises():
    wb = Workbook()
    wb.add_sheet("A")
    wb.add_sheet("B")
    with pytest.raises(ValueError):
        wb.rename_sheet("A", "B")


def test_iter_yields_names_in_insertion_order():
    wb = Workbook()
    wb.add_sheet("First")
    wb.add_sheet("Second")
    wb.add_sheet("Third")
    assert list(wb) == ["First", "Second", "Third"]


def test_sheets_yields_sheet_objects_in_order():
    wb = Workbook()
    a = wb.add_sheet("A")
    b = wb.add_sheet("B")
    assert list(wb.sheets()) == [a, b]


def test_meta_is_publicly_writable():
    wb = Workbook()
    wb.meta["author"] = "matthew"
    assert wb.meta["author"] == "matthew"


# --- event emission ---------------------------------------------------------


def test_workbook_emits_sheet_add():
    wb = Workbook()
    events = []
    wb.on("sheet:add", lambda sheet: events.append(sheet.name))
    wb.add_sheet("A")
    wb.add_sheet("B")
    assert events == ["A", "B"]


def test_workbook_emits_sheet_add_for_add_method():
    wb = Workbook()
    events = []
    wb.on("sheet:add", lambda sheet: events.append(sheet.name))
    wb.add(Sheet("Custom"))
    assert events == ["Custom"]


def test_workbook_emits_sheet_remove():
    wb = Workbook()
    wb.add_sheet("A")
    events = []
    wb.on("sheet:remove", lambda name, sheet: events.append((name, sheet.name)))
    wb.remove_sheet("A")
    assert events == [("A", "A")]


def test_workbook_emits_sheet_rename():
    wb = Workbook()
    a = wb.add_sheet("A")
    events = []
    wb.on("sheet:rename", lambda old, new, sheet: events.append((old, new, sheet is a)))
    wb.rename_sheet("A", "Z")
    assert events == [("A", "Z", True)]
    assert a.name == "Z"


def test_workbook_does_not_emit_on_failed_add():
    wb = Workbook()
    wb.add_sheet("A")
    events = []
    wb.on("sheet:add", lambda **kw: events.append(kw))
    with pytest.raises(ValueError):
        wb.add_sheet("A")
    assert events == []


def test_workbook_does_not_emit_on_failed_remove():
    wb = Workbook()
    events = []
    wb.on("sheet:remove", lambda **kw: events.append(kw))
    with pytest.raises(KeyError):
        wb.remove_sheet("Nope")
    assert events == []


def test_workbook_wildcard_subscription():
    wb = Workbook()
    events = []
    wb.on("*", lambda event, **kw: events.append(event))
    wb.add_sheet("A")
    wb.rename_sheet("A", "B")
    wb.remove_sheet("B")
    assert events == ["sheet:add", "sheet:rename", "sheet:remove"]
