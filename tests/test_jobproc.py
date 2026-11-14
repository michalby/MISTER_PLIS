"""Jobs in a process of their own (mister_plis/runners.ProcessRunner, mister_plis/jobproc.py; SECURITY_AUDIT.md H4)."""

from __future__ import annotations

import subprocess
import sys
import threading

from mister_plis import runners
from mister_plis.jobs import JobSpec
from mister_plis.toolkit import RunContext, Tool


def _run_toy_table(client):
    up = client.post("/api/uploads", files={"file": ("run.csv", b"sample,value\nwt,0.25\nwt,0.27\n", "text/csv")}).json()
    rows = client.post("/api/tools/toy-table/suggest/samples", json={"files": [up["id"]]}).json()["result"]
    return client.post("/api/tools/toy-table/run", json={"params": {"files": [up["id"]], "samples": rows}, "wait": 30}).json()


def test_a_kept_job_runs_in_its_own_process_without_the_servers_secrets(client, monkeypatch):
    calls, real = [], subprocess.Popen

    def spy(cmd, *a, **kw):
        calls.append((cmd, kw.get("env") or {}))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", spy)
    monkeypatch.setenv("MISTER_PLIS_GIT_TOKEN", "github_pat_secret")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    job = _run_toy_table(client)
    assert job["status"] == "done" and any(o["kind"] == "table" for o in job["outputs"])  # the same results as ever
    cmd, env = next((c, e) for c, e in calls if any(str(x).endswith("jobproc.py") for x in c))
    assert cmd[1] == "-P"  # neither the job folder nor the current folder can shadow a module
    assert "MISTER_PLIS_GIT_TOKEN" not in env and "SSH_AUTH_SOCK" not in env and "PATH" in env


def test_a_live_calculator_run_stays_in_the_server(client, monkeypatch):
    calls, real = [], subprocess.Popen
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, *a, **kw: calls.append(cmd) or real(cmd, *a, **kw))
    job = client.post("/api/tools/toy-calc/run", json={"params": {}, "wait": 10}).json()
    assert job["status"] == "done" and not any("jobproc.py" in str(c) for c in calls)


def test_the_environment_left_for_a_job():
    env = runners.child_env()
    for name in ("GITHUB_TOKEN", "MISTER_PLIS_GIT_TOKEN", "MISTER_PLIS_WORKER_TOKEN", "AWS_SECRET_ACCESS_KEY", "SSH_AUTH_SOCK",
                 "DB_PASSWORD", "API_KEY"):
        assert runners.SECRET_NAMES.search(name), name
    assert not any(runners.SECRET_NAMES.search(k) for k in env)
    assert not runners.SECRET_NAMES.search("PATH") and not runners.SECRET_NAMES.search("MISTER_PLIS_HOME")


def test_as_another_user_it_is_started_through_sudo():
    cmd = runners.ProcessRunner(job_user="mp-jobs").child_command()
    assert cmd[:6] == ["sudo", "-n", "-u", "mp-jobs", "--", sys.executable] and cmd[-1].endswith("jobproc.py")


# ---- what the server does when the job's process misbehaves ------------------------------------------------------------

class _Events:
    def __init__(self, tmp_path):
        self.ctx = RunContext("job1", tmp_path, tool_id="t")
        self.end = None
        self.done = threading.Event()
        self.started_ = False

    def context(self, job_id):
        return self.ctx

    def started(self, job_id):
        self.started_ = True

    def recording(self, job_id, book):
        pass

    def upload(self, uid):  # pragma: no cover - no inputs here
        raise AssertionError

    def render(self, job_id, result):  # pragma: no cover - rendered in the child
        raise AssertionError

    def finished(self, job_id, outputs, error, trace, status):
        self.end = (outputs, error, trace, status)
        self.done.set()


def _run(tmp_path, child_code: str, cancel_after: float | None = None) -> _Events:
    runner = runners.ProcessRunner(1, folders=lambda: [{"name": "src", "path": str(tmp_path)}],
                                   command=[sys.executable, "-c", child_code])
    spec = JobSpec(job_id="job1", tool_id="t", tool_source="src", tool_commit="", params={}, inputs={}, prefs={}, record=True,
                   workdir="jobs/job1")
    events = _Events(tmp_path)
    runner.start(spec, Tool(id="t", name="T", category="Test"), events)
    if cancel_after is not None:
        assert not events.done.wait(cancel_after)
        events.ctx.cancel()
    assert events.done.wait(30)
    runner.shutdown()
    return events


def test_a_process_that_dies_fails_its_job(tmp_path):
    e = _run(tmp_path, "import sys; sys.stdin.readline(); sys.exit(3)")
    assert e.end[3] == "failed" and "exit code 3" in e.end[1]


def test_what_a_tool_prints_doesnt_confuse_the_server(tmp_path):
    e = _run(tmp_path, "import sys, json; sys.stdin.readline(); print('not json'); print(json.dumps({'event': 'started'}));"
                       " print(json.dumps({'event': 'report', 'progress': 0.5, 'message': 'half', 'logs': ['a line']}));"
                       " print(json.dumps({'event': 'finished', 'status': 'done', 'outputs': [{'kind': 'text', 'text': 'x'}],"
                       " 'error': '', 'trace': '', 'phrases': {}}))")
    assert e.end[3] == "done" and e.end[0] == [{"kind": "text", "text": "x"}]
    assert e.started_ and e.ctx.logs == ["a line"] and e.ctx.progress_value == 0.5


def test_a_cancelled_job_whose_process_wont_stop_is_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(runners, "CANCEL_GRACE", 0.5)
    e = _run(tmp_path, "import sys, time, json; sys.stdin.readline(); print(json.dumps({'event': 'started'}), flush=True);"
                       " time.sleep(60)", cancel_after=1.5)
    assert e.end[3] == "cancelled"


def test_the_real_child_reports_a_tool_that_cant_be_loaded(tmp_path):
    runner = runners.ProcessRunner(1, folders=lambda: [{"name": "src", "path": str(tmp_path)}])
    spec = JobSpec(job_id="job1", tool_id="nothing-here", tool_source="src", tool_commit="", params={}, inputs={}, prefs={},
                   record=True, workdir="jobs/job1")
    events = _Events(tmp_path)
    runner.start(spec, Tool(id="nothing-here", name="N", category="Test"), events)
    assert events.done.wait(60)
    assert events.end[3] == "failed" and "couldn't be loaded" in events.end[1]


def test_the_job_users_self_check(tmp_path):
    """jobproc.py --check: what the user running it may reach (here the same user as the server: it can read the secrets,
    which `python -m mister_plis job-user --check` then reports as a problem)."""
    import json

    from mister_plis.runners import ProcessRunner

    secrets, jobs = tmp_path / "secrets", tmp_path / "jobs"
    secrets.mkdir()
    jobs.mkdir()
    (secrets / "git-credentials.toml").write_text("x", encoding="utf-8")
    r = subprocess.run([*ProcessRunner().child_command(), "--check"], input=json.dumps({"secrets": str(secrets), "jobs": str(jobs)}) + "\n",
                       capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["secrets_readable"] is True and got["jobs_writable"] is True and got["code_readable"] is True
    assert list(jobs.iterdir()) == []  # its probe file is gone


def test_the_steps_for_a_job_user_name_this_machines_paths(capsys):
    from mister_plis.__main__ import job_user_command

    assert job_user_command(["lab-jobs"]) == 0
    out = capsys.readouterr().out
    assert "useradd" in out and "jobproc.py, " in out and "jobproc.py --check" in out and 'job_user = "lab-jobs"' in out
