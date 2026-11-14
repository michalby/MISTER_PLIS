"""Printable PDF of a result table, with who ran it, when, from which files and with which settings.

The layout is picked to use as little paper as possible: portrait A4 if the table is narrow enough,
landscape otherwise, a condensed font when that saves a page width, and — when only a few rows
spill onto an extra page — slightly smaller type and padding so they fit on one page less.
"""

from __future__ import annotations

import io
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4, landscape

from .i18n import tn, tr
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

GREY = "#666666"
ACCENT = "#2a5d9f"  # tool name and the rule over the run details
PANEL = "#eef1f5"
MIN_SIZE = 5.0  # pt — below this a print is no longer readable


@dataclass
class ReportInfo:
    title: str
    tool: str = ""
    job_id: str = ""
    run_by: str = ""
    run_at: float | None = None
    printed_by: str = ""
    params: list = field(default_factory=list)  # [(label, value text)]
    note: str = ""  # e.g. "Sorted by …"
    lab: str = ""
    version: str = ""
    decimal: str = "."
    params_caption: str = "SETTINGS"  # the heading over ``params`` (e.g. "FILTERS" for a filtered list)


# --- fonts ---------------------------------------------------------------------------

# (regular, bold, condensed, condensed bold) — Arial on macOS / Windows, DejaVu on Linux.
_FONT_SETS = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Narrow.ttf", "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ARIALN.TTF", "C:/Windows/Fonts/ARIALNB.TTF"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"),
]
_fonts: dict | None = None


def fonts() -> dict:
    """Font names for "regular", "bold", "narrow", "narrow_bold" (registered on first use).

    TrueType fonts cover Polish letters, Greek and symbols like µ ± ²; the built-in Helvetica
    (the fallback when none are installed) only covers Western European text."""
    global _fonts
    if _fonts is None:
        _fonts = {"regular": "Helvetica", "bold": "Helvetica-Bold", "narrow": "Helvetica", "narrow_bold": "Helvetica-Bold"}
        for paths in _FONT_SETS:
            if all(Path(p).is_file() for p in paths[:2]):
                names = ("MP-Regular", "MP-Bold", "MP-Narrow", "MP-NarrowBold")
                ok = {}
                for key, name, p in zip(_fonts, names, paths):
                    try:
                        pdfmetrics.registerFont(TTFont(name, p))
                        ok[key] = name
                    except Exception:  # a missing or unreadable condensed face: use the regular one
                        pass
                if "regular" in ok and "bold" in ok:
                    _fonts = {"regular": ok["regular"], "bold": ok["bold"],
                              "narrow": ok.get("narrow", ok["regular"]), "narrow_bold": ok.get("narrow_bold", ok["bold"])}
                    break
    return _fonts


# --- cell text -------------------------------------------------------------------------


def cell_text(v: Any, decimal: str = ".") -> str:
    """The value as it appears in the table on screen."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        s = str(v)
        s = re.sub(r"e([+-])0*(\d)", r"e\1\2", s)  # 1e-07 → 1e-7, as on screen
        return s.replace(".", ",") if decimal == "," else s
    return str(v)


_NUM = re.compile(r"^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def _num_prefix(v: Any) -> float | None:
    """Like JavaScript's parseFloat, so sorting matches the table on screen."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM.match(str(v))
    return float(m.group(0)) if m else None


