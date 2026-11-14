"""Self-update: ``git pull`` the repo, reinstall requirements if they changed, restart the server."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import gitutil
from .config import ROOT, settings


# git commands that reach the code's repository: they may use the instance's tokens (Settings → GitHub access)
_NETWORK = {"fetch", "pull", "ls-remote"}


def git(*args: str, timeout: float = 60) -> tuple[int, str]:
    """git in the code checkout (keeps leading spaces: `git status --porcelain` needs them)."""
    return gitutil.run(*args, cwd=ROOT, timeout=timeout, credentials=bool(args) and args[0] in _NETWORK)


def _redact(url: str) -> str:
    return re.sub(r"//[^@/]+@", "//", url)


def head_info(ref: str = "HEAD") -> dict:
    code, out = git("log", "-1", "--format=%H%x1f%h%x1f%cI%x1f%s%x1f%an", ref)
    if code != 0 or not out:
        # no git checkout (a Docker image, a package): the build says which commit it was made from
        built = os.environ.get("MISTER_PLIS_COMMIT", "").strip() if ref == "HEAD" else ""
        if re.fullmatch(r"[0-9a-f]{7,40}", built):
            return {"commit": built, "short": built[:7], "date": os.environ.get("MISTER_PLIS_COMMIT_DATE", ""),
                    "subject": "", "author": ""}
        return {"commit": "", "short": "dev", "date": "", "subject": "", "author": ""}
    full, short, date, subject, author = out.split("\x1f")
    return {"commit": full, "short": short, "date": date, "subject": subject, "author": author}


RUNNING = head_info()  # the code version this process was started with
STARTED_AT = time.time()


BRANCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def _choice_file():
    return settings.data_path / "git_branch.json"


def chosen_branch() -> str:
    """The branch this server follows: the one picked on Settings → Server & updates, else ``git_branch`` in config.toml."""
    try:
        b = json.loads(_choice_file().read_text(encoding="utf-8")).get("branch", "")
    except (OSError, ValueError, AttributeError):
        b = ""
    return b if isinstance(b, str) and BRANCH_NAME.match(b) else settings.git_branch


def upstream() -> str:
    branch = chosen_branch()
    if branch:
        return f"origin/{branch}"
    code, out = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return out if code == 0 else ""


HOW = {  # how an instance without a git checkout is updated (Settings → Server & updates)
    "docker": "This server runs in Docker: it is updated with a new image (docker compose pull, then docker compose up -d). Its data stays in its volumes.",
    "package": "This server was installed as a package: it is updated by installing the new version (pip install --upgrade mister-plis), then restarting it.",
}


def status() -> dict:
    code, _ = git("rev-parse", "--is-inside-work-tree")
    if code != 0:
        from . import __version__, install

        kind = install.kind()
        return {"is_repo": False, "running": RUNNING, "version": __version__, "install": kind,
                "how": HOW.get(kind, HOW["package"])}
    _, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    code, remote = git("remote", "get-url", "origin")
    remote = remote if code == 0 else ""
    _, porcelain = git("status", "--porcelain", "--untracked-files=no")
    up = upstream()
    ahead = behind = 0
    if up:
        c, out = git("rev-list", "--left-right", "--count", f"HEAD...{up}")
        if c == 0 and out:
            ahead, behind = (int(x) for x in out.split())
    fetch_head = ROOT / ".git" / "FETCH_HEAD"
    return {
        "is_repo": True,
        "branch": branch,
        "remote": _redact(remote),
        "upstream": up,
        "ahead": ahead,
        "behind": behind,
        "dirty": [line[3:] for line in porcelain.splitlines() if line.strip()],
        "last_fetch": fetch_head.stat().st_mtime if fetch_head.exists() else None,
        "head": head_info(),
        "running": RUNNING,
        "restart_pending": head_info()["commit"] != RUNNING["commit"],
        "auto": auto_settings(),
    }


def check() -> dict:
    """Fetch from GitHub and list commits that a sync would bring in."""
    code, out = git("fetch", "--prune", "origin", timeout=90)
    st = status()
    st["fetch_ok"] = code == 0
    st["fetch_output"] = out
    st["incoming"] = []
    if code == 0 and st.get("upstream"):
        _, log = git("log", "--format=%h%x1f%an%x1f%cI%x1f%s", f"HEAD..{st['upstream']}", "-n", "50")
        st["incoming"] = [dict(zip(("short", "author", "date", "subject"), line.split("\x1f"))) for line in log.splitlines() if line]
    return st


def sync() -> dict:
    """Pull the latest code. Returns a step log; the caller schedules the restart."""
    steps: list[dict] = []

    def step(name: str, code: int, out: str) -> bool:
        steps.append({"name": name, "ok": code == 0, "output": out})
        return code == 0

    old = head_info()["commit"]
    branch = chosen_branch()
    pull_args = ["pull", "--ff-only", "origin", branch] if branch else ["pull", "--ff-only"]
    if not step("git pull", *git(*pull_args, timeout=120)):
        return {"ok": False, "steps": steps, "changed": False}
    return _finish(old, steps)


def _finish(old: str, steps: list) -> dict:
    """After the code on disk changed: list the changed files, reinstall packages if needed."""
    new = head_info()["commit"]
    changed = bool(old) and old != new
    if changed:
        _, files = git("diff", "--name-only", old, new)
        changed_files = files.splitlines()
        steps.append({"name": "changed files", "ok": True, "output": "\n".join(changed_files)})
        if any(f.startswith("requirements") for f in changed_files):
            # the pinned versions, each checked against its checksum (scripts/lock.sh); a checkout from before the lock
            # file existed: requirements.txt
            lock = ROOT / "requirements.lock"
            how = ["--require-hashes", "-r", str(lock)] if lock.is_file() else ["-r", str(ROOT / "requirements.txt")]
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *how],
                cwd=ROOT, capture_output=True, text=True, timeout=900,
            encoding="utf-8", errors="replace")
            out = (r.stdout + r.stderr).strip().splitlines()
            ok = r.returncode == 0
            steps.append({"name": "pip install " + " ".join(a if a.startswith("-") else Path(a).name for a in how), "ok": ok,
                          "output": "\n".join(out[-30:])})
            if not ok:
                return {"ok": False, "steps": steps, "changed": changed}
    restart_needed = head_info()["commit"] != RUNNING["commit"]
    return {"ok": True, "steps": steps, "changed": changed, "restart": restart_needed, "new": head_info()}


def branches() -> dict:
    """The branches on GitHub this server could run, and the one it runs now."""
    code, out = git("fetch", "--prune", "origin", timeout=90)
    _, current = git("rev-parse", "--abbrev-ref", "HEAD")
    _, listing = git("for-each-ref", "--sort=-committerdate", "--format=%(refname:short)%1f%(committerdate:iso-strict)%1f%(subject)", "refs/remotes/origin")
    names = []
    for line in listing.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3 and parts[0].startswith("origin/") and parts[0] != "origin/HEAD":
            names.append({"name": parts[0][len("origin/"):], "date": parts[1], "subject": parts[2]})
    return {"fetch_ok": code == 0, "fetch_output": "" if code == 0 else out, "current": current, "following": chosen_branch(),
            "pinned": settings.git_branch, "branches": names}


def switch(branch: str) -> dict:
    """Check out another branch from GitHub (refuses when files were edited on this machine). The caller restarts."""
    steps: list[dict] = []
    if not BRANCH_NAME.match(branch or "") or ".." in branch:
        return {"ok": False, "steps": [{"name": "Not a branch name", "ok": False, "output": branch}]}
    _, porcelain = git("status", "--porcelain", "--untracked-files=no")
    if porcelain.strip():
        return {"ok": False, "steps": [{"name": "Files were changed on this machine — switching would mix them in. Undo or commit them first.",
                                         "ok": False, "output": porcelain}]}
    old = head_info()["commit"]
    code, out = git("fetch", "origin", branch, timeout=120)
    steps.append({"name": "git fetch", "ok": code == 0, "output": out})
    if code != 0:
        return {"ok": False, "steps": steps}
    has_local = git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0
    if has_local:
        code, out = git("checkout", branch)
        steps.append({"name": "git checkout", "ok": code == 0, "output": out})
        if code == 0:
            code, out = git("merge", "--ff-only", f"origin/{branch}")
            steps.append({"name": "git pull", "ok": code == 0, "output": out})
    else:
        code, out = git("checkout", "-b", branch, "--track", f"origin/{branch}")
        steps.append({"name": "git checkout", "ok": code == 0, "output": out})
    if code != 0:
        return {"ok": False, "steps": steps}
    f = _choice_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"branch": branch, "switched": time.time()}), encoding="utf-8")
    return _finish(old, steps)


# ---- updating by itself at night -------------------------------------------------------------------------
# For code pushed from elsewhere (Claude Code on the web, another computer): the server pulls it between 3 and
# 5 at night, only when nobody's job is running and nothing was edited on this machine, then restarts.
AUTO_MODES = ("off", "night")
NIGHT = (3, 5)  # from 3:00 to 4:59, local time


def _auto_file():
    return settings.data_path / "auto_update.json"


def auto_settings() -> dict:
    try:
        d = json.loads(_auto_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    mode = d.get("mode") if d.get("mode") in AUTO_MODES else "off"
    return {"mode": mode, "last_day": d.get("last_day", ""), "last": d.get("last")}


def _save_auto(**changes) -> dict:
    d = {**auto_settings(), **changes}
    f = _auto_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d), encoding="utf-8")
    return auto_settings()


def set_auto(mode: str) -> dict:
    if mode not in AUTO_MODES:
        raise ValueError("unknown mode")
    return _save_auto(mode=mode)


def auto_due(now: float | None = None) -> bool:
    st = auto_settings()
    lt = time.localtime(time.time() if now is None else now)
    return st["mode"] == "night" and NIGHT[0] <= lt.tm_hour < NIGHT[1] and st["last_day"] != time.strftime("%Y-%m-%d", lt)


def auto_update(busy: bool, before_sync=None) -> dict:
    """One nightly try. ``busy``: jobs are running — try again in a minute. ``before_sync()``: called just before the
    code changes (a snapshot of the lab's settings, updates.py); if it raises, nothing is updated. Returns
    {"restart": bool, ...}."""
    today = time.strftime("%Y-%m-%d")
    if busy:
        return {"restart": False, "waiting": True}

    def done(result: str, ok: bool, restart: bool = False) -> dict:
        _save_auto(last_day=today, last={"at": time.time(), "ok": ok, "result": result})
        return {"restart": restart, "ok": ok, "result": result}

    st = check()
    if not st.get("is_repo"):
        return done("This folder is not a git repository.", False)
    if not st.get("fetch_ok"):
        return done("Couldn't reach GitHub (git fetch failed)", False)
    if not st.get("behind"):
        return done("Already up to date — nothing to do", True)
    if st.get("dirty"):
        return done("Files were changed on this machine — not updated. Undo or commit them first.", False)
    if before_sync is not None:
        try:
            before_sync()
        except Exception as e:
            return done(f"Not updated: the snapshot of the lab's settings failed ({e})", False)
    r = sync()
    if not r["ok"]:
        failed = next((x["name"] for x in r["steps"] if not x["ok"]), "git pull")
        return done(f"The update failed: {failed}", False)
    return done(f"Updated to {r['new']['short']} {r['new']['subject']}", True, bool(r.get("restart")))


# The exit code that asks a supervisor (Docker's restart policy, systemd's Restart=always) for a fresh process.
RESTART_EXIT_CODE = 75


def _on_windows() -> bool:
    return os.name == "nt"


def _restart_now() -> None:
    """Start this server again (same command line), the way this system and installation allow."""
    sys.stdout.flush()
    sys.stderr.flush()
    command = [sys.executable, "-m", "mister_plis", *sys.argv[1:]]
    if os.environ.get("MISTER_PLIS_SUPERVISED") == "1":
        os._exit(RESTART_EXIT_CODE)  # whatever supervises the server starts it again
    elif _on_windows():
        # Windows can't replace a running process: start a new one (it waits for the port, see __main__) and leave.
        subprocess.Popen(command, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        os._exit(0)
    else:
        os.chdir(ROOT)
        os.execv(sys.executable, command)


def schedule_restart(delay: float = 0.8) -> bool:
    """Replace this process with a fresh one (same command line) after ``delay`` seconds. Returns False in --reload
    dev mode. With ``MISTER_PLIS_SUPERVISED=1`` the server exits with :data:`RESTART_EXIT_CODE` instead and its
    supervisor starts it again."""
    if os.environ.get("MISTER_PLIS_DEV_RELOAD"):
        return False

    def _go():
        time.sleep(delay)
        _restart_now()

    threading.Thread(target=_go, daemon=True).start()
    return True
