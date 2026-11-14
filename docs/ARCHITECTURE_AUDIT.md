> **History.** This is the audit from before the reorganisation (docs/reorg). The current architecture is in
> [ARCHITECTURE.md](ARCHITECTURE.md).

# MISTER PLIS — architecture audit

*Written 2026-11-07, from commit `077060e`. It describes the code as it is. Nothing in the code was changed.*

This report covers how the app is built and organised, how tools and large modules are added, and how code and
data move between machines today. It ends with what this means for making the app deployable and shareable.

---

## 1. The short version

- **One Python process** (FastAPI + uvicorn) on one machine, the lab Mac Studio. It serves server-rendered HTML
  pages (Jinja2) plus a JSON API, and the browser adds plain JavaScript with no build step.
- **No database.** Each part keeps its state in files under `data/`: JSON files, job folders, and **three git
  repositories** that act as data stores:
  - Time Machine: a local git repo. It is never pushed.
  - Reagents / Consumables: a clone of `smith-lab/inventory`. The server commits each edit and pushes it.
  - Lab notebook: a read-only sparse clone of `smith-lab/notebook`.
- **GitHub carries everything between machines.** Code goes out by `git push`, and the server pulls it with
  `git pull --ff-only` and restarts itself. Notes come in by pull. Reagent data goes both ways and is merged
  cell by cell.
- **There are two ways to extend the app:**
  - A **tool** is one file in `tools/`. It is found automatically, and its form, job, results page, PDF and
    Excel export are generated for it.
  - A **large module** (Time Machine, Reagents, Lab notebook) is written by hand. It needs a back-end class, API
    routes, a template, JS/CSS, a sidebar link, a background thread and locale strings, all wired into `app.py`
    and `base.html`.
- **No logins.** A person's identity is the name they type in the top bar, kept in a cookie. The app is safe only
  on the lab LAN, and the deploy guide says so.

Tests: `.venv/bin/python -m pytest` — see §10 for the result of this audit's run.

---

## 2. Repository layout

```
MISTER_PLIS/
├── mister_plis/              the application package (~9.5k lines of Python)
│   ├── __main__.py           `python -m mister_plis` → uvicorn (host/port/--reload)
│   ├── config.py             Settings dataclass ← config.toml ← MISTER_PLIS_* env vars
│   ├── app.py                FastAPI app: creates every service object, all core routes (1150 lines)
│   ├── registry.py           discovers tools in tools/
│   ├── toolkit.py            Tool, RunContext, helpers — the public API for tool authors
│   ├── inputs.py outputs.py  form field types / result types (each knows its JSON spec and render)
│   ├── jobs.py               UploadStore, Job, JobManager (thread pool, job folders, meta.json)
│   ├── prefs.py              per-browser settings from cookies, a ContextVar for the current request/job
│   ├── i18n.py locale/       English → Polish catalogue, placeholder patterns, plurals
│   ├── report.py printout.py PDF of a result / protocol (reportlab)
│   ├── excel.py plotting.py  formatted .xlsx output; Plotly theme and palette
│   ├── labels.py             Brother P-touch label rendering + raw TCP:9100 printing
│   ├── backup.py             copies finished jobs to a backup folder (NAS / disk)
│   ├── feedback.py people.py small JSON stores (feedback list, merged names)
│   ├── updater.py            code self-update: git fetch/pull, pip install, os.execv restart, nightly mode
│   ├── timemachine.py tmgit.py   Time Machine module + its local-git history
│   ├── notes.py obsidian.py      Lab notebook: sparse clone of the vault + Obsidian-Markdown renderer
│   ├── reagents.py reagents_web.py  Reagents/Consumables inventory (workbooks in git) + its routes
│   ├── tidy.py               scheduled inventory clean-up (rules + local LLM via Ollama)
│   ├── templates/            Jinja2 pages: base.html (shell + sidebar) and one page per area
│   └── static/               css/, js/ (one file per area), GHS pictograms, label assets
├── tools/                    one file per tool; `_*.py` are shared helpers (not tools)
├── tests/                    pytest suite (unit + FastAPI TestClient)
├── docs/                     ADDING_TOOLS.md (also shown in-app at /guide), DEPLOY_MAC_STUDIO.md
├── scripts/                  setup.sh, dev.sh, run.sh, build_app.sh, install/uninstall_service.sh
├── macos/                    Swift launcher for "MISTER PLIS.app" + icon renderer
├── config.example.toml       per-machine settings template (config.toml is gitignored)
└── requirements*.txt         runtime / dev dependencies (lower bounds only, no lock file)
```

