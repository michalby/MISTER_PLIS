"""Time Machine: results worth keeping, copied out of Jobs & results so they stay for good.

Jobs & results is a working area — jobs are cleaned up after a while (and copied to the backup folder).
When a result becomes the basis of a study, it is added to Time Machine: its files and the description of
the run are copied to ``<storage>/modules/timemachine/<job number>/`` (``<data>/timemachine/`` before reorg P4), which is never
cleaned up::

    <storage>/modules/timemachine/
        .git/                        ← the history: every change is a commit (local only, see history.py)
        projects.json                ← the projects: name, description, colour
        20261019-142301-a1b2c3/
            meta.json                ← the job as it was: tool, who, when, input files, settings, results
            out/…                    ← the result files
            entry.json               ← who added it and when, where it came from, its projects and a note

A job is added from its result page, or by typing its job number on the Time Machine page — then it is looked
up among the jobs still on the server and, if it was cleaned up already, in the backup folder set in Settings.
The original stays where it was and follows the usual cleanup and backup schedule.

A kept result can have versions: a changed file uploaded later (e.g. an Excel sheet with analysis added) or a
re-run of the job with changed settings. Each version is an entry of its own (``version_of`` names the first
one), shown as a new point on the timeline. Things that never were jobs — other files worth keeping — can be
added by hand with a title and a description ("manual" entries); they exist only in Time Machine.

A task is a place kept for a result that doesn't exist yet: a title, a description and the person who is to do
it, no files. When the files are uploaded to it, or a job is added to it (by its number, or from the job's result
page), that becomes the task's next version and the task is done. Taking that version out again reopens it.

A kept result can be in any number of projects; moving it between projects, renaming a project, editing a note
or removing a result is one commit each, so "See history" shows who changed what and when, and a removed
result can be brought back.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from mister_plis.backup import JOB_ID, BackupCatalogue, matches, normalize_query  # noqa: F401  (re-exported)
from mister_plis.errors import ToolError
from mister_plis.jobs import ACTIVE, Job, JobManager, _new_id, clean_text
from mister_plis.toolkit import safe_filename

from .history import LocalHistory

PROJECT_ID = re.compile(r"^p-[0-9a-f]{6}$")
PICTURES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
COLORS = ("#a78bfa", "#f472b6", "#38bdf8", "#34d399", "#fbbf24", "#fb7185", "#818cf8", "#2dd4bf", "#f97316", "#c084fc", "#a3e635", "#60a5fa")


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


class TimeMachine:
    def __init__(self, data_path: Path, jobs: JobManager, backup_dir=lambda: "", catalogue: BackupCatalogue | None = None,
                 root: Path | None = None):
        self.root = root or data_path / "timemachine"  # as a module: <storage>/modules/timemachine
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs = jobs
        self.backup_dir = backup_dir  # () → the backup folder from Settings ("" = none)
        self.catalogue = catalogue or BackupCatalogue(backup_dir)  # finds and reads jobs in it (mister_plis/backup.py)
        self.history = LocalHistory(self.root)
        self._lock = threading.RLock()
        self._entries: dict[str, dict] = {}
        self._jobs: dict[str, Job] = {}
        self._projects: dict[str, dict] = {}
        self.load()

    # ---- reading ----
    def load(self) -> None:
        with self._lock:
            projects = _read_json(self.root / "projects.json").get("projects")
            self._projects = {k: v for k, v in (projects or {}).items() if PROJECT_ID.match(k) and isinstance(v, dict)}
            entries, kept = {}, {}
            for d in sorted(self.root.iterdir()):
                if not (d.is_dir() and JOB_ID.match(d.name)):
                    continue
                try:
                    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                    entry = json.loads((d / "entry.json").read_text(encoding="utf-8"))
                    job = Job.from_meta(meta, d, record=False)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                entries[d.name], kept[d.name] = entry, job
            self._entries, self._jobs = entries, kept
            self._migrate_studies()
            if not self.history.available:
                self.history.init()
            else:
                self.history.commit("Turn studies into projects", "MISTER PLIS", ["Action: project"])

    def _migrate_studies(self) -> None:
        """Before projects there was one "study" text per result: each study becomes a project."""
        for job_id, entry in self._entries.items():
            if "projects" in entry and "study" not in entry:
                continue
            study = clean_text(entry.pop("study", ""), 80)
            entry["projects"] = [p for p in entry.get("projects", []) if p in self._projects]
            if study:
                pid = next((k for k, p in self._projects.items() if p["name"].lower() == study.lower()), None) \
                    or self._new_project(study, "", entry.get("added_by", ""))
                if pid not in entry["projects"]:
                    entry["projects"].append(pid)
            _write_json(self.root / job_id / "entry.json", entry)

    def has(self, job_id: str) -> bool:
        return job_id in self._entries

    def job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id) if JOB_ID.match(job_id or "") else None

    def entry(self, job_id: str) -> dict | None:
        return self._entries.get(job_id)

    def all(self) -> list[tuple[dict, Job]]:
        """Everything kept, newest run first."""
        with self._lock:
            items = [(self._entries[i], self._jobs[i]) for i in self._entries]
        return sorted(items, key=lambda x: x[1].created, reverse=True)

    def file_path(self, job_id: str, rel: str) -> Path | None:
        job = self.job(job_id)
        return self.jobs.file_path(job, rel) if job else None

    def files(self, job_id: str) -> list[dict]:
        """Every file kept for a job (also those not shown as a result, e.g. inside a sub-folder)."""
        job = self.job(job_id)
        out = job.workdir / "out" if job else None
        if not out or not out.is_dir():
            return []
        return [{"rel": p.relative_to(job.workdir).as_posix(), "name": p.name, "size": p.stat().st_size}
                for p in sorted(out.rglob("*")) if p.is_file()]

    def _label(self, job_id: str) -> str:
        job = self._jobs.get(job_id)
        return f"{job.tool_name} ({job_id})" if job else job_id

    # ---- versions ----
    def root_of(self, job_id: str) -> str:
        e = self._entries.get(job_id)
        return (e.get("version_of") or job_id) if e else job_id

    def lineage(self, job_id: str) -> list[str]:
        """Every version of a kept result, oldest first (the first one is version 1)."""
        root = self.root_of(job_id)
        ids = [i for i, e in self._entries.items() if i == root or e.get("version_of") == root]
        return sorted(ids, key=lambda i: (i != root, self._jobs[i].created))

    def version_number(self, job_id: str) -> int:
        line = self.lineage(job_id)
        return line.index(job_id) + 1 if job_id in line else 1

    def root_for_job(self, job: Job) -> str:
        """The kept result a job is a re-run of (following its parents), or ""."""
        seen, p = set(), job.parent
        while p and p not in seen:
            seen.add(p)
            if p in self._entries:
                return self.root_of(p)
            parent = self.jobs.get(p)
            p = parent.parent if parent else ""
        return ""

    def _lineage_projects(self, root: str) -> list[str]:
        line = self.lineage(root)
        return list(self._entries[line[-1]].get("projects", [])) if line else []

    # ---- projects ----
    def projects(self) -> list[dict]:
        counts: dict[str, int] = {}
        for e in self._entries.values():
            for p in e.get("projects", []):
                counts[p] = counts.get(p, 0) + 1
        return sorted(({"id": k, **v, "count": counts.get(k, 0)} for k, v in self._projects.items()), key=lambda p: p["created"])

    def project_name(self, pid: str) -> str:
        return self._projects.get(pid, {}).get("name", pid)

    def _save_projects(self) -> None:
        _write_json(self.root / "projects.json", {"projects": self._projects})

    def _new_project(self, name: str, description: str, by: str, color: str | None = None) -> str:
        pid = "p-" + secrets.token_hex(3)
        while pid in self._projects:
            pid = "p-" + secrets.token_hex(3)
        self._projects[pid] = {"name": name, "description": description, "color": color or COLORS[len(self._projects) % len(COLORS)],
                               "created": time.time(), "created_by": clean_text(by, 60)}
        self._save_projects()
        return pid

    def create_project(self, name: str, description: str = "", by: str = "", color: str | None = None) -> dict:
        name = clean_text(name, 80)
        if not name:
            raise ToolError("Give the project a name.")
        if color and not re.match(r"^#[0-9a-fA-F]{6}$", str(color)):
            raise ToolError("Not a colour.")
        with self._lock:
            if any(p["name"].lower() == name.lower() for p in self._projects.values()):
                raise ToolError("There is already a project with this name.")
            pid = self._new_project(name, str(description or "")[:2000], by, str(color).lower() if color else None)
            self.history.commit(f"New project “{name}”", by, [f"Project: {pid}", "Action: project"])
            return {"id": pid, **self._projects[pid], "count": 0}

    def update_project(self, pid: str, name: str | None = None, description: str | None = None, color: str | None = None, by: str = "") -> dict:
        with self._lock:
            p = self._projects.get(pid)
            if not p:
                raise ToolError("There is no such project.")
            old = dict(p)
            if name is not None:
                name = clean_text(name, 80)
                if not name:
                    raise ToolError("Give the project a name.")
                if any(k != pid and q["name"].lower() == name.lower() for k, q in self._projects.items()):
                    raise ToolError("There is already a project with this name.")
                p["name"] = name
            if description is not None:
                p["description"] = str(description)[:2000]
            if color is not None:
                if not re.match(r"^#[0-9a-fA-F]{6}$", str(color)):
                    raise ToolError("Not a colour.")
                p["color"] = str(color).lower()
            if p == old:
                return {"id": pid, **p}
            self._save_projects()
            if p["name"] != old["name"]:
                what = f"Rename project “{old['name']}” to “{p['name']}”"
            elif p["color"] != old["color"] and p.get("description") == old.get("description"):
                what = f"New colour for project “{p['name']}”: {p['color']}"
            else:
                what = f"Edit project “{p['name']}”"
            self.history.commit(what, by, [f"Project: {pid}", "Action: project"])
            return {"id": pid, **p}

    def delete_project(self, pid: str, by: str = "") -> None:
        """The project goes; its results stay in Time Machine (in their other projects, or in none)."""
        with self._lock:
            p = self._projects.pop(pid, None)
            if not p:
                raise ToolError("There is no such project.")
            jobs = []
            for job_id, e in self._entries.items():
                if pid in e.get("projects", []):
                    e["projects"] = [x for x in e["projects"] if x != pid]
                    _write_json(self.root / job_id / "entry.json", e)
                    jobs.append(job_id)
            self._save_projects()
            self.history.commit(f"Delete project “{p['name']}” ({len(jobs)} result(s) taken out of it)", by,
                                [f"Project: {pid}", *[f"Job: {j}" for j in jobs], "Action: project"])

    def merge_projects(self, pid: str, into: str, by: str = "") -> dict:
        """Everything in one project goes into another (versions too, as they share projects); the first one goes.
        One commit, so the history shows it as one change."""
        with self._lock:
            src, dest = self._projects.get(pid), self._projects.get(into)
            if not src or not dest:
                raise ToolError("There is no such project.")
            if pid == into:
                raise ToolError("Choose another project to merge into.")
            jobs = []
            for job_id, e in self._entries.items():
                if pid in e.get("projects", []):
                    e["projects"] = list(dict.fromkeys(into if x == pid else x for x in e["projects"]))
                    _write_json(self.root / job_id / "entry.json", e)
                    jobs.append(job_id)
            del self._projects[pid]
            if src.get("description") and src["description"] not in dest.get("description", ""):
                dest["description"] = "\n".join(x for x in (dest.get("description", ""), src["description"]) if x)[:2000]
            self._save_projects()
            self.history.commit(f"Merge project “{src['name']}” into “{dest['name']}” ({len(jobs)} result(s) moved)", by,
                                [f"Project: {pid}", f"Project: {into}", *[f"Job: {j}" for j in jobs], "Action: project"])
            return {"id": into, **dest, "moved": len(jobs)}

    def _check_projects(self, pids) -> list[str]:
        pids = list(dict.fromkeys(str(p) for p in (pids or [])))
        unknown = [p for p in pids if p not in self._projects]
        if unknown:
            raise ToolError("There is no such project.")
        return pids

    def _names(self, pids) -> str:
        return ", ".join(f"“{self.project_name(p)}”" for p in pids)

    def assign(self, job_ids: list[str], add=(), remove=(), by: str = "") -> int:
        """Put results into projects and/or take them out — one commit for the whole change ("move" = both)."""
        with self._lock:
            add, remove = self._check_projects(add), self._check_projects(remove)
            ids = [j for j in dict.fromkeys(job_ids) if j in self._entries]
            ids = list(dict.fromkeys(v for j in ids for v in self.lineage(j)))  # all versions of a result share its projects
            if not ids:
                raise ToolError("Choose at least one kept result.")
            changed = []
            for job_id in ids:
                e = self._entries[job_id]
                base = [p for p in e.get("projects", []) if p not in remove]
                new = base + [p for p in add if p not in base]
                if new != e.get("projects", []):
                    e["projects"] = new
                    _write_json(self.root / job_id / "entry.json", e)
                    changed.append(job_id)
            if changed:
                roots = list(dict.fromkeys(self.root_of(j) for j in changed))
                what = self._label(roots[0]) if len(roots) == 1 else f"{len(roots)} results"
                if add and remove:
                    subject = f"Move {what} from {self._names(remove)} to {self._names(add)}"
                elif add:
                    subject = f"Add {what} to {self._names(add)}"
                else:
                    subject = f"Take {what} out of {self._names(remove)}"
                self.history.commit(subject, by, [*[f"Job: {j}" for j in changed], *[f"Project: {p}" for p in [*remove, *add]], "Action: projects"])
            return len(changed)

    def set_projects(self, job_id: str, pids: list[str], by: str = "") -> dict:
        """A result's projects as a whole list (the checkboxes on its page)."""
        with self._lock:
            e = self._entries.get(job_id)
            if not e:
                raise ToolError("This job is not in Time Machine.")
            pids = self._check_projects(pids)
            old = e.get("projects", [])
            self.assign([job_id], add=[p for p in pids if p not in old], remove=[p for p in old if p not in pids], by=by)
            return self._entries[job_id]

    # ---- finding a job by its number ----
    def find(self, text: str) -> list[dict]:
        """Jobs matching a (partial) job number: still in Jobs & results, or in the backup folder."""
        q = normalize_query(text)
        if not q:
            return []
        found: dict[str, dict] = {}
        for job in self.jobs.recent(10**9):
            if matches(job.id, q):
                found[job.id] = {"id": job.id, "source": "jobs", "tool_name": job.tool_name, "tool_id": job.tool_id, "user": job.user,
                                 "keyword": job.keyword, "created": job.created, "status": job.status}
        for row in self.catalogue.find(q):
            if row["id"] in found:
                continue
            found[row["id"]] = {"id": row["id"], "source": "backup", "tool_name": row.get("tool_name") or Path(row["folder"]).name,
                                "tool_id": row.get("tool_id", ""), "user": row.get("user", ""), "keyword": row.get("keyword", ""),
                                "created": row.get("created"), "status": "done", "folder": row["folder"], "parent": row.get("parent", "")}
        for job_id, job in self._jobs.items():  # also what exists only here (manual entries, uploaded versions)
            if job_id not in found and matches(job_id, q):
                found[job_id] = {"id": job_id, "source": "tm", "tool_name": job.tool_name, "tool_id": job.tool_id, "user": job.user,
                                 "keyword": job.keyword, "created": job.created, "status": "done"}
        for f in found.values():
            f["in_tm"] = self.has(f["id"])
        return sorted(found.values(), key=lambda f: f.get("created") or 0, reverse=True)

    # ---- adding ----
    def add(self, job: Job, added_by: str = "", note: str = "", projects=(), version_of: str = "") -> dict:
        """Copy a finished job from Jobs & results. Already there → nothing is copied again."""
        if job.status in ACTIVE:
            raise ToolError("The job is still running — add it to Time Machine when it has finished.")
        if job.status != "done":
            raise ToolError("Only finished jobs with results can be kept in Time Machine.")
        if not job.record:
            raise ToolError("This tool's results are not kept in the job history, so they can't go to Time Machine.")
        if self.has(job.id):
            return {**self._entries[job.id], "already": True}

        def fill(part: Path):
            out = job.workdir / "out"
            if out.is_dir():
                shutil.copytree(out, part / "out")
            d = job.to_dict(logs=False, translated=False)  # kept in English, translated when shown
            d["log"] = job.logs[-2000:]
            d["error"], d["message"] = job.error, job.saved_message
            return d

        return self._store(job.id, fill, "jobs", str(job.workdir), added_by, note, projects,
                           version_of=version_of or self.root_for_job(job))

    def retrieve(self, text: str, added_by: str = "", projects=(), version_of: str = "") -> dict:
        """Find a job by its number and copy it here; raises ToolError when nothing (or more than one) matches."""
        found = self.find(text)
        q = normalize_query(text)
        exact = [f for f in found if f["id"] == q]
        if exact:
            found = exact
        if not found:
            where = " or in the backup folder" if self.backup_dir() else ""
            raise ToolError(f"No job {q or text} in Jobs & results{where}.")
        if len(found) > 1:
            raise ToolError("Several jobs match — type more of the job number.")
        hit = found[0]
        if hit["in_tm"] and version_of:
            with self._lock:
                return self._link(hit["id"], version_of, added_by)
        if hit["in_tm"]:
            if projects:
                self.assign([hit["id"]], add=projects, by=added_by)
            return {**self._entries[hit["id"]], "already": True}
        if hit["source"] == "jobs":
            job = self.jobs.get(hit["id"])
            if job and job.workdir.is_dir():
                return self.add(job, added_by, projects=projects, version_of=version_of)
        return self._from_backup(hit["id"], Path(hit["folder"]), added_by, projects, version_of, parent=hit.get("parent", ""))

    def _from_backup(self, job_id: str, folder: Path, added_by: str, projects=(), version_of: str = "", parent: str = "") -> dict:
        """A job in the backup folder (maybe cleaned up from the server since), read by the backup catalogue: a v1
        backup is checked against its manifest and brings its files, inputs and full tables; a v0 one its files."""
        def fill(part: Path):
            rec = self.catalogue.import_files(folder, part)
            for k in ("imported", "backed_up"):
                rec.pop(k, None)
            return rec

        if not version_of and parent:
            version_of = self.root_of(parent) if parent in self._entries else ""
        return self._store(job_id, fill, "backup", str(folder), added_by, "", projects, version_of=version_of)

    def _store(self, job_id: str, fill, source: str, source_path: str, added_by: str, note: str, projects,
               version_of: str = "", kind: str = "job", extra: dict | None = None) -> dict:
        if not JOB_ID.match(job_id):
            raise ToolError("Not a job number.")
        dest = self.root / job_id
        part = self.root / f".{job_id}.partial"
        with self._lock:
            if job_id in self._entries:
                return {**self._entries[job_id], "already": True}
            projects = self._check_projects(projects)
            if version_of and version_of not in self._entries:
                raise ToolError("This job is not in Time Machine.")
            if version_of:
                version_of = self.root_of(version_of)
                projects = list(dict.fromkeys([*self._lineage_projects(version_of), *projects]))
            shutil.rmtree(part, ignore_errors=True)
            part.mkdir(parents=True)
            try:
                meta = fill(part)
                meta["status"] = "done"
                (part / "meta.json").write_text(json.dumps(meta, default=str), encoding="utf-8")
                entry = {"id": job_id, "added": time.time(), "added_by": clean_text(added_by, 60), "source": source,
                         "source_path": source_path, "kind": kind, "version_of": version_of, "projects": projects,
                         "note": str(note or "")[:4000], **(extra or {})}
                (part / "entry.json").write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
                if dest.exists():
                    shutil.rmtree(dest)
                part.rename(dest)
            except OSError as e:
                shutil.rmtree(part, ignore_errors=True)
                raise ToolError(f"Could not copy the job to Time Machine: {e.strerror or e}") from None
            self._entries[job_id] = entry
            self._jobs[job_id] = Job.from_meta(meta, dest, record=False)
            into = f" into {self._names(projects)}" if projects and not version_of else ""
            if kind == "manual":
                subject, action = f"Add “{entry.get('title')}” by hand ({job_id}){into}", "manual"
            elif kind == "task":
                who = f" for {entry['assignee']}" if entry.get("assignee") else ""
                subject, action = f"New task “{entry.get('title')}”{who} ({job_id}){into}", "task"
            elif version_of:
                n = self.version_number(job_id)
                how = "a new file" if kind == "update" else self._label(job_id)
                subject, action = f"Version {n} of {self._label(version_of)}: {how}", "version"
                if self._finish_task(version_of, job_id, added_by):
                    subject = f"Task “{self._entries[version_of].get('title')}” done: {how} ({job_id})"
            else:
                where = "from the backup folder" if source == "backup" else "from Jobs & results"
                subject, action = f"Keep {self._label(job_id)} {where}{into}", "add"
            self.history.commit(subject, added_by, [f"Job: {job_id}", *([f"Job: {version_of}"] if version_of else []),
                                                    *[f"Project: {p}" for p in projects], f"Action: {action}"])
        return entry

    # ---- files added by hand: a new version of a kept result, or something that never was a job ----
    def _files_entry(self, uploads, kind: str, tool_id: str, tool_name: str, by: str, note: str, projects=(),
                     version_of: str = "", extra: dict | None = None, keyword: str = "", title: str = "") -> dict:
        uploads = [u for u in uploads if u]
        if not uploads:
            raise ToolError("Add at least one file.")
        job_id = _new_id()
        while job_id in self._entries:
            job_id = _new_id()
        now = time.time()

        def fill(part: Path):
            out = part / "out"
            out.mkdir()
            outputs, used = [], set()
            for up in uploads:
                name = safe_filename(up.name)
                stem, suffix, n = Path(name).stem, Path(name).suffix, 2
                while name.lower() in used:
                    name, n = f"{stem}-{n}{suffix}", n + 1
                used.add(name.lower())
                shutil.copy2(up.path, out / name)
                url = f"/api/jobs/{job_id}/files/out/{name}"
                size = (out / name).stat().st_size
                if suffix.lower() in PICTURES:
                    outputs.append({"kind": "image", "url": url, "name": name, "size": size, "title": "", "caption": name})
                else:
                    outputs.append({"kind": "file", "url": url, "name": name, "label": name, "description": "", "size": size, "primary": False})
            return {"id": job_id, "tool_id": tool_id, "tool_name": tool_name, "user": clean_text(by, 60), "keyword": keyword, "title": title,
                    "status": "done", "created": now, "started": now, "finished": now, "params": {}, "files": {}, "outputs": outputs}

        return self._store(job_id, fill, "upload", "", by, note, projects, version_of=version_of, kind=kind, extra=extra)

    def add_manual(self, title: str, description: str, uploads, projects=(), by: str = "") -> dict:
        """Something worth keeping that never was a job: a title, a description and files (all required)."""
        title, description = clean_text(title, 120), str(description or "").strip()[:4000]
        if not title:
            raise ToolError("Give it a title.")
        if not description:
            raise ToolError("Describe what it is.")
        return self._files_entry(uploads, "manual", "", title, by, "", projects, extra={"title": title, "description": description})

    def add_version_files(self, job_id: str, uploads, note: str = "", by: str = "") -> dict:
        """A changed file for a kept result (e.g. the downloaded sheet with analysis added) as its next version."""
        with self._lock:
            if job_id not in self._entries:
                raise ToolError("This job is not in Time Machine.")
            root = self.root_of(job_id)
            first = self._jobs.get(root) or self._jobs[job_id]
            extra = {k: self._entries[root][k] for k in ("title", "description") if root in self._entries and k in self._entries[root]}
            return self._files_entry(uploads, "update", first.tool_id, first.tool_name, by, note, version_of=root, extra=extra, title=first.title,
                                     keyword=first.keyword)


    # ---- tasks: a result that doesn't exist yet, and who is to make it ----
    def is_task(self, job_id: str) -> bool:
        return (self._entries.get(job_id) or {}).get("kind") == "task"

    def add_task(self, title: str, description: str, assignee: str = "", projects=(), by: str = "") -> dict:
        """A title and a description (both required), maybe the person who is to do it — no files yet."""
        title, description = clean_text(title, 120), str(description or "").strip()[:4000]
        if not title:
            raise ToolError("Give it a title.")
        if not description:
            raise ToolError("Describe what it is.")
        job_id = _new_id()
        while job_id in self._entries:
            job_id = _new_id()
        now = time.time()

        def fill(part: Path):
            return {"id": job_id, "tool_id": "", "tool_name": title, "user": clean_text(by, 60), "keyword": "", "title": "",
                    "status": "done", "created": now, "started": now, "finished": None, "params": {}, "files": {}, "outputs": []}

        return self._store(job_id, fill, "task", "", by, "", projects, kind="task",
                           extra={"title": title, "description": description, "assignee": clean_text(assignee, 60),
                                  "done": None, "done_by": "", "done_with": ""})

    def _finish_task(self, root: str, job_id: str, by: str) -> bool:
        """The first version added to an open task is what it asked for: the task is done."""
        e = self._entries.get(root)
        if not e or e.get("kind") != "task" or e.get("done"):
            return False
        e.update(done=time.time(), done_by=clean_text(by, 60), done_with=job_id)
        _write_json(self.root / root / "entry.json", e)
        return True

    def _reopen_task(self, root: str) -> bool:
        """Its versions were taken out again: the task is open once more (or done by the version that's left)."""
        e = self._entries.get(root)
        if not e or e.get("kind") != "task" or not e.get("done") or e.get("done_with") in self._entries:
            return False
        left = [v for v in self.lineage(root) if v != root]
        if left:
            e["done_with"] = left[0]
        else:
            e.update(done=None, done_by="", done_with="")
        _write_json(self.root / root / "entry.json", e)
        return not left

    def tasks(self, open_only: bool = False) -> list[tuple[dict, Job]]:
        """The tasks, newest first; open_only → only those still to do."""
        return [(e, j) for e, j in self.all() if e.get("kind") == "task" and not (open_only and e.get("done"))]

    def update_task(self, job_id: str, assignee: str | None = None, description: str | None = None, by: str = "") -> dict:
        with self._lock:
            e = self._entries.get(job_id)
            if not e or e.get("kind") != "task":
                raise ToolError("This is not a task.")
            changes = []
            if assignee is not None and clean_text(assignee, 60) != e.get("assignee", ""):
                old, e["assignee"] = e.get("assignee", ""), clean_text(assignee, 60)
                changes.append(f"assigned to {e['assignee']}" if e["assignee"] else f"no longer assigned to {old}")
            if description is not None:
                description = str(description).strip()[:4000]
                if not description:
                    raise ToolError("Describe what it is.")
                if description != e.get("description", ""):
                    e["description"] = description
                    changes.append("description changed")
            if changes:
                _write_json(self.root / job_id / "entry.json", e)
                self.history.commit(f"Task “{e.get('title')}” ({job_id}): {', '.join(changes)}", by, [f"Job: {job_id}", "Action: task"])
            return e

    def _link(self, job_id: str, root: str, by: str = "") -> dict:
        """A result kept already, on its own, becomes the next version of another one (e.g. what a task asked for)."""
        e = self._entries[job_id]
        root = self.root_of(root)
        if job_id == root or e.get("version_of") == root:
            return {**e, "already": True}
        if e.get("version_of") or len(self.lineage(job_id)) > 1 or e.get("kind") == "task":
            raise ToolError("This job is already kept as a version of another result.")
        e["version_of"] = root
        e["projects"] = list(dict.fromkeys([*self._lineage_projects(root), *e.get("projects", [])]))
        _write_json(self.root / job_id / "entry.json", e)
        n = self.version_number(job_id)
        subject = f"Version {n} of {self._label(root)}: {self._label(job_id)}"
        if self._finish_task(root, job_id, by):
            subject = f"Task “{self._entries[root].get('title')}” done: {self._label(job_id)}"
        self.history.commit(subject, by, [f"Job: {job_id}", f"Job: {root}", "Action: version"])
        return {**e, "already": True}

    def add_to(self, job: Job, root: str, by: str = "") -> dict:
        """A finished job as the next version of a kept result — the "for a task" choice on a result page."""
        with self._lock:
            if root not in self._entries:
                raise ToolError("This job is not in Time Machine.")
            if self.has(job.id):
                return self._link(job.id, root, by)
        return self.add(job, by, version_of=root)

    # ---- changing ----
    def set_title(self, job_id: str, title: str, by: str = "") -> dict:
        """The title after the tool's name ("Chlorophyll concentration — WT vs mutant"). Something added by hand has no
        tool: its title is its name and can't be empty."""
        with self._lock:
            entry, job = self._entries.get(job_id), self._jobs.get(job_id)
            if not entry or not job:
                raise ToolError("This job is not in Time Machine.")
            title = clean_text(title, 120)
            meta_file = self.root / job_id / "meta.json"
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if entry.get("kind") in ("manual", "task"):
                if not title:
                    raise ToolError("Give it a title.")
                old = entry.get("title", "")
                if title == old:
                    return entry
                entry["title"] = job.tool_name = meta["tool_name"] = title
                _write_json(self.root / job_id / "entry.json", entry)
            else:
                old = job.title
                if title == old:
                    return entry
                job.title = meta["title"] = title
            meta_file.write_text(json.dumps(meta, default=str), encoding="utf-8")
            what = f"“{old}” → “{title}”" if old and title else f"“{title}”" if title else f"remove “{old}”"
            self.history.commit(f"Title of {job.tool_name if entry.get('kind') not in ('manual', 'task') else 'item'} ({job_id}): {what}", by,
                                [f"Job: {job_id}", "Action: title"])
            return entry

    def update(self, job_id: str, note: str | None = None, projects: list | None = None, by: str = "") -> dict:
        with self._lock:
            entry = self._entries.get(job_id)
            if not entry:
                raise ToolError("This job is not in Time Machine.")
            if projects is not None:
                self.set_projects(job_id, projects, by)
            if note is not None and str(note)[:4000] != entry.get("note", ""):
                entry["note"] = str(note)[:4000]
                _write_json(self.root / job_id / "entry.json", entry)
                self.history.commit(f"Edit the note of {self._label(job_id)}", by, [f"Job: {job_id}", "Action: note"])
            return entry

    def remove(self, job_id: str, by: str = "") -> None:
        with self._lock:
            if job_id not in self._entries:
                raise ToolError("This job is not in Time Machine.")
            label, pids = self._label(job_id), self._entries[job_id].get("projects", [])
            root = self._entries[job_id].get("version_of", "")
            del self._entries[job_id], self._jobs[job_id]
            shutil.rmtree(self.root / job_id, ignore_errors=True)
            reopened = self._reopen_task(root) if root else False
            subject = f"Remove {label}" + (f" — task “{self._entries[root].get('title')}” is open again" if reopened else "")
            self.history.commit(subject, by, [f"Job: {job_id}", *([f"Job: {root}"] if reopened else []),
                                              *[f"Project: {p}" for p in pids], "Action: remove"])

    def restore(self, sha: str, by: str = "") -> dict:
        """Bring back a result removed in commit ``sha``, as it was just before."""
        with self._lock:
            c = self.history.get(sha)
            if not c or c["action"] != "remove" or len(c["jobs"]) != 1:
                raise ToolError("Only a removed result can be brought back from the history.")
            job_id = c["jobs"][0]
            if job_id in self._entries:
                raise ToolError("This result is already back in Time Machine.")
            if not self.history.restore_folder(c["id"], job_id):
                raise ToolError("Could not bring the result back from the history.")
            d = self.root / job_id
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                entry = json.loads((d / "entry.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ToolError("Could not bring the result back from the history.") from None
            entry["projects"] = [p for p in entry.get("projects", []) if p in self._projects]
            _write_json(d / "entry.json", entry)
            self._entries[job_id], self._jobs[job_id] = entry, Job.from_meta(meta, d, record=False)
            if entry.get("version_of"):
                self._finish_task(entry["version_of"], job_id, by)
            self.history.commit(f"Bring back {self._label(job_id)} (removed {time.strftime('%Y-%m-%d', time.localtime(c['at']))})", by,
                                [f"Job: {job_id}", *[f"Project: {p}" for p in entry["projects"]], "Action: restore"])
            return entry

    def rename_person(self, old: str, new: str, by: str = "") -> int:
        """One person under two names (merged in People): ``old`` (any capitals) becomes ``new`` on everything kept
        here — who ran it, who kept it, whom a task is for, who started a project. Returns how many items changed."""
        same = lambda n: bool(n) and n.casefold() == old.casefold()
        with self._lock:
            changed = 0
            for job_id, entry in self._entries.items():
                job, hit = self._jobs[job_id], False
                for k in ("added_by", "assignee"):
                    if same(entry.get(k, "")):
                        entry[k], hit = new, True
                if hit:
                    _write_json(self.root / job_id / "entry.json", entry)
                if same(job.user):
                    meta_file = self.root / job_id / "meta.json"
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    job.user = meta["user"] = new
                    meta_file.write_text(json.dumps(meta, default=str), encoding="utf-8")
                    hit = True
                changed += hit
            projects = [p for p in self._projects.values() if same(p.get("created_by", ""))]
            for p in projects:
                p["created_by"] = new
            if projects:
                self._save_projects()
            if changed or projects:
                self.history.commit(f"“{old}” and “{new}” are one person: {changed} item(s) now under “{new}”", by, ["Action: people"])
            return changed

    def people(self) -> list[str]:
        """Everyone who ran a job, kept something or was given a task — to choose whom a task is for."""
        names = {j.user for j in self.jobs.recent(10**9)} | {j.user for j in self._jobs.values()}
        names |= {e.get(k, "") for e in self._entries.values() for k in ("assignee", "added_by")}
        return sorted((n for n in names if n), key=str.casefold)

    def log(self, job: str = "", project: str = "", limit: int = 200) -> list[dict]:
        out = []
        for c in self.history.log(job, project, limit):
            c["project_names"] = [self.project_name(p) for p in c["projects"]]
            c["restorable"] = c["action"] == "remove" and len(c["jobs"]) == 1 and c["jobs"][0] not in self._entries
            out.append(c)
        return out


def _read_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}

