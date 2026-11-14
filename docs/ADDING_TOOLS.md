# Adding a tool

A tool is **one Python file in a tool source**. MISTER PLIS finds it automatically, builds the form, handles uploads,
runs your code in the background and shows the results. You write no HTML or JavaScript. This page is the reference
for writing one; the lab's own tools are a good place to copy from.

**Where tools live.** Tools come from **tool sources**: git repositories of tools, listed on Settings → Tools → Tool
sources (`mister_plis/toolsources.py`). The lab's own are in
[`smith-lab/lab-tools`](https://github.com/smith-lab/lab-tools), whose README has the step-by-step howto.
Another lab's repository works too; a private one is added with a token that can read it (pasted next to its
address, kept on the server for that repository only). A tool source is a folder with:

| | |
|---|---|
| `mister-plis-tools.toml` | its manifest: `[source]` with `name`, `title`, `requires_toolkit` (e.g. `">=1,<2"`), `requirements`, `locale`; and, shown on Settings → Tools and in a catalogue, `description`, `maintainer`, `homepage`, `license` (all optional) |
| `*.py` | one tool each; files starting with `_` are helpers shared by the tools, imported relatively (`from ._units import …`) |
| `locale/pl.py` | the tools' texts in Polish (a dict `PL`) |
| `requirements.txt` | packages the tools need beyond MISTER PLIS's own (installed only if they change none of its packages) |
| `tests/` | the tools' tests |

`tests/fixtures/toolsource/` in this repository is the smallest example: two test tools the base's own tests use —
a good start for a new lab's own tools repository.

**Three kinds of source**, loaded in this order (a name already loaded stands in for a later one of the same name):
this machine's folders (`tool_folders`), the git repositories on Settings → Tools, and the sources **that come with
MISTER PLIS** — the basic tools (`bundled-tools.toml`: a release brings them, a server running from a git checkout
fetches them itself at the listed tag). A lab can switch a
bundled source off (Settings → Tools, or `[tools] bundled_off` in its lab file). A bundled source's packages must be
among MISTER PLIS's own.

**Publishing a source for other labs:** make its repository public, fill in the manifest's `description`,
`maintainer`, `homepage` and `license`, and ask whoever keeps a **tool catalogue** to list it — a JSON file
(docs/FORMATS.md §16) any lab can point Settings → Tools → *Browse a catalogue* at. A lab adds it from there switched
off and pinned, like any source that isn't its own.

## The 60-second version

1. In your clone of the tools repository, copy `_template.py` to `my_tool.py`.
2. Edit `id`, `name`, the inputs and the `run` function.
3. Point a local MISTER PLIS at your clone (`tool_folders = ["/path/to/MISTER_PLIS-tools"]` in its `config.toml`),
   run `./scripts/dev.sh` and open <http://localhost:8000>. It reloads when you save.
4. Commit and push the tools repository. On the lab server: **Settings → Tools → Tool sources → lab → Check →
   Update**, then restart when it asks.

```python
from mister_plis.toolkit import Tool, ToolError, inputs as I, outputs as O

tool = Tool(
    id="od-to-cells",
    name="OD600 → cells/mL",
    category="Calculators",
    icon="calculator",
    description="Estimate E. coli cell density from OD600.",
    live=True,                       # recompute as the user types
    inputs=[
        I.Number("od", "OD600", default=0.5, min=0),
        I.Number("factor", "Cells per OD unit", default=8e8),
    ],
)

@tool.runner
def run(p, ctx):
    return O.Metric("Cell density", p.od * p.factor, unit="cells/mL", highlight=True)
```

`p` holds the parsed inputs (`p.od` or `p["od"]`). `ctx` gives you progress, logging, output
files and subprocesses. Raise `ToolError("message")` for problems the user can fix — they see
the message, not a traceback.

## Tool options

| Option | Meaning |
|---|---|
| `id` | URL-safe name, e.g. `"image-converter"`. Keep it stable — links to old results use it. |
| `name`, `description`, `category`, `icon`, `tags` | What people see. `tags` help the sidebar search. |
| `live=True` | Re-run on every change (calculators). Live runs aren't listed under Jobs. |
| `protocol=True` | An "Add to protocol" button: people collect several results (from any tool with it) and print them on one PDF. |
| `@tool.label` | Reagent labels (needs `protocol=True`): each result added to the protocol becomes a label, and **Labels** under the protocol prints them all on one strip of tape for the lab's Brother P-touch, half-cut between labels. The function gets `p` and returns the default text, e.g. `{"name": "NaCl", "detail": "150 mM"}`; person and date are filled in, and everything can be edited before printing. |
| `background=True` | Long jobs: the page shows progress and people can leave and come back. |
| `max_concurrent=1` | Queue extra jobs, e.g. one GPU render at a time. |
| `submit_label` | Text on the run button. |
| `available=lambda: None or "reason"` | Disable the tool with a message, e.g. when a program is missing. |
| `order` | Sorting inside the category (lower first). |

