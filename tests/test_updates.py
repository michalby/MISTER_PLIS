"""Versions, the formats register, the update channels, the release feed and the snapshots of the lab's settings
(docs/PREP_PLAN.md R5)."""

import json
import re
from pathlib import Path

import pytest

from mister_plis import __version__, formats, install, transfer, updater, updates
from mister_plis.errors import ToolError

ROOT = Path(__file__).resolve().parents[1]


# ---- the formats register ----

def test_the_register_says_what_each_writer_writes():
    from mister_plis import accounts, backup, jobformat, jobstore, labsetup, toolsettings

    assert formats.WRITES == {
        "job": jobformat.VERSION, "job_index": jobstore.INDEX_VERSION, "backup": backup.VERSION,
        "backup_catalogue": backup.CATALOGUE_VERSION, "lab_file": labsetup.FORMAT, "lab_state": labsetup.FORMAT,
        "transfer": transfer.VERSION, "tool_settings": toolsettings.FORMAT, "release_feed": updates.FEED_VERSION,
        "accounts": accounts.FORMAT,
    }
    for name, version in formats.WRITES.items():  # it reads what it writes
        lo, hi = formats.READS[name]
        assert lo <= version <= hi, name


def test_going_back_is_refused_past_a_format_this_version_cant_read():
    assert formats.can_read({"job": 1}) == (True, [])
    assert formats.can_read({"job": 2, "backup": 1}) == (False, ["job"])


def test_version_lists_the_formats(client):
    assert client.get("/api/version").json()["formats"] == formats.WRITES


# ---- the changelog ----

def test_the_changelog_starts_with_this_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\d+\.\d+\.\d+)", text, re.M)
    assert first and first.group(1) == __version__


# ---- the release feed ----

def _feed(tmp_path, releases, name="feed-beta.json"):
    f = tmp_path / name
    f.write_text(json.dumps(updates.make_feed("beta", releases)), encoding="utf-8")
    return f.as_uri()


def test_a_feed_is_read_and_says_what_is_newer(tmp_path):
    from mister_plis import __version__

    major, minor, patch = (int(n) for n in __version__.split("."))
    next_fix = f"{major}.{minor}.{patch + 1}"  # just after the running version, whichever it is
    url = _feed(tmp_path, [{"version": "0.8.0", "writes": {"job": 1}},
                           {"version": "9.0.0", "date": "2027-01-01", "notes": "New", "writes": {"job": 7}},
                           {"version": next_fix, "writes": {"job": 1}}])
    newer = updates.newer_releases(updates.read_feed(url))
    assert [r["version"] for r in newer] == ["9.0.0", next_fix]
    assert newer[0]["can_go_back_here"] is False and newer[0]["formats_too_new"] == ["job"]
    assert newer[1]["can_go_back_here"] is True


@pytest.mark.parametrize("text, message", [
    ("not json", "valid JSON"), ('{"format": "something else", "releases": []}', "isn't a MISTER PLIS release feed"),
    ('{"format": "mister-plis-release-feed", "format_version": 99, "releases": []}', "newer"),
])
def test_a_bad_feed_says_so(tmp_path, text, message):
    f = tmp_path / "bad.json"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(ToolError, match=message):
        updates.read_feed(f.as_uri(), max_age=0)
    with pytest.raises(ToolError, match="https://"):
        updates.read_feed("http://example.org/feed.json")


# ---- the channels ----

@pytest.mark.parametrize("kind, cls", [("docker", updates.DockerChannel), ("package", updates.ReleaseChannel),
                                       ("checkout", updates.GitChannel), ("mac-app", updates.GitChannel),
                                       ("service", updates.GitChannel)])
def test_the_channel_follows_how_it_was_installed(monkeypatch, kind, cls):
    monkeypatch.setattr(install, "kind", lambda: kind)
    assert isinstance(updates.channel(), cls)


def test_a_docker_channel_reads_the_feed_and_says_how(monkeypatch, tmp_path):
    url = _feed(tmp_path, [{"version": "9.9.9", "writes": {}}])
    monkeypatch.setattr(updates, "update_settings", lambda: {"channel": "beta", "feed": url})
    st = updates.DockerChannel().status()
    assert st["available"][0]["version"] == "9.9.9" and "docker compose pull" in st["how"] and not st["can_update"]
    with pytest.raises(ToolError, match="Docker"):
        updates.DockerChannel().update()


