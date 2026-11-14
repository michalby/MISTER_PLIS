# MISTER PLIS

**M**ulti-purpose **I**nterface for **S**cientific **T**ools, **E**xperimental **R**esults,
**P**rocessing, **L**aboratory **I**ntegration & **S**tatistics.

A web toolbox for the lab. It runs on one machine in the lab (a Mac, a Linux server, or Windows with Docker) and
everyone uses it from their browser — no installs, no logins. Each tool is a single Python file; the web interface,
file uploads, background jobs and result pages are generated for you.

**For any lab.** Nothing in the code names one lab: which repositories hold a lab's tools, inventory and notebook, its
folders and printer come from its **lab file** (`labs/<lab>.toml`; ours is [labs/example.toml](labs/example.toml),
every setting is in [labs/template.toml](labs/template.toml)) or from the **setup page** that a new server opens by
itself — see [Set it up for your lab](#set-it-up-for-your-lab). The tools and repositories named below are our lab's.

**Tools:**

- **Molar solution** — pick a compound, enter molar concentration and volume → mass to weigh and % (w/v).
- **Stock solution** — C₁·V₁ = C₂·V₂: stock volume and diluent (or solve for any other value).

  Results collected in the protocol also print as reagent labels (name, concentration, person, date) — one strip of tape on the lab's Brother P-touch PT-E550W over Wi‑Fi, half-cut between labels. Set its address in Settings → Exports & printing; no macOS printer or driver is needed.
- **77 K fluorescence** — background subtraction per excitation (file prefix A/D = 412 nm, B/E = 440 nm,
  C/F = 470 nm), normalisation (PSII / PSI maximum, equal area, max), mean ± SD bands, PSI/PSII
  ratio with statistics between lines, Gaussian decomposition at the marker wavelengths ± 2 nm.
- **Chlorophyll concentration** — Chl a, b, a+b, carotenoids from Shimadzu tables or full spectra;
  volume for a set amount of chlorophyll, buffer to equalise samples, 1:1 denaturation buffer, final
  concentration.
- **Pchlide fluorescence** — relative protochlorophyllide (peak, area or Gaussian), dilution and
  per-amount correction, statistics.
- **Protein assay (96-well)** — click-to-assign plate layout (blank / standards / samples with
  dilutions), linear / quadratic / 4PL standard curve.
- **Assay reagents** — Bradford, Bradford micro, Bio-Rad DC (a modified Lowry), classic Lowry, BCA,
  Folin–Ciocalteu total phenolics, or your own method: volumes per cuvette → how much of each reagent
  (and its components) to prepare for N samples + standards + blanks, the standard dilution series
  from a stock, the protocol with your volumes, and names to type at the spectrophotometer — all of it on
  one page, printed with the **PDF** button. Methods
  with your volumes can be saved for the whole lab.
- **Cuvette assay (standard curve)** — Shimadzu photometric CSVs (or spectra): pick blanks /
  standards / samples (guessed from the names: "blank", "250", "std3", "WT_2", "mut x10"), fit a
  linear / quadratic / 4PL curve with residuals plotted, LOD/LOQ, concentration in the original
  sample (dilution, different pipetted volume), per g of tissue, volume for a set amount; or reuse a
  saved slope and intercept.
- **Same-scale resize** — finds the scale bar burned into micrographs and resizes a set of images
  to one nm-per-pixel (or uses the magnification from the file name).
- **Image converter** — TIFF → PNG, HEIC, JPEG…, batch resizing.
- **PDF converter** — PDF pages → PNG/JPEG/TIFF at a chosen dpi (200 by default), or images → one PDF.
- **Blender render** — queue one or more .blend files, GPU rendering with chosen or saved settings.
- **SPIRE 3D model** — the gyroid / diamond slice you set up in SPIRE (lattice parameter, volume proportion or level set, hkl,
  slice size and position, membranes, filled channels — typed in or read from SPIRE's parameter file) as a closed,
  manifold mesh (STL / OBJ / PLY / GLB) for 3D printing or Blender, with the model's projection to compare with the SPIRE image.

**Lab notebook.** The lab's Obsidian notes (a git repository; ours is `notebook`) are readable next to every
tool: the **Notes** panel on the right (button in the top bar, or press **N**) lists the notes, searches
titles and text (accents optional: "stezenie" finds "stężenie"), and follows `[[links]]` between notes,
with "Linked from" under each one. Drag its left edge to make it wider; close it to use only the tools.
It starts open on a wide screen (each browser remembers if you close it) and closed on a small one,
where it opens over the page. **Lab notebook** in the sidebar shows the same notes as a full page.
The notes are a read-only copy: edit them in Obsidian, then **Settings → Lab notebook → Sync notes** (manual —
it never restarts the server). The same tab chooses which folders the lab sees (ours:
`Protokoły/Metody` and `Protokoły/Odczynniki`); only those folders, and the pictures their notes use, are
downloaded to the server. Links to notes in other folders appear as plain text.

**English, with a Polish interface on request.** The app is in English by default; **PL / EN** in the top-right
corner (or Settings → You) switches the interface to Polish per browser. Only what is on screen is translated (and the PDF
printed from a result page, which matches the page). Everything written to disk is English, whoever ran the job:
the job records, the result files (Excel, CSV…), backups and Time Machine. A result kept in English is shown in
Polish when it is opened with a Polish interface. The translations live in `mister_plis/locale/` (English →
Polish); anything not in there simply stays in English.

**Feedback.** The glowing button in the middle of the top bar sends a bug (red), an inconvenience (orange) or
a feature idea (green), with the page it came from and your name. They are listed on the **Feedback** page (in the
sidebar, with the number still open), where each can be marked done or deleted, and the open ones copied as a Markdown list
for whoever implements them. They are stored on the server in `data/feedback.json`.

**Accounts.** Until the lab makes its first account, the server is open to anyone on the network, as it always was.
**Settings → People → Accounts**: an admin makes their own account (the first one, which turns sign-in on), then
everyone else's — each gets a temporary password and chooses their own at the first sign-in. Admins change Settings;
members do the everyday work. The name on everyone's results is their account's. The same panel shows the activity
log (sign-ins, accounts, changes to the settings). Locked out: `python -m mister_plis account reset "<name>"` on the
server. docs/SECURITY_AUDIT.md §7.

**People.** **Settings → People** lists everyone who added anything — ran a job, sent feedback or kept something in Time Machine — under
the name set in the top bar, with how many jobs and when they were last here; a name opens their jobs in **Jobs & results**. **Merge into…** joins two names of one
person ("Ola" and "Ola Nowak"): everything under the old name moves to the kept one, and a browser still set to the old
name is counted as the kept one, so the old name doesn't come back. Merges are remembered in `data/people.json`.

**Settings** (in the sidebar) is one page with tabs that switch instantly; the address follows the tab
(`/settings#tools`), so a tab can be linked. Each setting is marked **this browser** (kept in a cookie) or **whole lab**
(kept on the server):

| Tab | What is there |
|---|---|
| **You** | your name, language, theme (also toggled in the top-right corner), the decimal separator on screen, whether forms remember their inputs |
| **Exports & printing** | numbers in Excel/CSV downloads, the PNG resolution of plots; the label printer (whole lab) |
| **Tools** | the tool sources, the settings a tool needs on this server (e.g. where Blender is), tools that didn't load |
| **Jobs & backup** | where jobs are kept and how long, the backup folder, clearing the job history, Time Machine's own backup |
| **Reagents & consumables**, **Lab notebook** | each module's own tab (sync, history, tidy-up, columns, shown folders) |
| **People** | everyone who added anything, merging two names |
| **Server & updates** | the lab's name, how people reach the server, the running version, Sync with git, another branch, updating by itself, the server, Restart |

Dates are always shown as yyyy-mm-dd. The old address `/system` opens Server & updates.

**Results, file names and backup.** Each job is one folder in the storage folder, `<storage>/jobs/<job id>/`: its record
`job.json` (who, when, which tool and version, settings, results), the uploaded files it used (`inputs/`), its result
files (`out/`) and every result table in full (`tables/`); `<storage>/jobs/index.json` lists them all. The storage
folder is the data folder unless another one is chosen (Settings → Jobs & backup; on the Mac Studio by default
`~/Library/Application Support/MISTER PLIS/MISTER_PLIS/data/`). Jobs are deleted
after `job_retention_days` (30). Everyone sees everyone's jobs under **Jobs & results**, with a search bar (file
names, keyword, title, tool, person, job number — accents optional) and filters (who, which tool, when). A job can
have a **title** (typed above the Run button, or set and changed later above its results), shown after the tool's
name: "Chlorophyll concentration — WT vs mutant, day 3". Every result file is named `<date>_<your name>_<keyword>_<file>`, e.g.
`2026-10-19_Anna-Kowalska_WT-light_chlorophyll_results.xlsx`; the keyword is typed above the Run
button (files inside .zip archives keep their own names). If a backup folder is set in Settings → Jobs & backup
(a mounted NAS, an external disk…), finished results are copied there right away or after 1, 3 or
7 days, as `<backup>/<person>/<date>_<name>_<keyword> <tool> (<job id>)/`, in a form anyone can read without
MISTER PLIS:
- `README.md`: who, when, which tool, the input files, the settings, and every result in order;
- `results.xlsx`: every table on its own sheet, plus a Summary and every plotted value;
- `plots/`: each plot as a page that works offline;
- `report.pdf`, and the tool's own files in `files/`.

The `mister-plis/` folder inside holds what MISTER PLIS needs to bring the job back exactly: its record, input files,
full tables, and a checksum of every file. While a backup folder is set, a job is deleted from the server only once its
backup is there and checks out. **Back up now** copies everything pending at once; **Check the backups** compares every
copy with its checksums; **Update old backups** rewrites backups made before this form. **Jobs & results → Import
from backup** finds jobs in the backup folder (also ones long cleaned up from the server) and brings them back as
they were; Time Machine reads the backup folder the same way.

**Time Machine** (sidebar, the turning galaxy) keeps results worth keeping — the ones a study is built on.
It is its own space: always dark, under a starry sky. **Add to Time Machine** above any finished result copies it
(files, settings, who ran it) to `data/timemachine/<job id>/`, which is never cleaned up; the original stays in
Jobs & results and follows the usual cleanup and backup. On the Time Machine page, typing a job number (or just
its last six characters) finds the job in Jobs & results or, once cleaned up, in the backup folder, and copies it
in. Every result page and printed PDF shows the job number with a small galaxy mark. Kept results can be searched,
filtered by person / tool / project, browsed by month, given a note, and printed. A kept result can be in any
number of **projects**; results are added to, moved between and taken out of projects one by one or several at
once, and the list draws one lane per project (a result in several projects joins their lanes). Time Machine's
folder is a local git repository — never pushed anywhere — and every change (keeping, moving, renaming a project,
editing a note, removing) is one commit by whoever made it; **See history** shows the log, and a removed result
can be brought back from it.

A kept result can have **versions**: a changed file uploaded later (e.g. the downloaded Excel sheet with analysis
added) or a re-run — a job started from an opened result remembers it, and when added to Time Machine it becomes the
next version by itself (any other job can be attached by its number). Each version is a new point on the timeline,
drawn as a ring and joined to the one before it. **Add files by hand** keeps things that never were jobs: a title, a
description and at least one file are required; they get their own number and appear only in Time Machine. A **task**
keeps a place for a result that doesn't exist yet: a title, a description and, optionally, the person who is to do it.
When files are uploaded to it, or a job is added to it (by its number, or from the job's result page: **Add to Time
Machine** offers the open tasks), that becomes its version 2 and the task is done. The Time Machine page shows
**My tasks** (given to the name set in the top bar) and **All open tasks**, by person. **Jobs & results**
has a search bar (file names, keyword, tool, person, job number) and filters (who, what, when, kept or not).

**Reagents** (sidebar, the flask) is the lab's reagent inventory — its own space, like Time Machine. Its data is the
lab's inventory repository (ours: [smith-lab/inventory](https://github.com/smith-lab/inventory); chosen on
**Settings → Reagents & consumables**, on the setup page or in the lab file), whose master copy is one workbook, `wykaz_odczynnikow_kompletny.xlsx`: one row per
reagent keyed by its label number (`label_no`), up to 5 producers each, storage categories A–J, GHS pictograms; its sheet
`columns` names and types every column, and the repository's `AGENTS.md` sets the rules for everyone editing it.

