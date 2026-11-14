"""Time Machine's pages and API (moved from mister_plis/app.py in reorg phase P4). Registered by the module's
``register``; everything from the base comes through ``ctx`` (mister_plis/modules.py)."""

from __future__ import annotations

import asyncio
import json

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from mister_plis.errors import ToolError
from mister_plis.i18n import tr
from mister_plis.prefs import from_cookies

from .service import COLORS


def register(app, ctx, timemachine) -> None:
    SETTINGS, WORK = [Depends(ctx.settings_access)], [Depends(ctx.work_access)]  # which kind of change a route is

    def who(request: Request) -> str:
        return from_cookies(request.cookies)["name"]

    # Time Machine's own backup (backup.py) — before /api/tm/{job_id}, which would catch "backup" as a job number
    @app.get("/api/tm/backup")
    def api_tm_backup_info():
        return timemachine.backup.info()

    @app.post("/api/tm/backup", dependencies=SETTINGS)
    async def api_tm_backup_now():
        try:
            return await asyncio.to_thread(timemachine.backup.run, True)
        except OSError as e:
            return JSONResponse({"error": str(e)}, status_code=422)

    @app.post("/api/tm/backup/restore", dependencies=SETTINGS)
    async def api_tm_backup_restore():
        try:
            return await asyncio.to_thread(timemachine.backup.restore)
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=422)

    @app.get("/timemachine", response_class=HTMLResponse)
    def timemachine_page(request: Request):
        return ctx.page(request, "timemachine/timemachine.html", shell_class="tm", dark=True, hide_side_panels=True, tm_entry=None,
                    tm_root=str(timemachine.root), backup_dir=ctx.backups.settings().backup_dir)


    @app.get("/timemachine/{job_id}", response_class=HTMLResponse)
    def timemachine_entry_page(request: Request, job_id: str):
        if not timemachine.has(job_id):
            return ctx.page(request, "timemachine/timemachine.html", shell_class="tm", dark=True, hide_side_panels=True, tm_entry=None, tm_missing=job_id,
                        tm_root=str(timemachine.root), backup_dir=ctx.backups.settings().backup_dir)
        return ctx.page(request, "timemachine/timemachine.html", shell_class="tm", dark=True, hide_side_panels=True, tm_entry=job_id,
                    tm_root=str(timemachine.root), backup_dir=ctx.backups.settings().backup_dir)


    # --- API: Time Machine (results worth keeping) -----------------------------------------


    def _tm_or_404(job_id: str):
        job = timemachine.job(job_id)
        if not job:
            raise HTTPException(404, tr("This job is not in Time Machine."))
        return job


    def _tm_urls(d, job_id: str):
        """A kept job's links point at its copy in Time Machine, not at Jobs & results (which may be gone)."""
        return json.loads(json.dumps(d, default=str).replace(f"/api/jobs/{job_id}/", f"/api/tm/{job_id}/"))


    def _tm_item(entry: dict, job, full: bool = False) -> dict:
        from mister_plis.report import describe_files

        tool = ctx.registry.get(job.tool_id)
        d = job.to_dict(logs=full) | {"tool_name": ctx.tool_name(job), "known_tool": bool(tool), "entry": entry,
                                      "result_files": job.result_names(), "in_jobs": ctx.jobs.get(job.id) is not None}
        if not full:
            d["outputs"], d["params"] = [], {}
        d["input_files"] = [{"label": tr(label), "names": names} for label, names in describe_files(tool, job.files)]
        root = timemachine.root_of(job.id)
        d["version"], d["versions"], d["root"] = timemachine.version_number(job.id), len(timemachine.lineage(job.id)), root
        if entry.get("kind") in ("manual", "task") or (timemachine.entry(root) or {}).get("kind") in ("manual", "task"):
            d["tool_name"] = job.tool_name  # a title typed by a person: not translated
        return _tm_urls(d, job.id)


    @app.get("/api/tm")
    def api_tm_list():
        return {"entries": [_tm_item(e, j) for e, j in timemachine.all()], "projects": timemachine.projects(), "people": ctx.people_names(), "colors": COLORS,
                "root": str(timemachine.root), "backup_dir": ctx.backups.settings().backup_dir, "history": timemachine.history.available}


    def _who(request: Request) -> str:
        return from_cookies(request.cookies)["name"]


    def _tm_call(fn, *args, **kw):
        """Run a Time Machine change; a ToolError becomes a message for the page."""
        try:
            return fn(*args, **kw)
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=422)


    @app.get("/api/tm/projects")
    def api_tm_projects():
        return {"projects": timemachine.projects()}


    @app.post("/api/tm/projects", dependencies=WORK)
    def api_tm_project_new(request: Request, body: dict = Body(default={})):
        return _tm_call(timemachine.create_project, str(body.get("name") or ""), str(body.get("description") or ""), who(request),
                        body.get("color") or None)


    @app.post("/api/tm/projects/{pid}", dependencies=WORK)
    def api_tm_project_edit(request: Request, pid: str, body: dict = Body(default={})):
        return _tm_call(timemachine.update_project, pid, name=body.get("name"), description=body.get("description"),
                        color=body.get("color"), by=who(request))


    @app.post("/api/tm/projects/{pid}/merge", dependencies=WORK)
    def api_tm_project_merge(request: Request, pid: str, body: dict = Body(default={})):
        """Merge a project into another: its results move there and it goes — one change in the history."""
        return _tm_call(timemachine.merge_projects, pid, str(body.get("into") or ""), who(request))


    @app.delete("/api/tm/projects/{pid}", dependencies=WORK)
    def api_tm_project_delete(request: Request, pid: str):
        r = _tm_call(timemachine.delete_project, pid, who(request))
        return r if isinstance(r, JSONResponse) else {"ok": True}


    @app.post("/api/tm/assign", dependencies=WORK)
    def api_tm_assign(request: Request, body: dict = Body(default={})):
        """Put kept results into projects, take them out, or both at once (a move) — one change in the history."""
        ids = [str(i) for i in body.get("ids") or []]
        r = _tm_call(timemachine.assign, ids, add=body.get("add") or [], remove=body.get("remove") or [], by=who(request))
        return r if isinstance(r, JSONResponse) else {"changed": r, "projects": timemachine.projects()}


    def _uploads(ids) -> list:
        out = []
        for uid in ids if isinstance(ids, list) else []:
            out.append(ctx.uploads.get(str(uid)))  # ToolError when it expired
        return out


    @app.post("/api/tm/manual", dependencies=WORK)
    async def api_tm_manual(request: Request, body: dict = Body(default={})):
        """Files worth keeping that never were a job: title, description and files are all required."""
        def go():
            return timemachine.add_manual(str(body.get("title") or ""), str(body.get("description") or ""), _uploads(body.get("uploads")),
                                          projects=body.get("projects") or [], by=who(request))
        return await asyncio.to_thread(_tm_call, go)


    @app.post("/api/tm/tasks", dependencies=WORK)
    def api_tm_task_new(request: Request, body: dict = Body(default={})):
        """A task: a title and a description, maybe whom it is for — the files or the job come later."""
        return _tm_call(timemachine.add_task, str(body.get("title") or ""), str(body.get("description") or ""),
                        ctx.canonical(str(body.get("assignee") or "")), projects=body.get("projects") or [], by=who(request))


    @app.get("/api/tm/tasks")
    def api_tm_tasks(open: bool = True):
        """The tasks (by default only those still to do) — offered on a result page as what the result is for."""
        return {"tasks": [{"id": j.id, "title": e.get("title", ""), "assignee": e.get("assignee", ""), "user": j.user, "created": j.created,
                           "done": e.get("done"), "projects": e.get("projects", [])} for e, j in timemachine.tasks(open_only=open)]}


    @app.post("/api/tm/{job_id}/versions", dependencies=WORK)
    async def api_tm_version_files(request: Request, job_id: str, body: dict = Body(default={})):
        """A changed file for a kept result → its next version."""
        def go():
            return timemachine.add_version_files(job_id, _uploads(body.get("uploads")), str(body.get("note") or ""), who(request))
        return await asyncio.to_thread(_tm_call, go)


    @app.post("/api/tm/{job_id}/versions/job", dependencies=WORK)
    async def api_tm_version_job(request: Request, job_id: str, body: dict = Body(default={})):
        """Another job (e.g. a re-run with changed settings), found by its number, as the next version of a kept result."""
        if not timemachine.has(job_id):
            return JSONResponse({"error": tr("This job is not in Time Machine.")}, status_code=404)
        return await asyncio.to_thread(_tm_call, timemachine.retrieve, str(body.get("id") or ""), who(request), (), job_id)


    @app.get("/api/tm/history")
    def api_tm_history(job: str = "", project: str = "", limit: int = 300):
        """Every change to Time Machine (a local git log), optionally for one result or one project."""
        return {"available": timemachine.history.available, "commits": timemachine.log(job, project, limit)}


    @app.get("/api/tm/history/{sha}")
    def api_tm_commit(sha: str):
        c = timemachine.history.get(sha)
        if not c:
            raise HTTPException(404, tr("No such change in the history."))
        return c | {"files": timemachine.history.files_changed(c["id"])}


    @app.post("/api/tm/restore", dependencies=WORK)
    def api_tm_restore(request: Request, body: dict = Body(default={})):
        return _tm_call(timemachine.restore, str(body.get("commit") or ""), who(request))


    @app.get("/api/tm/find")
    def api_tm_find(q: str = ""):
        """Jobs matching a (partial) job number — in Jobs & results or in the backup folder."""
        return {"results": [f | {"tool_name": tr(f["tool_name"]) if f.get("tool_name") else ""} for f in timemachine.find(q)][:20]}


    @app.post("/api/tm/retrieve", dependencies=WORK)
    async def api_tm_retrieve(request: Request, body: dict = Body(default={})):
        """Type a job number on the Time Machine page → the job is found and copied here."""
        who = from_cookies(request.cookies)["name"]
        try:
            entry = await asyncio.to_thread(timemachine.retrieve, str(body.get("id") or ""), who, body.get("projects") or [])
        except ToolError as e:
            return JSONResponse({"error": tr(str(e)), "candidates": timemachine.find(str(body.get("id") or ""))[:20]}, status_code=422)
        return {"entry": entry, "already": bool(entry.get("already"))}


    @app.post("/api/jobs/{job_id}/timemachine", dependencies=WORK)
    async def api_job_to_tm(request: Request, job_id: str, body: dict = Body(default={})):
        """The "Add to Time Machine" button next to a job; with a task, the job is what that task asked for."""
        job = ctx.job_or_404(job_id)
        who, task = from_cookies(request.cookies)["name"], str(body.get("task") or "")
        try:
            if task and not timemachine.is_task(task):
                raise ToolError("This is not a task.")
            entry = await asyncio.to_thread(timemachine.add_to, job, task, who) if task else await asyncio.to_thread(timemachine.add, job, who)
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=422)
        return {"entry": entry, "already": bool(entry.get("already"))}


    @app.get("/api/tm/{job_id}")
    def api_tm_entry(request: Request, job_id: str):
        from mister_plis.report import describe_settings

        job = _tm_or_404(job_id)
        d = _tm_item(timemachine.entry(job_id), job, full=True)
        try:
            uploaded = timemachine.entry(job_id).get("source") in ("upload", "task")  # added by hand, or a task: no settings of its own
            d["settings"] = [] if uploaded else [{"label": k, "value": v} for k, v in describe_settings(ctx.registry.get(job.tool_id), job.params)]
        except Exception:  # a job whose tool has changed since — the raw values are still in meta.json
            d["settings"] = []
        d["files_kept"] = [f | {"url": f"/api/tm/{job_id}/files/{f['rel']}"} for f in timemachine.files(job_id)]
        d["files_base"] = ctx.files_base(request, job.workdir)  # its files from their own origin (MP.filesFrom)
        d["lineage"] = []
        for n, v in enumerate(timemachine.lineage(job_id), 1):
            e, j = timemachine.entry(v), timemachine.job(v)
            d["lineage"].append({"id": v, "n": n, "kind": e.get("kind", "job"), "created": j.created, "user": j.user, "note": e.get("note", ""),
                                 "keyword": j.keyword, "files": [o.get("name") for o in j.outputs if o.get("kind") in ("file", "image")][:6]})
        return d


    @app.post("/api/tm/{job_id}", dependencies=WORK)
    def api_tm_update(request: Request, job_id: str, body: dict = Body(default={})):
        projects = body.get("projects")
        if "title" in body:
            r = _tm_call(timemachine.set_title, job_id, str(body.get("title") or ""), who(request))
            if isinstance(r, JSONResponse):
                return r
        if "assignee" in body or "description" in body:
            r = _tm_call(timemachine.update_task, job_id, assignee=None if body.get("assignee") is None else ctx.canonical(str(body["assignee"])), description=body.get("description"), by=who(request))
            if isinstance(r, JSONResponse):
                return r
        return _tm_call(timemachine.update, job_id, note=body.get("note"), projects=projects if isinstance(projects, list) else None,
                        by=who(request))


    @app.delete("/api/tm/{job_id}", dependencies=WORK)
    def api_tm_delete(request: Request, job_id: str):
        try:
            timemachine.remove(job_id, who(request))
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=404)
        return {"ok": True}


    @app.get("/api/tm/{job_id}/files/{rel:path}")
    def api_tm_file(job_id: str, rel: str, download: bool = False):
        p = timemachine.file_path(job_id, rel)
        if not p:
            raise HTTPException(404, tr("File not found"))
        return ctx.file_response(p, download)  # shown only when nothing in it can run


    @app.api_route("/api/tm/{job_id}/report.pdf", dependencies=WORK, methods=["GET", "POST"])
    async def api_tm_pdf(request: Request, job_id: str):
        return await ctx.results_pdf(request, _tm_or_404(job_id))


