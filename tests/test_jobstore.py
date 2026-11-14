"""Jobs in a storage folder: one folder per job with job.json, index.json as a rebuildable list (reorg phase P2)."""

import hashlib
import json
import shutil
import threading
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from mister_plis import jobs as J
from mister_plis.jobformat import read_job, to_v1
from mister_plis.jobs import JobManager, UploadStore
from mister_plis.jobstore import JobStore
from mister_plis.toolkit import Tool, outputs as O, inputs as I

FIXTURES = Path(__file__).parent / "fixtures"
JOB_A = "20261107-093130-5c1d6c"


def _tool(rows=600, download="t.xlsx", history=True):
    t = Tool(id="t-big", name="Big table", inputs=[I.File("data", "Data", required=False)], history=history)

    @t.runner
    def run(p, ctx):
        df = pd.DataFrame({"sample": [f"S{i}" for i in range(rows)], "value": range(rows)})
        return [O.Metric("Rows", rows), O.Table(df, title="All rows", max_rows=50, download=download)]

    return t


def _manager(root: Path, **kw) -> JobManager:
    m = JobManager(root, UploadStore(root / "uploads"), max_workers=2, **kw)
    m.load_history()
    return m


def _run(m: JobManager, tool, params=None, **kw):
    job = m.submit(tool, params or {}, **kw)
    m.wait(job, 60)
    assert job.status == "done", job.error + job.traceback
    return job


def test_a_job_is_a_folder_with_its_record_and_a_row_in_the_index(tmp_path):
    m = _manager(tmp_path)
    job = _run(m, _tool(), prefs={"name": "Ola", "lang": "pl", "decimal": "comma"})
    rec = json.loads((job.workdir / "job.json").read_text(encoding="utf-8"))
    assert rec["format"] == "mister-plis-job" and rec["format_version"] == 1 and rec["record"] is True
    assert rec["tool"]["id"] == "t-big" and rec["tool"]["source"] == "" and "commit" in rec["tool"]
    assert rec["base"]["version"] and "commit" in rec["base"]
    assert rec["prefs"]["lang"] == "pl" and rec["prefs"]["decimal"] == "comma"  # who ran it, and how
    assert not (job.workdir / "meta.json").exists()  # v1 only (until P8 a v0 copy was written beside it)
    index = json.loads((tmp_path / "jobs" / "index.json").read_text(encoding="utf-8"))
    row = index["jobs"][job.id]
    assert row["user"] == "Ola" and row["status"] == "done" and row["result_files"]


def test_tables_are_kept_in_full(tmp_path):
    m = _manager(tmp_path)
    job = _run(m, _tool(rows=600))
    table = next(o for o in job.outputs if o["kind"] == "table")
    assert len(table["rows"]) == 50 and table["total_rows"] == 600  # the page shows the first rows…
    assert table["file"] == "tables/02_All-rows.xlsx"  # …the job keeps them all
    ws = load_workbook(job.workdir / table["file"]).worksheets[0]
    assert ws.max_row == 601
    assert table["download"]["derived"] == "table"  # the tool's own download: the same data again


def test_a_table_too_big_for_excel_is_kept_as_csv_only(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "XLSX_ROWS", 100)
    m = _manager(tmp_path)
    job = _run(m, _tool(rows=600, download=None))
    table = next(o for o in job.outputs if o["kind"] == "table")
    assert table["file"].endswith(".csv") and not list((job.workdir / "tables").glob("*.xlsx"))
    assert len(pd.read_csv(job.workdir / table["file"])) == 600


