"""Stored files from an origin of their own (mister_plis/fileorigin.py; SECURITY_AUDIT.md "Later")."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from mister_plis import fileorigin
from mister_plis.config import settings


@pytest.fixture
def folder():
    """A job-like folder in the storage folder, with a picture, an HTML report and a workbook."""
    d = settings.storage_path / "jobs" / "20260101-000000-f11e5a"
    (d / "out").mkdir(parents=True, exist_ok=True)
    (d / "out" / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    (d / "out" / "report.html").write_text("<h1>Report</h1><script>alert(1)</script>", encoding="utf-8")
    (d / "out" / "book.xlsx").write_bytes(b"PK")
    (d / "job.json").write_text("{}", encoding="utf-8")
    return d


@pytest.fixture
def files():
    with TestClient(fileorigin.files_app) as c:
        yield c


def test_a_link_opens_its_folder_and_nothing_else(folder, files):
    token = fileorigin.token_for(folder)
    r = files.get(f"/f/{token}/out/plot.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and "sandbox" in r.headers["content-security-policy"]
    assert files.get(f"/f/{token}/out/book.xlsx").headers["content-disposition"].startswith("attachment")
    assert files.get(f"/f/{token}/out/plot.png?download=1").headers["content-disposition"].startswith("attachment")
    for bad in ("../../../secrets/files-key", "..%2F..%2Fjob.json", "out/../../other/x", "out", "nope.txt"):
        assert files.get(f"/f/{token}/{bad}").status_code in (403, 404), bad
    other = fileorigin.token_for(folder / "out")  # a link to a sub-folder doesn't reach its parent
    assert files.get(f"/f/{other}/../job.json").status_code in (403, 404) and files.get(f"/f/{other}/plot.png").status_code == 200


def test_an_html_report_is_shown_there_but_runs_nothing(folder, files):
    r = files.get(f"/f/{fileorigin.token_for(folder)}/out/report.html")
    assert r.headers["content-type"].startswith("text/html") and r.headers["content-disposition"].startswith("inline")
    assert "sandbox" in r.headers["content-security-policy"] and "script-src" not in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"


def test_a_changed_or_expired_link_is_refused(folder, files, monkeypatch):
    token = fileorigin.token_for(folder)
    body, sig = token.split(".")
    other = fileorigin.token_for(settings.storage_path / "jobs")  # a whole other folder, signed — but not this signature
    assert files.get(f"/f/{other.split('.')[0]}.{sig}/out/plot.png").status_code == 403
    assert files.get(f"/f/{body}.{sig[:-2]}AA/out/plot.png").status_code == 403
    assert files.get("/f/nonsense/out/plot.png").status_code == 403
    real = time.time
    monkeypatch.setattr(fileorigin.time, "time", lambda: real() + fileorigin.TTL + 60)
    assert files.get(f"/f/{token}/out/plot.png").status_code == 403


def test_the_files_server_serves_nothing_of_the_app(files):
    assert files.get("/ping.gif").status_code == 200
    for url in ("/", "/api/jobs", "/api/version", "/settings", "/static/js/app.js", "/api/docs"):
        assert files.get(url).status_code == 404, url


def test_a_folder_outside_the_storage_and_data_folders_gets_no_link(tmp_path):
    assert fileorigin.token_for(tmp_path) is None


def test_pages_and_jobs_name_the_files_origin_when_it_listens(client, monkeypatch):
    monkeypatch.setattr(fileorigin, "listening", True)
    origin = f"http://testserver:{settings.files_port or settings.port + 1}"
    page = client.get("/")
    assert f"img-src 'self' {origin}" in page.headers["content-security-policy"] and f'"filesOrigin": "{origin}"' in page.text
    up = client.post("/api/uploads", files={"file": ("run.csv", b"sample,value\nwt,0.25\n", "text/csv")}).json()
    rows = client.post("/api/tools/toy-table/suggest/samples", json={"files": [up["id"]]}).json()["result"]
    job = client.post("/api/tools/toy-table/run", json={"params": {"files": [up["id"]], "samples": rows}, "wait": 30}).json()
    assert job["files_base"].startswith(f"{origin}/f/")
    files = TestClient(fileorigin.files_app)
    xlsx = next(o for o in job["outputs"] if o.get("url", "").endswith(".xlsx"))
    rel = xlsx["url"].split("/files/", 1)[1]
    assert files.get(job["files_base"].replace(origin, "") + rel).status_code == 200  # the same file, from there
    # kept in Time Machine: the entry carries its own link
    client.post(f"/api/jobs/{job['id']}/timemachine", json={})
    entry = client.get(f"/api/tm/{job['id']}").json()
    assert entry["files_base"].startswith(f"{origin}/f/")


def test_no_files_origin_when_off_on_https_or_not_listening(client, monkeypatch):
    monkeypatch.setattr(fileorigin, "listening", False)
    assert '"filesOrigin": ""' in client.get("/").text
    monkeypatch.setattr(fileorigin, "listening", True)
    with TestClient(client.app, base_url="https://testserver") as https:  # a page on HTTPS: not from plain HTTP
        assert '"filesOrigin": ""' in https.get("/").text
    monkeypatch.setattr(settings, "files_origin", "off")
    assert '"filesOrigin": ""' in client.get("/").text
    monkeypatch.setattr(settings, "files_origin", "https://files.lab.example/")  # behind a proxy: as given
    assert '"filesOrigin": "https://files.lab.example"' in client.get("/").text