def _natural(s: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", s))


def sort_rows(rows: list, col: int, descending: bool) -> list:
    """Sort like the table on screen: numbers by value, text naturally, empty cells always last."""
    filled = [r for r in rows if col < len(r) and r[col] is not None]
    empty = [r for r in rows if not (col < len(r) and r[col] is not None)]

    def key(r):
        n = _num_prefix(r[col])
        return (0, n, ()) if n is not None and not math.isnan(n) else (1, 0.0, _natural(str(r[col])))

    return sorted(filled, key=key, reverse=descending) + empty


# --- layout ----------------------------------------------------------------------------


@dataclass
class _Layout:
    pagesize: tuple
    narrow: bool
    size: float
    vpad: float
    margin: float

    @property
    def width(self) -> float:
        return self.pagesize[0] - 2 * self.margin


def _col_widths(columns, body, numeric, lay: _Layout):
    """Column widths that fit ``lay.width`` (headers wrap at spaces), or None if the table is too wide."""
    f = fonts()
    body_font = f["narrow" if lay.narrow else "regular"]
    head_font = f["narrow_bold" if lay.narrow else "bold"]
    hpad = 2 * max(1.5, lay.size * 0.4)
    sw = pdfmetrics.stringWidth
    widths, wants = [], []
    for i, c in enumerate(columns):
        cells = max((sw(r[i], body_font, lay.size) for r in body), default=0)
        word = max((sw(w, head_font, lay.size) for w in c.split()), default=0)
        widths.append(max(cells, word) + hpad + 0.5)
        wants.append(max(cells, sw(c, head_font, lay.size)) + hpad + 0.5)
    spare = lay.width - sum(widths)
    if spare < 0:
        return None
    short = [w - n for w, n in zip(wants, widths)]
    k = min(1.0, spare / sum(short)) if sum(short) > 0 else 0
    return [n + s * k for n, s in zip(widths, short)]


def _squeeze(columns, body, lay: _Layout):
    """Last resort for very wide tables: share the page width out, wrapping text columns."""
    f = fonts()
    sw = pdfmetrics.stringWidth
    hpad = 2 * max(1.5, lay.size * 0.4) + 0.5
    need = [max([sw(r[i], f["narrow"], lay.size) for r in body] + [sw(columns[i], f["narrow_bold"], lay.size)]) + hpad
            for i in range(len(columns))]
    # water-filling: columns narrower than the cap keep their width, the rest share what is left
    left, n = lay.width, len(need)
    for w in sorted(need):
        if w <= left / n:
            left -= w
            n -= 1
        else:
            cap = left / n
            break
    else:
        cap = max(need)
    return [min(w, cap) for w in need]


def _choose(columns, body, numeric, size: float = 8) -> tuple[_Layout, list]:
    portrait, wide = A4, landscape(A4)
    # larger type first if asked for (a list to read from a step away), then the usual ladder
    big = [(portrait, False, size), (portrait, True, size), (wide, False, size), (wide, True, size)] if size > 8 else []
    ladder = big + [(portrait, False, 8), (portrait, True, 8), (wide, False, 8), (wide, True, 8),
              (wide, True, 7.5), (wide, True, 7), (wide, True, 6.5), (wide, True, 6), (wide, True, 5.5), (wide, True, MIN_SIZE)]
    for pagesize, narrow, size in ladder:
        lay = _Layout(pagesize, narrow, size, vpad=0.8 if size >= 7 else 0.5, margin=10 * mm)
        widths = _col_widths(columns, body, numeric, lay)
        if widths:
            return lay, widths
    lay = _Layout(wide, True, MIN_SIZE, vpad=0.5, margin=8 * mm)
    return lay, _col_widths(columns, body, numeric, lay) or _squeeze(columns, body, lay)


def _tighter(lay: _Layout):
    """Slightly denser versions of a layout (same paper, up to ~20 % more rows per page), for pulling
    a few overflowing rows back. Anything more would cost readability, so then the extra page stays."""
    for dsize, vpad in [(0, 0.4), (-0.5, 0.3), (-1.0, 0.25)]:
        yield _Layout(lay.pagesize, lay.narrow, max(MIN_SIZE, lay.size + dsize), vpad=vpad, margin=8 * mm)


# --- Time Machine mark ---------------------------------------------------------------------


class GalaxyMark(Flowable):
    """A small, quiet spiral galaxy printed next to the job number: the number to type in Time Machine
    to find this result again. Grey hairlines, so it doesn't compete with the results."""

    def __init__(self, size: float = 7.5, color: str = "#8d93a0"):
        super().__init__()
        self.size, self.color = size, color

    def wrap(self, *_):
        return self.size, self.size

    def draw(self):
        c, r = self.canv, self.size / 2
        c.saveState()
        c.translate(r, r)
        c.setStrokeColor(self.color)
        c.setFillColor(self.color)
        c.setLineCap(1)
        for arm in (0, math.pi):  # two arms of a logarithmic spiral
            path = c.beginPath()
            for i in range(25):
                t = i / 24
                a = arm + t * 2.6 * math.pi / 2
                rad = r * (0.16 + 0.8 * t)
                x, y = rad * math.cos(a), rad * math.sin(a)
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            c.setLineWidth(0.45)
            c.drawPath(path, stroke=1, fill=0)
        c.circle(0, 0, r * 0.17, stroke=0, fill=1)
        for x, y, d in ((0.78, 0.62, 0.05), (-0.7, -0.74, 0.045), (0.88, -0.35, 0.04)):
            c.circle(x * r, y * r, r * d * 2, stroke=0, fill=1)
        c.restoreState()


def job_number_cell(job_id: str, style: ParagraphStyle) -> Table:
    """The job number with the Time Machine mark in front of it."""
    mark = GalaxyMark(style.fontSize * 0.95)
    t = Table([[mark, Paragraph(escape(job_id), style)]], colWidths=[mark.size + 3, None], hAlign="LEFT")
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


# --- document ----------------------------------------------------------------------------


def _meta_flowables(info: ReportInfo, lay: _Layout, total_rows: int, shown_rows: int, xlsx: str) -> list:
    """The header on the first page: tool, title, who / when, and the settings as a grid."""
    f = fonts()
    kicker = ParagraphStyle("k", fontName=f["bold"], fontSize=6.5, leading=8, textColor=ACCENT)
    kicker_r = ParagraphStyle("kr", parent=kicker, fontName=f["regular"], textColor=GREY, alignment=2)
    title = ParagraphStyle("t", fontName=f["bold"], fontSize=13, leading=15.5)
    cap = ParagraphStyle("c", fontName=f["regular"], fontSize=5.8, leading=7, textColor=GREY)
    value = ParagraphStyle("v", fontName=f["bold"], fontSize=7.8, leading=9.4)
    setting = ParagraphStyle("s", fontName=f["regular"], fontSize=7, leading=8.4)
    note = ParagraphStyle("n", fontName=f["regular"], fontSize=6.5, leading=8, textColor=GREY)

    def when(ts):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

    out = []
    head = [Paragraph(escape(info.tool.upper()), kicker), Paragraph(escape(info.lab), kicker_r)]
    t = Table([head], colWidths=[lay.width * 0.7, lay.width * 0.3], hAlign="LEFT")
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    out += [t, Paragraph(escape(info.title), title), Spacer(0, 4)]

    # who / when: one strip of small captions over values
    printed = when(time.time())
    if info.printed_by and info.printed_by != info.run_by:
        printed += f' <font name="{f["regular"]}">{escape(tr("by"))}</font> {escape(info.printed_by)}'
    cells = [(k, v) for k, v in (("RUN BY", escape(info.run_by)), ("RUN", when(info.run_at) if info.run_at else ""),
                                 ("PRINTED", printed), ("JOB", escape(info.job_id))) if v]
    weights = {"RUN BY": 1.0, "RUN": 0.8, "PRINTED": 1.25, "JOB": 1.15}
    total = sum(weights[k] for k, _ in cells)
    strip = Table([[[Paragraph(escape(tr(k)), cap), job_number_cell(info.job_id, value) if k == "JOB" else Paragraph(v, value)]
                    for k, v in cells]],
                  colWidths=[lay.width * weights[k] / total for k, _ in cells], hAlign="LEFT")
    strip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBEFORE", (1, 0), (-1, -1), 0.5, "#ffffff"), ("LINEABOVE", (0, 0), (-1, 0), 1.2, ACCENT),
    ]))
    out.append(strip)

    # settings: "label  value" pairs in a grid, read row by row
    if info.params:
        ncol = 3 if lay.width < 600 else 4
        items = [Paragraph(f'<font color="{GREY}">{escape(k)}</font>&nbsp; {escape(v)}', setting) for k, v in info.params]
        items += [""] * (-len(items) % ncol)
        grid = Table([[Paragraph(escape(tr(info.params_caption)), cap)] + [""] * (ncol - 1)] + [items[i:i + ncol] for i in range(0, len(items), ncol)],
                     colWidths=[lay.width / ncol] * ncol, hAlign="LEFT")
        grid.setStyle(TableStyle([
            ("SPAN", (0, 0), (-1, 0)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 0.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
            ("TOPPADDING", (0, 0), (-1, 0), 4), ("BOTTOMPADDING", (0, -1), (-1, -1), 4),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, "#c9ced6"),
        ]))
        out.append(grid)

    notes = [info.note] if info.note else []
    if shown_rows < total_rows:
        notes.append(tr("First {shown} of {total} rows", shown=shown_rows, total=total_rows)
                     + (tr(" — the full table is in {file}.", file=xlsx) if xlsx else "."))
    if notes:
        out += [Spacer(0, 2), Paragraph(escape(" ".join(notes)), note)]
    out.append(Spacer(0, 6))
    return out


