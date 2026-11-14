import json


def _pdf_text(pdf: bytes) -> str:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    return "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def test_pages(client):
    for url in ("/", "/jobs", "/settings", "/feedback", "/guide", "/tool/does-not-exist"):
        r = client.get(url)
        assert r.status_code == 200, url
    tools = client.get("/api/tools").json()
    assert not tools["broken"]
    for t in tools["tools"]:
        r = client.get(f"/tool/{t['id']}")
        assert r.status_code == 200 and t["name"] in r.text


def test_static_and_plotly(client):
    assert client.get("/static/css/app.css").status_code == 200
    r = client.get("/vendor/plotly.min.js")
    assert r.status_code == 200 and len(r.content) > 1_000_000


def test_upload_suggest_run_download(client, tmp_path):
    csv = tmp_path / "run1.CSV"
    csv.write_text("sample,value\nwt,0.247\nwt,0.251\n", encoding="utf-8")
    with csv.open("rb") as f:
        up = client.post("/api/uploads", files={"file": ("run1.CSV", f, "text/csv")}).json()
    rows = client.post("/api/tools/toy-table/suggest/samples", json={"files": [up["id"]]}).json()["result"]
    assert [r["sample"] for r in rows] == ["wt", "wt"]
    assert client.post("/api/tools/toy-table/suggest/nope", json={}).status_code == 404
    job = client.post("/api/tools/toy-table/run", json={"params": {"files": [up["id"]], "samples": rows}}).json()
    assert job["status"] == "done", job
    # every table offers an .xlsx download
    t = next(o for o in job["outputs"] if o["kind"] == "table")
    assert t["download"]["name"].endswith(".xlsx") and t["printable"]
    r = client.get(t["download"]["url"] + "?download=1")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.content[:2] == b"PK"
    # … no PDF per table: one PDF of the whole result, charts included when the page sends them
    assert "pdf" not in t and job["report"]
    r = client.get(job["report"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    assert _pdf_text(r.content).count("The chart is on the result page") == 1
    import base64
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (800, 400), "#2a78d6").save(buf, format="PNG")
    plot = next(i for i, o in enumerate(job["outputs"]) if o["kind"] == "plot")
    charts = json.dumps({str(plot): "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), "x": "junk", "99": "data:image/png;base64,!!"})
    r = client.post(job["report"], files={"charts": (None, charts)})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert "The chart is on the result page" not in _pdf_text(r.content) and b"/Subtype /Image" in r.content
    listed = client.get("/api/jobs").json()["jobs"]
    assert any(j["id"] == job["id"] for j in listed)
    assert client.get(f"/api/jobs/{job['id']}").json()["files"]["files"][0]["name"] == "run1.CSV"
    # a suggester that can't read the file reports the problem instead of crashing
    bad = client.post("/api/tools/toy-table/suggest/samples", json={"files": [up["id"]], "params": {}})
    assert bad.status_code == 200
    junk = tmp_path / "notes.txt"
    junk.write_text("not a table", encoding="utf-8")
    with junk.open("rb") as f:
        bad_up = client.post("/api/uploads", files={"file": ("notes.txt", f, "text/plain")}).json()
    rows = [{"key": f"{bad_up['id']}:0", "include": True, "sample": "x"}]
    job = client.post("/api/tools/toy-table/run", json={"params": {"files": [bad_up["id"]], "samples": rows}}).json()
    assert job["status"] == "failed" and "not a “sample,value” table" in job["error"] and not job["traceback"]


def test_path_traversal_blocked(client):
    assert client.get("/api/jobs/..%2F..%2Fetc/files/passwd").status_code == 404
    assert client.get("/api/uploads/../../etc/table").status_code == 404


def test_system(client):
    d = client.get("/api/system").json()
    assert "git" in d and d["server"]["tools"] >= 2
    v = client.get("/api/version").json()
    assert "commit" in v


def test_molar_compound_list(client):
    page = client.get("/tool/toy-calc").text
    assert "Putrescine dihydrochloride" not in page
    r = client.post("/api/tools/toy-calc/action/save", json={"params": {"new_name": "Putrescine dihydrochloride", "mw": "161.07"}})
    assert r.status_code == 200 and r.json()["reload"] and "Saved" in r.json()["message"]
    assert "Putrescine dihydrochloride" in client.get("/tool/toy-calc").text  # in the dropdown after a reload
    job = client.post("/api/tools/toy-calc/run", json={"params": {"compound": "user:Putrescine dihydrochloride", "conc": "1", "conc__unit": "M",
                                                                   "volume": "10", "volume__unit": "mL"}}).json()
    assert job["status"] == "done" and job["outputs"][0]["value"] == "1.611"
    assert client.post("/api/tools/toy-calc/action/save", json={"params": {"new_name": "", "mw": "1"}}).status_code == 422
    r = client.post("/api/tools/toy-calc/action/remove", json={"params": {"remove_which": "user:Putrescine dihydrochloride"}})
    assert r.status_code == 200
    assert "Putrescine dihydrochloride" not in client.get("/tool/toy-calc").text
    assert client.post("/api/tools/toy-calc/action/nope", json={}).status_code == 404


def test_saved_names_cannot_break_the_tool_page(client):
    name = "</script><script>alert(1)</script>"
    client.post("/api/tools/toy-calc/action/save", json={"params": {"new_name": name, "mw": "10"}})
    try:
        page = client.get("/tool/toy-calc").text
        assert name not in page and page.count("</script>") == page.count("<script")
        job = client.post("/api/tools/toy-calc/run", json={"params": {"compound": f"user:{name}", "conc": "1", "volume": "1"}}).json()
        assert job["status"] == "done" and "<script>" not in job["outputs"][-1]["html"]
    finally:
        client.post("/api/tools/toy-calc/action/remove", json={"params": {"remove_which": f"user:{name}"}})


def test_protocol_pdf(client):
    import json

    import pypdfium2 as pdfium

    def text(pdf):
        doc = pdfium.PdfDocument(pdf)
        return "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))

    # calculators: collect results, print them together; each item gets its settings
    items = []
    assert client.get("/api/jobs/nope/report.pdf").status_code == 404
    for tid, params in [("toy-calc", {"compound": "salt", "conc": 150, "volume": 500}),
                        ("toy-calc", {"compound": "sugar", "conc": 10, "volume": 50})]:
        j = client.post(f"/api/tools/{tid}/run", json={"params": params}).json()
        assert j["status"] == "done" and j["report"]
        items.append({"tool_id": tid, "params": params, "outputs": j["outputs"], "heading": j["tool_name"]})
    items.append({"tool_id": "gone", "heading": "<b>Old</b>", "outputs": [{"kind": "html", "html": "<p>x <script>y</script> & z</p>"}]})
    r = client.post("/api/protocol.pdf", data={"data": json.dumps({"title": "Buffers", "items": items})})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    t = text(r.content)
    for s in ("Buffers", "1. Salt · 150 mM", "Toy solution", "4.383", "Concentration", "2. Sugar · 10 mM", "3. <b>Old</b>", "x y & z"):
        assert s in t, s
    assert client.post("/api/protocol.pdf", data={"data": "{}"}).status_code == 422
    assert client.post("/api/protocol.pdf", data={"data": "not json"}).status_code == 422
