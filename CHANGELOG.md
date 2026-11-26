# What changed in MISTER PLIS

Newest first. Each version says what a lab will notice. The version numbers (`MAJOR.MINOR.PATCH`): MAJOR for a change
a lab must act on (e.g. a data format older versions can't read), MINOR for new features, PATCH for fixes. The formats
each version writes are in `mister_plis/formats.py`; every format is described in docs/FORMATS.md.

## 0.23.1 — 2026-11-26

- Input boxes no longer suggest made-up names: no example person (your name, a new account), lab name, job title,
  file name keyword, sample names (plate and spot layouts) or Time Machine title is shown in them any more. A box
  still shows what it is for, and the lab name box shows the lab file's name when there is one.
- No made-up names in help and messages either: the "Your name" help, the message asking for a person's name
  and the transfer folder box on the setup page.

## 0.23.0 — 2026-11-14

- **The basic tools come with MISTER PLIS**: Solution & dilution, Plate assay (96-well, standard curve) and
  Colorimetric assay (standard curve), from the public `michalby/MISTER_PLIS-basic-tools`. A server fetches them at its
  next start (Settings → Tools lists them as "basic", version v1.0.0); a lab can switch them off there.
- They are fetched by the commit `bundled-tools.toml` lists, so a moved tag can't change what a server runs.
- A lab's own tool with the same id as a basic one (e.g. its own Solution & dilution) is the one used, with no
  message about a duplicate.
- MISTER PLIS's code is public: `michalby/MISTER_PLIS` (branches `stable` and `beta`), GNU GPL v3.0 or later.

## 0.22.0 — 2026-11-14

- **MISTER PLIS is free software** under the GNU General Public License v3.0 or later (`LICENSE`).
- **The basic tools come by themselves**: a server running from a git checkout fetches the tool sources that come with
  MISTER PLIS (`bundled-tools.toml`) when it starts, at the listed tag, and again when an update lists a newer one —
  as a release already brought them. Settings → Tools shows each with its version, and why it couldn't be fetched.
  None is listed yet: the basic tools (Solution & dilution, a plate assay and a colorimetric assay) are listed once
  their public repository exists (docs/PUBLISHING.md).
- `scipy` is now one of MISTER PLIS's own packages (the basic tools need it); the next update installs it.

## 0.21.0 — 2026-11-14

- **Regions on a picture, named like a plate:** regions that are wells of a grid (e.g. the leaf-disc chambers of an
  IMAGING-PAM) are shown as plates beside the picture, and named exactly as on the protein plate layout — drag across
  wells or click a row/column label, type one name or several (one per row / column), Apply. Other regions are listed
  beside the picture. A picture menu above it shows whichever pictures the tool offers.
- A suggestion that arrives while you are already naming or moving regions no longer undoes that.

## 0.20.1 — 2026-11-14

- The setup page's list of lab files has **`labs/example.toml`**: a made-up lab set up the way most labs will be (its
  own tools, the notebook and inventory from their empty templates), to copy and change.

## 0.20.0 — 2026-11-14

**One computer, simpler settings** (Settings → Server & updates)
- **Everything runs on the server again.** Other computers that ran jobs for it (workers, from 0.11.0) are gone, with
  their panel, `python -m mister_plis worker` and docs/WORKERS.md. A tool that says what it needs (Blender…) runs here
  when this computer has it. Jobs a worker ran still open and still say where they ran; a `secrets/workers.json` is
  left where it is, unused.
- **New: *How people reach this server*** lists the addresses to give a new person (`http://<ip>:8000`, and on a Mac
  `http://<name>.local:8000`). With an account (Settings → People) they sign in from any computer, phone or tablet on
  the lab's network; nothing is set up on their devices. While the lab has no accounts, the panel says so.
- **Gone: *This server's neighbours*** (`[services]`). The inventory's tidy-up has its own local model's address
  (Settings → Reagents & consumables); an address set there before is taken over once by itself.
- **Gone: *This server's names*.** The server still answers only to its own names — its IP addresses and the names
  the computer and the network give it, which is all people on the lab's network use. A name only a proxy gives it
  goes into `server_names` in config.toml (or `MISTER_PLIS_SERVER_NAMES`); names a lab saved before still work.
- Lab files: `[services]` and `[server] names` are no longer settings; an older lab file with them still loads, with a
  note.

## 0.19.0 — 2026-11-14

