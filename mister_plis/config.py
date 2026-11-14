"""Server settings.

Defaults live here. Override them per machine in ``config.toml`` in the instance's folder (``HOME`` below: the
repository folder unless ``MISTER_PLIS_HOME`` says otherwise; gitignored, copy ``config.example.toml``) or with
``MISTER_PLIS_<NAME>`` environment variables, e.g. ``MISTER_PLIS_PORT=9000``.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ROOT is the code (read-only in a release); HOME is this instance (config.toml, data/, secrets/, logs/). Without
# MISTER_PLIS_HOME they are the same folder, as before.
HOME = Path(os.environ.get("MISTER_PLIS_HOME") or ROOT).expanduser().resolve()


def _config_table() -> dict:
    """The instance's ``config.toml`` (``{}`` when there is none)."""
    cfg = HOME / "config.toml"
    try:
        return tomllib.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
    except PermissionError:  # a job's process running as another user (job_user): it gets its folders from the server
        return {}


def _in_home(p: Path) -> Path:
    """A path from the settings: a relative one is relative to the instance's folder."""
    return p if p.is_absolute() else HOME / p


@dataclass
class Settings:
    host: str = "0.0.0.0"
    port: int = 8000
    # Stored files (jobs, Time Machine) also come from an address of their own (mister_plis/fileorigin.py): "" = this
    # host, files_port, plain HTTP; "off" = none; or the address a proxy gives it (https://files.mister-plis.lab.example)
    files_origin: str = ""
    files_port: int = 0  # 0 = port + 1
    # Other names this machine is reached by (a proxy's domain…), besides its own names and IP addresses, which always
    # work; the lab's own list is on Settings → Server & updates. Separated by commas (config.toml can give a list);
    # "*" = any name (the check against DNS rebinding off — docs/SECURITY_AUDIT.md H1)
    server_names: str = ""
    # The proxies (HTTPS in front of the server: docs/DEPLOY_LINUX.md) whose X-Forwarded-For / -Proto are believed: their
    # IP addresses, separated by commas; "*" = any (only when nothing but the proxy can reach the server, e.g. Docker
    # with no port published). "" = this computer only (127.0.0.1), as before.
    trusted_proxies: str = ""
    lab_name: str = ""
    data_dir: str = "data"
    # Where jobs (one folder each) and what tools save live; "" = the data folder. A folder chosen on Settings → Jobs & backup
    # (data/storage.json) wins over this. See mister_plis/storage.py.
    storage_dir: str = ""
    # Which modules (folders in modules/) to load: "" = all of them, "none" = none, or e.g. "timemachine, inventory"
    modules: str = ""
    # Fetch the tool sources that aren't here yet when the server starts (Settings → Tools); 0 = never
    # (tests, and machines without a network)
    fetch_tool_sources: int = 1
    # Tool folders on this machine, loaded before the tool sources: a working copy of a tools repository while you
    # write tools (it stands in for the source of the same name), or the tests' own fixture tools. Several are
    # separated with the system's path separator (":" on a Mac); config.toml can give a list.
    tool_folders: str = ""
    # The older way to tell a tool where Blender is (toolkit.find_program reads <name>_path); the Blender tool's own
    # setting on Settings → Tools wins over it.
    blender_path: str = ""
    max_workers: int = 8
    # Each job kept in the history runs in a process of its own ("process", runners.ProcessRunner) — or, "off", in the
    # server's own threads, as before 0.17.0 (docs/SECURITY_AUDIT.md H4)
    job_isolation: str = "process"
    # …and as this other user of the computer (Linux, macOS), who can't read the server's secrets: started with
    # "sudo -n -u <job_user>" (docs/DEPLOY_LINUX.md, "Jobs as another user"). "" = as the server's own user
    job_user: str = ""
    # 1 = publish the API's reference at /api/docs (for scripting against it); off by default, as it maps every route
    api_docs: int = 0
    job_retention_days: int = 30
    upload_retention_days: int = 3
    git_branch: str = ""  # empty = whatever branch is checked out
    # A lab file (docs/LAB_SETUP_PLAN.md): applied on start while the server isn't set up yet; a path (relative to the
    # code folder, or else to the instance's folder) or an https:// address. Ignored once the server is set up.
    lab_file: str = ""
    # the settings given in config.toml or as MISTER_PLIS_* variables (the rest are defaults): these win over what is
    # stored by the Settings page or a lab file
    explicit: frozenset = field(default_factory=frozenset, repr=False)

    @property
    def data_path(self) -> Path:
        return _in_home(Path(self.data_dir))

    @property
    def secrets_path(self) -> Path:
        """Where this instance keeps what must not be shared (tokens…): never inside the data or storage folder."""
        return HOME / "secrets"

    @property
    def logs_path(self) -> Path:
        return HOME / "logs"

    @property
    def storage_path(self) -> Path:
        """The storage folder: chosen on Settings → Jobs & backup, else ``storage_dir``, else the data folder."""
        import json

        try:
            chosen = json.loads((self.data_path / "storage.json").read_text(encoding="utf-8")).get("dir", "")
        except (OSError, ValueError, AttributeError):
            chosen = ""
        text = str(chosen or self.storage_dir or "").strip()
        if not text:
            return self.data_path
        return _in_home(Path(text).expanduser())

    def enabled_modules(self) -> list[str] | None:
        """The modules to load: ``modules = "timemachine, inventory"`` in config.toml (``"none"`` = none); else the
        ones chosen when the lab was set up (``modules`` in <data>/lab.json); else all."""
        if "modules" not in self.explicit:
            import json

            try:
                chosen = json.loads((self.data_path / "lab.json").read_text(encoding="utf-8")).get("modules")
            except (OSError, ValueError, AttributeError):
                chosen = None
            if isinstance(chosen, list):
                return [str(m) for m in chosen if isinstance(m, str) and m]
        text = (self.modules or "").strip()
        if not text:
            return None
        return [] if text.lower() == "none" else [m.strip() for m in text.replace(";", ",").split(",") if m.strip()]

    def server_name_list(self) -> list[str]:
        import re

        return [n for n in re.split(r"[\s,;:]+", str(self.server_names or "").strip()) if n]

    def tool_folder_paths(self) -> list[Path]:
        out = []
        for part in str(self.tool_folders or "").split(os.pathsep):
            if part.strip():
                out.append(_in_home(Path(part.strip()).expanduser()))
        return out

    def module_settings(self, mid: str) -> dict:
        """A module's own settings: the ``[module.<id>]`` table of config.toml, then ``MISTER_PLIS_MODULE_<ID>_<KEY>``
        environment variables (e.g. ``MISTER_PLIS_MODULE_INVENTORY_REPO=""`` turns its GitHub sync off)."""
        try:
            table = _config_table().get("module", {}).get(mid, {})
        except (OSError, ValueError, AttributeError):
            table = {}
        table = dict(table) if isinstance(table, dict) else {}
        prefix = f"MISTER_PLIS_MODULE_{mid.upper()}_"
        for k, v in os.environ.items():
            if k.startswith(prefix) and len(k) > len(prefix):
                table[k[len(prefix):].lower()] = v
        return table


def load_settings() -> Settings:
    values: dict = dict(_config_table())
    for f in fields(Settings):
        env = os.environ.get(f"MISTER_PLIS_{f.name.upper()}")
        if env is not None:
            values[f.name] = env
    known = {f.name: f.type for f in fields(Settings) if f.name != "explicit"}
    clean = {}
    for k, v in values.items():
        if k not in known:
            if not isinstance(v, dict):  # tables ([module.<id>]) are read by module_settings
                print(f"config.toml: {k!r} is not a setting (any more) — ignored. See config.example.toml.", file=sys.stderr)
            continue
        default = getattr(Settings, k)
        if isinstance(v, list):
            v = os.pathsep.join(str(x) for x in v)
        clean[k] = int(v) if isinstance(default, int) else str(v)
    return Settings(**clean, explicit=frozenset(clean))


settings = load_settings()
