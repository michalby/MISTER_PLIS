"""Start the server: ``python -m mister_plis [--port 8000] [--reload]``.

Set up the lab from a lab file (docs/LAB_SETUP_PLAN.md):
``python -m mister_plis setup labs/<name>.toml [--check] [--yes]`` and ``python -m mister_plis export [file]``.
Move a whole server: ``python -m mister_plis transfer export|check|import <folder>`` (mister_plis/transfer.py).
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time

from .config import ROOT, settings


def _lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def wait_for_port(host: str, port: int, seconds: float = 10.0) -> bool:
    """Wait until ``port`` can be listened on (True), for at most ``seconds`` (then False: uvicorn says why). After a
    restart on Windows the old process may still hold the port for a moment."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    deadline = time.monotonic() + seconds
    while True:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                if os.name != "nt":  # as uvicorn does; on Windows this would let two servers share the port
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)


# Browsers reuse an idle connection for the next click. uvicorn closes idle ones after 5 s by default, and a
# click that lands just as the server closes one fails with "page unavailable" (Safari especially) until a
# refresh. The page also polls every 15 s, so keep idle connections open longer than that.
KEEP_ALIVE_S = 75

MARK = {"change": "change", "same": "  same", "skip": "  skip", "later": " later", "error": " ERROR", "done": "  done"}


def _show(v) -> str:
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(map(str, v)) + "]"
    return f"“{v}”" if isinstance(v, str) else str(v)


def _print_rows(rows: list[dict], everything: bool = False) -> None:
    shown = [r for r in rows if everything or r["status"] != "same"]
    for r in shown:
        where = f"[{r['section']}] " if r["section"] else ""
        line = f"  {MARK.get(r['status'], r['status']):>6}  {where}{r['label']}: "
        line += _show(r["new"]) if r["status"] == "same" else f"{_show(r['old'])} → {_show(r['new'])}"
        if r.get("note"):
            line += f"   ({r['note']})"
        print(line)
    same = len(rows) - len(shown)
    if same:
        print(f"  {same} setting(s) already as the file says.")


