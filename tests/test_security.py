"""The fixes from docs/SECURITY_AUDIT.md (Phases 1 and 2): each test fails without its fix."""

from __future__ import annotations

import pytest


# ---- H1: a request must use one of the server's own names (DNS rebinding) --------------------------------------------

def test_a_name_the_server_doesnt_know_is_refused(client):
    """A page elsewhere that points its own name at this server (DNS rebinding) gets nothing — neither a read nor a
    change — even though its requests look same-origin to the browser."""
    evil = {"host": "evil.example:8000", "origin": "http://evil.example:8000", "sec-fetch-site": "same-origin"}
    r = client.post("/api/feedback", json={"kind": "bug", "text": "rebinding"}, headers=evil)
    assert r.status_code == 400 and "evil.example" in r.json()["error"]
    assert client.get("/api/jobs", headers={"host": "evil.example"}).status_code == 400
    page = client.get("/", headers={"host": "evil.example"})
    assert page.status_code == 400 and "config.toml" in page.text
    # a proxy can't smuggle a foreign name in either
    assert client.get("/api/jobs", headers={"x-forwarded-host": "evil.example"}).status_code == 400


def test_ip_addresses_own_names_and_the_machines_names_work(client, monkeypatch):
    from mister_plis import access
    from mister_plis.config import settings

    for host in ("127.0.0.1:8000", "192.168.1.20", "[::1]:8000", "localhost:8000", "testserver"):
        assert client.get("/api/version", headers={"host": host}).status_code == 200, host
    own = sorted(access.own_names())
    assert "localhost" in own and client.get("/api/version", headers={"host": own[-1]}).status_code == 200
    assert client.get("/api/version", headers={"host": "mister-plis.lab.example"}).status_code == 400
    # a name only a proxy gives it: server_names in config.toml (or MISTER_PLIS_SERVER_NAMES)
    monkeypatch.setattr(settings, "server_names", "testserver, Mister-Plis.lab.example, other.example")
    assert client.get("/api/version", headers={"host": "mister-plis.lab.example:443"}).status_code == 200
    assert client.get("/api/version", headers={"host": "other.example"}).status_code == 200
    monkeypatch.setattr(settings, "server_names", "*")  # "*": any name
    assert client.get("/api/version", headers={"host": "anything.example"}).status_code == 200
    monkeypatch.setattr(settings, "server_names", "testserver")
    assert client.get("/api/version", headers={"host": "other.example"}).status_code == 400
    assert client.post("/api/lab/names", json={"names": ["x.example"]}).status_code in (404, 405)  # not a lab setting any more


def test_names_a_lab_saved_before_0_19_still_work(client, monkeypatch, tmp_path):
    """Until 0.19.0 a lab could add names on Settings; a server that did keeps answering to them."""
    from mister_plis import app as app_mod
    from mister_plis.backup import LabSettings

    monkeypatch.setattr(app_mod.backups, "settings", lambda: LabSettings(server_names=["old-proxy.lab.example"]))
    assert client.get("/api/version", headers={"host": "old-proxy.lab.example"}).status_code == 200


def test_the_names_the_network_gives_this_computer_work_without_any_setting(monkeypatch):
    """A colleague who types the name the university's DNS gives the server (or its new name after a rename) gets in
    with nothing set: only names nobody gave this computer need adding."""
    import socket
    import time

    from mister_plis import access

    monkeypatch.setattr(access, "_addresses", lambda: {"10.1.2.3"})
    monkeypatch.setattr(socket, "gethostbyaddr", lambda ip: ("Mac-Studio.Biol.Uni.example.", ["mister-plis.uni.example"], [ip]))
    monkeypatch.setattr(access, "_local_names", lambda: {"localhost", "renamed-mac", "renamed-mac.local"})
    monkeypatch.setattr(access, "_own_at", -1e9)
    monkeypatch.setattr(access, "_dns_names", frozenset())
    monkeypatch.setattr(access, "_dns_busy", False)
    access.own_names()
    for _ in range(100):  # the DNS names are looked up in a thread
        if access._dns_names:
            break
        time.sleep(0.02)
    for name in ("mac-studio.biol.uni.example:8000", "mister-plis.uni.example", "renamed-mac.local:8000", "10.1.2.3:8000"):
        assert access.known_host(name), name
    assert not access.known_host("evil.example")
    monkeypatch.setattr(access, "_own_at", -1e9)  # worked out again for the next tests


def test_the_names_are_no_longer_a_setting_of_the_lab_file():
    """They describe the machine (a proxy in front of it), not the lab: config.toml since 0.19.0."""
    from mister_plis import labsetup

    lab, warnings = labsetup.parse('[server]\nnames = ["mister-plis.lab.example"]\n')
    assert "server" not in lab and "config.toml" in warnings[0]


