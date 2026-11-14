"""Reagents: the inventory workbook (read, edit, add, dispose, order), info from the lab, GitHub sync with a
cell-by-cell merge of the workbook, and the pages and API."""

import csv
import io
import json
import subprocess

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.table import Table

from mister_plis.errors import ToolError
from modules.inventory.service import Inventory

XLSX = "wykaz_odczynnikow_kompletny.xlsx"
CSVF = "wykaz_odczynnikow_kompletny.csv"
SLOT = [("name", "text"), ("catalog_no", "text"), ("container_size", "number"), ("container_unit", "enum"),
        ("containers_count", "integer"), ("to_order", "boolean"), ("order_amount", "text"), ("ordered", "boolean")]
COLS = ([("label_no", "integer", "", "Nr etykiety", "Label no.", "identification"),
         ("name_pl", "text", "", "Nazwa", "Name (Polish)", "identification"),
         ("name_en", "text", "", "Nazwa angielska", "Name", "identification"),
         ("cas_no", "text", "", "Nr CAS", "CAS number", "identification"),
         ("is_disposed", "boolean", "", "Zużyty", "Disposed", "status"),
         ("disposed_date", "date", "", "Data utylizacji", "Disposed on", "status"),
         ("storage_category_primary", "enum", "A;C;G", "Kategoria", "Storage category", "storage"),
         ("storage_categories", "list", "A;C;G", "Kategorie", "Categories", "storage"),
         ("storage_exact_location", "text", "", "Lokalizacja", "Exact location", "storage"),
         ("hazard_priority", "enum", "NISKI;WYSOKI", "Priorytet", "Hazard priority", "hazards"),
         ("ghs02_flammable", "boolean", "", "GHS02 łatwopalne", "GHS02 flammable", "hazards"),
         ("ghs07_harmful_irritant", "boolean", "", "GHS07 drażniące", "GHS07 harmful / irritant", "hazards")]
        + [(f"producer_{i}_{k}", t, "mg;g;L" if k == "container_unit" else "", f"{k} {i}", f"{k} {i}", "producers") for i in (1, 2) for k, t in SLOT]
        + [("order_note", "text", "", "Uwaga", "Order note", "ordering"), ("order_requested_by", "text", "", "Kto", "Requested by", "ordering"),
           ("order_requested_date", "date", "", "Kiedy", "Requested on", "ordering")])
HDR = [c[0] for c in COLS]


def _row(**kw):
    base = {"is_disposed": False, "producer_1_to_order": False, "producer_1_ordered": False}
    return [{**base, **kw}.get(h) for h in HDR]


def make_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "reagents"
    ws.append(HDR)
    ws.append(_row(label_no=1, name_pl="aceton", name_en="acetone", cas_no="67-64-1", storage_category_primary="A", storage_categories="A",
                   hazard_priority="WYSOKI", ghs02_flammable=True, ghs07_harmful_irritant=True, producer_1_name="Carl Roth", producer_1_container_size=5,
                   producer_1_container_unit="L", producer_1_containers_count=2))
    ws.append(_row(label_no=2, name_pl="agar", name_en="agar", storage_category_primary="G", storage_categories="G", producer_1_name="Sigma-Aldrich",
                   producer_1_catalog_no="A 5054", producer_2_name="Duchefa", producer_2_to_order=False, producer_2_ordered=False))
    ws.append(_row(label_no=3, name_pl="fenol", name_en="phenol", storage_category_primary="C", storage_categories="C;G", producer_1_name="POCH (Avantor)"))
    ws.add_table(Table(displayName="reagents", ref=f"A1:{ws.cell(row=1, column=len(HDR)).column_letter}4"))
    cs = wb.create_sheet("columns")
    cs.append(["column", "type", "values", "label_pl", "label_en", "group", "description_pl"])
    for c in COLS:
        cs.append(list(c) + [f"opis {c[0]}"])
    sc = wb.create_sheet("storage_categories")
    sc.append(["code", "color_hex", "name"])
    for row in (["A", "#CC0000", "Szafa na ciecze łatwopalne"], ["C", "#7030A0", "Szafa zamknięta na klucz"], ["G", "#D9D9D9", "Szafa standardowa"]):
        sc.append(row)
    wb.save(path / XLSX)
    (path / "AGENTS.md").write_text("notes\n", encoding="utf-8")


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


