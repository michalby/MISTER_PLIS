"""Runs tools in worker threads, keeps their results on disk, and stores uploads.

Each job kept in the history is a folder ``<storage>/jobs/<job id>/`` (``job.json``, ``inputs/``, ``out/``,
``tables/``), listed in ``index.json`` (mister_plis/jobstore.py). Finished jobs are held in memory as their index row;
their results, settings and log are read from ``job.json`` the first time they are needed, and only the most recently
used ones stay loaded.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .errors import ToolError
from .i18n import phrases, tr
from .inputs import File as FileInput
from .inputs import UploadedFile
from .jobformat import JOB_FILE, V0_FILE, read_job, record_file
from .jobstore import JobStore, folder_size, result_names, write_json
from .outputs import Table as TableOutput
from .outputs import coerce_outputs, printable, translate_output
from .prefs import DEFAULTS as DEFAULT_PREFS
from .prefs import signed_in_account
from .toolkit import RunContext, Tool, safe_filename

ACTIVE = ("queued", "running")


@dataclass
class JobSpec:
    """Everything a runner needs to run a job (docs/PREP_PLAN.md R8; mister_plis/runners.py), JSON-serializable."""

    job_id: str
    tool_id: str
    tool_source: str  # the tool source's name ("lab", "basic"…); "" for a tool of the base
    tool_commit: str  # the source's commit: the code the job ran
    params: dict  # the raw form values (as Job.params)
    inputs: dict  # input name → [{"id", "name", "path"}]: path relative to the job folder (kept jobs), or to the
    #               data folder ("uploads/<id>/<name>", live runs, which always run here)
    prefs: dict
    record: bool
    workdir: str  # relative to the storage folder: "jobs/<id>" (or "live/<id>")
    needs: list[str] = field(default_factory=list)  # Tool.needs
    # what a runner elsewhere (a job's own process) needs to name the result files as the server would ("<date>_<who>_<keyword>_<name>")
    tool_name: str = ""
    created: float = 0.0
    user: str = ""
    keyword: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "JobSpec":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
KEEP_INPUTS_BYTES = 200 * 1024 * 1024  # input files above this (in total, per job) are described, not copied (D3)
MAX_LOADED = 200  # finished jobs whose results stay loaded in memory
# What a finished job reads from its job.json when first needed (the rest comes from its index row).
HEAVY = ("params", "files", "outputs", "saved_logs", "phrases", "inputs", "prefs", "provenance")
# Excel's limits: a table beyond them is kept as .csv instead
XLSX_ROWS, XLSX_COLS, XLSX_CELL = 1_048_576, 16_384, 32_767


def _json_safe(v: Any) -> Any:
    """NaN / ±inf are not valid JSON — turn them into null so one odd number can't break a result page."""
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


def _new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


def _valid_id(s: str) -> bool:
    return bool(s) and all(c.isalnum() or c == "-" for c in s) and len(s) < 64


def clean_text(s: Any, limit: int) -> str:
    """One line of free text from a form or cookie: single spaces, at most ``limit`` characters."""
    return " ".join(str(s or "").split())[:limit]


def name_part(s: str) -> str:
    """A person's name or a keyword as a piece of a file name: "WT vs mutant" → "WT-vs-mutant"."""
    keep = "".join(c if c.isalnum() or c in "-.()" else " " for c in s)
    return "-".join(keep.split()).strip(".-")


# --- uploads -----------------------------------------------------------------


class TooLarge(ToolError):
    """An upload larger than the lab allows (``limit``: bytes)."""

    def __init__(self, limit: int):
        super().__init__(f"The file is larger than the {limit // (1024 * 1024)} MB this lab allows.")
        self.limit = limit


class UploadStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        # (upload id) → True if the file was put back (from a job that kept a copy of it); set by JobManager
        self.restore: Callable[[str], bool] | None = None

    def save(self, filename: str, stream, limit: int | None = None) -> UploadedFile:
        """Keep an uploaded file; :class:`TooLarge` (nothing kept) when it has more than ``limit`` bytes."""
        uid = secrets.token_hex(8)
        d = self.root / uid
        d.mkdir(parents=True)
        dest = d / safe_filename(filename or "upload")
        size = 0
        with dest.open("wb") as f:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if limit is not None and size > limit:
                    break
                f.write(chunk)
        if limit is not None and size > limit:
            shutil.rmtree(d, ignore_errors=True)
            raise TooLarge(limit)
        return UploadedFile(uid, dest.name, dest, dest.stat().st_size)

    def get(self, uid: str) -> UploadedFile:
        if not _valid_id(uid):
            raise ToolError("invalid upload id")
        d = self.root / uid
        files = [p for p in d.iterdir() if p.is_file()] if d.is_dir() else []
        if not files and self.restore and self.restore(uid):  # expired, but a job kept a copy (re-running it)
            files = [p for p in d.iterdir() if p.is_file()] if d.is_dir() else []
        if not files:
            raise ToolError("uploaded file has expired — please upload it again")
        p = files[0]
        return UploadedFile(uid, p.name, p, p.stat().st_size)

    def cleanup(self, max_age_s: float) -> None:
        cutoff = time.time() - max_age_s
        for d in self.root.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)


# --- jobs ----------------------------------------------------------------------


