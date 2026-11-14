"""How this instance is updated (docs/PREP_PLAN.md R5): the update "channel" seam, the release feed, and the snapshot of
the lab's settings made before every update.

* :class:`GitChannel` — a git checkout or the Mac app: today's updates from GitHub (``updater``, unchanged).
* :class:`DockerChannel` — a Docker image: updated with a new image; reads the release feed to say what is newer.
* :class:`ReleaseChannel` — a package install: reads the feed; installing releases beside each other is the final
  version's (FINAL_VERSION.md §3, "designed, not built").

:func:`channel` picks one by how the instance was installed (``install.kind()``). The feed's format is in
docs/FORMATS.md ("Release feed"); ``[updates] channel`` and ``feed`` come from the lab file or Settings and are kept in
``auto_update.json``.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Protocol

from . import __version__, updater
from .config import settings
from .errors import ToolError

FEED_FORMAT = "mister-plis-release-feed"
FEED_VERSION = 1
FEED_MAX = 1_000_000
CHANNELS = ("beta", "stable")
KEEP_SNAPSHOTS = 5

GIT_HOW = "Updated from GitHub with git: Sync with git, Run another branch, or by itself at night."
RELEASE_HOW = "Installed from a release: updating from the release feed by itself isn't available yet — install the newer version by hand."


# ---- the release feed ------------------------------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def read_feed(address: str, max_age: float = 3600) -> dict:
    """The release feed at an https:// or file:// address (10 s, at most 1 MB, kept for an hour). Raises ToolError."""
    address = (address or "").strip()
    if not address:
        raise ToolError("No release feed is set.")
    if not address.startswith(("https://", "file://")):
        raise ToolError("A release feed's address starts with https://.")
    with _cache_lock:
        hit = _cache.get(address)
        if hit and time.time() - hit[0] < max_age:
            return hit[1]
    try:
        req = urllib.request.Request(address, headers={"User-Agent": f"MISTER PLIS {__version__}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read(FEED_MAX + 1)
    except (OSError, ValueError) as e:
        raise ToolError(f"Couldn't read the release feed: {e}") from None
    if len(raw) > FEED_MAX:
        raise ToolError("The release feed is too large.")
    try:
        feed = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ToolError("The release feed isn't valid JSON.") from None
    if not isinstance(feed, dict) or feed.get("format") != FEED_FORMAT or not isinstance(feed.get("releases"), list):
        raise ToolError("That isn't a MISTER PLIS release feed.")
    if int(feed.get("format_version") or 0) > FEED_VERSION:
        raise ToolError("The release feed is newer than this MISTER PLIS reads.")
    feed["signed"] = _check_signature(address, raw)
    with _cache_lock:
        _cache[address] = (time.time(), feed)
    return feed


def _check_signature(address: str, raw: bytes) -> bool:
    """Whether the feed is signed by a release key (releasekeys.py). With release keys in the code, a feed without a
    good signature is refused (ToolError); with none, it is read unsigned (False)."""
    import shutil
    import subprocess
    import tempfile

    from .releasekeys import NAMESPACE, SIGNERS

    keys = [k.strip() for k in SIGNERS if k.strip()]
    if not keys:
        return False
    try:
        req = urllib.request.Request(address + ".sig", headers={"User-Agent": f"MISTER PLIS {__version__}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            sig = r.read(64 * 1024)
    except (OSError, ValueError):
        raise ToolError("The release feed isn't signed (no .sig next to it), so it wasn't used.") from None
    exe = shutil.which("ssh-keygen")
    if not exe:
        raise ToolError("ssh-keygen isn't installed here, so the release feed's signature can't be checked.")
    with tempfile.TemporaryDirectory() as tmp:
        signers, sig_file = Path(tmp) / "allowed_signers", Path(tmp) / "feed.sig"
        signers.write_text("".join(f'release namespaces="{NAMESPACE}" {k}\n' for k in keys), encoding="utf-8")
        sig_file.write_bytes(sig)
        try:
            r = subprocess.run([exe, "-Y", "verify", "-f", str(signers), "-I", "release", "-n", NAMESPACE, "-s", str(sig_file)],
                               input=raw, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            r = None
    if r is None or r.returncode != 0:
        raise ToolError("The release feed's signature doesn't match a MISTER PLIS release key, so it wasn't used.")
    return True


def _version_key(v: str):
    from packaging.version import InvalidVersion, Version

    try:
        return Version(str(v))
    except InvalidVersion:
        return Version("0")


def newer_releases(feed: dict, current: str = __version__) -> list[dict]:
    """The feed's releases newer than ``current``, newest first, each saying whether this version could go back to
    ``current`` after it (its formats are all readable here)."""
    from .formats import can_read

    out = []
    for r in feed.get("releases") or []:
        if isinstance(r, dict) and _version_key(r.get("version", "")) > _version_key(current):
            ok, too_new = can_read(r.get("writes") or {})
            out.append({**r, "can_go_back_here": ok, "formats_too_new": too_new})
    return sorted(out, key=lambda r: _version_key(r["version"]), reverse=True)


def make_feed(channel: str, releases: list[dict]) -> dict:
    """A release feed (scripts/release.sh writes one per channel)."""
    if channel not in CHANNELS:
        raise ValueError(f"channel should be one of {CHANNELS}")
    return {"format": FEED_FORMAT, "format_version": FEED_VERSION, "channel": channel,
            "releases": sorted(releases, key=lambda r: _version_key(r.get("version", "")), reverse=True)}


# ---- [updates] channel and feed: stored with the nightly update's settings --------------------------------------------

def update_settings() -> dict:
    """``{"channel": "beta"|"stable", "feed": str}`` (auto_update.json; older files lack them)."""
    try:
        d = json.loads((settings.data_path / "auto_update.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    ch = d.get("channel") if d.get("channel") in CHANNELS else "beta"
    feed = d.get("feed") if isinstance(d.get("feed"), str) else ""
    return {"channel": ch, "feed": feed}


def set_update_settings(channel: str | None = None, feed: str | None = None) -> dict:
    if channel is not None and channel not in CHANNELS:
        raise ToolError("Choose the beta or the stable channel.")
    if feed is not None:
        feed = feed.strip()
        if feed and not feed.startswith(("https://", "file://")):
            raise ToolError("A release feed's address starts with https://.")
    f = settings.data_path / "auto_update.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    if channel is not None:
        d["channel"] = channel
    if feed is not None:
        d["feed"] = feed
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d), encoding="utf-8")
    return update_settings()


# ---- snapshots of the lab's settings ---------------------------------------------------------------------------------

def snapshots_path() -> Path:
    """Next to the data folder (the instance's folder, ``<home>/snapshots``, unless data_dir is elsewhere)."""
    return settings.data_path.parent / "snapshots"


def make_snapshot(reason: str, module_storage: list[str] | None = None) -> dict:
    """Copy the lab's settings (transfer.export, settings only) into ``<instance>/snapshots/<date> <reason>/``, and keep
    the newest KEEP_SNAPSHOTS. Returns {"path", "files", "bytes"}."""
    from . import transfer

    root = snapshots_path()
    root.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now():%Y-%m-%d %H%M%S} {reason}".strip()
    name = "".join(c if c.isalnum() or c in " ._()-" else "_" for c in name)[:120]
    r = transfer.export(str(root), settings.data_path, settings.storage_path, module_storage or [], settings_only=True,
                        name=name, version=__version__, commit=updater.RUNNING.get("commit", ""))
    for old in list_snapshots()[KEEP_SNAPSHOTS:]:  # copies of settings: the oldest are let go
        shutil.rmtree(old["path"], ignore_errors=True)
    return r


def list_snapshots() -> list[dict]:
    """The snapshots, newest first: {"name", "path", "created", "version", "files"}."""
    root = snapshots_path()
    out = []
    for d in root.iterdir() if root.is_dir() else []:
        try:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(m, dict) and m.get("kind") == "settings":
            out.append({"name": d.name, "path": str(d), "created": m.get("created") or 0,
                        "version": (m.get("from") or {}).get("version", ""), "files": len(m.get("files") or {})})
    return sorted(out, key=lambda s: s["created"], reverse=True)


def restore_snapshot(name: str, by: str = "") -> dict:
    """Bring a snapshot's settings back (transfer.bring_in_settings); the server must restart to read them."""
    from . import transfer

    match = next((s for s in list_snapshots() if s["name"] == name), None)
    if match is None:
        raise ToolError("There is no such snapshot.")
    return transfer.bring_in_settings(match["path"], settings.data_path, by)


# ---- the channels ----------------------------------------------------------------------------------------------------

class Channel(Protocol):
    name: str

    def status(self) -> dict:
        """{"name", "current": {version, commit}, "available": [...], "can_update", "can_go_back", "how", "notes"}"""

    def update(self, to: str = "") -> dict:
        """A step log like updater.sync(); the caller restarts."""

    def go_back(self, to: str) -> dict:
        """Raises ToolError when not possible."""


class _FeedChannel:
    name = "release"
    how = RELEASE_HOW

    def status(self) -> dict:
        cfg = update_settings()
        available, notes, signed = [], "", None
        if cfg["feed"]:
            try:
                feed = read_feed(cfg["feed"])
                available, signed = newer_releases(feed), bool(feed.get("signed"))
            except ToolError as e:
                notes = str(e)
        return {"name": self.name, "channel": cfg["channel"], "feed": cfg["feed"], "signed": signed,
                "current": {"version": __version__, "commit": updater.RUNNING.get("commit", "")},
                "available": available, "can_update": False, "can_go_back": False, "how": self.how, "notes": notes}

    def update(self, to: str = "") -> dict:
        raise ToolError(self.how)

    def go_back(self, to: str) -> dict:
        raise ToolError(self.how)


class DockerChannel(_FeedChannel):
    name = "docker"
    how = updater.HOW["docker"]


class ReleaseChannel(_FeedChannel):
    name = "release"
    how = RELEASE_HOW


class GitChannel:
    """Today's updates from GitHub — :mod:`mister_plis.updater`, whose functions and routes stay as they are. An update
    makes a snapshot of the lab's settings first."""

    name = "git"
    how = GIT_HOW

    def __init__(self, module_storage: list[str] | None = None):
        self.module_storage = module_storage or []

    def status(self) -> dict:
        st = updater.status()
        return {"name": self.name, **update_settings(),
                "current": {"version": __version__, "commit": st.get("running", {}).get("commit", "")},
                "available": [], "can_update": bool(st.get("is_repo")), "can_go_back": False, "how": self.how,
                "notes": "", "git": st}

    def snapshot(self, reason: str = "") -> dict:
        return make_snapshot(reason or f"before an update from {__version__}", self.module_storage)

    def update(self, to: str = "") -> dict:
        snap = self.snapshot()
        r = updater.switch(to) if to else updater.sync()
        return {**r, "snapshot": snap["path"]}

    def go_back(self, to: str) -> dict:
        raise ToolError("Going back to an earlier version comes with releases; with git, Run another branch instead.")


def channel(module_storage: list[str] | None = None) -> Channel:
    """The channel for how this instance was installed."""
    from . import install

    kind = install.kind()
    if kind == "docker":
        return DockerChannel()
    if kind == "package":
        return ReleaseChannel()
    return GitChannel(module_storage)
