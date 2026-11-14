"""Printable PDF of a whole result — metrics, text, tables, warnings — and of a protocol: several
calculator results collected one after another ("Add to protocol") and printed together for the bench.

Built on the table report (:mod:`mister_plis.report`): same header, fonts and footer.
"""

from __future__ import annotations

import io
from html.parser import HTMLParser
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import CondPageBreak, Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .i18n import tr
from .outputs import PRINTABLE, printable  # noqa: F401  (re-exported)
from .report import ACCENT, GREY, PANEL, ReportInfo, _canvas_class, _col_widths, _Layout, _meta_flowables, _squeeze, _table, cell_text, fonts

MARGIN = 12 * mm
_families: set = set()
ALERT_COLORS = {"info": ("#eef1f5", "#8a96a8"), "success": ("#e9f5ee", "#2e8b57"),
                "warning": ("#fdf4e3", "#d08c00"), "error": ("#fbeaea", "#c0392b")}


_SUB = str.maketrans({c: f"<sub>{d}</sub>" for c, d in zip("₀₁₂₃₄₅₆₇₈₉", "0123456789")})


def _x(text) -> str:
    """Escaped for paragraph markup; subscript digits (C₁, H₂O — not in Arial) as real subscripts."""
    return escape(str(text)).translate(_SUB)


def _styles() -> dict:
    f = fonts()
    if f["regular"] not in _families:  # so <b> and <i> inside a paragraph switch to the bold face
        pdfmetrics.registerFontFamily(f["regular"], normal=f["regular"], bold=f["bold"], italic=f["regular"], boldItalic=f["bold"])
        _families.add(f["regular"])
    return {
        "body": ParagraphStyle("b", fontName=f["regular"], fontSize=9, leading=11.5, spaceAfter=3),
        "small": ParagraphStyle("sm", fontName=f["regular"], fontSize=7, leading=8.6, textColor=GREY),
        "h": ParagraphStyle("h", fontName=f["bold"], fontSize=9.5, leading=12, spaceBefore=4, spaceAfter=2),
        "section": ParagraphStyle("sec", fontName=f["bold"], fontSize=11.5, leading=14),
        "mlabel": ParagraphStyle("ml", fontName=f["regular"], fontSize=6.8, leading=8.2, textColor=GREY),
        "mvalue": ParagraphStyle("mv", fontName=f["bold"], fontSize=11, leading=13.5),
        "mhelp": ParagraphStyle("mh", fontName=f["regular"], fontSize=6.5, leading=7.8, textColor=GREY),
        "mono": ParagraphStyle("mo", fontName=f["regular"], fontSize=8, leading=9.8),
    }


# --- Markdown (already HTML) → paragraphs ---------------------------------------------------------


class _HTML(HTMLParser):
    """The small HTML subset Markdown produces → reportlab paragraph markup, one block at a time.

    Text is escaped, tags outside the subset are dropped, so nothing typed by a user turns into markup."""

    INLINE = {"strong": "b", "b": "b", "em": "i", "i": "i"}
    BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "td", "th", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, dict]] = []  # (tag, markup, extra)
        self.buf: list[str] = []
        self.lists: list[list] = []  # [kind, counter]
        self.row: list | None = None
        self.table: list | None = None
        self.block_tag = "p"

    def _flush(self):
        text = "".join(self.buf).strip()
        self.buf = []
        if not text:
            return
        if self.row is not None:
            self.row[-1] += text
            return
        extra = {}
        if self.block_tag == "li" and self.lists:
            kind = self.lists[-1]
            kind[1] += 1
            extra = {"bullet": f"{kind[1]}." if kind[0] == "ol" else "•", "depth": len(self.lists)}
        self.blocks.append((self.block_tag, text, extra))

    def handle_starttag(self, tag, attrs):
        if tag in self.INLINE:
            self.buf.append(f"<{self.INLINE[tag]}>")
        elif tag == "code":
            self.buf.append(f'<font name="{fonts()["narrow"]}">')
        elif tag == "br":
            self.buf.append("<br/>")
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append([tag, 0])
        elif tag == "table":
            self._flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.row.append("")
        elif tag in self.BLOCKS:
            self._flush()
            self.block_tag = tag

    def handle_endtag(self, tag):
        if tag in self.INLINE:
            self.buf.append(f"</{self.INLINE[tag]}>")
        elif tag == "code":
            self.buf.append("</font>")
        elif tag in ("ul", "ol"):
            self._flush()
            if self.lists:
                self.lists.pop()
            self.block_tag = "li" if self.lists else "p"
        elif tag in ("td", "th"):
            self._flush()
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.blocks.append(("table", "", {"rows": self.table}))
            self.table = None
        elif tag in self.BLOCKS:
            self._flush()
            self.block_tag = "li" if self.lists else "p"

    def handle_data(self, data):
        self.buf.append(_x(data))

    def close(self):
        super().close()
        self._flush()


