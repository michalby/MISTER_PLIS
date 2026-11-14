"""Time Machine's history: its folder is a local git repository, and every change is one commit.

Nothing is pushed anywhere — the repository only lives on the server, next to the kept results. Result files
never change once kept, so git stores each one once; what changes is ``entry.json`` (projects, note) and
``projects.json``. A commit message says what happened in words, with trailers for finding commits again::

    Move Chlorophyll concentration (20261019-142301-a1b2c3) from “PSI paper” to “Thesis ch. 2”

    Job: 20261019-142301-a1b2c3
    Project: p-1a2b3c
    Project: p-4d5e6f
    Action: projects

The author is whoever made the change (their name from Settings).
"""

from __future__ import annotations

import os
from pathlib import Path

SEP_FIELD, SEP_COMMIT = "\x1f", "\x1e"
EMAIL = "time-machine@mister-plis.local"


class LocalHistory:
    def __init__(self, root: Path):
        self.root = root
        self.env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(k, None)
        self.available = False

    def git(self, *args: str, timeout: float = 120) -> tuple[int, str]:
        from mister_plis import gitutil

        try:
            return gitutil.run(*args, cwd=self.root, timeout=timeout)
        except OSError as e:
            return 127, str(e)

    def init(self) -> bool:
        """Make the folder a repository (once) and commit whatever is there already."""
        if not (self.root / ".git").is_dir():
            code, _ = self.git("init", "-q")
            if code != 0:
                self.available = False
                return False
            (self.root / ".gitignore").write_text(".*.partial/\n*.tmp\n", encoding="utf-8")
        self.available = self.git("rev-parse", "--is-inside-work-tree")[0] == 0
        if self.available:
            self.commit("Time Machine history starts here", "MISTER PLIS", ["Action: start"])
        return self.available

    def commit(self, subject: str, author: str = "", trailers: list[str] | None = None) -> str | None:
        """Commit every change in the folder; returns the commit id, or None when nothing changed."""
        if not self.available:
            return None
        self.git("add", "-A")
        if self.git("diff", "--cached", "--quiet")[0] == 0 and self.git("rev-parse", "--verify", "-q", "HEAD")[0] == 0:
            return None
        message = subject + ("\n\n" + "\n".join(trailers) if trailers else "")
        who = author or "Someone without a name"
        code, out = self.git("-c", f"user.name={who}", "-c", f"user.email={EMAIL}", "commit", "-q", "--allow-empty", "-m", message)
        if code != 0:
            return None
        return self.git("rev-parse", "HEAD")[1].strip()

    def log(self, job: str = "", project: str = "", limit: int = 200) -> list[dict]:
        if not self.available:
            return []
        args = ["log", f"-n{max(1, min(limit, 2000))}", f"--format=%H{SEP_FIELD}%an{SEP_FIELD}%at{SEP_FIELD}%s{SEP_FIELD}%b{SEP_COMMIT}"]
        if job:
            args += ["-F", f"--grep=Job: {job}"]
        if project:
            args += ["-F", f"--grep=Project: {project}"]
        code, out = self.git(*args)
        if code != 0:
            return []
        commits = []
        for raw in out.split(SEP_COMMIT):
            parts = raw.strip("\n").split(SEP_FIELD)
            if len(parts) != 5:
                continue
            sha, author, at, subject, body = parts
            trailers: dict[str, list[str]] = {}
            for line in body.splitlines():
                k, sep, v = line.partition(": ")
                if sep and k in ("Job", "Project", "Action"):
                    trailers.setdefault(k.lower(), []).append(v.strip())
            commits.append({"id": sha, "short": sha[:7], "author": author, "at": int(at), "subject": subject,
                            "jobs": trailers.get("job", []), "projects": trailers.get("project", []),
                            "action": (trailers.get("action") or [""])[0]})
        return commits

    def get(self, sha: str) -> dict | None:
        if not (self.available and sha and all(c in "0123456789abcdef" for c in sha) and 4 <= len(sha) <= 40):
            return None
        found = [c for c in self.log(limit=2000) if c["id"].startswith(sha)]
        return found[0] if len(found) == 1 else None

    def files_changed(self, sha: str) -> list[str]:
        code, out = self.git("show", "--name-status", "--format=", sha)
        return out.splitlines() if code == 0 else []

    def restore_folder(self, sha: str, folder: str) -> bool:
        """Bring ``folder`` back as it was just before commit ``sha`` (e.g. a removed result)."""
        return self.git("checkout", f"{sha}^", "--", folder)[0] == 0
