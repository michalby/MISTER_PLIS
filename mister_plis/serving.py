"""Serving the files people and tools stored (job files, Time Machine's files) so they can't run anything in the app's
pages (docs/SECURITY_AUDIT.md H2), and the headers every response carries (M1).

A file someone uploaded is served from the app's own address. Shown in the browser, an HTML or SVG file would run its
scripts as the app — with the rights of whoever opens it. So only kinds a browser shows without running anything
(pictures, PDF, text, audio, video) open in the browser; everything else is downloaded. Those shown are sandboxed too
(no scripts, no forms), and no browser may guess another kind from the file's contents (``nosniff``).
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.responses import FileResponse

# suffix → the kind it is shown as (anything else is downloaded)
SHOWN = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".bmp": "image/bmp", ".avif": "image/avif",
    ".pdf": "application/pdf",
    ".txt": "text/plain", ".log": "text/plain", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".md": "text/markdown", ".json": "application/json",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".m4v": "video/mp4",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
}
# A shown file may hold nothing that runs. A PDF is left to the browser's own viewer, which a sandbox would block.
SANDBOX = "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; sandbox; frame-ancestors 'none'"

# On every response (unless it says otherwise): no other site may show the app's pages inside its own (clickjacking),
# no browser guesses a file's kind, and addresses inside the app aren't sent to other sites.
HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
# The pages' own policy (docs/SECURITY_AUDIT.md "Later"): scripts only from the server's own files — never inline, never
# from elsewhere —, so a piece of HTML that slips into a page (a tool's HTML result, a crafted name) can't run anything.
# Styles may be inline (the charts set their own); pictures may be data:/blob: (charts, label previews) or https: (the
# pictures a module shows from the web); nothing may be sent anywhere but here.
PAGE_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
               "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
               "frame-ancestors 'none'")
FRAME_POLICY = "frame-ancestors 'none'"  # for /api/docs (when on: its page loads scripts from a CDN)


def page_policy(files_origin: str = "") -> str:
    """:data:`PAGE_POLICY`, with the address the pages' pictures and videos come from when stored files are served from
    an origin of their own (mister_plis/fileorigin.py)."""
    if not files_origin:
        return PAGE_POLICY
    return (PAGE_POLICY.replace("img-src 'self' ", f"img-src 'self' {files_origin} ")
            .replace("default-src 'self';", f"default-src 'self'; media-src 'self' {files_origin};"))


HSTS = "max-age=15552000"  # half a year: a browser that reached the server over HTTPS never falls back to plain HTTP


def add_headers(headers, https: bool = False, policy: str = PAGE_POLICY) -> None:
    """Add :data:`HEADERS` (and :data:`PAGE_POLICY`, when the response has no policy of its own) to a response's
    headers; over HTTPS (behind a proxy that says so: ``trusted_proxies``) also Strict-Transport-Security."""
    if https and "strict-transport-security" not in headers:
        headers["Strict-Transport-Security"] = HSTS
    for k, v in HEADERS.items():
        if k not in headers:
            headers[k] = v
    if "content-security-policy" not in headers:
        headers["Content-Security-Policy"] = policy


# On the files' own origin (fileorigin.py) these are shown too — sandboxed, so nothing in them runs, and on an origin
# that holds nothing of the app's even if something did: a tool's HTML report can be read in the browser.
SHOWN_APART = {".html": "text/html", ".htm": "text/html", ".svg": "image/svg+xml", ".xml": "text/xml"}


def stored_file(path: Path, download: bool = False, apart: bool = False) -> FileResponse:
    """A stored file for the browser: shown (a kind in :data:`SHOWN`, sandboxed) unless ``download``; anything else
    always downloaded. ``apart``: served from the files' own origin, where HTML and SVG are shown too, sandboxed."""
    kind = SHOWN.get(path.suffix.lower()) or (SHOWN_APART.get(path.suffix.lower()) if apart else None)
    headers = {"X-Content-Type-Options": "nosniff"}
    if kind and not download:
        if kind.startswith("text/") or kind == "application/json":
            kind += "; charset=utf-8"
        if kind != "application/pdf":
            headers["Content-Security-Policy"] = SANDBOX
        return FileResponse(path, media_type=kind, filename=path.name, content_disposition_type="inline", headers=headers)
    headers["Content-Security-Policy"] = SANDBOX
    return FileResponse(path, media_type="application/octet-stream" if not kind else kind, filename=path.name,
                        content_disposition_type="attachment", headers=headers)


# ---- links (docs/SECURITY_AUDIT.md M2) --------------------------------------------------------------------------------
# A link people or tools give (a feedback's page, an inventory URL field, a catalogue's homepage, a link in a result's
# Markdown) must not run anything when clicked: "javascript:…" would run in the app's page. Browsers ignore tabs, line
# breaks and leading spaces inside a scheme ("java\tscript:"), so those go before the scheme is read.
_SCHEME = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.I)
_IGNORED = re.compile(r"[\x00-\x20\x7f]")


def safe_link(url: str, schemes: tuple = ("http", "https", "mailto")) -> bool:
    """Whether ``url`` is safe as a link: an address inside the app (``/…``, ``#…``, ``?…``, a relative path) or one with
    a scheme in ``schemes``."""
    m = _SCHEME.match(_IGNORED.sub("", str(url or "")))
    return m is None or m.group(1).lower() in schemes


def web_link(url: str) -> bool:
    """Whether ``url`` is empty or an ``http(s)://`` address (a link that leaves the app)."""
    url = str(url or "").strip()
    return not url or bool(re.match(r"^https?://", url, re.I)) and safe_link(url)
