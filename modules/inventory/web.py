"""Pages and API of the reagent inventory (mister_plis/reagents.py). Registered by app.py with ``register``."""

from __future__ import annotations

import asyncio
import io
import json
import re
import time
from typing import Callable

from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

from mister_plis.errors import ToolError
from mister_plis.excel import csv_safe, no_formulas
from mister_plis.i18n import tn, tr
from mister_plis.prefs import from_cookies
from mister_plis.toolkit import safe_filename

from .service import N_SLOTS, Inventory
from .tidy import Tidy


def _who(request: Request) -> str:
    return from_cookies(request.cookies)["name"]


def _lang(request: Request) -> str:
    return from_cookies(request.cookies)["lang"]


def _call(fn, *args, status: int = 422, **kw):
    try:
        return fn(*args, **kw)
    except ToolError as e:
        return JSONResponse({"error": tr(str(e))}, status_code=status)


def _steps_tr(d: dict) -> dict:
    for s in d.get("steps", []):
        s["name"] = tr(s["name"])
        if s.get("output") and not s["ok"]:
            s["output"] = tr(s["output"])
    return d


def order_rows(inv: Inventory, lang: str) -> list[dict]:
    """One row per producer (brand, for the consumables) of an item that is to be ordered or is ordered."""
    have = {f["key"] for f in inv.fields(lang)}
    cons = inv.INFO_FIELD == "consumable"
    rows = []
    for r in inv.items(lang):
        for i in range(1, N_SLOTS + 1):
            p = f"producer_{i}_"
            if not (r.get(p + "to_order") or r.get(p + "ordered")) or r.get("is_disposed"):
                continue
            size = " ".join(str(x) for x in (r.get(p + "container_size"), r.get(p + "container_unit")) if x not in (None, ""))
            row = {tr("No.") if cons else tr("Label no."): r["id"], tr("Name"): r["_title"]}
            if "cas_no" in have:
                row["CAS"] = r.get("cas_no") or ""
            if "size_spec" in have:
                row[tr("Size / specification")] = r.get("size_spec") or ""
            row[tr("Brand") if cons else tr("Manufacturer")] = r.get(p + "name") or ""
            if p + "supplier" in have:
                row[tr("Supplier")] = r.get(p + "supplier") or ""
            row[tr("Product code") if cons else tr("Catalogue no.")] = r.get(p + "catalog_no") or ""
            row[tr("Pack size") if cons else tr("Container size")] = size
            row[tr("How much to order")] = r.get(p + "order_amount") or ""
            if p + "product_url" in have:
                row[tr("Product page")] = r.get(p + "product_url") or ""
            row.update({tr("State"): tr("Ordered") if r.get(p + "ordered") else tr("To order"),
                        tr("Note"): r.get("order_note") or "", tr("Who asked"): r.get("order_requested_by") or "",
                        tr("When"): r.get("order_requested_date") or ""})
            rows.append(row)
    return rows


def _cell(f: dict, v, lang: str):
    """A value as the list on screen shows it (numbers stay numbers, for Excel)."""
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, bool) or f.get("type") == "bool":
        return tr("yes") if v else tr("no")
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    if f.get("type") == "multi":
        return ", ".join(x.strip() for x in str(v).split(";") if x.strip())
    if f.get("type") in ("text", "longtext"):
        return re.sub(r";(?=\S)", "; ", str(v))
    return str(v)


def _label(f: dict, lang: str) -> str:
    return (f.get("label_pl") if lang == "pl" else f.get("label")) or f.get("label") or f["key"]


def shown_table(inv: Inventory, data: dict, lang: str, pdf: bool = False) -> dict:
    """The list as it is shown — ``data["ids"]``: the items, filtered and in order; ``data["columns"]``: the columns
    shown — as a table ``{"columns", "numeric", "rows"}``. On the PDF the columns are the lab's choice when it has
    made one (Settings → Reagents & consumables)."""
    fields = {f["key"]: f for f in inv.fields(lang)}
    keys = [k for k in dict.fromkeys(str(k) for k in data.get("columns") or []) if k in fields]
    if pdf and inv.pdf_config()["source"] == "chosen":
        keys = [k for k in inv.pdf_config()["columns"] if k in fields] or keys
    keys = keys or [k for k in inv.config()["list"] if k in fields] or ["_title"]
    items = {r["id"]: r for r in inv.items(lang)}
    ids = data.get("ids")
    if isinstance(ids, list):
        rows = [items[i] for i in dict.fromkeys(str(i) for i in ids) if i in items]
    else:
        rows = [r for r in items.values() if r.get("is_disposed") is not True]
    cols = [fields[k] for k in keys]
    return {"columns": [_label(f, lang) for f in cols], "numeric": [f.get("type") == "number" for f in cols],
            "rows": [[_cell(f, r.get(f["key"]), lang) for f in cols] for r in rows]}