`data/`, `logs/`, `config.toml` and `.venv/` are gitignored. They exist only on the machine that runs the server.

---

## 3. Runtime architecture

### 3.1 Process and startup

`python -m mister_plis` (`__main__.py`) starts uvicorn on `mister_plis.app:app`. When `app.py` is imported, it
builds **every service object as a module-level singleton**:

```python
uploads      = UploadStore(data/uploads)
jobs         = JobManager(data, uploads, max_workers)
backups      = Backups(data, jobs)
printer      = Printer(data)
notebook     = Notebook(data, notes_repo, notes_branch)
feedback     = FeedbackStore(data)
timemachine  = TimeMachine(data, jobs, backup_dir)
merged_people= People(data)
inventory    = Inventory(data, reagents_repo, reagents_branch)
consumables  = Consumables(inventory)        # second workbook, same repo
tidy         = Tidy(inventory, ollama_url)
```

The FastAPI `lifespan` loads the tool registry and the job history from disk, loads the notebook index, and
starts the **background daemon threads**:

| Thread | Started in | Does |
|---|---|---|
| `maintenance` | app.py | every 10 min: backups; every hour: delete expired jobs/uploads |
| `auto-update` | app.py | every minute: if "night" mode and 03–05h and idle → pull code and restart |
| `notes-sync` | app.py | pulls the Obsidian vault every N min (if enabled) |
| `reagents-sync` | reagents_web.register | merges/pushes inventory every N min |
| `reagents-tidy-schedule` | reagents_web.register | runs the tidy-up at the scheduled time |
| `job-*` (pool) | JobManager | runs tool jobs (ThreadPoolExecutor, `max_workers`=8) |
| `threading.Timer(20 s)` | Inventory.commit | pushes reagent edits ~20 s after the last edit |

All state that is shared between requests lives **in this one process**: the jobs dict, locks, the cached
workbook, the notebook index and the timers. Running two copies of the server against the same `data/` would
break: there would be two schedulers, two pushers, and job lists that disagree.

### 3.2 Request handling

- An HTTP middleware reads cookies into a `ContextVar` (`prefs.current_prefs`). Any code (templates, tools,
  i18n) can then call `pref("lang")` or `pref("decimal")` without passing them around. A job copies the prefs
  of whoever started it into its worker thread.
- `page(request, template, **ctx)` renders a template with a shared context: prefs, running commit, the
  cache-busting `asset_v`, tool categories for the sidebar, broken tools, notebook/feedback flags and icons.
- The JSON API lives under `/api/...`. FastAPI publishes its OpenAPI docs at `/api/docs`.
- Errors that people can fix are raised as `ToolError` and returned as `{"error": "..."}` (HTTP 422),
  translated with `tr()`.

### 3.3 Frontend

- Plain JavaScript in IIFEs that share one global, `window.MP`. It holds the helpers `MP.$`, `MP.el`,
  `MP.api`, `MP.t`/`MP.tn` (i18n), `MP.icon` and `MP.fold`. There is no bundler, framework or npm.
- `base.html` is the shell: sidebar, top bar, notes panel, feedback button. It always loads `app.js` and
  `feedback.js`, and each page adds its own script in `{% block scripts %}` (`tool.js`, `jobs.js`,
  `timemachine.js`, `reagents.js`, `system.js`…).
- Tool pages are **built in the browser from a JSON spec**: the server embeds `tool.spec()`, and `tool.js` /
  `widgets.js` draw the form, upload files, call `/api/tools/{id}/run`, poll the job, and pass results to
  `outputs.js`.
- Plotly is served from the installed Python package (`/vendor/plotly.min.js`), so it needs no CDN.
- Static URLs carry `?v=<commit>-<start time>`, so a restart invalidates browser caches. `app.js` polls
  `/api/version` every 60 s and shows a "new version is live" banner when the commit changes.
