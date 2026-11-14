"""A tool catalogue (docs/PREP_PLAN.md R7): a list of tool sources labs have published, to browse on Settings → Tools and
add from. Its address is the lab's choice (``[tools] catalogue``); its format is in docs/FORMATS.md §16.

Adding a source from it is the same as adding one by hand (``ToolSources.add``): a source that isn't the lab's own is
fetched without the server's token, pinned, and left switched off until someone has read what it contains.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request

from . import __version__
from .errors import ToolError

FORMAT = "mister-plis-tool-catalogue"
VERSION = 1
MAX_BYTES = 1_000_000
NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def read(address: str, max_age: float = 3600) -> dict:
    """The catalogue at an https:// (or file://) address: 10 s, at most 1 MB, kept for an hour. Raises ToolError."""
    address = (address or "").strip()
    if not address.startswith(("https://", "file://")):
        raise ToolError("A catalogue's address starts with https://.")
    with _lock:
        hit = _cache.get(address)
        if hit and time.time() - hit[0] < max_age:
            return hit[1]
    try:
        req = urllib.request.Request(address, headers={"User-Agent": f"MISTER PLIS {__version__}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read(MAX_BYTES + 1)
    except (OSError, ValueError) as e:
        raise ToolError(f"Couldn't read the tool catalogue: {e}") from None
    if len(raw) > MAX_BYTES:
        raise ToolError("The tool catalogue is too large.")
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ToolError("The tool catalogue isn't valid JSON.") from None
    if not isinstance(d, dict) or d.get("format") != FORMAT or not isinstance(d.get("sources"), list):
        raise ToolError("That isn't a MISTER PLIS tool catalogue.")
    if int(d.get("format_version") or 0) > VERSION:
        raise ToolError("The tool catalogue is newer than this MISTER PLIS reads.")
    with _lock:
        _cache[address] = (time.time(), d)
    return d


def _text(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _homepage(v) -> str:
    """A source's homepage, if it is an http(s):// address (a catalogue is someone else's text: never "javascript:")."""
    from .serving import web_link

    v = _text(v, 300)
    return v if web_link(v) else ""


def entries(d: dict) -> list[dict]:
    """The catalogue's sources, tidied; entries that can't be added (no https address, a bad name) are left out."""
    out, seen = [], set()
    for s in d.get("sources") or []:
        if not isinstance(s, dict):
            continue
        name, url, branch = _text(s.get("name"), 31), _text(s.get("url"), 300), _text(s.get("branch") or "main", 200)
        if not NAME.match(name) or not url.startswith("https://") or not BRANCH.match(branch) or name in seen:
            continue
        seen.add(name)
        tags = s.get("tags") if isinstance(s.get("tags"), list) else []
        out.append({"name": name, "url": url, "branch": branch, "title": _text(s.get("title"), 80) or name,
                    "description": _text(s.get("description"), 600), "maintainer": _text(s.get("maintainer"), 120),
                    "homepage": _homepage(s.get("homepage")), "license": _text(s.get("license"), 60),
                    "requires_toolkit": _text(s.get("requires_toolkit"), 40),
                    "tags": [_text(t, 30) for t in tags if isinstance(t, str)][:12]})
    return out


def browse(address: str, sources) -> list[dict]:
    """The catalogue for Settings → Tools → Browse: each entry with whether this lab has it already (by name or address)
    and whether this MISTER PLIS's toolkit fits what it asks for."""
    from .toolkit import TOOLKIT_VERSION
    from .toolsources import toolkit_ok

    have = sources.sources()
    names = {s["name"] for s in have} | {b["name"] for b in sources.bundled()}
    urls = {s["url"].rstrip("/").removesuffix(".git") for s in have}
    return [{**e, "added": e["name"] in names or e["url"].rstrip("/").removesuffix(".git") in urls,
             "fits": toolkit_ok(e["requires_toolkit"], TOOLKIT_VERSION)} for e in entries(read(address))]


def add(address: str, name: str, sources) -> dict:
    """Add a source from the catalogue: as ToolSources.add does for one that isn't the lab's own (pinned, switched off)."""
    e = next((x for x in entries(read(address)) if x["name"] == name), None)
    if e is None:
        raise ToolError("The catalogue has no such tool source.")
    return sources.add(e["url"], e["name"], e["branch"], trusted=False)
