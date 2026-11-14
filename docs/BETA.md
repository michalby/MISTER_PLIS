# The beta: three servers, one code, and moving a server later

*November 2026. Where MISTER PLIS runs while it is tested, how a friend's lab joins, and how a server moves to
another machine (e.g. the faculty's server) with everything it holds.*

## 1. The servers

Every server runs the same code (`michalby/MISTER_PLIS`, branch `main`) and has its **own data**: its jobs, Time
Machine, settings and people. Nothing is shared between servers except the code, the tools, and the lab's own
repositories (inventory, notebook) that a server is set up to use.

| Server | Who uses it | Data | Set up from |
|---|---|---|---|
| **The lab's Mac Studio** | our lab | real | `labs/example.toml` (it is already set up: nothing to do) |
| **Your MacBook Pro** | you, testing | made up | `labs/smith-lab-test.toml`: our tools and notebook, but the inventory stays on the MacBook (§3) |
| **Your friend's Mac** | his lab | his | the setup page, or his own lab file (§2) |

Later, each lab's server moves to the faculty's server as a whole (§4). One server per lab is also how the final
version is meant to work (§5), so nothing set up now has to be undone.

## 2. Your friend's lab

**On github.com (you):** *Settings → Collaborators* of `MISTER_PLIS` and of `MISTER_PLIS-tools` → add him (read is
enough; he never pushes there). Don't add him to `inventory` or `notebook`: those are our lab's data.

**His GitHub token.** The Mac app asks for one token, and the server uses it for every repository. A *fine-grained*
token reaches only the repositories of **one owner**, so a fine-grained token of his can't read our (your) private
repositories, even as a collaborator. For the beta he makes a **classic** token instead: github.com → *Settings →
Developer settings → Personal access tokens → Tokens (classic) → Generate new token*, scope **`repo`**, the longest
expiry offered. It can reach every repository he can (his own and the two you shared), so it stays in that Mac's
Keychain only. (When the code is public, a fine-grained token for his own repositories is enough.)

**Or two fine-grained tokens** (from November 2026, docs/PREP_PLAN.md R3): *Settings → Server & updates → GitHub
access* keeps a token per owner. The Mac app's token (Keychain) reads the code; on that panel he adds a fine-grained
token for **his own** account (owner = his GitHub name) for his lab's repositories. The server asks the most
specific token first, then the Keychain. No classic token needed.

**On his Mac:**

1. `xcode-select --install` (Apple's Command Line Tools: git and the compiler for the app).
2. `git clone https://github.com/michalby/MISTER_PLIS.git` (with his GitHub name and the token as the password), then
   in that folder `./scripts/build_app.sh` → `dist/MISTER PLIS.app`. (Or you build it and send him the `.zip`: the app
   only remembers the repository's address, never a token.)
3. Copy the app into `/Applications`, open it (*Privacy & Security → Open Anyway* the first time), paste the token.
4. The browser opens on the **setup page**: his lab's name and language; **Tools**: add a source `lab`,
   `https://github.com/smith-lab/lab-tools.git`, trusted; **Modules**: the inventory with his own repository
   (or empty: kept on his Mac only, then **Start an empty inventory** on its Settings tab), the notebook off unless he
   has an Obsidian vault in git; his folders and printer. **Check**, **Set up**, **Restart now**.
5. **Download as a lab file** (on the setup page) keeps all of it in one file, to set up his next server the same way.

**Updates:** he gets what you push to `main` — by **Sync with git**, or by itself at night if he turns on **Update by
itself**. So keep `main` working: run the tests before pushing, and try risky work on a branch first (**Run another
branch** lets one server follow it).

**What he sends you:** the **Feedback** list is per server, so his lab's feedback stays on his Mac. Ask him to copy
it (**Copy as a list** on the Feedback page) when you want it.

## 3. Your MacBook (made-up data)

A clone run with `./scripts/dev.sh` (reloads when you save) keeps its data in that clone's `data/`, apart from the
Mac Studio's. Set it up with **`labs/smith-lab-test.toml`** (setup page, or `python -m mister_plis setup
labs/smith-lab-test.toml`): our tools and the notebook (read-only, harmless), but the **inventory kept on the MacBook
only**, so made-up edits never reach the lab's real inventory. (`labs/example.toml` there would sync them to
`inventory`.) To start over: stop it, rename `data/` (e.g. `data.old`), start it again — the setup page
opens.

## 4. Moving a server to another machine

**On the old server:** *Settings → Server & updates → Move this server* → a folder (a USB disk, the NAS, or any folder
you then copy over) → **Copy everything**. Not while jobs are running. It makes `MISTER PLIS <lab> <date>/` there:
every file copied, then checked against the original (size and SHA-256), listed in its `manifest.json`.

**On the new server** (installed and opened, so it shows the setup page): *Start from → Everything from another
server* → the folder's path → **Check** (every file is checked again; it shows the lab, the number of jobs and the
size) → **Bring it here**. The server restarts with everything. From the command line, the same:

```bash
python -m mister_plis transfer export /Volumes/USB                       # on the old server
python -m mister_plis transfer check "/Volumes/USB/MISTER PLIS Smith Lab 2026-11-11 1430"
python -m mister_plis transfer import "/Volumes/USB/MISTER PLIS Smith Lab 2026-11-11 1430"   # on the new one; asks first
```

**What moves:** the jobs (with their files and full tables), what tools save, Time Machine (with its whole history),
the lab's settings (name, language, backup schedule, printer, tool sources and tools' own settings, which modules are
on), people and their merged names, the Feedback list, and each module's own state — the inventory's copy of its
repository **with any change not sent yet**, the notebook's copy and chosen folders.

**What doesn't, and why:** the GitHub token (never in the data; the new server asks for its own); the tool sources'
clones (fetched again at the first start); uploads waiting for a run; this machine's choices — the storage folder
(the new server uses its own) and the branch it runs; `config.toml`; folders set aside earlier (`*.moved-*`…).

**Rules that keep it safe:**

- It goes only into a server **with no jobs yet**. Two servers are never merged. (Jobs of another server can still come
  in one by one through a backup folder: *Jobs & results → Import from backup*.)
- A damaged or incomplete copy changes nothing. What the new server had made by itself (an empty Time Machine, its
  `lab.json`) is renamed `<name>.before-import-<date>`, never deleted.
- **After moving, stop the old server** (quit the app, and untick *Start at Login*). Two servers on the same inventory
  would both send changes to it.
- If the backup folder's path is different on the new machine, set it on *Settings → Jobs & backup*; jobs whose copy
  isn't found there are simply copied again.

Fixed along the way: **Move here** for the storage folder (Settings → Jobs & backup) left Time Machine's results
behind in the old folder (nothing was lost, but Time Machine looked empty after the restart). Each module's storage
folder now moves with the jobs.

## 5. Toward the final version (not built yet)

The whole direction — any server (Mac, Linux, Windows in Docker), roles on several computers, updates from releases,
basic and own tools — is in [FINAL_VERSION.md](FINAL_VERSION.md). In short:
one server ("instance") per lab, each with a simple login — people who may change Settings, and everyone
else. What is here already fits it: a lab is one server with its own data, lab file and backup; a server moves whole
(§4); people's names (and merged names) are kept per server and can become accounts. Nothing in the beta needs to be
redone for it.

## 6. Not tried yet

- **The Mac app built and opened on a Mac other than the Mac Studio**, from a fresh clone — your friend's install is
  that test. The app's launcher was last changed (passing a lab file to the server) without being compiled here.
- **A move between two real Macs** (here it was tried between two servers on one Linux machine, through the pages and
  the command line).
- **The faculty's server** will likely be Linux: the Mac app doesn't apply there. It runs in Docker or as a systemd
  service: [DEPLOY_LINUX.md](DEPLOY_LINUX.md) (November 2026). Not tried on the faculty's machine yet.
