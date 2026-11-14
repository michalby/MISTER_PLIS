# MISTER PLIS on Windows

*November 2026 (docs/PREP_PLAN.md R4). On Windows, MISTER PLIS runs in **Docker Desktop** — the same image as on
Linux ([DEPLOY_LINUX.md](DEPLOY_LINUX.md)). (It also runs straight from a git clone with Python —
`scripts\run.sh` in Git Bash — which is what the tests check, but a lab server is easier to keep running in Docker.)*

1. Install **Docker Desktop** (with the WSL 2 backend, its default) and **Git for Windows**. Start Docker Desktop and
   tick *Start Docker Desktop when you sign in*.
2. In PowerShell, get the code and build the image:

   ```powershell
   git clone https://github.com/michalby/MISTER_PLIS.git
   cd MISTER_PLIS
   docker build --build-arg COMMIT=$(git rev-parse HEAD) -t mister-plis .
   ```

3. Make a folder for the server, e.g. `C:\MISTER PLIS`, and copy `deploy\docker-compose.yml` into it. Change the
   backup volume to the NAS (below), then in that folder: `docker compose up -d`.
4. Open `http://localhost:8000` (other computers: `http://<this PC's name>:8000`; allow port 8000 in *Windows Defender
   Firewall → Inbound rules* for the lab's network). On the setup page choose **`/storage`** as the storage folder and
   **`/backup`** as the backup folder — the paths *inside* the container, not `C:\…`. The server answers only to its own
   names and IP addresses; inside the container it doesn't know the PC's name, so set it in the compose file
   (`MISTER_PLIS_SERVER_NAMES: "<this PC's name>"`), or open it by its IP address. From another computer, the setup page asks for the server's
   setup code: `docker compose exec mister-plis python -m mister_plis setup-code` shows it.

**Where the folders are.** Next to the compose file: `home\` (the instance: `config.toml`, `data\`, `secrets\`) and
`storage\` (the jobs). Keep them on a local disk: Docker Desktop shares Windows folders with the container more slowly
than its own volumes, which is fine for a lab's use.

**The NAS as the backup folder.** The container can't see a mapped drive letter (`Z:`). Either give the compose file the
NAS's share as a Docker volume:

```yaml
volumes:
  nas-backup:
    driver: local
    driver_opts: {type: cifs, device: "//nas.lab.local/backup/mister-plis", o: "username=lab,password=…,uid=1000,gid=1000"}
```

and use `nas-backup:/backup` instead of the third line under the service's `volumes:` — or copy backups from a local
folder to the NAS with Windows' own tools. (A password in the compose file stays on that PC; never commit it.)

**Updating, logs, restarts:** as on Linux — `docker compose up -d` after a new image; `docker compose logs -f`; the
server restarts itself from Settings, and Docker Desktop starts it again after Windows restarts (`restart:
unless-stopped`).

**HTTPS, and several labs on one PC:** as on Linux with Docker — [DEPLOY_LINUX.md, HTTPS](DEPLOY_LINUX.md#https)
(Caddy in front, `docker-compose.https.yml`) and [Several labs on one machine](DEPLOY_LINUX.md#several-labs-on-one-machine).