def html_flowables(html: str, width: float) -> list:
    st = _styles()
    p = _HTML()
    p.feed(html or "")
    p.close()
    out = []
    for tag, text, extra in p.blocks:
        if tag == "table":
            rows = [[Paragraph(c, st["small"]) for c in r] for r in extra["rows"] if r]
            if rows:
                n = max(len(r) for r in rows)
                rows = [r + [""] * (n - len(r)) for r in rows]
                t = Table(rows, colWidths=[width / n] * n, hAlign="LEFT")
                t.setStyle(TableStyle([("INNERGRID", (0, 0), (-1, -1), 0.25, "#c2c2c2"), ("BOX", (0, 0), (-1, -1), 0.5, "#555555"),
                                       ("BACKGROUND", (0, 0), (-1, 0), "#e4e4e4"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                out += [t, Spacer(0, 4)]
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            out.append(Paragraph(text, st["h"]))
        elif tag == "li":
            depth = extra.get("depth", 1)
            style = ParagraphStyle("li", parent=st["body"], leftIndent=14 * depth, bulletIndent=14 * depth - 12, spaceAfter=1.5)
            out.append(Paragraph(text, style, bulletText=extra.get("bullet", "•")))
        elif tag == "pre":
            out.append(Paragraph(text.replace("\n", "<br/>"), st["mono"]))
        else:
            out.append(Paragraph(text, st["body"]))
    return out


# --- each kind of output -----------------------------------------------------------------------------


def _metric_value(o: dict, decimal: str) -> str:
    """As on screen: formatted when the job ran, shown with today's decimal mark."""
    v = str(o.get("value", ""))
    if isinstance(o.get("raw"), (int, float)) and not isinstance(o.get("raw"), bool):
        v = v.replace(".", ",") if decimal == "," else v.replace(",", ".")
    return v


def _metrics(group: list, width: float, decimal: str) -> Table:
    st = _styles()
    ncol = min(4, len(group))
    cells = []
    for o in group:
        unit = f' <font name="{fonts()["regular"]}" size="8">{_x(o.get("unit") or "")}</font>' if o.get("unit") else ""
        cell = [Paragraph(_x(o.get("label", "")), st["mlabel"]), Paragraph(_x(_metric_value(o, decimal)) + unit, st["mvalue"])]
        if o.get("help"):
            cell.append(Paragraph(_x(o["help"]), st["mhelp"]))
        cells.append(cell)
    cells += [""] * (-len(cells) % ncol)
    rows = [cells[i:i + ncol] for i in range(0, len(cells), ncol)]
    t = Table(rows, colWidths=[width / ncol] * ncol, hAlign="LEFT")
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    for i, o in enumerate(group):
        r, c = divmod(i, ncol)
        style += [("BACKGROUND", (c, r), (c, r), PANEL), ("LINEAFTER", (c, r), (c, r), 2, "#ffffff"), ("LINEBELOW", (c, r), (c, r), 2, "#ffffff")]
        if o.get("highlight"):
            style.append(("LINEBEFORE", (c, r), (c, r), 2, ACCENT))
    t.setStyle(TableStyle(style))
    return t


def _alert(o: dict, width: float) -> Table:
    bg, line = ALERT_COLORS.get(o.get("level"), ALERT_COLORS["info"])
    body = html_flowables(o.get("html", ""), width - 16) or [""]
    for p in body:
        if isinstance(p, Paragraph):
            p.style = ParagraphStyle("al", parent=p.style, spaceAfter=0)
    t = Table([[body]], colWidths=[width], hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 2.5, line),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _title(text: str) -> Paragraph:
    return Paragraph(_x(text), ParagraphStyle("ht", parent=_styles()["h"], keepWithNext=1))


def _text(o: dict, width: float) -> list:
    """Preformatted text; a long list of short lines (e.g. sample names) is set in columns to save paper."""
    st = _styles()
    lines = str(o.get("text", "")).splitlines() or [""]
    out = [_title(o["title"])] if o.get("title") else []
    longest = max(len(s) for s in lines)
    if len(lines) > 8 and longest <= 24:
        ncol = max(1, min(8, int(width // max(40, longest * 5.2 + 14))))
        per = -(-len(lines) // ncol)
        cols = [lines[i * per:(i + 1) * per] for i in range(ncol)]
        rows = [[c[r] if r < len(c) else "" for c in cols] for r in range(per)]
        t = Table(rows, colWidths=[width / ncol] * ncol, hAlign="LEFT")
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), fonts()["regular"], 8, 9.6), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                               ("TOPPADDING", (0, 0), (-1, -1), 0.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8)]))
        out.append(t)
    else:
        out.append(Paragraph("<br/>".join(_x(s).replace("  ", "&nbsp; ") for s in lines), st["mono"]))
    return out


def _min_widths(columns, body, lay: _Layout) -> list:
    """The narrowest each column can be without breaking a word or a number: numbers and header words stay whole."""
    f = fonts()
    sw = pdfmetrics.stringWidth
    hpad = 2 * max(1.5, lay.size * 0.4) + 0.5
    out = []
    for i, c in enumerate(columns):
        head = max((sw(w, f["narrow_bold"], lay.size) for w in c.split()), default=0)
        cell = max((sw(w, f["narrow"], lay.size) for r in body for w in (r[i].split() or [""])), default=0)
        out.append(max(head, cell) + hpad)
    return out


def _wrapped_widths(columns, body, numeric, lay: _Layout):
    """Widths for a table whose long text (notes, recipes) wraps inside its cells; numbers never wrap.
    None if even that doesn't fit the page."""
    f = fonts()
    sw = pdfmetrics.stringWidth
    hpad = 2 * max(1.5, lay.size * 0.4) + 0.5
    least = _min_widths(columns, body, lay)
    full = [max([sw(r[i], f["narrow"], lay.size) for r in body] + [least[i] - hpad]) + hpad for i in range(len(columns))]
    fixed = [full[i] if numeric[i] else least[i] for i in range(len(columns))]
    spare = lay.width - sum(fixed)
    if spare < 0:
        return None
    grow = [full[i] - fixed[i] for i in range(len(columns))]
    k = min(1.0, spare / sum(grow)) if sum(grow) > 0 else 0
    return [fixed[i] + grow[i] * k for i in range(len(columns))]


def _column_blocks(columns, body, numeric, lay: _Layout) -> list:
    """Split a table too wide for the page into blocks of columns stacked one under another. Each block
    repeats the leading text columns (sample, replicate…) so it can be read on its own."""
    least = _min_widths(columns, body, lay)
    keys = []
    for i, n in enumerate(numeric):
        if n or len(keys) == 3 or sum(least[k] for k in keys) + least[i] > lay.width * 0.4:
            break
        keys.append(i)
    rest = [i for i in range(len(columns)) if i not in keys]
    # columns that belong together stay together: "632 — position", "632 FWHM", "632 — area"… share their first word
    units = []
    for i in rest:
        first = (columns[i].split() or [""])[0]
        if units and (units[-1][0].split() or [""])[0] == first:
            units[-1][1].append(i)
        else:
            units.append((columns[i], [i]))

    def fits(cols):
        return _col_widths([columns[j] for j in cols], [[r[j] for j in cols] for r in body], [numeric[j] for j in cols], lay) is not None

    blocks, current = [], []
    for _, unit in units:
        if current and not fits(keys + current + unit):
            blocks.append(keys + current)
            current = []
        if not fits(keys + unit):  # one group alone is too wide: fall back to single columns
            for i in unit:
                if current and not fits(keys + current + [i]):
                    blocks.append(keys + current)
                    current = []
                current.append(i)
        else:
            current += unit
    if current:
        blocks.append(keys + current)
    return blocks


def _data_table(o: dict, width: float, decimal: str) -> list:
    columns = [str(c) for c in o.get("columns") or []] or [""]
    numeric = list(o.get("numeric") or [False] * len(columns))
    numeric += [False] * (len(columns) - len(numeric))
    rows = [list(r) + [None] * (len(columns) - len(r)) for r in o.get("rows") or []]
    body = [[cell_text(v, decimal) for v in r] for r in rows]
    page = (width + 2 * MARGIN, A4[1])
    out = [_title(o["title"])] if o.get("title") else []
    tables = None
    for narrow, size in [(False, 8), (True, 8), (True, 7.5), (True, 7)]:
        lay = _Layout(page, narrow, size, vpad=0.8, margin=MARGIN)
        widths = _col_widths(columns, body, numeric, lay)
        if widths:
            tables = [_table(columns, body, numeric, widths, lay, False)]
            break
    if tables is None:  # long notes or recipes: wrap the text in its cells, numbers stay whole
        lay = _Layout(page, True, 7.5, vpad=0.8, margin=MARGIN)
        widths = _wrapped_widths(columns, body, numeric, lay)
        if widths:
            tables = [_table(columns, body, numeric, widths, lay, True)]
    if tables is None:  # many columns (e.g. Gaussian components per band): several narrower tables, one under another
        lay = _Layout(page, True, 7.5, vpad=0.8, margin=MARGIN)
        tables = []
        for cols in _column_blocks(columns, body, numeric, lay):
            c = [columns[j] for j in cols]
            b = [[r[j] for j in cols] for r in body]
            n = [numeric[j] for j in cols]
            w = _col_widths(c, b, n, lay) or _wrapped_widths(c, b, n, lay) or _squeeze(c, b, lay)
            t = _table(c, b, n, w, lay, True)
            tables += [KeepTogether([t]) if len(b) <= 25 else t, Spacer(0, 5)]  # a short block isn't torn across pages
        tables = tables[:-1]
    if out and tables:  # the title stays with the start of the table
        out = [KeepTogether(out + [tables[0]])] if len(body) <= 25 else out + [tables[0]]
        out += tables[1:]
    else:
        out += tables
    total = int(o.get("total_rows") or len(rows))
    if len(rows) < total:
        name = (o.get("download") or {}).get("name", "")
        out.append(Paragraph(escape(tr("First {shown} of {total} rows", shown=len(rows), total=total)
                                    + (tr(" — the full table is in {file}.", file=name) if name else ".")), _styles()["small"]))
    return out


MAX_PICTURES = 24  # per PDF: a converter's 200 previews don't belong on paper


def _picture(data: bytes, width: float, max_height: float):
    """PNG / JPEG / TIFF… bytes → an image flowable at most ``width`` × ``max_height``, or None if unreadable."""
    from PIL import Image as PILImage
    from reportlab.platypus import Image as RLImage

    try:
        with PILImage.open(io.BytesIO(data)) as im:
            im.load()
            if im.mode not in ("RGB", "L"):
                bg = PILImage.new("RGB", im.size, "white")
                rgba = im.convert("RGBA")
                bg.paste(rgba, mask=rgba.getchannel("A"))
                im = bg
            if im.width > 2200:  # plenty for A4 at 300 dpi; keeps the PDF small
                im = im.resize((2200, round(im.height * 2200 / im.width)))
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            w, h = im.size
    except Exception:
        return None
    scale = min(width / w, max_height / h)
    buf.seek(0)
    pic = RLImage(buf, width=w * scale, height=h * scale)
    pic.hAlign = "LEFT"
    return pic


def _chart(o: dict, data: bytes | None, width: float) -> list:
    title = o.get("title") or o.get("caption") or ""
    head = [_title(title)] if title else []
    pic = _picture(data, width, 120 * mm if o.get("kind") == "plot" else 95 * mm) if data else None
    if pic is None:
        if o.get("kind") != "plot":
            return []
        note = tr("The chart is on the result page (open the PDF from there to include it).")
        return [KeepTogether(head + [Paragraph(_x(note), _styles()["small"])]), Spacer(0, 6)]
    cap = [Paragraph(_x(o["caption"]), _styles()["small"])] if o.get("kind") == "image" and o.get("caption") and o.get("title") else []
    return [KeepTogether(head + [pic] + cap), Spacer(0, 8)]


def output_flowables(outputs: list, width: float, decimal: str = ".", picture=None) -> list:
    """Everything a job showed, in order, as flowables ``width`` wide. Charts and pictures come from
    ``picture(index, output) -> bytes | None``; downloads and videos are left out."""
    out, i, pictures = [], 0, 0
    while i < len(outputs):
        o, kind = outputs[i], outputs[i].get("kind")
        if kind == "metric":
            group = []
            while i < len(outputs) and outputs[i].get("kind") == "metric":
                group.append(outputs[i])
                i += 1
            out += [_metrics(group, width, decimal), Spacer(0, 6)]
            continue
        if kind == "html":
            out += html_flowables(o.get("html", ""), width) + [Spacer(0, 3)]
        elif kind == "alert":
            out += [_alert(o, width), Spacer(0, 6)]
        elif kind == "text":
            out += [KeepTogether(_text(o, width)), Spacer(0, 6)]
        elif kind == "table":
            out += _data_table(o, width, decimal) + [Spacer(0, 8)]
        elif kind in ("plot", "image") and pictures < MAX_PICTURES:
            data = picture(i, o) if picture else None
            pictures += bool(data)
            out += _chart(o, data, width)
        i += 1
    return out


# --- documents ----------------------------------------------------------------------------------


def _doc(info: ReportInfo, story: list) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
                            title=info.title, author=info.run_by or info.printed_by, subject=info.tool, creator="MISTER PLIS")
    canvas_cls = _canvas_class(info)
    canvas_cls._mp_margin = MARGIN
    doc.build(story, canvasmaker=canvas_cls)
    return buf.getvalue()


def _width() -> float:
    return A4[0] - 2 * MARGIN


def results_pdf(outputs: list, info: ReportInfo, picture=None) -> bytes:
    """One job's results on A4: who ran it, when, with which settings, then everything it showed
    (charts and pictures from ``picture(index, output)``, see :func:`output_flowables`)."""
    lay = _Layout(A4, False, 8, 0.8, MARGIN)
    return _doc(info, _meta_flowables(info, lay, 0, 0, "") + output_flowables(outputs, _width(), info.decimal, picture))


def protocol_pdf(items: list, info: ReportInfo) -> bytes:
    """Several results, each with a tick box, a heading and its settings — for the bench.

    ``items``: ``[{"heading": str, "tool": str, "settings": [(label, text)], "outputs": [...]}]`` — the heading
    names what was made ("NaCl · 150 mM"), ``tool`` the calculator, shown small above the settings."""
    st = _styles()
    width = _width()
    lay = _Layout(A4, False, 8, 0.8, MARGIN)
    story = _meta_flowables(info, lay, 0, 0, "")
    box = ParagraphStyle("box", parent=st["section"], fontName=fonts()["regular"], textColor=GREY)
    for n, item in enumerate(items, 1):
        head = Table([[Paragraph("☐", box) if _has_glyph("☐") else _Box(), Paragraph(f"{n}. {_x(item['heading'])}", st["section"])]],
                     colWidths=[16, width - 16], hAlign="LEFT")
        head.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                  ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        top = [head]
        line = [f"<b>{_x(item['tool'])}</b>"] if item.get("tool") else []
        line += [f'<font color="{GREY}">{_x(k)}</font> {_x(v)}' for k, v in item.get("settings") or []]
        if line:
            top.append(Paragraph(" · ".join(line), st["small"]))
        top.append(Spacer(0, 4))
        body = output_flowables(item.get("outputs") or [], width, info.decimal)
        story += [CondPageBreak(60 * mm), KeepTogether(top + body[:2]), *body[2:], _Rule(width), Spacer(0, 8)]
    return _doc(info, story)


def _has_glyph(ch: str) -> bool:
    from reportlab.pdfbase import pdfmetrics

    try:
        face = pdfmetrics.getFont(fonts()["regular"]).face
        return ord(ch) in getattr(face, "charToGlyph", {})
    except Exception:
        return False


class _Box(Flowable):
    """An empty tick box, for fonts without ☐."""

    def wrap(self, *_):
        return 10, 10

    def draw(self):
        self.canv.setStrokeColor(GREY)
        self.canv.setLineWidth(0.8)
        self.canv.rect(0, 0, 9, 9)


class _Rule(Flowable):
    def __init__(self, width):
        super().__init__()
        self.width = width

    def wrap(self, *_):
        return self.width, 2

    def draw(self):
        self.canv.setStrokeColor("#c9ced6")
        self.canv.setLineWidth(0.5)
        self.canv.line(0, 1, self.width, 1)

