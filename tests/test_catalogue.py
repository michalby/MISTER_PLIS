"""Tool sources that come with a release, and a catalogue to browse and add from (docs/PREP_PLAN.md R7)."""

import json
import shutil
from pathlib import Path

import pytest

from mister_plis import catalogue
from mister_plis.errors import ToolError
from mister_plis.registry import Registry
from mister_plis.toolsources import ToolSources

from test_toolsources import make_source

FIXTURE = Path(__file__).parent / "fixtures" / "toolsource"


@pytest.fixture
def ts(tmp_path):
    bundled = tmp_path / "bundled-tools"
    bundled.mkdir()
    shutil.copytree(FIXTURE, bundled / "basic")  # as a release would bring it
    man = bundled / "basic" / "mister-plis-tools.toml"
    man.write_text(man.read_text(encoding="utf-8").replace('name = "fixture"', 'name = "basic"'), encoding="utf-8")
    s = ToolSources(tmp_path / "data", bundled_root=bundled)
    s._save([])
    return s


def test_a_bundled_source_is_loaded_listed_and_can_be_switched_off(ts):
    assert [b["name"] for b in ts.bundled()] == ["basic"]
    folders = ts.folders()
    assert [f["name"] for f in folders] == ["basic"] and folders[0]["bundled"]
    reg = Registry()
    reg.load(folders)
    assert reg.tools and all(t.source == "basic" for t in reg.tools.values())
    row = next(s for s in ts.status() if s["name"] == "basic")
    assert row["bundled"] and row["enabled"] and row["version"]
    ts.set_enabled("basic", False)  # through the same route as any source
    assert ts.bundled_off() == ["basic"] and ts.folders() == []
    with pytest.raises(ToolError, match="comes with MISTER PLIS"):
        ts.remove("basic")
    ts.set_enabled("basic", True)
    assert ts.bundled_off() == [] and ts.folders()


def test_a_clone_of_the_same_name_stands_in_for_a_bundled_source(tmp_path, ts):
    bare = make_source(tmp_path, "basic", {"own-one": "O"})
    ts.add(bare.as_uri(), "basic", trusted=True)
    names = [(f["name"], bool(f.get("bundled"))) for f in ts.folders()]
    assert names == [("basic", False)]
    assert next(s for s in ts.status() if s.get("bundled"))["replaced_by_local"]


def test_the_list_keeps_bundled_off_and_the_catalogue_when_sources_change(tmp_path, ts):
    ts.set_bundled("basic", False)
    ts.set_catalogue("https://example.org/catalogue.json")
    bare = make_source(tmp_path, "other", {"x-one": "X"})
    ts.add(bare.as_uri(), "other")
    d = json.loads(ts.file.read_text(encoding="utf-8"))
    assert d["bundled_off"] == ["basic"] and d["catalogue"] == "https://example.org/catalogue.json" and d["sources"]
    with pytest.raises(ToolError):
        ts.set_catalogue("http://insecure.example.org/c.json")


def test_a_checkout_brings_no_tools(tmp_path):
    from mister_plis.toolsources import BUNDLED_DIR

    assert not [p for p in BUNDLED_DIR.iterdir() if p.is_dir()]  # only its README: tools are added when a release is built


# ---- the catalogue ----

def _catalogue(tmp_path, sources):
    f = tmp_path / "catalogue.json"
    f.write_text(json.dumps({"format": "mister-plis-tool-catalogue", "format_version": 1, "sources": sources}), encoding="utf-8")
    return f.as_uri()


def test_browse_says_what_is_added_and_what_fits(tmp_path, ts, monkeypatch):
    url = _catalogue(tmp_path, [
        {"name": "plantlab", "title": "Plant lab tools", "url": "https://github.com/plants/tools.git", "description": "Leaves",
         "maintainer": "Dr. Green", "requires_toolkit": ">=1.1,<2", "tags": ["plants"]},
        {"name": "future", "url": "https://github.com/x/future.git", "requires_toolkit": ">=3"},
        {"name": "basic", "url": "https://github.com/x/basic.git"},
        {"name": "Bad Name", "url": "https://x"}, {"name": "insecure", "url": "http://x/y.git"},
    ])
    rows = {r["name"]: r for r in catalogue.browse(url, ts)}
    assert set(rows) == {"plantlab", "future", "basic"}  # what can't be added is left out
    assert rows["plantlab"]["fits"] and not rows["plantlab"]["added"] and rows["plantlab"]["maintainer"] == "Dr. Green"
    assert not rows["future"]["fits"] and rows["basic"]["added"]  # it comes with MISTER PLIS