@pytest.fixture
def inv(tmp_path):
    i = Inventory(tmp_path / "data")
    i.ensure()
    make_workbook(i.repo)
    i.commit("start", "t")
    return i


def _csv_rows(inv):
    return list(csv.DictReader(io.StringIO((inv.repo / CSVF).read_text(encoding="utf-8"))))


def test_reads_the_workbook(inv):
    items = {r["id"]: r for r in inv.items("pl")}
    a = items["1"]
    assert a["_title"] == "aceton" and a["_producers"] == ["Carl Roth"] and a["_ghs"] == ["GHS02 łatwopalne", "GHS07 drażniące"]
    assert a["restock"] == "" and a["producer_1_container_size"] == 5 and inv.items("en")[0]["_title"] == "acetone"
    f = {x["key"]: x for x in inv.fields("en")}
    assert f["storage_category_primary"]["type"] == "choice" and f["storage_category_primary"]["options"] == ["A", "C", "G"]
    assert f["storage_categories"]["type"] == "multi" and f["is_disposed"]["type"] == "bool" and f["producer_1_containers_count"]["integer"]
    assert f["producer_2_name"]["slot"] == 2 and f["producer_2_name"]["slot_key"] == "name" and f["order_note"]["type"] == "longtext"
    assert f["_producers"]["virtual"] and f["_producers"]["options"] == ["Carl Roth", "Duchefa", "POCH (Avantor)", "Sigma-Aldrich"]
    assert [c["code"] for c in inv.categories()] == ["A", "C", "G"]


def test_edit_add_dispose_and_order(inv):
    a = inv.get("1")
    r = inv.save({"storage_exact_location": "szafa A, górna półka", "producer_1_containers_count": "3", "storage_categories": ["A", "C"],
                  "ghs02_flammable": True}, user="Ola", rid="1", base=a["_v"])
    assert r["storage_exact_location"] == "szafa A, górna półka" and r["producer_1_containers_count"] == 3 and r["storage_categories"] == "A;C"
    with pytest.raises(ToolError, match="changed this reagent"):
        inv.save({"storage_exact_location": "x"}, user="Ania", rid="1", base=a["_v"])  # Ola saved meanwhile
    for bad in ({"producer_1_containers_count": "1.5"}, {"storage_category_primary": "Z"}, {"disposed_date": "soon"}, {"name_pl": ""}):
        with pytest.raises(ToolError):
            inv.save(bad, rid="1")
    log = inv.history("1")
    assert log[0]["author"] == "Ola" and log[0]["subject"].startswith("label_no 1 aceton: storage_exact_location")
    # the file: values in place, table, other sheets and the CSV kept up to date
    wb = load_workbook(inv.repo / XLSX)
    assert wb.sheetnames == ["reagents", "columns", "storage_categories"]
    assert wb["reagents"]["A2"].value == 1 and wb["reagents"].cell(row=2, column=HDR.index("storage_exact_location") + 1).value == "szafa A, górna półka"
    rows = _csv_rows(inv)
    assert rows[0]["producer_1_containers_count"] == "3" and rows[0]["ghs02_flammable"] == "TRUE" and rows[1]["producer_1_to_order"] == "FALSE"
    # a new reagent gets the next label number, at the bottom, inside the Excel table
    new = inv.save({"name_pl": "etanol", "storage_category_primary": "A", "producer_1_name": "POCH (Avantor)"}, user="Ola")
    assert new["id"] == "4" and new["is_disposed"] is False
    wb = load_workbook(inv.repo / XLSX)
    assert wb["reagents"]["A5"].value == 4 and wb["reagents"].tables["reagents"].ref.endswith("5")
    assert [r["label_no"] for r in _csv_rows(inv)] == ["1", "2", "3", "4"]
    # ordering, for one producer: to order → ordered → arrived
    r = inv.set_restock("2", 2, "needed", "Kasia", amount="2 × 500 g")
    assert r["producer_2_to_order"] is True and r["producer_2_order_amount"] == "2 × 500 g" and r["restock"] == "needed"
    assert r["order_requested_by"] == "Kasia"
    assert inv.set_restock("2", 2, "ordered", "Kasia")["restock"] == "ordered"
    r = inv.set_restock("2", 2, "", "Kasia", count="4")
    assert r["restock"] == "" and r["producer_2_containers_count"] == 4 and r["producer_2_order_amount"] is None
    # disposed: the row stays, marked
    r = inv.dispose("3", "Ola")
    assert r["is_disposed"] is True and len(r["disposed_date"]) == 10
    assert inv.dispose("3", "Ola", undo=True)["is_disposed"] is False
    assert len(inv.items()) == 4


