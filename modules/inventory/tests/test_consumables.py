"""Consumables: a second workbook in the reagents' repository — started by itself, edited and ordered like the
reagents, one list of info from the lab for both, one GitHub sync merging both workbooks cell by cell."""

import csv
import io
import json

import pytest
from openpyxl import load_workbook

from mister_plis.errors import ToolError
from modules.inventory.service import Consumables, Inventory

from test_reagents import XLSX, _git, make_workbook

CXLSX, CCSV = "consumables.xlsx", "consumables.csv"


@pytest.fixture
def pair(tmp_path):
    inv = Inventory(tmp_path / "data")
    cons = Consumables(inv)
    inv.ensure()
    make_workbook(inv.repo)
    inv.commit("start", "t")
    return inv, cons


def _csv(cons):
    return list(csv.DictReader(io.StringIO((cons.repo / CCSV).read_text(encoding="utf-8"))))


def test_the_workbook_starts_by_itself(tmp_path, pair):
    # no repository yet: nothing is made up
    lone = Consumables(Inventory(tmp_path / "other"))
    assert lone.book() is None and lone.items() == []
    inv, cons = pair
    assert cons.items() == [] and (cons.repo / CXLSX).exists() and (cons.repo / CCSV).exists()
    wb = load_workbook(cons.repo / CXLSX)
    assert wb.sheetnames == ["consumables", "columns"]
    assert inv.history()[0]["subject"] == "Start the consumables inventory"
    f = {x["key"]: x for x in cons.fields("en")}
    assert f["producer_1_product_url"]["type"] == "url" and f["producer_2_avoid"]["type"] == "bool"
    assert f["producer_1_notes"]["type"] == "longtext" and f["producer_3_name"]["slot"] == 3 and "producer_4_name" not in f
    assert f["_producers"]["label"] == "Brands" and "_ghs" not in f and f["item_no"]["label"] == "No."
    assert cons.config()["key"] == "item_no" and inv.config()["key"] == "label_no"
    # the reagents are untouched
    assert len(inv.items()) == 3 and load_workbook(inv.repo / XLSX).sheetnames == ["reagents", "columns", "storage_categories"]


def test_add_edit_order_and_no_longer_used(pair):
    inv, cons = pair
    tips = cons.save({"name_pl": "końcówki 200 µl", "name_en": "pipette tips 200 µl", "category": "końcówki do pipet", "size_spec": "200 µl",
                      "producer_1_name": "Eppendorf", "producer_1_supplier": "Merck", "producer_1_catalog_no": "0030000870",
                      "producer_1_product_url": "https://www.sigmaaldrich.com/PL/pl/product/sigma/z640220", "producer_1_containers_count": "4",
                      "producer_2_name": "NoName", "producer_2_avoid": True, "producer_2_notes": "pękają w pipecie Gilson"}, user="Ola")
    assert tips["id"] == "1" and tips["producer_1_containers_count"] == 4 and tips["_producers"] == ["Eppendorf", "NoName"]
    pvdf = cons.save({"name_pl": "membrana PVDF", "category": "membrany"}, user="Ola")
    assert pvdf["id"] == "2" and pvdf["is_disposed"] is False
    with pytest.raises(ToolError, match="consumable needs a name"):
        cons.save({"name_pl": ""})
    with pytest.raises(ToolError, match="changed this consumable"):
        old = cons.get("1")["_v"]
        cons.save({"storage_place": "szafka 2"}, user="Ola", rid="1")
        cons.save({"storage_place": "szafka 3"}, user="Ania", rid="1", base=old)
    with pytest.raises(ToolError, match="no such consumable"):
        cons.get("99")
    r = cons.set_restock("1", 1, "needed", "Kasia", amount="2 opakowania")
    assert r["restock"] == "needed" and r["order_requested_by"] == "Kasia" and r["producer_1_order_amount"] == "2 opakowania"
    r = cons.set_restock("1", 1, "", "Kasia", count="6")
    assert r["restock"] == "" and r["producer_1_containers_count"] == 6
    with pytest.raises(ToolError):
        cons.set_restock("1", 4, "needed")  # only three brands
    assert cons.dispose("2", "Ola")["is_disposed"] is True
    # its own history, its own trailer; the reagents' history doesn't list it
    assert cons.history("1")[0]["subject"].startswith("item_no 1 końcówki 200 µl:") and inv.history("1") == []
    assert [x["item_no"] for x in _csv(cons)] == ["1", "2"] and _csv(cons)[0]["producer_2_avoid"] == "TRUE"
    assert load_workbook(cons.repo / CXLSX)["consumables"].tables["consumables"].ref.endswith("3")
    cons.set_columns([], {"quick": ["_to_order", "used_for"]}, "Ola")
    assert json.loads((cons.repo / "mister_plis_consumables.json").read_text(encoding="utf-8"))["quick"] == ["_to_order", "used_for"]
    assert inv.config()["quick"] == ["_to_order", "storage_category_primary", "is_borrowed"]


