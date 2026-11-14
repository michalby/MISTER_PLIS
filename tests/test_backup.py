"""Result file names (date, who, keyword) and copying results to the backup folder."""

import time
from datetime import date
from pathlib import Path

import pytest

CSV = "sample,value\nwt,0.247\nwt,0.251\n"  # for the test tool toy-table (tests/fixtures/toolsource)


def _run(client, tmp_path, keyword="", name=""):
    csv = tmp_path / "run1.csv"
    csv.write_text(CSV, encoding="utf-8")
    with csv.open("rb") as f:
        up = client.post("/api/uploads", files={"file": ("run1.csv", f, "text/csv")}).json()
    rows = client.post("/api/tools/toy-table/suggest/samples", json={"files": [up["id"]]}).json()["result"]
    client.cookies.clear()
    client.cookies.set("lang", "en")
    if name:
        client.cookies.set("name", name)
    try:
        job = client.post("/api/tools/toy-table/run", json={"params": {"files": [up["id"]], "samples": rows}, "keyword": keyword}).json()
    finally:
        client.cookies.clear()
        client.cookies.set("lang", "en")
    assert job["status"] == "done", job
    return job


def _downloads(job):
    return [o.get("download", o)["name"] for o in job["outputs"] if o["kind"] in ("table", "file", "image")]


def test_file_names_have_date_name_and_keyword(client, tmp_path):
    job = _run(client, tmp_path, keyword="WT vs mutant / 2nd", name="Anna  Kowalska")
    prefix = f"{date.today():%Y-%m-%d}_Anna-Kowalska_WT-vs-mutant-2nd_"
    names = _downloads(job)
    assert names and all(n.startswith(prefix) for n in names), names
    assert job["user"] == "Anna Kowalska" and job["keyword"] == "WT vs mutant / 2nd"
    # the file is stored under that name, so the download has it too
    t = next(o for o in job["outputs"] if o["kind"] == "table")
    r = client.get(t["download"]["url"] + "?download=1")
    assert r.status_code == 200 and "Anna-Kowalska" in r.headers["content-disposition"]
    assert "Anna-Kowalska_WT-vs-mutant-2nd_" in client.get(job["report"]).headers["content-disposition"]
    # everyone's jobs are listed for everyone
    listed = client.get("/api/jobs").json()["jobs"]
    assert any(j["id"] == job["id"] and j["user"] == "Anna Kowalska" for j in listed)


def test_file_names_without_name_or_keyword(client, tmp_path):
    names = _downloads(_run(client, tmp_path))
    assert names and all(n.startswith(f"{date.today():%Y-%m-%d}_") and "__" not in n for n in names), names


def test_backup_settings_are_checked(client, tmp_path):
    from mister_plis.app import backups

    try:
        assert client.post("/api/lab", json={"backup_dir": "relative/path"}).status_code == 422
        assert client.post("/api/lab", json={"backup_dir": str(tmp_path / "missing")}).status_code == 422
        assert client.post("/api/lab", json={"backup_dir": str(backups.data_path / "jobs")}).status_code == 422
        assert client.post("/api/lab", json={"backup_dir": str(tmp_path), "backup_after_days": 5}).status_code == 422
        r = client.post("/api/lab", json={"backup_dir": str(tmp_path), "backup_after_days": 3})
        assert r.status_code == 200 and r.json()["backup_dir"] == str(tmp_path.resolve()) and r.json()["backup_after_days"] == 3
        page = client.get("/settings").text
        assert 'id="backup-dir"' in page and str(tmp_path.resolve()) in page
    finally:
        backups.update("", 1)
    assert client.post("/api/lab/backup").status_code == 422  # no folder set


@pytest.fixture
def backup_dir(tmp_path):
    from mister_plis.app import backups

    folder = tmp_path / "backup"
    folder.mkdir()
    backups.update(str(folder), 1)
    yield folder
    backups.update("", 1)


