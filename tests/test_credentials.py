"""The instance's own git tokens (docs/PREP_PLAN.md R3): mister_plis/credentials.py and how git gets them."""

import io
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from mister_plis import credentials, gitutil

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "home" / "secrets" / credentials.FILE_NAME
    monkeypatch.setattr(credentials, "store_path", lambda: path)
    monkeypatch.delenv(credentials.ENV_TOKEN, raising=False)
    return path


def _three(store):
    credentials.set_token("github.com", "", "", "tok-host-1111")
    credentials.set_token("github.com", "Smith-Lab", "", "tok-owner-2222")
    credentials.set_token("github.com", "smith-lab", "inventory.git", "tok-repo-3333")


def test_the_most_specific_token_wins(store):
    _three(store)
    assert credentials.token_for("github.com", "smith-lab/inventory.git") == "tok-repo-3333"
    assert credentials.token_for("github.com", "/Smith-Lab/notes") == "tok-owner-2222"
    assert credentials.token_for("github.com", "someone/else.git") == "tok-host-1111"
    assert credentials.token_for("gitlab.com", "smith-lab/inventory") is None
    credentials.set_token("github.com", "smith-lab", "", "tok-owner-new4")  # the same owner: replaced
    assert credentials.token_for("github.com", "smith-lab/notes") == "tok-owner-new4"
    assert len(credentials.list_tokens()) == 3
    assert credentials.remove_token("github.com", "smith-lab", "inventory") is True
    assert credentials.token_for("github.com", "smith-lab/inventory.git") == "tok-owner-new4"
    assert credentials.remove_token("github.com", "smith-lab", "inventory") is False


def test_the_environment_serves_what_nothing_matches(store, monkeypatch):
    monkeypatch.setenv(credentials.ENV_TOKEN, "tok-env-5555")
    assert credentials.token_for("github.com", "a/b") == "tok-env-5555"
    credentials.set_token("github.com", "a", "", "tok-a-6666")
    assert credentials.token_for("github.com", "a/b") == "tok-a-6666"


def test_the_list_never_holds_a_token(store):
    _three(store)
    listed = credentials.list_tokens()
    assert {t["last4"] for t in listed} == {"1111", "2222", "3333"}
    assert "tok-" not in repr(listed) and "tok-" not in repr(credentials.describe())


def test_names_not_addresses(store):
    from mister_plis.errors import ToolError

    for host, owner, repo, token in [("github.com", "a/b", "", "t"), ("github.com", "", "repo", "t"),
                                     ("https://github.com", "a", "", "t"), ("github.com", "a", "", ""),
                                     ("github.com", "a", "", "two words")]:
        with pytest.raises(ToolError):
            credentials.set_token(host, owner, repo, token)
    assert not store.exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows has no Unix file modes")
def test_only_the_server_can_read_the_file(store):
    _three(store)
    assert stat.S_IMODE(store.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.parent.stat().st_mode) == 0o700


def test_the_helper_speaks_gits_protocol(store):
    _three(store)
    out = io.StringIO()
    credentials.helper(["--store", str(store), "get"], io.StringIO("protocol=https\nhost=github.com\npath=smith-lab/inventory.git\n\n"), out)
    assert out.getvalue() == "username=x-access-token\npassword=tok-repo-3333\n"
    for asked in ("protocol=https\nhost=gitlab.com\n", "protocol=ssh\nhost=github.com\n", "protocol=https\n"):
        out = io.StringIO()
        credentials.helper(["--store", str(store), "get"], io.StringIO(asked), out)
        assert out.getvalue() == ""  # nothing: git asks the next helper
    out = io.StringIO()
    credentials.helper(["--store", str(store), "store"], io.StringIO("protocol=https\nhost=github.com\npassword=x\n"), out)
    assert out.getvalue() == ""


