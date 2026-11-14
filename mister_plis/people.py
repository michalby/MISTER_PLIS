"""People merged into one another (Settings → People).

A name is whatever someone typed in the top bar, so the same person can end up under two names ("Ola",
"Ola Nowak"). Merging moves everything under the old name to the kept one and remembers it here, in
``data/people.json``: a browser that still sends the old name is read as the kept one, so the old name
never comes back.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .errors import ToolError
from .jobs import clean_text


class People:
    def __init__(self, data_path: Path):
        self.path = data_path / "people.json"
        self.lock = threading.Lock()
        self._merged: dict[str, str] = {}  # old name, casefolded → the name it was merged into
        self.log: list[dict] = []
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self._merged = {str(k): str(v) for k, v in (d.get("merged") or {}).items()}
            self.log = [x for x in d.get("log") or [] if isinstance(x, dict)]
        except (OSError, ValueError, AttributeError):
            pass

    def canonical(self, name: str) -> str:
        """The name to use for ``name``: the one it was merged into (following merges of merges), or itself."""
        seen = set()
        while name and name.casefold() in self._merged and name.casefold() not in seen:
            seen.add(name.casefold())
            name = self._merged[name.casefold()]
        return name

    def unmerge(self, name: str) -> None:
        """``name`` is a name in use again (an account renamed back to it): no longer read as the one it was merged into."""
        key = clean_text(name, 60).casefold()
        with self.lock:
            if key not in self._merged:
                return
            del self._merged[key]
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"merged": self._merged, "log": self.log[-500:]}, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def merge(self, old: str, into: str, by: str = "") -> tuple[str, str]:
        """Remember that ``old`` is now ``into``; returns both, cleaned. The caller renames the stored records."""
        old, into = clean_text(old, 60), self.canonical(clean_text(into, 60))
        if not old or not into:
            raise ToolError("Choose both people.")
        if old.casefold() == into.casefold():
            raise ToolError("Choose two different people.")
        with self.lock:
            self._merged[old.casefold()] = into
            # anyone merged into the old name now goes straight to the kept one
            for k, v in self._merged.items():
                if v.casefold() == old.casefold():
                    self._merged[k] = into
            self.log.append({"from": old, "into": into, "by": clean_text(by, 60), "at": time.time()})
            self._save()
        return old, into