- Per-browser conveniences (form values, column choices, plot colours, notes panel width) are kept in
  `localStorage`. Per-browser settings that the server must know (name, language, theme, decimal mark) are
  cookies.

### 3.4 Configuration

`config.py` holds a `Settings` dataclass with defaults. `config.toml` overrides it, and environment variables
(`MISTER_PLIS_<NAME>`) override both. Settings that the whole lab changes from the UI are **not** in
`config.toml`. They are JSON files under `data/` (see §4).

### 3.5 Internationalisation

The code and templates are written in English. `i18n.Catalog` maps English to Polish from
`mister_plis/locale/pl_*.py`: about 1,130 tool strings, 770 UI, 340 reagents and 90 tidy-up. Keys can hold
`{placeholders}`, which are matched as regex patterns, so f-strings get translated, and plurals use
`"one|other"` keys. The same catalogue goes to the browser as `/i18n/pl.js` (`MP.i18n`). Strings missing from
the catalogue stay in English, and `tests/test_i18n.py` checks the catalogue is complete.

---

## 4. Where the data lives

Everything is under `settings.data_path` (default `<repo>/data`; on the Mac Studio,
`~/Library/Application Support/MISTER PLIS/MISTER_PLIS/data`).

| Path | Owner | Format | Lifetime / sync |
|---|---|---|---|
| `uploads/<id>/<file>` | UploadStore | raw files | deleted after `upload_retention_days` (3) |
| `jobs/<job id>/meta.json`, `out/`, `tmp/` | JobManager | JSON + result files | deleted after `job_retention_days` (30), unless the backup is still pending |
| `live/<id>/` | JobManager | live-calculator runs | ~1 h |
| `lab_settings.json` | Backups | JSON | backup folder + delay |
| `label_printer.json` | Printer | JSON | printer address, tape, cut options |
| `feedback.json` | FeedbackStore | JSON list | permanent, local only |
| `people.json` | People | JSON | name merges, local only |
| `assays.json` | `tools/_assays.py` | JSON | lab-saved assay methods, local only |
| `git_branch.json`, `auto_update.json` | updater | JSON | branch chosen to run; nightly update mode |
| `timemachine/` | TimeMachine | **local git repo**: `projects.json`, `<job>/meta.json`, `entry.json`, `out/…` | permanent; every change is one commit; **never pushed** |
| `notes/vault/`, `notes/settings.json` | Notebook | **sparse git clone** of `notebook` | pulled (read-only) |
| `reagents/repo/` | Inventory/Consumables | **git clone** of `inventory`: `.xlsx` workbooks (master), `.csv` copies, `mister_plis*.json` display config, `info/*.json` notes from the lab | edited here, committed, **pushed and merged both ways** |
| `reagents/settings.json` | Inventory | JSON | push on/off, auto-sync interval, last sync |
| `reagents/tidy/` | Tidy | `settings.json`, `last_run.json`, `runs.json` | local |
| *backup folder* (outside `data/`) | Backups | `<person>/<date>_<name>_<keyword> <tool> (<job>)/` + `job-info.txt/json` | copy only, never read back, except when Time Machine retrieves a cleaned-up job |

The stores have a few habits in common:

- **Atomic writes.** Each store writes `*.tmp` and then calls `replace()`.
- **One lock per store.** Each store has a `threading.Lock`/`RLock`. This is safe only because there is one
  process.
- **Few safeguards against editing conflicts.** Reagent saves send a `base` version hash, so a stale edit is
  refused. Other stores simply let the last write win.
- **Identity is a name.** Commits and records carry the person's typed name, and `People` maps old names to
  new ones.

---

## 5. How the code is written

The same patterns show up throughout the codebase:

1. **Service classes with a data path.** Each area is one class built with `data_path` (and maybe a repo URL),
   e.g. `FeedbackStore`, `TimeMachine`, `Inventory`. It owns its folder, its lock and its JSON files. Routes are
   thin wrappers that call methods on the singleton, usually through `asyncio.to_thread` for disk or git work.
