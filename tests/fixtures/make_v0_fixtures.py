"""Makes the frozen v0 fixtures in tests/fixtures/jobs_v0/ and tests/fixtures/backup_v0/ (reorg phase P0).

Run by hand, once, on the v0 code (tag v1-final / branch release/v1):

    .venv/bin/python tests/fixtures/make_v0_fixtures.py

The fixtures are the old formats as the real code wrote them. Later phases must keep **reading** them, so never
regenerate them with newer code: tests import them as they are. See docs/FORMATS.md and docs/reorg/P0.md.

What it makes:

- ``jobs_v0/<id>/``: a finished Chlorophyll concentration job (person, keyword and title set), as kept in
  Jobs & results: ``meta.json`` and ``out/``;
- ``backup_v0/Anna Kowalska/<date>_Anna-Kowalska_WT-light Chlorophyll concentration (<id>)/``: the same job as
  the backup writer copied it (result files, ``job-info.json``, ``job-info.txt``);
- ``backup_v0/Ola/<…> (<id2>)/``: a second job's backup with ``job-info.json`` and ``job-info.txt`` removed, like
  an old or hand-copied folder, where only the folder name says what it was.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TMP = Path(tempfile.mkdtemp(prefix="mister_plis_v0_fixtures_"))
os.environ["MISTER_PLIS_DATA_DIR"] = str(TMP / "data")
os.environ["MISTER_PLIS_REAGENTS_REPO"] = ""  # no GitHub
os.environ["MISTER_PLIS_NOTES_REPO"] = ""
sys.path.insert(0, str(ROOT))

CSV = ('"run1.PHO"\n"WL/nm",,652.0,663.0,645.0,470.0,750.0\n"No.","Sample Name","A1","A2","A3","A4","A5"\n'
       '1,"wt",0.138,0.247,0.094,0.221,0.007\n2,"wt",0.140,0.251,0.095,0.224,0.007\n'
       '3,"mut",0.120,0.215,0.090,0.200,0.006\n4,"mut",0.118,0.212,0.089,0.198,0.006\n')


def run_job(client, name: str, keyword: str, title: str) -> dict:
    csv = TMP / "run1.csv"
    csv.write_text(CSV)
    with csv.open("rb") as f:
        up = client.post("/api/uploads", files={"file": ("run1.csv", f, "text/csv")}).json()
    rows = client.post("/api/tools/chlorophyll/suggest/samples", json={"files": [up["id"]]}).json()["result"]
    client.cookies.clear()
    client.cookies.set("lang", "en")
    client.cookies.set("name", name)
    job = client.post("/api/tools/chlorophyll/run",
                      json={"params": {"files": [up["id"]], "samples": rows}, "keyword": keyword, "title": title}).json()
    assert job["status"] == "done", job
    return job


def main() -> None:
    from fastapi.testclient import TestClient

    from mister_plis.app import app, backups, jobs

    jobs_out, backup_out = HERE / "jobs_v0", HERE / "backup_v0"
    for d in (jobs_out, backup_out):
        if d.exists():
            sys.exit(f"{d} exists already. The v0 fixtures are frozen: don't regenerate them.")

    backup_dir = TMP / "backup"
    backup_dir.mkdir()
    with TestClient(app) as client:
        backups.update(str(backup_dir), 0)
        a = run_job(client, "Anna Kowalska", "WT light", "WT vs mutant, day 3")
        b = run_job(client, "Ola", "", "")
        status = backups.run(everything=True)
        assert status.copied == 2 and not status.last_error, status

    job_a = jobs.get(a["id"])
    dest = jobs_out / a["id"]
    dest.mkdir(parents=True)
    shutil.copy2(job_a.workdir / "meta.json", dest / "meta.json")
    shutil.copytree(job_a.workdir / "out", dest / "out")

    for person in backup_dir.iterdir():
        for folder in person.iterdir():
            target = backup_out / person.name / folder.name
            shutil.copytree(folder, target)
            if b["id"] in folder.name:  # the "old or hand-copied" folder: only its name says what it was
                for name in ("job-info.json", "job-info.txt"):
                    (target / name).unlink()

    for p in sorted(HERE.glob("*_v0/**/*")):
        if p.is_file():
            text = p.read_bytes()
            assert str(TMP).encode() not in text, f"{p} contains a temporary path"
            print(p.relative_to(HERE))
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
