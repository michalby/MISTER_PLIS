# Plan: MISTER PLIS for any lab — first-run setup and a lab file

*November 2026. Status: **done** (9 November 2026, phases L0–L5; the log, with where the build differs from the plan,
is §11). Part 1 is the audit: what tied the app to one lab. Part 2 is the plan: a lab file that sets everything up on
the first run, a setup page that does the same by hand, and a way back to it later. The open questions of §9 were
decided as proposed.*

---

# Part 1 — Audit: what another lab would trip over

The reorganisation already made most of the app lab-neutral: the base never names a module, tools come from tool
sources, and most lab-wide choices are set on the Settings page. What is left falls into four groups.

## 1. Repositories written into the code

These are the defaults a fresh install uses when nothing else is set. Another lab gets **our** repositories unless
it knows to override each one, and some can't be overridden at all without editing code.

| What | Where | Default today | Can another lab change it? |
|---|---|---|---|
| The lab's tool source | `mister_plis/toolsources.py:44` (`LAB`) | `smith-lab/lab-tools`, **trusted** | Yes, on Settings → Tools, but only *after* the first start has already cloned ours and trusted it (it gets the server's GitHub token). |
| The inventory repository | `modules/inventory/__init__.py:19` (`DEFAULTS["repo"]`) | `smith-lab/inventory` | Only in `config.toml` (`[module.inventory] repo`), by hand, on the server. Not on any page. |
| The notebook repository | `modules/notebook/__init__.py:17` (`DEFAULTS["repo"]`) | `smith-lab/notebook` | Only in `config.toml` (`[module.notebook] repo`). Not on any page. |
| The code repository (Mac app) | `scripts/build_app.sh:38`, baked into the app as `MPRepoURL` | the checkout's `origin`, else `michalby/MISTER_PLIS` | Yes, at build time (`MISTER_PLIS_REPO_URL`). Fine as it is. |
| The code's own updates | `mister_plis/updater.py` | the checkout's `origin` | Yes: whatever was cloned. Fine as it is. |

The two module repositories are the real problem: a lab that installs the app and turns the inventory on would sync
with `smith-lab/inventory` (or fail to, with a GitHub error), and the only fix is a file on the server.

## 2. Other lab-specific defaults in the code

| What | Where | Today | Problem for another lab |
|---|---|---|---|
| Notebook folders shown at first | `modules/notebook/service.py:29` (`DEFAULT_FOLDERS`) | `Protokoły/Metody`, `Protokoły/Odczynniki` | Folders of our vault; another vault won't have them. (Settable on the page afterwards.) |
| The "Make a solution" tool | `modules/inventory/__init__.py:19` (`calculator`) | `molarity` | A tool id from *our* tool source. Another lab's tools may not have it (the button then just doesn't show). |
| The reagents workbook | `modules/inventory/service.py:43` (`DEFAULT_CONFIG`) | `wykaz_odczynnikow_kompletny.xlsx`, columns `name_pl` / `name_en`, `label_no`… | Overridable through `mister_plis.json` in the inventory repository, but **a new, empty repository gets no reagents workbook** (consumables do: `Consumables.start_workbook`). A lab can't start a reagent inventory from nothing. |
| Titles in two languages | inventory `title: {"pl": …, "en": …}`, tidy-up reads `pl` | Polish first | Fine for us; a lab with one language has to fill a `name_pl` column. Not a setup question, but worth knowing. |
| The label printer | `mister_plis/labels.py` | Brother PT-E550W protocol | Address and tape are settable; the model isn't. Out of scope here. |
| Language of the interface | `mister_plis/prefs.py:16` | English, per browser | No lab-wide default language. A Polish lab has every person switch once. Small. |

## 3. Settings that exist, but only in `config.toml`

`config.toml` is per machine, gitignored, edited by hand on the server, and read only at start. Today it also holds
things that are about the **lab**, not the machine:

