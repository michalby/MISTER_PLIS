"""File and folder names any system can use: Windows and SMB shares refuse some that macOS and Linux allow
(docs/PREP_PLAN.md R2). Folders written before keep their names and are still found."""

import shutil
from pathlib import Path

import pytest

from mister_plis.toolkit import safe_filename

BAD_CHARS = '<>:"/\\|?*'


@pytest.mark.parametrize("name", ["con", "CON", "Con", "prn", "aux", "nul", "com1", "COM9", "lpt1", "Lpt9",
                                  "con.txt", "NUL.tar.gz", "aux.csv", "con .txt"])
def test_names_windows_keeps_for_itself(name):
    got = safe_filename(name)
    assert got.split(".")[0].strip().lower() not in {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {
        f"lpt{i}" for i in range(1, 10)}
    assert got.lower().startswith(name.split(".")[0].strip().lower())  # still recognisable


@pytest.mark.parametrize("name", ["console.txt", "com10.csv", "auxiliary", "nullable.json", "my con.txt", "Connor"])
def test_ordinary_names_are_kept(name):
    assert safe_filename(name) == name


@pytest.mark.parametrize("name", ['a<b>c:d"e|f?g*h.csv', "tab\there.txt", "bell\x07.txt", "ends with dot.",
                                  "ends with space ", "  .hidden", "...", "", "C:\\Users\\x\\data.csv"])
def test_characters_and_ends_windows_refuses(name):
    got = safe_filename(name)
    assert got and not any(c in got for c in BAD_CHARS)
    assert not any(ord(c) < 32 for c in got)
    assert not got.endswith((".", " ")) and not got.startswith((".", " "))


def test_letters_of_any_language_stay():
    assert safe_filename("Próbka żółta (dzień 3).csv") == "Próbka żółta (dzień 3).csv"


def test_a_backup_folder_named_before_is_still_found(tmp_path):
    """The catalogue finds a job's backup by the "(<job id>)" at the end of its folder's name and its manifest, not by
    the person's folder: one named otherwise before (here "Ola & Ana": "&" isn't kept any more) is still found."""
    from mister_plis.backup import BackupCatalogue

    fixture = Path(__file__).parent / "fixtures" / "backup_v0"
    root = tmp_path / "backup"
    shutil.copytree(fixture, root)
    (root / "Ola").rename(root / "Ola & Ana")
    found = BackupCatalogue(lambda: str(root)).find("20261107-093131-34a42a")
    assert len(found) == 1 and Path(found[0]["folder"]).parent.name == "Ola & Ana"
