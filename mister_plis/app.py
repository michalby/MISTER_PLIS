"""The web server: HTML pages plus a small JSON API used by the frontend."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import markdown
from fastapi import Body, Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__, credentials, install, storage, updater
from . import prefs as prefs_mod
from .backup import Backups
from . import access
from .config import ROOT, settings
from .errors import ToolError
from .feedback import KINDS as FEEDBACK_KINDS
from .feedback import FeedbackStore
from .i18n import LANGS, catalog, phrases, tn, tr, trc
from .icons import ICONS, icon_svg
from .jobs import ACTIVE, JobManager, TooLarge, UploadStore
from .labels import Label, Printer
from .people import People
from .prefs import PREFS, current_prefs, from_cookies
from .registry import BrokenTool, registry
from .toolsources import sources as toolsources
from . import locale
from .modules import Modules
from .outputs import translate_output
from .toolkit import TABLE_SUFFIXES, excel_sheets, read_table, safe_filename, translate_spec
from . import accounts as accounts_mod
from . import fileorigin, labsetup, serving, setupcode, toolsettings
from .runners import LocalRunner, ProcessRunner

PKG = Path(__file__).resolve().parent
DAY = 86400

labsetup.migrate()  # before anything is written to the data folder: a server from before lab files counts as set up
# The lab's accounts (accounts.py): none yet = the server is open, as before; the first one turns sign-in on
lab_accounts = accounts_mod.Accounts(settings.data_path, settings.secrets_path)
sign_in_throttle = accounts_mod.Throttle()
access.has_accounts = lab_accounts.any
access.audit = lab_accounts.audit
if setupcode.relevant():
    setupcode.ensure()  # who may set this server up, and make its first account (setupcode.py); __main__ prints it
toolsources.migrate()  # …and keeps the tool source it had by default
uploads = UploadStore(settings.data_path / "uploads")


def _job_env() -> dict:
    """Where a job's process finds this instance's folders (it may run as another user, with sudo's clean environment)."""
    from .config import HOME

    return {"MISTER_PLIS_HOME": str(HOME), "MISTER_PLIS_DATA_DIR": str(settings.data_path),
            "MISTER_PLIS_STORAGE_DIR": str(settings.storage_path), "MISTER_PLIS_FETCH_TOOL_SOURCES": "0"}


if settings.job_user and hasattr(os, "umask"):
    os.umask(0o002)  # the job folders the server makes: writable by the job user too, through the shared group

# Each job kept in the history runs in a process of its own (runners.ProcessRunner; job_isolation = "off": as before)
_runner = (LocalRunner(settings.max_workers) if settings.job_isolation == "off" else
           ProcessRunner(settings.max_workers, folders=lambda: registry.folders, job_user=settings.job_user, env=_job_env))
jobs = JobManager(settings.storage_path, uploads, settings.max_workers,  # jobs: <storage>/jobs (mister_plis/storage.py)
                  live_root=settings.data_path / "live", legacy_root=storage.legacy_jobs(), runner=_runner)
backups = Backups(settings.data_path, jobs, settings.lab_name)
printer = Printer(settings.data_path)
printer.keep_old_logo(labsetup.old_logo)  # once: a server that printed labels before keeps its logo
feedback = FeedbackStore(settings.data_path)
merged_people = People(settings.data_path)
prefs_mod.canonical_name = merged_people.canonical  # an old (merged) name in a cookie is read as the kept one
prefs_mod.lab_language = lambda: backups.settings().language  # a browser that hasn't chosen a language gets the lab's
access.extra_names = lambda: [*backups.settings().server_names, *settings.server_name_list()]  # access.known_host
modules = Modules()  # Time Machine and the other large modules: loaded at the end of this file (mister_plis/modules.py)


def keep_days() -> tuple[int, int]:
    """How long results and uploads are kept: config.toml when it says so, else the lab's setting, else the default."""
    lab = backups.settings()
    jobs_days = settings.job_retention_days if "job_retention_days" in settings.explicit or not lab.keep_days else lab.keep_days
    upload_days = (settings.upload_retention_days if "upload_retention_days" in settings.explicit or not lab.keep_uploads_days
                   else lab.keep_uploads_days)
    return jobs_days, upload_days


def _maintenance_loop():
    """Every 10 minutes: copy results that are due to the backup folder; every hour: delete old ones
    (except those still waiting for their backup)."""
    for n in range(10**9):
        try:
            backups.run()
        except Exception as e:  # pragma: no cover
            print(f"backup failed: {e}", file=sys.stderr)
        if n % 6 == 0:
            try:
                job_days, upload_days = keep_days()
                jobs.cleanup(job_days * DAY, upload_days * DAY, keep=backups.pending)
            except Exception as e:  # pragma: no cover
                print(f"cleanup failed: {e}", file=sys.stderr)
        time.sleep(600)


def _auto_update_loop():  # pragma: no cover - a background thread
    """At night, if chosen on Settings → Server & updates: pull new code from GitHub and restart (see updater.auto_update)."""
    while True:
        time.sleep(60)
        try:
            if updater.auto_due():
                r = updater.auto_update(busy=any(j.record for j in jobs.active()),
                                        before_sync=lambda: _channel().snapshot("before the nightly update"))
                if r.get("restart"):
                    updater.schedule_restart()
        except Exception as e:
            print(f"automatic update failed: {e}", file=sys.stderr)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.fetch_tool_sources:
        await asyncio.to_thread(toolsources.ensure_bundled)  # the basic tools, on a server running from a git checkout
        await asyncio.to_thread(toolsources.ensure_cloned)  # the lab's tools repository the first time, say
        await asyncio.to_thread(toolsources.ensure_requirements)  # and the packages its tools need, once
    registry.load()
    lab.apply_pending_tools()  # a lab file's [tool.<id>] tables that waited for their tool
    locale.reload()  # the tool sources' translations
    registry.broken += [BrokenTool(mid, err) for mid, err in modules.broken]  # shown with broken tools on the home page
    jobs.load_history()
    threading.Thread(target=_maintenance_loop, daemon=True, name="maintenance").start()
    threading.Thread(target=_auto_update_loop, daemon=True, name="auto-update").start()
    modules.start_threads()
    yield


# The API's reference (/api/docs) only where this machine asks for it (api_docs = 1): it maps every route for anyone
app = FastAPI(title="MISTER PLIS", version=__version__, lifespan=lifespan, redoc_url=None,
              docs_url="/api/docs" if settings.api_docs else None, openapi_url="/openapi.json" if settings.api_docs else None)


# Every route that changes something says whether it changes the lab's settings or is everyday work (mister_plis/access.py;
# tests/test_access.py finds a route without a mark).
PUBLIC = [Depends(access.public_access)]  # signing in and out: no signed-in person needed
SETTINGS = [Depends(access.settings_access)]
WORK = [Depends(access.work_access)]


@app.middleware("http")
async def only_from_our_pages(request: Request, call_next):
    """A change must come from this server's own pages (or from no page: curl, the command line) — never from another
    web site a lab member has open (access.same_site)."""
    if not access.same_site(request):
        return JSONResponse({"error": tr("This request came from another web site, so it was refused.")}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def settings_from_cookies(request: Request, call_next):
    token = current_prefs.set(from_cookies(request.cookies))
    try:
        return await call_next(request)
    finally:
        current_prefs.reset(token)


# A server that isn't set up yet: its pages lead to the setup page (docs/LAB_SETUP_PLAN.md). The API, files and the
# setup page itself don't, and "Skip for now" there lets the app run as it is.
NOT_LED_TO_SETUP = ("/api/", "/static/", "/m/", "/i18n/", "/vendor/", "/setup", "/favicon")


@app.middleware("http")
async def lead_to_setup(request: Request, call_next):
    if request.method == "GET" and not request.url.path.startswith(NOT_LED_TO_SETUP) and labsetup.is_new():
        return RedirectResponse("/setup", status_code=307)
    return await call_next(request)


# A server that isn't set up yet: a change needs its setup code (setupcode.py) — except the code itself
NO_SETUP_CODE = ("/api/setup/code",)


@app.middleware("http")
async def setup_code_first(request: Request, call_next):
    """Until the server is set up, whoever changes something must have its setup code, or be on its own computer:
    otherwise a new server would belong to whoever opens it first."""
    if request.method in access.UNSAFE and not request.url.path.startswith(NO_SETUP_CODE) and setupcode.needed(request):
        return JSONResponse({"error": tr("This server isn't set up yet. Enter its setup code on the setup page first."),
                             "setup_code": True}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def not_too_large(request: Request, call_next):
    """An upload larger than the lab allows is refused before it is read (it would fill the disk on its way in);
    /api/uploads checks again while it saves (a body without a length)."""
    if request.method == "POST" and request.url.path == "/api/uploads":
        limit = backups.max_upload_bytes()
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length > limit + 1024 * 1024:  # the form around the file
            return _too_large(limit)
    return await call_next(request)


@app.middleware("http")
async def signed_in_first(request: Request, call_next):
    """Once the lab has accounts, every page and request needs a signed-in person (access.PUBLIC lists the exceptions):
    a page leads to the sign-in page, a request is answered 401. Someone whose password an admin reset chooses their
    own first. The signed-in account is the person (access.current) and their name (prefs.signed_in_name)."""
    if not lab_accounts.any():
        return await call_next(request)
    acct = lab_accounts.session(request.cookies.get(accounts_mod.COOKIE, ""))
    if acct is not None:
        request.scope["mp_person"] = access.Person(acct["name"], acct["role"], True, acct.get("id", ""))
    token = prefs_mod.signed_in_name.set(acct["name"] if acct else "")
    account_token = prefs_mod.signed_in_account.set(acct.get("id", "") if acct else "")
    try:
        path = request.url.path
        if not access.is_public(path):
            asks_page = request.method == "GET" and not path.startswith("/api/")
            if acct is None:
                if asks_page:
                    there = path + (f"?{request.url.query}" if request.url.query else "")
                    return RedirectResponse(f"/login?next={quote(there)}", status_code=303)
                return JSONResponse({"error": tr("Sign in first."), "sign_in": True}, status_code=401)
            if acct.get("must_change") and path != "/api/account/password":
                if asks_page:
                    return RedirectResponse("/login?change=1", status_code=303)
                return JSONResponse({"error": tr("Choose your own password first."), "change_password": True}, status_code=403)
        return await call_next(request)
    finally:
        prefs_mod.signed_in_name.reset(token)
        prefs_mod.signed_in_account.reset(account_token)


@app.middleware("http")
async def safety_headers(request: Request, call_next):
    """No other site may show these pages in a frame; no browser guesses a file's kind (serving.add_headers)."""
    response = await call_next(request)
    docs = request.url.path.startswith("/api/docs")  # FastAPI's reference page (api_docs = 1): scripts from a CDN
    serving.add_headers(response.headers, https=request.url.scheme == "https",
                        policy=serving.FRAME_POLICY if docs else serving.page_policy(fileorigin.origin_for(request)))
    return response


@app.middleware("http")
async def only_our_names(request: Request, call_next):
    """A request must use a name of this server (access.known_host): a web page elsewhere can't point a name of its
    own at this server and use it as its own site (DNS rebinding). Runs first (the last middleware added)."""
    name = access.unknown_host(request)
    if name is not None:
        port = request.url.port or settings.port
        message = tr("This server doesn't answer to the name “{name}”. Open it by its IP address instead. A name only "
                     "a proxy gives it goes into server_names in its config.toml (port {port}).",
                     name=name, port=port)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": message}, status_code=400)
        return Response(message, status_code=400, media_type="text/plain; charset=utf-8")
    return await call_next(request)


app.mount("/static", StaticFiles(directory=PKG / "static"), name="static")
templates = Jinja2Templates(directory=PKG / "templates")


def _search_text(t) -> str:
    """What the sidebar / home search matches: the tool in English and in the page's language, and its tags."""
    words = [t.name, t.category, t.description, tr(t.name), tr(t.category), tr(t.description), *t.tags]
    return " ".join(dict.fromkeys(words)).lower()


templates.env.globals.update(icon=icon_svg, tone=lambda cat: sum(map(ord, cat.lower())) % 6, _=tr, _n=tn, _c=trc,
                             search_text=_search_text, langs=LANGS, unavailable=lambda tool: tool.unavailable_reason(), module_panels=modules.panels, module_shell=modules.shell,
                             module_scripts=lambda kind: modules.scripts(str(kind).strip()),
                             feedback_kinds=[(k, label, hint) for k, (label, hint) in FEEDBACK_KINDS.items()])


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    running = updater.RUNNING
    prefs = from_cookies(request.cookies)
    base = {
        "prefs": prefs,
        "version": __version__,
        "running": running,
        "asset_v": f"{running['short']}-{int(updater.STARTED_AT)}",
        "lab_name": backups.lab_name(),
        "categories": registry.by_category(),
        "broken": registry.broken,
        "path": request.url.path,
        "hide_side_panels": False,  # a full-page space (Time Machine, the inventory…): no side panels
        "feedback_open": feedback.open_count(),
        "icons_json": json.dumps(ICONS),
        "module_nav": modules.nav(),
        "module_styles": modules.styles(),
        "dark": False,  # a page that is always dark (Time Machine)
        "shell_class": "",
        "person": access.current(request),  # who it is, and whether they may change Settings (access.py)
        "max_upload": backups.max_upload_bytes(),  # the largest file one may upload (the browser checks first)
        "files_origin": fileorigin.origin_for(request),  # stored files' own address, "" for none (fileorigin.py)
    }
    return templates.TemplateResponse(request, name, {**base, **ctx})


# --- pages ---------------------------------------------------------------------



@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return page(request, "home.html")


@app.get("/tool/{tool_id}", response_class=HTMLResponse)
def tool_page(request: Request, tool_id: str):
    tool = registry.get(tool_id)
    if not tool:
        job = jobs.get(request.query_params.get("job", ""))
        if job is not None and job.tool_id == tool_id:  # its tool is gone (a tool source removed, say): read it anyway
            source = (job.record_dict().get("tool") or {}).get("source") or ""
            return page(request, "job.html", job_id=job.id, tool_name=_tool_name(job), source=source)
        return page(request, "notfound.html", message=tr("There is no tool “{id}”.", id=tool_id))
    # "<" escaped: the spec sits inside a <script> tag and holds text people typed (e.g. saved compound names)
    spec_json = json.dumps(_tool_spec(tool, translate=True), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return page(request, "tool.html", tool=tool, spec_json=spec_json)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    return page(request, "jobs.html")


# The Settings page's tabs: (id, label, icon, order). The modules add their own (mister_plis/modules.py, SettingsTab);
# templates/settings/<id>.html draws each of these.
SETTINGS_TABS = [("you", "You", "user", 10), ("exports", "Exports & printing", "download", 20), ("tools", "Tools", "tool", 30),
                 ("jobs", "Jobs & backup", "folder", 40), ("people", "People", "user", 80), ("server", "Server & updates", "sync", 90)]


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, tab: str = ""):
    """One page, its tabs switched in the browser (#you, #tools…). ``?tab=`` picks the first tab shown when the
    address has no fragment (/system redirects here with ?tab=server, keeping an old #fragment of its own)."""
    tabs = [{"id": i, "label": label, "icon": ic, "order": o, "template": f"settings/{i}.html"} for i, label, ic, o in SETTINGS_TABS]
    tabs += [{**t, "template": "settings/module.html"} for t in modules.settings_tabs()]
    if access.current(request).role != "admin":  # what only admins see: the server itself
        tabs = [t for t in tabs if t["id"] != "server"]
    tabs.sort(key=lambda t: t["order"])
    default = tab if any(t["id"] == tab for t in tabs) else tabs[0]["id"]
    return page(request, "settings.html", tabs=tabs, default_tab=default, pref_options=PREFS, lab=backups.info(),
                label_printer=printer.info(), results_dir=str(jobs.root), retention_days=keep_days()[0],
                setup_state={**lab.state(), "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(lab.state()["at"] or 0))},
                instance_id=lab.state()["instance"].get("id", ""), reach=_reach(request),
                account_mode=access.mode(), first_needs_code=not lab_accounts.any() and not setupcode.from_this_computer(request))


@app.get("/system")
def system_page():
    """System & updates is a tab of Settings now. No fragment in the address, so an old /system#storage keeps its own."""
    return RedirectResponse("/settings?tab=server", status_code=307)


@app.get("/feedback", response_class=HTMLResponse)
def feedback_page(request: Request):
    return page(request, "feedback.html")


@app.get("/guide", response_class=HTMLResponse)
def guide_page(request: Request):
    text = (ROOT / "docs" / "ADDING_TOOLS.md").read_text(encoding="utf-8")
    html = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
    return page(request, "guide.html", content=html)


@app.get("/i18n/{language}.js")
def i18n_js(language: str):
    """The translations for the browser's own texts (MP.t), cached until the next version."""
    if language not in LANGS:
        raise HTTPException(404, tr("Unknown language"))
    body = "MP.i18n = " + json.dumps(catalog(language), ensure_ascii=False).replace("<", "\\u003c") + ";"
    return Response(body, media_type="application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=604800"})


# --- feedback (button in the top bar; listed on /feedback) ----------------------------


# --- API: people — everyone who added anything --------------------------------------


def people() -> list[dict]:
    """Everyone who added anything to MISTER PLIS — ran a job, sent feedback or kept something in Time Machine
    (a result, files added by hand, a task) — under the name they set in the top bar. Spellings that differ only in capitals are one person (the latest spelling is shown)."""
    found: dict[str, dict] = {}

    def seen(name: str, when: float, what: str) -> None:
        name = merged_people.canonical((name or "").strip())
        if not name:
            return
        p = found.setdefault(name.casefold(), {"name": name, "jobs": 0, "feedback": 0, "first": when, "last": when})
        p[what] = p.get(what, 0) + 1
        if when >= p["last"]:
            p["name"], p["last"] = name, when
        p["first"] = min(p["first"], when)

    for j in jobs.recent(10**9):
        seen(j.user, j.created, "jobs")
    for item in feedback.all():
        seen(item.get("user", ""), item.get("created") or 0, "feedback")
    for name, when, what in modules.people():  # e.g. results kept in Time Machine ("kept")
        if what:
            seen(name, when or 0, what)
    return sorted(found.values(), key=lambda p: p["name"].casefold())


def _people_names() -> list[str]:
    """Names to offer when choosing whom a task is for: everyone in People, and anyone already given a task."""
    names = {p["name"].casefold(): p["name"] for p in people()}
    for n in map(merged_people.canonical, (name for name, _, what in modules.people() if not what and name)):  # a merged name never comes back
        names.setdefault(n.casefold(), n)
    return sorted(names.values(), key=str.casefold)


@app.get("/api/people")
def api_people():
    return {"people": people()}


def rename_person(old: str, new: str) -> dict:
    """Everything stored under ``old`` is now under ``new``: how many of each."""
    return {"jobs": jobs.rename_user(old, new), "feedback": feedback.rename_user(old, new),
            **modules.rename_person(old, new, current_prefs.get().get("name", ""))}


@app.post("/api/people/merge", dependencies=SETTINGS)
def api_people_merge(request: Request, body: dict = Body(default={})):
    """Two names of one person → one: ``from`` goes, ``into`` stays (with all of ``from``'s jobs and feedback). An
    account's name never goes (rename the account instead); a name merged into an account's is attached to it."""
    if lab_accounts.get(str(body.get("from") or "")) is not None:
        return JSONResponse({"error": tr("That is an account's name: rename the account instead (Settings → People → Accounts).")},
                            status_code=422)
    acct = lab_accounts.get(merged_people.canonical(str(body.get("into") or "")))
    if acct is not None:
        return _attach(request, acct["name"], str(body.get("from") or ""))
    try:
        old, into = merged_people.merge(str(body.get("from") or ""), str(body.get("into") or ""), by=from_cookies(request.cookies)["name"])
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {"from": old, "into": into, "moved": rename_person(old, into), "people": people()}


# --- signing in, and the lab's accounts (accounts.py; Settings → People, Settings → You) --------------------------------


def _session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(accounts_mod.COOKIE, token, max_age=accounts_mod.IDLE_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")


def _next_page(text: str) -> str:
    """Where to go after signing in: a page of this server only (never another site: //evil.example)."""
    text = str(text or "")
    return text if text.startswith("/") and not text.startswith("//") and "\\" not in text else "/"


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", change: int = 0):
    """The sign-in page (and, after an admin reset the password, the page to choose one's own)."""
    if not lab_accounts.any():
        return RedirectResponse("/", status_code=303)
    person = access.current(request)
    if person.signed_in and not change:
        return RedirectResponse(_next_page(next), status_code=303)
    return templates.TemplateResponse(request, "login.html", {
        "prefs": from_cookies(request.cookies), "langs": LANGS, "lab_name": backups.lab_name(), "next": _next_page(next),
        "change": bool(change and person.signed_in), "name": person.name,
        "asset_v": f"{updater.RUNNING['short']}-{int(updater.STARTED_AT)}"})


@app.post("/api/login", dependencies=PUBLIC)
async def api_login(request: Request, body: dict = Body(default={})):
    name, password = str(body.get("name") or ""), str(body.get("password") or "")
    ip = access.where(request)
    keys = (f"ip:{ip}", "name:" + " ".join(name.split()).casefold())
    if sign_in_throttle.blocked(*keys):
        lab_accounts.audit(name, "sign-in refused: too many tries", ip)
        return JSONResponse({"error": tr("Too many tries. Wait a quarter of an hour, or ask an admin to reset your password.")},
                            status_code=429)
    acct = await asyncio.to_thread(lab_accounts.verify, name, password)
    if acct is None:
        wait = sign_in_throttle.failed(*keys)
        lab_accounts.audit(name, "sign-in failed", ip)
        await asyncio.sleep(wait)
        return JSONResponse({"error": tr("Wrong name or password.")}, status_code=401)
    sign_in_throttle.succeeded(*keys)
    lab_accounts.signed_in(acct["name"])
    lab_accounts.audit(acct["name"], "signed in", ip)
    r = JSONResponse({"ok": True, "name": acct["name"], "change": bool(acct.get("must_change"))})
    _session_cookie(r, request, lab_accounts.start_session(acct["name"]))
    return r


@app.post("/api/logout", dependencies=PUBLIC)
def api_logout(request: Request, body: dict = Body(default={})):
    """Sign out this browser (``everywhere``: every browser this person is signed in on)."""
    token = request.cookies.get(accounts_mod.COOKIE, "")
    person = access.current(request)
    if body.get("everywhere") and person.signed_in:
        lab_accounts.end_sessions(person.name)
    elif token:
        lab_accounts.end_session(token)
    if person.signed_in:
        lab_accounts.audit(person.name, "signed out" + (" everywhere" if body.get("everywhere") else ""), access.where(request))
    r = JSONResponse({"ok": True})
    r.delete_cookie(accounts_mod.COOKIE, path="/")
    return r


@app.get("/api/account")
def api_account(request: Request):
    """Who is signed in here, and whether the lab has accounts at all."""
    person = access.current(request)
    return {"mode": access.mode(), "name": person.name, "role": person.role, "signed_in": person.signed_in}


@app.post("/api/account/password", dependencies=WORK)
async def api_account_password(request: Request, body: dict = Body(default={})):
    """One's own new password (with the current one; not after an admin's reset, which the sign-in just used)."""
    person = access.current(request)
    if not person.signed_in:
        return JSONResponse({"error": tr("Sign in first.")}, status_code=401)
    acct = lab_accounts.get(person.name) or {}
    old = None if acct.get("must_change") else str(body.get("old") or "")
    try:
        await asyncio.to_thread(lab_accounts.set_password, person.name, str(body.get("new") or ""), old,
                                request.cookies.get(accounts_mod.COOKIE, ""))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {"ok": True}


def _accounts_info(request: Request) -> dict:
    taken = {a["name"].casefold() for a in lab_accounts.list()}
    return {"mode": access.mode(), "accounts": lab_accounts.list(), "me": access.current(request).name,
            "people": [n for n in _people_names() if n.casefold() not in taken],
            "first_needs_code": not lab_accounts.any() and not setupcode.from_this_computer(request)}


@app.get("/api/accounts", dependencies=SETTINGS)
def api_accounts(request: Request):
    return _accounts_info(request)


@app.post("/api/accounts/first", dependencies=SETTINGS)
async def api_accounts_first(request: Request, body: dict = Body(default={})):
    """The lab's first account, an admin — which turns sign-in on. Needs the server's setup code, or being on the
    server's own computer (setupcode.py): otherwise anyone on the network could make themselves the lab's admin."""
    if lab_accounts.any():
        return JSONResponse({"error": tr("The lab has accounts already: an admin adds the next ones.")}, status_code=409)
    if not setupcode.from_this_computer(request) and not setupcode.matches(str(body.get("code") or "")):
        await asyncio.sleep(1)
        return JSONResponse({"error": tr("That isn't this server's setup code.")}, status_code=403)
    if str(body.get("password") or "") != str(body.get("repeat") or ""):
        return JSONResponse({"error": tr("The two passwords differ.")}, status_code=422)
    try:
        await asyncio.to_thread(lab_accounts.create, str(body.get("name") or ""), "admin", str(body.get("password") or ""),
                                "the first account")
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    acct = lab_accounts.get(str(body.get("name") or ""))
    setupcode.forget()
    lab_accounts.signed_in(acct["name"])
    lab_accounts.audit(acct["name"], "turned sign-in on (the first account)", access.where(request))
    r = JSONResponse({"ok": True, "name": acct["name"]})
    _session_cookie(r, request, lab_accounts.start_session(acct["name"]))
    return r


@app.post("/api/accounts", dependencies=SETTINGS)
async def api_accounts_add(request: Request, body: dict = Body(default={})):
    """A new account, with a temporary password (shown once): its person chooses their own when they first sign in."""
    if not lab_accounts.any():
        return JSONResponse({"error": tr("Make the first account (yours, an admin) first.")}, status_code=409)
    asked = " ".join(str(body.get("name") or "").split())
    if asked and merged_people.canonical(asked).casefold() != asked.casefold():
        return JSONResponse({"error": tr("That name was merged into {name}: use that name, or attach it to that person's account.",
                                         name=merged_people.canonical(asked))}, status_code=422)
    try:
        password = await asyncio.to_thread(lab_accounts.create, str(body.get("name") or ""), str(body.get("role") or "member"),
                                           None, access.current(request).name)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {**_accounts_info(request), "password": password}


@app.post("/api/accounts/role", dependencies=SETTINGS)
def api_accounts_role(request: Request, body: dict = Body(default={})):
    try:
        lab_accounts.set_role(str(body.get("name") or ""), str(body.get("role") or ""), access.current(request).name)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return _accounts_info(request)


@app.post("/api/accounts/reset", dependencies=SETTINGS)
def api_accounts_reset(request: Request, body: dict = Body(default={})):
    """A temporary password for someone who forgot theirs (shown once); they choose their own when they sign in."""
    try:
        password = lab_accounts.reset_password(str(body.get("name") or ""), access.current(request).name)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {**_accounts_info(request), "password": password}


def _attach(request: Request, name: str, earlier: str):
    """Attach a name used before there were accounts to an account: what was under it moves to the account."""
    earlier = " ".join(str(earlier or "").split())
    known = {p["name"].casefold() for p in people()}
    if earlier.casefold() not in known:
        return JSONResponse({"error": tr("Nobody added anything under that name: choose one of the names on the People list.")},
                            status_code=422)
    try:
        acct = lab_accounts.add_name(name, earlier, access.current(request).name)
        old, into = merged_people.merge(earlier, acct["name"], by=access.current(request).name)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {**_accounts_info(request), "moved": rename_person(old, into), "people": people(), "from": old, "into": into}


@app.post("/api/accounts/attach", dependencies=SETTINGS)
def api_accounts_attach(request: Request, body: dict = Body(default={})):
    """A name its person used before (``earlier``) becomes the account's: their jobs, feedback and kept results move."""
    return _attach(request, str(body.get("name") or ""), str(body.get("earlier") or ""))


@app.post("/api/accounts/rename", dependencies=SETTINGS)
def api_accounts_rename(request: Request, body: dict = Body(default={})):
    """An account's new name: everything under the old one moves with it (its id stays)."""
    acct = lab_accounts.get(str(body.get("name") or ""))
    if acct is None:
        return JSONResponse({"error": tr("There is no such account.")}, status_code=422)
    new = " ".join(str(body.get("new") or "").split())
    if new.casefold() != acct["name"].casefold() and new.casefold() in {p["name"].casefold() for p in people()} \
            and lab_accounts.get(new) is None:
        return JSONResponse({"error": tr("Someone's results are under that name already: attach it to the account instead.")},
                            status_code=422)
    other = lab_accounts.get(new)
    if other is not None and other["id"] != acct["id"]:
        return JSONResponse({"error": tr("There is an account with that name already.")}, status_code=422)
    old, by = acct["name"], access.current(request).name
    try:
        accounts_mod.clean_name(new)
        if new == old:
            return _accounts_info(request)
        merged_people.unmerge(new)  # the new name is in use (again): not read as another one
        if old.casefold() != new.casefold():
            merged_people.merge(old, new, by=by)  # a browser or record still under the old name is read as the new
        lab_accounts.rename(old, new, by)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {**_accounts_info(request), "moved": rename_person(old, new)}


@app.delete("/api/accounts", dependencies=SETTINGS)
def api_accounts_remove(request: Request, body: dict = Body(default={})):
    """Remove an account: its person can't sign in any more; their results stay, under their name."""
    try:
        lab_accounts.remove(str(body.get("name") or ""), access.current(request).name)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return _accounts_info(request)


@app.get("/api/activity", dependencies=SETTINGS)
def api_activity(limit: int = 200):
    """The newest entries of the activity log: sign-ins, accounts, changes to the lab's settings."""
    return {"entries": lab_accounts.activity(max(1, min(limit, 2000)))}


@app.get("/api/feedback")
def api_feedback_list():
    return {"items": feedback.all(), "kinds": {k: tr(label) for k, (label, _) in FEEDBACK_KINDS.items()}}


@app.post("/api/feedback", dependencies=WORK)
def api_feedback_add(request: Request, body: dict = Body(default={})):
    try:
        item = feedback.add(str(body.get("kind") or ""), str(body.get("text") or ""), user=from_cookies(request.cookies)["name"],
                            page=str(body.get("page") or ""), where=str(body.get("where") or ""),
                            account=access.current(request).account)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return item


@app.post("/api/feedback/{item_id}", dependencies=SETTINGS)
def api_feedback_update(item_id: str, body: dict = Body(default={})):
    try:
        return feedback.update(item_id, str(body.get("status") or ""))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=404)


@app.delete("/api/feedback/{item_id}", dependencies=SETTINGS)
def api_feedback_delete(item_id: str):
    try:
        feedback.delete(item_id)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=404)
    return {"ok": True}


def _steps_tr(d):
    """Step names of a sync ("git fetch", "12 notes from 2 folder(s) ready") in the viewer's language."""
    if isinstance(d, dict) and isinstance(d.get("steps"), list):
        d["steps"] = [dict(s, name=tr(s.get("name"))) if isinstance(s, dict) else s for s in d["steps"]]
    return d



@app.get("/vendor/plotly.min.js")
def plotly_js():
    import plotly

    path = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "public, max-age=604800"})