| Setting | Lab or machine? | On a page? |
|---|---|---|
| `[module.inventory] repo`, `branch` | lab | no |
| `[module.inventory] calculator`, `ollama_url` | lab (`ollama_url` is half machine) | no |
| `[module.notebook] repo`, `branch` | lab | no |
| `modules` (which modules are on) | lab | no |
| `lab_name` | lab | **yes** (Settings → Server & updates wins) |
| `storage_dir` | machine | **yes** (Settings → Jobs & backup wins) |
| `job_retention_days`, `upload_retention_days`, `max_workers` | lab-ish | no |
| `host`, `port`, `data_dir`, `tool_folders`, `fetch_tool_sources`, `git_branch` | machine | `git_branch` yes; the rest no, and that's right |

And the settings that are **only** on pages, kept in the data folder (so they are lost to a new machine unless the
data folder is copied): tool sources (`tool_sources.json`), backup folder and schedule and lab name
(`lab_settings.json`), label printer (`label_printer.json`), tool settings (`tool-settings/*.json`), notebook folders
and sync interval, inventory push / auto-sync, tidy-up schedule and model, auto-update.

So today a lab is configured in **three places** (code defaults, `config.toml`, pages), there is **no single place
that describes a lab**, and **nothing can be carried to another computer** except by copying the data folder.

## 4. Access and documentation

- **One token for everything.** `gitutil.credential_args` reuses the code checkout's credential helper (the Mac's
  Keychain) for every repository. GitHub's fine-grained tokens belong to **one owner**: if the code comes from
  `michalby/MISTER_PLIS` and another lab's inventory is in `their-org/inventory`, one token can't reach both. Today
  this works only because everything is under `smith-lab`. (A public code repository needs no token, which avoids it.)
- **No first-run moment.** On first start the server clones our tool source by itself and the modules start with
  our repositories. There is no point at which the app asks "which lab is this?".
- **No login.** Anyone on the network can open Settings. A setup page has the same exposure; acceptable for a lab
  network, but worth saying (§9, Q5).
- **Docs are written for our lab.** `README.md` and `docs/DEPLOY_MAC_STUDIO.md` name `smith-lab/…` repositories, the
  token's repository list, `notebook`. Fine for us; another lab needs a neutral version.
- Tests name `smith-lab/…` URLs only as sample strings; nothing to change there.

---

# Part 2 — The plan

## 5. Two files, two jobs

| | `config.toml` (exists) | **the lab file** (new) |
|---|---|---|
| About | **this machine**: port, data folder, working copies of tools, overrides while developing | **the lab**: its name, repositories, modules, folders, printer, schedules |
| Where | the checkout's root, gitignored | anywhere: `labs/<name>.toml` in this repository for now (§8), a file picked on the setup page, or a URL |
| Shared? | never | yes: the same file sets up every computer the lab uses |
| Secrets | never | **never** (tokens stay in the Keychain / credential helper) |
| Read | at every start | **once**, when it is applied (§6) |

`config.toml` keeps working as it does, so nothing on an existing server breaks.

## 6. The lab file is a seed, not a live layer

