"""The inventory's repository as a stored setting: changed on its Settings tab or by a lab file (docs/LAB_SETUP_PLAN.md)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mister_plis.errors import ToolError
from modules.inventory import _migrate, _setting, configure, lab_settings
from modules.inventory.calculator import Calculator
from modules.inventory.service import Consumables, Inventory
from modules.inventory.tidy import Tidy

from test_reagents import _git, make_workbook


def _remote(tmp_path, name):
    """A "GitHub" repository with the inventory workbook in it."""
    remote = tmp_path / f"{name}.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / f"{name}-work"
    _git(tmp_path, "clone", "-q", str(remote), str(work))
    make_workbook(work)
    _git(work, "add", "-A"); _git(work, "commit", "-qm", "start"); _git(work, "push", "-q", "origin", "HEAD:main")
    return remote


def test_another_repository_sets_the_old_copy_aside(tmp_path):
    first, second = _remote(tmp_path, "first"), _remote(tmp_path, "second")
    inv = Inventory(tmp_path / "data", str(first), "main")
    Consumables(inv)
    assert inv.sync("Ola")["ok"]
    inv.save_settings(push=False)
    inv.save({"storage_exact_location": "szafa A"}, user="Ola", rid="1")
    with pytest.raises(ToolError, match="haven't reached"):
        inv.set_repository(str(second))  # a change not sent yet: never left behind silently
    assert inv.url == str(first)
    inv.save_settings(push=True)
    assert inv.sync("Ola")["ok"]
    r = inv.set_repository(str(second), "main")
    assert r["changed"] and r["kept"].endswith(".before-" + r["kept"].rsplit(".before-", 1)[1])
    assert (tmp_path / "data" / "reagents").joinpath(Path(r["kept"]).name, ".git").is_dir()  # kept, not deleted
    assert inv.others[0].url == str(second) and inv.stored() == {"repo": str(second), "branch": "main"}
    assert inv.sync("Ola")["ok"]
    assert inv.get("1")["storage_exact_location"] in (None, "")  # the new repository's own data, nothing mixed in
    assert inv.set_repository(str(second), "main") == {"changed": False, "kept": ""}


def test_a_copy_never_synced_goes_to_the_new_repository(tmp_path):
    remote = tmp_path / "empty.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    inv = Inventory(tmp_path / "data")  # on this server only
    inv.ensure()
    make_workbook(inv.repo)
    inv.commit("start", "Ola")
    assert inv.set_repository(remote.as_uri())["kept"] == ""
    assert inv.sync("Ola")["ok"] and _git(tmp_path, "--git-dir", str(remote), "log", "--format=%s").strip() == "start"


def test_addresses_are_checked(tmp_path):
    inv = Inventory(tmp_path / "data")
    for bad in ("not an address", "https://user:token@github.com/a/b.git"):
        with pytest.raises(ToolError):
            inv.set_repository(bad)
    with pytest.raises(ToolError, match="branch"):
        inv.set_repository("", "no..dots")


def _svc(tmp_path, url=""):
    inv = Inventory(tmp_path / "data", url, "main")
    return SimpleNamespace(inventory=inv, consumables=Consumables(inv), tidy=Tidy(inv, "http://127.0.0.1:11434"),
                           calculator=Calculator(None, "molarity"))


def test_its_questions_from_a_lab_file(tmp_path):
    remote = _remote(tmp_path, "lab")
    svc, ctx = _svc(tmp_path), SimpleNamespace(settings={})
    values = {"repo": remote.as_uri(), "push": False, "auto_sync_minutes": 60, "calculator": "", "tidy_schedule": "daily",
              "tidy_at": "03:15", "ollama_url": ""}
    rows = {r["key"]: r for r in configure(ctx, svc, values, False)}
    assert rows["repo"]["old"] == "" and rows["repo"]["status"] == "change" and rows["tidy_at"]["old"] == "02:30"
    assert svc.inventory.url == "" and svc.calculator.tool_id == "molarity"  # only checked
    rows = configure(ctx, svc, values, True)
    assert all(r["status"] == "done" for r in rows), rows
    assert svc.inventory.url == remote.as_uri() and svc.calculator.tool_id == "" and not svc.tidy.ollama.enabled
    assert svc.inventory.settings()["auto_minutes"] == 60 and svc.tidy.settings()["schedule"] == "daily"
    assert svc.inventory.stored() == {"repo": remote.as_uri(), "branch": "main", "calculator": "", "ollama_url": ""}
    assert lab_settings(ctx, svc)["tidy_at"] == "03:15"
    bad = {r["key"]: r["status"] for r in configure(ctx, svc, {"repo": "nope", "tidy_at": "25:00", "auto_sync_minutes": 7}, False)}
    assert bad == {"repo": "error", "tidy_at": "error", "auto_sync_minutes": "error"}
    # config.toml on this machine wins: left alone, and said so
    row = configure(SimpleNamespace(settings={"repo": ""}), svc, {"repo": "https://github.com/x/y.git"}, True)[0]
    assert row["status"] == "skip" and "config.toml" in row["note"]


def test_what_is_stored_and_what_config_toml_says(tmp_path):
    stored = {"repo": "https://example.org/stored.git"}
    assert _setting(SimpleNamespace(settings={}), "repo", stored) == "https://example.org/stored.git"
    assert _setting(SimpleNamespace(settings={"repo": ""}), "repo", stored) == ""
    assert _setting(SimpleNamespace(settings={}), "branch", stored) == "main"


def test_an_old_server_keeps_the_repository_its_copy_came_from(tmp_path):
    remote = _remote(tmp_path, "old")
    inv = Inventory(tmp_path / "data", str(remote), "main")
    assert inv.sync("Ola")["ok"]
    (inv.settings_file).write_text('{"push": true}', encoding="utf-8")  # as an old server left it: no repo stored
    probe = Inventory(tmp_path / "data")
    _migrate(probe)
    assert probe.stored() == {"repo": str(remote), "calculator": "molarity"}  # what it used by default before
    fresh = Inventory(tmp_path / "new")
    _migrate(fresh)  # a new server: nothing to keep
    assert fresh.stored() == {}


def test_a_new_lab_starts_an_empty_inventory(tmp_path):
    local = Inventory(tmp_path / "local")  # on this server only
    cons = Consumables(local)
    assert local.items() == [] and local.start_workbook("Ola")
    fields = {f["key"] for f in local.fields()}
    assert {"label_no", "name_en", "molar_mass_g_mol", "purity_percent", "_ghs", "storage_exact_location"} <= fields
    rid = local.save({"name_pl": "aceton", "name_en": "acetone", "ghs02_flammable": True}, user="Ola")["id"]
    assert local.get(rid)["_ghs"] and cons.book() is not None  # the consumables follow
    assert not local.start_workbook("Ola")  # once
    remote = _remote(tmp_path, "theirs")
    synced = Inventory(tmp_path / "synced", str(remote), "main")
    with pytest.raises(ToolError, match="Sync"):
        synced.start_workbook()  # the repository may have one: never shadowed


def test_the_settings_tab_changes_it(client, tmp_path, monkeypatch):
    from mister_plis.app import modules

    svc = modules.loaded["inventory"].service
    monkeypatch.setattr(svc.inventory, "locked", ["repo"])  # the tests' environment sets it, like config.toml
    r = client.post("/api/reagents/repository", json={"repo": "https://github.com/x/y.git"})
    assert r.status_code == 422 and "config.toml" in r.json()["error"]
    assert client.get("/api/reagents/status").json()["locked"]
