"""The instance's folder (MISTER_PLIS_HOME) apart from the code folder (docs/PREP_PLAN.md R1)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mister_plis import config, install, labsetup, storage
from mister_plis.errors import ToolError

ROOT = Path(__file__).resolve().parent.parent

PROBE = """
import json
from mister_plis.config import HOME, ROOT, settings
print(json.dumps({
    "home": str(HOME), "root": str(ROOT), "port": settings.port, "data": str(settings.data_path),
    "storage": str(settings.storage_path), "secrets": str(settings.secrets_path), "logs": str(settings.logs_path),
    "tools": [str(p) for p in settings.tool_folder_paths()], "module": settings.module_settings("demo"),
}))
"""


def _probe(home: Path | None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MISTER_PLIS_")}
    if home is not None:
        env["MISTER_PLIS_HOME"] = str(home)
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_an_instance_can_live_apart_from_the_code(tmp_path):
    home = (tmp_path / "instance").resolve()
    home.mkdir()
    (home / "config.toml").write_text(
        'port = 9123\nstorage_dir = "store"\ntool_folders = ["my-tools"]\n\n[module.demo]\nanswer = "42"\n', encoding="utf-8")
    got = _probe(home)
    assert got["home"] == str(home) and got["root"] == str(ROOT)
    assert got["port"] == 9123  # config.toml is read from the instance's folder
    assert got["data"] == str(home / "data")
    assert got["storage"] == str(home / "store")  # a relative storage_dir is under the instance
    assert got["tools"] == [str(home / "my-tools")]
    assert got["secrets"] == str(home / "secrets") and got["logs"] == str(home / "logs")
    assert got["module"] == {"answer": "42"}


def test_without_a_home_everything_stays_in_the_code_folder():
    got = _probe(None)
    assert got["home"] == got["root"] == str(ROOT)
    assert got["data"] == str(ROOT / "data")


def test_install_kind(monkeypatch, tmp_path):
    monkeypatch.setenv("MISTER_PLIS_INSTALL", "docker")
    assert install.kind() == "docker"  # what the installer says wins
    monkeypatch.delenv("MISTER_PLIS_INSTALL")
    monkeypatch.setattr(install, "ROOT", tmp_path)
    assert install.kind() == "package"
    (tmp_path / ".git").mkdir()
    assert install.kind() == "checkout"


def test_the_instances_own_lab_files(monkeypatch, tmp_path):
    (tmp_path / "labs").mkdir()
    (tmp_path / "labs" / "ours.toml").write_text('[lab]\nname = "Our own lab"\n', encoding="utf-8")
    monkeypatch.setattr(labsetup, "HOME", tmp_path)
    files = labsetup.lab_files()
    assert {f["where"] for f in files} == {"code", "instance"}
    mine = [f for f in files if f["where"] == "instance"]
    assert mine == [{"path": str(tmp_path / "labs" / "ours.toml"), "name": "Our own lab", "where": "instance"}]
    assert "Our own lab" in labsetup.read_source(mine[0]["path"])[0]
    # a relative path not in the code folder is looked for in the instance's folder
    assert "Our own lab" in labsetup.read_source("labs/ours.toml")[0]
    # one that comes with the code is still read from the code folder
    code_file = next(f["path"] for f in files if f["where"] == "code")
    assert labsetup.read_source(code_file)[0] == (ROOT / code_file).read_text(encoding="utf-8")


def test_lab_files_come_once_when_home_is_the_code_folder():
    assert config.HOME == ROOT  # the tests run without MISTER_PLIS_HOME
    assert {f["where"] for f in labsetup.lab_files()} == {"code"}


def test_the_storage_folder_cannot_be_the_secrets_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOME", tmp_path)
    (tmp_path / "secrets" / "inner").mkdir(parents=True)
    for bad in (tmp_path / "secrets", tmp_path / "secrets" / "inner"):
        with pytest.raises(ToolError, match="secrets"):
            storage.check_folder(str(bad))
    (tmp_path / "store").mkdir()
    assert storage.check_folder(str(tmp_path / "store")) == (tmp_path / "store").resolve()


def test_the_server_panel_says_how_it_was_installed(client):
    info = client.get("/api/system").json()["server"]["install"]
    assert info["kind"] in {"checkout", "package"} and info["code"] == str(ROOT)
    assert info["separate"] is False