def test_the_git_channel_is_todays_updater_with_a_snapshot_first(monkeypatch, client):
    calls = []
    monkeypatch.setattr(updater, "sync", lambda: calls.append("sync") or {"ok": True, "steps": [], "changed": False})
    monkeypatch.setattr(updates, "make_snapshot", lambda reason, ms=None: calls.append("snapshot") or {"path": "/x"})
    r = updates.GitChannel().update()
    assert calls == ["snapshot", "sync"] and r["snapshot"] == "/x"
    st = updates.GitChannel().status()
    assert st["git"]["is_repo"] == updater.status()["is_repo"] and st["how"] == updates.GIT_HOW


def test_the_nightly_update_snapshots_first_and_stops_if_it_cant(monkeypatch):
    monkeypatch.setattr(updater, "check", lambda: {"is_repo": True, "fetch_ok": True, "behind": 1, "dirty": []})
    monkeypatch.setattr(updater, "_save_auto", lambda **k: {})
    synced = []
    monkeypatch.setattr(updater, "sync", lambda: synced.append(1) or {"ok": True, "steps": [], "new": {"short": "a", "subject": "b"}})

    def broken():
        raise OSError("disk full")

    r = updater.auto_update(busy=False, before_sync=broken)
    assert not r["ok"] and "snapshot" in r["result"] and not synced
    assert updater.auto_update(busy=False, before_sync=lambda: None)["ok"] and synced


def test_channel_and_feed_are_settings_of_the_lab_file(tmp_path):
    from mister_plis.labsetup import LabFileError, parse

    lab, _ = parse('[updates]\nchannel = "stable"\nfeed = "https://example.org/feed-stable.json"\n')
    assert lab["updates"] == {"channel": "stable", "feed": "https://example.org/feed-stable.json"}
    with pytest.raises(LabFileError):
        parse('[updates]\nchannel = "nightly"\n')


def test_the_settings_page_saves_the_channel(client):
    r = client.post("/api/system/updates", json={"channel": "stable", "feed": ""})
    assert r.json()["channel"] == "stable"
    assert client.post("/api/system/updates", json={"channel": "other"}).status_code == 422
    assert client.get("/api/system/updates").json()["name"] in ("git", "docker", "release")
    client.post("/api/system/updates", json={"channel": "beta"})


# ---- snapshots ----

def _server(root: Path) -> Path:
    data = root / "data"
    (data / "modules" / "inventory" / "repo").mkdir(parents=True)
    (data / "lab_settings.json").write_text('{"lab_name": "Smith Lab"}', encoding="utf-8")
    (data / "people.json").write_text('{"merged": {}}', encoding="utf-8")
    (data / "modules" / "inventory" / "settings.json").write_text('{"repo": "x"}', encoding="utf-8")
    (data / "modules" / "inventory" / "repo" / "reagents.csv").write_text("a\n", encoding="utf-8")  # its data: not a setting
    (data / "jobs").mkdir()
    (data / "jobs" / "x.txt").write_text("a job's file", encoding="utf-8")
    (data / "modules" / "timemachine").mkdir()
    (data / "modules" / "timemachine" / "projects.json").write_text("{}", encoding="utf-8")  # a module's storage
    return data


def test_a_snapshot_holds_the_settings_only_and_brings_them_back(tmp_path):
    data = _server(tmp_path)
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    r = transfer.export(str(snaps), data, data, ["modules/timemachine"], settings_only=True, name="before 0.9.1")
    names = set(json.loads((Path(r["path"]) / "manifest.json").read_text(encoding="utf-8"))["files"])
    assert names == {"data/lab_settings.json", "data/people.json", "data/modules/inventory/settings.json"}

    (data / "lab_settings.json").write_text('{"lab_name": "Changed"}', encoding="utf-8")
    out = transfer.bring_in_settings(r["path"], data, "Ada")  # a server with jobs may restore its settings
    assert out["files"] == 1 and json.loads((data / "lab_settings.json").read_text(encoding="utf-8"))["lab_name"] == "Smith Lab"
    kept = list(data.glob("lab_settings.json.before-restore-*"))
    assert kept and "Changed" in kept[0].read_text(encoding="utf-8")  # what it replaced is set aside, never deleted
    assert (data / "jobs" / "x.txt").exists() and (data / "modules" / "inventory" / "repo" / "reagents.csv").exists()


