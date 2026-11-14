# Toward the final version: where MISTER PLIS is going

*November 2026. Direction and proposals, nothing here is built. The beta ([BETA.md](BETA.md)) runs on Macs, one
server per lab, updated from GitHub. This page says what the final version should be, how far the code already is
from it, and proposes how to get there. Open questions are in §6. The detailed, step-by-step plan for preparing the
code for it — written so another agent can carry it out — is [PREP_PLAN.md](PREP_PLAN.md).*

## 1. What the final version is

- **One instance per lab**, each with a simple login: people who may change Settings, and everyone else. A lab's data
  stays in its own instance; an instance moves whole to another machine ([BETA.md](BETA.md) §4).
- **Runs on a Mac, Linux or Windows server.** Windows most likely in a Docker container (Docker also suits Linux).
- **One computer** (decided 14 November 2026, 0.19.0): the server runs the pages and every tool's jobs. People reach
  it from any device on the lab's network by its address and their account; nothing is set up per device. Other
  computers that ran jobs (workers, 0.11.0–0.18.0) and lab-wide addresses of other computers (`[services]`) were
  removed: they made the setup harder than the labs need. Storage and backups can still be folders on a NAS.
- **Updates from releases, not from GitHub's `main`** (§3).
- **Every module, a few basic tools**, and each lab adds its own tools its own way, usually its own git repository
  (§4).