def test_one_list_of_info(pair):
    inv, cons = pair
    cons.save({"name_pl": "bibuła Whatman 3MM"}, user="Ola")
    a = inv.add_info("został ostatni arkusz bibuły", user="Ola", consumable="1", page="/consumables/1")
    b = inv.add_info("aceton się kończy", user="Ola", reagent="1")
    c = inv.add_info("obchód: brak acetonu i końcówek 10 µl", user="Ania")
    assert a["consumable"] == "1" and a["consumable_name"] == "bibuła Whatman 3MM" and a["reagent"] == ""
    assert [i["id"] for i in cons.infos("1")] == [a["id"]] and [i["id"] for i in inv.infos("1")] == [b["id"]]
    assert len(inv.infos()) == len(cons.infos()) == 3
    assert "Consumable: 1" in inv.git("log", "-1", "--format=%B", "--grep=bibuły")[1]
    md = inv.info_markdown()
    assert "the consumable **bibuła Whatman 3MM** (item_no 1)" in md and "label_no 1" in md and c["text"] in md
    with pytest.raises(ToolError):
        inv.add_info("x", consumable="99")


def test_sync_merges_both_workbooks(tmp_path):
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(remote), str(other))
    make_workbook(other)
    _git(other, "add", "-A"); _git(other, "commit", "-qm", "start"); _git(other, "push", "-q", "origin", "HEAD:main")

    inv = Inventory(tmp_path / "data", str(remote), "main")
    cons = Consumables(inv)
    assert cons.book() is None  # not before the repository is here
    r = inv.sync("Ola")
    assert r["ok"] and any(s["name"] == "0 consumables ready" for s in r["steps"]), r
    cons.save({"name_pl": "szkiełka nakrywkowe", "size_spec": "18 × 18 mm"}, user="Ola")
    cons.save({"name_pl": "fiolki HPLC", "size_spec": "2 ml"}, user="Ola")
    assert inv.sync("Ola")["ok"] and cons.status()["others"][0]["rows"] == 2
    # someone else edits another cell of the consumables on GitHub; here, a different cell
    _git(other, "pull", "-q")
    wb = load_workbook(other / CXLSX)
    ws = wb["consumables"]
    hdr = [c.value for c in ws[1]]
    ws.cell(row=3, column=hdr.index("storage_place") + 1).value = "szuflada HPLC"
    wb.save(other / CXLSX)
    _git(other, "commit", "-qam", "vials moved"); _git(other, "push", "-q", "origin", "HEAD:main")
    cons.save({"storage_place": "mikroskop"}, user="Ola", rid="1")
    r = cons.sync("Ola")  # the consumables sync the one repository
    assert r["ok"], r
    assert cons.get("1")["storage_place"] == "mikroskop" and cons.get("2")["storage_place"] == "szuflada HPLC"
    assert {x["item_no"]: x["storage_place"] for x in _csv(cons)} == {"1": "mikroskop", "2": "szuflada HPLC"}
    # the same cell changed differently: named, nothing changed here
    _git(other, "pull", "-q")
    wb = load_workbook(other / CXLSX)
    wb["consumables"].cell(row=2, column=hdr.index("storage_place") + 1).value = "szafa 1"
    wb.save(other / CXLSX)
    _git(other, "commit", "-qam", "coverslips moved"); _git(other, "push", "-q", "origin", "HEAD:main")
    cons.save({"storage_place": "szafa 2"}, user="Ola", rid="1")
    r = inv.sync("Ola")
    assert not r["ok"] and "item_no 1, storage_place" in r["steps"][-1]["output"]
    assert cons.get("1")["storage_place"] == "szafa 2"


