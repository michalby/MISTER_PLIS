"""The lab's setup (docs/LAB_SETUP_PLAN.md): a lab file applied once, whether this server is set up, and the way back.

A **lab file** (``labs/<name>.toml``, format 1) describes a lab: its name and language, tool sources, which modules
are on and each module's own settings, how long results are kept, the storage and backup folders, the label printer,
updates, and tools' own settings. It never holds a token or a password.

Applying it writes every value **where the Settings page keeps it** (``lab_settings.json``, ``tool_sources.json``,
``label_printer.json``, each module's own settings…); after that the pages are where things change. What isn't in the
file isn't changed. Before anything is written, :meth:`LabSetup.plan` lists each setting as old → new, so applying a
file again (to test it, or on a second computer) shows what it would do first. A setting given in config.toml (or as
a ``MISTER_PLIS_*`` variable) on this machine wins and is left alone.

A module's ``[module.<id>]`` table is handed to that module (``Module.configure``, mister_plis/modules.py), and a
tool's ``[tool.<tool id>]`` table goes through mister_plis/toolsettings.py, as if set on Settings → Tools. When the
module or the tool isn't loaded yet (turned on by this same file, say), its table waits in ``lab.json`` and is applied
when it is.

``<data>/lab.json`` (docs/FORMATS.md)::

    {"format": 1, "state": "set_up" | "skipped", "at": …, "by": "…", "from": "labs/x.toml" | "page" | "migrated",
     "modules": ["…"],                                  # only when the lab chose which modules are on
     "pending": {"module": {id: {...}}, "tool": {id: {...}}}}

No file: the server isn't set up yet, and the pages lead to the setup page (``/setup``).
"""

from __future__ import annotations

import json
import re
import time
import tomllib
from pathlib import Path
from typing import Any, Callable

from .config import HOME, ROOT, settings
from .errors import ToolError

FORMAT = 1
STATE_FILE = "lab.json"
LABS_DIR = ROOT / "labs"
MAX_FILE = 1_000_000
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

# What a server that was running before lab files existed has in its data folder (any of these: it counts as set up)
EXISTING = ("tool_sources.json", "tool-sources", "lab_settings.json", "label_printer.json", "storage.json", "people.json",
            "feedback.json", "jobs", "modules", "reagents", "notes", "auto_update.json", "git_branch.json", "tool-settings")


class LabFileError(ToolError):
    """What is wrong with a lab file (every problem, one per line)."""


# ---- reading a lab file ------------------------------------------------------------------------------------------

def _text(limit: int):
    def check(v):
        if not isinstance(v, str):
            raise ValueError("should be text in quotes")
        v = " ".join(v.split()) if limit <= 200 else v.strip()
        if len(v) > limit:
            raise ValueError(f"{limit} characters at most")
        return v
    return check


def _folder(v):
    if not isinstance(v, str):
        raise ValueError("should be a folder's path in quotes")
    v = v.strip()
    if v and not (v.startswith("/") or v.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", v)):
        raise ValueError("give the full path (it may start with ~)")
    return v


def _int(lo: int, hi: int):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"should be a whole number from {lo} to {hi}")
        return v
    return check


def _choice(*options):
    def check(v):
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if v not in options or isinstance(v, bool) and not any(isinstance(o, bool) for o in options):
            raise ValueError("should be one of " + ", ".join(json.dumps(o) for o in options))
        return v
    return check


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("should be true or false")
    return v


def _names(v) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) and SOURCE_NAME.match(x) for x in v):
        raise ValueError('should be a list of tool source names, e.g. ["basic"]')
    return sorted(set(v))


def _feed(v) -> str:
    if not isinstance(v, str) or (v.strip() and not v.strip().startswith("https://")):
        raise ValueError("should be an https:// address, or empty")
    return v.strip()


def _logo(v) -> str:
    """The labels' logo: "" (none) or the picture itself as a data: address (a file next to the lab file is read into
    one by :func:`parse`)."""
    from .labels import logo_data_url, logo_from_data_url

    if not isinstance(v, str):
        raise ValueError("should be a picture's file name, or empty for none")
    if not v.strip():
        return ""
    if not v.strip().startswith("data:"):
        raise ValueError(f"couldn't read the picture {v!r} (a file next to the lab file, or an https:// address)")
    try:
        return logo_data_url(logo_from_data_url(v))
    except ToolError as e:
        raise ValueError(str(e)) from None


