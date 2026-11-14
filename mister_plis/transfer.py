"""Moving a whole server to another one (docs/BETA.md): everything the lab made and chose, in one checked folder.

**Export** copies, from this server, into ``<folder>/MISTER PLIS <lab> <date>/``::

    manifest.json   {"format": "mister-plis-transfer", "format_version": 1, "created", "by", "from": {host, data,
                     storage, version, commit}, "lab_name", "jobs", "bytes", "files": {"data/…": {size, sha256}, …}}
    data/…          the data folder: the lab's settings, people, feedback, tool settings, each module's own state
                    (its clones of other repositories too, with what wasn't sent yet)
    storage/…       the storage folder: jobs/, tool-data/, and each module's storage folder (modules/<id>)

Left out: what belongs to this machine or comes back by itself — uploads and live runs, the tool sources' clones
(fetched again at the next start), the chosen storage folder and branch (``storage.json``, ``git_branch.json``),
``config.toml``, and folders set aside earlier (``*.moved-*``, ``*.migrated-*``, ``*.before-*``…). No token or
password is ever in a server's data folder, so none is in a transfer.

It is written to ``….partial`` and renamed when every file is copied and checked (size and SHA-256).

**Import** brings a transfer into a server with **no jobs yet** (a new one): every file is checked against the
manifest first (a damaged transfer changes nothing); what is in the way (what a new server made by itself, its
lab.json…) is renamed ``<name>.before-import-<date>``, never deleted; then the files are copied and checked, and the
server counts as set up. It restarts to load them. Merging two servers is not done here; jobs from another server
can still come in through its backup folder (Jobs & results → Import from backup).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import time
from datetime import datetime
from pathlib import Path

from .errors import ToolError

FORMAT = "mister-plis-transfer"
VERSION = 1
MANIFEST = "manifest.json"
# in the data folder: what belongs to this machine, or comes back by itself
SKIP_DATA = {"uploads", "live", "tool-sources", "tool-packages", "storage.json", "git_branch.json", "jobs", "tool-data", "logs"}
SET_ASIDE = re.compile(r"\.(moved|migrated|before|replaced|partial|restoring|tmp)(-|$)|\.before-import-|^\.DS_Store$|~\$")
CHUNK = 1 << 20


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _skipped(rel: Path) -> bool:
    return any(SET_ASIDE.search(part) for part in rel.parts)


def _files(root: Path, skip_top: set[str] = frozenset(), skip_paths: set[str] = frozenset()) -> list[Path]:
    """Every file under ``root`` (relative), leaving out ``skip_top`` names at its top and ``skip_paths`` folders."""
    out = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath).relative_to(root)
        keep = []
        for d in dirnames:
            rel = here / d
            if (not here.parts and d in skip_top) or rel.as_posix() in skip_paths or _skipped(rel) or (Path(dirpath) / d).is_symlink():
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            rel = here / name
            if (not here.parts and name in skip_top) or _skipped(rel) or (Path(dirpath) / name).is_symlink():
                continue
            out.append(rel)
    return sorted(out)


def _plan(data: Path, storage: Path, module_storage: list[str]) -> list[tuple[str, Path]]:
    """(name in the transfer, source file) for everything a transfer holds."""
    data, storage = data.resolve(), storage.resolve()
    same = data == storage
    storage_parts = ["jobs", "tool-data", *module_storage]
    items: list[tuple[str, Path]] = []
    # the storage folder: jobs, tool-data and the modules' storage — nothing else of it (when it is the data folder too,
    # the rest is the data folder's, below)
    for part in storage_parts:
        root = storage / part
        for rel in _files(root):
            items.append((f"storage/{part}/{rel.as_posix()}", root / rel))
    skip_paths = set(module_storage) if same else set()
    for rel in _files(data, skip_top=SKIP_DATA, skip_paths=skip_paths):
        items.append((f"data/{rel.as_posix()}", data / rel))
    # the instance's secrets (tokens) never travel, wherever the data and storage folders are
    from .config import settings

    secrets = settings.secrets_path.resolve()
    return [(arc, src) for arc, src in items if secrets not in src.resolve().parents]


# The accounts and the activity log aren't settings: going back to a snapshot must never bring back a removed account
# or an old password, nor rewrite what happened (mister_plis/accounts.py). A whole transfer does carry them.
NOT_IN_SNAPSHOTS = {"data/accounts.json"}


def _settings_plan(data: Path, storage: Path, module_storage: list[str]) -> list[tuple[str, Path]]:
    """Only the lab's settings: the data folder's files (as a transfer has them), but of each module only the files at
    the top of its folder (its settings) — not its copies of repositories (the inventory's, with changes not sent yet),
    nor its storage. What a snapshot before an update keeps (R5)."""
    out = []
    for arc, src in _plan(data, storage, module_storage):
        parts = arc.split("/")
        if parts[0] != "data":
            continue
        if arc in NOT_IN_SNAPSHOTS or arc.startswith("data/audit.log"):
            continue
        if parts[1] == "modules" and (len(parts) > 4 or "/".join(parts[1:3]) in module_storage):
            continue
        out.append((arc, src))
    return out


def export(dest_folder: str, data: Path, storage: Path, module_storage: list[str], *, lab_name: str = "", by: str = "",
           version: str = "", commit: str = "", jobs: int = 0, settings_only: bool = False, name: str = "") -> dict:
    """Copy this server into a new folder inside ``dest_folder``; returns {"path", "files", "bytes"}. ``settings_only``:
    only the lab's settings (a snapshot before an update; ``"kind": "settings"`` in its manifest). ``name``: the new
    folder's name (default "MISTER PLIS <lab> <date>")."""
    text = (dest_folder or "").strip()
    if not text:
        raise ToolError("Give the full path of the folder to copy the server into, e.g. a USB disk or the NAS.")
    parent = Path(text).expanduser()
    if not parent.is_absolute():
        raise ToolError("Give the full path of the folder, e.g. /Volumes/USB.")
    if not parent.is_dir():
        raise ToolError(f"There is no folder {parent} on the server. Create it (or connect the disk) first.")
    parent = parent.resolve()
    for inside in (data.resolve(), storage.resolve()):
        if parent == inside or inside in parent.parents:
            raise ToolError("The copy can't go inside the server's own data or storage folder.")
    items = _settings_plan(data, storage, module_storage) if settings_only else _plan(data, storage, module_storage)
    label = re.sub(r"[^\w .()-]+", "_", lab_name).strip() or "server"
    name = name or f"MISTER PLIS {label} {datetime.now():%Y-%m-%d %H%M}"
    final = parent / name
    if final.exists():
        raise ToolError(f"{final} is there already.")
    part = parent / (name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    files, total = {}, 0
    try:
        for arc, src in items:
            dest = part / arc
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dest)
            except FileNotFoundError:  # gone meanwhile (a temporary file, say)
                continue
            digest = _sha256(src)
            if _sha256(dest) != digest:
                raise ToolError(f"The copy of {src} doesn't match the original — nothing was finished; try again.")
            size = dest.stat().st_size
            files[arc] = {"size": size, "sha256": digest}
            total += size
        manifest = {"format": FORMAT, "format_version": VERSION, "created": time.time(), "by": by,
                    "from": {"host": socket.gethostname(), "data": str(data), "storage": str(storage), "version": version,
                             "commit": commit},
                    "lab_name": lab_name, "jobs": 0 if settings_only else jobs, "bytes": total, "files": files,
                    "kind": "settings" if settings_only else "server"}
        (part / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
        part.rename(final)
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    return {"path": str(final), "files": len(files), "bytes": total}


def read(folder: str) -> tuple[Path, dict]:
    p = Path((folder or "").strip()).expanduser()
    if not str(folder or "").strip() or not p.is_absolute():
        raise ToolError("Give the full path of the copied server's folder (the one with manifest.json in it).")
    try:
        m = json.loads((p / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ToolError(f"{p} isn't a copy of a MISTER PLIS server (no readable manifest.json).") from None
    if not isinstance(m, dict) or m.get("format") != FORMAT or not isinstance(m.get("files"), dict):
        raise ToolError(f"{p} isn't a copy of a MISTER PLIS server.")
    if int(m.get("format_version") or 0) > VERSION:
        raise ToolError("This copy was made by a newer MISTER PLIS. Update this server first.")
    for arc in m["files"]:
        rel = Path(arc)
        if rel.is_absolute() or ".." in rel.parts or rel.parts[0] not in ("data", "storage") or len(rel.parts) < 2:
            raise ToolError(f"{p} has a file it shouldn't: {arc}")
    return p, m


def summary(folder: str, verify: bool = True) -> dict:
    """What a transfer holds; with ``verify``, every file checked against its manifest (ToolError lists what is wrong)."""
    p, m = read(folder)
    bad = []
    if verify:
        for arc, info in m["files"].items():
            f = p / arc
            try:
                if f.stat().st_size != info.get("size") or _sha256(f) != info.get("sha256"):
                    bad.append(arc)
            except OSError:
                bad.append(arc)
            if len(bad) >= 20:
                break
    if bad:
        raise ToolError("This copy is damaged or incomplete — nothing would be changed. Files that don't check out:\n"
                        + "\n".join(bad))
    jobs = len({a.split("/")[2] for a in m["files"] if a.startswith("storage/jobs/") and a.count("/") >= 3})
    return {"path": str(p), "lab_name": m.get("lab_name", ""), "created": m.get("created"), "by": m.get("by", ""),
            "from": m.get("from", {}), "files": len(m["files"]), "bytes": m.get("bytes", 0), "jobs": jobs, "checked": verify}


def _has_jobs(storage: Path) -> bool:
    root = storage / "jobs"
    return root.is_dir() and any((d / "job.json").exists() or (d / "meta.json").exists() for d in root.iterdir() if d.is_dir())


def _set_aside(path: Path, stamp: str) -> Path:
    target, n = path.with_name(f"{path.name}.before-import-{stamp}"), 2
    while target.exists():
        target, n = path.with_name(f"{path.name}.before-import-{stamp}-{n}"), n + 1
    path.rename(target)
    return target


def bring_in_settings(folder: str, data: Path, by: str = "") -> dict:
    """Restore the lab's settings from a snapshot (or a transfer's data/ files of settings) into this server, which may
    have jobs: only ``data/…`` files are taken, each file it replaces is set aside (``<name>.before-restore-<date>``),
    nothing else is touched. The server must restart to read them. Returns {"files", "set_aside"}."""
    info = summary(folder, verify=True)
    p, m = read(folder)
    if m.get("kind") != "settings":
        raise ToolError("This folder isn't a snapshot of settings — a whole server comes in only on a new server's setup page.")
    stamp = datetime.now().strftime("%Y-%m-%d %H%M")
    aside, restored = [], 0
    for arc, meta in m["files"].items():
        tree, *rest = Path(arc).parts
        if tree != "data":
            raise ToolError(f"A snapshot of settings holds only the data folder's files, not {arc}.")
        dest = data.joinpath(*rest)
        if dest.exists():
            if _sha256(dest) == meta["sha256"]:
                continue
            target, n = dest.with_name(f"{dest.name}.before-restore-{stamp}"), 2
            while target.exists():
                target, n = dest.with_name(f"{dest.name}.before-restore-{stamp}-{n}"), n + 1
            dest.rename(target)
            aside.append(str(target))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p / arc, dest)
        if _sha256(dest) != meta["sha256"]:
            raise ToolError(f"The copy of {arc} on this server doesn't check out.")
        restored += 1
    return {"files": restored, "set_aside": aside, "lab_name": info["lab_name"]}


def bring_in(folder: str, data: Path, storage: Path, by: str = "") -> dict:
    """Take a transfer in (see the module's docstring). Returns {"files", "bytes", "set_aside": [...], "lab_name"}."""
    if _has_jobs(storage):
        raise ToolError("This server has jobs already. A server's copy is brought only into a new one — merging two "
                        "servers isn't done here (jobs can come in through a backup folder: Jobs & results → Import from backup).")
    info = summary(folder, verify=True)
    p, m = read(folder)
    roots = {"data": data, "storage": storage}
    # what is in the way: each top-level item (and each modules/<id>) that the transfer brings
    tops = set()
    for arc in m["files"]:
        tree, *rest = Path(arc).parts
        depth = 2 if rest[0] == "modules" and len(rest) > 2 else 1
        tops.add(roots[tree].joinpath(*rest[:depth]))
    stamp = datetime.now().strftime("%Y-%m-%d")
    aside = [str(_set_aside(t, stamp)) for t in sorted(tops, key=str) if t.exists() or t.is_symlink()]
    total = 0
    for arc, meta in m["files"].items():
        tree, *rest = Path(arc).parts
        dest = roots[tree].joinpath(*rest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p / arc, dest)
        if _sha256(dest) != meta["sha256"]:
            raise ToolError(f"The copy of {arc} on this server doesn't check out. What was here is kept as "
                            + ", ".join(aside) + ".")
        total += meta["size"]
    # it counts as set up, by this move; the modules the lab chose come along
    from . import labsetup

    state = labsetup.read_state(data)
    state = {k: v for k, v in state.items() if k != "format"}
    src = m.get("from", {})
    labsetup.write_state({**state, "state": "set_up", "at": time.time(), "by": by,
                          "from": f"moved from {src.get('host') or 'another server'} ({datetime.fromtimestamp(m.get('created') or 0):%Y-%m-%d})"},
                         data)
    return {"files": len(m["files"]), "bytes": total, "set_aside": aside, "lab_name": info["lab_name"], "jobs": info["jobs"]}
