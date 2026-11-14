"""``results.xlsx``: every result table on its own sheet (in full, from the job's ``tables/``), a **Summary** sheet
(the job and its numbers) and a **Plot data** sheet (every plotted point). A table that doesn't fit Excel is written
as ``tables/NN_<title>.csv`` instead — never both."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from . import slug

XLSX_ROWS, XLSX_COLS = 1_048_576, 16_384


def _when(t) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else ""


def summary_rows(rec: dict) -> list[tuple]:
    rows = [("Job", rec.get("id"), ""), ("Tool", rec.get("tool_name"), ""), ("Title", rec.get("title"), ""),
            ("Run by", rec.get("user"), ""), ("Started", _when(rec.get("started") or rec.get("created")), ""),
            ("Finished", _when(rec.get("finished")), ""), ("Keyword", rec.get("keyword"), ""), ("Status", rec.get("status"), "")]
    rows = [r for r in rows if r[1] not in (None, "")]
    for o in rec.get("outputs") or []:
        if isinstance(o, dict) and o.get("kind") == "metric":
            raw = o.get("raw")
            rows.append((o.get("label") or "", raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else o.get("value"), o.get("unit") or ""))
    return rows


def _table_frame(o: dict, job_dir: Path):
    """(DataFrame or None, path of a .csv kept instead, complete?)"""
    import pandas as pd

    rel = o.get("file")
    path = (job_dir / rel) if rel else None
    if path and path.is_file():
        if path.suffix.lower() == ".csv":
            return None, path, True
        try:
            return pd.read_excel(path), None, True
        except Exception:
            pass
    cols = [str(c) for c in o.get("columns") or []]
    rows = o.get("rows") or []
    return pd.DataFrame(rows, columns=cols if rows and len(cols) == len(rows[0]) else None), None, len(rows) >= (o.get("total_rows") or 0)


def _values(v):
    """A trace's x / y as a list: plain lists as they are, plotly's compact arrays ({dtype, bdata[, shape]}) decoded.
    2-D arrays (heatmaps) are left out."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict) and isinstance(v.get("bdata"), str) and v.get("dtype"):
        import base64

        import numpy as np

        try:
            arr = np.frombuffer(base64.b64decode(v["bdata"]), dtype=np.dtype(v["dtype"]))
        except (ValueError, TypeError):
            return None
        if v.get("shape") and "," in str(v["shape"]):
            return None
        return arr.tolist()
    return None


def _plot_points(rec: dict):
    import pandas as pd

    rows = []
    for i, o in enumerate(rec.get("outputs") or []):
        if not (isinstance(o, dict) and o.get("kind") == "plot" and isinstance(o.get("figure"), dict)):
            continue
        plot = o.get("title") or f"Plot {i + 1}"
        for n, t in enumerate(o["figure"].get("data") or []):
            if not isinstance(t, dict):
                continue
            xs, ys = _values(t.get("x")), _values(t.get("y"))
            if ys is None:
                continue
            xs = xs if xs is not None and len(xs) == len(ys) else list(range(len(ys)))
            err = _values((t.get("error_y") or {}).get("array")) if isinstance(t.get("error_y"), dict) else None
            err = err if err is not None and len(err) == len(ys) else [None] * len(ys)
            name = t.get("name") or f"trace {n + 1}"
            rows += [(plot, name, x, y, e) for x, y, e in zip(xs, ys, err)]
            if len(rows) >= XLSX_ROWS - 1:
                break
    if not rows:
        return None
    df = pd.DataFrame(rows[: XLSX_ROWS - 1], columns=["Plot", "Trace", "x", "y", "± error"])
    return df if df["± error"].notna().any() else df.drop(columns="± error")


def write(rec: dict, job_dir: Path, dest: Path) -> dict[int, dict]:
    import pandas as pd

    from ..excel import write_table_workbook as write_workbook

    sheets = {"Summary": pd.DataFrame(summary_rows(rec), columns=["Item", "Value", "Unit"])}
    made: dict[int, dict] = {}
    used = {"Summary", "Plot data"}
    for i, o in enumerate(rec.get("outputs") or []):
        if not (isinstance(o, dict) and o.get("kind") == "table"):
            continue
        title = o.get("title") or f"Table {i + 1}"
        df, csv, complete = _table_frame(o, job_dir)
        if csv is None and df is not None and (len(df) + 1 > XLSX_ROWS or len(df.columns) > XLSX_COLS):
            csv = dest / "tables" / f"{i + 1:02d}_{slug(title)}.csv"
            csv.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(csv, index=False)
            df = None
        if csv is not None:
            target = dest / "tables" / f"{i + 1:02d}_{slug(title)}.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            if Path(csv).resolve() != target.resolve():
                shutil.copy2(csv, target)
            made[i] = {"title": title, "csv": target.relative_to(dest).as_posix(), "complete": True}
            continue
        name = "".join("_" if c in '[]:*?/\\' else c for c in title)[:31] or f"Table {i + 1}"
        n = 2
        while name in used:
            name = f"{name[:27]} ({n})"
            n += 1
        used.add(name)
        sheets[name] = df
        made[i] = {"title": title, "sheet": name, "complete": complete, "rows": int(len(df)), "total_rows": o.get("total_rows")}
    points = _plot_points(rec)
    if points is not None:
        sheets["Plot data"] = points
    write_workbook(dest / "results.xlsx", sheets)
    return made
