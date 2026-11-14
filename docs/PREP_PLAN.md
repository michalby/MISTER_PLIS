# Plan: preparing MISTER PLIS for the final version

*November 2026. Status: **done** — R1–R11 (the log is in §15; the review after R3 that added R11 and changed the order is §16). What is left is the final version's own work and the owner's questions (§14). Written so that another agent (or person) can carry it out
without the conversation it came from. The direction is in [FINAL_VERSION.md](FINAL_VERSION.md); this plan does
**not** build the final version (no login, no remote workers, no release installer). It puts in
the **seams** those need, so each can later be added without reworking what is here, and it fixes what ties the
server to one Mac today.*

---

## 0. Read this first (for whoever implements it)

**Before starting:** read `CLAUDE.md`, then `docs/ARCHITECTURE.md`, `docs/MODULES.md`, `docs/FORMATS.md`,
`docs/LAB_SETUP_PLAN.md`, `docs/BETA.md`, `docs/FINAL_VERSION.md`. Set up with `./scripts/setup.sh --dev` and run
`.venv/bin/python -m pytest` (all green before you change anything; ~250 tests, ~30 s).

**Rules of this codebase that every work package below must keep** (each has a test that fails if broken):

| Rule | Where it is checked |
|---|---|
| The base (`mister_plis/`) never names or imports a module (`timemachine`, `inventory`, `notebook`, and words like "notebook", "obsidian", `/api/tm`…); modules plug in through `mister_plis/modules.py` | `tests/test_modules.py::test_the_base_does_not_name_its_modules`, `::test_the_base_runs_without_any_module` |
| No lab in the code: no lab's repository, folder or tool id as a default | review; `labs/template.toml` must name every setting (`tests/test_labsetup.py::test_the_template_names_every_setting`) |
| Tools import only `mister_plis.toolkit`; a change to `toolkit.__all__` or to `Tool`'s fields is an API change: an addition raises `TOOLKIT_VERSION`'s minor number (1.1 → 1.2) | `tests/test_tool_boundary.py` |
| Never break old data: every on-disk format is in `docs/FORMATS.md`; the frozen fixtures in `tests/fixtures/*_v0/` stay readable; add a reader, never change an old one | `tests/test_formats_v0.py`, `tests/test_backup*.py` |
| Files on disk are English; every interface text has Polish (`mister_plis/locale/pl_ui.py` for the base, `modules/<id>/locale/pl.py` for a module) | `tests/test_i18n.py::test_every_interface_text_has_polish` (texts in templates `_("…")` and scripts `MP.t("…")`) |
| Data that moves: copy, check, then switch; rename the old, never delete | review (`storage.move_folder_once`, `copy_verified`, `gitutil.set_aside`) |
| A setting a lab chooses goes into the lab file too (`mister_plis/labsetup.py` `BASE`, or a module's `setup_fields` / `configure`) and into `labs/template.toml` | `tests/test_labsetup.py` |

**How to work:** one work package (§3–§12) per branch/commit series; each ends with all tests green, its docs updated
(the files named in its "Docs" line), and a commit message saying what changed for the lab. Push to the session's
branch and keep `main` up to date with it (CLAUDE.md). Where a package says **ask the owner**, do the default it gives
and note the question in the commit message instead of stopping.

**Style:** the code's comments and docstrings, the docs and the interface use plain words for a lab audience (see the
existing files). Interface texts are short and say what happens ("Copy everything", "Move here"). New interface text
needs Polish in the same commit.

---

## 1. Goal and what is out of scope

**Goal:** after this plan, MISTER PLIS (still the beta, still updated from GitHub) also:

1. keeps an instance's own files apart from its code (§3), so the code can be replaced by a release;
2. restarts and runs on Linux and Windows as well as macOS, tested on all three (§4);
3. keeps its GitHub access in a place of its own, one token per repository owner if needed, not only the Mac's Keychain
   (§5);
4. runs in Docker, with a Linux service as the alternative (§6);
5. has version numbers that mean something, a changelog, a formats register, release builds, and an update "channel"
   seam with today's git updates behind it (§7);
6. installs tools' packages outside the app's own Python environment (§8);
7. understands bundled tool sources and a tool catalogue (§9);
8. runs jobs through a "runner" seam that a remote worker can later fill (§10);
9. marks every route that changes something as "settings" or "work", ready for a login (§11);
10. has an identity per instance and a place for the addresses of other services (§12).

**Out of scope:** the login itself, remote workers, installing releases side by side (only designed here), the
tool catalogue's public hosting, splitting the tools repository (another
repository; only instructions here, §9.6).

---

## 2. The code today: where each concern lives

| Concern | Where | What it does now | Touched by |
|---|---|---|---|
| Code folder and instance files | `mister_plis/config.py`: `ROOT` (the checkout), `Settings.data_path` (`ROOT/data` by default), `load_settings()` reads `ROOT/config.toml`, `Settings.module_settings()` reads it again | code and instance in one folder | §3 |
| Restart | `mister_plis/updater.py` `schedule_restart()`: `os.execv(sys.executable, [-m mister_plis …])` | POSIX only in practice; the Mac app's launcher (`macos/launcher/main.swift`) also restarts a server that exits | §4 |
| Host name | `mister_plis/app.py` `_local_hostname()`: runs `scutil` (macOS) | falls back to `socket.gethostname()` | §4 |
| GitHub token | `mister_plis/gitutil.py` `credential_args()`: copies the code checkout's `credential.helper` (on the Mac app: `osxkeychain`) into every git call with `credentials=True`; `run(..., credentials=...)` | one token for every repository, from the Keychain | §5 |
| Who may reach which repository | `mister_plis/toolsources.py` `ToolSources.git()`: a source that isn't `trusted` gets `-c credential.helper=` (no token); `mister_plis/labsetup.py` `reach()` tries without, then with the token | foreign sources never get the token | §5 |
| Updates | `mister_plis/updater.py`: `status()`, `check()`, `sync()` (`git pull --ff-only`, then `pip install -r requirements.txt` when it changed), `branches()`, `switch()`, `auto_update()` (nightly), `RUNNING` (commit at start); routes `/api/system/*` in `app.py`; UI `templates/settings/server.html`, `static/js/settings.js` | git only | §7 |
| Version | `mister_plis/__init__.py` `__version__ = "0.1.0"` (never raised); `pyproject.toml` reads it | meaningless today | §7 |
| CI | `.github/workflows/tests.yml`: Ubuntu, Python 3.12, `pytest` | Linux only | §4, §6, §7 |
| Tool packages | `toolsources.py` `ToolSources._requirements()`: `pip install -r <source>/requirements.txt -c <pins>` into **the app's own environment** (`sys.executable`), after a dry run (`mister_plis/pins.py`) | tools change the app's environment | §8 |
| Tool sources | `toolsources.py` (`sources()` from `<data>/tool_sources.json`; clones in `<data>/tool-sources/<name>/`; `local_folders()` from `tool_folders`); `registry.py` `Registry.load()` / `_load_folder()` (each source its own package `mp_tools_<name>`) | git clones and local folders | §8, §9 |
| Running jobs | `mister_plis/jobs.py` `JobManager.submit()` → `self.pool.submit(self._run, job, tool)` → `_run_job()` (parse params, `tool.run_fn(params, ctx)`, `_render()` outputs, `save_meta()`); `RunContext` in `toolkit.py` | threads in the app's process | §10 |
| Who someone is | a cookie `name` (`prefs.from_cookies(request.cookies)["name"]`), read in `app.py` (11 places) and in modules via `ctx.who(request)` / their own `_who()` (27 places); `people.py` merges names | anyone may do anything | §11 |
| Lab's setup | `mister_plis/labsetup.py` (lab file, `lab.json`), `mister_plis/transfer.py` (moving an instance) | done (L1–L5, beta) | §3, §12 |
| Mac-only installer | `scripts/build_app.sh`, `macos/launcher/main.swift`; `scripts/install_service.sh` (an older macOS LaunchAgent) | macOS only | §6 |

---

## 3. R1 — The instance's home, apart from the code

**Why.** A release (or a Docker image) replaces the code folder; the instance's `config.toml`, data and secrets must
not live inside it. Today `config.toml` is read from `ROOT` and `data_dir` defaults to `ROOT/data`.

**Changes.**

1. `mister_plis/config.py`:
   - Add `HOME = Path(os.environ.get("MISTER_PLIS_HOME") or ROOT).expanduser().resolve()` next to `ROOT`, with a
     comment: *ROOT is the code (read-only in a release); HOME is this instance (config.toml, data/, secrets/, logs/).
     Without MISTER_PLIS_HOME they are the same folder, as before.*
   - `load_settings()` and `Settings.module_settings()`: read `HOME / "config.toml"` (both places; factor a helper
     `_config_table() -> dict` used by both, which also removes the double read).
   - `Settings.data_path`, `storage_path` (for a relative `storage_dir`) and `tool_folder_paths()`: relative paths are
     relative to `HOME`, not `ROOT`.
   - Add `Settings.secrets_path` (`HOME / "secrets"`) and `Settings.logs_path` (`HOME / "logs"`), properties only.
