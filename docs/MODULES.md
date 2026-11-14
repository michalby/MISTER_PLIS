# Writing a module

A **module** is a large feature with its own pages, data and background work, such as Time Machine, the inventory
or the lab notebook. It lives in `modules/<id>/` and plugs into the base through one interface,
`mister_plis/modules.py` (`API = 1`). **The base never imports a module by name** (`tests/test_modules.py` checks
this), so a module can be switched off, or added, without editing the base.

A **tool**, by contrast, is one file with a form and a `run` function; see [ADDING_TOOLS.md](ADDING_TOOLS.md).
If what you are building has its own pages, its own data, or background work, it is a module.

## The folder

```
modules/<id>/
    __init__.py         module = Module(...)  — the only thing the base reads
    service.py          the module's own logic (a class holding its data folder and a lock)
    web.py              register(app, ctx, service): its routes
    templates/          its pages; found as "<id>/<name>.html", and they can {% extends "base.html" %}
        panels/         small templates the base includes on its own pages (see "panels" below)
    static/             served at /m/<id>/static/
    locale/pl.py        PL = {"English text": "Polish text", …}; merged into the catalogue (the base's own texts win)
    tests/              collected by the root pytest run (testpaths in pyproject.toml)
    MODULE.md           what it does, its data, its settings
```

## `Module(...)`

