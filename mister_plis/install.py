"""How this instance was installed, and where its code and its own files are (Settings → Server & updates).

The code folder (``config.ROOT``) is what an update or a release replaces; the instance's folder (``config.HOME``,
``MISTER_PLIS_HOME``) holds config.toml, data/, secrets/ and logs/. Without ``MISTER_PLIS_HOME`` they are the same.
"""

from __future__ import annotations

import os

from .config import HOME, ROOT, settings

KINDS = ("docker", "mac-app", "service", "checkout", "package")


def kind() -> str:
    """How this instance was installed: what ``MISTER_PLIS_INSTALL`` says (the Dockerfile, the Mac app's launcher or a
    service set it: "docker", "mac-app", "service"…); else "checkout" (a git clone) or "package" (no .git)."""
    told = os.environ.get("MISTER_PLIS_INSTALL", "").strip().lower()
    if told:
        return told
    return "checkout" if (ROOT / ".git").exists() else "package"


def describe() -> dict:
    return {
        "kind": kind(),
        "code": str(ROOT),
        "home": str(HOME),
        "separate": HOME != ROOT.resolve(),
        "data": str(settings.data_path),
        "storage": str(settings.storage_path),
    }
