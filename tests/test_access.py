"""Every route that changes something says whether it changes the lab's settings or is everyday work, and a change
must come from the server's own pages (mister_plis/access.py, docs/PREP_PLAN.md R9)."""

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from mister_plis import access

CHANGES = {"POST", "PUT", "PATCH", "DELETE"}


def _marks(route: APIRoute) -> list[str]:
    return [getattr(d.dependency, "access") for d in route.dependencies if hasattr(d.dependency, "access")]


def _routes():
    from mister_plis.app import app

    return [r for r in app.routes if isinstance(r, APIRoute) and r.methods & CHANGES]


def test_every_route_that_changes_something_is_marked(client):
    routes = _routes()
    assert len(routes) > 60  # the base's and the modules' (all of them are on in the tests)
    unmarked = sorted(f"{sorted(r.methods & CHANGES)} {r.path}" for r in routes if len(_marks(r)) != 1)
    assert not unmarked, "mark these with dependencies=SETTINGS or WORK (mister_plis/access.py):\n" + "\n".join(unmarked)


@pytest.mark.parametrize("path, kind", [
    ("/api/system/restart", "settings"), ("/api/tools/sources", "settings"), ("/api/setup/apply", "settings"),
    ("/api/transfer/export", "settings"), ("/api/system/credentials", "settings"), ("/api/label/printer", "settings"),
    ("/api/tools/{tool_id}/run", "work"), ("/api/label/print", "work"), ("/api/jobs/{job_id}/title", "work"),
    ("/api/history/clear", "work"),  # clearing everyone's asks for settings inside the route
    ("/api/tm/backup", "settings"), ("/api/notes/sync", "settings"), ("/api/reagents/sync", "settings"),
    ("/api/reagents/fields", "settings"), ("/api/reagents", "work"), ("/api/tm/projects", "work"),
])
def test_the_kind_of_each_change(client, path, kind):
    marks = {m for r in _routes() if r.path == path for m in _marks(r)}
    assert marks == {kind}, path


def test_a_member_may_work_but_not_change_settings(client, accounts_on):
    """With accounts, a member does the everyday work; only an admin changes the lab's settings."""
    assert client.post("/api/label/printer/check").status_code == 401  # signed out: nothing
    member = accounts_on("Mo Member")
    assert member.post("/api/system/restart").status_code == 403
    assert member.post("/api/tools/sources", json={}).status_code == 403
    assert member.post("/api/history/clear", json={"scope": "all"}).status_code == 403
    assert member.post("/api/history/clear", json={"scope": "mine"}).status_code != 403
    assert member.post("/api/label/preview.png", json={"labels": [{"name": "NaCl"}]}).status_code == 200
    admin = accounts_on("Ada Admin")
    assert admin.post("/api/label/printer/check").status_code != 403


def test_a_change_from_another_web_site_is_refused(client, monkeypatch):
    """A page elsewhere could otherwise restart the server: a POST without a body needs no permission from a browser."""
    from mister_plis import updater
    from mister_plis.config import settings

    host = "testserver"
    calls = []
    real = updater.schedule_restart
    updater.schedule_restart = lambda *a, **k: calls.append(1) or True
    monkeypatch.setattr(settings, "server_names", "testserver, lab.example.org")  # a proxy's name, in config.toml
    try:
        for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"},
                        {"Origin": "http://testserver.evil.example"}, {"Sec-Fetch-Site": "same-site"}):
            r = client.post("/api/system/restart", headers=headers)
            assert r.status_code == 403 and "another web site" in r.json()["error"], headers
        assert not calls
        for headers in ({}, {"Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"},
                        {"Origin": "https://lab.example.org", "X-Forwarded-Host": "lab.example.org"}):
            assert client.post("/api/system/restart", headers=headers).status_code == 200, headers
        assert len(calls) == 4
    finally:
        updater.schedule_restart = real
    assert client.get("/api/version", headers={"Origin": "https://evil.example"}).status_code == 200  # reading is fine


def test_a_module_marks_its_routes_through_its_context(tmp_path):
    """The base's services offer the marks (ctx.settings_access, ctx.work_access); a module never imports access."""
    from mister_plis.app import _Services

    assert _Services.settings_access is access.settings_access and _Services.work_access is access.work_access
    from fastapi import Depends, FastAPI

    app = FastAPI()

    @app.post("/x", dependencies=[Depends(_Services.settings_access)])
    def x():
        return {"ok": True}

    assert TestClient(app).post("/x").json() == {"ok": True}
