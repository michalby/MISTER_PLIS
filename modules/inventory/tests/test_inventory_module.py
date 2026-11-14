"""The inventory as a module (reorg P5): its folder moved, its settings, and it plugs into the base."""

import subprocess
from types import SimpleNamespace

from mister_plis.storage import move_folder_once


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace").stdout


def test_its_data_lives_in_the_module_folder():
    from mister_plis.app import modules
    from mister_plis.config import settings

    svc = modules.get("inventory")
    assert svc.inventory.root == settings.data_path / "modules" / "inventory"
    assert svc.consumables.root == svc.inventory.root and svc.consumables.main is svc.inventory


def test_the_old_folder_moves_once_with_its_repository(tmp_path):
    old, new = tmp_path / "data" / "reagents", tmp_path / "data" / "modules" / "inventory"
    (old / "repo").mkdir(parents=True)
    (old / "settings.json").write_text('{"push": true}', encoding="utf-8")
    (old / "repo" / "wykaz.csv").write_text("label_no;name\n1;aceton\n", encoding="utf-8")
    _git(old / "repo", "init", "-q")
    _git(old / "repo", "add", "-A")
    _git(old / "repo", "commit", "-q", "-m", "Add label_no 1 aceton")
    assert move_folder_once(old, new, "The inventory")
    assert (new / "settings.json").read_text(encoding="utf-8") == '{"push": true}'
    assert "Add label_no 1 aceton" in _git(new / "repo", "log", "--format=%s")
    assert not old.exists() and list((tmp_path / "data").glob("reagents.migrated-*"))
    assert not move_folder_once(old, new)


def test_settings_from_its_table_or_the_defaults(monkeypatch):
    from mister_plis.config import settings
    from modules.inventory import DEFAULTS, _setting

    assert _setting(SimpleNamespace(settings={}), "repo") == DEFAULTS["repo"] == ""  # no lab's repository by default
    assert _setting(SimpleNamespace(settings={"repo": "https://example.org/new.git"}), "repo") == "https://example.org/new.git"
    monkeypatch.setenv("MISTER_PLIS_MODULE_INVENTORY_REPO", "")
    assert settings.module_settings("inventory")["repo"] == ""  # what the tests use to stay off GitHub


def test_it_plugs_into_the_base(client):
    page = client.get("/").text
    assert 'href="/reagents"' in page and 'href="/consumables"' in page and "/m/inventory/static/reagents.css" in page
    page = client.get("/settings").text  # its own tab on Settings: sync, history, tidy-up and columns together
    assert 'data-tab="inventory"' in page and 'id="rg-sync"' in page and "/m/inventory/static/reagents_admin.js" in page
    assert 'id="rg-fields"' in client.get("/settings").text
    assert client.get("/m/inventory/static/ghs/GHS02.svg").status_code == 200