2. `mister_plis/labsetup.py`: `read_source()` keeps reading relative paths against `ROOT` (lab files that come with the
   code, `labs/`), and **also** tries `HOME / path` when it doesn't exist there; `lab_files()` lists `ROOT/labs/*.toml`
   and `HOME/labs/*.toml` (the instance's own lab files), marking which is which (`"where": "code" | "instance"`).
3. `mister_plis/storage.py` `check_folder()`: besides "not inside the code folder", refuse the instance's `secrets/`.
4. New `mister_plis/install.py`:

   ```python
   def kind() -> str:
       """How this instance was installed: "docker", "mac-app", "checkout" (a git clone), or "package"."""
   ```

   Order: env `MISTER_PLIS_INSTALL` if set (`docker`, `mac-app`, `service`…: the Dockerfile and the launcher set it);
   else `"checkout"` if `(ROOT / ".git").exists()`; else `"package"`. Also `def describe() -> dict` →
   `{"kind", "code": str(ROOT), "home": str(HOME), "data": …, "storage": …}`.
5. `app.py` `_server_info()`: add `"install": install.describe()`; `static/js/settings.js` (Server panel `#server-info`):
   show *Installed as* (kind) and *Instance folder* (home) rows. Polish for the new labels.
6. `macos/launcher/main.swift` `childEnvironment()`: set `MISTER_PLIS_INSTALL=mac-app` (HOME stays the checkout: the
   app's layout doesn't change in this plan). Mark in the commit that the Swift change is not compiled in CI.
7. `scripts/run.sh`, `scripts/dev.sh`: unchanged (they work from the checkout: HOME = ROOT).

**Formats.** None change. `docs/FORMATS.md` intro: "paths are relative to the data folder", add one sentence on HOME.

**Tests** (new `tests/test_home.py`):
- with `MISTER_PLIS_HOME=<tmp>` in a subprocess: `config.toml` there is read (e.g. `port = 9123` → `settings.port`),
  `data_path == <tmp>/data`, a relative `storage_dir` is under `<tmp>`;
- without it: `HOME == ROOT` (nothing changes for existing installs);
- `install.kind()`: env wins; a folder with `.git` → `"checkout"`; else `"package"`;
- `labsetup.lab_files()` lists a `HOME/labs/x.toml`.

**Done when:** an instance can live in any folder (`MISTER_PLIS_HOME=/srv/mister-plis python -m mister_plis`) with
the code elsewhere and read-only; existing installs behave exactly as before. **Docs:** `ARCHITECTURE.md` (config.py
row, a line on HOME vs ROOT), `README.md` (Configuration), `config.example.toml` (header: where config.toml lives).
**Size:** S.

---

## 4. R2 — Linux and Windows: restart, small macOS assumptions, CI on three systems

**Why.** `os.execv` restart and `scutil` are POSIX/macOS habits; nothing tests on Windows or macOS.

**Changes.**

1. `updater.schedule_restart(delay)`:
   - if env `MISTER_PLIS_SUPERVISED=1` (a supervisor restarts the process: Docker's restart policy, systemd
     `Restart=always`): after `delay`, flush and `os._exit(RESTART_EXIT_CODE)` with `RESTART_EXIT_CODE = 75`;
   - else on Windows (`os.name == "nt"`): start `subprocess.Popen([sys.executable, "-m", "mister_plis", *sys.argv[1:]],
     cwd=ROOT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)` then `os._exit(0)` (execv on Windows doesn't keep
     the process and the port may still be held: wait for the old socket to close — the new process retries binding
     for up to 10 s, see 2.);
   - else `os.execv` as today. The Mac app's launcher does **not** set `MISTER_PLIS_SUPERVISED` (it keeps today's
     behaviour, which works).
2. `__main__.main()`: before `uvicorn.run`, if the port is taken, retry for up to 10 s (a restart on Windows overlaps).
3. `app._local_hostname()`: call `scutil` only when `sys.platform == "darwin"`.
4. **File and folder names that Windows (and SMB shares) refuse.** Audit `toolkit.safe_filename()`,
   `jobs.Job.file_name()` / `clean_text()`, `backup.job_folder()` (backup folders named after a person, keyword and
   tool), `export/` names, `transfer.export()` folder name: none may produce `<>:"/\|?*`, a control character, a
   trailing dot or space, or a reserved name (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, any case,
   with or without extension). Add one helper in the base, e.g. `toolkit.safe_filename` gains the rules (it is part of
   the toolkit: behaviour change only for names that were invalid anyway — note it in `TOOLKIT_VERSION`'s comment, no
   version bump needed since the signature is unchanged), and use it everywhere a name is built from user text.
   **Old backups and jobs keep their names** (readers look folders up by job id, not by name: check that
   `backup.BackupCatalogue` finds a folder by the `(<job id>)` suffix and the manifest only).
5. `.github/workflows/tests.yml`: a matrix `os: [ubuntu-latest, macos-latest, windows-latest]`, Python 3.12. Windows
   starts with `continue-on-error: true`; fix what fails (expect: `file://` URLs built from Windows paths in tests —
   use `Path.as_uri()`; `/bin/sh` used as a sample program path; line endings in text compared byte for byte; git
   `core.autocrlf` — set `git config --global core.autocrlf false` in the workflow; paths with `\`); then remove
   `continue-on-error`. Don't skip a test to get green: make the code or the test portable.
6. `mister_plis/gitutil.py` `LOCAL_PUSH` uses `git -c receive.denyCurrentBranch=updateInstead receive-pack` as a
   `--receive-pack` program: check it works with Git for Windows (it runs through its shell); if not, document that a
   local-folder inventory isn't supported on Windows yet (a lab there uses a GitHub repository).

**Tests:** `tests/test_restart.py` with `schedule_restart` monkeypatched (`os._exit`, `os.execv`, `subprocess.Popen`)
for the three branches; `tests/test_filenames.py` for the reserved names/characters (parametrized), including that a
v0 backup fixture is still found by `BackupCatalogue`.

**Done when:** CI is green on Ubuntu, macOS and Windows; a supervised server exits with 75 to restart. **Docs:**
`ARCHITECTURE.md` (Testing: three systems), `docs/FORMATS.md` §3/§11 (one line: names are made safe for Windows and
SMB from this version; older names are kept). **Size:** M.

---

## 5. R3 — The instance's own GitHub access, one token per owner if needed

**Why.** Today the only token is the code checkout's credential helper (the Mac's Keychain). Docker, Linux and Windows
have no Keychain; and a fine-grained GitHub token reaches one owner's repositories only (docs/BETA.md §2), so a lab
whose code and data have different owners needs two tokens.

**Changes.**

1. New `mister_plis/credentials.py`:
   - The store: `<HOME>/secrets/git-credentials.toml` (created with mode `0o600`; the folder `0o700`):

     ```toml
     # Tokens this instance uses to read (and, for a module's repository, write) git repositories.
     # The most specific match wins: owner/repo, then owner, then host. Never committed, never in a lab file,
     # never in a transfer.
     [[token]]
     host = "github.com"
     owner = "smith-lab"          # optional
     repo = ""                    # optional, e.g. "inventory"
     token = "github_pat_…"
     ```

   - `token_for(host: str, path: str) -> str | None` (path like `smith-lab/inventory.git`): the most specific entry;
     then env `MISTER_PLIS_GIT_TOKEN` (any host, for Docker secrets); else `None`.
   - `set_token(host, owner, repo, token)`, `remove_token(...)`, `list_tokens() -> [{host, owner, repo, last4,
     added}]` — never returns a token.
   - A git credential helper entry point: `python -m mister_plis.credentials get` reads git's credential protocol on
     stdin (`protocol=`, `host=`, `path=` lines), prints `username=x-access-token` and `password=<token>` when
     `token_for` finds one, prints nothing otherwise (git then tries the next helper). `store`/`erase` are no-ops.
2. `mister_plis/gitutil.py` `credential_args()`: return, in order, `-c credential.helper=` (clear), `-c
   credential.useHttpPath=true`, `-c credential.helper=!"<sys.executable>" -m mister_plis.credentials` (quoted for
   paths with spaces; on Windows use forward slashes), then the code checkout's own helpers as today (so the Mac app's
   Keychain keeps working as the fallback). The token never appears in a command line or a log.
3. Callers stay as they are: `credentials=True` still means "this repository may get the instance's tokens";
   `toolsources.ToolSources.git()` still clears all helpers for a source that isn't trusted.
4. Interface: *Settings → Server & updates* → a panel **GitHub access** (scope: whole lab): the list from
   `list_tokens()` (owner/repo, `…last4`, added when), **Add a token** (host default `github.com`, owner, repo
   optional, token field `type=password`, never echoed back), **Remove**, and a line saying where else access comes
   from (`MISTER_PLIS_GIT_TOKEN` set; the Mac's Keychain via the code checkout). Routes `GET /api/system/credentials`,
   `POST /api/system/credentials`, `DELETE /api/system/credentials` (marked "settings" in §11). Polish for all texts.
5. The setup page's **Check** (`labsetup.check_access`) already says which repositories can't be read: add to its
   note "add a token for <owner> on Settings → Server & updates → GitHub access".
6. `transfer.py`: `secrets/` is under HOME, not under the data folder, so it is never copied; add an explicit test.

**Formats:** `docs/FORMATS.md` new section "The instance's secrets" (the file above; mode; never copied).

**Tests** (`tests/test_credentials.py`): most specific match wins; env fallback; the helper protocol (feed stdin, read
stdout); the file is created `0600` (skip the mode check on Windows); `list_tokens()` never contains a token; a git
call with `credentials=True` against a local bare repository served over `file://` doesn't break (helpers are only
asked for http(s)); an untrusted tool source's git call has no helper (inspect the command built by
`ToolSources.git`); a transfer never contains `secrets/`.

