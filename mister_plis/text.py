"""Small text helpers shared by the base and the modules (reorg P5)."""

from __future__ import annotations

import unicodedata


def norm(text: str) -> str:
    """How names are compared: Unicode-normalised and case-insensitive."""
    return unicodedata.normalize("NFC", text).casefold().strip()


def fold(text: str) -> str:
    """For search: no case, no accents (ł → l, ę → e), so "stezenie" finds "stężenie"."""
    t = unicodedata.normalize("NFKD", text.casefold().replace("ł", "l"))
    return "".join(c for c in t if not unicodedata.combining(c))
