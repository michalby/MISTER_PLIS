"""The lab notebook: chosen folders of the lab's Obsidian vault (a GitHub repository), shown read-only.

The server keeps a partial clone in ``<data>/modules/notebook/vault``. Only the chosen folders, and the pictures and
files their notes use, are downloaded (git sparse checkout); everything else stays on GitHub. Syncing is
manual (Settings → Lab notebook → Sync notes) and never restarts the server.

GitHub access: the instance's own tokens (mister_plis/credentials.py, Settings → Server & updates → GitHub access),
then the code repository's credential helper (on a Mac app: the token in the Keychain).

Lab-wide choices live in ``<data>/modules/notebook/settings.json``: ``{"folders": [...], "synced_at": ...}``.
"""

from __future__ import annotations

import json
import posixpath
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from mister_plis import gitutil, updater
from mister_plis.errors import ToolError
from .obsidian import NoteRef, Renderer, fold, norm, plain_text, title_of

DEFAULT_FOLDERS: list[str] = []  # none until the lab chooses (Settings → Lab notebook, or a lab file)
SERVED_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".bmp": "image/bmp", ".avif": "image/avif", ".svg": "image/svg+xml", ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8",
}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


from mister_plis.gitutil import credential_args as _credential_args  # noqa: E402,F401  (one token for every repository)


def _explain(out: str) -> str:
    low = out.lower()
    if any(s in low for s in ("authentication failed", "could not read username", "repository not found",
                              "terminal prompts disabled", "403", "invalid username or password")):
        return ("GitHub didn't let the server read the notebook repository. On github.com edit the MISTER PLIS "
                "token (Settings → Developer settings → Fine-grained tokens) → Repository access → add the "
                "notebook repository with Contents: Read-only. No change is needed on the Mac.\n\n" + out)
    if "could not resolve host" in low or "unable to access" in low:
        return "The server couldn't reach GitHub. Check its internet connection.\n\n" + out
    return out


def _sparse_pattern(path: str, folder: bool) -> str:
    """A path as a sparse-checkout (gitignore-style) pattern matching exactly that path."""
    p = re.sub(r"([\\*?\[\]!#])", r"\\\1", path)
    p = re.sub(r" $", "\\ ", p)
    return "/" + p + ("/" if folder else "")


@dataclass
class Note:
    id: str      # vault path without ".md"
    path: str    # vault path
    title: str
    folder: str
    text: str
    plain: str = ""
    html: str = ""
    links: set[str] = field(default_factory=set)
    backlinks: set[str] = field(default_factory=set)


