"""Tool sources: the git repositories tools come from (reorg phase P7, decisions D1–D2).

A lab's tools live in their own repository (e.g. ``smith-lab/lab-tools``), given when the lab is set up (a lab
file's ``[[tool_sources]]``, or the setup page); more repositories — someone else's public tools, say — can be added on
Settings → Tools. Each source is a clone in
``<data>/tool-sources/<name>/`` with a manifest ``mister-plis-tools.toml``::

    [source]
    name = "lab"                       # short id: folder name, import package mp_tools_<name>, shown in the UI
    title = "Lab tools"
    requires_toolkit = ">=1,<2"        # the toolkit API versions it works with (mister_plis.toolkit.TOOLKIT_API)
    requirements = "requirements.txt"  # extra packages its tools need
    locale = { pl = "locale/pl.py" }

The list of sources is ``<data>/tool_sources.json``. A source is updated like the base (fast-forward only, never
over local edits), can follow another branch, and can be **pinned** to a commit. Tools are Python code running inside
the server with access to everything, so a source that isn't ``trusted`` (anything but the lab's own) is added
**disabled and pinned** to the commit shown when it was added; enabling it is a separate step, and moving its pin
shows the incoming commits and changed files first. Foreign repositories never get the server's GitHub token; a private
one gets a token of its own, pasted when it is added and used for that repository only.

Folders on this machine can be loaded too (``tool_folders`` in config.toml): a working copy of a tools repository while
someone writes tools — it stands in for the source of the same name — or the tests' fixture tools. With no source and
no folder, the server runs and says there are no tools yet.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

from . import credentials, gitutil
from .config import ROOT, settings
from .errors import ToolError

MANIFEST = "mister-plis-tools.toml"
NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def _version(v) -> tuple[int, int]:
    major, _, minor = str(v).partition(".")
    return int(major), int(minor or 0)


def toolkit_ok(spec: str, version) -> bool:
    """``requires_toolkit = ">=1,<2"`` (or "1", "==1", ">=1.1,<2") against this base's toolkit version
    (``TOOLKIT_VERSION``, e.g. "1.1"; a plain number is read as "<n>.0"). A bare major number in "==" / "<=" / ">"
    means that API as a whole: "==1" and "<=1" are true for 1.1, ">1" is not."""
    spec = str(spec or "").strip()
    if not spec:
        return True
    have = _version(version)
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(>=|<=|==|>|<)?\s*(\d+)(?:\.(\d+))?\s*", part)
        if not m:
            return False
        op = m.group(1) or "=="
        want = (int(m.group(2)), int(m.group(3) or 0))
        a = have if m.group(3) is not None else (have[0], 0)
        if op in ("<", ">="):  # a bare "<2" means below 2.0; ">=1" means 1.0 or later
            a = have
        if not {"<": a < want, "<=": a <= want, ">": a > want, ">=": a >= want, "==": a == want}[op]:
            return False
    return True


def read_manifest(folder: Path) -> dict:
    """The ``[source]`` table of a source's manifest (empty when there is none)."""
    try:
        d = tomllib.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    src = d.get("source") if isinstance(d.get("source"), dict) else {}
    return src


# Tool sources that come with MISTER PLIS (docs/PREP_PLAN.md R7): bundled-tools/<name>/, as bundled-tools.toml lists
# them — never committed here. A release brings them (scripts/release.sh); a server running from a git checkout fetches
# them itself (ToolSources.ensure_bundled), at the tag listed.
BUNDLED_DIR = ROOT / "bundled-tools"
BUNDLED_LIST = ROOT / "bundled-tools.toml"
BUNDLED_MARK = ".bundled.json"  # in each bundled source's folder: {"url", "tag", "commit"} it was fetched at
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def bundled_list(path: Path | None = None) -> list[dict]:
    """The sources bundled-tools.toml lists: [{name, url, tag, commit}] (commit "" when not given). An entry that isn't
    a name, an https:// address and a tag is left out."""
    try:
        listed = tomllib.loads((path or BUNDLED_LIST).read_text(encoding="utf-8")).get("source", [])
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out = []
    for s in listed if isinstance(listed, list) else []:
        if not isinstance(s, dict):
            continue
        name, url, tag, commit = (str(s.get(k) or "").strip() for k in ("name", "url", "tag", "commit"))
        if NAME.match(name) and url.startswith("https://") and TAG.match(tag) and (not commit or COMMIT.match(commit)):
            out.append({"name": name, "url": url, "tag": tag, "commit": commit})
    return out


