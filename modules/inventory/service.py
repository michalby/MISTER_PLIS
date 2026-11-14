"""Reagent inventory: the lab's chemicals, where they are, and what needs to be ordered.

It is its own space (like Time Machine). The data is the lab's inventory repository on GitHub
(``repo``: set on its Settings tab, by the lab's setup or in ``[module.inventory]`` of config.toml), kept in ``<data>/modules/inventory/repo``. Its master
copy is one Excel workbook, described in that repository's AGENTS.md:

    wykaz_odczynnikow_kompletny.xlsx   sheet `reagents`: one row per reagent, key `label_no`;
                                       sheet `columns`: column | type | values | label_pl | label_en | group | description_pl;
                                       sheet `storage_categories`: code | color_hex | name | …
    wykaz_odczynnikow_kompletny.csv    an exact copy of the `reagents` sheet, rewritten with every change
    mister_plis.json                   how it is shown here (title column, quick filters, list columns)
    info/<when>-<id>.json              info from the lab: remarks and transcripts, for correcting the records later

Every change made here is one commit by whoever made it. **Sync** merges GitHub's changes in; two edits of the
workbook are merged cell by cell (by ``label_no`` and column), and only the same cell changed differently on both
sides stops the sync. Pushing back can be turned off. Nothing is ever forced.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from pathlib import Path

from mister_plis import gitutil
from mister_plis.errors import ToolError
from mister_plis.serving import safe_link
from mister_plis.text import fold

EMAIL = "reagents@mister-plis.local"
MAX_INFO = 60000
N_SLOTS = 5
RESTOCK = ("", "needed", "ordered")
CONFIG_FILE = "mister_plis.json"
STORED = ("repo", "branch", "calculator", "ollama_url")  # lab-wide choices kept in settings.json (config.toml wins)
DEFAULT_CONFIG = {
    "workbook": "wykaz_odczynnikow_kompletny.xlsx", "sheet": "reagents", "csv": "wykaz_odczynnikow_kompletny.csv",
    "key": "label_no", "title": {"pl": "name_pl", "en": "name_en"},
    "quick": ["_to_order", "storage_category_primary", "is_borrowed"],
    "list": ["label_no", "_title", "storage_category_primary", "storage_exact_location", "_producers"],
    "hidden": ["name_pl_original", "name_en_original"],
    # the printed list (Inventory → PDF): which columns ("list": those shown on screen; "chosen": `columns`),
    # whether the filters are named at the top, and the type size ("normal", or "large" to read from a step away)
    "pdf": {"source": "list", "columns": ["label_no", "_title", "storage_exact_location", "_producers"], "filters": True, "size": "normal"},
}
PDF_SOURCES, PDF_SIZES = ("list", "chosen"), ("normal", "large")
TYPE_MAP = {"text": "text", "integer": "number", "number": "number", "boolean": "bool", "date": "date", "enum": "choice", "list": "multi"}
SLOT = re.compile(r"^producer_(\d+)_(\w+)$")
GHS = re.compile(r"^ghs0\d_")


def _nfc(s) -> str:
    return unicodedata.normalize("NFC", str(s if s is not None else ""))


def _line(s, limit: int) -> str:
    return " ".join(_nfc(s).split())[:limit]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _replace(tmp: Path, target: Path) -> None:
    """Move a freshly written file into place, keeping the file's mode (so git sees no mode change)."""
    try:
        os.chmod(tmp, target.stat().st_mode & 0o777)
    except OSError:
        pass
    tmp.replace(target)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def plain(v):
    """A cell value as JSON: dates as yyyy-mm-dd, whole floats as they are."""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str) and not v.strip():
        return None
    return v