# --- API: tools & jobs -------------------------------------------------------------


@app.get("/api/version")
def api_version():
    from .formats import WRITES

    return {"version": __version__, "commit": updater.RUNNING["commit"], "short": updater.RUNNING["short"], "started": updater.STARTED_AT,
            "instance_id": labsetup.read_state().get("instance", {}).get("id", ""), "formats": WRITES}


def _tool_spec(tool, translate: bool = False) -> dict:
    """A tool's form for the browser."""
    return tool.spec(translate=translate)


@app.get("/api/tools")
def api_tools():
    return {"tools": [_tool_spec(tool) for tool in registry.sorted()], "broken": [b.__dict__ for b in registry.broken]}


@app.post("/api/tools/{tool_id}/run", dependencies=WORK)
async def api_run(request: Request, tool_id: str, body: dict = Body(default={})):
    tool = registry.get(tool_id)
    if not tool:
        raise HTTPException(404, tr("No tool {id}", id=repr(tool_id)))
    reason = tool.unavailable_reason()
    if reason:
        raise HTTPException(409, tr(reason))
    job = await asyncio.to_thread(jobs.submit, tool, body.get("params") or {}, prefs=from_cookies(request.cookies),  # copies its inputs
                                  keyword=str(body.get("keyword") or ""), parent=str(body.get("parent") or ""),
                                  title=str(body.get("title") or ""))
    wait = 0.0 if tool.background else min(float(body.get("wait", 25)), 120)
    await asyncio.to_thread(jobs.wait, job, wait)
    return _job_dict(job, request)


