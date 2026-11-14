"""The v0 on-disk formats (docs/FORMATS.md) stay readable — reorg phase P0.

The fixtures in tests/fixtures/jobs_v0 and backup_v0 were written by the v0 code itself
(tests/fixtures/make_v0_fixtures.py) and are frozen: every later phase must still read them through the
public code paths. Don't regenerate them, and don't relax these tests to fit a new format — add a reader.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from test_backup import _run

FIXTURES = Path(__file__).parent / "fixtures"
JOBS_V0 = FIXTURES / "jobs_v0"
BACKUP_V0 = FIXTURES / "backup_v0"
JOB_A = "20261107-093130-5c1d6c"  # Anna Kowalska, keyword "WT light", title "WT vs mutant, day 3"; full backup
JOB_B = "20261107-093131-34a42a"  # Ola; backup folder without job-info.json / job-info.txt


@pytest.fixture
def backup_copy(tmp_path):
    """The v0 backup fixture, copied, set as the lab's backup folder."""
    from mister_plis.app import backups

    folder = tmp_path / "backup"
    shutil.copytree(BACKUP_V0, folder)
    backups.update(str(folder), 1)
    yield folder
    backups.update("", 1)


def _out_names(job_dir: Path) -> set[str]:
    return {p.name for p in (job_dir / "out").iterdir()}


def test_fixtures_are_there():
    assert (JOBS_V0 / JOB_A / "meta.json").is_file()
    folders = {f.name: f for person in BACKUP_V0.iterdir() for f in person.iterdir()}
    assert any(JOB_A in n for n in folders) and any(JOB_B in n for n in folders)


def test_job_history_reads_v0_job_folders(tmp_path):
    from mister_plis.jobs import JobManager, UploadStore

    shutil.copytree(JOBS_V0, tmp_path / "jobs")
    jm = JobManager(tmp_path, UploadStore(tmp_path / "uploads"), max_workers=1)
    jm.load_history()
    job = jm.get(JOB_A)
    assert job is not None and job.status == "done"
    assert (job.user, job.keyword, job.title, job.tool_id) == ("Anna Kowalska", "WT light", "WT vs mutant, day 3", "chlorophyll")
    assert [o["kind"] for o in job.outputs] == ["file", "metric", "metric", "metric", "metric", "table", "plot", "table"]
    assert job.files["files"][0]["name"] == "run1.csv"
    assert job.backed_up  # it was copied to the backup folder before the fixture was taken
    # every file the results point at is in the folder, under the name the result shows
    for o in job.outputs:
        for ref in ([o] if o["kind"] in ("file", "image", "video") else [o["download"]] if o.get("download") else []):
            rel = ref["url"].split(f"/api/jobs/{JOB_A}/files/", 1)[1]
            assert jm.file_path(job, rel) is not None and Path(rel).name == ref["name"]
    assert set(job.result_names()) == _out_names(JOBS_V0 / JOB_A)


def test_v0_job_opens_and_downloads_through_the_api(client):
    from mister_plis.app import jobs

    dest = jobs.root / JOB_A
    shutil.copytree(JOBS_V0 / JOB_A, dest)
    try:
        jobs.load_history()
        d = client.get(f"/api/jobs/{JOB_A}").json()
        assert d["user"] == "Anna Kowalska" and d["title"] == "WT vs mutant, day 3"
        table = next(o for o in d["outputs"] if o["kind"] == "table" and o.get("download"))
        r = client.get(table["download"]["url"])
        assert r.status_code == 200 and r.content[:2] == b"PK"  # an .xlsx
        listed = client.get("/api/jobs").json()["jobs"]
        assert any(j["id"] == JOB_A for j in listed)
    finally:
        jobs.delete([jobs.get(JOB_A)])
        shutil.rmtree(dest, ignore_errors=True)


def test_v0_backup_job_info_is_a_job_record():
    from mister_plis.jobs import Job

    [folder] = [f for p in BACKUP_V0.iterdir() for f in p.iterdir() if JOB_A in f.name]
    meta = json.loads((folder / "job-info.json").read_text(encoding="utf-8"))
    job = Job.from_meta(meta, folder, record=False)
    assert job.id == JOB_A and job.user == "Anna Kowalska" and job.status == "done"
    info = (folder / "job-info.txt").read_text(encoding="utf-8")
    assert f"Job:       {JOB_A}" in info and "Run by:    Anna Kowalska" in info and "run1.csv" in info
    assert _out_names(JOBS_V0 / JOB_A) <= {p.name for p in folder.iterdir()}


def test_time_machine_retrieves_a_v0_backup(client, backup_copy):
    from mister_plis.app import jobs, modules
    timemachine = modules.get("timemachine")

    assert jobs.get(JOB_A) is None  # only the backup has it
    found = client.get(f"/api/tm/find?q={JOB_A}").json()["results"]
    assert found and found[0]["source"] == "backup"
    r = client.post("/api/tm/retrieve", json={"id": JOB_A})
    assert r.status_code == 200 and r.json()["entry"]["source"] == "backup"
    try:
        d = client.get(f"/api/tm/{JOB_A}").json()
        assert d["user"] == "Anna Kowalska" and d["title"] == "WT vs mutant, day 3"
        assert {f["name"] for f in d["files_kept"]} == _out_names(JOBS_V0 / JOB_A)
    finally:
        client.delete(f"/api/tm/{JOB_A}")
    assert not timemachine.has(JOB_A)


def test_time_machine_retrieves_a_v0_backup_without_its_job_info(client, backup_copy):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    r = client.post("/api/tm/retrieve", json={"id": JOB_B[-6:]})
    assert r.status_code == 200, r.text
    try:
        d = client.get(f"/api/tm/{JOB_B}").json()
        assert d["user"] == "Ola"  # from the person folder
        assert d["tool_name"].endswith("Chlorophyll concentration")  # from the folder name (with its date prefix)
        assert {f["name"] for f in d["files_kept"]} == {
            "2026-11-07_Ola_chlorophyll.xlsx", "2026-11-07_Ola_chlorophyll_replicates.xlsx", "2026-11-07_Ola_chlorophyll_results.xlsx"}
    finally:
        client.delete(f"/api/tm/{JOB_B}")
    assert not timemachine.has(JOB_B)


def test_the_backup_writer_now_writes_v1(client, tmp_path):
    """Until P3 this checked the v0 layout the writer produced. P3 replaced the writer with v1 on purpose; the v0
    *reading* tests above stay as they are. The folder's place and name are the same as in v0 (D7)."""
    from mister_plis.app import backups, jobs

    folder = tmp_path / "bk"
    folder.mkdir()
    backups.update(str(folder), 0)
    try:
        job_d = _run(client, tmp_path, keyword="light", name="Anna Kowalska")
        assert backups.run(everything=True).copied >= 1
    finally:
        backups.update("", 1)
    job = jobs.get(job_d["id"])
    [made] = [f for f in (folder / "Anna Kowalska").iterdir() if job.id in f.name]
    assert re.fullmatch(rf"\d{{4}}-\d{{2}}-\d{{2}}_Anna-Kowalska_light Toy averages \({job.id}\)", made.name)
    assert {"README.md", "results.xlsx", "files", "mister-plis"} <= {p.name for p in made.iterdir()}
    assert not (made / "job-info.json").exists() and not (made / "job-info.txt").exists()
    assert json.loads((made / "mister-plis" / "job.json").read_text(encoding="utf-8"))["id"] == job.id