@dataclass
class Job:
    id: str
    tool_id: str
    tool_name: str
    params: dict
    record: bool
    workdir: Path
    status: str = "queued"
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    error: str = ""
    traceback: str = ""
    outputs: list = field(default_factory=list)
    files: dict = field(default_factory=dict)  # input name -> [{id, name}] for re-filling forms
    ctx: RunContext | None = field(default=None, repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)
    saved_logs: list = field(default_factory=list, repr=False)
    saved_progress: float | None = None
    saved_message: str = ""
    prefs: dict = field(default_factory=lambda: dict(DEFAULT_PREFS))  # number format etc. of whoever ran it
    user: str = ""  # their name from Settings, if they gave one
    keyword: str = ""  # optional words for the file names, typed above the Run button
    backed_up: float | None = None  # when its files were copied to the backup folder
    parent: str = ""  # the job whose form this one was started from (a re-run with changed settings)
    title: str = ""  # optional title: "Chlorophyll concentration — WT vs mutant, day 3"; can be changed later
    phrases: dict = field(default_factory=dict, repr=False)  # {language: {english: translation}}, see i18n.recording
    inputs: dict = field(default_factory=dict, repr=False)  # input name -> [{id, name, path, size, sha256, kept}]
    provenance: dict = field(default_factory=dict, repr=False)  # {"tool": {id, name, source, source_url, commit}, "base": {…}}
    worker: str = ""  # the computer that ran it, for a job a worker ran (0.11.0–0.18.0; read, no longer written)
    account: str = ""  # the id of the account that ran it (mister_plis/accounts.py; from 0.15.0, "" before or without accounts)
    store: JobStore | None = field(default=None, repr=False, compare=False)

    # ---- a finished job loaded from its index row: the HEAVY fields are read from job.json when first needed ----
    @classmethod
    def from_row(cls, row: dict, workdir: Path, loader: Callable[[], dict | None], on_load=None) -> "Job":
        job = cls(id=row["id"], tool_id=row.get("tool_id") or "", tool_name=row.get("tool_name") or row.get("tool_id") or "",
                  params={}, record=True, workdir=workdir, status=row.get("status") or "done", created=row.get("created") or 0.0,
                  started=row.get("started"), finished=row.get("finished"), error=row.get("error") or "",
                  traceback=row.get("traceback") or "", user=row.get("user") or "", keyword=row.get("keyword") or "",
                  backed_up=row.get("backed_up"), parent=row.get("parent") or "", title=row.get("title") or "",
                  account=str(row.get("account") or ""))
        job.done.set()
        job.__dict__["_result_files"] = list(row.get("result_files") or [])
        job.__dict__["_upload_ids"] = list(row.get("upload_ids") or [])
        job.__dict__["_n_outputs"] = row.get("n_outputs") or 0
        job.__dict__["_row_files"] = row.get("files") if isinstance(row.get("files"), dict) else {}
        job.__dict__["_row_params"] = row.get("params_brief") if isinstance(row.get("params_brief"), dict) else {}
        job.__dict__["_on_load"] = on_load
        for k in HEAVY:
            job.__dict__.pop(k, None)
        job.__dict__["_loader"] = loader
        return job

    def __getattr__(self, name: str):  # only called for attributes that aren't there: an unloaded HEAVY field
        if name in HEAVY and self.__dict__.get("_loader"):
            self.load()
            return self.__dict__[name]
        raise AttributeError(name)

    @property
    def loaded(self) -> bool:
        return not self.__dict__.get("_loader")

    def load(self) -> None:
        """Read what is only in job.json (results, settings, log…), once."""
        loader = self.__dict__.get("_loader")
        if not loader:
            return
        rec = loader() or {}
        values = {
            "params": rec.get("params") or {}, "files": rec.get("files") or {}, "outputs": rec.get("outputs") or [],
            "saved_logs": rec.get("log") or [], "phrases": rec.get("phrases") if isinstance(rec.get("phrases"), dict) else {},
            "inputs": rec.get("inputs") if isinstance(rec.get("inputs"), dict) else {},
            "prefs": rec.get("prefs") if isinstance(rec.get("prefs"), dict) and rec.get("prefs") else dict(DEFAULT_PREFS),
            "provenance": {"tool": rec.get("tool") or {}, "base": rec.get("base") or {}},
        }
        for k, v in values.items():
            self.__dict__.setdefault(k, v)
        self.saved_message = rec.get("message") or self.saved_message
        self.saved_progress = rec.get("progress", self.saved_progress)
        self.worker = str(rec.get("worker") or self.worker or "")
        self.__dict__["_loader"] = None
        on_load = self.__dict__.get("_on_load")
        if on_load:
            on_load(self)

    def _unload(self, loader: Callable[[], dict | None]) -> None:
        """Forget the HEAVY fields (they are on disk); they are read again when needed."""
        if self.status in ACTIVE:
            return
        if self.loaded:  # what the index row would say, for lists and searches without loading
            self.__dict__["_result_files"] = self.result_names()
            self.__dict__["_upload_ids"] = self._kept_upload_ids()
            self.__dict__["_n_outputs"] = len(self.outputs)
        for k in HEAVY:
            self.__dict__.pop(k, None)
        self.__dict__["_loader"] = loader

    def summary_dict(self) -> dict:
        """What the job list shows and searches — from the index row, so listing reads no records."""
        if self.loaded:
            d = self.to_dict(logs=False)
            d["outputs"] = []
            return d
        return {"id": self.id, "tool_id": self.tool_id, "tool_name": self.tool_name, "user": self.user, "keyword": self.keyword,
                "title": self.title, "backed_up": self.backed_up, "parent": self.parent, "status": self.status, "created": self.created,
                "started": self.started, "finished": self.finished, "progress": None, "message": "", "error": tr(self.error),
                "traceback": "", "params": dict(self.__dict__.get("_row_params") or {}), "files": dict(self.__dict__.get("_row_files") or {}),
                "outputs": [], "n_outputs": self.__dict__.get("_n_outputs") or 0,
                "report": f"/api/jobs/{self.id}/report.pdf" if self.status == "done" else None}

    def _kept_upload_ids(self) -> list[str]:
        if not self.loaded:
            return list(self.__dict__.get("_upload_ids") or [])
        return [e.get("id") for es in self.inputs.values() if isinstance(es, list) for e in es
                if isinstance(e, dict) and e.get("kept") and e.get("id")]

    @property
    def logs(self) -> list[str]:
        return self.ctx.logs if self.ctx else self.saved_logs

    def to_dict(self, logs: bool = True, translated: bool = True) -> dict:
        """The job as JSON. ``translated``: messages and results in the language of whoever is asking (for the
        browser); ``False`` keeps them in English, as they are stored (for files on disk)."""
        self.load()
        if translated:
            with phrases(self.phrases):  # the pieces its tool translated, put back in the reader's language
                return self._dict(logs, tr, translate_output)
        d = self._dict(logs, lambda s: s, None)
        d["phrases"] = self.phrases
        d["prefs"], d["inputs"] = self.prefs, self.inputs
        d["tool"] = {"id": self.tool_id, "name": self.tool_name, "source": "", "source_url": "", "commit": "",
                     **(self.provenance.get("tool") or {})}
        d["base"] = self.provenance.get("base") or {}
        return d

    def _dict(self, logs: bool, t, translate) -> dict:
        d = {
            "id": self.id,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "user": self.user,
            "keyword": self.keyword,
            "title": self.title,
            "backed_up": self.backed_up,
            "parent": self.parent,
            "status": self.status,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "progress": self.ctx.progress_value if self.ctx else self.saved_progress,
            "message": t(self.ctx.message if self.ctx else self.saved_message),
            "error": t(self.error),
            "traceback": self.traceback,
            "params": self.params,
            "files": self.files,
            "outputs": ([translate(o) for o in self.outputs] if translate else self.outputs) if self.status not in ACTIVE else [],
            "n_outputs": len(self.outputs),
            "report": f"/api/jobs/{self.id}/report.pdf" if self.status == "done" and printable(self.outputs) else None,
        }
        if self.worker:
            d["worker"] = self.worker
        if self.account:
            d["account"] = self.account
        if logs:
            d["log"] = self.logs[-400:]
        return d

    @classmethod
    def from_meta(cls, d: dict, workdir: Path, record: bool = True) -> "Job":
        """A finished job as saved in its ``meta.json`` (also used for the copies kept in Time Machine)."""
        job = cls(
            id=d["id"], tool_id=d["tool_id"], tool_name=d.get("tool_name") or d["tool_id"], params=d.get("params") or {},
            user=d.get("user") or "", keyword=d.get("keyword") or "", backed_up=d.get("backed_up"), record=record, workdir=workdir,
            status=d.get("status") or "done", created=d.get("created") or 0.0, started=d.get("started"), finished=d.get("finished"),
            error=d.get("error") or "", traceback=d.get("traceback") or "", outputs=d.get("outputs") or [], files=d.get("files") or {},
            saved_logs=d.get("log") or [], saved_progress=d.get("progress"), saved_message=d.get("message") or "",
            parent=d.get("parent") or "", title=d.get("title") or "",
            phrases=d.get("phrases") if isinstance(d.get("phrases"), dict) else {},
            inputs=d.get("inputs") if isinstance(d.get("inputs"), dict) else {},
            prefs=d.get("prefs") if isinstance(d.get("prefs"), dict) and d.get("prefs") else dict(DEFAULT_PREFS),
            provenance={"tool": d.get("tool") or {}, "base": d.get("base") or {}}, worker=str(d.get("worker") or ""),
            account=str(d.get("account") or ""),
        )
        job.done.set()
        return job

    def result_names(self) -> list[str]:
        """Names of the result files offered for download (for searching)."""
        if not self.loaded:
            return list(self.__dict__.get("_result_files") or [])
        return result_names(self.outputs) if self.status == "done" else []

    def file_prefix(self) -> str:
        """Start of every output file name: date, who ran it, keyword — "2026-10-19_Anna-Kowalska_WT-light"."""
        day = datetime.fromtimestamp(self.created).strftime("%Y-%m-%d")
        return "_".join(p for p in (day, name_part(self.user), name_part(self.keyword)) if p)

    def file_name(self, name: str) -> str:
        """``name`` with the prefix in front (once)."""
        name, prefix = safe_filename(name), self.file_prefix()
        return name if name.startswith(prefix + "_") else f"{prefix}_{name}"

    def record_dict(self) -> dict:
        """The job's record as written to ``job.json`` (English, plain JSON)."""
        from .jobformat import to_v1

        d = self.to_dict(logs=False, translated=False)  # files on disk are English
        d["log"] = self.logs[-2000:]
        d["error"], d["message"] = self.error, (self.ctx.message if self.ctx else self.saved_message)  # in English: shown translated
        return to_v1(json.loads(json.dumps(d, default=str)))

    def save_meta(self) -> None:
        """Write the job's record (``job.json``) and its index row."""
        if not self.record:
            return
        self.workdir.mkdir(parents=True, exist_ok=True)
        d = self.record_dict()
        if self.store is not None:
            self.store.save(d, self.workdir)
        else:
            from .jobformat import to_v1

            write_json(self.workdir / JOB_FILE, to_v1(d))
            write_json(self.workdir / V0_FILE, to_v1(d))


