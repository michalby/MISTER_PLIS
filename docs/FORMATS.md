# On-disk formats

This file describes every format MISTER PLIS writes to disk.

- **v0** is the format as of tag `v1-final` / branch `release/v1` (2026-11-07), before the reorganisation
  ([reorg/README.md](reorg/README.md)). It was written from the code, not from memory.
- Later phases add **v1** sections (job v1 in P2: §9–10; backup v1 in P3) and must keep a reader for every v0
  format below.
- Frozen v0 examples made by the real code live in `tests/fixtures/jobs_v0/` and `tests/fixtures/backup_v0/`.
  They are read by `tests/test_formats_v0.py`.

Paths are relative to the **data folder** (`data_dir`; default `<repo>/data`; on the Mac Studio,
`~/Library/Application Support/MISTER PLIS/MISTER_PLIS/data`) unless they start with `<backup>` or `<repo>`. A relative
`data_dir` is relative to the instance's folder (`MISTER_PLIS_HOME`; without it, `<repo>`, as before).

## Conventions shared by every v0 store

- JSON files are written to `<name>.tmp` (or `.<name>.tmp`) and then renamed into place, so a reader sees the
  old file or the new one, never half a file. Readers treat a missing or unreadable file as empty or default.
- Times are Unix seconds (`time.time()`, a float or an int) unless a field is named `*_date` (then `yyyy-mm-dd`).
- A person is a free-text name from the browser's `name` cookie, cut to 60 characters. Names merged on System &
  updates → People are rewritten in place (see `people.json`).
- **Job id:** `YYYYmmdd-HHMMSS-xxxxxx` (local time, then 6 hex digits), matched by
  `^\d{8}-\d{6}-[0-9a-f]{6}$`.

---

## 1. Jobs — `jobs/<job id>/` (v0)

Written by `mister_plis/jobs.py` (`Job.save_meta`, `JobManager`) for every tool whose runs are kept in history
(`Tool.history`, true unless `live=True`).

```
jobs/<job id>/
    meta.json          the record (below)
    out/               result files; every name is "<date>_<person>_<keyword>_<name>" (parts left out when empty)
    tmp/               the tool's scratch folder (ctx.tmpdir); not removed after the run
```

Live calculator runs (`live=True`) go to `live/<job id>/` and are never saved with a `meta.json`. They are
deleted after about an hour. Jobs are deleted after `job_retention_days` (30) by the hourly cleanup, except
those still waiting for their backup.

### `meta.json` fields

| Field | Type | Meaning |
|---|---|---|
| `id` | str | job id |
| `tool_id`, `tool_name` | str | the tool's id and English name at run time |
| `user` | str | who ran it (may be empty) |
| `keyword` | str | the optional file-name keyword (≤ 60 chars) |
| `title` | str | optional title (≤ 120 chars), can be changed later |
| `backed_up` | float \| null | when its files were copied to the backup folder |
| `parent` | str | the job whose form this run started from (a re-run), or "" |
| `status` | str | `queued`, `running`, `done`, `failed`, `cancelled`; `interrupted` is set when the server restarted mid-run |
| `created`, `started`, `finished` | float \| null | times |
| `progress` | float \| null | last progress (0–1) |
| `message` | str | last progress message, **in English** (translated when shown) |
| `error` | str | the message for the person, **in English**; for crashes `"<ExceptionType>: <text>"` |
| `traceback` | str | for crashes only |
| `params` | object | the raw form values as the browser sent them (upload ids for file inputs, rows for tables…) |
| `files` | object | input name → `[{"id": <upload id>, "name": <file name>}]`; the uploads themselves are deleted after `upload_retention_days` (3), so the ids go stale |
| `outputs` | list | the rendered results (below) |
| `n_outputs` | int | `len(outputs)` |
| `report` | str \| null | `/api/jobs/<id>/report.pdf` when the result is printable |
| `log` | list[str] | the last 2,000 log lines |

The record does **not** include the person's settings (`prefs`: language, decimal mark…).

**Language.** Up to commit `7c1c23a`, the texts inside `outputs` were translated into the runner's language when
the job finished, so a v0 record can be Polish. From the next commit on (2026-11-07), jobs kept in the history
run in English, so their `outputs`, files and messages are English. Two fields come with that:

- `phrases`: `{"pl": {english: polish}}`, the pieces the tool translated while running (up to 3,000 per
  language). They are used to show the result in Polish (`i18n.phrases`, `outputs.translate_output`).
- In `outputs`, `html` and `alert` items also carry `md`: the Markdown as the tool wrote it, re-translated when
  shown.

Readers must accept records with or without these fields.

### `outputs[]` — the rendered results

Each item has a `kind`. URLs point at `/api/jobs/<id>/files/<path inside the job folder>`.