def test_columns_and_display(inv):
    f = {x["key"]: x for x in inv.fields("pl")}
    assert f["_title"]["virtual"] and "hidden" not in f["cas_no"]
    inv.set_columns([{"key": "storage_exact_location", "label_pl": "Gdzie dokładnie", "label_en": "Where exactly"}],
                    {"quick": ["_to_order", "_producers", "nonsense"], "list": ["label_no", "name_pl"], "hidden": ["cas_no"]}, "Ola")
    f = {x["key"]: x for x in inv.fields("pl")}
    assert f["storage_exact_location"]["label_pl"] == "Gdzie dokładnie" and f["cas_no"]["hidden"]
    cfg = json.loads((inv.repo / "mister_plis.json").read_text(encoding="utf-8"))
    assert cfg["quick"] == ["_to_order", "_producers"] and cfg["list"] == ["label_no", "name_pl"] and cfg["key"] == "label_no"


def test_info_from_the_lab(inv):
    i = inv.add_info("Zostały dwie butelki", user="Ola", reagent="1", page="/reagents/1")
    j = inv.add_info("obchód: w lodówce brak agaru...\n" * 300, user="Ania")
    assert i["reagent"] == "1" and i["reagent_name"] == "aceton" and (inv.repo / "info" / f"{i['id']}.json").exists()
    assert [x["id"] for x in inv.infos("1")] == [i["id"]] and len(inv.infos()) == 2
    md = inv.info_markdown()
    assert "dwie butelki" in md and "label_no 1" in md and "obchód" in md
    inv.set_info(i["id"], "done", "Kasia")
    assert "dwie butelki" not in inv.info_markdown()
    inv.delete_info(j["id"])
    assert len(inv.infos()) == 1
    with pytest.raises(ToolError):
        inv.add_info("  ")


def _cell(path, rid, col):
    ws = load_workbook(path / XLSX)["reagents"]
    hdr = [c.value for c in ws[1]]
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == rid:
            return ws.cell(row=r, column=hdr.index(col) + 1).value


def _edit(path, rid, col, value, msg):
    wb = load_workbook(path / XLSX)
    ws = wb["reagents"]
    hdr = [c.value for c in ws[1]]
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == rid:
            ws.cell(row=r, column=hdr.index(col) + 1).value = value
    wb.save(path / XLSX)
    _git(path, "commit", "-qam", msg)
    _git(path, "push", "-q", "origin", "HEAD:main")


