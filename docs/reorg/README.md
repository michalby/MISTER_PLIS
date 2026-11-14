# Reorganisation — handbook for agents (and people) doing the work

> **Finished (2026-11-07).** All phases P0–P8 are done; this folder is kept as the record of how and why. For how
> the code is organised now, read [../ARCHITECTURE.md](../ARCHITECTURE.md), [../MODULES.md](../MODULES.md),
> [../ADDING_TOOLS.md](../ADDING_TOOLS.md) and [../FORMATS.md](../FORMATS.md).

The **why** and the **target design** are in [../MODULARIZATION_PLAN.md](../MODULARIZATION_PLAN.md), and the
starting point is in [../ARCHITECTURE_AUDIT.md](../ARCHITECTURE_AUDIT.md). This folder holds the **how**: one
file per phase, with tasks small enough for one agent session each. Read this page fully before you take a
task.

## Status board

Update this table in the same commit that finishes, or starts, a phase.

| Phase | File | Status | Branch | Notes |
|---|---|---|---|---|
| P0 Safety net | [P0.md](P0.md) | **done** (2026-11-07), except two owner steps: push tag `v1-final`, and copy `data/` on the Mac Studio before P2 | `claude/eager-heisenberg-s121fy` → `main` | branch `release/v1` = `cb88d4d` |
| P1 Tool SDK clean-up | [P1.md](P1.md) | **done** (2026-11-07) | `claude/eager-heisenberg-s121fy` → `main` | |
| P2 Job store | [P2.md](P2.md) | **done** (2026-11-07), on `main` by the owner's decision without a trial on the Mac Studio | `claude/eager-heisenberg-s121fy` → `main` | |
| P3 Backup v2 + re-import | [P3.md](P3.md) | **done** (2026-11-07) | `claude/eager-heisenberg-s121fy` → `main` | |
| P4 Module framework + Time Machine | [P4.md](P4.md) | **done** (2026-11-07) | `claude/eager-heisenberg-s121fy` → `main` | |
| P5 Inventory module | [P5.md](P5.md) | **done** (2026-11-07) | `claude/eager-heisenberg-s121fy` → `main` | |
| P6 Lab notebook module | [P6.md](P6.md) | **done** (2026-11-07) | `claude/eager-heisenberg-s121fy` → `main` | |
| P7 Tool sources (separate repos) | [P7.md](P7.md) | **done** (2026-11-07): the tools are in `smith-lab/lab-tools`, and `tools/` is gone from here | `claude/eager-heisenberg-s121fy` → `main` | see P7.md Log |
| P8 Finishing | [P8.md](P8.md) | **done** (2026-11-07), the shims removed on the owner's word | `claude/eager-heisenberg-s121fy` → `main` | see P8.md Log |

P1 is independent of P2–P6 and can run in parallel with them. Everything else is in order.

## Confirmed decisions (2026-11-07)

These come from §1 of the plan. Don't reopen them without the owner.

| | Decision |
|---|---|
| D1 | Tools repository: `smith-lab/lab-tools`, private. The server's token gets read access. |
| D2 | Extra public tool repositories are added only from System & updates, **disabled and pinned to a commit** until a person enables them. Foreign repositories never get the token. |
| D3 | Input files are copied into each job folder at submit time (cap: 200 MB per job; above it, only names and checksums). |
| D4 | Plots in backups: always `.html` (offline) plus their data in `results.xlsx`; also `.png` when `kaleido` is installed. |
| D5 | Module data that is job-like (Time Machine) lives under `<storage>/modules/<id>/`. Git clones of GitHub repositories (inventory, notebook) live under `<data_dir>/modules/<id>/`. |
| D6 | **The Lab notebook is a module** (`modules/notebook`, phase P6). The modules are `timemachine`, `inventory` and `notebook`. |
| D7 | The backup folder layout stays `<backup>/<person>/<date>_<keyword> <tool> (<job id>)/`. |

## Rules for every task

1. **One phase per branch.** Name it `reorg/p<N>-<short-name>`, unless your session was given its own branch.
   Then use that, and say which phase it is in the commit messages.
2. **Main stays deployable.** The lab server may update itself from `main` at night. A phase is merged only
   when its "Done when" list passes. Work that is half done stays on its branch.
3. **Run the tests before every push:** `.venv/bin/python -m pytest -q`. Never skip, delete or weaken a test to
   get green. If an old test's expectation really changes (because the format changes on purpose), change it
   and say why in the commit message.
4. **Never break old data.** Every format change keeps a reader for the old format. Fixtures in
   `tests/fixtures/*_v0/` (from P0) must load **in every phase**. Treat them as read-only; never regenerate
   them.
5. **Migrations copy, verify, then switch.** Never move or delete the only copy of anything. Old folders are
   renamed to `*.migrated-<date>`, not deleted.
6. **Keep links and ids stable:** `/tool/<id>`, job ids, `/api/jobs/...`, `/timemachine/<id>`, `/reagents/<n>`,
   `/notes/<id>`. Add redirects if a URL must move.
7. **Follow the house style.**
   - Module docstrings explain things from the lab's point of view.
   - User-facing messages are full sentences in English, raised as `ToolError`, and get a Polish entry in the
     locale catalogue. `tests/test_i18n.py` must stay green.
   - Comments are short and useful.
8. **Don't widen the scope.** Do what the phase file says. If you find a bug or a needed change outside it,
   write it under "Found along the way" at the end of the phase file. Don't fix it in passing.
9. **Leave a trail.** When you finish a task, tick it in the phase file (`- [x]`), and add one line under
   "Log" with the date, the commit and anything the next agent must know.
10. **Commit and push** as `CLAUDE.md` says. A session with its own branch also fast-forwards `main`, but only
    when the phase's "Done when" holds.

## How the phase files are written

Each `P<N>.md` has the same sections:

- **Goal:** one paragraph.
- **Before you start:** what must already be true.
- **Tasks:** numbered tasks, each with files, steps and its own check. They are ordered; a task marked
  *(parallel)* doesn't depend on the ones before it.
- **Done when:** the acceptance list for merging the phase.
- **Rollback:** how to go back if the phase misbehaves on the lab server.
- **Log** and **Found along the way:** filled in while working.

## Glossary

| Word | Meaning |
|---|---|
| base | everything in `mister_plis/`: the app without modules or tools |
| module | a large feature in `modules/<id>/` with its own pages, data and background work (Time Machine, Inventory, Lab notebook) |
| tool | one file defining `tool = Tool(...)`; from P7 on, tools come from tool sources |
| tool source | a git repository of tools (the lab's `MISTER_PLIS-tools`, or a public one) |
| storage | the folder the user chooses for jobs and job-like module data (`storage_dir`, from P2) |
| data dir | the server's own state folder (`data_dir`): settings, small JSON stores, git clones |
| v0 / v1 | today's on-disk formats (described in [../FORMATS.md](../FORMATS.md)) / the new ones from P2 and P3 |
