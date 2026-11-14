# Time Machine (module `timemachine`)

Results worth keeping for good, copied out of Jobs & results. They are organised in projects, with versions, files
added by hand, and tasks (a place kept for a result someone is to make). Every change is a commit in a local git
repository, so **See history** shows who changed what, and a removed result can be brought back.

- **Data:** `<storage>/modules/timemachine/` (before reorg P4: `<data>/timemachine/`, moved once at start, the old
  folder kept as `timemachine.migrated-<date>`). Format: docs/FORMATS.md §4.
- **In the backup folder:** `<backup>/Time Machine/` (`timemachine.bundle`, `projects.md`, `index.json`, each kept result
  in readable form), written when it changed, checked every 10 minutes. **Settings → Jobs & backup → Time Machine: its own
  backup** to copy now or restore.
- **On the base's pages:**
  - "Add to Time Machine" above every result (`static/tm-button.js`);
  - a galaxy mark and a Kept / Not kept filter in Jobs & results;
  - "kept" counts on People;
  - `in_tm` / `tm_root` on every job in the API.
- **Retrieving jobs:** from Jobs & results, or from the backup folder through the base's backup catalogue (old and
  new backups).
- **Settings:** none of its own. The backup folder comes from Settings → Jobs & backup.
- **Code:** `service.py` (TimeMachine), `history.py` (the local git history), `web.py` (routes), `backup.py`,
  `templates/`, `static/`, `locale/pl.py`, `tests/`.
