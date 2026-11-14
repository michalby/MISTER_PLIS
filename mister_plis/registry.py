"""Finds tools in the tool sources (mister_plis/toolsources.py): the git repositories of tools, and this machine's
``tool_folders``. A file that fails to import is reported, not fatal."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback
import types
from dataclasses import dataclass
from pathlib import Path

from .toolkit import Tool

NOT_TOOLS = {"locale", "tests"}  # folders next to the tools: their translations and their tests
# Categories listed first, in this order; any others follow alphabetically.
CATEGORY_ORDER = ["Calculators", "Spectroscopy", "Assays", "Images", "Rendering"]


@dataclass
class BrokenTool:
    module: str
    error: str


class Registry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        self.broken: list[BrokenTool] = []
        self._package_paths: list[str] = []  # the tool sources' own packages, at the end of sys.path
        self.folders: list[dict] = []  # the folders loaded last (what a job's own process loads: runners.ProcessRunner)

    def load(self, folders: list[dict] | None = None) -> None:
        """Load the tools of every source folder (``folders``: from ToolSources.folders(); default: the sources)."""
        self.tools.clear()
        self.broken.clear()
        if folders is None:
            from .toolsources import sources

            folders = sources.folders()
        self.folders = [f for f in folders if not f.get("error")]
        self._use_packages([f.get("packages") for f in folders if not f.get("error")])
        for src in folders:
            if src.get("error"):
                self.broken.append(BrokenTool(f"tool source {src['name']}", src["error"]))
                continue
            self._load_folder(src)

    def _use_packages(self, paths: list) -> None:
        """Make the enabled sources' own packages importable — appended, so the app's own packages win — and drop
        those of sources no longer loaded."""
        wanted = [str(p) for p in paths if p]
        for p in self._package_paths:
            if p not in wanted and p in sys.path:
                sys.path.remove(p)
        for p in wanted:
            if p not in sys.path:
                sys.path.append(p)
        self._package_paths = wanted
        importlib.invalidate_caches()

    def _load_folder(self, src: dict) -> None:
        path, name = Path(src["path"]), src["name"]
        # each source its own package, so helper modules of two sources never collide. ``package`` lets a tools
        # repository's own tests load it under the name they import it by (``tools``).
        package = src.get("package") or f"mp_tools_{name}"
        loaded = sys.modules.get(package)
        if loaded is not None and list(getattr(loaded, "__path__", [])) != [str(path)] and not src.get("package"):
            for mod in [m for m in sys.modules if m == package or m.startswith(package + ".")]:
                del sys.modules[mod]  # the same name from another folder (a working copy instead of the clone)
        if package not in sys.modules:
            pkg = types.ModuleType(package)
            pkg.__path__ = [str(path)]
            sys.modules[package] = pkg
        for info in sorted(pkgutil.iter_modules([str(path)]), key=lambda m: m.name):
            if info.name.startswith("_") or info.name in NOT_TOOLS:
                continue
            modname = f"{package}.{info.name}"
            try:
                mod = importlib.import_module(modname)
            except Exception:
                self.broken.append(BrokenTool(modname, traceback.format_exc(limit=6)))
                continue
            found = [v for v in vars(mod).values() if isinstance(v, Tool)]
            if not found:
                self.broken.append(BrokenTool(modname, "No `tool = Tool(...)` defined in this module."))
            for t in found:
                if t.id in self.tools and src.get("bundled"):
                    continue  # the lab's own tool of that id (a source loaded before) stands in for the one MISTER PLIS brings
                if t.id in self.tools:
                    first = self.tools[t.id].source
                    self.broken.append(BrokenTool(modname, f"Duplicate tool id {t.id!r} (already used by the tool source {first!r})"))
                    continue
                t.source, t.source_url, t.source_commit = name, src.get("url", ""), src.get("commit", "")
                self.tools[t.id] = t

    def get(self, tool_id: str) -> Tool | None:
        return self.tools.get(tool_id)

    def sorted(self) -> list[Tool]:
        def cat_key(c: str):
            return (CATEGORY_ORDER.index(c), "") if c in CATEGORY_ORDER else (len(CATEGORY_ORDER), c.lower())

        return sorted(self.tools.values(), key=lambda t: (cat_key(t.category), t.order, t.name.lower()))

    def by_category(self) -> list[tuple[str, list[Tool]]]:
        groups: dict[str, list[Tool]] = {}
        for t in self.sorted():
            groups.setdefault(t.category, []).append(t)
        return list(groups.items())


registry = Registry()