2. **Git as a storage engine.** `tmgit.LocalHistory`, `Inventory.git()` and `Notebook.git()` each wrap
   `subprocess.run(["git", ...])` with `GIT_TERMINAL_PROMPT=0` and a timeout. Commits carry trailers
   (`Job:`, `Project:`, `Reagent:`, `Action:`), which the history views later filter on.
3. **Declarative tools.** A `Tool` dataclass lists inputs and a decorated `run(p, ctx)` function. Inputs and
   outputs are small classes, each with `spec()`/`parse()` or `render()`.
4. **Plain-language docstrings and messages.** Every module opens with a docstring that explains it from the
   lab's point of view. User-facing errors are full sentences, translated later.
5. **Defensive reads.** A broken JSON file or workbook falls back to defaults instead of crashing a page, and
   a tool that fails to import is listed as "broken" instead of stopping the app.
6. **Tests via TestClient.** `tests/conftest.py` points `MISTER_PLIS_DATA_DIR` at a temp folder and turns off
   the reagents remote, then drives the real app. Some tests (`test_reagents`, `test_timemachine`) create real
   local git repos in temp folders.

---

## 6. How a new tool is added

The full guide is `docs/ADDING_TOOLS.md`, also shown in the app at `/guide`.

1. Copy `tools/_template.py` to `tools/my_tool.py`. A file whose name starts with `_` is treated as a helper,
   not a tool.
2. Define a module-level `tool = Tool(id=..., name=..., category=..., icon=..., inputs=[...])` and decorate a
   function with `@tool.runner`.
3. That's all. At startup, `registry.Registry.load()` imports every `tools/*.py`, collects each `Tool`
   instance, rejects duplicate ids, and records import errors as "broken tools" with a traceback on the home
   page.

What the framework then provides for free:

```
Tool definition ──► tool.spec() JSON ──► tool.js/widgets.js draw the form (show_if, units, sections, tables, plate)
                                          │ uploads → /api/uploads → data/uploads/<id>/
                                          ▼
              POST /api/tools/{id}/run ──► JobManager.submit → thread pool → tool.parse() → run_fn(p, ctx)
                                          │ ctx.progress/log/out/run(subprocess)/cancel
                                          ▼
              outputs coerced (Metric/Table/Plot/Image/File/…) → files renamed <date>_<person>_<keyword>_<name>
                                          → meta.json → results page, Excel, one-click PDF, backup, Time Machine
```

Options that switch behaviour on:

| Option | Effect |
|---|---|
| `live=True` | re-runs as the person types; the run is not kept in history |
| `background=True` | returns at once and the page shows progress |
| `max_concurrent=N` | queues extra jobs (e.g. one GPU render at a time) |
| `protocol=True` + `@tool.label` | "Add to protocol" and P-touch labels |
| `@tool.suggest(input)` | pre-fills a `SampleTable` or `PlateLayout` from the uploaded files |
| `available=` | disables the tool with a message (e.g. Blender missing) |

Other steps:

- Polish strings go in `locale/pl_tools.py`.
- A new pip dependency goes in `requirements.txt`. The next "Sync with git" installs it.
- Code shared between tools goes in a `tools/_helper.py`, e.g. `_spectra`, `_stats`, `_curves`, `_assays`,
  `_units`, `_spire`, `_scalebar`.
- A tool may keep state of its own. `assay_reagents` saves lab methods to `data/assays.json` through
  `tools/_assays.py`. No framework API exists for this: the tool reads `settings.data_path` directly.

The bundled tools: molarity, dilution, assay_reagents (calculators); fluorescence_77k, chlorophyll, pchlide,
cuvette_assay (spectroscopy / assays); protein_plate; image_scale, image_converter, pdf_converter (images);
blender_render, spire_model (rendering / 3D).

---

## 7. How a large module is added (Time Machine, Reagents, Lab notebook)

No plugin interface exists for large modules. Each one is written by hand and wired into the core in several
places. Taking the existing ones as the pattern, a new module needs:

