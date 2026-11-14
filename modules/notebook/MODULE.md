# Lab notebook (module `notebook`)

Chosen folders of the lab's Obsidian vault (a GitHub repository), read-only. They appear as a full page (`/notes`)
and as a side panel beside every page, with search (accents optional), `[[links]]` and "Linked from".

- **Data:** `<data>/modules/notebook/`, holding a sparse, partial clone of the vault (`vault/`) and `settings.json`
  (the shown folders, the sync interval). Before reorg P6 this was `<data>/notes/`, moved once at start, with the
  old folder kept as `notes.migrated-<date>`. Format: docs/FORMATS.md §6.
- **Settings:** chosen on its Settings tab (the repository: **Change…**; the folders; sync by itself), on the setup
  page, or in a lab file's `[module.notebook]` (`repo`, `branch`, `folders`, `auto_sync_minutes`; `SETUP` in
  `__init__.py`). `repo` and `branch` are stored in `settings.json`; the same keys in `[module.notebook]` of config.toml
  (or `MISTER_PLIS_MODULE_NOTEBOOK_REPO` etc.) win on that machine. Another repository (`Notebook.set_repository`)
  renames the copy `vault.before-<date>` and downloads the new one at the next sync. A server from before this kept the
  address its clone came from (`_migrate`). (Before P8 they were the top-level `notes_repo`, `notes_branch`; those are
  now ignored, with a note in the log.) `repo` can also be a folder on this machine with git initialised in it
  (`repo = "~/Obsidian/Lab"`), read the same way. With no repository, the module is switched off (`enabled`): no link,
  no panel; `/notes` says it is off; its Settings tab stays, to choose a repository.
- **On the base's pages:**
  - the shell (`shell/`): a pre-paint script (`head.html`), the Notes button (`topbar.html`) and the panel with its
    rail (`aside.html`), and the `notes-on` page class. They are left out on full-page spaces
    (`page(..., hide_side_panels=True)`);
  - a sidebar link;
  - its own Settings tab, Lab notebook (`SettingsTab`): check, sync, sync by itself, and the shown folders (`panels/sync.html`,
    `static/notes_admin.js`).
- **Background:** the "sync by itself" loop (every 15 min / 1 h / 4 h, as chosen). A sync never restarts the server.
- **Code:** `service.py` (Notebook, the sparse sync and the index), `obsidian.py` (Obsidian Markdown → HTML),
  `web.py`, `templates/`, `static/` (`notes.js`, `notes_admin.js`, `notebook.css`), `locale/pl.py`, `tests/`.