def _filters(data: dict) -> list[tuple[str, str]]:
    """The filters the list was shown with, as (label, value) pairs worded by the page."""
    out = []
    for x in data.get("filters") or []:
        if isinstance(x, (list, tuple)) and len(x) == 2 and str(x[1]).strip():
            out.append((" ".join(str(x[0]).split())[:80], " ".join(str(x[1]).split())[:200]))
    return out[:40]


def _grid_response(columns: list, rows: list, name: str, fmt: str) -> Response:
    import pandas as pd

    # columns by position: two columns may share a name
    df = pd.DataFrame(rows, columns=range(len(columns)))
    df.columns = columns
    return _frame_response(df, name, fmt)


def _table_response(rows: list[dict], name: str, fmt: str) -> Response:
    import pandas as pd

    return _frame_response(pd.DataFrame(rows), name, fmt)


def _frame_response(df, name: str, fmt: str) -> Response:
    import pandas as pd

    stamp = time.strftime("%Y-%m-%d")
    if fmt == "csv":
        body = "﻿" + csv_safe(df).to_csv(index=False, sep=";")
        return Response(body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stamp}_{name}.csv"'})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name=name[:31])
        ws = xw.sheets[name[:31]]
        no_formulas(ws)  # a name typed as "=…" stays text (docs/SECURITY_AUDIT.md L2)
        for col in ws.columns:
            width = max((len(str(c.value or "")) for c in col), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(8, width + 2))
        ws.freeze_panes = "A2"
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{stamp}_{name}.xlsx"'})


def _tidy_tr(d: dict) -> dict:
    """A tidy-up status or run in the viewer's language (it is kept in English)."""
    runs = [d.get("last")] if "last" in d else [d]
    for r in runs:
        if not r:
            continue
        for s in r.get("steps", []):
            s["name"] = tr(s["name"])
        for p in r.get("proposals", []):
            p["title"], p["why"] = tr(p["title"]), "; ".join(tr(w) for w in str(p["why"] or "").split("; "))
            p["error"] = tr(p["error"]) if p.get("error") else ""
            for c in p.get("changes", []):
                c["why"] = tr(c["why"]) if c.get("why") else ""
        for x in r.get("problems", []):
            x["problem"] = tr(x["problem"])
    if d.get("running"):
        d["running"]["step"] = tr(d["running"]["step"])
    if d.get("ollama", {}).get("error"):
        d["ollama"]["error"] = tr(d["ollama"]["error"])
    return d


SPACES = {
    "reagents": {"kind": "reagents", "base": "/reagents", "api": "/api/reagents", "icon": "flask"},
    "consumables": {"kind": "consumables", "base": "/consumables", "api": "/api/consumables", "icon": "box"},
}


def _marks(access) -> tuple[list, list]:
    """The dependencies that mark a route as a change of the lab's settings, or as everyday work (the base's access)."""
    if access is None:  # tests that build the routes alone
        return [], []
    return [Depends(access[0])], [Depends(access[1])]