def test_sync_merges_the_workbook_cell_by_cell(tmp_path):
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    other = tmp_path / "other"  # another agent / person working on the repository
    _git(tmp_path, "clone", "-q", str(remote), str(other))
    make_workbook(other)
    _git(other, "add", "-A"); _git(other, "commit", "-qm", "start"); _git(other, "push", "-q", "origin", "HEAD:main")

    inv = Inventory(tmp_path / "data", str(remote), "main")
    inv.save_settings(push=False)
    assert inv.sync("Ola")["ok"] and len(inv.items()) == 3
    # different cells changed here and on GitHub: both kept
    inv.save({"storage_exact_location": "szafa A"}, user="Ola", rid="1")
    _git(other, "pull", "-q")
    _edit(other, 2, "storage_exact_location", "półka 3", "agar moved")
    r = inv.sync("Ola")
    assert r["ok"], r
    assert inv.get("1")["storage_exact_location"] == "szafa A" and inv.get("2")["storage_exact_location"] == "półka 3"
    assert {x["label_no"]: x["storage_exact_location"] for x in _csv_rows(inv)} == {"1": "szafa A", "2": "półka 3", "3": ""}
    assert "Ola" not in _git(remote, "log", "--format=%an", "main")
    inv.save_settings(push=True)
    assert inv.sync("Ola")["ok"]
    assert "Ola" in _git(remote, "log", "--format=%an", "main") and inv.status()["ahead"] == 0
    _git(other, "pull", "-q")
    assert _cell(other, 1, "storage_exact_location") == "szafa A"
    # the same cell changed differently: nothing changes here, the cell is named
    inv.save({"storage_exact_location": "szafa B"}, user="Ola", rid="3")
    _edit(other, 3, "storage_exact_location", "szafa C", "fenol moved")
    r = inv.sync("Ola")
    assert not r["ok"] and "label_no 3, storage_exact_location" in r["steps"][-1]["output"]
    assert inv.get("3")["storage_exact_location"] == "szafa B" and not (inv.repo / ".git" / "MERGE_HEAD").exists()


def test_without_a_workbook(tmp_path):
    inv = Inventory(tmp_path / "data")
    assert inv.items() == [] and inv.fields() == [] and not inv.sync()["ok"]
    with pytest.raises(ToolError, match="isn't here yet"):
        inv.save({"name_pl": "x"})


# ---- pages and API ------------------------------------------------------------------------------

@pytest.fixture
def app_inv(client):
    from mister_plis import app as app_mod

    svc = app_mod.modules.get("inventory")
    inv = svc.inventory
    inv.ensure()
    if not (inv.repo / XLSX).exists():
        make_workbook(inv.repo)
        inv.commit("start", "t")
    return inv


def test_pages_and_info_button_only_on_reagents_pages(client, app_inv):
    page = client.get("/reagents").text
    assert 'href="/reagents"' in page and 'id="rg-info-btn"' in page and 'id="fb-btn"' in page and "/m/inventory/static/reagents.js" in page
    for url in ("/reagents/order", "/reagents/info", "/reagents/new", "/reagents/1", "/reagents/1/edit"):
        r = client.get(url)
        assert r.status_code == 200 and 'id="rg-info-btn"' in r.text, url
    home = client.get("/").text
    assert 'href="/reagents"' in home and 'id="rg-info-btn"' not in home
    # the GitHub sync and the fields are on the inventory's own Settings tab
    assert client.get("/reagents/setup", follow_redirects=False).headers["location"] == "/settings#inventory"
    assert 'id="rg-sync"' in client.get("/settings").text and "reagents_admin.js" in client.get("/settings").text
    assert 'id="rg-fields"' in client.get("/settings").text
    assert "no such reagent" in client.get("/reagents/999").text