## Inputs (`inputs as I`)

Every input takes `name`, `label`, `default`, `help`, `required` and `show_if`.

| Input | Value in `p` |
|---|---|
| `I.Number(name, label, min=, max=, step=, unit="mL")` | `float` (or `None` if empty and `required=False`) |
| `I.Number(..., units=["M", "mM", "µM"], default_unit="mM")` | number + a unit dropdown; the choice is in `p.<name>_unit` |
| `I.Integer(...)` | `int` |
| `I.Slider(name, label, min=0, max=100, step=1)` | `float` |
| `I.Text(name, label, placeholder=)` / `I.TextArea(..., rows=8)` | `str` |
| `I.Select(name, label, options=["a", "b"])` or `options=[("value", "Label")]` | the value |
| `I.Checkbox(name, label)` | `bool` |
| `I.File(name, label, accept=".csv,.xlsx", multiple=False)` | `UploadedFile` (`.path`, `.name`, `.stem`, `.suffix`, `.read_bytes()`) or a list |
| `I.Column(name, label, source="file_input", multiple=False, numeric=False)` | column name(s) of the table uploaded in `source` |
| `I.SampleTable(name, label, source="files", columns=[I.col(...), ...])` | list of row dicts — an editable table, one row per uploaded file (see below) |
| `I.PlateLayout(name, label, source="plate")` | `{"A1": {"role": "standard", "value": 2.0}, "B3": {"role": "sample", "name": "WT", "dilution": 2}, ...}` |
| `I.ImageSpots(name, label, source="picture", radius=15, refresh_on=())` (*1.3*) | `[{"id": "A1", "x": 120.0, "y": 80.0, "r": 15.0, "sample": "WT", "group": "", "row": "A", "col": 1}, ...]` — circles (regions) placed and named on a picture (see below; `row`/`col` only for wells of a grid) |
| `I.Section("Advanced", collapsed=True)` | not a value — starts a new group of inputs |

`show_if={"mode": ["exact", "fit"]}` shows an input only when the input `mode` has one of those
values; `show_if={"advanced": True}` follows a checkbox.

**A link can fill the form in:** `/tool/<id>?<input>=<value>` (and `<input>__unit=<unit>` for a number with units)
sets those inputs over what the browser remembers, opens a collapsed section whose input it changes, and is then
dropped from the address. Only plain inputs (number, text, select, checkbox…; not files). The inventory's
**Make a solution** opens Solution & dilution this way, so renaming its `compound`, `new_name`, `mw`, `purity` or
`density` inputs breaks that link (it then hides its button, or leaves out what no longer fits).

### Arranging files: `SampleTable` and `@tool.suggest`

Instruments rarely name files consistently, so tools that take many files show a table where
people fix sample names, replicates, roles (sample / blank / ignore), dilutions… before running.
The tool fills it from the uploads:

```python
tool = Tool(..., wide=True, inputs=[
    I.File("spectra", "Spectra", accept=".asc,.txt", multiple=True),
    I.SampleTable("samples", "Samples", source="spectra", columns=[
        I.col("file", "File", "readonly"),
        I.col("role", "Role", "select", ["sample", "blank", "ignore"]),
        I.col("sample", "Sample name"),
        I.col("dilution", "Diluted ×", "number"),
    ]),
])

@tool.suggest("samples")
def suggest(files, params):          # called whenever the uploads change
    return [{"key": f.id, "file": f.name, "role": "sample", "sample": f.stem, "dilution": 1} for f in files]
```

Column kinds: `text`, `number`, `select`, `checkbox`, `readonly`, `image` (a `data:` URL, e.g.
`toolkit.data_url(png_bytes)`). Every row needs a unique `key`; edits survive adding more files.
The suggester also gets the other form values in `params`; list the inputs it depends on in
`SampleTable(..., refresh_on=("letter_at",))` and changing one re-reads the files (replacing the rows).
`wide=True` puts the form across the page so the table has room. `PlateLayout` works the same way:
a suggester returning `{"values": {"A1": 0.32, ...}}` shows the readings in the wells.