def _job_dict(job, request: Request | None = None) -> dict:
    """A job for the browser; results that can go into the protocol also say what they're called there. A failed
    job's traceback (the server's paths, its code) only for an admin."""
    d = job.to_dict() | modules.job_flags(job, True)
    if request is not None:
        d["files_base"] = fileorigin.files_base(request, job.workdir)  # its files from their own origin (fileorigin.py)
        if access.current(request).role != "admin":
            d["traceback"] = ""
    tool = registry.get(job.tool_id)
    if tool and tool.protocol and job.status == "done":
        d["heading"] = tr(tool.heading(job.params))
    return d


@app.post("/api/tools/{tool_id}/suggest/{input_name}", dependencies=WORK)
async def api_suggest(tool_id: str, input_name: str, body: dict = Body(default={})):
    """Pre-fill a SampleTable / PlateLayout / ImageSpots from the uploaded files."""
    tool = registry.get(tool_id)
    fn = tool.suggesters.get(input_name) if tool else None
    if not fn:
        raise HTTPException(404, tr("Nothing to suggest for this input"))
    try:
        files = [uploads.get(i) for i in body.get("files") or []]
        result = await asyncio.to_thread(fn, files, body.get("params") or {})  # to_thread keeps the settings
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    except Exception as e:  # show the problem in the form instead of failing silently
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
    return {"result": result}