class ToolSources:
    def __init__(self, data_path: Path, local_paths: list[Path] | None = None, bundled_root: Path | None = None):
        self.local_paths = list(local_paths or [])
        self.bundled_root = bundled_root or BUNDLED_DIR
        self.file = data_path / "tool_sources.json"
        self.root = data_path / "tool-sources"
        self.packages_root = data_path / "tool-packages"  # each source's packages, beside the app's own (R6)
        self.lock = threading.RLock()
        self.errors: dict[str, str] = {}
        self.pip_extra: list[str] = []  # extra pip arguments (tests: --no-index)

    # ---- the list ----
    def _stored(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return d if isinstance(d, dict) else {}

    def sources(self) -> list[dict]:
        d = self._stored()
        items = d.get("sources") if d else None
        if items is None:  # none yet: they come from the lab's setup (a lab file, the setup page) or Settings → Tools
            items = []
        out = []
        for s in items if isinstance(items, list) else []:
            if isinstance(s, dict) and NAME.match(str(s.get("name") or "")) and s.get("url"):
                out.append({"branch": "main", "enabled": True, "pinned": None, "trusted": False, **s})
        return out

    def _save(self, items: list[dict] | None = None, **other) -> None:
        """Write the list (and ``bundled_off``, ``catalogue``: kept as they are unless given)."""
        with self.lock:
            d = self._stored()
            d = {k: v for k, v in d.items() if k in ("bundled_off", "catalogue")}
            d = {"sources": items if items is not None else self.sources(), **d, **other}
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.file)

    # ---- the tool sources that come with MISTER PLIS (bundled-tools/) ----
    def bundled(self) -> list[dict]:
        """{name, path, manifest} for each bundled source (a folder with a manifest)."""
        out = []
        root = self.bundled_root
        for path in sorted(root.iterdir()) if root.is_dir() else []:
            if path.is_dir() and (path / MANIFEST).is_file() and NAME.match(path.name):
                man = read_manifest(path)
                out.append({"name": str(man.get("name") or path.name) if NAME.match(str(man.get("name") or "")) else path.name,
                            "path": path, "manifest": man})
        return out

    def ensure_bundled(self, listed: list[dict] | None = None, timeout: float = 300) -> list[str]:
        """Fetch each source bundled-tools.toml lists that this server doesn't have at the listed tag (a server running
        from a git checkout; after an update that lists a newer tag) — by its commit when one is listed, else by the
        tag. A copy a release brought (no mark) is left as it
        is. Fetched into a new folder, checked (its manifest, the commit when listed), then swapped in; the folder it
        replaces is kept as ``<name>.previous`` until the next swap. Errors are kept for the page. Returns the names
        fetched."""
        import shutil

        fetched = []
        for s in bundled_list() if listed is None else listed:
            dest = self.bundled_root / s["name"]
            mark = dest / BUNDLED_MARK
            if dest.exists() and not mark.is_file():
                continue  # brought by a release
            try:
                have = json.loads(mark.read_text(encoding="utf-8")) if mark.is_file() else {}
            except (OSError, ValueError):
                have = {}
            if have.get("url") == s["url"] and have.get("tag") == s["tag"] and (not s.get("commit") or have.get("commit") == s["commit"]):
                continue
            part = self.bundled_root / f".{s['name']}.partial"
            try:
                shutil.rmtree(part, ignore_errors=True)
                self.bundled_root.mkdir(parents=True, exist_ok=True)
                if s.get("commit"):  # the commit is the pin (a tag can be moved; the tag is then only a label)
                    part.mkdir(parents=True)
                    for args in (("init", "--quiet"), ("remote", "add", "origin", s["url"]),
                                 ("fetch", "--quiet", "--depth", "1", "origin", s["commit"]), ("checkout", "--quiet", "FETCH_HEAD")):
                        code, out = gitutil.run(*args, cwd=part, timeout=timeout, credentials=False)
                        if code != 0:
                            break
                else:
                    code, out = gitutil.run("clone", "--quiet", "--depth", "1", "--branch", s["tag"], s["url"], str(part),
                                            cwd=self.bundled_root, timeout=timeout, credentials=False)
                if code != 0:
                    raise ToolError(f"Couldn't fetch {s['url']} at {s['tag']}: {out.strip()[-300:]}")
                code, head = gitutil.run("rev-parse", "HEAD", cwd=part, timeout=30, credentials=False)
                head = head.strip()
                if s.get("commit") and head != s["commit"]:
                    raise ToolError(f"{s['url']} at {s['tag']} is commit {head[:12]}, not the {s['commit'][:12]} listed: not used.")
                if not (part / MANIFEST).is_file():
                    raise ToolError(f"{s['url']} at {s['tag']} has no {MANIFEST}: it isn't a tool source.")
                shutil.rmtree(part / ".git", ignore_errors=True)
                (part / BUNDLED_MARK).write_text(json.dumps({"url": s["url"], "tag": s["tag"], "commit": head}), encoding="utf-8")
                if dest.exists():
                    previous = self.bundled_root / f"{s['name']}.previous"
                    shutil.rmtree(previous, ignore_errors=True)
                    dest.rename(previous)
                part.rename(dest)
                self.errors.pop(s["name"], None)
                fetched.append(s["name"])
            except (ToolError, OSError) as e:
                shutil.rmtree(part, ignore_errors=True)
                self.errors[s["name"]] = str(e)
        return fetched

    def bundled_tag(self, name: str) -> str:
        """The tag a fetched bundled source is at ("" for one a release brought)."""
        try:
            return str(json.loads((self.bundled_root / name / BUNDLED_MARK).read_text(encoding="utf-8")).get("tag") or "")
        except (OSError, ValueError):
            return ""

    def bundled_off(self) -> list[str]:
        off = self._stored().get("bundled_off")
        return [str(x) for x in off if isinstance(x, str)] if isinstance(off, list) else []

    def set_bundled(self, name: str, on: bool) -> dict:
        if name not in {b["name"] for b in self.bundled()} and on:
            raise ToolError("There is no such tool source.")
        off = [x for x in self.bundled_off() if x != name] + ([] if on else [name])
        self._save(bundled_off=sorted(set(off)))
        return {"name": name, "enabled": on, "bundled": True}

    def set_bundled_off(self, names: list[str]) -> list[str]:
        """The lab file's ``[tools] bundled_off``: which sources that come with MISTER PLIS are switched off."""
        self._save(bundled_off=sorted({str(n) for n in names}))
        return self.bundled_off()

    def catalogue(self) -> str:
        """The address of the tool catalogue this lab browses (``[tools] catalogue``), "" for none."""
        c = self._stored().get("catalogue")
        return c if isinstance(c, str) else ""

    def set_catalogue(self, address: str) -> str:
        address = str(address or "").strip()
        if address and not address.startswith(("https://", "file://")):
            raise ToolError("A catalogue's address starts with https://.")
        self._save(catalogue=address)
        return self.catalogue()

    def get(self, name: str) -> dict:
        s = next((s for s in self.sources() if s["name"] == name), None)
        if not s:
            raise ToolError("There is no such tool source.")
        return s

    def _update(self, name: str, **changes) -> dict:
        with self.lock:
            items = self.sources()
            for s in items:
                if s["name"] == name:
                    s.update(changes)
            self._save(items)
        return self.get(name)

    def folder(self, name: str) -> Path:
        return self.root / name

    def cloned(self, name: str) -> bool:
        return (self.folder(name) / ".git").is_dir()

    def git(self, s: dict, *args, cwd: Path | None = None, timeout: float = 300):
        # a foreign repository never gets the server's token: only one stored for exactly that repository (pasted when
        # it was added), no other credential helper
        opts = ("-c", "commit.gpgsign=false", "-c", "core.quotepath=off") + \
            (() if s.get("trusted") else tuple(gitutil.repo_token_args(s.get("url", ""))))
        return gitutil.run(*args, cwd=cwd or self.folder(s["name"]), timeout=timeout, credentials=bool(s.get("trusted")), options=opts)

    # ---- what the registry loads ----
    def local_folders(self) -> list[dict]:
        """The ``tool_folders`` of this machine: {name, path, manifest}. The name is the manifest's (else the folder's)."""
        out = []
        for path in self.local_paths:
            man = read_manifest(path)
            name = str(man.get("name") or "") or re.sub(r"[^a-z0-9_]+", "_", path.name.lower()).strip("_") or "local"
            out.append({"name": name, "path": path, "manifest": man})
        return out

    def folders(self) -> list[dict]:
        """The tool folders to load, in order: this machine's ``tool_folders``, then the enabled and fetched sources (a
        source with the same name as a local folder is left out: the folder is a working copy of it). Each: {name, path,
        url, commit, manifest, error}."""
        from .toolkit import TOOLKIT_VERSION

        def entry(name, path, url, commit, man, local=False):
            error = "" if toolkit_ok(man.get("requires_toolkit", ""), TOOLKIT_VERSION) else \
                f"needs toolkit {man.get('requires_toolkit')} — this MISTER PLIS has {TOOLKIT_VERSION}"
            if not path.is_dir():
                error = f"the folder {path} isn't there"
            return {"name": name, "path": path, "url": url, "commit": commit, "manifest": man, "error": error, "local": local}

        out = []
        for f in self.local_folders():
            code, commit = gitutil.run("rev-parse", "HEAD", cwd=f["path"], timeout=10) if (f["path"] / ".git").exists() else (1, "")
            out.append(entry(f["name"], f["path"], str(f["path"]), commit.strip() if code == 0 else "", f["manifest"], local=True))
        local = {f["name"] for f in out}
        for s in self.sources():
            if not s.get("enabled") or not self.cloned(s["name"]) or s["name"] in local:
                continue
            path = self.folder(s["name"])
            code, commit = self.git(s, "rev-parse", "HEAD")
            out.append({**entry(s["name"], path, s["url"], commit.strip() if code == 0 else "", read_manifest(path)),
                        "packages": self.packages_path(s["name"])})
        # last, the sources that come with MISTER PLIS — unless switched off, or a folder or clone of the same name
        # stands in for one
        taken = local | {s["name"] for s in self.sources()}
        off = set(self.bundled_off())
        for b in self.bundled():
            if b["name"] not in taken and b["name"] not in off:
                out.append({**entry(b["name"], b["path"], str(b["path"]), _app_version(), b["manifest"]), "bundled": True})
        return out

    # ---- status ----
    def status(self) -> list[dict]:
        local = self.local_folders()
        names = {f["name"] for f in local}
        out = [{"name": f["name"], "url": str(f["path"]), "local": True, "enabled": True, "cloned": True, "trusted": True,
                "manifest": f["manifest"], "error": "" if f["path"].is_dir() else f"the folder {f['path']} isn't there"}
               for f in local]
        for s in self.sources():
            d = {**s, "cloned": self.cloned(s["name"]), "error": self.errors.get(s["name"], ""), "head": None, "branch_here": "",
                 "manifest": {}, "behind": 0, "dirty": [], "replaced_by_local": s["name"] in names}
            if d["cloned"]:
                code, head = self.git(s, "log", "-1", "--format=%H%x1f%h%x1f%cI%x1f%s")
                if code == 0 and head:
                    full, short, date, subject = head.split("\x1f", 3)
                    d["head"] = {"commit": full, "short": short, "date": date, "subject": subject}
                d["branch_here"] = self.git(s, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()
                d["manifest"] = read_manifest(self.folder(s["name"]))
                c, out_ = self.git(s, "rev-list", "--count", f"HEAD..origin/{s['branch']}")
                d["behind"] = int(out_) if c == 0 and out_.strip().isdigit() else 0
                d["dirty"] = [line[3:] for line in self.git(s, "status", "--porcelain", "--untracked-files=no")[1].splitlines() if line.strip()]
            out.append(d)
        taken = names | {s["name"] for s in self.sources()}
        off = set(self.bundled_off())
        for b in self.bundled():
            out.append({"name": b["name"], "url": str(b["path"]), "bundled": True, "version": self.bundled_tag(b["name"]) or _app_version(),
                        "trusted": True, "enabled": b["name"] not in off, "cloned": True, "manifest": b["manifest"],
                        "error": self.errors.get(b["name"], ""),
                        "replaced_by_local": b["name"] in taken})
        return out

    # ---- changing ----
    def _clone(self, s: dict, timeout: float = 900) -> None:
        dest = self.folder(s["name"])
        part = dest.with_name(dest.name + ".partial")
        gitutil.remove_clone(part)
        self.root.mkdir(parents=True, exist_ok=True)
        code, out = self.git(s, "clone", "--quiet", "--branch", s["branch"], s["url"], str(part), cwd=self.root, timeout=timeout)
        if code != 0:
            gitutil.remove_clone(part)
            raise ToolError(f"Couldn't fetch {s['url']}: {out}")
        if s.get("pinned"):
            code, out = self.git(s, "checkout", "--quiet", s["pinned"], cwd=part)
            if code != 0:
                gitutil.remove_clone(part)
                raise ToolError(f"The pinned commit isn't there: {out}")
        part.rename(dest)

    def ensure_cloned(self, timeout: float = 120) -> None:
        """Clone every enabled source that isn't here yet (at start; errors are kept for the page)."""
        for s in self.sources():
            if s.get("enabled") and not self.cloned(s["name"]):
                try:
                    self._clone(s, timeout=timeout)
                    self.errors.pop(s["name"], None)
                except ToolError as e:
                    self.errors[s["name"]] = str(e)

    def ensure_requirements(self) -> None:
        """Install what an enabled source's tools need and this server lacks (a new machine, an instance moved here —
        its tool-packages folder isn't moved —, or another Python after an update). Same guard as an update; a failure
        is kept for the page."""
        from .pins import missing

        for s in self.sources():
            if not s.get("enabled") or not self.cloned(s["name"]):
                continue
            folder = self.folder(s["name"])
            req = folder / str(read_manifest(folder).get("requirements") or "requirements.txt")
            built = self.packages_folder(s["name"]) / MARKER
            stale = built.is_file() and not self._marker_fits(s["name"], req)
            if not stale and not missing(req, [self.packages_path(s["name"])]):
                continue
            r = self._requirements(s)
            if not r.get("ok"):
                self.errors[s["name"]] = r.get("output") or "Its packages couldn't be installed."

    def review(self, folder: Path) -> dict:
        """What to read before switching a source on: its files, and the packages its tools need — installing a package
        can run that package's code, so the page says which (``packages``) and which lines a source that isn't trusted
        may not have (``refused``: never installed)."""
        man = read_manifest(folder)
        req = folder / str(man.get("requirements") or "requirements.txt")
        files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and ".git" not in p.parts)
        text = req.read_text(encoding="utf-8") if req.is_file() else ""
        return {"manifest": man, "requirements": text, "files": files[:500], "n_files": len(files), **requirements_review(text)}

    def add(self, url: str, name: str = "", branch: str = "main", trusted: bool = False, token: str = "") -> dict:
        """Add a source. Not trusted (the default for anything but the lab's own): fetched without the server's tokens,
        pinned to the commit fetched now, and left disabled until someone enables it. ``token``: a token for this one
        repository (a private one), kept with the server's tokens for exactly this repository and used for it only."""
        url, branch = str(url or "").strip(), str(branch or "main").strip() or "main"
        if not re.match(r"^(https://|file://|git@)", url):
            raise ToolError("Give the repository's address, e.g. https://github.com/someone/their-tools.git")
        token = str(token or "").strip()
        if token and not credentials.repository(url):
            raise ToolError("A token works with an https address of one repository, e.g. https://github.com/someone/their-tools.git")
        if not BRANCH.match(branch) or ".." in branch:
            raise ToolError("Not a branch name.")
        name = (name or re.sub(r"[^a-z0-9_]+", "_", Path(url.rstrip("/")).stem.lower()).strip("_") or "tools")[:30]
        if not NAME.match(name):
            raise ToolError("Give the source a short name: small letters, digits and _ (e.g. other_lab).")
        if any(s["name"] == name for s in self.sources()):
            raise ToolError("There is a tool source with that name already.")
        s = {"name": name, "url": url, "branch": branch, "enabled": bool(trusted), "pinned": None, "trusted": bool(trusted),
             "added": time.time()}
        before = credentials.token_entry(*credentials.repository(url)) if token else None
        if token:
            credentials.set_token(*credentials.repository(url), token)
        try:
            self._clone(s)
        except ToolError:
            if token:  # the token didn't fetch it: put back what was there
                if before:
                    credentials.set_token(before["host"], before["owner"], before["repo"], before["token"])
                else:
                    credentials.remove_token(*credentials.repository(url))
            raise
        if not trusted:
            s["pinned"] = self.git(s, "rev-parse", "HEAD")[1].strip()
        with self.lock:
            self._save(self.sources() + [s])
        return {**self.get(name), "review": self.review(self.folder(name))}

    def configure(self, s: dict) -> dict:
        """A source as a lab file gives it ({name, url, branch, trusted}; mister_plis/labsetup.py). A new trusted one is
        listed and fetched at the next start; a new one that isn't trusted is fetched now, pinned and left off, as
        :meth:`add` does. One that is here already (the same repository) follows the file's branch and trust."""
        have = next((x for x in self.sources() if x["name"] == s["name"]), None)
        if have is None:
            if not s.get("trusted"):
                return self.add(s["url"], s["name"], s.get("branch") or "main", False)
            entry = {"name": s["name"], "url": s["url"], "branch": s.get("branch") or "main", "enabled": True, "pinned": None,
                     "trusted": True, "added": time.time()}
            with self.lock:
                self._save(self.sources() + [entry])
            return self.get(s["name"])
        name = s["name"]
        if bool(have.get("trusted")) != bool(s.get("trusted")):
            if s.get("trusted"):
                have = self._update(name, trusted=True, enabled=True, pinned=None)
            else:  # no longer trusted: off, and pinned where it is, until someone reviews it
                head = self.git(have, "rev-parse", "HEAD")[1].strip() if self.cloned(name) else None
                have = self._update(name, trusted=False, enabled=False, pinned=head or None)
        branch = s.get("branch") or "main"
        if have["branch"] != branch:
            if self.cloned(name) and not have.get("pinned"):
                self.switch(name, branch)
            else:
                self._update(name, branch=branch)
        return self.get(name)

    def migrate(self) -> bool:
        """A server from before lab files whose list was never saved used the lab's repository by default: keep it,
        as it is cloned here (its address from the clone itself). Returns True when it wrote the list."""
        if self.file.exists() or not self.cloned("lab"):
            return False
        code, url = gitutil.run("remote", "get-url", "origin", cwd=self.folder("lab"), timeout=10)
        code2, branch = gitutil.run("rev-parse", "--abbrev-ref", "HEAD", cwd=self.folder("lab"), timeout=10)
        if code != 0 or not url.strip():
            return False
        branch = branch.strip() if code2 == 0 and BRANCH.match(branch.strip()) and branch.strip() != "HEAD" else "main"
        url = re.sub(r"//[^@/]+@", "//", url.strip())
        self._save([{"name": "lab", "url": url, "branch": branch, "enabled": True, "pinned": None, "trusted": True}])
        return True

    def set_enabled(self, name: str, on: bool) -> dict:
        if name not in {s["name"] for s in self.sources()} and name in {b["name"] for b in self.bundled()}:
            return self.set_bundled(name, on)
        s = self.get(name)
        if on and not self.cloned(name):
            self._clone(s)
        return self._update(name, enabled=bool(on))

    def remove(self, name: str) -> None:
        if name not in {s["name"] for s in self.sources()} and name in {b["name"] for b in self.bundled()}:
            raise ToolError("This tool source comes with MISTER PLIS: switch it off instead.")
        self.get(name)
        with self.lock:
            self._save([s for s in self.sources() if s["name"] != name])
        gitutil.remove_clone(self.folder(name))  # a clone of the repository: it can be fetched again

    def check(self, name: str) -> dict:
        """Fetch, and list what an update would bring: commits and changed files."""
        s = self.get(name)
        if not self.cloned(name):
            raise ToolError("This source isn't fetched yet.")
        code, out = self.git(s, "fetch", "--prune", "origin", timeout=300)
        if code != 0:
            raise ToolError(f"Couldn't reach the repository: {out}")
        target = f"origin/{s['branch']}"
        log = self.git(s, "log", "--format=%h%x1f%an%x1f%cI%x1f%s", f"HEAD..{target}", "-n", "50")[1]
        files = self.git(s, "diff", "--name-status", f"HEAD...{target}")[1]
        man = read_manifest(self.folder(name))
        req_name = str(man.get("requirements") or "requirements.txt")
        changed = [x.split("\t")[-1] for x in files.splitlines() if x]
        extra = {}
        if req_name in changed:  # the update changes what it installs: shown, as for a new source
            code, text = self.git(s, "show", f"{target}:{req_name}")
            extra = {"requirements": text if code == 0 else "", **requirements_review(text if code == 0 else "")}
        return {"incoming": [dict(zip(("short", "author", "date", "subject"), x.split("\x1f"))) for x in log.splitlines() if x],
                "files": [x for x in files.splitlines() if x][:300], "target": self.git(s, "rev-parse", target)[1].strip(), **extra}

    def update(self, name: str, to: str = "") -> dict:
        """Bring in the source's new commits (fast-forward only; refused over local edits). A pinned source moves its
        pin to ``to`` — the commit shown by :meth:`check`, so what is installed is what was reviewed."""
        s = self.get(name)
        if not self.cloned(name):
            self._clone(s)
            return {"ok": True, "changed": True, "requirements": self._install_if_on(s)}
        if self.git(s, "status", "--porcelain", "--untracked-files=no")[1].strip():
            raise ToolError("Files were changed in this source's folder on the server — not updated.")
        old = self.git(s, "rev-parse", "HEAD")[1].strip()
        if s.get("pinned"):
            if not re.fullmatch(r"[0-9a-f]{7,40}", to or ""):
                raise ToolError("Check the source first, then update to the commit it showed.")
            code, out = self.git(s, "checkout", "--quiet", to)
            if code != 0:
                raise ToolError(f"Couldn't move to {to}: {out}")
            self._update(name, pinned=self.git(s, "rev-parse", "HEAD")[1].strip())
        else:
            code, out = self.git(s, "fetch", "origin", s["branch"], timeout=300)
            if code == 0:
                code, out = self.git(s, "merge", "--ff-only", f"origin/{s['branch']}")
            if code != 0:
                raise ToolError(f"The update failed: {out}")
        new = self.git(s, "rev-parse", "HEAD")[1].strip()
        changed = new != old
        req = self._install_if_on(self.get(name), old) if changed else {"ok": True, "installed": False}
        return {"ok": req["ok"], "changed": changed, "requirements": req}

    def switch(self, name: str, branch: str) -> dict:
        s = self.get(name)
        if not BRANCH.match(branch or "") or ".." in branch:
            raise ToolError("Not a branch name.")
        if s.get("pinned"):
            raise ToolError("This source is pinned to a commit — unpin it first.")
        self._update(name, branch=branch)
        if not self.cloned(name):
            return self.update(name)
        s = self.get(name)
        if self.git(s, "status", "--porcelain", "--untracked-files=no")[1].strip():
            raise ToolError("Files were changed in this source's folder on the server — not switched.")
        code, out = self.git(s, "fetch", "origin", branch, timeout=300)
        if code == 0:
            code, out = self.git(s, "checkout", "-B", branch, f"origin/{branch}")
        if code != 0:
            raise ToolError(f"Couldn't switch to {branch}: {out}")
        return {"ok": True, "changed": True, "requirements": self._install_if_on(s)}

    def set_pin(self, name: str, pinned: bool) -> dict:
        s = self.get(name)
        if not pinned and not s.get("trusted"):
            raise ToolError("A source that isn't trusted stays pinned: each update is reviewed first.")
        return self._update(name, pinned=self.git(s, "rev-parse", "HEAD")[1].strip() if pinned else None)

    # ---- the packages a source's tools need ----
    # They are installed beside the app's own environment, in the instance's folder: <data>/tool-packages/<source>/ (a
    # pip "prefix"; its site-packages is added to the end of sys.path when the tools load, so the app's own packages
    # always win). A release or a Docker image replaces the app's environment, which may be read-only; the instance's
    # folder stays. Packages a source already found in the app's environment (servers from before this) are used from
    # there: only what is missing is installed.
    def packages_folder(self, name: str) -> Path:
        return self.packages_root / name

    def packages_path(self, name: str, folder: Path | None = None) -> Path:
        """The folder the source's packages are imported from (site-packages inside its prefix)."""
        import sysconfig

        prefix = folder or self.packages_folder(name)
        return Path(sysconfig.get_path("purelib", vars={"base": str(prefix), "platbase": str(prefix)}))

    def _marker_fits(self, name: str, req: Path) -> bool:
        """Whether the packages there were installed for these requirements, this Python and this system."""
        try:
            m = json.loads((self.packages_folder(name) / MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return m == {**m, **_build_key(req)}

    def _install_if_on(self, s: dict, old: str = "") -> dict:
        """Install the source's packages now if it is switched on. One that is off — a source that isn't trusted, waiting
        for its review — gets them when it is switched on (at the next start): installing a package can run its code
        (docs/SECURITY_AUDIT.md H4)."""
        if not s.get("enabled"):
            return {"ok": True, "installed": False, "later": True}
        return self._requirements(s, old)

    def _requirements(self, s: dict, old: str = "") -> dict:
        """Install the source's requirements into its own folder — but only if that changes none of the packages the
        app's environment has (checked with a dry run against this server's own installed versions first,
        mister_plis/pins.py). Built in a new folder, then swapped in: a failed install leaves the old one."""
        import hashlib
        import os
        import shutil

        from .pins import write_constraints

        folder = self.folder(s["name"])
        man = read_manifest(folder)
        req = folder / str(man.get("requirements") or "requirements.txt")
        if not req.is_file() or not [x for x in req.read_text(encoding="utf-8").splitlines() if x.strip() and not x.strip().startswith("#")]:
            return {"ok": True, "installed": False}
        if old and req.relative_to(folder).as_posix() not in self.git(s, "diff", "--name-only", old, "HEAD")[1].splitlines():
            return {"ok": True, "installed": False}
        if not s.get("trusted"):  # someone else's: only packages by name, ready made (building one runs its code)
            problems = untrusted_requirement_problems(req.read_text(encoding="utf-8"))
            if problems:
                return {"ok": False, "installed": False,
                        "output": "A tool source that isn't the lab's own may only name packages (e.g. numpy>=1.26) — "
                                  "nothing was installed. Not allowed:\n" + "\n".join(problems[:20])}
        pins = write_constraints(self.root / "constraints.txt", everything=True)
        dest = self.packages_folder(s["name"])
        part = dest.with_name(dest.name + ".partial")
        shutil.rmtree(part, ignore_errors=True)
        part.parent.mkdir(parents=True, exist_ok=True)
        base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
                "--prefix", str(part), "-r", str(req), "-c", str(pins)] + self.pip_extra
        if not s.get("trusted"):
            base += ["--only-binary", ":all:"]
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PIP_TARGET", "PIP_PREFIX", "PIP_USER")}
        dry = subprocess.run(base + ["--dry-run"], capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace",
                             env=env)
        if dry.returncode != 0:
            shutil.rmtree(part, ignore_errors=True)
            return {"ok": False, "installed": False,
                    "output": "Its packages don't fit with MISTER PLIS's own — nothing was installed.\n\n"
                              + (dry.stdout + dry.stderr)[-3000:]}
        r = subprocess.run(base, capture_output=True, text=True, timeout=1800, encoding="utf-8", errors="replace", env=env)
        if r.returncode != 0:
            shutil.rmtree(part, ignore_errors=True)
            return {"ok": False, "installed": False, "output": (r.stdout + r.stderr)[-3000:]}
        part.mkdir(parents=True, exist_ok=True)
        (part / MARKER).write_text(json.dumps({**_build_key(req), "installed_at": time.time()}, indent=1), encoding="utf-8")
        old_dir = None
        if dest.exists():  # the packages of before: set aside, then removed (they are rebuilt whenever needed)
            old_dir = dest.with_name(f"{dest.name}.replaced-{hashlib.sha1(str(time.time()).encode()).hexdigest()[:8]}")
            dest.rename(old_dir)
        part.rename(dest)
        if old_dir is not None:
            shutil.rmtree(old_dir, ignore_errors=True)  # Windows: a package in use stays until the next start
        return {"ok": True, "installed": True, "output": (r.stdout + r.stderr)[-3000:]}


def requirements_review(text: str) -> dict:
    """The packages a requirements file names (``packages``) and the lines a source that isn't trusted may not have
    (``refused``)."""
    from packaging.requirements import InvalidRequirement, Requirement

    names = []
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if line and not line.startswith(("#", "-")):
            try:
                names.append(Requirement(line).name)
            except InvalidRequirement:
                pass
    return {"packages": sorted(set(names), key=str.casefold), "refused": untrusted_requirement_problems(text)}


def untrusted_requirement_problems(text: str) -> list[str]:
    """The lines of a requirements file that a source that isn't trusted may not have: anything but a package's name
    and versions (an option such as -e or --index-url, a path, an address, a "pkg @ url" reference)."""
    from packaging.requirements import InvalidRequirement, Requirement

    out = []
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        try:
            r = Requirement(line)
        except InvalidRequirement:
            out.append(line)
            continue
        if r.url or line.startswith("-"):
            out.append(line)
    return out


def _app_version() -> str:
    from . import __version__

    return __version__


MARKER = ".mister-plis.json"  # in a source's packages folder: what they were installed for


def _build_key(req: Path) -> dict:
    """What a source's installed packages depend on: its requirements, this Python (major.minor) and this system."""
    import hashlib
    import platform

    try:
        digest = hashlib.sha256(req.read_bytes()).hexdigest()
    except OSError:
        digest = ""
    return {"requirements_sha256": digest, "python": platform.python_version().rsplit(".", 1)[0],
            "platform": sys.platform, "machine": platform.machine()}


sources = ToolSources(settings.data_path, settings.tool_folder_paths())
