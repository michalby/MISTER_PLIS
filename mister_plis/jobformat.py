"""The job record on disk: ``job.json`` (v1), and reading the older ``meta.json`` (v0). See docs/FORMATS.md.

v1 is v0 with more: every v0 field keeps its name and meaning (so a v0 reader can still read a v1 record), plus

- ``format`` / ``format_version``: ``"mister-plis-job"`` / 1;
- ``tool``: ``{id, name, source, source_url, commit}`` — which tool made it, from where (``"builtin"`` until tools
  come from their own repositories), at which commit;
- ``base``: ``{version, commit}`` — the MISTER PLIS that ran it;
- ``prefs``: the settings of whoever ran it (language of their interface, decimal mark…);
- ``inputs``: input name → ``[{id, name, path, size, sha256, kept}]`` — the uploaded files, copied into
  ``inputs/<input name>/`` when ``kept``;
- ``record``: always true (only jobs kept in the history are written).

A folder can hold ``job.json``, ``meta.json`` or both; ``job.json`` wins.
"""

from __future__ import annotations

import json
from pathlib import Path

FORMAT = "mister-plis-job"
VERSION = 1
JOB_FILE = "job.json"
V0_FILE = "meta.json"


def to_v1(d: dict) -> dict:
    """A v0 ``meta.json`` (or a v1 record) as a v1 record. Nothing is lost; what v0 didn't know stays empty."""
    out = dict(d)
    out["format"], out["format_version"] = FORMAT, VERSION
    tool = out.get("tool") if isinstance(out.get("tool"), dict) else {}
    out["tool"] = {"id": tool.get("id") or out.get("tool_id") or "", "name": tool.get("name") or out.get("tool_name") or "",
                   "source": tool.get("source") or "", "source_url": tool.get("source_url") or "", "commit": tool.get("commit") or ""}
    if isinstance(tool.get("needs"), list) and tool["needs"]:  # from toolkit 1.2: what a computer must have to run it
        out["tool"]["needs"] = [str(n) for n in tool["needs"]]
    out["tool_id"], out["tool_name"] = out["tool"]["id"], out["tool"]["name"] or out["tool"]["id"]
    base = out.get("base") if isinstance(out.get("base"), dict) else {}
    out["base"] = {"version": base.get("version") or "", "commit": base.get("commit") or ""}
    out.setdefault("prefs", {})
    out.setdefault("inputs", {})
    out.setdefault("phrases", {})
    out["record"] = True
    return out


def read_job(folder: Path) -> dict | None:
    """The record in a job folder (v1, or v0 converted), or None when there is none / it can't be read."""
    for name in (JOB_FILE, V0_FILE):
        p = Path(folder) / name
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("id"):
            return to_v1(d)
    return None


def record_file(folder: Path) -> Path | None:
    """The file :func:`read_job` reads in ``folder``."""
    for name in (JOB_FILE, V0_FILE):
        p = Path(folder) / name
        if p.is_file():
            return p
    return None