| Layer | Time Machine | Reagents / Consumables | Lab notebook |
|---|---|---|---|
| Back-end service class | `timemachine.py` `TimeMachine` (+ `tmgit.py`) | `reagents.py` `Inventory`, `Consumables(Inventory)`; `tidy.py` `Tidy` | `notes.py` `Notebook` (+ `obsidian.py` renderer) |
| Singleton created in | `app.py` (top) | `app.py` (top) | `app.py` (top) |
| Routes | **inline in `app.py`** (`/timemachine`, `/api/tm/*`, ~25 routes) | **separate `reagents_web.register(app, page, …)`**, called once from `app.py` | inline in `app.py` (`/notes`, `/api/notes/*`) |
| Background threads | none (git commits run inside the request) | auto-sync loop, tidy scheduler, 20 s push timer (started in `register`) | `auto_sync_loop` (started in `lifespan`) |
| Templates | `timemachine.html` (+ `partials/galaxy.html`; `tm_mode` turns the whole shell dark) | `reagents.html` (+ `partials/flask.html`), the same template serving both spaces | `notes.html` + the side panel in `base.html` |
| JS / CSS | `timemachine.js` (~970 lines), styles in `app.css` | `reagents.js` (~1050), `reagents_admin.js`, `label.js`, `reagents.css` | `notes.js` |
| Sidebar link | hard-coded in `base.html` | hard-coded in `base.html` (two links) | hard-coded, shown if `notes_enabled` |
| Settings / admin UI | in its own page | sections on `system.html` and `settings.html` | section on `system.html` |
| Locale | `pl_ui.py` | `pl_reagents.py`, `pl_tidy.py` | `pl_ui.py` |
| Hooks into the core | "Add to Time Machine" on every result (`app.js`), `_job_dict` adds `in_tm`, People merge renames its entries, reads the backup folder | portion labels through `labels.py`; the order list exports through pandas | the side panel on every page (`base.html`) |
| Config | — | `reagents_repo`, `reagents_branch`, `ollama_url` | `notes_repo`, `notes_branch` |
| Tests | `test_timemachine.py` | `test_reagents.py`, `test_consumables.py`, `test_tidy.py` | `test_notes.py` |

`reagents_web.register()` is the cleanest pattern so far: one function receives `app`, the `page()` renderer
and the service objects, then adds its own routes and threads. It even registers the same set of pages twice
(`SPACES`: reagents, consumables) on two `Inventory` objects. Time Machine and the notebook predate it and live
in `app.py`.

The recipe for a new large module, as the code stands:

1. Write `mister_plis/<module>.py` with a service class that owns `data/<module>/` and its own lock.
2. Write `mister_plis/<module>_web.py` with `register(app, page, service)`, following `reagents_web.py`.
3. In `app.py`, create the singleton and call `register(...)`.
4. Add `templates/<module>.html` (extending `base.html`), `static/js/<module>.js`, and optionally CSS.
5. Add the sidebar link in `base.html`.
6. Add Polish strings in `locale/pl_<module>.py`, and add that dict to the merge in `locale/__init__.py`
   (`PL = {**TOOLS, **UI, **REAGENTS, **TIDY}`).
7. Add any new settings to `config.py` and `config.example.toml`, and admin sections to `system.html` /
   `settings.html`.
8. Add tests that use the `client` fixture.

---

## 8. Synchronisation as it is now

Four flows run through GitHub, plus one local-only history:

```
            developer laptop / Claude Code on the web / another computer
                         │ git push (code)
                         ▼
  ┌──────────── GitHub ─────────────────────────────────────────────────────┐
  │ michalby/MISTER_PLIS     smith-lab/notebook     smith-lab/inventory │
  └──────┬───────────────────────────┬──────────────────────────┬───────────┘
         │ pull --ff-only            │ fetch + sparse checkout  │ fetch / merge (cell-by-cell) / push
         │ (manual, or nightly 3–5h) │ (manual or every 15m–4h) │ (every 15m–4h, + ~20 s after each edit)
         ▼                           ▼                          ▼
  Mac Studio: the code checkout   data/notes/vault (read-only)  data/reagents/repo (read-write)
  pip install if requirements*     ▲                             ▲
  changed → os.execv restart       │ Obsidian Git plugin on       │ the lab's edits in the browser,
                                   │ lab computers pushes notes   │ the tidy-up (Ollama), other agents
                                                                  │ editing the workbook on GitHub
  data/timemachine/.git  ── local only, never pushed
  data/jobs, feedback, people, settings … ── local files only, no sync at all
```

