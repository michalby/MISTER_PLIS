"""Repositories in a folder on this machine: which addresses are folders."""

from pathlib import Path

from mister_plis import gitutil


def test_local_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # where Windows looks for ~
    assert gitutil.address(" ~/Lab ") == str(tmp_path / "Lab")
    assert gitutil.local_folder("~/Lab") == tmp_path / "Lab"
    assert gitutil.local_folder("/Volumes/NAS/inventory") == Path("/Volumes/NAS/inventory")
    assert gitutil.local_folder("file:///srv/My%20vault") == Path("/srv/My vault")
    for url in ("https://github.com/smith-lab/inventory.git", "git@github.com:a/b.git", ""):
        assert gitutil.local_folder(url) is None


def test_remove_clone_deletes_read_only_files(tmp_path):
    """Git keeps its object files read-only; Windows refuses to delete those unless they are made writable."""
    import stat

    clone = tmp_path / "clone"
    (clone / ".git" / "objects" / "ab").mkdir(parents=True)
    obj = clone / ".git" / "objects" / "ab" / "cdef"
    obj.write_bytes(b"x")
    obj.chmod(stat.S_IREAD)
    gitutil.remove_clone(clone)
    assert not clone.exists()
    gitutil.remove_clone(clone)  # nothing there: nothing to do
