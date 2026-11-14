"""Time Machine: results worth keeping for good — copied out of Jobs & results, organised in projects, with versions,
tasks and a history of every change (a local git repository). See MODULE.md.

A module of MISTER PLIS (mister_plis/modules.py): the base doesn't know it by name.
"""

from __future__ import annotations

import time
from pathlib import Path

from mister_plis.modules import Hooks, Module, NavItem
from mister_plis.storage import move_folder_once

HERE = Path(__file__).resolve().parent


def _move_old_folder(old: Path, new: Path) -> None:
    """Before P4 Time Machine lived in ``<data>/timemachine``: moved once (mister_plis.storage.move_folder_once)."""
    move_folder_once(old, new, "Time Machine")


def setup(ctx):
    from .service import TimeMachine

    root = ctx.storage
    try:
        _move_old_folder(ctx.services.data_path / "timemachine", root)
    except OSError as e:  # keep working from the old place rather than losing anything
        print(f"Time Machine: {e}", flush=True)
        root = ctx.services.data_path / "timemachine"
    tm = TimeMachine(ctx.services.data_path, ctx.jobs, lambda: ctx.backups.settings().backup_dir, ctx.backups.catalogue, root=root)
    tm.load()
    from .backup import TimeMachineBackup

    tm.backup = TimeMachineBackup(tm, ctx)
    return tm


def register(app, ctx, tm) -> None:
    from . import web

    web.register(app, ctx, tm)


def _job_flags(job, full: bool) -> dict:
    tm = _tm()
    if tm is None:
        return {}
    kept = tm.has(job.id)
    flags = {"in_tm": kept}
    if full:
        flags["tm_root"] = "" if kept else tm.root_for_job(job)
    return flags


def _people() -> list:
    tm = _tm()
    if tm is None:
        return []
    out = [(e.get("added_by", ""), e.get("added") or 0, "kept") for e, _ in tm.all()]
    out += [(n, 0, None) for n in tm.people()]  # names only (a task's assignee, say): offered when choosing whom a task is for
    return out


def _rename_person(old: str, new: str, by: str) -> dict:
    tm = _tm()
    return {"kept": tm.rename_person(old, new, by=by)} if tm else {}


def _tm():
    from mister_plis.app import modules

    return modules.get("timemachine")


def _backup_loop(tm) -> None:  # pragma: no cover - a background thread
    while True:
        time.sleep(600)
        try:
            tm.backup.run()
        except Exception as e:
            print(f"Time Machine backup failed: {e}", flush=True)


module = Module(
    id="timemachine",
    name="Time Machine",
    setup_intro="Results worth keeping: projects, versions and tasks, with their history and a backup of their own.",
    setup=setup,
    register=register,
    nav=[NavItem(label="Time Machine", href="/timemachine", icon_template="partials/galaxy.html", order=20,
                 title="Results worth keeping — the basis of a study")],
    threads=[_backup_loop],
    templates=HERE / "templates",
    static=HERE / "static",
    scripts={"*": ["tm-button.js"], "settings": ["tm-backup.js"]},
    styles=["timemachine.css"],
    panels={"jobs_filters": ["panels/jobs_filter.html"], "jobs_lede": ["panels/jobs_lede.html"],
            "settings:jobs": ["panels/backup.html"],
            # a line in each folder of the tab's overview: where it keeps its results, and where they are copied
            "settings:jobs-storage-map": ["panels/map_storage.html"], "settings:jobs-backup-map": ["panels/map_backup.html"]},  # its copy in the backup folder, on Settings → Jobs & backup
    hooks=Hooks(job_flags=_job_flags, people=_people, rename_person=_rename_person),
)