### 8.1 Code (`updater.py`)

- The server runs from a **normal git checkout**. "System & updates → Check" runs `git fetch` and lists the
  incoming commits. "Sync with git" runs `git pull --ff-only origin <branch>`. If any `requirements*` file
  changed, it runs `pip install -r requirements.txt`, then `schedule_restart()` replaces the process with
  `os.execv` on the same port. Jobs still running are listed first, and the person confirms.
- **Branch.** "Run another branch" checks out any remote branch and saves it in `data/git_branch.json`. This
  wins over `git_branch` in `config.toml`.
- **Nightly mode** (`auto_update.json`). Between 03:00 and 05:00, at most once a day, the server checks, pulls
  and restarts, but only if no job is running and the checkout has no local edits.
- **Safety.** It pulls only with `--ff-only` and refuses to update a dirty checkout. It never pushes code.
- **Clients.** Browsers see the new commit through `/api/version` and show a refresh banner.
- **Credentials.** The Mac app (`macos/launcher/main.swift`) clones the repo on first launch, asks for a GitHub
  fine-grained token, and stores it in the macOS Keychain. It then sets `credential.helper=osxkeychain` on the
  checkout. The launcher also creates the venv, keeps the server alive, prevents sleep, and offers a dock menu.

### 8.2 Lab notebook (`notes.py`)

- This is a **one-way pull**: a partial, sparse clone of `notebook`. Only the folders chosen on System &
  updates, plus the files their notes link to, are checked out.
- It reuses the code checkout's credential helper (`_credential_args()`), so **one token** serves all repos.
- A sync is manual or runs every 15 min, 1 h or 4 h. It rebuilds the in-memory index (links, backlinks,
  search) and never restarts the server.
- Authors edit in Obsidian, and the Obsidian Git plugin pushes their changes to GitHub.

### 8.3 Reagents and Consumables (`reagents.py`)

This is the only **two-way** data sync.

- **The master copy** is `wykaz_odczynnikow_kompletny.xlsx` (reagents) and `consumables.xlsx` in
  `inventory`. A `columns` sheet defines each column's type and allowed values, and the repo's
  `AGENTS.md` holds the editing rules for people and agents.
- **Each edit in the browser** goes through the same steps:
  1. It is checked against the column definitions.
  2. It is written into the workbook in place with openpyxl, keeping formatting and the other sheets.
  3. The CSV copy is rewritten.
  4. It is committed as the person, with trailers such as `Reagent: 12` and `Action: edit`.
  5. A 20 s timer then calls `sync()`, so several quick edits go out together.
- **Sync** runs in this order:
  1. `git fetch`.
  2. If the repo has no local history yet, take GitHub's version.
  3. Otherwise `git merge`. If the workbook or CSV conflicts, `_resolve()` runs `_merge_workbook()`: it reads
     the base, ours and theirs versions of the workbook, starts from GitHub's file, and re-applies the cells
     changed here since the common version, keyed by `label_no`/`item_no` and column.
  4. If the **same cell changed differently** on both sides, the merge is aborted and the clashing cells are
     named. Nothing is ever forced.
  5. A conflict in any other file also stops the sync.
  6. Then `git push origin HEAD:<branch>`, unless pushing is turned off.
- **Info from the lab** notes are `info/*.json` files in the same repo, so they sync the same way.
- **The tidy-up** (`tidy.py`) runs inside the server on a schedule:
  1. sync first;
  2. rule-based format fixes;
  3. producer spelling;
  4. a local Ollama model reads the open notes and proposes cell changes.

  Every change takes the same save, commit and sync path, so it cannot clash with the lab's own edits.

### 8.4 Time Machine (`tmgit.py`)

`data/timemachine/` is a **local** git repository. Every keep, move, note, rename, removal or restore is one
commit authored by the person's name. "See history" reads `git log` filtered by trailers, and "restore" checks
out a folder from the parent of a commit. **Nothing is pushed**, so this history exists only on the Mac Studio
disk. Its only off-site copy is whatever the backup folder holds of the original jobs.

