"""Running another branch: the choice is remembered, bad names and local edits are refused."""

import json

from mister_plis import updater


def test_bad_branch_names_are_refused():
    for name in ("", "-x", "a..b", "a b", "x;rm"):
        assert updater.switch(name)["ok"] is False, name


def test_local_edits_block_a_switch(monkeypatch):
    calls = []

    def fake_git(*args, timeout=60):
        calls.append(args)
        return (0, " M mister_plis/app.py") if args[0] == "status" else (0, "")

    monkeypatch.setattr(updater, "git", fake_git)
    r = updater.switch("time-machine")
    assert r["ok"] is False and "changed on this machine" in r["steps"][0]["name"]
    assert not any(a[0] in ("checkout", "fetch") for a in calls)


def test_chosen_branch_is_followed(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "_choice_file", lambda: tmp_path / "git_branch.json")
    monkeypatch.setattr(updater.settings, "git_branch", "")
    assert updater.chosen_branch() == "" and updater.upstream() != "origin/test"
    (tmp_path / "git_branch.json").write_text(json.dumps({"branch": "test"}), encoding="utf-8")
    assert updater.chosen_branch() == "test" and updater.upstream() == "origin/test"


def test_branch_list(client):
    d = client.get("/api/system/branches").json()
    assert {"current", "branches", "fetch_ok"} <= set(d)