Applying a lab file **writes its values into the same places the Settings page edits** (`tool_sources.json`,
`lab_settings.json`, `label_printer.json`, each module's `settings.json`, …). From then on the Settings page is where
things change. The file is not read again until someone applies it again.

Why not read it at every start, like `config.toml`? Because then a setting changed on the page would be undone by the
file at the next restart, or the page would have to show "locked by the lab file" everywhere. A seed keeps **one**
place of truth (the pages), and still gives a file that sets up a computer in one step.

The order of precedence stays simple:

```
environment (MISTER_PLIS_…)  >  config.toml  >  what is stored (set on a page, or by a lab file)  >  nothing set
```

`config.toml` still wins, so a development clone can keep `repo = ""` under `[module.inventory]`. A page shows such a
value as "set in config.toml on this machine" and doesn't offer to change it.

**Applying again** (to test a change to the file, or to bring a second computer in line) shows what would change
first — setting by setting, old → new — and changes nothing until confirmed. The same view is the answer to "what
would this file do?" from the command line (§7c).

**The way back:** Settings → Server & updates → **Download this lab's file** writes the current settings as a lab
file. That is how a lab moves to a new server, and how the template (§8) is made: download from a server with
nothing set up.

## 7. First run, and reconfiguring later

### 7a. When is the server "set up"?

`<data>/lab.json` = `{"format": 1, "set_up_at": …, "set_up_by": …, "from": "labs/example.toml" | "page" | "migrated"}`.
No file = not set up yet.

**Existing servers count as set up** (never break old data): on the first start of the new version, a server whose
data folder already has any of `tool_sources.json`, `tool-sources/lab/`, `modules/inventory/repo/`,
`modules/notebook/vault/` or `lab_settings.json` writes `lab.json` with `"from": "migrated"`, and stores the values
it has been using so far (the clones' `origin` addresses, the old defaults) as stored settings. Our Mac Studio
therefore carries on exactly as before, and the code's defaults can then become "nothing set" (§7e).

### 7b. The setup page (`/setup`)

While the server isn't set up, every page leads to `/setup` (the API and the static files don't, and **Skip for now**
lets the app run with nothing set up — the base already runs with no tools and no modules). Steps:

1. **Start from** a lab file — one of `labs/*.toml` in the checkout, a file from this computer, or a URL (a raw file
   in a GitHub repository) — or **from nothing**. A lab file fills in every step below; each step can still be edited.
2. **The lab:** name; the interface's default language (new, small: §2).
3. **Tools:** the tool sources (address, branch; the first one trusted). Empty is allowed.
4. **Modules:** each module on or off, and each one's own questions (repository, branch, …) — asked by the module,
   not by the base (§7d).
5. **This machine:** storage folder, backup folder (both checked: exist, writable, separate), label printer address.
6. **Check:** every repository is reached (`git ls-remote`) and each says *public*, *needs the token* or *not
   reachable — the token doesn't include it*; folders are checked again. Then **Set up**, which applies everything
   and clones what is needed in the background, showing progress.

**Reconfiguring:** Settings → Server & updates gets a **Lab setup** panel: *Open the setup again* (the same page,
filled with the current values; Set up shows the changes first, as in §6), *Apply a lab file…*, and *Download this
lab's file*. Each setting also stays editable on its own tab, as today.

### 7c. Without a browser: many computers, one file

For setting up (or re-testing) the same lab on several computers without clicking through the page:

- `lab_file = "labs/example.toml"` in `config.toml`, or `MISTER_PLIS_LAB_FILE=…`: a server that **isn't set up yet**
  applies this file on start, as if Set up had been pressed. A server that is set up ignores it (and says so in the
  log), so it can stay in `config.toml` safely.
- `python -m mister_plis setup labs/example.toml --check` prints what the file would change and whether every
  repository and folder can be reached; without `--check` it applies it (asking first, unless `--yes`).
- The Mac app: `scripts/build_app.sh` can bake a lab file's address into the app (`MISTER_PLIS_LAB_FILE` at build
  time, like `MISTER_PLIS_REPO_URL` today), and the launcher passes it to the server on first launch.

### 7d. Modules and tools answer their own questions

The base must never name a module (`tests/test_modules.py`). So the setup page and the lab file can't know what the
inventory needs. Modules declare it, the same way tools already declare their settings (`Tool(settings=…)`,
`mister_plis/toolsettings.py`):

- `Module(setup=[Setting("repo", "Repository", kind="repository", …), Setting("branch", …)], configure=fn)` —
  the fields shown in step 4, and a function that checks and stores the values (and says whether a restart is needed).
- The lab file's `[module.<id>]` table is handed to that module as it is; the base only checks it's a table.
  Keys a module doesn't know are reported, like unknown keys in `config.toml` today.
- Tools' own settings (the Blender program, …) come from `[tool.<tool id>]` tables, stored through
  `toolsettings.py`, exactly as if set on Settings → Tools. A tool that isn't installed yet keeps its table until it is.

### 7e. Repositories become settings like any other

- `[module.inventory] repo/branch` and `[module.notebook] repo/branch` move into each module's stored
  `settings.json` (both modules already keep one), editable on the module's Settings tab.
