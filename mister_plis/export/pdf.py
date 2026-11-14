"""``report.pdf``: the same PDF as the result page's PDF button (in English), with the plots as pictures when they
could be made (``plots.py``); otherwise the PDF says where the interactive plots are."""

from __future__ import annotations

import sys
from pathlib import Path


def write(rec: dict, job_dir: Path, dest: Path, plots: dict, tool=None, lab: str = "") -> str | None:
    from .. import __version__, printout, report

    outputs = [o for o in rec.get("outputs") or [] if isinstance(o, dict)]
    if rec.get("status") != "done" or not printout.printable(outputs):
        return None
    jid = rec.get("id") or ""

    def picture(i: int, o: dict) -> bytes | None:
        if o.get("kind") == "plot":
            png = (plots.get(i) or {}).get("png")
            return (dest / png).read_bytes() if png else None
        url = str(o.get("url") or "")
        marker = f"/{jid}/files/"  # /api/jobs/<id>/files/… or a module's copy of the job
        if url.startswith("/api/") and marker in url:
            p = (job_dir / url.split(marker, 1)[1]).resolve()
            if job_dir.resolve() in p.parents and p.is_file() and p.stat().st_size < 40 * 1024 * 1024:
                return p.read_bytes()
        return None

    title = rec.get("tool_name") or ""
    info = report.ReportInfo(title=f"{title} — {rec['title']}" if rec.get("title") else title, tool=title, job_id=jid,
                             run_by=rec.get("user") or "", run_at=rec.get("started") or rec.get("created"), lab=lab,
                             version=__version__, decimal=".")
    try:
        info.params = report.describe_settings(tool, rec.get("params") or {}, ".")
        (dest / "report.pdf").write_bytes(printout.results_pdf(outputs, info, picture))
        return "report.pdf"
    except Exception as e:  # a PDF that can't be drawn must not stop the backup: the README and workbook have it all
        print(f"backup: no report.pdf for {jid}: {type(e).__name__}: {e}", file=sys.stderr)
        return None
