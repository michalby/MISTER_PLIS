"""The instance's own tokens for git repositories (Settings → Server & updates → GitHub access; docs/PREP_PLAN.md R3).

Kept in ``<instance>/secrets/git-credentials.toml`` (only this server's user can read it), never in the data folder,
a lab file, a transfer or git. One token per host, owner or repository: the most specific one that matches a
repository is used, so a lab whose code and data belong to different GitHub owners can have a token for each (a
fine-grained GitHub token reaches one owner's repositories only). ``MISTER_PLIS_GIT_TOKEN`` (e.g. a Docker secret)
serves any repository nothing here matches.

Git asks for them through a credential helper (git's own protocol, ``git help credential``):
``python -I mister_plis/credentials.py --store <file> get`` (``-I``: nothing from the folder it runs in, nor this
package's own folder, is imported) — :func:`mister_plis.gitutil.credential_args` adds it to the git
calls that may use the server's tokens. It runs as a plain script (git starts it inside other repositories' folders,
where this package can't be imported), so the part it needs uses the standard library only. The token is never on a
command line or in a log.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import tomllib
from pathlib import Path

ENV_TOKEN = "MISTER_PLIS_GIT_TOKEN"
FILE_NAME = "git-credentials.toml"
HEADER = """\
# Tokens this instance uses to read (and, for a module's repository, write) git repositories.
# The most specific match wins: owner/repo, then owner, then host. Never committed, never in a lab file,
# never in a transfer. Change them on Settings -> Server & updates -> GitHub access.
"""

_lock = threading.Lock()


# ---- reading (also used by the helper, standard library only) ----------------------------------------------------

def _clean(s) -> str:
    return str(s or "").strip().strip("/").lower()


def _read(store: Path) -> list[dict]:
    try:
        entries = tomllib.loads(store.read_text(encoding="utf-8")).get("token", [])
    except (OSError, ValueError):
        return []
    out = []
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and str(e.get("token") or "").strip() and _clean(e.get("host")):
            out.append({"host": _clean(e["host"]), "owner": _clean(e.get("owner")), "repo": _clean(e.get("repo")),
                        "token": str(e["token"]).strip(), "added": e.get("added", "")})
    return out


def _split(path: str) -> tuple[str, str]:
    """"smith-lab/inventory.git" → ("smith-lab", "inventory")."""
    parts = [p for p in str(path or "").strip("/").split("/") if p]
    owner = parts[0].lower() if parts else ""
    repo = parts[1].lower() if len(parts) > 1 else ""
    return owner, repo[:-4] if repo.endswith(".git") else repo


def match(entries: list[dict], host: str, path: str = "") -> dict | None:
    """The most specific entry for a repository: owner and repository, then owner, then the host alone."""
    host = _clean(host)
    owner, repo = _split(path)
    best, rank = None, -1
    for e in entries:
        if e["host"] != host:
            continue
        if e["repo"] and not (e["owner"] == owner and e["repo"] == repo):
            continue
        if e["owner"] and e["owner"] != owner:
            continue
        r = 2 if e["repo"] else 1 if e["owner"] else 0
        if r > rank:
            best, rank = e, r
    return best


def token_from(store: Path, host: str, path: str = "", repo_only: bool = False) -> str | None:
    """The token for a repository at ``host`` (``path`` like ``smith-lab/inventory.git``): the most specific stored
    one, else ``MISTER_PLIS_GIT_TOKEN``, else None. ``repo_only``: only a token stored for exactly this repository
    (a tool source that isn't the lab's own gets its own token, never the server's)."""
    e = match(_read(store), host, path)
    if repo_only:
        return e["token"] if e and e["repo"] else None
    if e:
        return e["token"]
    return os.environ.get(ENV_TOKEN, "").strip() or None


def helper(argv: list[str], stdin=sys.stdin, stdout=sys.stdout) -> int:
    """git's credential helper: ``--store <file> [--repo-only] get|store|erase``. ``get`` reads ``key=value`` lines
    (protocol, host, path…) and answers with a username and password when a token matches; else says nothing, and git
    asks the next helper (on the Mac app, the Keychain). ``--repo-only``: only a token stored for that one repository.
    ``store`` and ``erase`` do nothing: tokens are changed on the Settings page."""
    store, action, repo_only = None, "", False
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--store" and args:
            store = Path(args.pop(0))
        elif a == "--repo-only":
            repo_only = True
        else:
            action = a
    asked = {}
    for line in stdin.read().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            asked[k.strip()] = v.strip()
    if action != "get" or asked.get("protocol") not in ("https", "http") or not asked.get("host"):
        return 0
    if store:
        token = token_from(store, asked["host"], asked.get("path", ""), repo_only)
    else:
        token = None if repo_only else os.environ.get(ENV_TOKEN, "").strip()
    if token:
        if hasattr(stdout, "reconfigure"):
            stdout.reconfigure(newline="\n")  # git reads plain lines, on Windows too
        stdout.write(f"username=x-access-token\npassword={token}\n")
    return 0


# ---- the instance's store (the server) ---------------------------------------------------------------------------

def store_path() -> Path:
    from .config import settings

    return settings.secrets_path / FILE_NAME


def _toml_str(s: str) -> str:
    return json.dumps(str(s), ensure_ascii=False)  # a JSON string is a TOML basic string


def _write(store: Path, entries: list[dict]) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(store.parent, 0o700)
    except OSError:
        pass
    lines = [HEADER]
    for e in entries:
        lines += ["[[token]]"] + [f"{k} = {_toml_str(e.get(k, ''))}" for k in ("host", "owner", "repo", "token", "added")]
        lines.append("")
    tmp = store.with_name(store.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    os.replace(tmp, store)
    try:
        os.chmod(store, 0o600)
    except OSError:
        pass


def _check(host: str, owner: str, repo: str) -> tuple[str, str, str]:
    from .errors import ToolError

    host, owner, repo = _clean(host) or "github.com", _clean(owner), _clean(repo)
    if repo.endswith(".git"):
        repo = repo[:-4]
    ok = all(c.isalnum() or c in "-_." for c in owner + repo) and all(c.isalnum() or c in "-." for c in host)
    if not ok or "/" in owner or "/" in repo:
        raise ToolError("Give the host (e.g. github.com), the owner (a user or an organisation) and, if you like, one "
                        "repository: names only, not an address.")
    if repo and not owner:
        raise ToolError("A token for one repository needs its owner too.")
    return host, owner, repo


def set_token(host: str, owner: str, repo: str, token: str) -> None:
    """Add a token, or replace the one for the same host, owner and repository."""
    from .errors import ToolError

    host, owner, repo = _check(host, owner, repo)
    token = str(token or "").strip()
    if not token or any(c.isspace() for c in token) or len(token) > 1000:
        raise ToolError("Paste the token (one line, no spaces).")
    with _lock:
        store = store_path()
        entries = [e for e in _read(store) if (e["host"], e["owner"], e["repo"]) != (host, owner, repo)]
        entries.append({"host": host, "owner": owner, "repo": repo, "token": token,
                        "added": time.strftime("%Y-%m-%d %H:%M")})
        _write(store, entries)


def remove_token(host: str, owner: str, repo: str) -> bool:
    host, owner, repo = _check(host, owner, repo)
    with _lock:
        store = store_path()
        entries = _read(store)
        kept = [e for e in entries if (e["host"], e["owner"], e["repo"]) != (host, owner, repo)]
        if len(kept) == len(entries):
            return False
        _write(store, kept)
        return True


def list_tokens() -> list[dict]:
    """The stored tokens as the page shows them: never the token, only its last four characters."""
    return [{"host": e["host"], "owner": e["owner"], "repo": e["repo"], "last4": e["token"][-4:], "added": e["added"]}
            for e in _read(store_path())]


def repository(url: str) -> tuple[str, str, str] | None:
    """(host, owner, repo) of an https address like ``https://github.com/smith-lab/tools.git``, else None."""
    from urllib.parse import urlparse

    u = urlparse(str(url or "").strip())
    owner, repo = _split(u.path)
    if u.scheme != "https" or not u.hostname or not owner or not repo or len([x for x in u.path.split("/") if x]) != 2:
        return None
    return u.hostname.lower(), owner, repo


def token_entry(host: str, owner: str, repo: str) -> dict | None:
    """The token stored for exactly this repository (the whole entry), else None."""
    host, owner, repo = _clean(host), _clean(owner), _clean(repo)
    return next((e for e in _read(store_path()) if (e["host"], e["owner"], e["repo"]) == (host, owner, repo)), None)


def token_for(host: str, path: str = "") -> str | None:
    return token_from(store_path(), host, path)


def path_hosts() -> list[str]:
    """Hosts with a token for one owner or repository: git must tell the helper which repository it asks for
    (``credential.<host>.useHttpPath``). Only for those hosts: the Mac's Keychain looks items up by path when it is on,
    and its token has none."""
    return sorted({e["host"] for e in _read(store_path()) if e["owner"]})


def describe() -> dict:
    """What the GitHub access panel shows besides the list: other places access comes from."""
    from . import gitutil

    return {"tokens": list_tokens(), "env": bool(os.environ.get(ENV_TOKEN, "").strip()),
            "checkout_helpers": gitutil.checkout_helpers(), "store": str(store_path())}


if __name__ == "__main__":
    sys.exit(helper(sys.argv[1:]))