def _table(columns, body, numeric, widths, lay: _Layout, wrap_cells: bool) -> Table:
    f = fonts()
    body_font = f["narrow" if lay.narrow else "regular"]
    head_font = f["narrow_bold" if lay.narrow else "bold"]
    leading = lay.size * 1.15
    hs = ParagraphStyle("h", fontName=head_font, fontSize=lay.size, leading=leading)
    hs_num = ParagraphStyle("hn", parent=hs, alignment=2)
    cs = ParagraphStyle("c", fontName=body_font, fontSize=lay.size, leading=leading)
    head = [Paragraph(escape(c), hs_num if numeric[i] else hs) for i, c in enumerate(columns)]
    rows = [[Paragraph(escape(v), cs) if wrap_cells and not numeric[i] else v for i, v in enumerate(r)] for r in body]
    hpad = max(1.5, lay.size * 0.4)
    style = [
        ("FONT", (0, 1), (-1, -1), body_font, lay.size, leading),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), hpad),
        ("RIGHTPADDING", (0, 0), (-1, -1), hpad),
        ("TOPPADDING", (0, 0), (-1, -1), lay.vpad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), lay.vpad + 0.6),
        ("BACKGROUND", (0, 0), (-1, 0), "#e4e4e4"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), ["#ffffff", "#f3f3f3"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, "#c2c2c2"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, "#555555"),
        ("BOX", (0, 0), (-1, -1), 0.6, "#555555"),
    ]
    style += [("ALIGN", (i, 1), (i, -1), "RIGHT") for i, n in enumerate(numeric) if n]
    t = Table([head] + rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle(style))
    return t


