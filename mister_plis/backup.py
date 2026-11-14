"""Copies finished results to a backup folder (a NAS, an external disk…), in a form anyone can read — and that
MISTER PLIS can import back (reorg phase P3; the formats are in docs/FORMATS.md §3 (v0) and §11 (v1)).

The folder and the delay are lab-wide settings (Settings → Jobs & backup), kept in ``<data>/lab_settings.json``.
Each job becomes one folder, sorted by person::

    <backup>/Anna Kowalska/2026-10-19_Anna-Kowalska_WT-light Chlorophyll concentration (20261019-142301-a1b2c3)/
        README.md            ← everything about the job, readable anywhere
        results.xlsx         ← every table (one sheet each), Summary, Plot data
        plots/               ← each plot as an interactive page (and .png when possible)
        report.pdf           ← the result as printed from its page
        files/               ← the tool's own result files
        mister-plis/         ← for bringing the job back: job.json, input files, full tables, manifest.json

A copy is written next to its place and renamed when complete, then checked against its manifest (size and SHA-256
of every file). Only then is the job marked as backed up — and while a backup folder is set, a job is deleted from
the server only when its backup is there and still checks out.

The backup catalogue lists every job in the backup folder (both formats), finds one by its number, and imports it
back into Jobs & results or Time Machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path

from .errors import ToolError
from .jobformat import to_v1
from .jobs import Job, JobManager
from .jobstore import write_json
from .prefs import DEFAULTS, current_prefs
from .toolkit import safe_filename

AFTER_DAYS = (0, 1, 3, 7)  # choices on the Settings page; 0 = as soon as the job is done
LANGUAGES = ("en", "pl")  # the interface's languages (mister_plis/i18n.py LANGS)
# The addresses of other computers a lab could once set for the whole lab ([services], November 2026 – 0.18.0). No
# longer set (0.19.0): still read, so the inventory can take its local model's address over (modules/inventory).
SERVICES = {"model": "a local model (Ollama) other parts may use, e.g. http://192.168.1.20:11434",
            "facility": "the facility's MISTER PLIS (shared booking) — never used"}
MAX_KEEP_DAYS = 3650
DEFAULT_MAX_UPLOAD_MB = 2048
MAX_UPLOAD_MB = 1024 * 1024
SERVER_NAME = re.compile(r"^(\*|[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*)$")
FORMAT = "mister-plis-backup"
VERSION = 1
CATALOGUE_VERSION = 1  # <backup>/index.json
SUB = "mister-plis"  # the folder inside a backup that is for MISTER PLIS
MANIFEST = f"{SUB}/manifest.json"
CATALOGUE = "mister-plis-index.json"  # at the backup folder's root: the list of every backup (a cache)
BACKUP_INFO = ("job-info.json", "job-info.txt")  # v0
JOB_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
IN_FOLDER_NAME = re.compile(r"\((\d{8}-\d{6}-[0-9a-f]{6})\)$")  # "… Chlorophyll concentration (20261019-142301-a1b2c3)"
SUB_README = """This folder lets MISTER PLIS bring the job back (Jobs & results → Import from backup).
Please don't edit or move anything in it.