def test_backup_after_delay_and_cleanup_waits(client, tmp_path, backup_dir):
    from mister_plis.app import backups, jobs

    job_d = _run(client, tmp_path, keyword="light", name="Anna Kowalska")
    job = jobs.get(job_d["id"])
    assert backups.run().copied == 0 and not job.backed_up  # finished just now, the delay is 1 day
    # an old job that isn't backed up yet survives cleanup
    job.finished -= 2 * 86400
    jobs.cleanup(0, 10**9, keep=backups.pending)
    assert jobs.get(job.id) and job.workdir.is_dir()
    assert backups.info()["waiting"] >= 1

    status = backups.run()
    assert status.copied >= 1 and not status.last_error and job.backed_up
    person = backup_dir / "Anna Kowalska"
    [folder] = [d for d in person.iterdir() if job.id in d.name]
    assert folder.name.startswith(f"{date.today():%Y-%m-%d}_Anna-Kowalska_light Toy averages")
    files = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}  # the v1 backup (P3)
    assert {"README.md", "results.xlsx", "report.pdf", "mister-plis/job.json", "mister-plis/manifest.json"} <= files
    kept = {Path(f).name for f in files if f.startswith(("files/", "mister-plis/out/"))}
    assert set(_downloads(job_d)) <= kept  # every result file is there (table downloads under mister-plis/out)
    info = (folder / "README.md").read_text(encoding="utf-8")
    assert "| Run by | Anna Kowalska |" in info and "run1.csv" in info and "| Keyword | light |" in info
    assert not list(person.glob("*.partial"))
    # backed up → the next cleanup may delete it; the flag survives a restart
    assert '"backed_up":' in (job.workdir / "job.json").read_text(encoding="utf-8")
    jobs.cleanup(0, 10**9, keep=backups.pending)
    assert jobs.get(job.id) is None


def test_backup_now_ignores_delay(client, tmp_path, backup_dir):
    from mister_plis.app import jobs

    job_d = _run(client, tmp_path)
    r = client.post("/api/lab/backup").json()
    assert r["status"]["copied"] >= 1 and r["waiting"] == 0
    assert jobs.get(job_d["id"]).backed_up
    assert any(job_d["id"] in d.name for d in (backup_dir / "No name").iterdir())


def test_unavailable_backup_folder_keeps_results(client, tmp_path, backup_dir):
    from mister_plis.app import backups, jobs

    job_d = _run(client, tmp_path)
    gone = Path(str(backup_dir) + "-unmounted")
    backup_dir.rename(gone)  # like a NAS that isn't mounted
    try:
        status = backups.run(everything=True)
        assert "not available" in status.last_error and not jobs.get(job_d["id"]).backed_up
        jobs.get(job_d["id"]).finished = time.time() - 30 * 86400
        jobs.cleanup(0, 10**9, keep=backups.pending)
        assert jobs.get(job_d["id"])
    finally:
        gone.rename(backup_dir)


def test_clear_history_backs_up_the_ticked_ones_first(client, tmp_path, backup_dir):
    from mister_plis.app import jobs

    a, b, c = (_run(client, tmp_path, name="Clear Tester", keyword=k) for k in ("a", "b", "c"))
    other = _run(client, tmp_path, name="Someone Else")
    from mister_plis.app import backups

    backups._copy(jobs.get(c["id"]), backup_dir)  # already copied (a mark alone wouldn't do: the copy must be there)
    assert client.get("/api/history/clear?scope=mine").status_code == 422  # no name → no "mine"
    client.cookies.set("name", "Clear Tester")
    try:
        pre = client.get("/api/history/clear?scope=mine").json()
        assert pre["count"] == 3 and pre["backups_on"] and {j["id"] for j in pre["unbacked"]} == {a["id"], b["id"]}
        assert client.get("/api/history/clear?scope=all").json()["count"] >= 4
        r = client.post("/api/history/clear", json={"scope": "mine", "backup": [a["id"]]}).json()
    finally:
        client.cookies.clear()
        client.cookies.set("lang", "en")
    assert r == {"deleted": 3, "backed_up": 1, "kept": 0, "error": ""}
    assert all(jobs.get(j["id"]) is None for j in (a, b, c)) and jobs.get(other["id"])
    copied = [d.name for d in (backup_dir / "Clear Tester").iterdir()]
    assert any(a["id"] in n for n in copied) and not any(b["id"] in n for n in copied)
    assert not any(j["id"] == a["id"] for j in client.get("/api/jobs").json()["jobs"])


def test_clear_history_keeps_what_it_could_not_back_up(client, tmp_path, backup_dir):
    from mister_plis.app import jobs

    a, b = _run(client, tmp_path, name="Unmounted Tester"), _run(client, tmp_path, name="Unmounted Tester")
    gone = Path(str(backup_dir) + "-unmounted")
    backup_dir.rename(gone)
    client.cookies.set("name", "Unmounted Tester")
    try:
        r = client.post("/api/history/clear", json={"scope": "mine", "backup": [a["id"]]}).json()
    finally:
        client.cookies.clear()
        client.cookies.set("lang", "en")
        gone.rename(backup_dir)
    assert r["deleted"] == 1 and r["kept"] == 1 and "not available" in r["error"]
    assert jobs.get(a["id"]) and jobs.get(b["id"]) is None