def test_input_files_are_kept_and_bring_an_expired_upload_back(tmp_path):
    m = _manager(tmp_path)
    src = tmp_path / "plate.csv"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    with src.open("rb") as f:
        up = m.uploads.save("plate.csv", f)
    job = _run(m, _tool(), {"data": up.id})
    [entry] = job.inputs["data"]
    assert entry["kept"] and entry["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert (job.workdir / entry["path"]).read_text(encoding="utf-8") == "a,b\n1,2\n"
    shutil.rmtree(m.uploads.root / up.id)  # the upload expired (3 days)
    assert m.uploads.get(up.id).path.read_text(encoding="utf-8") == "a,b\n1,2\n"  # put back from the job, e.g. to run it again
    again = _run(m, _tool(), {"data": up.id}, parent=job.id)
    assert again.inputs["data"][0]["sha256"] == entry["sha256"]


def test_big_inputs_are_described_not_copied(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "KEEP_INPUTS_BYTES", 3)
    m = _manager(tmp_path)
    src = tmp_path / "big.csv"
    src.write_bytes(b"a,b\n1,2\n")  # exactly 8 bytes (write_text would add \r on Windows)
    with src.open("rb") as f:
        up = m.uploads.save("big.csv", f)
    job = _run(m, _tool(), {"data": up.id})
    [entry] = job.inputs["data"]
    assert not entry["kept"] and entry["size"] == 8 and entry["sha256"] and not (job.workdir / "inputs").exists()


def test_the_index_can_be_deleted_and_comes_back_the_same(tmp_path):
    m = _manager(tmp_path)
    ids = {_run(m, _tool(rows=5)).id for _ in range(3)}
    index = tmp_path / "jobs" / "index.json"
    before = json.loads(index.read_text(encoding="utf-8"))["jobs"]
    index.unlink()
    again = _manager(tmp_path)
    assert {j.id for j in again.recent()} == ids
    after = json.loads(index.read_text(encoding="utf-8"))["jobs"]
    assert {k: {f: v for f, v in r.items() if f != "mtime"} for k, r in after.items()} == \
           {k: {f: v for f, v in r.items() if f != "mtime"} for k, r in before.items()}
    index.write_text("{ not json", encoding="utf-8")  # unreadable → rebuilt too
    assert {j.id for j in _manager(tmp_path).recent()} == ids


def test_a_damaged_record_is_reported_not_fatal(tmp_path):
    m = _manager(tmp_path)
    good, bad = _run(m, _tool(rows=5)), _run(m, _tool(rows=5))
    for name in ("job.json", "meta.json"):
        (bad.workdir / name).write_text("{ broken", encoding="utf-8")
    again = _manager(tmp_path)
    assert [j.id for j in again.recent()] == [good.id]
    assert any(bad.id in p for p in again.store.problems)


def test_saves_from_many_threads_keep_the_index_whole(tmp_path):
    store = JobStore(tmp_path / "jobs")
    recs = [to_v1({"id": f"20261107-1200{i:02d}-abcdef", "tool_id": "x", "tool_name": "X", "status": "done", "outputs": []})
            for i in range(40)]
    for r in recs:
        (store.root / r["id"]).mkdir()
    threads = [threading.Thread(target=store.save, args=(r,)) for r in recs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(json.loads(store.index_file.read_text(encoding="utf-8"))["jobs"]) == 40
    assert len(JobStore(tmp_path / "jobs").load()) == 40


def test_finished_jobs_load_their_results_when_needed(tmp_path, monkeypatch):
    m = _manager(tmp_path)
    ids = [_run(m, _tool(rows=5)).id for _ in range(4)]
    monkeypatch.setattr(J, "MAX_LOADED", 2)
    again = _manager(tmp_path)
    jobs = [again.get(i) for i in ids]
    assert all(not j.loaded for j in jobs)  # listed from the index: nothing read yet
    assert jobs[0].result_names() and not jobs[0].loaded  # lists and searches don't need the record
    for j in jobs:
        assert j.to_dict()["outputs"][0]["label"] == "Rows"
    assert sum(j.loaded for j in jobs) == 2  # only the two most recently used stay loaded
    assert jobs[0].to_dict()["outputs"][1]["total_rows"] == 5  # a forgotten one is simply read again


def test_v0_job_folders_are_read_and_given_a_v1_record(tmp_path):
    shutil.copytree(FIXTURES / "jobs_v0", tmp_path / "jobs")
    m = _manager(tmp_path)
    job = m.get(JOB_A)
    assert job.user == "Anna Kowalska" and job.title == "WT vs mutant, day 3"
    assert (tmp_path / "jobs" / JOB_A / "meta.json").is_file()  # the v0 record stays
    rec = json.loads((tmp_path / "jobs" / JOB_A / "job.json").read_text(encoding="utf-8"))
    assert rec["format_version"] == 1 and rec["tool"]["id"] == "chlorophyll" and rec["outputs"] == job.outputs
    assert read_job(tmp_path / "jobs" / JOB_A)["user"] == "Anna Kowalska"


def test_jobs_move_once_from_the_old_folder(tmp_path):
    old = tmp_path / "data" / "jobs"
    shutil.copytree(FIXTURES / "jobs_v0", old)
    (old / ".20261107-000000-aaaaaa.partial").mkdir()  # leftovers are ignored
    storage = tmp_path / "storage"
    m = _manager(storage, legacy_root=old)
    assert m.get(JOB_A) is not None and m.migration["copied"] == 1
    assert not old.exists() and list((tmp_path / "data").glob("jobs.migrated-*"))  # renamed, never deleted
    assert (storage / "jobs" / ".migrated-from-v0.json").is_file()
    assert _manager(storage, legacy_root=old).get(JOB_A) is not None  # next start: nothing to do


def test_an_interrupted_move_carries_on_next_time(tmp_path, monkeypatch):
    old = tmp_path / "data" / "jobs"
    shutil.copytree(FIXTURES / "jobs_v0", old)
    real = J.folder_size
    monkeypatch.setattr(J, "folder_size", lambda p: -1 if p.name.endswith(".partial") else real(p))
    m = _manager(tmp_path / "storage", legacy_root=old)
    assert m.migration["failed"] and old.is_dir() and m.get(JOB_A) is None  # nothing half-done, the old folder stays
    monkeypatch.setattr(J, "folder_size", real)
    m = _manager(tmp_path / "storage", legacy_root=old)
    assert m.get(JOB_A) is not None and not old.exists()


def test_the_storage_folder_setting(tmp_path, monkeypatch):
    from mister_plis import storage
    from mister_plis.config import settings
    from mister_plis.errors import ToolError

    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "storage_dir", "")
    (tmp_path / "data").mkdir()
    assert settings.storage_path == tmp_path / "data"  # by default: the data folder
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "configured"))
    assert settings.storage_path == tmp_path / "configured"
    for bad, msg in (("relative/path", "full path"), (str(tmp_path / "missing"), "no folder"),
                     (str(Path(__file__).resolve().parents[1] / "docs"), "code folder")):
        with pytest.raises(ToolError, match=msg):
            storage.check_folder(bad)
    (tmp_path / "bk").mkdir()
    with pytest.raises(ToolError, match="separate"):
        storage.check_folder(str(tmp_path / "bk"), backup_dir=str(tmp_path / "bk"))


