"""Time Machine as a module (reorg P4): it moved out of the base's data folder, and it backs itself up."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_backup import _run


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace").stdout


def test_the_old_folder_moves_once_with_its_history(tmp_path):
    from modules.timemachine import _move_old_folder

    old, new = tmp_path / "data" / "timemachine", tmp_path / "storage" / "modules" / "timemachine"
    (old / "20261107-093130-5c1d6c" / "out").mkdir(parents=True)
    (old / "20261107-093130-5c1d6c" / "out" / "a.xlsx").write_bytes(b"x" * 100)
    (old / "projects.json").write_text("{}", encoding="utf-8")
    _git(old, "init", "-q")
    _git(old, "add", "-A")
    _git(old, "commit", "-q", "-m", "Keep a result\n\nJob: 20261107-093130-5c1d6c\nAction: add")
    _move_old_folder(old, new)
    assert (new / "20261107-093130-5c1d6c" / "out" / "a.xlsx").read_bytes() == b"x" * 100
    assert "Keep a result" in _git(new, "log", "--format=%s")  # its history came along
    assert not old.exists() and list((tmp_path / "data").glob("timemachine.migrated-*"))  # renamed, never deleted
    _move_old_folder(old, new)  # nothing left to do: nothing happens


def test_a_copy_that_differs_is_refused(tmp_path, monkeypatch):
    from mister_plis import storage
    from modules import timemachine as tmmod

    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "f").write_text("1", encoding="utf-8")
    real = shutil.copytree

    def lossy(src, dst, **kw):
        real(src, dst, **kw)
        (Path(dst) / "f").unlink()

    monkeypatch.setattr(storage.shutil, "copytree", lossy)
    with pytest.raises(OSError, match="differs"):
        tmmod._move_old_folder(old, new)
    assert old.is_dir() and not new.exists()  # nothing changed: Time Machine stays where it was


def test_time_machine_backs_itself_up_and_comes_back(client, tmp_path):
    from mister_plis.app import backups, modules

    tm = modules.get("timemachine")
    folder = tmp_path / "backup"
    folder.mkdir()
    backups.update(str(folder), 1)
    try:
        jid = _run(client, tmp_path, name="Kept Tester")["id"]
        assert client.post(f"/api/jobs/{jid}/timemachine", json={}).status_code == 200
        r = client.post("/api/tm/backup").json()
        assert r["ok"] and r["entries"] >= 1
        dest = folder / "Time Machine"
        assert (dest / "timemachine.bundle").is_file() and (dest / "projects.md").is_file()
        index = json.loads((dest / "index.json").read_text(encoding="utf-8"))
        assert any(e["id"] == jid for e in index["entries"])
        assert list((dest / "Kept Tester").glob(f"*({jid})/README.md"))  # each kept result readable too
        assert client.post("/api/tm/backup").json()["ok"]  # unchanged: written again only when asked (here: forced)
        info = client.get("/api/tm/backup").json()
        assert info["bundle"] and info["state"]["entries"] >= 1
        # the disk is lost: Time Machine comes back from the backup, history and all
        client.delete(f"/api/tm/{jid}")
        assert not tm.has(jid)
        r = client.post("/api/tm/backup/restore").json()
        assert r["ok"] and tm.has(jid) and Path(r["previous"]).is_dir()
        assert any(jid in c["jobs"] for c in tm.log())
    finally:
        backups.update("", 1)
        if tm.has(jid):
            client.delete(f"/api/tm/{jid}")


def test_kept_jobs_are_flagged_in_the_base(client, tmp_path):
    jid = _run(client, tmp_path, name="Flag Tester")["id"]
    assert client.get(f"/api/jobs/{jid}").json()["in_tm"] is False
    client.post(f"/api/jobs/{jid}/timemachine", json={})
    try:
        assert client.get(f"/api/jobs/{jid}").json()["in_tm"] is True
        assert next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == jid)["in_tm"] is True
        people = {p["name"]: p for p in client.get("/api/people").json()["people"]}
        assert people["Flag Tester"].get("kept", 0) >= 0
    finally:
        client.delete(f"/api/tm/{jid}")