**Done when:** a Linux/Docker instance reads private repositories with a token added on its Settings page (or from
`MISTER_PLIS_GIT_TOKEN`), two owners can have two tokens, and the Mac app behaves as before. **Docs:** `BETA.md` §2
(his token can go in GitHub access instead of a classic token, once this exists), `DEPLOY_MAC_STUDIO.md` (Keychain
remains), `ARCHITECTURE.md`. **Size:** M.

---

## 6. R4 — Docker (Linux, Windows) and a Linux service

**Depends on:** R1 (HOME), R2 (supervised restart), R3 (token without Keychain).

**Changes.**

1. `Dockerfile` at the root:
   - `FROM python:3.12-slim`; `apt-get install -y --no-install-recommends git ca-certificates` (and nothing else);
   - a user `misterplis` (uid 1000), `WORKDIR /app`, `COPY requirements.txt` then `pip install --no-cache-dir -r`,
     then `COPY mister_plis modules labs docs pyproject.toml ./` (docs are read by `/guide`);
   - `ENV MISTER_PLIS_HOME=/srv/mister-plis MISTER_PLIS_INSTALL=docker MISTER_PLIS_SUPERVISED=1
     MISTER_PLIS_HOST=0.0.0.0 PYTHONUNBUFFERED=1`; `VOLUME ["/srv/mister-plis", "/storage", "/backup"]`;
   - `EXPOSE 8000`; `HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/version',timeout=3)"`;
   - `USER misterplis`; `CMD ["python", "-m", "mister_plis"]`.
2. `.dockerignore`: `.git`, `.venv`, `data`, `logs`, `config.toml`, `build`, `dist`, `tests`, `__pycache__`.
3. `deploy/docker-compose.yml` (example): one service, `restart: unless-stopped`, port `8000:8000`, volumes
   `./home:/srv/mister-plis`, `./storage:/storage`, `/mnt/nas/mister-plis:/backup`, optional `env_file: secrets.env`
   with `MISTER_PLIS_GIT_TOKEN`; a comment: choose `/storage` as the storage folder and `/backup` as the backup folder
   on the setup page (or `[jobs] storage_folder = "/storage"` / `[backup] folder = "/backup"` in a lab file).
4. In a Docker instance, *Settings → Server & updates* must not offer **Sync with git**, **Run another branch** or
   **Update by itself** (there is no checkout): `updater.status()` returns `"is_repo": False` already when there is no
   `.git`; make the panel say instead "This server runs in Docker: it is updated with a new image (docker compose pull
   && docker compose up -d)." (driven by `install.kind()`, §3; the channel seam in §7 takes this over).
5. `deploy/mister-plis.service` (systemd, Linux without Docker): `User=`, `WorkingDirectory=` the checkout,
   `Environment=MISTER_PLIS_HOME=… MISTER_PLIS_SUPERVISED=1 MISTER_PLIS_INSTALL=service`,
   `ExecStart=<checkout>/.venv/bin/python -m mister_plis`, `Restart=always`, `RestartSec=2`. And
   `docs/DEPLOY_LINUX.md`: install (`scripts/setup.sh`), the unit, the firewall, updating (git in a checkout), and the
   Docker way; `docs/DEPLOY_WINDOWS.md`: Docker Desktop (WSL 2 backend), the compose file, where the folders are, and
   that the NAS is mounted into the container (`/backup`).
6. CI: a job `docker` on Ubuntu that builds the image and runs it for 30 s against a temporary HOME volume: `curl
   /api/version` must answer, `/` must lead to `/setup` (a new instance), and a restart through `POST
   /api/system/restart` must bring it back (supervised exit 75 + `--restart unless-stopped` in `docker run`).

**Tests:** besides CI's docker job, `tests/test_install.py` checks the Server panel's text for `kind == "docker"`
(monkeypatch `install.kind`).

**Done when:** `docker compose up -d` gives a working instance on Linux and on Windows (Docker Desktop), it survives
restarts and keeps its data in volumes, and a transfer (`docs/BETA.md` §4) moves an instance into it. **Docs:** the two
new deploy guides, `README.md` (Install: three ways), `FINAL_VERSION.md` §2 (mark "Docker image" as done).
**Size:** M.

---

## 7. R5 — Versions, a changelog, a formats register, release builds, and the update channel seam

**Why.** The final version updates from tested releases (FINAL_VERSION.md §3). This package makes versions real,
builds releases, and puts today's git updates behind an interface a release channel can later fill — without
building the side-by-side installer yet.

**Changes.**

1. **Version numbers.** `__version__` follows `MAJOR.MINOR.PATCH`: MAJOR for a change a lab must act on (e.g. a data
   format older versions can't read), MINOR for new features, PATCH for fixes. Start at `0.9.0` (the beta).
   `CLAUDE.md`: "a change the lab will notice raises the version and adds a line to CHANGELOG.md".
2. **`CHANGELOG.md`** (newest first): per version, a date and plain-language lines for the lab ("Moving a server to
   another machine", "Fixed: …"). Write the entries for the work so far (L1–L5, transfer, this plan's packages as they
   land) under `0.9.0`.
3. **The formats register** `mister_plis/formats.py`:

   ```python
   WRITES = {"job": 1, "job_index": 1, "backup": 1, "backup_catalogue": 1, "lab_file": 1, "lab_state": 1,
             "transfer": 1, "tool_settings": 1, "credentials": 1}   # what this version writes
   READS = {"job": (0, 1), "backup": (0, 1), "lab_file": (1, 1), …}  # what it can read
   ```

   with a test that each number equals the constant where the format is written (`jobformat` / `jobstore` version,
   `backup.VERSION`, `labsetup.FORMAT`, `transfer.VERSION`, `toolsettings.FORMAT`, …) — so a format change can't be
   made without the register (and the feed, below) saying so. `/api/version` returns `formats: WRITES`.
4. **Release builds** `.github/workflows/release.yml`, on a tag `v*`:
   - run the tests (the matrix from §4);
   - build the sdist/wheel (`python -m build`; `pyproject.toml` already packages `mister_plis` and `modules`);
   - build the Docker image and push it to `ghcr.io/<owner>/mister-plis:<version>` and `:beta` (or `:stable`, from a
     `channel:` line in the tag message; default `beta`), with `GITHUB_TOKEN` only;
   - write `feed-<channel>.json` (format below) and attach it, the wheel and `CHANGELOG.md`'s section to the GitHub
     release. (The Mac app stays built by hand with `scripts/build_app.sh` — it needs a Mac.)
   - **Ask the owner** (FINAL_VERSION.md F1, F2): public or private repository decides whether a server can read the
     feed without a token. Until answered, build everything, publish the feed as a release asset only.
5. **The feed** (new `docs/FORMATS.md` section "Release feed"):

   ```json
   {"format": "mister-plis-release-feed", "format_version": 1, "channel": "beta",
    "releases": [{"version": "0.9.1", "date": "2026-12-01", "notes": "…", "notes_pl": "…",
                  "writes": {"job": 1, …}, "min_reads": {"job": 0, …},
                  "artifacts": {"wheel": {"url", "sha256"}, "docker": "ghcr.io/…:0.9.1"}}]}
   ```

6. **The update channel seam**: a new package `mister_plis/updates/` with

   ```python
   class Channel(Protocol):
       name: str                                  # "git", "release", "docker"
       def status(self) -> dict: ...              # {"current": {...}, "available": [...], "can_update": bool,
                                                  #  "can_go_back": bool, "how": "…", "notes": "…"}
       def update(self, to: str = "") -> dict: ...  # step log like updater.sync(); the caller restarts
       def go_back(self, to: str) -> dict: ...    # raises ToolError when not possible
   ```

   - `GitChannel`: wraps today's `updater` functions **unchanged** (status/check/sync/branches/switch/auto_update keep
     their behaviour and their routes; existing tests must pass untouched).
   - `DockerChannel`: `status()` reads the feed (if configured) and says "update with a new image"; `update()` raises
     with that instruction.
   - `ReleaseChannel` (for `install.kind() == "package"`): reads the feed and shows what is available; `update()` raises
     "not available yet" — the installer is the final version's (design in 7.8).
   - `channel()` picks by `install.kind()`: checkout and mac-app → `GitChannel`; docker → `DockerChannel`; package →
     `ReleaseChannel`. The Server tab's version panel shows `status()["how"]`.
   - Settings: `[updates] channel = "beta" | "stable"` and `feed = "https://…"` in the lab file (`labsetup.BASE`,
     template), stored in `auto_update.json` (add the keys; old files lack them: defaults).
