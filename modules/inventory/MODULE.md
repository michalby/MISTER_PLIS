# Inventory (module `inventory`): Reagents and Consumables

The lab's reagent and consumables inventories:

- two workbooks in one GitHub repository (the lab's inventory repository), edited from the pages;
- each change committed by the person who made it, and merged with GitHub's changes cell by cell;
- orders (To order → Ordered → Arrived), notes from the lab, portion labels on the P-touch printer;
- a scheduled tidy-up with a local model (Ollama).

- **Data:** `<data>/modules/inventory/` (before reorg P5: `<data>/reagents/`, moved once at start, the old folder kept
  as `reagents.migrated-<date>`). Its `repo/` is the clone of the inventory repository; `settings.json`; `tidy/`.
  Format: docs/FORMATS.md §5.
- **Settings:** chosen on its Settings tab (the repository: **Change…**), on the setup page, or in a lab file's
  `[module.inventory]` (`repo`, `branch`, `push`, `auto_sync_minutes`, `calculator`, `ollama_url`, `tidy_schedule`,
  `tidy_at`, `tidy_model`, `tidy_apply`; the questions are `SETUP` in `__init__.py`). `repo`, `branch`, `calculator` and
  `ollama_url` are stored in `settings.json`; the same keys in `[module.inventory]` of config.toml (or
  `MISTER_PLIS_MODULE_INVENTORY_REPO` etc.) win on that machine, and the page then shows the repository as set there.
  `repo = ""` turns the sync off. `repo` can also be a folder on this machine with git initialised in it
  (`repo = "~/Lab/inventory"`, or a shared disk): it syncs the same way, and the lab's changes are written into that
  folder's files (`gitutil.LOCAL_PUSH`); if someone has uncommitted edits there, the push waits and says so.
  **Another repository** (`Inventory.set_repository`): refused while changes made here haven't reached the current
  one; otherwise the copy is renamed `repo.before-<date>` and the new repository comes in at the next sync, nothing
  mixed in. A copy that was never synced (or had no repository) stays and is sent to the new one. A server from
  before this kept the address its clone came from (`_migrate`). (Before P8 these were the top-level `reagents_repo`,
  `reagents_branch`, `ollama_url`; those are now ignored, with a note in the log.)
- **Pages:** `/reagents…`, `/consumables…` (`web.py`, `templates/reagents.html`, `static/reagents.js`).
- **API:** `/api/reagents/*` (the sync, history, tidy-up and notes are shared), `/api/consumables/*`.
- **On the base's pages:**
  - two sidebar links;
  - its own Settings tab, Reagents & consumables (`SettingsTab`): the GitHub sync, its history, the tidy-up (`panels/sync.html`)
    and the columns of both inventories (`panels/columns.html`), driven by `static/reagents_admin.js`;
  - Settings: which columns are shown, for each inventory (`panels/settings.html`).
- **To the solution calculator:** a reagent's page has **Make a solution**, which opens the tool `calculator`
  (default `molarity`, Solution & dilution in MISTER_PLIS-tools) with the reagent's name, `molar_mass_g_mol` and
  `purity_percent` filled in (`calculator.py`; the base fills a tool's inputs from its address). Shown only while that
  tool is loaded and has the inputs `compound` (with `custom`), `new_name` and `mw`; `purity` (100 if unknown) and
  `density` (cleared) only if it has them.
- **Background:** the sync loop (every 15 min / 1 h / 4 h, as chosen) and the tidy-up's schedule.
- **Labels:** the portion labels use the base's label printer (`mister_plis/labels.py`). Its layout options (a
  category letter in a square, a large number on the right, GHS pictograms) are generic, so the renderer stayed in
  the base; this module only fills them in.
- **Code:** `service.py` (Inventory, Consumables, the cell-by-cell merge), `web.py`, `tidy.py`, `templates/`,
  `static/` (pages, admin, CSS, the GHS pictograms for the screen), `locale/pl.py`, `tests/`.