**People and accounts (agreed, November 2026).** Every route that changes something already says whether it changes
the lab's settings or is everyday work (`mister_plis/access.py`, PREP_PLAN.md R9); the login only has to say who is
who. An account has a display name. The names the lab already uses — every name in the jobs, Time Machine and
`people.json` (with its merges) — are offered as the accounts' names when the login comes, so each person's jobs and
Time Machine entries stay theirs. A shared "settings key" before the login was considered and left for the login
itself (the owner's choice, F7).

## 2. Any server, and roles on several computers

**What ties the server to a Mac today, and the way out:**

| Today | Final |
|---|---|
| The Mac app (launcher, Python inside, Keychain, login item) | stays, for labs with a Mac; beside it a **Docker image** (Linux and Windows) and a plain install with a service file (Linux `systemd`) — **done** (PREP_PLAN.md R4: `Dockerfile`, `deploy/`, DEPLOY_LINUX.md, DEPLOY_WINDOWS.md) |
| The GitHub token in the Mac's Keychain, reused through git's credential helper | a **secret of the instance** (a file only the server reads, or Docker's secrets), used for every repository the instance reads |
| Paths written for a Mac (`/Volumes/…`) in docs and examples | paths are already handled as paths (`C:\…`, `~/…`); in Docker the data, storage and backup folders are **volumes** |
| `git` needed for updates and tool sources | still needed for tool sources and the modules' repositories (it is in the image); not for updates (§3) |

**Roles** (as planned before 14 November 2026; since 0.19.0 the app, the jobs and the model's address are all on the
one server: see §1). An instance is made of parts that could each live on another computer. They meet over the lab's network, and
each is a setting of the instance (a lab file can hold them):

| Role | What it does | Today | To build |
|---|---|---|---|
| **App** | the pages, the API, the job list, the lab's settings | the server | — (the one part that is always there) |
| **Workers** | run the tools' jobs | threads inside the app, and **workers** (0.11.0, [WORKERS.md](WORKERS.md)): `python -m mister_plis worker` on another computer asks the app for jobs and sends results back over HTTP, so a GPU machine can run Blender while the app stays on a small server. A tool says what it needs (GPU, a program), and only a worker that has it takes the job. Without a worker, the app runs jobs itself, as before — **done** | later: workers updating their code with the server's |
| **Model** | the local model for the inventory's tidy-up and future helpers | an address, set once for the lab in `[services] model` (Settings → Server & updates); a module's own (`ollama_url`) wins | — (already a separate machine if wanted) |
| **Storage** | jobs, Time Machine, what tools save | a folder; can be a mounted network share | keep it a folder (a share mounted on the app and the workers); later maybe object storage |
| **Backup** | the readable, checked copies | a folder (NAS) | — |

The order to build it: the Docker image and the instance's own secret first (they make Linux and Windows possible),
then workers when one lab needs them (e.g. Blender on a GPU machine).

## 3. Updates: a proposal

**Why not GitHub's `main`:** every server needs a token that can read the code; whatever is pushed reaches every lab
at once, tested or not; a server can't easily go back; and Windows/Docker servers don't keep a git checkout.

**Proposed: releases, checked and reversible.**

1. **Versions.** Code that is ready gets a version number (`1.4.0`); `main` stays where work happens. Each version is
   built and tested by GitHub Actions into what each kind of server installs: a package with its dependencies pinned,
   a Docker image, and the Mac app.
2. **Channels.** `stable` for labs, `beta` for those who test (us, a friend's lab). A version goes to `beta` first and
   to `stable` when it has run for a while without trouble.
3. **A release feed.** A small public file per channel (e.g. on GitHub Releases or the lab's site): the newest version,
   what changed (in the lab's words), its checksum, the formats it reads and writes. A server reads it without any
   token.
4. **Updating from Settings.** *Settings → Server & updates* shows what is new and what changed. **Update** (someone
   who may change Settings; or by itself at night, as now) downloads the version, checks its checksum (and its
   signature), installs it **beside** the running one (`versions/1.4.0/`), makes a quick copy of the lab's settings,
   switches, and restarts. If it doesn't start, it goes back by itself. **Go back to 1.3.2** stays offered for a while.
   On Docker, the same is a new image tag on the same volumes.
5. **Data stays readable across versions** (already a rule: docs/FORMATS.md). A version that writes a new format says
   so in the feed, so going back past it is refused rather than breaking data.
6. **Developers keep git.** Running from a checkout (`./scripts/dev.sh`, **Run another branch**) stays, for us; labs
   don't need it.

Tools are updated separately from the app (§4), so a tools fix doesn't wait for a release.

**Prepared (PREP_PLAN.md R5, November 2026):** version numbers and `CHANGELOG.md`; the formats register
(`mister_plis/formats.py`) and the release feed's format; `scripts/release.sh` builds the wheel, the Docker image and the
feed by hand (no CI, the owner's choice); the update channels (`mister_plis/updates.py`: git, Docker, release) with
today's git updates behind the git one; a snapshot of the lab's settings before every update, restorable.

**Agreed design for installing releases side by side (not built):** `<instance>/versions/<version>/` is each a
virtual environment with that version's wheel installed; `<instance>/current` points at one; the launcher (the Mac
app, the systemd unit, a Windows service) starts `<instance>/current/bin/python -m mister_plis`. An update downloads the
wheel, checks its checksum from the feed, installs it into a new `versions/<version>/`, makes a snapshot, switches
`current` and restarts; if `/api/version` doesn't answer within 60 s it switches back by itself. **Go back to <version>**
is offered while the newer version's `writes` (from the feed) are all within the older one's `READS`. On Docker the same
is a new image tag on the same volumes.

## 4. Tools: a few for everyone, each lab its own

- **Every module, and a basic set of tools.** The release brings all modules and a small **basic tool source**, made
  only of tools any lab can use (e.g. molar solution, PDF converter, plots of a table). It is versioned and tested with
  the release. Our lab's own tools stay in our repository, which other labs don't get by default.
- **A lab's own tools** come from its own git repositories, as tool sources do today: trusted (its own) or reviewed
  and pinned (someone else's). Also possible later: a tools folder uploaded as a `.zip`, for labs without git.
- **A catalogue to choose from.** *Settings → Tools → Browse*: a public list of tool sources labs have published (name,
  what they do, who keeps them, which toolkit versions they need). Adding one is the same as adding a source today, with
  the same review for a source that isn't trusted.
- **What makes this safe:** the toolkit API is versioned (`TOOLKIT_API`, `requires_toolkit`), so a tool says which
  versions of MISTER PLIS it works with, and an app update never silently breaks a lab's tools. A tool runs with the
  server's rights: only sources someone trusted run without review.
- **What has to change first:** our tools repository has to be split into the **basic** source (for everyone) and
  **ours** (this lab's only).
- **Prepared (PREP_PLAN.md R7, November 2026):** a release can bring tool sources with it (`bundled-tools.toml`, empty
  until F3 is answered), a lab can switch them off, and Settings → Tools → *Browse a catalogue* reads any catalogue's
  address. The catalogue itself (where it is published, who keeps it) is still to come.

## 5. How the beta prepares for it

- One instance per lab, its settings in a lab file, moved whole: already so.
- Nothing in the code names one lab; modules plug in; tools come from sources with a versioned API: already so.
- People's names (and merged names) are kept per instance: they can become the login's accounts.
- What the beta still does the "beta way": updates from GitHub, the Mac app as the only installer, the token in the
  Keychain, jobs run in the app's own process.

## 6. Open questions

| # | Question | To decide when |
|---|---|---|
| F1 | Public code (and which licence), or private with releases only? A public release feed needs no token. | **answered (2026-11-14):** public, GNU GPL v3.0 or later (docs/PUBLISHING.md) |
| F2 | Who builds and signs releases (GitHub Actions on tags; a signing key kept where)? | when releases start |
| F3 | Which tools are "basic"? | **answered (2026-11-14):** Solution & dilution, a generic plate assay and a generic colorimetric assay (docs/PUBLISHING.md §5) |
| F5 | Login: the lab's own accounts, or the university's (e.g. its single sign-on)? | **answered (2026-11-13):** the lab's own accounts — built in 0.14.0 (docs/SECURITY_AUDIT.md §7) |
| F6 | Workers: is a separate GPU/Blender machine needed soon, or later? | **answered (2026-11-14):** no — one computer; workers removed in 0.19.0 |
| F7 | Before the login: a shared settings key for servers on a wide network (a faculty server)? ([PREP_PLAN.md](PREP_PLAN.md) §16.3) | **answered:** no — it comes with the login's options |