def _canvas_class(info: ReportInfo):
    """A canvas that writes "page n of N" and the run details in every page's footer."""
    f = fonts()

    class Footed(pdfcanvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            n = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._footer(n)
                super().showPage()
            super().save()

        def _footer(self, total):
            w, _ = self._pagesize
            m = self._mp_margin
            self.setFont(f["regular"], 6.5)
            self.setFillColor(GREY)
            left = " · ".join(x for x in (info.title, info.tool, info.run_by, info.job_id) if x)
            right = " · ".join(x for x in (info.lab, f"MISTER PLIS {info.version}".strip()) if x)
            right += " · " + tr("page {n} of {total}", n=self._pageNumber, total=total)
            y = m * 0.45
            self.drawRightString(w - m, y, right)
            room = w - 2 * m - pdfmetrics.stringWidth(right, f["regular"], 6.5) - 12
            while left and pdfmetrics.stringWidth(left, f["regular"], 6.5) > room:
                left = left[:-2] + "…" if len(left) > 2 else ""
            self.drawString(m, y, left)

    return Footed


def _build(info, columns, body, numeric, widths, lay, wrap, total_rows, xlsx) -> tuple[bytes, int]:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=lay.pagesize, leftMargin=lay.margin, rightMargin=lay.margin,
                            topMargin=lay.margin, bottomMargin=lay.margin, title=info.title,
                            author=info.run_by or info.printed_by, subject=info.tool, creator="MISTER PLIS")
    canvas_cls = _canvas_class(info)
    canvas_cls._mp_margin = lay.margin
    story = _meta_flowables(info, lay, total_rows, len(body), xlsx) + [_table(columns, body, numeric, widths, lay, wrap)]
    doc.build(story, canvasmaker=canvas_cls)
    return buf.getvalue(), doc.page


def table_pdf(output: dict, info: ReportInfo, sort: int | None = None, descending: bool = False, size: float = 8) -> bytes:
    """PDF bytes for a rendered :class:`~mister_plis.outputs.Table` (its JSON dict). ``size``: the type size to try
    first (pt); a larger one falls back to the usual 8 pt and smaller when the table doesn't fit."""
    columns = [str(c) for c in output.get("columns") or []] or [""]
    numeric = list(output.get("numeric") or [False] * len(columns))
    numeric += [False] * (len(columns) - len(numeric))
    rows = [list(r) + [None] * (len(columns) - len(r)) for r in output.get("rows") or []]
    if sort is not None and 0 <= sort < len(columns):
        rows = sort_rows(rows, sort, descending)
        info.note = (info.note + " " if info.note else "") + tr("Sorted by {column}{order}.", column=columns[sort],
                                                                 order=tr(" (descending)") if descending else "")
    body = [[cell_text(v, info.decimal) for v in r] for r in rows]
    total = int(output.get("total_rows") or len(rows))
    xlsx = (output.get("download") or {}).get("name", "")

    lay, widths = _choose(columns, body, numeric, size)
    wrap = _col_widths(columns, body, numeric, lay) is None
    pdf, pages = _build(info, columns, body, numeric, widths, lay, wrap, total, xlsx)
    if pages > 1 and not wrap:  # only a few rows over? try a denser layout that saves a page
        for tight in _tighter(lay):
            w = _col_widths(columns, body, numeric, tight)
            if not w:
                continue
            p2, n2 = _build(info, columns, body, numeric, w, tight, False, total, xlsx)
            if n2 < pages:
                return p2
    return pdf


# --- run details --------------------------------------------------------------------------


