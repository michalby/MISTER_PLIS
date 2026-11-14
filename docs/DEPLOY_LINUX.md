# MISTER PLIS on a Linux server

*November 2026 (docs/PREP_PLAN.md R4). Two ways: **Docker** (the simplest; also how Windows runs it, see
[DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md)), or a **service** run by systemd from a git clone. A Mac uses the app instead
([DEPLOY_MAC_STUDIO.md](DEPLOY_MAC_STUDIO.md)). Whichever you choose, a new server opens its **setup page**, and a
server from another machine moves in with **Everything from another server** there ([BETA.md](BETA.md) §4).*

## Where things are

| | Docker | Service |
|---|---|---|
| The code | inside the image (`/app`), replaced by a new image | a git clone, e.g. `/opt/MISTER_PLIS` |
| The instance (`config.toml`, `data/`, `secrets/`) | the volume `/srv/mister-plis` (`./home` next to the compose file) | `MISTER_PLIS_HOME`, e.g. `/srv/mister-plis` |
| The storage folder (jobs, what tools save) | the volume `/storage` | any folder; choose it on the setup page |
| The backup folder | the volume `/backup` (the NAS, mounted on the host) | the NAS, mounted on the host |
| How it updates | a new image: `docker compose pull && docker compose up -d` | **Sync with git** on Settings, or by itself at night |
| Restarts | the server exits with code 75; Docker's `restart: unless-stopped` starts it again | systemd's `Restart=always` |

The instance never lives inside the code: a new image or a new clone leaves the lab's data where it is.

## With Docker

You need Docker Engine with the compose plugin (`docker compose version`).

1. Get the code (`git clone https://github.com/michalby/MISTER_PLIS.git`) and go into it. Build the image:

   ```bash
   docker build --build-arg COMMIT=$(git rev-parse HEAD) -t mister-plis .
   ```

   (`COMMIT` is shown on Settings → Server & updates; the image has no `.git` to read it from.)
2. Copy `deploy/docker-compose.yml` where the server's folders should be (e.g. `/srv/mister-plis-compose/`). Change
   the backup volume's left side to where the NAS is mounted on the host. Start it:

   ```bash
   docker compose up -d
   ```

3. Open `http://<server>:8000`. On the setup page choose **`/storage`** as the storage folder and **`/backup`** as the
   backup folder (or, in a lab file: `[jobs] storage_folder = "/storage"`, `[backup] folder = "/backup"`).
   The server answers only to its own names and to IP addresses (docs/SECURITY_AUDIT.md H1). Inside a container it
   doesn't know the host's name, so give the names people use in the compose file
   (`MISTER_PLIS_SERVER_NAMES: "labserver, labserver.uni.example"`), or open it by its IP address.
   The setup page asks for the server's **setup code** (so a new server belongs to whoever started it, not whoever
   opens it first): `docker compose logs mister-plis | grep "setup code"`, or
   `docker compose exec mister-plis python -m mister_plis setup-code`.