@app.post("/api/tools/{tool_id}/action/{input_name}", dependencies=WORK)
async def api_action(tool_id: str, input_name: str, body: dict = Body(default={})):
    """Run a form Button's server-side action."""
    from .inputs import Button

    tool = registry.get(tool_id)
    btn = tool.input_map().get(input_name) if tool else None
    if not isinstance(btn, Button) or not btn.action:
        raise HTTPException(404, tr("No such button"))
    try:
        message = await asyncio.to_thread(btn.action, body.get("params") or {})
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {"message": tr(message or "Done."), "reload": btn.reload}


def _tool_name(job) -> str:
    known = registry.get(job.tool_id)
    return known.name if known else job.tool_name


@app.get("/api/jobs")
def api_jobs(limit: int = 100, tool: str | None = None):
    return {"jobs": [j.summary_dict() | modules.job_flags(j, False) | {"tool_name": _tool_name(j),
                                              "result_files": j.result_names()} for j in jobs.recent(limit, tool)]}


def _job_or_404(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, tr("Job not found (it may have been cleaned up)"))
    return job


@app.get("/api/jobs/{job_id}")
def api_job(request: Request, job_id: str):
    return _job_dict(_job_or_404(job_id), request)


@app.post("/api/jobs/{job_id}/title", dependencies=WORK)
def api_job_title(job_id: str, body: dict = Body(default={})):
    """Give a job a title (shown after the tool's name), or change it; "" removes it."""
    job = _job_or_404(job_id)
    jobs.set_title(job, str(body.get("title") or ""))
    return {"title": job.title}


@app.post("/api/jobs/{job_id}/cancel", dependencies=WORK)
def api_cancel(job_id: str):
    job = _job_or_404(job_id)
    jobs.cancel(job)
    return job.to_dict()


@app.get("/api/jobs/{job_id}/files/{rel:path}")
def api_job_file(job_id: str, rel: str, download: bool = False):
    job = _job_or_404(job_id)
    p = jobs.file_path(job, rel)
    if not p:
        raise HTTPException(404, tr("File not found"))
    return serving.stored_file(p, download)  # shown only when nothing in it can run (serving.py)


def _report_info(request: Request, title: str, job=None):
    from . import report

    viewer = from_cookies(request.cookies)
    decimal = "," if viewer["decimal"] == "comma" else "."
    info = report.ReportInfo(
        title=title, printed_by=viewer["name"], lab=backups.lab_name(),
        version=f"{__version__} ({updater.RUNNING['short']})" if updater.RUNNING.get("short") else __version__,
        decimal=decimal,
    )
    if job is not None:
        info.tool, info.job_id, info.run_by, info.run_at = tr(_tool_name(job)), job.id, job.user, job.started or job.created
        info.params = report.describe_settings(registry.get(job.tool_id), job.params, decimal)
    return info


def _pdf_response(pdf: bytes, name: str) -> Response:
    from urllib.parse import quote

    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_")
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "no-store",
    })


@app.get("/api/jobs/{job_id}/outputs/{index}/report.pdf")
def api_table_pdf(request: Request, job_id: str, index: int, sort: int | None = None, desc: bool = False):
    """A result table as a printable PDF: who ran it, when, from which files, with which settings."""
    from . import report

    job = _job_or_404(job_id)
    out = job.outputs[index] if 0 <= index < len(job.outputs) else None
    if not out or out.get("kind") != "table":
        raise HTTPException(404, tr("No such table"))
    title = out.get("title") or tr("Table")
    pdf = report.table_pdf(out, _report_info(request, title, job), sort=sort, descending=desc)
    return _pdf_response(pdf, job.file_name(f"{safe_filename(title)}.pdf"))


