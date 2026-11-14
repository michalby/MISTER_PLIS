"""A job as files anyone can read without MISTER PLIS — the human-readable half of a backup (reorg phase P3,
docs/FORMATS.md §11): ``README.md``, ``results.xlsx``, ``plots/`` (interactive .html, .png when possible),
``report.pdf`` and ``tables/*.csv`` for tables too big for Excel. Always in English, like every file the app writes.

Each part is a function of the job's record (``job.json``) and its folder; :func:`export_job` writes them all.
"""

from __future__ import annotations

from pathlib import Path

from ..prefs import DEFAULTS, current_prefs


def slug(text: str, limit: int = 60) -> str:
    """A title as a piece of a file name: "Pigments per sample (mean ± SD)" → "Pigments-per-sample-mean-SD"."""
    keep = "".join(c if c.isalnum() or c in "-._" else " " for c in str(text or ""))
    return "-".join(keep.split()).strip(".-_")[:limit] or "untitled"


def export_job(rec: dict, job_dir: Path, dest: Path, tool=None, lab: str = "") -> dict:
    """Write the readable files of the job ``rec`` (whose folder is ``job_dir``) into ``dest``. Returns what was made:
    ``{"files": [paths inside dest], "plots": {index: {...}}, "tables": {index: {...}}, "notes": [...]}``."""
    from . import pdf, plots, readme, workbook

    token = current_prefs.set({**DEFAULTS, "lang": "en"})  # files on disk are English, with plain numbers
    try:
        dest.mkdir(parents=True, exist_ok=True)
        made = {"files": [], "notes": []}
        made["plots"] = plots.write(rec, dest)
        made["tables"] = workbook.write(rec, job_dir, dest)
        made["pdf"] = pdf.write(rec, job_dir, dest, made["plots"], tool, lab)
        readme.write(rec, job_dir, dest, made, tool)
        made["files"] = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
        return made
    finally:
        current_prefs.reset(token)