# section → key → (label shown on the page, check)
BASE: dict[str, dict[str, tuple[str, Callable]]] = {
    "lab": {
        "name": ("The lab's name", _text(60)),
        "language": ("Language for new browsers", _choice("", "en", "pl")),
    },
    "jobs": {
        "keep_days": ("Keep results for (days)", _int(1, 3650)),
        "keep_uploads_days": ("Keep uploads for (days)", _int(1, 3650)),
        "max_upload_mb": ("Largest upload (MB)", _int(1, 1024 * 1024)),
        "storage_folder": ("Storage folder", _folder),
    },
    "backup": {
        "folder": ("Backup folder", _folder),
        "after_days": ("Back up after (days)", _choice(0, 1, 3, 7)),
    },
    "label_printer": {
        "address": ("Label printer's address", _text(200)),
        "tape_mm": ("Label tape (mm)", _choice(9, 12, 18, 24)),
        "hires": ("Label printer: high resolution", _bool),
        "half_cut": ("Label printer: half cut", _bool),
        "auto_cut": ("Label printer: auto cut", _bool),
        "chain": ("Label printer: chain printing", _bool),
        "logo": ("Logo on the labels", _logo),
    },
    "updates": {
        "auto": ("Update by itself", _choice("off", "night")),
        "channel": ("Release channel", _choice("beta", "stable")),
        "feed": ("Release feed", lambda v: _feed(v)),
    },
    "tools": {
        "bundled_off": ("Tool sources that come with MISTER PLIS, switched off", lambda v: _names(v)),
        "catalogue": ("Tool catalogue", lambda v: _feed(v)),
    },
}
# Settings lab files once had that this version no longer takes: an older lab file still loads, with a note
RETIRED = {
    "server": "[server] names is no longer a lab setting (0.19.0) — ignored. The server answers to its IP addresses "
              "and its own names by itself; a name only a proxy gives it goes into server_names in config.toml "
              "(or MISTER_PLIS_SERVER_NAMES).",
    "services": "[services] is no longer a lab setting (0.19.0) — ignored. Set the local model's address in the "
                "inventory's own settings (Settings → Reagents & consumables) if it uses one.",
}
SECTIONS = ("lab_file", *BASE, "tool_sources", "modules", "module", "tool")
SOURCE_KEYS = {"name", "url", "branch", "trusted"}
SOURCE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def parse(text: str, where: str = "") -> tuple[dict, list[str]]:
    """A lab file's text → (the lab, warnings). The lab has the file's shape, checked and tidied; a section or key
    the file leaves out is left out. Raises :class:`LabFileError` listing every problem. ``where``: where the file
    was read (:func:`read_source`), so the files it names (the labels' logo) are found next to it."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise LabFileError(f"This isn't a valid lab file (TOML): {e}") from None
    extra = _read_logo(raw, where)
    lab, warnings = normalize(raw)
    return lab, extra + warnings


def _read_logo(raw: dict, where: str) -> list[str]:
    """``[label_printer] logo = "<file>"`` → the picture itself (a data: address), read next to the lab file or from an
    https:// address. A picture that can't be found is left out, with a warning (the rest of the file still applies)."""
    from .labels import LOGO_MAX, check_logo, logo_data_url

    lp = raw.get("label_printer")
    ref = lp.get("logo") if isinstance(lp, dict) else None
    if not isinstance(ref, str) or not ref.strip() or ref.strip().startswith("data:"):
        return []
    ref = ref.strip()
    try:
        if ref.startswith("https://") or where.startswith("https://"):
            import urllib.parse
            import urllib.request

            url = ref if ref.startswith("https://") else urllib.parse.urljoin(
                re.sub(r"^https://github\.com/([^/]+)/([^/]+)/blob/", r"https://raw.githubusercontent.com/\1/\2/", where), ref)
            if not url.startswith("https://"):
                raise ToolError("not an https:// address")
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "MISTER PLIS"}), timeout=30) as r:
                data = r.read(LOGO_MAX + 1)
        else:
            p = Path(ref).expanduser()
            if not p.is_absolute():
                if not where or re.match(r"^[a-z]+://", where):
                    raise ToolError("the lab file was given without its folder")
                p = _local_path(where).parent / p
            data = p.read_bytes()
        lp["logo"] = logo_data_url(check_logo(data))
        return []
    except (OSError, ToolError) as e:
        del lp["logo"]
        why = e.strerror if isinstance(e, OSError) and e.strerror else str(e)
        return [f"[label_printer] logo: couldn't read the picture {ref!r} ({why}) — left out; choose it on "
                "Settings → Exports & printing."]


def _local_path(where: str) -> Path:
    """A lab file's path as :func:`read_source` finds it: relative ones in the code folder, then the instance's."""
    p = Path(where).expanduser()
    if not p.is_absolute():
        p = ROOT / p if (ROOT / p).exists() or not (HOME / p).exists() else HOME / p
    return p