| Field | What it does |
|---|---|
| `id`, `name` | `id` is also its URL prefix, its data folders' name and its `[module.<id>]` table in config.toml |
| `setup(ctx) → service` | builds the module's object(s), once, when the app starts; moves old data if needed |
| `register(app, ctx, service)` | adds routes. Modules are loaded **after** the base's routes, so a base route always wins a clash. Put fixed paths (`/api/x/backup`) before patterns (`/api/x/{id}`). |
| `nav=[NavItem(label, href, icon \| icon_template, title, order)]` | links in the sidebar, under "Jobs & results" |
| `threads=[fn(service)]` | daemon threads started with the app (sync loops, schedules) |
| `templates`, `static` | its folders (above) |
| `scripts={"*": [...], "<page kind>": [...]}` | scripts from `static/` added to every page (`"*"`) or to pages whose `{% block page %}` is that kind (`jobs`, `settings`, `tool`…). They load after `app.js` and before the page's own script. On Settings, start loading data with `MP.whenShown(element, fn)`: it runs `fn` when the tab holding `element` is first opened. (The old kind `system` is read as `settings`.) |
| `styles=[...]` | stylesheets from `static/`, on every page |
| `settings_tab=SettingsTab(label, icon, order)` | a tab of its own on the Settings page, `/settings#<id>`, holding its `panels["settings"]`. `order` places it among the base's tabs (You 10, Exports & printing 20, Tools 30, Jobs & backup 40, People 80, Server & updates 90). |
| `panels={"settings" \| "settings:<tab>" \| "jobs_filters" \| "jobs_lede": [template]}` | templates the base includes in those places. `"settings"`: the module's own tab (without one, the end of Server & updates); `"settings:<tab>"`: one of the base's tabs (`you`, `exports`, `tools`, `jobs`, `people`, `server`), e.g. Time Machine's backup on `settings:jobs`. `"settings:jobs-storage-map"` / `"settings:jobs-backup-map"`: an `<li>` in the overview of the two folders at the top of Jobs & backup, saying what the module keeps in that folder. The old key `"system"` is read as `"settings"`. |
| `hooks=Hooks(...)` | see below |
| `shell={"html_class", "head", "topbar", "aside"}` | parts of the page shell on every page (the lab notebook's side panel): a class on `<html>`, a template before the first paint, one in the top bar, one after the main column. Left out on pages that pass `hide_side_panels=True`. |
| `enabled=lambda service: bool` | the module switched off by its own settings (e.g. no repository set): its links, scripts, styles, panels and shell parts are left out — except its own Settings tab and that page's scripts, where it can be switched on again |
| `setup_fields=[SetupField(key, label, kind, help, choices, placeholder, group)]` | its questions when the lab is set up: on the setup page, and the keys of a lab file's `[module.<id>]` (docs/LAB_SETUP_PLAN.md). `kind`: `text`, `repository`, `branch`, `choice`, `bool`, `number`, `list` (one per line), `tool` (chosen from the loaded tools; `choices=(("", "label of none"),)`). A `repository` is checked for access on the setup page. The help is shown under the input: say what the setting *does*, not only what it is. |
| `setup_groups=[SetupGroup(id, title, help, folded)]` | headings over its questions on the setup page (a field's `group` is a group's `id`; `""` is the first). `folded=True`: shown closed, with its first choice as a summary — for settings rarely changed. |
| `setup_intro="…"` | one sentence on the setup page under the module's name: what it is for |
| `lab_settings(ctx, service) → dict` | its current settings as a `[module.<id>]` table (Download this lab's file, `python -m mister_plis export`) |
| `configure(ctx, service, values, apply, who) → [row]` | a `[module.<id>]` table checked (`apply=False`: change nothing) or stored. A row is `{"key", "old", "new", "status", "note"}`, status `change`, `same`, `skip` (a note why, e.g. set in config.toml), `error` (the note says what is wrong), and once applied `done`. `mister_plis.modules.plan_rows(values, current, checks, explicit)` makes the rows; the module then applies the changed ones. |

## The lab's setup: stored settings, config.toml, defaults

A setting a lab chooses (on the module's Settings tab, the setup page, or a lab file) is **stored** in the module's
own data folder (e.g. `<data>/modules/<id>/settings.json`). The order is: `ctx.settings` (config.toml or
`MISTER_PLIS_MODULE_<ID>_<KEY>` on this machine) › what is stored › the module's own default. A default never names one
lab's repository: with nothing set, the module works without it or is off. When a module starts storing a setting it
used to take only from config.toml or a default, it stores what an existing server was using the first time (e.g. the
address its clone came from), so nothing changes for that server. A setting changed while the server runs takes
effect at once where it can; data that no longer fits (a clone of another repository) is renamed
(`gitutil.set_aside`: `<name>.before-<date>`), never deleted. `gitutil.check_address` and `check_branch` check what a
person typed.

## `ctx` — what a module may use from the base

`ctx.id`, `ctx.storage` (`<storage>/modules/<id>/`, for job-like data that must be kept and backed up), `ctx.data`
(`<data>/modules/<id>/`, for its own state and clones of other repositories), `ctx.settings` (the `[module.<id>]`
table of config.toml, plus `MISTER_PLIS_MODULE_<ID>_<KEY>` environment variables: only what this machine sets; they
win over what the module stores), and the base's services:

- `jobs`, `backups` (with `backups.catalogue`), `uploads`, `registry`, `printer`, `feedback`, `data_path`,
  `storage_path`, `lab_name`;
- `page(request, template, **context)` (with `dark=True` and `shell_class="…"` for a page in its own style);
- `tr`, `who(request)` (the person's name: their account's once the lab has accounts, else the name typed in the top
  bar — never take a name from the request itself), `tool_name(job)`, `people_names()`, `canonical(name)`, `job_or_404(id)`;
- `results_pdf(request, job)`, `table_pdf(request, table, title, filename, kicker=, params=, params_caption=, note=, size=)`
  (any table as a PDF in the app's own look), `files_base(request, folder)` (a signed link to a folder on the stored files' own origin: put it in a
  JSON answer as `files_base` and the pages' `MP.filesFrom(d)` points the file links there), `file_response(path, download=False)` (a stored file — a job's, a kept
  result's — served so that nothing in it can run: pictures, PDF, text, audio and video are shown, sandboxed;
  anything else, HTML and SVG among them, is downloaded; `mister_plis/serving.py`), and `git(*args)`;
- `settings_access`, `work_access` — the marks of a route that changes something (below);
- `services_address(name)` — an address the lab once set for the whole lab in `[services]` (`"model"`: a local model),
  `""` if none. No longer set since 0.19.0 (each module keeps its own address); read only so a module can take an old
  one over once, as the inventory does with its `ollama_url`.

**No inline scripts** (from 0.17.0): the pages allow only scripts from the server's own files (Content-Security-Policy,
`mister_plis/serving.py`), so a module's templates load their code from `static/` (`<script src="/m/<id>/static/…">`),
put data in `<script type="application/json">`, and attach event handlers in JavaScript, never `onclick="…"`
(`tests/test_security.py` checks every template).

**Every route that changes something** (POST, PUT, PATCH, DELETE) says which kind of change it is, with exactly one of
the two: `@app.post("/api/x", dependencies=[Depends(ctx.settings_access)])` for the lab's settings (what Settings and
the setup page change: repositories, folders, syncing with the lab's repository…), `ctx.work_access` for everyday work
(adding an item, keeping a result). Today everyone may do both; the login will let only some people change settings.
`tests/test_access.py` fails while a route has no mark. (`mister_plis/access.py`; docs/PREP_PLAN.md R9.)

A module may also import the base's public helpers (`mister_plis.errors`, `mister_plis.jobs.Job`,
`mister_plis.backup`, `mister_plis.toolkit`…). Everything else in the base is internal.

## Hooks: joining in on the base's own pages

| Hook | Used for |
|---|---|
| `job_flags(job, full) → dict` | extra fields on every job in the API, e.g. `{"in_tm": True}`. `full=False` is the job list: keep it cheap. |
| `people() → [(name, when, what)]` | counts on Settings → People (`what` is a counter name, e.g. `"kept"`), or `what=None` for a name to offer when choosing a person |
| `rename_person(old, new, by) → {what: n}` | when two names of one person are merged |

On the browser's side, `app.js` defines `MP.hooks`:

- `MP.hooks.resultActions.push((job, toolSpec) => button | null)`: a button above every finished result;
- `MP.hooks.jobMarks.push(job => element | null)`: a mark in the job's row.
- `MP.exportBtn(kind, {href | onclick, title, label})`: every print or download button in the app looks the same — `"pdf"` in the accent colour with the file icon, `"xlsx"` (Excel), `"csv"` and other formats plain with the download icon. Put them in the order PDF, Excel, CSV.

A filter on Jobs & results is a `jobs_filters` panel with `<div class="seg" data-flag="<job field>">` buttons
(`data-want=""`, `"in"`, `"out"`). `jobs.js` reads it by itself.

## Switching modules on and off

Chosen when the lab is set up (the setup page, or `[modules] on = [...]` in a lab file; kept in `<data>/lab.json`). On
one machine, config.toml wins: `modules = "timemachine, inventory"`, or `modules = "none"`. With neither, every folder in
`modules/` is loaded. A change takes effect at the next start. A module that fails to load is listed on the home page with the broken tools, and the rest keeps
working.

## The worked example: Time Machine

`modules/timemachine/` (reorg phase P4):

- **`__init__.py`:**
  - `setup` moves the old `<data>/timemachine/` to `ctx.storage` once (copy, compare, `git fsck`, rename the
    old folder);
  - the hooks: `job_flags` gives `in_tm` / `tm_root`, `people` gives the "kept" count, `rename_person`;
  - the sidebar link with the animated galaxy (`icon_template="partials/galaxy.html"`);
  - `tm-button.js` on every page (the "Add to Time Machine" button through `MP.hooks.resultActions`);
  - panels for Jobs & results (its filter and a sentence) and Settings → Jobs & backup (Time Machine in the backup folder, `panels["settings:jobs"]`);
  - a thread that backs it up every 10 minutes when it changed.
- **`service.py`, `history.py`:** the kept results and their local git history.
- **`web.py`:** `/timemachine` (a dark page: `dark=True, shell_class="tm"`) and `/api/tm/*`.
- **`backup.py`:** its own copy in `<backup>/Time Machine/`, and restoring from it.

## Checklist for a new module

1. `modules/<id>/__init__.py` with `module = Module(id="<id>", …)`.
2. Data in `ctx.storage` (kept, backed up) or `ctx.data` (state). Never write anywhere else.
3. Routes in `web.py`, each that changes something marked `settings_access` or `work_access`; pages extend
   `base.html`; texts in English, with Polish in `locale/pl.py`.
4. Tests in `modules/<id>/tests/`. Use the shared fixtures in the repository's `conftest.py` (`client`…).
5. `.venv/bin/python -m pytest` must pass, including `tests/test_i18n.py` (every text has Polish) and
   `tests/test_modules.py` (the base doesn't name the module; the base runs without it).