The list shows each reagent's name in the interface's language (Polish or English), sorted by name (click **#** to sort by
label number). It searches every field (accents optional, `#14` finds label 14) and has **quick filters** at the top (to
order, category, borrowed), plus **All filters**, one per column, by section. Filters are kept in the address. **Columns…**
chooses what the list shows, per browser. Every row has an **Order…** button (which producer, how much, a note), and the
list scrolls with the page, with a button back to the top. A reagent opens read-only: names, formula, molar mass, purity, category
and its GHS pictograms at the top, then the other columns by section. **Make a solution** opens Solution & dilution with the
reagent's name, molar mass and purity filled in (purity 100 % if the inventory has none). **Edit** opens the edit view, where every column can be
changed, producers one card each. A save refuses to overwrite a change someone else saved meanwhile. Used-up reagents are
marked disposed (the row and its label number stay) and leave the list. **To order** lists producers marked *to order*,
grouped by producer: copy as text, Excel/CSV, print; *Ordered*, then *Arrived* (with the new container count). **Add info**
(on the Reagents pages; on a reagent's page it is about that reagent) takes remarks instead of edits — "the Sigma acetone
moved to cabinet 3", "two bottles left", or a pasted transcript of a walk round the lab — saved as `info/*.json` in the
repository, listed under **Info from the lab**, and copied as Markdown for an agent. The inventory's GitHub sync, its history and
**Reagents: fields** (which names the columns and chooses which are visible, quick filters and default list columns, for
the whole lab) are on **Settings → Reagents & consumables**.

**Consumables** (sidebar, the box) is the same space for lab consumables — blotting paper, PVDF membranes, coverslips,
pipette tips, HPLC vials… — with the same list, filters, item page, edit view, **To order** and **Info from the lab**; a
switch under the title moves between Reagents and Consumables. There are no hazards: each item has a name, kind,
size / specification, what it is used for and where it is, and up to 3 brands, each with its supplier, product code, a
link to the product page, pack size, packs in the lab, price, an opinion and **Don't buy again** ("these tips crack —
buy another brand next time"). The order list is grouped by supplier. Its data is a second workbook in the same
repository, `consumables.xlsx` (sheet `consumables`, key `item_no`, its own `columns` sheet; shown as set in
`mister_plis_consumables.json`), made empty by the server the first time the repository is here. So the sync, the
history and **Info from the lab** are shared: one list of notes for both, since one message often is about both (a note
sent from a consumable's page names it). The tidy-up changes only the reagents; notes about consumables wait for a person.
Its fields are in **Settings → Reagents & consumables → Consumables: fields**.

**Tidy-up by a local model.** On a schedule (Settings → Reagents & consumables → *Reagents: tidy-up by a local model*), the server
tidies the inventory: values in the wrong format (filler such as "brak danych", TRUE/FALSE or numbers stored as text,
dates, lists), producers spelled several ways, and, with a model running on the Mac Studio (Ollama, `ollama_url` under `[module.inventory]`),
the notes in Info from the lab turned into corrections. Every change is checked like an edit and committed, so it
syncs like the lab's own edits. What it may apply by itself is a lab-wide choice; the rest waits on the page with
**Apply** / **Reject**. A note the model finds unclear gets its question and waits for a person. Setup:
[docs/DEPLOY_MAC_STUDIO.md](docs/DEPLOY_MAC_STUDIO.md#9-working-from-several-places).

Every change made here edits the workbook in place (formatting, drop-down lists and the other sheets kept), rewrites the
CSV copy next to it, and is one commit by whoever made it, sent to GitHub about 20 s later. **Sync** (Settings → Reagents & consumables; by hand or every
15 min / 1 h / 4 h) merges GitHub's changes in: two edits of the workbook are combined cell by cell, by `label_no` and
column; only the same cell changed differently on both sides stops the sync, and those cells are named. Nothing is ever
forced. The server's token needs *Contents: Read and write* on the inventory repository.

Every result has one **PDF** button: the whole result on A4 — who ran it, when, the settings, then every number,
table, text, chart and picture in order (charts in the colours chosen on the page). Calculators also collect
results into one protocol (**Add to protocol**), titled by the compound, e.g. "NaCl · 150 mM". Every table
downloads as .xlsx; every plot is interactive
(zoom, crosshair), exports PNG/SVG, and has a small palette button to change each sample's colour
(remembered per tool in your browser). Files are arranged into samples in an editable table, so no
naming convention is required.

---

## Everyday workflow

```
your laptop                            GitHub                       Mac Studio (lab)
───────────                            ──────                       ────────────────
edit the base or a module → git push ► michalby/MISTER_PLIS ──────► Settings → Server & updates → Sync with git
                                                                     (pulls, reinstalls deps if needed, restarts)
edit a tool               → git push ► smith-lab/lab-tools ► Settings → Tools → Tool sources → Check → Update
./scripts/dev.sh to try either                                       (then restart when it asks)
```

Our tools live in [smith-lab/lab-tools](https://github.com/smith-lab/lab-tools), not here (a tool source,
named in the lab file).

Everyone who has the page open gets a "new version is live — refresh" banner within a minute.

## Develop on your computer

```bash
./scripts/setup.sh --dev     # creates .venv and installs everything
./scripts/dev.sh             # http://localhost:8000, reloads when you save
.venv/bin/python -m pytest   # run the tests
```

The tests use two small test tools (`tests/fixtures/toolsource/`). To have the lab's tools (and its inventory and
notebook) on your computer, set it up from the lab file: `python -m mister_plis setup labs/example.toml`, or open the
page and choose it on the setup page; the tools are fetched at the next start. To work on them, clone that repository and point
`tool_folders` in `config.toml` at your clone; the dev server then reloads when you save a tool. The reference for
writing tools is [docs/ADDING_TOOLS.md](docs/ADDING_TOOLS.md) (also in the app under **Add a tool**); a module is
[docs/MODULES.md](docs/MODULES.md).

## Install it (once)

Three ways, one code; each keeps the lab's data apart from the code, and opens its setup page the first time:

- **A Mac:** the app, below ([docs/DEPLOY_MAC_STUDIO.md](docs/DEPLOY_MAC_STUDIO.md)).
- **Linux:** Docker (`docker compose up -d` with [deploy/docker-compose.yml](deploy/docker-compose.yml)) or a systemd
  service ([deploy/mister-plis.service](deploy/mister-plis.service)) — [docs/DEPLOY_LINUX.md](docs/DEPLOY_LINUX.md).
- **Windows:** Docker Desktop — [docs/DEPLOY_WINDOWS.md](docs/DEPLOY_WINDOWS.md).

Everything runs on that one computer: the pages, the tools and their jobs. Anyone on the lab's network reaches it by
its address (Settings → Server & updates → *How people reach this server* lists them) and signs in with their account;
nothing is set up on their own devices.

### On the lab Mac Studio

On the Mac Studio, MISTER PLIS is an ordinary app: **MISTER PLIS.app** sits in the Dock, starts at
login, restarts the server if it stops and keeps the Mac awake. It has Python inside, so the Mac
needs no Homebrew — only Apple's Command Line Tools for git. The full walkthrough, including
reaching it from every computer on the network and keeping it on through restarts and power cuts,
is in [docs/DEPLOY_MAC_STUDIO.md](docs/DEPLOY_MAC_STUDIO.md). The short version:

1. On either Mac: download and extract the repository ZIP (or use a Git checkout), then run
   `./scripts/build_app.sh` from that folder → `dist/MISTER PLIS.app`.
   Add `MISTER_PLIS_LAB_FILE=labs/<lab>.toml` in front to set the Mac up from that lab file on its first start.
2. On github.com make a fine-grained token: only the repositories the lab file names (ours: `MISTER_PLIS`,
   `MISTER_PLIS-tools`, `notebook` and `inventory`), *Contents: Read and write* (the server pushes the lab's
   reagent edits; it never pushes code). A fine-grained token covers one owner's repositories: keep them under one
   account, or make the code repository public.
3. On the Mac Studio: `xcode-select --install`, copy the app into `/Applications`, open it, paste
   the token. It downloads the code and packages, then opens the page in the browser: the setup page, unless a lab
   file was baked in.
4. Keep it on: *Users & Groups → Automatically log in as…* (needs FileVault off — see the guide)
   and *Energy → Start up automatically after a power failure*. Allow incoming connections for
   Python when macOS asks.
5. Tell the lab the address shown in the dock menu, e.g. `http://mister-plis.local:8000`.

Right-click the dock icon for the status, the log, *Restart Server*, *Start at Login* and
*Remove App Data and Quit…* (uninstall: deletes the folder below, the token and the login item). The
code, `config.toml`, results and logs live in `~/Library/Application Support/MISTER PLIS/MISTER_PLIS/`.

## Set it up for your lab

A new server opens the **setup page** (`/setup`) until it is set up: start from a lab file (one in `labs/`, a file from
your computer, or an `https://` address), check or change each step — the lab's name and language, tool sources, the
modules and their repositories, this computer's folders and label printer — then **Check** lists every change and
whether each repository can be read, and **Set up** applies it (and restarts when tools or modules need it). **Skip for
now** runs the app with nothing set up. Later, **Settings → Server & updates → Lab setup** opens it again, and
**Download this lab's file** writes the server's settings as a lab file.

Without a browser, for setting up the same lab on several computers:

```bash
python -m mister_plis setup labs/example.toml --check   # what it would change, and can each repository be read
python -m mister_plis setup labs/example.toml           # apply it (asks first; --yes to skip the question)
python -m mister_plis export ourlab.toml                 # this server's settings as a lab file
```

or put `lab_file = "labs/example.toml"` in `config.toml`: a server that isn't set up yet applies it when it starts.
A lab file never holds a token or password. Applying one again shows each change first; what it leaves out stays as
it is. **Moving a server** to another machine (the jobs, Time Machine, settings, everything):
**Settings → Server & updates → Move this server**, then **Everything from another server** on the new server's setup
page. The beta — our lab, a test MacBook, a friend's lab — and how a move works: [docs/BETA.md](docs/BETA.md); where it is going
(any server, several computers, releases): [docs/FINAL_VERSION.md](docs/FINAL_VERSION.md).
What has to change before it is safe on a shared network (the login, keeping labs apart): [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md).
The plan and the decisions behind it are in [docs/LAB_SETUP_PLAN.md](docs/LAB_SETUP_PLAN.md); the format is in
[docs/FORMATS.md](docs/FORMATS.md) §12.

## How updating works

A Mac app or a git clone updates from GitHub, as below. A **Docker** server is updated with a new image
(`docker compose pull && docker compose up -d`, or `docker build` again): Settings → Server & updates says so and shows
the version and the commit the image was built from.

**Settings → Server & updates** shows the running commit and what's waiting on GitHub.
**Sync with git** does `git pull --ff-only`; if `requirements*.txt` changed it runs
`pip install -r requirements.txt`; then the server replaces itself with a fresh process
(same port, ~2 s). Jobs still running are listed first and you're asked to confirm.

**Run another branch** (same tab) switches the server to any branch on GitHub — e.g. a test branch on
your own computer — and restarts it; from then on **Sync with git** follows that branch. The choice is kept
in `data/git_branch.json` and wins over `git_branch` in `config.toml`. It applies to everyone using that server.

**Update by itself** (same tab) pulls and restarts every night between 3 and 5 am, only when no job is running —
for code pushed from Claude Code on the web or another computer. The **Lab notebook** tab can likewise sync the
notes by itself (every 15 min, 1 h or 4 h), for notes pushed from Obsidian's Git plugin.

Before every update (and the nightly one) the server makes a **snapshot of the lab's settings** — the newest five
are on the same tab, each with **Restore**; jobs and the modules' data aren't in them and stay as they are. What
changed from version to version is in [CHANGELOG.md](CHANGELOG.md); a release is built by hand with
`./scripts/release.sh` (tests, the wheel, the Docker image, the release feed — publishing is left to you).

Static files are cache-busted by commit, so a normal refresh always loads the new interface.

Don't edit files directly on the server — `git pull --ff-only` refuses to overwrite local edits
(the page warns about them).

## Configuration

Copy `config.example.toml` to `config.toml` (ignored by git) or use `MISTER_PLIS_*` environment
variables. `config.toml` lives in the **instance's folder**: the repository folder, unless `MISTER_PLIS_HOME` names
another (e.g. `MISTER_PLIS_HOME=/srv/mister-plis python -m mister_plis`); that folder then holds `config.toml`,
`data/`, `secrets/` and `logs/`, relative paths in the settings are relative to it, and the code can stay elsewhere,
read-only. Settings → Server & updates shows both folders. Tokens for private repositories go on Settings → Server & updates → GitHub access (one per owner if needed; kept in `secrets/`), or in `MISTER_PLIS_GIT_TOKEN`. Settings: `host`, `port`, `lab_name` (the default; **Settings → Server & updates** can set another), `data_dir`,
`storage_dir` (where jobs are kept, one folder each, and what tools save; `""` = the data folder; **Settings → Jobs &
backup** can move them to another folder), `blender_path` (the older way; the Blender tool's own setting on **Settings →
Tools** wins), `max_workers`,
`job_retention_days`, `upload_retention_days`, `git_branch`, `modules` (which modules to load), `fetch_tool_sources`,
`tool_folders` (tool folders on this computer, e.g. a working copy of the tools repository), `lab_file` (a lab file
applied when a new server first starts). What the lab sets up (the modules' repositories, how long results are kept,
which modules are on…) is stored by the server; `config.toml` is for **this machine** and wins over it where it says
something: e.g. `[module.inventory] repo = ""` keeps a development copy off the lab's inventory, and the page then
says so. As environment variables: `MISTER_PLIS_MODULE_INVENTORY_REPO=""`. A key the server doesn't know is reported
in the log when it starts.

## Layout

The whole picture is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
mister_plis/            the base: a complete app on its own
  toolkit.py            Tool, RunContext, helpers  ← the only thing tools import (TOOLKIT_API 1, version 1.1)
  toolsettings.py       what a tool declares it needs on this server (Settings → Tools)
  inputs.py outputs.py  form fields and result types
  jobs.py jobstore.py jobformat.py   running jobs; one folder per job (job.json), index.json
  storage.py            the storage folder (chosen on Settings → Jobs & backup)
  backup.py export/     readable, checked backups; importing them back
  modules.py            the module interface (Time Machine, the inventory, the notebook plug in here)
  registry.py toolsources.py   tools from git repositories (tool sources) and tool_folders
  updater.py gitutil.py the code's self-update; one git runner
  labsetup.py           the lab's setup: lab files, /setup, python -m mister_plis setup
  app.py                FastAPI routes; templates/ and static/ hold the UI
modules/                large modules, one folder each (see docs/MODULES.md)
  timemachine/          results worth keeping (projects, versions, tasks, history; copied into the backup folder)
  inventory/            Reagents and Consumables (two workbooks in a GitHub repository), tidy-up
  notebook/             the lab's Obsidian notes, read-only, beside every page
labs/                   lab files: ours (smith-lab.toml) and template.toml with every setting
docs/                   ARCHITECTURE, MODULES, ADDING_TOOLS, FORMATS, DEPLOY_MAC_STUDIO, reorg/ (the reorganisation)
scripts/                setup, run, dev, build_app (the Mac app), install/uninstall service, make_constraints
macos/                  the Mac app's launcher (Swift) and icon renderer
data/                   the server's state (not in git); jobs live in the storage folder (by default this one)
tests/                  the base's tests; fixtures/ holds the frozen v0 data and two test tools (toolsource/)
```

There's an auto-generated API reference at `/api/docs` if you want to script against it: turn it on with `api_docs = 1`
in config.toml (or `MISTER_PLIS_API_DOCS=1`); it is off by default, as it maps every route for anyone.

## Licence

MISTER PLIS is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; see [LICENSE](LICENSE).