# ---- H2: a stored file never runs in the app's pages; M1: no framing -------------------------------------------------

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)"/>'


def _kept(client, name: str, data: bytes) -> tuple[str, str]:
    """A file kept in Time Machine by hand (anyone may): (its result's id, the file's path in it)."""
    up = client.post("/api/uploads", files={"file": (name, data, "application/octet-stream")}).json()
    jid = client.post("/api/tm/manual", json={"title": "t", "description": "d", "uploads": [up["id"]]}).json()["id"]
    return jid, f"out/{name}"


def test_an_uploaded_svg_or_html_file_is_downloaded_not_shown(client):
    for name, data in (("evil.svg", SVG), ("evil.html", b"<script>alert(1)</script>"), ("evil.xhtml", b"<x/>")):
        jid, rel = _kept(client, name, data)
        r = client.get(f"/api/tm/{jid}/files/{rel}")
        assert r.status_code == 200, name
        assert r.headers["content-disposition"].startswith("attachment"), name
        assert "html" not in r.headers["content-type"] and "svg" not in r.headers["content-type"], name
        assert "sandbox" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"


def test_pictures_and_text_are_still_shown_but_sandboxed(client):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    jid, rel = _kept(client, "plot.png", png)
    r = client.get(f"/api/tm/{jid}/files/{rel}")
    assert r.headers["content-type"] == "image/png" and r.headers["content-disposition"].startswith("inline")
    assert "sandbox" in r.headers["content-security-policy"]
    assert client.get(f"/api/tm/{jid}/files/{rel}?download=1").headers["content-disposition"].startswith("attachment")
    jid, rel = _kept(client, "notes.txt", b"<script>alert(1)</script>")
    r = client.get(f"/api/tm/{jid}/files/{rel}")
    assert r.headers["content-type"].startswith("text/plain") and r.headers["x-content-type-options"] == "nosniff"
    jid, rel = _kept(client, "report.pdf", b"%PDF-1.4\n")
    r = client.get(f"/api/tm/{jid}/files/{rel}")
    assert r.headers["content-type"] == "application/pdf" and "sandbox" not in r.headers.get("content-security-policy", "")


def test_a_jobs_files_are_served_the_same_way(client, tmp_path):
    from mister_plis import serving

    p = tmp_path / "x.svg"
    p.write_bytes(SVG)
    r = serving.stored_file(p)
    assert r.headers["content-disposition"].startswith("attachment") and r.media_type == "application/octet-stream"
    import inspect

    from mister_plis import app as app_module

    assert "serving.stored_file" in inspect.getsource(app_module.api_job_file)


def test_no_page_can_be_shown_inside_another_site(client):
    for url in ("/", "/settings", "/api/jobs", "/static/js/app.js"):
        r = client.get(url)
        assert r.headers["x-frame-options"] == "DENY", url
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"], url
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "same-origin"


# ---- M2: no link that runs something ("javascript:") ------------------------------------------------------------------

def test_safe_link():
    from mister_plis.serving import safe_link, web_link

    for bad in ("javascript:alert(1)", " JaVaScRiPt:alert(1)", "java\tscript:alert(1)", "data:text/html,<script>", "vbscript:x"):
        assert not safe_link(bad), bad
    for ok in ("https://example.org", "http://x", "mailto:a@b.c", "/api/jobs", "#top", "?q=1", "www.sigma.com", "java%0ascript:1"):
        assert safe_link(ok), ok
    assert web_link("") and web_link("https://x.example") and not web_link("/local") and not web_link("javascript:1")


def test_markdown_in_a_result_keeps_no_javascript_link():
    from mister_plis.outputs import Markdown

    html = Markdown("[click](javascript:alert(1)) [ok](https://example.org) ![p](javascript:x)").render(None, None)["html"]
    assert "javascript" not in html and 'href="https://example.org"' in html


def test_feedback_keeps_only_a_page_of_the_app(client):
    for page, kept in (("javascript:alert(1)", ""), ("//evil.example/x", ""), ("https://evil.example", ""),
                       ("/tool/toy-table?job=1", "/tool/toy-table?job=1")):
        r = client.post("/api/feedback", json={"kind": "bug", "text": "x", "page": page})
        assert r.json()["page"] == kept, page


def test_a_catalogues_homepage_must_be_a_web_address():
    from mister_plis.catalogue import entries

    found = entries({"sources": [
        {"name": "a", "url": "https://github.com/x/a.git", "homepage": "javascript:alert(1)"},
        {"name": "b", "url": "https://github.com/x/b.git", "homepage": "https://x.example/b"}]})
    assert [e["homepage"] for e in found] == ["", "https://x.example/b"]


