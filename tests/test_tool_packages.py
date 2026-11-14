"""A tool source's packages live with the instance, not in the app's own environment (docs/PREP_PLAN.md R6)."""

import json
import sys
import zipfile

import pytest

from mister_plis.registry import Registry
from mister_plis.toolsources import MARKER, ToolSources

from test_toolsources import make_source, push

PKG = "mp_toy_pkg_r6"


def _wheel(folder, version="1.0", answer=42):
    """A tiny wheel, to install with no network (pip --no-index --find-links)."""
    folder.mkdir(exist_ok=True)
    name = f"{PKG}-{version}-py3-none-any.whl"
    info = f"{PKG}-{version}.dist-info"
    with zipfile.ZipFile(folder / name, "w") as z:
        z.writestr(f"{PKG}/__init__.py", f"ANSWER = {answer}\n")
        z.writestr(f"{info}/METADATA", f"Metadata-Version: 2.1\nName: {PKG}\nVersion: {version}\n")
        z.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{info}/RECORD", f"{PKG}/__init__.py,,\n{info}/METADATA,,\n{info}/WHEEL,,\n{info}/RECORD,,\n")
    return folder


USES = '''
from mister_plis.toolkit import Tool, outputs as O

tool = Tool(id="{id}", name="Uses", category="Test", live=True)


@tool.runner
def run(p, ctx):
    import {pkg}
    return O.Metric("Answer", {pkg}.ANSWER)
'''


@pytest.fixture
def ts(tmp_path):
    s = ToolSources(tmp_path / "data")
    s._save([])
    s.pip_extra = ["--no-index", "--find-links", str(_wheel(tmp_path / "wheels"))]
    yield s
    for p in list(sys.path):
        if str(tmp_path) in p:
            sys.path.remove(p)
    for m in [m for m in sys.modules if m == PKG or m.startswith(PKG + ".")]:
        del sys.modules[m]


def test_packages_go_to_the_instances_folder_and_the_tools_import_them(tmp_path, ts):
    bare = make_source(tmp_path, "pkgs", {"p-one": "P"}, requirements=f"{PKG}==1.0\n")
    ts.add(bare.as_uri(), "pkgs", trusted=True)
    (ts.folder("pkgs") / "uses.py").write_text(USES.format(id="p-uses", pkg=PKG), encoding="utf-8")
    ts.ensure_requirements()
    assert "pkgs" not in ts.errors, ts.errors
    site = ts.packages_path("pkgs")
    assert (site / PKG / "__init__.py").is_file() and str(tmp_path / "data" / "tool-packages" / "pkgs") in str(site)
    marker = json.loads((ts.packages_folder("pkgs") / MARKER).read_text(encoding="utf-8"))
    assert marker["python"] == ".".join(map(str, sys.version_info[:2])) and marker["platform"] == sys.platform
    with pytest.raises(ImportError):
        __import__(PKG)  # not in the app's own environment
    reg = Registry()
    reg.load(ts.folders())
    assert reg.get("p-uses") is not None and str(site) == sys.path[-1]  # appended: the app's own packages win
    assert reg.get("p-uses").run_fn(None, None).value == 42
    reg.load([])  # the source is gone: so is its folder from sys.path
    assert str(site) not in sys.path


def test_installed_once_then_left_alone_and_reinstalled_when_something_changed(tmp_path, ts, monkeypatch):
    bare = make_source(tmp_path, "pkgs", {"p-one": "P"}, requirements=f"{PKG}==1.0\n")
    ts.add(bare.as_uri(), "pkgs", trusted=True)
    ts.ensure_requirements()
    calls = []
    real = ts._requirements
    monkeypatch.setattr(ts, "_requirements", lambda s, old="": calls.append(1) or real(s, old))
    ts.ensure_requirements()
    assert not calls  # all there, built for this Python
    marker = ts.packages_folder("pkgs") / MARKER
    m = json.loads(marker.read_text(encoding="utf-8"))
    marker.write_text(json.dumps({**m, "python": "2.7"}), encoding="utf-8")  # an instance moved to another Python
    ts.ensure_requirements()
    assert calls == [1] and json.loads(marker.read_text(encoding="utf-8"))["python"] != "2.7"
    assert not list(ts.packages_root.glob("*.replaced-*")) and not list(ts.packages_root.glob("*.partial"))


