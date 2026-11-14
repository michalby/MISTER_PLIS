"""Who may change what — and, once the lab has accounts, who may use the server at all (docs/SECURITY_AUDIT.md §7).

Every route that changes something says which kind of change it is, with one dependency:

* ``settings_access`` — the lab's settings: Settings, the setup page, tool sources, moving the server, updates…
* ``work_access`` — the lab's everyday work: running tools, naming jobs, printing labels, the modules' own entries…

``tests/test_access.py`` fails when a route that changes something has no mark.

**Two modes** (:func:`mode`): until the lab makes its first account (mister_plis/accounts.py), the server is **open**,
as it always was: everyone on the lab's network may do everything, and a person is the name typed in the top bar.
Once there is an account, **sign-in** is on: every page and request needs a signed-in person (the app's middleware,
:data:`PUBLIC` lists the few exceptions), :func:`current` is the signed-in account, and only an account with the role
``admin`` may change the lab's settings.

Besides that, two checks run for everyone: a request must use one of the server's own names (:func:`known_host`), and
a change must come from the server's own pages (:func:`same_site`), never from another web site a lab member happens to
have open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from .i18n import tr
from .prefs import from_cookies

ROLES = ("admin", "member")  # admin: may change Settings; member: the everyday work only

# Whether the lab has accounts (set by the app: mister_plis/accounts.py). No account: the server is open, as before.
has_accounts: Callable[[], bool] = lambda: False
# Writes a line to the activity log (set by the app): (who, what, from where)
audit: Callable[[str, str, str], None] = lambda who, what, where: None

# What a person who isn't signed in may still reach: the sign-in page, the files every page loads, the server's version
# (the health check).
PUBLIC = ("/login", "/api/login", "/api/logout", "/static/", "/i18n/", "/vendor/", "/favicon", "/api/version")


def mode() -> str:
    """"open" (no accounts yet: everyone may do everything) or "accounts" (sign-in)."""
    return "accounts" if has_accounts() else "open"


def is_public(path: str) -> bool:
    if path.startswith(PUBLIC):
        return True
    parts = path.split("/")
    return len(parts) > 3 and parts[1] == "m" and parts[3] == "static"  # a module's own files: /m/<id>/static/…


@dataclass(frozen=True)
class Person:
    name: str  # the signed-in account's name; with no accounts, the name typed in the top bar
    role: str  # "admin" or "member"
    signed_in: bool = False
    account: str = ""  # the account's permanent id (accounts.py), "" without accounts


def current(request: Request) -> Person:
    """The person behind a request: the signed-in account (set by the app's middleware), else — while the lab has no
    accounts — everyone, as an admin, under the name in their browser."""
    person = request.scope.get("mp_person")
    if isinstance(person, Person):
        return person
    if mode() == "accounts":
        return Person(name="", role="nobody")
    return Person(name=from_cookies(request.cookies)["name"], role="admin")


def where(request: Request) -> str:
    return getattr(request.client, "host", "") or ""


def settings_access(request: Request) -> Person:
    """For a route that changes the lab's settings (or shows what only admins see): 403 for anyone else. A change is
    written to the activity log."""
    person = current(request)
    if person.role != "admin":
        raise HTTPException(403, tr("Only someone who may change the lab's settings can do this."))
    if request.method in UNSAFE:
        audit(person.name, f"{request.method} {request.url.path}", where(request))
    return person


def work_access(request: Request) -> Person:
    """For a route that is the lab's everyday work: everyone who may use the server."""
    person = current(request)
    if person.role not in ROLES:
        raise HTTPException(401, tr("Sign in first."))
    return person


def public_access(request: Request) -> None:
    """For the few routes that change something and need no signed-in person: signing in and out."""
    return None


settings_access.access = "settings"  # how tests/test_access.py recognises the marks
work_access.access = "work"
public_access.access = "public"

# ---- which names this server answers to (docs/SECURITY_AUDIT.md H1) ------------------------------------------------
# A web page elsewhere can point a name of its own at this server's address ("DNS rebinding") and then talk to it as if
# it were that page's own site — past same_site(), which compares the page with the name it used. So a request must
# use a name this server knows: an IP address, localhost, this computer's own names, or one the lab added
# ([server] names in a lab file, Settings → Server & updates; ``server_names`` in config.toml). "*" turns the check off.

# The names the lab and this machine added (set by the app: the lab's settings, then config.toml).
extra_names: Callable[[], list[str]] = lambda: []


def bare_host(host: str) -> str:
    """``Example.org:8000`` → ``example.org``; ``[::1]:8000`` → ``::1``."""
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host[1:]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def _is_ip(name: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(name.split("%", 1)[0])
        return True
    except ValueError:
        return False


_own: frozenset[str] = frozenset()
_own_at = -1e9  # when _own was worked out (time.monotonic)
_dns_names: frozenset[str] = frozenset()  # what the network's DNS calls this computer's addresses (found in a thread)
_dns_busy = False
OWN_NAMES_EVERY = 300  # seconds: a Mac renamed, or given another address, is noticed within this


def _local_names() -> set[str]:
    """The names this computer gives itself: its host name (with and without its domain), ``<name>.local``, and on a
    Mac the Bonjour name (System Settings → Sharing → Local hostname), which is what the lab's browsers use."""
    import socket
    import subprocess
    import sys

    names = {"localhost"}
    for n in (socket.gethostname(),):
        n = (n or "").strip().lower().rstrip(".")
        if n and n != "localhost":
            names |= {n, n.split(".", 1)[0], n.split(".", 1)[0] + ".local"}
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=2)
            if r.stdout.strip():
                names.add(r.stdout.strip().lower() + ".local")
        except (OSError, subprocess.SubprocessError):
            pass
    return names


def _addresses() -> set[str]:
    """This computer's IP addresses on the network (not loopback): those its name has, and the one it reaches the
    network from (found by asking the system for a route; nothing is sent)."""
    import socket

    found = set()
    try:
        found |= {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)}
    except OSError:
        pass
    for family, probe in ((socket.AF_INET, "192.0.2.1"), (socket.AF_INET6, "2001:db8::1")):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as sk:
                sk.connect((probe, 9))
                found.add(sk.getsockname()[0])
        except OSError:
            pass
    return {a.split("%", 1)[0] for a in found if not a.startswith(("127.", "::1"))}


