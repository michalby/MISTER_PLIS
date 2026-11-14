# MISTER PLIS — security audit

*13 November 2026, version 0.11.0 (commit `f02d442`). Nothing was changed in the code for this audit. Findings marked
**confirmed** were reproduced against the running app (FastAPI's TestClient); the rest come from reading the code.*

*Status: **Phase 1 done in 0.12.0** (13 November 2026): H1, H2, M1, M2, L1, L2, L4, L5 fixed, and H4's `pip` part
(packages of a source that isn't trusted: only once it is switched on, ready-made, by name). **Phase 2 done in 0.13.0**:
M3 (HTTPS with Caddy, `trusted_proxies`, HSTS), M4 (the setup code), L8 (workers ask for their token), and §6's
deployment notes (docs/DEPLOY_LINUX.md, "Several labs on one machine"). **Phase 3 done in 0.14.0**: H3 (accounts and
sign-in, §7: deny by default, admin-only reads, identity from the account, sessions, scrypt passwords, throttling, the
first admin with the setup code, the activity log) and L3 (tracebacks for admins only). The lab's own accounts — not the
university's single sign-on (the owner's choice, F5). 0.15.0: an account owns its jobs (an id stored with each) and its names (rename, attach
earlier names). **Phase 4 done in 0.16.0** (M5): `requirements.lock` with checksums, signed release feeds
(`mister_plis/releasekeys.py`, waiting for the owner's key), docs/RELEASES.md (including protecting `main`, which the
owner does on GitHub). **The "Later" list done in 0.17.0**: kept jobs run in a process of their own (`runners.ProcessRunner`,
`jobproc.py`) without the server's tokens, optionally as another OS user (`job_user`, Linux service); a strict
Content-Security-Policy (`script-src 'self'`) on every page; the tool-source review lists the packages a source would
install. **0.18.0:** stored files also come from an origin of their own (`mister_plis/fileorigin.py`: a files-only server
on the next port, signed links). **Still open (H4):** the server itself imports every enabled tool source's code to draw its forms, so a tool
source is trusted as a whole — reviewing a source that isn't the lab's own stays the safeguard against malicious code. Each fix has a test in
`tests/test_security.py` (and `tests/test_tool_packages.py`, `modules/inventory/tests/test_links.py`). The table in §4
says which are still open.*

## 1. Summary

**The goal:** one server per lab, used by trusted people who sign in. A lab must not see another lab's content, but labs may
use the same tools.

**Where the code is:** the base is careful in many places: paths are checked, secrets are kept apart, tokens are
stored as hashes, subprocesses never use a shell, and requests from other web sites are refused. It is not ready for a
server outside one closed lab network yet, for three reasons:

1. **There is no login** (this was planned). Every page and every read is open to anyone who can reach the port,
   and a person is only the name in a cookie. `access.py` already gives the login a place to plug in, but it only
   marks routes that *change* things; reads are open today.
2. **Two flaws let an outside web page or one user's file act as the server's own page.** A web page anywhere can
   control the server through *DNS rebinding* (H1, confirmed). An uploaded SVG/HTML file is served as a live page
   from the app's own address (H2, confirmed). With either one, an attacker can do anything the browser's user can,
   including adding a trusted tool source, which runs code on the server.
3. **Tools run with all the server's rights** (H4). Separating labs therefore depends on how the server is deployed:
   one container or OS user per lab, never shared. The application cannot do this separation on its own.

The planned design (one instance per lab, FINAL_VERSION.md §1) is the right one for separating labs. §6 lists what that needs. §7 lists what the login needs. §8 gives an order of work.
Most of the fixes in §4 are small, and we suggest doing them before the login.

## 2. Threat model used

| Who | Today (beta) | Final |
|---|---|---|
| Members of the lab | trusted, no login | trusted, signed in; *admins* may change Settings, *members* do everyday work |
| Members of **other** labs on the same network (faculty LAN, VPN) | can reach the server: **everything is open to them** | must see nothing of this lab's data |
| Any web site a lab member opens | must not be able to act on the server (the goal of `access.same_site`) | the same |
| Authors of tool sources | the lab's own source is trusted; other sources are reviewed and pinned | the same |
| The GitHub repository and PyPI | code arrives from there (updates, packages) | releases (FINAL_VERSION.md §3) |

## 3. What is already done well

- **Cross-site requests are refused** (`access.same_site`, which checks `Sec-Fetch-Site` and `Origin`). Every route
  that changes something is marked as settings or work, and `tests/test_access.py` fails on an unmarked one. This is
  a good base for the login.
- **Paths are checked:** job files (`jobs.file_path`), worker uploads (`workers.file_target`/`input_file`), backup
  imports (`folder_of`), transfers (`..` refused, a manifest of SHA-256 sums), notebook files, and upload ids.
- **Secrets:** `secrets/` is `0700` and its files are `0600`. Worker tokens are kept only as SHA-256 hashes and
  compared with `hmac.compare_digest`. A transfer never includes `secrets/`. A token inside an address is refused. A
  tool source that isn't trusted is fetched **without** the server's tokens, pinned and left off until it is reviewed.
- **No shell:** every `subprocess` call takes a list of arguments. Git addresses are matched against a strict pattern
  (no `ext::`, and no address starting with `-`). Branch names are checked.
- **The notebook is rendered safely:** raw HTML is shown as text and `javascript:` links are dropped (tested). Its
  files are served with `CSP: sandbox` and `nosniff`.
- **Worker archives** are unpacked with `filter="data"`. The worker's own credentials are stored as `0600`.
- **Jinja autoescaping** is on. The front end builds the page with `textContent`/`createElement` (`MP.el`).
  `innerHTML` is used only for HTML the server has rendered.
- `pip-audit` finds no known vulnerabilities in `requirements.txt` (on the day of this audit).

## 4. Findings

Severity is given for the **final** deployment (a server that labs reach over a shared network). "Today" says whether
it already matters on a closed lab LAN without a login.

| ID | Severity | Finding | Today (0.11.0) → status |
|---|---|---|---|
| H1 | **High** | DNS rebinding gets past the same-site check: any web site can read and change everything | yes → **fixed in 0.12.0** |
| H2 | **High** | Uploaded HTML/SVG files are served as live pages from the app's address (stored XSS) | yes → **fixed in 0.12.0** |
| H3 | **High** | No login: every read is open, and identity is a cookie name anyone can set | known, planned → **fixed in 0.14.0** (once the lab makes its first account) |
| H4 | **High** (for separating labs) | Tools run inside the server process with all its rights; `pip` can run a source's code before it is enabled | by design → `pip` part **fixed in 0.12.0**; in-process tools open; **0.17.0**: jobs in their own process, optionally as another user — the tools' code is still imported by the server |
| M1 | Medium | No protection against framing (clickjacking) | yes → **fixed in 0.12.0** |
| M2 | Medium | `javascript:` links can be stored: feedback, inventory URL fields, catalogue homepages, Markdown outputs | yes → **fixed in 0.12.0** |
| M3 | Medium | Plain HTTP on `0.0.0.0`. Tokens and (later) session cookies travel unencrypted | deployment → **0.13.0**: Caddy in `deploy/`, docs/DEPLOY_LINUX.md#https; the Mac app stays on HTTP unless the lab adds Caddy |
| M4 | Medium | A new server's setup page belongs to whoever opens it first | yes → **fixed in 0.13.0** (the setup code) |
| M5 | Medium | Code arrives straight from `main` / any branch, and packages arrive unpinned | known, planned → **0.16.0**: lock file, signed feeds; protecting `main` is the owner's (docs/RELEASES.md §3) |
| L1 | Low | No size limits on uploads or request bodies (a full disk) | yes → uploads **fixed in 0.12.0**; the proxy's limit comes with M3 |
| L2 | Low | Formula injection in exported spreadsheets and CSV | yes → the base's and the inventory's exports **fixed in 0.12.0** |
| L3 | Low | Error texts and tracebacks are shown to everyone | — → **fixed in 0.14.0** |
| L4 | Low | `/api/docs` and `/openapi.json` are public | — → **fixed in 0.12.0** (`api_docs = 1` turns them on) |
| L5 | Low | A crafted backup can copy any file the server can read into a job when it is imported | needs a writable NAS → **fixed in 0.12.0** |
| L6 | Info | A settings admin can reach any folder, URL or host the server's OS user can | by design |
| L7 | Info | Job numbers can be guessed (a timestamp and 24 random bits) | — |
| L8 | Info | A worker runs whatever code its server sends, and its token is put on the command line once | by design → token no longer on the command line (0.13.0); a worker still belongs to one lab |

### H1 — DNS rebinding gets past the same-site check (confirmed)

`access.same_site` accepts a request whose `Origin` matches the `Host` header. Under DNS rebinding, an attacker's
page at `http://evil.example:8000` makes `evil.example` resolve to the lab server's IP. The browser then sends
`Origin: http://evil.example:8000` with `Host: evil.example:8000`. These match, so the request passes, and the page can
also **read** the replies, because to the browser it is the same origin. Reproduced:

```
POST /api/feedback   Host: evil.example:8000   Origin: http://evil.example:8000   → 200 (accepted)
POST /api/feedback   Origin: http://evil.example                                  → 403 (refused, as intended)
```

With no login, a lab member who only visits a web page can expose all the lab's data. The page can also add a
trusted tool source (`POST /api/tools/sources`) and so run code on the server. Chrome's *Private Network Access*
blocks some of these requests, but Firefox and Safari don't, so the browser doesn't fix this for us.

*Done in 0.12.0–0.12.1: the server's own names (IP addresses, the names it gives itself, the names the network's DNS gives
its addresses) work with nothing set; only a name nobody gave the computer (a proxy's) is added on Settings.*

**Fix (small):** accept only the server's own host names, e.g. Starlette's `TrustedHostMiddleware`. Take the
allowed names from the lab's setup (`[server] hosts = ["mister-plis.lab.example", "mac-studio.local"]`), and always
allow `localhost`/`127.0.0.1` and the machine's own name. Add the setting to `labs/template.toml` and `labsetup.py`,
following the "no lab in the code" rule. `same_site` should then compare `Origin` with the allowed names, not with
the `Host` the browser sent. Once there is a login, a rebinding page also lacks the session cookie (it is a different
origin), but the host check is still worth having.

### H2 — Uploaded HTML/SVG files are served as live pages (confirmed)

`GET /api/jobs/{id}/files/{rel}` (`app.py:515`) and `GET /api/tm/{id}/files/{rel}`
(`modules/timemachine/web.py:285`) return files with `Content-Disposition: inline` and a type guessed from the
extension. They send no `nosniff` and no CSP. Anyone can upload a file and keep it in Time Machine ("files worth
keeping", `/api/tm/manual`), and a tool whose `File` input accepts any type also keeps the upload in
`jobs/<id>/inputs/`. Reproduced:

```
POST /api/uploads  evil.svg (<svg onload="alert(1)">)  →  POST /api/tm/manual
GET /api/tm/<id>/files/out/evil.svg   →  200  image/svg+xml  inline
```

A script inside that file runs with the app's origin, so `same_site` doesn't stop it. After the login it would act
with the session of whoever opens the file, for example an admin who clicks a colleague's "result". It is the most
direct path from member to admin.

**Fix (small):** serve stored files the way the notebook already does (`modules/notebook/web.py:33`): add the headers
`Content-Security-Policy: default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox` and
`X-Content-Type-Options: nosniff`. Also force `attachment` for active types (`.html .htm .xhtml .svg .xml .js .mjs`)
unless `?download=0` is asked for *and* the file is a sandboxed type. Put this in one helper in the base, used by both
routes and offered to modules (`ModuleContext`). The sturdiest version, for later: serve user files from a separate
origin (another port or host name).

### H3 — No login (known, planned)

What this means in detail, so that the login covers all of it:

- **Reads are not protected.** `test_access.py` checks only routes that change something. These are open to everyone:
  every job, its files and result PDFs, Time Machine, the inventory, the notebook, people, feedback, the backup
  catalogue, `/api/setup/export` (the lab's whole setup: repositories, folders, printer), `/api/system` (paths on
  disk, git remote, host name), `/api/system/credentials` (which hosts, owners and repositories have tokens, and the
  path of the token store), `/api/system/workers`, `/api/system/storage`, and `/openapi.json`.
- **Identity is the `name` cookie** (`access.current`, `prefs.from_cookies`). Anyone can choose any name. That name
  decides "clear **my** jobs" (`_history_scope`), the author of inventory commits, `added_by` on worker tokens,
  `changed_by` on tool settings, and Time Machine authorship.
- `MODE = "open"` makes everyone an admin.

§7 lists what the login needs.

### H4 — Tools run with all the server's rights; `pip` runs a source's code early

- `LocalRunner` runs tools as **threads of the server process**. A tool (or a translation file, `locale/pl.py`, which
  is executed too) can read `secrets/git-credentials.toml`, call git's credential helper (which can return the Mac
  Keychain's GitHub login), read every job and module, and reach anything the server's OS user can. A **trusted** tool
  source is therefore as powerful as a settings admin. Trusting another lab's source gives that lab this power over
  our server.
- `ToolSources.update()` → `_requirements()` runs `pip install --dry-run` and then `pip install -r requirements.txt`
  for a **pinned, untrusted, still-disabled** source as soon as someone moves its pin (`toolsources.py:450`). A
  requirements file can name a local path (`-e .`, `./`), a `git+https://…` package, an sdist (whose `setup.py` runs at
  build time, *even under `--dry-run`*), or an `--index-url`. So the code runs before anyone enables the source. The
  review page shows `requirements.txt`, but it doesn't warn about any of this.

**Fixes:** for sources that aren't trusted, (a) install packages only when the source is **enabled**, not when its pin
moves; (b) pass `--only-binary :all:` and refuse requirement lines that are options, paths or URLs; (c) show a clear
warning on the review page. For separating labs (§6), run **one instance per OS user or container**, so that the
worst a tool can do is limited to its own lab. Later, if tools from other labs become common: run jobs in a
subprocess as a separate, unprivileged user, or in a container, using the `JobSpec` and runner seam that workers
already use, so that a tool never sees `secrets/`.

### M1 — Clickjacking

No `X-Frame-Options` and no `frame-ancestors`. Any web site can show Settings in an invisible frame and trick a
click ("Restart", "Remove source", "Apply"). `same_site` doesn't help, because the click comes from the real page.
**Fix:** a middleware that adds `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors 'none'` to every
response. A full CSP for the pages (`script-src 'self'`) would also be good. It needs the inline `<script>` blocks in
`base.html` and `tool.html` moved into files or given a nonce.

### M2 — Stored `javascript:` links

`MP.el` sets `href` with `setAttribute`, so a stored `javascript:alert(1)` becomes a clickable script:

- **Feedback** `page` (confirmed: it is stored as sent) → the `/feedback` list (`feedback.js:121`).
- **Inventory** fields of type `url` (`reagents.js:49` `extLink`). They are not checked on save.
- **Catalogue** `homepage` (`catalogue.py:76`, shown in `settings.js:553`). This one comes from a third-party
  catalogue, so it is outside content.
- **Markdown and Alert outputs** (`outputs._markdown`, confirmed: `[x](javascript:…)` is kept). A tool that puts a
  sample name or title someone typed into Markdown passes the link on.

**Fix:** in `MP.el`, allow only `http:`, `https:`, `mailto:` and relative addresses in `href`/`src`, and drop any other
scheme (one place, covers every page). On the server, check URL fields and feedback `page` on save, and use the
notebook's link filter (`modules/notebook/obsidian.py`) in `outputs._markdown` too.

### M3 — Plain HTTP on every interface

`config.host = "0.0.0.0"`, and uvicorn serves HTTP only. Worker tokens (`Authorization: Bearer`), and soon passwords
and session cookies, cross the network in the clear. **Fix (deployment):** put a reverse proxy with TLS in front
(Caddy or nginx; a university certificate, or an internal CA). Bind the app to `127.0.0.1` (or the Docker network
only). Run uvicorn with `proxy_headers=True` and `forwarded_allow_ips` set to the proxy. Send HSTS. Add a section to
DEPLOY_LINUX.md and DEPLOY_WINDOWS.md, and a Caddy service to `deploy/docker-compose.yml`. Workers should use the
`https://` address.

### M4 — The setup page belongs to whoever comes first

A new server sends every page to `/setup`, and `/api/setup/apply`, `/api/transfer/import` and the tool-source routes
are open (settings, and today everyone is an admin). Whoever opens a new server first sets it up, which includes
choosing its tool sources (code). **Fix:** until the server is set up, accept setup only with a one-time **setup code**
that the server prints in its log and console at start (as Jupyter does). The same code makes the first admin account
when the login comes.

### M5 — Where the code comes from

`Sync with git`, the nightly auto-update and **Run another branch** run whatever is on GitHub's `main` or a chosen
branch. `pip install -r requirements.txt` takes the newest versions allowed by lower bounds only. A compromised GitHub
account, a pushed mistake, or a hijacked package reaches every lab overnight. This is already planned (releases,
FINAL_VERSION.md §3). Before other labs depend on it: protect `main` (no force push, require 2FA for everyone who can
push), pin the versions in a lock file with hashes (`pip-compile --generate-hashes`) for releases and the Docker image,
and sign releases (F2).

### L1 — No size limits

`/api/uploads`, `PUT /api/worker/jobs/…/files/…` and the PDF form (64 MB per part) take any amount of data, and
uvicorn sets no limit. **Fix:** a limit at the proxy (`client_max_body_size` / `request_body max_size`), and a lab
setting checked in `UploadStore.save` while copying.

### L2 — Formula injection in exports

Text people type (sample names, inventory fields, titles) goes into `.xlsx` through openpyxl, which stores a string
starting with `=` as a **formula**, and into the inventory's CSV. A cell such as `=HYPERLINK("http://…","click")` works
when the file is opened. **Fix:** in `excel.py` and the inventory exports, write user text that starts with
`= + - @` (or a tab or CR) as text, either by setting `cell.data_type = "s"` or by prefixing `'`. Don't touch real
numbers.

### L3 — Error details

`api_suggest` returns `f"{type(e).__name__}: {e}"`, and jobs store and show a `trace`. That is fine among trusted
colleagues. After the login, show tracebacks only to admins.

### L4 — API documentation

`docs_url="/api/docs"` and `/openapi.json` are public. Turn them off, or make them admin-only once the login exists.

### L5 — A backup is trusted input on import

`Catalogue.import_files` (`backup.py:396`) copies `folder / e["backup"]` for each manifest entry. It checks that the
*target* stays inside the job, but not that the *source* stays inside the backup. A backup folder on a NAS that other
people can write to could hold a manifest with `"backup": "../../../../home/…/secrets/git-credentials.toml"`. Its
checksums would match, because the attacker computes them. Importing it puts that file inside a job, where everyone
can download it. **Fix:** resolve the source and require it to be inside `folder`. Give each lab's backup share its own
credentials (§6).

### L6 — How much a settings admin can do

Settings can point the server at any folder (storage, backup, transfer, lab files, a repository as `/path` or
`file://`), any `https://` address (lab file, catalogue, release feed), any `host:port` (label printer, model), and
any tool source. That is fine for an admin who runs the machine. On a shared faculty server, though, a lab's admin
would have the server's OS rights. Limit folders to a list of allowed roots chosen by whoever runs the machine
(config.toml, not the lab file), or rely on the container's volumes (§6).

### L7 — Job numbers

`20261113-121508-60737a`: a timestamp and 6 hex digits. Fine inside a lab, where everyone may see every job. Don't
use job numbers as secrets (e.g. "anyone with the link" sharing).

### L8 — Workers

A worker runs whatever tools its server sends. A worker computer therefore belongs to **one** lab, or to one OS user
per lab. The first run takes `--token` on the command line, where it ends up in the shell history and `ps`. Offer
`MISTER_PLIS_WORKER_TOKEN` or reading it from stdin.

## 5. Checked and found fine

Path traversal in job, Time Machine, notebook and worker files; upload ids; the transfer manifest; tar extraction on
workers; git option injection (addresses, branches, `sha` in Time Machine, `rid` in the inventory history); the
notebook's Markdown; Jinja autoescaping; the front end's DOM building; the credential helper's quoting; secrets'
file modes; worker token storage and comparison; `/api/setup/read` with `path` (limited to the lab files that come
with the code); dependencies (`pip-audit`).

## 6. Keeping labs apart

**Model (keep it):** *one instance per lab*. Labs share tools by adding the same tool source, never by sharing a
server. Each instance has its own data, storage, backup and secrets. Nothing in one instance names or reads
another. The code supports this already. The rest depends on the deployment:

1. **One container (or OS user) per lab, always.** Because of H4, two labs' instances must never run as the same OS
   user or in the same container. Each lab gets its own Docker service with its own volumes (`home`, `storage`,
   `backup`). No volume is shared between labs, and nothing is mounted from another lab's folders.
2. **The network.** Each instance sits behind the TLS proxy (M3) with the host check (H1) and the login (§7). If the
   faculty network is wide, also allow only the university network or VPN at the proxy.
3. **Its own tokens.** Each lab uses its own fine-grained GitHub tokens, limited to its repositories: read-only for
   tool sources and the notebook, read/write only for the inventory repository. Never a person's classic token with
   access to everything.
4. **Backups.** Backups are complete and easy to read, so each lab's backup share must be readable only by that lab
   (its own NAS user). Also L5.
5. **Workers.** One worker per lab, or one OS user per lab on a shared GPU machine (L8).
6. **The model server (Ollama).** It may be shared. It sees inventory text, has no login, and must stay on the
   internal network.
7. **Other labs' tool sources** stay untrusted (reviewed and pinned), and their packages are installed only when the
   source is enabled (H4).

**Not recommended: one server for several labs.** The base keeps one global set of everything: one data folder, one
job list, one set of settings, people and tool sources, and tools running in-process. Making each of these per lab
would touch almost every store and route, and a single missed filter would leak data. Separate instances isolate labs
by construction.

## 7. What the login has to cover

`access.py` is the seam. Fill `current()` and make access **deny-by-default**:

1. **A middleware that requires a session for every route**, with an explicit list of exceptions: `/static`,
   `/i18n`, the login pages, `/api/version` (the health check; consider leaving out `instance_id`), and `/api/worker/*`
   (worker token). Extend `tests/test_access.py`: every route not on that list must answer 401/redirect without a
   session, *including GETs*.
2. **Reads only admins may make:** `/api/system`, `/api/system/credentials`, `/api/system/workers`,
   `/api/system/storage`, `/api/setup/export`, `/api/system/snapshots`, the backup catalogue (it covers all jobs ever),
   and `/api/docs`.
3. **Identity from the account, not the cookie.** Store an account id with jobs, feedback, Time Machine entries and
   inventory commits, plus the display name. Base "my jobs" on the id. Accounts start from the names already in use
   (agreed in FINAL_VERSION.md §1). The `name` cookie becomes display only, or goes away.
4. **Sessions:** a random session id kept on the server, or a signed cookie (`itsdangerous`) with an expiry. Use
   `HttpOnly; Secure; SameSite=Lax`, a new id at sign-in, and sign-out. Keep `same_site` as a second line of defence.
5. **Passwords**, if the lab keeps its own accounts: argon2id or bcrypt, a limit on attempts, and a reset that only an
   admin can trigger. **Single sign-on** (F5) is better: OIDC with the university (through `authlib`, or
   `oauth2-proxy` in front). With SSO no passwords are stored, and people who leave the university lose access by
   themselves. Even with SSO, roles stay in MISTER PLIS: the instance keeps a list of who is a member and who is an
   admin, so a valid university account alone doesn't open a lab's server.
6. **The first admin** is created with the setup code (M4).
7. **An audit log** of settings changes and sign-ins (who and when). Some of it exists already (`changed_by`,
   snapshots), but it records cookie names.
8. **Workers** keep their tokens. Only admins add and remove them (already the case).

## 8. Order of work

| When | What | Effort |
|---|---|---|
| **Now** (also useful on the closed lab network) | H1 host check · H2 safe file serving · M1 frame headers · M2 `href` filter and the Markdown link filter · L1 upload limit · L4 docs off · L5 backup source check · H4 pip only on enable, binary-only · L2 formula escaping | **done in 0.12.0** |
| **Before another lab's server or a faculty network** | M3 TLS proxy in `deploy/` · M4 setup code · §6 deployment notes in DEPLOY_LINUX.md (one container per lab, volumes, tokens, backups) · L8 worker token | **done in 0.13.0** |
| **The login** | §7, then H3 is closed; L3 tracebacks for admins only | **done in 0.14.0** |
| **Releases** | M5: protected `main`, hashed lock file, signed releases (F2) | **done in 0.16.0** (the key and GitHub's settings: the owner) |
| Later | tools in a subprocess (0.17.0: kept jobs; the forms' code still in the server); a strict CSP (**done in 0.17.0**); user files from a separate origin (**done in 0.18.0**); a warning on the review page for a source's requirements (**done in 0.17.0**) | — |
