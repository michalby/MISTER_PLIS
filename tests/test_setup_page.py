"""The setup page (/setup) and its API, and the Lab setup panel on Settings (docs/LAB_SETUP_PLAN.md)."""

import json
import tomllib

import pytest

from mister_plis import labsetup


@pytest.fixture
def fresh_state(tmp_path, monkeypatch):
    """The session's server, as if it weren't set up yet (with its setup code); put back afterwards."""
    from mister_plis import setupcode

    monkeypatch.setattr(setupcode, "path", lambda: tmp_path / "secrets" / "setup-code")
    setupcode.ensure()
    f = labsetup.state_file()
    before = f.read_text(encoding="utf-8")
    f.write_text('{"format": 1, "state": "new"}', encoding="utf-8")
    yield
    f.write_text(before, encoding="utf-8")


def test_a_new_server_leads_its_pages_to_the_setup_page(client, fresh_state):
    for path in ("/", "/jobs", "/settings", "/tool/toy-calc"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/setup", path
    assert client.get("/api/jobs").status_code == 200 and client.get("/api/version").status_code == 200  # never the API
    page = client.get("/setup").text
    assert "Set up MISTER PLIS for your lab" in page and 'id="setup-skip"' in page and "/static/js/setup.js" in page
    from mister_plis import setupcode

    assert client.post("/api/setup/code", json={"code": setupcode.current()}).status_code == 200  # from another computer
    assert client.post("/api/setup/skip").json()["state"]["status"] == "skipped"
    assert client.get("/", follow_redirects=False).status_code == 200
    assert setupcode.current()  # kept: the lab's first account is made with it (accounts.py)
    client.cookies.delete(setupcode.COOKIE)


def test_the_setup_page_once_set_up(client):
    page = client.get("/setup").text
    assert "Lab setup" in page and 'id="setup-skip"' not in page
    settings = client.get("/settings").text
    assert 'id="lab-setup-panel"' in settings and 'href="/setup"' in settings and "/api/setup/export" in settings


def test_what_the_page_starts_from(client):
    d = client.get("/api/setup").json()
    assert {"lab", "modules", "jobs", "backup", "label_printer", "updates"} <= set(d["current"])
    assert any(f["path"] == "labs/example.toml" for f in d["files"])
    forms = {m["id"]: m for m in d["modules"]}
    assert [f["key"] for f in forms["notebook"]["fields"]] == ["repo", "branch", "auto_sync_minutes", "folders"]
    assert forms["inventory"]["fields"][0]["kind"] == "repository" and forms["timemachine"]["fields"] == []
    # grouped under headings, each module saying what it is for; the calculator is chosen from the loaded tools
    inv = forms["inventory"]
    assert [g["id"] for g in inv["groups"]] == ["", "pages", "tidy"] and [g["folded"] for g in inv["groups"]] == [False, False, True]
    assert {f["group"] for f in inv["fields"]} == {"", "pages", "tidy"} and inv["intro"] and forms["timemachine"]["intro"]
    calc = next(f for f in inv["fields"] if f["key"] == "calculator")
    assert calc["kind"] == "tool" and calc["label"] == "Solution calculator" and "Make a solution" in calc["help"]
    assert {"id": "toy-calc", "name": "Toy solution"} in d["tools"]


def test_reading_a_lab_file(client):
    r = client.post("/api/setup/read", json={"path": "labs/example.toml"}).json()
    assert r["lab"]["module"]["inventory"]["branch"] == "main" and r["source"] == "labs/example.toml"
    assert client.post("/api/setup/read", json={"path": "../config.toml"}).status_code == 422  # only labs/*.toml
    r = client.post("/api/setup/read", json={"text": '[lab]\nname = "A"\nnoise = 1\n', "name": "mine.toml"}).json()
    assert r["lab"] == {"lab": {"name": "A"}} and r["warnings"] and r["source"] == "mine.toml"
    bad = client.post("/api/setup/read", json={"text": "[lab\n"})
    assert bad.status_code == 422 and "TOML" in bad.json()["error"]
    assert client.post("/api/setup/read", json={"url": "http://example.org/x.toml"}).status_code == 422


def test_check_then_set_up(client):
    from mister_plis.app import backups

    before_name, before_state = backups.settings().lab_name, labsetup.state_file().read_text(encoding="utf-8")
    try:
        lab = {"lab": {"name": "Test Lab"}, "backup": {"folder": "/no/such/folder"}}
        plan = client.post("/api/setup/plan", json={"lab": lab, "access": False}).json()
        rows = {r["key"]: r for r in plan["rows"]}
        assert rows["name"]["status"] == "change" and rows["folder"]["status"] == "error" and plan["access"] == []
        assert backups.settings().lab_name == before_name  # a check changes nothing
        assert client.post("/api/setup/plan", json={"lab": {"lab": {"name": 7}}}).status_code == 422
        r = client.post("/api/setup/apply", json={"lab": lab, "source": "labs/test.toml"}, cookies={"name": "Ada"}).json()
        assert {x["key"]: x["status"] for x in r["rows"]} == {"name": "done", "folder": "error"} and not r["restart"]
        assert backups.settings().lab_name == "Test Lab"
        assert r["state"]["status"] == "set_up" and r["state"]["from"] == "labs/test.toml" and r["state"]["by"] == "Ada"
        assert "Test Lab" in client.get("/").text
    finally:
        backups.set_lab_name(before_name)
        labsetup.state_file().write_text(before_state, encoding="utf-8")


def test_the_lab_file_of_this_server_and_of_the_page(client):
    r = client.get("/api/setup/export")
    assert r.headers["content-disposition"].startswith("attachment") and r.headers["content-type"].startswith("application/toml")
    found = tomllib.loads(r.text)
    assert found["lab_file"]["format"] == 1 and "module" in found and labsetup.parse(r.text)[0]
    r = client.post("/api/setup/file", json={"lab": {"lab": {"name": "Smith Lab"}}})
    assert 'filename="smith-lab.toml"' in r.headers["content-disposition"] and tomllib.loads(r.text)["lab"]["name"] == "Smith Lab"


def test_the_page_in_polish(client):
    client.cookies.set("lang", "pl")
    try:
        assert "Konfiguracja laboratorium" in client.get("/setup").text
        rows = client.post("/api/setup/plan", json={"lab": {"lab": {"name": "X"}}, "access": False}).json()["rows"]
        assert rows[0]["label"] == "Nazwa laboratorium"
    finally:
        client.cookies.set("lang", "en")