def _look_up_dns_names() -> None:
    """The names the network's DNS gives this computer's addresses (e.g. ``mac-studio.biol.uni.example``): a name
    someone typed that is one of these is this server's, set by whoever runs the network — never by a web page
    elsewhere, which can only point names of its own at an address. Runs in a thread: a slow DNS server mustn't hold up
    a request."""
    global _dns_names, _dns_busy
    import socket

    names = set()
    try:
        fqdn = socket.getfqdn().strip().lower().rstrip(".")
        if fqdn and "." in fqdn and fqdn != "localhost":
            names.add(fqdn)
        for ip in _addresses():
            try:
                host, aliases, _ = socket.gethostbyaddr(ip)
            except OSError:
                continue
            names |= {n.strip().lower().rstrip(".") for n in (host, *aliases) if n and n.strip().lower() != "localhost"}
        _dns_names = frozenset(names)
    finally:
        _dns_busy = False


def network_addresses() -> list[str]:
    """This computer's IP addresses on the network (what other devices reach it by), sorted."""
    return sorted(_addresses())


def own_names() -> frozenset[str]:
    """This computer's own names: localhost, the names it gives itself (:func:`_local_names`) and the names the
    network's DNS gives its addresses (:func:`_look_up_dns_names`, found in the background). Worked out again every
    few minutes, so a renamed Mac is still found."""
    global _own, _own_at, _dns_busy
    import threading
    import time

    now = time.monotonic()
    if now - _own_at > OWN_NAMES_EVERY:
        _own_at = now
        _own = frozenset(_local_names())
        if not _dns_busy:
            _dns_busy = True
            threading.Thread(target=_look_up_dns_names, daemon=True, name="own-names").start()
    return _own | _dns_names


def known_host(host: str) -> bool:
    """Whether a request's ``Host`` is a name of this server (see above). A request without one (HTTP/1.0) passes:
    a browser always sends it."""
    name = bare_host(host)
    if not name or _is_ip(name) or name in own_names():
        return True
    extra = {bare_host(n) for n in extra_names()}
    return "*" in extra or name in extra


def unknown_host(request: Request) -> str | None:
    """The name a request used that this server doesn't know (``Host``, or ``X-Forwarded-Host`` from a proxy), else None."""
    names = [request.headers.get("host", "")]
    names += [h for h in request.headers.get("x-forwarded-host", "").split(",") if h.strip()]
    return next((bare_host(h) for h in names if not known_host(h)), None)


UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def same_site(request: Request) -> bool:
    """Whether a request that changes something comes from this server's own pages (or from no page at all: curl,
    the command line). Browsers say where a request comes from (``Sec-Fetch-Site``, ``Origin``); a request another
    site's page sends to the server is refused, so a page elsewhere can't restart the server or cancel a job."""
    if request.method not in UNSAFE:
        return True
    fetch_site = request.headers.get("sec-fetch-site", "")
    if fetch_site == "cross-site":
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return fetch_site in ("", "same-origin", "none")
    if origin == "null":
        return False
    there = urlsplit(origin).netloc.lower()
    here = {h.strip().lower() for h in (request.headers.get("host", ""), request.headers.get("x-forwarded-host", ""))
            for h in h.split(",") if h.strip()}
    return bool(there) and there in here
