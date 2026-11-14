"""The setup code: who may set up a new server (docs/SECURITY_AUDIT.md M4).

A server that isn't set up yet (lab.json says "new") would belong to whoever opens its setup page first — including
choosing its tool sources, which run code on it. So until it is set up, a change needs this server's **setup code**:
eight letters and digits it makes once (``<instance>/secrets/setup-code``) and prints when it starts, and which
``python -m mister_plis setup-code`` shows again on the server. Entered on the setup page, it is kept in a cookie for
that browser. Someone working on the server's own computer (``localhost``, the Mac app) needs no code: being there is
proof enough.

The same code makes the lab's **first account** (mister_plis/accounts.py), which turns sign-in on — on a new server or
on one set up before accounts existed. It is kept until that account exists (:func:`relevant`); then it is gone, and
the accounts decide who may change what.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from .config import settings

FILE_NAME = "setup-code"
COOKIE = "mp_setup"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: read off a screen and typed
FORWARDED = ("x-forwarded-for", "forwarded", "x-real-ip")


def path() -> Path:
    return settings.secrets_path / FILE_NAME


def _clean(text: str) -> str:
    return "".join(c for c in str(text or "").upper() if c.isalnum())


def current() -> str:
    """The code ("ABCD-EFGH"), or "" when there is none."""
    try:
        return path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ensure() -> str:
    """The code, made the first time (kept in secrets/, readable by the server's user only)."""
    code = current()
    if code:
        return code
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    code = f"{raw[:4]}-{raw[4:]}"
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(code + "\n")
    return code


def relevant() -> bool:
    """Whether the server still has a use for its code: it isn't set up yet, or it has no account yet."""
    from . import labsetup
    from .accounts import Accounts

    return labsetup.is_new() or not Accounts(settings.data_path, settings.secrets_path).any()


def forget() -> None:
    """The first account exists: the code is no longer needed."""
    try:
        path().unlink()
    except OSError:
        pass


def matches(text: str) -> bool:
    code = _clean(current())
    return bool(code) and hmac.compare_digest(_clean(text).encode(), code.encode())


def from_this_computer(request) -> bool:
    """A request made on the server's own computer, not passed on by a proxy (a proxy on the same computer would make
    every request look local; it says whom it passes on, so such a request isn't counted as local)."""
    host = getattr(request.client, "host", "") or ""
    local = host == "::1" or host.startswith("127.") or host == "localhost"
    return local and not any(h in request.headers for h in FORWARDED)


def needed(request) -> bool:
    """Whether ``request`` may change nothing yet: the server isn't set up, and it brings neither the code nor comes
    from the server's own computer."""
    from . import labsetup

    if not labsetup.is_new() or from_this_computer(request):
        return False
    return not matches(request.cookies.get(COOKIE, ""))
