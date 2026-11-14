"""The storage folder: where jobs (``jobs/``, one folder each), what tools save (``tool-data/``) and, later, module
data live (reorg phase P2). Chosen in config.toml (``storage_dir``) or on Settings → Jobs & backup, which is kept in
``<data>/storage.json`` and wins. By default it is the data folder itself.

Changing it from the page can move what is there: everything is copied to the new folder and checked file by file
(size and SHA-256), then the server switches to it and restarts. The old folders are renamed ``*.moved-<date>``, never
deleted. Nothing is moved while a job is running.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from .config import ROOT, settings
from .errors import ToolError

MOVED = ("jobs", "tool-data")  # what a move takes along


def choice_file() -> Path:
    return settings.data_path / "storage.json"


def check_folder(text: str, backup_dir: str = "") -> Path:
    """A folder that can be the storage folder, or ToolError with what is wrong (shown on the page)."""
    text = (text or "").strip()
    if not text:
        raise ToolError("Give the full path of the storage folder.")
    folder = Path(text).expanduser()
    if not folder.is_absolute():
        raise ToolError("Give the full path of the folder, e.g. /Volumes/Lab data/MISTER PLIS.")
    if not folder.is_dir():
        raise ToolError(f"There is no folder {folder} on the server. Create it (or connect the disk) first.")
    folder = folder.resolve()
    code = ROOT.resolve()
    if folder == code or code in folder.parents:
        raise ToolError("The storage folder can't be inside the app's own code folder — updates would touch it.")
    secrets = settings.secrets_path.resolve()
    if folder == secrets or secrets in folder.parents:
        raise ToolError("The storage folder can't be inside the server's secrets folder.")
    if backup_dir:
        b = Path(backup_dir).expanduser().resolve()
        if folder == b or b in folder.parents or folder in b.parents:
            raise ToolError("The storage folder and the backup folder must be separate — a backup must not hold the original.")
    try:
        probe = folder / f".mister-plis-write-test-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise ToolError(f"The server can't write to {folder}: {e.strerror or e}.") from None
    return folder


def legacy_jobs() -> Path | None:
    """The data folder's own ``jobs/`` (where v0 kept jobs), to move into the storage folder once — unless the storage
    folder was chosen on the page *without* moving (then the person chose to leave those jobs behind)."""
    try:
        chosen = json.loads(choice_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        chosen = {}
    if isinstance(chosen, dict) and chosen.get("dir") and chosen.get("moved") is False:
        return None
    return settings.data_path / "jobs"


def info(jobs_count: int) -> dict:
    """What the Storage panel shows."""
    path = settings.storage_path
    try:
        disk = shutil.disk_usage(path)
        free, total = disk.free, disk.total
    except OSError:
        free = total = None
    try:
        chosen = json.loads(choice_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        chosen = {}
    return {"path": str(path), "is_data_dir": path.resolve() == settings.data_path.resolve(), "config": settings.storage_dir,
            "chosen": chosen if isinstance(chosen, dict) else {}, "jobs": jobs_count, "disk_free": free, "disk_total": total,
            "network": _looks_like_network(path)}


def _looks_like_network(path: Path) -> bool:
    """A NAS or another computer's share (slow, and it can go away): better for backups than for storage."""
    try:
        import subprocess

        out = subprocess.run(["df", "-P", str(path)], capture_output=True, text=True, timeout=3, encoding="utf-8", errors="replace").stdout.splitlines()
        fs = out[1].split()[0] if len(out) > 1 else ""
        return fs.startswith("//") or ":" in fs or fs.startswith("smb") or fs.startswith("afp")
    except Exception:
        return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_lock(rel: str) -> bool:
    """A git lock file (``index.lock``, ``objects/maintenance.lock``…): git makes and removes these while it works,
    including in the background after a commit (auto-maintenance), so one can vanish mid-copy. A copy never takes
    them: a stale lock in the copy would block git there."""
    parts = rel.replace("\\", "/").split("/")
    return parts[-1].endswith(".lock") and ".git" in parts[:-1]


def _skip_git_locks(folder: str, names: list[str]) -> set[str]:
    """``shutil.copytree``'s ``ignore``: leave git's lock files behind (``_git_lock``)."""
    return {n for n in names if _git_lock(f"{Path(folder).as_posix()}/{n}")}


def _files(root: Path) -> dict[str, Path]:
    return {rel: p for p in root.rglob("*") if p.is_file() and not _git_lock(rel := p.relative_to(root).as_posix())}