def setup_command(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="mister_plis setup", description="Set this server up from a lab file.")
    ap.add_argument("file", help="the lab file: a path (e.g. labs/ourlab.toml) or an https:// address")
    ap.add_argument("--check", action="store_true", help="only show what it would change, and whether the repositories can be reached")
    ap.add_argument("--yes", action="store_true", help="don't ask before applying")
    ap.add_argument("--if-new", action="store_true", help="only if this server isn't set up yet (used at start for lab_file)")
    ap.add_argument("--no-network", action="store_true", help="don't try to reach the repositories")
    args = ap.parse_args(argv)

    os.chdir(ROOT)
    from . import labsetup

    labsetup.migrate()
    if args.if_new and not labsetup.is_new():
        print("This server is set up already; the lab file is not applied again (use the setup page, or run this "
              "without --if-new).")
        return 0
    try:
        text, where = labsetup.read_source(args.file)
        lab, warnings = labsetup.parse(text, where)
    except labsetup.ToolError as e:
        print(f"{args.file}:\n{e}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"warning: {w}")

    from .app import lab as setup  # loads the base and its modules (nothing starts)

    rows = setup.plan(lab)
    print(f"What {where} would change on this server ({settings.data_path}):")
    _print_rows(rows, everything=args.check)
    if not args.no_network:
        access = labsetup.check_access(lab, setup.modules.setup_forms())
        if access:
            print("Repositories:")
            for a in access:
                said = {"public": "can be read (public)", "token": "can be read with the server's GitHub token",
                        "folder": "a git folder on this computer", "unreachable": "CAN'T BE READ"}[a["status"]]
                print(f"  {a['what']}: {a['url']} — {said}" + (f" ({a['note']})" if a["note"] else ""))
    errors = sum(r["status"] == "error" for r in rows)
    if args.check:
        return 1 if errors else 0
    if not any(r["status"] in ("change", "later") for r in rows):
        print("Nothing to change.")
        setup.apply(lab, "command line", where)  # the server counts as set up all the same
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("Run it again with --yes to apply.")
            return 1
        if input("Apply these changes? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing was changed.")
            return 1
    r = setup.apply(lab, "command line", where)
    print("Applied:")
    _print_rows(r["rows"])
    if r["restart"]:
        print("Restart the server to use everything (tool sources and modules are loaded at start).")
    return 1 if any(x["status"] == "error" for x in r["rows"]) else 0


def export_command(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="mister_plis export", description="Write this server's settings as a lab file.")
    ap.add_argument("file", nargs="?", help="where to write it (default: print it)")
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    from . import labsetup
    from .app import lab as setup

    text = labsetup.dumps(setup.current(), "This server's settings as a lab file (python -m mister_plis export).")
    if args.file:
        with open(args.file, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Written to {args.file}")
    else:
        sys.stdout.write(text)
    return 0


def transfer_command(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="mister_plis transfer",
                                 description="Move a whole server: its jobs, Time Machine, settings and the modules' data.")
    sub = ap.add_subparsers(dest="what", required=True)
    e = sub.add_parser("export", help="copy this server into a new folder inside FOLDER (a USB disk, the NAS…)")
    e.add_argument("folder")
    c = sub.add_parser("check", help="what a copied server holds, every file checked")
    c.add_argument("folder")
    i = sub.add_parser("import", help="bring a copied server into this one (a new server: no jobs yet); asks first")
    i.add_argument("folder")
    i.add_argument("--yes", action="store_true", help="don't ask")
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    from . import labsetup, transfer
    from .errors import ToolError

    labsetup.migrate()

    def show(s: dict) -> None:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["created"] or 0))
        print(f"  {s['lab_name'] or '(no lab name)'} — from {s['from'].get('host', '?')}, copied {when}"
              f"{' by ' + s['by'] if s['by'] else ''}: {s['jobs']} job(s), {s['files']} files, {s['bytes'] / 1e6:.1f} MB")

    try:
        if args.what == "export":
            from .app import backups, jobs, modules
            from . import __version__, updater

            if any(j.record for j in jobs.active()):
                raise ToolError("Jobs are running — wait until they finish, then copy the server.")
            r = transfer.export(args.folder, settings.data_path, settings.storage_path,
                                modules.storage_folders(settings.storage_path), lab_name=backups.lab_name(), by="command line",
                                version=__version__, commit=updater.RUNNING.get("commit", ""), jobs=len(jobs.recent(10**9)))
            print(f"Copied and checked: {r['files']} files, {r['bytes'] / 1e6:.1f} MB\n  {r['path']}")
            return 0
        s = transfer.summary(args.folder, verify=True)
        print("Checked, every file:")
        show(s)
        if args.what == "check":
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                print("Run it again with --yes to bring it in.")
                return 1
            if input(f"Bring it into this server ({settings.data_path})? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Nothing was changed.")
                return 1
        r = transfer.bring_in(args.folder, settings.data_path, settings.storage_path, "command line")
        print(f"Brought in: {r['jobs']} job(s), {r['files']} files.")
        for a in r["set_aside"]:
            print(f"  what was here is kept as {a}")
        print("Start (or restart) the server to use it. Tool sources are fetched again at the start.")
        return 0
    except ToolError as err:
        print(str(err), file=sys.stderr)
        return 2


def _first_start() -> None:
    """``lab_file`` in config.toml: a server that isn't set up yet applies it before it starts (in its own process,
    so the server then starts with everything in place)."""
    from . import labsetup

    labsetup.migrate()
    if settings.lab_file.strip() and labsetup.is_new():
        print(f"  Setting this server up from {settings.lab_file}…", flush=True)
        subprocess.run([sys.executable, "-m", "mister_plis", "setup", settings.lab_file, "--yes", "--if-new"], cwd=ROOT)


def _trusted_proxies() -> str:
    """Whose X-Forwarded-For / -Proto uvicorn believes (``trusted_proxies``; else this computer only)."""
    import re

    return ",".join(p for p in re.split(r"[\s,;]+", settings.trusted_proxies or "") if p) or "127.0.0.1"


