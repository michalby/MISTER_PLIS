"""Lab notebook: Obsidian rendering, the partial/sparse sync, and the pages and API."""

import subprocess
from types import SimpleNamespace

import pytest

from mister_plis.errors import ToolError
from modules.notebook.service import Notebook
from modules.notebook.obsidian import NoteRef, Renderer

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


# ---- rendering -----------------------------------------------------------------------------

def _renderer(shown=("TBS", "Other")):
    notes = {n: f"text of {n}" for n in shown}
    return Renderer(lambda name, _f: NoteRef(name, name) if name in notes else None,
                    lambda name, _f: f"Pliki/{name}" if name.endswith(".png") else None,
                    lambda i: notes.get(i))


def test_links_embeds_and_obsidian_syntax():
    src = ("---\ntags: x\n---\n# Buffers\nSee [[TBS]], [[TBS|the TBS]], [[TBS#Recipe]], [[Hidden note]] and [[#Buffers]].\n"
           "![[pic.png|200]] ![[Other]]\n\n> [!warning] Hot\n> careful\n\n==mark== ~~old~~ %%secret%%\n"
           "- [ ] todo\n- [x] done\n")
    out = _renderer().render(src, "Notes/A")
    h = out.html
    assert 'href="/notes/TBS" data-note="TBS">TBS</a>' in h
    assert ">the TBS</a>" in h and 'href="/notes/TBS#h-recipe"' in h
    assert '<span class="wikilink-missing"' in h and "Hidden note" in h  # not shown → plain text
    assert '<h1 id="h-buffers">' in h and 'href="#h-buffers"' in h
    assert '<img src="/notes/files/Pliki/pic.png"' in h and 'width="200"' in h
    assert '<div class="note-embed">' in h and "text of Other" in h and "<p><div" not in h
    assert 'class="callout callout-warning"' in h and ">Hot</div>" in h
    assert "<mark>mark</mark>" in h and "<del>old</del>" in h and "secret" not in h and "tags" not in h
    assert 'class="task"' in h and "checked" in h
    assert out.links == {"TBS", "Other"} and out.files == {"Pliki/pic.png"}


def test_unsafe_content_is_neutralised():
    src = ("<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1)) [ok](https://example.org)\n\n"
           "![](file:///C:/Temp/clip.gif) ![ext](https://example.org/a.png)\n\n```\n[[TBS]] <b>\n```\n")
    h = _renderer().render(src, "A").html
    assert "<script" not in h and "&lt;script&gt;" in h and "<img src=x" not in h
    assert "javascript:" not in h and 'href="https://example.org" rel="noopener noreferrer" target="_blank"' in h
    assert "file:" not in h and "[image: not available]" in h and 'src="https://example.org/a.png"' in h
    assert "[[TBS]] &lt;b&gt;" in h  # code stays code


def test_list_right_after_text():
    h = _renderer().render("TBS x5 na 1:\n- NaCl 146 g\n- Tris\n", "A").html
    assert "<ul>" in h and "<li>NaCl 146 g</li>" in h


# ---- sync ------------------------------------------------------------------------------------

def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def vault(tmp_path):
    """A small vault on a "GitHub" (a bare repo that allows partial clones) and a Notebook reading it."""
    src = tmp_path / "src"
    files = {
        "Protokoły/Metody/Elfo i transfer.md": "Bufor: [[TBS]]\n- 2× [[TBST]]\nOsobiste: [[Secret]]\n![[gel.png]]\n",
        "Protokoły/Metody/Stężenie chlorofilu.md": "chl a = 12.7 · A663\n",
        "Protokoły/Odczynniki/TBS.md": "TBS ×5 na 1 L\n- NaCl 146 g\n\n[[TBST]]\n",
        "Protokoły/Odczynniki/TBST.md": "Tween 20 na 1 L [[TBS]]\n",
        "Protokoły/Varia/Hasło.md": "password\n",
        "Osoby/Ala/Secret.md": "![[private.png]]\n",
    }
    for rel, text in files.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="utf-8")
    (src / "Pliki").mkdir()
    (src / "Pliki/gel.png").write_bytes(PNG)
    (src / "Pliki/private.png").write_bytes(PNG)
    _git(tmp_path, "init", "-q", "-b", "main", str(src))
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "init")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(src), str(origin))
    _git(origin, "config", "uploadpack.allowFilter", "true")
    _git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    nb = Notebook(tmp_path / "data", origin.as_uri(), "main")
    nb._save_settings(folders=["Protokoły/Metody", "Protokoły/Odczynniki"])  # chosen by the lab (none by default)
    return nb, src, origin


