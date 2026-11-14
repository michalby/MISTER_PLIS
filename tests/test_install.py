"""Installs without a git checkout (Docker, a package), and git in folders owned by someone else (docs/PREP_PLAN.md R4)."""

import os
import subprocess
import sys

import pytest

from mister_plis import gitutil, install, updater


def test_a_docker_instance_says_how_it_is_updated(monkeypatch):
    monkeypatch.setattr(updater, "git", lambda *a, **k: (128, "not a git repository"))
    monkeypatch.setenv("MISTER_PLIS_INSTALL", "docker")
    s = updater.status()
    assert not s["is_repo"] and s["install"] == "docker" and "docker compose pull" in s["how"] and s["version"]
    monkeypatch.setenv("MISTER_PLIS_INSTALL", "")
    monkeypatch.setattr(install, "ROOT", install.ROOT / "no-such-folder")
    assert "pip install" in updater.status()["how"]  # a package


def test_an_image_says_which_commit_it_was_built_from(monkeypatch):
    monkeypatch.setattr(updater, "git", lambda *a, **k: (128, ""))
    monkeypatch.setenv("MISTER_PLIS_COMMIT", "5e0726acfe813f4683804f496714e7437ae1f145")
    info = updater.head_info()
    assert info["commit"].startswith("5e0726a") and info["short"] == "5e0726a"
    monkeypatch.setenv("MISTER_PLIS_COMMIT", "not a commit; rm -rf")
    assert updater.head_info()["short"] == "dev"


def test_version_is_meaningful():
    from mister_plis import __version__

    major, minor, patch = (int(x) for x in __version__.split("."))
    assert (major, minor) >= (0, 9)


def test_git_trusts_the_folder_it_runs_in(tmp_path):
    args = gitutil._safe(tmp_path)
    assert args == ["-c", f"safe.directory={tmp_path.resolve().as_posix()}"]


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0, reason="needs root, to give a folder to another user")
def test_a_repository_owned_by_another_user_still_works(tmp_path):
    """A Docker volume made by root, a NAS folder: git refuses "dubious ownership" without safe.directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for root, dirs, files in os.walk(repo):
        for name in [root, *(os.path.join(root, f) for f in dirs + files)]:
            os.chown(name, 4321, 4321)
    plain = subprocess.run(["git", "status"], cwd=repo, capture_output=True, text=True,
                           env={**gitutil.ENV, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    assert plain.returncode != 0 and "dubious ownership" in plain.stderr  # what git does on its own
    code, out = gitutil.run("status", cwd=repo)
    assert code == 0, out


def test_the_docker_files_name_what_the_server_reads():
    from mister_plis.config import ROOT

    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for part in ("mister_plis", "modules", "labs", "docs", "requirements.txt", "MISTER_PLIS_SUPERVISED=1",
                 "MISTER_PLIS_INSTALL=docker", "MISTER_PLIS_HOME=/srv/mister-plis", "ARG COMMIT"):
        assert part in docker, part
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert {".git", "data", "secrets", "config.toml"} <= set(ignored)
    assert "MISTER_PLIS_SUPERVISED=1" in (ROOT / "deploy" / "mister-plis.service").read_text(encoding="utf-8")