def test_the_browser_drops_unsafe_link_addresses():
    """MP.el (static/js/app.js) is where every link on the pages is made: it checks the address."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "mister_plis" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "MP.safeUrl" in js and '!MP.safeUrl(v, k)) continue;' in js


# ---- L1: uploads have a limit ----------------------------------------------------------------------------------------

def test_an_upload_larger_than_the_lab_allows_is_refused(client):
    from mister_plis.app import uploads

    before = {p.name for p in uploads.root.iterdir()}
    try:
        assert client.post("/api/lab/uploads", json={"max_upload_mb": 1}).json()["max_upload_mb"] == 1
        big = b"x" * (3 * 1024 * 1024)
        r = client.post("/api/uploads", files={"file": ("big.csv", big, "text/csv")})
        assert r.status_code == 413 and "1 MB" in r.json()["error"]
        assert {p.name for p in uploads.root.iterdir()} == before  # nothing kept
        assert client.post("/api/uploads", files={"file": ("small.csv", b"a,b\n", "text/csv")}).status_code == 200
        assert client.post("/api/lab/uploads", json={"max_upload_mb": -1}).status_code == 422
    finally:
        client.post("/api/lab/uploads", json={"max_upload_mb": 0})
    assert client.get("/api/lab").json()["max_upload_mb"] == 0


def test_the_upload_store_stops_at_the_limit_without_a_length(tmp_path):
    import io

    import pytest

    from mister_plis.jobs import TooLarge, UploadStore

    store = UploadStore(tmp_path)
    with pytest.raises(TooLarge):
        store.save("x.bin", io.BytesIO(b"x" * 5000), limit=4096)
    assert list(tmp_path.iterdir()) == []
    assert store.save("x.bin", io.BytesIO(b"x" * 4096), limit=4096).size == 4096


def test_the_upload_limit_is_a_setting_of_the_lab_file():
    from mister_plis import labsetup

    lab, warnings = labsetup.parse("[jobs]\nmax_upload_mb = 500\n")
    assert not warnings and lab["jobs"] == {"max_upload_mb": 500}


# ---- L4: the API's reference is off ----------------------------------------------------------------------------------

def test_the_api_reference_is_not_published(client):
    assert client.get("/api/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


# ---- L5: a backup's manifest can't fetch a file from elsewhere ----------------------------------------------------------

def test_a_backup_manifest_cant_bring_in_a_file_from_outside_the_backup(tmp_path, monkeypatch):
    import json

    from mister_plis import backup as backup_mod

    secret = tmp_path / "secret.txt"
    secret.write_text("token", encoding="utf-8")
    folder = tmp_path / "backup" / "job"
    (folder / backup_mod.SUB).mkdir(parents=True)
    (folder / "ok.txt").write_text("fine", encoding="utf-8")
    (folder / backup_mod.SUB / "job.json").write_text(json.dumps({"id": "20260101-000000-abcdef", "tool_id": "x"}), encoding="utf-8")
    (folder / backup_mod.MANIFEST).write_text(json.dumps({"files": [
        {"job": "out/ok.txt", "backup": "ok.txt"},
        {"job": "out/stolen.txt", "backup": "../../secret.txt"}]}), encoding="utf-8")
    monkeypatch.setattr(backup_mod, "verify", lambda folder, full=False: (True, ""))  # checksums an attacker made match
    cat = backup_mod.BackupCatalogue(lambda: str(tmp_path / "backup"))
    into = tmp_path / "into"
    cat.import_files(folder, into)
    assert (into / "out" / "ok.txt").read_text(encoding="utf-8") == "fine"
    assert not (into / "out" / "stolen.txt").exists()


# ---- L2: what people typed never becomes a spreadsheet formula ------------------------------------------------------------

def test_exported_tables_keep_formulas_as_text(tmp_path):
    import openpyxl
    import pandas as pd

    from mister_plis.excel import csv_safe, write_table_workbook, write_workbook

    df = pd.DataFrame({"sample": ['=HYPERLINK("http://x","y")', "-5", "@SUM(A1)", "plain", "-80 °C", "-2+3+cmd|' /C calc'!A0"],
                       "value": [1, 2, 3, 4, 5, 6]})
    write_table_workbook(tmp_path / "t.xlsx", {"T": df})
    ws = openpyxl.load_workbook(tmp_path / "t.xlsx").active
    assert ws["A2"].data_type == "s" and ws["A2"].value.startswith("=HYPERLINK")
    write_workbook(tmp_path / "tool.xlsx", {"T": pd.DataFrame({"f": ["=1+1"]})})  # a tool's own workbook: as before
    assert openpyxl.load_workbook(tmp_path / "tool.xlsx").active["A2"].data_type == "f"
    assert csv_safe(df)["sample"].tolist() == ["'=HYPERLINK(\"http://x\",\"y\")", "-5", "'@SUM(A1)", "plain", "-80 °C",
                                               "'-2+3+cmd|' /C calc'!A0"]


# ---- M4: a new server belongs to whoever has its setup code ------------------------------------------------------------

@pytest.fixture
def new_server(tmp_path, monkeypatch):
    from mister_plis import labsetup, setupcode

    monkeypatch.setattr(setupcode, "path", lambda: tmp_path / "secrets" / "setup-code")
    f = labsetup.state_file()
    before = f.read_text(encoding="utf-8")
    f.write_text('{"format": 1, "state": "new"}', encoding="utf-8")
    yield setupcode.ensure()
    f.write_text(before, encoding="utf-8")


def test_a_new_server_changes_nothing_without_its_setup_code(client, new_server):
    import re

    from mister_plis import setupcode

    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", new_server) and setupcode.path().stat().st_mode & 0o077 == 0
    assert client.get("/api/setup").json()["code_needed"] is True
    for url, body in (("/api/setup/skip", None), ("/api/tools/sources", {"url": "https://github.com/x/y.git"}),
                      ("/api/feedback", {"kind": "bug", "text": "x"})):
        r = client.post(url, json=body)
        assert r.status_code == 403 and r.json()["setup_code"] is True, url
    assert client.post("/api/setup/code", json={"code": "WRON-GCOD"}).status_code == 403
    r = client.post("/api/setup/code", json={"code": new_server.lower().replace("-", " ")})  # typed loosely
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    try:
        assert client.get("/api/setup").json()["code_needed"] is False
        assert client.post("/api/feedback", json={"kind": "bug", "text": "x"}).status_code == 200
    finally:
        client.cookies.delete(setupcode.COOKIE)


def test_on_the_servers_own_computer_no_code_is_needed(new_server):
    from types import SimpleNamespace

    from mister_plis import setupcode

    def req(host, headers=None):
        return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers or {}, cookies={})

    assert not setupcode.needed(req("127.0.0.1")) and not setupcode.needed(req("::1"))
    assert setupcode.needed(req("192.168.1.30"))
    assert setupcode.needed(req("127.0.0.1", {"x-forwarded-for": "203.0.113.9"}))  # a proxy on the server passes it on


def test_once_set_up_changes_need_no_code_but_the_first_account_does(client, new_server):
    from mister_plis import labsetup, setupcode

    labsetup.write_state({"state": "set_up", "at": 0, "by": "", "from": "page"})
    assert client.get("/api/setup").json()["code_needed"] is False
    assert client.post("/api/feedback", json={"kind": "bug", "text": "x"}).status_code == 200
    assert setupcode.current() and setupcode.relevant()  # until the first account (tests/test_accounts.py)


# ---- M3: behind an HTTPS proxy -----------------------------------------------------------------------------------------

def test_over_https_browsers_are_told_to_stay_on_https(client):
    plain = client.get("/api/version")
    assert "strict-transport-security" not in plain.headers
    from fastapi.testclient import TestClient

    from mister_plis.app import app

    with TestClient(app, base_url="https://testserver") as https:  # as uvicorn sees it behind a trusted proxy
        assert https.get("/api/version").headers["strict-transport-security"].startswith("max-age=")


def test_the_trusted_proxies_reach_uvicorn(monkeypatch):
    from mister_plis import __main__ as main
    from mister_plis.config import settings

    monkeypatch.setattr(settings, "trusted_proxies", "")
    assert main._trusted_proxies() == "127.0.0.1"
    monkeypatch.setattr(settings, "trusted_proxies", "172.18.0.5, 10.0.0.2")
    assert main._trusted_proxies() == "172.18.0.5,10.0.0.2"


# ---- "Later": the pages run no inline script ------------------------------------------------------------------------------

def test_every_page_forbids_inline_scripts(client):
    for url in ("/", "/settings", "/tool/toy-table", "/jobs", "/api/jobs"):
        csp = client.get(url).headers["content-security-policy"]
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src", 1)[1].split(";", 1)[0], url
        assert "object-src 'none'" in csp and "frame-ancestors 'none'" in csp and "base-uri 'self'" in csp


def test_no_template_has_an_inline_script_or_handler():
    """With script-src 'self' they wouldn't run: code goes in static/js, data in <script type="application/json">."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    bad = []
    for t in [*root.glob("mister_plis/templates/**/*.html"), *root.glob("modules/*/templates/**/*.html")]:
        text = t.read_text(encoding="utf-8")
        for m in re.finditer(r"<script\b([^>]*)>", text):
            if "src=" not in m.group(1) and 'type="application/json"' not in m.group(1):
                bad.append(f"{t.relative_to(root)}: <script{m.group(1)}>")
        bad += [f"{t.relative_to(root)}: {m.group(0)}" for m in re.finditer(r"\son[a-z]+\s*=\s*[\"']", text)]
    assert not bad, bad
