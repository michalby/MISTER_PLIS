"""Moving a whole server to another one (mister_plis/transfer.py, docs/BETA.md)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mister_plis import labsetup, transfer
from mister_plis.errors import ToolError

from test_jobstore import _manager, _run, _tool

ROOT = Path(__file__).resolve().parents[1]


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
                          cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace").stdout


def _server(root: Path, separate_storage: bool) -> tuple[Path, Path, str]:
    """A server's folders as a lab leaves them: a job, Time Machine, the inventory's clone with a change not sent yet,
    settings, people — and what a transfer leaves out."""
    data = root / "data"
    storage = root / "storage" if separate_storage else data
    data.mkdir(parents=True)
    storage.mkdir(exist_ok=True)
    job = _run(_manager(storage), _tool(rows=5), prefs={"name": "Ola"})
    (data / "lab_settings.json").write_text('{"lab_name": "Smith Lab", "backup_dir": "/Volumes/NAS"}', encoding="utf-8")
    (data / "people.json").write_text('{"merged": {"ola": "Ola K."}}', encoding="utf-8")
    (data / "lab.json").write_text('{"format": 1, "state": "set_up", "modules": ["timemachine", "inventory"]}', encoding="utf-8")
    (data / "tool-settings").mkdir()
    (data / "tool-settings" / "toy-table.json").write_text('{"format": 1, "values": {"program": "/bin/sh"}}', encoding="utf-8")
    repo = data / "modules" / "inventory" / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "reagents.csv").write_text("label_no,name\n1,aceton\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "Add aceton (not sent yet)")
    (data / "modules" / "inventory" / "settings.json").write_text('{"repo": "https://github.com/smith/inventory.git"}', encoding="utf-8")
    tm = storage / "modules" / "timemachine"
    tm.mkdir(parents=True, exist_ok=True)
    (tm / "projects.json").write_text('{"projects": [{"name": "Gels"}]}', encoding="utf-8")
    (tm / "entries").mkdir()
    (tm / "entries" / "e1.json").write_text("{}", encoding="utf-8")
    # left out: this machine's, or fetched again
    for rel in ("uploads/u1/x.csv", "live/j/x", "tool-sources/lab/tool.py", "jobs.moved-2026-01-01/old/job.json"):
        (data / rel).parent.mkdir(parents=True, exist_ok=True)
        (data / rel).write_text("x", encoding="utf-8")
    (data / "storage.json").write_text(json.dumps({"dir": str(storage)}), encoding="utf-8")  # this machine's choice: not carried over
    (data / "git_branch.json").write_text('{"branch": "test"}', encoding="utf-8")
    return data, storage, job.id


@pytest.mark.parametrize("separate_storage", [False, True], ids=["storage is the data folder", "storage of its own"])
def test_a_server_moves_to_a_new_one(tmp_path, separate_storage):
    data, storage, job_id = _server(tmp_path / "old", separate_storage)
    out = tmp_path / "usb"
    out.mkdir()
    r = transfer.export(str(out), data, storage, ["modules/timemachine"], lab_name="Smith Lab", by="Ola", jobs=1)
    names = set(json.loads((Path(r["path"]) / "manifest.json").read_text(encoding="utf-8"))["files"])
    assert f"storage/jobs/{job_id}/job.json" in names and "storage/modules/timemachine/projects.json" in names
    assert "data/modules/inventory/repo/.git/HEAD" in names and "data/tool-settings/toy-table.json" in names
    assert not [n for n in names if any(s in n for s in ("uploads", "live/", "tool-sources", "storage.json", "git_branch", ".moved-"))]
    assert not any(n.startswith("data/modules/timemachine") for n in names) or separate_storage  # never twice
    assert Path(r["path"]).name.startswith("MISTER PLIS Smith Lab ") and not list(out.glob("*.partial"))

    s = transfer.summary(r["path"])
    assert s["jobs"] == 1 and s["lab_name"] == "Smith Lab" and s["checked"]

    # a new server: the folders it made by itself are in the way, and are set aside, never deleted
    new = tmp_path / "new" / "data"
    (new / "modules" / "timemachine" / ".git").mkdir(parents=True)
    (new / "lab.json").write_text('{"format": 1, "state": "new"}', encoding="utf-8")
    r2 = transfer.bring_in(r["path"], new, new, by="Ada")
    assert r2["jobs"] == 1 and any(".before-import-" in a for a in r2["set_aside"])
    assert list((new / "modules").glob("timemachine.before-import-*"))
    assert json.loads((new / "modules" / "timemachine" / "projects.json").read_text(encoding="utf-8"))["projects"][0]["name"] == "Gels"
    assert "Add aceton (not sent yet)" in _git(new / "modules" / "inventory" / "repo", "log", "--format=%s")
    assert json.loads((new / "people.json").read_text(encoding="utf-8"))["merged"]["ola"] == "Ola K."
    assert not (new / "storage.json").exists() and not (new / "uploads").exists()
    state = labsetup.read_state(new)
    assert state["state"] == "set_up" and state["by"] == "Ada" and state["modules"] == ["timemachine", "inventory"]
    assert state["from"].startswith("moved from ")
    assert _manager(new).get(job_id) is not None  # the job opens on the new server

    with pytest.raises(ToolError, match="jobs already"):  # never merged into a server that has jobs
        transfer.bring_in(r["path"], new, new)


def test_a_damaged_copy_changes_nothing(tmp_path):
    data, storage, _ = _server(tmp_path / "old", False)
    out = tmp_path / "usb"
    out.mkdir()
    r = transfer.export(str(out), data, storage, ["modules/timemachine"])
    (Path(r["path"]) / "data" / "people.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ToolError, match="damaged") as e:
        transfer.summary(r["path"])
    assert "data/people.json" in str(e.value)
    new = tmp_path / "new"
    new.mkdir()
    with pytest.raises(ToolError, match="damaged"):
        transfer.bring_in(r["path"], new, new)
    assert not any(new.iterdir())


def test_where_a_copy_may_go_and_what_it_must_be(tmp_path):
    data, storage, _ = _server(tmp_path / "old", False)
    for bad in ("", "relative/folder", str(tmp_path / "nowhere"), str(data)):
        with pytest.raises(ToolError):
            transfer.export(bad, data, storage, [])
    with pytest.raises(ToolError, match="isn't a copy"):
        transfer.summary(str(tmp_path))
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "manifest.json").write_text(json.dumps({"format": "mister-plis-transfer", "format_version": 1,
                                                    "files": {"data/../../escape": {"size": 1, "sha256": "x"}}}), encoding="utf-8")
    with pytest.raises(ToolError, match="shouldn't"):
        transfer.summary(str(evil))


def test_on_the_settings_page_and_the_setup_page(client, tmp_path, monkeypatch):
    out = tmp_path / "usb"
    out.mkdir()
    r = client.post("/api/transfer/export", json={"dir": str(out)})
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    s = client.post("/api/transfer/check", json={"dir": path}).json()
    assert s["checked"] and "here_has_jobs" in s
    assert client.post("/api/transfer/check", json={"dir": str(tmp_path)}).status_code == 422
    calls = []
    monkeypatch.setattr(transfer, "bring_in", lambda *a: calls.append(a) or {"jobs": 0, "files": 1, "bytes": 1, "set_aside": [], "lab_name": ""})
    from mister_plis import updater

    monkeypatch.setattr(updater, "schedule_restart", lambda delay=0.8: True)
    assert client.post("/api/transfer/import", json={"dir": path}).json()["restarting"] and calls[0][0] == path
    page = client.get("/settings").text
    assert 'id="transfer-panel"' in page and 'id="transfer-btn"' in page
    assert 'id="setup-transfer-check"' in client.get("/setup").text


def test_from_the_command_line(tmp_path):
    data, storage, job_id = _server(tmp_path / "old", False)
    out = tmp_path / "usb"
    out.mkdir()

    def run(data_dir, *args):
        env = {**os.environ, "MISTER_PLIS_DATA_DIR": str(data_dir), "MISTER_PLIS_MODULES": "none"}
        return subprocess.run([sys.executable, "-m", "mister_plis", "transfer", *args], cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=240, encoding="utf-8", errors="replace")

    r = run(data, "export", str(out))
    assert r.returncode == 0 and "Copied and checked" in r.stdout, r.stdout + r.stderr
    copy = next(out.glob("MISTER PLIS *"))
    assert run(tmp_path / "new", "check", str(copy)).returncode == 0
    r = run(tmp_path / "new", "import", str(copy), "--yes")
    assert r.returncode == 0 and "Brought in: 1 job(s)" in r.stdout, r.stdout + r.stderr
    assert _manager(tmp_path / "new").get(job_id) is not None and not labsetup.is_new(tmp_path / "new")
