"""Large modules (Time Machine, the inventory, the lab notebook…) plugged into the base (reorg phase P4).

A module is a folder ``modules/<id>/`` whose ``__init__.py`` defines ``module = Module(...)``. The base never imports a
module by name: it loads the ones listed in ``modules`` in config.toml (default: every folder in ``modules/``), gives
each a :class:`ModuleContext` (its folders, the base's services), and lets it add routes, sidebar links, a tab of its
own on the Settings page (and panels on the base's tabs), scripts and styles, background threads and translations. Where a module touches the base's
own pages (a button above every result, a mark in the job list, a count on People), it does so through the
:class:`Hooks` below. A module that fails to load is listed like a broken tool; the rest of the app keeps working.

See docs/MODULES.md for how to write one.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

API = 1  # the module interface's version (Module.api must match)
MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"


@dataclass
class NavItem:
    """A link in the sidebar, under "Jobs & results"."""

    label: str
    href: str
    icon: str = "grid"  # a name from mister_plis/icons.py, or…
    icon_template: str = ""  # …a template drawing the icon (e.g. the animated galaxy)
    title: str = ""  # tooltip
    match: str = ""  # the link is "active" on pages whose path starts with this (default: href)
    order: int = 50
    visible: Callable[[], bool] | None = None


@dataclass
class SettingsTab:
    """A tab of the module's own on the Settings page (``/settings#<module id>``), holding its ``panels["settings"]``."""

    label: str
    icon: str = "grid"  # a name from mister_plis/icons.py
    order: int = 50  # the base's tabs: You 10, Exports & printing 20, Tools 30, Jobs & backup 40, People 80, Server 90
    visible: Callable[[], bool] | None = None


# The Settings page's own tabs, by id. A module puts a panel on one of them with panels["settings:<id>"].
SETTINGS_TABS = ("you", "exports", "tools", "jobs", "people", "server")


@dataclass
class SetupField:
    """A question a module asks when the lab is set up (the setup page, and a lab file's ``[module.<id>]`` table)."""

    key: str  # its key in [module.<id>]
    label: str
    # "text", "repository" (an address or a folder), "branch", "choice", "bool", "number", "list" (one per line),
    # "tool" (one of the loaded tools, chosen from a list; "" = none)
    kind: str = "text"
    help: str = ""
    choices: tuple = ()  # for "choice": (value, label) pairs; for "tool", the label of "" (none)
    placeholder: str = ""
    group: str = ""  # a SetupGroup's id; "" = the module's first, unnamed group

    def spec(self) -> dict:
        return {"key": self.key, "label": self.label, "kind": self.kind, "help": self.help,
                "choices": [list(c) for c in self.choices], "placeholder": self.placeholder, "group": self.group}


@dataclass
class SetupGroup:
    """A heading over some of a module's questions on the setup page; ``folded``: shown closed (rarely changed)."""

    id: str
    title: str
    help: str = ""
    folded: bool = False

    def spec(self) -> dict:
        return {"id": self.id, "title": self.title, "help": self.help, "folded": self.folded}


@dataclass
class Hooks:
    """Where a module joins in on the base's own pages and data. Every one is optional."""

    # job → extra fields for that job in the API (e.g. {"in_tm": True}); ``full`` is False for the job list (keep it cheap)
    job_flags: Callable[[Any, bool], dict] | None = None
    # → [(name, when, what)]: people who did something in the module, for Settings → People
    people: Callable[[], list] | None = None
    # (old, new, by) → {what: count}: a person merged into another one (Settings → People)
    rename_person: Callable[[str, str, str], dict] | None = None


