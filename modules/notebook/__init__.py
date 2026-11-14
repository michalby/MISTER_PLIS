"""The lab notebook: chosen folders of the lab's Obsidian vault (a GitHub repository), read-only — a full page and a
side panel next to every page. See MODULE.md.

A module of MISTER PLIS (mister_plis/modules.py): the base doesn't know it by name.
"""

from __future__ import annotations

import re
from pathlib import Path

from mister_plis.modules import Module, NavItem, SettingsTab, SetupField, SetupGroup, plan_rows
from mister_plis.storage import move_folder_once

HERE = Path(__file__).resolve().parent


# The built-in defaults. The repository, once chosen (Settings → Lab notebook, or a lab file's [module.notebook]), is
# kept in <data>/modules/notebook/settings.json; repo and branch in config.toml (or MISTER_PLIS_MODULE_NOTEBOOK_<KEY>)
# win over that.
DEFAULTS = {"repo": "", "branch": "main"}
# The folders a server from before the lab's setup showed without saying so (kept for it the first time; see _migrate)
OLD_FOLDERS = ["Protokoły/Metody", "Protokoły/Odczynniki"]


def _setting(ctx, key: str, stored: dict | None = None) -> str:
    """``[module.notebook] <key>`` in config.toml (or ``MISTER_PLIS_MODULE_NOTEBOOK_<KEY>``), else what is stored,
    else the default."""
    if key in ctx.settings:
        return str(ctx.settings[key])
    if stored and key in stored:
        return str(stored[key])
    return str(DEFAULTS[key])


def _migrate(nb, explicit=()) -> None:
    """A server from before the repository was stored keeps what it used: the repository its copy came from, and the
    folders it showed by default."""
    if not nb.cloned():
        return
    if "repo" not in nb.stored() and "repo" not in explicit:
        code, url = nb.git("remote", "get-url", "origin")
        if code == 0 and url.strip():
            nb._save_settings(repo=re.sub(r"//[^@/]+@", "//", url.strip()))
    if "folders" not in nb._settings():
        nb._save_settings(folders=list(OLD_FOLDERS))


def setup(ctx):
    from .service import Notebook

    root = ctx.data
    try:
        move_folder_once(ctx.services.data_path / "notes", root, "The lab notebook")
    except OSError as e:  # keep working from the old place rather than losing anything
        print(f"Lab notebook: {e}", flush=True)
        root = ctx.services.data_path / "notes"
    probe = Notebook(ctx.services.data_path, "", "main", root=root)
    _migrate(probe, ctx.settings)
    stored = probe.stored()
    nb = Notebook(ctx.services.data_path, _setting(ctx, "repo", stored), _setting(ctx, "branch", stored), root=root)
    nb.locked = sorted(k for k in ("repo", "branch") if k in ctx.settings)  # set in config.toml: not on the page
    nb.load()
    return nb


# ---- the lab's setup (the setup page, a lab file's [module.notebook]; mister_plis/labsetup.py) -----------------------

AUTO = ((0, "only by hand"), (15, "every 15 min"), (60, "every hour"), (240, "every 4 hours"))
GROUPS = [SetupGroup("", "Where the notebook is"), SetupGroup("shown", "What the lab sees")]
SETUP = [
    SetupField("repo", "Repository", "repository", "The Obsidian vault's git repository: on GitHub, or a folder on this "
               "computer with git in it. Empty: the notebook is off.", placeholder="https://github.com/your-lab/notes.git"),
    SetupField("branch", "Branch", "branch", placeholder="main"),
    SetupField("auto_sync_minutes", "Sync by itself", "choice", choices=AUTO),
    SetupField("folders", "Folders shown to the lab", "list", "The vault's folders, one per line (e.g. Protocols/Methods). "
               "Once it has synced, they can also be ticked on Settings → Lab notebook.", group="shown"),
]


def _folders(v):
    if isinstance(v, str):
        v = [x for x in v.splitlines() if x.strip()]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ValueError("should be a list of folders, e.g. [\"Protocols/Methods\"]")
    return [x.strip().strip("/") for x in v if x.strip()]


def _auto(v):
    if v not in [a for a, _ in AUTO]:
        raise ValueError("should be 0, 15, 60 or 240")
    return v


def lab_settings(ctx, nb) -> dict:
    from mister_plis.updater import _redact

    return {"repo": _redact(nb.url), "branch": nb.branch, "folders": nb.folders(), "auto_sync_minutes": nb.auto_minutes()}


def configure(ctx, nb, values: dict, apply: bool, who: str = "") -> list[dict]:
    from mister_plis import gitutil

    checks = {"repo": gitutil.check_address, "branch": gitutil.check_branch, "folders": _folders, "auto_sync_minutes": _auto}
    rows = plan_rows(values, lab_settings(ctx, nb), checks, {k for k in ("repo", "branch") if k in ctx.settings})
    if not apply:
        return rows
    new = {r["key"]: r["new"] for r in rows if r["status"] == "change"}
    steps = {("repo", "branch"): lambda: nb.set_repository(new.get("repo", nb.url), new.get("branch", nb.branch)),
             ("folders",): lambda: nb.set_folders(new["folders"]),
             ("auto_sync_minutes",): lambda: nb.set_auto(new["auto_sync_minutes"])}
    for keys, fn in steps.items():
        if not any(k in new for k in keys):
            continue
        try:
            out = fn()
            note = f"the old copy is kept as {out['kept']}" if isinstance(out, dict) and out.get("kept") else ""
            for r in rows:
                if r["key"] in keys and r["status"] == "change":
                    r.update(status="done", note=note)
        except Exception as e:  # ToolError, or a folder that couldn't be renamed
            for r in rows:
                if r["key"] in keys and r["status"] == "change":
                    r.update(status="error", note=str(e))
    return rows


def register(app, ctx, nb) -> None:
    from . import web

    web.register(app, ctx, nb)


def _sync_loop(nb) -> None:  # pragma: no cover - a background thread
    nb.auto_sync_loop()


module = Module(
    id="notebook",
    name="Lab notebook",
    setup=setup,
    register=register,
    enabled=lambda nb: nb.enabled,  # no repository set: no link, no panel
    nav=[NavItem(label="Lab notebook", href="/notes", icon="book", order=10)],
    threads=[_sync_loop],
    templates=HERE / "templates",
    static=HERE / "static",
    styles=["notebook.css"],
    scripts={"*": ["notes.js"], "settings": ["notes_admin.js"]},
    panels={"settings": ["panels/sync.html"]},
    settings_tab=SettingsTab("Lab notebook", icon="book", order=60),
    shell={"html_class": "notes-on", "head": "shell/head.html", "topbar": "shell/topbar.html", "aside": "shell/aside.html"},
    setup_fields=SETUP,
    setup_groups=GROUPS,
    setup_intro="Chosen folders of the lab's Obsidian vault, read-only: a page of its own and a panel beside every page.",
    lab_settings=lab_settings,
    configure=configure,
)
