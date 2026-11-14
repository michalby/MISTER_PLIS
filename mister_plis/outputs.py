"""Results a tool can return. Each is turned into JSON for the browser."""

from __future__ import annotations

import functools
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .i18n import exact, tr, tr_text
from .prefs import decimal_mark

UrlFor = Callable[[Path], str]  # turns a file path into a download URL
SaveBytes = Callable[[str, bytes], Path]  # stores bytes as an output file


def fmt(value: Any, sig: int = 4) -> str:
    """Format a number for humans: 4 significant digits, scientific notation when tiny/huge.

    Uses the decimal separator chosen on the Settings page (dot or comma)."""
    s = _fmt(value, sig)
    is_number = isinstance(value, (int, float)) or (type(value).__module__ == "numpy" and hasattr(value, "item"))
    return s.replace(".", ",") if is_number and not isinstance(value, bool) and decimal_mark() == "," else s


def _fmt(value: Any, sig: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            import numpy as np

            if isinstance(value, np.generic):
                value = value.item()
            else:
                return str(value)
        except ImportError:  # pragma: no cover
            return str(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ") if abs(value) >= 10000 else str(value)
    if math.isnan(value) or math.isinf(value):
        return str(value)
    if value == 0:
        return "0"
    if abs(value) >= 1e6 or abs(value) < 1e-3:
        return f"{value:.{sig - 1}e}"
    digits = max(0, sig - 1 - int(math.floor(math.log10(abs(value)))))
    s = f"{value:.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def md_escape(text: Any) -> str:
    """Plain text (a sample, file or compound name) to put inside Markdown: shown as typed, never as formatting.

    Raw HTML is never rendered from Markdown / Alert text anyway (see ``_markdown``)."""
    return re.sub(r"([\\`*_\[\]|])", r"\\\1", str(text))


def _markdown(text: str, extensions: tuple = ()) -> str:
    """Markdown → HTML with raw HTML shown as text: names people type end up here and must not become markup."""
    import markdown

    md = markdown.Markdown(extensions=list(extensions))
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    md.treeprocessors.register(_safe_links()(md), "safe_links", 0)
    return md.convert(text)


@functools.cache
def _safe_links():
    from markdown.treeprocessors import Treeprocessor

    from .serving import safe_link

    class SafeLinks(Treeprocessor):
        """A link or picture that would run something ("javascript:…") loses its address (docs/SECURITY_AUDIT.md M2)."""

        def run(self, root):
            for el in root.iter():
                for attr in ("href", "src"):
                    if el.get(attr) is not None and not safe_link(el.get(attr), ("http", "https", "mailto") if attr == "href" else ("http", "https")):
                        del el.attrib[attr]

    return SafeLinks



MD_EXTENSIONS = {"html": ("tables", "fenced_code", "sane_lists"), "alert": ("tables",)}


def translate_output(o: dict) -> dict:
    """A rendered result (as stored with its job) in the language of whoever is looking.

    Jobs kept in the history run in English, so their records and files stay English; this turns their results into
    the interface's language when they are shown or printed. Texts that were already translated (older jobs, live
    calculator runs) are left as they are: their words aren't catalogue entries."""
    from .i18n import lang

    if lang() == "en" or not isinstance(o, dict):
        return o
    o = json.loads(json.dumps(o))  # a copy: the stored record stays English
    kind = o.get("kind")
    for k in ("title", "caption", "unit", "help", "description"):
        if isinstance(o.get(k), str) and o[k]:
            o[k] = tr(o[k])
    if kind == "metric":
        o["label"] = tr(o.get("label") or "")
        if isinstance(o.get("raw"), str) and isinstance(o.get("value"), str):
            o["value"] = tr(o["value"])
    elif kind in MD_EXTENSIONS and isinstance(o.get("md"), str):
        o["html"] = _markdown(tr_text(o["md"]), MD_EXTENSIONS[kind])
    elif kind == "table":
        cols = [tr(c) if isinstance(c, str) else c for c in o.get("columns") or []]
        if len(set(map(str, cols))) == len(cols):  # never merge two columns into one name
            o["columns"] = cols
        o["rows"] = [[exact(v) if isinstance(v, str) else v for v in row] for row in o.get("rows") or []]
    elif kind == "plot" and isinstance(o.get("figure"), dict):
        o["figure"] = _translated_figure(o["figure"])
    elif kind == "file" and isinstance(o.get("label"), str) and o["label"] != o.get("name"):
        o["label"] = tr(o["label"])
    return o


# Kinds that go into the whole-result PDF (mister_plis/printout.py). Plots are drawn by the browser and sent along
# when someone asks for the PDF; pictures are read from the job's files; videos and downloads are left out.
PRINTABLE = {"html", "alert", "metric", "table", "text", "file", "plot", "image"}
CONTENT = {"html", "alert", "metric", "table", "text", "plot"}  # worth a PDF (a result of only files / pictures isn't)


def printable(outputs: list) -> bool:
    """Every result with something to read gets the one "PDF" button: the whole result, settings and all."""
    return any(o.get("kind") in CONTENT for o in outputs)


class Output:
    kind = "output"

    def render(self, url_for: UrlFor, save: SaveBytes) -> dict:
        raise NotImplementedError


@dataclass
class Markdown(Output):
    text: str
    kind = "html"

    def render(self, url_for, save):
        # "md": the text as the tool wrote it, so a job stored in English can be shown in another language
        return {"kind": "html", "html": _markdown(tr_text(self.text), MD_EXTENSIONS["html"]), "md": self.text}


@dataclass
class HTML(Output):
    html: str

    def render(self, url_for, save):
        return {"kind": "html", "html": self.html}


@dataclass
class Text(Output):
    text: str
    title: str = ""

    def render(self, url_for, save):
        return {"kind": "text", "text": self.text, "title": tr(self.title)}


@dataclass
class Alert(Output):
    text: str
    level: str = "info"  # info | success | warning | error

    def render(self, url_for, save):
        return {"kind": "alert", "level": self.level, "html": _markdown(tr_text(self.text), MD_EXTENSIONS["alert"]), "md": self.text}


@dataclass
class Metric(Output):
    label: str
    value: Any
    unit: str = ""
    help: str = ""
    sig: int = 4
    highlight: bool = False

    def render(self, url_for, save):
        return {
            "kind": "metric",
            "label": tr(self.label),
            "value": fmt(self.value, self.sig) if not isinstance(self.value, str) else tr(self.value),
            "raw": self.value if isinstance(self.value, (int, float, str)) else str(self.value),
            "unit": tr(self.unit),
            "help": tr(self.help),
            "highlight": self.highlight,
        }


def _cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None if math.isnan(v) else str(v)
        return int(v) if v.is_integer() and abs(v) < 1e15 else float(f"{v:.6g}")
    if isinstance(v, (int, str, bool)):
        return v
    try:
        import pandas as pd

        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        return _cell(v.item())
    return str(v)


def _translated(df):
    """Column names in the language of whoever ran the job; text cells only when they are a whole catalogue entry
    (role names like "blank"), so sample names stay as typed."""
    renamed = df.rename(columns=lambda c: tr(c) if isinstance(c, str) else c)
    if len(set(map(str, renamed.columns))) == len(renamed.columns):  # never merge two columns into one name
        df = renamed
    import pandas as pd

    text = [c for c in df.columns if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])]
    if text:
        df = df.copy()
        for c in text:
            df[c] = df[c].map(lambda v: exact(v) if isinstance(v, str) else v).astype(df[c].dtype)
    return df


