"""The exact versions of MISTER PLIS's own packages, as installed on this server (reorg P7, task 7.4).

A tool source's requirements are installed with ``-c <these pins>`` after a dry run, so a tool repository can add
packages but never upgrade or downgrade the base's. The pins are read from the running environment each time — the
lab server's own versions, not anyone else's.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()



def installed_pins(requirements: Path | None = None) -> dict[str, str]:
    """{package: version} for requirements.txt and everything it needs, as installed."""
    env = default_environment()
    todo, seen, pins = [], set(), {}
    for line in (requirements or ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            todo.append((Requirement(line), ""))
    while todo:
        req, extra = todo.pop()
        if req.marker and not req.marker.evaluate({**env, "extra": extra}):
            continue
        key = (norm(req.name), tuple(sorted(req.extras)))
        if key in seen:
            continue
        seen.add(key)
        try:
            dist = metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            continue  # not installed: nothing to protect
        pins[norm(req.name)] = dist.version
        for dep in dist.requires or []:
            r = Requirement(dep)
            for e in [""] + sorted(req.extras):
                if not r.marker or r.marker.evaluate({**env, "extra": e}):
                    todo.append((r, e))
                    break
    return pins


def all_installed() -> dict[str, str]:
    """{package: version} for everything installed in the app's own environment (not only the base's): a tool source's
    packages may add to it, never change it (toolsources: they are installed beside it, in the instance's folder)."""
    out: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"] if dist.metadata else None
        if name and norm(name) not in out:
            out[norm(name)] = dist.version
    return out


def _version(name: str, paths: list[str]) -> str | None:
    """The installed version of a package, looked for in ``paths`` (a tool source's own folder) and then the app's
    environment."""
    if paths:
        for dist in metadata.distributions(path=[str(p) for p in paths]):
            if dist.metadata and norm(dist.metadata["Name"] or "") == norm(name):
                return dist.version
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def missing(requirements: Path, paths: list | None = None) -> list[str]:
    """The lines of a requirements file that this environment doesn't satisfy (not installed, or another version).
    ``paths``: folders of packages to look in first (a tool source's own, toolsources.packages_path)."""
    env, out = default_environment(), []
    paths = [str(p) for p in paths or [] if Path(p).is_dir()]
    try:
        lines = requirements.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            req = Requirement(line)
        except ValueError:
            out.append(line)  # pip will say what's wrong with it
            continue
        if req.marker and not req.marker.evaluate(env):
            continue
        version = _version(req.name, paths)
        if version is None:
            out.append(line)
            continue
        if req.specifier and not req.specifier.contains(version, prereleases=True):
            out.append(line)
    return out


def write_constraints(path: Path, everything: bool = False) -> Path:
    """The pins as a pip constraints file: the base's packages, or (``everything``) every package installed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pins = {**all_installed(), **installed_pins()} if everything else installed_pins()
    path.write_text("".join(f"{n}=={v}\n" for n, v in sorted(pins.items())), encoding="utf-8")
    return path
