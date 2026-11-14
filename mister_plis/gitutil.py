"""Running git for the server (reorg P5): the code checkout, and the repositories modules keep (clones of other
GitHub repositories, local histories). One place for the rules every git call follows:

- never wait for a password (``GIT_TERMINAL_PROMPT=0``; ssh in batch mode); messages in English (``LC_ALL=C``);
- a timeout on every call; "git is not installed" / "timed out" as an answer, not an exception;
- no signing of commits, file names as they are (``core.quotepath=off``);
- the repository it runs in counts as safe (``safe.directory``): git otherwise refuses one whose files belong to
  another user — usual in Docker volumes and on network shares. The server only runs git in repositories it made
  itself (its code, its clones, its modules' copies), so it trusts them;
- with ``credentials=True``: the instance's own tokens (mister_plis/credentials.py: one per host, owner or
  repository, set on Settings → Server & updates → GitHub access), then the code checkout's credential helpers (on
  the Mac app, the Keychain), so the server reads and writes the lab's repositories with the lab's tokens.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .errors import ToolError

ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",  # never hang waiting for a password
    "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -o BatchMode=yes"),
    "LC_ALL": "C",
}
for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):  # a git hook's environment must not leak into our calls
    ENV.pop(_k, None)


def run(*args: str, cwd: Path | str, timeout: float = 120, credentials: bool = False, binary: bool = False,
        options: tuple = ("-c", "commit.gpgsign=false", "-c", "core.quotepath=off")) -> tuple[int, str | bytes]:
    """``git <args>`` in ``cwd``: (exit code, output). ``binary``: stdout as bytes (e.g. ``git show :1:file.xlsx``)."""
    cmd = ["git", *options, *_safe(cwd), *(credential_args() if credentials else []), *args]
    try:
        r = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return 127, b"" if binary else "git is not installed"
    except subprocess.TimeoutExpired:
        return 124, b"" if binary else f"git {args[0] if args else ''} timed out after {timeout:.0f}s"
    if binary:
        return r.returncode, r.stdout
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").rstrip("\n")


def _safe(cwd) -> list[str]:
    """``-c safe.directory=<cwd>`` (given on the command line, which git respects for this setting): the folder git runs
    in may belong to another user than the server's (a Docker volume made by root, a NAS)."""
    try:
        folder = Path(cwd).resolve()
    except (OSError, TypeError):
        return []
    return ["-c", f"safe.directory={folder.as_posix()}"]


def checkout_helpers() -> list[str]:
    """The credential helpers git uses for the code checkout (its own, the user's and the system's settings, after the
    last one that clears the list); on the Mac app: ``osxkeychain``."""
    from .config import ROOT

    code, out = run("config", "--get-all", "credential.helper", cwd=ROOT, options=())
    helpers = out.split("\n") if code == 0 and out.strip() else []
    if "" in helpers:
        helpers = helpers[len(helpers) - helpers[::-1].index(""):]
    return [h for h in helpers if h]


def _helper_command(repo_only: bool = False) -> str:
    """The instance's own helper as git runs it (through a shell: quoted, with forward slashes on Windows too)."""
    from . import credentials

    def q(p: Path | str) -> str:
        return '"' + str(Path(p).as_posix() if os.name == "nt" else p).replace('"', '\\"') + '"'

    only = " --repo-only" if repo_only else ""
    return f"!{q(sys.executable)} -I {q(Path(credentials.__file__))} --store {q(credentials.store_path())}{only}"


def credential_args() -> list[str]:
    """Options that give a git call the server's tokens: the instance's own (mister_plis/credentials.py, asked first),
    then the code checkout's helpers (on the Mac app, the Keychain). For a host with a token for one owner or
    repository, git tells the helpers which repository it asks for (``useHttpPath``)."""
    from . import credentials

    args = ["-c", "credential.helper=", "-c", f"credential.helper={_helper_command()}"]
    for h in checkout_helpers():
        args += ["-c", f"credential.helper={h}"]
    for host in credentials.path_hosts():
        args += ["-c", f"credential.https://{host}.useHttpPath=true"]
    return args


def repo_token_args(url: str) -> list[str]:
    """Options that give a git call only a token stored for exactly the repository at ``url`` (a tool source that isn't
    the lab's own: its own token, never the server's), and no other helper; none for an address that isn't https."""
    from . import credentials

    where = credentials.repository(url)
    if not where:
        return ["-c", "credential.helper="]
    return ["-c", "credential.helper=", "-c", f"credential.helper={_helper_command(repo_only=True)}",
            "-c", f"credential.https://{where[0]}.useHttpPath=true"]


