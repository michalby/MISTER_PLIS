# MISTER PLIS — architecture

*As of the reorganisation (docs/reorg, phases P0–P8, November 2026). The audit it started from is in
[ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md), kept as history.*

## In one picture

```
GitHub                                              the server (the lab's Mac Studio)
──────                                              ─────────────────────────────────
michalby/MISTER_PLIS (main | any branch) ─────────► the code checkout
                                                       mister_plis/        the base: a complete app on its own
                                                       modules/timemachine Time Machine           ┐ modules: plugged in through
                                                       modules/inventory   Reagents, Consumables   │ mister_plis/modules.py;
                                                       modules/notebook    the lab notebook        ┘ the base never names them
the lab's tools (ours: smith-lab/lab-tools) ► <data>/tool-sources/lab/      ┐ tool sources (mister_plis/toolsources.py);
other public tool repositories (pinned) ──────────► <data>/tool-sources/<name>/   ┘ or folders on the machine (tool_folders)
                                    their packages ► <data>/tool-packages/<name>/   (pip --prefix; beside the app's own Python)
the lab's inventory (ours: inventory) ◄─ cell by cell ─► <data>/modules/inventory/repo
the lab's notebook (ours: notebook) ── read-only ──► <data>/modules/notebook/vault
                                                    (which repositories: the lab's setup — a lab file, labs/*.toml, or /setup)

                                                    <storage>/  (a folder chosen on Settings → Jobs & backup; default: <data>)
                                                       jobs/<job id>/  job.json · inputs/ · out/ · tables/
                                                       jobs/index.json the list (a rebuildable cache)
                                                       tool-data/<tool>/ what tools save for the lab
                                                       modules/timemachine/ kept results + their local git history
                                                    <backup>/   (a NAS, a disk)
                                                       <person>/<date>_<name>_<keyword> <tool> (<job id>)/
                                                          README.md · results.xlsx · plots/ · report.pdf · files/ · mister-plis/
                                                       Time Machine/  timemachine.bundle · projects.md · readable copies
                                                       mister-plis-index.json  the catalogue of backups
```

**Everything written to disk is English** (job records, result files, backups). Only the interface is translated:
English by default, Polish per browser. Results stored in English are translated when shown, with the help of
each job's phrase book (`i18n.recording` / `i18n.phrases`).

## The base (`mister_plis/`)