- The built-in defaults become **nothing set**: no `smith-lab/…` addresses in the code. A module with no repository
  is off (the notebook already works that way; the inventory then works without sync, as with `repo = ""` today).
  `toolsources.LAB` goes; the first tool source comes from the lab file or the setup page. `DEFAULT_FOLDERS` of the
  notebook becomes empty (the setup page lists the vault's folders to choose from once it's cloned).
- **Changing a repository on a running server:** the inventory first pushes what it hasn't pushed (or refuses, with
  the reason); the old clone is **renamed, never deleted** (`repo` → `repo.before-<date>`, like
  `storage.move_folder_once`); the new one is cloned. The notebook only reads, so it just renames and clones.
- **A new, empty inventory repository** gets an empty reagents workbook, as consumables already do (§2), so a lab
  can start from nothing.

## 8. The lab file (format 1)

TOML, like `config.toml`. Every section is optional; what isn't in the file isn't changed. Paths may start with `~`.
The full draft for our lab is `labs/example.toml`; its shape:

```toml
[lab_file]
format = 1                 # this file's format (docs/FORMATS.md gets a section when it is read)

[lab]
name = "…"                 # shown under the logo
language = "pl"            # default interface language for new browsers ("en" | "pl")

[[tool_sources]]           # in order; the first is the lab's own (trusted: gets the token)
name = "lab"
url = "https://github.com/smith-lab/lab-tools.git"
branch = "main"
trusted = true

[modules]
on = ["timemachine", "inventory", "notebook"]   # or "all", or [] for none

[module.inventory]         # handed to the module as it is (§7d)
repo = "https://github.com/smith-lab/inventory.git"
branch = "main"

[module.notebook]
repo = "https://github.com/smith-lab/notebook.git"
folders = ["Protokoły/Metody", "Protokoły/Odczynniki"]

[jobs]
keep_days = 30             # job_retention_days

[backup]
folder = "/Volumes/…"      # this machine's view of the NAS
after_days = 1

[label_printer]
address = "192.168.1.50"
tape_mm = 12

[tool."<tool id>"]         # a tool's own settings (§7d), e.g. where Blender is
"<setting>" = "/Applications/Blender.app/Contents/MacOS/Blender"
```

Machine-specific values (backup folder, printer address, Blender path) are allowed in the lab file, because the
point is to set a whole computer up in one step. A lab with several different computers keeps one file per
computer, or leaves those out and sets them on the page.

### Our own file, and the template later

- **Now:** `labs/example.toml` lives in this repository, so every checkout on every computer has it, and
  `lab_file = "labs/example.toml"` (§7c) sets a fresh computer up as ours. It holds no secrets, so being in the
  repository is safe. Rename it freely: nothing depends on the name.
- **Later:** `labs/template.toml` — every setting, commented out, each with a line saying what it does — made by
  *Download this lab's file* on an empty server and then commented by hand. A test checks the template has every
  key the reader knows, so they can't drift apart.
- Our file can stay in `labs/` beside the template. If the repository becomes public and the lab doesn't want its
  repository names in it, the file moves to a private repository and is applied by URL (§7b step 1, §7c) — nothing
  else changes.
- A test parses every `labs/*.toml` with the real reader (`--check` without the network), so a typo in our file
  fails CI instead of a fresh computer.

## 9. Open questions

| # | Question | Proposal |
|---|---|---|
| Q1 | One token for repositories of different owners (§4)? | Keep one token; say clearly in step 6 which repositories it can't reach. Recommend the code repository be public (or forked into the lab's own account) so the token only needs the lab's repositories. Per-owner tokens only if a lab really needs them. |
| Q2 | Should the lab file be a seed (§6) or always read? | Seed, with "apply again" showing changes first. |
| Q3 | Remove the `smith-lab` defaults from code (§7e) in the same step as the migration? | Yes, the same release: the migration stores them for every existing server first, so nothing changes for us. |
| Q4 | Default interface language per lab (§2)? | Add it (`[lab] language`); a person's own choice still wins. |
| Q5 | `/setup` with no login? | Same exposure as Settings today. Once set up, `/setup` asks for confirmation (shows changes) and logs who applied what in `lab.json`. A real login is a separate question. |
| Q6 | Name of our file? | `labs/example.toml` for now (the owner of the repositories); rename to the lab's name when there is one. |

