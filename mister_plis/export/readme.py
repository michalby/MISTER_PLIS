"""``README.md``: everything about a job, readable without MISTER PLIS — who ran it, when, with which tool and settings,
from which files, and every result in the order the tool showed them, pointing at the files next to it."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

TABLE_PREVIEW = 20
LOG_LINES = 50


def _when(t) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "—"


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _md_table(columns: list, rows: list) -> str:
    if not columns:
        return ""
    head = "| " + " | ".join(_cell(c) for c in columns) + " |"
    sep = "|" + "|".join(" --- " for _ in columns) + "|"
    body = ["| " + " | ".join(_cell(v) for v in r) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def _html_to_text(html: str) -> str:
    """Markdown/alert outputs keep their Markdown in ``md``; older records only have HTML."""
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", html or "")
    text = re.sub(r"<li>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _link(path: str) -> str:
    return "<" + path + ">" if " " in path else path


def build(rec: dict, job_dir: Path, made: dict, tool=None) -> str:
    from ..report import describe_files, describe_settings

    title = rec.get("tool_name") or rec.get("tool_id") or "Job"
    lines = [f"# {title}" + (f" — {rec['title']}" if rec.get("title") else ""), "",
             f"Job number **{rec.get('id')}** · MISTER PLIS", ""]
    tool_rec = rec.get("tool") or {}
    base = rec.get("base") or {}
    facts = [("Run by", rec.get("user") or "(no name set)"), ("Started", _when(rec.get("started") or rec.get("created"))),
             ("Finished", _when(rec.get("finished"))), ("Status", rec.get("status") or ""),
             ("Tool", f"{title} (`{rec.get('tool_id')}`)"), ("Keyword", rec.get("keyword") or ""),
             ("Tool from", " · ".join(x for x in (tool_rec.get("source"), tool_rec.get("source_url"), (tool_rec.get("commit") or "")[:10]) if x)),
             ("MISTER PLIS", " · ".join(x for x in (base.get("version"), (base.get("commit") or "")[:10]) if x)),
             ("Re-run of job", rec.get("parent") or "")]
    lines += ["| | |", "|---|---|"] + [f"| {k} | {_cell(v)} |" for k, v in facts if v] + [""]

    inputs = rec.get("inputs") or {}
    files = describe_files(tool, rec.get("files") or {})
    if inputs or files:
        lines += ["## Input files", ""]
        if inputs:
            labels = dict((i.name, i.label) for i in (tool.inputs if tool else []) if hasattr(i, "label"))
            for name, entries in inputs.items():
                for e in entries if isinstance(entries, list) else []:
                    kept = f"copy in `mister-plis/{e['path']}`" if e.get("kept") and e.get("path") else "not kept (too large)"
                    lines.append(f"- **{labels.get(name, name)}:** {e.get('name')} — {e.get('size', 0):,} bytes, "
                                 f"SHA-256 `{(e.get('sha256') or '')[:16]}…`, {kept}")
        else:
            lines += [f"- **{label}:** {', '.join(names)}" for label, names in files]
        lines.append("")

    try:
        settings = describe_settings(tool, rec.get("params") or {}, ".")
    except Exception:  # the tool changed since: the raw values are in mister-plis/job.json
        settings = []
    if settings:
        lines += ["## Settings", ""] + [f"- **{label}:** {_cell(text)}" for label, text in settings] + [""]

    lines += ["## Results", ""]
    if rec.get("status") != "done":
        lines += [f"This job did not finish: **{rec.get('status')}**." + (f" {rec.get('error')}" if rec.get("error") else ""), ""]
    tables, plots = made.get("tables") or {}, made.get("plots") or {}
    jid = rec.get("id") or ""
    for i, o in enumerate(rec.get("outputs") or []):
        if not isinstance(o, dict):
            continue
        kind = o.get("kind")
        if kind == "metric":
            unit = f" {o['unit']}" if o.get("unit") else ""
            lines.append(f"- **{o.get('label')}:** {o.get('value')}{unit}")
            continue
        if lines[-1] != "":
            lines.append("")
        if kind in ("html", "alert"):
            text = o.get("md") if isinstance(o.get("md"), str) else _html_to_text(o.get("html") or "")
            if kind == "alert":
                text = "\n".join("> " + line for line in text.splitlines()) or "> "
                text = f"> **{(o.get('level') or 'note').capitalize()}**\n>\n" + text
            lines.append(text)
        elif kind == "text":
            lines += [f"### {o.get('title')}" if o.get("title") else "", "```", o.get("text") or "", "```"]
        elif kind == "table":
            t = tables.get(i) or {}
            lines.append(f"### {o.get('title') or 'Table'}")
            cols, rows = o.get("columns") or [], (o.get("rows") or [])[:TABLE_PREVIEW]
            lines += ["", _md_table(cols, rows), ""]
            total = o.get("total_rows") or len(o.get("rows") or [])
            where = f"`results.xlsx`, sheet “{t['sheet']}”" if t.get("sheet") else f"`{t['csv']}`" if t.get("csv") else "—"
            shown = f"First {len(rows)} of {total} rows. " if total > len(rows) else ""
            partial = "" if t.get("complete", True) else f" (only the {t.get('rows')} rows the job kept)"
            lines.append(f"{shown}The whole table: {where}{partial}.")
        elif kind == "plot":
            p = plots.get(i) or {}
            lines.append(f"### {o.get('title') or 'Plot'}")
            if p.get("png"):
                lines += ["", f"![{o.get('title') or 'plot'}]({_link(p['png'])})"]
            lines += ["", f"Interactive: [{p.get('html')}]({_link(p.get('html') or '')}) (opens in a browser, offline). "
                          "The plotted values are in `results.xlsx`, sheet “Plot data”."]
        elif kind in ("image", "file", "video"):
            name = o.get("name") or ""
            rel = _file_rel(o.get("url") or "", jid)
            target = f"files/{rel[len('out/'):]}" if rel.startswith("out/") else rel
            label = o.get("title") or o.get("label") or name
            if kind == "image":
                lines += [f"**{label}**", "", f"![{label}]({_link(target)})"]
            else:
                lines.append(f"- [{label}]({_link(target)})" + (f" — {o['description']}" if o.get("description") else ""))
    lines.append("")

    if made.get("pdf"):
        lines += ["The whole result as one printable page: [report.pdf](report.pdf).", ""]
    log = [line for line in (rec.get("log") or []) if line][-LOG_LINES:]
    if log or rec.get("error"):
        lines += ["## Log", "", "```", *log, *([rec["error"]] if rec.get("error") else []), "```", ""]
    lines += ["## Bringing this job back into MISTER PLIS", "",
              "**Jobs & results → Import from backup**, then search for the job number. The `mister-plis/` folder holds what "
              "that needs (the job's record, its input files and checksums of every file); please leave it as it is.", ""]
    return "\n".join(lines)


def _file_rel(url: str, jid: str) -> str:
    marker = f"/{jid}/files/"  # /api/jobs/<id>/files/… or a module's copy of the job (/api/<area>/<id>/files/…)
    return url.split(marker, 1)[1] if url.startswith("/api/") and marker in url else ""


def write(rec: dict, job_dir: Path, dest: Path, made: dict, tool=None) -> None:
    (dest / "README.md").write_text(build(rec, job_dir, made, tool), encoding="utf-8")
