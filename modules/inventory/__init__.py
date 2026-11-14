"""The inventory: the lab's reagents and consumables (two workbooks in one GitHub repository, synced cell by cell),
orders, notes from the lab, and a scheduled tidy-up by a local model. See MODULE.md.

A module of MISTER PLIS (mister_plis/modules.py): the base doesn't know it by name.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from mister_plis.modules import Module, NavItem, SettingsTab, SetupField, SetupGroup, plan_rows
from mister_plis.storage import move_folder_once

HERE = Path(__file__).resolve().parent


# The built-in defaults. Each is kept, once chosen (Settings tab, or a lab file's [module.inventory]), in
# <data>/modules/inventory/settings.json; repo, branch, calculator and ollama_url in config.toml (or
# MISTER_PLIS_MODULE_INVENTORY_<KEY>) win over that.
# calculator: the tool a reagent's "Make a solution" button opens (calculator.py); "" for none
DEFAULTS = {"repo": "", "branch": "main", "ollama_url": "http://127.0.0.1:11434", "calculator": ""}
# What a server from before the lab's setup used without saying so (kept for it the first time; see _migrate)
OLD_CALCULATOR = "molarity"


def _setting(ctx, key: str, stored: dict | None = None) -> str:
    """``[module.inventory] <key>`` in config.toml (or ``MISTER_PLIS_MODULE_INVENTORY_<KEY>``), else what is stored,
    else the default."""
    if key in ctx.settings:
        return str(ctx.settings[key])
    if stored and key in stored:
        return str(stored[key])
    return str(DEFAULTS[key])


def _migrate(inv, explicit=(), old_model: str = "") -> None:
    """A server from before these settings were stored keeps what it used: the repository its copy came from, the
    calculator it had by default, and the local model's address the lab once set for the whole lab (``[services]
    model``, until 0.19.0), which becomes the inventory's own."""
    stored = inv.stored()
    if old_model and "ollama_url" not in stored and "ollama_url" not in explicit:
        inv.save_settings(ollama_url=old_model)
    existing = (inv.repo / ".git").is_dir() or inv.settings_file.exists()
    if "repo" not in stored and "repo" not in explicit and (inv.repo / ".git").is_dir():
        code, url = inv.git("remote", "get-url", "origin")
        url = url.strip() if code == 0 else ""
        inv.save_settings(repo=re.sub(r"//[^@/]+@", "//", url))
    if "calculator" not in stored and "calculator" not in explicit and existing:
        inv.save_settings(calculator=OLD_CALCULATOR)


def setup(ctx):
    from .calculator import Calculator
    from .service import Consumables, Inventory
    from .tidy import Tidy

    root = ctx.data
    try:
        move_folder_once(ctx.services.data_path / "reagents", root, "The inventory")
    except OSError as e:  # keep working from the old place rather than losing anything
        print(f"Inventory: {e}", flush=True)
        root = ctx.services.data_path / "reagents"
    probe = Inventory(ctx.services.data_path, root=root)
    old = ctx.services_address("model") if callable(getattr(ctx, "services_address", None)) else ""
    _migrate(probe, ctx.settings, old)
    stored = probe.stored()
    inv = Inventory(ctx.services.data_path, _setting(ctx, "repo", stored), _setting(ctx, "branch", stored), root=root)
    inv.locked = sorted(k for k in ("repo", "branch") if k in ctx.settings)  # set in config.toml: not on the page
    consumables = Consumables(inv)  # a second workbook in the same repository
    tidy = Tidy(inv, _setting(ctx, "ollama_url", stored))
    calculator = Calculator(ctx.services.registry, _setting(ctx, "calculator", stored))
    return SimpleNamespace(inventory=inv, consumables=consumables, tidy=tidy, calculator=calculator)


# ---- the lab's setup (the setup page, a lab file's [module.inventory]; mister_plis/labsetup.py) ----------------------

AUTO = ((0, "only by hand"), (15, "every 15 min"), (60, "every hour"), (240, "every 4 hours"))
GROUPS = [
    SetupGroup("", "Where the inventory is kept"),
    SetupGroup("pages", "Reagent pages"),
    SetupGroup("tidy", "Tidy-up by a local model", "A scheduled check of the inventory: format and spelling, and the notes "
               "people leave, read by a model running on this computer (Ollama).", folded=True),
]
SETUP = [
    SetupField("repo", "Repository", "repository", "The inventory's git repository: on GitHub, or a folder on this computer "
               "with git in it. Empty: the inventory stays on this server only.",
               placeholder="https://github.com/your-lab/inventory.git"),
    SetupField("branch", "Branch", "branch", placeholder="main"),
    SetupField("auto_sync_minutes", "Sync automatically", "choice", choices=AUTO),
    SetupField("push", "Send the lab's changes to the repository", "bool",
               "Each change made here goes to the repository about 20 seconds later."),
    SetupField("calculator", "Solution calculator", "tool",
               "Each reagent's page gets a “Make a solution” button that opens this tool with the reagent's name, molar "
               "mass and purity filled in.", choices=(("", "none: no “Make a solution” button"),), group="pages"),
    SetupField("ollama_url", "Local model's address", "text", "Empty: the tidy-up runs its checks only.",
               placeholder="http://127.0.0.1:11434", group="tidy"),
    SetupField("tidy_model", "Model", "text", "Which of the local model's models it uses.", group="tidy"),
    SetupField("tidy_schedule", "Runs", "choice", choices=(("off", "only by hand"), ("daily", "every day"), ("weekdays", "on weekdays")),
               group="tidy"),
    SetupField("tidy_at", "At", "text", placeholder="02:30", group="tidy"),
    SetupField("tidy_apply", "What it may change by itself", "choice",
               choices=(("none", "nothing: everything waits for a person"), ("checks", "format and spelling fixes"),
                        ("all", "everything")), group="tidy"),
]


