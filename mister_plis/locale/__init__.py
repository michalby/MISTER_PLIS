"""Translations, English → Polish. See mister_plis/i18n.py.

The base's own texts are here (``pl_*.py``). The tools bring theirs: ``locale/pl.py`` (a dict ``PL``) next to the
tools, in every tool folder the server loads (each tool source, and each folder in ``tool_folders``). Modules bring
theirs the same way (``modules/<id>/locale/pl.py``). The base's texts win when both have the same key.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .pl_ui import UI


def tool_catalogues(folders: list[Path] | None = None, language: str = "pl") -> list[dict[str, str]]:
    """The ``PL`` dicts of ``<folder>/locale/<language>.py`` in each tool folder (a broken file is skipped and
    reported on stderr, like a broken tool: the interface just shows those texts in English)."""
    if folders is None:
        from ..toolsources import sources

        folders = [f["path"] for f in sources.folders()]
    out = []
    for folder in folders:
        path = Path(folder) / "locale" / f"{language}.py"
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"_mister_plis_tool_locale_{abs(hash(str(path)))}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            entries = getattr(mod, language.upper(), None)
            if isinstance(entries, dict):
                out.append(entries)
        except Exception as e:  # pragma: no cover - a broken catalogue must not stop the server
            print(f"could not read the translations in {path}: {e}", file=sys.stderr)
    return out


def merged(language: str = "pl", folders: list[Path] | None = None) -> dict[str, str]:
    tools: dict[str, str] = {}
    for entries in tool_catalogues(folders, language=language):
        tools.update(entries)
    from ..modules import catalogues as module_catalogues

    for entries in module_catalogues(language):  # each module's modules/<id>/locale/<language>.py
        tools.update(entries)
    return {**tools, **UI}


PL: dict[str, str] = merged("pl")


def reload(folders: list[Path] | None = None) -> None:
    """Read the catalogues again (after the tool sources changed, at start). ``folders``: the tool folders whose
    translations to read (default: the tool sources'; a worker gives the ones it was sent)."""
    global PL
    PL = merged("pl", folders)
    from .. import i18n

    i18n._catalogs.cache_clear()
    i18n._translate.cache_clear()