class Index:
    """The shown notes, how names resolve to them, and their HTML."""

    def __init__(self, notes: dict[str, Note], all_files: list[str], folders: list[str], commit: dict | None):
        self.notes = notes
        self.folders = folders
        self.commit = commit or {}
        self.by_id = {norm(i): i for i in notes}
        self.by_title: dict[str, list[str]] = {}
        for n in notes.values():
            self.by_title.setdefault(norm(n.title), []).append(n.id)
        self.files = {norm(f): f for f in all_files if not f.lower().endswith(".md")}
        self.files_by_name: dict[str, list[str]] = {}
        for f in self.files.values():
            self.files_by_name.setdefault(norm(posixpath.basename(f)), []).append(f)
        self.attachments: set[str] = set()

    @classmethod
    def empty(cls) -> "Index":
        return cls({}, [], [], None)

    # ---- resolving names the way Obsidian does --------------------------------------------
    def resolve_note(self, name: str, from_id: str) -> NoteRef | None:
        name = _nfc(name).strip().replace("\\", "/")
        if name.lower().endswith(".md"):
            name = name[:-3]
        key = norm(name)
        if key in self.by_id:
            i = self.by_id[key]
            return NoteRef(i, self.notes[i].title)
        cands = [i for i in self.by_title.get(norm(posixpath.basename(name)), []) if norm(i).endswith(key)]
        if not cands:
            return None
        here = posixpath.dirname(from_id)
        cands.sort(key=lambda i: (posixpath.dirname(i) != here, len(i), i))
        return NoteRef(cands[0], self.notes[cands[0]].title)

    def resolve_file(self, name: str, from_id: str) -> str | None:
        name = _nfc(name).strip().replace("\\", "/").split("#")[0].split("?")[0]
        if not name:
            return None
        for cand in (posixpath.normpath(posixpath.join(posixpath.dirname(from_id), name)), posixpath.normpath(name.lstrip("/"))):
            if norm(cand) in self.files:
                return self.files[norm(cand)]
        found = sorted(self.files_by_name.get(norm(posixpath.basename(name)), []), key=lambda f: (len(f), f))
        return found[0] if found else None

    def load_text(self, note_id: str) -> str | None:
        n = self.notes.get(note_id)
        return n.text if n else None

    def render_all(self) -> None:
        r = Renderer(self.resolve_note, self.resolve_file, self.load_text)
        for n in self.notes.values():
            out = r.render(n.text, n.id)
            n.html = out.html
            n.links = out.links - {n.id}
            n.plain = plain_text(n.text)
            self.attachments |= out.files
        for n in self.notes.values():
            for target in n.links:
                self.notes[target].backlinks.add(n.id)

    # ---- what the pages ask for ---------------------------------------------------------
    def tree(self) -> list[dict]:
        groups: dict[str, list[Note]] = {}
        for n in self.notes.values():
            groups.setdefault(n.folder, []).append(n)
        return [{"folder": f, "notes": [{"id": n.id, "title": n.title} for n in sorted(groups[f], key=lambda n: fold(n.title))]}
                for f in sorted(groups, key=fold)]

    def note(self, note_id: str) -> dict | None:
        n = self.notes.get(note_id) or self.notes.get(self.by_id.get(norm(note_id), ""))
        if not n:
            return None
        back = sorted(n.backlinks, key=lambda i: fold(self.notes[i].title))
        return {"id": n.id, "title": n.title, "folder": n.folder, "path": n.path, "html": n.html,
                "backlinks": [{"id": i, "title": self.notes[i].title, "folder": self.notes[i].folder} for i in back]}

    def search(self, q: str, limit: int = 40) -> list[dict]:
        words = fold(q).split()
        if not words:
            return []
        hits = []
        for n in self.notes.values():
            t, body = fold(n.title), fold(n.plain)
            if not all(w in t or w in body for w in words):
                continue
            score = sum(w in t for w in words) * 10 + (t.startswith(words[0]) * 5)
            hits.append((-score, fold(n.title), n))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [{"id": n.id, "title": n.title, "folder": n.folder, "snippet": self._snippet(n.plain, words)}
                for _, _, n in hits[:limit]]

    @staticmethod
    def _snippet(plain: str, words: list[str], width: int = 150) -> str:
        folded = fold(plain)
        if len(folded) != len(plain):  # folding changed the length: positions don't line up, start at the top
            return plain[:width] + ("…" if len(plain) > width else "")
        pos = min((folded.find(w) for w in words if folded.find(w) >= 0), default=0)
        start = max(0, pos - width // 3)
        return ("…" if start else "") + plain[start:start + width].strip() + ("…" if start + width < len(plain) else "")


class Notebook:
    def __init__(self, data_path: Path, url: str, branch: str, root: Path | None = None):
        self.root = root or data_path / "notes"  # as a module: <data>/modules/notebook
        self.vault = self.root / "vault"
        self.settings_file = self.root / "settings.json"
        self.url = gitutil.address(url)  # GitHub, or a git repository in a folder on this machine
        self.branch = branch.strip() or "main"
        self.index = Index.empty()
        self.last_error = ""
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    @property
    def remote_ref(self) -> str:
        return f"origin/{self.branch}"

    @property
    def folder(self) -> Path | None:
        """The vault's folder when it is on this machine (repo = a path), not on GitHub."""
        return gitutil.local_folder(self.url)

    def _explain(self, out: str) -> str:
        if self.folder:
            why = gitutil.explain_local(out, self.folder)
            return why + "\n\n" + out if why else out
        return _explain(out)

    # ---- settings ---------------------------------------------------------------------
    def _settings(self) -> dict:
        try:
            d = json.loads(self.settings_file.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self, **changes) -> None:
        d = self._settings() | changes
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.settings_file)

    def stored(self) -> dict:
        """The repository chosen on the Settings tab or by a lab file (repo, branch); config.toml wins over it."""
        d = self._settings()
        return {k: d[k] for k in ("repo", "branch") if isinstance(d.get(k), str)}

    def set_repository(self, url: str, branch: str = "main") -> dict:
        """Read another repository (or none: "" turns the notebook off), at once. The old copy is renamed
        ``vault.before-<date>`` (never deleted); the new one is downloaded at the next sync."""
        url = gitutil.address(gitutil.check_address(url))
        branch = gitutil.check_branch(branch)
        with self._lock:
            if (url, branch) == (self.url, self.branch):
                self._save_settings(repo=url, branch=branch)
                return {"changed": False, "kept": ""}
            kept = str(gitutil.set_aside(self.vault)) if self.vault.exists() else ""
            self.url, self.branch = url, branch
            self.index = Index.empty()
            self.last_error = ""
            self._save_settings(repo=url, branch=branch, synced_at=None, synced_commit="")
        return {"changed": True, "kept": kept}

    AUTO = (0, 15, 60, 240)  # minutes between automatic syncs; 0 = only by hand

    def auto_minutes(self) -> int:
        m = self._settings().get("auto_minutes", 0)
        return m if m in self.AUTO else 0

    def set_auto(self, minutes) -> int:
        """Sync by itself every so often — for notes edited in Obsidian on other computers and pushed by its Git
        plugin. Like Sync notes, it never restarts the server."""
        try:
            m = int(minutes or 0)
        except (TypeError, ValueError):
            m = -1
        if m not in self.AUTO:
            raise ToolError("Sync every 15 min, 1 h, 4 h, or only by hand.")
        self._save_settings(auto_minutes=m)
        return m

    def auto_sync_loop(self) -> None:  # pragma: no cover - a background thread
        tried = 0.0  # a failing sync (no network, no token) waits a whole interval too
        while True:
            time.sleep(60)
            m = self.auto_minutes()
            if not (self.enabled and m):
                continue
            if time.time() - max(self._settings().get("synced_at") or 0, tried) >= m * 60:
                tried = time.time()
                try:
                    self.sync()
                except Exception as e:
                    self.last_error = str(e)

    def folders(self) -> list[str]:
        f = self._settings().get("folders")
        return [_nfc(x) for x in f if isinstance(x, str)] if isinstance(f, list) else list(DEFAULT_FOLDERS)

    def set_folders(self, folders: list) -> list[str]:
        clean = []
        for f in folders:
            f = _nfc(str(f)).strip().strip("/")
            if not f or f.startswith(".") or ".." in f.split("/") or "\\" in f:
                raise ToolError(f"Not a folder of the notebook: {f!r}")
            clean.append(f)
        if self.cloned():
            known = {d["path"] for d in self.available_folders()}
            unknown = [f for f in clean if f not in known]
            if unknown:
                raise ToolError(f"The notebook has no folder {unknown[0]!r}. Check for updates and try again.")
        # a ticked folder already includes its subfolders
        clean = sorted({f for f in clean if not any(f.startswith(p + "/") for p in clean if p != f)}, key=fold)
        self._save_settings(folders=clean)
        return clean

    # ---- git --------------------------------------------------------------------------
    def git(self, *args: str, cwd: Path | None = None, timeout: float = 180) -> tuple[int, str]:
        return gitutil.run(*args, cwd=cwd or self.vault, timeout=timeout, credentials=True)

    def cloned(self) -> bool:
        return (self.vault / ".git").is_dir()

    def _clone(self) -> tuple[int, str]:
        """Partial clone without files: history and folder names only, file contents come on demand."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "vault.partial"
        gitutil.remove_clone(tmp)
        code, out = self.git("clone", "--filter=blob:none", "--no-checkout", "--branch", self.branch, self.url, str(tmp),
                             cwd=self.root, timeout=600)
        if code != 0:
            gitutil.remove_clone(tmp)
            return code, out
        for k, v in (("core.sparseCheckout", "true"), ("core.sparseCheckoutCone", "false"), ("core.precomposeUnicode", "true")):
            self.git("config", k, v, cwd=tmp)
        (tmp / ".git" / "info").mkdir(exist_ok=True)
        (tmp / ".git" / "info" / "sparse-checkout").write_text("", encoding="utf-8")
        tmp.rename(self.vault)
        return 0, out

    def _fetch(self) -> tuple[int, str]:
        if not self.cloned():
            return self._clone()
        # the repository may have changed in config.toml since the first download
        code, current = self.git("remote", "get-url", "origin")
        if code != 0 or current.strip() != self.url:
            self.git("remote", "set-url", "origin", self.url)
        return self.git("fetch", "--prune", "origin", f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}", timeout=300)

    def _ls(self, ref: str) -> list[str]:
        code, out = self.git("ls-tree", "-r", "-z", "--name-only", ref)
        return [_nfc(p) for p in out.split("\0") if p] if code == 0 else []

    def _commit(self, ref: str = "HEAD") -> dict | None:
        code, out = self.git("log", "-1", "--format=%H%x1f%h%x1f%cI%x1f%s", ref)
        if code != 0 or not out:
            return None
        full, short, date, subject = out.split("\x1f", 3)
        return {"commit": full, "short": short, "date": date, "subject": subject}

    def available_folders(self) -> list[dict]:
        """Every folder of the vault that holds notes, with how many (subfolders included)."""
        counts: dict[str, int] = {}
        for p in self._ls(self.remote_ref) or self._ls("HEAD"):
            if not p.lower().endswith(".md") or any(part.startswith(".") for part in p.split("/")):
                continue
            parts = p.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                d = "/".join(parts[:i])
                counts[d] = counts.get(d, 0) + 1
        return [{"path": d, "notes": n, "depth": d.count("/")} for d, n in sorted(counts.items(), key=lambda kv: fold(kv[0]))]

    def _apply_sparse(self, folders: list[str], files: set[str]) -> tuple[int, str]:
        lines = [_sparse_pattern(f, True) for f in folders] + [_sparse_pattern(f, False) for f in sorted(files)]
        (self.vault / ".git" / "info" / "sparse-checkout").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.git("read-tree", "-mu", "HEAD", timeout=600)

    # ---- building the index from the files on disk ------------------------------------------
    def build_index(self) -> Index:
        folders = self.folders()
        all_files = self._ls("HEAD")
        notes: dict[str, Note] = {}
        for p in all_files:
            if not p.lower().endswith(".md") or not any(p.startswith(f + "/") for f in folders):
                continue
            f = self.vault / p
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            nid = p[:-3]
            notes[nid] = Note(id=nid, path=p, title=title_of(p), folder=posixpath.dirname(p), text=text)
        idx = Index(notes, all_files, folders, self._commit())
        idx.render_all()
        return idx

    def load(self) -> None:
        """At start-up: index what was synced before (no network)."""
        if self.enabled and self.cloned() and self._commit():
            try:
                self.index = self.build_index()
            except Exception as e:  # pragma: no cover - a broken note must not stop the server
                self.last_error = f"Couldn't read the notes: {e}"

    # ---- what the System page calls ----------------------------------------------------------
    def status_light(self) -> dict:
        """What the notes panel shows in its header (no git calls)."""
        return {"repo": updater._redact(self.url).rsplit("/", 1)[-1].removesuffix(".git"),
                "synced_at": self._settings().get("synced_at")}

    def status(self) -> dict:
        st = self._settings()
        d = {
            "enabled": self.enabled,
            "locked": bool(getattr(self, "locked", None)),
            "repo": updater._redact(self.url),
            "folder": str(self.folder or ""),
            "branch": self.branch,
            "folders": self.folders(),
            "cloned": self.cloned(),
            "synced_at": st.get("synced_at"),
            "auto_minutes": self.auto_minutes(),
            "last_error": self.last_error,
            "notes": len(self.index.notes),
            "files": len(self.index.attachments),
            "head": self._commit() if self.cloned() else None,
            "behind": 0,
            "last_fetch": None,
            "available": [],
        }
        if self.cloned():
            fetch_head = self.vault / ".git" / "FETCH_HEAD"
            d["last_fetch"] = fetch_head.stat().st_mtime if fetch_head.exists() else st.get("synced_at")
            code, out = self.git("rev-list", "--count", f"HEAD..{self.remote_ref}")
            d["behind"] = int(out) if code == 0 and out.isdigit() else 0
            d["available"] = self.available_folders()
        return d

    def check(self) -> dict:
        """Fetch from GitHub and list the changes a sync would bring to the shown folders."""
        with self._lock:
            code, out = self._fetch()
        st = self.status()
        st["fetch_ok"] = code == 0
        st["fetch_output"] = self._explain(out) if code else ""
        st["incoming"] = []
        if code == 0 and st["head"]:
            fmt = "%h%x1f%an%x1f%cI%x1f%s"
            _, log = self.git("log", f"--format={fmt}", f"HEAD..{self.remote_ref}", "-n", "50", "--", *self.folders())
            st["incoming"] = [dict(zip(("short", "author", "date", "subject"), line.split("\x1f"))) for line in log.splitlines() if line]
        return st

    def sync(self) -> dict:
        """Download the newest version of the chosen folders and re-index. Returns a step log."""
        steps: list[dict] = []

        def step(name: str, code: int, out: str) -> bool:
            steps.append({"name": name, "ok": code == 0, "output": self._explain(out) if code else out})
            return code == 0

        if not self.enabled:
            return {"ok": False, "steps": [{"name": "The notebook is turned off: choose its repository on Settings → Lab notebook", "ok": False, "output": ""}]}
        with self._lock:
            first = not self.cloned()
            if not step("git clone (first time)" if first else "git fetch", *self._fetch()):
                self.last_error = steps[-1]["output"]
                return {"ok": False, "steps": steps}
            folders = self.folders()
            if not step("update to the newest version", *self.git("reset", "-q", "--hard", self.remote_ref)):
                return {"ok": False, "steps": steps}
            known = self.index.attachments if not first else set()
            if not step("download the chosen folders", *self._apply_sparse(folders, known)):
                return {"ok": False, "steps": steps}
            idx = self.build_index()
            if idx.attachments != known:
                if not step(f"download {len(idx.attachments)} pictures and files the notes use", *self._apply_sparse(folders, idx.attachments)):
                    return {"ok": False, "steps": steps}
            self.index = idx
            self.last_error = ""
            self._save_settings(synced_at=time.time(), synced_commit=(idx.commit or {}).get("commit", ""))
            steps.append({"name": f"{len(idx.notes)} notes from {len(folders)} folder(s) ready", "ok": True, "output": ""})
        return {"ok": True, "steps": steps, "status": self.status()}

    def file(self, path: str) -> Path | None:
        """A picture or file a shown note uses — nothing else is served."""
        path = _nfc(path)
        if path not in self.index.attachments:
            return None
        p = (self.vault / path).resolve()
        if not p.is_file() or self.vault.resolve() not in p.parents:
            return None
        return p
