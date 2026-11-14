"""Form inputs a tool can declare. The web UI renders them; values arrive parsed in ``p``.

Every input takes ``name`` (the key in ``p``), ``label``, ``default``, ``help`` (small hint
text) and ``show_if`` (only show it when other inputs have certain values, e.g.
``show_if={"mode": ["exact", "fit"]}`` or ``show_if={"advanced": True}``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar

from .errors import ToolError


@dataclass
class UploadedFile:
    id: str
    name: str
    path: Path
    size: int

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()

    @property
    def stem(self) -> str:
        return Path(self.name).stem

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.path.read_text(encoding=encoding, errors="replace")


@dataclass
class Input:
    name: str
    label: str = ""
    default: Any = None
    help: str = ""
    required: bool = True
    show_if: dict | None = None
    kind: ClassVar[str] = "input"

    def __post_init__(self):
        if not self.label:
            self.label = self.name.replace("_", " ").capitalize()

    def spec(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind
        return d

    def parse(self, raw: Any, resolve: Callable[[str], UploadedFile]) -> Any:
        return raw

    def _blank(self, raw: Any) -> bool:
        return raw is None or (isinstance(raw, str) and raw.strip() == "") or raw == []

    def _missing(self):
        if self.required:
            raise ToolError("required")
        return None


@dataclass
class Number(Input):
    min: float | None = None
    max: float | None = None
    step: float | str = "any"
    unit: str = ""
    placeholder: str = ""
    units: list = field(default_factory=list)  # e.g. ["M", "mM", "µM"]: adds a unit dropdown; p.<name>_unit holds the choice
    default_unit: str = ""
    kind: ClassVar[str] = "number"

    def __post_init__(self):
        super().__post_init__()
        if self.units and not self.default_unit:
            self.default_unit = self.units[0]

    def parse_unit(self, raw: Any) -> str:
        return raw if raw in self.units else self.default_unit

    def _convert(self, raw):
        return float(raw)

    def parse(self, raw, resolve):
        if self._blank(raw):
            return self._missing()
        try:
            v = self._convert(str(raw).strip().replace(",", ".") if isinstance(raw, str) else raw)
        except (TypeError, ValueError):
            raise ToolError(f"“{raw}” is not a number") from None
        if self.min is not None and v < self.min:
            raise ToolError(f"must be ≥ {self.min:g}")
        if self.max is not None and v > self.max:
            raise ToolError(f"must be ≤ {self.max:g}")
        return v


@dataclass
class Integer(Number):
    step: float | str = 1
    kind: ClassVar[str] = "integer"

    def _convert(self, raw):
        f = float(raw)
        if not f.is_integer():
            raise ValueError
        return int(f)


@dataclass
class Slider(Number):
    min: float | None = 0
    max: float | None = 100
    step: float | str = 1
    kind: ClassVar[str] = "slider"


@dataclass
class Text(Input):
    required: bool = False
    placeholder: str = ""
    kind: ClassVar[str] = "text"

    def parse(self, raw, resolve):
        if self._blank(raw):
            return self._missing() if self.required else ""
        return str(raw).strip()


@dataclass
class TextArea(Text):
    rows: int = 6
    monospace: bool = True
    kind: ClassVar[str] = "textarea"

    def parse(self, raw, resolve):
        if self._blank(raw):
            return self._missing() if self.required else ""
        return str(raw)


@dataclass
class Select(Input):
    options: Any = field(default_factory=list)  # ["a", "b"], [("value", "Label"), ...], or a function returning that
    sort: bool = False  # keep the options alphabetical (in the language shown); "custom" / "" values stay last
    kind: ClassVar[str] = "select"

    @staticmethod
    def _norm(opts) -> list:
        return [list(o) if isinstance(o, (tuple, list)) else [o, str(o)] for o in opts]

    def current(self) -> list:
        """The options right now — a function is called again on every page load (e.g. a list people add to)."""
        return self._norm(self.options() if callable(self.options) else self.options)

    def __post_init__(self):
        super().__post_init__()
        if not callable(self.options):
            self.options = self._norm(self.options)
            if self.default is None and self.options:
                self.default = self.options[0][0]

    def spec(self) -> dict:
        opts = self.current()
        d = {"kind": self.kind, "name": self.name, "label": self.label, "help": self.help, "required": self.required,
             "show_if": self.show_if, "options": opts, "default": self.default if self.default is not None else (opts[0][0] if opts else None),
             "sort": self.sort}
        return d

    def parse(self, raw, resolve):
        if self._blank(raw):
            return self._missing()
        for value, _ in self.current():
            if str(value) == str(raw):
                return value
        raise ToolError(f"“{raw}” is not one of the options")


@dataclass
class Button(Input):
    """A button in the form that runs ``action(raw_values) -> message`` on the server (e.g. "Save to list").

    Return a message to show; ``reload=True`` reloads the page afterwards so new options appear.
    """

    action: Any = None
    reload: bool = False
    required: bool = False
    kind: ClassVar[str] = "button"

    def spec(self) -> dict:
        return {"kind": self.kind, "name": self.name, "label": self.label, "help": self.help, "show_if": self.show_if}

    def parse(self, raw, resolve):
        return None


@dataclass
class Checkbox(Input):
    default: Any = False
    required: bool = False
    kind: ClassVar[str] = "checkbox"

    def parse(self, raw, resolve):
        if isinstance(raw, str):
            return raw.lower() in ("1", "true", "on", "yes")
        return bool(raw)


@dataclass
class File(Input):
    accept: str = ""  # e.g. ".csv,.xlsx" or "image/*"
    multiple: bool = False
    kind: ClassVar[str] = "file"

    def parse(self, raw, resolve):
        ids = raw if isinstance(raw, list) else ([] if self._blank(raw) else [raw])
        if not ids:
            return self._missing() if self.required else ([] if self.multiple else None)
        files = [resolve(i) for i in ids]
        allowed = [a.strip().lower() for a in self.accept.split(",") if a.strip().startswith(".")]
        if allowed:
            bad = [f.name for f in files if f.suffix not in allowed]
            if bad:
                raise ToolError(f"unsupported file type: {', '.join(bad)} (expected {self.accept})")
        return files if self.multiple else files[0]


@dataclass
class Column(Input):
    """A dropdown filled with the column names of a table uploaded in another File input."""

    source: str = ""  # name of the File input holding the table
    multiple: bool = False
    numeric: bool = False  # only offer numeric columns
    kind: ClassVar[str] = "column"

    def parse(self, raw, resolve):
        if self.multiple:
            vals = [v for v in (raw if isinstance(raw, list) else [raw]) if not self._blank(v)]
            return vals if vals else (self._missing() if self.required else [])
        if self._blank(raw):
            return self._missing()
        return str(raw)


@dataclass
class Section:
    """Visual divider that starts a new group of inputs."""

    title: str
    description: str = ""
    collapsed: bool = False
    show_if: dict | None = None

    def spec(self) -> dict:
        return {"kind": "section", **asdict(self)}


def col(key: str, label: str = "", kind: str = "text", options: list | None = None, width: int | None = None,
        help: str = "", default=None) -> dict:
    """A column of a SampleTable. kind: text | number | select | checkbox | readonly | image."""
    opts = [list(o) if isinstance(o, (tuple, list)) else [o, str(o)] for o in (options or [])]
    return {"key": key, "label": label or key.replace("_", " ").capitalize(), "kind": kind, "options": opts,
            "width": width, "help": help, "default": default}


@dataclass
class SampleTable(Input):
    """An editable table with one row per uploaded file (or per sample found in the files).

    The tool fills it with ``@tool.suggest("<name>")``: a function receiving the uploaded files
    (and the other form values) and returning one dict per row, each with a unique ``"key"``.
    People then fix names, replicates, roles… before running. ``p.<name>`` is the list of rows.
    ``refresh_on`` names other inputs whose change re-runs the suggester and replaces the rows.
    """

    source: str = ""  # the File input whose uploads fill the table
    refresh_on: tuple = ()  # inputs that change how the files are read (their change resets the table)
    columns: list = field(default_factory=list)  # made with col(...)
    kind: ClassVar[str] = "samples"

    def parse(self, raw, resolve):
        rows = raw if isinstance(raw, list) else []
        if not rows:
            return self._missing() if self.required else []
        kinds = {c["key"]: c["kind"] for c in self.columns}
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            row = dict(r)
            for k, kind in kinds.items():
                v = row.get(k)
                if kind == "number":
                    try:
                        row[k] = None if v in (None, "") else float(str(v).replace(",", "."))
                    except ValueError:
                        raise ToolError(f"“{v}” in column {k} is not a number") from None
                elif kind == "checkbox":
                    row[k] = v in (True, "true", "on", 1, "1")
                elif kind in ("text", "select") and v is not None:
                    row[k] = str(v).strip()
            out.append(row)
        return out


@dataclass
class PlateLayout(Input):
    """A clickable microplate: mark wells as blank / standard (with a concentration) / sample (name, dilution).

    If ``source`` names a File input and the tool has ``@tool.suggest("<name>")`` returning
    ``{"values": {"A1": 0.32, ...}}``, the measured values are shown in the wells.
    ``p.<name>`` is a dict ``{"A1": {"role": "standard", "value": 2.0}, "B3": {"role": "sample", "name": "WT", "dilution": 2}}``.
    """

    source: str = ""
    rows: int = 8
    cols: int = 12
    unit: str = "µg/mL"
    kind: ClassVar[str] = "plate"

    def parse(self, raw, resolve):
        wells = raw if isinstance(raw, dict) else {}
        clean = {}
        for well, info in wells.items():
            if not isinstance(info, dict) or info.get("role") in (None, "", "empty"):
                continue
            role = info["role"]
            if role not in ("blank", "standard", "sample"):
                raise ToolError(f"unknown role {role!r} in well {well}")
            item = {"role": role}
            if role == "standard":
                try:
                    item["value"] = float(info.get("value"))
                except (TypeError, ValueError):
                    raise ToolError(f"standard well {well} has no concentration") from None
            if role == "sample":
                item["name"] = str(info.get("name") or "").strip() or "sample"
                try:
                    item["dilution"] = float(info.get("dilution") or 1)
                except (TypeError, ValueError):
                    item["dilution"] = 1.0
            clean[well.upper()] = item
        if not clean and self.required:
            raise ToolError("mark the blank, standard and sample wells on the plate")
        return clean


@dataclass
class ImageSpots(Input):
    """Circles placed on a picture: areas to measure, each with a label and a sample name (toolkit 1.3).

    The tool shows the picture and suggests the circles with ``@tool.suggest("<name>")``: a function receiving the
    uploads of ``source`` (and the other form values) and returning ``{"image": data_url, "width": w, "height": h,
    "spots": [{"id": "A1", "x": 120, "y": 80, "r": 15, "sample": "WT", "group": "left"}, ...]}`` — ``x``, ``y``, ``r``
    in the picture's pixels, ``group`` optional (e.g. which cassette). Instead of ``image`` it may return
    ``"images": [{"label": "Fm", "src": data_url}, ...]`` to offer several backgrounds, and ``"note"`` (a line shown
    under the picture). Circles with a ``row`` (A, B…) and a ``col`` (1, 2…) are wells of a grid: with
    ``"grids": [{"group": "left", "title": "Left chamber", "rows": 5, "cols": 3}, ...]`` they are also shown as plates
    beside the picture and named like a plate layout. People then move, resize, add, remove and name the circles.
    ``p.<name>`` is the list of spots (dicts with ``id``, ``x``, ``y``, ``r``, ``sample``, ``group``, and ``row`` and
    ``col`` for wells). ``refresh_on`` names inputs whose change asks the suggester again (and replaces the circles);
    new uploads in ``source`` do that too.
    """

    source: str = ""
    refresh_on: tuple = ()
    radius: float = 15  # a new circle's radius (picture pixels)
    kind: ClassVar[str] = "spots"

    def parse(self, raw, resolve):
        spots = raw.get("spots") if isinstance(raw, dict) else raw
        out, seen = [], set()
        for s in spots if isinstance(spots, list) else []:
            if not isinstance(s, dict):
                continue
            try:
                x, y, r = (float(s.get(k)) for k in ("x", "y", "r"))
            except (TypeError, ValueError):
                raise ToolError(f"circle {s.get('id', '?')} has no position or size") from None
            if not (r > 0) or x != x or y != y:
                raise ToolError(f"circle {s.get('id', '?')} has no size")
            sid = str(s.get("id") or "").strip() or str(len(out) + 1)
            if sid in seen:
                raise ToolError(f"two circles are called {sid}")
            seen.add(sid)
            spot = {"id": sid, "x": x, "y": y, "r": r, "sample": str(s.get("sample") or "").strip() or sid,
                    "group": str(s.get("group") or "").strip()}
            if s.get("row") and s.get("col"):  # a well of a grid (shown as a plate for naming)
                try:
                    spot.update(row=str(s["row"]).strip(), col=int(s["col"]))
                except (TypeError, ValueError):
                    pass
            out.append(spot)
        if not out and self.required:
            raise ToolError("place at least one circle on the picture")
        return out
