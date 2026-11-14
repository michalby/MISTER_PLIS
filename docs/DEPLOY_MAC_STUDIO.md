# Running MISTER PLIS on the lab Mac Studio

One Mac Studio runs the server; every computer, tablet or phone on the same network opens it in a
browser at an address like `http://mister-plis.local:8000`. Nothing is installed on the other
computers.

On the Mac Studio it's an ordinary app, **MISTER PLIS.app**: put it in Applications, double-click
it, and it stays in the Dock serving the lab. It has Python inside, so the Mac needs no Homebrew and
no Python of its own — only Apple's Command Line Tools (for git).

1. [Build the app](#1-build-the-app) (on your own Mac)
2. [Make a GitHub token](#2-make-a-github-token)
3. [Install it on the Mac Studio](#3-install-it-on-the-mac-studio)
4. [Make it reachable from the network](#4-make-it-reachable-from-the-network)
5. [Keep it always on](#5-keep-it-always-on)
6. [Checking on it](#6-checking-on-it), [troubleshooting](#7-troubleshooting), [security](#8-security)
7. [Working from several places](#9-working-from-several-places): code from Claude Code and other computers, notes from
   Obsidian, and the reagents' tidy-up by a local model (Ollama)

The Mac Studio needs macOS 13 or newer. You need an administrator password for the energy and
firewall steps.

---

## How it works

```
MISTER PLIS.app (fixed)                       ~/Library/Application Support/MISTER PLIS/
───────────────────────                       ──────────────────────────────────────────
launcher: dock icon and menu,     sets up →   python/          copy of the bundled Python
first-run setup, restarts the                 MISTER_PLIS/     git checkout of this repository
server if it stops, keeps the     runs    →     .venv/         packages from requirements.txt
Mac awake                                       config.toml    your settings (optional)
Python 3.12 (bundled)                           data/  logs/   uploads, results, server.log
```

The server's code is a normal git checkout, so **Sync with git** in the web interface works as
always: it pulls, reinstalls packages if `requirements.txt` changed, and restarts the server. Only
the launcher is fixed inside the app — rebuild the app only when `macos/launcher/` changes or you
want a newer bundled Python.

## 1. Build the app

You can build on your own Mac or directly on the Mac Studio. Use an existing Git checkout,
or download the source from GitHub: **Code → Download ZIP**, then double-click the ZIP to extract it.
Open Terminal, type `cd ` (with a space), drag the extracted `MISTER_PLIS-main` folder into Terminal,
and press Return. Then run:

```bash
./scripts/build_app.sh
```

A source ZIP does not contain Git history; the build supports it and uses
`https://github.com/michalby/MISTER_PLIS.git` for the app's code and updates. A Git checkout uses its
`origin` remote. To build for a fork, set `MISTER_PLIS_REPO_URL=https://github.com/you/fork.git` before
`./scripts/build_app.sh` on the same command line.

**Set the Mac up as your lab's at the same time:** `MISTER_PLIS_LAB_FILE=labs/example.toml ./scripts/build_app.sh`
bakes that lab file (a path in the repository, or an `https://` address) into the app; on the Mac's first start the
server applies it — tool sources, modules and their repositories, folders, printer — and skips the setup page. Without
it, the browser opens on the setup page (step 4 below). Either way it holds no token.

It needs Apple's Command Line Tools (you have them if you use git) and, the first time, internet to
download Python (≈ 24 MB, checked against its published checksum). It makes `dist/MISTER PLIS.app`
and `dist/MISTER PLIS.zip` (≈ 26 MB). The app remembers this repository's GitHub address — never a
password or token.

## 2. Make a GitHub token

The repository is private, so the Mac Studio needs a key that can read it. On github.com:

1. Profile picture → **Settings** → **Developer settings** → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**.
   (The app's token window has a "Create Token on GitHub…" button that opens this page.)
2. **Name:** e.g. `MISTER PLIS Mac Studio`. **Expiration:** the longest offered.
3. **Repository access:** *Only select repositories* → the code and every repository the lab file names. Ours:
   `MISTER_PLIS`, `MISTER_PLIS-tools` (the lab's tools — see [Tool sources](#tool-sources) below), `inventory`
   and `notebook` (the lab notebook — see [Lab notebook](#lab-notebook) below). A fine-grained token covers the
   repositories of **one** owner (a person or an organisation): keep the lab's repositories under one, or make the
   code repository public so the token only needs the lab's own. The setup page's **Check** says which repository the
   token can't read. Repositories of another owner: add a token for that owner on **Settings → Server & updates →
   GitHub access** (the Keychain's token stays the one for everything else).
4. **Permissions** → **Repository permissions** → **Contents: Read and write** (Reagents sends the lab's edits to
   the inventory repository; the code, the tools and the notebook are only read). Nothing else.
5. **Generate token** and copy it (it starts with `github_pat_`). You'll paste it once on the Mac
   Studio; it's stored in that Mac's Keychain.

The token can only reach these repositories. When it expires, "Sync with git" reports an
authentication error — make a new one and use **Change GitHub Token…** in the app's dock menu.

### Tool sources

The tools come from their own repository (ours: `smith-lab/lab-tools`), named in the lab file or on the setup
page. The server fetches it when it next starts, with the same token, and loads its tools; MISTER PLIS itself contains none. If it can't (the token doesn't
include the repository, no network), the home page says there are no tools yet and Settings → Tools
shows why. **Settings → Tools → Tool sources** shows each source (its branch, its commit, how many tools it loaded)
and has Check, Update, Branch…, Pin and Switch on/off. After an update, restart when it asks. A tools update that
needs new packages installs them, and so does a start that finds a source's packages missing (a new machine), but
only after a dry run shows that none of MISTER PLIS's own packages would change.

More repositories of tools (another lab's, say) can be added there too. They are fetched without the token, added
switched off and pinned to the commit you saw, and every later update shows its commits and changed files before it
is applied. Read what a repository contains before switching it on: its tools run inside the server.

### Lab notebook

The **Notes** panel and the **Lab notebook** page show chosen folders of the lab's Obsidian vault (ours:
`notebook`; the repository is chosen in the lab file, on the setup page, or with **Change…** on Settings → Lab
notebook). The server reads it with the same token, so nothing else is set up on the Mac.
If the token was made before the notebook existed, don't make a new one: on github.com open the
token (**Fine-grained tokens** → its name) → **Edit** → **Repository access** → also tick
`notebook` → **Update**. Then **Settings → Lab notebook → Sync notes**. If that reports that GitHub
didn't let the server read the notebook, the token doesn't include `notebook` yet.

## 3. Install it on the Mac Studio

Log in as the macOS user the server should run under. A dedicated account (e.g. "lab") is tidiest.

1. **Command Line Tools.** In Terminal: `xcode-select --install` and click *Install*. (If you skip
   this, the app opens the same installer on first launch and waits for it.)
2. **Copy the app** into `/Applications` — from a USB stick, a shared folder, or AirDrop the `.zip`
   and double-click it to unzip.
3. **Open it.** The app isn't from the App Store, so if it came by AirDrop or download, macOS says it
   can't check it. Click *Done*, then *System Settings → Privacy & Security*, scroll down, and click
   **Open Anyway** next to "MISTER PLIS was blocked". You do this once. (Or in Terminal:
   `xattr -dr com.apple.quarantine "/Applications/MISTER PLIS.app"`.)
4. **Paste the token** when asked, and click *Continue*.
5. **Wait** while it copies Python, downloads the code and installs packages — a few minutes. When
   it's done, the browser opens MISTER PLIS. The first start takes ~30 s; later ones a few seconds.
   Without a lab file baked into the app, it opens on the **setup page**: choose the lab's file (e.g.
   `labs/example.toml`), **Check**, **Set up**, **Restart now**. (Or **Skip for now**, and set it up later from
   Settings → Server & updates → Lab setup.)
6. If macOS asks *"Do you want the application python3.12 to accept incoming network
   connections?"*, click **Allow**.

The app adds itself to the login items, so it starts whenever this user logs in.

**Settings of this Mac** (port, …): the lab's own settings are on the Settings page and the setup page. For the machine,
put a `config.toml` in
`~/Library/Application Support/MISTER PLIS/MISTER_PLIS/` (copy `config.example.toml` from there),
then choose **Restart Server** in the dock menu. *Show Files in Finder* in the dock menu opens that
folder.

**A new version of the app** (only when you rebuilt it): quit the old one, replace it in
Applications, open it. Code, settings and results are kept; if the bundled Python changed, it
reinstalls the packages by itself.

**Removing it** (e.g. after trying it on a laptop): dock menu → **Remove App Data and Quit…** stops
the server, deletes `~/Library/Application Support/MISTER PLIS/` (code, Python, packages,
`config.toml`, results, logs), takes the app's GitHub token out of the Keychain and removes the
login item. Then move the app from Applications to the Trash. Only quitting and trashing the app
leaves all of that behind.

**Coming from `scripts/install_service.sh`?** On first launch the app offers to remove the old
background service, which would otherwise hold the same port. The app uses its own checkout, so copy
your `config.toml` over; the old `~/MISTER_PLIS` folder can be deleted once you're happy.

## 4. Make it reachable from the network

The server already listens on the whole network. Three things can still get in the way: the
address, the firewall, and the cable.

### Give the Mac a clear name

*System Settings → General → Sharing → Local hostname → Edit…* — set something short, e.g.
`mister-plis`. The lab then uses `http://mister-plis.local:8000`. The dock menu shows the current
address, and *Copy Address* puts it on the clipboard.

The `.local` name works out of the box on Macs, iPhones/iPads, Linux and Windows 10/11, and finds
the Mac even if its IP address changes.

### Give it a fixed IP address too (recommended)

Android phones and some Windows or corporate networks don't resolve `.local` names. For those, use
the IP address (the dock menu shows it under the address) — and make sure it doesn't change:

- **Best:** ask whoever runs the router / IT to add a *DHCP reservation* for the Mac Studio's
  Ethernet MAC address (*System Settings → Network → Ethernet → Details → Hardware*).
- **Or:** *System Settings → Network → Ethernet → Details → TCP/IP → Configure IPv4: Using DHCP
  with manual address*, and pick an address outside the router's DHCP range (ask IT which).

### Use Ethernet

Plug the Mac Studio into the network with a cable. Wi-Fi works, but drops connections now and then
and makes large uploads slower.

### Allow it through the macOS firewall

If the firewall is on (*System Settings → Network → Firewall*) and you missed or denied the
"accept incoming network connections" question, allow it from Terminal:

```bash
PY="$HOME/Library/Application Support/MISTER PLIS/python/bin/python3.12"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PY"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$PY"
```

(or *Firewall → Options…*, remove any blocked Python entry and add that file). Repeat this after
installing an app version that bundles a different Python.

### Check from another computer

Open `http://mister-plis.local:8000` (or the IP) on any other computer on the network. If it doesn't
load, see [troubleshooting](#7-troubleshooting).

### Optional: drop the `:8000`

Put `port = 80` in `config.toml` and choose **Restart Server**. The address becomes simply
`http://mister-plis.local`. (macOS lets normal users serve on port 80, no admin rights needed.)

## 5. Keep it always on

"Always on" means surviving several different things:

| What happens                       | What keeps it running                                          |
| ---------------------------------- | -------------------------------------------------------------- |
| The server crashes                 | the app restarts it after 5 s (backing off to 1 min if it keeps failing) |
| "Sync with git" / restart button   | the server replaces itself; the app keeps watching it          |
| Someone quits the app              | it asks first: "Stop MISTER PLIS?" — *Keep Running* is the default |
| The Mac goes to sleep              | the app keeps the Mac awake while it runs (the display may sleep) |
| The Mac restarts                   | automatic login + the app is a login item                      |
| Power cut                          | Energy setting: start up after a power failure                 |

### Log in automatically after a restart

The app runs in the user's login session, so after a restart the Mac must log that user in by
itself: *System Settings → Users & Groups → Automatically log in as: (the server user)*.

Check that **Start at Login** is ticked in the dock menu (it's also listed in *System Settings →
General → Login Items & Extensions → Open at Login*).

**FileVault:** macOS doesn't allow automatic login while FileVault disk encryption is on (the option
is greyed out). You have two choices:

- **Turn FileVault off** (*System Settings → Privacy & Security → FileVault*) — the Mac comes back by
  itself after any restart or power cut. Reasonable for a lab machine that stays in a locked room
  and holds no personal data; check with your IT policy.
- **Keep FileVault on** — after every restart someone has to type the password at the Mac before
  MISTER PLIS comes back. For restarts you plan, `sudo fdesetup authrestart` reboots once without
  asking for the password at startup.

After automatic login you can lock the screen (Control-Command-Q) — the app keeps running.

> Why not run it without anyone logged in? The server needs things that only exist in a login
> session: the Keychain (where the GitHub token lives) and GPU access for Blender.

### Never sleep, and come back after a power cut

While the app runs it stops the Mac from going to sleep by itself. Still set *System Settings →
Energy* (on a Mac Studio), so it also holds before the app has started:

- **Prevent automatic sleeping when the display is off** — on
- **Wake for network access** — on
- **Start up automatically after a power failure** — on

Or the same in one Terminal command:

```bash
sudo pmset -a sleep 0 disksleep 0 womp 1 autorestart 1 displaysleep 15
pmset -g          # check: sleep 0, autorestart 1
```

### Don't let macOS updates restart it at random

*System Settings → General → Software Update → Automatic updates (ⓘ)*: keep *Download new updates*
and *Install Security Responses and system files* on, but turn **Install macOS updates** off, and
install macOS updates yourself at a quiet time.

### Optional: a small UPS

A cheap UPS plugged into the Mac Studio by USB rides through short power cuts and lets macOS shut
down cleanly on long ones; with "start up after a power failure" on, it restarts by itself when power
returns.

### Test it

Restart the Mac Studio (*Apple menu → Restart*) without touching it, then open the address from
another computer. It should answer within a minute or two of the Mac starting.

## 6. Checking on it

**Right-click the dock icon** (clicking it opens MISTER PLIS in the browser):

- the status line — *Running at http://…*, *Starting…*, or *Stopped unexpectedly — restarting…*
- **Open MISTER PLIS**, **Copy Address**
- **Restart Server** — e.g. after editing `config.toml`
- **Show Log** — the server's log in Console
- **Show Files in Finder** — the checkout, with `config.toml`, `data/` and `logs/`
- **Change GitHub Token…**
- **Start at Login**

From anywhere on the network, **Settings → Server & updates** shows the running version and
lets you sync with git or restart.

In Terminal on the Mac Studio:

```bash
curl -s http://localhost:8000/api/version                                     # is it answering?
tail -f ~/Library/Application\ Support/MISTER\ PLIS/MISTER_PLIS/logs/server.log    # live log
cat ~/Library/Application\ Support/MISTER\ PLIS/launcher.log                  # setup and restarts
```

`server.log` is moved to `server.log.1` when it passes 20 MB, so it never fills the disk.

## 7. Troubleshooting

| Symptom | Likely cause and fix |
| ------- | -------------------- |
| "MISTER PLIS can't be opened" / "Apple could not verify…" | It came by AirDrop or download. *System Settings → Privacy & Security → Open Anyway* ([step 3](#3-install-it-on-the-mac-studio)). |
| `./scripts/build_app.sh` says `permission denied` | The extracted folder lost the script's "executable" flag (some unzip tools do that). Run it as `bash scripts/build_app.sh` instead. |
| `build_app.sh` says `fatal: not a git repository` | An older build script requires Git history, which GitHub’s source ZIP does not include. Download and extract the latest source ZIP, then run the updated script in that folder ([step 1](#1-build-the-app)). |
| Setup sits at "Installing Apple's Command Line Tools" | Finish the installer window (it may be behind other windows). Setup continues by itself. |
| "GitHub didn't accept the token" | The token must include the `MISTER_PLIS` repository with *Contents: Read-only*, and mustn't have expired. Make a new one. |
| "Sync with git" fails with an authentication error | The token expired — dock menu → **Change GitHub Token…**. |
| "Sync notes" says GitHub didn't let the server read the notebook | Add `notebook` to the token's repository access on github.com (see [Lab notebook](#lab-notebook)). |
| Works on the Mac Studio, not from other computers | Firewall is blocking Python — see [the firewall step](#allow-it-through-the-macos-firewall). Or `host` in `config.toml` is `127.0.0.1`; remove that line. |
| `mister-plis.local` not found, but the IP works | That device or network doesn't support `.local` names (common on Android and some managed Windows PCs). Use the IP and give it a [fixed IP](#give-it-a-fixed-ip-address-too-recommended). |
| Worked yesterday, IP address doesn't work today | The router gave the Mac a new address. Set up a DHCP reservation or manual address. |
| Nothing works after a power cut or restart | Nobody is logged in — check automatic login and FileVault ([above](#log-in-automatically-after-a-restart)). |
| Other computers are on guest Wi-Fi / a different network | Guest and isolated networks block traffic between devices. They must be on the same lab network (or IT must route between them). |
| Dock menu keeps saying "Stopped unexpectedly — restarting" | **Show Log** and read the end. Commonly: the port is taken by another copy (an old `run.sh` / `install_service.sh` server — stop it), or a broken commit — fix it and push, then **Restart Server**. |

## 8. Security

Until the lab makes its first account, MISTER PLIS has no sign-in: anyone who can reach the address can use every
tool, see recent results, and press "Sync with git" or restart. To turn sign-in on, open **Settings → People** on the
Mac Studio itself (or with the setup code the app's log shows) and make your own account, as an admin; then add
everyone else's there (each gets a temporary password and chooses their own). Locked out?
`python -m mister_plis account reset "<your name>"` on the Mac gives a new password. Either way, it is meant for a lab
network, so:

- keep it on the internal lab / institute network,
- **never** forward its port on the router or expose it to the internet,
- if you need it from home, use the institute's VPN rather than opening it up.

It talks plain HTTP, which is fine inside the lab's own network. If the network is shared more widely (a whole
institute), HTTPS can be put in front with Caddy (`brew install caddy`), as for a Linux service:
[DEPLOY_LINUX.md, HTTPS](DEPLOY_LINUX.md#https) — then set `host = "127.0.0.1"` in the instance's `config.toml`.

## 9. Working from several places

Everything reaches the Mac Studio through GitHub. Nobody edits files on the Mac Studio itself:

```
Claude Code on the web ─┐
another computer ───────┼─ push ─► MISTER_PLIS ──── nightly update ─────────► Mac Studio: the server's code (base + modules)
                        ├─ push ─► MISTER_PLIS-tools ── Tool sources: Update ─► Mac Studio: the tools
                        │
Obsidian + Git plugin ──┴─ push ─► notebook ─── sync every 15 min ──────► Mac Studio: Lab notebook
                                   inventory ◄── cell-by-cell sync ──► Mac Studio: Reagents
                                                           ▲
                                     Ollama on the Mac Studio: the scheduled tidy-up, inside the server
```

### The code: Claude Code on the web, or another computer

- **Claude Code on the web** (claude.ai/code): start a session on the `michalby/MISTER_PLIS` repository. The
  repository's `CLAUDE.md` tells it to run the tests and push to `main` when a change is done.
- **Another computer:** clone the repository, `./scripts/setup.sh --dev`, try a change with `./scripts/dev.sh`
  (http://localhost:8000), run `.venv/bin/python -m pytest`, then push. To try work in progress on the lab
  server, push a branch and pick it under **Settings → Server & updates → Run another branch**.
- **On the Mac Studio:** **Settings → Server & updates → Version → Update by itself → every night, between 3 and 5 am**.
  The server pulls what was pushed and restarts, but only while no job is running and nothing was edited on the
  Mac Studio. Below the choice it says what happened last night. **Sync with git** still updates at once.

If you also use Claude Code or git yourself *on the Mac Studio*, work in a separate clone (e.g. `~/Code/MISTER_PLIS`),
never in `~/Library/Application Support/MISTER PLIS/`. Run it on another port (`./scripts/dev.sh --port 8001`),
and put `repo = ""` under `[module.inventory]` in that clone's `config.toml`, so trying out the Reagents pages doesn't
edit the real inventory. To work on the tools there too, clone `MISTER_PLIS-tools` beside it and add
`tool_folders = ["~/Code/MISTER_PLIS-tools"]`: that clone's tools are used instead of the fetched ones, and the dev
server reloads when you save one. The app's token sits in the Keychain as *the* login for github.com, so your own `git push` in the same
macOS account would use it. Either run the server under its own account ("lab"), or sign git in as yourself with
`gh auth login` and `gh auth setup-git` (or use SSH remotes).

### The lab notebook: Obsidian on several computers

1. On each computer, open the vault as a git clone of `notebook`. Install the community plugin **Git**
   (Settings → Community plugins → Browse → "Git"). Set *Auto commit-and-sync interval* (e.g. 10 minutes) and
   turn on *Pull on startup*, so the computers don't drift apart.
2. On the Mac Studio: **Settings → Lab notebook → Sync by itself → every 15 min**. New and edited notes
   then show up by themselves. A notes sync never restarts the server.

### The reagents' tidy-up by a local model (Ollama)

The server tidies the inventory on a schedule, from inside MISTER PLIS. Its corrections go the same way as an edit
in the lab: checked against the workbook's `columns` sheet, committed, and sent to `inventory` with the
usual cell-by-cell sync. That's why it can't clash with the lab's edits, and why it needs no git setup of its own.
One run:

1. syncs with GitHub (a failed sync stops the run);
2. **format checks** (no model): filler such as "brak danych", "-" or "?" emptied; TRUE/FALSE and numbers stored
   as text made real; dates as yyyy-mm-dd; lists as `B;C`; extra spaces; an allowed value in the wrong case
   ("wysoki" → "WYSOKI"). Values that can't be fixed this way are listed for a person;
3. **producers' spelling** (no model): "Sigma Aldrich" and "Sigma-Aldrich" become the spelling used most;
4. **Info from the lab** (the model): each note still *new* is read with the whole inventory and the rules in the
   repository's `AGENTS.md`. The model says which cells to change, and every change is checked like an edit. A
   model that proposes something impossible (a label number that doesn't exist, a value outside the allowed
   list) is told why and gets one more try. A note it finds unclear gets its question (`agent_note`, shown under
   Info from the lab) and stays *new* for a person. Its changes and the note marked *done* are one commit, naming
   the note's id.

**Set it up on the Mac Studio:**

1. Install Ollama: download it from [ollama.com](https://ollama.com/download) and move it to Applications. Open it
   once; it adds itself to the login items and listens on `http://127.0.0.1:11434`.
2. Download a model in Terminal, for example `ollama pull qwen3:32b`. Pick one that `ollama list` shows and that
   fits the Mac's memory. Bigger models understand Polish notes better; a 30B-class model fits easily in a Mac
   Studio with 64 GB.
3. **Settings → Reagents & consumables → Reagents: tidy-up by a local model**: choose the **model** and **when** it runs (every day
   or on weekdays, at e.g. 02:30). Then choose what is **applied by itself**:
   - *format and spelling fixes; the model's corrections wait for a person* (the default, recommended at first),
   - *everything, the model's corrections too*,
   - *nothing — everything waits for a person*.

   Waiting proposals are listed on the same page with the note, each cell's old and new value, and **Apply** /
   **Reject** (or **Apply all**). A person who applies one is its author, with `Proposed-by: Tidy-up (model)` in
   the commit. A rejected note keeps a remark, so the model doesn't propose the same thing again.
4. Press **Run now** once and look at what it proposes.

Ollama on another machine of the lab network works too: set `ollama_url = "http://that-mac.local:11434"` under
`[module.inventory]` in `config.toml` (and start Ollama there with `OLLAMA_HOST=0.0.0.0`). `ollama_url = ""` turns
the model off; the format and spelling checks still run. The tidy-up keeps its settings and its last run in
`data/modules/inventory/tidy/`. Everything it changed is in the inventory's history, author `Tidy-up (model)`.

---

## Without the app

The older setup still works if you'd rather not use the app: a launchd background service that runs
the server from a checkout in your home folder. It needs Python 3.11+ (e.g. from
[python.org](https://www.python.org/downloads/macos/)) and the Command Line Tools, no Homebrew:

```bash
git clone https://github.com/michalby/MISTER_PLIS.git ~/MISTER_PLIS   # Username: anything; Password: the token
cd ~/MISTER_PLIS
./scripts/setup.sh
./scripts/install_service.sh
```

Apple's git saves the token in the Keychain after the first successful clone. Logs are in
`~/MISTER_PLIS/logs/server.log`; `./scripts/uninstall_service.sh` removes the service. Everything in
sections 4, 5 and 8 applies the same way, except that the service doesn't keep the Mac awake by
itself — the Energy settings are required.