def _js_str(v: Any) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def _shown(cond: dict | None, params: dict, defaults: dict) -> bool:
    """Same rule as ``visible()`` in tool.js: was the input on screen when the job was started?"""
    if not cond:
        return True
    for k, want in cond.items():
        cur = params.get(k, defaults.get(k))
        if not any(_js_str(w) == _js_str(cur) for w in (want if isinstance(want, list) else [want])):
            return False
    return True


def _short(s: str, n: int = 80) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def describe_files(tool, files: dict) -> list:
    """``[(input label, [file names])]`` from a job's ``files``, in form order (for the backup's job-info)."""
    labels = {i.name: i.label for i in (tool.inputs if tool else []) if hasattr(i, "label")}
    return [(labels.get(k, k), [f["name"] for f in v]) for k, v in files.items() if v]


def _same(a: Any, b: Any) -> bool:
    if a in (None, "") and b in (None, ""):
        return True
    try:
        return float(str(a).replace(",", ".")) == float(str(b).replace(",", "."))
    except (TypeError, ValueError):
        return _js_str(a) == _js_str(b)


def _untouched_advanced(tool, params: dict) -> set:
    """Names of inputs in collapsed (advanced) sections where nothing was changed from the defaults —
    e.g. the standard extinction coefficients. Leaving them out keeps the report readable."""
    from .inputs import Input, Section

    groups, current = [], None
    for item in tool.inputs:
        if isinstance(item, Section):
            current = [] if item.collapsed else None
            if current is not None:
                groups.append(current)
        elif isinstance(item, Input) and current is not None:
            current.append(item)
    return {i.name for g in groups if all(_same(params.get(i.name, i.default), i.default) for i in g) for i in g}


def describe_settings(tool, params: dict, decimal: str = ".") -> list:
    """``[(label, text)]`` for the form values a job ran with — what someone would need to repeat it."""
    from .inputs import Button, Checkbox, Column, ImageSpots, Input, Number, PlateLayout, SampleTable, Select, Text
    from .inputs import File as FileInput

    if tool is None:  # the tool is gone: show the plain values
        return [(k, _short(_js_str(v))) for k, v in params.items() if v not in (None, "", []) and not isinstance(v, (dict, list))]
    inputs = [i for i in tool.inputs if isinstance(i, Input)]
    defaults = {i.name: i.default for i in inputs}
    advanced_at_defaults = _untouched_advanced(tool, params)
    out = []
    for inp in inputs:
        if isinstance(inp, (FileInput, Button)) or not _shown(inp.show_if, params, defaults) or inp.name in advanced_at_defaults:
            continue
        raw = params.get(inp.name, inp.default)
        if isinstance(inp, Checkbox):
            text = tr("yes") if inp.parse(raw, None) else tr("no")
        elif raw is None or raw == "" or raw == [] or raw == {}:
            continue
        elif isinstance(inp, Number):
            text = cell_text(raw, decimal) if isinstance(raw, (int, float)) else str(raw).strip()
            unit = inp.parse_unit(params.get(f"{inp.name}__unit")) if inp.units else inp.unit  # the form's key (p.<name>_unit after parsing)
            unit = tr(unit)
            text = f"± {text} {unit[1:].strip()}" if unit.startswith("±") else f"{text} {unit}".strip()
        elif isinstance(inp, Select):
            text = next((tr(str(label)) for value, label in inp.current() if str(value) == str(raw)), str(raw))
        elif isinstance(inp, Column):
            text = ", ".join(map(str, raw)) if isinstance(raw, list) else str(raw)
        elif isinstance(inp, SampleTable):
            text = tn(len(raw), "{n} row", "{n} rows") if isinstance(raw, list) else "—"
        elif isinstance(inp, PlateLayout):
            roles = [w.get("role") for w in raw.values() if isinstance(w, dict)] if isinstance(raw, dict) else []
            counts = [(r, roles.count(r)) for r in ("blank", "standard", "sample") if roles.count(r)]
            names = {"blank": ("{n} blank", "{n} blanks"), "standard": ("{n} standard", "{n} standards"), "sample": ("{n} sample", "{n} samples")}
            text = ", ".join(tn(n, *names[r]) for r, n in counts) or tr("empty")
        elif isinstance(inp, ImageSpots):
            spots = raw.get("spots") if isinstance(raw, dict) else raw
            spots = [s for s in spots if isinstance(s, dict)] if isinstance(spots, list) else []
            samples = {str(s.get("sample") or s.get("id") or "") for s in spots}
            text = (tn(len(spots), "{n} circle", "{n} circles") + ", " + tn(len(samples), "{n} sample", "{n} samples")) if spots else tr("empty")
        elif isinstance(inp, Text):
            text = _short(raw)
        else:
            text = _short(_js_str(raw))
        out.append((tr(inp.label), text))
    return out