MAX_CHART_BYTES = 8 * 1024 * 1024  # one chart as a PNG data URL


def _chart_images(raw: str) -> dict[int, bytes]:
    """``{"3": "data:image/png;base64,…"}`` (output index → the chart as the browser drew it) → bytes."""
    import base64

    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    out = {}
    for k, v in (data.items() if isinstance(data, dict) else []):
        if isinstance(v, str) and v.startswith("data:image/") and "," in v and len(v) < MAX_CHART_BYTES * 4 // 3 + 100:
            try:
                out[int(k)] = base64.b64decode(v.split(",", 1)[1], validate=True)
            except (ValueError, TypeError):
                pass
    return out


@app.api_route("/api/jobs/{job_id}/report.pdf", dependencies=WORK, methods=["GET", "POST"])
async def api_results_pdf(request: Request, job_id: str):
    """Everything a job showed — metrics, tables, text, warnings, charts, pictures — as one printable PDF.

    POSTed with a form field ``charts`` (the result page's charts as PNGs, drawn by the browser) so they are
    on paper too; a plain GET prints the rest and says where the charts are."""
    return await _results_pdf(request, _job_or_404(job_id))


async def _results_pdf(request: Request, job) -> Response:
    from . import printout

    if job.status != "done" or not printout.printable(job.outputs):
        raise HTTPException(404, tr("Nothing printable"))
    charts = {}
    if request.method == "POST":
        form = await request.form(max_part_size=64 * 1024 * 1024)
        charts = _chart_images(str(form.get("charts") or ""))

    def picture(i: int, o: dict) -> bytes | None:
        if o.get("kind") == "plot":
            return charts.get(i)
        url = str(o.get("url") or "")
        path = None
        marker = f"/{job.id}/files/"
        if url.startswith("/api/") and marker in url:  # /api/jobs/<id>/files/… or a module's copy of the job
            path = jobs.file_path(job, url.split(marker, 1)[1])
        return path.read_bytes() if path and path.stat().st_size < 40 * 1024 * 1024 else None

    title = tr(_tool_name(job))
    info = _report_info(request, f"{title} — {job.title}" if job.title else title, job)
    with phrases(job.phrases):  # stored in English; printed like the page shows it
        outputs = [translate_output(o) for o in job.outputs]
    pdf = await asyncio.to_thread(printout.results_pdf, outputs, info, picture)
    return _pdf_response(pdf, job.file_name(f"{safe_filename(title)}.pdf"))


@app.post("/api/protocol.pdf", dependencies=WORK)
async def api_protocol_pdf(request: Request):
    """Results collected with "Add to protocol" (kept in the browser), printed together.

    Posted as a form field ``data`` (JSON) so the PDF opens in a new tab like any link."""
    from . import printout, report

    form = await request.form()
    try:
        data = json.loads(str(form.get("data") or "{}"))
    except ValueError:
        raise HTTPException(422, tr("Bad protocol data")) from None
    raw_items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(422, tr("The protocol is empty"))
    title = " ".join(str(data.get("title") or "").split())[:120] or tr("Protocol")
    info = _report_info(request, title)
    info.tool = tr("Protocol")
    items = []
    for it in raw_items[:200]:
        if not isinstance(it, dict):
            continue
        outputs = [o for o in it.get("outputs") or [] if isinstance(o, dict) and o.get("kind") in printout.PRINTABLE]
        tool = registry.get(str(it.get("tool_id") or ""))
        params = it.get("params") if isinstance(it.get("params"), dict) else {}
        # the heading is what was made (the compound), worked out again here; the calculator goes under it
        heading = tr(tool.heading(params)) if tool else str(it.get("heading") or tr("Result"))
        items.append({"heading": " ".join(heading.split())[:160],
                      "tool": tr(tool.name) if tool and tr(tool.name) != heading else "",
                      "settings": report.describe_settings(tool, params, info.decimal) if tool else [],
                      "outputs": outputs})
    pdf = await asyncio.to_thread(printout.protocol_pdf, items, info)
    return _pdf_response(pdf, f"{time.strftime('%Y-%m-%d')}_{safe_filename(title)}.pdf")


# --- API: reagent labels (Brother P-touch) --------------------------------------------


@app.post("/api/tools/{tool_id}/label", dependencies=WORK)
async def api_tool_label(tool_id: str, body: dict = Body(default={})):
    """What a result's label says by default (the person can edit it before printing)."""
    tool = registry.get(tool_id)
    if not tool or not tool.labeler:
        raise HTTPException(404, tr("This tool has no labels"))
    try:
        params = tool.parse(body.get("params") or {}, uploads.get)
        fields = await asyncio.to_thread(tool.labeler, params)  # to_thread keeps the settings (decimal comma)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {"fields": Label.from_dict(fields or {}).__dict__, "printer": printer.info()}


def _labels_from(body: dict) -> list[Label]:
    raw = body.get("labels")
    if not isinstance(raw, list):
        raise ToolError("No labels sent.")
    return [Label.from_dict(d) for d in raw[:500]]


def _label_options(body: dict) -> dict:
    """One print's tape, resolution and cut choices (the rest come from Settings → Exports & printing)."""
    opts = body.get("options")
    opts = dict(opts) if isinstance(opts, dict) else {}
    if "tape_mm" in body:  # older clients sent only the tape
        opts.setdefault("tape_mm", body["tape_mm"])
    return opts


@app.post("/api/label/preview.png", dependencies=WORK)
async def api_label_preview(body: dict = Body(default={})):
    """The strip of labels as it will print (one label or a whole protocol)."""
    try:
        png = await asyncio.to_thread(printer.preview, _labels_from(body), _label_options(body))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/label/print", dependencies=WORK)
async def api_label_print(body: dict = Body(default={})):
    try:
        message = await asyncio.to_thread(printer.print, _labels_from(body), _label_options(body))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {"message": tr(message)}


@app.get("/api/label/printer")
def api_label_printer():
    return printer.info()


@app.post("/api/label/printer", dependencies=SETTINGS)
def api_label_printer_save(body: dict = Body(default={})):
    try:
        printer.update(body)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return printer.info()


@app.get("/api/label/logo.png")
def api_label_logo():
    """The lab's logo, as Settings → Exports & printing shows it."""
    png = printer.logo_png()
    if not png:
        raise HTTPException(404, tr("This lab has no logo for its labels."))
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/label/printer/check", dependencies=SETTINGS)
async def api_label_printer_check():
    try:
        return {"message": tr(await asyncio.to_thread(printer.check))}
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)


# --- API: lab settings (shared by everyone) --------------------------------------------


@app.get("/api/lab")
def api_lab():
    return backups.info()


@app.post("/api/lab/name", dependencies=SETTINGS)
def api_lab_name(body: dict = Body(default={})):
    """The lab's name (sidebar, PDF reports, backups), for everyone; empty = the one in config.toml."""
    try:
        backups.set_lab_name(str(body.get("lab_name") or ""))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {"lab_name": backups.lab_name(), "saved": backups.settings().lab_name, "default": backups.lab}


@app.get("/api/system/credentials", dependencies=SETTINGS)
async def api_credentials():
    """The instance's git tokens, as the GitHub access panel shows them (never a token itself)."""
    return await asyncio.to_thread(credentials.describe)


@app.post("/api/system/credentials", dependencies=SETTINGS)
async def api_credentials_add(body: dict = Body(default={})):
    try:
        await asyncio.to_thread(credentials.set_token, str(body.get("host") or ""), str(body.get("owner") or ""),
                                str(body.get("repo") or ""), str(body.get("token") or ""))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return await asyncio.to_thread(credentials.describe)


@app.delete("/api/system/credentials", dependencies=SETTINGS)
async def api_credentials_remove(body: dict = Body(default={})):
    try:
        gone = await asyncio.to_thread(credentials.remove_token, str(body.get("host") or ""), str(body.get("owner") or ""),
                                       str(body.get("repo") or ""))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    if not gone:
        return JSONResponse({"error": tr("There is no such token.")}, status_code=404)
    return await asyncio.to_thread(credentials.describe)


@app.post("/api/lab/uploads", dependencies=SETTINGS)
def api_lab_uploads(body: dict = Body(default={})):
    """The largest file one may upload, in MB (0 = the default)."""
    try:
        backups.set_max_upload_mb(body.get("max_upload_mb", 0))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return backups.info()


@app.post("/api/lab", dependencies=SETTINGS)
def api_lab_save(body: dict = Body(default={})):
    try:
        after = int(body.get("backup_after_days", 1))
        backups.update(str(body.get("backup_dir") or ""), after)
    except (ToolError, ValueError) as e:
        return JSONResponse({"error": tr(str(e)) if isinstance(e, ToolError) else tr("Invalid number of days.")}, status_code=422)
    return backups.info()


@app.post("/api/lab/backup", dependencies=SETTINGS)
async def api_backup_now():
    """Copy every finished result that hasn't been backed up yet, without waiting for the delay."""
    if not backups.settings().backup_dir:
        return JSONResponse({"error": tr("Set a backup folder first.")}, status_code=422)
    await asyncio.to_thread(backups.run, True)
    return backups.info()


@app.post("/api/lab/verify", dependencies=SETTINGS)
async def api_backup_verify():
    """Check every backed-up job's copy file by file (size and SHA-256); a copy that doesn't check out is made again."""
    if not backups.settings().backup_dir:
        return JSONResponse({"error": tr("Set a backup folder first.")}, status_code=422)
    return await asyncio.to_thread(backups.verify_all)