### 8.5 What is not synchronised at all

Job results (until the backup copies them), uploads, `feedback.json`, `people.json`, `assays.json`, printer and
backup settings, the tidy-up settings and runs, and the Time Machine repository exist **only on the server's
disk**. If that disk is lost, they are gone, except for backed-up job copies.

---

## 9. What this means for a deployable, shareable version

The current design fits its goal well: one trusted machine on a lab LAN, zero install for users, code updated
from anywhere through GitHub. The points below are what a move to "deployable and shareable" (another lab, a
cloud host, several instances) would run into. They are observations, not changes.

1. **Single-process, single-machine state.** The jobs list, locks, schedulers and push timers are in memory,
   and the stores are files on a local disk. A second instance, or a restart on another host, needs a shared
   database and a job queue, or at minimum one instance pinned to one persistent volume.
2. **The deployment mechanism is the git checkout itself.** The running server pulls its own code, runs
   `pip install`, and `execv`s itself. There is no build artifact or container image, and `requirements.txt`
   has only lower bounds (`>=`) and no lock file, so two installs can end up with different package versions.
   For a hosted deployment this would usually become a versioned image, built in CI and rolled out by the host.
3. **Git is used as a database in three places.** That gives free history and offline editing (Excel in the
   inventory repo), but it is slow per write, serialised per process, and the inventory's cell-merge logic is
   custom code. A shared deployment needs to decide which of these stay git-backed, because people edit them
   outside the app (the notebook and the inventory are two such cases), and which should move to a database
   (Time Machine metadata, feedback, people, settings).
4. **Lab-specific defaults are baked in.** `config.py` defaults point to `smith-lab/notebook` and
   `smith-lab/inventory`. Default notebook folders are Polish paths. The reagent schema (`label_no`, GHS,
   storage A–J) and the consumables columns are in code. Another lab would need these to become configuration.
5. **No authentication or authorisation.** Anyone who can reach the port can edit inventory, restart the
   server, or switch the running branch. Identity is a free-text cookie. Sharing beyond the LAN would need
   logins (e.g. an SSO/OAuth proxy) and roles at the least, especially for System & updates.
6. **Secrets and the host are macOS-specific.** The GitHub token lives in the macOS Keychain and is reused by
   the notes and reagents syncs through the credential helper. Several features assume the server sits in the
   lab:
   - the launcher is a Swift app;
   - scale-bar reading uses macOS Vision;
   - Blender, the Ollama URL and the P-touch printer (raw TCP to a LAN IP) are local to the lab;
   - the backup folder is a mounted path.

   A hosted version needs a secrets store and a way to reach the lab's devices, such as a small local agent or
   print relay.
7. **Large modules are not pluggable.** Each one edits `app.py`, `base.html` (sidebar), `system.html` /
   `settings.html` and the locale files. `reagents_web.register()` already shows the shape of a module
   interface (routes + threads + nav entry). Generalising it would let modules be turned on or off per
   deployment.
8. **The data's only safety net is the backup folder.** Time Machine is described as "kept for good", but its
   git history is never pushed, and feedback, people and settings have no backup. Any hosted design should add
   real backups of `data/`, or of whatever store replaces it.

---

## 10. Test run during this audit

`.venv/bin/python -m pytest -q` — result recorded below.

On a fresh `./scripts/setup.sh --dev` (Python 3.12, Linux):

- **155 passed, 1 skipped**: the skip is the Blender render test (no Blender installed).
- **One flaky test**: `tests/test_tidy.py::test_unclear_notes_and_a_second_try` failed in about 1 of 4 full runs
  and 2 of 6 runs of that file alone.
  - Cause: `Inventory.add_info` stores `created` rounded to whole seconds, and `Inventory.infos()` sorts only
    by `created`.
  - Two notes added in the same second therefore tie, and their order falls back to directory listing order.
  - The test assumes the first note is read first.
  - This is a test or ordering issue, not a data problem. A tie-breaker on the id or an unrounded timestamp
    would fix it.

The run also gave 69 warnings from scipy and scikit-image (NumPy 2.5 deprecations), not from the app's own code.