class JobManager:
    """The jobs: the list, their records, what the pages show. A runner (mister_plis/runners.py) runs them; the
    JobManager is its RunnerEvents."""

    def __init__(self, storage_path: Path, uploads: UploadStore, max_workers: int = 8,
                 live_root: Path | None = None, legacy_root: Path | None = None, runner=None):
        """``storage_path``: the storage folder (jobs go to ``<storage>/jobs``). ``live_root``: where live calculator
        runs go (default ``<storage>/live``). ``legacy_root``: an older jobs folder to move jobs from once (when the
        storage folder was changed, or a v0 install got a storage folder of its own). ``runner``: where jobs run
        (default: :class:`~mister_plis.runners.LocalRunner`, threads in this process)."""
        from .runners import LocalRunner

        self.storage_path = storage_path
        self.root = storage_path / "jobs"
        self.live_root = live_root or storage_path / "live"
        self.legacy_root = legacy_root
        self.root.mkdir(parents=True, exist_ok=True)
        self.live_root.mkdir(parents=True, exist_ok=True)
        self.store = JobStore(self.root)
        self.uploads = uploads
        uploads.restore = self._restore_upload
        self.runner = runner if runner is not None else LocalRunner(max_workers)
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self._loaded: OrderedDict[str, None] = OrderedDict()
        self._loaded_lock = threading.Lock()
        self.migration: dict = {}  # what moving jobs from legacy_root did (Settings → Jobs & backup)

    # ---- lifecycle ----
    def load_history(self) -> None:
        self._migrate_legacy()
        rows = self.store.load()
        for jid, row in rows.items():
            if jid in self.jobs:
                continue
            job = Job.from_row(row, self.root / jid, loader=lambda jid=jid: self.store.read(jid), on_load=self._on_load)
            job.store = self.store
            if job.status in ACTIVE:
                job.status = "interrupted"
                job.error = "The server restarted while this job was running."
                job.save_meta()
            self.jobs[jid] = job

    def _on_load(self, job: Job) -> None:
        """Keep the results of the most recently used finished jobs in memory; forget the oldest beyond MAX_LOADED."""
        with self._loaded_lock:
            self._loaded[job.id] = None
            self._loaded.move_to_end(job.id)
            while len(self._loaded) > MAX_LOADED:
                old_id, _ = self._loaded.popitem(last=False)
                old = self.jobs.get(old_id)
                if old is not None and old.loaded and old.status not in ACTIVE:
                    old._unload(lambda jid=old_id: self.store.read(jid))

    def _migrate_legacy(self) -> None:
        """Copy jobs from the older jobs folder into the storage folder, once: each job is copied next to its place
        and renamed at the end (so a half copy never looks finished), then checked. When every job is there, the old
        folder is renamed ``jobs.migrated-<date>`` (never deleted). Interrupted → the next start carries on."""
        old = self.legacy_root
        if not old or not old.is_dir() or old.resolve() == self.root.resolve():
            return
        copied, kept, failed = 0, 0, []
        for d in sorted(old.iterdir()):
            if not d.is_dir() or not _valid_id(d.name) or record_file(d) is None:
                continue
            dest = self.root / d.name
            if record_file(dest) is not None:
                kept += 1
                continue
            part = self.root / f".{d.name}.partial"
            try:
                shutil.rmtree(part, ignore_errors=True)
                shutil.copytree(d, part)
                if folder_size(part) != folder_size(d) or read_job(part) is None:
                    raise OSError("the copy differs from the original")
                part.rename(dest)
                copied += 1
            except OSError as e:
                shutil.rmtree(part, ignore_errors=True)
                failed.append(f"{d.name}: {e}")
        self.migration = {"from": str(old), "copied": copied, "already_there": kept, "failed": failed, "at": time.time()}
        if failed:
            print(f"Moving jobs from {old} stopped: {len(failed)} could not be copied — they stay there; next start tries again.\n"
                  + "\n".join(failed[:20]), flush=True)
            return
        target = old.with_name(f"{old.name}.migrated-{datetime.now():%Y-%m-%d}")
        n = 2
        while target.exists():
            target = old.with_name(f"{old.name}.migrated-{datetime.now():%Y-%m-%d}-{n}")
            n += 1
        old.rename(target)
        write_json(self.root / ".migrated-from-v0.json", {**self.migration, "renamed_to": str(target)})
        print(f"Moved {copied} job(s) from {old} to {self.root}; the old folder is now {target}.", flush=True)

    def cleanup(self, job_age_s: float, upload_age_s: float, keep: Callable[[Job], bool] = lambda job: False) -> None:
        """Delete old jobs and uploads; ``keep(job)`` spares a job (e.g. its backup hasn't been made yet)."""
        now = time.time()
        gone = []
        with self.lock:
            for jid, job in list(self.jobs.items()):
                limit = job_age_s if job.record else 3600
                if job.status not in ACTIVE and now - job.created > limit and not keep(job):
                    del self.jobs[jid]
                    shutil.rmtree(job.workdir, ignore_errors=True)
                    gone.append(jid)
        self.store.remove(gone)
        for root, limit in ((self.root, job_age_s), (self.live_root, 3600)):
            for d in root.iterdir():
                if d.is_dir() and d.name not in self.jobs and now - d.stat().st_mtime > limit:
                    shutil.rmtree(d, ignore_errors=True)
        self.uploads.cleanup(upload_age_s)

    def delete(self, doomed: list[Job]) -> None:
        """Remove finished jobs from the history and delete their files (running ones are left alone)."""
        gone = []
        with self.lock:
            for job in doomed:
                if job is not None and job.status not in ACTIVE and self.jobs.get(job.id) is job:
                    del self.jobs[job.id]
                    shutil.rmtree(job.workdir, ignore_errors=True)
                    gone.append(job.id)
        self.store.remove(gone)

    def rename_user(self, old: str, new: str) -> int:
        """Every job run under ``old`` (any capitals) is now under ``new``; returns how many."""
        with self.lock:
            hit = [j for j in self.jobs.values() if j.user and j.user.casefold() == old.casefold()]
            for j in hit:
                j.user = new
                if j.status not in ACTIVE:  # a running job saves itself when it finishes
                    j.save_meta()
        return len(hit)

    # ---- queries ----
    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid) if _valid_id(jid) else None

    def recent(self, limit: int = 100, tool_id: str | None = None) -> list[Job]:
        jobs = [j for j in self.jobs.values() if j.record and (tool_id is None or j.tool_id == tool_id)]
        return sorted(jobs, key=lambda j: j.created, reverse=True)[:limit]

    def active(self) -> list[Job]:
        return [j for j in self.jobs.values() if j.status in ACTIVE]

    # ---- uploads kept with their jobs ----
    def _restore_upload(self, uid: str) -> bool:
        """An expired upload that a job kept a copy of (in its ``inputs/``) is put back, so a job can be run again."""
        for job in sorted(self.jobs.values(), key=lambda j: j.created, reverse=True):
            if not job.record or uid not in job._kept_upload_ids():
                continue
            for entries in job.inputs.values():
                for e in entries if isinstance(entries, list) else []:
                    if not (isinstance(e, dict) and e.get("id") == uid and e.get("kept")):
                        continue
                    src = (job.workdir / str(e.get("path") or "")).resolve()
                    if job.workdir.resolve() not in src.parents or not src.is_file():
                        continue
                    dest = self.uploads.root / uid
                    dest.mkdir(parents=True, exist_ok=True)
                    tmp = dest / f".{src.name}.tmp"
                    shutil.copy2(src, tmp)
                    tmp.rename(dest / safe_filename(str(e.get("name") or src.name)))
                    return True
        return False

    def _keep_inputs(self, job: Job, tool: Tool) -> None:
        """Copy the job's uploaded files into ``inputs/<input name>/`` (D3: up to KEEP_INPUTS_BYTES in total; beyond
        that only their names, sizes and checksums are kept)."""
        found = []
        for inp in tool.inputs:
            if not isinstance(inp, FileInput):
                continue
            ids = job.params.get(inp.name) or []
            for uid in ids if isinstance(ids, list) else [ids]:
                try:
                    found.append((inp.name, self.uploads.get(str(uid))))
                except ToolError:
                    pass
        keep = sum(up.size for _, up in found) <= KEEP_INPUTS_BYTES
        inputs: dict[str, list] = {}
        for name, up in found:
            h = hashlib.sha256()
            with up.path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            entry = {"id": up.id, "name": up.name, "size": up.size, "sha256": h.hexdigest(), "kept": False, "path": ""}
            if keep:
                folder = job.workdir / "inputs" / safe_filename(name)
                folder.mkdir(parents=True, exist_ok=True)
                dest, n = folder / up.name, 2
                while dest.exists():
                    dest = folder / f"{Path(up.name).stem}-{n}{Path(up.name).suffix}"
                    n += 1
                shutil.copy2(up.path, dest)
                entry.update(kept=True, path=dest.relative_to(job.workdir).as_posix())
            inputs.setdefault(name, []).append(entry)
        job.inputs = inputs

    # ---- running ----
    def submit(self, tool: Tool, raw: dict, prefs: dict | None = None, keyword: str = "", parent: str = "", title: str = "") -> Job:
        from .updater import RUNNING
        from . import __version__

        jid = _new_id()
        record = bool(tool.history)
        job = Job(
            id=jid, tool_id=tool.id, tool_name=tool.name, params=raw, record=record,
            workdir=(self.root if record else self.live_root) / jid,
            prefs=dict(prefs or DEFAULT_PREFS), user=clean_text((prefs or {}).get("name"), 60), account=signed_in_account.get(),
            keyword=clean_text(keyword, 60), parent=parent if _valid_id(parent or "") else "", title=clean_text(title, 120),
            provenance={"tool": {"id": tool.id, "name": tool.name, "source": getattr(tool, "source", ""),
                                 "source_url": getattr(tool, "source_url", ""),
                                 "commit": getattr(tool, "source_commit", "") or RUNNING.get("commit", ""),
                                 **({"needs": list(tool.needs)} if getattr(tool, "needs", ()) else {})},
                        "base": {"version": __version__, "commit": RUNNING.get("commit", "")}},
        )
        if record:
            job.store = self.store
        for inp in tool.inputs:
            if isinstance(inp, FileInput):
                ids = raw.get(inp.name) or []
                ids = ids if isinstance(ids, list) else [ids]
                job.files[inp.name] = []
                for uid in ids:
                    try:
                        job.files[inp.name].append({"id": uid, "name": self.uploads.get(uid).name})
                    except ToolError:
                        pass
        job.ctx = RunContext(jid, job.workdir, tool_id=job.tool_id)
        with self.lock:
            self.jobs[jid] = job
            if not record:  # keep memory bounded for chatty live tools
                live = [j for j in self.jobs.values() if not j.record and j.status not in ACTIVE]
                for old in sorted(live, key=lambda j: j.created)[:-200]:
                    del self.jobs[old.id]
        if record:  # the uploads it uses become files of the job (a runner elsewhere finds them with the job)
            try:
                self._keep_inputs(job, tool)
            except OSError as e:
                job.status, job.error, job.finished = "failed", f"Couldn't keep the job's input files: {e}", time.time()
                job.save_meta()
                job.done.set()
                return job
        job.save_meta()
        self.runner.start(self.spec(job, tool), tool, self)
        return job

    def spec(self, job: Job, tool: Tool) -> JobSpec:
        """The job as a runner gets it."""
        if job.record:
            inputs = {name: [{"id": e.get("id"), "name": e.get("name"), "path": e.get("path") or ""} for e in entries]
                      for name, entries in job.inputs.items()}
        else:
            inputs = {}
            for name, entries in job.files.items():
                rows = []
                for e in entries:
                    try:
                        up = self.uploads.get(str(e.get("id")))
                        rows.append({"id": up.id, "name": up.name, "path": f"uploads/{up.id}/{up.path.name}"})
                    except ToolError:
                        pass
                inputs[name] = rows
        try:
            workdir = job.workdir.relative_to(self.storage_path).as_posix()
        except ValueError:  # a live folder elsewhere (tests)
            workdir = job.workdir.as_posix()
        tool_info = job.provenance.get("tool", {})
        return JobSpec(job_id=job.id, tool_id=tool.id, tool_source=getattr(tool, "source", "") or "",
                       tool_commit=tool_info.get("commit", ""), params=dict(job.params), inputs=inputs,
                       prefs=dict(job.prefs), record=job.record, workdir=workdir, needs=list(getattr(tool, "needs", ())),
                       tool_name=job.tool_name, created=job.created, user=job.user, keyword=job.keyword)

    # ---- RunnerEvents: what the runner reports (mister_plis/runners.py) ----
    def context(self, job_id: str) -> RunContext:
        ctx = self.jobs[job_id].ctx
        assert ctx is not None
        return ctx

    def started(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job.status = "running"
        job.started = time.time()
        job.ctx.message = ""
        job.save_meta()

    def recording(self, job_id: str, book: dict) -> None:
        self.jobs[job_id].phrases = book

    def upload(self, upload_id: str):
        return self.uploads.get(upload_id)

    def render(self, job_id: str, result: Any) -> list[dict]:
        return render_outputs(self.jobs[job_id], result)

    def finished(self, job_id: str, outputs: list[dict] | None, error: str, trace: str, status: str) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        ctx = job.ctx
        if outputs is not None:
            job.outputs = outputs
        job.status = status
        if error:
            job.error = error
        if trace:
            job.traceback = trace
        job.finished = time.time()
        if ctx is not None:
            job.saved_logs = ctx.logs
            job.saved_progress = ctx.progress_value
            job.saved_message = ctx.message
        job.save_meta()
        job.done.set()

    def set_title(self, job: Job, title: str) -> None:
        """Give a job a title (or change it); kept with the job."""
        job.title = clean_text(title, 120)
        if job.status not in ACTIVE:
            job.save_meta()

    def wait(self, job: Job, timeout: float) -> None:
        job.done.wait(timeout)

    def cancel(self, job: Job) -> None:
        if job.status in ACTIVE and job.ctx:
            job.ctx.cancel()
            self.runner.cancel(job.id)
            if job.status == "queued":
                job.status = "cancelled"

    def file_path(self, job: Job, rel: str) -> Path | None:
        p = (job.workdir / rel).resolve()
        work = job.workdir.resolve()
        if work in p.parents and p.is_file():
            return p
        return None


def render_outputs(job: Job, result: Any) -> list[dict]:
    """A tool's result → the job's outputs (JSON), its files named and written into the job folder. Runs where the
    files are: in the server's process, or in a job's own process (mister_plis/jobproc.py)."""
    ctx = job.ctx
    assert ctx is not None
    used: set[Path] = set()
    renamed: dict[Path, Path] = {}
    work = job.workdir.resolve()

    def free(folder: Path, name: str) -> Path:
        """``folder/name`` with the date / name / keyword prefix, numbered if it is taken."""
        base = Path(job.file_name(name))
        p, n = folder / base, 2
        while p.exists() or p in used:
            p = folder / f"{base.stem}-{n}{base.suffix}"
            n += 1
        used.add(p)
        return p

    def save(name: str, data: bytes) -> Path:
        p = free(ctx.outdir, name)
        p.write_bytes(data)
        return p

    def place(path: Path) -> Path:
        """Give a result file its "<date>_<who>_<keyword>_<name>" name (an upload is copied in)."""
        path = Path(path).resolve()
        if path not in renamed:
            if work not in path.parents:
                dest = free(ctx.outdir.resolve(), path.name)
                shutil.copy2(path, dest)
            elif path.name != job.file_name(path.name):
                dest = free(path.parent, path.name)
                path.rename(dest)
            else:
                dest = path
            renamed[path] = dest
        return renamed[path]

    def url_for(path: Path) -> str:
        rel = place(path).relative_to(work).as_posix()
        return f"/api/jobs/{job.id}/files/{rel}"

    outputs = coerce_outputs(result)
    for o in outputs:  # rename before rendering: File / Image / Video read the file's name and size
        if isinstance(getattr(o, "src", None), (str, Path)):
            o.src = place(o.src)
    # every file offered for download is named this way; files inside zips keep their names
    rendered = []
    for i, o in enumerate(outputs):
        d = _json_safe(o.render(url_for, save))
        if job.record and isinstance(o, TableOutput):
            d["file"] = _keep_table(o, job.workdir, i)  # the whole table, whatever the page shows
            if isinstance(d.get("download"), dict):
                d["download"]["derived"] = "table"  # the same data again, as the tool offers it
        rendered.append(d)
    return rendered


def _keep_table(o: TableOutput, workdir: Path, index: int) -> str:
    """Write a result table in full to ``tables/NN_<title>.xlsx`` — or ``.csv`` when it doesn't fit Excel's limits
    (never both). Returns the path inside the job folder."""
    import pandas as pd

    from .excel import csv_safe, write_table_workbook as write_workbook

    df = o.df if isinstance(o.df, pd.DataFrame) else pd.DataFrame(o.df)
    shown = df.reset_index() if o.index else df
    title = str(o.title or "Table")
    folder = workdir / "tables"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{index + 1:02d}_{name_part(safe_filename(title))[:80] or 'Table'}"
    too_big = len(shown) + 1 > XLSX_ROWS or len(shown.columns) > XLSX_COLS or any(
        shown[c].map(lambda v: isinstance(v, str) and len(v) > XLSX_CELL).any() for c in shown.columns if shown[c].dtype == object)
    if too_big:
        path = folder / f"{stem}.csv"
        csv_safe(shown).to_csv(path, index=False)
    else:
        path = folder / f"{stem}.xlsx"
        write_workbook(path, {title[:31] or "Table": shown})
    return path.relative_to(workdir).as_posix()
