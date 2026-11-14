"""Backups anyone can read, that MISTER PLIS can bring back, and that are checked before a job is deleted (reorg P3)."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from openpyxl import load_workbook

from test_backup import _downloads, _run

FIXTURES = Path(__file__).parent / "fixtures"
JOB_A, JOB_B = "20261107-093130-5c1d6c", "20261107-093131-34a42a"


@pytest.fixture
def backup_dir(tmp_path):
    from mister_plis.app import backups

    folder = tmp_path / "backup"
    folder.mkdir()
    backups.update(str(folder), 1)
    yield folder
    backups.update("", 1)


def _folder(backup_dir: Path, job_id: str) -> Path:
    [f] = [d for p in backup_dir.iterdir() if p.is_dir() for d in p.iterdir() if d.name.endswith(f"({job_id})")]
    return f


def _sums(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*") if p.is_file() and p.name not in ("job.json", "meta.json")}


def test_a_backup_reads_without_mister_plis(client, tmp_path, backup_dir):
    from mister_plis.app import backups
    from mister_plis.backup import verify

    job_d = _run(client, tmp_path, keyword="light", name="Anna Kowalska")
    assert backups.run(everything=True).copied >= 1
    f = _folder(backup_dir, job_d["id"])
    readme = (f / "README.md").read_text(encoding="utf-8")
    for text in ("# Toy averages", "| Run by | Anna Kowalska |", "## Input files", "run1.csv", "## Settings",
                 "**Mean value:**", "### Every measurement", "results.xlsx", "plots/", "report.pdf", "Import from backup"):
        assert text in readme, text
    wb = load_workbook(f / "results.xlsx")
    assert wb.sheetnames[0] == "Summary" and "Every measurement" in wb.sheetnames and "Plot data" in wb.sheetnames
    assert "Mean value" in [c.value for c in wb["Summary"]["A"]]
    assert wb["Every measurement"].max_row - 1 == next(o["total_rows"] for o in job_d["outputs"] if o.get("title") == "Every measurement")
    [html] = (f / "plots").glob("*.html")
    assert '<script charset="utf-8" src="plotly.min.js">' in html.read_text(encoding="utf-8") and (f / "plots" / "plotly.min.js").is_file()
    assert (f / "report.pdf").read_bytes()[:4] == b"%PDF"
    files = {p.relative_to(f).as_posix() for p in f.rglob("*") if p.is_file()}
    assert not any(n.startswith("job-info") for n in files)  # the v0 files are gone; README.md tells it all
    assert {"mister-plis/job.json", "mister-plis/manifest.json", "mister-plis/README.txt", "mister-plis/inputs/files/run1.csv"} <= files
    assert verify(f, full=True) == (True, "")
    # no table twice: the tool's table downloads are kept for re-import only, the data is in results.xlsx
    assert not any(n.startswith("files/") and n.endswith("_toy.xlsx") for n in files)
    assert any(n.startswith("mister-plis/out/") and n.endswith("_toy.xlsx") for n in files)
    assert {Path(n).name for n in files} >= set(_downloads(job_d))


def test_deleted_and_brought_back_unchanged(client, tmp_path, backup_dir):
    from mister_plis.app import backups, jobs

    job_d = _run(client, tmp_path, name="Ola")
    jid = job_d["id"]
    backups.run(everything=True)
    job = jobs.get(jid)
    assert job.backed_up["format_version"] == 1 and job.backed_up["verified_at"]
    before = _sums(job.workdir)
    jobs.cleanup(0, 10**9, keep=backups.pending)  # backed up and checked → may go
    assert jobs.get(jid) is None and not (jobs.root / jid).exists()
    cat = client.get(f"/api/backup/catalogue?q={jid[-6:]}").json()
    [row] = cat["rows"]
    assert row["id"] == jid and row["format"] == 1 and not row["in_jobs"]
    r = client.post("/api/jobs/import", json={"folders": [row["folder"]]}).json()
    assert r == {"imported": [jid], "skipped": [], "errors": []}
    back = jobs.get(jid)
    assert _sums(back.workdir) == before  # every result file, input file and full table, byte for byte
    d = client.get(f"/api/jobs/{jid}").json()
    assert d["user"] == "Ola" and d["outputs"] == client.get(f"/api/jobs/{jid}").json()["outputs"]
    assert client.get(next(o["download"]["url"] for o in d["outputs"] if o.get("download"))).status_code == 200
    rec = json.loads((back.workdir / "job.json").read_text(encoding="utf-8"))
    assert rec["imported"]["format"] == 1 and rec["backed_up"]["folder"] == row["folder"]
    assert not backups.pending(back)  # it counts as backed up: cleanup may remove it again
    again = client.post("/api/jobs/import", json={"folders": [row["folder"]]}).json()
    assert again["skipped"] == [jid] and not again["imported"]


def test_old_backups_are_brought_back_too(client, backup_dir):
    from mister_plis.app import jobs

    shutil.copytree(FIXTURES / "backup_v0", backup_dir, dirs_exist_ok=True)
    rows = client.get("/api/backup/catalogue?rescan=1").json()["rows"]
    old = {r["id"]: r for r in rows if r["format"] == 0}
    assert set(old) == {JOB_A, JOB_B}
    try:
        r = client.post("/api/jobs/import", json={"folders": [old[JOB_A]["folder"], old[JOB_B]["folder"]]}).json()
        assert sorted(r["imported"]) == [JOB_A, JOB_B] and not r["errors"]
        a = client.get(f"/api/jobs/{JOB_A}").json()
        assert a["user"] == "Anna Kowalska" and a["title"] == "WT vs mutant, day 3"
        assert client.get(next(o["download"]["url"] for o in a["outputs"] if o.get("download"))).status_code == 200
        b = jobs.get(JOB_B)
        assert b.user == "Ola" and {p.name for p in (b.workdir / "out").iterdir()} == {
            "2026-11-07_Ola_chlorophyll.xlsx", "2026-11-07_Ola_chlorophyll_replicates.xlsx", "2026-11-07_Ola_chlorophyll_results.xlsx"}
    finally:
        jobs.delete([jobs.get(JOB_A), jobs.get(JOB_B)])


def test_a_job_is_deleted_only_when_its_backup_checks_out(client, tmp_path, backup_dir):
    from mister_plis.app import backups, jobs

    a, b, c = (_run(client, tmp_path, name="Strict Tester", keyword=k)["id"] for k in ("a", "b", "c"))
    backups.run(everything=True)
    # a: the NAS isn't mounted → kept, and still marked backed up
    away = Path(str(backup_dir) + "-away")
    backup_dir.rename(away)
    jobs.cleanup(0, 10**9, keep=backups.pending)
    assert jobs.get(a) and jobs.get(b) and jobs.get(c)
    assert jobs.get(a).backed_up
    away.rename(backup_dir)
    # b: a file in its backup was changed → kept, and copied again
    f = _folder(backup_dir, b)
    target = next(p for p in (f / "files").iterdir())
    target.write_bytes(target.read_bytes() + b"x")
    assert client.post("/api/lab/verify").json()["bad"] == [b]
    assert not jobs.get(b).backed_up
    # c: its backup folder was deleted → kept
    shutil.rmtree(_folder(backup_dir, c))
    jobs.cleanup(0, 10**9, keep=backups.pending)
    assert jobs.get(a) is None and jobs.get(b) and jobs.get(c)
    assert backups.run(everything=True).copied == 2  # b and c are copied again…
    jobs.cleanup(0, 10**9, keep=backups.pending)
    assert jobs.get(b) is None and jobs.get(c) is None  # …and only then may go


def test_old_backups_can_be_updated(client, backup_dir):
    from mister_plis.app import backups

    shutil.copytree(FIXTURES / "backup_v0", backup_dir, dirs_exist_ok=True)
    backups.catalogue.rows(rescan=True)
    assert backups.info()["old_backups"] == 2
    r = client.post("/api/lab/upgrade").json()
    assert sorted(r["upgraded"]) == [JOB_A, JOB_B] and not r["errors"]
    assert backups.info()["old_backups"] == 0
    new = _folder(backup_dir, JOB_A)
    assert (new / "README.md").is_file() and (new / "mister-plis" / "manifest.json").is_file()
    assert "WT vs mutant, day 3" in (new / "README.md").read_text(encoding="utf-8")
    kept = [d for d in (backup_dir / "Anna Kowalska").iterdir() if d.name.endswith(".v0")]
    assert kept and (kept[0] / "job-info.json").is_file()  # the old folder stays beside it


def test_a_table_too_big_for_excel_goes_to_csv_in_the_backup(client, tmp_path, backup_dir, monkeypatch):
    from mister_plis import jobs as J
    from mister_plis.app import backups
    from mister_plis.export import workbook

    monkeypatch.setattr(J, "XLSX_ROWS", 2)
    monkeypatch.setattr(workbook, "XLSX_ROWS", 2)
    job_d = _run(client, tmp_path, name="Csv Tester")
    backups.run(everything=True)
    f = _folder(backup_dir, job_d["id"])
    csvs = sorted(p.name for p in (f / "tables").glob("*.csv"))
    assert csvs and not any(name.endswith(".csv") for name in load_workbook(f / "results.xlsx").sheetnames)
    sheets = load_workbook(f / "results.xlsx").sheetnames
    assert "Every measurement" not in sheets  # never both


def test_import_refuses_folders_outside_the_backup(client, tmp_path, backup_dir):
    r = client.post("/api/jobs/import", json={"folders": [str(tmp_path)]}).json()
    assert not r["imported"] and r["errors"]
    assert client.post("/api/jobs/import", json={"folders": []}).status_code == 422


def test_the_list_follows_the_backup_folder(client, tmp_path, backup_dir):
    """The list of backups is a cache: it still works when the folder is mounted elsewhere, and it notices folders
    copied in by hand."""
    from mister_plis.app import backups

    jid = _run(client, tmp_path, name="Moved Tester")["id"]
    backups.run(everything=True)
    assert [r["id"] for r in client.get(f"/api/backup/catalogue?q={jid}").json()["rows"]] == [jid]
    elsewhere = tmp_path / "nas-mounted-elsewhere"
    shutil.copytree(backup_dir, elsewhere)
    backups.update(str(elsewhere), 1)
    try:
        [row] = client.get(f"/api/backup/catalogue?q={jid}").json()["rows"]
        assert Path(row["folder"]).parent.parent == elsewhere.resolve() or Path(row["folder"]).parent.parent == elsewhere
        shutil.copytree(FIXTURES / "backup_v0", elsewhere, dirs_exist_ok=True)  # copied in by hand
        ids = {r["id"] for r in client.get("/api/backup/catalogue").json()["rows"]}
        assert {jid, JOB_A, JOB_B} <= ids
        r = client.post("/api/jobs/import", json={"folders": [row["folder"]]}).json()
        assert not r["errors"]
    finally:
        backups.update(str(backup_dir), 1)