@dataclass
class Module:
    id: str  # also its URL prefix, its data folder's name and its [modules.<id>] table in config.toml
    name: str
    setup: Callable[["ModuleContext"], Any]  # builds the module's service object(s); returns what register gets
    register: Callable[[Any, "ModuleContext", Any], None] | None = None  # (app, ctx, service) → adds routes
    api: int = API
    nav: list = field(default_factory=list)  # [NavItem]
    threads: list = field(default_factory=list)  # [callable(service)] run as daemon threads after setup
    templates: Path | None = None  # its templates, found as "<id>/<name>.html"
    static: Path | None = None  # served at /m/<id>/static/
    scripts: dict = field(default_factory=dict)  # page kind ("*" = every page) → [file in static/]
    styles: list = field(default_factory=list)  # CSS files in static/, on every page
    # where → [template]: "settings" (the module's own Settings tab; without one, the end of Server & updates),
    # "settings:<tab>" (one of the base's tabs, SETTINGS_TABS), "jobs_filters", "jobs_lede". "system" is the old
    # name of "settings" (before the two pages became one) and is still read.
    panels: dict = field(default_factory=dict)
    settings_tab: SettingsTab | None = None
    hooks: Hooks = field(default_factory=Hooks)
    # Parts of the page shell on every page (a side panel beside the content, say): templates for "head" (before the
    # first paint), "topbar" (the right of the top bar), "aside" (after the main column), and an <html> class.
    # Left out on pages that ask for no side panels (page(..., hide_side_panels=True): full-page spaces).
    shell: dict = field(default_factory=dict)
    # service → False when the module is switched off by its own settings (e.g. no repository set): then its links,
    # scripts, styles, panels and shell parts are left out (its routes stay and say it is off) — except its own tab on
    # the Settings page and that page's scripts, where it can be switched on again
    enabled: Callable[[Any], bool] | None = None
    # The lab's setup (mister_plis/labsetup.py, docs/LAB_SETUP_PLAN.md): the questions on the setup page, the module's
    # settings as a lab file's [module.<id>] table (ctx, service) → dict, and configure(ctx, service, values, apply,
    # who) → [{"key", "old", "new", "status"?, "note"?, "restart"?}]: check the values (apply=False) or store them.
    # A status is "change", "same", "skip" (with a note why) or "error" (with the note); once applied, "done".
    setup_fields: list = field(default_factory=list)  # [SetupField]
    setup_groups: list = field(default_factory=list)  # [SetupGroup]: headings over the questions (in this order)
    setup_intro: str = ""  # one sentence on the setup page: what the module is for
    lab_settings: Callable[["ModuleContext", Any], dict] | None = None
    configure: Callable[["ModuleContext", Any, dict, bool, str], list] | None = None


@dataclass
class ModuleContext:
    """What a module may use from the base — nothing else."""

    id: str
    storage: Path  # <storage>/modules/<id>/: job-like data that must be kept (and backed up)
    data: Path  # <data>/modules/<id>/: the module's own state (settings, clones of other repositories)
    settings: dict  # the [modules.<id>] table of config.toml
    services: Any  # the base's services (mister_plis/app.py: jobs, backups, uploads, registry, page, tr, who…)
    service: Any = None  # what the module's setup returned (set after setup; routes can read it when called)

    def __getattr__(self, name: str):
        return getattr(self.services, name)


@dataclass
class Loaded:
    module: Module
    ctx: ModuleContext

    @property
    def service(self):
        return self.ctx.service