job.json       the job's record: who, when, which tool, its settings and results
manifest.json  every file of this backup, where it belongs in the job, its size and SHA-256 checksum
inputs/        the files the job was run on (if they were small enough to keep)
tables/        every result table in full, as the job kept it
out/           the tool's downloads that only repeat a table (the same data is in results.xlsx)
"""


def normalize_query(text: str) -> str:
    """A job number as people type it: "(20261019-142301-A1B2C3) " → "20261019-142301-a1b2c3"."""
    q = str(text or "").strip().strip("()#[] ").lower()
    return "".join(c for c in q if c.isalnum() or c == "-")[:40]


def matches(job_id: str, q: str) -> bool:
    """The whole job number, its last part ("a1b2c3"), or at least 6 characters of it."""
    return bool(q) and (job_id == q or job_id.endswith("-" + q) or (len(q) >= 6 and q in job_id))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


@dataclass
class LabSettings:
    backup_dir: str = ""  # empty = no backups
    backup_after_days: int = 1
    lab_name: str = ""  # the lab's name (sidebar, PDF reports, backups); empty = lab_name in config.toml
    language: str = ""  # the interface's language for a browser that hasn't chosen one ("" = English)
    keep_days: int = 0  # results are deleted after this many days; 0 = job_retention_days in config.toml
    keep_uploads_days: int = 0  # uploads likewise; 0 = upload_retention_days in config.toml
    services: dict = field(default_factory=dict)  # name (SERVICES) → its http(s):// address; older files lack it
    # other names this server is reached by (access.known_host); older files lack it
    server_names: list = field(default_factory=list)
    max_upload_mb: int = 0  # the largest file one may upload; 0 = DEFAULT_MAX_UPLOAD_MB; older files lack it


@dataclass
class Status:
    last_run: float | None = None
    last_error: str = ""
    copied: int = 0  # in the last run


# ---- writing one backup ---------------------------------------------------------------------------------------


def job_folder(job: Job, root: Path) -> Path:
    person = safe_filename(job.user) if job.user else "No name"
    return root / person / safe_filename(f"{job.file_prefix()} {job.tool_name} ({job.id})")


def copy_job(job: Job, root: Path, lab: str = "") -> Path:
    """Write the job's backup (v1) and check it. Returns its folder; raises OSError if it can't be written or doesn't
    check out (then nothing is marked as backed up)."""
    from .export import export_job
    from .registry import registry

    job.load()
    rec = job.record_dict()
    dest = job_folder(job, root)
    part = dest.with_name(dest.name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    try:
        sub = part / SUB
        sub.mkdir()
        # the tool's own files; downloads that only repeat a table go to mister-plis/out (the data is in results.xlsx)
        derived = set()
        for o in rec.get("outputs") or []:
            dl = o.get("download") if isinstance(o, dict) else None
            if isinstance(dl, dict) and dl.get("derived") and isinstance(dl.get("url"), str):
                derived.add(dl["url"].split(f"/api/jobs/{job.id}/files/", 1)[-1])
        out = job.workdir / "out"
        for p in sorted(out.rglob("*")) if out.is_dir() else []:
            if p.is_file():
                rel = p.relative_to(job.workdir).as_posix()
                target = sub / rel if rel in derived else part / "files" / p.relative_to(out)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
        token = current_prefs.set({**DEFAULTS, "lang": "en"})
        try:
            export_job(rec, job.workdir, part, registry.get(job.tool_id), lab)
        finally:
            current_prefs.reset(token)
        for name in ("inputs", "tables"):  # what the job keeps besides its results (a .csv table is already in tables/)
            src = job.workdir / name
            for p in sorted(src.rglob("*")) if src.is_dir() else []:
                rel = p.relative_to(job.workdir)
                if p.is_file() and not (part / rel).exists():
                    (sub / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, sub / rel)
        write_json(sub / "job.json", rec)
        (sub / "README.txt").write_text(SUB_README, encoding="utf-8")
        write_json(part / MANIFEST, _manifest(part, rec))
        old = None
        if dest.exists():  # an older backup of the same job: replaced only once the new one is complete
            old = dest.with_name(dest.name + ".old")
            shutil.rmtree(old, ignore_errors=True)
            dest.rename(old)
        part.rename(dest)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    ok, problem = verify(dest, full=True)
    if not ok:
        raise OSError(problem)
    return dest


def _job_path(rel: str, part: Path) -> str | None:
    """Where a file of the backup belongs in the job's folder (None: made for the backup, not part of the job)."""
    if rel.startswith("files/"):
        return "out/" + rel[len("files/"):]
    if rel.startswith(f"{SUB}/") and rel.split("/")[1] in ("out", "inputs", "tables"):
        return rel[len(SUB) + 1:]
    if rel.startswith("tables/") and rel.endswith(".csv"):
        return rel  # a table too big for Excel: the job's own copy
    return None


