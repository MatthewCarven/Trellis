"""CSV read and write for Trellis.

Read: :func:`read_csv` loads a CSV into a fresh :class:`Workbook` with a
single :class:`Sheet`. Cell values are inferred: empty cells become
``None``, numeric strings that round-trip exactly are parsed as ``int``
or ``float``, everything else stays a string. Booleans are NOT inferred
— ``"TRUE"``/``"true"``/``"True"`` is too ambiguous across data sources,
and Excel itself often quotes booleans as strings on CSV export. A
leading ``=`` is preserved as literal text; no surprise re-evaluation.

Write: :func:`write_csv` and the :meth:`trellis.Sheet.to_csv` method
write a single sheet to a CSV file. Each cell's ``value`` is written
(formulas are saved as their computed value, matching Excel's CSV
export). The bounding rectangle is determined by the maximum populated
row and column; trailing empty cells inside that rectangle are emitted
as empty fields, since CSV is rectangular.

Round-trip behaviour: a workbook with one sheet that contains only
strings, ints, floats, and ``None`` (= empty) round-trips losslessly.
Formulas do NOT round-trip — write emits the computed value, read
treats ``"=..."`` strings as literal text. By design.
"""

from __future__ import annotations

import csv as _csv
import math
from pathlib import Path
from typing import TYPE_CHECKING, Union

from ..core.workbook import Workbook

if TYPE_CHECKING:
    from ..core.sheet import Sheet


PathLike = Union[str, Path]

_INFINITES = (float("inf"), -float("inf"))


def _infer_value(s: str) -> int | float | str | None:
    """Infer a Python value from a CSV cell string.

    Empty string -> ``None``. Otherwise try ``int``, then ``float``,
    requiring that ``str(parsed) == s`` so that leading zeros, trailing
    zeros, scientific notation, and ``+`` signs are preserved as
    strings rather than silently normalised. NaN and infinities are
    also returned as strings (a CSV cell holding the literal text
    ``"nan"`` almost certainly didn't mean IEEE-754 NaN).

    Anything that doesn't parse is returned unchanged.
    """
    if s == "":
        return None

    # int first — exact round-trip required
    try:
        i = int(s)
        if str(i) == s:
            return i
    except (ValueError, TypeError):
        pass

    # float second — exact round-trip required, no NaN/inf
    try:
        f = float(s)
        if math.isnan(f) or f in _INFINITES:
            return s
        if str(f) == s:
            return f
    except (ValueError, TypeError):
        pass

    return s


def read_csv(
    path: PathLike,
    *,
    sheet_name: str = "Sheet1",
    encoding: str = "utf-8",
    dialect: str = "excel",
    workbook: Workbook | None = None,
) -> Workbook:
    """Load a CSV file into a Workbook.

    Each CSV row becomes a sheet row starting at A1. Values are inferred
    via :func:`_infer_value` (int → float → string; empty → ``None``).

    Parameters
    ----------
    path
        Filesystem path to read.
    sheet_name
        Name for the new sheet. Defaults to ``"Sheet1"``.
    encoding
        File encoding. Defaults to UTF-8. Pass ``"utf-8-sig"`` if the
        file was written by Excel with a BOM.
    dialect
        A :mod:`csv` dialect name. Defaults to ``"excel"`` (comma-
        separated, double-quote escaping).
    workbook
        If given, add the new sheet to this workbook and return it.
        Otherwise a fresh :class:`Workbook` is created.

    Returns
    -------
    Workbook
        The workbook containing the loaded sheet.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    """
    wb = workbook if workbook is not None else Workbook()
    sheet = wb.add_sheet(sheet_name)

    p = Path(path)
    with p.open("r", encoding=encoding, newline="") as f:
        reader = _csv.reader(f, dialect=dialect)
        # One batch for the whole load: a single sheet:batch event instead
        # of one cell:change per cell, and any formulas in the target
        # workbook that reference the loaded region recompute once on exit.
        with sheet.batch():
            for row_idx, row in enumerate(reader):
                for col_idx, raw in enumerate(row):
                    value = _infer_value(raw)
                    # Skip empty cells — they're already absent. Keeps the
                    # sparse dict sparse; ragged-right rows don't fill in
                    # phantom blanks.
                    if value is None:
                        continue
                    sheet.set((row_idx, col_idx), _make_cell(value))

    return wb


def _make_cell(value):
    """Build a plain value Cell for a loaded CSV field.

    Always a ``Cell(value=value)`` — never a formula, even when the text
    starts with ``=`` (the literal-text policy). Passing a Cell instance to
    ``sheet.set`` stores it as-is, bypassing the leading-``=`` formula
    sugar. read_csv writes these inside a single ``sheet.batch()`` so the
    whole load emits one ``sheet:batch`` event rather than one
    ``cell:change`` per cell.
    """
    from ..core.cell import Cell
    return Cell(value=value)


def write_csv(
    sheet: "Sheet",
    path: PathLike,
    *,
    encoding: str = "utf-8",
    dialect: str = "excel",
) -> None:
    """Write a sheet to a CSV file.

    The sheet's bounding rectangle is determined by the maximum row and
    column that contain a populated cell. All cells within that
    rectangle are emitted; cells with value ``None`` (or absent) become
    empty CSV fields. Formulas are written as their computed value
    (``cell.value``), not the formula text — this matches Excel's CSV
    export behaviour.

    Parameters
    ----------
    sheet
        The sheet to write.
    path
        Destination path. Overwrites if it exists.
    encoding
        File encoding. Defaults to UTF-8.
    dialect
        A :mod:`csv` dialect name. Defaults to ``"excel"``.
    """
    cells = sheet._cells
    if not cells:
        # Empty sheet writes an empty file. Could alternatively raise,
        # but "no content" is a legitimate state.
        Path(path).write_text("", encoding=encoding)
        return

    max_row = max(r for (r, _c) in cells)
    max_col = max(c for (_r, c) in cells)

    with Path(path).open("w", encoding=encoding, newline="") as f:
        writer = _csv.writer(f, dialect=dialect)
        for r in range(max_row + 1):
            row: list = []
            for c in range(max_col + 1):
                cell = cells.get((r, c))
                if cell is None or cell.value is None:
                    row.append("")
                else:
                    row.append(_stringify(cell.value))
            writer.writerow(row)


def _stringify(v) -> str:
    """Render a Trellis cell value for CSV output.

    Strings pass through. Numbers use ``str(...)`` — Python's default
    handles ints and floats sensibly. Booleans render as ``"True"`` /
    ``"False"`` (Python form, not Excel's uppercase). FormulaError
    values render as their error code string (``"#VALUE!"`` etc.)
    so the user sees the error in the exported CSV rather than a
    confusing repr.
    """
    # Import inside the function to keep the module-load cycle clean.
    from ..formula.errors import FormulaError

    if isinstance(v, FormulaError):
        return v.code
    if isinstance(v, str):
        return v
    return str(v)


__all__ = ["read_csv", "write_csv"]