## 10. Phases

Each phase is one change that keeps the tests green and an existing server working.

| Phase | What | Visible to the lab |
|---|---|---|
| **L0** | This plan; the draft `labs/example.toml`. | nothing |
| **L1** | The lab file reader (format 1) and `python -m mister_plis setup <file> [--check]`; applying writes the existing stores; `lab.json`; the migration of existing servers (§7a); `lab_file` in `config.toml`; a test that parses `labs/*.toml`; FORMATS.md. | nothing, unless `lab_file` is set |
| **L2** | Module setup fields (`Module(setup=…, configure=…)`) and `[tool.<id>]` tables; inventory and notebook repositories become stored settings, shown and changed on their tabs (§7e: push first, rename the old clone). | repository fields on the module tabs |
| **L3** | No lab-specific defaults in code (`LAB`, module `DEFAULTS`, `DEFAULT_FOLDERS`); an empty reagents workbook for a new repository. Needs L1's migration. | nothing for an existing server |
| **L4** | The setup page (`/setup`), the Lab setup panel (open again, apply a file with its changes shown, download this lab's file). | the first-run page; the panel |
| **L5** | `labs/template.toml` and its test; the lab-neutral install guide (README, DEPLOY_MAC_STUDIO split into "any lab" and "our lab"); the lab file baked into the Mac app. | docs |

## 11. Log

| Phase | Commit message starts | What was built |
|---|---|---|
| L0 | "Audit and plan" | this plan; `labs/example.toml` |
| L1 | "Lab setup L1" | `mister_plis/labsetup.py` (read, plan, apply, export, `lab.json`, migration, waiting tables), `python -m mister_plis setup / export`, `lab_file`, `settings.explicit`, the lab's language and how long results are kept as stored settings; FORMATS.md §12 |
| L2 | "Lab setup L2" | `Module(setup_fields, lab_settings, configure)`, `modules.plan_rows`; the inventory's and notebook's repositories (and the inventory's calculator and local model) stored, with **Change…** on their tabs; another repository sets the old clone aside (`gitutil.set_aside`); `gitutil.check_address / check_branch` |
| L3 | "Lab setup L3" | no lab's repositories, calculator or notebook folders in the code; what an existing server used is stored for it the first time; **Start an empty inventory** |
| L4 | "Lab setup L4" | `/setup`, the first-run redirect, Settings → Server & updates → Lab setup; Polish; tests (API and a browser run) |
| L5 | "Lab setup L5" | `labs/template.toml` and its test; README, ARCHITECTURE, DEPLOY_MAC_STUDIO, config.example.toml; `MISTER_PLIS_LAB_FILE` for `scripts/build_app.sh`, passed on by the Mac app's launcher |

Where the build differs from the plan:

- **An empty reagents workbook is a button** (Settings → Reagents & consumables → **Start an empty inventory**), not
  automatic: made by itself, it could shadow a repository's own workbook before the first sync. It is offered on an
  inventory kept on the server only, or once a sync has found none.
- **A module that is off by its own settings keeps its Settings tab** (and that tab's scripts), so the notebook can be
  given a repository there. Its links, panels and side panel stay hidden.
- **The inventory refuses another repository while changes made here haven't reached the current one**; a copy that
  was never synced (or had no repository) is kept and sent to the new repository at the next sync.
- **A lab file's `storage_folder` is applied only while there are no jobs**; afterwards it is reported as left alone,
  and the folder is moved on Settings → Jobs & backup (which copies and checks the jobs).
- **The setup page doesn't show each lab file key by itself**: the form holds the lab file's shape; what it doesn't
  show (the label printer's cut options, a tool's own settings) passes through as loaded. Tool sources can be added,
  but not removed, there (that stays on Settings → Tools).
- `lab.json` is written as `"state": "new"` on a new server's first start, so the folders it makes itself never pass
  it off as a server from before lab files at the next start.