def test_sync_downloads_only_the_chosen_folders(vault):
    nb, src, origin = vault
    r = nb.sync()
    assert r["ok"], r
    ids = set(nb.index.notes)
    assert ids == {"Protokoły/Metody/Elfo i transfer", "Protokoły/Metody/Stężenie chlorofilu",
                   "Protokoły/Odczynniki/TBS", "Protokoły/Odczynniki/TBST"}
    on_disk = {p.relative_to(nb.vault).as_posix() for p in nb.vault.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert "Pliki/gel.png" in on_disk
    assert not any(p.startswith(("Osoby", "Protokoły/Varia")) for p in on_disk) and "Pliki/private.png" not in on_disk

    elfo = nb.index.note("Protokoły/Metody/Elfo i transfer")
    assert 'data-note="Protokoły/Odczynniki/TBS"' in elfo["html"]
    assert 'class="wikilink-missing"' in elfo["html"]  # [[Secret]] lives in a hidden folder
    assert [b["title"] for b in nb.index.note("Protokoły/Odczynniki/TBS")["backlinks"]] == ["Elfo i transfer", "TBST"]
    # only pictures used by shown notes are served
    assert nb.file("Pliki/gel.png") and not nb.file("Pliki/private.png") and not nb.file("../settings.json")
    # search ignores case and Polish letters
    assert [h["title"] for h in nb.index.search("stezenie")] == ["Stężenie chlorofilu"]
    assert nb.index.search("TBS")[0]["title"] == "TBS"

    st = nb.status()
    assert st["notes"] == 4 and st["behind"] == 0
    assert {"Osoby", "Osoby/Ala", "Protokoły", "Protokoły/Metody", "Protokoły/Varia"} <= {f["path"] for f in st["available"]}

    # a change on GitHub: Check lists it only when it touches the shown folders
    (src / "Protokoły/Odczynniki/TBS.md").write_text("TBS ×10\n", encoding="utf-8")
    _git(src, "commit", "-qam", "TBS stronger")
    (src / "Osoby/Ala/Secret.md").write_text("more\n", encoding="utf-8")
    _git(src, "commit", "-qam", "personal")
    _git(src, "push", "-q", str(origin), "main")
    c = nb.check()
    assert c["fetch_ok"] and c["behind"] == 2 and [i["subject"] for i in c["incoming"]] == ["TBS stronger"]
    assert "TBS ×5" in nb.index.note("Protokoły/Odczynniki/TBS")["html"]  # nothing changes until Sync
    assert nb.sync()["ok"] and "TBS ×10" in nb.index.note("Protokoły/Odczynniki/TBS")["html"]

    # fewer folders: the others disappear from disk too
    assert nb.set_folders(["Protokoły/Odczynniki", "Protokoły/Odczynniki"]) == ["Protokoły/Odczynniki"]
    assert nb.sync()["ok"]
    assert set(nb.index.notes) == {"Protokoły/Odczynniki/TBS", "Protokoły/Odczynniki/TBST"}
    assert not (nb.vault / "Protokoły/Metody").exists() and not (nb.vault / "Pliki/gel.png").exists()
    # a folder inside a chosen one is covered already
    assert nb.set_folders(["Protokoły", "Protokoły/Metody"]) == ["Protokoły"]
    for bad in (["../etc"], ["Nope"], [".obsidian"]):
        with pytest.raises(ToolError):
            nb.set_folders(bad)

    # the server restarting: the index comes back from disk, without the network
    again = Notebook(nb.root.parent, "file:///nowhere.git", "main")
    again.load()
    assert set(again.index.notes) == set(nb.index.notes)


def test_bad_repository_is_explained(tmp_path):
    nb = Notebook(tmp_path / "data", (tmp_path / "missing.git").as_uri(), "main")
    r = nb.sync()
    assert not r["ok"] and not nb.cloned() and nb.last_error


# ---- pages and API -----------------------------------------------------------------------

def test_pages_and_api(client, vault, monkeypatch):
    from mister_plis.app import modules

    nb, _, _ = vault
    assert nb.sync()["ok"]
    monkeypatch.setattr(modules.loaded["notebook"].ctx, "service", nb)

    page = client.get("/tool/molarity").text
    assert 'id="notes-panel"' in page and 'id="notes-btn"' in page and 'href="/notes"' in page

    d = client.get("/api/notes").json()
    assert [g["folder"] for g in d["tree"]] == ["Protokoły/Metody", "Protokoły/Odczynniki"] and d["commit"]["short"]
    n = client.get("/api/notes/note", params={"id": "Protokoły/Odczynniki/TBS"}).json()
    assert n["title"] == "TBS" and n["backlinks"]
    assert client.get("/api/notes/note", params={"id": "Osoby/Ala/Secret"}).status_code == 404
    assert client.get("/api/notes/search", params={"q": "tween"}).json()["results"][0]["title"] == "TBST"

    r = client.get("/notes/Protoko%C5%82y/Metody/Elfo%20i%20transfer")
    assert r.status_code == 200 and "Elfo i transfer" in r.text and 'id="notes-panel"' not in r.text
    assert "There is no note" in client.get("/notes/Osoby/Ala/Secret").text
    assert client.get("/notes").status_code == 200

    img = client.get("/notes/files/Pliki/gel.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and "sandbox" in img.headers["content-security-policy"]
    for bad in ("Pliki/private.png", "Osoby/Ala/Secret.md", "..%2Fsettings.json"):
        assert client.get(f"/notes/files/{bad}").status_code == 404

    st = client.get("/api/notes/status").json()
    assert st["folders"] == ["Protokoły/Metody", "Protokoły/Odczynniki"] and st["notes"] == 4
    assert client.post("/api/notes/folders", json={"folders": ["Nope"]}).status_code == 422
    r = client.post("/api/notes/folders", json={"folders": ["Protokoły/Odczynniki"]}).json()
    assert r["ok"] and client.get("/api/notes/status").json()["notes"] == 2
    page = client.get("/settings").text  # its own tab on Settings
    assert 'data-tab="notebook"' in page and 'id="notes-sync-panel"' in page and "/m/notebook/static/notes_admin.js" in page


def test_notebook_off(client, tmp_path, monkeypatch):
    from mister_plis.app import modules

    monkeypatch.setattr(modules.loaded["notebook"].ctx, "service", Notebook(tmp_path, "", "main"))
    page = client.get("/tool/molarity").text
    assert 'id="notes-panel"' not in page and 'href="/notes"' not in page
    assert "turned off" in client.get("/notes").text
    assert not client.post("/api/notes/sync").json()["ok"]


def test_sync_from_a_working_folder(tmp_path):
    """repo = the vault's own folder on this machine (git initialised, e.g. where Obsidian keeps it)."""
    folder = tmp_path / "Vault"
    (folder / "Protokoły" / "Metody").mkdir(parents=True)
    (folder / "Protokoły" / "Metody" / "PCR.md").write_text("# PCR\n", encoding="utf-8")
    (folder / "Private").mkdir()
    (folder / "Private" / "diary.md").write_text("no\n", encoding="utf-8")
    _git(folder, "init", "-q", "-b", "main"); _git(folder, "add", "-A"); _git(folder, "commit", "-qm", "start")
    nb = Notebook(tmp_path / "data", str(folder), "main")
    nb._save_settings(folders=["Protokoły/Metody"])  # chosen by the lab
    assert nb.folder == folder and nb.status()["folder"] == str(folder)
    r = nb.sync()
    assert r["ok"], r
    assert set(nb.index.notes) == {"Protokoły/Metody/PCR"} and not (nb.vault / "Private").exists()
    missing = Notebook(tmp_path / "data2", str(tmp_path / "nowhere"), "main")
    assert not missing.sync()["ok"] and "There is no folder" in missing.last_error


def test_another_repository_sets_the_old_copy_aside(vault, tmp_path):
    from modules.notebook import _migrate, configure, lab_settings

    nb, src, origin = vault
    assert nb.sync()["ok"] and nb.index.notes
    r = nb.set_repository("", "main")  # off
    assert r["changed"] and ".before-" in r["kept"] and not nb.enabled and not nb.index.notes
    assert not nb.vault.exists() and list(nb.root.glob("vault.before-*"))
    ctx = SimpleNamespace(settings={})
    rows = {x["key"]: x for x in configure(ctx, nb, {"repo": origin.as_uri(), "folders": ["Protokoły/Odczynniki"],
                                                     "auto_sync_minutes": 15}, True)}
    assert all(x["status"] == "done" for x in rows.values()), rows
    assert nb.enabled and nb.sync()["ok"] and set(nb.index.notes) == {"Protokoły/Odczynniki/TBS", "Protokoły/Odczynniki/TBST"}
    assert lab_settings(ctx, nb) == {"repo": origin.as_uri(), "branch": "main", "folders": ["Protokoły/Odczynniki"],
                                     "auto_sync_minutes": 15}
    assert configure(ctx, nb, {"folders": "nope"}, False)[0]["status"] == "change"  # one per line, as on the page
    assert configure(ctx, nb, {"auto_sync_minutes": 5}, False)[0]["status"] == "error"
    # an old server: the repository its copy came from is kept
    (nb.settings_file).write_text("{}", encoding="utf-8")
    probe = Notebook(nb.root.parent, "", "main", root=nb.root)
    _migrate(probe)
    assert probe.stored() == {"repo": origin.as_uri()}


def test_the_settings_tab_stays_when_it_is_off(client, tmp_path, monkeypatch):
    from mister_plis.app import modules

    monkeypatch.setattr(modules.loaded["notebook"].ctx, "service", Notebook(tmp_path, "", "main"))
    page = client.get("/settings").text  # where it is switched on again
    assert 'data-tab="notebook"' in page and "/m/notebook/static/notes_admin.js" in page
    assert 'href="/notes"' not in page