def _show_setup_code() -> None:
    """A server that isn't set up yet: say its setup code (mister_plis/setupcode.py), for setting it up from another
    computer."""
    from . import labsetup, setupcode

    if labsetup.is_new():
        code = setupcode.ensure()
        print(f"\n  This server isn't set up yet. Its setup code: {code}\n"
              "  (needed on the setup page from another computer; on this one, open http://localhost:… — no code)", flush=True)
    elif setupcode.relevant():
        code = setupcode.ensure()
        print(f"\n  Sign-in is off: the lab has no accounts yet. To make the first one (an admin) from another computer,\n"
              f"  Settings → People asks for this server's setup code: {code}", flush=True)


def account_command(argv: list[str]) -> int:
    """``python -m mister_plis account list | add <name> [--admin] | reset <name>``: the lab's accounts from the server's
    own command line — e.g. when the only admin forgot their password."""
    from . import accounts
    from .errors import ToolError

    ap = argparse.ArgumentParser(prog="mister_plis account", description="The lab's accounts (who may sign in).")
    ap.add_argument("what", choices=("list", "add", "reset"))
    ap.add_argument("name", nargs="?", default="")
    ap.add_argument("--admin", action="store_true", help="add: an admin (may change Settings)")
    args = ap.parse_args(argv)
    store = accounts.Accounts(settings.data_path, settings.secrets_path)
    try:
        if args.what == "list":
            for a in store.list():
                print(f"{a['name']}  ({a['role']})")
            if not store.any():
                print("No accounts: sign-in is off. Settings → People makes the first one (or: account add <name> --admin).")
            return 0
        if not args.name:
            print("Give the account's name.", file=sys.stderr)
            return 2
        if args.what == "add":
            password = store.create(args.name, "admin" if args.admin or not store.any() else "member", None, "command line")
            from . import setupcode

            setupcode.forget()
            print(f"Made {args.name}'s account. Temporary password (they choose their own at sign-in): {password}")
        else:
            password = store.reset_password(args.name, "command line")
            print(f"New temporary password for {args.name} (they choose their own at sign-in): {password}")
        print("The server picks this up at once; no restart needed.")
        return 0
    except ToolError as e:
        print(str(e), file=sys.stderr)
        return 2


def job_user_command(argv: list[str]) -> int:
    """``python -m mister_plis job-user [<name>] [--check]``: how to make jobs run as another user of this computer
    (job_user, docs/DEPLOY_LINUX.md "Jobs as another user"), and — with --check — whether it works: that user can't
    read the server's secrets, and can write job folders."""
    import getpass
    import json
    import subprocess
    from pathlib import Path

    from .runners import ProcessRunner

    ap = argparse.ArgumentParser(prog="mister_plis job-user")
    ap.add_argument("name", nargs="?", default="")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    name = args.name or settings.job_user or "mister-plis-jobs"
    me = getpass.getuser()
    child = ProcessRunner(job_user="").child_command()
    if not args.check:
        print(f"""To run jobs as the user {name} (on Linux; as root):

  useradd --system --no-create-home --shell /usr/sbin/nologin --gid "$(id -gn {me})" {name}
  chmod -R g+rwX,g+s "{settings.storage_path / 'jobs'}" "{settings.storage_path / 'tool-data'}"
  echo '{me} ALL=({name}) NOPASSWD: {" ".join(child)}, {" ".join(child)} --check' > /etc/sudoers.d/mister-plis-jobs
  chmod 440 /etc/sudoers.d/mister-plis-jobs

then in config.toml: job_user = "{name}", restart the server, and check it with:
  python -m mister_plis job-user {name} --check
(the secrets folder {settings.secrets_path} must stay readable by {me} only: it is, unless someone changed it).""")
        return 0
    folders = {"secrets": str(settings.secrets_path), "jobs": str(settings.storage_path / "jobs"),
               "tool_data": str(settings.storage_path / "tool-data")}
    cmd = ["sudo", "-n", "-u", name, "--", *child, "--check"]
    try:
        r = subprocess.run(cmd, input=json.dumps(folders) + "\n", capture_output=True, text=True, timeout=60)
        got = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        got, r = None, None
        print(f"Couldn't run it: {e}")
    if got is None:
        print("The job user couldn't be used:", (r.stderr.strip() if r else "") or "sudo refused (see the steps without --check).")
        return 1
    problems = []
    if got["user"] == me:
        problems.append(f"the job ran as {me}, the server's own user")
    if got["secrets_readable"]:
        problems.append(f"{name} can read the secrets folder {folders['secrets']} (it should be readable by {me} only)")
    if not got["jobs_writable"]:
        problems.append(f"{name} can't write in {folders['jobs']} (the shared group, g+rwX,g+s)")
    if got.get("tool_data_writable") is False:
        problems.append(f"{name} can't write in {folders['tool_data']}")
    if not got["code_readable"]:
        problems.append(f"{name} can't read the code ({Path(__file__).resolve().parent})")
    for p in problems:
        print(f"  ✗ {p}")
    if not problems:
        print(f"  ✓ jobs run as {got['user']}, who can't read the server's secrets and can write job folders.")
    return 1 if problems else 0