| | |
|---|---|
| `app.py` | the FastAPI app: the services, the base's pages and API, and then the modules (loaded last, so a base route always wins) |
| `config.py` | `ROOT` (the code folder) and `HOME` (this instance's folder: config.toml, data/, secrets/, logs/; `MISTER_PLIS_HOME`, else the same as `ROOT`). Relative paths in the settings are relative to `HOME`. `Settings` from config.toml / `MISTER_PLIS_*` (`storage_dir`, `modules`, `[module.<id>]` tables or `MISTER_PLIS_MODULE_<ID>_<KEY>`, `fetch_tool_sources`, `tool_folders`, `lab_file`…); unknown keys are reported at start. `settings.explicit`: what this machine sets, which wins over what the lab stored |
| `Dockerfile`, `deploy/` | HTTPS with Caddy (`Caddyfile`, `docker-compose.https.yml`); the Docker image (code in `/app`, the instance in the volume `/srv/mister-plis`; `deploy/docker-entrypoint.sh` gives Docker's volume folders to the server's user and drops root), the compose file and the systemd unit (docs/DEPLOY_LINUX.md, DEPLOY_WINDOWS.md) |
| `formats.py` | the formats register: which version of each on-disk format this version writes and reads (docs/FORMATS.md §15) |
| `updates.py`, `releasekeys.py` | how this instance is updated (the release feed is checked against the release keys in `releasekeys.py`: docs/RELEASES.md; packages from `requirements.lock`, made by `scripts/lock.sh`): the channel (git, Docker, release) by `install.kind()`, the release feed, and the snapshots of the lab's settings made before every update; `CHANGELOG.md`, `scripts/release.sh` and `scripts/make_feed.py` make a release by hand |
| `install.py` | how this instance was installed (`MISTER_PLIS_INSTALL`: docker, mac-app, service; else checkout or package) and where its code and its own files are (Settings → Server & updates) |
| `transfer.py` | moving a whole server: everything it holds copied into one checked folder (Settings → Server & updates → Move this server, `python -m mister_plis transfer`), and brought into a new server (its setup page). docs/BETA.md |
| `labsetup.py` | the lab's setup (docs/LAB_SETUP_PLAN.md): a lab file read, compared (old → new) and applied into the stores the pages use; `<data>/lab.json` (set up or not; a server from before counts as set up); `/setup`; `python -m mister_plis setup / export` |
| `toolkit.py` | **the tools' API** (`TOOLKIT_API = 1`, `TOOLKIT_VERSION = "1.1"`, `__all__`). Tools import nothing else from the base (`tests/test_tool_boundary.py`). |
| `toolsettings.py` | what a tool declares it needs on this server (`Tool(settings=…)`, toolkit 1.1): `<data>/tool-settings/<tool id>.json`, set on Settings → Tools |
| `inputs.py`, `outputs.py` | form fields and result types; `translate_output` shows a stored (English) result in the reader's language |
| `registry.py`, `toolsources.py`, `pins.py` | tools from tool sources (git repositories), `tool_folders`, and the sources that come with a release (`bundled-tools/`), each as its own package `mp_tools_<name>`; a source's packages installed with the instance (`<data>/tool-packages/`) only if they change none of the app's (`pins.py`) |
| `catalogue.py` | a tool catalogue to browse on Settings → Tools and add sources from (pinned and off, as any source that isn't the lab's own) |
| `runners.py` | where a job runs: a runner gets a `JobSpec` (the job as JSON) and reports back through the JobManager's events; `LocalRunner` runs it in threads of this process; `ProcessRunner` (the server's, from 0.17.0) runs each job kept in the history in a process of its own (`jobproc.py`: no tokens in its environment; with `job_user`, as another user through `sudo`), live runs in its threads |
| `jobs.py`, `jobstore.py`, `jobformat.py` | the jobs: the list, their records, `JobSpec` (run by a runner, `runners.py`); one folder per job with `job.json` (v1; a v0 `meta.json` is still read); `index.json`; finished jobs loaded on first use |
| `storage.py` | the storage folder (choose, move, checked copies); `move_folder_once` for modules whose data moved |
| `backup.py`, `export/` | backups anyone can read (README, workbook, plots, PDF) with a manifest that lets them be imported back; the strict cleanup rule; the backup catalogue (v0 and v1) |
| `modules.py` | the module interface: `Module`, `NavItem`, `Hooks`, `ModuleContext`; loading, nav, panels, scripts, styles, shells |
| `i18n.py`, `locale/` | the catalogue (English → Polish): the base's own `pl_ui.py`, plus every tool source's and module's `locale/pl.py` |
| `gitutil.py`, `text.py`, `updater.py` | one git runner (with `credentials=True`: the instance's tokens, then the code checkout's helpers, e.g. the Keychain); accent folding; the code's self-update and branch choice (its fetch and pull use the tokens too) |
| `access.py`, `accounts.py` | who may do what: every route that changes something is marked `settings_access` (the lab's settings: admins) or `work_access` (everyday work); with no account the server is open, as before (`access.mode()` "open"); the lab's first account (made with the setup code) turns **sign-in** on: every page and request then needs a signed-in person (`access.PUBLIC` lists the exceptions), who the person is comes from their account (`prefs.signed_in_name`, so `ctx.who` and every name recorded is the account's), and admins see the activity log. `accounts.py`: accounts (`<data>/accounts.json`, scrypt hashes), sessions (`secrets/sessions.json`), sign-in throttling, the activity log; `python -m mister_plis account list|add|reset`. And `known_host()`: a request must use one of the server's own names (DNS rebinding); `same_site()`: a change must come from the server's own pages, not another web site (`tests/test_access.py`, `tests/test_accounts.py`, `tests/test_security.py`) |
| `setupcode.py` | the setup code: until a server is set up, a change from another computer needs it (`secrets/setup-code`, printed at start, `python -m mister_plis setup-code`); none on the server's own computer (docs/SECURITY_AUDIT.md M4) |
| `fileorigin.py` | stored files from an origin of their own: a files-only server in a thread (`files_port`, default port + 1; `files_origin`), signed links to a job's folder (`files_base`, 2 hours, `secrets/files-key`), used by the pages when they reach it (`MP.filesFrom`), else the app's own links |
| `serving.py` | how stored files are served so nothing in them runs (pictures, PDF, text, audio, video shown and sandboxed; anything else downloaded; `ctx.file_response` for modules), the headers on every response (no framing, `nosniff`, a Content-Security-Policy allowing only the app's own scripts), and `safe_link()` for links people or catalogues give (docs/SECURITY_AUDIT.md) |
| `credentials.py` | the instance's git tokens, one per host, owner or repository (`<instance>/secrets/git-credentials.toml`, `MISTER_PLIS_GIT_TOKEN`), and git's credential helper that hands them out (Settings → Server & updates → GitHub access) |
| `labels.py`, `report.py`, `printout.py`, `excel.py`, `plotting.py` | label printer, PDFs, workbooks, plot theme |
| `feedback.py`, `people.py`, `prefs.py` | small stores; per-browser settings in cookies |
| `templates/`, `static/` | pages built on `base.html`, which has slots for modules (nav, panels, shell parts, scripts, styles) |

## The pages

The sidebar has the tools, **Jobs & results**, the modules' spaces, and at the bottom **Add a tool**, **Feedback** (the
list of everything sent with the glowing button, with the number still open) and **Settings**. Settings is one page
with tabs switched in the browser (`MP.tabs` in `static/js/app.js`; the address follows the tab, `/settings#tools`):
You, Exports & printing, Tools, Jobs & backup, a tab per module that has one, People, Server & updates. Each tab
(`templates/settings/<tab>.html`) asks the server for its data the first time it is opened (`MP.whenShown`).
`/system`, the page it replaced, leads to Server & updates.

## Modules (`modules/<id>/`)

See [MODULES.md](MODULES.md). Each module has a `Module(...)` in `__init__.py`, its own routes, templates, static
files, translations and tests. It reaches the base only through `ModuleContext` and `Hooks`. The base runs with
none of them (`modules = "none"`; `tests/test_modules.py` checks this, and that the base never names a module).

| Module | Data | Joins the base's pages through |
|---|---|---|
| `timemachine` | `<storage>/modules/timemachine/` (+ its copy in `<backup>/Time Machine/`) | the Add to Time Machine button, the job-list mark and filter, People counts, `in_tm` on jobs, a panel on Settings → Jobs & backup |
| `inventory` | `<data>/modules/inventory/` (a clone of the lab's inventory repository) | two sidebar links, its own Settings tab, background sync and tidy-up |
| `notebook` | `<data>/modules/notebook/` (a sparse clone of the lab's Obsidian vault) | the side panel on every page (shell parts), a sidebar link, its own Settings tab, background sync |

## Tools

Tools come from tool sources ([ADDING_TOOLS.md](ADDING_TOOLS.md)): the lab's own repository (ours:
`smith-lab/lab-tools`), given when the lab is set up, and any other repository added on Settings → Tools → Tool
sources. Each has a `mister-plis-tools.toml`. A source that isn't fetched yet is cloned when the server starts. With no
source at all, it runs and says there are no tools yet. A folder on the
machine can be loaded too (`tool_folders` in config.toml): a working copy while someone writes tools, which stands in
for the source of the same name. A tool is one file with a `Tool(...)` and a `run(p, ctx)`, and the base does the
rest: the form, the job, the result page, the PDF, Excel, file naming, backup, Time Machine. The base itself holds no
tools, except two toys for its own tests (`tests/fixtures/toolsource/`).

## Setting a lab up

Nothing in the code names one lab. A new server leads its pages to **/setup** until it is set up; there, or with
`python -m mister_plis setup <lab file>`, or `lab_file` in config.toml on first start, a **lab file** (`labs/*.toml`:
ours, and `template.toml` with every setting) gives its name and language, tool sources, which modules are on and each
module's own settings (`Module.setup_fields` / `configure`), folders, printer and updates. Applying it writes into the
same stores the Settings page edits, so the pages stay the one place things change; it can be applied again and shows
each change first. Settings → Server & updates → Lab setup downloads a server's settings as a lab file. See
[LAB_SETUP_PLAN.md](LAB_SETUP_PLAN.md).

## Data formats

[FORMATS.md](FORMATS.md) describes every format: v0 (before the reorganisation, still read everywhere) and v1 (job
folders, the storage folder, backups). The frozen v0 fixtures in `tests/fixtures/*_v0/` must stay readable.

## Moving code and data between machines

| What | How | Direction |
|---|---|---|
| The base and its modules | `git pull --ff-only` on **Sync with git** or nightly; **Run another branch**; `pip install` if requirements changed; the server restarts itself | GitHub → server |
| Tools | **Tool sources**: Check / Update (fast-forward, or a reviewed pin move) / Branch; restart to load | GitHub → server |
| The inventory | each edit is committed and pushed about 20 s later; Sync merges GitHub's changes cell by cell (`repo` can also be a git folder on the machine) | both ways |
| The notebook | read-only sync of the chosen folders (from GitHub, or a git folder on the machine) | GitHub → server |
| Jobs | the backup folder (readable, verified); **Import from backup** brings them back | server → backup → server |
| A whole server | **Move this server** → a checked folder → the new server's setup page (**Everything from another server**) | old server → folder → new server |
| Time Machine | copied into the backup folder, in `Time Machine/` (a git bundle plus readable copies), whenever it changes; **Restore from the backup** | server → backup → server |

## Testing

`.venv/bin/python -m pytest` runs `tests/` (the base, with the test tools of `tests/fixtures/toolsource/`, loaded
through `tool_folders`) and `modules/*/tests/`. The shared fixtures are in the repository's `conftest.py`. There is
no CI (the owner's choice, 2026-11-12): the tests are run by hand, before every push. The code must still work on Linux,
macOS and Windows (it passed on all three before CI was removed): build paths with
`pathlib` and `file://` addresses with `Path.as_uri()`, never by gluing strings, and give files a name with
`toolkit.safe_filename()` (it keeps Windows' rules), and read and write text with `encoding="utf-8"` (Windows' default
is another code page). `tests/test_settings_browser.py` drives the
Settings tabs in Chromium when the `playwright` package is installed (it is skipped otherwise). The tools repository has its own tests (each
tool, the tools inside the app, the toolkit boundary), run by hand (its README says how); it has no CI.
