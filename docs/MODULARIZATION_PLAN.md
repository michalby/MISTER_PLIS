# MISTER PLIS — plan: a modular base, separate tool repositories, portable job storage

*Written 2026-11-07, against commit `64e1771`. This is a plan only: no code has been changed for it.
The current architecture it starts from is described in [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md).*

---

## 0. The target in one picture

```
GitHub                                         the server (Mac Studio)
──────                                         ───────────────────────
michalby/MISTER_PLIS  (branch: main | any) ──► app checkout ── mister_plis/      the base: a complete app
                                                              modules/timemachine/
                                                              modules/inventory/   (reagents + consumables + tidy-up)

smith-lab/lab-tools (branch: main | any) ─► <app home>/tool-sources/lab/          ┐
github.com/<anyone>/<public tools repo> ────────► <app home>/tool-sources/<name>/      ├─ tools, loaded by the base
                                                                                         ┘

                                               <storage>/  (a folder the user chooses)
                                                 jobs/<job id>/job.json + out/ + inputs/   one folder per job, flat JSON
                                                 jobs/index.json                            rebuildable cache
                                                 modules/timemachine/ …                     module data
                                               <backup>/   (another folder the user chooses: NAS, disk)
                                                 <person>/<date>_<keyword> <tool> (<job id>)/
                                                   README.md  results.xlsx  plots/  files/
                                                   mister-plis/  (job.json, manifest.json, inputs/) → re-import
```

The plan has three goals:

1. **The base is a complete app on its own.** It includes jobs, storage, backup and re-import, settings, people,
   feedback, updates, the label printer and the lab notebook. It runs with no modules and no tools at all.
   Modules live in `modules/<name>/`, plug into the base through one documented interface, and the base does not
   import them by name. Three modules: Time Machine, Inventory and the Lab notebook.
2. **Tools come from git repositories**: the lab's tools repository plus any number of extra public ones. For
   each repository you can choose which branch to run, the same way the base works. Each such repository is
   called a "tool source" in this plan.
3. **Each job is a self-contained folder** in a storage location you choose, with flat JSON files. Backups are
   human-readable (`.md`, `.xlsx`, plots, files) and contain enough to bring the job back into MISTER PLIS.
   Time Machine retrieves jobs through the same importer.

---

## 1. Decisions (confirmed 2026-11-07)

All recommendations below were accepted, except D6: **the Lab notebook becomes a module** (phase P6).

| # | Question | Recommendation |
|---|---|---|
| D1 | Name and visibility of the tools repository | `smith-lab/lab-tools`, private (like the base). The server's token gets read access to it. |
| D2 | Who may add extra public tool repositories, and how much they are trusted | Only from **System & updates**, and each one is pinned to a commit. They run as normal Python inside the server (§9.3), so treat them like installing software. |
| D3 | Keep the input files with each job? | Yes, copied into the job folder at submit time, with a size cap (default 200 MB per job, above which only names and checksums are kept). This makes re-runs and re-imports complete. Today, uploads are deleted after 3 days. |
| D4 | Plot pictures in backups | Always an interactive `.html` (works offline) plus the plot's data in `results.xlsx`. Also a `.png` when the optional `kaleido` package (which needs Chrome on the server) is installed. |
| D5 | Where module data lives | Under the storage location (`<storage>/modules/<id>/`), because Time Machine holds job data that is as valuable as the jobs themselves. Small app settings stay in the local `data/` folder. |
| D6 | Is the Lab notebook a module? | **Yes** — moved to `modules/notebook` in P6, after Inventory. |
| D7 | Backup folder layout | Keep today's `<person>/<date>_<keyword> <tool> (<job id>)/`, so existing backups and habits still work. |

---

## 2. Order of work (phases)

Each phase is one branch. It is tried on the Mac Studio with **System & updates → Run another branch**, then
merged to `main`. Turn off the nightly self-update while a phase that migrates data is being rolled out.

| Phase | What | Size | Depends on |
|---|---|---|---|
| **P0** | Safety net: tests that pin today's behaviour, a release tag, a data backup | S | — |
| **P1** | Tool SDK clean-up, still in this repo: tools stop reaching into the base's internals | S | P0 |
| **P2** | Job store: a storage location you choose, `job.json` per job, `index.json`, migration | M | P0 |
| **P3** | Backup v2 (human-readable) and re-import, a shared "backup catalogue" | L | P2 |
| **P4** | Module framework in the base; Time Machine moved to `modules/timemachine` | L | P2, P3 |
| **P5** | Inventory moved to `modules/inventory` | M | P4 |
| **P6** | Lab notebook moved to `modules/notebook` | M | P4, P5 |
| **P7** | Tool sources: tools move to their own repository, extra public repositories, branch choice | L | P1, P4 |
| **P8** | Docs, the Mac app, CI, removing the compatibility shims | S | all |

The reasons for this order:

- The job store and backup (P2, P3) come before the modules because Time Machine is mostly a consumer of jobs
  and backups. Moving it onto the new APIs is simpler than moving it twice.