def csv_value(v) -> str:
    """Exactly as the repository's scripts/export_csv.py writes it."""
    v = plain(v)
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def key_str(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip() if v is not None else ""


# ---- the workbook ---------------------------------------------------------------------------------

class Book:
    """One version of the workbook, read: its columns (from the `columns` sheet), rows and storage categories."""

    def __init__(self, data: bytes, sheet: str = "reagents", key: str = "label_no"):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        if sheet not in wb.sheetnames:
            raise ToolError(f"The workbook has no sheet “{sheet}”.")
        rows = wb[sheet].iter_rows(values_only=True)
        self.header = [h for h in next(rows, []) if h is not None]
        if key not in self.header:
            raise ToolError(f"The sheet “{sheet}” has no column “{key}”.")
        ki = self.header.index(key)
        self.rows: list[dict] = []
        for r in rows:
            r = list(r)[:len(self.header)] + [None] * max(0, len(self.header) - len(r))
            if key_str(r[ki]) == "":
                continue
            self.rows.append({h: plain(v) for h, v in zip(self.header, r)})
        self.key = key
        meta: dict[str, dict] = {}
        if "columns" in wb.sheetnames:
            it = wb["columns"].iter_rows(values_only=True)
            head = [str(h or "") for h in next(it, [])]
            for r in it:
                d = dict(zip(head, r))
                c = d.get("column")
                if c in self.header:
                    meta[c] = d
        self.columns = [self._column(h, meta.get(h, {})) for h in self.header]
        self.categories = []
        if "storage_categories" in wb.sheetnames:
            it = wb["storage_categories"].iter_rows(values_only=True)
            head = [str(h or "") for h in next(it, [])]
            self.categories = [{k: plain(v) for k, v in zip(head, r)} for r in it if r and r[0]]
        wb.close()

    @staticmethod
    def _column(h: str, m: dict) -> dict:
        typ = TYPE_MAP.get(str(m.get("type") or "text"), "text")
        if typ == "text" and (h.endswith(("_notes", "_findings", "_note")) or h in ("supplier_storage_source",)):
            typ = "longtext"
        if typ == "text" and h.endswith("_url"):
            typ = "url"
        f = {"key": h, "type": typ, "label": _line(m.get("label_en") or h, 80), "label_pl": _line(m.get("label_pl") or m.get("label_en") or h, 80),
             "group": _line(m.get("group") or "other", 40), "help": _line(m.get("description_pl"), 300)}
        if str(m.get("type")) == "integer":
            f["integer"] = True
        vals = [_line(v, 80) for v in str(m.get("values") or "").split(";") if _line(v, 80)]
        if vals:
            f["options"] = vals
        s = SLOT.match(h)
        if s:
            f["slot"], f["slot_key"] = int(s.group(1)), s.group(2)
        return f

    def by_key(self) -> dict[str, dict]:
        return {key_str(r[self.key]): r for r in self.rows}


def version(row: dict) -> str:
    return hashlib.sha1(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


def convert(f: dict, v):
    """A value from the edit view as it is kept in the workbook (None = empty = unknown)."""
    t = f["type"]
    if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
        return None
    if t == "bool":
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "1", "yes", "tak"):
            return True
        if s in ("false", "0", "no", "nie"):
            return False
        raise ToolError(f"“{f['label']}” is yes or no.")
    if t == "number":
        s = str(v).strip().replace(",", ".").replace(" ", "")
        try:
            n = float(s)
        except ValueError:
            raise ToolError(f"“{f['label']}” must be a number (got “{v}”).")
        if f.get("integer"):
            if not n.is_integer():
                raise ToolError(f"“{f['label']}” must be a whole number (got “{v}”).")
            return int(n)
        return int(n) if n.is_integer() and "." not in s else n
    if t == "date":
        s = _line(v, 40)
        m = re.match(r"^(\d{4})[-./](\d{1,2})(?:[-./](\d{1,2}))?$", s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}" + (f"-{int(m.group(3)):02d}" if m.group(3) else "")
        m = re.match(r"^(\d{1,2})[-./](\d{1,2})[-./](\d{4})$", s)
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        raise ToolError(f"“{f['label']}”: write the date as yyyy-mm-dd (got “{v}”).")
    if t == "multi":
        items = v if isinstance(v, list) else re.split(r"[;,\n]", str(v))
        items = list(dict.fromkeys(_line(i, 120) for i in items if _line(i, 120)))
        bad = [i for i in items if f.get("options") and i not in f["options"]]
        if bad:
            raise ToolError(f"“{f['label']}”: “{bad[0]}” is not one of {', '.join(f['options'])}.")
        return ";".join(items) or None
    if t == "choice":
        s = _line(v, 300)
        if f.get("options") and s not in f["options"]:
            raise ToolError(f"“{f['label']}”: “{s}” is not one of {', '.join(f['options'])}.")
        return s
    if t == "longtext":
        return _nfc(v).strip()[:20000]
    if t == "url":  # a link someone clicks must not run anything in the page ("javascript:…")
        s = _line(v, 1000)
        if not safe_link(s, ("http", "https")):
            raise ToolError(f"“{f['label']}”: a link starts with http:// or https:// (got “{s[:60]}”).")
        return s
    return _line(v, 1000)


class Inventory:
    """The reagents' workbook, and the repository it lives in (git, GitHub sync, info from the lab). The
    consumables (``Consumables`` below) are a second workbook in the same repository, sharing all of that."""

    CONFIG_FILE = CONFIG_FILE
    DEFAULT_CONFIG = DEFAULT_CONFIG
    TRAILER = "Reagent"        # commit trailer naming the row ("Reagent: 12"), for its history
    INFO_FIELD = "reagent"     # the field of a note from the lab that names the row it is about
    PRODUCERS = ("Producers", "Producenci")
    MISSING = "There is no such reagent — it may have been deleted."
    CHANGED = "Someone changed this reagent while you were editing it. Open it again to see their change, then edit it."
    NEEDS_NAME = "A reagent needs a name."
    SHOWN = "Change how the reagents are shown"

    def __init__(self, data_path: Path, url: str = "", branch: str = "main", root: Path | None = None):
        self.main: Inventory = self   # the one that owns the repository: syncs, pushes, keeps the settings
        self.others: list[Inventory] = []
        self.root = root or data_path / "reagents"  # as a module: <data>/modules/inventory
        self.repo = self.root / "repo"
        self.settings_file = self.root / "settings.json"
        self.url = gitutil.address(url)  # GitHub, or a git repository in a folder on this machine
        self.branch = (branch or "").strip() or "main"
        self.lock = threading.RLock()
        self.last_error = ""
        self._book: tuple[float, Book] | None = None
        self._push_timer: threading.Timer | None = None
        self.env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(k, None)

    # ---- settings (not in the repository) --------------------------------------------
    def settings(self) -> dict:
        d = _read_json(self.settings_file)
        d = d if isinstance(d, dict) else {}
        return {"push": bool(d.get("push", True)), "auto_minutes": int(d.get("auto_minutes", 15) or 0),
                "synced_at": d.get("synced_at"), "pushed_at": d.get("pushed_at")}

    def save_settings(self, **changes) -> dict:
        d = _read_json(self.settings_file)
        d = d if isinstance(d, dict) else {}
        if "push" in changes:
            d["push"] = bool(changes["push"])
        if "auto_minutes" in changes:
            m = int(changes["auto_minutes"] or 0)
            if m not in (0, 15, 60, 240):
                raise ToolError("Sync every 15 min, 1 h, 4 h, or only by hand.")
            d["auto_minutes"] = m
        for k in ("synced_at", "pushed_at", *STORED):
            if k in changes:
                d[k] = changes[k]
        _write_json(self.settings_file, d)
        return self.settings()

    def start_workbook(self, user: str = "") -> bool:
        """Start an empty reagents workbook (a new lab), when there is none: on an inventory kept on this server only,
        or once a sync has shown the repository has none — never before, so a repository's own workbook isn't
        shadowed. The consumables' workbook follows by itself."""
        if self.main is not self or self.xlsx.exists() or (self.repo / ".git" / "MERGE_HEAD").exists():
            return False
        if self.url and not self.settings()["synced_at"]:
            raise ToolError("Sync with the repository first: it may have the lab's workbook already.")
        with self.lock:
            self.ensure()
            if self.xlsx.exists():
                return False
            tmp = self.xlsx.with_name("." + self.xlsx.name + ".tmp")
            tmp.write_bytes(new_reagents_workbook())
            tmp.replace(self.xlsx)
            wb, ws, header = self._open()
            self._write_csv(ws, header, 1)
            self.commit("Start the reagents inventory", user or "MISTER PLIS", ["Action: add"])
        return True

    def stored(self) -> dict:
        """The lab-wide choices kept with the settings (set on the Settings tab or by a lab file): repo, branch,
        calculator, ollama_url. config.toml wins over them (the module's __init__.py)."""
        d = _read_json(self.settings_file)
        return {k: d[k] for k in STORED if isinstance(d, dict) and isinstance(d.get(k), str)}

    def set_repository(self, url: str, branch: str = "main") -> dict:
        """Use another repository (or none: ""), at once. What was synced from the old one is kept, never mixed into
        the new one: its copy is renamed ``repo.before-<date>`` and the new repository comes in at the next sync. That
        is refused while changes made here haven't reached the old repository yet (sync first). A copy that was never
        synced (or had no repository) stays, and goes to the new repository at the next sync."""
        if self.main is not self:
            return self.main.set_repository(url, branch)
        url = gitutil.address(gitutil.check_address(url))
        branch = gitutil.check_branch(branch)
        with self.lock:
            if (url, branch) == (self.url, self.branch):
                self.save_settings(repo=url, branch=branch)
                return {"changed": False, "kept": ""}
            kept = ""
            if self.url and self.has_commits() and self.git("rev-parse", "--verify", "-q", self.remote_ref)[0] == 0:
                ahead = self.git("rev-list", "--count", f"{self.remote_ref}..HEAD")[1].strip()
                if ahead not in ("", "0"):
                    raise ToolError(f"{ahead} change(s) made here haven't reached the current repository yet. Sync first "
                                    "(with sending turned on), then change the repository.")
                if self._push_timer:
                    self._push_timer.cancel()
                kept = str(gitutil.set_aside(self.repo))
            self.url, self.branch = url, branch
            for o in self.others:
                o.url, o.branch = url, branch
            for c in self.catalogues():
                c._book = None
            self.last_error = ""
            self.save_settings(repo=url, branch=branch, synced_at=None, pushed_at=None)
        return {"changed": True, "kept": kept}

    # ---- git ----------------------------------------------------------------------------
    def git(self, *args: str, timeout: float = 120, network: bool = False, binary: bool = False):
        from mister_plis import gitutil

        # network: with the code repository's token (one token for every repository)
        return gitutil.run(*args, cwd=self.repo, timeout=timeout, credentials=network, binary=binary)

    def ensure(self) -> bool:
        if (self.repo / ".git").is_dir():
            return True
        self.repo.mkdir(parents=True, exist_ok=True)
        code, _ = self.git("init", "-q", "-b", self.branch)
        if code != 0:
            code, _ = self.git("init", "-q")
        info = self.repo / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "exclude").write_text(".*.tmp\n~$*\n", encoding="utf-8")
        return code == 0

    def has_commits(self) -> bool:
        return (self.repo / ".git").is_dir() and self.git("rev-parse", "--verify", "-q", "HEAD")[0] == 0

    def commit(self, subject: str, author: str = "", trailers: list[str] | None = None) -> str | None:
        self.ensure()
        self.git("add", "-A")
        if self.git("diff", "--cached", "--quiet")[0] == 0 and self.has_commits():
            return None
        msg = subject + ("\n\n" + "\n".join(trailers) if trailers else "")
        who = _line(author, 60) or "Someone without a name"
        code, out = self.git("-c", f"user.name={who}", "-c", f"user.email={EMAIL}", "commit", "-q", "-m", msg)
        if code != 0:
            raise ToolError("Couldn't save the change in the reagents' history:\n" + out)
        self._push_soon()
        return self.git("rev-parse", "HEAD")[1].strip()

    def _push_soon(self) -> None:
        """After a change: send it to GitHub shortly (several quick edits go together)."""
        if self.main is not self:
            return self.main._push_soon()
        if not self.url or not self.settings()["push"]:
            return
        if self._push_timer:
            self._push_timer.cancel()
        self._push_timer = threading.Timer(20, self._background_sync)
        self._push_timer.daemon = True
        self._push_timer.start()

    def _background_sync(self) -> None:  # pragma: no cover - a background thread
        try:
            self.sync("MISTER PLIS")
        except Exception as e:
            self.last_error = str(e)

    # ---- configuration and the workbook ------------------------------------------------------
    def config(self) -> dict:
        c = _read_json(self.repo / self.CONFIG_FILE)
        c = c if isinstance(c, dict) else {}
        out = {**self.DEFAULT_CONFIG, **{k: v for k, v in c.items() if k in self.DEFAULT_CONFIG}}
        for k in ("workbook", "csv"):
            p = str(out[k])
            if "/" in p or "\\" in p or p.startswith("."):
                out[k] = self.DEFAULT_CONFIG[k]
        return out

    def pdf_config(self) -> dict:
        """What goes on the printed list, with the defaults for anything missing or unknown."""
        d, base = self.config().get("pdf"), self.DEFAULT_CONFIG["pdf"]
        d = d if isinstance(d, dict) else {}
        cols = d.get("columns")
        return {"source": d.get("source") if d.get("source") in PDF_SOURCES else base["source"],
                "columns": [str(c) for c in cols] if isinstance(cols, list) else list(base["columns"]),
                "filters": bool(d.get("filters", base["filters"])),
                "size": d.get("size") if d.get("size") in PDF_SIZES else base["size"]}

    def catalogues(self) -> list[Inventory]:
        """Every workbook kept in this repository: the reagents first, then the others (consumables)."""
        return [self.main, *self.main.others]

    @property
    def xlsx(self) -> Path:
        return self.repo / self.config()["workbook"]

    def book(self) -> Book | None:
        p = self.xlsx
        try:
            stamp = p.stat().st_mtime_ns
        except OSError:
            return None
        if self._book and self._book[0] == stamp:
            return self._book[1]
        cfg = self.config()
        b = Book(p.read_bytes(), cfg["sheet"], cfg["key"])
        self._book = (stamp, b)
        return b

    def _need_book(self) -> Book:
        b = self.book()
        if b is None:
            raise ToolError("The inventory isn't here yet. Sync with GitHub first (Settings → Reagents & consumables).")
        return b

    def fields(self, lang: str = "en") -> list[dict]:
        b = self.book()
        if b is None:
            return []
        hidden = set(self.config()["hidden"])
        out = [dict(f, hidden=True) if f["key"] in hidden else dict(f) for f in b.columns]
        out.insert(0, {"key": "_title", "type": "text", "label": "Name", "label_pl": "Nazwa", "group": "identification", "virtual": True})
        ghs = [f for f in out if GHS.match(f["key"]) and f["type"] == "bool"]
        prods = sorted({r.get(f"producer_{i}_name") for r in b.rows for i in range(1, N_SLOTS + 1)} - {None, ""}, key=fold)
        out.append({"key": "_producers", "type": "multi", "label": self.PRODUCERS[0], "label_pl": self.PRODUCERS[1], "group": "producers",
                    "virtual": True, "options": prods})
        if ghs:
            out.append({"key": "_ghs", "type": "multi", "label": "GHS pictograms", "label_pl": "Piktogramy GHS", "group": "hazards",
                        "virtual": True, "options": [g["label_pl"] if lang == "pl" else g["label"] for g in ghs]})
        return out

    def _item(self, r: dict, lang: str, ghs: list[dict]) -> dict:
        cfg = self.config()
        d = dict(r)
        d["id"] = key_str(r[cfg["key"]])
        t = cfg["title"]
        d["_title"] = _line(r.get(t.get(lang) or t.get("pl")) or r.get(t.get("pl")) or r.get("name_pl") or d["id"], 300)
        d["_producers"] = [r[f"producer_{i}_name"] for i in range(1, N_SLOTS + 1) if r.get(f"producer_{i}_name")]
        d["_ghs"] = [(g["label_pl"] if lang == "pl" else g["label"]) for g in ghs if r.get(g["key"]) is True]
        slots = [i for i in range(1, N_SLOTS + 1) if r.get(f"producer_{i}_to_order") or r.get(f"producer_{i}_ordered")]
        needed = any(r.get(f"producer_{i}_to_order") and not r.get(f"producer_{i}_ordered") for i in slots)
        d["restock"] = "needed" if needed else ("ordered" if slots else "")
        d["_v"] = version(r)
        return d

    def items(self, lang: str = "en") -> list[dict]:
        b = self.book()
        if b is None:
            return []
        ghs = [f for f in b.columns if GHS.match(f["key"]) and f["type"] == "bool"]
        return [self._item(r, lang, ghs) for r in b.rows]

    def get(self, rid: str, lang: str = "en") -> dict:
        b = self._need_book()
        r = b.by_key().get(str(rid))
        if r is None:
            raise ToolError(self.MISSING)
        return self._item(r, lang, [f for f in b.columns if GHS.match(f["key"]) and f["type"] == "bool"])

    def categories(self) -> list[dict]:
        b = self.book()
        return b.categories if b else []

    # ---- writing the workbook -----------------------------------------------------------------
    def _open(self):
        from openpyxl import load_workbook

        wb = load_workbook(self.xlsx)
        ws = wb[self.config()["sheet"]]
        header = [c.value for c in ws[1]]
        while header and header[-1] is None:
            header.pop()
        return wb, ws, header

    def _find_row(self, ws, header: list, rid: str) -> int | None:
        ki = header.index(self.config()["key"]) + 1
        for r in range(2, ws.max_row + 1):
            if key_str(ws.cell(row=r, column=ki).value) == str(rid):
                return r
        return None

    def _last_row(self, ws, header: list) -> int:
        ki = header.index(self.config()["key"]) + 1
        last = 1
        for r in range(2, ws.max_row + 1):
            if ws.cell(row=r, column=ki).value not in (None, ""):
                last = r
        return last

    def _set(self, ws, row: int, col: int, value, key: str = "") -> None:
        from openpyxl.styles import Font, PatternFill

        cell = ws.cell(row=row, column=col)
        cell.value = value
        if key == "storage_category_primary":  # the colour of the category, as the workbook has it
            colors = {c.get("code"): str(c.get("color_hex") or "").lstrip("#") for c in self.categories()}
            col_hex = colors.get(value)
            if col_hex and re.fullmatch(r"[0-9A-Fa-f]{6}", col_hex):
                cell.fill = PatternFill("solid", fgColor=col_hex)
                r_, g_, b_ = (int(col_hex[i:i + 2], 16) for i in (0, 2, 4))
                cell.font = Font(bold=True, color="FFFFFF" if 0.299 * r_ + 0.587 * g_ + 0.114 * b_ < 140 else "000000")
            else:
                cell.fill = PatternFill(fill_type=None)

    def _save(self, wb, ws, header: list) -> None:
        last = self._last_row(ws, header)
        for t in ws.tables.values():  # the Excel table covers every reagent
            first, _, end = t.ref.partition(":")
            if end:
                col = re.match(r"[A-Z]+", end).group(0)
                t.ref = f"{first}:{col}{max(last, 2)}"
        tmp = self.xlsx.with_name("." + self.xlsx.name + ".tmp")
        wb.save(tmp)
        _replace(tmp, self.xlsx)
        self._write_csv(ws, header, last)
        self._book = None

    def _write_csv(self, ws, header: list, last: int) -> None:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(header)
        for r in ws.iter_rows(min_row=2, max_row=last, max_col=len(header), values_only=True):
            if r[header.index(self.config()["key"])] in (None, ""):
                continue
            w.writerow([csv_value(v) for v in r])
        p = self.repo / self.config()["csv"]
        tmp = p.with_name("." + p.name + ".tmp")
        tmp.write_text(buf.getvalue(), encoding="utf-8", newline="")
        _replace(tmp, p)

    def _fields_by_key(self) -> dict[str, dict]:
        return {f["key"]: f for f in self._need_book().columns}

    def save(self, values: dict, user: str = "", rid: str = "", base: str = "", commit: bool = True) -> dict:
        """Add (no id) or change a reagent. ``base`` is the version the edit view started from: if someone changed
        the reagent in the meantime, the save is refused instead of quietly overwriting their change. With
        ``commit=False`` the caller (holding ``self.lock``) commits several changes together."""
        fdef = self._fields_by_key()
        key = self.config()["key"]
        with self.lock:
            book = self._need_book()
            rows = book.by_key()
            old = rows.get(str(rid)) if rid else None
            if rid and old is None:
                raise ToolError(self.MISSING)
            if old is not None and base and version(old) != base:
                raise ToolError(self.CHANGED)
            new = {}
            for k, v in values.items():
                if k in fdef and k != key:
                    new[k] = convert(fdef[k], v)
            # a producer newly marked "to order": who asked, and when (unless given)
            asked = any(new.get(f"producer_{i}_to_order") is True and not (old or {}).get(f"producer_{i}_to_order")
                        for i in range(1, N_SLOTS + 1))
            if asked and "order_requested_by" in fdef and not (values.get("order_requested_by") or "").strip():
                new["order_requested_by"] = _line(user, 60) or None
                if "order_requested_date" in fdef:
                    new["order_requested_date"] = dt.date.today().isoformat()
            title = self.config()["title"].get("pl") or "name_pl"
            name = new.get(title, (old or {}).get(title))
            if not _line(name, 300):
                raise ToolError(self.NEEDS_NAME)
            wb, ws, header = self._open()
            if old is None:
                nums = [int(k) for k in rows if k.isdigit()]
                rid = str(max(nums, default=0) + 1)
                row = self._last_row(ws, header) + 1
                ws.cell(row=row, column=header.index(key) + 1).value = int(rid)
                if "is_disposed" in header:
                    new.setdefault("is_disposed", False)
                for c in range(1, len(header) + 1):  # look like the row above
                    above = ws.cell(row=row - 1, column=c)
                    if above.has_style and row > 2:
                        ws.cell(row=row, column=c).alignment = above.alignment.copy()
                changed = [k for k, v in new.items() if v is not None]
            else:
                row = self._find_row(ws, header, rid)
                changed = [k for k, v in new.items() if v != old.get(k)]
            for k in changed:
                if k in header:
                    self._set(ws, row, header.index(k) + 1, new[k], k)
            if not changed and old is not None:
                return self.get(rid)
            self._save(wb, ws, header)
            what = ", ".join(changed[:6]) + ("…" if len(changed) > 6 else "")
            subject = (f"Add {key} {rid} {_line(name, 60)}" if old is None
                       else f"{key} {rid} {_line(name, 60)}: {what}")
            if commit:
                self.commit(subject, user, [f"{self.TRAILER}: {rid}", f"Action: {'add' if old is None else 'edit'}"])
        return self.get(rid)

    def set_restock(self, rid: str, slot: int, state: str, user: str = "", amount: str | None = None,
                    count=None, note: str | None = None) -> dict:
        """From the order list, for one producer: to order → ordered → arrived (both cleared)."""
        if state not in RESTOCK:
            raise ToolError("Unknown order state.")
        if not 1 <= int(slot) <= N_SLOTS:
            raise ToolError("Unknown producer.")
        p = f"producer_{int(slot)}_"
        vals: dict = {f"{p}to_order": state == "needed" or state == "ordered", f"{p}ordered": state == "ordered"}
        if state == "":
            vals.update({f"{p}to_order": False, f"{p}ordered": False, f"{p}order_amount": None})
            if count is not None and str(count).strip() != "":
                vals[f"{p}containers_count"] = count
        if amount is not None:
            vals[f"{p}order_amount"] = amount
        if state == "needed":
            vals.update({"order_requested_by": _line(user, 60), "order_requested_date": dt.date.today().isoformat()})
        if note is not None:
            vals["order_note"] = note
        fdef = self._fields_by_key()
        vals = {k: v for k, v in vals.items() if k in fdef}
        if f"{p}to_order" not in vals:
            raise ToolError("This inventory has no ordering columns for that producer.")
        return self.save(vals, user, rid)

    def dispose(self, rid: str, user: str = "", undo: bool = False) -> dict:
        fdef = self._fields_by_key()
        if "is_disposed" not in fdef:
            raise ToolError("This inventory has no column is_disposed.")
        vals = {"is_disposed": not undo}
        if "disposed_date" in fdef:
            vals["disposed_date"] = None if undo else dt.date.today().isoformat()
        return self.save(vals, user, rid)

    def set_columns(self, changes: list, display: dict, user: str = "") -> None:
        """Rename columns on screen (label_pl / label_en in the `columns` sheet) and choose the quick filters, the
        list columns and what goes on the printed list (mister_plis.json)."""
        b = self._need_book()
        known = {f["key"] for f in self.fields()}
        with self.lock:
            touched = []
            if changes:
                from openpyxl import load_workbook

                wb = load_workbook(self.xlsx)
                if "columns" not in wb.sheetnames:
                    raise ToolError("The workbook has no sheet “columns”.")
                cs = wb["columns"]
                head = [c.value for c in cs[1]]
                for name in ("label_pl", "label_en"):
                    if name not in head:
                        head.append(name)
                        cs.cell(row=1, column=len(head)).value = name
                rows = {cs.cell(row=r, column=head.index("column") + 1).value: r for r in range(2, cs.max_row + 1)}
                for ch in changes:
                    k = ch.get("key")
                    if k not in b.header:
                        continue
                    r = rows.get(k)
                    if r is None:
                        r = cs.max_row + 1
                        cs.cell(row=r, column=head.index("column") + 1).value = k
                    for name in ("label_pl", "label_en"):
                        v = _line(ch.get(name), 80)
                        if v and cs.cell(row=r, column=head.index(name) + 1).value != v:
                            cs.cell(row=r, column=head.index(name) + 1).value = v
                            touched.append(k)
                if touched:
                    tmp = self.xlsx.with_name("." + self.xlsx.name + ".tmp")
                    wb.save(tmp)
                    _replace(tmp, self.xlsx)
                    self._book = None
            if display:
                cfg = {**(_read_json(self.repo / self.CONFIG_FILE) or {})}
                for k in ("quick", "list", "hidden"):
                    if isinstance(display.get(k), list):
                        cfg[k] = [x for x in dict.fromkeys(display[k]) if x in known or x == "_to_order"]
                if isinstance(display.get("pdf"), dict):
                    new, old = display["pdf"], self.pdf_config()
                    cols = new.get("columns")
                    cfg["pdf"] = {"source": new["source"] if new.get("source") in PDF_SOURCES else old["source"],
                                  "columns": [x for x in dict.fromkeys(cols) if x in known] if isinstance(cols, list) else old["columns"],
                                  "filters": bool(new.get("filters", old["filters"])),
                                  "size": new["size"] if new.get("size") in PDF_SIZES else old["size"]}
                cfg = {**{k: v for k, v in self.DEFAULT_CONFIG.items() if k not in cfg}, **cfg}
                _write_json(self.repo / self.CONFIG_FILE, cfg)
            self.commit(self.SHOWN, user, ["Action: fields"])

    def history(self, rid: str = "", limit: int = 100) -> list[dict]:
        if not self.has_commits():
            return []
        args = ["log", f"-n{max(1, min(limit, 1000))}", "--format=%H%x1f%an%x1f%at%x1f%s%x1e"]
        if rid:
            if not re.fullmatch(r"[\w-]{1,40}", rid):
                return []
            args += ["-E", f"--grep=^{self.TRAILER}: {re.escape(rid)}$"]
        code, out = self.git(*args)
        commits = []
        for raw in out.split("\x1e") if code == 0 else []:
            parts = raw.strip("\n").split("\x1f")
            if len(parts) == 4:
                commits.append({"id": parts[0], "short": parts[0][:7], "author": parts[1], "at": int(parts[2]), "subject": parts[3]})
        return commits

    # ---- info from the lab ------------------------------------------------------------
    def _info_dir(self) -> Path:
        return self.repo / "info"

    def infos(self, rid: str = "") -> list[dict]:
        d = self._info_dir()
        items = []
        for p in d.glob("*.json") if d.is_dir() else []:
            i = _read_json(p)
            if isinstance(i, dict):
                i["id"] = p.stem
                items.append(i)
        if rid:
            items = [i for i in items if str(i.get(self.INFO_FIELD) or "") == str(rid)]
        return sorted(items, key=lambda i: (i.get("created") or 0, i["id"]), reverse=True)  # the id: a stable order for ties

    def add_info(self, text: str, user: str = "", reagent: str = "", page: str = "", consumable: str = "") -> dict:
        """A note from the lab. One list for the reagents and the consumables (a note often is about both); it may
        name the reagent or the consumable whose page it was sent from."""
        text = _nfc(text).strip()[:MAX_INFO]
        if not text:
            raise ToolError("Write a few words first.")
        cats = {c.INFO_FIELD: c for c in self.catalogues()}
        rid, cat = (str(reagent), cats["reagent"]) if reagent else (str(consumable), cats.get("consumable")) if consumable else ("", None)
        if rid and cat is None:
            raise ToolError("There is no such consumable — it may have been deleted.")
        name = cat.get(rid, "pl")["_title"] if rid else ""
        now = time.time()
        iid = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + secrets.token_hex(2)
        # "created" is not rounded to whole seconds, so two notes sent in one second keep their order
        item = {"id": iid, "text": text, "user": _line(user, 60), "created": round(now, 6), "reagent": str(reagent or ""),
                "reagent_name": _line(name, 200) if reagent else "", "page": _line(page, 300), "status": "new"}
        if rid and not reagent:
            item.update(consumable=rid, consumable_name=_line(name, 200))
        with self.lock:
            self.ensure()
            _write_json(self._info_dir() / f"{iid}.json", item)
            about = f" about {cat.config()['key']} {rid} {_line(name, 50)}" if rid else ""
            self.commit(f"Info from the lab{about}: {_line(text, 60)}", user,
                        [f"Info: {iid}"] + ([f"{cat.TRAILER}: {rid}"] if rid else []) + ["Action: info"])
        return item

    def set_info(self, iid: str, status: str, user: str = "") -> dict:
        if status not in ("new", "done") or not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{2,8}", iid or ""):
            raise ToolError("Unknown status.")
        with self.lock:
            p = self._info_dir() / f"{iid}.json"
            i = _read_json(p)
            if not isinstance(i, dict):
                raise ToolError("That info is gone — someone may have deleted it.")
            i["status"] = status
            i["done_by"], i["done_at"] = (_line(user, 60), round(time.time())) if status == "done" else ("", None)
            _write_json(p, i)
            self.commit(f"Info {'dealt with' if status == 'done' else 'reopened'}: {_line(i.get('text'), 60)}", user, [f"Info: {iid}", "Action: info"])
        return i

    def update_info(self, iid: str, user: str = "", status: str | None = None, agent_note: str | None = None,
                    commit: bool = True) -> dict:
        """For the tidy-up (mister_plis/tidy.py): mark a note done and/or leave a remark on it (``agent_note``, as
        AGENTS.md asks of agents). With ``commit=False`` the caller, holding ``self.lock``, commits it together
        with the corrections."""
        if status not in (None, "new", "done") or not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{2,8}", iid or ""):
            raise ToolError("Unknown status.")
        with self.lock:
            p = self._info_dir() / f"{iid}.json"
            i = _read_json(p)
            if not isinstance(i, dict):
                raise ToolError("That info is gone — someone may have deleted it.")
            if status:
                i["status"] = status
                i["done_by"], i["done_at"] = (_line(user, 60), round(time.time())) if status == "done" else ("", None)
            if agent_note is not None:
                i["agent_note"] = _nfc(agent_note).strip()[:2000]
            _write_json(p, i)
            if commit:
                self.commit(f"Info {iid}: {_line(agent_note or status, 60)}", user, [f"Info: {iid}", "Action: info"])
        return i

    def discard_changes(self) -> None:
        """Undo files changed but not committed (a set of changes that failed half-way)."""
        with self.lock:
            if self.has_commits():
                self.git("checkout", "-q", "--", ".")
            self._book = None

    def delete_info(self, iid: str, user: str = "") -> None:
        with self.lock:
            p = self._info_dir() / f"{iid}.json"
            if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{2,8}", iid or "") or not p.is_file():
                raise ToolError("That info is gone — someone may have deleted it.")
            p.unlink()
            self.commit("Delete info from the lab", user, [f"Info: {iid}", "Action: info"])

    def info_markdown(self) -> str:
        books = " and ".join(f"`{c.config()['workbook']}` (key `{c.config()['key']}`)" for c in self.catalogues())
        lines = ["# Info from the lab about the reagents and consumables (not dealt with yet)", "",
                 f"The inventory is {books}; see AGENTS.md. A note can be about both. Mark an item dealt "
                 "with by setting its `status` to `done` in `info/<id>.json`.", ""]
        for i in reversed([i for i in self.infos() if i.get("status") != "done"]):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(i.get("created") or 0))
            about = (f" — about **{i['reagent_name']}** (label_no {i['reagent']})" if i.get("reagent")
                     else f" — about the consumable **{i.get('consumable_name') or ''}** (item_no {i['consumable']})" if i.get("consumable") else "")
            lines.append(f"- [{when}] {i.get('user') or 'someone'}{about} (info `{i['id']}`):")
            lines += ["  " + t for t in i.get("text", "").splitlines()]
        return "\n".join(lines) + "\n"

    # ---- GitHub ---------------------------------------------------------------------
    @property
    def remote_ref(self) -> str:
        return f"origin/{self.branch}"

    @property
    def folder(self) -> Path | None:
        """The repository's folder when it is on this machine (repo = a path), not on GitHub."""
        return gitutil.local_folder(self.url)

    def _where(self, github: str, folder: str) -> str:
        return folder if self.folder else github

    def _explain(self, out: str) -> str:
        if self.folder:
            why = gitutil.explain_local(out, self.folder)
            return why + "\n\n" + out if why else out
        low = out.lower()
        if any(s in low for s in ("authentication failed", "could not read username", "repository not found", "403",
                                  "terminal prompts disabled", "permission to", "denied")):
            return ("GitHub didn't let the server use the reagents repository. On github.com edit the MISTER PLIS token "
                    "(Settings → Developer settings → Fine-grained tokens) → Repository access → add the reagents "
                    "repository with Contents: Read and write.\n\n" + out)
        if "could not resolve host" in low or "unable to access" in low:
            return "The server couldn't reach GitHub. Check its internet connection.\n\n" + out
        return out

    def status(self) -> dict:
        if self.main is not self:
            return self.main.status()
        st = self.settings()
        b = None
        try:
            b = self.book()
        except Exception as e:  # a broken workbook must not break the page
            self.last_error = f"Couldn't read the workbook: {e}"
        d = {"repo": self.url, "folder": str(self.folder or ""), "branch": self.branch, "enabled": bool(self.url), **st, "last_error": self.last_error,
             "locked": bool(getattr(self, "locked", None)),
             "reagents": len(b.rows) if b else 0, "columns": len(b.header) if b else 0, "local": str(self.repo),
             "workbook": self.config()["workbook"], "has_workbook": b is not None,
             "ahead": 0, "behind": 0, "head": None, "open_info": sum(1 for i in self.infos() if i.get("status") != "done"),
             "others": []}
        for o in self.others:
            try:
                ob = o.book()
            except Exception as e:
                ob, self.last_error = None, f"Couldn't read the workbook: {e}"
                d["last_error"] = self.last_error
            d["others"].append({"kind": o.INFO_FIELD, "workbook": o.config()["workbook"], "has_workbook": ob is not None,
                                "rows": len(ob.rows) if ob else 0, "columns": len(ob.header) if ob else 0})
        if self.has_commits():
            code, out = self.git("log", "-1", "--format=%h%x1f%an%x1f%at%x1f%s")
            if code == 0 and out:
                h, a, at, s = out.split("\x1f", 3)
                d["head"] = {"short": h, "author": a, "at": int(at), "subject": s}
            if self.git("rev-parse", "--verify", "-q", self.remote_ref)[0] == 0:
                code, out = self.git("rev-list", "--left-right", "--count", f"HEAD...{self.remote_ref}")
                if code == 0 and len(out.split()) == 2:
                    d["ahead"], d["behind"] = (int(x) for x in out.split())
        return d

    def _merge_workbook(self, path: str) -> tuple[bool, str]:
        """During a merge conflict on the workbook: combine both sides cell by cell. Starts from GitHub's file (its
        layout, sheets and formatting) and applies the changes made here since the common version."""
        cfg = self.config()
        blobs = {}
        for stage, name in ((1, "base"), (2, "ours"), (3, "theirs")):
            code, data = self.git("show", f":{stage}:{path}", binary=True)
            blobs[name] = data if code == 0 else None
        if not blobs["ours"] or not blobs["theirs"]:
            return False, "The workbook was deleted on one side."
        try:
            ours = Book(blobs["ours"], cfg["sheet"], cfg["key"]).by_key()
            theirs_book = Book(blobs["theirs"], cfg["sheet"], cfg["key"])
            base = Book(blobs["base"], cfg["sheet"], cfg["key"]).by_key() if blobs["base"] else {}
        except Exception as e:
            return False, f"Couldn't read a version of the workbook: {e}"
        theirs = theirs_book.by_key()
        mine: dict[str, dict] = {}
        clashes = []
        for k, row in ours.items():
            b = base.get(k)
            t = theirs.get(k)
            if b is None and t is not None and t != row:
                clashes.append(f"{cfg['key']} {k}: added on both sides, differently")
                continue
            for c, v in row.items():
                if b is not None and b.get(c) == v:
                    continue
                if b is None and t is None:
                    mine.setdefault(k, {})[c] = v
                    continue
                tv = (t or {}).get(c)
                if tv == v:
                    continue
                if b is not None and tv != b.get(c):
                    clashes.append(f"{cfg['key']} {k}, {c}: here “{v}”, {self.main._where('on GitHub', 'in the folder')} “{tv}”")
                    continue
                if c not in theirs_book.header:
                    continue  # the column is gone on GitHub
                mine.setdefault(k, {})[c] = v
        if clashes:
            return False, "\n".join(clashes[:30])
        (self.repo / path).write_bytes(blobs["theirs"])
        self._book = None
        if mine:
            wb, ws, header = self._open()
            ki = header.index(cfg["key"]) + 1
            for k, cells in mine.items():
                row = self._find_row(ws, header, k)
                if row is None:
                    row = self._last_row(ws, header) + 1
                    ws.cell(row=row, column=ki).value = int(k) if k.isdigit() else k
                for c, v in cells.items():
                    if c in header:
                        self._set(ws, row, header.index(c) + 1, v, c)
            self._save(wb, ws, header)
        else:
            wb, ws, header = self._open()
            self._write_csv(ws, header, self._last_row(ws, header))
        return True, f"{sum(len(c) for c in mine.values())} cell(s) changed here kept"

    def sync(self, user: str = "") -> dict:
        """Bring in GitHub's changes (merged, cell by cell for the workbook), then send ours back if allowed."""
        if self.main is not self:
            return self.main.sync(user)
        steps: list[dict] = []

        def step(name: str, code: int, out: str) -> bool:
            steps.append({"name": name, "ok": code == 0, "output": self._explain(out) if code else out})
            return code == 0

        if not self.url:
            return {"ok": False, "steps": [{"name": "No repository is set: choose one on Settings → Reagents & consumables", "ok": False, "output": ""}]}
        with self.lock:
            self.ensure()
            code, cur = self.git("remote", "get-url", "origin")
            if code != 0:
                self.git("remote", "add", "origin", self.url)
            elif cur.strip() != self.url:
                self.git("remote", "set-url", "origin", self.url)
            remote = step("git fetch", *self.git("fetch", "--prune", "origin", f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}",
                                                  timeout=600, network=True))
            if not remote:
                low = steps[-1]["output"].lower()
                if "couldn't find remote ref" in low or "could not find remote ref" in low:
                    steps[-1].update(ok=True, output=f"The repository has no branch “{self.branch}” yet.")
                else:
                    self.last_error = steps[-1]["output"]
                    return {"ok": False, "steps": steps}
            if remote:
                if not self.has_commits():
                    if not step("take the repository's version", *self.git("checkout", "-q", "-B", self.branch, self.remote_ref)):
                        return {"ok": False, "steps": steps}
                    self.git("branch", "-q", f"--set-upstream-to={self.remote_ref}")
                else:
                    who = _line(user, 60) or "MISTER PLIS"
                    args = ["-c", f"user.name={who}", "-c", f"user.email={EMAIL}", "merge", "--no-edit", "-m", self._where("Merge changes from GitHub", "Merge changes from the folder")]
                    if self.git("merge-base", "HEAD", self.remote_ref)[0] != 0:
                        args.append("--allow-unrelated-histories")
                    code, out = self.git(*args, self.remote_ref)
                    if code != 0:
                        ok, msg = self._resolve(who)
                        if not ok:
                            self.git("merge", "--abort")
                            for c in self.catalogues():
                                c._book = None
                            text = self._where("The same cells were changed here and on GitHub, differently. Nothing was changed here. "
                                               "Fix them on GitHub (or here), then sync again:",
                                               "The same cells were changed here and in the folder, differently. Nothing was changed here. "
                                               "Fix them in the folder (or here), then sync again:") + "\n" + msg
                            steps.append({"name": self._where("merge GitHub's changes", "merge the folder's changes"), "ok": False, "output": text})
                            self.last_error = text
                            return {"ok": False, "steps": steps}
                        steps.append({"name": self._where("merge GitHub's changes, cell by cell", "merge the folder's changes, cell by cell"), "ok": True, "output": msg})
                    else:
                        steps.append({"name": self._where("merge GitHub's changes", "merge the folder's changes"), "ok": True, "output": out})
            for c in self.catalogues():
                c._book = None
            if self.settings()["push"] and self.has_commits():
                ahead = self.git("rev-list", "--count", f"{self.remote_ref}..HEAD")[1] if remote else "1"
                if ahead.strip() not in ("", "0"):
                    into = gitutil.LOCAL_PUSH if self.folder else ()
                    if not step(self._where("send the lab's changes to GitHub", "send the lab's changes to the folder"),
                                *self.git("push", *into, "origin", f"HEAD:refs/heads/{self.branch}", timeout=600, network=True)):
                        self.last_error = steps[-1]["output"]
                        return {"ok": False, "steps": steps, "status": self.status()}
                    self.git("fetch", "origin", f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}", network=True)
                    self.save_settings(pushed_at=time.time())
            elif self.has_commits() and remote and self.git("rev-list", "--count", f"{self.remote_ref}..HEAD")[1].strip() not in ("", "0"):
                steps.append({"name": self._where("the lab's changes stay on this server (sending to GitHub is off)",
                                               "the lab's changes stay on this server (sending to the folder is off)"), "ok": True, "output": ""})
            self.last_error = ""
            self.save_settings(synced_at=time.time())
            b = self.book()
            steps.append({"name": f"{len(b.rows) if b else 0} reagents ready", "ok": True, "output": ""})
            for o in self.others:
                ob = o.book()
                if ob is not None:
                    steps.append({"name": f"{len(ob.rows)} consumables ready", "ok": True, "output": ""})
        return {"ok": True, "steps": steps, "status": self.status()}

    def _resolve(self, who: str) -> tuple[bool, str]:
        """A merge stopped on conflicts: the workbook is merged cell by cell and its CSV rewritten; anything else
        in conflict stops the sync."""
        _, out = self.git("diff", "--name-only", "--diff-filter=U")
        files = [f for f in out.splitlines() if f]
        cats = self.catalogues()
        mine = {f for c in cats for f in (c.config()["workbook"], c.config()["csv"])}
        others = [f for f in files if f not in mine]
        if others:
            return False, "\n".join(others)
        notes = []
        for c in cats:
            cfg = c.config()
            if cfg["workbook"] in files:
                ok, msg = c._merge_workbook(cfg["workbook"])
                if not ok:
                    return False, msg
                notes.append(msg)
            elif cfg["csv"] in files:
                wb, ws, header = c._open()
                c._write_csv(ws, header, c._last_row(ws, header))
        self.git("add", "--", *files)
        code, out = self.git("-c", f"user.name={who}", "-c", f"user.email={EMAIL}", "commit", "-q", "--no-edit")
        if code != 0:
            return False, out
        return True, "; ".join(notes)

    def auto_sync_loop(self) -> None:  # pragma: no cover - a background thread
        last = 0.0
        while True:
            time.sleep(60)
            m = self.settings()["auto_minutes"]
            if self.url and m and time.time() - last >= m * 60:
                last = time.time()
                try:
                    self.sync("MISTER PLIS")
                except Exception as e:
                    self.last_error = str(e)