4. Private repositories (the lab's tools, inventory, notebook): add a token on **Settings → Server & updates → GitHub
   access** (one per owner if needed). Or give `MISTER_PLIS_GIT_TOKEN` from a file that never goes into git
   (`env_file: secrets.env` in the compose file).

**The folders' owner.** The server runs as the user `misterplis` (uid 1000) inside the container. Folders Docker makes
for the volumes belong to root: the container gives them to uid 1000 the first time it starts (the backup folder only
while it is empty). If your folders belong to another user on the host, set `MISTER_PLIS_UID` (and `MISTER_PLIS_GID`)
to that user's numbers in the compose file's `environment:`. git works in folders owned by another user too
(the server tells git to trust the repositories it made).

**Updating:** build the new image the same way (or pull it, once releases are published — docs/PREP_PLAN.md R5),
then `docker compose up -d`. The data stays in the volumes; the setup page doesn't come back.

**Logs:** `docker compose logs -f`.

## As a service (systemd), without Docker

1. Install Python 3.11+ and git (`sudo apt install python3 python3-venv git`), make a user for the server
   (`sudo useradd --system --create-home misterplis`), and as that user clone the code and set it up:

   ```bash
   git clone https://github.com/michalby/MISTER_PLIS.git /opt/MISTER_PLIS
   cd /opt/MISTER_PLIS && ./scripts/setup.sh
   ```

2. Make the instance's folder (`sudo mkdir -p /srv/mister-plis && sudo chown misterplis: /srv/mister-plis`).
3. Copy `deploy/mister-plis.service` to `/etc/systemd/system/`, change `User=`, `WorkingDirectory=`,
   `MISTER_PLIS_HOME` and `ExecStart=` if your folders differ, then:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now mister-plis
   journalctl -u mister-plis -f
   ```

4. Open `http://<server>:8000` and set it up; the setup page asks for the server's setup code
   (`journalctl -u mister-plis | grep "setup code"`, or `python -m mister_plis setup-code` as the server's user with
   its `MISTER_PLIS_HOME`). Updates come from git as on a Mac (**Sync with git**, **Update by
   itself**); the clone needs read access to the code repository (a token on Settings → GitHub access, or the code
   repository public).

## The firewall

The server listens on port 8000 on every network interface. Open it to the lab's network only, e.g. with ufw:
`sudo ufw allow from 192.168.1.0/24 to any port 8000 proto tcp`. Anyone who can reach the port can use the server and
change its settings until the lab makes its first account (Settings → People; then everyone signs in, and only
admins change Settings); a change can only come from the server's own pages, never from another
web site, and only by one of the server's own names (its IP addresses, the names the computer and the network give it, and
`server_names` in `config.toml`). With HTTPS
(below), open ports 80 and 443 instead, and close 8000.

**Port 8001** (from 0.18.0): stored files — results, kept files — also come from an address of their own, the same
host on the next port (`files_port`), so that nothing in a file could ever run where the app's pages are. Open it like
8000 (`sudo ufw allow from 192.168.1.0/24 to any port 8001 proto tcp`). If it is closed, the pages notice and take the
files from port 8000, sandboxed, as before: nothing breaks. `files_origin = "off"` in `config.toml` turns it off.

## HTTPS