def setup_code_command(argv: list[str]) -> int:
    """``python -m mister_plis setup-code``: the setup code again (e.g. ``docker compose exec mister-plis python -m
    mister_plis setup-code``)."""
    from . import labsetup, setupcode

    labsetup.migrate()
    if not setupcode.relevant():
        print("This server is set up and has accounts: no setup code is needed.")
        return 0
    print(setupcode.ensure())
    return 0


def _utf8_output() -> None:
    """Print in UTF-8 (arrows, Polish letters) where the system's default is an older code page (Windows, into a pipe
    or a log); what a terminal can't show becomes "?" rather than an error."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _utf8_output()
    commands = {"setup": setup_command, "export": export_command, "transfer": transfer_command,
                "setup-code": setup_code_command, "account": account_command, "job-user": job_user_command}
    if len(sys.argv) > 1 and sys.argv[1] in commands:
        sys.exit(commands[sys.argv[1]](sys.argv[2:]))

    import uvicorn

    ap = argparse.ArgumentParser(prog="mister_plis", description="Run the MISTER PLIS web server.",
                                 epilog="Also: python -m mister_plis setup <lab file> [--check], python -m mister_plis export [file], python -m mister_plis setup-code, python -m mister_plis account list|add|reset")
    ap.add_argument("--host", default=settings.host)
    ap.add_argument("--port", type=int, default=settings.port)
    ap.add_argument("--reload", action="store_true", help="development mode: restart on code changes")
    args = ap.parse_args()

    os.chdir(ROOT)
    _first_start()
    _show_setup_code()
    settings.port = args.port
    if not wait_for_port(args.host, args.port):
        print(f"  Port {args.port} is still in use.", file=sys.stderr, flush=True)
    if (settings.files_origin or "").strip().lower() != "off":
        from . import fileorigin

        fileorigin.serve(args.host, settings.files_port or args.port + 1)  # stored files from an origin of their own
    ip = _lan_ip()
    print(f"\n  MISTER PLIS  →  http://localhost:{args.port}")
    if ip and args.host in ("0.0.0.0", "::"):
        print(f"  on the network →  http://{ip}:{args.port}   http://{socket.gethostname()}:{args.port}")
    print()

    if args.reload:
        os.environ["MISTER_PLIS_DEV_RELOAD"] = "1"
        os.environ["MISTER_PLIS_PORT"] = str(args.port)
        uvicorn.run(
            "mister_plis.app:app",
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[str(ROOT / "mister_plis"), str(ROOT / "modules"),
                         *[str(p) for p in [settings.data_path / "tool-sources", *settings.tool_folder_paths()] if p.is_dir()]],
            reload_includes=["*.py", "*.html", "*.md"],
            timeout_keep_alive=KEEP_ALIVE_S,
            proxy_headers=True, forwarded_allow_ips=_trusted_proxies(),
        )
    else:
        uvicorn.run("mister_plis.app:app", host=args.host, port=args.port, log_level="info", timeout_keep_alive=KEEP_ALIVE_S,
                    proxy_headers=True, forwarded_allow_ips=_trusted_proxies())


if __name__ == "__main__":
    main()