- Tools leave the repository last (P7), because that is the most disruptive step and it needs P1's clean SDK.

---

## 3. P0 — Safety net

1. Tag the current `main` as `v1-final` so you can always go back to it with **Run another branch**.
2. Add "characterisation" tests for the parts that will move:
   - the layout of today's backup folders (`job-info.json`, `job-info.txt`, the files);
   - Time Machine retrieving from a v0 backup folder;
   - `meta.json` loading in `JobManager.load_history`;
   - the reagents sync.

   The existing tests cover most of this (`test_backup.py`, `test_timemachine.py::test_retrieve_from_the_backup_folder`);
   P0 adds fixtures with **real old folders** (`tests/fixtures/backup_v0/…`, `tests/fixtures/jobs_v0/…`), so
   later phases must keep reading them.
3. Write `docs/FORMATS.md`, describing today's on-disk formats (the "v0" formats). Every importer and migration
   later refers to it.
4. On the Mac Studio, make a one-off copy of `data/` before P2 starts.

**Done when:** the new fixtures load, and the tag exists.

---

## 4. P1 — Tool SDK clean-up (preparation for separate tool repositories)

Today, tools reach into the base in four ways that would break once they live in another repository:

| Where | What | Replace with |
|---|---|---|
| `tools/molarity.py` | `settings.data_path / "compounds.json"` | `ctx`-free helper `toolkit.tool_data_dir("molarity")` → `<storage>/tool-data/<source>/<tool>/` |
| `tools/_assays.py` | `settings.data_path / "assays.json"` | the same helper |
| `tools/blender_render.py` | `settings.find_blender()` | `toolkit.find_program("blender", setting="blender_path")` |
| `tools/assay_reagents.py` | `from mister_plis.i18n import trc` | re-export `trc` from `mister_plis.toolkit` |
| every helper import | `from tools._spectra import …` | relative imports: `from ._spectra import …` |
| `mister_plis/locale/pl_tools.py` | the tools' Polish texts live in the base | `tools/locale/pl.py` next to the tools; the base merges the catalogue of every tool source |
| `tests/test_tools.py`, parts of `test_report.py` | tool tests live in the base | `tools/tests/` next to the tools (moved with them in P7) |

Also in P1:

- **Make `mister_plis.toolkit` the only public API** for tools and give it a version: `TOOLKIT_API = 1`. Write
  what it includes in `docs/ADDING_TOOLS.md`: `Tool`, `inputs`, `outputs`, `ToolError`, `RunContext`, `tr/tn/trc`,
  `pref`, `read_table`, `write_workbook`, `fmt`, `PALETTE`, `tool_data_dir`, `find_program`, etc. Anything not
  listed there is internal.
- **Add a `pyproject.toml` to the base**, so the tools repository's own tests can `pip install` the base at a
  chosen branch (`pip install "mister-plis @ git+https://github.com/michalby/MISTER_PLIS@stable"`). This doesn't
  change how the server runs.
- **Add a test that fails if any file in `tools/` imports `mister_plis.<anything other than toolkit>`.**

**Migration:** on first start, move `data/compounds.json` and `data/assays.json` into the new per-tool folders.
Saved compounds and methods are kept.

**Done when:** `tools/` imports only `mister_plis.toolkit`, and all tests pass.

---

## 5. P2 — Job store in a storage location you choose

### 5.1 Settings: two folders, not one

| Setting | Holds | Default | Set in |
|---|---|---|---|
| `data_dir` (exists) | app state: settings JSON, people, feedback, clones of the notebook and inventory, tool sources | `<repo>/data` | `config.toml` |
| **`storage_dir`** (new) | jobs, uploads in progress, per-tool data, module data (Time Machine) | `<data_dir>/storage` | `config.toml` **and** System & updates → Storage |
| `backup_dir` (exists, lab setting) | backups | none | Settings → Results & backup |

The storage folder is checked the same way `Backups.check_folder` checks the backup folder: it must be an
absolute path, exist, be writable, and not sit inside the code checkout or the backup folder.

Changing `storage_dir` from the page offers **"Move the jobs there"**:

1. copy everything;
2. verify the copy;
3. switch;
4. restart;
5. keep the old folder until the person deletes it.

The page refuses while jobs are running.

### 5.2 One folder per job

```
<storage>/jobs/<job id>/
    job.json          ← the record (source of truth), schema below
    inputs/           ← copies of the uploaded files (D3), by input name: inputs/spectra/WT_1.txt …
    out/              ← result files, named <date>_<person>_<keyword>_<name> as today
    tables/           ← every table the tool returned, in full, as .xlsx (see 5.4)
    tmp/              ← scratch, deleted when the job finishes
```

`job.json` extends today's `meta.json` and adds a schema version and provenance:

