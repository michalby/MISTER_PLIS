"""A toy module for tests/test_modules.py: a page, an API route, a sidebar link, a panel, a thread, hooks."""
import threading

from fastapi import Request
from pathlib import Path

from mister_plis.modules import Hooks, Module, NavItem

HERE = Path(__file__).resolve().parent
ticked = threading.Event()


def setup(ctx):
    ctx.storage.mkdir(parents=True, exist_ok=True)
    return {"greeting": ctx.settings.get("greeting", "hello"), "ctx": ctx}


def register(app, ctx, svc):
    @app.get("/api/hello")
    def hello():
        return {"says": svc["greeting"], "storage": str(ctx.storage)}

    @app.get("/hello")
    def hello_page(request: Request):
        return ctx.page(request, "hello/hello.html")


def tick(svc):
    ticked.set()


module = Module(id="hello", name="Hello", setup=setup, register=register,
                nav=[NavItem(label="Hello", href="/hello", icon="tool", order=5)], threads=[tick],
                templates=HERE / "templates", static=HERE / "static", scripts={"*": ["hello.js"]}, styles=["hello.css"],
                panels={"system": ["panel.html"]},
                hooks=Hooks(job_flags=lambda job, full: {"hello_flag": True}, people=lambda: [("Ada", 1.0, "greeted")],
                            rename_person=lambda old, new, by: {"greeted": 1}))
