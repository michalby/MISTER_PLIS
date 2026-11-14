"""Feedback from the lab: bugs, inconveniences and feature ideas sent with the button in the top bar.

Kept on the server in ``data/feedback.json`` (shared by everyone, not in git) and listed on the
Feedback page (/feedback), where each one can be marked as done or deleted — a to-do list for future work.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path

from .errors import ToolError

# kind → (label, hint); the dot colours are in app.css (.fb-kind-<kind>)
KINDS = {
    "bug": ("Bug", "Something doesn't work"),
    "inconvenience": ("Inconvenience", "It works, but it's awkward"),
    "idea": ("Feature idea", "Something new that would help"),
}
MAX_TEXT = 4000
MAX_ITEMS = 5000


def _line(s, limit: int) -> str:
    return " ".join(str(s or "").split())[:limit]


class FeedbackStore:
    def __init__(self, data_path: Path):
        self.path = data_path / "feedback.json"
        self.lock = threading.Lock()

    def _read(self) -> list[dict]:
        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [i for i in items if isinstance(i, dict) and i.get("id")] if isinstance(items, list) else []

    def _write(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> list[dict]:
        """Newest first."""
        with self.lock:
            return sorted(self._read(), key=lambda i: i.get("created", 0), reverse=True)

    def rename_user(self, old: str, new: str) -> int:
        """Everything sent under ``old`` (any capitals) is now under ``new``; returns how many."""
        with self.lock:
            items = self._read()
            hit = [i for i in items if (i.get("user") or "").casefold() == old.casefold()]
            for i in hit:
                i["user"] = new
            if hit:
                self._write(items)
        return len(hit)

    def open_count(self) -> int:
        return sum(1 for i in self.all() if i.get("status") != "done")

    def add(self, kind: str, text: str, user: str = "", page: str = "", where: str = "", account: str = "") -> dict:
        if kind not in KINDS:
            raise ToolError("Pick what kind of feedback it is.")
        text = str(text or "").strip()[:MAX_TEXT]
        if not text:
            raise ToolError("Write a few words first.")
        page = _line(page, 300)
        if not page.startswith("/") or page.startswith("//") or "\\" in page:  # a page of this app, never a link elsewhere
            page = ""
        item = {"id": secrets.token_hex(6), "kind": kind, "text": text, "user": _line(user, 60),
                "page": page, "where": _line(where, 160), "created": time.time(), "status": "new"}
        if account:  # the sender's account (mister_plis/accounts.py), from 0.15.0
            item["account"] = account
        with self.lock:
            items = self._read()
            items.append(item)
            self._write(items[-MAX_ITEMS:])
        return item

    def update(self, item_id: str, status: str) -> dict:
        if status not in ("new", "done"):
            raise ToolError("Unknown status.")
        with self.lock:
            items = self._read()
            for i in items:
                if i["id"] == item_id:
                    i["status"] = status
                    i["done_at"] = time.time() if status == "done" else None
                    self._write(items)
                    return i
        raise ToolError("That feedback is gone — someone may have deleted it.")

    def delete(self, item_id: str) -> None:
        with self.lock:
            items = self._read()
            kept = [i for i in items if i["id"] != item_id]
            if len(kept) == len(items):
                raise ToolError("That feedback is gone — someone may have deleted it.")
            self._write(kept)