# ---- a repository in a folder on this machine (instead of GitHub) ----------------------------------------------

def address(url: str) -> str:
    """A repository address as git should get it: ``~/Lab/inventory`` becomes an absolute path (git doesn't expand
    ``~``); a URL (https://…, git@…:…, file://…) stays as it is."""
    url = (url or "").strip()
    if url.startswith("~"):
        return str(Path(url).expanduser())
    return url


def local_folder(url: str) -> Path | None:
    """The folder when the address is a git repository on this machine (``/path``, ``~/path``, ``file:///path``,
    or ``C:\\path``), else None. Such a folder can be synced like GitHub: fetch from it, push into it."""
    url = address(url)
    if url.startswith("file://"):
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        return Path(url2pathname(urlparse(url).path))  # file:///C:/x → C:\x on Windows
    if url.startswith("/") or (len(url) > 2 and url[1] == ":" and url[2] in "\\/"):
        return Path(url)
    return None


# A folder with its branch checked out refuses a push by default. updateInstead: the push also updates the files
# there, and is refused (nothing changed) if they have edits not committed yet. Set for this push only, so the
# folder's own configuration is left alone.
LOCAL_PUSH = ("--receive-pack", "git -c receive.denyCurrentBranch=updateInstead receive-pack")


def explain_local(out: str, folder: Path) -> str | None:
    """What a git error means for a repository in a folder, in plain words (None: nothing more to say)."""
    low = out.lower()
    if not folder.exists():
        return f"There is no folder {folder} on this computer. Check the path (repo in config.toml), or create the folder and run “git init” in it."
    if "does not appear to be a git repository" in low or "not a git repository" in low:
        return f"The folder {folder} isn't a git repository. Run “git init” in it (or give the folder that has .git inside)."
    if "working directory has unstaged changes" in low or "updateinstead" in low or "would be overwritten" in low \
            or "uncommitted" in low or "index has changes" in low:
        return (f"The folder {folder} has changes nobody has committed yet, so the server didn't touch it. Commit them "
                "there (or undo them), then sync again.")
    if "permission denied" in low or "insufficient permission" in low or "read-only file system" in low:
        return f"The server isn't allowed to write in the folder {folder}. Give the user the server runs as write access to it."
    return None


# ---- checking what a person or a lab file gives as a repository ----------------------------------------------------

_ADDRESS = re.compile(r"^(https?://\S+|ssh://\S+|git@[^\s:]+:\S+|file://\S+|/.*|~.*|[A-Za-z]:[\\/].*)$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def check_address(url) -> str:
    """A repository's address as given (tidied), or ToolError: "" (none), https://…, git@host:…, ssh://…, file://…, or
    a folder on this machine (/…, ~/…). An address with a password or token in it is refused."""
    url = str(url if url is not None else "").strip()
    if not url:
        return ""
    if not _ADDRESS.match(url):
        raise ToolError("Give the repository's address (https://github.com/…/….git) or a folder on this computer (/… or ~/…).")
    if re.match(r"^https?://[^/@]+@", url):
        raise ToolError("Leave the user name and token out of the address: the server uses its own GitHub token.")
    return url


def check_branch(branch) -> str:
    branch = str(branch if branch is not None else "").strip() or "main"
    if not _BRANCH.match(branch) or ".." in branch:
        raise ToolError("Not a branch name.")
    return branch


def remove_clone(folder: Path) -> None:
    """Delete a git clone (one that can be fetched again) if it is there. Git keeps its object files read-only, which
    Windows refuses to delete: those are made writable first."""
    import shutil
    import stat
    import sys

    def _writable_and_again(func, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        except OSError:
            pass

    if folder.exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(folder, onexc=_writable_and_again)
        else:
            shutil.rmtree(folder, onerror=_writable_and_again)


def set_aside(folder: Path) -> Path:
    """Rename a folder that is no longer used to ``<name>.before-<date>`` (never deleted); returns the new name."""
    from datetime import datetime

    stamp = datetime.now().strftime("%Y-%m-%d")
    target, n = folder.with_name(f"{folder.name}.before-{stamp}"), 2
    while target.exists():
        target, n = folder.with_name(f"{folder.name}.before-{stamp}-{n}"), n + 1
    folder.rename(target)
    return target