def normalize(raw: dict) -> tuple[dict, list[str]]:
    """The same checks for a lab already read (from TOML, or as JSON from the setup page)."""
    problems: list[str] = []
    warnings: list[str] = []
    lab: dict[str, Any] = {}
    if not isinstance(raw, dict):
        raise LabFileError("This isn't a lab file.")
    head = raw.get("lab_file", {})
    fmt = head.get("format", FORMAT) if isinstance(head, dict) else FORMAT
    if not isinstance(fmt, int) or fmt < 1:
        problems.append("[lab_file] format: should be 1")
    elif fmt > FORMAT:
        raise LabFileError(f"This lab file is format {fmt}; this MISTER PLIS reads format {FORMAT}. Update MISTER PLIS first.")
    for section, value in raw.items():
        if section in RETIRED:
            if value:
                warnings.append(RETIRED[section])
        elif section not in SECTIONS:
            warnings.append(f"[{section}] is not a part of a lab file — ignored.")
        elif section in BASE:
            if not isinstance(value, dict):
                problems.append(f"[{section}] should be a table")
                continue
            out = {}
            for key, v in value.items():
                spec = BASE[section].get(key)
                if spec is None:
                    warnings.append(f"[{section}] {key} is not a setting — ignored.")
                    continue
                try:
                    out[key] = spec[1](v)
                except ValueError as e:
                    problems.append(f"[{section}] {key}: {e}")
            lab[section] = out
    if "tool_sources" in raw:
        items = raw["tool_sources"]
        if not isinstance(items, list):
            problems.append("[[tool_sources]] should be a list of tables")
        else:
            out, names = [], set()
            for n, s in enumerate(items, 1):
                if not isinstance(s, dict):
                    problems.append(f"tool source {n}: should be a table")
                    continue
                for k in set(s) - SOURCE_KEYS:
                    warnings.append(f"tool source {n}: {k} is not a setting — ignored.")
                url, name = str(s.get("url") or "").strip(), str(s.get("name") or "").strip()
                branch = str(s.get("branch") or "main").strip()
                if not re.match(r"^(https://|file://|git@|/|~)", url):
                    problems.append(f"tool source {n}: url should be a repository's address (https://…)")
                if not SOURCE_NAME.match(name):
                    problems.append(f"tool source {n}: name should be small letters, digits and _ (e.g. lab)")
                elif name in names:
                    problems.append(f"tool source {n}: there is another source named {name}")
                if not BRANCH.match(branch) or ".." in branch:
                    problems.append(f"tool source {n}: {branch!r} is not a branch name")
                if "trusted" in s and not isinstance(s["trusted"], bool):
                    problems.append(f"tool source {n}: trusted should be true or false")
                names.add(name)
                out.append({"name": name, "url": url, "branch": branch, "trusted": s.get("trusted") is True})
            lab["tool_sources"] = out
    if "modules" in raw:
        m = raw["modules"]
        on = m.get("on") if isinstance(m, dict) else None
        if not isinstance(m, dict) or "on" not in m:
            problems.append('[modules] on: should be "all" or a list of module names, e.g. ["one", "two"]')
        elif on == "all":
            lab["modules"] = {"on": "all"}
        elif isinstance(on, list) and all(isinstance(x, str) and ID.match(x) for x in on):
            lab["modules"] = {"on": list(dict.fromkeys(on))}
        else:
            problems.append('[modules] on: should be "all" or a list of module names')
    for section in ("module", "tool"):
        if section in raw:
            tables = raw[section]
            if not isinstance(tables, dict) or not all(isinstance(v, dict) for v in tables.values()):
                problems.append(f"[{section}.<id>] should be tables")
                continue
            bad = [k for k in tables if not ID.match(k)]
            problems += [f"[{section}.{k}]: not a name" for k in bad]
            lab[section] = {k: dict(v) for k, v in tables.items() if k not in bad}
    if problems:
        raise LabFileError("\n".join(problems))
    return lab, warnings


def read_source(where: str) -> tuple[str, str]:
    """A lab file's text from a path or an https:// address → (text, what it was). A relative path is looked for in
    the code folder (the lab files that come with it, ``labs/``), then in the instance's folder. A github.com page of
    a file is read as the raw file."""
    where = (where or "").strip()
    if not where:
        raise ToolError("Give a lab file: a path or an https:// address.")
    if where.startswith("https://"):
        import urllib.request

        url = re.sub(r"^https://github\.com/([^/]+)/([^/]+)/blob/", r"https://raw.githubusercontent.com/\1/\2/", where)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "MISTER PLIS"}), timeout=30) as r:
                data = r.read(MAX_FILE + 1)
        except OSError as e:
            raise ToolError(f"Couldn't read {where}: {e}") from None
        if len(data) > MAX_FILE:
            raise ToolError("That file is too large to be a lab file.")
        return data.decode("utf-8", "replace"), where
    if re.match(r"^[a-z]+://", where):
        raise ToolError("A lab file's address must start with https://.")
    p = _local_path(where)
    try:
        if p.stat().st_size > MAX_FILE:
            raise ToolError("That file is too large to be a lab file.")
        return p.read_text(encoding="utf-8"), where
    except OSError as e:
        raise ToolError(f"Couldn't read {where}: {e.strerror or e}") from None


