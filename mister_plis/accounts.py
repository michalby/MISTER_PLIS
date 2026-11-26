"""The lab's accounts: who may use this server, and who may change its settings (docs/SECURITY_AUDIT.md §7).

- **Accounts** (``<data>/accounts.json``, :data:`FORMAT`): a name, a role (``admin``: may change Settings; ``member``:
  the everyday work), a password kept only as a scrypt hash. In the data folder, so a moved server keeps them; left out
  of the settings snapshots made before updates, so going back never brings back a removed account or an old password.
- **Sessions** (``<instance>/secrets/sessions.json``): a signed-in browser holds a random key in a cookie; only its
  SHA-256 is kept. A session ends when its person signs out, after :data:`IDLE_DAYS` without use, or when the account
  is removed or its password is changed.
- **The activity log** (``<data>/audit.log``): sign-ins, accounts made and changed, and every change to the lab's
  settings — who, when, from where. One JSON object a line; the newest :data:`AUDIT_MAX_BYTES` are kept.

Sign-in is **off** until the first account (an admin) is made: then the server is open, as before accounts existed
(``access.mode()`` "open"). Making that first account needs the server's setup code, or being on its own computer
(mister_plis/setupcode.py). From then on every page and every request needs a signed-in person (access.py).

A person's **name** is their account's: what the server records for jobs, Time Machine, the inventory and feedback, as
the name typed in the top bar was before. Each account also has a permanent **id**, stored with every job its person
runs (from 0.15.0), so a job belongs to the account, not just to a spelling. Renaming an account renames everything
under its name; a person's earlier names (typed before there were accounts, "Ola" for "Aleksandra Nowak") can be
attached to their account, which moves what was under them to it. Accounts start from the names the lab already uses.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from .errors import ToolError

FORMAT = 1  # accounts.json (docs/FORMATS.md)
ROLES = ("admin", "member")
MIN_PASSWORD = 8
IDLE_DAYS = 30  # a session not used for this long ends
SEEN_EVERY = 300  # seconds: how often a session's "last used" is written
COOKIE = "mp_session"
AUDIT_MAX_BYTES = 5 * 1024 * 1024
# scrypt: 16 MB of memory a try — slow for someone guessing, quick enough for one sign-in
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def _now() -> float:
    return time.time()


def _write_private(path: Path, data: dict) -> None:
    """Write JSON readable by the server's user only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read(path: Path, key: str) -> list[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = d.get(key) if isinstance(d, dict) else None
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


# ---- passwords ----------------------------------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, maxmem=64 * 1024 * 1024, **SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${b64(salt)}${b64(digest)}"


def check_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = str(stored).split("$")
        if kind != "scrypt":
            return False
        want = base64.b64decode(digest)
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(want), maxmem=128 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


_DUMMY = None


def _waste_time(password: str) -> None:
    """As long as checking a real password: a name that has no account can't be told apart by the answer's speed."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not a password")
    check_password(password, _DUMMY)


def check_new_password(password: str) -> str:
    password = str(password or "")
    if len(password) < MIN_PASSWORD:
        raise ToolError("A password needs at least 8 characters.")
    if len(password) > 200:
        raise ToolError("That password is too long (200 characters at most).")
    return password


def temporary_password() -> str:
    """A password to hand over once (an account made or reset by an admin); its person chooses their own at sign-in."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


# ---- accounts -----------------------------------------------------------------------------------------------------

