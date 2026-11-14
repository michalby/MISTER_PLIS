# Notes for Claude / coding agents

- **Where work goes:** never push to `stable` or `beta`. Work on a branch of your own — a branch of this repository
  for its maintainers, a fork for everyone else —, run the tests (`.venv/bin/python -m pytest`), and open a pull
  request **into `beta`**. `beta` goes to `stable` by a pull request once it has run for a while without trouble
  (CONTRIBUTING.md, "Branches"). If a session was given a working branch, that is the branch to push to.
- **No CI:** the tests are run by hand, before a pull request; don't add GitHub Actions workflows.

## How the code is organised

- Read **docs/ARCHITECTURE.md** first: the base (`mister_plis/`), the modules (`modules/<id>/`), the tools (tool
  sources), the storage and backup folders.
- **The base never names a module.** Modules plug in through `mister_plis/modules.py` (see docs/MODULES.md);
  `tests/test_modules.py` fails if the base mentions or imports one, and checks the base runs with `modules = "none"`.
- **No tools live here.** Tools are in repositories of their own (tool sources, docs/ADDING_TOOLS.md); the basic set
  every lab gets is one of them. They use only `mister_plis.toolkit` (`TOOLKIT_API`), so a change to `toolkit.__all__`
  is a change of the API: keep it compatible (an addition raises `TOOLKIT_VERSION`'s minor number, e.g. 1.1 → 1.2), or
  raise `TOOLKIT_API` on purpose. The base's tests use the two test tools in `tests/fixtures/toolsource/` (loaded
  through `tool_folders`); `tests/test_tool_boundary.py` checks the toolkit boundary on them.
- **Versions:** a change a lab will notice raises `mister_plis/__version__` (MAJOR.MINOR.PATCH: MAJOR when a lab must
  act, e.g. a format older versions can't read; MINOR for features; PATCH for fixes) and adds a line to `CHANGELOG.md`
  (`tests/test_updates.py` checks its top entry is this version). A new on-disk format version goes into
  `mister_plis/formats.py` too.
- **Never break old data.** Every on-disk format is in docs/FORMATS.md; the frozen fixtures in `tests/fixtures/*_v0/`
  must stay readable. Add a reader for a new format; don't change an old one.
- **No lab in the code.** What makes a server one lab's (repositories, folders, printer…) comes from its lab's setup:
  a lab file (`labs/template.toml` names every setting, `labs/example.toml` is a made-up lab), the setup page, or the
  Settings page — never a default in the code. A new setting the lab chooses goes into the lab file too
  (`mister_plis/labsetup.py`, or a module's `setup_fields` / `configure`), and into `labs/template.toml`
  (`tests/test_labsetup.py` checks the template names every setting).
- **Every route that changes something is marked** `dependencies=SETTINGS` (the lab's settings) or `WORK` (everyday
  work) in the base, `[Depends(ctx.settings_access)]` / `ctx.work_access` in a module (`mister_plis/access.py`);
  `tests/test_access.py` fails on an unmarked one.
- **Files on disk are English;** only the interface is translated (`locale/pl.py` next to the code that shows the text).
  `tests/test_i18n.py` checks every interface text has Polish.
- Data that moves: copy, check, then switch; rename the old folder, never delete it
  (`mister_plis.storage.move_folder_once`, `copy_verified`).