- **Circles on a picture** — a new kind of tool input (toolkit 1.3, `inputs.ImageSpots`): the tool shows a picture made
  from the uploaded file and suggests circles on it (e.g. leaf discs found in a cassette); people move, resize, add,
  delete, select and name them — one sample name for several circles (replicates), or several names, one per row,
  column or circle — and save layouts in their browser. The first tool to use it is PAM imaging (Walz) in the lab's
  tools. A tool source that uses it asks for `requires_toolkit = ">=1.3,<2"`.

## 0.18.0 — 2026-11-14

**Security** (docs/SECURITY_AUDIT.md, "Later")
- **Stored files come from an address of their own**: the server also listens on the next port (8001 by default,
  `files_port`) and serves there nothing but results and kept files, through signed links that open one job's folder
  for two hours. A file can't run anything where the app's pages and data are, even if something got past the sandbox.
  **Open port 8001 like 8000** in a firewall; if a browser can't reach it, the pages quietly use port 8000, sandboxed,
  as before. Behind HTTPS it needs a second name (docs/DEPLOY_LINUX.md); `files_origin = "off"` turns it off.
- There, HTML and SVG files are shown (sandboxed, no scripts) instead of only downloaded: a tool's HTML report can be read
  in the browser.
- New: `<instance>/secrets/files-key` (docs/FORMATS.md).

## 0.17.0 — 2026-11-14

**Security** (docs/SECURITY_AUDIT.md, "Later")
- **Every job kept in the history runs in a process of its own**: a tool that crashes, fills the memory or hangs takes
  only its own job with it, a crafted input file reaches only that process, and the process gets none of the server's
  tokens. Cancelling stops it (and kills it if it won't stop). Live calculator runs stay in the server, instant as
  before. `job_isolation = "off"` in config.toml goes back to the old way.
- **Jobs as another user** (Linux service): `job_user` in config.toml runs each job's process as another user of the
  computer, who can't read the server's secrets at all. `python -m mister_plis job-user` prints the steps for the
  machine, and `--check` checks them (docs/DEPLOY_LINUX.md, "Jobs as another user").
- **The pages run only the app's own scripts** (a Content-Security-Policy): a piece of HTML that slips into a page —
  a tool's HTML result, a crafted name — can't run anything. The last inline scripts moved into files.
- **Reviewing a tool source** (Settings → Tools): which packages its tools would install — installing a package can run
  its code — and which lines are never installed; also when an update changes them.
- For tool authors: a kept job's `run` gets everything from its parameters and `ctx`, not from the server's memory
  (docs/ADDING_TOOLS.md, "Where run runs").

## 0.16.0 — 2026-11-13

**Where the code comes from** (docs/SECURITY_AUDIT.md M5, docs/RELEASES.md)
- **`requirements.lock`** pins every package to one version with its checksums. The Docker image, `scripts/setup.sh`
  and a git update that changes it install exactly those files (`pip --require-hashes`): a new or hijacked version on
  PyPI no longer reaches a lab by itself. `./scripts/lock.sh` makes it again after `requirements.txt` changes.
- **Signed release feeds:** `scripts/release.sh` signs the feed with the owner's SSH release key
  (`MISTER_PLIS_SIGNING_KEY`), and a server whose code has that key (`mister_plis/releasekeys.py`) refuses a feed it
  didn't sign. No key is set yet (the owner makes it: docs/RELEASES.md §2), so feeds are still read, marked unsigned.
  The Docker image now has `ssh-keygen` (openssh-client) to check signatures.
- A release carries its `requirements.lock`, with its checksum in the feed.
- docs/RELEASES.md §3: protecting `main` on GitHub (no force pushes or deletions, few people with write access, two-factor
  authentication, read-only tokens for servers).

## 0.15.0 — 2026-11-13

**An account owns its jobs and its names**
- Every account has a permanent id, and every job its person runs (and every feedback they send) stores it beside
  their name. "My jobs" are the account's: a removed account's jobs never become someone else's who later gets the
  same name.
- **Rename an account** (Settings → People → Accounts → Rename): everything under the old name — jobs, feedback, Time
  Machine entries — moves with it; its person stays signed in.
- **Attach a name** to an account: a name its person used before there were accounts ("Ola" for "Aleksandra Nowak").
  What was under it becomes theirs. Merging names on the People list does the same when the kept name is an account's,
  and refuses to merge an account's own name away.
- A new account can't take a name that was merged into someone else's.
- Accounts made by 0.14.0 get their id the first time 0.15.0 reads them (docs/FORMATS.md §18).

## 0.14.0 — 2026-11-13

**Accounts and sign-in** (docs/SECURITY_AUDIT.md, Phase 3)
- **Nothing changes until the lab turns it on:** with no account, the server stays open, as before. On Settings →
  People, an admin makes **the first account — their own, as an admin** — which turns sign-in on. From another
  computer this needs the server's setup code (the server shows it when it starts; `python -m mister_plis
  setup-code`); on the server itself (the Mac app) it doesn't.
- **From then on everyone signs in** (a sign-in page; a session lasts 30 days of use). Admins add the others' accounts
  on Settings → People — each gets a temporary password, shown once, and chooses their own at the first sign-in — and
  can make someone an admin or a member, give a new password, or remove an account (their results stay). The lab
  always keeps at least one admin.
- **Admins** change Settings; **members** do the everyday work (tools, jobs, Time Machine, the inventory). Members don't
  see Server & updates, nor the server's details (paths, tokens, workers), nor tracebacks of failed jobs.
- **Who you are is your account:** the name on your jobs, PDFs, Time Machine entries and inventory changes is your
  account's name, whatever a browser's name setting says. Make the accounts with the names people already used (the
  form offers them), so everyone's results stay theirs.
- Settings → You: change your password; sign out here or everywhere. Settings → People: the **activity log** (sign-ins,
  accounts, every change to the lab's settings).
- Locked out (the only admin forgot their password)? On the server: `python -m mister_plis account reset "<name>"`.
- Too many wrong passwords from one computer or for one name are slowed down, then refused for a quarter of an hour.
- New: `<data>/accounts.json` (password hashes only), `<data>/audit.log`, `<instance>/secrets/sessions.json`
  (docs/FORMATS.md §18). A moved server keeps its accounts; settings snapshots don't hold them.

## 0.13.0 — 2026-11-13

**Security** (docs/SECURITY_AUDIT.md, Phase 2)
- **A new server's setup code.** Until a server is set up, setting it up from another computer needs its setup code,
  so a new server belongs to whoever started it, not whoever opens it first. The server shows the code when it
  starts; `python -m mister_plis setup-code` shows it again. On the server's own computer (`http://localhost:…`, the
  Mac app) no code is needed. Servers already set up see no change.