def _translated_figure(fig: dict) -> dict:
    """Axis titles, the chart title, notes on the chart and legend entries (names that are catalogue entries)."""

    def title(obj):
        if isinstance(obj, dict) and isinstance(obj.get("title"), dict) and isinstance(obj["title"].get("text"), str):
            obj["title"]["text"] = tr(obj["title"]["text"])
        elif isinstance(obj, dict) and isinstance(obj.get("title"), str):
            obj["title"] = tr(obj["title"])

    layout = fig.get("layout") or {}
    title(layout)
    for k, v in layout.items():
        if re.fullmatch(r"[xy]axis\d*|legend|coloraxis\d*", k):
            title(v)
            if isinstance(v, dict):
                title(v.get("colorbar"))
    for a in layout.get("annotations") or []:
        if isinstance(a, dict) and isinstance(a.get("text"), str):
            a["text"] = tr(a["text"])
    for t in fig.get("data") or []:
        if isinstance(t, dict):
            if isinstance(t.get("name"), str):
                t["name"] = exact(t["name"])
            if isinstance(t.get("legendgrouptitle"), dict):
                title({"title": t["legendgrouptitle"]})
            title(t.get("colorbar"))
    return fig


@dataclass
class Table(Output):
    df: Any  # pandas DataFrame (or anything pd.DataFrame() accepts)
    title: str = ""
    max_rows: int = 500
    download: str | None = "table.xlsx"  # filename (.xlsx or .csv) for the full table, None to skip
    index: bool = False
    printable: bool = True  # kept for older tools: tables have no PDF of their own any more — the whole result prints

    def render(self, url_for, save):
        import pandas as pd

        df = self.df if isinstance(self.df, pd.DataFrame) else pd.DataFrame(self.df)
        df = _translated(df)
        shown = df.reset_index() if self.index else df
        head = shown.head(self.max_rows)
        title = tr(self.title)
        out = {
            "kind": "table",
            "title": title,
            "columns": [str(c) for c in head.columns],
            "numeric": [bool(pd.api.types.is_numeric_dtype(head[c])) for c in head.columns],
            "rows": [[_cell(v) for v in row] for row in head.itertuples(index=False, name=None)],
            "total_rows": int(len(df)),
            "printable": self.printable,
        }
        if self.download:
            if self.download.lower().endswith(".xlsx"):
                from .excel import write_table_workbook as write_workbook

                p = save(self.download, b"")
                write_workbook(p, {title or tr("Table"): shown})
            else:  # a comma decimal separator needs ";" between columns
                comma = decimal_mark("xlsx_numbers") == ","
                from .excel import csv_safe

                p = save(self.download, csv_safe(df).to_csv(index=self.index, sep=";" if comma else ",", decimal="," if comma else ".").encode())
            out["download"] = {"url": url_for(p), "name": p.name}
        return out