def test_moving_to_another_storage_folder(tmp_path, monkeypatch):
    from mister_plis import storage
    from mister_plis.config import settings
    from mister_plis.errors import ToolError

    data, new = tmp_path / "data", tmp_path / "new"
    data.mkdir()
    new.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data))
    monkeypatch.setattr(settings, "storage_dir", "")
    m = _manager(data)
    job = _run(m, _tool(rows=5))
    (data / "tool-data" / "molarity").mkdir(parents=True)
    (data / "tool-data" / "molarity" / "compounds.json").write_text('{"Tris": 121.14}', encoding="utf-8")
    with pytest.raises(ToolError, match="running"):
        storage.choose(str(new), True, busy=True)
    r = storage.choose(str(new), True, busy=False)
    assert r["ok"] and settings.storage_path == new
    assert (new / "jobs" / job.id / "job.json").is_file() and (new / "tool-data" / "molarity" / "compounds.json").is_file()
    assert list(data.glob("jobs.moved-*")) and not (data / "jobs").exists()  # the old ones kept, renamed
    assert storage.legacy_jobs() == data / "jobs"  # moved: nothing left to migrate, the old place is just empty
    assert _manager(new, legacy_root=storage.legacy_jobs()).get(job.id) is not None
    with pytest.raises(ToolError, match="already"):
        storage.choose(str(new), True, busy=False)


def test_a_modules_storage_moves_with_the_jobs(tmp_path, monkeypatch):
    """Time Machine keeps its results in <storage>/modules/timemachine: they go along, not left behind."""
    from mister_plis import storage
    from mister_plis.config import settings

    data, new = tmp_path / "data", tmp_path / "new"
    (data / "modules" / "timemachine").mkdir(parents=True)
    (data / "modules" / "timemachine" / "projects.json").write_text('{"projects": []}', encoding="utf-8")
    (data / "modules" / "inventory").mkdir()
    (data / "modules" / "inventory" / "settings.json").write_text("{}", encoding="utf-8")  # module data, not storage: stays
    new.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data))
    monkeypatch.setattr(settings, "storage_dir", "")
    r = storage.choose(str(new), True, busy=False, extra=("modules/timemachine", "../escape"))
    assert r["ok"] and (new / "modules" / "timemachine" / "projects.json").is_file()
    assert list((data / "modules").glob("timemachine.moved-*")) and (data / "modules" / "inventory" / "settings.json").is_file()
    assert not (tmp_path / "escape").exists()


def test_a_job_a_worker_ran_still_opens(tmp_path):
    """Jobs could run on other computers (workers) from 0.11.0 to 0.18.0; their job.json says which. Workers are gone
    (0.19.0), but such a job still opens and still says where it ran."""
    m = _manager(tmp_path)
    job = _run(m, _tool(rows=3))
    rec_path = job.workdir / "job.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    rec["worker"] = "blender-pc"
    rec_path.write_text(json.dumps(rec), encoding="utf-8")
    (tmp_path / "jobs" / "index.json").unlink()  # rebuilt from the job folders
    again = _manager(tmp_path).get(job.id)
    again.load()  # what a page does when it opens the job
    assert again.status == "done" and again.outputs and again.worker == "blender-pc"