def lab_files() -> list[dict]:
    """The lab files for the setup page's list: those that come with the code (``labs/*.toml``, ``"where": "code"``),
    then the instance's own (``<home>/labs/*.toml``, ``"where": "instance"``; given by their full path) when the
    instance lives apart from the code."""
    out = []
    folders = [(LABS_DIR, "code")]
    if HOME != ROOT.resolve():
        folders.append((HOME / "labs", "instance"))
    for folder, where in folders:
        for p in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
            try:
                lab, _ = parse(p.read_text(encoding="utf-8"))
                name = lab.get("lab", {}).get("name", "")
            except (OSError, ToolError):
                name = ""
            path = p.relative_to(ROOT).as_posix() if where == "code" else str(p)
            out.append({"path": path, "name": name, "where": where})
    return out


# ---- writing a lab file -------------------------------------------------------------------------------------------

def _key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    if v is None:
        return '""'
    return json.dumps(str(v), ensure_ascii=False)


def dumps(lab: dict, header: str = "") -> str:
    """A lab (as :func:`normalize` returns it) as the text of a lab file."""
    lines = [f"# {line}" if line else "#" for line in header.splitlines()]
    if lines:
        lines.append("")

    def table(name: str, d: dict) -> None:
        simple = {k: v for k, v in d.items() if not isinstance(v, dict)}
        lines.append(f"[{name}]")
        lines.extend(f"{_key(k)} = {_value(v)}" for k, v in simple.items())
        lines.append("")

    table("lab_file", {"format": FORMAT})
    for section in ("lab",):
        if section in lab:
            table(section, lab[section])
    for s in lab.get("tool_sources", []):
        lines.append("[[tool_sources]]")
        lines.extend(f"{k} = {_value(s[k])}" for k in ("name", "url", "branch", "trusted") if k in s)
        lines.append("")
    if "modules" in lab:
        table("modules", lab["modules"])
    for mid, t in lab.get("module", {}).items():
        table(f"module.{_key(mid)}", t)
    for section in ("tools", "jobs", "backup", "label_printer", "updates"):
        if section in lab:
            table(section, lab[section])
    for tid, t in lab.get("tool", {}).items():
        table(f"tool.{_key(tid)}", t)
    return "\n".join(lines).rstrip() + "\n"


# ---- whether the server is set up ----------------------------------------------------------------------------------

def state_file(data_path: Path | None = None) -> Path:
    return (data_path or settings.data_path) / STATE_FILE