- **HTTPS** with Caddy in front: `deploy/Caddyfile` and `deploy/docker-compose.https.yml`, and a new section in
  docs/DEPLOY_LINUX.md (also for Windows and, optionally, the Mac). New setting `trusted_proxies` (config.toml): the
  proxies whose word about the browser is believed. Over HTTPS, browsers are told to stay on HTTPS, and the page's
  own cookies are sent only over HTTPS.
- **Several labs on one machine:** docs/DEPLOY_LINUX.md says how to keep them apart (a container, folders, tokens,
  backup share and workers per lab).
- **Workers ask for their token** instead of taking it on the command line, where it stayed in the shell's history.
  Settings shows the command and the token separately. `--token` and `MISTER_PLIS_WORKER_TOKEN` still work.

## 0.12.1 — 2026-11-13

**Fixed**
- Colleagues reach the server by any of its own names with nothing set, as before 0.12.0: besides its IP addresses
  and the names it gives itself (on a Mac, `<local hostname>.local`, what *Copy Address* gives), it now also knows the
  names the network's DNS gives its addresses (e.g. a university's `mac-studio.biol.uni.example`), and notices a new
  name within five minutes when the Mac is renamed. Only a name nobody gave the computer — a proxy's — needs adding
  on Settings → Server & updates → This server's names.

## 0.12.0 — 2026-11-13

**Security** (docs/SECURITY_AUDIT.md, Phase 1)
- The server answers only to **its own names**: its IP addresses, `localhost`, this computer's names, and the names
  on Settings → Server & updates → **This server's names** (`[server] names` in a lab file, `server_names` in
  config.toml). A web page elsewhere can no longer point a name of its own at the server and use it (DNS rebinding).
  **A server opened by another name** (a proxy's, a name set in the network's DNS) shows how to add it: open it by its
  IP address once, then add the name there.