def copy_verified(src: Path, dest: Path) -> int:
    """Copy the folder ``src`` to ``dest`` (which must not exist) through ``dest.partial``, check every file (size and
    SHA-256), then rename. Returns the number of files. Raises ToolError if the copy differs."""
    part = dest.with_name(dest.name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    try:
        shutil.copytree(src, part, ignore=_skip_git_locks)
        a, b = _files(src), _files(part)
        if set(a) != set(b):
            raise ToolError(f"The copy of {src} is missing files: {sorted(set(a) - set(b))[:5]}")
        for rel, p in a.items():
            q = b[rel]
            if p.stat().st_size != q.stat().st_size or _sha256(p) != _sha256(q):
                raise ToolError(f"The copy of {rel} differs from the original.")
        part.rename(dest)
        return len(a)
    except OSError as e:
        shutil.rmtree(part, ignore_errors=True)
        raise ToolError(f"Could not copy {src} to {dest}: {e.strerror or e}") from None
    except ToolError:
        shutil.rmtree(part, ignore_errors=True)
        raise


def choose(text: str, move: bool, busy: bool, backup_dir: str = "", by: str = "", extra: tuple = ()) -> dict:
    """Make ``text`` the storage folder. ``move``: copy ``jobs/``, ``tool-data/`` and ``extra`` (the modules' storage
    folders, e.g. ``modules/<id>``, relative to the storage folder) there first (checked), and rename the old ones
    ``*.moved-<date>``. The caller restarts the server afterwards."""
    if busy:
        raise ToolError("Jobs are running — wait until they finish, then change the storage folder.")
    new = check_folder(text, backup_dir)
    old = settings.storage_path.resolve()
    steps = []
    if new == old:
        raise ToolError("That is the storage folder already.")
    moved = [*MOVED, *[str(x) for x in extra if x and ".." not in Path(str(x)).parts and not Path(str(x)).is_absolute()]]
    if move:
        clash = [name for name in moved if (old / name).is_dir() and (new / name).exists()]
        if clash:
            raise ToolError(f"{new} already has {', '.join(clash)} — choose an empty folder to move into, or use it without moving.")
        for name in moved:
            if (old / name).is_dir():
                (new / name).parent.mkdir(parents=True, exist_ok=True)
                n = copy_verified(old / name, new / name)
                steps.append({"name": f"copied {name} ({n} files) and checked them", "ok": True, "output": ""})
    tmp = choice_file().with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps({"dir": str(new), "chosen_at": time.time(), "by": by, "previous": str(old), "moved": bool(move)},
                              ensure_ascii=False), encoding="utf-8")
    tmp.replace(choice_file())
    steps.append({"name": f"the storage folder is now {new}", "ok": True, "output": ""})
    if move:
        stamp = datetime.now().strftime("%Y-%m-%d")
        for name in moved:
            src = old / name
            if src.is_dir():
                target, n = src.with_name(f"{src.name}.moved-{stamp}"), 2
                while target.exists():
                    target, n = src.with_name(f"{src.name}.moved-{stamp}-{n}"), n + 1
                src.rename(target)
                steps.append({"name": f"the old {name} folder is kept as {target}", "ok": True, "output": ""})
    return {"ok": True, "steps": steps, "path": str(new)}


def move_folder_once(old: Path, new: Path, what: str = "") -> bool:
    """A module's folder moved (reorg P4–P6): copy ``old`` to ``new`` once (next to it, renamed when complete),
    check the copy (the same files; a git repository's history intact), then rename ``old`` to
    ``<name>.migrated-<date>`` — never deleted. Returns True when it moved; raises OSError when the copy doesn't
    check out (then nothing changed)."""
    import subprocess

    if new.exists() or not old.is_dir() or not any(old.iterdir()):
        return False
    part = new.with_name(new.name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    part.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(old, part, symlinks=True, ignore=_skip_git_locks)
    files = lambda root: sorted(_files(root))  # noqa: E731
    if files(old) != files(part):
        shutil.rmtree(part, ignore_errors=True)
        raise OSError(f"the copy of {old} differs from the original — {what or 'it'} stays there for now")
    for repo in sorted({p.parent for p in part.rglob(".git")} if (part / ".git").exists() or any(part.rglob(".git")) else []):
        r = subprocess.run(["git", "fsck", "--no-progress"], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            shutil.rmtree(part, ignore_errors=True)
            raise OSError(f"the copied history in {repo.name} doesn't check out: {r.stdout}{r.stderr}")
    part.rename(new)
    target, n = old.with_name(f"{old.name}.migrated-{datetime.now():%Y-%m-%d}"), 2
    while target.exists():
        target, n = old.with_name(f"{old.name}.migrated-{datetime.now():%Y-%m-%d}-{n}"), n + 1
    old.rename(target)
    print(f"{what or old.name} moved from {old} to {new}; the old folder is kept as {target}.", flush=True)
    return True