### Circles on a picture: `ImageSpots` (toolkit 1.3)

For tools that measure areas of an image (wells, leaf discs, leaves): the tool shows a picture made from the upload and
suggests circles; people move them (drag), resize them (drag the handle, or type a radius), add them (double-click, or
**Add circles**), delete them (Delete), select several (drag across the picture, or click a sample in the legend) and
name them — one name for the selection, or several, one per row, column or circle, like the plate layout. Layouts can be
saved in the browser and loaded again.

```python
I.ImageSpots("spots", "Spots", source="image", radius=12, refresh_on=("detect",)),

@tool.suggest("spots")
def suggest(files, params):
    return {"images": [{"label": "Fm", "src": data_url(png)}], "width": 640, "height": 480,
            "spots": [{"id": "A1", "x": 161, "y": 157, "r": 18, "sample": "WT", "group": "left"}],
            "note": "24 discs found"}
```

`x`, `y` and `r` are in the picture's pixels (`width` × `height`); `"image": data_url` instead of `"images"` gives one
picture (with several, people choose which to see). Circles with a `row` ("A", "B"…) and a `col` (1, 2…) are wells
of a grid: with `"grids": [{"group": "left", "title": "Left chamber", "rows": 5, "cols": 3}]` they are also shown as
plates beside the picture (the circles of each `group` on its plate) and named exactly like a plate layout; the other
circles are listed beside it. A circle without a sample name is a sample of its own (named like the circle). New uploads, a change of an
input in `refresh_on` and **Suggest again** replace the circles with new suggestions; the circles aren't remembered
between visits (they belong to one picture), but a result opened again keeps its own.

## Outputs (`outputs as O`)

Return one output, a list, or a plain value (a `str` becomes Markdown, a DataFrame a table, a
plotly/matplotlib figure a plot, a PIL image an image).

| Output | Shows |
|---|---|
| `O.Metric(label, value, unit="", help="", highlight=False)` | a big number card (click copies it) |
| `O.Markdown(text)` | formatted text, tables, links |
| `O.Alert(text, level="info" \| "success" \| "warning" \| "error")` | a callout |
| `O.Table(df, title=, max_rows=500, download="name.xlsx")` | sortable table with an Excel download. Every result gets one **PDF** button that prints the whole result — who ran it, when, the settings, then every metric, table, text, chart and picture in order |
| `O.Plot(fig, title=)` | interactive plotly chart with PNG/SVG export (matplotlib → image) |
| `O.Image(pil_image_or_path, title=, filename=)` | image preview + download |
| `O.File(path_or_bytes, label=, primary=True)` | a file card with a download button; the tool's workbook (a primary `.xlsx` next to other results) is an **Excel** button beside **PDF** above the result instead |
| `O.Video(path)` | video player |
| `O.Text(text, title=)` | monospace text with a copy button |

## The `ctx` object

