"""The lab notebook's pages and API (moved from mister_plis/app.py in reorg P6)."""

from __future__ import annotations

import asyncio

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from mister_plis.errors import ToolError
from mister_plis.i18n import tr

from .service import SERVED_TYPES


def _steps_tr(d):
    """Step names of a sync ("git fetch", "12 notes from 2 folder(s) ready") in the viewer's language."""
    if isinstance(d, dict) and isinstance(d.get("steps"), list):
        d["steps"] = [dict(s, name=tr(s.get("name"))) if isinstance(s, dict) else s for s in d["steps"]]
    return d


def register(app, ctx, _notebook) -> None:
    SETTINGS = [Depends(ctx.settings_access)]  # every route that changes something here changes the lab's settings
    # the notebook is read from ctx.service when a route is called (tests swap it)
    @app.get("/notes", response_class=HTMLResponse)
    def notes_home(request: Request):
        if not ctx.service.enabled:
            return ctx.page(request, "notfound.html", message=tr("The lab notebook is turned off: no repository is set. Choose one on Settings → Lab notebook."))
        return ctx.page(request, "notebook/notes.html", tree=ctx.service.index.tree(), note=None, synced=bool(ctx.service.index.commit), hide_side_panels=True)


    @app.get("/notes/files/{path:path}")
    def notes_file(path: str):
        """A picture or file used by a shown note. Served so that it can't run anything in the page."""
        p = ctx.service.file(path)
        if not p:
            raise HTTPException(404, tr("Not a file of a shown note"))
        kind = SERVED_TYPES.get(p.suffix.lower())
        headers = {"Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
                   "X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=3600"}
        if kind:
            return FileResponse(p, media_type=kind, headers=headers)
        return FileResponse(p, filename=p.name, headers=headers)  # anything else: download only


    @app.get("/notes/{note_id:path}", response_class=HTMLResponse)
    def notes_page(request: Request, note_id: str):
        if not ctx.service.enabled:
            return ctx.page(request, "notfound.html", message=tr("The lab notebook is turned off."))
        note = ctx.service.index.note(note_id)
        if not note:
            return ctx.page(request, "notfound.html", message=tr("There is no note “{id}” (it may be in a folder that isn't shown).", id=note_id))
        return ctx.page(request, "notebook/notes.html", tree=ctx.service.index.tree(), note=note, synced=True, hide_side_panels=True)


    @app.get("/api/notes")
    def api_notes():
        idx = ctx.service.index
        return {"enabled": ctx.service.enabled, "commit": idx.commit, **ctx.service.status_light(), "tree": idx.tree()}


    @app.get("/api/notes/note")
    def api_note(id: str):
        note = ctx.service.index.note(id)
        if not note:
            raise HTTPException(404, tr("Note not found — it may be in a folder that isn't shown, or was renamed."))
        return note


    @app.get("/api/notes/search")
    def api_notes_search(q: str = ""):
        return {"results": ctx.service.index.search(q)}


    @app.get("/api/notes/status")
    async def api_notes_status():
        return await asyncio.to_thread(ctx.service.status)


    @app.post("/api/notes/check", dependencies=SETTINGS)
    async def api_notes_check():
        return await asyncio.to_thread(ctx.service.check)


    @app.post("/api/notes/sync", dependencies=SETTINGS)
    async def api_notes_sync():
        return _steps_tr(await asyncio.to_thread(ctx.service.sync))


    @app.post("/api/notes/repository", dependencies=SETTINGS)
    def api_notes_repository(body: dict = Body(default={})):
        """Read another repository (Settings → Lab notebook); the old copy is kept, renamed."""
        nb = ctx.service
        if getattr(nb, "locked", None):
            return JSONResponse({"error": tr("The repository is set in config.toml on this computer — change it there.")}, status_code=422)
        try:
            r = nb.set_repository(str(body.get("repo") or ""), str(body.get("branch") or "main"))
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=422)
        return {**r, "status": nb.status()}


    @app.post("/api/notes/settings", dependencies=SETTINGS)
    def api_notes_settings(body: dict = Body(default={})):
        try:
            return {"auto_minutes": ctx.service.set_auto(body.get("auto_minutes"))}
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=422)


    @app.post("/api/notes/folders", dependencies=SETTINGS)
    async def api_notes_folders(body: dict = Body(default={})):
        """Choose the shown folders (for the whole lab), then sync so the change shows at once."""
        folders = body.get("folders")
        if not isinstance(folders, list):
            return JSONResponse({"error": tr("Send a list of folders.")}, status_code=422)
        try:
            await asyncio.to_thread(ctx.service.set_folders, folders)
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=422)
        return _steps_tr(await asyncio.to_thread(ctx.service.sync))