def register(app: FastAPI, page: Callable, inv: Inventory, tidy: Tidy | None = None, consumables: Inventory | None = None,
             table_pdf: Callable | None = None, calculator=None, access: tuple[Callable, Callable] | None = None) -> None:
    """The Reagents space and, next to it, the Consumables space: the same pages on another workbook of the same
    repository. The sync, the history, the tidy-up and the info from the lab are shared (under /api/reagents).
    ``access``: the base's (settings_access, work_access): every route that changes something says which it is."""
    SETTINGS, WORK = _marks(access)
    spaces = [("reagents", inv)] + ([("consumables", consumables)] if consumables is not None else [])

    @app.get("/reagents/setup")
    def reagents_setup_page():  # old address: sync and fields are on Settings → Reagents & consumables
        return RedirectResponse("/settings#inventory", status_code=307)

    @app.get("/consumables/setup")
    def consumables_setup_page():
        return RedirectResponse("/settings#inventory", status_code=307)

    @app.get("/api/reagents/status")
    def api_reagent_status():
        return inv.status()

    @app.post("/api/reagents/settings", dependencies=SETTINGS)
    def api_reagent_settings(body: dict = Body(default={})):
        changes = {k: body[k] for k in ("push", "auto_minutes") if k in body}
        return _call(inv.save_settings, **changes)

    @app.post("/api/reagents/repository", dependencies=SETTINGS)
    def api_reagent_repository(body: dict = Body(default={})):
        """Use another repository (Settings → Reagents & consumables); the old copy is kept, renamed."""
        if getattr(inv, "locked", None):
            return JSONResponse({"error": tr("The repository is set in config.toml on this computer — change it there.")}, status_code=422)
        r = _call(inv.set_repository, str(body.get("repo") or ""), str(body.get("branch") or "main"))
        return r if isinstance(r, JSONResponse) else {**r, "status": inv.status()}

    @app.post("/api/reagents/start", dependencies=SETTINGS)
    def api_reagent_start(request: Request):
        """A new lab: an empty reagents workbook (and the consumables' with it)."""
        r = _call(inv.start_workbook, _who(request))
        return r if isinstance(r, JSONResponse) else {"started": r, "status": inv.status()}

    @app.post("/api/reagents/sync", dependencies=SETTINGS)
    async def api_reagent_sync(request: Request):
        return _steps_tr(await asyncio.to_thread(inv.sync, _who(request)))

    @app.get("/api/reagents/history")
    def api_reagent_history(limit: int = 200):
        return {"commits": inv.history(limit=limit)}

    # ---- the tidy-up by a local model (mister_plis/tidy.py) ---------------------------------
    if tidy is not None:
        @app.get("/api/reagents/tidy")
        async def api_tidy_status():
            return _tidy_tr(await asyncio.to_thread(tidy.status))

        @app.post("/api/reagents/tidy/settings", dependencies=SETTINGS)
        def api_tidy_settings(body: dict = Body(default={})):
            changes = {k: body[k] for k in ("model", "schedule", "at", "apply") if k in body}
            return _call(lambda: (tidy.save_settings(**changes), _tidy_tr(tidy.status(check_model=False)))[1])

        @app.post("/api/reagents/tidy/run", dependencies=SETTINGS)
        def api_tidy_run(request: Request):
            if not tidy.start(_who(request)):
                return JSONResponse({"error": tr("A tidy-up is already running.")}, status_code=409)
            return _tidy_tr(tidy.status(check_model=False))

        @app.post("/api/reagents/tidy/apply-all", dependencies=SETTINGS)
        async def api_tidy_apply_all(request: Request):
            try:
                await asyncio.to_thread(tidy.apply_all, _who(request))
            except ToolError as e:
                return JSONResponse({"error": tr(str(e))}, status_code=422)
            return _tidy_tr(tidy.status(check_model=False))

        @app.post("/api/reagents/tidy/{pid}", dependencies=SETTINGS)
        async def api_tidy_decide(request: Request, pid: str, body: dict = Body(default={})):
            try:
                await asyncio.to_thread(tidy.decide, pid, str(body.get("action") or ""), _who(request))
            except ToolError as e:
                return JSONResponse({"error": tr(str(e))}, status_code=422)
            return _tidy_tr(tidy.status(check_model=False))

    # ---- info from the lab: one list for reagents and consumables ------------------------------
    @app.get("/api/reagents/info")
    def api_reagent_infos(reagent: str = "", consumable: str = ""):
        if consumable and consumables is not None:
            return {"items": consumables.infos(consumable)}
        return {"items": inv.infos(reagent)}

    @app.get("/api/reagents/info.md")
    def api_reagent_infos_md():
        return PlainTextResponse(inv.info_markdown(), media_type="text/markdown; charset=utf-8")

    @app.post("/api/reagents/info", dependencies=WORK)
    def api_reagent_info_add(request: Request, body: dict = Body(default={})):
        return _call(inv.add_info, str(body.get("text") or ""), _who(request), str(body.get("reagent") or ""), str(body.get("page") or ""),
                     str(body.get("consumable") or ""))

    @app.post("/api/reagents/info/{iid}", dependencies=WORK)
    def api_reagent_info_set(request: Request, iid: str, body: dict = Body(default={})):
        return _call(inv.set_info, iid, str(body.get("status") or ""), _who(request), status=404)

    @app.delete("/api/reagents/info/{iid}", dependencies=WORK)
    def api_reagent_info_delete(request: Request, iid: str):
        return _call(lambda: (inv.delete_info(iid, _who(request)), {"ok": True})[1], status=404)

    for name, store in spaces:
        _space(app, page, store, SPACES[name], consumables is not None, table_pdf, calculator if name == "reagents" else None,
               access)