| `kind` | Fields |
|---|---|
| `metric` | `label`, `value` (formatted text), `raw` (the number or text), `unit`, `help`, `highlight` |
| `html` | `html` (from `O.Markdown` or `O.HTML`) |
| `alert` | `level` (`info`/`success`/`warning`/`error`), `html` |
| `text` | `text`, `title` |
| `table` | `title`, `columns`, `numeric` (per column), `rows` (**only the first `max_rows`, default 500**), `total_rows`, `printable`, and optionally `download: {url, name}`: the full table as `.xlsx` or `.csv` in `out/` |
| `plot` | `title`, `height`, `figure` (Plotly JSON). **There is no image file**: browsers draw it. |
| `image` | `title`, `caption`, `url`, `name`, `size` |
| `file` | `url`, `name`, `label`, `description`, `size`, `primary` |
| `video` | `title`, `url`, `name`, `size` |

## 2. Uploads — `uploads/<upload id>/<file name>` (v0)

The upload id is 16 hex digits, with one file per folder (`UploadStore`). Folders are deleted
`upload_retention_days` (3) after their last change.

## 3. Backups — `<backup>/<person>/<folder>/` (v0)

Written by `mister_plis/backup.py` (`copy_job`) for jobs that are finished, recorded and old enough
(`backup_after_days`), or at once from "Back up now" or "Clear history → back up first".

```
<backup>/<person or "No name">/<date>_<person>_<keyword> <tool name> (<job id>)/
    <every file and folder of the job's out/, copied as is>
    job-info.json      a copy of meta.json (above)
    job-info.txt       a plain-text summary (below)
```

- The folder name is `safe_filename(f"{job.file_prefix()} {job.tool_name} ({job.id})")`. The job id in brackets
  at the end is how Time Machine finds a backup (`\((\d{8}-\d{6}-[0-9a-f]{6})\)$`).
- A copy is written to `<folder>.partial` and renamed at the end. A `.partial` folder is unfinished.
- After a successful copy, the job's `meta.json` gets `backed_up`.
- **Plots are not in the backup** (only their JSON inside `job-info.json`). Tables are there only if the tool
  made a download file.
- Older backups, or folders copied by hand, may lack `job-info.json`. Time Machine then takes the tool name from
  the folder name and the person from the parent folder.

`job-info.txt` lines, aligned to 11 characters:

- `Tool:`, `Title:` (if any), `Run by:`, `Started:`, `Finished:`, `Job:`, `Keyword:` (if any);
- then `Input files:` (`<label>: <names>`) and `Settings:` (`<label>: <value>`, human-readable, from
  `report.describe_settings`).

## 4. Time Machine — `timemachine/` (v0)

From reorg P4 on, the same folder lives in `<storage>/modules/timemachine/` (moved once, the old one kept as
`timemachine.migrated-<date>`), and is copied into the backup folder, in `<backup>/Time Machine/` (modules/timemachine/MODULE.md).

Written by `mister_plis/timemachine.py` and `tmgit.py`.

```
timemachine/
    .git/                   local git repository; never pushed
    .gitignore              ".*.partial/" and "*.tmp"
    projects.json           {"projects": {"p-xxxxxx": {name, description, color, created, created_by}}}
    <job id>/
        meta.json           a job record in the format of §1 (for kept jobs: the job as it was; see kinds below)
        out/                its result files
        entry.json          Time Machine's own record (below)
    .<job id>.partial/      only while copying
```

### `entry.json` fields

| Field | Meaning |
|---|---|
| `id` | the job id (Time Machine-only entries get a new job id of the same form) |
| `added`, `added_by` | when and by whom |
| `source` | `jobs` (from Jobs & results), `backup` (from the backup folder), `upload` (files added by hand), `task` |
| `source_path` | the folder it was copied from ("" for uploads and tasks) |
| `kind` | `job`, `manual` (files that never were a job), `update` (a new version made of uploaded files), `task` |
| `version_of` | the id of the first version of the lineage, or "" |
| `projects` | list of project ids |
| `note` | free text (≤ 4,000 chars) |
| `title`, `description` | for `manual`, `task` and their `update` versions |
| `assignee`, `done`, `done_by`, `done_with` | for `task` only: `done` is a time or null; `done_with` is the job id of the version that completed it |

