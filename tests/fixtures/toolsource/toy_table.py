"""A toy file tool: reads "sample,value" tables and averages the samples. It has what the base's job features need:
an uploaded file, a sample table filled by a suggester, tables with downloads, a plot, a workbook among the files."""

from __future__ import annotations

import csv

import pandas as pd
import plotly.graph_objects as go

from mister_plis.toolkit import Tool, ToolError, find_program, fmt, inputs as I, outputs as O, tool_setting, tr, write_workbook

tool = Tool(
    id="toy-table",
    name="Toy averages",
    category="Spectroscopy",
    icon="leaf",
    description="Averages the values of each sample in “sample,value” tables (a test tool).",
    wide=True,
    order=20,
    inputs=[
        I.File("files", "Measurements", accept=".csv,.txt", multiple=True),
        I.SampleTable("samples", "Samples", source="files", columns=[
            I.col("source", "Source", "readonly"),
            I.col("include", "Use", "checkbox"),
            I.col("sample", "Sample name", "text"),
            I.col("value", "Value", "readonly"),
        ]),
        I.Section("Settings"),
        I.Number("factor", "Dilution", default=2, min=0.001, unit="×"),
    ],
    # what it needs set up on the server (toolkit 1.1): a made-up helper program, to test Settings → Tools
    settings=[I.Text("program", "Helper program", placeholder="/usr/local/bin/toy-helper",
                     help="Leave empty to look in the usual places.")],
    settings_status=lambda: tr("Found: {path}", path=p) if (p := helper()) else tr("The helper program was not found."),
)


def helper() -> str | None:
    return find_program("toy-helper", (), configured=tool_setting("toy-table", "program"))


def read(path) -> list[tuple[str, float]]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = [r for r in csv.reader(fh) if r]
    if not rows or [c.strip().lower() for c in rows[0][:2]] != ["sample", "value"]:
        raise ToolError(f"{path.name}: not a “sample,value” table.")
    try:
        return [(r[0].strip(), float(r[1])) for r in rows[1:]]
    except (ValueError, IndexError):
        raise ToolError(f"{path.name}: a value that isn't a number.") from None


@tool.suggest("samples")
def suggest(files, params):
    return [{"key": f"{f.id}:{i}", "source": f.name, "include": True, "sample": name, "value": value}
            for f in sorted(files, key=lambda f: f.name) for i, (name, value) in enumerate(read(f.path))]


@tool.runner
def run(p, ctx):
    ctx.log(f"helper program: {ctx.setting('program') or 'not set'}")
    files = {f.id: f for f in p.files}
    rows = []
    for r in p.samples:
        fid, idx = r["key"].rsplit(":", 1)
        if r.get("include") and fid in files:
            _, value = read(files[fid].path)[int(idx)]
            rows.append({"Sample": r.get("sample") or "?", "Source": files[fid].name, "Value": value * p.factor})
    if not rows:
        raise ToolError("No measurements selected — upload files and tick the samples to use.")
    every = pd.DataFrame(rows)
    means = every.groupby("Sample", sort=False)["Value"].agg(["count", "mean"]).reset_index()
    means.columns = ["Sample", "n", "Mean"]
    fig = go.Figure(go.Bar(x=means["Sample"], y=means["Mean"]))
    book = write_workbook(ctx.out("toy_results.xlsx"), {"Means": means, "Measurements": every}, [("Dilution", p.factor)])
    return [
        O.File(book, label="Results workbook (.xlsx)", primary=True),
        O.Metric("Mean value", float(every["Value"].mean()), help=tr("{n} measurements", n=len(every))),
        O.Table(means, title="Samples and means", download="toy.xlsx"),
        O.Plot(fig, title="Mean per sample"),
        O.Table(every, title="Every measurement", download="toy_rows.xlsx"),
        O.Text(" ".join(means["Sample"]), title="Sample names"),
        O.Markdown(f"Values × **{fmt(p.factor)}**."),
    ]
