"""Per-browser settings (Settings page). Each one is a cookie, so the server can use them too:
pages are drawn in the chosen theme and jobs format numbers and Excel files the way the person asked.

The current request's (or running job's) settings are in ``current_prefs`` — tool code can simply call
``pref("decimal")``.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Callable, Mapping
from urllib.parse import unquote

# name → (default, allowed values)
PREFS: dict[str, tuple[str, tuple[str, ...]]] = {
    "lang": ("en", ("en", "pl")),  # interface language (top bar switch); see mister_plis/i18n.py. Files are always English
    "theme": ("auto", ("auto", "light", "dark")),
    "decimal": ("dot", ("dot", "comma")),  # numbers shown on screen
    "xlsx_numbers": ("number", ("number", "dot", "comma")),  # numbers in .xlsx / .csv downloads
    "plot_scale": ("3", ("2", "3", "4", "6")),  # PNG export of plots, × screen size
    "remember_inputs": ("on", ("on", "off")),  # tool forms keep their last values
}
TEXT_PREFS = {"name": 60}  # free text → longest allowed; "name" is who appears on PDF reports
DEFAULTS = {**{k: v[0] for k, v in PREFS.items()}, **{k: "" for k in TEXT_PREFS}}

current_prefs: ContextVar[dict] = ContextVar("prefs", default=DEFAULTS)
# The signed-in account's name for this request (set by the app once the lab has accounts: mister_plis/accounts.py). It is
# who the person is — on their jobs, PDFs, Time Machine… —, whatever name their browser's cookie says.
signed_in_name: ContextVar[str | None] = ContextVar("signed_in_name", default=None)
# …and their account's permanent id ("" without accounts), stored with each job they run (mister_plis/jobs.py)
signed_in_account: ContextVar[str] = ContextVar("signed_in_account", default="")

# A name merged into another one (Settings → People) is read as the kept one; set by the app.
canonical_name: Callable[[str], str] = lambda name: name
# The lab's language for a browser that hasn't chosen one (set on the setup page or by a lab file); set by the app.
lab_language: Callable[[], str] = lambda: ""


def from_cookies(cookies: Mapping[str, str]) -> dict:
    """Valid settings from the request cookies, defaults for the rest."""
    out = {k: (cookies.get(k) if cookies.get(k) in allowed else default) for k, (default, allowed) in PREFS.items()}
    if cookies.get("lang") not in PREFS["lang"][1]:
        try:
            lang = lab_language()
        except Exception:  # pragma: no cover - a broken settings file must not break every page
            lang = ""
        out["lang"] = lang if lang in PREFS["lang"][1] else out["lang"]
    for k, limit in TEXT_PREFS.items():
        try:
            out[k] = " ".join(unquote(cookies.get(k) or "").split())[:limit]
        except ValueError:
            out[k] = ""
    account = signed_in_name.get()
    out["name"] = account if account is not None else canonical_name(out["name"])
    return out


def pref(name: str) -> str:
    return current_prefs.get().get(name, DEFAULTS[name])


def decimal_mark(setting: str = "decimal") -> str:
    """"," or "." for the given setting (``"decimal"`` on screen, ``"xlsx_numbers"`` in files)."""
    return "," if pref(setting) == "comma" else "."