def test_adding_from_the_catalogue_is_untrusted_and_pinned(tmp_path, ts, monkeypatch):
    bare = make_source(tmp_path, "plantlab", {"leaf": "L"})
    url = _catalogue(tmp_path, [{"name": "plantlab", "url": "https://example.org/plantlab.git"}])
    seen = {}

    def fake_add(u, name, branch, trusted):
        seen.update(url=u, name=name, trusted=trusted)
        return ToolSources.add(ts, bare.as_uri(), name, branch, trusted)

    monkeypatch.setattr(ts, "add", fake_add)
    r = catalogue.add(url, "plantlab", ts)
    assert seen == {"url": "https://example.org/plantlab.git", "name": "plantlab", "trusted": False}
    assert not r["enabled"] and r["pinned"] and not r["trusted"] and r["review"]["n_files"]
    with pytest.raises(ToolError, match="no such"):
        catalogue.add(url, "nothing", ts)


@pytest.mark.parametrize("text, message", [("[]", "isn't a MISTER PLIS tool catalogue"), ("{", "valid JSON"),
                                           ('{"format": "mister-plis-tool-catalogue", "format_version": 5, "sources": []}', "newer")])
def test_a_bad_catalogue_says_so(tmp_path, text, message):
    f = tmp_path / "c.json"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(ToolError, match=message):
        catalogue.read(f.as_uri(), max_age=0)


def test_the_lab_file_names_the_catalogue_and_bundled_sources_off():
    from mister_plis.labsetup import LabFileError, parse

    lab, _ = parse('[tools]\nbundled_off = ["basic"]\ncatalogue = "https://example.org/c.json"\n')
    assert lab["tools"] == {"bundled_off": ["basic"], "catalogue": "https://example.org/c.json"}
    with pytest.raises(LabFileError):
        parse('[tools]\nbundled_off = "basic"\n')


def test_the_settings_page_reads_the_catalogue(client, tmp_path):
    url = _catalogue(tmp_path, [{"name": "zzz_test", "url": "https://github.com/x/zzz.git"}])
    assert client.post("/api/tools/catalogue", json={"address": url}).json()["address"] == url
    d = client.get("/api/tools/catalogue").json()
    assert d["sources"][0]["name"] == "zzz_test" and not d["error"]
    client.post("/api/tools/catalogue", json={"address": ""})
    assert client.get("/api/tools/catalogue").json() == {"address": "", "sources": [], "error": ""}


# ---- a server running from a git checkout fetches the bundled sources itself (bundled-tools.toml) ------------------

def test_bundled_tools_toml_is_read_and_checked(tmp_path):
    from mister_plis.toolsources import bundled_list

    f = tmp_path / "bundled-tools.toml"
    f.write_text('[[source]]\nname = "basic"\nurl = "https://github.com/o/basic.git"\ntag = "v1.0.0"\n'
                 '[[source]]\nname = "Bad Name"\nurl = "https://x/y.git"\ntag = "v1"\n'
                 '[[source]]\nname = "plain"\nurl = "http://x/y.git"\ntag = "v1"\n'
                 '[[source]]\nname = "pinned"\nurl = "https://x/y.git"\ntag = "v2"\ncommit = "' + "a" * 40 + '"\n', encoding="utf-8")
    assert bundled_list(f) == [{"name": "basic", "url": "https://github.com/o/basic.git", "tag": "v1.0.0", "commit": ""},
                               {"name": "pinned", "url": "https://x/y.git", "tag": "v2", "commit": "a" * 40}]
    assert bundled_list(tmp_path / "none.toml") == []
    from mister_plis.toolsources import BUNDLED_LIST

    assert isinstance(bundled_list(BUNDLED_LIST), list)  # the code's own file reads (empty until the basic tools are public)


