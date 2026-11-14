"""requirements.lock pins what requirements.txt asks for, each with its checksums (scripts/lock.sh; SECURITY_AUDIT.md M5)."""

import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def _pins() -> dict[str, tuple[str, int]]:
    """name → (version, number of checksums) from requirements.lock."""
    pins, current = {}, None
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;\\]+)", line)
        if m:
            current = canonicalize_name(m.group(1))
            pins[current] = (m.group(2), 0)
        elif current and "--hash=sha256:" in line:
            v, n = pins[current]
            pins[current] = (v, n + 1)
    return pins


def test_every_requirement_is_pinned_with_checksums():
    pins = _pins()
    assert len(pins) > 20 and all(n >= 1 for _, n in pins.values()), [k for k, (_, n) in pins.items() if not n]
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} is in requirements.txt but not in requirements.lock: run ./scripts/lock.sh"
        assert req.specifier.contains(Version(pins[name][0]), prereleases=True), \
            f"{req.name}=={pins[name][0]} doesn't fit {req.specifier}: run ./scripts/lock.sh"


def test_the_image_installs_only_the_pinned_versions():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in docker
    assert "--require-hashes" in (ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
