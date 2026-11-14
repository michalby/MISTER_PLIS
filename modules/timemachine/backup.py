"""Time Machine's own backup, in ``<backup folder>/Time Machine/`` (reorg phase P4, task 4.9).

Before P4, Time Machine existed only on the server's disk: its history was a local git repository, never pushed,
and its added-by-hand results and tasks were nowhere else. Now, whenever it changed (checked every 10 minutes,
and on **Back up Time Machine now**), it writes:

    <backup>/Time Machine/
        timemachine.bundle      the whole repository — every kept file and every change — as one git bundle
        projects.md             the projects and what is in each, readable
        index.json              what is kept: job number, title, who, when, projects
        <person>/<… (job id)>/  each kept result, in the same readable form as a job's backup (README, workbook…)

**Restore Time Machine from the backup** (Settings → Jobs & backup) clones the bundle into place; the current folder is kept,
renamed ``*.replaced-<date>``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from mister_plis.backup import copy_job, job_folder
from mister_plis.errors import ToolError
from mister_plis.jobstore import write_json

FOLDER = "Time Machine"
BUNDLE = "timemachine.bundle"


class TimeMachineBackup:
    def __init__(self, tm, ctx):
        self.tm, self.ctx = tm, ctx
        self.state_file = ctx.data / "backup.json"
        self.lock = threading.Lock()

    def folder(self) -> Path | None:
        bd = self.ctx.backups.settings().backup_dir
        return Path(bd) / FOLDER if bd else None

    def state(self) -> dict:
        try:
            d = json.loads(self.state_file.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _git(self, *args, cwd: Path | None = None) -> tuple[int, str]:
        r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=cwd or self.tm.root, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr).strip()

    def run(self, force: bool = False) -> dict:
        """Write the backup if Time Machine changed since the last one (``force``: anyway)."""
        dest = self.folder()
        if dest is None or not dest.parent.is_dir():
            return {"ok": False, "reason": "no backup folder"}
        if not self.tm.history.available:
            return {"ok": False, "reason": "no history (git) here"}
        with self.lock:
            code, head = self._git("rev-parse", "HEAD")
            if code != 0:
                return {"ok": False, "reason": head}
            state = self.state()
            if not force and state.get("head") == head and (dest / BUNDLE).is_file():
                return {"ok": True, "skipped": True}
            dest.mkdir(parents=True, exist_ok=True)
            tmp = dest / (BUNDLE + ".partial")
            code, out = self._git("bundle", "create", str(tmp), "--all")
            if code != 0:
                tmp.unlink(missing_ok=True)
                raise OSError(f"git bundle failed: {out}")
            code, out = self._git("bundle", "verify", str(tmp))
            if code != 0:
                tmp.unlink(missing_ok=True)
                raise OSError(f"the bundle doesn't check out: {out}")
            tmp.replace(dest / BUNDLE)
            entries = []
            copied = 0
            for e, job in self.tm.all():
                entries.append({"id": job.id, "title": e.get("title") or job.title, "tool": job.tool_name, "user": job.user,
                                "added": e.get("added"), "added_by": e.get("added_by"), "kind": e.get("kind", "job"),
                                "version_of": e.get("version_of", ""), "projects": e.get("projects", [])})
                if job_folder(job, dest).exists():
                    continue
                try:
                    copy_job(job, dest, self.ctx.services.lab_name)
                    copied += 1
                except OSError as err:  # one result that can't be copied must not stop the bundle (which has it anyway)
                    print(f"Time Machine backup: {job.id}: {err}", flush=True)
            write_json(dest / "index.json", {"format": "mister-plis-timemachine-backup", "written": time.time(), "head": head,
                                             "entries": entries})
            (dest / "projects.md").write_text(self._projects_md(entries), encoding="utf-8")
            state = {"head": head, "at": time.time(), "entries": len(entries), "folder": str(dest)}
            write_json(self.state_file, state)
            return {"ok": True, "copied": copied, **state}

    def _projects_md(self, entries: list[dict]) -> str:
        lines = ["# Time Machine — projects", "", f"Written {datetime.now():%Y-%m-%d %H:%M}. Every kept result is in its own folder next to "
                 "this file; the whole Time Machine (with its history) is `timemachine.bundle`.", ""]
        projects = self.tm.projects()
        for p in projects:
            lines += [f"## {p.get('name')}", ""]
            if p.get("description"):
                lines += [p["description"], ""]
            inside = [e for e in entries if p.get("id") in (e.get("projects") or [])]
            lines += [f"- `{e['id']}` {e.get('tool') or ''}{' — ' + e['title'] if e.get('title') else ''} ({e.get('user') or '—'})" for e in inside]
            lines.append("")
        loose = [e for e in entries if not e.get("projects")]
        if loose:
            lines += ["## Not in a project", ""] + [f"- `{e['id']}` {e.get('tool') or ''}{' — ' + e['title'] if e.get('title') else ''}" for e in loose]
        return "\n".join(lines) + "\n"

    def info(self) -> dict:
        dest = self.folder()
        bundle = dest / BUNDLE if dest else None
        return {"folder": str(dest) if dest else "", "kept_in": str(self.tm.root), "state": self.state(),
                "bundle": bool(bundle and bundle.is_file()), "bundle_at": bundle.stat().st_mtime if bundle and bundle.is_file() else None}

    def restore(self) -> dict:
        """Replace Time Machine's folder with the one in the backup (the current one is kept, renamed)."""
        dest = self.folder()
        bundle = dest / BUNDLE if dest else None
        if not bundle or not bundle.is_file():
            raise ToolError("There is no Time Machine backup in the backup folder yet.")
        root = self.tm.root
        with self.lock, self.tm._lock:
            new = root.with_name(root.name + ".restoring")
            shutil.rmtree(new, ignore_errors=True)
            code, out = self._git("clone", "--quiet", str(bundle), str(new), cwd=root.parent)
            if code != 0:
                shutil.rmtree(new, ignore_errors=True)
                raise ToolError(f"Couldn't read the Time Machine backup: {out}")
            self._git("remote", "remove", "origin", cwd=new)
            old = root.with_name(f"{root.name}.replaced-{datetime.now():%Y-%m-%d-%H%M%S}")
            if root.exists():
                root.rename(old)
            new.rename(root)
            self.tm.load()
        return {"ok": True, "entries": len(self.tm.all()), "previous": str(old)}