- **Files people keep** (Time Machine, a job's inputs and results) can no longer run anything in the app's pages:
  pictures, PDF, text, audio and video are shown, sandboxed; anything else — HTML and SVG files among them — is
  downloaded instead of shown.
- No other site can show the app's pages inside its own (clickjacking).
- A link that would run something (`javascript:…`) is never made: not from a feedback's page, an inventory link
  field (refused when saved), a tool catalogue's homepage, or a link in a result.
- **Largest upload** (Settings → Jobs & backup; `[jobs] max_upload_mb`): 2048 MB unless the lab sets another.
- The API's reference (`/api/docs`) is off unless config.toml says `api_docs = 1`.
- A tool source that isn't the lab's own installs its packages only once it is switched on (not when its pin moves),
  only ready-made ones (`--only-binary`), and only packages by name: a requirements file with `-e`, a path, an
  address or `--index-url` is refused.
- Tables exported as Excel or CSV (results, backups, the inventory's lists): text that starts with `=` stays text.
- Importing a backup takes only files that are inside that backup.
- New in `lab_settings.json`: `server_names`, `max_upload_mb` (docs/FORMATS.md); older versions ignore them.

## 0.11.0 — 2026-11-12

**Jobs on other computers**
- **Computers that run jobs** (Settings → Server & updates): another computer on the lab's network — the one with
  Blender and a graphics card, say — can run jobs for this server. Add it there, then start MISTER PLIS on it with
  `python -m mister_plis worker --server … --token …` (the page gives the command). It fetches the tools from the
  server, takes the jobs it can run and sends the results back; no folder has to be shared. docs/WORKERS.md.
- A tool that says what it needs (`Tool(needs=…)`, e.g. Blender render's `program:blender`) goes to a worker that has
  it, as does a tool this server can't run itself; everything else runs on the server, and without a worker
  everything runs there, as before. A job says where it ran ("on blender-pc").
- New: `secrets/workers.json` (the workers' tokens, hashed) and the `worker` of a job in `job.json`; older versions
  read such jobs as before (docs/FORMATS.md §17).

## 0.10.0 — 2026-11-12

**New**
- Settings → Tools: a **private** tool source can be added with **a token of its own**, pasted next to its address. The
  token is kept on the server for that one repository only (it is listed on Settings → Server & updates → GitHub
  access) and is used for nothing else; a source that isn't the lab's own still never gets the server's own tokens.
  This replaces 0.9.1's "lab's own" tick box. A failed fetch of a private repository says whether a token is missing
  or can't read it.

## 0.9.1 — 2026-11-12

**Fixed**
- Settings → Tools: a tool source can be added again as **the lab's own** (a new "trusted" tick box). Before, a source
  added there was always fetched without the server's GitHub token, so the lab's own private repository, once removed,
  couldn't be added back ("could not read Username"). A failed fetch of a private repository now says so. (Replaced in
  0.10.0 by a token for the source.)

## 0.9.0 — 2026-11-12 (the beta)

The first numbered version: everything before it is part of the beta.

**For another lab**
- Each lab sets up its server from its own **lab file**, or on the **setup page** a new server opens by itself: its
  name and language, tool sources, modules and their repositories, folders, label printer. Nothing in the code names
  one lab.
- **Its own logo on its labels**: Settings → Exports & printing, or `[label_printer] logo` in the lab file. A new lab
  prints no logo; our logo now comes only from our lab file.
- **GitHub access** on Settings → Server & updates: a token per owner (or repository), not only the Mac's Keychain.
- **This server's neighbours**: the address of a local model (Ollama) once for the whole lab, `[services]` in the lab
  file. Each server has an id of its own, kept when it moves.

**Where it runs**
- **Linux and Windows** besides the Mac: Docker (`Dockerfile`, `deploy/docker-compose.yml`) or a systemd service —
  docs/DEPLOY_LINUX.md, docs/DEPLOY_WINDOWS.md. The instance's own files can live apart from the code
  (`MISTER_PLIS_HOME`). File names are safe on Windows and network shares.
- **Moving a whole server** to another machine: Settings → Server & updates → Move this server.

**Updates**
- Version numbers that mean something, and this changelog. Settings → Server & updates says how this server is
  updated (from GitHub, or with a new Docker image) and, with a release feed set, what is newer.
- **A snapshot of the lab's settings before every update** (the newest five kept), to restore from the same tab.

**Tools**
- A tool source's packages are installed with the instance (`<data>/tool-packages/`), no longer into MISTER PLIS's own
  Python; packages already installed keep working.
- A tool can say what a computer must have to run it (`needs`, toolkit 1.2), recorded with each job.
- **Browse a catalogue** of tool sources other labs published (Settings → Tools; `[tools] catalogue`), and tool sources
  that come with a release, which a lab can switch off. A source's manifest can say what it is, who keeps it and its
  licence; Settings → Tools shows it.

**Safety**
- A change can only come from the server's own pages: another web site open in a lab member's browser can no longer
  restart the server or cancel a job.
- Every action that changes something is marked as the lab's settings or everyday work, ready for a login.
