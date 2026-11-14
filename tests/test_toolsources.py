"""Tool sources: tools from git repositories (reorg P7, mister_plis/toolsources.py)."""

import subprocess
import textwrap
from pathlib import Path

import pytest

from mister_plis.errors import ToolError
from mister_plis.registry import Registry
from mister_plis.toolsources import ToolSources, toolkit_ok


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
                          cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace").stdout


TOOL = '''
from mister_plis.toolkit import Tool, outputs as O
from ._helper import WORD

tool = Tool(id="{id}", name="{name}", category="Test", live=True)


@tool.runner
def run(p, ctx):
    return O.Metric("{label}", 1, unit=WORD)
'''


def make_source(tmp: Path, name: str, tools: dict, word: str = "w", toolkit: str = ">=1,<2", locale: dict | None = None,
                requirements: str = "") -> Path:
    """A bare repository (the "GitHub" side) with a tools folder; returns its file:// URL folder."""
    work = tmp / f"{name}-work"
    work.mkdir()
    (work / "mister-plis-tools.toml").write_text(f'[source]\nname = "{name}"\ntitle = "{name.title()} tools"\nrequires_toolkit = "{toolkit}"\n', encoding="utf-8")
    (work / "_helper.py").write_text(f"WORD = {word!r}\n", encoding="utf-8")
    for tid, label in tools.items():
        (work / f"{tid.replace('-', '_')}.py").write_text(textwrap.dedent(TOOL.format(id=tid, name=tid.title(), label=label)), encoding="utf-8")
    if locale:
        (work / "locale").mkdir()
        (work / "locale" / "pl.py").write_text(f"PL = {locale!r}\n", encoding="utf-8")
    if requirements:
        (work / "requirements.txt").write_text(requirements, encoding="utf-8")
    _git(work, "init", "-q")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "tools")
    bare = tmp / f"{name}.git"
    _git(tmp, "clone", "-q", "--bare", str(work), str(bare))
    _git(work, "remote", "add", "origin", str(bare))
    return bare