# ---- consumables: a second workbook in the same repository ------------------------------------------------

CONSUMABLES_CONFIG = {
    "workbook": "consumables.xlsx", "sheet": "consumables", "csv": "consumables.csv",
    "key": "item_no", "title": {"pl": "name_pl", "en": "name_en"},
    "quick": ["_to_order", "category", "_producers"],
    "list": ["item_no", "_title", "category", "size_spec", "storage_place", "_producers"],
    "hidden": [],
    "pdf": {"source": "list", "columns": ["item_no", "_title", "size_spec", "storage_place", "_producers"], "filters": True, "size": "normal"},
}
CONSUMABLE_SLOTS = 3
# column, type, allowed values, label_pl, label_en, group, description_pl — the `columns` sheet of a new workbook
_SLOT_COLS = [
    ("name", "text", "Marka", "Brand", "Producent / marka, np. Whatman, Millipore, Eppendorf."),
    ("supplier", "text", "Dostawca", "Supplier", "U kogo kupujemy, np. Merck, VWR, Bionovo (jeśli inny niż marka)."),
    ("catalog_no", "text", "Nr katalogowy", "Product code", "Numer katalogowy / kod produktu u dostawcy."),
    ("product_url", "text", "Strona produktu", "Product page", "Link do produktu na stronie dostawcy."),
    ("container_size", "number", "Wielkość opakowania", "Pack size", "Ile sztuk (arkuszy, metrów…) w jednym opakowaniu."),
    ("container_unit", "text", "Jednostka", "Unit", "np. szt., arkuszy, m, rolka."),
    ("containers_count", "integer", "Opakowań w lab.", "Packs in the lab", "Ile opakowań tej marki jest teraz w laboratorium."),
    ("price", "text", "Cena", "Price", "Cena za opakowanie, z walutą, np. 420 zł."),
    ("notes", "text", "Opinia", "Opinion", "Jak się sprawdza — np. „rwie się przy transferze”, „pasuje do pipet Gilson”."),
    ("avoid", "boolean", "Nie kupować więcej", "Don't buy again", "TAK = ta marka się nie sprawdziła; następnym razem kupić inną."),
    ("to_order", "boolean", "Do zamówienia", "To order", "Trzeba zamówić."),
    ("order_amount", "text", "Ile zamówić", "How much to order", "np. 2 opakowania."),
    ("ordered", "boolean", "Zamówione", "Ordered", "Zamówione, czeka na dostawę."),
]
CONSUMABLE_COLUMNS = (
    [("item_no", "integer", "", "Nr", "No.", "identification", "Numer pozycji w spisie, nadawany automatycznie. Nie zmieniać."),
     ("name_pl", "text", "", "Nazwa", "Name (Polish)", "identification", "Nazwa po polsku, np. końcówki do pipet 200 µl."),
     ("name_en", "text", "", "Nazwa angielska", "Name", "identification", "Nazwa po angielsku, np. pipette tips 200 µl."),
     ("category", "text", "", "Rodzaj", "Kind", "identification", "np. końcówki do pipet, membrany, bibuła, szkiełka, fiolki HPLC, probówki."),
     ("size_spec", "text", "", "Rozmiar / parametry", "Size / specification", "identification", "np. 200 µl, 0,45 µm, 18 × 18 mm, 2 ml, 8 × 6 cm."),
     ("used_for", "text", "", "Do czego", "Used for", "identification", "np. western blot, HPLC, mikroskopia."),
     ("is_disposed", "boolean", "", "Już nie używamy", "No longer used", "status", "TAK = już tego nie używamy; zostaje w spisie, znika z listy."),
     ("disposed_date", "date", "", "Nie używamy od", "No longer used since", "status", "Data (rrrr-mm-dd)."),
     ("storage_place", "text", "", "Gdzie leży", "Where it is", "storage", "Pomieszczenie, szafka, szuflada."),
     ("stock_min", "text", "", "Zamówić, gdy zostanie", "Reorder when down to", "storage", "np. 1 opakowanie."),
     ("stock_checked_date", "date", "", "Stan sprawdzony", "Stock checked on", "storage", "Kiedy ostatnio policzono opakowania (rrrr-mm-dd).")]
    + [(f"producer_{i}_{k}", t, "", f"{pl} {i}", f"{en} {i}", "producers", d) for i in range(1, CONSUMABLE_SLOTS + 1) for k, t, pl, en, d in _SLOT_COLS]
    + [("order_note", "text", "", "Uwaga do zamówienia", "Order note", "ordering", "Dla osoby zamawiającej."),
       ("order_requested_by", "text", "", "Kto zgłosił", "Requested by", "ordering", "Wpisywane samo przy oznaczeniu „do zamówienia”."),
       ("order_requested_date", "date", "", "Kiedy zgłoszono", "Requested on", "ordering", "Data (rrrr-mm-dd)."),
       ("general_notes", "text", "", "Uwagi", "Notes", "notes", "Wszystko inne.")]
)


