"""Where a job runs (docs/PREP_PLAN.md R8): always on this computer, the server's.

:class:`~mister_plis.jobs.JobManager` keeps the jobs — the list, their records, what the pages show. A *runner* runs
them. It is given a :class:`~mister_plis.jobs.JobSpec` (everything a job is, as JSON) and the tool, and reports back
through :class:`RunnerEvents`, which the JobManager implements. :class:`LocalRunner` runs jobs in threads of the
process it is in, exactly as jobs always ran.

The server's runner is a :class:`ProcessRunner`: each job kept in the history runs in a process of its own, live
calculator runs in the server's threads (``job_isolation = "off"`` in config.toml: a LocalRunner for everything).
**Results are rendered where the files are** (``RunnerEvents.render``). Jobs once also ran on other computers
(workers, 0.11.0–0.18.0); since 0.19.0 everything runs on the server again.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol

from .errors import Cancelled, ToolError
from .i18n import recording
from .prefs import current_prefs
from .toolkit import RunContext, Tool

if TYPE_CHECKING:  # pragma: no cover
    from .jobs import JobSpec


class RunnerEvents(Protocol):
    """What a runner tells the job list (JobManager)."""

    def context(self, job_id: str) -> RunContext:
        """The job's RunContext: progress, messages and logs the pages read; cancelling sets it."""

    def started(self, job_id: str) -> None:
        """The job got its slot and starts running now."""

    def recording(self, job_id: str, book: dict) -> None:
        """Where the tool's translated pieces are noted while a kept job runs (it is stored in English)."""

    def upload(self, upload_id: str) -> Any:
        """An upload the job's parameters name (tool.parse reads them)."""

    def render(self, job_id: str, result: Any) -> list[dict]:
        """The tool's result → the job's outputs, written into its folder (where the files are)."""

    def finished(self, job_id: str, outputs: list[dict] | None, error: str, trace: str, status: str) -> None:
        """The job is over: "done", "failed" or "cancelled"."""


class Runner(Protocol):
    def start(self, spec: "JobSpec", tool: Tool, events: RunnerEvents) -> None:
        """Run the job, now or when there is room; return at once."""

    def cancel(self, job_id: str) -> None:
        """Stop the job if it is still running (its RunContext is cancelled too)."""

    def shutdown(self, wait: bool = False) -> None:
        """Stop taking jobs (the server stops)."""


class LocalRunner:
    """Jobs run in threads of the app's own process; a tool's ``max_concurrent`` limits how many of it run at once."""

    def __init__(self, max_workers: int = 8):
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self.tool_slots: dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    def start(self, spec: "JobSpec", tool: Tool, events: RunnerEvents) -> None:
        self.pool.submit(self._run, spec, tool, events)

    def cancel(self, job_id: str) -> None:
        """Nothing more to do here: the job's RunContext, shared with the pages, was cancelled by the JobManager, and
        the tool stops at its next check."""

    def shutdown(self, wait: bool = False) -> None:
        self.pool.shutdown(wait=wait, cancel_futures=not wait)

    def _slot(self, tool: Tool) -> threading.Semaphore | None:
        if not tool.max_concurrent:
            return None
        with self._lock:
            return self.tool_slots.setdefault(tool.id, threading.Semaphore(tool.max_concurrent))

    def _run(self, spec: "JobSpec", tool: Tool, events: RunnerEvents) -> None:
        if not spec.record:
            return self._run_job(spec, tool, events)
        with recording() as book:  # stored in English: note the tool's translated pieces for showing it later
            events.recording(spec.job_id, book)  # filled as the job runs, saved with it
            self._run_job(spec, tool, events)

    def _run_job(self, spec: "JobSpec", tool: Tool, events: RunnerEvents) -> None:
        ctx = events.context(spec.job_id)
        # … and the settings of whoever started it (decimal separator). Jobs kept in the history run in English: their
        # record and files on disk are English, and the results are translated when shown. Live calculator runs are
        # never stored, so they run in the language of whoever is looking.
        current_prefs.set({**spec.prefs, "lang": "en"} if spec.record else spec.prefs)
        slot = self._slot(tool)
        outputs, error, trace, status = None, "", "", "failed"
        try:
            if slot:
                ctx.message = "Waiting for a free slot…"
                while not slot.acquire(timeout=0.5):
                    ctx.check_cancelled()
            try:
                ctx.check_cancelled()
                outputs, error, trace, status = self._execute(spec, tool, events, ctx)
            finally:
                if slot:
                    slot.release()
        except Cancelled:
            status = "cancelled"
        except Exception as e:  # pragma: no cover - _execute reports its own failures
            error, trace = f"{type(e).__name__}: {e}", traceback.format_exc()
        finally:
            events.finished(spec.job_id, outputs, error, trace, status)

    def _execute(self, spec: "JobSpec", tool: Tool, events: RunnerEvents, ctx: RunContext) -> tuple:
        """Run the tool here, in this process: (outputs, error, trace, status)."""
        try:
            events.started(spec.job_id)
            params = tool.parse(spec.params, events.upload)
            result = tool.run_fn(params, ctx)
            return events.render(spec.job_id, result), "", "", "done"
        except Cancelled:
            return None, "", "", "cancelled"
        except ToolError as e:
            return None, str(e), "", "failed"
        except Exception as e:  # noqa: BLE001 - every failure is the job's
            return None, f"{type(e).__name__}: {e}", traceback.format_exc(), "failed"


# ---- a job in a process of its own (docs/SECURITY_AUDIT.md H4) -------------------------------------------------------