def test_api_round_trip(client, app_inv):
    client.cookies.set("name", "Ola")
    try:
        d = client.get("/api/reagents").json()
        assert d["ready"] and d["config"]["key"] == "label_no" and any(f["key"] == "_ghs" for f in d["fields"])
        one = client.get("/api/reagents/1").json()
        v = one["item"]["_v"]
        ok = client.post("/api/reagents/1", json={"values": {"storage_exact_location": "szafa A"}, "base": v})
        assert ok.status_code == 200 and ok.json()["storage_exact_location"] == "szafa A"
        bad = client.post("/api/reagents/1", json={"values": {"storage_exact_location": "x"}, "base": v})
        assert bad.status_code == 422 and "changed this reagent" in bad.json()["error"]
        assert client.post("/api/reagents", json={"values": {"name_pl": ""}}).status_code == 422
        new = client.post("/api/reagents", json={"values": {"name_pl": "Tris", "producer_1_name": "Roth"}}).json()
        assert int(new["id"]) >= 4
        r = client.post("/api/reagents/2/restock", json={"slot": 1, "state": "needed", "amount": "1 kg", "note": "the cheap one"}).json()
        assert r["restock"] == "needed" and r["order_note"] == "the cheap one"
        x = client.get("/api/reagents/order.xlsx")
        assert x.status_code == 200 and x.content[:2] == b"PK"
        assert "agar" in client.get("/api/reagents/order.csv").content.decode("utf-8-sig")
        # printed like every other list: the app's own PDF, only what is still to order, without the State column
        pdf = client.get("/api/reagents/order.pdf")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf.content)
        text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
        assert "agar" in text and "Sigma-Aldrich" in text and "To order" in text and "State" not in text
        assert client.get("/api/reagents/order.txt").status_code == 404
        assert client.get("/api/reagents/inventory.xlsx").content[:2] == b"PK"
        assert "label_no" in client.get("/api/reagents/inventory.csv").text
        info = client.post("/api/reagents/info", json={"text": "only two bottles left", "reagent": "1"}).json()
        assert info["user"] == "Ola" and "only two bottles left" in client.get("/api/reagents/info.md").text
        assert client.post(f"/api/reagents/info/{info['id']}", json={"status": "done"}).json()["status"] == "done"
        assert client.post(f"/api/reagents/{new['id']}/dispose", json={}).json()["is_disposed"] is True
        assert client.post("/api/reagents/fields", json={"display": {"quick": ["_to_order", "is_disposed"]}}).json()["config"]["quick"] == ["_to_order", "is_disposed"]
        st = client.get("/api/reagents/status").json()
        assert st["enabled"] is False and st["has_workbook"] and st["reagents"] >= 4
        assert client.post("/api/reagents/settings", json={"auto_minutes": 7}).status_code == 422
    finally:
        client.cookies.delete("name")


def test_link_to_the_solution_calculator(client, app_inv):
    """A reagent's page links to the solution calculator with its name and molar mass filled in — only while that tool
    is loaded (the lab's `molarity` is not, in the tests), filling in only the inputs the tool has."""
    from urllib.parse import parse_qs, urlsplit

    from mister_plis import app as app_mod

    calc = app_mod.modules.get("inventory").calculator
    assert calc.tool_id == "" and client.get("/api/reagents/1").json()["calculator"] == ""  # none chosen: no button
    calc.tool_id = "toy-calc"  # the test tools' calculator: compound, name and molar mass, but no purity or density
    try:
        link = urlsplit(client.get("/api/reagents/1").json()["calculator"])
        assert link.path == "/tool/toy-calc"
        assert parse_qs(link.query, keep_blank_values=True) == {"compound": ["custom"], "new_name": ["acetone"], "mw": [""]}
        client.cookies.set("lang", "pl")  # the name as the page shows it
        assert "new_name=aceton&" in client.get("/api/reagents/1").json()["calculator"]
        assert client.get(link.path).status_code == 200
    finally:
        calc.tool_id = ""
        client.cookies.set("lang", "en")
    assert client.get("/api/consumables/1").json().get("calculator", "") == ""  # consumables are not weighed out


def test_calculator_fills_in_what_the_tool_has():
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit

    from mister_plis.toolkit import Tool, inputs as I
    from modules.inventory.calculator import Calculator

    full = Tool(id="solutions", name="Solutions", inputs=[
        I.Select("compound", "Compound", options=[("nacl", "NaCl"), ("custom", "Other")]), I.Text("new_name", "Name"),
        I.Number("mw", "Molar mass", required=False), I.Number("purity", "Purity", default=100, required=False),
        I.Number("density", "Density", required=False)])
    bare = Tool(id="bare", name="Bare", inputs=[I.Number("mw", "Molar mass")])
    calc = Calculator(SimpleNamespace(get={"solutions": full, "bare": bare}.get), "solutions")

    def q(**item):
        link = calc.link(item)
        assert urlsplit(link).path == "/tool/solutions"
        return {k: v[0] for k, v in parse_qs(urlsplit(link).query, keep_blank_values=True).items()}

    assert q(_title="kwas octowy 99,8%", molar_mass_g_mol=60.052, purity_percent=99.8) == {
        "compound": "custom", "new_name": "kwas octowy 99,8%", "mw": "60.052", "purity": "99.8", "density": ""}
    # no purity known (or a wrong one): 100 %, not the purity of the reagent the calculator was last used with
    assert q(_title="NaCl", molar_mass_g_mol=58.44)["purity"] == "100"
    assert q(_title="x", purity_percent=150)["purity"] == "100" and q(_title="x", purity_percent="96,5")["purity"] == "96.5"
    assert q(_title="agar", molar_mass_g_mol=None)["mw"] == "" and q(_title="x", molar_mass_g_mol=100.0)["mw"] == "100"
    # no tool, or one without a compound to fill in: no link
    assert Calculator(SimpleNamespace(get={}.get), "solutions").link({"_title": "x"}) == ""
    assert Calculator(SimpleNamespace(get={"bare": bare}.get), "bare").link({"_title": "x"}) == ""
    assert Calculator(SimpleNamespace(get={"solutions": full}.get), "").link({"_title": "x"}) == ""