Kinds without a real job (`manual`, `update`, `task`) still have a `meta.json` in the §1 format:
- for `manual` and `update`, `tool_id` is "" (or the first version's tool) and `outputs` are `image` / `file` items
  pointing at `/api/tm/<id>/files/out/<name>`;
- for `task`, `finished` is null and there are no outputs.

### History commits

Each change is one commit:

- author: the person's name, email `time-machine@mister-plis.local`;
- subject: a sentence ("Keep Chlorophyll concentration (…) from Jobs & results into “PSI paper”");
- body: trailers, one per line, `Job: <id>` (one or more), `Project: <p-id>` (zero or more) and
  `Action: <start|add|manual|task|version|projects|project|note|title|people|remove|restore>`.

**See history** filters on these trailers.

## 5. Reagent and consumables inventory — `reagents/` (v0)

From reorg P5 on, the same folder is `<data>/modules/inventory/` (moved once, the old one kept as
`reagents.migrated-<date>`).

Written by `mister_plis/reagents.py` and `tidy.py`.

```
reagents/
    settings.json           {"push": bool, "auto_minutes": 0|15|60|240, "synced_at": float, "pushed_at": float}
    repo/                   a git clone of reagents_repo (github.com/smith-lab/inventory), branch reagents_branch
        wykaz_odczynnikow_kompletny.xlsx   master workbook; sheet "reagents" (key label_no), sheet "columns"
                                           (column | type | values | label_pl | label_en | group | description_pl),
                                           sheet "storage_categories", others kept untouched
        wykaz_odczynnikow_kompletny.csv    the "reagents" sheet as CSV, rewritten on every change
        consumables.xlsx / consumables.csv the consumables workbook (sheet "consumables", key item_no, own "columns" sheet);
                                           created empty by the server if missing
        mister_plis.json                   how the reagents are shown: workbook, sheet, csv, key, title {pl, en},
                                           quick, list, hidden, and (optional) pdf: the printed list
                                           {"source": list|chosen, "columns": [...], "filters": bool,
                                            "size": normal|large}
        mister_plis_consumables.json       the same for the consumables
        info/<YYYYmmdd-HHMMSS>-<4 hex>.json  a note from the lab (below)
        AGENTS.md                          the repository's own rules (not written by MISTER PLIS)
    tidy/
        settings.json       {"model", "schedule": off|daily|weekdays, "at": "HH:MM", "apply": none|checks|all}
        last_run.json       the newest tidy-up run with its proposals and problems
        runs.json           summaries of the last 60 runs
```

- **A note from the lab (`info/*.json`)** has the fields `id`, `text`, `user`, `created`, `reagent`,
  `reagent_name`, `page` and `status` (`new` / `done`). It may also have:
  - `consumable`, `consumable_name`;
  - `done_by`, `done_at`;
  - `agent_note`: the tidy-up's question or remark.

  From commit `64e1771` on, `created` keeps microseconds (a float); before that it was whole seconds.
- **Commits:** every change is one commit by the person (email `reagents@mister-plis.local`), with trailers
  `Reagent: <label_no>` or `Consumable: <item_no>`, `Info: <id>` and `Action: <add|edit|fields|info|tidy|…>` (`tidy`: changes made by the tidy-up). Merges from
  GitHub are committed as "Merge changes from GitHub".

## 6. Lab notebook — `notes/` (v0)

From reorg P6 on, the same folder is `<data>/modules/notebook/` (moved once, the old one kept as
`notes.migrated-<date>`).

Written by `mister_plis/notes.py`.

```
notes/
    settings.json   {"folders": [vault folders shown], "synced_at": float, "auto_minutes": 0|15|60|240}
    vault/          a partial, sparse git clone of notes_repo (notebook), read-only
```

## 7. Small stores in the data folder (v0)

| File | Written by | Content |
|---|---|---|
| `feedback.json` | `feedback.py` | list of `{id (12 hex), kind: bug\|inconvenience\|idea, text, user, page, where, created, status: new\|done}` (at most 5,000); from 0.15.0 also `account` (the sender's account id, §18) |
| `people.json` | `people.py` | `{"merged": {old name casefolded: kept name}, "log": [up to 500 merge records]}` |
| `lab_settings.json` | `backup.py` | `{"backup_dir": str, "backup_after_days": 0\|1\|3\|7, "lab_name": str}`; `lab_name` from November 2026 (Settings → Server & updates; empty or missing = `lab_name` in config.toml). From the lab setup (§12) also `"language": ""\|"en"\|"pl"` (for a browser that hasn't chosen; "" = English), `"keep_days"`, `"keep_uploads_days"` (0 or missing = config.toml's `job_retention_days` / `upload_retention_days`, which win when they are set there). From November 2026 (R10) `"services": {"model": "http://…", "facility": "http://…"}` — the addresses of the computers this instance talks to; a name without an address is left out. **No longer set from 0.19.0**: still read and kept (the inventory takes `model` over once as its own `ollama_url`). Missing keys read as these defaults. From 0.12.0 also `"server_names": [str]` (other names the server answers to, lower case; `["*"]` = any; no longer set from 0.19.0 — `server_names` in config.toml instead — but still read and kept) and `"max_upload_mb": int` (0 or missing = 2048); older versions ignore both. |
| `tool-settings/<tool id>.json` | `toolsettings.py` | from November 2026 (toolkit 1.1): `{"format": 1, "values": {name: value}, "changed_by": str, "changed_at": float}`, a tool's own settings for this server (Settings → Tools); kept when the tool is gone |
| `label_printer.json` | `labels.py` | `{"address", "tape_mm", "hires", "half_cut", "auto_cut", "chain", "logo"}`; `"logo"` (bool, from November 2026): whether the lab has a logo — a file without it is from before labs chose their own, and is given its old logo once at start (`Printer.keep_old_logo`) |
| `tool-packages/<source>/` | `toolsources.py` | from November 2026 (R6): the packages a tool source's `requirements.txt` adds, installed with `pip install --prefix` (its `site-packages` is appended to `sys.path` when the tools load) and `.mister-plis.json` = `{"requirements_sha256", "python": "3.12", "platform", "machine", "installed_at"}`. Rebuilt whenever that doesn't match (an instance moved, another Python); never in a transfer. Packages a source found in the app's own environment before this are used from there |
| `label_logo.png` | `labels.py` | the lab's logo for its labels (PNG, at most 256 kB); no file = no logo |
| `git_branch.json` | `updater.py` | `{"branch": str, "switched": float}`: the branch chosen under Run another branch (wins over `git_branch` in config) |
| `auto_update.json` | `updater.py` | `{"mode": off\|night, "last_day": "YYYY-mm-dd", "last": {at, ok, result}}` |
| `assays.json` | the lab's tool `_assays.py` (now in `MISTER_PLIS-tools`) | the lab's saved assay methods: name → method dict (see the module's docstring) |
| `compounds.json` | the lab's tool `molarity.py` (now in `MISTER_PLIS-tools`) | the lab's saved compounds: name → molar mass (g/mol) |
| `tool-data/<tool>/…` | `toolkit.tool_data_dir` | from P1 on: what tools save; `tool-data/molarity/compounds.json` and `tool-data/assay-reagents/assays.json` replace the two files above (copied once on first use; the old files stay) |

## 8. Outside the data folder (v0)

- `<repo>/config.toml`: per-machine settings (see `config.example.toml`); it is not data.
- `<repo>/logs/server.log` and the Mac app's `launcher.log`, `server.pid`: logs.
- Browser-side only, never on the server: cookies (`name`, `lang`, `theme`, `decimal`, `xlsx_numbers`,
  `plot_scale`, `remember_inputs`), and `localStorage` (form values, column choices, plot colours, protocol
  contents, notes panel width).

---

# v1 formats (reorg phase P2, 2026-11-07)

## 9. The storage folder (v1)

`storage_dir` in config.toml, or the folder chosen on Settings → Jobs & backup (kept in
`<data>/storage.json`: `{dir, chosen_at, by, previous, moved}`), else the data folder itself. It holds:

```
<storage>/
    jobs/
        index.json                  the list of jobs (a cache, rebuilt from the folders when missing or stale)
        .migrated-from-v0.json      only after jobs were moved in from the data folder: what was moved, when
        <job id>/                   one job (below)
    tool-data/<tool>/…              what tools save for the lab (toolkit.tool_data_dir)
```

Live calculator runs stay in `<data>/live/`, and uploads in `<data>/uploads/`. When the storage folder is changed
on the page, `jobs/` and `tool-data/` are copied there and checked, and the old ones are renamed
`<old storage>/jobs.moved-<date>` and `tool-data.moved-<date>`. When a storage folder of its own is set in config,
the data folder's v0 `jobs/` are copied in at the next start, and the old folder is renamed
`<data>/jobs.migrated-<date>`.

## 10. A job folder (v1)

```
<storage>/jobs/<job id>/
    job.json        the record (below)
    meta.json       only in folders from before P8: a v0 record (or a copy of job.json, written beside it from P2 to
                    P8 so release/v1 could still read the job). Read when there is no job.json; job.json wins.
    inputs/<input name>/<file>   copies of the uploaded files (up to 200 MB per job in total)
    out/            result files, as in v0
    tables/NN_<title>.xlsx       every result table in full (or .csv when it exceeds Excel's limits: never both)
    tmp/            the tool's scratch folder
```

A v0 folder (only `meta.json`) is read as it is. At the first start of P2 it gets a `job.json`, and its
`meta.json` stays. From P8 on, only `job.json` is written, so a job made since can't be opened by `release/v1`.

### `job.json`

`job.json` holds **every v0 field of §1 with the same meaning**, so a v0 reader still reads it, plus:

| Field | Meaning |
|---|---|
| `format`, `format_version` | `"mister-plis-job"`, `1` |
| `record` | `true` |
| `tool` | `{id, name, source, source_url, commit}`: `source` is the tool source's name (`"lab"`…) and `commit` its commit; records written before P7 say `"builtin"` and the base's commit. From November 2026 (toolkit 1.2) also `needs` (a list, e.g. `["gpu"]`) when the tool says what a computer must have to run it; missing = nothing |
| `base` | `{version, commit}` of MISTER PLIS that ran it |
| `prefs` | the settings of whoever ran it (`lang`: the language of *their interface*, not of the record, which is English; `decimal`, `xlsx_numbers`, `name`…) |
| `inputs` | input name → `[{id, name, size, sha256, kept, path}]`: `path` is inside the job folder when `kept`; above 200 MB in total nothing is copied (`kept: false`) |
| `phrases` | see §1 "Language" |
| `worker` | 0.11.0 to 0.18.0: the name of the computer that ran it, when a worker did (§17); missing = the server. Still read and shown; no longer written |
| `account` | from 0.15.0: the id of the account that ran it (§18); missing = run before accounts, or with sign-in off. `user` stays its person's name |

In `outputs`, a `table` item also has `file` (`tables/…`, the whole table), and its tool-made `download`, if
any, has `"derived": "table"` (the same data again).

`backed_up` is still a time (float) or null. P3 turns it into an object.

### `index.json`

```json
{"format": "mister-plis-job-index", "format_version": 1, "written": 1794049729.9,
 "jobs": {"<job id>": {"id", "tool_id", "tool_name", "user", "keyword", "title", "status", "created", "started",
                       "finished", "backed_up", "parent", "error", "traceback", "n_outputs", "report",
                       "result_files": [...], "upload_ids": [...], "modules": {}, "mtime": <job.json's mtime>}}}
```

At each start, a row whose `mtime` differs from its `job.json` is made again, rows of missing folders are dropped,
and folders without a row are added. A folder whose record can't be read is skipped and listed under
Settings → Jobs & backup.

## 11. Backups (v1, reorg phase P3)

The same place and name as in v0 (`<backup>/<person or "No name">/<date>_<person>_<keyword> <tool> (<job id>)/`,
D7). It is written to `<folder>.partial`, renamed when complete, then checked. From R2 (docs/PREP_PLAN.md) the
person's folder and file names are also made safe for Windows and SMB shares (`toolkit.safe_filename`: a name Windows
keeps for itself, like `Con` or `nul.txt`, gets a `_` after its stem); folders written before keep their names: each job
remembers its backup's folder, and the catalogue finds a backup by the `(<job id>)` at the end of its name. An older backup of the same job is
replaced only after the new one is complete.

```
<folder>/
    README.md              everything about the job (English): who, when, tool and versions, input files, settings,
                           every result in order (tables: first 20 rows), links to the files below
    results.xlsx           sheet "Summary" (Item | Value | Unit: the job, then every metric), one sheet per result table
                           (in full, from the job's tables/), sheet "Plot data" (Plot | Trace | x | y | ± error)
    tables/NN_<title>.csv  only for a table too big for Excel (rows > 1,048,576 or columns > 16,384): then it is
                           not in results.xlsx (never both)
    plots/NN_<title>.html  each plot, interactive, offline (uses plots/plotly.min.js next to it)
    plots/NN_<title>.png   the same as a picture, only when kaleido (with Chrome) is installed on the server
    report.pdf             the result as printed from its page (absent when nothing in it is printable)
    files/…                the tool's own result files (the job's out/), except downloads that only repeat a table
    mister-plis/
        README.txt         what this folder is for
        job.json           the job's record (job v1, §10)
        manifest.json      below
        inputs/…           the job's kept input files
        tables/…           the job's full tables (.xlsx)
        out/…              the tool's downloads that only repeat a table (`"derived": "table"`)
```

`NN` is the output's position in the result (01, 02…), so a table's sheet, its file and the README's section match.

### `manifest.json`

```json
{"format": "mister-plis-backup", "format_version": 1, "job_id": "…", "written": 1794058713.1,
 "base": {"version": "…", "commit": "…"},
 "files": [{"backup": "files/…_results.xlsx", "job": "out/…_results.xlsx", "size": 18234, "sha256": "…"},
           {"backup": "results.xlsx", "job": null, "size": 9100, "sha256": "…"}]}
```

Every file of the backup except the manifest itself is listed. `job` is where the file belongs in the job's folder
(`files/X` → `out/X`; `mister-plis/out|inputs|tables/X` → `out|inputs|tables/X`; `tables/X.csv` → `tables/X.csv`),
or null for files made for the backup (README, workbook, plots, PDF, `mister-plis/job.json` and `README.txt`).
Importing copies each file with a `job` back into place, so `out/` is never stored twice.

### Checking, and when a job may be deleted

`backed_up` in the job's record is `{at, folder, format_version: 1, verified_at}` after a v1 backup was written and
checked (every file: size and SHA-256). Older records may hold a float (v0) or `{…, format_version: 0}` (imported from
a v0 backup).

While a backup folder is set, cleanup deletes a job only if its backup checks out:

- v1: every file's size is checked each time, and the checksums once (and again on **Check the backups**);
- v0: the folder must be there.

A backup that doesn't check out is forgotten (`backed_up: null`), so the job is copied again. If the whole backup
folder is unavailable (a NAS not mounted), nothing is deleted and nothing is forgotten.

### `<backup>/mister-plis-index.json`

The catalogue of every backup, kept so a NAS isn't walked each time:

```json
{"format": "mister-plis-backup-index", "format_version": 1, "written": 1794058713.1, "rows": [...]}
```

Each row is `{id, format: 0|1, folder (relative to the backup folder), person, tool_id, tool_name, user, title,
keyword, created, parent}`. Each time it is used, it is compared with the folder names actually there: new folders
(copied in by hand, say) are read, and folders gone are dropped. Folder times are not used, because copying keeps the
original times. It is ignored when unreadable.

### Importing

- **v1:** every file is checked against the manifest first (a damaged backup is refused), then copied into place,
  with `mister-plis/job.json` as the record.
- **v0:** the folder's files go to `out/`; `job-info.json` (or, without it, the folder's name: tool name and person)
  becomes the record.

Either way the record gets `imported: {from, at, format}` and counts as backed up (to the folder it came from).

**Update old backups** rewrites each v0 backup as v1 in its place. The v0 folder is kept beside it as `… (<job id>).v0`,
which the catalogue ignores.

---

## 12. The lab's setup (from November 2026; docs/LAB_SETUP_PLAN.md)

### `<data>/lab.json`

Written by `mister_plis/labsetup.py`. Missing means a server from before lab files: on its first start it gets one
(`"state": "set_up", "from": "migrated"` when the data folder already holds anything, else `"state": "new"`).

```json
{"format": 1,
 "state": "new" | "set_up" | "skipped",       // new: the pages lead to /setup; skipped: "Skip for now"
 "at": 1762700000.0, "by": "Ada",             // when it was set up (or skipped), and by whom
 "from": "labs/ourlab.toml" | "page" | "migrated" | "https://…",
 "modules": ["…"],                            // only when the lab chose which modules are on (else: all of them);
                                              // `modules` in config.toml wins
 "pending": {"module": {"<id>": {…}}, "tool": {"<tool id>": {…}}},   // a lab file's tables waiting for their module
                                              // or tool to be loaded; removed once applied
 "instance": {"id": "<32 hex>", "created_at": 1762700000.0}}   // from November 2026: made once at a start that finds
                                              // none; a transfer keeps it (the same instance moved), a lab file never
                                              // holds it. A fresh install filled from a backup is a new instance.
```

### The lab file (format 1)

TOML, read by `labsetup.parse` (every section optional; what is left out is not changed). Not stored by the server:
it is applied into the stores above and below. `python -m mister_plis export` writes one from a server's settings.

| Section | Keys | Stored in |
|---|---|---|
| `[lab_file]` | `format = 1` | — (a newer format is refused) |
| `[lab]` | `name` (≤ 60), `language` (`""`, `"en"`, `"pl"`) | `lab_settings.json` |
| `[[tool_sources]]` | `name`, `url`, `branch` (default `main`), `trusted` (default false) | `tool_sources.json` (a source not trusted is fetched, pinned and left off) |
| `[modules]` | `on = "all"` or a list of module ids | `lab.json` → `modules` |
| `[module.<id>]` | the module's own questions (`Module.setup_fields`) | the module's own settings (its MODULE.md) |
| `[jobs]` | `keep_days`, `keep_uploads_days` (1–3650), `max_upload_mb` (from 0.12.0), `storage_folder` (a full path; only while there are no jobs) | `lab_settings.json`, `storage.json` |
| `[backup]` | `folder` (a full path, `""` = none), `after_days` (0, 1, 3, 7) | `lab_settings.json` |
| `[label_printer]` | `address`, `tape_mm` (9, 12, 18, 24), `hires`, `half_cut`, `auto_cut`, `chain`, `logo` (a picture next to the lab file, an `https://` address, or the picture itself as `data:image/png;base64,…` — what a downloaded lab file holds; `""` = none) | `label_printer.json`, `label_logo.png` |
| `[updates]` | `auto` (`"off"`, `"night"`) | `auto_update.json` |
| `[server]` | `names` (0.12.0 to 0.18.0). **Ignored from 0.19.0**, with a note: a name only a proxy gives the server is `server_names` in its config.toml | — |
| `[services]` | `model`, `facility` (November 2026 to 0.18.0). **Ignored from 0.19.0**, with a note: the inventory has its own `ollama_url` | — |
| `[tool.<tool id>]` | the tool's own settings (`Tool(settings=…)`) | `tool-settings/<tool id>.json` |

### `tool_sources.json` on a server from before lab files

Until lab files, a server without `tool_sources.json` used the lab's repository by default. On its first start with
lab files, if `tool-sources/lab/` is a clone, the list is written with that one source (its address and branch read
from the clone, trusted), so nothing changes for it.

---

## 13. A server's transfer (from November 2026; mister_plis/transfer.py, docs/BETA.md §4)

`<folder>/MISTER PLIS <lab> <yyyy-mm-dd HHMM>/`, written as `….partial` and renamed when every file is copied and
checked:

```
manifest.json   {"format": "mister-plis-transfer", "format_version": 1, "created": float, "by": str,
                 "from": {"host", "data", "storage", "version", "commit"}, "lab_name": str, "jobs": int, "bytes": int,
                 "files": {"data/<path>" | "storage/<path>": {"size": int, "sha256": str}}}
data/…          the data folder, without uploads/, live/, tool-sources/, tool-packages/, storage.json, git_branch.json, logs/, the
                storage parts below, and folders set aside (*.moved-*, *.migrated-*, *.before-*, *.replaced-*, *.partial…)
storage/…       jobs/, tool-data/, and each loaded module's storage folder (modules/<id>) that holds anything — also
                when the storage folder is the data folder (they are then not under data/ too)
```

Files are copied as they are, in whatever format they are (v0 jobs stay v0). Bringing one in: every file is checked
first; the server must have no jobs; each top-level item (and each `modules/<id>`) the transfer brings is renamed
`<name>.before-import-<date>` if present; `data/…` goes to the data folder, `storage/…` to the storage folder (the
same folder on a new server); then `lab.json` gets `"state": "set_up", "from": "moved from <host> (<date>)"`, keeping
the lab's `modules` and `pending`.

## 14. The instance's secrets (from November 2026; mister_plis/credentials.py, docs/PREP_PLAN.md R3)

`<instance>/secrets/` (the instance's folder: `MISTER_PLIS_HOME`, else the code folder; ignored by git). Not in the
data or storage folder: **never copied** by a transfer or a backup, never in a lab file. The folder is `0700`, its
files `0600` (on Windows, the user's own permissions).

`secrets/git-credentials.toml` — the git tokens, written by Settings → Server & updates → GitHub access:

```toml
# (a comment saying what the file is)
[[token]]
host = "github.com"
owner = "smith-lab"          # "" = every repository on the host
repo = "inventory"           # "" = every repository of the owner
token = "github_pat_…"
added = "2026-11-11 21:10"   # local time, shown on the page
```

Host, owner and repository are kept in lower case. The most specific entry for a repository wins (owner and
repository, then owner, then host); `MISTER_PLIS_GIT_TOKEN` serves what none matches. An entry without a token or a
host is ignored. Git gets a token through `python -I mister_plis/credentials.py --store <file> get` (git's credential
protocol; username `x-access-token`).

## 15. Versions, the release feed and snapshots (from November 2026; docs/PREP_PLAN.md R5)

**The formats register.** `mister_plis/formats.py`: `WRITES` — the version of each format this MISTER PLIS writes
(job, job index, backup, backup catalogue, lab file, `lab.json`, transfer, tool settings, release feed) — and `READS`,
the oldest and newest it reads. `tests/test_updates.py` fails when a
writer's constant and the register differ. `/api/version` returns `"formats": WRITES`.

**The release feed** (`feed-<channel>.json`, written by `scripts/make_feed.py`; read by `mister_plis/updates.py` from an
`https://` or `file://` address, at most 1 MB):

```json
{"format": "mister-plis-release-feed", "format_version": 1, "channel": "beta" | "stable",
 "releases": [{"version": "0.9.1", "date": "2026-12-01", "notes": "…", "notes_pl": "…",
               "writes": {"job": 1, …},            // formats.WRITES of that version
               "min_reads": {"job": 0, …},         // the oldest version of each format it reads
               "artifacts": {"wheel": {"url": "…", "sha256": "…"}, "docker": "ghcr.io/…:0.9.1"}}]}   // newest first
```

A server lists the releases newer than its own, each saying whether this version could still read what it writes
(`formats.can_read`): going back past a format this version doesn't read is refused.

From 0.16.0 (docs/RELEASES.md): `artifacts` may also have `"lock": {"url", "sha256"}` (the release's
`requirements.lock`), and `docker` should name the image by its digest (`…@sha256:…`). Beside the feed,
**`feed-<channel>.json.sig`**: an SSH signature of the feed's bytes (`ssh-keygen -Y sign -n mister-plis-release`). A
server whose code has release keys (`mister_plis/releasekeys.py`) refuses a feed without a signature by one of them; the
feed format itself is unchanged.

**`[updates]` in `auto_update.json`:** besides `mode`, `last_day`, `last` (§ data folder), `"channel": "beta" |
"stable"` and `"feed": "https://…"` (older files lack them: beta, no feed).

**Snapshots of the lab's settings:** `<instance>/snapshots/<yyyy-mm-dd HHMMSS> <why>/` (next to the data folder; ignored
by git), made before every update (Sync with git, Run another branch, the nightly update) and by hand; the newest 5 are
kept. Each is a transfer (§13) with `"kind": "settings"` in its manifest (a whole server's copy says `"kind": "server"`;
older ones lack it) and only `data/…` files: the data folder as a transfer has it, but of each module only the files at
the top of its folder (its settings), never its copies of repositories or its storage. Restoring one
(`transfer.bring_in_settings`, Settings → Server & updates) is allowed on a server with jobs: it takes only `data/…`
files, renames each file it replaces `<name>.before-restore-<date>`, and the server restarts.

## 16. Tool sources that come with a release, and the tool catalogue (from November 2026; docs/PREP_PLAN.md R7)

**`<data>/tool_sources.json`** gains two optional keys beside `"sources"` (older files lack them; older readers ignore
them): `"bundled_off": ["basic", …]` — the sources that come with MISTER PLIS (`<code>/bundled-tools/<name>/`, each with
its manifest) that this lab switched off — and `"catalogue": "https://…"`, the tool catalogue it browses. The lab file
names both: `[tools] bundled_off = [...]`, `catalogue = "https://…"`.

**`bundled-tools.toml`** (in this repository): `[[source]]` tables with `name`, `url` (`https://`), `tag`, and optionally
`commit` (40 hex digits) — what a release clones into `bundled-tools/` when it is built (`scripts/release.sh`), and what a
server running from a git checkout fetches there itself (from 0.22.0). Such a fetched copy has **`.bundled.json`**:
`{"url": "…", "tag": "…", "commit": "<40 hex>"}`, what it was fetched at; a copy without it came with a release and is
never fetched over. The copy a newer tag replaced is kept as `bundled-tools/<name>.previous/` until the next one.

**A tool catalogue** (any `https://` address; read at most 1 MB, kept for an hour):

```json
{"format": "mister-plis-tool-catalogue", "format_version": 1,
 "sources": [{"name": "plantlab", "title": "Plant lab tools", "description": "…", "url": "https://github.com/…/….git",
              "branch": "main", "maintainer": "…", "homepage": "https://…", "license": "MIT",
              "requires_toolkit": ">=1.1,<2", "tags": ["plants", "imaging"]}]}
```

`name` (small letters, digits, `_`) and an `https://` `url` are required; an entry without them is left out.

## 17. Workers (0.11.0 to 0.18.0; removed in 0.19.0)

Other computers could run jobs for a server from 0.11.0 to 0.18.0. 0.19.0 removed them: every job runs on the server.
It no longer reads or writes the files below; a server that had them keeps them where they are, unused (nothing is
deleted). A job a worker ran still opens, and still says where it ran (`worker` in its `job.json`, §10).

**On the server: `<instance>/secrets/workers.json`** — who may run jobs for it (Settings → Server & updates →
Computers that run jobs). In the secrets folder (§14): never copied, never in a lab file.

```json
{"format": 1, "workers": [{"name": "blender-pc", "sha256": "<sha256 of the token>", "added": "2026-11-12 21:10",
                           "added_by": "Ola"}]}
```

`name`: lower-case letters, digits, `.`, `-` (at most 40). Only the token's hash is kept; the token (`mpw_…`) is shown
once. An entry without `name` or `sha256` is ignored.

**On a worker: `<instance>/secrets/worker.json`** — `{"format": 1, "server": "http://…:8000", "token": "mpw_…"}`,
written by `python -m mister_plis worker --server … --token …` and read when it starts again. **`<data>/worker/`** holds
the server's tool sources as fetched (`tool-sources/<name>/`, each with a `.digest`), their packages
(`tool-packages/<name>/`, as on a server) and the jobs it is running (`jobs/<id>/`, removed when sent). All of it is
rebuilt as needed.

A job a worker ran is a job folder like any other (§10), with `worker` in its `job.json`.


## 18. Accounts and sign-in (from 0.14.0; mister_plis/accounts.py, docs/SECURITY_AUDIT.md §7)

**`<data>/accounts.json`** — who may sign in. Readable by the server's user only. In the data folder, so a transfer
(§13) carries it; left out of the settings snapshots before updates (§15), so going back never brings back a removed
account or an old password. No file, or no account in it: sign-in is off (the server is open, as before 0.14.0).

```json
{"format": 1, "accounts": [{"name": "Anna Kowalska", "role": "admin",
  "password": "scrypt$16384$8$1$<salt, base64>$<hash, base64>",
  "created": 1794600000.0, "created_by": "the first account", "last_sign_in": 1794600300.0, "must_change": false}]}
```

`id` (from 0.15.0; given once to an account made by 0.14.0): 16 hex digits, never changing — stored with every job
its person runs (§10 `account`). `names` (from 0.15.0): the person's earlier names — the account's old names after a
rename, and names attached to it (typed before there were accounts); what was under them was moved to the account's
name. `name`: as on the person's results (at most 60 characters; one account per name, capitals not counting). `role`:
`admin` (may change Settings) or `member`. `password`: never the password itself, only its scrypt hash with its own
salt. `must_change`: the password was given by an admin (a new account, a reset); its person chooses their own at the
next sign-in. An entry without `name` or with another `role` is ignored.

**`<instance>/secrets/sessions.json`** — the browsers signed in: `{"format": 1, "sessions": [{"key": "<sha256 of the
cookie's key>", "name": "Anna Kowalska", "started": …, "seen": …}]}`. In the secrets folder (§14): never copied. A
session not used for 30 days is dropped; signing out, a new password and removing the account end it.

**`<data>/audit.log`** — the activity log: one JSON object a line, `{"at": …, "who": "Anna Kowalska", "what": "signed in",
"from": "192.168.1.30"}`: sign-ins (and failed ones), accounts made and changed, and every change to the lab's settings
(`"what": "POST /api/lab/name"`). Above 5 MB it is renamed `audit.log.1` (the one before is dropped). Not in snapshots.

**`<instance>/secrets/setup-code`** (from 0.13.0) — the setup code (mister_plis/setupcode.py), one line `ABCD-EFGH`;
removed once the lab's first account exists.

**`<instance>/secrets/files-key`** (from 0.18.0) — the key the links to stored files are signed with
(mister_plis/fileorigin.py): 64 hex digits, made once. Never copied; a new one (deleting it) only makes the links pages
hold now stop working. The links themselves are never stored: `<origin>/f/<token>/<file's path>`, the token holding the
folder (inside the storage or data folder) and when it expires (2 hours), signed.