def _space(app: FastAPI, page: Callable, inv: Inventory, sp: dict, both: bool, table_pdf: Callable | None = None,
           calculator=None, access: tuple[Callable, Callable] | None = None) -> None:
    """The pages and the per-item API of one space (/reagents or /consumables). ``calculator``: a reagent's link to the
    solution calculator (calculator.py)."""
    SETTINGS, WORK = _marks(access)
    base, apiu, kind = sp["base"], sp["api"], sp["kind"]
    gone = ("There is no such consumable — it may have been deleted." if kind == "consumables"
            else "There is no such reagent — it may have been deleted.")

    def view(request: Request, name: str, rid: str = "") -> HTMLResponse:
        return page(request, "inventory/reagents.html", reagents_view=name, reagent_id=rid, hide_side_panels=True,
                    reagents_sync=bool(inv.url), space=sp, spaces_both=both)

    def missing(request: Request) -> HTMLResponse:
        return page(request, "notfound.html", message=tr(gone))

    # ---- pages ------------------------------------------------------------------------
    @app.get(base, response_class=HTMLResponse, name=f"{kind}_page")
    def list_page(request: Request):
        return view(request, "list")

    @app.get(base + "/order", response_class=HTMLResponse, name=f"{kind}_order_page")
    def order_page(request: Request):
        return view(request, "order")

    @app.get(base + "/info", response_class=HTMLResponse, name=f"{kind}_info_page")
    def info_page(request: Request):
        return view(request, "info")

    @app.get(base + "/new", response_class=HTMLResponse, name=f"{kind}_new_page")
    def new_page(request: Request):
        return view(request, "edit")

    @app.get(base + "/{rid}", response_class=HTMLResponse, name=f"{kind}_item_page")
    def item_page(request: Request, rid: str):
        try:
            inv.get(rid)
        except ToolError:
            return missing(request)
        return view(request, "item", rid)

    @app.get(base + "/{rid}/edit", response_class=HTMLResponse, name=f"{kind}_edit_page")
    def edit_page(request: Request, rid: str):
        try:
            inv.get(rid)
        except ToolError:
            return missing(request)
        return view(request, "edit", rid)

    # ---- API: the list, fields ---------------------------------------------------------------
    def _all(request: Request) -> dict:
        lang = _lang(request)
        cfg = inv.config()
        return {"fields": inv.fields(lang), "items": inv.items(lang), "categories": inv.categories(),
                "config": {**{k: cfg[k] for k in ("key", "title", "quick", "list", "hidden")}, "pdf": inv.pdf_config()}, "sync": bool(inv.url),
                "ready": inv.book() is not None, "open_info": sum(1 for i in inv.infos() if i.get("status") != "done")}

    @app.get(apiu, name=f"api_{kind}")
    def api_all(request: Request):
        return _call(_all, request)

    @app.post(apiu + "/fields", dependencies=SETTINGS, name=f"api_{kind}_fields")
    def api_fields_save(request: Request, body: dict = Body(default={})):
        return _call(lambda: (inv.set_columns(list(body.get("columns") or []), dict(body.get("display") or {}), _who(request)), _all(request))[1])

    # ---- files: the order list, the whole inventory ---------------------------------------
    @app.get(apiu + "/order.{fmt}", name=f"api_{kind}_order_file")
    def api_order_file(request: Request, fmt: str):
        if fmt == "pdf" and table_pdf is not None:
            return order_pdf(request)
        if fmt not in ("csv", "xlsx"):
            return JSONResponse({"error": tr("Unknown format")}, status_code=404)
        return _table_response(order_rows(inv, _lang(request)), tr("to-order"), fmt)

    def order_pdf(request: Request) -> Response:
        """What is still to be ordered, grouped by producer, in the app's own PDF look (like every other printout)."""
        cons = kind == "consumables"
        state, maker, name = tr("State"), tr("Brand") if cons else tr("Manufacturer"), tr("Name")
        rows = [r for r in order_rows(inv, _lang(request)) if r.get(state) == tr("To order")]
        rows.sort(key=lambda r: (not r.get(maker), str(r.get(maker) or "").casefold(), str(r.get(name) or "").casefold()))
        columns = [c for c in (rows[0] if rows else {}) if c != state]
        table = {"columns": columns, "rows": [[r.get(c) for c in columns] for r in rows], "numeric": [False] * len(columns)}
        n = len(rows)
        note = tn(n, "{n} consumable", "{n} consumables") if cons else tn(n, "{n} reagent", "{n} reagents")
        kicker = tr("Consumables inventory") if cons else tr("Reagent inventory")
        filename = f"{time.strftime('%Y-%m-%d')}_{safe_filename(tr('to-order'))}.pdf"
        return table_pdf(request, table, tr("To order"), filename, kicker=kicker, note=note)

    @app.post(apiu + "/list.{fmt}", dependencies=WORK, name=f"api_{kind}_list_file")
    async def api_list_file(request: Request, fmt: str):
        """What the list shows (its filters, its order, its columns) as Excel, CSV or a PDF to print. Posted by the
        page as a form field ``data`` (JSON: ids, columns, filters, sort, desc), so the file opens like any link."""
        if fmt not in ("csv", "xlsx", "pdf") or (fmt == "pdf" and table_pdf is None):
            return JSONResponse({"error": tr("Unknown format")}, status_code=404)
        form = await request.form()
        try:
            data = json.loads(str(form.get("data") or "{}"))
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return JSONResponse({"error": tr("Bad list data")}, status_code=422)
        lang = _lang(request)
        try:
            table = await asyncio.to_thread(shown_table, inv, data, lang, fmt == "pdf")
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=422)
        stamp = time.strftime("%Y-%m-%d")
        if fmt != "pdf":
            return _grid_response(table["columns"], table["rows"], kind, fmt)
        pc, filters = inv.pdf_config(), _filters(data)
        cons = kind == "consumables"
        n = len(table["rows"])
        note = tn(n, "{n} consumable", "{n} consumables") if cons else tn(n, "{n} reagent", "{n} reagents")
        sort = " ".join(str(data.get("sort") or "").split())[:80]
        if sort:
            note += ". " + tr("Sorted by {column}{order}.", column=sort, order=tr(" (descending)") if data.get("desc") else "")
        word = tr("Consumables") if cons else tr("Reagents")
        title = (" · ".join(v for _, v in filters)[:120] if pc["filters"] and filters else "") or word
        kicker = tr("Consumables inventory") if cons else tr("Reagent inventory")
        return await asyncio.to_thread(table_pdf, request, table, title, f"{stamp}_{safe_filename(title)}.pdf", kicker=kicker,
                                       params=filters if pc["filters"] else [], params_caption="FILTERS", note=note,
                                       size=11 if pc["size"] == "large" else 8)

    @app.get(apiu + "/inventory.{fmt}", name=f"api_{kind}_workbook")
    def api_workbook(fmt: str):
        cfg = inv.config()
        p = inv.repo / (cfg["workbook"] if fmt == "xlsx" else cfg["csv"] if fmt == "csv" else "-")
        if fmt not in ("csv", "xlsx") or not p.is_file():
            return JSONResponse({"error": tr("Unknown format")}, status_code=404)
        return FileResponse(p, filename=f"{time.strftime('%Y-%m-%d')}_{p.name}")

    # ---- one item --------------------------------------------------------------------
    @app.post(apiu, dependencies=WORK, name=f"api_{kind}_add")
    def api_add(request: Request, body: dict = Body(default={})):
        return _call(inv.save, dict(body.get("values") or {}), _who(request))

    @app.get(apiu + "/{rid}", name=f"api_{kind}_item")
    def api_item(request: Request, rid: str):
        lang = _lang(request)
        try:
            item = inv.get(rid, lang)
        except ToolError as e:
            return JSONResponse({"error": tr(str(e))}, status_code=404)
        return {"item": item, "fields": inv.fields(lang), "categories": inv.categories(), "history": inv.history(rid, 50),
                "info": inv.infos(rid), "calculator": calculator.link(item) if calculator is not None else ""}

    @app.post(apiu + "/{rid}", dependencies=WORK, name=f"api_{kind}_save")
    def api_save(request: Request, rid: str, body: dict = Body(default={})):
        return _call(inv.save, dict(body.get("values") or {}), _who(request), rid, str(body.get("base") or ""))

    @app.post(apiu + "/{rid}/restock", dependencies=WORK, name=f"api_{kind}_restock")
    def api_restock(request: Request, rid: str, body: dict = Body(default={})):
        amount = body.get("amount")
        try:
            slot = int(body.get("slot") or 1)
        except (TypeError, ValueError):
            slot = 0
        note = body.get("note")
        return _call(inv.set_restock, rid, slot, str(body.get("state") or ""), _who(request),
                     None if amount is None else str(amount), body.get("count"), None if note is None else str(note))

    @app.post(apiu + "/{rid}/dispose", dependencies=WORK, name=f"api_{kind}_dispose")
    def api_dispose(request: Request, rid: str, body: dict = Body(default={})):
        return _call(inv.dispose, rid, _who(request), bool(body.get("undo")))