@dataclass
class Plot(Output):
    fig: Any  # plotly figure; matplotlib figures are converted to an image
    title: str = ""
    height: int | None = None

    def render(self, url_for, save):
        if hasattr(self.fig, "to_json"):
            return {"kind": "plot", "title": tr(self.title), "height": self.height, "figure": _translated_figure(json.loads(self.fig.to_json()))}
        if hasattr(self.fig, "savefig"):
            buf = io.BytesIO()
            self.fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
            return Image(buf.getvalue(), title=self.title, filename="figure.png").render(url_for, save)  # translated there
        raise TypeError(f"Plot() expects a plotly or matplotlib figure, got {type(self.fig).__name__}")


@dataclass
class Image(Output):
    src: Any  # PIL image, path, or bytes
    title: str = ""
    filename: str = "image.png"
    caption: str = ""

    def render(self, url_for, save):
        if isinstance(self.src, (str, Path)):
            p = Path(self.src)
        elif isinstance(self.src, (bytes, bytearray)):
            p = save(self.filename, bytes(self.src))
        else:  # PIL image
            buf = io.BytesIO()
            fmt_name = (Path(self.filename).suffix.lstrip(".") or "png").upper().replace("JPG", "JPEG")
            self.src.save(buf, format=fmt_name)
            p = save(self.filename, buf.getvalue())
        return {"kind": "image", "title": tr(self.title), "caption": tr(self.caption), "url": url_for(p), "name": p.name, "size": p.stat().st_size}


@dataclass
class File(Output):
    src: Any  # path or bytes
    filename: str = ""
    label: str = ""
    description: str = ""
    primary: bool = False  # show as a big download button

    def render(self, url_for, save):
        if isinstance(self.src, (bytes, bytearray)):
            p = save(self.filename or "download.bin", bytes(self.src))
        else:
            p = Path(self.src)
        return {
            "kind": "file",
            "url": url_for(p),
            "name": p.name,
            "label": tr(self.label) or p.name,
            "description": tr(self.description),
            "size": p.stat().st_size,
            "primary": self.primary,
        }


@dataclass
class Video(Output):
    src: Any  # path to an .mp4 / .webm / .mov file
    title: str = ""

    def render(self, url_for, save):
        p = Path(self.src)
        return {"kind": "video", "title": tr(self.title), "url": url_for(p), "name": p.name, "size": p.stat().st_size}


def coerce_outputs(result: Any) -> list[Output]:
    """Turn whatever a run function returned into a flat list of Output objects."""
    if result is None:
        return []
    if isinstance(result, Output):
        return [result]
    if isinstance(result, (list, tuple)):
        return [o for r in result for o in coerce_outputs(r)]
    if isinstance(result, str):
        return [Markdown(result)]
    if isinstance(result, Path):
        return [File(result)]
    if isinstance(result, dict):
        return [Metric(str(k), v) for k, v in result.items()]
    mod = type(result).__module__
    if mod.startswith("pandas"):
        return [Table(result)]
    if mod.startswith("plotly") or mod.startswith("matplotlib"):
        return [Plot(result)]
    if mod.startswith("PIL"):
        return [Image(result)]
    return [Text(repr(result))]
