"""Stored files from an origin of their own (docs/SECURITY_AUDIT.md, "Later").

The files people and tools keep (a job's inputs and results, Time Machine's copies) are served sandboxed and, where
they could run anything, only downloaded (mister_plis/serving.py). As one more wall, the pages also get them from a
**second address**: a small server in the same program, listening on its own port (``files_port``, by default the
app's port + 1), that serves nothing but these files. Even if something in a file did run, it would run on an origin
that holds none of the app's pages, data or API — the browser keeps the two apart. There, HTML and SVG files can be
shown too (sandboxed: a tool's HTML report can be read instead of downloaded).

**Links, not sign-in.** That server knows no one: a page gets, with a job, a signed link to that job's folder
(``files_base``: ``<origin>/f/<token>/``), valid for :data:`TTL` and for that folder only. The token is made with a
key only this instance has (``<instance>/secrets/files-key``).

**Where it is.** ``files_origin`` in config.toml: "" (the default) — the same host as the page, ``files_port``, plain
HTTP; "off" — no second address; or the address a proxy gives it (``https://files.mister-plis.lab.example``: HTTPS,
docs/DEPLOY_LINUX.md). If a browser can't reach it (a firewall closed that port; a page on HTTPS and the second address
on HTTP), the pages notice and use the app's own links, which still work, sandboxed as before (static/js/app.js,
``MP.filesReady``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from . import serving
from .config import settings

TTL = 2 * 3600  # how long a link to a job's files works
KEY_FILE = "files-key"
listening = False  # whether this process's files server listens (set by serve())
_key: bytes | None = None
_key_lock = threading.Lock()
# the folders links may point into: the storage folder (jobs, Time Machine) and the data folder
ROOTS = {"storage": lambda: settings.storage_path, "data": lambda: settings.data_path}


def key() -> bytes:
    """This instance's key for the links (made once, readable by the server's user only)."""
    global _key
    with _key_lock:
        if _key is None:
            path = settings.secrets_path / KEY_FILE
            try:
                _key = bytes.fromhex(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                path.parent.mkdir(parents=True, exist_ok=True)
                fresh = secrets.token_bytes(32)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(fresh.hex())
                _key = fresh
        return _key


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(root: str, folder: str, ttl: float = TTL) -> str:
    body = _b64(json.dumps({"r": root, "p": folder, "e": int(time.time() + ttl)}, separators=(",", ":")).encode())
    return f"{body}.{_b64(hmac.new(key(), body.encode(), hashlib.sha256).digest())}"


def verify(token: str) -> tuple[str, str] | None:
    """(root, folder) a token points into, or None (made with another key, changed, or expired)."""
    body, _, sig = str(token).partition(".")
    if not body or not sig:
        return None
    good = _b64(hmac.new(key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        d = json.loads(_unb64(body))
    except ValueError:
        return None
    if not isinstance(d, dict) or d.get("r") not in ROOTS or not isinstance(d.get("p"), str) or float(d.get("e", 0)) < time.time():
        return None
    return d["r"], d["p"]


def token_for(folder: Path) -> str | None:
    """A token for ``folder`` (inside the storage or the data folder), else None."""
    try:
        folder = Path(folder).resolve()
    except OSError:
        return None
    for name, root in ROOTS.items():
        base = root().resolve()
        if folder == base or base in folder.parents:
            return sign(name, folder.relative_to(base).as_posix())
    return None


def origin_for(request) -> str:
    """The files' origin as this page's browser reaches it, "" when there is none."""
    chosen = (settings.files_origin or "").strip().rstrip("/")
    if chosen.lower() == "off":
        return ""
    if chosen:
        return chosen
    if not listening or request.url.scheme != "http":  # a page on HTTPS can't show pictures from plain HTTP
        return ""
    host = request.url.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{files_port()}" if host else ""


def files_port() -> int:
    return settings.files_port or settings.port + 1


def files_base(request, folder: Path) -> str:
    """``<origin>/f/<token>/``: where the page gets ``folder``'s files (append a file's path inside it), "" if nowhere
    else than the app itself."""
    origin = origin_for(request)
    token = token_for(folder) if origin else None
    return f"{origin}/f/{token}/" if token else ""


# ---- the files' own server ----------------------------------------------------------------------------------------

files_app = FastAPI(title="MISTER PLIS files", docs_url=None, redoc_url=None, openapi_url=None)
PING = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")  # a 1×1 GIF


@files_app.middleware("http")
async def _headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")  # a file's own links don't reveal its signed address
    response.headers.setdefault("Content-Security-Policy", serving.SANDBOX)
    return response


@files_app.get("/ping.gif")
def _ping():
    """Lets a page check that it can reach this server (MP.filesReady)."""
    return Response(PING, media_type="image/gif", headers={"Cache-Control": "no-store"})


@files_app.get("/f/{token}/{rel:path}")
def _file(token: str, rel: str, download: bool = False):
    where = verify(token)
    if where is None:
        raise HTTPException(403, "This link has expired or isn't valid: open the result again in MISTER PLIS.")
    folder = (ROOTS[where[0]]() / where[1]).resolve()
    path = (folder / rel).resolve()
    if folder not in path.parents or not path.is_file():
        raise HTTPException(404, "File not found")
    return serving.stored_file(path, download, apart=True)


def serve(host: str, port: int) -> bool:
    """Start the files' server in a thread of this process (the app's own server stays in the main thread). False when
    its port can't be had: the pages then use the app's own links."""
    global listening
    import uvicorn

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
    except OSError as e:
        sock.close()
        print(f"  The files' own address (port {port}) isn't free: {e} — files come from the app's address.", flush=True)
        return False
    sock.set_inheritable(True)
    server = uvicorn.Server(uvicorn.Config(files_app, log_level="warning", proxy_headers=False))
    threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True, name="files-origin").start()
    listening = True
    return True
