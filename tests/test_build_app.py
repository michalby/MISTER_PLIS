"""Build metadata from real Git checkouts and source ZIPs, with the macOS toolchain stubbed."""

import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# The Mac app is built with a bash script (macOS toolchain stubbed here, so it also runs on Linux); Windows has no
# /bin/bash and never builds the Mac app.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the Mac app is built with bash, on macOS (or Linux)")

BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_app.sh"
UPSTREAM = "https://github.com/michalby/MISTER_PLIS.git"


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=Build Test", "-c", "user.email=build@example.invalid", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    encoding="utf-8", errors="replace")


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source archive"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(BUILD_SCRIPT, root / "scripts/build_app.sh")
    (root / "mister_plis").mkdir()
    (root / "mister_plis/__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    build = root / "build/macos"
    build.mkdir(parents=True)
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    version = re.search(r"^PY_VERSION=(.+)$", script, re.M)[1]
    release = re.search(r"^PY_RELEASE=(.+)$", script, re.M)[1]
    (build / f"cpython-{version}+{release}-aarch64-apple-darwin-install_only_stripped.tar.gz").touch()

    # Only external build tools are stubbed; Git and the build script run normally.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "build-tool"
    stub.write_text("""#!/bin/bash
set -eu
case "$(basename "$0")" in
  curl)
    printf '%s\\n' "$@" > "$TEST_CURL_LOG"
    while [ "$1" != "-o" ]; do shift; done
    printf 'downloaded archive' > "$2"
    ;;
  shasum) echo "$TEST_PY_SHA256  archive" ;;
  swiftc)
    while [ "$1" != "-o" ]; do shift; done
    printf '#!/bin/sh\\nmkdir -p "$2"\\n' > "$2"
    chmod +x "$2"
    ;;
  ditto) touch "${@: -1}" ;;
esac
""", encoding="utf-8")
    stub.chmod(0o755)
    for command in ("xcrun", "curl", "shasum", "swiftc", "iconutil", "tar", "codesign", "ditto"):
        (bin_dir / command).symlink_to(stub)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               TEST_CURL_LOG=str(bin_dir / "curl-args.txt"),
               TEST_PY_SHA256=re.search(r"^PY_SHA256=(.+)$", script, re.M)[1])
    env.pop("MISTER_PLIS_REPO_URL", None)
    env.pop("MISTER_PLIS_LAB_FILE", None)
    return root, env


@pytest.mark.parametrize("checkout,remote,override", [
    ("archive", None, None),
    ("archive", None, "https://github.com/example/fork.git"),
    ("parent", "https://github.com/example/unrelated.git", None),
    ("checkout", "https://github.com/example/fork.git", None),
    ("checkout", "https://token@example.com/fork.git", None),
    ("checkout", None, None),
    ("checkout", "https://github.com/example/fork.git", "https://github.com/example/override.git"),
])
def test_build_metadata(source, checkout, remote, override):
    root, env = source
    if checkout != "archive":
        repo = root.parent if checkout == "parent" else root
        git(repo, "init", "-q")
        git(repo, "commit", "--allow-empty", "-qm", "first")
        git(repo, "commit", "--allow-empty", "-qm", "second")
        if remote:
            git(repo, "remote", "add", "origin", remote)
    if override:
        env["MISTER_PLIS_REPO_URL"] = override
    result = subprocess.run(
        ["/bin/bash", str(root / "scripts/build_app.sh")], cwd=root.parent,
        env=env, capture_output=True, text=True, errors="backslashreplace",
    encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fatal:" not in result.stderr
    assert not Path(env["TEST_CURL_LOG"]).exists()
    with (root / "dist/MISTER PLIS.app/Contents/Info.plist").open("rb") as f:
        info = plistlib.load(f)
    expected = override or (remote if checkout == "checkout" else None) or UPSTREAM
    assert info["MPRepoURL"] == re.sub(r"://[^/@]+@", "://", expected)
    assert info["CFBundleVersion"] == ("2" if checkout == "checkout" else "1")
    assert info["CFBundleShortVersionString"] == "1.0.0"
    assert info["MPLabFile"] == ""  # no lab file unless asked
    assert (root / "dist/MISTER PLIS.zip").is_file()


@pytest.mark.parametrize("lab_file,ok", [("labs/our & their lab.toml", True), ("https://example.org/lab.toml", True),
                                          ("https://user:token@example.org/lab.toml", False)])
def test_a_lab_file_is_baked_in(source, lab_file, ok):
    root, env = source
    env["MISTER_PLIS_LAB_FILE"] = lab_file
    result = subprocess.run(["/bin/bash", str(root / "scripts/build_app.sh")], cwd=root.parent, env=env,
                            capture_output=True, text=True, errors="backslashreplace", encoding="utf-8")
    assert (result.returncode == 0) == ok, result.stdout + result.stderr
    if ok:
        with (root / "dist/MISTER PLIS.app/Contents/Info.plist").open("rb") as f:
            assert plistlib.load(f)["MPLabFile"] == lab_file
        assert "lab file:" in result.stdout


@pytest.mark.parametrize("locale", ["C", "en_US.UTF-8", "pl_PL.UTF-8"])
def test_first_build_downloads_python(source, locale):
    root, env = source
    archive, = (root / "build/macos").glob("cpython-*.tar.gz")
    archive.unlink()
    env["LC_ALL"] = locale
    result = subprocess.run(
        ["/bin/bash", str(root / "scripts/build_app.sh")], cwd=root.parent,
        env=env, capture_output=True, text=True, errors="backslashreplace",
    encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Downloading Python " in result.stdout
    args = Path(env["TEST_CURL_LOG"]).read_text(encoding="utf-8").splitlines()
    release = archive.name.split("+", 1)[1].split("-", 1)[0]
    url = ("https://github.com/astral-sh/python-build-standalone/releases/download/"
           f"{release}/{archive.name.replace('+', '%2B')}")
    assert args == ["-fL", "--progress-bar", "-o", str(archive) + ".part", url]
    assert archive.read_text(encoding="utf-8") == "downloaded archive"
    assert not archive.with_suffix(archive.suffix + ".part").exists()
    assert (root / "dist/MISTER PLIS.zip").is_file()