def _manifest(part: Path, rec: dict) -> dict:
    files = []
    for p in sorted(part.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(part).as_posix()
        if rel == MANIFEST:
            continue
        files.append({"backup": rel, "job": _job_path(rel, part), "size": p.stat().st_size, "sha256": _sha256(p)})
    return {"format": FORMAT, "format_version": VERSION, "job_id": rec.get("id"), "written": time.time(),
            "base": rec.get("base") or {}, "files": files}


def verify(folder: Path, full: bool = True) -> tuple[bool, str]:
    """Does a v1 backup still hold every file of its manifest, unchanged? ``full``: compare checksums too (else
    only sizes — quick enough for every cleanup)."""
    man = _read_json(folder / MANIFEST)
    if man.get("format") != FORMAT or not isinstance(man.get("files"), list):
        return False, f"{folder}: no manifest"
    for e in man["files"]:
        p = folder / str(e.get("backup") or "")
        try:
            if p.stat().st_size != e.get("size"):
                return False, f"{e.get('backup')}: changed size"
        except OSError:
            return False, f"{e.get('backup')}: missing"
        if full and _sha256(p) != e.get("sha256"):
            return False, f"{e.get('backup')}: changed contents"
    return True, ""


# ---- the catalogue of what is in the backup folder ------------------------------------------------------------


class BackupCatalogue:
    """Every job in the backup folder — v1 (with ``mister-plis/manifest.json``) and v0 (``job-info.json``, or only the
    job number in the folder name). Kept in ``<backup>/mister-plis-index.json`` so a NAS isn't walked every time."""

    def __init__(self, root_fn):
        self.root_fn = root_fn  # () → the backup folder ("" = none)
        self.lock = threading.RLock()
        self._rows: list[dict] | None = None
        self._root = ""

    def root(self) -> Path | None:
        r = str(self.root_fn() or "")
        p = Path(r) if r else None
        return p if p and p.is_dir() else None

    @staticmethod
    def describe(folder: Path) -> dict | None:
        """One backup folder as a catalogue row, or None when it isn't a job's backup."""
        m = IN_FOLDER_NAME.search(folder.name)
        man = folder / MANIFEST
        if man.is_file():
            rec = _read_json(folder / SUB / "job.json")
            if not JOB_ID.match(str(rec.get("id") or "")):
                return None
            return {"id": rec["id"], "format": 1, "folder": str(folder), "person": folder.parent.name, "tool_id": rec.get("tool_id") or "",
                    "tool_name": rec.get("tool_name") or "", "user": rec.get("user") or "", "title": rec.get("title") or "",
                    "keyword": rec.get("keyword") or "", "created": rec.get("created"), "parent": rec.get("parent") or ""}
        if not m:
            return None
        meta = _read_json(folder / "job-info.json")
        name = IN_FOLDER_NAME.sub("", folder.name).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}\S* ", name):  # "<date>_<person>_<keyword> <tool name>": the tool's name
            name = name.split(" ", 1)[1]
        name = meta.get("tool_name") or name
        return {"id": m.group(1), "format": 0, "folder": str(folder), "person": folder.parent.name, "tool_id": meta.get("tool_id") or "",
                "tool_name": name, "user": meta.get("user") or folder.parent.name, "title": meta.get("title") or "",
                "keyword": meta.get("keyword") or "", "created": meta.get("created") or folder.stat().st_mtime,
                "parent": meta.get("parent") or ""}

    def _scan(self, root: Path) -> list[dict]:
        rows = []
        try:
            for person in sorted(root.iterdir()):
                if not person.is_dir() or person.name.startswith(".") or person.name == "Time Machine":
                    continue
                for folder in sorted(person.iterdir()):
                    if folder.is_dir() and not folder.name.endswith((".partial", ".old")):
                        row = self.describe(folder)
                        if row:
                            rows.append(row)
        except OSError:  # the NAS went away while looking
            pass
        return rows

    @staticmethod
    def _listing(root: Path) -> set[str]:
        """The backup folders there now, as ``<person>/<folder>`` — names only (one listing per person: cheap on a NAS).
        Folder times can't tell what changed: copying keeps the original times."""
        names = set()
        try:
            for person in root.iterdir():
                if person.is_dir() and not person.name.startswith(".") and person.name != "Time Machine":
                    names |= {f"{person.name}/{f.name}" for f in person.iterdir()
                              if not f.name.endswith((".partial", ".old")) and f.is_dir()}
        except OSError:  # the NAS went away while looking
            pass
        return names

    def rows(self, rescan: bool = False) -> list[dict]:
        root = self.root()
        if root is None:
            return []
        with self.lock:
            if rescan:
                self._rows = self._scan(root)
            else:
                if self._rows is None or self._root != str(root):
                    cached = _read_json(root / CATALOGUE)
                    self._rows = ([{**r, "folder": str(root / r["folder"])} for r in cached["rows"]
                                   if isinstance(r, dict) and r.get("id") and r.get("folder")]
                                  if cached.get("format") == "mister-plis-backup-index" and isinstance(cached.get("rows"), list) else [])
                # the cache is kept relative to the backup folder (it may be mounted elsewhere now); bring it up to date
                # with what is there: folders gone are dropped, new ones (copied in by hand, say) are read
                there = self._listing(root)
                known = {Path(r["folder"]).relative_to(root).as_posix(): r for r in self._rows
                         if Path(r["folder"]).is_relative_to(root)}
                if set(known) != there:
                    kept = [r for rel, r in known.items() if rel in there]
                    for rel in sorted(there - set(known)):
                        row = self.describe(root / rel)
                        if row:
                            kept.append(row)
                    self._rows = kept
                    self._save(root)
                    self._root = str(root)
                    return list(self._rows)
            if rescan:
                self._save(root)
            self._root = str(root)
            return list(self._rows)

    def _save(self, root: Path) -> None:
        rows = []
        for r in self._rows or []:
            try:
                rows.append({**r, "folder": Path(r["folder"]).relative_to(root).as_posix()})
            except ValueError:
                continue
        try:
            write_json(root / CATALOGUE, {"format": "mister-plis-backup-index", "format_version": CATALOGUE_VERSION, "written": time.time(), "rows": rows})
        except OSError:
            pass

    def add(self, folder: Path) -> None:
        row = self.describe(folder)
        root = self.root()
        if row is None or root is None:
            return
        with self.lock:
            rows = [r for r in self.rows() if r.get("folder") != row["folder"]]
            self._rows = rows + [row]
            self._save(root)

    def find(self, text: str) -> list[dict]:
        """Backups matching a (partial) job number. Not in the list → the folder is looked through again (folders
        copied there by hand appear that way)."""
        q = normalize_query(text)
        if not q:
            return []
        hits = [r for r in self.rows() if matches(r["id"], q)]
        if not hits:
            hits = [r for r in self.rows(rescan=True) if matches(r["id"], q)]
        return [r for r in hits if Path(r["folder"]).is_dir()]

    def folder_of(self, folder: str) -> Path:
        """A folder inside the backup folder (refuses anything else)."""
        root = self.root()
        if root is None:
            raise ToolError("The backup folder is not available.")
        p = Path(folder).resolve()
        if root.resolve() not in p.parents or not p.is_dir():
            raise ToolError("That is not a backup in the backup folder.")
        return p

    def import_files(self, folder: Path, into: Path) -> dict:
        """Put the job's files from its backup into the folder ``into`` (out/, inputs/, tables/) and return its record
        (not written). A v1 backup is checked first; a damaged one is refused."""
        into.mkdir(parents=True, exist_ok=True)
        if (folder / MANIFEST).is_file():
            ok, problem = verify(folder, full=True)
            if not ok:
                raise ToolError(f"This backup is damaged ({problem}) — it can't be imported as it is.")
            here = folder.resolve()
            for e in _read_json(folder / MANIFEST)["files"]:
                if e.get("job"):
                    target = into / e["job"]
                    source = (folder / str(e.get("backup") or "")).resolve()
                    # both ends inside their folders: a manifest someone made by hand can't fetch a file from elsewhere
                    # on the server (its secrets, another lab's backups) into the job (docs/SECURITY_AUDIT.md L5)
                    if into.resolve() not in target.resolve().parents or here not in source.parents:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            rec = to_v1(_read_json(folder / SUB / "job.json"))
            rec["imported"] = {"from": str(folder), "at": time.time(), "format": 1}
            rec["backed_up"] = {"at": time.time(), "folder": str(folder), "format_version": 1, "verified_at": time.time()}
            return rec
        row = self.describe(folder)
        if row is None:
            raise ToolError("That folder is not a job's backup.")
        out = into / "out"
        out.mkdir(parents=True, exist_ok=True)
        for p in folder.iterdir():
            if p.name in BACKUP_INFO:
                continue
            (shutil.copytree if p.is_dir() else shutil.copy2)(p, out / p.name)
        meta = _read_json(folder / "job-info.json")
        if not meta.get("id"):  # a folder without its description: what the folder name says
            meta = {"id": row["id"], "tool_id": "", "tool_name": row["tool_name"], "user": row["person"],
                    "status": "done", "created": folder.stat().st_mtime, "outputs": []}
        rec = to_v1(meta)
        rec["status"] = rec.get("status") or "done"
        rec["imported"] = {"from": str(folder), "at": time.time(), "format": 0}
        rec["backed_up"] = {"at": time.time(), "folder": str(folder), "format_version": 0}
        return rec

    def import_job(self, folder: Path, jobs_root: Path) -> dict:
        """Bring a backed-up job back into ``jobs_root/<id>/`` (written next to its place, renamed when complete)."""
        row = self.describe(folder)
        if row is None:
            raise ToolError("That folder is not a job's backup.")
        dest = jobs_root / row["id"]
        if dest.exists():
            return {"id": row["id"], "skipped": True}
        part = jobs_root / f".{row['id']}.partial"
        shutil.rmtree(part, ignore_errors=True)
        try:
            rec = self.import_files(folder, part)
            write_json(part / "job.json", rec)
            part.rename(dest)
        except BaseException:
            shutil.rmtree(part, ignore_errors=True)
            raise
        return {"id": row["id"], "skipped": False}