def test_a_checkout_fetches_the_bundled_sources_at_their_tag(tmp_path):
    from test_toolsources import _git, push

    from mister_plis.toolsources import BUNDLED_MARK

    bare = make_source(tmp_path, "basic", {"basic-one": "One"})
    work = tmp_path / "basic-work"
    _git(work, "tag", "v1")
    _git(work, "push", "-q", "origin", "v1")
    root = tmp_path / "bundled-tools"
    ts = ToolSources(tmp_path / "data", bundled_root=root)
    ts._save([])
    listed = [{"name": "basic", "url": bare.as_uri(), "tag": "v1", "commit": ""}]
    assert ts.ensure_bundled(listed) == ["basic"]
    assert [b["name"] for b in ts.bundled()] == ["basic"] and not (root / "basic" / ".git").exists()
    assert json.loads((root / "basic" / BUNDLED_MARK).read_text(encoding="utf-8"))["tag"] == "v1"
    row = next(s for s in ts.status() if s.get("bundled"))
    assert row["version"] == "v1" and row["enabled"] and not row["error"]
    reg = Registry()
    reg.load(ts.folders())
    assert set(reg.tools) == {"basic-one"}
    assert ts.ensure_bundled(listed) == []  # already there: nothing fetched

    # a newer tag (an update of the code lists it): fetched, the old one set aside
    head = push(work, "two", {"basic_two.py": (work / "basic_one.py").read_text(encoding="utf-8").replace("basic-one", "basic-two")})
    _git(work, "tag", "v2")
    _git(work, "push", "-q", "origin", "v2")
    listed = [{"name": "basic", "url": bare.as_uri(), "tag": "v2", "commit": head}]
    assert ts.ensure_bundled(listed) == ["basic"]
    reg.load(ts.folders())
    assert set(reg.tools) == {"basic-one", "basic-two"} and (root / "basic.previous").is_dir()
    assert [b["name"] for b in ts.bundled()] == ["basic"]  # the previous copy and a part folder are never loaded

    # listed by its commit: that commit is fetched, whatever the tag points at now (a tag can be moved)
    _git(work, "tag", "-f", "v2", "HEAD~1")
    _git(work, "push", "-q", "-f", "origin", "v2")
    assert ts.ensure_bundled(listed) == []  # already at that commit
    (root / "basic" / BUNDLED_MARK).unlink()
    import shutil
    shutil.rmtree(root / "basic")
    assert ts.ensure_bundled(listed) == ["basic"]
    reg.load(ts.folders())
    assert set(reg.tools) == {"basic-one", "basic-two"}  # the commit listed, not where v2 points now
    # a commit that isn't there: refused, the copy there stays
    gone = [{"name": "basic", "url": bare.as_uri(), "tag": "v3", "commit": "0" * 40}]
    assert ts.ensure_bundled(gone) == []
    assert "Couldn't fetch" in ts.errors["basic"] and "Couldn't fetch" in next(s for s in ts.status() if s.get("bundled"))["error"]
    assert ts.bundled_tag("basic") == "v2"
    # a source that isn't there (no network, a wrong address): an error for the page, nothing else
    assert ts.ensure_bundled([{"name": "other", "url": (tmp_path / "nowhere.git").as_uri(), "tag": "v1", "commit": ""}]) == []
    assert "Couldn't fetch" in ts.errors["other"] and not (root / "other").exists()


def test_a_copy_a_release_brought_is_left_as_it_is(tmp_path, ts):
    """A release (the Docker image) brings its bundled sources without a mark: never fetched over."""
    before = sorted(p.name for p in ts.bundled_root.joinpath("basic").iterdir())
    assert ts.ensure_bundled([{"name": "basic", "url": (tmp_path / "nowhere.git").as_uri(), "tag": "v9", "commit": ""}]) == []
    assert "basic" not in ts.errors and sorted(p.name for p in ts.bundled_root.joinpath("basic").iterdir()) == before


def test_a_labs_own_tool_stands_in_for_a_bundled_one_of_the_same_id(tmp_path, ts):
    """A lab that already has a tool the basic tools bring (e.g. its own Solution & dilution) keeps its own, with no
    "duplicate" shown; the bundled source's other tools load."""
    bundled = next(f for f in ts.folders() if f.get("bundled"))
    reg = Registry()
    reg.load([bundled])
    one = sorted(reg.tools)[0]
    bare = make_source(tmp_path, "lab", {one: "Ours"})
    ts.add(bare.as_uri(), "lab", trusted=True)
    reg.load(ts.folders())
    assert reg.tools[one].source == "lab" and not reg.broken
    assert any(t.source == "basic" for t in reg.tools.values()) or len(reg.tools) == 1