@app.post("/api/lab/upgrade", dependencies=SETTINGS)
async def api_backup_upgrade():
    """Rewrite older backups (job-info.txt + files) in today's readable form; the old folders are kept beside them."""
    try:
        return await asyncio.to_thread(backups.upgrade_old)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)


# --- API: the backup folder's jobs, and bringing them back -------------------------------------------------------


@app.get("/api/backup/catalogue")
async def api_backup_catalogue(q: str = "", rescan: bool = False, limit: int = 300):
    """Jobs in the backup folder (newest first), filtered by words (job number, tool, person, title, keyword)."""
    from .text import fold

    if not backups.settings().backup_dir:
        return {"available": False, "rows": [], "total": 0}
    rows = await asyncio.to_thread(backups.catalogue.rows, rescan)
    words = fold(q).split()
    hits = [r for r in rows if all(w in fold(" ".join(str(r.get(k) or "") for k in ("id", "tool_name", "user", "person", "title", "keyword")))
                                   for w in words)]
    hits.sort(key=lambda r: r.get("created") or 0, reverse=True)
    out = [r | modules.job_flags(SimpleNamespace(id=r["id"]), False) | {"in_jobs": jobs.get(r["id"]) is not None, "tool_name": tr(r.get("tool_name") or "")}
           for r in hits[:max(1, min(limit, 2000))]]
    return {"available": backups.catalogue.root() is not None, "rows": out, "total": len(hits), "all": len(rows)}


@app.post("/api/jobs/import", dependencies=SETTINGS)
async def api_jobs_import(body: dict = Body(default={})):
    """Bring jobs back from the backup folder into Jobs & results (``folders``: their backup folders)."""
    folders = [str(f) for f in body.get("folders") or [] if f][:500]
    if not folders:
        return JSONResponse({"error": tr("Tick the jobs to bring back first.")}, status_code=422)
    r = await asyncio.to_thread(backups.import_jobs, folders)
    r["errors"] = [tr(e) for e in r["errors"]]
    return r


# --- API: clearing the job history (Settings → Jobs & backup) ------------------------------------------


def _is_mine(job, request: Request, name: str) -> bool:
    """A job of the person asking: run by their account (its id), or — a job from before accounts — under their name."""
    account = access.current(request).account
    if account and job.account:
        return job.account == account
    return job.user == name


def _history_scope(request: Request, scope: str) -> tuple[list, int]:
    """Finished jobs in the history — the viewer's own (by their name in Settings) or everyone's — and how
    many of theirs are still running (those are never cleared)."""
    if scope not in ("mine", "all"):
        raise HTTPException(422, tr("Choose whose jobs to clear."))
    name = from_cookies(request.cookies)["name"]
    if scope == "mine" and not name:
        raise HTTPException(422, tr("Set your name in Settings first — your jobs are the ones run under it."))
    picked = [j for j in jobs.recent(10**9) if scope == "all" or _is_mine(j, request, name)]
    return [j for j in picked if j.status not in ACTIVE], sum(j.status in ACTIVE for j in picked)


@app.get("/api/history/clear")
def api_clear_preview(request: Request, scope: str = "mine"):
    """What clearing would delete, and which results aren't backed up yet (to offer copying them first)."""
    doomed, running = _history_scope(request, scope)
    return {"count": len(doomed), "running": running, "backups_on": bool(backups.settings().backup_dir),
            "unbacked": [{"id": j.id, "tool": _tool_name(j), "user": j.user, "keyword": j.keyword, "finished": j.finished or j.created}
                         for j in doomed if backups.pending(j)]}


@app.post("/api/history/clear", dependencies=WORK)
async def api_clear(request: Request, body: dict = Body(default={})):
    """Delete the jobs (and their result files); ``backup`` lists job ids to copy to the backup folder first. Clearing
    one's own is everyday work; clearing everyone's is the lab's settings."""
    if str(body.get("scope") or "") == "all":
        access.settings_access(request)
    doomed, _ = _history_scope(request, str(body.get("scope") or ""))
    backup = {str(i) for i in body.get("backup") or []}
    return await asyncio.to_thread(backups.clear, doomed, backup)


# --- API: uploads ------------------------------------------------------------------


def _too_large(limit: int) -> JSONResponse:
    return JSONResponse({"error": tr("The file is larger than {mb} MB, the most this lab allows (Settings → Jobs & backup).",
                                     mb=limit // (1024 * 1024))}, status_code=413)


@app.post("/api/uploads", dependencies=WORK)
async def api_upload(file: UploadFile):
    try:
        up = await asyncio.to_thread(uploads.save, file.filename or "upload", file.file, backups.max_upload_bytes())
    except TooLarge as e:
        return _too_large(e.limit)
    return {"id": up.id, "name": up.name, "size": up.size}


@app.get("/api/uploads/{upload_id}")
def api_upload_info(upload_id: str):
    try:
        up = uploads.get(upload_id)
    except ToolError as e:
        raise HTTPException(404, tr(str(e))) from None
    return {"id": up.id, "name": up.name, "size": up.size}


@app.get("/api/uploads/{upload_id}/table")
def api_upload_table(upload_id: str):
    """Column names of an uploaded table — fills Column() dropdowns."""
    try:
        up = uploads.get(upload_id)
        if up.suffix not in TABLE_SUFFIXES:
            return {"columns": [], "sheets": []}
        df = read_table(up.path)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e)), "columns": []}, status_code=422)
    import pandas as pd

    cols = [{"name": str(c), "numeric": bool(pd.api.types.is_numeric_dtype(df[c]))} for c in df.columns]
    return {"columns": cols, "rows": int(len(df)), "sheets": excel_sheets(up.path)}


# --- API: system / self-update -------------------------------------------------------


def _local_hostname() -> str:
    """The name other computers on the network can use, e.g. "mac-studio.local" (on a Mac), else the host name."""
    if sys.platform == "darwin":
        try:
            name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=2, encoding="utf-8", errors="replace").stdout.strip()
            if name:
                return f"{name}.local"
        except (OSError, subprocess.SubprocessError):
            pass
    return socket.gethostname()


def _reach(request: Request) -> list[str]:
    """The addresses to give a new person (Settings → Server & updates): the one this page was opened with, this
    computer's name on the network (on a Mac, ``<name>.local``) and its IP addresses — any device on the lab's network
    can use them, with nothing set up on it (access.known_host knows them all)."""
    out = []
    here = request.base_url
    if here.hostname not in ("localhost", "127.0.0.1", "::1"):
        out.append(str(here).rstrip("/"))
    name = _local_hostname()
    if name.endswith(".local"):
        out.append(f"http://{name}:{settings.port}")
    out += [f"http://{ip}:{settings.port}" for ip in access.network_addresses() if ":" not in ip]  # IPv4
    return list(dict.fromkeys(out)) or [f"http://{name}:{settings.port}"]


def _server_info() -> dict:
    disk = shutil.disk_usage(settings.data_path)
    host = _local_hostname()
    return {
        "hostname": host,
        "url_hint": f"http://{host}:{settings.port}",
        "python": sys.version.split()[0],
        "platform": platform.platform(terse=True),
        "uptime_s": time.time() - updater.STARTED_AT,
        "data_dir": str(settings.data_path),
        "disk_free": disk.free,
        "disk_total": disk.total,
        "tools": len(registry.tools),
        "broken": [b.__dict__ for b in registry.broken],
        "active_jobs": [j.to_dict(logs=False) | {"outputs": []} for j in jobs.active() if j.record],
        "version": __version__,
        "install": install.describe(),
    }


@app.get("/api/system", dependencies=SETTINGS)
async def api_system():
    git = await asyncio.to_thread(updater.status)
    return {"git": git, "server": _server_info()}


@app.post("/api/system/check", dependencies=SETTINGS)
async def api_check():
    return {"git": await asyncio.to_thread(updater.check)}


@app.post("/api/system/sync", dependencies=SETTINGS)
async def api_sync(body: dict = Body(default={})):
    active = [j for j in jobs.active() if j.record]
    if active and not body.get("force"):
        return JSONResponse(
            {"ok": False, "needs_confirm": True, "active": [j.to_dict(logs=False) | {"outputs": []} for j in active]},
            status_code=409,
        )
    try:
        result = _steps_tr(await asyncio.to_thread(_channel().update))  # a snapshot of the settings, then git pull
    except (ToolError, OSError) as e:
        return JSONResponse({"ok": False, "error": tr(str(e)), "steps": []}, status_code=422)
    if result["ok"] and result.get("restart"):
        result["restarting"] = updater.schedule_restart()
    return result


@app.get("/api/system/branches", dependencies=SETTINGS)
async def api_branches():
    return await asyncio.to_thread(updater.branches)


@app.post("/api/system/branch", dependencies=SETTINGS)
async def api_switch_branch(body: dict = Body(default={})):
    """Run another branch from GitHub on this server (e.g. a test branch on a laptop), then restart."""
    active = [j for j in jobs.active() if j.record]
    if active and not body.get("force"):
        return JSONResponse(
            {"ok": False, "needs_confirm": True, "active": [j.to_dict(logs=False) | {"outputs": []} for j in active]},
            status_code=409,
        )
    branch = str(body.get("branch") or "").strip()
    if not updater.BRANCH_NAME.match(branch) or ".." in branch:  # nothing to snapshot for
        return _steps_tr(updater.switch(branch))
    try:
        result = _steps_tr(await asyncio.to_thread(_channel().update, branch))
    except (ToolError, OSError) as e:
        return JSONResponse({"ok": False, "error": tr(str(e)), "steps": []}, status_code=422)
    if result["ok"]:
        result["restarting"] = updater.schedule_restart() if result.get("restart") else False
    return result