# ---- a git repository in a folder on this machine, instead of GitHub ----------------------------------------

def test_sync_with_a_working_folder(tmp_path, monkeypatch):
    """repo = a folder with git initialised and its branch checked out (not a bare repository): the lab's changes
    are written into its files, and edits committed there come in. Uncommitted edits there stop the push."""
    folder = tmp_path / "Lab inventory"
    folder.mkdir()
    _git(folder, "init", "-q", "-b", "main")
    make_workbook(folder)
    _git(folder, "add", "-A"); _git(folder, "commit", "-qm", "start")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # where Windows looks for ~
    inv = Inventory(tmp_path / "data", "~/Lab inventory", "main")  # ~ is expanded
    assert inv.folder == folder and inv.status()["folder"] == str(folder)
    assert inv.sync("Ola")["ok"] and len(inv.items()) == 3

    inv.save({"storage_exact_location": "szafa A"}, user="Ola", rid="1")
    r = inv.sync("Ola")
    assert r["ok"], r
    assert "send the lab's changes to the folder" in [s["name"] for s in r["steps"]]
    assert _cell(folder, 1, "storage_exact_location") == "szafa A"  # the folder's own files, updated
    assert _git(folder, "status", "--porcelain") == "" and "Ola" in _git(folder, "log", "--format=%an")

    wb = load_workbook(folder / XLSX)  # someone edits the workbook in the folder and commits
    wb["reagents"].cell(row=3, column=HDR.index("storage_exact_location") + 1).value = "półka 3"
    wb.save(folder / XLSX); _git(folder, "commit", "-qam", "agar moved")
    assert inv.sync("Ola")["ok"] and inv.get("2")["storage_exact_location"] == "półka 3"

    (folder / "AGENTS.md").write_text("someone is typing here\n", encoding="utf-8")  # not committed
    inv.save({"storage_exact_location": "szafa B"}, user="Ola", rid="3")
    r = inv.sync("Ola")
    assert not r["ok"] and "changes nobody has committed yet" in r["steps"][-1]["output"]
    assert (folder / "AGENTS.md").read_text(encoding="utf-8") == "someone is typing here\n" and _cell(folder, 3, "storage_exact_location") is None
    _git(folder, "commit", "-qam", "notes")
    assert inv.sync("Ola")["ok"] and _cell(folder, 3, "storage_exact_location") == "szafa B"


def test_a_folder_that_isnt_a_repository_is_explained(tmp_path):
    (tmp_path / "plain").mkdir()
    for path, words in ((tmp_path / "plain", "isn't a git repository"), (tmp_path / "missing", "There is no folder")):
        inv = Inventory(tmp_path / "data", str(path), "main")
        r = inv.sync("Ola")
        assert not r["ok"] and words in r["steps"][-1]["output"], r