# ---- the lab's backups ----------------------------------------------------------------------------------------


class Backups:
    def __init__(self, data_path: Path, jobs: JobManager, lab: str = ""):
        self.file = data_path / "lab_settings.json"
        self.data_path = data_path
        self.jobs = jobs
        self.lab = lab  # lab_name from config.toml: used when no name is set on Settings
        self.status = Status()
        self._lock = threading.Lock()
        self.catalogue = BackupCatalogue(lambda: self.settings().backup_dir)

    # ---- settings ----
    def settings(self) -> LabSettings:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return LabSettings()
        after = d.get("backup_after_days")
        lang = d.get("language") if d.get("language") in LANGUAGES else ""
        days = lambda k: d[k] if isinstance(d.get(k), int) and not isinstance(d.get(k), bool) and 0 < d[k] <= MAX_KEEP_DAYS else 0  # noqa: E731
        raw = d.get("services") if isinstance(d.get("services"), dict) else {}
        services = {k: str(raw[k]).strip() for k in SERVICES if isinstance(raw.get(k), str) and raw[k].strip()}
        names = [n for n in d.get("server_names") or [] if isinstance(n, str) and SERVER_NAME.match(n)] \
            if isinstance(d.get("server_names"), list) else []
        upload = d.get("max_upload_mb")
        upload = upload if isinstance(upload, int) and not isinstance(upload, bool) and 0 < upload <= MAX_UPLOAD_MB else 0
        return LabSettings(str(d.get("backup_dir") or ""), after if after in AFTER_DAYS else LabSettings.backup_after_days,
                           " ".join(str(d.get("lab_name") or "").split()), lang, days("keep_days"), days("keep_uploads_days"),
                           services, names, upload)

    def _write(self, new: LabSettings) -> LabSettings:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(new), indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.file)
        return new

    def update(self, backup_dir: str, after_days: int) -> LabSettings:
        """Check and store new settings; raises ToolError with a message for the page."""
        if after_days not in AFTER_DAYS:
            raise ToolError("Choose when to back up from the list.")
        folder = self.check_folder(backup_dir)
        return self._write(replace(self.settings(), backup_dir=str(folder) if folder else "", backup_after_days=after_days))

    def lab_name(self) -> str:
        """The lab's name: set on Settings → Server & updates, else lab_name in config.toml (may be empty)."""
        return self.settings().lab_name or self.lab

    def set_lab_name(self, name: str) -> LabSettings:
        name = " ".join(str(name or "").split())
        if len(name) > 60:
            raise ToolError("The lab's name can be 60 characters at most.")
        return self._write(replace(self.settings(), lab_name=name))

    def set_after_days(self, after_days: int) -> LabSettings:
        if after_days not in AFTER_DAYS:
            raise ToolError("Choose when to back up from the list.")
        return self._write(replace(self.settings(), backup_after_days=after_days))

    def set_language(self, language: str) -> LabSettings:
        """The interface's language for browsers that haven't chosen one ("" = English)."""
        if language not in ("", *LANGUAGES):
            raise ToolError("Choose a language from the list.")
        return self._write(replace(self.settings(), language=language))

    def set_keep_days(self, keep_days: int | None = None, keep_uploads_days: int | None = None) -> LabSettings:
        """How long results and uploads are kept (0 = what config.toml says, else its default)."""
        cur = self.settings()
        for v in (keep_days, keep_uploads_days):
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= MAX_KEEP_DAYS):
                raise ToolError(f"Keep results for 1 to {MAX_KEEP_DAYS} days.")
        return self._write(replace(cur, keep_days=cur.keep_days if keep_days is None else keep_days,
                                   keep_uploads_days=cur.keep_uploads_days if keep_uploads_days is None else keep_uploads_days))

    def set_max_upload_mb(self, mb) -> LabSettings:
        """The largest file one may upload, in MB (0 = the default)."""
        if isinstance(mb, bool) or not isinstance(mb, int) or not 0 <= mb <= MAX_UPLOAD_MB:
            raise ToolError("Give the largest upload in MB, as a whole number (0: the default).")
        return self._write(replace(self.settings(), max_upload_mb=mb))

    def max_upload_bytes(self) -> int:
        return (self.settings().max_upload_mb or DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024

    def check_folder(self, text: str) -> Path | None:
        text = (text or "").strip()
        if not text:
            return None
        folder = Path(text).expanduser()
        if not folder.is_absolute():
            raise ToolError("Give the full path of the folder, e.g. /Volumes/LabNAS/MISTER PLIS backup.")
        if not folder.is_dir():
            raise ToolError(f"There is no folder {folder} on the server. Create it (or connect the disk) first.")
        folder = folder.resolve()
        if folder == self.data_path.resolve() or self.data_path.resolve() in folder.parents:
            raise ToolError("The backup folder can't be inside the server's own data folder — it would be cleaned up too.")
        storage = self.jobs.root.parent.resolve()
        if folder == storage or storage in folder.parents or folder in storage.parents:
            raise ToolError("The storage folder and the backup folder must be separate — a backup must not hold the original.")
        try:
            probe = folder / f".mister-plis-write-test-{os.getpid()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            raise ToolError(f"The server can't write to {folder}: {e.strerror or e}.") from None
        return folder

    # ---- which jobs ----
    def due(self, job: Job, cfg: LabSettings, now: float | None = None) -> bool:
        """Finished, kept in history, not copied yet, and old enough."""
        if not (cfg.backup_dir and job.record and job.status == "done" and not job.backed_up):
            return False
        return (now or time.time()) - (job.finished or job.created) >= cfg.backup_after_days * 86400

    def backed_up(self, job: Job, full: bool = False) -> bool:
        """Is the job's backup there and intact? A v1 backup is checked against its manifest (sizes; ``full`` or the
        first time: checksums too); a v0 one (older) by its folder. A backup that no longer checks out is forgotten,
        so the job is copied again — unless the whole backup folder is away (a NAS not mounted): then nothing changes."""
        bk = job.backed_up
        if not bk:
            return False
        root = Path(self.settings().backup_dir or "")
        if not str(root) or str(root) == "." or not root.is_dir():
            return False
        if isinstance(bk, dict) and bk.get("format_version", 1) >= 1:
            folder = Path(str(bk.get("folder") or ""))
            ok, problem = verify(folder, full=full or not bk.get("verified_at")) if folder.is_dir() else (False, "missing")
            if ok and not bk.get("verified_at"):
                job.backed_up = {**bk, "verified_at": time.time()}
                job.save_meta()
        else:
            folder = Path(str(bk.get("folder"))) if isinstance(bk, dict) else job_folder(job, root)
            ok = folder.is_dir()
        if not ok:
            job.backed_up = None
            job.save_meta()
        return ok

    def pending(self, job: Job) -> bool:
        """Still to be copied, or its copy doesn't check out (whatever its age) — cleanup leaves these alone."""
        cfg = self.settings()
        return bool(cfg.backup_dir) and job.record and job.status == "done" and not self.backed_up(job)

    def waiting(self) -> int:
        cfg = LabSettings(self.settings().backup_dir, 0)
        return sum(self.due(j, cfg) for j in list(self.jobs.jobs.values()))

    # ---- copying ----
    def _copy(self, job: Job, root: Path) -> None:
        dest = copy_job(job, root, self.lab_name())
        job.backed_up = {"at": time.time(), "folder": str(dest), "format_version": VERSION, "verified_at": time.time()}
        job.save_meta()
        self.catalogue.add(dest)

    def run(self, everything: bool = False) -> Status:
        """Copy every job that is due (``everything``: ignore the delay). Safe to call from any thread."""
        with self._lock:
            cfg = self.settings()
            if not cfg.backup_dir:
                return self.status
            if everything:
                cfg = LabSettings(cfg.backup_dir, 0)
            status = Status(last_run=time.time())
            root = Path(cfg.backup_dir)
            if not root.is_dir():  # e.g. the NAS isn't mounted — try again next time, nothing is deleted meanwhile
                status.last_error = f"The backup folder {root} is not available."
            else:
                for job in sorted(self.jobs.jobs.values(), key=lambda j: j.created):
                    if not self.due(job, cfg):
                        continue
                    try:
                        self._copy(job, root)
                    except OSError as e:
                        status.last_error = f"Could not back up job {job.id}: {e.strerror or e}"
                        break
                    status.copied += 1
            self.status = status
            return status

    def clear(self, doomed: list[Job], backup_first: set[str]) -> dict:
        """Delete jobs from the history with their result files; those in ``backup_first`` that aren't backed up
        yet are copied to the backup folder first. A job whose copy fails is kept, so nothing is lost."""
        with self._lock:  # not while the maintenance thread is copying
            cfg = self.settings()
            root = Path(cfg.backup_dir) if cfg.backup_dir else None
            copied, kept, error, gone = 0, 0, "", []
            for job in doomed:
                if job.id in backup_first and self.pending(job):
                    if not error and not (root and root.is_dir()):
                        error = f"The backup folder {root} is not available." if root else "Backups are off."
                    if not error:
                        try:
                            self._copy(job, root)
                            copied += 1
                        except OSError as e:
                            error = f"Could not back up job {job.id}: {e.strerror or e}"
                    if not job.backed_up:
                        kept += 1
                        continue
                gone.append(job)
            self.jobs.delete(gone)
        return {"deleted": len(gone), "backed_up": copied, "kept": kept, "error": error}

    def verify_all(self) -> dict:
        """Check every backed-up job's copy file by file; one that doesn't check out is copied again later."""
        ok, bad = 0, []
        for job in list(self.jobs.jobs.values()):
            if job.record and job.status == "done" and job.backed_up:
                if self.backed_up(job, full=True):
                    ok += 1
                else:
                    bad.append(job.id)
        return {"ok": ok, "bad": bad}

    def import_jobs(self, folders: list[str]) -> dict:
        """Bring backed-up jobs back into Jobs & results."""
        done, skipped, errors = [], [], []
        for f in folders:
            try:
                r = self.catalogue.import_job(self.catalogue.folder_of(f), self.jobs.root)
                (skipped if r["skipped"] or self.jobs.get(r["id"]) else done).append(r["id"])
            except (ToolError, OSError) as e:
                errors.append(f"{Path(f).name}: {e}")
        if done:
            self.jobs.load_history()
        return {"imported": done, "skipped": skipped, "errors": errors}

    def upgrade_old(self) -> dict:
        """Rewrite the backup folder's v0 backups in the v1 form (README, workbook, plots, manifest). The old folder
        is kept beside it, renamed ``… (<job id>).v0``; nothing is deleted."""
        root = self.catalogue.root()
        if root is None:
            raise ToolError("The backup folder is not available.")
        done, errors = [], []
        work = self.data_path / "backup-upgrade"
        with self._lock:
            for row in [r for r in self.catalogue.rows(rescan=True) if r.get("format") == 0]:
                folder = Path(row["folder"])
                tmp = work / row["id"]
                shutil.rmtree(tmp, ignore_errors=True)
                try:
                    rec = self.catalogue.import_files(folder, tmp)
                    rec["backed_up"] = None
                    job = Job.from_meta(rec, tmp, record=True)
                    old = folder.with_name(folder.name + ".v0")
                    if old.exists():
                        raise OSError(f"{old.name} exists already")
                    folder.rename(old)
                    try:
                        copy_job(job, root, self.lab_name())
                    except BaseException:
                        if not folder.exists():
                            old.rename(folder)
                        raise
                    done.append(row["id"])
                except (ToolError, OSError) as e:
                    errors.append(f"{folder.name}: {e}")
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            self.catalogue.rows(rescan=True)
        shutil.rmtree(work, ignore_errors=True)
        return {"upgraded": done, "errors": errors}

    def info(self) -> dict:
        cfg = self.settings()
        old = sum(r.get("format") == 0 for r in self.catalogue.rows()) if cfg.backup_dir else 0
        return {**asdict(cfg), "lab_name_default": self.lab, "after_choices": list(AFTER_DAYS), "status": asdict(self.status),
                "waiting": self.waiting() if cfg.backup_dir else 0, "old_backups": old,
                "default_max_upload_mb": DEFAULT_MAX_UPLOAD_MB}
