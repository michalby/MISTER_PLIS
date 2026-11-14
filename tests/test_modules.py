"""The module framework (mister_plis/modules.py, reorg P4): loading, hooks, and the base on its own."""

import os
import re
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from mister_plis.modules import Modules

ROOT = Path(__file__).resolve().parents[1]
TOYS = Path(__file__).parent / "fixtures" / "modules"


class _Services:
    def __init__(self, templates):
        self.templates = templates

    def page(self, request, name, **ctx):
        return self.templates.TemplateResponse(request, name, ctx)


def test_a_toy_module_plugs_in(tmp_path):
    app = FastAPI()
    templates = Jinja2Templates(directory=str(tmp_path))
    (tmp_path / "base.html").write_text("<body>{% block content %}{% endblock %}</body>", encoding="utf-8")
    mods = Modules(root=TOYS)
    mods.load(app, ["hello", "broken", "oldapi", "missing"], _Services(templates), tmp_path / "storage", tmp_path / "data",
              lambda mid: {"greeting": "ahoj"} if mid == "hello" else {}, templates.env)
    assert list(mods.loaded) == ["hello"]
    broken = dict(mods.broken)
    assert "broken on purpose" in broken["modules.broken"] and "module API 0" in broken["modules.oldapi"] and "modules.missing" in broken
    c = TestClient(app)
    assert c.get("/api/hello").json() == {"says": "ahoj", "storage": str(tmp_path / "storage" / "modules" / "hello")}
    assert 'id="hello-page"' in c.get("/hello").text  # its template, extending the base's
    assert c.get("/m/hello/static/hello.js").status_code == 200
    assert mods.nav() == [{"id": "hello", "label": "Hello", "href": "/hello", "icon": "tool", "icon_template": "", "title": "", "match": "/hello"}]
    assert mods.panels("system") == ["hello/panel.html"] and mods.panels("settings") == []
    assert mods.scripts("jobs") == ["/m/hello/static/hello.js"] and mods.styles() == ["/m/hello/static/hello.css"]
    assert mods.job_flags(object(), True) == {"hello_flag": True}
    assert mods.people() == [("Ada", 1.0, "greeted")] and mods.rename_person("a", "b", "me") == {"greeted": 1}

    toy = sys.modules[next(k for k in sys.modules if k.endswith("_hello"))]
    mods.start_threads()
    assert toy.ticked.wait(5)


def test_the_app_loads_its_modules(client):
    from mister_plis.app import modules

    assert "timemachine" in modules.loaded and not modules.broken
    page = client.get("/").text
    assert 'href="/timemachine"' in page and "/m/timemachine/static/timemachine.css" in page and "/m/timemachine/static/tm-button.js" in page
    assert 'id="tm-backup"' in client.get("/settings").text  # its panel on Settings → Jobs & backup


def test_the_base_runs_without_any_module(tmp_path):
    """modules = "none": the whole app still works — no Time Machine link, button, filter or route."""
    code = r'''
import json
from fastapi.testclient import TestClient
from mister_plis.app import app, modules
with TestClient(app) as c:
    out = {"loaded": list(modules.loaded)}
    for path in ("/", "/jobs", "/tool/toy-calc", "/tool/toy-table", "/settings", "/feedback"):
        r = c.get(path)
        # what belongs to the module (not the word: the footer shows the running commit's message)
        out[path] = [r.status_code, any(m in r.text for m in ('href="/timemachine"', "/m/timemachine/", "tm-btn", "data-flag=\"in_tm\"",
                                                              'href="/reagents"', "/m/inventory/", 'id="rg-',
                                                              'href="/notes"', 'id="notes-panel"', "/m/notebook/")),
                     "/api/tm" in r.text]
    out["/timemachine"] = c.get("/timemachine").status_code
    out["inventory"] = [c.get(u).status_code for u in ("/reagents", "/consumables", "/api/reagents/status")]
    out["notebook"] = [c.get(u).status_code for u in ("/notes", "/api/notes")]
    out["run"] = c.post("/api/tools/toy-calc/run", json={"params": {"compound": "salt", "conc": 1, "volume": 1}}).json()["status"]
    out["jobs"] = c.get("/api/jobs").status_code
print("RESULT" + json.dumps(out))
'''
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "lab.json").write_text('{"format": 1, "state": "skipped"}', encoding="utf-8")  # not led to the setup page
    env = {**os.environ, "MISTER_PLIS_MODULES": "none", "MISTER_PLIS_DATA_DIR": str(tmp_path / "data"), }
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=240, encoding="utf-8", errors="replace")
    import json

    line = next((x for x in r.stdout.splitlines() if x.startswith("RESULT")), None)
    assert line, r.stdout[-2000:] + r.stderr[-4000:]
    out = json.loads(line[len("RESULT"):])
    assert out["loaded"] == [] and out["/timemachine"] == 404 and out["run"] == "done" and out["jobs"] == 200
    assert out["inventory"] == [404, 404, 404] and out["notebook"] == [404, 404]
    for path in ("/", "/jobs", "/tool/toy-calc", "/tool/toy-table", "/settings", "/feedback"):
        assert out[path] == [200, False, False], (path, out[path])


# What the base may not mention: a module by name. The base finds modules through mister_plis/modules.py only.
FORBIDDEN = re.compile(r"timemachine|/api/tm\b|\bin_tm\b|tmButton|addToTM"  # Time Machine (P4)
                       r"|/api/reagents|/api/consumables|reagents_admin|reagents\.(js|css)|\brg-|modules\.inventory|reagents_web"  # inventory (P5)
                       r"|/api/notes|notes-panel|notes_enabled|hide_notes_panel|\bnotebook\b|obsidian|\bnotes\.js")  # lab notebook (P6)
ALLOWED = {  # documentation examples (comments / docstrings), not code
    "mister_plis/config.py", "mister_plis/modules.py",
}


def test_the_base_does_not_name_its_modules():
    bad = []
    for p in sorted((ROOT / "mister_plis").rglob("*")):
        rel = p.relative_to(ROOT).as_posix()
        if not p.is_file() or p.suffix not in (".py", ".html", ".js", ".css") or "/locale/" in rel or rel in ALLOWED:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                bad.append(f"{rel}:{n}: {line.strip()[:120]}")
    assert not bad, "\n".join(bad)
    for p in (ROOT / "mister_plis").rglob("*.py"):
        assert not re.search(r"^\s*(from|import)\s+modules\b", p.read_text(encoding="utf-8"), re.M), f"{p} imports a module directly"