def test_the_list_as_shown_excel_csv_and_pdf(client, app_inv):
    """The downloads over the list carry what it shows: the filtered rows, in its order, with its columns."""
    from openpyxl import load_workbook

    post = lambda fmt, **data: client.post(f"/api/reagents/list.{fmt}", data={"data": json.dumps(data)})
    shown = {"ids": ["3", "1", "999"], "columns": ["label_no", "_title", "storage_categories", "nope"],
             "filters": [["Search", "o"]], "sort": "Name", "desc": True}
    x = post("xlsx", **shown)
    assert x.status_code == 200 and "attachment" in x.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(x.content)).active
    head = [c.value for c in ws[1]]
    assert head[:2] == ["Label no.", "Name"] and len(head) == 3  # the unknown column is left out
    assert [r[0].value for r in ws.iter_rows(min_row=2)] == [3, 1]  # the unknown one is left out; the order is kept
    assert ws.cell(row=2, column=2).value == "phenol"
    c = post("csv", **shown).content.decode("utf-8-sig")
    assert c.splitlines()[1].startswith("3;phenol;C, G") and "agar" not in c
    # the PDF: the app's own look, the filters named, the columns shown in the list by default
    p = post("pdf", **shown)
    assert p.status_code == 200 and p.content[:4] == b"%PDF" and p.headers["content-type"] == "application/pdf"
    assert post("txt", **shown).status_code == 404
    assert client.post("/api/reagents/list.pdf", data={"data": "[1]"}).status_code == 422


def test_what_goes_on_the_pdf_is_a_setting(client, app_inv, monkeypatch):
    from mister_plis import report
    from modules.inventory import web

    d = client.get("/api/reagents").json()
    assert d["config"]["pdf"] == {"source": "list", "columns": ["label_no", "_title", "storage_exact_location", "_producers"],
                                  "filters": True, "size": "normal"}
    pdf = {"source": "chosen", "columns": ["_title", "storage_exact_location", "no_such_column", "_title"], "filters": False, "size": "large"}
    try:
        saved = client.post("/api/reagents/fields", json={"display": {"pdf": pdf}}).json()["config"]["pdf"]
        assert saved == {"source": "chosen", "columns": ["_title", "storage_exact_location"], "filters": False, "size": "large"}
        # a bad value keeps what was there
        assert client.post("/api/reagents/fields", json={"display": {"pdf": {"size": "huge"}}}).json()["config"]["pdf"]["size"] == "large"
        assert web.shown_table(app_inv, {"ids": ["1"], "columns": ["label_no"]}, "en", pdf=True)["columns"] == ["Name", "Exact location"]
        assert web.shown_table(app_inv, {"ids": ["1"], "columns": ["label_no"]}, "en")["columns"] == ["Label no."]  # Excel: as shown
        seen = {}
        real = report.table_pdf
        monkeypatch.setattr(report, "table_pdf", lambda table, info, **kw: (seen.update(info=info, table=table, **kw), real(table, info, **kw))[1])
        r = client.post("/api/reagents/list.pdf", data={"data": json.dumps({"ids": ["1", "2"], "filters": [["Exact location", "szafa A"]]})})
        assert r.status_code == 200 and seen["size"] == 11 and seen["info"].params == [] and seen["info"].title == "Reagents"
        assert seen["table"]["columns"] == ["Name", "Exact location"] and len(seen["table"]["rows"]) == 2
        client.post("/api/reagents/fields", json={"display": {"pdf": {"filters": True, "size": "normal"}}})
        client.post("/api/reagents/list.pdf", data={"data": json.dumps({"ids": ["1"], "filters": [["Exact location", "szafa A"]]})})
        assert seen["info"].title == "szafa A" and seen["info"].params == [("Exact location", "szafa A")] and seen["size"] == 8
        assert seen["info"].params_caption == "FILTERS" and seen["info"].tool == "Reagent inventory"
    finally:
        client.post("/api/reagents/fields", json={"display": {"pdf": {"source": "list", "filters": True, "size": "normal"}}})


def test_old_settings_without_a_pdf_part_still_read(tmp_path):
    inv = Inventory(tmp_path / "data")
    inv.ensure()
    make_workbook(inv.repo)
    (inv.repo / "mister_plis.json").write_text(json.dumps({"quick": ["is_borrowed"], "list": ["label_no", "_title"]}), encoding="utf-8")
    assert inv.config()["list"] == ["label_no", "_title"] and inv.pdf_config()["source"] == "list"
    (inv.repo / "mister_plis.json").write_text(json.dumps({"pdf": "nonsense"}), encoding="utf-8")
    assert inv.pdf_config()["columns"] == ["label_no", "_title", "storage_exact_location", "_producers"]