def clean_name(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ToolError("Give the person's name, as it appears on their results.")
    if len(name) > 60:
        raise ToolError("A name can be 60 characters at most.")
    return name


class Accounts:
    def __init__(self, data_path: Path, secrets_path: Path):
        self.file = data_path / "accounts.json"
        self.sessions_file = secrets_path / "sessions.json"
        self.audit_file = data_path / "audit.log"
        self.lock = threading.RLock()
        self._sessions: list[dict] | None = None  # cached (checked on every request)
        self._cache: tuple[float, list[dict]] | None = None  # (file's mtime, accounts)

    # ---- the accounts file ----
    def _all(self) -> list[dict]:
        try:
            mtime = self.file.stat().st_mtime_ns
        except OSError:
            return []
        if self._cache and self._cache[0] == mtime:
            return self._cache[1]
        items = [a for a in _read(self.file, "accounts") if a.get("name") and a.get("role") in ROLES]
        if any(not a.get("id") for a in items):  # accounts from 0.14.0: given their id once
            with self.lock:
                for a in items:
                    if not a.get("id"):
                        a["id"] = secrets.token_hex(8)
                self._save(items)
            return self._all()
        self._cache = (mtime, items)
        return items

    def _save(self, items: list[dict]) -> None:
        _write_private(self.file, {"format": FORMAT, "accounts": items})
        self._cache = None

    def any(self) -> bool:
        return bool(self._all())

    def get(self, name: str) -> dict | None:
        key = " ".join(str(name or "").split()).casefold()
        return next((a for a in self._all() if a["name"].casefold() == key), None)

    def by_id(self, account_id: str) -> dict | None:
        return next((a for a in self._all() if account_id and a.get("id") == account_id), None)

    def list(self) -> list[dict]:
        """The accounts for the page: never a password's hash."""
        return [{**{k: a.get(k) for k in ("id", "name", "role", "created", "created_by", "last_sign_in", "must_change")},
                 "names": list(a.get("names") or [])}
                for a in sorted(self._all(), key=lambda a: a["name"].casefold())]

    def admins(self) -> int:
        return sum(a["role"] == "admin" for a in self._all())

    def create(self, name: str, role: str = "member", password: str | None = None, by: str = "") -> str:
        """A new account; returns its first password (``password``, or a temporary one its person replaces)."""
        name = clean_name(name)
        if role not in ROLES:
            raise ToolError("Choose admin or member.")
        temporary = password is None
        password = temporary_password() if temporary else check_new_password(password)
        with self.lock:
            items = list(self._all())
            if any(a["name"].casefold() == name.casefold() for a in items):
                raise ToolError("There is an account with that name already.")
            items.append({"id": secrets.token_hex(8), "name": name, "role": role, "password": hash_password(password),
                          "created": _now(), "created_by": by, "last_sign_in": None, "must_change": temporary, "names": []})
            self._save(items)
        self.audit(by, f"made the account {name} ({role})")
        return password

    def _change(self, account_name: str, **changes) -> dict:
        with self.lock:
            items = [dict(a) for a in self._all()]
            hit = next((a for a in items if a["name"].casefold() == str(account_name).casefold()), None)
            if hit is None:
                raise ToolError("There is no such account.")
            hit.update(changes)
            self._save(items)
            return hit

    def set_role(self, name: str, role: str, by: str = "") -> None:
        if role not in ROLES:
            raise ToolError("Choose admin or member.")
        acct = self.get(name)
        if acct and acct["role"] == "admin" and role != "admin" and self.admins() <= 1:
            raise ToolError("The lab needs at least one admin: make someone else an admin first.")
        self._change(name, role=role)
        self.audit(by, f"made {name} {role}")

    def remove(self, name: str, by: str = "") -> None:
        acct = self.get(name)
        if acct is None:
            raise ToolError("There is no such account.")
        if acct["role"] == "admin" and self.admins() <= 1:
            raise ToolError("The lab needs at least one admin: make someone else an admin first.")
        with self.lock:
            self._save([a for a in self._all() if a["name"].casefold() != acct["name"].casefold()])
        self.end_sessions(acct["name"])
        self.audit(by, f"removed the account {acct['name']} (their results stay)")

    def rename(self, name: str, new: str, by: str = "") -> dict:
        """The account's new name (its id stays). The caller moves what is stored under the old name (the app's
        rename_person). Its sessions carry on under the new name."""
        new = clean_name(new)
        acct = self.get(name)
        if acct is None:
            raise ToolError("There is no such account.")
        other = self.get(new)
        if other is not None and other["id"] != acct["id"]:
            raise ToolError("There is an account with that name already.")
        old = acct["name"]
        names = [n for n in acct.get("names") or [] if n.casefold() != new.casefold()]
        if old.casefold() != new.casefold():
            names.append(old)
        hit = self._change(old, name=new, names=names)
        with self.lock:
            for s in self._load_sessions():
                if s.get("name", "").casefold() == old.casefold():
                    s["name"] = new
            self._save_sessions()
        self.audit(by, f"renamed the account {old} to {new}")
        return hit

    def add_name(self, name: str, earlier: str, by: str = "") -> dict:
        """Remember that ``earlier`` (a name typed before there were accounts) is this account's person. The caller
        moves what is stored under it."""
        acct = self.get(name)
        if acct is None:
            raise ToolError("There is no such account.")
        earlier = clean_name(earlier)
        if self.get(earlier) is not None:
            raise ToolError("That is another account's name: an account's name can't be attached to another account.")
        names = [n for n in acct.get("names") or [] if n.casefold() != earlier.casefold()] + [earlier]
        hit = self._change(acct["name"], names=names)
        self.audit(by, f"attached the earlier name {earlier} to {acct['name']}")
        return hit

    def reset_password(self, name: str, by: str = "") -> str:
        """A temporary password for someone who forgot theirs; their sessions end. Returns it (shown once)."""
        password = temporary_password()
        acct = self._change(name, password=hash_password(password), must_change=True)
        self.end_sessions(acct["name"])
        self.audit(by, f"reset the password of {acct['name']}")
        return password

    def set_password(self, name: str, new: str, old: str | None = None, keep: str = "") -> None:
        """A person's own new password (``old``: theirs, checked). Their other sessions end (``keep``: this one)."""
        acct = self.get(name)
        if acct is None:
            raise ToolError("There is no such account.")
        if old is not None and not check_password(str(old), acct["password"]):
            raise ToolError("That isn't your current password.")
        new = check_new_password(new)
        if old is not None and new == old:
            raise ToolError("Choose a new password, not the one you have.")
        self._change(acct["name"], password=hash_password(new), must_change=False)
        self.end_sessions(acct["name"], keep=keep)
        self.audit(acct["name"], "changed their password")

    def verify(self, name: str, password: str) -> dict | None:
        """The account, if ``password`` is its password (the time taken is the same either way)."""
        acct = self.get(name)
        if acct is None:
            _waste_time(str(password or ""))
            return None
        return acct if check_password(str(password or ""), acct["password"]) else None

    def signed_in(self, name: str) -> None:
        self._change(name, last_sign_in=_now())

    # ---- sessions ----
    def _load_sessions(self) -> list[dict]:
        if self._sessions is None:
            self._sessions = _read(self.sessions_file, "sessions")
        return self._sessions

    def _save_sessions(self) -> None:
        _write_private(self.sessions_file, {"format": FORMAT, "sessions": self._sessions or []})

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    def start_session(self, name: str) -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        with self.lock:
            live = [s for s in self._load_sessions() if now - s.get("seen", 0) < IDLE_DAYS * 86400]
            live.append({"key": self._key(token), "name": name, "started": now, "seen": now})
            self._sessions = live
            self._save_sessions()
        return token

    def session(self, token: str) -> dict | None:
        """The account a session key belongs to (None: no such session, ended, or its account is gone)."""
        if not token:
            return None
        key, now = self._key(token), _now()
        with self.lock:
            s = next((s for s in self._load_sessions() if hmac.compare_digest(s.get("key", ""), key)), None)
            if s is None:
                return None
            if now - s.get("seen", 0) > IDLE_DAYS * 86400:
                self._sessions = [x for x in self._sessions if x is not s]
                self._save_sessions()
                return None
            if now - s.get("seen", 0) > SEEN_EVERY:
                s["seen"] = now
                self._save_sessions()
        return self.get(s["name"])

    def end_session(self, token: str) -> None:
        key = self._key(token)
        with self.lock:
            self._sessions = [s for s in self._load_sessions() if s.get("key") != key]
            self._save_sessions()

    def end_sessions(self, name: str, keep: str = "") -> None:
        keep_key = self._key(keep) if keep else ""
        with self.lock:
            self._sessions = [s for s in self._load_sessions()
                              if s.get("name", "").casefold() != name.casefold() or s.get("key") == keep_key]
            self._save_sessions()

    # ---- the activity log ----
    def audit(self, who: str, what: str, where: str = "") -> None:
        line = json.dumps({"at": _now(), "who": who or "", "what": what, "from": where}, ensure_ascii=False)
        with self.lock:
            try:
                self.audit_file.parent.mkdir(parents=True, exist_ok=True)
                if self.audit_file.exists() and self.audit_file.stat().st_size > AUDIT_MAX_BYTES:
                    os.replace(self.audit_file, self.audit_file.with_name("audit.log.1"))  # the one before is dropped
                fd = os.open(self.audit_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)  # the server's eyes only
                with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as f:
                    f.write(line + "\n")
            except OSError:  # pragma: no cover - a full disk must not stop a sign-in
                pass

    def activity(self, limit: int = 200) -> list[dict]:
        """The newest entries of the activity log, newest first."""
        try:
            lines = self.audit_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in reversed(lines[-limit:]):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


class Throttle:
    """Slows down guessing: after a few failed sign-ins from one address, or for one name, more wait first."""

    WINDOW = 15 * 60
    FREE = 5  # failures in the window before anything is refused
    LIMIT = 20

    def __init__(self):
        self.failures: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        return [t for t in self.failures.get(key, []) if now - t < self.WINDOW]

    def blocked(self, *keys: str) -> bool:
        now = _now()
        with self.lock:
            return any(len(self._recent(k, now)) >= self.LIMIT for k in keys)

    def failed(self, *keys: str) -> float:
        """Count a failure; returns how long to wait before answering (seconds)."""
        now = _now()
        with self.lock:
            worst = 0
            for k in keys:
                recent = self._recent(k, now) + [now]
                self.failures[k] = recent
                worst = max(worst, len(recent))
        return 0.5 if worst <= self.FREE else min(5.0, 0.5 * (worst - self.FREE))

    def succeeded(self, *keys: str) -> None:
        with self.lock:
            for k in keys:
                self.failures.pop(k, None)