class Modules:
    def __init__(self, root: Path | None = None):
        self.root = root or MODULES_DIR  # another folder of modules: for tests
        self.loaded: dict[str, Loaded] = {}
        self.broken: list = []  # [(module id, error)] — shown like broken tools

    def available(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir()
                      if p.is_dir() and (p / "__init__.py").is_file() and not p.name.startswith(("_", ".")))

    def load(self, app, enabled, services, storage: Path, data: Path, settings_for: Callable[[str], dict], templates_env) -> None:
        """Import, set up and register every enabled module (``enabled``: ids, or None for all there are)."""
        root = str(MODULES_DIR.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        ids = self.available() if enabled is None else [i for i in enabled if i]
        for mid in ids:
            try:
                mod = self._import(mid).module
                if not isinstance(mod, Module) or mod.id != mid:
                    raise TypeError(f"modules/{mid}/__init__.py must define module = Module(id={mid!r}, …)")
                if mod.api != API:
                    raise TypeError(f"written for module API {mod.api}; this MISTER PLIS has {API}")
                ctx = ModuleContext(mid, storage / "modules" / mid, data / "modules" / mid, settings_for(mid), services)
                ctx.service = service = mod.setup(ctx)
                if mod.register:
                    mod.register(app, ctx, service)
                if mod.static:
                    from fastapi.staticfiles import StaticFiles

                    app.mount(f"/m/{mid}/static", StaticFiles(directory=mod.static), name=f"module-{mid}-static")
                self.loaded[mid] = Loaded(mod, ctx)
            except Exception:
                self.broken.append((f"modules.{mid}", traceback.format_exc(limit=8)))
                print(f"module {mid} could not be loaded:\n{self.broken[-1][1]}", file=sys.stderr)
        self._templates(templates_env)

    def _import(self, mid: str):
        if self.root == MODULES_DIR:
            return importlib.import_module(f"modules.{mid}")
        folder = self.root / mid
        spec = importlib.util.spec_from_file_location(f"_modules_{abs(hash(str(self.root)))}_{mid}", folder / "__init__.py",
                                                      submodule_search_locations=[str(folder)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    def _templates(self, env) -> None:
        """Module templates are found as "<id>/<name>.html" (and can extend the base's "base.html")."""
        from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader

        prefixed = {mid: FileSystemLoader(str(l.module.templates)) for mid, l in self.loaded.items() if l.module.templates}
        if prefixed:
            env.loader = ChoiceLoader([env.loader, PrefixLoader(prefixed)])

    def start_threads(self) -> None:
        for mid, l in self.loaded.items():
            for fn in l.module.threads:
                threading.Thread(target=fn, args=(l.service,), daemon=True, name=f"module-{mid}-{getattr(fn, '__name__', 'loop')}").start()

    def get(self, mid: str):
        """A loaded module's service object (None when the module is off)."""
        l = self.loaded.get(mid)
        return l.service if l else None

    # ---- what the base's pages ask of all modules ----
    def _on(self) -> list:
        """The loaded modules that are switched on (by their own settings)."""
        out = []
        for l in self.loaded.values():
            try:
                if l.module.enabled is None or l.module.enabled(l.service):
                    out.append(l)
            except Exception as e:  # pragma: no cover
                print(f"module {l.module.id}: enabled() failed: {e}", file=sys.stderr)
        return out

    def shell(self, hide: bool = False) -> list[dict]:
        """The shell parts of the switched-on modules ([] on pages without side panels)."""
        if hide:
            return []
        return [{"id": l.module.id, "html_class": l.module.shell.get("html_class", ""),
                 **{k: f"{l.module.id}/{l.module.shell[k]}" for k in ("head", "topbar", "aside") if l.module.shell.get(k)}}
                for l in self._on() if l.module.shell]

    def nav(self) -> list:
        items = [(l.module.id, n) for l in self._on() for n in l.module.nav if not n.visible or n.visible()]
        return [{"id": mid, "label": n.label, "href": n.href, "icon": n.icon, "icon_template": n.icon_template,
                 "title": n.title, "match": n.match or n.href} for mid, n in sorted(items, key=lambda x: x[1].order)]

    @staticmethod
    def _settings_panels(m: Module) -> list[str]:
        """A module's panels for the Settings page as a whole ("settings", and the old "system"), in that order."""
        return list(dict.fromkeys([*m.panels.get("settings", []), *m.panels.get("system", [])]))

    def _tab_visible(self, m: Module) -> bool:
        t = m.settings_tab
        return t is not None and (t.visible is None or t.visible())

    def panels(self, where: str) -> list[str]:
        out = [f"{l.module.id}/{t}" for l in self._on() for t in l.module.panels.get(where, [])]
        if where == "settings:server":  # a module without a tab of its own: its Settings panels go at the end
            out += [f"{l.module.id}/{t}" for l in self._on() if not self._tab_visible(l.module)
                    for t in self._settings_panels(l.module)]
        return out

    def settings_tabs(self) -> list[dict]:
        """The modules' own tabs on the Settings page, in order: id, label, icon, order, panels."""
        out = [{"id": l.module.id, "label": l.module.settings_tab.label, "icon": l.module.settings_tab.icon,
                "order": l.module.settings_tab.order,
                "panels": [f"{l.module.id}/{t}" for t in self._settings_panels(l.module)]}
               for l in self.loaded.values() if self._tab_visible(l.module)]  # also when off: switched on there
        return sorted(out, key=lambda t: t["order"])

    def scripts(self, page_kind: str) -> list[str]:
        def kinds(m: Module) -> list[str]:
            own = [*m.scripts.get("*", [])]
            if page_kind != "*":
                own += m.scripts.get(page_kind, [])
                if page_kind == "settings":  # the old System page's scripts now run on Settings
                    own += m.scripts.get("system", [])
            return list(dict.fromkeys(own))

        out = [f"/m/{l.module.id}/static/{s}" for l in self._on() for s in kinds(l.module)]
        if page_kind == "settings":  # a module that is off keeps its own Settings tab, and that tab's scripts
            on = {l.module.id for l in self._on()}
            out += [f"/m/{l.module.id}/static/{s}" for l in self.loaded.values() if l.module.id not in on and self._tab_visible(l.module)
                    for s in dict.fromkeys([*l.module.scripts.get("settings", []), *l.module.scripts.get("system", [])])]
        return out

    def styles(self) -> list[str]:
        return [f"/m/{l.module.id}/static/{s}" for l in self._on() for s in l.module.styles]

    # ---- the lab's setup ----
    def can_configure(self, mid: str) -> bool:
        l = self.loaded.get(mid)
        return bool(l and l.module.configure)

    def configure(self, mid: str, values: dict, apply: bool, who: str = "") -> list[dict]:
        """A lab file's [module.<id>] table: checked (apply=False) or stored. Rows get the questions' labels; keys the
        module doesn't ask about are reported."""
        l = self.loaded[mid]
        fields_ = {f.key: f for f in l.module.setup_fields}
        unknown = [k for k in values if k not in fields_]
        rows = l.module.configure(l.ctx, l.service, {k: v for k, v in values.items() if k in fields_}, apply, who) or []
        rows = [{**r, "label": r.get("label") or (fields_[r["key"]].label if r.get("key") in fields_ else r.get("key", ""))}
                for r in rows]
        return rows + [{"key": k, "label": k, "old": None, "new": values[k], "status": "error",
                        "note": "not a setting of this module"} for k in unknown]

    def storage_folders(self, storage: Path) -> list[str]:
        """The loaded modules' storage folders that hold anything, relative to ``storage`` (e.g. "modules/<id>"): what
        moves with the jobs when the storage folder changes, and what a server's transfer counts as storage."""
        out = []
        for l in self.loaded.values():
            p = l.ctx.storage
            try:
                if p.is_dir() and any(p.iterdir()) and storage.resolve() in p.resolve().parents:
                    out.append(p.resolve().relative_to(storage.resolve()).as_posix())
            except OSError:
                continue
        return out

    def lab_settings(self) -> dict:
        """Every loaded module's settings as lab file tables ({id: {...}})."""
        out = {}
        for mid, l in self.loaded.items():
            if l.module.lab_settings:
                try:
                    out[mid] = dict(l.module.lab_settings(l.ctx, l.service) or {})
                except Exception as e:  # pragma: no cover - one module must not break the export
                    print(f"module {mid}: lab_settings failed: {e}", file=sys.stderr)
        return out

    def setup_forms(self) -> list[dict]:
        """For the setup page: every module there is (loaded or not), with its questions when it is loaded."""
        out = []
        for mid in self.available():
            l = self.loaded.get(mid)
            ok = bool(l and l.module.configure)
            out.append({"id": mid, "name": l.module.name if l else mid, "loaded": bool(l), "intro": l.module.setup_intro if l else "",
                        "fields": [f.spec() for f in l.module.setup_fields] if ok else [],
                        "groups": [g.spec() for g in l.module.setup_groups] if ok else []})
        return out

    def job_flags(self, job, full: bool = True) -> dict:
        out: dict = {}
        for mid, l in self.loaded.items():
            if l.module.hooks.job_flags:
                try:
                    out.update(l.module.hooks.job_flags(job, full) or {})
                except Exception as e:  # pragma: no cover - one module must not break the job page
                    print(f"module {mid}: job_flags failed: {e}", file=sys.stderr)
        return out

    def people(self) -> list:
        return [p for l in self.loaded.values() if l.module.hooks.people for p in (l.module.hooks.people() or [])]

    def rename_person(self, old: str, new: str, by: str) -> dict:
        out: dict = {}
        for l in self.loaded.values():
            if l.module.hooks.rename_person:
                out.update(l.module.hooks.rename_person(old, new, by) or {})
        return out


def plan_rows(values: dict, current: dict, checks: dict, explicit=()) -> list[dict]:
    """For a module's ``configure``: each value of a lab file's table against what the module has now. ``checks[key](v)``
    returns the tidied value or raises ToolError / ValueError (the row is then an error, with that message). A key in
    ``explicit`` (set in config.toml on this machine) is left alone. Rows: {"key", "old", "new", "status", "note"}."""
    from .errors import ToolError

    rows = []
    for key, v in values.items():
        old = current.get(key)
        try:
            v = checks[key](v) if key in checks else v
        except (ToolError, ValueError, TypeError) as e:
            rows.append({"key": key, "old": old, "new": v, "status": "error", "note": str(e)})
            continue
        if key in explicit:
            rows.append({"key": key, "old": old, "new": v, "status": "same" if old == v else "skip",
                         "note": "set in config.toml on this machine, which wins"})
        else:
            rows.append({"key": key, "old": old, "new": v, "status": "same" if old == v else "change", "note": ""})
    return rows


def catalogues(language: str = "pl") -> list[dict]:
    """The translations every module brings (``modules/<id>/locale/<language>.py``, a dict named like the language)."""
    from .locale import tool_catalogues

    if not MODULES_DIR.is_dir():
        return []
    return tool_catalogues([p for p in sorted(MODULES_DIR.iterdir()) if p.is_dir() and not p.name.startswith(("_", "."))], language)