# The columns of a new, empty reagents workbook (Start an empty inventory): what the pages use — names, storage,
# hazards (GHS pictograms), producers with what to order, the calculator's molar mass and purity.
_REAGENT_SLOT_COLS = [c for c in _SLOT_COLS if c[0] != "avoid"]
_GHS = [("ghs01_explosive", "GHS01 wybuchowe", "GHS01 explosive"), ("ghs02_flammable", "GHS02 łatwopalne", "GHS02 flammable"),
        ("ghs03_oxidizing", "GHS03 utleniające", "GHS03 oxidising"), ("ghs04_compressed_gas", "GHS04 gazy pod ciśnieniem", "GHS04 gas under pressure"),
        ("ghs05_corrosive", "GHS05 żrące", "GHS05 corrosive"), ("ghs06_toxic", "GHS06 toksyczne", "GHS06 toxic"),
        ("ghs07_harmful_irritant", "GHS07 drażniące", "GHS07 harmful / irritant"), ("ghs08_health_hazard", "GHS08 zagrożenie dla zdrowia", "GHS08 health hazard"),
        ("ghs09_environment", "GHS09 środowisko", "GHS09 environment")]
REAGENT_COLUMNS = (
    [("label_no", "integer", "", "Nr etykiety", "Label no.", "identification", "Numer na etykiecie, nadawany automatycznie. Nie zmieniać."),
     ("name_pl", "text", "", "Nazwa", "Name (Polish)", "identification", "Nazwa po polsku."),
     ("name_en", "text", "", "Nazwa angielska", "Name", "identification", "Nazwa po angielsku."),
     ("cas_no", "text", "", "Nr CAS", "CAS number", "identification", "np. 67-64-1."),
     ("molar_mass_g_mol", "number", "", "Masa molowa (g/mol)", "Molar mass (g/mol)", "identification", "Dla kalkulatora roztworów."),
     ("purity_percent", "number", "", "Czystość (%)", "Purity (%)", "identification", "np. 99,5."),
     ("is_disposed", "boolean", "", "Zużyty", "Used up", "status", "TAK = już go nie ma; zostaje w spisie, znika z listy."),
     ("disposed_date", "date", "", "Data zużycia", "Used up on", "status", "Data (rrrr-mm-dd)."),
     ("storage_category_primary", "text", "", "Kategoria przechowywania", "Storage category", "storage", "np. szafa na ciecze łatwopalne."),
     ("storage_exact_location", "text", "", "Lokalizacja", "Exact location", "storage", "Pomieszczenie, szafa, półka."),
     ("is_borrowed", "boolean", "", "Pożyczony", "Borrowed", "borrowing", "TAK = pożyczony od innego laboratorium."),
     ("borrowed_from", "text", "", "Od kogo", "Borrowed from", "borrowing", "Laboratorium lub osoba.")]
    + [(key, "boolean", "", pl, en, "hazards", "TAK = ten piktogram jest na opakowaniu.") for key, pl, en in _GHS]
    + [(f"producer_{i}_{k}", t, "", f"{pl} {i}", f"{en} {i}", "producers", d) for i in range(1, 4) for k, t, pl, en, d in _REAGENT_SLOT_COLS]
    + [("order_note", "text", "", "Uwaga do zamówienia", "Order note", "ordering", "Dla osoby zamawiającej."),
       ("order_requested_by", "text", "", "Kto zgłosił", "Requested by", "ordering", "Wpisywane samo przy oznaczeniu „do zamówienia”."),
       ("order_requested_date", "date", "", "Kiedy zgłoszono", "Requested on", "ordering", "Data (rrrr-mm-dd)."),
       ("general_notes", "text", "", "Uwagi", "Notes", "notes", "Wszystko inne.")]
)


