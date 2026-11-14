"""Jobs on disk: one folder per job in ``<storage>/jobs/``, each with its record ``job.json``, and one ``index.json``
that lists them all (reorg phase P2; formats in docs/FORMATS.md).

- **The job folders are the truth.** A folder can be copied, moved, backed up or restored on its own, and a damaged
  record affects that one job only.
- **``index.json`` is a cache:** one small row per job (who, what, when, status, result file names…) for lists and
  searches without reading every record. It is checked against the folders when the server starts and rebuilt
  where it is missing, unreadable or older than a record, so deleting it loses nothing.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .jobformat import JOB_FILE, V0_FILE, read_job, record_file, to_v1

INDEX = "index.json"
INDEX_FORMAT = "mister-plis-job-index"
INDEX_VERSION = 1
ROW_FIELDS = ("id", "tool_id", "tool_name", "user", "keyword", "title", "status", "created", "started", "finished",
              "backed_up", "parent", "error", "n_outputs", "report", "account")


def _valid_id(s: str) -> bool:
    return bool(s) and all(c.isalnum() or c == "-" for c in s) and len(s) < 64


def result_names(outputs: list) -> list[str]:
    """Names of the result files offered for download (for searching)."""
    names: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            n = o.get("name")
            if isinstance(n, str) and "." in n:
                names.append(n)
            for k in ("download", "files", "items"):
                if k in o:
                    walk(o[k])
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(outputs)
    return list(dict.fromkeys(names))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    tmp.replace(path)


def make_row(rec: dict, mtime: float) -> dict:
    row = {k: rec.get(k) for k in ROW_FIELDS}
    row["tool_name"] = row["tool_name"] or row["tool_id"]
    row["n_outputs"] = row["n_outputs"] if isinstance(row["n_outputs"], int) else len(rec.get("outputs") or [])
    row["result_files"] = result_names(rec.get("outputs") or []) if rec.get("status") == "done" else []
    row["upload_ids"] = [e.get("id") for es in (rec.get("inputs") or {}).values() if isinstance(es, list)
                         for e in es if isinstance(e, dict) and e.get("kept") and e.get("id")]
    row["traceback"] = rec.get("traceback") or ""
    # what the job list shows and searches (the input file names, short settings), so listing needs no records
    row["files"] = {k: [{"id": f.get("id"), "name": f.get("name")} for f in v if isinstance(f, dict)]
                    for k, v in (rec.get("files") or {}).items() if isinstance(v, list)}
    row["params_brief"] = {k: v for k, v in (rec.get("params") or {}).items()
                           if isinstance(v, (str, int, float)) and not isinstance(v, bool) and len(str(v)) <= 80}
    row["modules"] = rec.get("modules") if isinstance(rec.get("modules"), dict) else {}  # flags added by modules (P4)
    row["mtime"] = mtime
    return row


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_file = root / INDEX
        self.lock = threading.RLock()
        self.rows: dict[str, dict] = {}
        self.problems: list[str] = []  # folders whose record couldn't be read (shown on Settings → Jobs & backup)

    # ---- the index ----
    def _read_index(self) -> dict[str, dict]:
        try:
            d = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(d, dict) or d.get("format") != INDEX_FORMAT or not isinstance(d.get("jobs"), dict):
            return {}
        return {k: v for k, v in d["jobs"].items() if isinstance(v, dict)}

    def _write_index(self) -> None:
        write_json(self.index_file, {"format": INDEX_FORMAT, "format_version": INDEX_VERSION, "written": time.time(), "jobs": self.rows})

    def load(self) -> dict[str, dict]:
        """Check the index against the folders: rows for new or changed records are made again, rows of folders
        that are gone are dropped. A folder with only a v0 ``meta.json`` gets its ``job.json`` (the v0 file stays)."""
        with self.lock:
            old = self._read_index()
            rows: dict[str, dict] = {}
            problems: list[str] = []
            changed = not self.index_file.exists()
            for d in sorted(self.root.iterdir()) if self.root.is_dir() else []:
                if not d.is_dir() or not _valid_id(d.name):
                    continue
                f = record_file(d)
                if f is None:
                    continue
                mtime = f.stat().st_mtime
                row = old.get(d.name)
                if row and row.get("mtime") == mtime and f.name == JOB_FILE:
                    rows[d.name] = row
                    continue
                rec = read_job(d)
                if rec is None or rec.get("id") != d.name:
                    problems.append(f"{d.name}: its record can't be read")
                    continue
                if f.name == V0_FILE:  # an older job: give it a v1 record next to the old one
                    write_json(d / JOB_FILE, rec)
                    mtime = (d / JOB_FILE).stat().st_mtime
                rows[d.name] = make_row(rec, mtime)
                changed = True
            if set(rows) != set(old):
                changed = True
            self.rows, self.problems = rows, problems
            if changed:
                self._write_index()
            return dict(rows)

    # ---- records ----
    def read(self, job_id: str) -> dict | None:
        if not _valid_id(job_id):
            return None
        return read_job(self.root / job_id)

    def save(self, rec: dict, folder: Path | None = None) -> None:
        """Write a job's record (``job.json``) and its index row. An older ``meta.json`` in the folder is left as it
        is: ``job.json`` wins when both are there."""
        rec = to_v1(rec)
        folder = folder or self.root / rec["id"]
        write_json(folder / JOB_FILE, rec)
        if folder.parent.resolve() != self.root.resolve():
            return
        with self.lock:
            self.rows[rec["id"]] = make_row(rec, (folder / JOB_FILE).stat().st_mtime)
            self._write_index()

    def remove(self, job_ids) -> None:
        """Drop the rows (the caller deletes the folders)."""
        with self.lock:
            hit = [i for i in job_ids if self.rows.pop(i, None) is not None]
            if hit:
                self._write_index()


def folder_size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total