def test_a_whole_servers_copy_isnt_restored_as_settings(tmp_path):
    data = _server(tmp_path)
    out = tmp_path / "usb"
    out.mkdir()
    r = transfer.export(str(out), data, data, [])
    with pytest.raises(ToolError, match="isn't a snapshot"):
        transfer.bring_in_settings(r["path"], data)


def test_the_newest_five_snapshots_are_kept(tmp_path, monkeypatch):
    data = _server(tmp_path)
    monkeypatch.setattr(updates, "settings", type("S", (), {"data_path": data, "storage_path": data})())
    made = [updates.make_snapshot(f"n{i}")["path"] for i in range(7)]
    have = updates.list_snapshots()
    assert len(have) == updates.KEEP_SNAPSHOTS and {s["path"] for s in have} == set(made[-5:])
    assert Path(have[0]["path"]).parent == tmp_path / "snapshots"
    updates.restore_snapshot(have[-1]["name"])
    with pytest.raises(ToolError):
        updates.restore_snapshot("no such")


# ---- a signed release feed (mister_plis/releasekeys.py, docs/RELEASES.md) ---------------------------------------------

import shutil as _shutil
import subprocess as _subprocess

import pytest as _pytest


@_pytest.fixture
def signed_feed(tmp_path, monkeypatch):
    """A feed file, an SSH key that signs it, and the key as the code's release key. Returns (feed path, sign())."""
    if not _shutil.which("ssh-keygen"):
        _pytest.skip("ssh-keygen isn't installed")
    from mister_plis import releasekeys, updates

    key = tmp_path / "release_key"
    _subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test release key", "-f", str(key)], check=True)
    feed = tmp_path / "feed-beta.json"
    feed.write_text(json.dumps(updates.make_feed("beta", [{"version": "99.0.0", "date": "2026-11-13", "notes": "x"}])),
                    encoding="utf-8")

    def sign():
        sig = Path(str(feed) + ".sig")
        sig.unlink(missing_ok=True)
        _subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", releasekeys.NAMESPACE, str(feed)], check=True,
                        capture_output=True)

    monkeypatch.setattr(releasekeys, "SIGNERS", [(tmp_path / "release_key.pub").read_text(encoding="utf-8")])
    updates._cache.clear()
    yield feed, sign
    updates._cache.clear()


def test_a_feed_signed_by_the_release_key_is_read(signed_feed):
    from mister_plis import updates

    feed, sign = signed_feed
    sign()
    assert updates.read_feed(feed.as_uri())["signed"] is True


def test_an_unsigned_or_changed_feed_is_refused(signed_feed):
    from mister_plis import updates
    from mister_plis.errors import ToolError

    feed, sign = signed_feed
    with _pytest.raises(ToolError, match="isn't signed"):
        updates.read_feed(feed.as_uri())
    sign()
    feed.write_text(feed.read_text(encoding="utf-8").replace("99.0.0", "99.0.1"), encoding="utf-8")  # changed after signing
    updates._cache.clear()
    with _pytest.raises(ToolError, match="doesn't match"):
        updates.read_feed(feed.as_uri())


def test_another_keys_signature_is_refused(signed_feed, tmp_path, monkeypatch):
    from mister_plis import releasekeys, updates
    from mister_plis.errors import ToolError

    feed, sign = signed_feed
    sign()
    other = tmp_path / "other_key"
    _subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other)], check=True)
    monkeypatch.setattr(releasekeys, "SIGNERS", [(tmp_path / "other_key.pub").read_text(encoding="utf-8")])
    with _pytest.raises(ToolError, match="doesn't match"):
        updates.read_feed(feed.as_uri())


def test_without_a_release_key_a_feed_is_read_unsigned(tmp_path, monkeypatch):
    from mister_plis import releasekeys, updates

    monkeypatch.setattr(releasekeys, "SIGNERS", [])
    feed = tmp_path / "feed-beta.json"
    feed.write_text(json.dumps(updates.make_feed("beta", [])), encoding="utf-8")
    updates._cache.clear()
    assert updates.read_feed(feed.as_uri())["signed"] is False