# ---- pages and API ------------------------------------------------------------------------------

@pytest.fixture
def app_cons(client):
    from mister_plis import app as app_mod

    svc = app_mod.modules.get("inventory")
    inv = svc.inventory
    inv.ensure()
    if not (inv.repo / XLSX).exists():
        make_workbook(inv.repo)
        inv.commit("start", "t")
    return svc.consumables


def test_pages(client, app_cons):
    page = client.get("/consumables").text
    assert 'data-kind="consumables"' in page and 'data-api="/api/consumables"' in page and 'class="rg-spaces"' in page
    assert 'href="/consumables/order"' in page and 'id="rg-info-btn"' in page and "Add a consumable" in page
    assert 'href="/consumables"' in client.get("/reagents").text and 'href="/consumables"' in client.get("/").text  # sidebar
    for url in ("/consumables/order", "/consumables/info", "/consumables/new"):
        assert client.get(url).status_code == 200, url
    assert "no such consumable" in client.get("/consumables/999").text
    assert 'id="cs-fields"' in client.get("/settings").text


def test_api_round_trip(client, app_cons):
    client.cookies.set("name", "Ola")
    try:
        d = client.get("/api/consumables").json()
        assert d["ready"] and d["config"]["key"] == "item_no" and not any(f["key"] == "_ghs" for f in d["fields"])
        new = client.post("/api/consumables", json={"values": {"name_pl": "membrana PVDF", "producer_1_name": "Millipore",
                                                                "producer_1_catalog_no": "IPVH00010", "producer_1_product_url": "https://example.com/pvdf"}}).json()
        one = client.get(f"/api/consumables/{new['id']}").json()
        assert one["item"]["_title"] == "membrana PVDF" and one["history"]
        bad = client.post(f"/api/consumables/{new['id']}", json={"values": {"name_pl": ""}})
        assert bad.status_code == 422 and "needs a name" in bad.json()["error"]
        r = client.post(f"/api/consumables/{new['id']}/restock", json={"slot": 1, "state": "needed", "amount": "1 rolka"}).json()
        assert r["restock"] == "needed"
        rows = client.get("/api/consumables/order.csv").content.decode("utf-8-sig")
        assert "Millipore" in rows and "IPVH00010" in rows and "https://example.com/pvdf" in rows and "Product code" in rows and "CAS" not in rows
        assert client.get("/api/consumables/inventory.xlsx").content[:2] == b"PK"
        info = client.post("/api/reagents/info", json={"text": "membrany się kończą", "consumable": new["id"]}).json()
        assert info["consumable"] == new["id"]
        assert [i["id"] for i in client.get(f"/api/consumables/{new['id']}").json()["info"]] == [info["id"]]
        assert any(i["id"] == info["id"] for i in client.get("/api/reagents/info").json()["items"])
        st = client.get("/api/reagents/status").json()
        assert st["others"][0]["kind"] == "consumable" and st["others"][0]["rows"] >= 1
        assert client.post(f"/api/consumables/{new['id']}/dispose", json={}).json()["is_disposed"] is True
    finally:
        client.cookies.delete("name")


def test_the_list_as_shown(client, app_cons):
    """Consumables: the same downloads of what the list shows, and their own PDF settings."""
    import json as _json

    new = client.post("/api/consumables", json={"values": {"name_pl": "końcówki 10 µl", "size_spec": "10 µl", "storage_place": "szafka 2"}}).json()
    data = {"data": _json.dumps({"ids": [new["id"]], "columns": ["item_no", "_title", "storage_place"], "filters": [["Place", "szafka 2"]]})}
    c = client.post("/api/consumables/list.csv", data=data).content.decode("utf-8-sig")
    assert c.splitlines() == ["No.;Name;" + c.splitlines()[0].split(";")[2], f"{new['id']};końcówki 10 µl;szafka 2"]
    assert client.post("/api/consumables/list.pdf", data=data).content[:4] == b"%PDF"
    pdf = client.get("/api/consumables").json()["config"]["pdf"]
    assert pdf["source"] == "list" and pdf["columns"][0] == "item_no"
    # each inventory keeps its own
    assert client.get("/api/reagents").json()["config"]["pdf"]["columns"][0] == "label_no"
