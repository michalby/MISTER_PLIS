"""The Settings page (one page, tabs), the Feedback page, the lab's name, and the settings a tool declares
(toolkit 1.1). The tabs' switching in a browser is in test_settings_browser.py."""

import json
import re

import pytest

from mister_plis import toolsettings
from mister_plis.toolkit import RunContext, find_program, tool_setting


def _tabs(page: str) -> list[str]:
    return re.findall(r'role="tab" id="tabbtn-([a-z]+)"', page)


def test_one_page_with_every_tab(client):
    page = client.get("/settings").text
    tabs = _tabs(page)
    assert tabs[:4] == ["you", "exports", "tools", "jobs"] and tabs[-2:] == ["people", "server"]
    assert "inventory" in tabs and tabs.index("inventory") < tabs.index("people")  # a module's own tab, by its order
    for t in tabs:
        assert f'role="tabpanel" id="tab-{t}" data-tab="{t}"' in page
    # what used to be on two pages, each in its place
    for tab, ids in {"you": ["pref-name", "forget-btn"], "exports": ["printer-panel"], "tools": ["tool-sources", "tool-settings"],
                     "jobs": ["storage", "lab-panel", "history-panel", "tm-backup"], "people": ["people-list"],
                     "server": ["lab-name", "git-info", "server-info"], "inventory": ["rg-sync", "rg-tidy", "rg-fields", "cs-fields"]}.items():
        panel = page[page.index(f'id="tab-{tab}"'):]
        panel = panel[:panel.index('role="tabpanel"', 20)] if 'role="tabpanel"' in panel[20:] else panel
        for i in ids:
            assert f'id="{i}"' in panel, (tab, i)
    assert 'data-tab-default="you"' in page and "/static/js/settings.js" in page
    assert "this browser" in page and "whole lab" in page
    assert 'data-tab-default="server"' in client.get("/settings?tab=server").text
    assert 'data-tab-default="you"' in client.get("/settings?tab=nonsense").text


def test_old_addresses_lead_to_the_tabs(client):
    r = client.get("/system", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/settings?tab=server"  # an old #fragment stays the browser's
    page = client.get("/settings").text
    assert json.loads(re.search(r"data-tab-aliases='([^']+)'", page).group(1))["feedback"] == "/feedback"


def test_the_sidebar_has_settings_and_feedback(client):
    page = client.get("/").text
    assert 'href="/settings"' in page and 'href="/feedback"' in page and 'href="/system"' not in page
    fb = client.get("/feedback").text
    assert 'id="fb-list"' in fb and 'id="fb-filter"' in fb and "Feedback from the lab" in fb


def test_the_lab_name(client):
    from mister_plis.app import backups

    try:
        assert client.post("/api/lab/name", json={"lab_name": "  Smith   Lab "}).json()["lab_name"] == "Smith Lab"
        assert "Smith Lab" in client.get("/").text and backups.lab_name() == "Smith Lab"
        assert client.get("/api/lab").json()["lab_name"] == "Smith Lab"
        # the backup settings keep it, and it keeps them
        info = client.get("/api/lab").json()
        client.post("/api/lab", json={"backup_dir": "", "backup_after_days": info["backup_after_days"]})
        assert backups.lab_name() == "Smith Lab"
        assert client.post("/api/lab/name", json={"lab_name": "x" * 61}).status_code == 422
    finally:
        client.post("/api/lab/name", json={"lab_name": ""})
    assert backups.lab_name() == backups.lab  # back to config.toml's (empty in the tests)
    assert "lab toolbox" in client.get("/").text


def test_a_tool_declares_its_settings(client, tmp_path):
    rows = client.get("/api/tools/settings").json()["tools"]
    toy = next(t for t in rows if t["id"] == "toy-table")
    assert [i["name"] for i in toy["inputs"]] == ["program"] and toy["values"] == {"program": ""}
    assert toy["status"] == "The helper program was not found." and toy["source"] == "fixture"
    assert all(t["id"] != "toy-calc" for t in rows)  # only tools that declare settings
    helper = tmp_path / "toy-helper"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    client.cookies.set("name", "Ola")
    try:
        saved = client.post("/api/tools/toy-table/settings", json={"values": {"program": f"  {helper}  "}}).json()
        assert saved["values"] == {"program": str(helper)} and saved["status"] == f"Found: {helper}"
        assert saved["changed"]["changed_by"] == "Ola"
        assert tool_setting("toy-table", "program") == str(helper)
        assert RunContext("j", tmp_path, tool_id="toy-table").setting("program") == str(helper)
        rec = json.loads((toolsettings.folder() / "toy-table.json").read_text(encoding="utf-8"))
        assert rec["format"] == 1 and rec["values"] == {"program": str(helper)}
        # in Polish: the form and the status line
        client.cookies.set("lang", "pl")
        pl = next(t for t in client.get("/api/tools/settings").json()["tools"] if t["id"] == "toy-table")
        assert pl["inputs"][0]["label"] == "Program pomocniczy" and pl["status"] == f"Znaleziono: {helper}"
    finally:
        client.cookies.set("lang", "en")
        client.cookies.delete("name")
        client.post("/api/tools/toy-table/settings", json={"values": {"program": ""}})
    assert client.post("/api/tools/toy-calc/settings", json={"values": {}}).status_code == 404
    assert client.post("/api/tools/nope/settings", json={"values": {}}).status_code == 404


def test_find_program_order(tmp_path, monkeypatch):
    from mister_plis.config import settings

    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("", encoding="utf-8")
    b.write_text("", encoding="utf-8")
    assert find_program("toyprog", [str(b)]) == str(b)  # the candidates
    monkeypatch.setattr(settings, "toyprog_path", str(a), raising=False)
    assert find_program("toyprog", [str(b)]) == str(a)  # config.toml's <name>_path wins over them
    assert find_program("toyprog", [str(b)], configured=str(b)) == str(b)  # the tool's setting wins over config.toml
    assert find_program("toyprog", [str(a)], configured=str(tmp_path / "gone")) is None  # set but not there: not found


def test_a_removed_tool_keeps_its_settings_file(tmp_path, monkeypatch):
    from mister_plis.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "tool-settings").mkdir()
    (tmp_path / "tool-settings" / "gone-tool.json").write_text(json.dumps({"format": 1, "values": {"x": "1"}}), encoding="utf-8")
    assert tool_setting("gone-tool", "x") == "1" and toolsettings.saved("gone-tool") == {"x": "1"}
    assert (tmp_path / "tool-settings" / "gone-tool.json").exists()
    assert toolsettings.saved("../evil") == {}  # a tool id can't reach outside the folder…
    with pytest.raises(ValueError):  # …nor be written there
        toolsettings._file("../evil")


def test_server_tab_says_how_people_reach_it(client, monkeypatch):
    """One computer, nothing to set up per device (0.19.0): the addresses to give a new person, and none of the panels
    for other computers (workers, neighbours, names)."""
    from mister_plis import access

    monkeypatch.setattr(access, "_addresses", lambda: {"192.168.1.42", "fe80::1"})
    page = client.get("/settings", headers={"host": "192.168.1.42:8000"}).text
    panel = page[page.index('id="reach-panel"'):]
    panel = panel[:panel.index("</section>")]
    assert "http://192.168.1.42:8000" in panel and "fe80" not in panel  # IPv4 addresses: what people type
    assert "No accounts yet" in panel  # open server: make an account first
    for gone in ("workers-panel", "services-panel", "names-panel", "server-names", "service-model"):
        assert gone not in page, gone