7. **A snapshot before every update:** `transfer.export(..., only=("data",))` gains an option to copy the data folder's
   settings only (no jobs, no storage), into `<HOME>/snapshots/<date> before <version>/`; `GitChannel.update()` (and
   the nightly update) make one first and keep the last 5. A restore is the transfer's import with an option to bring
   settings into a server that has jobs (settings only) — add `bring_in(..., only=("data",))` that refuses anything
   but `data/…` files, sets aside only what it replaces, and leaves jobs alone. Show the snapshots on the Server tab
   (list, Restore settings from this snapshot).
8. **Designed, not built — side-by-side install (for the final version):** `<HOME>/versions/<version>/` each a venv
   with the wheel installed; `<HOME>/current` pointing at one; the launcher (Mac app, systemd unit, Windows service)
   starts `<HOME>/current/bin/python -m mister_plis`; an update installs into a new folder, makes a snapshot, switches
   `current`, restarts; if `/api/version` doesn't answer within 60 s, it switches back by itself; **Go back** is
   allowed while the newer version's `writes` are all within the older one's `READS`. Write this down in
   `FINAL_VERSION.md` §3 as the agreed design.

**Tests:** `tests/test_formats_register.py`; `tests/test_updates.py` (channel chosen by kind; `GitChannel` returns what
`updater` returns; `DockerChannel`/`ReleaseChannel` read a feed file from a local `file://` path or a test server;
an update makes a snapshot; restoring a snapshot brings back `lab_settings.json` and leaves a job in place);
`tests/test_changelog.py` (the top entry's version equals `__version__`).

**Done when:** versions and changelog are kept; a tag builds and publishes the wheel, image and feed; the Server tab
says how this instance is updated; every update leaves a snapshot that can be restored. **Docs:** `FORMATS.md` (feed,
snapshots, formats register), `ARCHITECTURE.md`, `README.md` (How updating works), `CLAUDE.md` (version and changelog
rule). **Size:** L.

---

## 8. R6 — Tools' packages outside the app's environment

**Why.** Today a tool source's `requirements.txt` is installed into the app's own Python (`sys.executable -m pip
install …`). A release or a Docker image has an environment that is replaced on update (and may be read-only), so
tools' packages must live with the instance.

**Changes.**

1. `toolsources.ToolSources._requirements()`: install with `pip install --target <data>/tool-packages/<source name>
   -r … -c <pins>` (keep the dry run and the "never change the base's packages" rule of `pins.py`); write
   `<data>/tool-packages/<source name>/.mister-plis.json` = `{"requirements_sha256", "python": "3.12.x", "platform":
   sys.platform, "installed_at"}`.
2. `registry.Registry.load()`: before importing a source's tools, append (not prepend: the base's packages win)
   `<data>/tool-packages/<name>` to `sys.path` for each enabled source; drop the paths of sources no longer enabled.
3. `ensure_requirements()` (at start): reinstall a source's packages when its `.mister-plis.json` doesn't match the
   requirements' hash, this Python's version or this platform (a moved instance, §transfer; a new Python in an update).
4. `transfer.SKIP_DATA` gains `"tool-packages"` (built for one machine; rebuilt at the next start).
5. Existing installs: packages already in the app's environment keep working (nothing is removed); the next update of a
   source installs into the new place. Note it in `CHANGELOG.md`.

**Tests:** adapt `tests/test_toolsources.py::test_at_start_a_source_gets_the_packages_it_lacks` and the requirements
tests (they use `pip_extra = ["--no-index", "--find-links", …]`) to check the target folder, the marker file, the
reinstall on a changed hash, and that a tool imports its package from there; `tests/test_transfer.py`: tool-packages
not in a transfer.

**Done when:** a tool source's packages are installed under the instance's data folder and survive replacing the code.
**Docs:** `ADDING_TOOLS.md` (where packages go), `FORMATS.md` (the folder and its marker), `ARCHITECTURE.md`.
**Size:** M.

---

## 9. R7 — Bundled tool sources and a tool catalogue

**Why.** The final version ships every module and a small **basic** tool set with each release, and lets labs browse
published tool sources (FINAL_VERSION.md §4). `CLAUDE.md`'s "no tools live here" stays true: bundled tools are added
to a release at build time, never committed here.

**Changes.**