def push(work: Path, msg: str, files: dict) -> str:
    for rel, text in files.items():
        (work / rel).write_text(text, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", msg)
    _git(work, "push", "-q", "origin", "HEAD:main")
    return _git(work, "rev-parse", "HEAD").strip()


@pytest.fixture
def ts(tmp_path):
    s = ToolSources(tmp_path / "data")
    s._save([])  # no lab source in these tests
    return s


def test_toolkit_versions():
    assert toolkit_ok(">=1,<2", 1) and toolkit_ok("1", 1) and toolkit_ok("", 1)
    assert not toolkit_ok(">=2", 1) and not toolkit_ok("nonsense", 1)
    # 1.1 (tool settings): the lab's ">=1,<2" still loads; a source asking for 1.1 loads here and not on a 1.0 base
    assert toolkit_ok(">=1,<2", "1.1") and toolkit_ok("1", "1.1") and toolkit_ok("==1", "1.1") and toolkit_ok("<=1", "1.1")
    assert toolkit_ok(">=1.1,<2", "1.1") and not toolkit_ok(">=1.1,<2", 1) and not toolkit_ok(">=1.2", "1.1")
    assert not toolkit_ok(">1", "1.1") and not toolkit_ok("<1.1", "1.1") and toolkit_ok("==1.1", "1.1")


def test_a_trusted_source_is_cloned_and_its_tools_load(tmp_path, ts):
    bare = make_source(tmp_path, "lab", {"alpha": "A"}, word="lab-word")
    s = ts.add(bare.as_uri(), "lab", trusted=True)
    assert s["enabled"] and not s["pinned"] and s["review"]["manifest"]["title"] == "Lab tools"
    folders = ts.folders()
    assert [f["name"] for f in folders][0] == "lab" and folders[0]["commit"]
    assert [f["name"] for f in folders] == ["lab"]
    reg = Registry()
    reg.load([f for f in folders if f["name"] == "lab"])
    t = reg.get("alpha")
    assert t.source == "lab" and t.source_commit == folders[0]["commit"] and not reg.broken
    out = t.run_fn({}, None)
    assert out.unit == "lab-word"  # its own helper module (relative import)


def test_a_local_folder_stands_in_for_the_source_of_its_name(tmp_path, ts):
    bare = make_source(tmp_path, "lab", {"alpha": "A"}, word="clone")
    ts.add(bare.as_uri(), "lab", trusted=True)
    work = tmp_path / "lab-work"  # the working copy make_source pushed from: its manifest says "lab"
    push(work, "local edit", {"_helper.py": "WORD = 'working copy'\n"})
    ts.local_paths = [work, tmp_path / "missing"]
    folders = ts.folders()
    assert [(f["name"], f["local"]) for f in folders] == [("lab", True), ("missing", True)]  # the clone is left out
    assert folders[0]["path"] == work and folders[0]["commit"] and "isn't there" in folders[1]["error"]
    reg = Registry()
    reg.load(folders)
    assert reg.get("alpha").run_fn({}, None).unit == "working copy"
    status = {(s["name"], bool(s.get("local"))): s for s in ts.status()}
    assert status[("lab", False)]["replaced_by_local"] and status[("lab", True)]["url"] == str(work)


def test_no_sources_no_tools(tmp_path, ts):
    assert ts.folders() == []
    reg = Registry()
    reg.load([])
    assert not reg.tools and not reg.broken


def test_two_sources_never_mix_their_helpers_and_the_first_id_wins(tmp_path, ts):
    a = make_source(tmp_path, "one", {"shared-id": "from one", "only-one": "x"}, word="ONE")
    b = make_source(tmp_path, "two", {"shared-id": "from two", "only-two": "y"}, word="TWO")
    ts.add(a.as_uri(), "one", trusted=True)
    ts.add(b.as_uri(), "two", trusted=True)
    reg = Registry()
    reg.load(ts.folders())
    assert reg.get("shared-id").source == "one" and reg.get("only-one").run_fn({}, None).unit == "ONE"
    assert reg.get("only-two").run_fn({}, None).unit == "TWO"  # same helper file name, its own module
    assert any("Duplicate tool id 'shared-id'" in b.error and "one" in b.error for b in reg.broken)


def test_a_public_source_is_reviewed_before_it_runs(tmp_path, ts):
    bare = make_source(tmp_path, "other", {"beta": "B"}, requirements="")
    s = ts.add(bare.as_uri(), "other")  # not trusted
    assert not s["enabled"] and s["pinned"] and "beta.py" in s["review"]["files"]
    assert "other" not in [f["name"] for f in ts.folders()]  # switched off: not loaded
    ts.set_enabled("other", True)
    assert "other" in [f["name"] for f in ts.folders()]
    with pytest.raises(ToolError, match="stays pinned"):
        ts.set_pin("other", False)
    new = push(tmp_path / "other-work", "more", {"gamma.py": textwrap.dedent(TOOL.format(id="gamma", name="Gamma", label="G"))})
    c = ts.check("other")
    assert [x["subject"] for x in c["incoming"]] == ["more"] and any("gamma.py" in f for f in c["files"]) and c["target"] == new
    with pytest.raises(ToolError, match="Check the source first"):
        ts.update("other")
    r = ts.update("other", to=c["target"])
    assert r["ok"] and r["changed"] and ts.get("other")["pinned"] == new
    assert (ts.folder("other") / "gamma.py").is_file()


def test_a_public_source_never_gets_the_token(tmp_path, ts, monkeypatch):
    from mister_plis import gitutil

    calls = []
    real = gitutil.run
    monkeypatch.setattr(gitutil, "run", lambda *a, **kw: (calls.append(kw), real(*a, **kw))[1])
    bare = make_source(tmp_path, "pub", {"theta": "T"})
    ts.add(bare.as_uri(), "pub")
    assert calls and all(not kw.get("credentials") and "credential.helper=" in kw.get("options", ()) for kw in calls)
    calls.clear()
    lab = make_source(tmp_path, "lab", {"alpha": "A"})
    ts.add(lab.as_uri(), "lab", trusted=True)
    assert any(kw.get("credentials") for kw in calls)  # the lab's own: with the server's token


def test_updates_never_overwrite_edits_and_follow_branches(tmp_path, ts):
    bare = make_source(tmp_path, "lab", {"alpha": "A"})
    ts.add(bare.as_uri(), "lab", trusted=True)
    work = tmp_path / "lab-work"
    push(work, "fix", {"alpha.py": textwrap.dedent(TOOL.format(id="alpha", name="Alpha", label="A2"))})
    (ts.folder("lab") / "alpha.py").write_text("# edited on the server\n", encoding="utf-8")
    with pytest.raises(ToolError, match="changed"):
        ts.update("lab")
    _git(ts.folder("lab"), "checkout", "--", "alpha.py")
    assert ts.update("lab")["changed"] and 'label="A2"' not in (ts.folder("lab") / "alpha.py").read_text(encoding="utf-8")
    assert '"A2"' in (ts.folder("lab") / "alpha.py").read_text(encoding="utf-8")
    _git(work, "checkout", "-q", "-b", "try")
    push_branch = lambda: (_git(work, "add", "-A"), _git(work, "commit", "-q", "-m", "on try"), _git(work, "push", "-q", "origin", "try"))  # noqa: E731
    (work / "delta.py").write_text(textwrap.dedent(TOOL.format(id="delta", name="Delta", label="D")), encoding="utf-8")
    push_branch()
    ts.switch("lab", "try")
    assert (ts.folder("lab") / "delta.py").is_file() and ts.get("lab")["branch"] == "try"
    ts.switch("lab", "main")
    assert not (ts.folder("lab") / "delta.py").exists()
    ts.remove("lab")
    assert not ts.folder("lab").exists() and not any(s["name"] == "lab" for s in ts.sources())


def test_a_source_for_another_toolkit_is_reported(tmp_path, ts):
    bare = make_source(tmp_path, "future", {"zeta": "Z"}, toolkit=">=2")
    ts.add(bare.as_uri(), "future", trusted=True)
    reg = Registry()
    reg.load([f for f in ts.folders() if f["name"] == "future"])
    assert reg.get("zeta") is None and any("needs toolkit >=2" in b.error for b in reg.broken)


def test_packages_that_would_change_the_base_are_refused(tmp_path, ts):
    bare = make_source(tmp_path, "heavy", {"eta": "E"}, requirements="pandas<1\n")
    ts.pip_extra = ["--no-index"]  # no network: a requirement the base's packages can't meet fails at once
    ts.add(bare.as_uri(), "heavy", trusted=True)
    r = ts._requirements(ts.get("heavy"))
    assert not r["ok"] and not r["installed"] and "nothing was installed" in r["output"]


def test_at_start_a_source_gets_the_packages_it_lacks(tmp_path, ts, monkeypatch):
    from mister_plis.pins import missing

    req = tmp_path / "req.txt"
    req.write_text("pandas>=1\nsurely-not-installed-pkg==1.0\nother; sys_platform == 'nonexistent-os'\n# a comment\n", encoding="utf-8")
    assert missing(req) == ["surely-not-installed-pkg==1.0"]  # installed ones and other platforms' are fine
    ok = make_source(tmp_path, "fine", {"theta": "T"}, requirements="pandas>=1\n")
    lacking = make_source(tmp_path, "lacking", {"iota": "I"}, requirements="pandas<1\n")
    ts.add(ok.as_uri(), "fine", trusted=True)
    ts.add(lacking.as_uri(), "lacking", trusted=True)
    ts.pip_extra = ["--no-index"]
    called = []
    real = ts._requirements
    monkeypatch.setattr(ts, "_requirements", lambda s, old="": called.append(s["name"]) or real(s, old))
    ts.ensure_requirements()
    assert called == ["lacking"]  # only the source whose packages aren't there
    assert "nothing was installed" in ts.errors["lacking"] and "fine" not in ts.errors


def test_a_sources_translations_are_used(tmp_path, ts):
    from mister_plis.locale import tool_catalogues

    bare = make_source(tmp_path, "lab", {"alpha": "A"}, locale={"Alpha": "Alfa"})
    ts.add(bare.as_uri(), "lab", trusted=True)
    cats = tool_catalogues([ts.folder("lab")])
    assert cats == [{"Alpha": "Alfa"}]


def test_a_job_whose_tool_is_gone_can_still_be_read(client):
    from mister_plis.app import jobs
    from mister_plis.toolkit import Tool, outputs as O

    gone = Tool(id="gone-tool", name="Gone tool", category="Test")

    @gone.runner
    def run(p, ctx):
        return O.Metric("Answer", 42)

    gone.source = "old_source"
    job = jobs.submit(gone, {})
    jobs.wait(job, 30)
    assert job.status == "done"
    page = client.get(f"/tool/gone-tool?job={job.id}")
    assert page.status_code == 200 and "installed on this server any more" in page.text and "old_source" in page.text
    assert client.get(f"/api/jobs/{job.id}").json()["outputs"][0]["label"] == "Answer"
    assert client.post("/api/tools/gone-tool/run", json={"params": {}}).status_code == 404  # it can't run again
    assert "There is no tool" in client.get("/tool/gone-tool").text