def test_an_update_that_changes_the_requirements_reinstalls(tmp_path, ts):
    bare = make_source(tmp_path, "pkgs", {"p-one": "P"}, requirements=f"{PKG}==1.0\n")
    ts.add(bare.as_uri(), "pkgs", trusted=True)
    ts.ensure_requirements()
    _wheel(tmp_path / "wheels", "2.0", answer=7)
    push(tmp_path / "pkgs-work", "newer", {"requirements.txt": f"{PKG}==2.0\n"})
    r = ts.update("pkgs")
    assert r["requirements"]["installed"], r
    site = ts.packages_path("pkgs")
    assert "ANSWER = 7" in (site / PKG / "__init__.py").read_text(encoding="utf-8")


def test_a_failed_install_keeps_what_was_there(tmp_path, ts):
    bare = make_source(tmp_path, "pkgs", {"p-one": "P"}, requirements=f"{PKG}==1.0\n")
    ts.add(bare.as_uri(), "pkgs", trusted=True)
    ts.ensure_requirements()
    (ts.folder("pkgs") / "requirements.txt").write_text(f"{PKG}==9.9\n", encoding="utf-8")  # no such version here
    r = ts._requirements(ts.get("pkgs"))
    assert not r["ok"] and (ts.packages_path("pkgs") / PKG).is_dir()


def test_a_source_that_isnt_trusted_gets_its_packages_only_once_it_is_switched_on(tmp_path, ts):
    """Installing a package can run its code (a setup.py): a source waiting for its review installs nothing, even
    when its pin moves (docs/SECURITY_AUDIT.md H4)."""
    bare = make_source(tmp_path, "other", {"o-one": "O"}, requirements=f"{PKG}==1.0\n")
    ts.add(bare.as_uri(), "other")
    assert not ts.get("other")["enabled"]
    push(tmp_path / "other-work", "newer", {"requirements.txt": f"{PKG}==2.0\n"})
    r = ts.update("other", to=ts.check("other")["target"])
    assert r["changed"] and r["requirements"] == {"ok": True, "installed": False, "later": True}
    assert not ts.packages_folder("other").exists()
    ts.pip_extra[-1] = str(_wheel(tmp_path / "wheels", "2.0"))
    ts.set_enabled("other", True)
    ts.ensure_requirements()  # at the next start
    assert (ts.packages_folder("other") / MARKER).is_file()


def test_a_source_that_isnt_trusted_may_only_name_ready_made_packages(tmp_path, ts, monkeypatch):
    from mister_plis.toolsources import untrusted_requirement_problems

    assert untrusted_requirement_problems(f"# ours\n{PKG}==1.0  # pinned\nnumpy>=1.26; python_version>'3'\n") == []
    bad = "-e .\n./local\n--index-url https://evil.example/simple\nevil @ https://evil.example/e.whl\ngit+https://x/y.git\n"
    assert len(untrusted_requirement_problems(bad)) == 5
    bare = make_source(tmp_path, "other", {"o-one": "O"}, requirements="-e .\n")
    ts.add(bare.as_uri(), "other")
    ts.set_enabled("other", True)
    r = ts._requirements(ts.get("other"))
    assert not r["ok"] and "-e ." in r["output"] and not ts.packages_folder("other").exists()
    (ts.folder("other") / "requirements.txt").write_text(f"{PKG}==1.0\n", encoding="utf-8")
    import subprocess

    calls, real = [], subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **kw: calls.append(cmd) or real(cmd, *a, **kw))
    assert ts._requirements(ts.get("other"))["installed"]
    assert calls and all("--only-binary" in c for c in calls)


def test_a_transfer_leaves_the_packages_behind(tmp_path):
    from mister_plis import transfer

    assert "tool-packages" in transfer.SKIP_DATA  # built for one machine; rebuilt at the next start


def test_the_review_says_which_packages_a_source_would_install(tmp_path, ts):
    bare = make_source(tmp_path, "other", {"o-one": "O"}, requirements=f"{PKG}==1.0\nnumpy>=1.26\n-e .\n")
    r = ts.add(bare.as_uri(), "other")
    assert r["review"]["packages"] == ["mp_toy_pkg_r6", "numpy"] and r["review"]["refused"] == ["-e ."]
    # an update that changes them says so before it is taken
    push(tmp_path / "other-work", "more", {"requirements.txt": f"{PKG}==2.0\nevil @ https://evil.example/e.whl\n"})
    c = ts.check("other")
    assert c["packages"] == ["evil", "mp_toy_pkg_r6"] and c["refused"] == ["evil @ https://evil.example/e.whl"]
