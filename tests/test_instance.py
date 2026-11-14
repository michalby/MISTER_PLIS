"""The instance's identity (docs/PREP_PLAN.md R10), and the lab-wide addresses it no longer takes (0.19.0)."""

import json
from types import SimpleNamespace

import pytest

from mister_plis import labsetup, transfer
from mister_plis.backup import Backups
from mister_plis.errors import ToolError
from mister_plis.labsetup import dumps, parse

from test_jobstore import _manager, _run, _tool
from test_labsetup import setup  # noqa: F401 — the fixture: a small server of its own


def test_an_instance_gets_its_id_once(tmp_path):
    labsetup.migrate(tmp_path)
    first = labsetup.read_state(tmp_path)["instance"]
    assert len(first["id"]) == 32 and first["created_at"] > 0
    labsetup.migrate(tmp_path)  # every start
    assert labsetup.read_state(tmp_path)["instance"] == first
    # an older server (lab.json from before ids) gets one too, and keeps the rest of its state
    old = tmp_path / "old"
    old.mkdir()
    (old / "lab.json").write_text('{"format": 1, "state": "set_up", "from": "migrated", "modules": ["x"]}', encoding="utf-8")
    labsetup.migrate(old)
    d = labsetup.read_state(old)
    assert d["instance"]["id"] and d["modules"] == ["x"] and d["state"] == "set_up"


def test_a_moved_instance_keeps_its_id(tmp_path):
    data = tmp_path / "old"
    data.mkdir()
    _run(_manager(data), _tool(rows=2), prefs={"name": "Ola"})
    labsetup.migrate(data)
    labsetup.write_state({**labsetup.read_state(data), "state": "set_up"}, data)
    ident = labsetup.read_state(data)["instance"]["id"]
    out = tmp_path / "usb"
    out.mkdir()
    r = transfer.export(str(out), data, data, [], lab_name="Smith Lab", by="Ola", jobs=1)
    new = tmp_path / "new"
    new.mkdir()
    labsetup.migrate(new)  # the new server made an id of its own before taking the old one in
    assert labsetup.read_state(new)["instance"]["id"] != ident
    transfer.bring_in(r["path"], new, new, by="Ada")
    assert labsetup.read_state(new)["instance"]["id"] == ident


def test_a_lab_file_never_carries_the_id(setup):
    labsetup.migrate(setup.data_path)
    text = dumps(setup.current())
    assert labsetup.read_state(setup.data_path)["instance"]["id"] not in text and "instance" not in text


def test_version_says_which_instance(client):
    assert len(client.get("/api/version").json()["instance_id"]) == 32


def test_an_old_lab_file_with_services_and_names_still_loads(setup):
    """[services] and [server] names were lab settings until 0.19.0: an older lab file still loads, with a note."""
    lab, warnings = parse('[lab]\nname = "Smith Lab"\n[services]\nmodel = "http://192.168.1.20:11434/"\n'
                          '[server]\nnames = ["x.example"]\n')
    assert lab == {"lab": {"name": "Smith Lab"}}
    assert any("[services]" in w and "inventory" in w for w in warnings)
    assert any("[server] names" in w and "config.toml" in w for w in warnings)
    assert "services" not in setup.current() and "server" not in setup.current()
    assert "[services]" not in dumps(setup.current())


def test_old_lab_settings_with_services_are_still_read(tmp_path):
    (tmp_path / "lab_settings.json").write_text('{"lab_name": "Smith Lab", "services": {"model": "http://gpu:11434"},'
                                                ' "server_names": ["old.example"]}', encoding="utf-8")
    b = Backups(tmp_path, SimpleNamespace(root=tmp_path / "jobs", jobs={}))
    assert b.settings().services == {"model": "http://gpu:11434"} and b.settings().server_names == ["old.example"]
    b.set_lab_name("Smith Lab 2")  # another setting saved: the old ones are kept
    d = json.loads((tmp_path / "lab_settings.json").read_text(encoding="utf-8"))
    assert d["services"] == {"model": "http://gpu:11434"} and d["server_names"] == ["old.example"]


def test_the_inventory_takes_the_labs_old_model_address_over_once(tmp_path):
    from modules.inventory import DEFAULTS, _migrate, _setting
    from modules.inventory.service import Inventory

    inv = Inventory(tmp_path, root=tmp_path / "inventory")
    _migrate(inv, {}, "http://gpu:11434")
    assert inv.stored()["ollama_url"] == "http://gpu:11434"
    _migrate(inv, {}, "http://other:11434")  # once: its own address, from then on, wins
    assert inv.stored()["ollama_url"] == "http://gpu:11434"
    fresh = Inventory(tmp_path, root=tmp_path / "fresh")
    _migrate(fresh, {}, "")
    assert _setting(SimpleNamespace(settings={}), "ollama_url", fresh.stored()) == DEFAULTS["ollama_url"]