def new_reagents_workbook() -> bytes:
    """An empty reagents workbook: the `reagents` sheet (header only, an Excel table) and its `columns` sheet."""
    return _new_workbook(DEFAULT_CONFIG["sheet"], "reagents", REAGENT_COLUMNS)


def new_consumables_workbook() -> bytes:
    """An empty consumables workbook: the `consumables` sheet (header only, an Excel table) and its `columns` sheet."""
    return _new_workbook(CONSUMABLES_CONFIG["sheet"], "consumables", CONSUMABLE_COLUMNS)


def _new_workbook(sheet: str, table: str, columns: list) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    header = [c[0] for c in columns]
    ws.append(header)
    end = ws.cell(row=1, column=len(header)).column_letter
    t = Table(displayName=table, ref=f"A1:{end}2")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)
    ws.freeze_panes = "C2"
    for i, h in enumerate(header, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(10, min(40, len(h) + 4))
    cs = wb.create_sheet("columns")
    cs.append(["column", "type", "values", "label_pl", "label_en", "group", "description_pl"])
    for c in columns:
        cs.append(list(c))
    for cell in cs[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0B7D71")
    for col, w in zip("ABCDEFG", (28, 10, 14, 24, 24, 16, 70)):
        cs.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class Consumables(Inventory):
    """Lab consumables (pipette tips, membranes, blotting paper, coverslips, HPLC vials…): catalogued like the
    reagents — brands with product codes and links, packs in the lab, what to order, which brand not to buy
    again — but no hazards. Its workbook lives in the reagents' repository, so the GitHub sync, the history and
    the info from the lab are shared. A new repository gets an empty workbook to start from."""

    CONFIG_FILE = "mister_plis_consumables.json"
    DEFAULT_CONFIG = CONSUMABLES_CONFIG
    TRAILER = "Consumable"
    INFO_FIELD = "consumable"
    PRODUCERS = ("Brands", "Marki")
    MISSING = "There is no such consumable — it may have been deleted."
    CHANGED = "Someone changed this consumable while you were editing it. Open it again to see their change, then edit it."
    NEEDS_NAME = "A consumable needs a name."
    SHOWN = "Change how the consumables are shown"

    def __init__(self, main: Inventory):
        super().__init__(main.root.parent, main.url, main.branch, root=main.root)
        self.main, self.lock, self.env = main, main.lock, main.env
        main.others.append(self)

    def book(self) -> Book | None:
        if not self.xlsx.exists():
            self.start_workbook()
        return super().book()

    def start_workbook(self, user: str = "") -> bool:
        """Once the repository is here (synced, or started on this server), add an empty workbook if it has none."""
        if not self.main.has_commits() or (self.repo / ".git" / "MERGE_HEAD").exists():
            return False
        with self.lock:
            if self.xlsx.exists():
                return False
            tmp = self.xlsx.with_name("." + self.xlsx.name + ".tmp")
            tmp.write_bytes(new_consumables_workbook())
            tmp.replace(self.xlsx)
            wb, ws, header = self._open()
            self._write_csv(ws, header, 1)
            self.commit("Start the consumables inventory", "MISTER PLIS", ["Action: add"])
        return True

    def auto_sync_loop(self) -> None:  # pragma: no cover - the reagents' loop syncs the repository
        return None