def _choice(options):
    def check(v):
        if v not in options:
            raise ValueError("should be one of " + ", ".join(map(str, options)))
        return v
    return check


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("should be true or false")
    return v


def _url_or_empty(v):
    v = str(v or "").strip()
    if v and not re.match(r"^https?://\S+$", v):
        raise ValueError("should be an address starting with http://, or empty")
    return v


def _tool_id(v):
    v = str(v or "").strip()
    if v and not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$", v):
        raise ValueError("should be a tool's id, e.g. molarity")
    return v


def _time(v):
    v = str(v or "").strip()
    if not re.match(r"^([01][0-9]|2[0-3]):[0-5][0-9]$", v):
        raise ValueError("should be a time as hh:mm, e.g. 02:30")
    return v


def lab_settings(ctx, svc) -> dict:
    from mister_plis.updater import _redact

    st, tidy = svc.inventory.settings(), svc.tidy.settings()
    return {"repo": _redact(svc.inventory.url), "branch": svc.inventory.branch, "push": st["push"],
            "auto_sync_minutes": st["auto_minutes"], "calculator": svc.calculator.tool_id, "ollama_url": svc.tidy.ollama.url,
            "tidy_schedule": tidy["schedule"], "tidy_at": tidy["at"], "tidy_model": tidy["model"], "tidy_apply": tidy["apply"]}


def configure(ctx, svc, values: dict, apply: bool, who: str = "") -> list[dict]:
    from mister_plis import gitutil

    from .tidy import Ollama

    checks = {"repo": gitutil.check_address, "branch": gitutil.check_branch, "push": _bool,
              "auto_sync_minutes": _choice([a for a, _ in AUTO]), "calculator": _tool_id, "ollama_url": _url_or_empty,
              "tidy_schedule": _choice(["off", "daily", "weekdays"]), "tidy_at": _time, "tidy_model": lambda v: str(v or "").strip(),
              "tidy_apply": _choice(["none", "checks", "all"])}
    explicit = {k for k in ("repo", "branch", "calculator", "ollama_url") if k in ctx.settings}
    rows = plan_rows(values, lab_settings(ctx, svc), checks, explicit)
    if not apply:
        return rows
    new = {r["key"]: r["new"] for r in rows if r["status"] == "change"}
    inv, tidy = svc.inventory, svc.tidy
    steps = {
        ("repo", "branch"): lambda: inv.set_repository(new.get("repo", inv.url), new.get("branch", inv.branch)),
        ("push",): lambda: inv.save_settings(push=new["push"]),
        ("auto_sync_minutes",): lambda: inv.save_settings(auto_minutes=new["auto_sync_minutes"]),
        ("calculator",): lambda: (setattr(svc.calculator, "tool_id", new["calculator"]), inv.save_settings(calculator=new["calculator"])),
        ("ollama_url",): lambda: (setattr(tidy, "ollama", Ollama(new["ollama_url"])), inv.save_settings(ollama_url=new["ollama_url"])),
        ("tidy_schedule", "tidy_at", "tidy_model", "tidy_apply"):
            lambda: tidy.save_settings(**{k[5:]: new[k] for k in ("tidy_schedule", "tidy_at", "tidy_model", "tidy_apply") if k in new}),
    }
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


def register(app, ctx, svc) -> None:
    from . import web

    web.register(app, ctx.page, svc.inventory, svc.tidy, svc.consumables, table_pdf=ctx.table_pdf, calculator=svc.calculator,
                 access=(ctx.settings_access, ctx.work_access))


def _sync_loop(svc) -> None:  # pragma: no cover - a background thread
    svc.inventory.auto_sync_loop()


def _tidy_loop(svc) -> None:  # pragma: no cover - a background thread
    svc.tidy.loop()


module = Module(
    id="inventory",
    name="Inventory",
    setup=setup,
    register=register,
    nav=[NavItem(label="Reagents", href="/reagents", icon="flask", order=30, title="Reagent inventory: where everything is, and what to order"),
         NavItem(label="Consumables", href="/consumables", icon="box", order=31,
                 title="Lab consumables: tips, membranes, papers, vials… what there is, and what to order")],
    threads=[_sync_loop, _tidy_loop],
    templates=HERE / "templates",
    static=HERE / "static",
    styles=["reagents.css"],
    scripts={"settings": ["reagents_admin.js"]},
    panels={"settings": ["panels/sync.html", "panels/columns.html"]},
    settings_tab=SettingsTab("Reagents & consumables", icon="flask", order=50),
    setup_fields=SETUP,
    setup_groups=GROUPS,
    setup_intro="The lab's reagents and consumables: two workbooks in a git repository, edited from the pages and synced cell by cell.",
    lab_settings=lab_settings,
    configure=configure,
)