def read_state(data_path: Path | None = None) -> dict:
    try:
        d = json.loads(state_file(data_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def write_state(d: dict, data_path: Path | None = None) -> dict:
    f = state_file(data_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"format": FORMAT, **d}, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)
    return read_state(data_path)


def is_new(data_path: Path | None = None) -> bool:
    return read_state(data_path).get("state") not in ("set_up", "skipped")


# Before labs chose their own label logo (November 2026), every label carried the picture that came with the code — our
# lab's, since only our lab's servers existed before lab files. Kept only for those servers (old_logo).
LEGACY_LOGO = LABS_DIR / "legacy-label-logo.png"


def old_logo(data_path: Path | None = None) -> bytes | None:
    """The logo a server printed before labs chose their own (labels.Printer.keep_old_logo): the one the lab file it
    was set up from names; for a server older than lab files, the picture that came with the code; else none."""
    source = str(read_state(data_path).get("from") or "")
    if source == "migrated":
        return LEGACY_LOGO.read_bytes() if LEGACY_LOGO.is_file() else None
    if not source or source.startswith("https://") or not source.endswith(".toml"):
        return None
    try:
        text, where = read_source(source)
        lab, _ = parse(text, where)
    except ToolError:
        return None
    logo = lab.get("label_printer", {}).get("logo")
    if not logo:
        return None
    from .labels import logo_from_data_url

    return logo_from_data_url(logo)


def migrate(data_path: Path | None = None) -> bool:
    """Called first thing at every start. A server that was running before lab files existed (no lab.json, but data)
    counts as set up (``"from": "migrated"``), so it carries on as it was; a new one is marked ``"new"`` at once, so the
    folders it makes itself never pass it off as an old one later. Every server gets its id (:func:`ensure_instance`).
    Returns True when it migrated."""
    data = data_path or settings.data_path
    migrated = False
    if not state_file(data).exists():
        if any((data / name).exists() for name in EXISTING):
            write_state({"state": "set_up", "at": time.time(), "by": "", "from": "migrated"}, data)
            migrated = True
        else:
            write_state({"state": "new"}, data)
    ensure_instance(data)
    return migrated


def ensure_instance(data_path: Path | None = None) -> dict:
    """This instance's identity — ``{"id", "created_at"}`` in lab.json, made once. It stays when the instance moves
    (a transfer carries lab.json); a lab file never holds it (a lab file sets a lab up, it isn't an instance)."""
    import uuid

    d = read_state(data_path)
    inst = d.get("instance")
    if isinstance(inst, dict) and isinstance(inst.get("id"), str) and inst["id"]:
        return inst
    inst = {"id": uuid.uuid4().hex, "created_at": time.time()}
    write_state({**{k: v for k, v in d.items() if k != "format"}, "instance": inst}, data_path)
    return inst


# ---- planning and applying -----------------------------------------------------------------------------------------

def _shown(v) -> Any:
    return "" if v is None else v


def _update_settings() -> dict:
    from . import updates

    return updates.update_settings()


def _picture(data_url: str) -> str:
    """How a plan shows a picture (the labels' logo)."""
    return "a picture" if data_url else "none"


class LabSetup:
    """Plans and applies a lab on this server, and exports its settings as a lab file. The base's services are
    passed in (mister_plis/app.py), so this never names a module."""

    def __init__(self, data_path: Path, *, backups, printer, toolsources, modules, registry, jobs_count: Callable[[], int],
                 updater, storage):
        self.data_path = data_path
        self.backups, self.printer, self.toolsources = backups, printer, toolsources
        self.modules, self.registry, self.jobs_count = modules, registry, jobs_count
        self.updater, self.storage = updater, storage

    # ---- state ----
    def state(self) -> dict:
        d = read_state(self.data_path)
        status = d.get("state") if d.get("state") in ("set_up", "skipped") else "new"
        return {"status": status, "at": d.get("at"), "by": d.get("by", ""), "from": d.get("from", ""),
                "pending": d.get("pending") or {}, "instance": d.get("instance") or {}}

    def is_new(self) -> bool:
        return self.state()["status"] == "new"

    def skip(self, who: str = "") -> dict:
        d = read_state(self.data_path)
        if d.get("state") != "set_up":
            write_state({**{k: v for k, v in d.items() if k != "format"}, "state": "skipped", "at": time.time(), "by": who},
                        self.data_path)
        return self.state()

    def _pending(self, kind: str, ident: str, table: dict | None) -> None:
        d = read_state(self.data_path)
        p = d.get("pending") if isinstance(d.get("pending"), dict) else {}
        group = dict(p.get(kind) or {})
        if table is None:
            group.pop(ident, None)
        else:
            group[ident] = {**group.get(ident, {}), **table}
        p = {**p, kind: group}
        p = {k: v for k, v in p.items() if v}
        write_state({**{k: v for k, v in d.items() if k not in ("format", "pending")}, **({"pending": p} if p else {})},
                    self.data_path)

    # ---- the rows of a plan ----
    @staticmethod
    def _row(section: str, key: str, label: str, old, new, status: str = "", note: str = "", restart: bool = False) -> dict:
        status = status or ("same" if old == new else "change")
        return {"section": section, "key": key, "label": label, "old": _shown(old), "new": _shown(new), "status": status,
                "note": note, "restart": restart and status == "change"}

    def _base_items(self, lab: dict):
        """(row, apply) for each base setting the lab has; apply is None when there is nothing to do."""
        from dataclasses import asdict

        from .backup import DEFAULT_MAX_UPLOAD_MB

        cur = self.backups.settings()
        here = "set in config.toml on this machine, which wins"
        for key, new in lab.get("lab", {}).items():
            label = BASE["lab"][key][0]
            if key == "name":
                yield self._row("lab", key, label, cur.lab_name, new), lambda v=new: self.backups.set_lab_name(v)
            else:
                yield self._row("lab", key, label, cur.language, new), lambda v=new: self.backups.set_language(v)
        jobs = lab.get("jobs", {})
        for key, cfg in (("keep_days", "job_retention_days"), ("keep_uploads_days", "upload_retention_days")):
            if key in jobs:
                label, stored = BASE["jobs"][key][0], getattr(cur, key)
                old = stored or getattr(settings, cfg)
                if cfg in settings.explicit:
                    yield self._row("jobs", key, label, old, jobs[key], "skip" if old != jobs[key] else "same", here), None
                else:
                    yield (self._row("jobs", key, label, old, jobs[key]),
                           lambda k=key, v=jobs[key]: self.backups.set_keep_days(**{k: v}))
        if "max_upload_mb" in jobs:
            yield (self._row("jobs", "max_upload_mb", BASE["jobs"]["max_upload_mb"][0],
                             cur.max_upload_mb or DEFAULT_MAX_UPLOAD_MB, jobs["max_upload_mb"]),
                   lambda v=jobs["max_upload_mb"]: self.backups.set_max_upload_mb(v))
        if "storage_folder" in jobs:
            yield from self._storage_item(jobs["storage_folder"])
        backup = lab.get("backup", {})
        if "folder" in backup:
            new = backup["folder"]
            folder = str(Path(new).expanduser()) if new else ""
            row = self._row("backup", "folder", BASE["backup"]["folder"][0], cur.backup_dir, folder)
            if row["status"] == "change":
                try:
                    self.backups.check_folder(folder)
                except ToolError as e:
                    row.update(status="error", note=str(e))
            yield row, lambda f=folder: self.backups.update(f, self.backups.settings().backup_after_days)
        if "after_days" in backup:
            yield (self._row("backup", "after_days", BASE["backup"]["after_days"][0], cur.backup_after_days, backup["after_days"]),
                   lambda v=backup["after_days"]: self.backups.set_after_days(v))
        printer = asdict(self.printer.settings()) | {"logo": self.printer.logo_data()}
        for key, new in lab.get("label_printer", {}).items():
            row = self._row("label_printer", key, BASE["label_printer"][key][0], printer.get(key), new)
            if key == "logo":  # a picture: say so, rather than show its data
                row.update(old=_picture(printer["logo"]), new=_picture(new))
            yield row, lambda k=key, v=new: self.printer.update({k: v})
        tools = lab.get("tools", {})
        if "bundled_off" in tools:
            yield (self._row("tools", "bundled_off", BASE["tools"]["bundled_off"][0], ", ".join(self.toolsources.bundled_off()),
                             ", ".join(tools["bundled_off"]), restart=True),
                   lambda v=tools["bundled_off"]: self.toolsources.set_bundled_off(v))
        if "catalogue" in tools:
            yield (self._row("tools", "catalogue", BASE["tools"]["catalogue"][0], self.toolsources.catalogue(), tools["catalogue"]),
                   lambda v=tools["catalogue"]: self.toolsources.set_catalogue(v))
        if "auto" in lab.get("updates", {}):
            new = lab["updates"]["auto"]
            yield (self._row("updates", "auto", BASE["updates"]["auto"][0], self.updater.auto_settings()["mode"], new),
                   lambda v=new: self.updater.set_auto(v))
        from . import updates

        cfg = updates.update_settings()
        for key in ("channel", "feed"):
            if key in lab.get("updates", {}):
                new = lab["updates"][key]
                yield (self._row("updates", key, BASE["updates"][key][0], cfg[key], new),
                       lambda k=key, v=new: updates.set_update_settings(**{k: v}))
        if "modules" in lab:
            on = lab["modules"]["on"]
            current = settings.enabled_modules()
            old = "all" if current is None else current
            label = "Modules that are on"
            unknown = [m for m in (on if isinstance(on, list) else []) if m not in self.modules.available()]
            if unknown:
                yield self._row("modules", "on", label, old, on, "error", "no such module here: " + ", ".join(unknown)), None
            elif "modules" in settings.explicit:
                yield self._row("modules", "on", label, old, on, "skip" if old != on else "same", here), None
            else:
                yield (self._row("modules", "on", label, old, on, restart=True),
                       lambda v=on: self._set_modules(None if v == "all" else v))

    def _set_modules(self, on: list | None) -> None:
        d = {k: v for k, v in read_state(self.data_path).items() if k not in ("format", "modules")}
        write_state({**d, **({"modules": on} if on is not None else {})}, self.data_path)

    def _storage_item(self, new: str):
        label = BASE["jobs"]["storage_folder"][0]
        old = str(settings.storage_path)
        folder = str(Path(new).expanduser()) if new else str(settings.data_path)
        if Path(folder).resolve() == Path(old).resolve():
            yield self._row("jobs", "storage_folder", label, old, folder, "same"), None
            return
        if self.jobs_count():
            yield self._row("jobs", "storage_folder", label, old, folder, "skip",
                            "there are jobs here already: change it on Settings → Jobs & backup, which moves them"), None
            return
        row = self._row("jobs", "storage_folder", label, old, folder, restart=True)
        try:
            self.storage.check_folder(folder, self.backups.settings().backup_dir)
        except ToolError as e:
            row.update(status="error", note=str(e), restart=False)
        yield row, lambda: self.storage.choose(folder, False, False, self.backups.settings().backup_dir, "lab file")

    def _source_items(self, lab: dict):
        current = {s["name"]: s for s in self.toolsources.sources()}
        for s in lab.get("tool_sources", []):
            name = s["name"]
            label = f"Tool source “{name}”"
            new = f"{s['url']} ({s['branch']})" + (", trusted" if s["trusted"] else "")
            have = current.get(name)
            if have is None:
                note = "" if s["trusted"] else "not trusted: added turned off and pinned, to be reviewed on Settings → Tools"
                yield (self._row("tool_sources", name, label, None, new, "change", note, restart=True),
                       lambda s=s: self.toolsources.configure(s))
                continue
            old = f"{have['url']} ({have['branch']})" + (", trusted" if have.get("trusted") else "")
            if have["url"].rstrip("/").removesuffix(".git") != s["url"].rstrip("/").removesuffix(".git"):
                yield self._row("tool_sources", name, label, old, new, "error",
                                "another repository has this name here: remove it on Settings → Tools first"), None
            else:
                yield self._row("tool_sources", name, label, old, new, restart=True), lambda s=s: self.toolsources.configure(s)

    def _module_rows(self, lab: dict, apply: bool, who: str) -> list[dict]:
        rows = []
        for mid, table in lab.get("module", {}).items():
            section = f"module.{mid}"
            if mid not in self.modules.available():
                rows.append(self._row(section, "", f"Module “{mid}”", None, None, "error", "there is no such module here"))
                continue
            if self.modules.can_configure(mid):
                try:
                    rows += [{**self._row(section, r["key"], r.get("label") or r["key"], r.get("old"), r.get("new"),
                                          r.get("status", ""), r.get("note", ""), r.get("restart", False))}
                             for r in self.modules.configure(mid, table, apply, who)]
                except ToolError as e:
                    rows.append(self._row(section, "", f"Module “{mid}”", None, None, "error", str(e)))
                continue
            loaded_later = mid not in self.modules.loaded  # turned on by this file, say
            note = ("applied when the module is loaded (after a restart)" if loaded_later
                    else "this module takes no settings from a lab file")
            rows += [self._row(section, k, k, None, v, "later" if loaded_later else "error", note) for k, v in table.items()]
            if apply and loaded_later:
                self._pending("module", mid, table)
        return rows

    def _tool_rows(self, lab: dict, apply: bool, who: str) -> list[dict]:
        from . import toolsettings
        from .i18n import tr

        rows = []
        for tid, table in lab.get("tool", {}).items():
            section = f"tool.{tid}"
            tool = self.registry.get(tid) if self.registry else None
            if tool is None or not getattr(tool, "settings", None):
                rows += [self._row(section, k, k, None, v, "later", "applied when this tool is here (after the tool sources are fetched)")
                         for k, v in table.items()]
                if apply:
                    self._pending("tool", tid, table)
                continue
            known = {i.name: i for i in tool.settings}
            have = toolsettings.values(tool)
            for k, v in table.items():
                if k not in known:
                    rows.append(self._row(section, k, k, None, v, "error", f"{tr(tool.name)} has no such setting"))
                    continue
                label = f"{tr(tool.name)}: {tr(known[k].label)}"
                try:
                    v = known[k].parse(v, toolsettings._no_files)
                    rows.append(self._row(section, k, label, have.get(k), v))
                except (ToolError, ValueError, TypeError) as e:
                    rows.append(self._row(section, k, label, have.get(k), v, "error", str(e)))
            changes = {r["key"]: table[r["key"]] for r in rows if r["section"] == section and r["status"] == "change"}
            if apply and changes:
                try:
                    toolsettings.save(tool, {**toolsettings.saved(tid), **changes}, who)
                    for r in rows:
                        if r["section"] == section and r["status"] == "change":
                            r["status"] = "done"
                except ToolError as e:
                    for r in rows:
                        if r["section"] == section and r["status"] == "change":
                            r.update(status="error", note=str(e))
        return rows

    def plan(self, lab: dict) -> list[dict]:
        """What applying ``lab`` would change, setting by setting (status: change, same, skip, later or error)."""
        rows = [row for row, _ in self._base_items(lab)] + [row for row, _ in self._source_items(lab)]
        return rows + self._module_rows(lab, False, "") + self._tool_rows(lab, False, "")

    def apply(self, lab: dict, who: str = "", source: str = "page") -> dict:
        """Apply ``lab``: each setting on its own (one that can't be set is reported, the rest still are).
        Returns {"rows": [...], "restart": bool}; a row's status is done, same, skip, later or error."""
        rows = []
        for items in (self._base_items(lab), self._source_items(lab)):
            for row, fn in items:
                if row["status"] == "change" and fn is not None:
                    try:
                        fn()
                        row["status"] = "done"
                    except (ToolError, ValueError, OSError) as e:
                        row.update(status="error", note=str(e), restart=False)
                rows.append(row)
        rows += self._module_rows(lab, True, who)
        rows += self._tool_rows(lab, True, who)
        d = {k: v for k, v in read_state(self.data_path).items() if k != "format"}
        write_state({**d, "state": "set_up", "at": time.time(), "by": who, "from": source}, self.data_path)
        restart = any(r.get("restart") for r in rows) or any(r["status"] == "later" and r["section"].startswith("module.")
                                                              for r in rows)
        return {"rows": rows, "restart": restart}

    # ---- what waits for a module or a tool ----
    def apply_pending_modules(self) -> None:
        for mid, table in dict(self.state()["pending"].get("module") or {}).items():
            if mid in self.modules.loaded and self.modules.can_configure(mid):
                try:
                    rows = self.modules.configure(mid, table, True, "lab file")
                    bad = [r for r in rows if r.get("status") == "error"]
                    for r in bad:
                        print(f"lab file: [module.{mid}] {r.get('key')}: {r.get('note')}", flush=True)
                except ToolError as e:
                    print(f"lab file: [module.{mid}]: {e}", flush=True)
                self._pending("module", mid, None)

    def apply_pending_tools(self) -> None:
        for tid, table in dict(self.state()["pending"].get("tool") or {}).items():
            tool = self.registry.get(tid)
            if tool is not None and getattr(tool, "settings", None):
                for r in self._tool_rows({"tool": {tid: table}}, True, "lab file"):
                    if r["status"] == "error":
                        print(f"lab file: [tool.{tid}] {r['key']}: {r['note']}", flush=True)
                self._pending("tool", tid, None)

    # ---- the way back: this server's settings as a lab ----
    def current(self) -> dict:
        from dataclasses import asdict

        from .backup import DEFAULT_MAX_UPLOAD_MB

        from . import toolsettings

        cur = self.backups.settings()
        on = settings.enabled_modules()
        printer = asdict(self.printer.settings()) | {"logo": self.printer.logo_data()}
        lab = {
            "lab": {"name": cur.lab_name or self.backups.lab, "language": cur.language},
            "tool_sources": [{"name": s["name"], "url": s["url"], "branch": s["branch"], "trusted": bool(s.get("trusted"))}
                             for s in self.toolsources.sources()],
            "modules": {"on": "all" if on is None else on},
            "tools": {"bundled_off": self.toolsources.bundled_off(), "catalogue": self.toolsources.catalogue()},
            "module": {mid: t for mid, t in self.modules.lab_settings().items() if t},
            "jobs": {"keep_days": cur.keep_days or settings.job_retention_days,
                     "keep_uploads_days": cur.keep_uploads_days or settings.upload_retention_days,
                     "max_upload_mb": cur.max_upload_mb or DEFAULT_MAX_UPLOAD_MB,
                     "storage_folder": "" if settings.storage_path == settings.data_path else str(settings.storage_path)},
            "backup": {"folder": cur.backup_dir, "after_days": cur.backup_after_days},
            "label_printer": {k: printer[k] for k in BASE["label_printer"] if k in printer},
            "updates": {"auto": self.updater.auto_settings()["mode"], **_update_settings()},
        }
        tools = {}
        for t in (self.registry.tools.values() if self.registry else []):
            if getattr(t, "settings", None) and toolsettings.saved(t.id):
                tools[t.id] = {k: v for k, v in toolsettings.values(t).items() if v not in (None, "")}
        if tools:
            lab["tool"] = tools
        return normalize(lab)[0]


# ---- can this server reach the lab's repositories? -----------------------------------------------------------------

def reach(url: str, token: bool = True, timeout: float = 30) -> dict:
    """Whether a repository can be read from here: {"status": "public" | "token" | "folder" | "unreachable", "note"}.
    ``token``: also try with the server's GitHub token (never for a tool source that isn't trusted)."""
    from . import gitutil

    address = gitutil.address(url)
    folder = gitutil.local_folder(address)
    if folder is not None:
        ok = (folder / ".git").exists() or (folder / "HEAD").is_file()
        return {"status": "folder" if ok else "unreachable",
                "note": "" if ok else f"{folder} isn't a git repository on this computer"}
    plain = ("-c", "credential.helper=", "-c", "core.askPass=")
    code, out = gitutil.run("ls-remote", "--heads", address, cwd=ROOT, timeout=timeout, options=plain)
    if code == 0:
        return {"status": "public", "note": ""}
    if token:
        code, out = gitutil.run("ls-remote", "--heads", address, cwd=ROOT, timeout=timeout, credentials=True)
        if code == 0:
            return {"status": "token", "note": ""}
    last = [line for line in str(out).splitlines() if line.strip()][-1:] or [""]
    if not token:
        return {"status": "unreachable", "note": "it isn't public, or doesn't exist: " + last[0].strip()}
    owner = _owner(address)
    add = (f"add a token for {owner} on Settings → Server & updates → GitHub access" if owner
           else "add a token on Settings → Server & updates → GitHub access")
    return {"status": "unreachable",
            "note": f"no token of this server reaches it ({add}), or it doesn't exist: " + last[0].strip()}


def _owner(address: str) -> str:
    """The owner in a repository's address: https://github.com/smith-lab/x.git or git@github.com:smith-lab/x → smith-lab."""
    m = re.match(r"^(?:https?://(?:[^@/]+@)?[^/]+/|ssh://(?:[^@/]+@)?[^/]+/|[^@\s]+@[^:]+:)([^/]+)/", address.strip())
    return m.group(1) if m else ""


def repositories(lab: dict, forms: list[dict]) -> list[dict]:
    """The repositories a lab names: its tool sources, and the module questions of the kind "repository"."""
    out = [{"what": f"Tool source “{s['name']}”", "url": s["url"], "token": s["trusted"]} for s in lab.get("tool_sources", [])]
    kinds = {(f["id"], q["key"]): q for f in forms for q in f["fields"]}
    for mid, table in lab.get("module", {}).items():
        for k, v in table.items():
            q = kinds.get((mid, k))
            if q and q["kind"] == "repository" and isinstance(v, str) and v.strip():
                out.append({"what": f"{next((f['name'] for f in forms if f['id'] == mid), mid)}: {q['label']}", "url": v.strip(),
                            "token": True})
    return out


def check_access(lab: dict, forms: list[dict]) -> list[dict]:
    """:func:`reach` for every repository the lab names, a few at a time."""
    from concurrent.futures import ThreadPoolExecutor

    repos = repositories(lab, forms)
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = list(pool.map(lambda r: reach(r["url"], r["token"]), repos))
    return [{**r, **f} for r, f in zip(repos, found)]
