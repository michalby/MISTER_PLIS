"""Write tidy, readable .xlsx files (bold header, frozen first row, sensible column widths).

Numbers follow the "Numbers in Excel files" setting: real numbers (Excel shows them with the
computer's own decimal separator) or text with a fixed dot / comma, which looks the same everywhere
but is text to Excel."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable

HEADER_FILL = "1D1F22"
_NUMBER_TEXT = re.compile(r"^-?\d+([.,]\d+)?(e[-+]?\d+)?$")


def _as_text(v: Any, mark: str) -> Any:
    """A float as text with ``mark`` as the decimal separator (whole numbers stay numbers)."""
    if hasattr(v, "item") and type(v).__module__ == "numpy":
        v = v.item()
    if not isinstance(v, float) or math.isnan(v) or math.isinf(v):
        return v
    if v.is_integer() and abs(v) < 1e15:
        return int(v)
    return f"{v:.15g}".replace(".", mark)


def _numbers_to_text(df, mark: str):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f" or df[c].dtype == object:
            df[c] = df[c].astype(object).map(lambda v: _as_text(v, mark))
    return df


def _style_sheet(ws, df) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    for row in ws.iter_rows(min_row=2):  # numbers written as text still line up on the right
        for cell in row:
            if cell.data_type == "s" and isinstance(cell.value, str) and _NUMBER_TEXT.match(cell.value):
                cell.alignment = Alignment(horizontal="right")
    for i, col in enumerate(df.columns, start=1):
        values = [str(col)] + [str(v) for v in df[col].head(200).tolist()]
        width = min(48, max(9, max(len(v) for v in values) + 2))
        ws.column_dimensions[get_column_letter(i)].width = width


def no_formulas(ws) -> None:
    """Text that starts with "=" stays text: a sample name someone typed as ``=HYPERLINK(…)`` must not become a formula
    when the workbook is opened (docs/SECURITY_AUDIT.md L2)."""
    for row in ws.iter_rows():
        for cell in row:
            if cell.data_type == "f":
                cell.data_type = "s"


def csv_safe(df):
    """A copy of ``df`` for a CSV file someone opens in Excel: text Excel would read as a formula starts with ' —
    "=…", "@…", and "+…" / "-…" with a formula's signs in it ("-2+3+cmd|' /C calc'!A0"). Plain values such as "-5",
    "-80 °C" or "-" stay as they are."""
    import re

    def cell(v):
        if isinstance(v, str) and (v.startswith(("=", "@", "\t", "\r"))
                                   or v.startswith(("+", "-")) and re.search(r"[(!|=;]", v)):
            return "'" + v
        return v

    import pandas as pd

    df = df.copy()
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]):
            df[c] = df[c].astype(object).map(cell)
    return df


def write_workbook(path: str | Path, sheets: dict, notes: Iterable[tuple] | None = None) -> Path:
    """``sheets`` maps sheet name → DataFrame. ``notes`` adds a "Method" sheet of (label, value) rows."""
    return _write_workbook(path, sheets, notes)


def write_table_workbook(path: str | Path, sheets: dict, notes: Iterable[tuple] | None = None) -> Path:
    """:func:`write_workbook` for the base's own exports of results (tables, backups): what people typed is in them,
    so no text becomes a formula. (A tool's own :func:`write_workbook` keeps formulas, as it always has.)"""
    return _write_workbook(path, sheets, notes, formulas=False)


def _write_workbook(path: str | Path, sheets: dict, notes: Iterable[tuple] | None = None, formulas: bool = True) -> Path:
    import pandas as pd

    from .prefs import pref

    if pref("xlsx_numbers") in ("dot", "comma"):
        mark = "," if pref("xlsx_numbers") == "comma" else "."
        sheets = {k: _numbers_to_text(v, mark) for k, v in sheets.items()}
        notes = [tuple(_as_text(x, mark) for x in r) for r in notes] if notes else notes

    path = Path(path)
    used = set()
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            safe = "".join("_" if c in '[]:*?/\\' else c for c in str(name))[:31] or "Sheet"
            n = 2
            while safe in used:
                safe = f"{safe[:28]}_{n}"
                n += 1
            used.add(safe)
            df.to_excel(xw, sheet_name=safe, index=False)
            _style_sheet(xw.sheets[safe], df)
            if not formulas:
                no_formulas(xw.sheets[safe])
        if notes:
            from openpyxl.styles import Font

            ws = xw.book.create_sheet("Method")
            for row in notes:
                ws.append([str(row[0]), *row[1:]])
            for c in ws["A"]:
                c.font = Font(bold=True)
            ws.column_dimensions["A"].width = 42
            ws.column_dimensions["B"].width = 60
            if not formulas:
                no_formulas(ws)
    return path