Without it, everything people send — and, once there is a login, their passwords — crosses the network readable by
anyone on it. A **proxy** in front of the server does HTTPS: [Caddy](https://caddyserver.com) answers on port 443 and
passes each request on to MISTER PLIS, which no longer listens on the network itself. Pick a name people will open,
e.g. `mister-plis.lab.example`, that points at this server (ask IT), and where its **certificate** comes from:

| The name… | Certificate | `MISTER_PLIS_TLS` |
|---|---|---|
| can be reached from the internet | Caddy gets one by itself (Let's Encrypt) | `""` |
| is known only on the lab's or the university's network | **from the university's IT**: put `cert.pem` and `key.pem` in `certs/` | `"tls /certs/cert.pem /certs/key.pem"` |
| is known only on the lab's network, and IT has no certificate | Caddy's own: each computer trusts it once (below) | `"tls internal"` |

**With Docker:** copy `deploy/Caddyfile` and `deploy/docker-compose.https.yml` next to `docker-compose.yml`, write a file
`.env` there:

```
MISTER_PLIS_DOMAIN=mister-plis.lab.example
MISTER_PLIS_TLS=tls internal
```

and start both (Docker Compose 2.24 or newer):

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
```

MISTER PLIS is then reached only through Caddy (its port 8000 is no longer published), believes what Caddy says about
the browser (`MISTER_PLIS_TRUSTED_PROXIES`), and answers to the name in `.env`.

**As a service:** install Caddy (`sudo apt install caddy`), put this in `/etc/caddy/Caddyfile` and
`sudo systemctl reload caddy`:

```
mister-plis.lab.example {
	tls internal                # or: tls /etc/caddy/cert.pem /etc/caddy/key.pem — or no line, for a public name
	request_body {
		max_size 2100MB
	}
	reverse_proxy 127.0.0.1:8000
}
```

and make MISTER PLIS listen on this computer only, in its `config.toml`: `host = "127.0.0.1"` (Caddy on the same
computer is trusted by itself). Add the name as `server_names` in `config.toml` (or `MISTER_PLIS_SERVER_NAMES`).

**`tls internal`: trusting Caddy's certificate.** Copy Caddy's root certificate
(`docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt > mister-plis-root.crt`; as a service:
`/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt`) to each computer and trust it once: on a Mac,
double-click it → Keychain Access → *Always Trust*; on Windows, double-click → *Install Certificate* → *Local Machine*
→ *Trusted Root Certification Authorities*; on Linux, `/usr/local/share/ca-certificates/` and
`sudo update-ca-certificates` (Firefox: Settings → Certificates → Import).

**Stored files from a name of their own** (optional; mister_plis/fileorigin.py): behind HTTPS, the files' own
address needs a second name for this server (`files.mister-plis.lab.example`), a second block in the Caddyfile (there,
commented out: `reverse_proxy mister-plis:8001`; as a service, `127.0.0.1:8001`) and, for MISTER PLIS,
`MISTER_PLIS_FILES_ORIGIN=https://files.mister-plis.lab.example` in `.env` (as a service: `files_origin = "https://…"`
in `config.toml`). Without it, files come from the main name, sandboxed, as before.

**Uploads** larger than 2100 MB stop at Caddy: if the lab allows larger ones (Settings → Jobs & backup), raise
`max_size` too.

## Jobs as another user

Every job kept in the history runs in a process of its own (from 0.17.0; `job_isolation = "off"` in `config.toml`
runs them in the server's threads, as before). That process gets none of the server's tokens in its environment. To
make sure a tool can't read the server's **secrets folder** at all (GitHub tokens, sessions), let jobs
run as **another user** of the computer — on Linux, for a service:

```bash
python -m mister_plis job-user           # as the server's user: prints the steps for this machine
```

It prints, with this machine's paths filled in: make the user (`useradd --system … --gid <the server's group>
mister-plis-jobs`), make the job and tool-data folders writable by the group (`chmod -R g+rwX,g+s`), and a `sudo` rule
that lets the server start exactly one command as that user (`/etc/sudoers.d/mister-plis-jobs`). Then set
`job_user = "mister-plis-jobs"` in `config.toml`, restart, and check:

```bash
python -m mister_plis job-user mister-plis-jobs --check
```

which runs a job's process as that user and says whether it can read the secrets folder (it must not) and write job
folders (it must). With `job_user` set, the server makes its folders group-writable (umask 002). Some older systems'
`sudo` wants a terminal: add `Defaults:<server user> !requiretty` to the rule's file.

Not yet for Docker (the container already keeps the server apart from the host; a job user inside it is a later step)
nor for the Mac app (which runs as the person logged in on the Mac); there, jobs still run in a process of their own.

## Several labs on one machine

Each lab gets **a server of its own** — one instance per lab, never two labs in one. Tools run with the server's
rights, so the only wall between two labs is the operating system's (docs/SECURITY_AUDIT.md §6):

- **One container per lab** (or, as services, one Linux user per lab): a folder per lab with its own copy of the
  compose files (`/srv/lab-smith/`, `/srv/lab-jones/`), its own `home/`, `storage/` and backup volume. No folder is
  shared between two labs, and none is mounted into another lab's container.
- **Its own name and port:** with HTTPS, one Caddy for the machine with one block per lab name
  (`smith.mister-plis.uni.example { reverse_proxy lab-smith-mister-plis-1:8000 }`, with Caddy on each lab's Docker
  network); without, a port per lab (`"8001:8000"`, `"8002:8000"`).
- **Its own GitHub tokens**, fine-grained and limited to that lab's repositories (read-only, except the inventory's).
- **Its own backup share** on the NAS, which only that lab's server (and its people) can read: a backup holds
  everything, readable.
- A **local model** (Ollama) may be shared, but stays on the internal network: it has no login.