# Names of environment variables a job's process never gets: the server's tokens and anything like them.
SECRET_NAMES = re.compile(r"TOKEN|SECRET|PASSW|CREDENTIAL|_KEY$|^SSH_AUTH_SOCK$|^GIT_ASKPASS$|^SSH_ASKPASS$|COOKIE|SESSION",
                          re.IGNORECASE)
CANCEL_GRACE = 10  # seconds a cancelled job's process has to stop by itself before it is killed


def child_env(extra: dict | None = None) -> dict:
    """This process's environment without its secrets, for a job's process."""
    env = {k: v for k, v in os.environ.items() if not SECRET_NAMES.search(k)}
    env.update(extra or {})
    return env


class ProcessRunner(LocalRunner):
    """Jobs kept in the history run each in a **process of its own** (mister_plis/jobproc.py): a tool that crashes,
    fills the memory or hangs takes only its own job with it, a crafted input file reaches only that process, and the
    process has none of the server's secrets in its environment. With ``job_user`` (config.toml; Linux and macOS), it
    runs as that other user of the computer — through ``sudo -n -u`` —, who can't read the server's secrets folder at
    all. Live calculator runs stay in the server's own threads: they are instant, and starting Python for each would
    make them slow.

    The tools' code is still imported by the server to draw their forms: a tool source is still trusted as a whole
    (a source that isn't the lab's own is reviewed before it is switched on: docs/ADDING_TOOLS.md)."""

    def __init__(self, max_workers: int = 8, folders: Callable[[], list[dict]] = lambda: [], job_user: str = "",
                 command: list[str] | None = None, env: Callable[[], dict] | None = None):
        super().__init__(max_workers)
        self.folders = folders  # the tool folders the server loaded (registry.folders)
        self.job_user = job_user
        self.command = command  # tests: another child command
        self.env = env or (lambda: {})  # the settings a job's process needs (folders): MISTER_PLIS_* variables

    def child_command(self) -> list[str]:
        if self.command:
            return list(self.command)
        script = str(Path(__file__).resolve().parent / "jobproc.py")
        cmd = [sys.executable, "-P", script]
        if self.job_user:
            return ["sudo", "-n", "-u", self.job_user, "--", *cmd]
        return cmd

    def _execute(self, spec: "JobSpec", tool: Tool, events: RunnerEvents, ctx: RunContext) -> tuple:
        folder = next((f for f in self.folders() if f.get("name") == spec.tool_source), None) if spec.tool_source else None
        if not spec.record or folder is None:  # a live run; or a tool that isn't from a tool folder (one made in code)
            return super()._execute(spec, tool, events, ctx)
        try:
            uploads = {}
            for entries in (spec.inputs or {}).values():
                for e in entries if isinstance(entries, list) else []:
                    uid = str(e.get("id") or "")
                    if uid and uid not in uploads:
                        up = events.upload(uid)
                        uploads[uid] = {"name": up.name, "path": str(up.path), "size": up.size}
        except ToolError as e:
            return None, str(e), "", "failed"
        payload = {"spec": spec.to_dict(), "workdir": str(ctx.workdir), "uploads": uploads, "env": self.env(),
                   "folder": {k: (str(v) if isinstance(v, Path) else v) for k, v in folder.items()
                              if k in ("name", "path", "url", "commit", "packages", "package")},
                   "umask": 0o002 if self.job_user else None}
        try:
            proc = subprocess.Popen(self.child_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                                    cwd=str(ctx.workdir), env=child_env(), text=True, encoding="utf-8", errors="replace")
        except OSError as e:
            return None, f"The job's process couldn't be started: {e}", "", "failed"
        proc.stdin.write(json.dumps(payload, default=str) + "\n")
        proc.stdin.flush()
        stop = threading.Event()

        def watch() -> None:  # cancelling: ask, then insist
            while not stop.wait(0.3):
                if ctx.cancelled:
                    try:
                        proc.stdin.write("cancel\n")
                        proc.stdin.flush()
                    except (OSError, ValueError):
                        pass
                    if not stop.wait(CANCEL_GRACE) and proc.poll() is None:
                        proc.kill()
                    return

        threading.Thread(target=watch, daemon=True, name=f"watch-{spec.job_id}").start()
        end = None
        try:
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("event") == "started":
                    events.started(spec.job_id)
                if msg.get("event") in ("report", "finished"):
                    if "progress" in msg:
                        p = msg.get("progress")
                        ctx.progress_value = None if p is None else max(0.0, min(1.0, float(p)))
                    if isinstance(msg.get("message"), str):
                        ctx.message = msg["message"][:500]
                    for line_ in (msg.get("logs") or [])[:5000]:
                        ctx.log(str(line_))
                if msg.get("event") == "finished":
                    end = msg
            proc.wait()
        finally:
            stop.set()
            try:
                proc.stdin.close()
            except OSError:
                pass
        if end is None:
            if ctx.cancelled:
                return None, "", "", "cancelled"
            return None, f"The job's process stopped unexpectedly (exit code {proc.returncode}).", "", "failed"
        if isinstance(end.get("phrases"), dict):
            events.recording(spec.job_id, end["phrases"])
        status = end.get("status") if end.get("status") in ("done", "failed", "cancelled") else "failed"
        outputs = end.get("outputs") if status == "done" and isinstance(end.get("outputs"), list) else None
        return outputs, str(end.get("error") or ""), str(end.get("trace") or ""), status


Factory = Callable[[int], Runner]
