"""A job in a process of its own (docs/SECURITY_AUDIT.md H4; the server's side is runners.ProcessRunner).

The server starts ``python -P <this file>`` for each job it keeps (not for live calculator runs). This process gets the
job on its first line of input (JSON), loads the job's tool from its tool folder, runs it, writes its result files into
the job folder and tells the server how it goes, one JSON object a line:

    {"event": "started"}                                       the tool runs now
    {"event": "report", "progress": 0.4, "message": "…", "logs": ["…"]}   every few tenths of a second, when it changed
    {"event": "finished", "status": "done"|"failed"|"cancelled", "outputs": […], "error": "…", "trace": "…",
     "phrases": {…}, "progress": …, "message": "…", "logs": […]}

A line ``cancel`` from the server cancels the job (the tool stops at its next check; the server kills the process if it
doesn't). What the tool prints goes to the server's log, never into these lines.

The process gets **no secrets**: the server leaves its tokens out of the environment (runners.child_env), the job
carries only the folders it needs, and with ``job_user`` set the process runs as another user of the computer, who
can't read the server's secrets folder (docs/DEPLOY_LINUX.md, "Jobs as another user"). Run with ``-P`` and from this
file's path, so neither the job folder nor the current folder can put a module of its own in front of Python's.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path


def check() -> int:
    """``jobproc.py --check`` (``python -m mister_plis job-user --check`` runs it as the job user): what this user may
    reach. The instance's folders come as JSON on the first line, as for a job."""
    folders = json.loads(sys.stdin.readline() or "{}")

    def readable(p: str) -> bool:
        try:
            os.listdir(p)
            for name in os.listdir(p):
                with open(os.path.join(p, name), "rb"):
                    pass
            return True
        except OSError:
            return False

    def writable(p: str) -> bool:
        try:
            probe = os.path.join(p, f".mister-plis-job-user-{os.getpid()}")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return True
        except OSError:
            return False

    import getpass

    print(json.dumps({"user": getpass.getuser(), "secrets_readable": readable(folders.get("secrets", "")),
                      "jobs_writable": writable(folders.get("jobs", "")),
                      "tool_data_writable": writable(folders.get("tool_data", "")) if folders.get("tool_data") else None,
                      "code_readable": os.path.isfile(os.path.join(str(Path(__file__).resolve().parent), "jobs.py"))}))
    return 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return check()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the code folder (python -P left it out)
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)  # these lines: the server reads them
    os.dup2(2, 1)  # anything the tool prints (Python or a program it runs) goes to the server's log instead
    sys.stdout = sys.stderr
    lock = threading.RLock()

    def send(d: dict) -> None:
        with lock:
            proto.write(json.dumps(d, ensure_ascii=False, default=str, allow_nan=False) + "\n")
            proto.flush()

    job = json.loads(sys.stdin.readline())
    os.environ.update({k: str(v) for k, v in (job.get("env") or {}).items()})
    if job.get("umask") is not None:
        os.umask(int(job["umask"]))

    from mister_plis import locale
    from mister_plis.errors import Cancelled, ToolError
    from mister_plis.i18n import recording
    from mister_plis.inputs import UploadedFile
    from mister_plis.jobs import Job, JobSpec, _json_safe, render_outputs
    from mister_plis.prefs import current_prefs
    from mister_plis.registry import Registry
    from mister_plis.toolkit import RunContext

    spec = JobSpec.from_dict(job["spec"])
    workdir = Path(job["workdir"])
    folder = job.get("folder") or {}
    class Context(RunContext):
        """Its log lines are also kept until they are sent to the server."""

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.outbox: list[str] = []

        def log(self, line: str) -> None:
            super().log(line)
            with lock:
                self.outbox.append(str(line).rstrip("\n"))
                del self.outbox[:-5000]

    ctx = Context(spec.job_id, workdir, tool_id=spec.tool_id)
    uploads = {uid: UploadedFile(uid, u["name"], Path(u["path"]), int(u.get("size") or 0)) for uid, u in (job.get("uploads") or {}).items()}

    def upload(uid: str):
        if uid not in uploads:
            raise ToolError("uploaded file has expired — please upload it again")
        return uploads[uid]

    def listen() -> None:  # the server's "cancel"
        for line in sys.stdin:
            if line.strip() == "cancel":
                ctx.cancel()

    def snapshot() -> dict:
        with lock:
            logs, ctx.outbox[:] = list(ctx.outbox), []
        return {"progress": ctx.progress_value, "message": ctx.message, "logs": logs}

    done = threading.Event()

    def report() -> None:
        last = None
        while not done.wait(0.3):
            now = (ctx.progress_value, ctx.message, len(ctx.outbox))
            if now != last or now[2]:
                last = now
                send({"event": "report", **snapshot()})

    threading.Thread(target=listen, daemon=True).start()
    threading.Thread(target=report, daemon=True).start()
    outputs, error, trace, status, book = None, "", "", "failed", {}
    try:
        registry = Registry()
        registry.load([folder] if folder else [])
        locale.reload([folder["path"]] if folder else [])
        tool = registry.get(spec.tool_id)
        if tool is None:
            broken = "; ".join(b.error.strip().splitlines()[-1] for b in registry.broken if b.error.strip())
            raise ToolError(f"The tool {spec.tool_id!r} couldn't be loaded for this job." + (f" {broken}" if broken else ""))
        current_prefs.set({**spec.prefs, "lang": "en"} if spec.record else spec.prefs)
        with recording() as book:  # stored in English: the tool's translated pieces are noted, for showing it later
            ctx.check_cancelled()
            send({"event": "started"})
            params = tool.parse(spec.params, upload)
            result = tool.run_fn(params, ctx)
            record = Job(id=spec.job_id, tool_id=spec.tool_id, tool_name=spec.tool_name or spec.tool_id, params=dict(spec.params),
                         record=spec.record, workdir=workdir, created=spec.created or time.time(), user=spec.user,
                         keyword=spec.keyword, ctx=ctx)
            outputs = _json_safe(render_outputs(record, result))
            status = "done"
    except Cancelled:
        status = "cancelled"
    except ToolError as e:
        error = str(e)
    except Exception as e:  # noqa: BLE001 - every failure is the job's
        error, trace = f"{type(e).__name__}: {e}", traceback.format_exc()
    done.set()
    send({"event": "finished", "status": status, "outputs": outputs, "error": error, "trace": trace,
          "phrases": dict(book or {}), **snapshot()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