def test_the_helper_runs_as_a_script_anywhere(store, tmp_path):
    """git starts it inside other repositories' folders, where the package can't be imported."""
    _three(store)
    elsewhere = tmp_path / "some repository"
    elsewhere.mkdir()
    r = subprocess.run([sys.executable, "-I", str(ROOT / "mister_plis" / "credentials.py"), "--store", str(store), "get"],
                       input="protocol=https\nhost=github.com\npath=smith-lab/x\n\n", capture_output=True, text=True,
                       encoding="utf-8", cwd=elsewhere, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["username=x-access-token", "password=tok-owner-2222"]


def test_git_gets_the_token_through_the_helper(store):
    _three(store)
    args = gitutil.credential_args()
    assert args[:2] == ["-c", "credential.helper="] and "credentials.py" in args[3] and "tok-" not in " ".join(args)
    assert "credential.https://github.com.useHttpPath=true" in args  # a token for one owner: git says which repository
    for path, token in (("smith-lab/inventory.git", "tok-repo-3333"), ("someone/x.git", "tok-host-1111")):
        r = subprocess.run(["git", *args, "credential", "fill"], input=f"protocol=https\nhost=github.com\npath={path}\n\n",
                           capture_output=True, text=True, encoding="utf-8", env=gitutil.ENV, timeout=30)
        assert f"password={token}" in r.stdout.splitlines(), r.stderr


def test_without_owner_tokens_git_asks_as_before(store):
    """No token for one owner: git doesn't send the path, so the Mac's Keychain finds its token as before."""
    credentials.set_token("github.com", "", "", "tok-host-1111")
    assert not any("useHttpPath" in a for a in gitutil.credential_args())


def test_the_checkout_helpers_come_after(store, monkeypatch):
    monkeypatch.setattr(gitutil, "checkout_helpers", lambda: ["osxkeychain"])
    args = gitutil.credential_args()
    helpers = [a.split("=", 1)[1] for a in args if a.startswith("credential.helper=")]
    assert helpers[0] == "" and "credentials.py" in helpers[1] and helpers[2] == "osxkeychain"


def test_a_local_repository_still_works_with_credentials(store, tmp_path):
    _three(store)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    code, out = gitutil.run("ls-remote", bare.as_uri(), cwd=tmp_path, credentials=True)
    assert code == 0, out


def test_an_untrusted_tool_source_gets_no_helper(store, tmp_path, monkeypatch):
    from mister_plis.toolsources import ToolSources

    _three(store)
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(gitutil.subprocess, "run", fake_run)
    ts = ToolSources(tmp_path / "data")
    ts.git({"name": "theirs", "trusted": False, "url": "git@github.com:someone/x.git"}, "fetch")
    ts.git({"name": "https", "trusted": False, "url": "https://github.com/someone/x.git"}, "fetch")
    ts.git({"name": "ours", "trusted": True}, "fetch")
    untrusted, https, trusted = [c for c in seen if c[-1] == "fetch"]
    assert [a for a in untrusted if a.startswith("credential.helper")] == ["credential.helper="]
    helpers = [a for a in https if a.startswith("credential.helper")]
    assert helpers[0] == "credential.helper=" and len(helpers) == 2 and helpers[1].endswith("--repo-only")
    assert any("credentials.py" in a for a in trusted)


def test_an_untrusted_tool_source_gets_only_its_own_token(store):
    """A token stored for exactly that repository, never the host's or the owner's (nor MISTER_PLIS_GIT_TOKEN)."""
    _three(store)
    os.environ[credentials.ENV_TOKEN] = "tok-env-5555"
    try:
        for url, token in (("https://github.com/smith-lab/inventory.git", "tok-repo-3333"),
                           ("https://github.com/smith-lab/notes.git", None), ("https://github.com/else/x.git", None)):
            args = gitutil.repo_token_args(url)
            r = subprocess.run(["git", *args, "credential", "fill"], capture_output=True, text=True, encoding="utf-8",
                               input=f"protocol=https\nhost=github.com\npath={url.split('github.com/')[1]}\n\n",
                               env=gitutil.ENV, timeout=30)
            passwords = [x for x in r.stdout.splitlines() if x.startswith("password=")]
            assert passwords == ([f"password={token}"] if token else []), (url, r.stdout, r.stderr)
    finally:
        os.environ.pop(credentials.ENV_TOKEN, None)


def test_a_tool_source_added_with_a_token(store, tmp_path, monkeypatch):
    from mister_plis.errors import ToolError
    from mister_plis.toolsources import ToolSources

    ts = ToolSources(tmp_path / "data")
    with pytest.raises(ToolError, match="https address"):
        ts.add("git@github.com:smith-lab/tools.git", token="tok-x")
    # the fetch fails: the token isn't kept, and one stored before is put back
    monkeypatch.setattr(ts, "_clone", lambda s, **kw: (_ for _ in ()).throw(ToolError("Couldn't fetch")))
    with pytest.raises(ToolError):
        ts.add("https://github.com/smith-lab/tools.git", token="tok-new-1")
    assert credentials.list_tokens() == []
    credentials.set_token("github.com", "smith-lab", "tools", "tok-old-2")
    with pytest.raises(ToolError):
        ts.add("https://github.com/smith-lab/tools.git", token="tok-new-1")
    assert credentials.token_for("github.com", "smith-lab/tools.git") == "tok-old-2"
    # it works: kept for exactly that repository
    monkeypatch.setattr(ts, "_clone", lambda s, **kw: (ts.folder(s["name"]) / ".git").mkdir(parents=True))
    monkeypatch.setattr(ts, "git", lambda s, *a, **kw: (0, "abc123"))
    ts.add("https://github.com/Smith-Lab/tools.git", token="tok-new-3")
    assert [(t["owner"], t["repo"], t["last4"]) for t in credentials.list_tokens()] == [("smith-lab", "tools", "ew-3")]


def test_the_updater_reaches_github_with_the_tokens(monkeypatch):
    from mister_plis import updater

    seen = []
    monkeypatch.setattr(updater.gitutil, "run", lambda *a, **kw: seen.append((a[0], kw.get("credentials"))) or (0, ""))
    updater.git("fetch", "--prune", "origin")
    updater.git("status", "--porcelain")
    assert seen == [("fetch", True), ("status", False)]


def test_a_transfer_never_holds_the_secrets(tmp_path, monkeypatch):
    """Even with the data folder at the instance's folder itself, secrets/ isn't copied."""
    from mister_plis import config, transfer

    home = tmp_path / "home"
    (home / "secrets").mkdir(parents=True)
    (home / "secrets" / credentials.FILE_NAME).write_text("[[token]]\n", encoding="utf-8")
    (home / "lab.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "HOME", home)
    names = [arc for arc, _ in transfer._plan(home, home, [])]
    assert "data/lab.json" in names and not any("secrets" in n for n in names)


def test_the_github_access_panel(client, store):
    r = client.post("/api/system/credentials", json={"host": "github.com", "owner": "smith-lab", "token": "tok-api-7777"})
    assert r.status_code == 200 and r.json()["tokens"][0]["last4"] == "7777" and "tok-api" not in r.text
    assert "tok-api" not in client.get("/api/system/credentials").text
    assert client.post("/api/system/credentials", json={"owner": "a/b", "token": "x"}).status_code == 422
    r = client.request("DELETE", "/api/system/credentials", json={"host": "github.com", "owner": "smith-lab"})
    assert r.status_code == 200 and r.json()["tokens"] == []
    assert client.request("DELETE", "/api/system/credentials", json={"host": "github.com", "owner": "smith-lab"}).status_code == 404


def test_the_setup_check_says_which_owner_needs_a_token(monkeypatch):
    from mister_plis import labsetup

    monkeypatch.setattr(gitutil, "run", lambda *a, **kw: (128, "fatal: could not read Username"))
    note = labsetup.reach("https://github.com/smith-lab/inventory.git")["note"]
    assert "add a token for smith-lab on Settings → Server & updates → GitHub access" in note
