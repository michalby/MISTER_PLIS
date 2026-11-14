"""Everything a tool author needs.

A tool is a Python file in a tool source (a git repository, docs/ADDING_TOOLS.md) that defines a module-level
``tool``::

    from mister_plis.toolkit import Tool, inputs as I, outputs as O

    tool = Tool(
        id="dilution",
        name="Dilution",
        category="Calculators",
        description="C1·V1 = C2·V2",
        inputs=[I.Number("c1", "Stock concentration", default=1)],
        live=True,
    )

    @tool.runner
    def run(p, ctx):
        return O.Metric("Result", p.c1 * 2)

``p`` holds the parsed input values (``p.c1`` or ``p["c1"]``), ``ctx`` is a
:class:`RunContext` for progress, logging, output files and subprocesses.
Return an output, a list of outputs, or a plain value (str, DataFrame, plotly
figure, PIL image) that is converted automatically.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import inputs, outputs  # noqa: F401  (re-exported for tool authors)
from .errors import Cancelled, ToolError  # noqa: F401
from .excel import write_workbook  # noqa: F401
from .prefs import pref  # noqa: F401  (the settings of whoever runs the tool, e.g. pref("decimal"))
from .i18n import tn, tr, trc  # noqa: F401  (translated texts — see mister_plis/i18n.py)
from .outputs import fmt, md_escape  # noqa: F401  (md_escape: names people typed, inside Markdown text)
from .plotting import DIVERGING, PALETTE, SEQUENTIAL  # noqa: F401  (also installs the plot theme)
from .inputs import Input, Section, UploadedFile  # noqa: F401
from .outputs import Output, coerce_outputs  # noqa: F401


# The version of this module's public API (``__all__``). Tools may use only what is listed there: they will live in
# their own repositories (docs/reorg/P1.md), so everything else in mister_plis is internal and may change.
TOOLKIT_API = 1
# Which additions to API 1 are here: "1.1" adds the settings a tool declares (Tool(settings=...), settings_status,
# tool_setting, ctx.setting, find_program(configured=...)). A tool source that needs them asks for
# requires_toolkit = ">=1.1,<2"; an older MISTER PLIS then says it can't load it instead of failing on the tools.
# (safe_filename also refuses the names Windows keeps for itself, e.g. "con.csv" → "con_.csv": only names that were
# unusable there anyway change, so this is not a new version.)
# "1.2" adds Tool(needs=(...)): what a computer must have to run the tool ("gpu", "program:blender").
# "1.3" adds inputs.ImageSpots: circles people place and name on a picture the tool shows (e.g. areas of an image to
# measure), suggested by @tool.suggest like a PlateLayout.
TOOLKIT_VERSION = "1.3"

__all__ = [
    "TOOLKIT_API", "TOOLKIT_VERSION",
    # defining a tool
    "Tool", "Params", "RunContext", "Input", "Section", "UploadedFile", "Output", "inputs", "outputs", "coerce_outputs",
    "ToolError", "Cancelled",
    # texts and settings of whoever runs the tool
    "tr", "tn", "trc", "pref", "fmt", "md_escape", "alphabetical_key",
    # files, tables, plots
    "read_table", "excel_sheets", "write_workbook", "zip_files", "safe_filename", "human_size", "figure_to_png", "data_url",
    "TABLE_SUFFIXES", "PALETTE", "SEQUENTIAL", "DIVERGING",
    # the server around the tool
    "tool_data_dir", "tool_data_file", "find_program", "which", "tool_setting",
]

_PLAIN_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
# Polish letters come right after their base letter (a < ą < b … l < ł < m), not after z
_POLISH = {c: base + "\u0080" for c, base in zip("ąćęłńóśźż", "acelnoszz")}
_POLISH["ż"] = "z\u0081"  # ź < ż


def alphabetical_key(label: str) -> tuple:
    """Sort key for names people pick from a list: ignores case, reads K₂HPO₄ as K2HPO4, numbers by value
    (2 before 12), Polish letters in Polish order."""
    import re

    text = "".join(_POLISH.get(c, c) for c in label.translate(_PLAIN_DIGITS).casefold())
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in re.split(r"(\d+)", text) if part)


class Params(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


@dataclass
class Tool:
    id: str
    name: str
    description: str = ""
    category: str = "Other"
    icon: str = "tool"
    inputs: list = field(default_factory=list)
    live: bool = False  # re-run automatically whenever an input changes (calculators)
    background: bool = False  # long jobs: return immediately and show progress
    max_concurrent: int | None = None  # e.g. 1 for GPU-bound renders: extra jobs queue up
    submit_label: str = "Run"
    history: bool | None = None  # list runs on the Jobs page (default: not for live tools)
    available: Callable[[], str | None] | None = None  # return a reason string if unusable
    wide: bool = False  # form spans the full width above the results (for tables / plate layouts)
    protocol: bool = False  # "Add to protocol": collect several results and print them together (calculators)
    report_label: str = ""  # no longer used: every result has the same "PDF" button (the whole result)
    order: int = 100
    tags: tuple = ()
    author: str = ""
    run_fn: Callable | None = field(default=None, repr=False)
    suggesters: dict = field(default_factory=dict, repr=False)
    labeler: Callable | None = field(default=None, repr=False)
    # What the tool needs set up on this server (toolkit 1.1): inputs like a form's (I.Text, I.Select…), lab-wide,
    # set on Settings → Tools and read with tool_setting(id, name) or ctx.setting(name). settings_status: one line
    # shown under them (e.g. where the program was found), or None.
    settings: list = field(default_factory=list)
    settings_status: Callable[[], str | None] | None = field(default=None, repr=False)
    # What a computer must have to run it (toolkit 1.2), e.g. ("gpu",) or ("program:blender",). Recorded with each job;
    # the tool's own ``available`` check says whether this server has it.
    needs: tuple = ()
    # where the tool came from (set by the registry): its tool source, that repository's address and commit
    source: str = field(default="", repr=False)
    source_url: str = field(default="", repr=False)
    source_commit: str = field(default="", repr=False)

    def __post_init__(self):
        if self.history is None:
            self.history = not self.live
        names = [i.name for i in self.inputs if isinstance(i, Input)]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"Tool {self.id}: duplicate input names {sorted(dupes)}")
        self.needs = tuple(self.needs)
        if not all(isinstance(n, str) and n.strip() for n in self.needs):
            raise ValueError(f"Tool {self.id}: needs must be words, e.g. ('gpu',)")
        snames = [i.name for i in self.settings]
        if not all(isinstance(i, Input) for i in self.settings) or len(set(snames)) != len(snames):
            raise ValueError(f"Tool {self.id}: settings must be inputs with different names")

    def runner(self, fn: Callable) -> Callable:
        self.run_fn = fn
        return fn

    def suggest(self, input_name: str) -> Callable:
        """Decorator: ``fn(files, params)`` pre-fills a SampleTable / PlateLayout / ImageSpots from the uploads."""

        def deco(fn: Callable) -> Callable:
            self.suggesters[input_name] = fn
            return fn

        return deco

    def label(self, fn: Callable) -> Callable:
        """Decorator: ``fn(params)`` → what a printed reagent label says by default, e.g.
        ``{"name": "NaCl", "detail": "150 mM"}``. Results added to the protocol then become labels, printed together
        on one strip of P-touch tape ("Labels" under the protocol)."""
        self.labeler = fn
        return fn

    def heading(self, raw: dict) -> str:
        """What a result is called in the protocol: the reagent (and its concentration) when the tool makes labels,
        e.g. "NaCl · 150 mM" — that's what matters at the bench, not which calculator made it. Else the tool's name."""
        if not self.labeler:
            return self.name

        def no_files(_):
            raise ToolError("no files here")

        try:
            fields = self.labeler(self.parse(raw or {}, no_files)) or {}
        except Exception:
            return self.name
        name = " ".join(str(fields.get("name") or "").split())
        detail = " ".join(str(fields.get("detail") or "").split())
        return " · ".join(x for x in (name or self.name, detail) if x)

    def unavailable_reason(self) -> str | None:
        if self.run_fn is None:
            return "This tool has no @tool.runner function."
        if self.available:
            try:
                return self.available()
            except Exception as e:  # pragma: no cover
                return f"Availability check failed: {e}"
        return None

    def input_map(self) -> dict[str, Input]:
        return {i.name: i for i in self.inputs if isinstance(i, Input)}

    def parse(self, raw: dict, resolve_upload: Callable[[str], UploadedFile]) -> Params:
        values = Params()
        errors = []
        for inp in self.input_map().values():
            try:
                values[inp.name] = inp.parse(raw[inp.name] if inp.name in raw else inp.default, resolve_upload)
                if getattr(inp, "units", None):
                    values[f"{inp.name}_unit"] = inp.parse_unit(raw.get(f"{inp.name}__unit"))
            except ToolError as e:
                from .i18n import tr

                errors.append(f"{tr(inp.label)}: {tr(str(e))}")
        if errors:
            raise ToolError("\n".join(errors))
        return values

    def spec(self, translate: bool = False) -> dict:
        """What the browser needs to draw the form (``translate``: its texts in the viewer's language)."""
        d = self._spec()
        return translate_spec(d) if translate else d

    def _spec(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "live": self.live,
            "wide": self.wide,
            "protocol": self.protocol,
            "report_label": self.report_label,
            "label": self.labeler is not None,
            "background": self.background,
            "history": bool(self.history),
            "submit_label": self.submit_label,
            "tags": list(self.tags),
            "author": self.author,
            "unavailable": self.unavailable_reason() or None,
            "inputs": [i.spec() for i in self.inputs],
        }


_TEXT_KEYS = ("name", "description", "category", "submit_label", "unavailable", "label", "help", "placeholder", "title", "unit")


def translate_spec(d):
    """A tool's spec with its words in the viewer's language: labels, hints, option names, table columns.
    Values (``name`` of an input, option values) stay as they are — only what people read changes."""
    from .i18n import tr, tr_text

    if isinstance(d, list):
        return [translate_spec(x) for x in d]
    if not isinstance(d, dict):
        return d
    out = dict(d)
    is_input = "kind" in d and "id" not in d
    for k in _TEXT_KEYS:
        if k == "name" and is_input:
            continue  # an input's name is its key in p
        if isinstance(out.get(k), str):
            out[k] = tr_text(out[k]) if k in ("help", "description") else tr(out[k])
    if isinstance(out.get("options"), list):
        out["options"] = [[o[0], tr(o[1]) if isinstance(o[1], str) else o[1], *o[2:]] if isinstance(o, list) and len(o) >= 2 else o
                          for o in out["options"]]
        if out.get("sort"):  # alphabetical in the shown language; "Other…" (an empty or "custom" value) stays last
            last = [o for o in out["options"] if o[0] in ("", "custom")]
            rest = sorted((o for o in out["options"] if o[0] not in ("", "custom")), key=lambda o: alphabetical_key(str(o[1])))
            out["options"] = rest + last
    for k in ("inputs", "columns"):
        if isinstance(out.get(k), list):
            out[k] = [translate_spec(x) for x in out[k]]
    return out


class RunContext:
    """Handed to every run function."""

    def __init__(self, job_id: str, workdir: Path, on_update: Callable[[], None] | None = None, tool_id: str = ""):
        self.job_id = job_id
        self.workdir = workdir
        self.tool_id = tool_id
        self.progress_value: float | None = None
        self.message: str = ""
        self.logs: list[str] = []
        self._cancel = threading.Event()
        self._procs: list[subprocess.Popen] = []
        self._on_update = on_update or (lambda: None)

    # --- feedback -------------------------------------------------------
    def progress(self, fraction: float | None, message: str | None = None) -> None:
        """Report progress (0..1, or None for indeterminate) and an optional status line."""
        self.check_cancelled()
        self.progress_value = None if fraction is None else max(0.0, min(1.0, float(fraction)))
        if message is not None:
            self.message = message
        self._on_update()

    def log(self, line: str) -> None:
        self.logs.append(str(line).rstrip("\n"))
        if len(self.logs) > 2000:
            del self.logs[:500]
        self._on_update()

    # --- files ----------------------------------------------------------
    @property
    def outdir(self) -> Path:
        d = self.workdir / "out"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def tmpdir(self) -> Path:
        d = self.workdir / "tmp"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def out(self, filename: str) -> Path:
        """Path for an output file. Pass it to outputs.File / outputs.Image to offer a download."""
        p = self.outdir / safe_filename(filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # --- cancellation & subprocesses -----------------------------------
    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()

    def setting(self, name: str) -> Any:
        """A setting of the tool being run (toolkit 1.1; Tool(settings=...), set on Settings → Tools)."""
        return tool_setting(self.tool_id, name)

    def cancel(self) -> None:
        self._cancel.set()
        for p in list(self._procs):
            if p.poll() is None:
                p.terminate()

    def run(
        self,
        cmd: list[str],
        cwd: str | Path | None = None,
        on_line: Callable[[str], None] | None = None,
        log_output: bool = True,
        env: dict | None = None,
    ) -> int:
        """Run an external program, streaming its output into the job log. Returns the exit code.

        Cancelling the job terminates the process.
        """
        self.check_cancelled()
        proc = subprocess.Popen(
            [str(c) for c in cmd],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            errors="replace",
        encoding="utf-8")
        self._procs.append(proc)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if log_output:
                    self.log(line)
                if on_line:
                    on_line(line)
            code = proc.wait()
        finally:
            self._procs.remove(proc)
        self.check_cancelled()
        return code


# --- helpers useful in many tools --------------------------------------------

TABLE_SUFFIXES = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls", ".json")


# Names Windows (and SMB shares) refuse whatever their extension: "con", "NUL.txt", "com1.csv"…
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_filename(name: str) -> str:
    """A name any system can use for a file or folder: letters, digits and ``._- ()[]`` only (the rest become ``_``),
    no leading or trailing dot or space, and never a name Windows keeps for itself ("con.csv" → "con_.csv")."""
    keep = "".join(c if c.isalnum() or c in "._- ()[]" else "_" for c in Path(name).name)
    keep = keep.strip(" .") or "file"
    stem, dot, rest = keep.partition(".")
    if stem.rstrip(" ").lower() in _RESERVED:
        keep = f"{stem.rstrip(' ')}_{dot}{rest}"
    return keep


def read_table(path: str | Path, sheet: str | int | None = None, decimal: str = ".", skiprows: int = 0):
    """Load CSV / TSV / Excel / JSON into a pandas DataFrame, guessing the delimiter.

    ``sheet`` is an Excel sheet name or 0-based index (default: first sheet).
    """
    import pandas as pd

    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix in (".xlsx", ".xlsm", ".xls"):
            if isinstance(sheet, str) and sheet.strip().isdigit():
                sheet = int(sheet) - 1 if int(sheet) > 0 else 0
            return pd.read_excel(path, sheet_name=0 if sheet in (None, "") else sheet, skiprows=skiprows or None)
        if suffix == ".json":
            return pd.read_json(path)
        if suffix == ".tsv":
            return pd.read_csv(path, sep="\t", decimal=decimal, skiprows=skiprows or None)
        if decimal == ",":  # "1,5;2,7" style files: the separator is almost always ";"
            return pd.read_csv(path, sep=";", decimal=",", skiprows=skiprows or None)
        return pd.read_csv(path, sep=None, engine="python", skiprows=skiprows or None)
    except Exception as e:
        raise ToolError(f"Could not read {path.name}: {e}") from e


def excel_sheets(path: str | Path) -> list[str]:
    import pandas as pd

    path = Path(path)
    if path.suffix.lower() not in (".xlsx", ".xlsm", ".xls"):
        return []
    with pd.ExcelFile(path) as xf:
        return [str(s) for s in xf.sheet_names]


def zip_files(paths: Iterable[Path], dest: Path, base: Path | None = None) -> Path:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=str(p.relative_to(base)) if base else p.name)
    return dest


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def which(program: str) -> str | None:
    return shutil.which(program)


def tool_setting(tool_id: str, name: str) -> Any:
    """The value of a tool's setting (toolkit 1.1: ``Tool(settings=[I.Text("program", …)])``), as set on Settings →
    Tools for the whole lab; the input's default when nothing is set. None for a setting the tool doesn't declare."""
    from . import toolsettings
    from .registry import registry

    tool = registry.get(tool_id)
    if tool is not None and tool.settings:
        return toolsettings.values(tool).get(name)
    return toolsettings.saved(tool_id).get(name)  # while the tools are still loading


def figure_to_png(fig) -> bytes:
    """Render a matplotlib figure to PNG bytes."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    return buf.getvalue()


def data_url(png: bytes, mime: str = "image/png") -> str:
    """Embed small images (e.g. previews in a SampleTable) directly in JSON."""
    import base64

    return f"data:{mime};base64," + base64.b64encode(png).decode()


# ---- the server around a tool ----------------------------------------------------------------------------------

def tool_data_dir(name: str) -> Path:
    """A folder where a tool keeps what the lab saves with it (saved compounds, lab methods…), shared by everyone.

    Use it instead of reaching for the server's data folder: where tools keep their data is the server's business
    (today ``<storage>/tool-data/<name>/``)."""
    from .config import settings

    if not name or any(c in name for c in "/\\") or name.startswith("."):
        raise ValueError(f"not a tool data folder name: {name!r}")
    d = settings.storage_path / "tool-data" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool_data_file(name: str, filename: str, legacy: str = "") -> Path:
    """``tool_data_dir(name) / filename``. ``legacy``: where the file used to be, relative to the server's data folder
    (e.g. ``"compounds.json"``); if it is there and the new file isn't, it is copied over once (and left in place)."""
    from .config import settings

    path = tool_data_dir(name) / filename
    if not path.exists():
        # where it was before: <data>/tool-data/ (when the storage folder is elsewhere), then the old place in <data>
        for old in (settings.data_path / "tool-data" / name / filename, settings.data_path / legacy if legacy else None):
            if old is not None and old != path and old.is_file():
                tmp = path.with_name(path.name + ".tmp")
                shutil.copy2(old, tmp)
                tmp.replace(path)
                break
    return path


def find_program(name: str, candidates: Iterable[str] = (), configured: str = "") -> str | None:
    """Where a program is on the server, or None. ``configured`` (a tool's setting, e.g. its "program" on Settings →
    Tools) wins, then a path in config.toml as ``<name>_path`` (e.g. ``blender_path``) — either must exist; else the
    first of ``candidates`` that exists; else the program on the PATH."""
    from .config import settings

    configured = str(configured or "").strip() or str(getattr(settings, f"{name}_path", "") or "")
    if configured:
        configured = str(Path(configured).expanduser())
        return configured if Path(configured).exists() else None
    for c in candidates:
        if Path(c).exists():
            return str(c)
    return shutil.which(name)
