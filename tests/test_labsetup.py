"""Setting a server up from a lab file (mister_plis/labsetup.py, docs/LAB_SETUP_PLAN.md)."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mister_plis import labsetup
from mister_plis.backup import Backups
from mister_plis.labels import Printer
from mister_plis.labsetup import LabFileError, LabSetup, dumps, normalize, parse
from mister_plis.modules import Modules
from mister_plis.toolsources import ToolSources

ROOT = Path(__file__).resolve().parents[1]
TOYS = Path(__file__).parent / "fixtures" / "modules"


@pytest.mark.parametrize("path", sorted((ROOT / "labs").glob("*.toml")), ids=lambda p: p.name)
def test_every_lab_file_in_the_repository_reads(path):
    lab, warnings = parse(path.read_text(encoding="utf-8"), str(path))  # read from its folder: a logo is found next to it
    assert not warnings, warnings
    assert parse(dumps(lab))[0] == lab  # and survives being written out again


def test_what_is_wrong_is_listed_and_unknown_keys_are_warned_about():
    with pytest.raises(LabFileError) as e:
        parse('[lab]\nname = 5\n[backup]\nafter_days = 2\nfolder = "relative/path"\n'
              '[[tool_sources]]\nname = "Bad Name"\nurl = "ftp://x"\n[modules]\non = 3\n')
    text = str(e.value)
    for bit in ("[lab] name", "[backup] after_days", "[backup] folder", "name should be", "url should be", "[modules] on"):
        assert bit in text, bit
    lab, warnings = parse('[lab]\nname = "  Smith   Lab "\ncolour = "red"\n[weather]\nsunny = true\n')
    assert lab == {"lab": {"name": "Smith Lab"}} and len(warnings) == 2
    with pytest.raises(LabFileError, match="format 2"):
        parse("[lab_file]\nformat = 2\n")
    with pytest.raises(LabFileError, match="TOML"):
        parse("[lab\n")


def test_tables_of_modules_and_tools_are_kept_as_they_are():
    lab, _ = normalize({"module": {"hello": {"repo": "x", "n": 3}}, "tool": {"toy-table": {"program": "/bin/true"}},
                        "modules": {"on": ["hello", "hello"]}})
    assert lab == {"module": {"hello": {"repo": "x", "n": 3}}, "tool": {"toy-table": {"program": "/bin/true"}},
                   "modules": {"on": ["hello"]}}
    text = dumps({**lab, "lab": {"name": "Łódź \"Lab\""}})
    assert "[module.hello]" in text and '[tool.toy-table]' in text and parse(text)[0]["lab"]["name"] == 'Łódź "Lab"'


def test_a_server_from_before_lab_files_counts_as_set_up(tmp_path):
    new, old, done = tmp_path / "new", tmp_path / "old", tmp_path / "done"
    new.mkdir(), old.mkdir(), done.mkdir()
    (old / "lab_settings.json").write_text("{}", encoding="utf-8")
    (done / "lab.json").write_text('{"format": 1, "state": "skipped"}', encoding="utf-8")
    assert not labsetup.migrate(new) and labsetup.is_new(new)
    (new / "jobs").mkdir()  # what a new server makes by itself doesn't pass it off as an old one at the next start
    assert not labsetup.migrate(new) and labsetup.is_new(new)
    assert labsetup.migrate(old) and not labsetup.is_new(old) and labsetup.read_state(old)["from"] == "migrated"
    assert not labsetup.migrate(done) and labsetup.read_state(done)["state"] == "skipped"


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
                          cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace").stdout


def test_the_tool_source_an_old_server_cloned_is_kept(tmp_path):
    from test_toolsources import make_source

    bare = make_source(tmp_path, "lab", {"t-one": "One"})
    data = tmp_path / "data"
    (data / "tool-sources").mkdir(parents=True)
    _git(data / "tool-sources", "clone", "-q", str(bare), "lab")
    ts = ToolSources(data)
    assert ts.migrate() and not ts.migrate()
    assert ts.sources() == [{"name": "lab", "url": str(bare), "branch": "main", "enabled": True, "pinned": None, "trusted": True}]


@pytest.fixture
def setup(tmp_path):
    """A LabSetup over stores of its own (the app's are shared by every test)."""
    data = tmp_path / "data"
    data.mkdir()
    jobs = SimpleNamespace(root=tmp_path / "storage" / "jobs", jobs={})
    auto = {"mode": "off"}
    updater = SimpleNamespace(auto_settings=lambda: dict(auto), set_auto=lambda m: auto.update(mode=m))
    storage = SimpleNamespace(check_folder=lambda *a: None, choose=lambda *a: None)
    ts = ToolSources(data)
    ts._save([])
    mods = Modules(root=TOYS)
    return LabSetup(data, backups=Backups(data, jobs), printer=Printer(data), toolsources=ts, modules=mods, registry=None,
                    jobs_count=lambda: 0, updater=updater, storage=storage)


def test_a_plan_shows_old_and_new_and_changes_nothing(setup, tmp_path):
    backup = tmp_path / "nas"
    backup.mkdir()
    lab, _ = parse(f'[lab]\nname = "Smith Lab"\nlanguage = "pl"\n[backup]\nfolder = \'{backup}\'\nafter_days = 3\n'
                   '[label_printer]\naddress = "192.168.1.50"\ntape_mm = 18\n[updates]\nauto = "night"\n'
                   '[jobs]\nkeep_days = 60\n')
    rows = {(r["section"], r["key"]): r for r in setup.plan(lab)}
    assert rows[("lab", "name")] | {} == {**rows[("lab", "name")], "old": "", "new": "Smith Lab", "status": "change"}
    assert rows[("backup", "after_days")]["old"] == 1 and rows[("label_printer", "tape_mm")]["old"] == 12
    assert rows[("jobs", "keep_days")]["old"] == 30 and rows[("updates", "auto")]["status"] == "change"
    assert setup.backups.settings().lab_name == "" and not (setup.data_path / "label_printer.json").exists()

    r = setup.apply(lab, "Ada", "labs/smith.toml")
    assert all(x["status"] == "done" for x in r["rows"]), r["rows"]
    cur = setup.backups.settings()
    assert (cur.lab_name, cur.language, cur.backup_dir, cur.backup_after_days, cur.keep_days) == \
        ("Smith Lab", "pl", str(backup.resolve()), 3, 60)
    assert setup.printer.settings().address == "192.168.1.50" and setup.printer.settings().tape_mm == 18
    assert setup.updater.auto_settings()["mode"] == "night"
    state = setup.state()
    assert state["status"] == "set_up" and state["by"] == "Ada" and state["from"] == "labs/smith.toml"
    assert all(x["status"] == "same" for x in setup.plan(lab))  # applying it again would change nothing


def test_a_setting_that_cant_be_set_is_reported_and_the_rest_still_are(setup, tmp_path):
    lab, _ = parse(f'[lab]\nname = "Smith Lab"\n[backup]\nfolder = \'{tmp_path / "no" / "such" / "folder"}\'\n')
    rows = {r["key"]: r for r in setup.plan(lab)}
    assert rows["folder"]["status"] == "error" and "no folder" in rows["folder"]["note"]
    r = setup.apply(lab)
    assert {x["key"]: x["status"] for x in r["rows"]} == {"name": "done", "folder": "error"}
    assert setup.backups.settings().lab_name == "Smith Lab"


def test_tool_sources_from_a_lab_file(setup, tmp_path):
    from test_toolsources import make_source

    ours = make_source(tmp_path, "ours", {"t-one": "One"})
    theirs = make_source(tmp_path, "theirs", {"t-two": "Two"})
    lab, _ = normalize({"tool_sources": [{"name": "ours", "url": ours.as_uri(), "trusted": True},
                                         {"name": "theirs", "url": theirs.as_uri()}]})
    assert [r["status"] for r in setup.plan(lab)] == ["change", "change"]
    r = setup.apply(lab)
    assert r["restart"] and [x["status"] for x in r["rows"]] == ["done", "done"]
    src = {s["name"]: s for s in setup.toolsources.sources()}
    assert src["ours"]["trusted"] and src["ours"]["enabled"] and not setup.toolsources.cloned("ours")  # fetched at start
    assert not src["theirs"]["trusted"] and not src["theirs"]["enabled"] and src["theirs"]["pinned"]  # reviewed first
    other, _ = normalize({"tool_sources": [{"name": "ours", "url": theirs.as_uri(), "trusted": True}]})
    assert setup.plan(other)[0]["status"] == "error"  # never swapped for another repository under the same name


def test_module_and_tool_tables_wait_for_what_isnt_loaded(setup):
    lab, _ = normalize({"module": {"hello": {"greeting": "hi"}, "nosuch": {"x": 1}}, "tool": {"toy-table": {"program": "/bin/sh"}}})
    rows = setup.plan(lab)
    status = {(r["section"], r["key"]): r["status"] for r in rows}
    assert status[("module.hello", "greeting")] == "later" and status[("module.nosuch", "")] == "error"
    assert status[("tool.toy-table", "program")] == "later"
    r = setup.apply(lab)
    assert r["restart"]
    assert setup.state()["pending"] == {"module": {"hello": {"greeting": "hi"}}, "tool": {"toy-table": {"program": "/bin/sh"}}}


def test_a_waiting_tool_table_is_applied_when_its_tool_is_here(setup, client):
    from mister_plis import toolsettings
    from mister_plis.app import registry

    before = toolsettings.record("toy-table")
    try:
        setup.registry = registry
        setup._pending("tool", "toy-table", {"program": "/bin/sh"})
        setup.apply_pending_tools()
        assert toolsettings.saved("toy-table")["program"] == "/bin/sh" and not setup.state()["pending"]
        assert setup.current()["tool"]["toy-table"] == {"program": "/bin/sh"}
    finally:
        f = toolsettings._file("toy-table")
        f.write_text(json.dumps(before), encoding="utf-8") if before else f.unlink(missing_ok=True)


def test_the_lab_language_is_for_browsers_that_havent_chosen(monkeypatch):
    from mister_plis import prefs

    monkeypatch.setattr(prefs, "lab_language", lambda: "pl")
    assert prefs.from_cookies({})["lang"] == "pl" and prefs.from_cookies({"lang": "en"})["lang"] == "en"
    monkeypatch.setattr(prefs, "lab_language", lambda: "")
    assert prefs.from_cookies({})["lang"] == "en"


def test_the_command_line_checks_applies_and_exports(tmp_path):
    lab = tmp_path / "smith.toml"
    lab.write_text('[lab]\nname = "Smith Lab"\n[label_printer]\ntape_mm = 24\n[tool."no-such-tool"]\nx = 1\n', encoding="utf-8")
    env = {**os.environ, "MISTER_PLIS_DATA_DIR": str(tmp_path / "data"), "MISTER_PLIS_MODULES": "none"}

    def run(*args):
        return subprocess.run([sys.executable, "-m", "mister_plis", *args], cwd=ROOT, env=env, capture_output=True, text=True,
                              timeout=240, encoding="utf-8", errors="replace")

    r = run("setup", str(lab), "--check", "--no-network")
    assert r.returncode == 0 and "“” → “Smith Lab”" in r.stdout and "later" in r.stdout, r.stdout + r.stderr
    assert labsetup.is_new(tmp_path / "data")
    r = run("setup", str(lab), "--yes", "--no-network")
    assert r.returncode == 0 and "done" in r.stdout, r.stdout + r.stderr
    assert not labsetup.is_new(tmp_path / "data")
    r = run("setup", str(lab), "--yes", "--if-new")
    assert r.returncode == 0 and "set up already" in r.stdout
    r = run("export")
    exported = parse(r.stdout)[0]
    assert exported["lab"]["name"] == "Smith Lab" and exported["label_printer"]["tape_mm"] == 24
    bad = tmp_path / "bad.toml"
    bad.write_text("[lab]\nname = 1\n", encoding="utf-8")
    assert run("setup", str(bad), "--check").returncode == 2


def test_the_template_names_every_setting():
    """labs/template.toml, with its "# " taken off, is a lab file naming every setting the reader knows (each module's
    questions included), so the two can't drift apart."""
    import importlib
    import re

    text = (ROOT / "labs" / "template.toml").read_text(encoding="utf-8")
    assert parse(text)[0] == {}  # as it comes: changes nothing
    lines = [re.sub(r"^# ", "", line) if re.match(r'^# (\[|[A-Za-z_"<][^=]*=)', line) else line for line in text.splitlines()]
    raw = __import__("tomllib").loads("\n".join(lines))
    assert raw.pop("tool") == {"<tool id>": {"<setting>": "/Applications/Blender.app/Contents/MacOS/Blender"}}
    lab, warnings = normalize(raw)
    assert not warnings
    for section, keys in labsetup.BASE.items():
        assert set(lab[section]) == set(keys), section
    assert set(lab["tool_sources"][0]) == labsetup.SOURCE_KEYS and lab["modules"]["on"]
    for mid in Modules().available():
        fields = {f.key for f in importlib.import_module(f"modules.{mid}").module.setup_fields}
        assert set(lab.get("module", {}).get(mid, {})) == fields, mid
