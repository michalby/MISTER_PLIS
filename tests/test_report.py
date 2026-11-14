"""PDF reports of result tables: run details, sorting like the screen, and as few pages as possible."""

import time

import pypdfium2 as pdfium

from mister_plis.prefs import from_cookies
from mister_plis.report import ReportInfo, cell_text, describe_settings, sort_rows, table_pdf
from mister_plis.toolkit import Tool
from mister_plis.toolkit import inputs as I


def _table(n, ncols=5):
    cols = ["Sample"] + [f"conc. [µg/µL] {i}" for i in range(ncols - 1)]
    rows = [[f"WT {r}"] + [round((r * 37 + c * 11) % 97 + 0.1234, 4) for c in range(ncols - 1)] for r in range(n)]
    return {"kind": "table", "title": "Protein", "columns": cols, "numeric": [False] + [True] * (ncols - 1), "rows": rows, "total_rows": n}


def _pdf(out, **kw):
    info = ReportInfo(title=out["title"], tool="Protein plate", job_id="20261019-120000-abcdef", run_by="Anna Kowalska",
                      run_at=time.time(), printed_by="Michał Ł.",
                      params=[("Unit", "µg/mL")])
    return pdfium.PdfDocument(table_pdf(out, info, **kw))


def _text(doc):
    return "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def test_report_has_run_details():
    doc = _pdf(_table(5))
    text = _text(doc)
    for s in ("Protein", "Anna Kowalska", "Michał Ł.", "Unit", "µg/mL", "20261019-120000-abcdef", "page 1 of 1"):
        assert s in text, s
    w, h = doc[0].get_size()
    assert h > w  # a narrow table prints in portrait


def test_wide_table_goes_landscape():
    doc = _pdf(_table(10, ncols=30))
    w, h = doc[0].get_size()
    assert w > h and len(doc) == 1


def _plain_pages(out):
    """Pages the first-choice layout needs, before any tightening."""
    from mister_plis.report import _build, _choose

    body = [[cell_text(v) for v in r] for r in out["rows"]]
    lay, widths = _choose(out["columns"], body, out["numeric"])
    return _build(ReportInfo(title="T"), out["columns"], body, out["numeric"], widths, lay, False, len(body), "")[1]


def test_a_few_extra_rows_are_pulled_back_onto_the_page():
    fits = next(n for n in range(40, 200) if _plain_pages(_table(n + 1)) == 2)
    assert fits > 60
    # a couple of rows over: the layout tightens slightly instead of printing a nearly empty page
    assert len(_pdf(_table(fits + 3))) == 1
    # far over: it stays readable and simply uses another page
    assert len(_pdf(_table(fits + 40))) == 2


def test_sorting_matches_the_screen():
    rows = [["b", 10], ["a", None], ["c", 9], ["d", "2 mM"]]
    assert [r[0] for r in sort_rows(rows, 1, False)] == ["d", "c", "b", "a"]
    assert [r[0] for r in sort_rows(rows, 1, True)] == ["b", "c", "d", "a"]  # empty cells stay last
    assert [r[0] for r in sort_rows([["x10"], ["x9"]], 0, False)] == ["x9", "x10"]
    text = _text(_pdf(_table(4), sort=1, descending=True))
    assert "Sorted by conc. [µg/µL] 0 (descending)" in text


def test_cell_text_matches_screen():
    assert cell_text(1.5e-07) == "1.5e-7" and cell_text(2.5, ",") == "2,5" and cell_text(None) == "" and cell_text(True) == "true"


def test_settings_summary_skips_hidden_and_file_inputs():
    tool = Tool(id="t", name="T", inputs=[
        I.File("data", "Data"),
        I.Select("mode", "Mode", options=[("fit", "Curve fit"), ("exact", "Exact")]),
        I.Number("conc", "Concentration", units=["mM", "µM"]),
        I.Number("k", "Rate", show_if={"mode": "exact"}),
        I.Checkbox("log", "Log scale"),
        I.SampleTable("samples", "Samples", source="data"),
    ])
    s = dict(describe_settings(tool, {"data": ["x"], "mode": "fit", "conc": 2.5, "conc__unit": "µM", "k": 3, "log": True,
                                      "samples": [{"key": 1}, {"key": 2}]}, decimal=","))
    assert s == {"Mode": "Curve fit", "Concentration": "2,5 µM", "Log scale": "yes", "Samples": "2 rows"}


def test_name_cookie():
    assert from_cookies({"name": "Micha%C5%82%20%20B."})["name"] == "Michał B."
    assert from_cookies({"name": "x" * 500})["name"] == "x" * 60
    assert from_cookies({})["name"] == ""


def test_job_records_who_ran_it(client):
    client.cookies.set("name", "Anna%20K.")
    try:
        job = client.post("/api/tools/toy-calc/run", json={"params": {}}).json()
        assert job["user"] == "Anna K."
        page = client.get("/settings").text
        assert 'id="pref-name"' in page and 'value="Anna K."' in page
    finally:
        client.cookies.clear()
        client.cookies.set("lang", "en")


def test_very_wide_table_is_split_into_readable_blocks():
    """A table with dozens of columns (77 K Gaussian components) prints as stacked blocks that each fit the page,
    every block repeating the sample columns, each band's columns kept together — never squeezed letter by letter."""
    from reportlab.platypus import KeepTogether, Table

    from mister_plis import printout

    bands = [632, 653, 670, 680, 690]
    columns = ["excitation", "sample", "replicate", "fit R²"] + [f"{b} {k}" for b in bands for k in ("centre", "FWHM", "height", "area", "area %")]
    rows = [["440 nm", s, f"{s}_R{r}", 0.9965] + [123.4567] * (len(columns) - 4) for s in ("C0D5", "C0D5S") for r in (1, 2, 3)]
    o = {"kind": "table", "title": "Gaussian components per replicate", "columns": columns, "rows": rows,
         "numeric": [False, False, False] + [True] * (len(columns) - 3), "total_rows": len(rows)}
    width = printout._width()

    def tables(flow):
        for f in flow:
            if isinstance(f, Table):
                yield f
            elif isinstance(f, KeepTogether):
                yield from tables(f._content)

    blocks = list(tables(printout.output_flowables([o], width)))
    assert len(blocks) >= 2
    seen = []
    for t in blocks:
        assert sum(t._colWidths) <= width + 0.5
        head = [p.text for p in t._cellvalues[0]]
        assert head[:3] == ["excitation", "sample", "replicate"]
        seen += head[3:]
        bands_here = {h.split()[0] for h in head[3:] if h[0].isdigit()}
        for b in bands_here:  # a band's five columns are in one block
            assert sum(h.startswith(f"{b} ") for h in head) == 5
    assert seen == columns[3:]