| | |
|---|---|
| `ctx.out("result.xlsx")` | a path to write an output file to (when returned, it's renamed `<date>_<user>_<keyword>_result.xlsx`) |
| `ctx.tmpdir` | scratch folder for this run |
| `ctx.progress(0.4, "Fitting sample 4/10")` | progress bar (`None` = spinning) |
| `ctx.log("…")` | a line in the job log |
| `ctx.run(["program", "arg"], on_line=fn)` | run an external program; output goes to the log; cancel kills it |
| `ctx.cancelled` | `True` once the user pressed Cancel |

**Where `run` runs (from 0.17.0).** A job kept in the history runs in a **process of its own**, started for it: the
tool is loaded there again from its folder, runs, and its results are written into the job folder; live calculator
runs stay in the server. So `run` must get everything from `p` and `ctx` (and the toolkit's helpers: `tool_setting`,
`tool_data_dir`…): a module-level variable set by a `@tool.suggest` or a `Button` action in the server isn't there,
and what `run` changes in memory doesn't reach the server. It has none of the server's tokens, and with `job_user` it
runs as another user of the computer (docs/DEPLOY_LINUX.md). What it prints goes to the server's log. An `O.HTML`
result can't run scripts: the pages allow none that aren't the app's own files.

## Helpers in `mister_plis.toolkit`

`read_table(path, sheet=None, decimal=".", skiprows=0)` loads CSV/TSV/Excel/JSON (delimiter
guessed) · `excel_sheets(path)` · `zip_files(paths, dest)` · `write_workbook(path, {"Sheet": df}, notes)`
for a formatted multi-sheet .xlsx with a Method sheet · `fmt(number)` for 4 significant digits ·
`PALETTE` — the colour-blind-safe series colours used by all plots.

## Settings of a tool (toolkit 1.1)

When a tool needs something set up on the server — where a program is installed, say — it declares it, and the lab
sets it on **Settings → Tools → Settings of the tools**. The settings are the same inputs a form uses (`I.Text`,
`I.Select`, `I.Checkbox`, `I.Number`…), lab-wide and kept for this server (`<data>/tool-settings/<tool id>.json`).
`settings_status` is one line shown under them, recomputed when the tab is opened and on **Check**; translate it with
`tr` (it is shown as it is).

```python
from mister_plis.toolkit import Tool, find_program, tool_setting, tr, inputs as I

CANDIDATES = ["/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender"]

def find_blender():
    return find_program("blender", CANDIDATES, configured=tool_setting("blender-render", "program"))

tool = Tool(
    id="blender-render", ...,
    settings=[I.Text("program", "Blender program", placeholder=CANDIDATES[0],
                     help="Leave empty to look in the usual places.")],
    settings_status=lambda: tr("Found: {path}", path=p) if (p := find_blender()) else tr("Blender was not found on the server."),
    available=lambda: None if find_blender() else "Blender was not found. Set where it is on Settings → Tools.",
)
```

In `run(p, ctx)`, `ctx.setting("program")` reads it too. A setting is for the server; what one person prefers stays in
the form (forms remember their last inputs per browser). Export and printing (number format, plot PNG size, the label
printer) are the base's, the same for every tool, on Settings → Exports & printing; `pref(...)` reads the per-browser
ones. The manifest of a source that uses settings asks for `requires_toolkit = ">=1.1,<2"` — or, to keep working on an
older MISTER PLIS too, import `tool_setting` in `try: … except ImportError:` and pass `settings=` only when it is there
(as the lab's Blender render does); then `">=1,<2"` stays.

## What a tool needs to run (toolkit 1.2)

A tool that needs something particular of the computer it runs on says so: `Tool(..., needs=("gpu",))`, or
`("program:blender",)`. It is recorded with each job (`job.json` → `tool.needs`). Every job runs on the server (since
0.19.0; from 0.11.0 to 0.18.0 such a job could go to another computer, a "worker"), so the tool's own `available` check
is what says whether this server can run it: return a reason there when the program isn't found. A source that sets
`needs` asks for `requires_toolkit = ">=1.2,<2"` — or passes it only on toolkit 1.2 and newer (`TOOLKIT_VERSION`), as
Blender render does.

## The toolkit API (`TOOLKIT_API = 1`, version 1.3)

A tool may import **only** `mister_plis.toolkit`, and only the names listed here (they are its `__all__`). Tools will
live in their own repositories, so everything else in `mister_plis` is internal and may change. A tools repository
checks this with a test of its own (`tests/test_boundary.py` in `MISTER_PLIS-tools`; here, `tests/test_tool_boundary.py`
checks the test tools). Shared helpers inside a tool source are imported relatively: `from ._spectra import read_xy`.
A source whose manifest asks for another `requires_toolkit` than this base's toolkit version is not loaded, with a
clear message on Settings → Tools. The version is `TOOLKIT_VERSION` ("1.3"): API 1 plus the additions marked *1.1*,
*1.2* and *1.3* (`inputs.ImageSpots`). A source that uses them asks for `requires_toolkit = ">=1.1,<2"` (then an older MISTER PLIS refuses it with that
message instead of failing on its tools); `">=1,<2"` keeps matching.

| Name | What it is |
|---|---|
| `TOOLKIT_API`, `TOOLKIT_VERSION` | this API's version (1), and which additions to it are here ("1.3") |
| `Tool`, `Params`, `RunContext` | the tool definition, the parsed inputs (`p`), the run context (`ctx`); `Tool(needs=...)` is *1.2* |
| `inputs`, `outputs`, `Input`, `Section`, `UploadedFile`, `Output`, `coerce_outputs` | form fields and result types (`inputs as I`, `outputs as O`); `inputs.ImageSpots` is *1.3* |
| `ToolError`, `Cancelled` | a message for the person / the run was cancelled |
| `tr`, `tn`, `trc` | translated texts (see *Polish translation*); `trc(context, text)` when one English word has two meanings |
| `pref` | a setting of whoever runs the tool, e.g. `pref("decimal")` |
| `fmt`, `md_escape`, `alphabetical_key` | 4 significant digits; names people typed, inside Markdown; sorting names people pick from a list |
| `read_table`, `excel_sheets`, `TABLE_SUFFIXES` | reading tables |
| `write_workbook`, `zip_files`, `safe_filename`, `human_size` | writing results |
| `figure_to_png`, `data_url` | a matplotlib figure as PNG; a small picture inside JSON (e.g. a SampleTable preview) |
| `PALETTE`, `SEQUENTIAL`, `DIVERGING` | the plot colours |
| `tool_data_dir(name)`, `tool_data_file(name, filename, legacy="")` | where a tool keeps what the lab saves with it (saved compounds, lab methods), shared by everyone. Never use the server's data folder directly. Read and write it with `encoding="utf-8"` (Windows otherwise uses its code page, and "MgCl₂" can't be saved or read back). |
| `find_program(name, candidates=(), configured="")`, `which(program)` | an external program on the server: `configured` (a tool's setting, *1.1*) wins, then `<name>_path` in config.toml (e.g. `blender_path`), then the candidates, then the PATH |
| `tool_setting(tool_id, name)` (*1.1*) | the value of a tool's own setting (below); `ctx.setting(name)` is the same for the tool being run |

The lab's tools repository has helpers worth reusing: `_spectra.py` (reading two-column spectra, blank subtraction,
normalisation, Gaussian fits, mean ± SD bands, marker lines, crosshair), `_stats.py` (t-test / ANOVA + Tukey /
non-parametric, dot plots), `_scalebar.py`, `_curves.py` (standard curves with inverse, residuals, LOD/LOQ),
`_assays.py` (the colorimetric methods) and `_units.py`.

## Plots

Figures automatically use the lab theme (fonts, colours, dark mode). Use colours from `PALETTE`
in order if you set them by hand, and avoid two y-axes — use two plots or subplots instead.

## Polish translation

Write the tool in English. The page shows it in Polish from the catalogue in the tool source's
`locale/pl.py` (a dict `PL`; the manifest's `locale` names it) — add your labels, help texts, option names, result titles, column names
and messages there (`"English": "Polski"`). Sentences built with values are matched as patterns:
an f-string `f"Weigh {mass} of {name}"` is translated by the entry `"Weigh {0} of {1}": "Odważ {0} {1}"`
(placeholders numbered in order; the values are translated too when they are entries themselves).
Anything missing just stays in English. When a sentence is glued together from pieces, translate the pieces
in the tool with `tr` / `tn` from `mister_plis.toolkit`:
`tn(n, "{n} sample", "{n} samples")` — the Polish entry `"{n} sample|{n} samples"` has three forms
(`"{n} próbka|{n} próbki|{n} próbek"`). The base's own texts win when a source has the same key.

A `Select(..., sort=True)` keeps its options alphabetical in whichever language is shown.

**Files are always English.** A tool whose runs are kept (not `live`) always runs in English, so its result files
and the job's record are English. Its results are translated when someone with a Polish interface looks at them. The
pieces it translated with `tr` / `tn` / `trc` while running are remembered with the job, so sentences glued from
them come back in Polish too. Live calculators aren't stored, so they run in the language of whoever is looking.

## Dependencies

Add new packages to the tool source's `requirements.txt`. When the source is updated on the server and that file
changed, the server first checks with a dry run (`pip install --dry-run` against its own installed versions,
`mister_plis/pins.py`) that nothing already installed — MISTER PLIS's own packages and anything else in its
environment — would change. Only then does it install them. If something would change, it installs nothing and shows
the packages.

They are installed **with the instance, not into MISTER PLIS's own Python**: `<data>/tool-packages/<source name>/`
(only what the app's environment doesn't have already). The tools import them as usual; the app's own packages come
first. An instance moved to another computer, or a new Python after an update, rebuilds them at its next start.

## Tips

- Keep heavy imports (e.g. `torch`) inside `run()` so the app starts fast.
- A tool that fails to import doesn't take the app down — it shows a warning on the home page
  with the traceback.
- Results are kept for 30 days and uploads for 3 days (`config.toml` changes this).