1. **Bundled sources:** `ToolSources` gains a third kind besides clones and `tool_folders`: every folder in
   `<ROOT>/bundled-tools/<name>/` that has a `mister-plis-tools.toml` (absent in a checkout: nothing changes). They are
   trusted, read-only, never updated by git (they change with the release), listed on Settings → Tools with "comes with
   MISTER PLIS (version X)", and can be switched off (stored in `tool_sources.json` as `{"name", "kind": "bundled",
   "enabled": false}`; add the `kind` field to the format with a reader default of `"git"` for old entries). A cloned
   source or a `tool_folders` entry of the same name stands in for a bundled one (as local folders do for clones).
   Order in `folders()`: local folders, then clones, then bundled.
2. **Lab file:** `[[tool_sources]]` entries unchanged; a bundled source can be switched off with
   `[tools] bundled_off = ["basic"]` (labsetup `BASE`, template, test).
3. **Release build** (`release.yml`, §7.4): before building the wheel/image, clone the basic tools repository at the
   tag named in `bundled-tools.toml` at the root of this repository:

   ```toml
   # Tool sources a release brings with it (cloned at build time into bundled-tools/; never committed here).
   [[source]]
   name = "basic"
   url = "https://github.com/<owner>/MISTER_PLIS-tools-basic.git"
   tag = "v1.0.0"
   ```

   and include `bundled-tools/` in the package data and the image. Until the basic repository exists (§9.6), the file
   lists nothing and the build bundles nothing.
4. **Manifest fields** (`mister-plis-tools.toml` `[source]`, all optional, shown on Settings → Tools and in the
   catalogue): `description`, `maintainer`, `homepage`, `license`. `toolsources.read_manifest` already returns the
   table: show them; document in `ADDING_TOOLS.md`.
5. **The catalogue:** a JSON file anywhere on the web (format in `FORMATS.md`):

   ```json
   {"format": "mister-plis-tool-catalogue", "format_version": 1,
    "sources": [{"name": "plantlab", "title": "Plant lab tools", "description": "…", "url": "https://github.com/…/….git",
                 "branch": "main", "maintainer": "…", "requires_toolkit": ">=1.1,<2", "tags": ["plants", "imaging"]}]}
   ```

   Setting `[tools] catalogue = "https://…"` (labsetup `BASE`, template; stored in `lab_settings.json`). Settings →
   Tools → **Browse** (a panel shown when a catalogue is set): its sources not added yet, with their description and
   whether this MISTER PLIS's toolkit fits (`toolsources.toolkit_ok`); **Add** calls the existing
   `ToolSources.add(url, name, branch, trusted=False)` — added off and pinned, reviewed as today. Reading the
   catalogue: `urllib` with a 10 s timeout, 1 MB limit, cached for an hour in memory.
6. **Splitting the tools repository** (in `smith-lab/lab-tools`, not here; instructions for whoever does it):
   create `MISTER_PLIS-tools-basic` with its own `mister-plis-tools.toml` (`name = "basic"`), move there the tools any
   lab can use, keep the lab's own in `MISTER_PLIS-tools` (`name = "lab"`), move shared helpers into each (a source
   can't import another's). **Ask the owner** which tools are basic (FINAL_VERSION.md F3); until then, leave the
   repository as it is.

**Tests:** `tests/test_toolsources.py`: a bundled folder (a fixture copy of `tests/fixtures/toolsource` placed in a
temporary `bundled-tools/` via a monkeypatched path) is listed, loaded, switched off, and replaced by a clone of the
same name; `tests/test_catalogue.py`: reading a catalogue file, toolkit fit, **Add** makes an untrusted pinned source;
the template test still names every setting.

**Done when:** a release can bring tools with it, and a lab can browse a catalogue and add a source from it.
**Docs:** `ADDING_TOOLS.md`, `FORMATS.md`, `ARCHITECTURE.md`, `labs/template.toml`. **Size:** M.

---

## 10. R8 — A runner seam for jobs (ground for remote workers)

**Why.** The final version can run jobs on other computers (a GPU machine for Blender). Today running is threads
inside `JobManager`. This package separates *what a job is* from *where it runs*, with no change in behaviour.

**Changes.**

1. **The job spec** — `mister_plis/jobs.py`:

   ```python
   @dataclass
   class JobSpec:                     # everything a runner needs, JSON-serializable
       job_id: str
       tool_id: str
       tool_source: str               # the tool source's name ("lab", "basic"…)
       tool_commit: str               # the source's commit (a worker must run the same code)
       params: dict                   # the raw form values (as Job.params)
       inputs: dict                   # input name → [{"id", "name", "path"}]: paths relative to the job folder
       prefs: dict
       record: bool
       workdir: str                   # relative to the storage folder ("jobs/<id>") — or "live/<id>"
       needs: list[str]               # from Tool.needs (2.)
       def to_dict(self) -> dict: ...
       @classmethod
       def from_dict(cls, d: dict) -> "JobSpec": ...
   ```

   `JobManager.submit()` builds a `JobSpec` after `_keep_inputs` (move that call from `_run_job` to `submit` for record
   jobs, so a spec's inputs are always files in the job folder; live jobs keep reading uploads, `inputs` then carries
   the upload paths relative to the data folder and a note that live jobs always run locally).
2. **`Tool.needs`** (toolkit 1.2): a new optional field `needs: tuple[str, ...] = ()`, e.g. `("gpu",)`,
   `("program:blender",)`. Raise `TOOLKIT_VERSION` to `"1.2"` with a comment line; `tests/test_tool_boundary.py` and
   `ADDING_TOOLS.md` updated. Today it is only recorded (in the spec and `job.json`'s `tool` provenance, a new optional
   key `needs`: readers ignore unknown keys; add it to FORMATS §10).
3. **The runner interface** — new `mister_plis/runners.py`:

   ```python
   class Runner(Protocol):
       def start(self, spec: JobSpec, tool: Tool, events: "RunnerEvents") -> None: ...
       def cancel(self, job_id: str) -> None: ...
   class RunnerEvents(Protocol):        # implemented by JobManager
       def started(self, job_id: str) -> None: ...
       def progress(self, job_id: str, fraction: float | None, message: str, logs: list[str]) -> None: ...
       def finished(self, job_id: str, outputs: list[dict] | None, error: str, traceback: str, status: str) -> None: ...
   ```

   `LocalRunner` holds the `ThreadPoolExecutor`, the per-tool semaphores (`max_concurrent`) and the body of today's
   `_run_job` up to `tool.run_fn` and `_render`; `JobManager` keeps the job list, records and the events. **Rendering
   outputs stays where the files are** (the runner side), since it writes files into the job folder; a remote worker
   will need the storage folder mounted (FINAL_VERSION.md §2) — write that down in the module docstring.
4. `JobManager(..., runner: Runner | None = None)` defaults to `LocalRunner(max_workers)`; `app.py` unchanged.

**Tests:** every existing job test passes unchanged (behaviour identical); new `tests/test_runners.py`: a fake runner
receives a spec that survives `json.dumps`/`from_dict`; `JobManager` with the fake runner records progress and the
finished outputs through the events; `Tool(needs=("gpu",))` lands in the spec and in `job.json`.

**Done when:** jobs run exactly as before, through `LocalRunner`, and a job can be described as JSON. **Docs:**
`ARCHITECTURE.md` (jobs.py row), `ADDING_TOOLS.md` (`needs`), `FORMATS.md` §10 (`tool.needs`). **Size:** M.

---

## 11. R9 — Every change marked "settings" or "work" (ground for the login)

**Why.** The final version has people who may change Settings and everyone else (FINAL_VERSION.md §1). Today anyone
on the network may do anything. This package makes every route say which it is, with everyone allowed both for now.

**Changes.**

1. New `mister_plis/access.py`:

   ```python
   @dataclass(frozen=True)
   class Person:
       name: str              # today: the name cookie (prefs.from_cookies); later: the signed-in account
       role: str              # "admin" (may change Settings) or "member"
       signed_in: bool        # False until there is a login
   def current(request: Request) -> Person: ...
   def settings_access(request: Request) -> Person: ...   # FastAPI dependency: 403 for a member (never, today)
   def work_access(request: Request) -> Person: ...       # FastAPI dependency: everyone today
   MODE = "open"   # today every person is "admin"; the login replaces this
   ```

   Each dependency function gets an attribute (e.g. `settings_access.access = "settings"`) so a test can find it on a
   route.
2. **Mark every route that changes something** (POST/PUT/PATCH/DELETE) with `dependencies=[Depends(settings_access)]`
   or `Depends(work_access)`. Base routes in `app.py` (as of this plan; the test in 4. finds any missed):
   - **settings:** `/api/people/merge`, `/api/feedback/{item_id}` (POST: mark done; DELETE), `/api/label/printer`
     (POST), `/api/label/printer/check`, `/api/lab/name`, `/api/lab`, `/api/lab/backup`, `/api/lab/verify`,
     `/api/lab/upgrade`, `/api/jobs/import`, `/api/history/clear` (scope `all`; `mine` is work — split the check inside
     the route), `/api/system/check`, `/api/system/sync`, `/api/system/branch`, `/api/system/auto-update`,
     `/api/system/restart`, `/api/system/storage`, `/api/tools/{tool_id}/settings`, `/api/tools/sources` and every
     `/api/tools/sources/{name}/…`, `/api/setup/*` (all), `/api/transfer/*` (all), `/api/system/credentials` (§5);
   - **work:** `/api/tools/{tool_id}/run`, `/api/tools/{tool_id}/suggest/{input_name}`,
     `/api/tools/{tool_id}/action/{input_name}`, `/api/jobs/{job_id}/title`, `/api/jobs/{job_id}/cancel`,
     `/api/protocol.pdf`, `/api/tools/{tool_id}/label`, `/api/label/preview.png`, `/api/label/print`,
     `/api/feedback` (POST: send), `/api/uploads`, `/api/jobs/{job_id}/report.pdf` (POST).
3. **Modules:** `ModuleContext` gains `settings_access` and `work_access` (from the base's services) and
   `docs/MODULES.md` says every module route that changes something uses one. Mark: inventory — settings:
   `/api/reagents/settings`, `/api/reagents/repository`, `/api/reagents/start`, `/api/reagents/sync` (settings: it
   pushes), `/api/reagents/tidy/settings`, `/tidy/run`, `/tidy/apply-all`, `/tidy/{pid}`, each space's `…/fields`;
   work: adding/editing/restocking/disposing items, info from the lab, order and list files. Notebook — settings:
   `/api/notes/settings`, `/api/notes/folders`, `/api/notes/repository`, `/api/notes/sync`, `/api/notes/check`.
   Time Machine — settings: `/api/tm/backup` (POST), `/api/tm/backup/restore`; work: keeping results, projects,
   tasks. (Go through each `web.py`; the test finds what is missed.)
4. **The test that keeps it so** — `tests/test_access.py`: walk `app.routes` (after the modules load); every route
   whose methods include POST/PUT/PATCH/DELETE must have exactly one dependency with an `access` attribute; the
   failure lists the unmarked routes. Also: with `MODE` monkeypatched to a "member" for everyone, every settings
   route answers 403 and every work route doesn't.
5. **Pages:** `page()` adds `person` (from `access.current`) to every template; `settings.html` and `/setup` show a
   short notice instead of their controls when `person.role != "admin"` (never today). Polish for the notice.
6. **People ↔ accounts:** write down in `FINAL_VERSION.md` §1 how names map to accounts later: an account has a
   display name; the existing names (and `people.json`'s merges) are offered as the accounts' names, so jobs and Time
   Machine entries keep their people.

**Done when:** every route that changes something is marked, the test enforces it, and nothing behaves differently
today. **Docs:** `MODULES.md` (the access rule), `ARCHITECTURE.md`, `CLAUDE.md` (a new route must be marked).
**Size:** M.

---

## 12. R10 — The instance's identity and the addresses of other services

**Why.** Roles on other computers (a model, later workers) need to know which
instance is which, and an instance needs one place for the addresses it talks to.

**Changes.**

1. **Instance id:** `labsetup.migrate()` (every start) adds `"instance": {"id": uuid4().hex, "created_at": …}` to
   `<data>/lab.json` when missing; `labsetup.state()` returns it; `/api/version` returns `instance_id`. A transfer
   carries `lab.json`, so a moved instance keeps its id (it is the same instance); a lab file never contains it (it
   sets a lab up; it isn't an instance). Add to FORMATS §12.
2. **Services:** a lab file section and stored settings for the addresses an instance talks to:

   ```toml
   [services]
   model = "http://192.168.1.20:11434"      # a local model (Ollama) other parts may use
   facility = ""                             # the facility instance (shared booking) — not used yet
   ```

   In `labsetup.BASE` (labels, checks: `http(s)://` or empty), stored in `lab_settings.json` under `"services"`
   (`backup.LabSettings` gains `services: dict`, read with a default; old files lack it), shown on the setup page
   (step 5, *This computer* → rename the step *This computer and its neighbours*, or a new step), and on Settings →
   Server & updates. The template and its test.
3. **Modules use it:** the inventory's `ollama_url`, when not set in its own settings or config.toml, falls back to
   `services.model` — the base offers `ctx.services_address("model")` on `ModuleContext` (the base doesn't know which
   module asks); `modules/inventory/__init__.py` `_setting(ctx, "ollama_url", stored)` uses it as the default before
   `DEFAULTS`. Document in `MODULES.md`.

**Tests:** `tests/test_labsetup.py`: an id is made once and kept; a transfer keeps it; `[services]` read, checked,
stored, exported; the template names it; the inventory takes `services.model` when its own isn't set.

**Done when:** each instance has a stable id and one place for its neighbours' addresses. **Docs:** `FORMATS.md` §12,
`MODULES.md`, `labs/template.toml`, `FINAL_VERSION.md` §2 (Model row: "set once in `[services]`"). **Size:** S.

---

## 13. Order, dependencies and size

```
R1 home ──┬─► R2 platforms ──┬─► R4 Docker ──► R5 versions & channels
          │                  │
          └─► R3 credentials ┘
R6 tool packages (after R1; before R4) ──► R7 bundled & catalogue (after R5's release build for bundling)
R8 runner seam      (independent)
R9 access marks     (independent; after R3 if its credentials routes exist)
R10 identity & services (independent)
```

| Package | Size | Depends on | Changes for the lab when done |
|---|---|---|---|
| R1 | S | — | nothing visible; instance can live apart from the code |
| R2 | M | R1 | names safe on Windows/SMB; tested on three systems |
| R3 | M | R1 | GitHub access on Settings, several owners |
| R4 | M | R1–R3, R6 | Docker and Linux installs |
| R5 | L | R1, R4 | versions, changelog, snapshots before updates, release builds |
| R6 | M | R1 | tools' packages kept with the instance |
| R7 | M | R5 (bundling), R6 | basic tools with releases; Browse a catalogue |
| R8 | M | — | nothing visible |
| R9 | M | (R3) | nothing visible |
| R10 | S | — | `[services]` on the setup page |
| R11 | S | — | the lab's own logo on labels (§16.2; done) |

A sensible sequence for one agent: R1 → R2 → R3 → R9 → R10 → R8 → R6 → R4 → R5 → R7. **After the review (§16.4): R11 → R9 → R10 → R8 → R6 → R4 → R5 → R7**, with R9 and R4 extended by §16.3 and §16.5.

---

## 14. Questions for the owner, and what to do meanwhile

| # | Question (FINAL_VERSION.md §6) | Default until answered |
|---|---|---|
| F1 | Public code (licence?) or private with releases only | keep private; publish the feed as a release asset; servers that need it use a token (R3) |
| F2 | Who builds and signs releases | GitHub Actions on tags; no signing yet (checksums only); note it in the release workflow |
| F3 | Which tools are "basic" | bundle nothing (`bundled-tools.toml` empty) |
| F5 | Login: own accounts or the university's single sign-on | R9's seam fits both; build nothing |
| F6 | Remote workers soon or later | **answered (2026-11-12):** now, for Blender — built in 0.11.0 (docs/WORKERS.md) |
| F7 | A shared settings key before the login (§16.3) | **answered (2026-11-12):** not now — it comes with the login's options |

---

## 15. When it is all done

- Update `docs/FINAL_VERSION.md`: mark in §2, §3, §4 what is prepared (and by which package), and keep the rest as the
  final version's work.
- `docs/ARCHITECTURE.md`'s tables list the new files: `install.py`, `credentials.py`, `formats.py`, `updates/`,
  `runners.py`, `access.py`; `docs/FORMATS.md` has the new formats (secrets, release feed, snapshots, catalogue,
  tool-packages marker, `lab.json`'s `instance`, `tool_sources.json`'s `kind`, `job.json`'s `tool.needs`).
- `CHANGELOG.md` has a line for each package that the lab notices.
- This file's status line says **done**, with a short log (package → commit) as `docs/LAB_SETUP_PLAN.md` §11 has.

**Log.**

| Package | Done | Notes |
|---|---|---|
| R1 | November 2026 | `MISTER_PLIS_HOME`, `install.py`, Server panel rows; the Swift launcher change isn't compiled in CI. In the Mac app's launcher `MISTER_PLIS_HOME` already named its own test folder and is removed from the server's environment, so the app's instance folder stays its checkout. |
| R2 | November 2026 | Restart (supervised exit 75 / new process on Windows / execv), port wait, `scutil` on a Mac only, `safe_filename` refuses Windows' reserved names; CI green on Ubuntu, macOS and Windows. Windows found more than §4 expected: text files weren't read and written as UTF-8 (now every text read/write names it), git clones couldn't be deleted (`gitutil.remove_clone`), `file:///C:/…` was read wrongly (`gitutil.local_folder`). A repository in a folder (`LOCAL_PUSH`) works with Git for Windows. `tests/test_build_app.py` (the Mac app's bash build) is skipped on Windows only. |
| R3 | November 2026 | `credentials.py`, GitHub access panel, `/api/system/credentials`. Unlike §5.2, `credential.useHttpPath` is set only for hosts with a token for one owner or repository (`credential.<host>.useHttpPath`): with it on, the Mac's Keychain looks its token up by path and wouldn't find it, so a Mac app without such tokens behaves exactly as before. The helper runs as `python -I <file>` (git starts it in other repositories' folders, where the package can't be imported). The updater's fetch and pull use the tokens too; `secrets/` is in `.gitignore`. |
| — | 2026-11-12 | **No CI any more** (the owner's choice): `.github/workflows/tests.yml` was removed; the tests are run by hand before every push. Where this plan says CI (§5's docker job, §7's release workflow running the tests), run the same steps by hand instead, unless the owner asks for a workflow. Its last failure (macOS): a folder move copied git's `objects/maintenance.lock` while git's background maintenance removed it — folder copies now leave git's lock files behind (`storage._git_lock`). |
| R4 | 2026-11-12 | `Dockerfile`, `.dockerignore`, `deploy/docker-compose.yml`, `deploy/mister-plis.service`, `deploy/docker-entrypoint.sh`, DEPLOY_LINUX.md, DEPLOY_WINDOWS.md. Beyond §6: the image starts as root only to give the volume folders Docker made to uid 1000 (`MISTER_PLIS_UID`/`GID` to match the host) and then drops to it with `setpriv` — without it a compose bind mount isn't writable. §16.5: every git call says `-c safe.directory=<its folder>` (git honours it on the command line), so repositories owned by another user work (tested as root with a repository given to another uid); `__version__` 0.9.0; `MISTER_PLIS_COMMIT` (a build arg) is the running commit when there is no `.git`; the Version panel says how a Docker or package install is updated and hides the git controls. Tried by hand (no CI): the image built and ran with bind mounts, `/` led to `/setup`, a restart from Settings came back (exit 75, `restart: unless-stopped`) with the same instance id. Not tried: `apt-get install git` in the image (this machine can't reach Debian's mirrors) — so no tool source or module repository was cloned in a container yet. The Mac example paths (`/Volumes/…`) stay (the owner's choice). |
| R5 | 2026-11-12 | `CHANGELOG.md` (0.9.0), the version rule in CLAUDE.md, `formats.py` (+ `jobstore.INDEX_VERSION`, `backup.CATALOGUE_VERSION` named), `updates.py` (one module rather than a package: `Channel`, `GitChannel`, `DockerChannel`, `ReleaseChannel`, `channel()`, the feed, snapshots), `[updates] channel, feed` (lab file, `auto_update.json`), Settings → Server & updates: *Snapshots of the lab's settings* and the newest release when a feed is set. Snapshots are `transfer.export(settings_only=True)` (the data folder's settings, of each module only its top-level files) in `<instance>/snapshots/` — next to the data folder rather than `HOME`, so a test or a data folder elsewhere keeps its snapshots beside it; `transfer.bring_in_settings` restores (only from a `"kind": "settings"` copy). Sync, Run another branch and the nightly update snapshot first; a failed snapshot stops the update. §7.4's release workflow is `scripts/release.sh` + `scripts/make_feed.py`, run by hand (no CI): it publishes nothing (F1, F2). A wheel install ("package") lacks `docs/` and `labs/` (the guide page, the bundled lab files): to settle with the side-by-side installer. |
| R6 | 2026-11-12 | Unlike §8.1, `pip install --prefix <data>/tool-packages/<name>` rather than `--target`: `--target` ignores what is installed and would download every dependency the app has again (pandas…), while a prefix install adds only what is missing. The constraints now pin **every** installed package (`pins.write_constraints(everything=True)`), so pip can never change the app's environment. Built in `<name>.partial`, swapped in; a failure keeps the old folder. `pins.missing(req, paths)` also looks in the source's folder; `ensure_requirements` rebuilds when the marker doesn't fit. |
| R7 | 2026-11-12 | `ToolSources` reads `bundled-tools/<name>/` (trusted, no git, listed as "comes with MISTER PLIS <version>", switched off through the same route as any source; a local folder or a source of the same name stands in). Unlike §9.1, switching one off is stored as `"bundled_off": [...]` beside `"sources"` in `tool_sources.json`, not as entries with a `kind` (an entry needs a `url`; this keeps old readers and entries unchanged); `"catalogue"` is kept there too rather than in `lab_settings.json` (with the other tool-source settings). `[tools] bundled_off, catalogue` in the lab file. `catalogue.py`; Settings → Tools → *Browse a catalogue*; the manifest's `description`, `maintainer`, `homepage`, `license` shown. `bundled-tools.toml` lists nothing (F3); `scripts/release.sh` clones what it lists, the Dockerfile copies `bundled-tools/`. §9.6 (splitting `MISTER_PLIS-tools`) not done: it is another repository and waits for F3. |
| R8 | 2026-11-12 | `runners.py` (`Runner`, `RunnerEvents`, `LocalRunner` with the thread pool and the tools' slots), `jobs.JobSpec`; the JobManager is the runner's events (`context`, `started`, `recording`, `upload`, `render`, `finished`) — `context` (the job's RunContext) and `recording` were added to §10's three, since a local run reports progress through the context the pages read, and kept jobs note their translated pieces. A kept job's inputs are copied at submit (the run route now calls `submit` in a thread, so a large copy doesn't hold the server up). `Tool.needs`, toolkit 1.2, `job.json` → `tool.needs`. |
| R9 | 2026-11-12 | `access.py`; every route that changes something is marked (`SETTINGS` / `WORK` in `app.py`; modules through `ctx.settings_access` / `ctx.work_access` — the inventory's `web.register` takes them as `access=`); clearing everyone's history asks for settings inside the route; `person` on every page, with a notice on Settings and the setup page for someone who may not change them (never today). Plus §16.3.1: `same_site()` refuses a change sent by another web site's page (`Sec-Fetch-Site: cross-site`, or an `Origin` that isn't this server's `Host` / `X-Forwarded-Host`; no `Origin` at all — curl, the CLI — passes). No settings key (F7: with the login). |
| R10 | 2026-11-12 | `labsetup.ensure_instance()` (called by `migrate()` on every start, after its early return — §16.6); `/api/version` → `instance_id`; the id is on Settings → Server & updates. `[services] model, facility` (`labsetup.BASE`, `backup.LabSettings.services`, `/api/lab/services`); the setup page's step 5 asks for the model's address, Settings has a panel *This server's neighbours*; `ctx.services_address()`; the inventory's `ollama_url` falls back to `services.model` before its default. |
| R11 | 2026-11-12 | The lab's logo: `<data>/label_logo.png`, Settings → Exports & printing (**Choose a picture…**, **No logo**), `[label_printer] logo` in a lab file (a picture next to it or an `https://` address, read into the lab as a `data:` address, so a downloaded lab file carries it). Our logo moved to `labs/legacy-label-logo.png`, named by `labs/smith-lab*.toml`. Once at start, a server whose `label_printer.json` predates this keeps a logo only if its lab file names one, or it is older than lab files (`"from": "migrated"`: `labsetup.LEGACY_LOGO`) — a lab set up on the setup page stops printing ours. |

---

## 16. Review after R1–R3 (2026-11-12): what the code still needs, and the order from here

*An audit of the code at `275a3a0` against this plan and against "another lab can use it". Tests: 312 passed, 2
skipped. The plan's references (functions, files, routes) still match the code; what follows is what it missed or
should change.*

### 16.1 Findings

| # | Finding | Where | Effect on another lab | Proposed |
|---|---|---|---|---|
| A1 | **Our lab's logo is in the code.** Every label starts with "MAAMI™" (`LOGO = PKG/"static"/"label"/"logo.png"`), drawn whenever `Label.logo` is true (the default); the docstring copies our P-touch template ("Odczynnik") | `mister_plis/labels.py:37`, `:189`; `static/label/logo.png` | a friend's lab prints our name on its reagents — the one place left that breaks "no lab in the code" | **R11** (16.2) |
| A2 | **Cross-site requests can change things.** No route checks where a request comes from. Routes with a JSON body are safe only by accident (FastAPI refuses a `text/plain` body: tried), but body-less POSTs — `/api/system/restart`, `/api/system/check`, `/api/lab/backup`, `/verify`, `/upgrade`, `/api/tools/sources/{name}/check`, `/api/setup/skip`, `/api/jobs/{id}/cancel`, `/api/label/printer/check` — answer any web page a lab member has open | `app.py` (no Origin check; middlewares at `:120`, `:134`) | on a faculty network, a page anywhere can restart a lab's server or cancel its jobs | **R9** gains it (16.3) |
| A3 | **Anyone who reaches the server may run code on it.** Adding and switching on a tool source (`POST /api/tools/sources`, `…/{name}/enable`) runs that repository's Python as the server; the storage folder and a transfer export accept any path | `app.py:999–1037`, `:1052`, `:1174` | fine on one lab's network (the beta); not on a Docker/Linux server the whole university can reach — which is what R4 makes possible | **R9** gains an optional settings key (16.3); ask the owner (F7) |
| A4 | **R4 needs R6.** In the image the app's Python belongs to root and the server runs as `misterplis`, so `ToolSources._requirements()` (`pip install` into `sys.executable`, `toolsources.py:404`) fails for any tool source with a `requirements.txt`. §13's sequence has R6 before R4, but its table doesn't say R4 depends on it | `toolsources.py:391–414` | tools with packages don't load in Docker | §13 corrected (16.4) |
| A5 | **git refuses volumes owned by someone else** ("detected dubious ownership"): a HOME volume made by `root` or a NAS-mounted folder read by uid 1000 stops every clone, fetch and the modules' repositories | `gitutil.ENV` | a Docker or Linux install can't read its repositories | **R4** gains it (16.5) |
| A6 | **Mac paths as examples:** `/Volumes/…` placeholders on the setup page and Settings, and in three error messages | `templates/setup.html:33,75,78`, `settings/jobs.html:45`, `settings/server.html:50`; `storage.py:37`, `backup.py:499`, `transfer.py:112` | confusing on Linux, Windows and Docker (where the answer is `/storage`, `/backup`) | **R4** gains it (16.5) |
| A7 | **A network share isn't recognised on Windows:** `_looks_like_network()` runs `df` (absent on Windows) and so says "local" for `\\nas\share` and mapped drives | `storage.py:89–98` | no "better for backups than storage" hint on Windows | **R4** gains it (16.5) |
| A8 | **A Docker image says version 0.1.0 and commit "".** There is no `.git` in the image (`.dockerignore`), so `updater.RUNNING` is empty; `__version__` was never raised | `__init__.py:4`, `/api/version` (`app.py:365`) | the Server tab and a bug report can't say what runs | **R4** takes R5.1 early (16.5) |
| A9 | **The docs speak to our lab.** README's first paragraph says it runs "on one machine (the Mac Studio)" and lists our lab's tools first; `modules/notebook/service.py:7` still says GitHub access comes from the Mac Studio's Keychain (R3 changed that); no "start here" for a lab that isn't ours | `README.md`, `modules/notebook/service.py` | a new lab reads our lab's story before its own | **R4** docs (16.5) |
| A10 | **R10 has a trap:** `labsetup.migrate()` returns at once when `lab.json` exists (`labsetup.py:360`), so the instance id can't be added there as §12.1 says; it needs its own step. (Every `write_state` caller keeps the keys it doesn't know — `labsetup.py:399,413,485,607`, `transfer.py:240` — so the id, once written, stays) | `labsetup.py:355–366` | — | §12.1 note (16.6) |

Seen and **left as they are** (not a lab in the code): `scripts/build_app.sh`'s default `REPO_URL` and
`pyproject.toml`'s install line name *the code's* repository, not a lab's; the inventory's built-in field labels
("Dostawca", "Merck, VWR…") are the inventory module's own bilingual data; `toolsources.py`'s docstring says "ours"
as an example. Known limits, written down rather than built: the label printer is Brother's P-touch raster over
port 9100 only (other labs print the PDF); the interface has two languages (`i18n.LANGS`), and a third needs a
catalogue next to every `pl.py`.

### 16.2 R11 — The lab's own label logo (new package; size S)

**Why.** A1: the last piece of our lab in the code, and the one a friend's lab sees first.

1. **Where it lives:** `<data>/label_logo.png` (data folder: a transfer carries it; a backup of settings does too).
   `labels.py`: `LOGO` becomes `logo_path(data_path) -> Path | None` — the lab's file if it exists, else none. A label
   without a logo starts with the name (the layout already handles `logo is None`: check `x0`).
2. **Our logo leaves the code:** `static/label/logo.png` → `labs/legacy-label-logo.png`; `labs/example.toml` and
   `labs/smith-lab-test.toml` gain `[label_printer] logo = "legacy-label-logo.png"`. Remove the file from `static/`
   (git keeps it).
3. **Existing servers keep what they print** (the inventory's `OLD_CALCULATOR` pattern): at start, a server that was
   set up before this (`labsetup.read_state()["state"] == "set_up"`, a `label_printer.json` with an address, and no
   `label_logo.png` and no `"logo"` choice in it) gets the old logo copied in once — from `labs/legacy-label-logo.png`
   **only if** its stored lab file source names it; otherwise record `"logo": ""` (none). **Ask the owner:** is it
   simpler to copy the logo into the Mac Studio by hand once (Settings → upload) and skip this migration? Default: do
   the migration (a server must not change what it prints by itself).
4. **Lab file:** `[label_printer] logo = "<file>"` — a path relative to the lab file (as `read_source` reads lab files:
   `ROOT/labs`, then `HOME/labs`) or an `https://` address; PNG, at most 200 kB, checked with Pillow. `labsetup.BASE`
   gets the key (a new check `_image_ref`); `labs/template.toml` names it; **Download as a lab file** can't embed a
   picture, so it writes the key commented out with a note ("upload it on Settings → Exports & printing").
5. **Interface:** *Settings → Exports & printing → Label printer*: the logo's preview, **Choose a picture…** (upload,
   `POST /api/label/logo`, marked *settings* in R9) and **No logo**. The Labels window keeps its per-print "logo" tick.
   Polish for the new texts.
6. `labels.py`'s docstring: "the lab's logo (if it has one)", not our template's name.

**Formats:** FORMATS.md, the label printer section: `label_logo.png`, and `label_printer.json`'s optional `"logo"`
(`""` = none chosen). **Tests:** a fresh data folder prints without a logo; an uploaded PNG is used; a non-PNG and an
oversize file are refused; a lab file with `logo` installs it (fixture PNG); the migration gives a set-up server its old
logo once and never again; the template test names the key; `grep -r MAAMI mister_plis` finds nothing (add to
`tests/test_labsetup.py` or a new `tests/test_no_lab_in_code.py` with the other names that must not appear in the base:
`smith-lab`, `inventory`, `notebook`, `MAAMI` — allowing docstrings that say "ours", or not, as the owner
prefers).

### 16.3 Additions to R9 (access marks)

1. **Same-site requests only** (A2) — a middleware before the routes: for `POST/PUT/PATCH/DELETE`, refuse (403,
   "This request came from another site.") when `Sec-Fetch-Site` is `cross-site`, or when `Origin` is present and its
   host:port differs from the request's `Host`. No `Origin` and no `Sec-Fetch-*` (curl, the CLI, tests' `TestClient`)
   passes. This changes nothing for the pages and closes A2 today. Test: a restart with `Origin: https://evil.example`
   is refused; one with the server's own origin and one with none are not.
2. **An optional settings key** (A3; **ask the owner — F7**): `access.MODE = "open" | "key"`. With a key set on
   *Settings → Server & updates* (stored as a salted hash in `<HOME>/secrets/settings-key`, mode 0600, never in a lab
   file or a transfer), `settings_access` answers 403 until the browser has typed it once (a signed cookie, 30 days,
   signed with a random secret in `<HOME>/secrets/`). Work stays open to everyone. A new instance has no key, so its
   setup page works; the setup page offers to set one. `python -m mister_plis key --clear` (on the server itself)
   removes a forgotten key. It is the login's `settings_access` with one shared password instead of accounts, so the
   login later replaces the check and nothing else. Default until answered: build 1. now, build 2. but leave it off.
3. Mark `/api/setup/read` *settings*: with `url` it makes the server fetch an address (§11.2 has it under `/api/setup/*`;
   say why in the code).

### 16.4 Corrections to §13 (order)

- R4 depends on R1–R3 **and R6** (A4).
- R10's instance id: add it in a step of its own after `migrate()`'s early return, e.g. `labsetup.ensure_instance()`
  called from the same place at start (A10).
- **New sequence:** **R11 → R9 (with 16.3) → R10 → R8 → R6 → R4 (with 16.5) → R5 → R7.** R11 first: small, and the
  friend's lab (BETA.md §2) sees it now. R9 before R4: a server the whole university can reach should not arrive before
  the same-site check exists.

### 16.5 Additions to R4 (Docker and Linux)

1. **git and volumes** (A5): `gitutil.ENV` adds `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_n=safe.directory`/`VALUE_n` for
   HOME, the data folder's `tool-sources/`, and each module's repository folder (the paths, not `*`). Test: a clone
   owned by another uid can't be made in the test, so check the env the git calls get.
2. **Examples that fit the computer** (A6): `install.example_folders() -> {"storage", "backup", "usb"}` by
   `install.kind()` and `sys.platform` — docker: `/storage`, `/backup`, `/backup`; mac: today's `/Volumes/…`; Linux:
   `/mnt/lab-data/MISTER PLIS`, `/mnt/nas/MISTER PLIS backup`, `/media/usb`; Windows: `D:\MISTER PLIS`,
   `\\nas\MISTER PLIS backup`, `E:\`. Passed to the three templates; the three error messages become "Give the full
   path of the folder, e.g. {example}." (one Polish text with `{example}`).
3. **Shares on Windows** (A7): in `_looks_like_network`, on Windows, a path starting `\\` is a share, and a drive letter
   asks `GetDriveTypeW` (`ctypes`, `DRIVE_REMOTE == 4`); `df` stays for the others.
4. **Version in the image** (A8): do R5.1 now (`__version__ = "0.9.0"`); the image gets `ARG COMMIT` →
   `ENV MISTER_PLIS_COMMIT`, which `updater.RUNNING` reads when there is no `.git`.
5. **Docs for another lab** (A9): a new `docs/NEW_LAB.md` — "start here": choose how to install (Mac app, Docker,
   Linux service), GitHub access (R3), the setup page or a lab file from `labs/template.toml`, your own tools repository
   (start from a copy of `tests/fixtures/toolsource`, ADDING_TOOLS.md), backups, moving later (BETA.md §4). README's
   first paragraph says "one machine in the lab" (not the Mac Studio) and links it; our tools' list moves under "Our
   lab's tools". `modules/notebook/service.py`'s docstring: the instance's tokens (`credentials.py`) first, then the
   code checkout's helper.

### 16.6 A note for R10

`ensure_instance()` (16.4) writes `"instance": {"id", "created_at"}` into `lab.json` when missing; `transfer.bring_in`
already keeps the copied `lab.json`'s keys (`transfer.py:240`), so a moved instance keeps its id — add the test §12
lists. A server restored from a **backup** (not a transfer) into a fresh install gets a new id: write that down in
FORMATS §12 as intended (it is a new instance holding old jobs).

### 16.7 A new question for the owner

| # | Question | Default until answered |
|---|---|---|
| F7 | Before the login: a shared **settings key** for servers on a wide network (16.3.2)? | build it, off by default; the same-site check (16.3.1) is on for everyone |
