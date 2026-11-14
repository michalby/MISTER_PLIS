"""Folder copies (storage.copy_verified, move_folder_once) leave git's lock files behind: git makes and removes them
while it works, also in the background after a commit, and one that vanished mid-copy failed the move (CI on macOS,
2026-11-12, objects/maintenance.lock)."""

import subprocess

from mister_plis import storage


def _repo_with_locks(root):
    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (root / ".git" / "index.lock").write_bytes(b"")
    (root / ".git" / "objects" / "maintenance.lock").write_bytes(b"")
    (root / "notes.lock").write_text("not git's — copied", encoding="utf-8")


def test_git_lock_names():
    assert storage._git_lock(".git/index.lock")
    assert storage._git_lock("a/.git/objects/maintenance.lock")
    assert not storage._git_lock("notes.lock")
    assert not storage._git_lock(".git/HEAD")


def test_copy_verified_leaves_git_locks_behind(tmp_path):
    src = tmp_path / "src"
    _repo_with_locks(src)
    n = storage.copy_verified(src, tmp_path / "dest")
    dest = tmp_path / "dest"
    assert n == 2 and (dest / ".git" / "HEAD").is_file() and (dest / "notes.lock").is_file()
    assert not (dest / ".git" / "index.lock").exists() and not (dest / ".git" / "objects" / "maintenance.lock").exists()


def test_move_folder_once_leaves_git_locks_behind(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "a.txt").write_text("a", encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "maintenance.auto=false"]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "a"]):
        subprocess.run([*git, *args], cwd=old, check=True, capture_output=True)
    (old / ".git" / "objects" / "maintenance.lock").write_bytes(b"")  # git's background maintenance, mid-way
    assert storage.move_folder_once(old, new, "test") is True
    assert (new / "a.txt").is_file() and not (new / ".git" / "objects" / "maintenance.lock").exists()
