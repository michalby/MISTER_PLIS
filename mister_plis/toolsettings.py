"""Settings a tool declares itself (``Tool(settings=[...])``, toolkit 1.1): what it needs set up on this server —
where a program is installed, say. Lab-wide, set on Settings → Tools.

They belong to this machine (a program's path is about this computer), so they are kept in the server's data
folder, not in the storage folder that can move between machines: ``<data>/tool-settings/<tool id>.json`` =
``{"format": 1, "values": {name: value}, "changed_by": str, "changed_at": float}`` (docs/FORMATS.md). A tool that
is gone leaves its file alone: it comes back with the tool.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .errors import ToolError

FORMAT = 1
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def _no_files(_):
    raise ToolError("a setting can't be a file")


def folder() -> Path:
    from .config import settings

    return settings.data_path / "tool-settings"


def _file(tool_id: str) -> Path:
    if not _ID.match(tool_id or ""):
        raise ValueError(f"not a tool id: {tool_id!r}")
    return folder() / f"{tool_id}.json"


def record(tool_id: str) -> dict:
    """The saved record ({} when nothing was saved, or the file can't be read)."""
    try:
        d = json.loads(_file(tool_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) and isinstance(d.get("values"), dict) else {}


def saved(tool_id: str) -> dict:
    """The raw saved values, as stored."""
    return dict(record(tool_id).get("values") or {})


def values(tool) -> dict[str, Any]:
    """Every setting of ``tool``: the saved value, read like a form value; its default when nothing usable is saved."""
    raw = saved(tool.id)
    out = {}
    for inp in tool.settings:
        try:
            out[inp.name] = inp.parse(raw[inp.name], _no_files) if inp.name in raw else inp.parse(inp.default, _no_files)
        except (ToolError, ValueError, TypeError):
            out[inp.name] = inp.default
    return out


def save(tool, raw: dict, by: str = "") -> dict[str, Any]:
    """Check ``raw`` like a form (a ToolError lists what is wrong) and keep it; returns the values as read back."""
    from .i18n import tr

    new, errors = {}, []
    for inp in tool.settings:
        try:
            new[inp.name] = inp.parse(raw.get(inp.name, inp.default), _no_files)
        except ToolError as e:
            errors.append(f"{tr(inp.label)}: {tr(str(e))}")
    if errors:
        raise ToolError("\n".join(errors))
    path = _file(tool.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"format": FORMAT, "values": new, "changed_by": by, "changed_at": time.time()}, indent=1,
                              ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return values(tool)


def status(tool) -> str | None:
    """The tool's own one-line status of its settings (``Tool.settings_status``), or None."""
    if not tool.settings_status:
        return None
    try:
        return tool.settings_status()
    except Exception as e:  # pragma: no cover - a tool's check must not break the page
        return f"The check failed: {e}"
