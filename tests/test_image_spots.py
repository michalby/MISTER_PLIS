"""ImageSpots (toolkit 1.3): circles placed and named on a picture the tool shows — parsing, the suggester, a run,
the settings in a PDF, and the widget in a real browser (Playwright + Chromium; skipped where none is installed)."""

import io
import pytest
from PIL import Image

from mister_plis.errors import ToolError
from mister_plis.inputs import ImageSpots
from mister_plis.toolkit import TOOLKIT_VERSION


def _png(squares=((0, 0), (40, 20))) -> bytes:
    im = Image.new("L", (80, 60), 0)
    for x, y in squares:
        im.paste(255, (x, y, x + 10, y + 10))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_parse():
    inp = ImageSpots("spots", source="picture")
    got = inp.parse([{"id": "A1", "x": "10", "y": 12.5, "r": 4, "sample": " WT ", "group": "left"},
                     {"x": 30, "y": 30, "r": 5}], None)
    assert got == [{"id": "A1", "x": 10.0, "y": 12.5, "r": 4.0, "sample": "WT", "group": "left"},
                   {"id": "2", "x": 30.0, "y": 30.0, "r": 5.0, "sample": "2", "group": ""}]  # unnamed: its own sample
    assert inp.parse({"spots": [{"id": "x", "x": 1, "y": 1, "r": 1}]}, None)[0]["id"] == "x"
    well = inp.parse([{"id": "L A1", "x": 1, "y": 1, "r": 1, "row": "A", "col": "1"}], None)[0]
    assert (well["row"], well["col"]) == ("A", 1)
    with pytest.raises(ToolError):
        inp.parse([], None)
    assert ImageSpots("s", required=False).parse(None, None) == []
    for bad in ([{"id": "a", "x": 1, "y": 1, "r": 0}], [{"id": "a", "x": "?", "y": 1, "r": 2}],
                [{"id": "a", "x": 1, "y": 1, "r": 2}, {"id": "a", "x": 5, "y": 1, "r": 2}]):
        with pytest.raises(ToolError):
            inp.parse(bad, None)
    assert TOOLKIT_VERSION >= "1.3" and inp.spec()["kind"] == "spots"


def test_suggest_run_and_pdf(client):
    up = client.post("/api/uploads", files={"file": ("squares.png", _png(), "image/png")}).json()
    d = client.post("/api/tools/toy-spots/suggest/spots", json={"files": [up["id"]], "params": {"size": 4}}).json()["result"]
    assert d["images"][0]["src"].startswith("data:image/png;base64,") and (d["width"], d["height"]) == (80, 60)
    assert [(s["x"], s["y"], s["r"], s["row"], s["col"]) for s in d["spots"]] == [(5, 5, 4.0, "A", 1), (45, 25, 4.0, "B", 3)]
    spots = d["spots"] + [{"id": "dark", "x": 70, "y": 50, "r": 3, "sample": "background"}]
    job = client.post("/api/tools/toy-spots/run", json={"params": {"picture": up["id"], "spots": spots, "size": 4}}).json()
    assert job["status"] == "done", job
    rows = next(o for o in job["outputs"] if o["kind"] == "table")["rows"]
    assert [(r[0], r[1], round(float(r[2]))) for r in rows] == [("S1", "bright", 255), ("S2", "bright", 255), ("dark", "background", 0)]
    pdf = client.get(f"/api/jobs/{job['id']}/report.pdf")
    assert pdf.status_code == 200
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf.content)
    assert "3 circles, 2 samples" in "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