def _channel():
    from . import updates

    return updates.channel(modules.storage_folders(settings.storage_path))


@app.get("/api/system/updates", dependencies=SETTINGS)
async def api_updates():
    """How this instance is updated, and what the release feed has that is newer (updates.py)."""
    st = await asyncio.to_thread(lambda: _channel().status())
    st.pop("git", None)
    return {**st, "how": tr(st["how"]), "notes": tr(st["notes"]) if st.get("notes") else ""}


@app.post("/api/system/updates", dependencies=SETTINGS)
def api_updates_save(body: dict = Body(default={})):
    """[updates] channel and feed: which releases this instance follows."""
    from . import updates

    try:
        updates.set_update_settings(body.get("channel"), body.get("feed"))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return updates.update_settings()


@app.get("/api/system/snapshots", dependencies=SETTINGS)
def api_snapshots():
    from . import updates

    return {"snapshots": updates.list_snapshots(), "keep": updates.KEEP_SNAPSHOTS}


@app.post("/api/system/snapshots", dependencies=SETTINGS)
async def api_snapshot_now():
    """A snapshot of the lab's settings now (one is made before every update by itself)."""
    from . import updates

    try:
        r = await asyncio.to_thread(updates.make_snapshot, "by hand", modules.storage_folders(settings.storage_path))
    except (ToolError, OSError) as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {**r, "snapshots": updates.list_snapshots()}


@app.post("/api/system/snapshots/restore", dependencies=SETTINGS)
async def api_snapshot_restore(request: Request, body: dict = Body(default={})):
    """Bring the lab's settings back from a snapshot, then restart (jobs and the modules' data stay as they are)."""
    from . import updates

    if any(j.record for j in jobs.active()):
        return JSONResponse({"error": tr("Jobs are running — wait until they finish.")}, status_code=409)
    try:
        r = await asyncio.to_thread(updates.restore_snapshot, str(body.get("name") or ""), from_cookies(request.cookies)["name"])
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {**r, "restarting": updater.schedule_restart(delay=1.0)}


@app.post("/api/system/auto-update", dependencies=SETTINGS)
def api_auto_update(body: dict = Body(default={})):
    """Update by itself at night (code pushed from elsewhere arrives without pressing Sync with git)."""
    try:
        return {"auto": updater.set_auto(str(body.get("mode") or ""))}
    except ValueError:
        return JSONResponse({"error": tr("Unknown choice.")}, status_code=422)


# --- API: settings a tool declares (Settings → Tools; mister_plis/toolsettings.py) ------------------------------


def _tool_settings_row(tool) -> dict:
    spec = translate_spec({"inputs": [i.spec() for i in tool.settings]})
    return {"id": tool.id, "name": tr(tool.name), "source": tool.source, "inputs": spec["inputs"],
            "values": toolsettings.values(tool), "status": toolsettings.status(tool) or None,  # the tool translates it (tr)
            "changed": {k: toolsettings.record(tool.id).get(k) for k in ("changed_by", "changed_at")}}


@app.get("/api/tools/settings")
async def api_tool_settings():
    """Every tool that declares settings: their form, values and status (the status may look for a program: a thread)."""
    tools = [t for t in registry.tools.values() if t.settings]
    return {"tools": await asyncio.to_thread(lambda: [_tool_settings_row(t) for t in sorted(tools, key=lambda t: tr(t.name))])}


@app.post("/api/tools/{tool_id}/settings", dependencies=SETTINGS)
def api_tool_settings_save(request: Request, tool_id: str, body: dict = Body(default={})):
    tool = registry.get(tool_id)
    if tool is None or not tool.settings:
        raise HTTPException(404, tr("There is no such tool."))
    try:
        toolsettings.save(tool, dict(body.get("values") or {}), from_cookies(request.cookies)["name"])
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return _tool_settings_row(tool)


# --- API: tool sources (Settings → Tools; mister_plis/toolsources.py) -----------------------------


def _sources_call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)


@app.get("/api/tools/sources")
async def api_sources():
    return {"sources": await asyncio.to_thread(toolsources.status), "loaded": {t.id: t.source for t in registry.tools.values()},
            "errors": toolsources.errors}


@app.post("/api/tools/sources", dependencies=SETTINGS)
async def api_source_add(body: dict = Body(default={})):
    return await asyncio.to_thread(_sources_call, toolsources.add, str(body.get("url") or ""), str(body.get("name") or ""),
                                   str(body.get("branch") or "main"), bool(body.get("trusted")), str(body.get("token") or ""))


@app.post("/api/tools/sources/{name}/enable", dependencies=SETTINGS)
async def api_source_enable(name: str, body: dict = Body(default={})):
    r = await asyncio.to_thread(_sources_call, toolsources.set_enabled, name, bool(body.get("on")))
    return r if isinstance(r, JSONResponse) else {**r, "restart_needed": True}


@app.post("/api/tools/sources/{name}/check", dependencies=SETTINGS)
async def api_source_check(name: str):
    return await asyncio.to_thread(_sources_call, toolsources.check, name)


@app.post("/api/tools/sources/{name}/update", dependencies=SETTINGS)
async def api_source_update(name: str, body: dict = Body(default={})):
    r = await asyncio.to_thread(_sources_call, toolsources.update, name, str(body.get("to") or ""))
    return r if isinstance(r, JSONResponse) else {**r, "restart_needed": bool(r.get("changed"))}


@app.post("/api/tools/sources/{name}/branch", dependencies=SETTINGS)
async def api_source_branch(name: str, body: dict = Body(default={})):
    r = await asyncio.to_thread(_sources_call, toolsources.switch, name, str(body.get("branch") or ""))
    return r if isinstance(r, JSONResponse) else {**r, "restart_needed": True}


@app.post("/api/tools/sources/{name}/pin", dependencies=SETTINGS)
def api_source_pin(name: str, body: dict = Body(default={})):
    return _sources_call(toolsources.set_pin, name, bool(body.get("pinned")))


@app.delete("/api/tools/sources/{name}", dependencies=SETTINGS)
def api_source_remove(name: str):
    r = _sources_call(toolsources.remove, name)
    return r if isinstance(r, JSONResponse) else {"removed": name, "restart_needed": True}


@app.get("/api/tools/catalogue")
async def api_catalogue():
    """The tool catalogue this lab browses (Settings → Tools → Browse; mister_plis/catalogue.py)."""
    from . import catalogue

    address = toolsources.catalogue()
    if not address:
        return {"address": "", "sources": [], "error": ""}
    try:
        found = await asyncio.to_thread(catalogue.browse, address, toolsources)
    except ToolError as e:
        return {"address": address, "sources": [], "error": tr(str(e))}
    return {"address": address, "sources": found, "error": ""}


@app.post("/api/tools/catalogue", dependencies=SETTINGS)
def api_catalogue_save(body: dict = Body(default={})):
    try:
        return {"address": toolsources.set_catalogue(str(body.get("address") or ""))}
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)


@app.post("/api/tools/catalogue/add", dependencies=SETTINGS)
async def api_catalogue_add(body: dict = Body(default={})):
    """Add a source the catalogue lists: pinned and switched off, as any source that isn't the lab's own."""
    from . import catalogue

    try:
        r = await asyncio.to_thread(catalogue.add, toolsources.catalogue(), str(body.get("name") or ""), toolsources)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return r


@app.post("/api/system/restart", dependencies=SETTINGS)
def api_restart():
    return {"restarting": updater.schedule_restart()}


# --- API: the storage folder (jobs, what tools save) -------------------------------------------------------------


@app.get("/api/system/storage")
def api_storage():
    return {**storage.info(len(jobs.recent(10**9))), "problems": jobs.store.problems, "migration": jobs.migration}


@app.post("/api/system/storage", dependencies=SETTINGS)
async def api_storage_choose(request: Request, body: dict = Body(default={})):
    """Make another folder the storage folder (moving the jobs there if asked), then restart."""
    busy = any(j.record for j in jobs.active())
    try:
        r = await asyncio.to_thread(storage.choose, str(body.get("dir") or ""), bool(body.get("move", True)), busy,
                                    backups.settings().backup_dir, from_cookies(request.cookies)["name"],
                                    tuple(modules.storage_folders(settings.storage_path)))  # Time Machine's, say
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    for s in r["steps"]:
        s["name"] = tr(s["name"])
    r["restarting"] = updater.schedule_restart(delay=1.5)
    return r


# --- the lab's setup: /setup, a lab file read, checked and applied (mister_plis/labsetup.py) ---------------------------


def _lab_from(body: dict) -> tuple[dict, list[str]]:
    """The lab the page sends (the same shape as a lab file), checked."""
    return labsetup.normalize(body.get("lab") if isinstance(body.get("lab"), dict) else {})


def _rows_tr(rows: list[dict]) -> list[dict]:
    pictures = lambda r: {"old": tr(r["old"]), "new": tr(r["new"])} if r.get("key") == "logo" else {}  # noqa: E731
    return [{**r, "label": tr(r["label"]), "note": tr(r["note"]) if r.get("note") else "", **pictures(r)} for r in rows]


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    return page(request, "setup.html", setup_state=lab.state(), hide_side_panels=True)