```jsonc
{
  "format": "mister-plis-job", "format_version": 1,
  "id": "20261019-142301-a1b2c3", "title": "", "keyword": "", "user": "Anna Kowalska",
  "tool": {"id": "chlorophyll", "name": "Chlorophyll concentration",
           "source": "lab", "source_url": "https://github.com/smith-lab/lab-tools", "commit": "4f2c…"},
  "base": {"version": "2.0.0", "commit": "9ab1…"},
  "status": "done", "created": 1760876581.2, "started": …, "finished": …, "parent": "",
  "params": {…}, "prefs": {"lang": "pl", "decimal": "comma", …},
  "inputs": {"spectra": [{"name": "WT_1.txt", "path": "inputs/spectra/WT_1.txt", "size": 1234, "sha256": "…"}]},
  "outputs": [ … rendered outputs as today; tables gain "file": "tables/01_Results.xlsx" … ],
  "log": [ … ], "error": "", "traceback": "",
  "backed_up": {"at": …, "folder": "/Volumes/NAS/…", "format_version": 1} | null
}
```

### 5.3 The flat-file "database"

- **The source of truth is the `job.json` files**, one per folder. Each job then survives on its own: it can be
  copied, moved or restored without touching anything else, and a damaged file affects only one job.
- **`<storage>/jobs/index.json` is a cache.** It holds one small row per job (id, tool, user, title, keyword,
  status, dates, result file names, `backed_up`, flags that modules add), used for lists, search and filters.
  - It is written atomically (`.tmp` + rename) after each change.
  - It is rebuilt from the folders at start if it is missing, older than the folders, or unreadable.
  - Rebuilding takes seconds for thousands of jobs.
- This replaces today's "load every `meta.json` into memory at start". The in-memory job list is kept only for
  running jobs.
- Code: a new `mister_plis/jobstore.py` (`JobStore`: `create`, `get`, `update`, `list(filter)`, `delete`,
  `rebuild_index`, `import_folder`). It sits under `JobManager`, which keeps the thread pool and the running
  jobs.
- **Why not a single JSON database file as the only store:** one bad write would damage the whole history, two
  threads would contend for one file, and a single job could no longer be copied out on its own. The index gives
  the convenience of one file without that risk.

### 5.4 What changes in how results are saved