@app.get("/api/setup")
async def api_setup(request: Request):
    """What the setup page starts from: this server's settings, the lab files that come with the code, the modules."""
    def form(m):
        return {**m, "name": tr(m["name"]), "intro": tr(m["intro"]) if m["intro"] else "",
                "groups": [{**g, "title": tr(g["title"]), "help": tr(g["help"]) if g["help"] else ""} for g in m["groups"]],
                "fields": [{**f, "label": tr(f["label"]), "help": tr(f["help"]) if f["help"] else "",
                            "choices": [[v, tr(t)] for v, t in f["choices"]]} for f in m["fields"]]}

    tools = sorted(({"id": t.id, "name": tr(t.name)} for t in registry.tools.values()), key=lambda t: t["name"].casefold())
    return {"state": lab.state(), "current": await asyncio.to_thread(lab.current), "files": labsetup.lab_files(),
            "modules": [form(m) for m in modules.setup_forms()], "tools": tools, "langs": LANGS,
            "code_needed": setupcode.needed(request)}


@app.post("/api/setup/code", dependencies=SETTINGS)
async def api_setup_code(request: Request, body: dict = Body(default={})):
    """The setup code, checked: kept in a cookie for this browser until the server is set up (setupcode.py)."""
    if not setupcode.matches(str(body.get("code") or "")):
        await asyncio.sleep(1)  # one guess a second
        return JSONResponse({"error": tr("That isn't this server's setup code.")}, status_code=403)
    r = JSONResponse({"ok": True})
    r.set_cookie(setupcode.COOKIE, setupcode.current(), max_age=86400, httponly=True, samesite="strict",
                 secure=request.url.scheme == "https")
    return r


@app.post("/api/setup/read", dependencies=SETTINGS)
async def api_setup_read(body: dict = Body(default={})):
    """A lab file to start from: one that comes with the code (path), from an https:// address (url), or its text."""
    try:
        if body.get("text") is not None:
            text, where = str(body["text"]), str(body.get("name") or "file")
            if len(text) > labsetup.MAX_FILE:
                raise ToolError("That file is too large to be a lab file.")
        else:
            where = str(body.get("url") or body.get("path") or "")
            if body.get("path") and where not in {f["path"] for f in labsetup.lab_files()}:
                raise ToolError("There is no such lab file.")
            text, where = await asyncio.to_thread(labsetup.read_source, where)
        found, warnings = labsetup.parse(text, "" if body.get("text") is not None else where)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {"lab": found, "warnings": warnings, "source": where}


@app.post("/api/setup/plan", dependencies=SETTINGS)
async def api_setup_plan(body: dict = Body(default={})):
    """What setting the lab up this way would change (nothing is written), and whether its repositories can be read."""
    try:
        found, warnings = _lab_from(body)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    rows = await asyncio.to_thread(lab.plan, found)
    access = await asyncio.to_thread(labsetup.check_access, found, modules.setup_forms()) if body.get("access", True) else []
    return {"rows": _rows_tr(rows), "access": [{**a, "what": tr(a["what"]), "note": a["note"]} for a in access], "warnings": warnings}


@app.post("/api/setup/apply", dependencies=SETTINGS)
async def api_setup_apply(request: Request, body: dict = Body(default={})):
    try:
        found, _ = _lab_from(body)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    source = str(body.get("source") or "page")[:300]
    r = await asyncio.to_thread(lab.apply, found, from_cookies(request.cookies)["name"], source)
    return {**r, "rows": _rows_tr(r["rows"]), "state": lab.state()}


@app.post("/api/setup/skip", dependencies=SETTINGS)
def api_setup_skip(request: Request):
    return {"state": lab.skip(from_cookies(request.cookies)["name"])}


def _lab_file_response(found: dict, note: str) -> Response:
    name = safe_filename(found.get("lab", {}).get("name") or "lab").lower().replace(" ", "-") or "lab"
    text = labsetup.dumps(found, note)
    return Response(text, media_type="application/toml; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.toml"'})


@app.get("/api/setup/export", dependencies=SETTINGS)
async def api_setup_export():
    """This server's settings as a lab file (Settings → Server & updates → Download this lab's file)."""
    found = await asyncio.to_thread(lab.current)
    return _lab_file_response(found, f"MISTER PLIS lab file: this server's settings on {time.strftime('%Y-%m-%d')}.\n"
                                     "Set a computer up with it: python -m mister_plis setup <this file>, or on the setup page.")


@app.post("/api/setup/file", dependencies=SETTINGS)
def api_setup_file(body: dict = Body(default={})):
    """What is on the setup page, as a lab file to keep."""
    try:
        found, _ = _lab_from(body)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return _lab_file_response(found, "MISTER PLIS lab file, from the setup page.")


# --- moving a whole server (mister_plis/transfer.py): Settings → Server & updates, and the setup page ------------------


@app.post("/api/transfer/export", dependencies=SETTINGS)
async def api_transfer_export(request: Request, body: dict = Body(default={})):
    """Copy this server (jobs, Time Machine, settings, the modules' data) into a new folder inside ``dir``."""
    from . import transfer

    if any(j.record for j in jobs.active()):
        return JSONResponse({"error": tr("Jobs are running — wait until they finish, then copy the server.")}, status_code=409)
    try:
        return await asyncio.to_thread(transfer.export, str(body.get("dir") or ""), settings.data_path, settings.storage_path,
                                       modules.storage_folders(settings.storage_path), lab_name=backups.lab_name(),
                                       by=from_cookies(request.cookies)["name"], version=__version__,
                                       commit=updater.RUNNING.get("commit", ""), jobs=len(jobs.recent(10**9)))
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)


@app.post("/api/transfer/check", dependencies=SETTINGS)
async def api_transfer_check(body: dict = Body(default={})):
    """What a copied server holds, every file checked — before bringing it in."""
    from . import transfer

    try:
        s = await asyncio.to_thread(transfer.summary, str(body.get("dir") or ""), True)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {**s, "here_has_jobs": transfer._has_jobs(settings.storage_path)}


@app.post("/api/transfer/import", dependencies=SETTINGS)
async def api_transfer_import(request: Request, body: dict = Body(default={})):
    """Bring a copied server into this one (only while it has no jobs); the server must restart to load it."""
    from . import transfer

    try:
        r = await asyncio.to_thread(transfer.bring_in, str(body.get("dir") or ""), settings.data_path, settings.storage_path,
                                    from_cookies(request.cookies)["name"])
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=422)
    return {**r, "restarting": updater.schedule_restart(delay=1.0)}


# --- the modules (Time Machine, …): loaded last, so a base route always wins over a module's -----------------------


class _Services:
    """What the base offers modules (ModuleContext.services). Methods call the base's own helpers when used."""

    jobs, backups, uploads, registry, printer, feedback = jobs, backups, uploads, registry, printer, feedback
    data_path = settings.data_path

    @property
    def lab_name(self):  # set on Settings → Server & updates, else config.toml
        return backups.lab_name()

    tr = staticmethod(tr)

    @property
    def storage_path(self):
        return settings.storage_path

    @staticmethod
    def page(request: Request, name: str, **ctx) -> HTMLResponse:
        return page(request, name, **ctx)

    @staticmethod
    def who(request: Request) -> str:
        return from_cookies(request.cookies)["name"]

    # a module's routes that change something use one of these, as the base's do (docs/MODULES.md):
    #   @app.post("/api/x", dependencies=[Depends(ctx.settings_access)])
    @staticmethod
    def services_address(name: str) -> str:
        """An address the lab once set for the whole lab (``[services]``: "model"; no longer set since 0.19.0), "" if
        none: a module takes it over once (the inventory's ollama_url)."""
        return backups.settings().services.get(name, "")

    settings_access = staticmethod(access.settings_access)
    work_access = staticmethod(access.work_access)

    @staticmethod
    def tool_name(job) -> str:
        return _tool_name(job)

    @staticmethod
    def people_names() -> list[str]:
        return _people_names()

    @staticmethod
    def canonical(name: str) -> str:
        return merged_people.canonical(name)

    @staticmethod
    async def results_pdf(request: Request, job) -> Response:
        return await _results_pdf(request, job)

    @staticmethod
    def table_pdf(request: Request, table: dict, title: str, filename: str, *, kicker: str = "", params: list = (),
                  params_caption: str = "SETTINGS", note: str = "", size: float = 8) -> Response:
        """A table (``{"columns", "rows", "numeric"}``) as a PDF in the app's own look: the header with the lab,
        who printed it and when, ``params`` as label / value pairs under ``params_caption``, and the footer."""
        from . import report

        info = _report_info(request, title)
        info.tool, info.params, info.params_caption, info.note = kicker, list(params), params_caption, note
        return _pdf_response(report.table_pdf(table, info, size=size), filename)

    @staticmethod
    def job_or_404(job_id: str):
        return _job_or_404(job_id)

    @staticmethod
    def files_base(request: Request, folder: Path) -> str:
        """A signed link to ``folder`` on the stored files' own origin (fileorigin.py), "" for none: the page's links
        to its files become that plus each file's path inside the folder (MP.filesFrom)."""
        return fileorigin.files_base(request, folder)

    @staticmethod
    def file_response(path: Path, download: bool = False) -> Response:
        """A stored file (a job's, a kept result's) for the browser, so that nothing in it can run (serving.py)."""
        return serving.stored_file(path, download)

    @staticmethod
    def git(*args, **kw):
        return updater.git(*args, **kw)


modules.load(app, settings.enabled_modules(), _Services(), settings.storage_path, settings.data_path, settings.module_settings, templates.env)
lab = labsetup.LabSetup(settings.data_path, backups=backups, printer=printer, toolsources=toolsources, modules=modules,
                        registry=registry, jobs_count=lambda: len(jobs.recent(10**9)), updater=updater, storage=storage)
lab.apply_pending_modules()  # a lab file's [module.<id>] tables that waited for their module