- **Tables are saved in full.** Today `O.Table` keeps only the first `max_rows` (500) rows in `meta.json`, and the
  full table exists only if the tool asked for a download. From P2 on, every table is also written to
  `tables/NN_<title>.xlsx` (or `.csv` beyond Excel's limits, see §6.3), and `outputs[i]["file"]` points to it.
  Tables no longer depend on the tool remembering to ask for a download.
- **Plots** stay as Plotly JSON in `job.json` (as today), so the result page keeps working unchanged.
- **Inputs** are copied in at submit time (D3). The `UploadStore` keeps its short retention for uploads that
  never became a job.

### 5.5 Migration (automatic, on first start of P2)

For each `data/jobs/<id>/meta.json`:

1. copy the folder to `<storage>/jobs/<id>/`;
2. write `job.json` from `meta.json` (format 0 → 1). Fields that can't be recovered stay empty: tool commit, and
   inputs whose uploads are already deleted;
3. keep `meta.json` beside it for one release.

Then build `index.json`. The old `data/jobs` is renamed `data/jobs.migrated-<date>` rather than deleted.

Two cleanups follow:

- Live calculator runs (`data/live`) move to `<data_dir>/live`. They are disposable and stay off the chosen
  storage.
- **Retention** stays as it is (`job_retention_days`), with a stronger guarantee in P3: with a backup folder set,
  a job is deleted **only if its backup is verified** (§6.5).

**Done when:**

- jobs are created, listed, searched, re-run and cleaned up from `<storage>`;
- old jobs are visible after migration;
- deleting `index.json` and restarting gives the same list.

---

## 6. P3 — Backup v2 (human-readable) and re-import

### 6.1 The backup folder of one job

```
<backup>/Anna Kowalska/2026-10-19_WT-light Chlorophyll concentration (20261019-142301-a1b2c3)/
    README.md                         ← everything about the job, readable without MISTER PLIS
    results.xlsx                      ← every table, one sheet each; plus "Summary" and "Plot data" sheets
    plots/01_Spectra.html             ← interactive, works offline (uses plots/plotly.min.js next to it)
    plots/01_Spectra.png              ← only when kaleido is installed (D4)
    plots/plotly.min.js
    files/…                           ← every other output file as the tool produced it (images, zips, PDFs, meshes…)
    report.pdf                        ← the same PDF as the result page's PDF button (charts as PNG when available)
    mister-plis/                      ← for re-import; people can ignore it
        README.txt                    ← "This folder lets MISTER PLIS import the job again. Don't edit it."
        job.json                      ← the full record (as in storage)
        manifest.json                 ← format version + where every file came from + checksums
        inputs/…                      ← copies of the input files (if kept, D3)
```

### 6.2 `README.md` contents

The README is generated **in English**, like every file the app writes (the interface alone is translated).

1. A title line (`# Chlorophyll concentration — WT vs mutant, day 3`) and the job number.
2. A "Who / when / tool" table:
   - person, started, finished, status;
   - tool name and id;
   - tool source and commit, base version and commit;
   - parent job (re-run of …).
3. **Input files:** names, sizes, sha256, and whether a copy is in `mister-plis/inputs/`.
4. **Settings:** the human-readable list from `report.describe_settings`, which also drives today's
   `job-info.txt`.
5. **Results**, in the order the tool returned them:
   - metrics as a list (`- **Chl a+b:** 12.3 µg/mL`);
   - Markdown and alerts as text;
   - each table as the first 20 rows in Markdown, plus "full table: `results.xlsx`, sheet *Results*";
   - each plot as `![Spectra](plots/01_Spectra.png)` (or a link to the `.html`);
   - images and files as links into `files/`.
6. The last 50 log lines, and errors if any.
7. "To bring this job back into MISTER PLIS: Jobs & results → Import from backup."

### 6.3 `results.xlsx`, or `.csv` only when xlsx is impossible

- One sheet per `Table` output. The sheet names are the table titles, cut to 31 characters and de-duplicated.
- A **Summary** sheet holds the metrics and the job description.
- A **Plot data** sheet holds the x/y values of every plotted trace, labelled by plot and trace name.
- It is written with the existing `excel.write_workbook`, so it gets the same formatting as today's downloads.
- **The CSV rule:** a table that cannot go into Excel is written as `tables/<title>.csv` instead, and **not also**
  as a sheet. The README says why. "Cannot" means more than 1,048,576 rows or 16,384 columns, or a cell longer
  than 32,767 characters. Nothing is written in both formats.
- **No duplicates of table downloads.** Files that are only per-table download copies (today's
  `Table(download=…)` files) are marked `"derived": "table"` in `job.json` and not copied to `files/`, because the
  same data is in `results.xlsx`. Files the tool produced deliberately (`O.File`, `O.Image`, zips, meshes) are
  copied as they are.

### 6.4 `manifest.json`: what makes re-import possible without storing results twice

```jsonc
{
  "format": "mister-plis-backup", "format_version": 1, "job_id": "…", "written": "2026-10-20T03:10:00",
  "base": {"version": "2.0.0", "commit": "…"},
  "files": [
    {"backup": "files/2026-10-19_Anna-Kowalska_WT-light_chlorophyll_results.xlsx",
     "job": "out/2026-10-19_Anna-Kowalska_WT-light_chlorophyll_results.xlsx", "size": 18234, "sha256": "…"},
    {"backup": "results.xlsx", "job": null, "generated": true, "sha256": "…"},
    {"backup": "mister-plis/inputs/spectra/WT_1.txt", "job": "inputs/spectra/WT_1.txt", "sha256": "…"}
  ]
}
```

- Re-import rebuilds the job folder from the human-readable files: each `backup` path is copied to its `job`
  path. `out/` is not stored a second time.
- Generated files (`README.md`, `results.xlsx`, plots, `report.pdf`) have `job: null` and are not imported. The
  imported job draws them again from `job.json`.
- The checksums let import (and the retention check) **verify** the backup.

### 6.5 Writing a backup safely, and when a job may be deleted

- Write to `<name>.partial/`, then rename it, as today. A `.partial` folder is never treated as a backup.
- After the rename, re-read `manifest.json` and check every file's size and checksum. Only then set
  `job.json → backed_up = {at, folder, format_version}`.
- Cleanup (`job_retention_days`) deletes a job only when one of two things is true:
  - no backup folder is set, which keeps today's behaviour; or
  - `backed_up` is set **and** the backup folder is reachable **and** its manifest still verifies.

  If the NAS isn't mounted, nothing is deleted. That is today's rule, made strict.
- "Clear history → back up first" (today's `Backups.clear`) uses the same rule.

### 6.6 The backup catalogue (shared by Jobs & results and Time Machine)

The new `mister_plis/backup.py` grows a `BackupCatalogue` that is used everywhere a job is looked up in the
backup folder:

- `scan()` walks `<backup>/<person>/<folder>/`, recognises v1 folders (they have `mister-plis/manifest.json`) and
  **v0 folders** (today's `job-info.json` + files, and the job id in brackets in the folder name). It returns rows
  `{id, tool, user, title, keyword, created, folder, format}`.
- To avoid walking a NAS each time, `<backup>/mister-plis-index.json` caches the rows. It is updated when a backup
  is written, rebuilt by a **Rescan** button, and ignored if unreadable.
- `find(query)` matches by job number, its last 6 characters, title, keyword or person. This is today's
  `timemachine.normalize_query/matches`, moved to the base.
- `import_job(folder, into)` copies a backup folder into a job folder:
  - **v1:** follows the manifest, verifies the checksums, and writes `job.json`.
  - **v0:** copies the files into `out/`, turns `job-info.json` into `job.json`, and marks the job "imported from
    an old backup: some details may be missing".
  - Both: set `"imported": {"from": folder, "at": …}`.

### 6.7 Re-import in Jobs & results

- **Jobs & results → Import from backup** opens a search over the catalogue (same filters as the job list).
  Selected jobs are imported into `<storage>/jobs/`.
- Imported jobs are normal jobs. They can be opened, re-run and re-printed, and they carry the "imported" mark.
  They count as already backed up (the folder they came from), so cleanup may remove them again without
  re-copying.
- If a job with that id is already in storage, the import is skipped and the existing job is shown.
- An API endpoint (`POST /api/jobs/import {folders: [...]}`) serves the page and scripts.

### 6.8 Migration and compatibility

- Existing v0 backup folders stay where they are and remain importable (§6.6).
- An optional **"Upgrade old backups"** button on System & updates rewrites a v0 folder into v1, adding
  `README.md`, `results.xlsx` and `mister-plis/` and keeping the files. It is offered, never automatic.
- `job-info.txt` / `job-info.json` are no longer written for new backups. `README.md` and `mister-plis/job.json`
  replace them.

**Done when:**

- a v1 backup opens and reads correctly on a computer without MISTER PLIS;
- a job deleted after backup comes back through Import with identical result files (checksums match);
- a v0 fixture folder imports;
- cleanup never deletes an unverified job (test with an unmounted or tampered backup folder).

---

## 7. P4 — The module framework, and Time Machine in `modules/timemachine`

### 7.1 Layout

```
modules/
  timemachine/
    __init__.py         ← exports `module = Module(...)`
    service.py          ← today's timemachine.py (TimeMachine) — retrieval now via the base's BackupCatalogue
    history.py          ← today's tmgit.py
    web.py              ← routes (today ~25 routes inline in app.py: /timemachine, /api/tm/*)
    templates/          ← timemachine.html, partials/galaxy.html
    static/             ← timemachine.js, timemachine.css (TM rules split out of app.css)
    locale/pl.py        ← TM strings split out of locale/pl_ui.py
    tests/              ← today's tests/test_timemachine.py
    MODULE.md           ← what it does, its data, its settings
  inventory/            ← P5
  notebook/             ← P6
```

`modules/` is a top-level folder in the base repository, next to `mister_plis/`, so it is clearly separate code
but follows the base's branch.

### 7.2 The module interface (in the base: `mister_plis/modules.py`)

```python
@dataclass
class Module:
    id: str                         # "timemachine" — also its URL prefix and data folder name
    name: str                       # "Time Machine"
    api: int = 1                    # the module API version it was written for
    setup: Callable[[ModuleContext], Any]       # build the service object(s); called once at start
    register: Callable[[FastAPI, ModuleContext], None]  # add routes (under /<id> and /api/<id>)
    nav: list[NavItem] = ()         # sidebar links: label, href, icon or template partial, order, match prefix
    threads: list[Callable] = ()    # background loops, started by the base after setup
    templates: Path | None = None   # added to the Jinja loader as "<id>/…"
    static: Path | None = None      # mounted at /m/<id>/static/
    scripts: dict[str, list[str]] = {}   # extra JS per page kind: {"job": ["timemachine-button.js"], "jobs": [...]}
    panels: dict[str, str] = {}     # template partials for "system" and "settings" pages
    locale: dict[str, dict] = {}    # {"pl": {...}}
    hooks: Hooks = Hooks()          # see 7.3
```

`ModuleContext` is everything a module may use from the base, and nothing else:

- `storage` (its folder `<storage>/modules/<id>/`) and `data` (its folder `<data_dir>/modules/<id>/`);
- `settings` (a section `[modules.<id>]` from `config.toml`);
- `jobs` (the `JobStore`, read / create / import) and `backups` (`BackupCatalogue`, backup settings);
- `people` (canonical names), `page()` (renders a page in the shell), `tr`, `printer` (the label printer);
- `git` (the shared helper that runs git with the server's token, today copied in three places).

**Loading:**

- `config.toml` → `modules = ["timemachine", "inventory"]`. The default is every folder in `modules/`.
- The base imports `modules.<id>`, checks `api`, calls `setup`, and then `register`.
- A module that fails to load is listed like a broken tool and does not stop the app, the same rule as tools
  today.

### 7.3 Hooks: the places where modules touch the base today, turned into explicit calls

| Today (hard-coded in the base) | Becomes |
|---|---|
| `app._job_dict` adds `in_tm`, `tm_root` | `hooks.job_flags(job) -> dict`; the base merges `{"modules": {"timemachine": {...}}}` into every job dict and index row |
| `app.js` draws "Add to Time Machine" on every result | the module's `scripts["job"]` adds the button through `MP.hooks.resultActions.push(fn)` (a new small hook list in `app.js`) |
| `jobs.js` "kept or not" filter | `hooks.job_filters()` declares extra filters; `jobs.js` draws them generically |
| `app.people()` counts "kept" from Time Machine | `hooks.people() -> [{name, what, when}]` |
| `app.rename_person` calls `timemachine.rename_person` | `hooks.rename_person(old, new, by) -> count` |
| `/api/jobs/{id}/report.pdf` also accepts `/api/tm/{id}/files/` URLs | `hooks.file_resolver(url) -> Path|None` |
| `base.html` has fixed sidebar links and `tm_mode` | the sidebar loops over `nav`; `page(..., shell_class="tm")` replaces the TM-only flag |
| `system.html` / `settings.html` hold reagent sections, `reagents.css`, `reagents_admin.js` | `panels["system"]`, `panels["settings"]` included in a loop |
| `report.py` draws the "galaxy" mark by the job number | stays in the base as the **job number mark** (it identifies a job anywhere, and works without Time Machine) |

### 7.4 What changes inside Time Machine

- **Storage:** `data/timemachine/` moves to `<storage>/modules/timemachine/` (migrated on first start; the local
  git history moves with it). Kept jobs use the **same job folder format** as `<storage>/jobs/` (`job.json`,
  `out/`, `inputs/`, `tables/`) plus `entry.json`.
- **Retrieval:** `find`, `retrieve` and `_from_backup` stop parsing backup folders themselves. They call
  `ctx.backups.find()` and `ctx.backups.import_job(folder, into=<tm>/<job id>)`. Time Machine therefore reads v0
  and v1 backups, verifies checksums, and gets inputs back when the backup has them.
- **Adding from Jobs & results:** copies the job folder through `ctx.jobs` (no reaching into `JobManager`).
- **Backing up Time Machine itself.** Today its git history is never pushed and its manual entries and tasks
  exist only on the server.
  - When a backup folder is set, Time Machine writes `<backup>/Time Machine/`:
    - every kept entry in the same v1 human-readable format;
    - `projects.md`;
    - a `timemachine.bundle` (a `git bundle` of its history) after every change, debounced.
  - **System & updates → Time Machine → Restore from backup** rebuilds the module's folder from that copy.
  - This closes the "kept for good, but only on one disk" gap found in the audit.

**Done when:**

- the base starts and passes its tests with `modules = []`;
- with `["timemachine"]`, all of today's Time Machine tests pass from `modules/timemachine/tests/`;
- `grep -ri "timemachine\|/api/tm" mister_plis/` finds only the migration code.

---

## 8. P5 — Inventory in `modules/inventory`

- **Move:** `reagents.py` → `modules/inventory/service.py`, `reagents_web.py` → `web.py`, `tidy.py` → `tidy.py`.
  The templates `reagents.html` and `partials/flask.html`, the static files `reagents.js`, `reagents_admin.js`,
  `reagents.css` and the reagent parts of `label.js`, and the locale files `pl_reagents.py` and `pl_tidy.py` all
  move too. So do the tests (`test_reagents`, `test_consumables`, `test_tidy`).
- **Two nav items** (Reagents, Consumables) from one module, as `reagents_web.SPACES` already does.
- **Settings:** `reagents_repo`, `reagents_branch` and `ollama_url` move from `Settings` to
  `[modules.inventory]`. The old top-level keys are still read for one release.
- **Data:** the clone stays in `<data_dir>/modules/inventory/repo` (moved from `data/reagents/`). It is a git
  clone of GitHub, not job data, so it doesn't belong in `<storage>`.
- **Labels:**
  - `labels.py` splits into the **printer driver and generic label** (base, used by the calculators' protocol
    labels) and the **portion label with storage category and GHS pictograms** (module).
  - The GHS images move to `modules/inventory/static/`.
- **Shared helpers:** `obsidian.fold` (accent-folding, used by reagents) moves to `mister_plis/text.py`.
- **Git:** the three copies of the git runner (`updater.git`, `Notebook.git`, `Inventory.git`, and the
  credential trick in `notes._credential_args`) become one `mister_plis/gitutil.py`, offered to modules as
  `ctx.git`.

**Done when:** the same three checks as P4 pass for `inventory`, and a sync with the real
`inventory` works from the test branch on the Mac Studio.

---

## 8b. P6 — Lab notebook in `modules/notebook`

- **Move:** `notes.py` → `modules/notebook/service.py` and `obsidian.py` → `modules/notebook/obsidian.py`. The
  notebook routes (`/notes`, `/notes/files/*`, `/api/notes/*`, inline in `app.py` today), `notes.html`,
  `notes.js`, the notes CSS (out of `app.css`), its strings in `pl_ui.py` and `tests/test_notes.py` all move with
  them.
- **The side panel on every page.** Today `base.html` hard-codes the notes button, the panel, the rail, the
  pre-paint script and the `notes_enabled` / `hide_notes_panel` flags. The module interface gains **shell
  contributions**:
  - `Module.shell = {"topbar": partial, "aside": partial, "head_script": partial, "scripts": [...]}`;
  - a page-level `page(..., hide_panels={"notebook"})` replaces `hide_notes_panel`.

  The `N` key shortcut and the remembered width stay in the module's JS.
- **Settings:** `notes_repo`, `notes_branch` → `[modules.notebook]`. The old keys are read for one release. The
  clone moves from `data/notes/` to `<data_dir>/modules/notebook/` (it is a GitHub clone, not job data).
- **Shared code:** the credential reuse (`notes._credential_args`) is already `mister_plis/gitutil.py` after P5,
  and `fold` is `mister_plis/text.py`.
- **System panel:** the "Lab notebook" section of `system.html` becomes `panels["system"]`.

**Done when:**

- the base runs with the notebook module off: no panel, no button, no link;
- with it on, today's notebook tests pass from `modules/notebook/tests/`;
- `grep -ri "notebook\|notes_" mister_plis/` finds only migration code.

---

## 9. P7 — Tools in their own repositories

### 9.1 Creating `MISTER_PLIS-tools`

1. Use `git filter-repo --path tools/ --path-rename tools/:` on a copy of the base repository, which keeps the
   tools' history. Then add:

   ```
   MISTER_PLIS-tools/
     mister-plis-tools.toml   ← the manifest (below)
     *.py, _helpers.py        ← the tools, as today
     locale/pl.py             ← from P1
     tests/                   ← from P1, run in this repo's own CI against the base (pip install @ branch)
     requirements.txt         ← extra packages these tools need beyond the base's
     README.md                ← how to add a tool (today's docs/ADDING_TOOLS.md moves here; the base keeps the SDK reference)
   ```

2. Remove `tools/` from the base, keeping a tiny `tests/fixtures/toolsource/` with two toy tools so the base's
   tests don't need the real tools.
3. The base's requirements shrink to what the base needs. Tool-only packages (`scikit-image`, `trimesh`,
   `fast-simplification`, `pypdfium2`, `pillow-heif`, `pyobjc-framework-Vision`) move to the tools repository's
   `requirements.txt`.

The manifest:

```toml
[source]
name = "lab"                       # short id: folder name, import package, shown in the UI
title = "Lab tools"
requires_toolkit = ">=1,<2"        # TOOLKIT_API range it works with
requirements = "requirements.txt"
locale = { pl = "locale/pl.py" }
```

### 9.2 Tool sources in the base (`mister_plis/toolsources.py`)

- **The list of sources** is in `<data_dir>/tool_sources.json`, managed on **System & updates → Tool sources**.
  `config.toml` may preset it, and the lab repository is preset by default:

  ```json
  [{"name": "lab", "url": "https://github.com/smith-lab/lab-tools.git", "branch": "main",
    "enabled": true, "pinned": null, "trusted": true}]
  ```

- **Clone and update.** Each source is cloned to `<app home>/tool-sources/<name>/` with the shared git helper and
  the same token. Each source's panel has **Check**, **Update**, **Run another branch** and **Remove**: the same
  actions and safeguards as the base's `updater.py` (fast-forward only, refuses local edits, lists incoming
  commits). The base's own panel stays as it is.
- **Loading:** `registry.py` stops scanning `ROOT/tools`.
  - Each enabled source is imported as its own package `mp_tools_<name>`, so helper modules from two sources
    never collide (relative imports from P1 make this work).
  - Tools are tagged with their `source`, and the source and commit are written into each `job.json`.
- **Tool id collisions:** the first source in the list wins. The other tool is listed as broken ("id `dilution`
  already used by source *lab*"). The ids stay unqualified, so `/tool/<id>` links and old job records keep
  working.
- **Locale:** each source's `locale/pl.py` is merged into the catalogue; the base's own strings win.
- **Dependencies:**
  - When a source is added or updated and its `requirements.txt` changed, the base first runs
    `pip install --dry-run -r requirements.txt -c <base constraints>`.
  - If installing would upgrade or downgrade anything the base pins, the update stops and shows which packages.
    Otherwise it installs.
  - The base gains a `constraints.txt`: exact versions of its own dependencies, produced from the running venv.
    This also fixes the audit's "no lock file" point.
- **Restart on update:** updating a source schedules the same idle restart as a base update (the same
  "jobs are running" confirmation). Reloading Python code inside a running process is not attempted.
- **Missing tool:** a job whose tool's source was removed still opens, prints and backs up (all of that works
  from `job.json`). Only **Re-run** is disabled, with a message naming the missing source.

### 9.3 Extra public repositories: trust and safety

A tool is Python code running inside the server, with access to every job, the inventory and the GitHub token.
So:

- Adding a source shows its URL, its manifest, its requirements, and the list of its files.
  - A non-`trusted` source is added **disabled and pinned to the commit shown**.
  - A person enables it explicitly.
  - Later updates show the incoming commits and the changed files before applying.
- A source that is public **and not owned by the lab** never gets the token: it is cloned anonymously.
- Optional later step (not in this plan's scope): run untrusted sources' jobs in a separate worker process with
  only the job folder writable.

### 9.4 Updating the Mac app and the first start

- The launcher (`macos/launcher/main.swift`) keeps cloning only the base. The base clones its tool sources on
  first start (System & updates shows progress). No launcher rebuild is needed, unless you want a progress
  window.
- The token instructions (`docs/DEPLOY_MAC_STUDIO.md`) add `MISTER_PLIS-tools` to the token's repository list.

**Done when:**

- the base with no sources starts and shows "no tools yet";
- adding `MISTER_PLIS-tools` (main) brings back every tool, and old jobs re-run;
- switching that source to a test branch and back works;
- a second public source can be added, pinned, enabled and removed.

---

## 10. P8 — Finishing

- **Docs:**
  - `docs/ARCHITECTURE.md` (the base, the module API, the storage formats, the tool sources);
  - `docs/MODULES.md` (how to write a module, using Time Machine as the example);
  - `docs/FORMATS.md` (job v1, backup v1, the v0 readers);
  - `README.md` and `DEPLOY_MAC_STUDIO.md` updated.
- **CI (GitHub Actions):**
  - the base runs its tests and the module tests;
  - the tools repo runs its tests against the base at `main`;
  - a nightly job runs the tools tests against base branches being tested.
- **Remove the compatibility shims** after one release: old `meta.json` readers stay, because they read old
  backups and the v0 importer needs them; the old config keys go, and so do the `data/jobs.migrated-*` hints.
- **CLAUDE.md:** describe the module rule (the base never imports `modules.*` by name) and where tools now live.

---

## 11. What changes for each kind of person

| Who | Before | After |
|---|---|---|
| People using the lab app | — | Same pages and links. New: Import from backup, Storage and Tool sources panels, readable backup folders. |
| Someone adding a tool | a file in `tools/` of the app repository | a file in `MISTER_PLIS-tools` (same SDK, same template). Their own public repository also works. |
| Someone adding a large module | edits `app.py`, `base.html`, `system.html`, locale… | a folder in `modules/` exporting a `Module` object; the base is not edited |
| Whoever runs the server | one checkout, `data/` | one checkout plus tool-source clones, a chosen storage folder, a backup folder |

---

## 12. Risks and how the plan handles them

| Risk | Handling |
|---|---|
| Data loss in migration on the live server | P0 copy of `data/`; migrations copy and verify before switching; old folders renamed, not deleted; each phase tried on a branch first; nightly update off meanwhile |
| Old backups become unreadable | v0 importer kept for good, with fixtures of real old folders in the tests |
| Broken links and old jobs after tools move | tool ids unchanged; `job.json` keeps everything needed to show and print without the tool |
| Package conflicts between tool sources | per-source requirements, base constraints file, dry-run before install |
| Untrusted code from public repositories | disabled and pinned by default, review of changes, no token for foreign repos |
| Storage on a NAS is slow or goes away | storage should be a local disk (the backup is the NAS); the page warns when `storage_dir` is on a network volume; jobs refuse to start if storage is unavailable, with a clear message |
| The size of P4 (Time Machine is ~2,000 lines across Python and JS) | hooks are added to the base first, with Time Machine still in place; then the move is a mostly mechanical relocation, with its tests moved unchanged |

---

## 13. Rough checklist of files per phase

- **P1:**
  - edit `tools/molarity.py`, `tools/_assays.py`, `tools/blender_render.py`, `tools/assay_reagents.py`, all helper
    imports in `tools/`, and `mister_plis/toolkit.py`;
  - move `mister_plis/locale/pl_tools.py` → `tools/locale/pl.py`;
  - add `pyproject.toml` and the new tests.
- **P2:**
  - new `mister_plis/jobstore.py`;
  - edit `jobs.py`, `config.py`, `app.py` (job routes, system panel), `system.html` + `system.js` (Storage panel),
    `outputs.py` (tables in full);
  - add migration code, tests and fixtures.
- **P3:**
  - rewrite `backup.py` (writer v1, `BackupCatalogue`, importer v0/v1, verification);
  - new `mister_plis/export_md.py` (README) and the plot export;
  - edit `jobs.html` and `jobs.js` (Import from backup), `settings.html` (backup panel), `report.py` /
    `printout.py` (PDF without a browser when PNGs are available).
- **P4:**
  - new `mister_plis/modules.py`;
  - edit `app.py` (remove the TM routes, the people/rename/file-resolver hooks), `base.html` (generic nav, panels,
    scripts), `app.js` (`MP.hooks`), `jobs.js`, `system.html`, `settings.html`;
  - new `modules/timemachine/**`; move `tests/test_timemachine.py`.
- **P5:**
  - new `modules/inventory/**`;
  - edit `labels.py` (split), `config.py`;
  - new `mister_plis/text.py` and `mister_plis/gitutil.py`; edit `notes.py` and `updater.py` to use `gitutil`;
  - move the three tests.
- **P6:** new `modules/notebook/**` (from `notes.py`, `obsidian.py`, `notes.html`, `notes.js`, the panel in `base.html`); edit `app.py`, `base.html`, `config.py`; move `tests/test_notes.py`.
- **P7:**
  - new repository `MISTER_PLIS-tools`;
  - new `mister_plis/toolsources.py`;
  - edit `registry.py`, `__main__.py` (reload dirs), `updater.py` (shared branch/sync logic), `system.html` +
    `system.js` (Tool sources);
  - add `constraints.txt` and `tests/fixtures/toolsource/`;
  - remove `tools/`.
- **P8:** docs, CI workflows, `CLAUDE.md`.
